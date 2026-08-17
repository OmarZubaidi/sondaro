"""The calendar feed.

One URL, subscribed to once. A subscription you have to maintain is a
subscription that goes stale, so adding a trip has to make its shows appear in
the feed you already have rather than minting a new one to remember.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db, library, scan  # noqa: E402
from api.config import config  # noqa: E402
from api.match import artist_key  # noqa: E402
from api.providers.base import Event  # noqa: E402
from api.util import now_iso  # noqa: E402

TRIP_START = date.today() + timedelta(days=30)
TRIP_END = TRIP_START + timedelta(days=10)
LYON = (45.7640, 4.8357)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "worker_enabled", False)

    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


def a_show_in_lyon(name: str = "Palehound", affinity: float = 1.0) -> None:
    """An artist in the library, playing France during the trip window."""
    db.execute(
        "INSERT INTO artists(key, name, affinity, listens, updated_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(key) DO NOTHING",
        (artist_key(None, name), name, affinity, 500, now_iso()),
    )
    scan.ingest(
        [
            Event(
                provider="ticketmaster",
                provider_event_id=f"lyon-{name}",
                artist_name=name,
                date=(TRIP_START + timedelta(days=2)).isoformat(),
                time="20:00",
                venue="Le Transbordeur",
                city="Lyon",
                country="FR",
                lat=LYON[0],
                lon=LYON[1],
            )
        ],
        library.all_artists(),
    )


def make_trip(client, name: str):
    response = client.post(
        "/api/trips",
        json={
            "name": name,
            "legs": [{"country": "FR"}],
            "start_date": TRIP_START.isoformat(),
            "end_date": TRIP_END.isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_the_feed_lives_at_sondaro_ics(client):
    response = client.get("/sondaro.ics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert 'filename="Sondaro.ics"' in response.headers["content-disposition"]


def test_adding_a_trip_fills_the_subscription_you_already_have(client):
    """The whole point of one feed: no new URL to add, nothing to remember."""
    a_show_in_lyon()
    assert "Palehound" not in client.get("/sondaro.ics").text

    make_trip(client, "France")

    assert "Palehound" in client.get("/sondaro.ics").text


def test_a_show_in_two_trips_appears_once(client):
    """Overlapping trips are one itinerary from the calendar's point of view."""
    a_show_in_lyon()
    make_trip(client, "France")
    make_trip(client, "France again")

    assert client.get("/sondaro.ics").text.count("SUMMARY:Palehound") == 1


def test_min_score_still_narrows_the_subscription(client):
    """Subscribe to only what's worth your attention, without changing what the
    app itself shows."""
    a_show_in_lyon("Palehound", affinity=1.0)
    a_show_in_lyon("Barely Played", affinity=0.5)
    make_trip(client, "France")

    everything = client.get("/sondaro.ics").text
    assert "Palehound" in everything and "Barely Played" in everything

    narrowed = client.get("/sondaro.ics?min_score=0.9").text
    assert "Palehound" in narrowed
    assert "Barely Played" not in narrowed


def test_the_per_trip_feed_is_gone(client):
    """One trip, one URL to add and later remove, was the thing being fixed."""
    trip = make_trip(client, "France")

    response = client.get(f"/trips/{trip['id']}.ics")

    assert not response.headers.get("content-type", "").startswith("text/calendar")
