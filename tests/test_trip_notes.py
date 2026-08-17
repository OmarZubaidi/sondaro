"""An empty country has to say which kind of empty it is.

A trip to France that shows nothing can mean the sweep hasn't run, that France
is your home country and deliberately left alone, or that genuinely nothing in
your library is playing there. All three render as a blank list, and the first
is worth waiting for while the third is worth acting on.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db, library, scan, settings  # noqa: E402
from api.config import config  # noqa: E402
from api.match import artist_key  # noqa: E402
from api.providers.base import Event  # noqa: E402
from api.util import now_iso  # noqa: E402

START = date.today() + timedelta(days=30)
END = START + timedelta(days=10)
LYON = (45.7640, 4.8357)


@pytest.fixture(autouse=True)
def named_countries(tmp_path, monkeypatch):
    """A note that says "IS" instead of "Iceland" is barely a note, so these
    assert the names the user actually reads — which needs the border index."""
    from api import borders
    from scripts import build_borders

    path = tmp_path / "borders.db"
    build_borders.build(
        {
            "features": [
                {
                    "properties": {"ISO_A2_EH": code, "ISO_A3_EH": code3, "NAME_EN": name},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0.0, 40.0], [3.0, 40.0], [3.0, 42.0], [0.0, 40.0]]],
                    },
                }
                for code, code3, name in (
                    ("FR", "FRA", "France"),
                    ("IS", "ISL", "Iceland"),
                )
            ]
        },
        path,
    )
    monkeypatch.setattr(config, "borders_db", str(path))
    borders.reset()
    yield
    borders.reset()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "worker_enabled", False)
    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


def a_trip(client, legs, name="Europe"):
    response = client.post(
        "/api/trips",
        json={
            "name": name,
            "legs": legs,
            "start_date": START.isoformat(),
            "end_date": END.isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def a_show_in_lyon() -> None:
    name = "Palehound"
    db.execute(
        "INSERT INTO artists(key, name, affinity, listens, updated_at) VALUES(?,?,?,?,?)",
        (artist_key(None, name), name, 1.0, 500, now_iso()),
    )
    scan.ingest(
        [
            Event(
                provider="ticketmaster",
                provider_event_id="lyon-1",
                artist_name=name,
                date=(START + timedelta(days=2)).isoformat(),
                venue="Le Transbordeur",
                city="Lyon",
                country="FR",
                lat=LYON[0],
                lon=LYON[1],
            )
        ],
        library.all_artists(),
    )


def notes(client) -> list[str]:
    return client.get("/api/trips").json()["notes"]


def test_a_country_still_being_swept_says_so(client):
    """The common case on a trip you added a minute ago."""
    a_trip(client, [{"country": "FR"}])

    assert any("still searching France" in note for note in notes(client))


def test_a_swept_country_with_nothing_on_says_that_instead(client):
    """Same blank list, opposite meaning: waiting will not help."""
    a_trip(client, [{"country": "FR"}])
    db.execute("UPDATE fetch_tasks SET last_ok_at = ?", (now_iso(),))

    assert any("nothing from your library" in note for note in notes(client))
    assert not any("still searching" in note for note in notes(client))


def test_a_country_that_produced_shows_is_not_mentioned(client):
    """Notes are for absences. Explaining a country that worked is noise."""
    a_show_in_lyon()
    a_trip(client, [{"country": "FR"}])

    assert notes(client) == []


def test_only_the_empty_half_of_a_trip_is_explained(client):
    """The reported shape: cities booked in one country, another left open and
    showing nothing, with no way to tell why."""
    a_show_in_lyon()
    a_trip(client, [{"country": "FR"}, {"country": "IS"}])

    reported = notes(client)
    assert len(reported) == 1
    assert "Iceland" in reported[0]


def test_the_home_country_still_explains_itself(client):
    """It is deliberately not swept, which no amount of waiting changes."""
    settings.set_value("home_country", "FR")
    a_trip(client, [{"country": "FR"}])

    assert any("home country" in note for note in notes(client))
