"""Artist photos ride along on shows and favorites.

The browser loads them from wherever Lidarr says they live, so the API only
has to carry the URL, or say plainly that there isn't one.
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

HOME = (38.0, -95.0)
SOON = date.today() + timedelta(days=21)
POSTER = "https://img.test/poster.jpg"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "worker_enabled", False)
    settings.set_value("home_lat", HOME[0])
    settings.set_value("home_lon", HOME[1])

    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


def a_show_by(name: str, poster: str | None = None) -> None:
    db.execute(
        "INSERT INTO artists(key, name, affinity, listens, updated_at, image_poster) "
        "VALUES(?,?,?,?,?,?)",
        (artist_key(None, name), name, 1.0, 100, now_iso(), poster),
    )
    scan.ingest(
        [
            Event(
                provider="ticketmaster",
                provider_event_id=name.lower(),
                artist_name=name,
                date=SOON.isoformat(),
                time="20:00",
                venue="The Hall",
                city="Nearby",
                country="US",
                lat=HOME[0] + 0.1,
                lon=HOME[1] + 0.1,
            )
        ],
        library.all_artists(),
    )
    # bought, so it clears every filter and the test is about the field alone
    scan.set_purchased(f"ticketmaster:{name.lower()}", True)


def test_a_show_carries_its_artists_photo(client):
    a_show_by("Photographed", POSTER)

    shows = [show for month in client.get("/api/local").json()["months"] for show in month["shows"]]

    assert [show["image"] for show in shows] == [{"poster": POSTER, "fanart": None}]


def test_a_favorite_carries_its_photo_or_says_there_is_none(client):
    a_show_by("Photographed", POSTER)
    a_show_by("Unphotographed")

    artists = client.get("/api/favorites").json()["artists"]

    assert {artist["name"]: artist["image"] for artist in artists} == {
        "Photographed": {"poster": POSTER, "fanart": None},
        "Unphotographed": None,
    }
