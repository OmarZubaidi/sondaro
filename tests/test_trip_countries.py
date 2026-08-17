"""The country filter is also the explanation.

A trip to France that shows nothing can mean the sweep hasn't run, that France
is your home country and deliberately left alone, or that genuinely nothing in
your library is playing there. Leaving the country out of the list entirely
made all three indistinguishable from "France isn't on any trip", so every
country a trip touches gets a row — with a zero, a "still going" marker, or a
reason it will stay empty.
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


def countries(client) -> dict[str, dict]:
    return {c["name"]: c for c in client.get("/api/trips").json()["countries"]}


def test_a_country_with_nothing_still_gets_a_row(client):
    """The whole point: an empty country you can see is an answer, and an
    absent one is a question the page used to need a banner to answer."""
    a_trip(client, [{"country": "FR"}])

    assert "France" in countries(client)


def test_a_country_still_being_swept_is_marked_as_such(client):
    """Zero isn't the final answer yet, and the row says so rather than
    inviting you to go and edit the trip."""
    a_trip(client, [{"country": "FR"}])

    assert countries(client)["France"]["searching"] is True


def test_a_swept_country_with_nothing_on_is_not(client):
    """Same zero, opposite meaning: waiting will not help."""
    a_trip(client, [{"country": "FR"}])
    db.execute("UPDATE fetch_tasks SET last_ok_at = ?", (now_iso(),))

    assert countries(client)["France"]["searching"] is False


def test_a_country_that_produced_shows_is_never_marked_as_searching(client):
    a_show_in_lyon()
    a_trip(client, [{"country": "FR"}])

    assert countries(client)["France"] == {
        "code": "FR",
        "name": "France",
        "searching": False,
        "note": None,
    }


def test_both_halves_of_a_trip_are_listed(client):
    """The reported shape: cities booked in one country, another left open and
    showing nothing. Both belong in the filter."""
    a_show_in_lyon()
    a_trip(client, [{"country": "FR"}, {"country": "IS"}])

    assert set(countries(client)) == {"France", "Iceland"}


def test_the_home_country_explains_itself_in_a_tooltip(client):
    """It is deliberately not swept, which no amount of waiting changes — and
    that can't be inferred from a zero."""
    settings.set_value("home_country", "FR")
    a_trip(client, [{"country": "FR"}])

    entry = countries(client)["France"]
    assert entry["searching"] is False
    assert "home country" in entry["note"]


def test_a_detour_over_a_border_is_listed_too(client):
    """A show can turn up somewhere no trip goes. Filtering it needs a row."""
    a_show_in_lyon()
    a_trip(client, [{"country": "IS"}, {"country": "FR"}])

    assert "France" in countries(client)
