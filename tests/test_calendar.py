"""The calendar subscription.

One URL, added once, holding only what you've said you're going to. A calendar
full of suggestions is one you stop trusting, and a downloaded snapshot is a
calendar that was right the day you saved it.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db, library, routing, scan  # noqa: E402
from api.config import config  # noqa: E402
from api.match import artist_key  # noqa: E402
from api.providers.base import Event  # noqa: E402
from api.util import now_iso  # noqa: E402

SOON = date.today() + timedelta(days=30)
TORONTO = (43.6532, -79.3832)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "worker_enabled", False)

    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


def a_show(
    name: str = "Sabaton",
    *,
    event_id: str = "tm-1",
    day: date = SOON,
    starts_at: str | None = None,
    end_date: str | None = None,
    end_time: str | None = None,
    ends_at: str | None = None,
    tracks: int = 212,
) -> str:
    db.execute(
        "INSERT INTO artists(key, name, affinity, listens, tracks, updated_at) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET tracks = excluded.tracks",
        (artist_key(None, name), name, 1.0, 500, tracks, now_iso()),
    )
    scan.ingest(
        [
            Event(
                provider="ticketmaster",
                provider_event_id=event_id,
                artist_name=name,
                date=day.isoformat(),
                time="19:30",
                starts_at=starts_at,
                end_date=end_date,
                end_time=end_time,
                ends_at=ends_at,
                venue="History",
                city="Toronto",
                country="CA",
                lat=TORONTO[0],
                lon=TORONTO[1],
            )
        ],
        library.all_artists(),
    )
    return f"ticketmaster:{event_id}"


def feed(client) -> str:
    response = client.get("/sondaro.ics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    return response.text


def test_only_shows_you_are_going_to_appear(client):
    """The change in what this feed means: a suggestion is not a commitment."""
    event_id = a_show()

    assert "Sabaton" not in feed(client)

    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})

    assert "Sabaton" in feed(client)


def test_unmarking_takes_it_back_out(client):
    """A subscription that only ever grows is a subscription you clean by hand."""
    event_id = a_show()
    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})
    assert "Sabaton" in feed(client)

    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": False})

    assert "Sabaton" not in feed(client)


def test_the_feed_is_subscribable_rather_than_a_download(client):
    """An attachment is a snapshot. It was right the day you saved it and has
    been drifting ever since, which is the whole bug being fixed."""
    response = client.get("/sondaro.ics")

    assert "content-disposition" not in response.headers
    assert "no-cache" in response.headers["cache-control"]
    assert "REFRESH-INTERVAL;VALUE=DURATION:PT1H" in response.text


def test_the_calendar_is_just_called_sondaro(client):
    assert "X-WR-CALNAME:Sondaro\r\n" in feed(client)


def test_a_bought_ticket_blocks_your_time(client):
    """Everything here is a commitment, so nothing is tentative or see-through."""
    client.put(f"/api/shows/{a_show()}/purchased", json={"purchased": True})

    text = feed(client)
    assert "STATUS:CONFIRMED" in text and "TRANSP:OPAQUE" in text
    assert "TENTATIVE" not in text and "TRANSPARENT" not in text


def test_an_out_of_town_show_is_pinned_to_a_real_moment(client):
    """Floating time renders in the reader's zone, so a Toronto show read from
    home lands hours out. The provider's instant is the fix."""
    event_id = a_show(starts_at="2026-09-28T23:30:00Z", day=date(2026, 9, 28))
    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})

    text = feed(client)
    assert "DTSTART:20260928T233000Z" in text
    assert "DTEND:20260929T023000Z" in text


def test_a_show_with_doors_still_tba_stays_floating(client):
    """Inventing a timezone is worse than admitting we only know the evening."""
    client.put(f"/api/shows/{a_show()}/purchased", json={"purchased": True})

    assert f"DTSTART:{SOON.strftime('%Y%m%d')}T193000\r\n" in feed(client)


def test_a_published_end_is_used_instead_of_the_assumed_one(client):
    """Three hours is what we assume when nobody said. When somebody did say,
    assuming anything is just being wrong on purpose."""
    event_id = a_show(end_time="23:30")
    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})

    text = feed(client)
    assert f"DTSTART:{SOON.strftime('%Y%m%d')}T193000\r\n" in text
    assert f"DTEND:{SOON.strftime('%Y%m%d')}T233000\r\n" in text


def test_a_festival_blocks_out_every_day_it_runs(client):
    """A three-day run that reads as one evening is a calendar that will let
    you book a flight home on day two."""
    last_day = SOON + timedelta(days=2)
    event_id = a_show(end_date=last_day.isoformat(), end_time="22:00")
    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})

    assert f"DTEND:{last_day.strftime('%Y%m%d')}T220000\r\n" in feed(client)


def test_a_curfew_past_midnight_lands_the_next_morning(client):
    """01:00 against doors at 19:30 is tomorrow, and read literally it would be
    an event that ends eighteen hours before it starts."""
    event_id = a_show(end_time="01:00")
    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})

    tomorrow = SOON + timedelta(days=1)
    assert f"DTEND:{tomorrow.strftime('%Y%m%d')}T010000\r\n" in feed(client)


def test_a_published_absolute_end_pins_the_finish_to_a_real_moment(client):
    """Same argument as the start: the reader's timezone is not the venue's."""
    event_id = a_show(
        starts_at="2026-09-28T23:30:00Z",
        ends_at="2026-09-29T02:00:00Z",
        end_time="22:00",
        day=date(2026, 9, 28),
    )
    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})

    assert "DTEND:20260929T020000Z" in feed(client)


def test_the_description_is_the_drive_and_the_library(client):
    """It used to carry the score, every reason and every flag, which is
    reference material for a decision you have already made."""
    routing.store(
        routing.point_key(*_home()),
        routing.point_key(*TORONTO),
        routing.Route(drive_hours=9.5, miles=620.0, estimated=False),
    )
    client.put(f"/api/shows/{a_show(tracks=212)}/purchased", json={"purchased": True})

    line = next(l for l in feed(client).splitlines() if l.startswith("DESCRIPTION:"))

    assert line == "DESCRIPTION:9h 30m drive · 212 songs in Lidarr"


def test_a_single_track_is_not_pluralised(client):
    client.put(f"/api/shows/{a_show(tracks=1)}/purchased", json={"purchased": True})

    assert "1 song in Lidarr" in feed(client)


def test_yesterdays_gig_is_not_still_in_your_calendar(client):
    """Past shows are pruned from the cache, and the feed follows."""
    event_id = a_show(day=date.today() - timedelta(days=1), event_id="tm-old")
    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})

    assert "Sabaton" not in feed(client)


def test_a_show_appears_once_even_when_two_trips_want_it(client):
    """It used to be assembled from every trip's candidate list, so overlapping
    trips could emit the same event twice."""
    event_id = a_show()
    client.put(f"/api/shows/{event_id}/purchased", json={"purchased": True})
    for name in ("Canada", "Canada again"):
        client.post(
            "/api/trips",
            json={
                "name": name,
                "legs": [{"country": "CA"}],
                "start_date": SOON.isoformat(),
                "end_date": (SOON + timedelta(days=5)).isoformat(),
            },
        )

    assert feed(client).count("SUMMARY:Sabaton") == 1


def test_the_per_trip_feed_is_gone(client):
    """One trip, one URL to add and later remove, was the thing being fixed."""
    response = client.get("/trips/1.ics")

    assert not response.headers.get("content-type", "").startswith("text/calendar")


def _home() -> tuple[float, float]:
    from api import settings

    return settings.home()
