"""Marking a ticket as bought.

Once you hold a ticket the score has done its job — it was advice about whether
to go, and you've decided. So the mark has to outrank every filter, and it has
to survive the event cache being swept out from under it.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db, library, routing, scan, settings  # noqa: E402
from api.config import config  # noqa: E402
from api.match import artist_key  # noqa: E402
from api.providers.base import Event  # noqa: E402
from api.util import now_iso  # noqa: E402

HOME = (38.0, -95.0)
MILLBROOK = (35.5, -100.5)
SOON = date.today() + timedelta(days=21)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "worker_enabled", False)
    settings.set_value("home_lat", HOME[0])
    settings.set_value("home_lon", HOME[1])

    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


def a_distant_show(name: str = "Barely Played") -> str:
    """Six hours away and barely listened to — nowhere near any threshold."""
    db.execute(
        "INSERT INTO artists(key, name, affinity, listens, updated_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(key) DO NOTHING",
        (artist_key(None, name), name, 0.5, 0, now_iso()),
    )
    routing.store(
        routing.point_key(*HOME),
        routing.point_key(*MILLBROOK),
        routing.Route(drive_hours=6.0, km=580, estimated=False),
    )
    scan.ingest(
        [
            Event(
                provider="ticketmaster",
                provider_event_id="atl1",
                artist_name=name,
                date=SOON.isoformat(),
                time="20:00",
                venue="The Tabernacle",
                city="Millbrook",
                country="US",
                lat=MILLBROOK[0],
                lon=MILLBROOK[1],
            )
        ],
        library.all_artists(),
    )
    return "ticketmaster:atl1"


def test_marking_and_unmarking(client):
    event_id = a_distant_show()

    marked = client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})
    assert marked.status_code == 200
    assert marked.json()["purchased"] is True
    assert scan.is_purchased(event_id)

    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": False})
    assert not scan.is_purchased(event_id)


def test_the_local_feed_reports_it(client):
    event_id = a_distant_show()
    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})

    shows = [
        show
        for month in client.get("/api/local?min_score=0").json()["months"]
        for show in month["shows"]
    ]
    assert [s["purchased"] for s in shows if s["id"] == event_id] == [True]


def test_a_ticket_you_hold_outranks_the_filter(client):
    """The point of the whole feature. A 6h drive for an artist you barely play
    scores near zero, and hiding a show you're going to would be absurd."""
    event_id = a_distant_show()

    hidden = client.get("/api/local?min_score=0.9").json()
    assert event_id not in [s["id"] for m in hidden["months"] for s in m["shows"]]

    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})

    shown = client.get("/api/local?min_score=0.9").json()
    assert event_id in [s["id"] for m in shown["months"] for s in m["shows"]]


def a_nearby_show(name: str = "Favorite") -> str:
    """Half an hour away, played constantly — clears any floor on its own."""
    db.execute(
        "INSERT INTO artists(key, name, affinity, listens, updated_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(key) DO NOTHING",
        (artist_key(None, name), name, 1.0, 900, now_iso()),
    )
    springfield = (38.2, -95.2)
    routing.store(
        routing.point_key(*HOME),
        routing.point_key(*springfield),
        routing.Route(drive_hours=0.5, km=40, estimated=False),
    )
    scan.ingest(
        [
            Event(
                provider="ticketmaster",
                provider_event_id="dur1",
                artist_name=name,
                date=SOON.isoformat(),
                time="20:00",
                venue="Motorco",
                city="Springfield",
                country="US",
                lat=springfield[0],
                lon=springfield[1],
            )
        ],
        library.all_artists(),
    )
    return "ticketmaster:dur1"


def test_marking_a_ticket_is_what_puts_it_in_the_calendar(client):
    """Buying the ticket is the moment a show stops being a suggestion, so it's
    the moment it earns a place in your week."""
    event_id = a_nearby_show()
    assert "Favorite" not in client.get("/sondaro.ics").text

    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})

    held = client.get("/sondaro.ics").text
    assert "Favorite" in held
    assert "STATUS:CONFIRMED" in held
    assert "TRANSP:OPAQUE" in held


def test_a_bought_ticket_reaches_the_calendar_even_when_the_score_would_not(client):
    """The stored floor keeps the feed short. It must not keep out a show you
    are actually going to."""
    event_id = a_distant_show()
    assert "Barely Played" not in client.get("/sondaro.ics").text

    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})

    assert "Barely Played" in client.get("/sondaro.ics").text


def test_it_survives_the_listing_being_swept_away(client):
    """`events` is a provider cache that ingest rewrites. A decision you made
    is not cache, so it must not be collateral."""
    event_id = a_distant_show()
    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})

    db.execute("DELETE FROM events")

    assert scan.is_purchased(event_id)


def test_marking_something_we_have_never_seen_is_allowed(client):
    """Same reason: the listing may have aged out before you got round to it."""
    response = client.put("/api/shows/ticketmaster:gone/purchased", json={"purchased": True})

    assert response.status_code == 200
    assert scan.is_purchased("ticketmaster:gone")
