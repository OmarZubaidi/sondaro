"""Editing a trip.

Plans change: things get booked and narrowed, legs get dropped. The tricky
part isn't the update itself, it's knowing when an edit changes *what gets
searched* — re-planning spends API calls, so a rename must not trigger one,
while removing a country must not leave its sweeps queued.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db, queue, settings  # noqa: E402
from api.config import config  # noqa: E402
from api.util import today  # noqa: E402

START = today() + timedelta(days=30)
END = START + timedelta(days=10)
LATER_START = START + timedelta(days=11)
LATER_END = LATER_START + timedelta(days=9)
BEFORE_START = START - timedelta(days=19)


@pytest.fixture
def client(monkeypatch):
    """No worker: these tests are about planning, not draining."""
    monkeypatch.setattr(config, "worker_enabled", False)
    monkeypatch.setattr(config, "ticketmaster_api_key", "key")
    settings.set_value("home_country", "US")

    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


def legs(*pairs):
    """(country, city or None) -> the leg payload the API takes."""
    return [{"country": c, "city": city} for c, city in pairs]


def make_trip(client, **overrides):
    payload = {
        "name": "Europe",
        "legs": legs(("FR", None), ("ES", None)),
        "start_date": START.isoformat(),
        "end_date": END.isoformat(),
        "flex_before": 2,
        "flex_after": 2,
    }
    payload.update(overrides)
    response = client.post("/api/trips", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def task_countries() -> set[str]:
    """Which countries currently have sweeps queued."""
    return {
        row["task_key"].split(":")[2]
        for row in db.query("SELECT task_key FROM fetch_tasks WHERE task_key LIKE 'trip:%'")
    }


def test_renaming_does_not_spend_api_calls(client):
    trip = make_trip(client)
    before = db.scalar("SELECT COUNT(*) FROM fetch_tasks WHERE task_key LIKE 'trip:%'")

    response = client.patch(f"/api/trips/{trip['id']}", json={"name": "Renamed"})

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["rescanned"] is False
    assert db.scalar("SELECT COUNT(*) FROM fetch_tasks WHERE task_key LIKE 'trip:%'") == before


def test_dropping_a_country_removes_its_sweeps(client):
    trip = make_trip(client)
    assert task_countries() == {"FR", "ES"}

    response = client.patch(f"/api/trips/{trip['id']}", json={"legs": legs(("FR", None))})

    assert response.status_code == 200
    assert response.json()["countries"] == ["FR"]
    assert response.json()["rescanned"] is True
    assert task_countries() == {"FR"}


def test_adding_a_country_plans_it(client):
    trip = make_trip(client, legs=legs(("FR", None)))
    assert task_countries() == {"FR"}

    client.patch(f"/api/trips/{trip['id']}", json={"legs": legs(("FR", None), ("IT", None))})

    assert task_countries() == {"FR", "IT"}


def test_narrowing_to_a_city_once_it_is_booked(client):
    trip = make_trip(client)

    response = client.patch(
        f"/api/trips/{trip['id']}", json={"legs": legs(("FR", "Lyon"), ("ES", None))}
    )

    assert response.json()["cities"] == ["Lyon"]
    assert response.json()["rescanned"] is True


def test_a_partial_edit_keeps_everything_else(client):
    """You should be able to rename without resending the whole trip."""
    trip = make_trip(client, legs=legs(("FR", "Lyon"), ("ES", None)))

    updated = client.patch(f"/api/trips/{trip['id']}", json={"name": "Just the name"}).json()

    assert updated["name"] == "Just the name"
    assert updated["countries"] == ["FR", "ES"]
    assert updated["cities"] == ["Lyon"]
    assert updated["start_date"] == START.isoformat()
    assert updated["flex_before"] == 2


def test_changing_dates_replans(client):
    trip = make_trip(client)

    response = client.patch(
        f"/api/trips/{trip['id']}",
        json={"start_date": LATER_START.isoformat(), "end_date": LATER_END.isoformat()},
    )

    assert response.json()["start_date"] == LATER_START.isoformat()
    assert response.json()["rescanned"] is True


def test_switching_to_strict_dates_clears_the_slack(client):
    trip = make_trip(client)

    updated = client.patch(f"/api/trips/{trip['id']}", json={"strict_dates": True}).json()

    assert updated["strict_dates"] is True
    assert updated["flex_before"] == 0
    assert updated["flex_after"] == 0


def test_an_invalid_edit_changes_nothing(client):
    trip = make_trip(client)

    response = client.patch(
        f"/api/trips/{trip['id']}", json={"end_date": BEFORE_START.isoformat()}
    )

    assert response.status_code == 400
    assert "before start date" in response.json()["detail"]
    unchanged = next(
        t for t in client.get("/api/trips").json()["trips"] if t["id"] == trip["id"]
    )
    assert unchanged["end_date"] == END.isoformat()


def test_editing_a_missing_trip_is_a_404(client):
    assert client.patch("/api/trips/999", json={"name": "nope"}).status_code == 404


def test_dropping_a_country_also_drops_its_coverage(client):
    trip = make_trip(client)
    queue.record_coverage(f"trip:{trip['id']}:ES", *_window(), "ticketmaster")
    assert db.scalar("SELECT COUNT(*) FROM coverage WHERE scope_key LIKE 'trip:%'") > 0

    client.patch(f"/api/trips/{trip['id']}", json={"legs": legs(("FR", None))})

    remaining = db.query("SELECT scope_key FROM coverage WHERE scope_key LIKE 'trip:%'")
    assert not any("ES" in row["scope_key"] for row in remaining)


def _window():
    return START, END
