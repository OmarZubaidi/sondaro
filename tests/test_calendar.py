"""Calendar feeds, and what a browser calls them when you download one.

A subscribing client ignores Content-Disposition entirely — this only matters
for the download, where "4.ics" tells you nothing about which trip it was.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.config import config  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "worker_enabled", False)

    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


def make_trip(client, name: str):
    response = client.post(
        "/api/trips",
        json={
            "name": name,
            "countries": ["FR"],
            "start_date": "2026-09-20",
            "end_date": "2026-09-30",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_the_local_feed_lives_at_sondaro_ics(client):
    response = client.get("/sondaro.ics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert 'filename="Sondaro.ics"' in response.headers["content-disposition"]


def test_the_old_calendar_ics_path_is_gone(client):
    """It falls through to the SPA or a 404, but it is never a calendar."""
    response = client.get("/calendar.ics")
    assert not response.headers.get("content-type", "").startswith("text/calendar")


def test_a_trip_downloads_under_its_own_name(client):
    trip = make_trip(client, "Family trip")

    response = client.get(f"/trips/{trip['id']}.ics")

    assert response.status_code == 200
    assert 'filename="Family trip.ics"' in response.headers["content-disposition"]


def test_an_awkward_trip_name_still_produces_a_usable_filename(client):
    """Slashes and accents can't go in the plain filename, so it gets a
    sanitised fallback and the real name in the RFC 6266 form."""
    trip = make_trip(client, "Köln / Paris")

    disposition = client.get(f"/trips/{trip['id']}.ics").headers["content-disposition"]

    assert 'filename="Kln  Paris.ics"' in disposition
    assert "filename*=UTF-8''K%C3%B6ln%20%2F%20Paris.ics" in disposition
