"""Behaviour tests for the worldwide favorites feed.

The interesting half of this file is what happens when the ranking moves. The
event cache is global and keyed on the listing, not on who was in your top ten
when it was fetched, so a favourite who slips a place keeps every date already
paid for — and the follow window keeps them on the page long enough to notice.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import borders, db, library, queue, scan, settings  # noqa: E402
from api.config import config  # noqa: E402
from api.match import artist_key  # noqa: E402
from api.providers.base import Event  # noqa: E402
from api.util import now_iso, today  # noqa: E402
from scripts import build_borders  # noqa: E402

scenarios("favorites.feature")

HOME = (38.0, -95.0)
# (lat, lon, ISO-2, region)
PLACES = {
    "Springfield": (38.2, -95.2, "US", "KS"),
    "Berlin": (52.5200, 13.4050, "DE", None),
    "Munich": (48.1351, 11.5820, "DE", None),
    "Amsterdam": (52.3676, 4.9041, "NL", None),
    "Tokyo": (35.6762, 139.6503, "JP", None),
    "Boston": (42.3601, -71.0589, "US", "MA"),
    "Chicago": (41.8781, -87.6298, "US", "IL"),
    "Los Angeles": (34.0522, -118.2437, "US", "CA"),
}

# Berlin first, then Munich, then Tokyo — so "Germany before Japan" is a claim
# about grouping by earliest date rather than an accident of insertion order.
# Berlin and Munich are deliberately ten days apart, which is the span that has
# to stay inside one trip.
WHEN_PLAYED = {
    "Berlin": today() + timedelta(days=20),
    "Amsterdam": today() + timedelta(days=22),
    "Boston": today() + timedelta(days=20),
    "Chicago": today() + timedelta(days=22),
    "Los Angeles": today() + timedelta(days=22),
    "Munich": today() + timedelta(days=30),
    "Tokyo": today() + timedelta(days=40),
}

BORDER_SAMPLE = {
    "features": [
        {
            "properties": {"ISO_A2_EH": code, "ISO_A3_EH": code3, "NAME_EN": name},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0.0, 40.0], [3.0, 40.0], [3.0, 42.0], [0.0, 40.0]]],
            },
        }
        for code, code3, name in (
            ("US", "USA", "United States"),
            ("DE", "DEU", "Germany"),
            ("NL", "NLD", "Netherlands"),
            ("JP", "JPN", "Japan"),
        )
    ]
}


@pytest.fixture
def world():
    return {"feed": None, "counter": 0}


@pytest.fixture
def client(monkeypatch, routes):
    """Every scenario gets the mock transport installed, with nothing routed.

    That makes "no provider was called" a real assertion rather than a vacuous
    one: an outbound call from this feed would hit the registry, find no route,
    and fail the request outright.
    """
    monkeypatch.setattr(config, "worker_enabled", False)
    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------------------------------
# Given
# --------------------------------------------------------------------------


@given("my home is set")
def _home():
    settings.set_value("home_lat", HOME[0])
    settings.set_value("home_lon", HOME[1])


@given("Ticketmaster is configured")
def _ticketmaster(monkeypatch):
    monkeypatch.setattr(config, "ticketmaster_api_key", "test-key")


@given("the border index is loaded")
def _borders(tmp_path, monkeypatch):
    path = tmp_path / "borders.db"
    build_borders.build(BORDER_SAMPLE, path)
    monkeypatch.setattr(config, "borders_db", str(path))
    borders.reset()
    yield
    borders.reset()


@given(parsers.parse("I follow my top {count:d} artists"))
@given(parsers.parse("I follow my top {count:d} artist"))
def _follow_count(count):
    settings.set_value("favorite_artists", count)


@given(parsers.parse('"{name}" is a favourite with {listens:d} scrobbles'))
def _favourite(name, listens):
    """Affinity is set flat at 1.0 on purpose. Everyone in the top decile
    clamps there, which is exactly the case where the ranking has to fall back
    on play counts instead of the alphabet."""
    db.execute(
        "INSERT INTO artists(key, name, affinity, listens, updated_at) "
        "VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
        "affinity=excluded.affinity, listens=excluded.listens",
        (artist_key(None, name), name, 1.0, listens, now_iso()),
    )


@given(parsers.parse('"{name}" plays {place}'))
def _plays(world, name, place):
    lat, lon, country, region = PLACES[place]
    world["counter"] += 1
    scan.ingest(
        [
            Event(
                provider="ticketmaster",
                provider_event_id=f"t{world['counter']}",
                artist_name=name,
                date=WHEN_PLAYED[place].isoformat(),
                time="20:00",
                venue=f"{place} Hall",
                city=place,
                region=region,
                country=country,
                lat=lat,
                lon=lon,
                url=f"https://example.test/t{world['counter']}",
            )
        ],
        library.all_artists(),
    )


def _lookup_task(name: str, **columns) -> None:
    key = queue.artist_task_key(queue.local_scope(*settings.home()), artist_key(None, name))
    queue.plan_artist_lookup(
        artist_key(None, name), name, 1.0, today(), settings.horizon_end(),
        scope=queue.local_scope(*settings.home()), worldwide=True,
    )
    for column, value in columns.items():
        db.execute(f"UPDATE fetch_tasks SET {column} = ? WHERE task_key = ?", (value, key))


@given(parsers.parse('the worldwide search for "{name}" has run'))
def _searched(name):
    _lookup_task(name, last_ok_at=now_iso())


@given(parsers.parse('I have been following "{name}"'))
def _following(name):
    library.follow_top(settings.get("favorite_artists"))
    assert db.query_one(
        "SELECT top_seen_at FROM artists WHERE key = ?", (artist_key(None, name),)
    )["top_seen_at"] is not None, f"{name} was not in the top slice to begin with"


# --------------------------------------------------------------------------
# When
# --------------------------------------------------------------------------


@when(parsers.parse('"{name}" slips out of my top {count:d}'))
def _slips(name, count):
    """Someone else out-listens them. Nothing touches the event cache, which is
    the whole point."""
    for rank in range(count):
        filler = f"Newly Obsessed {rank}"
        db.execute(
            "INSERT INTO artists(key, name, affinity, listens, updated_at) "
            "VALUES(?,?,?,?,?)",
            (artist_key(None, filler), filler, 1.0, 90_000 + rank, now_iso()),
        )
    assert artist_key(None, name) not in {
        a.key for a in library.top_artists(count)
    }, f"{name} is still in the top {count}"


@when(parsers.parse("I cut back to my top {count:d} artist"))
def _cut_back(client, count):
    response = client.patch("/api/settings", json={"favorite_artists": count})
    assert response.status_code == 200, response.text


@when("I look at who's touring")
def _look(world, client):
    _fetch(world, client)


@when(parsers.parse("I look at trips of at most {days:d} days"))
def _look_tight(world, client, days):
    _fetch(world, client, cluster_days=days)


@when(parsers.parse("I look at trips within {km:d} km"))
def _look_wide(world, client, km):
    _fetch(world, client, cluster_km=km)


def _fetch(world, client, **params) -> None:
    response = client.get("/api/favorites", params=params)
    assert response.status_code == 200, response.text
    world["feed"] = response.json()


# --------------------------------------------------------------------------
# Then
# --------------------------------------------------------------------------


def _artist(world, name: str) -> dict | None:
    return next((a for a in world["feed"]["artists"] if a["name"] == name), None)


def _dates(world) -> list[dict]:
    return [
        show
        for artist in world["feed"]["artists"]
        for country in artist["countries"]
        for show in country["shows"]
    ]


@then(parsers.parse('"{name}" is listed'))
def _listed(world, name):
    assert _artist(world, name) is not None, (
        f"{name} missing from {[a['name'] for a in world['feed']['artists']]}"
    )


@then(parsers.parse('"{name}" is not listed'))
def _not_listed(world, name):
    assert _artist(world, name) is None


@then(parsers.parse("the {place} date is listed under {country}"))
def _date_under_country(world, place, country):
    for artist in world["feed"]["artists"]:
        for entry in artist["countries"]:
            if entry["name"] == country:
                assert any(show["city"] == place for show in entry["shows"])
                return
    raise AssertionError(f"no {country} group in {world['feed']}")


@then("no date is flagged")
def _unflagged(world):
    assert all(not show["flags"] for show in _dates(world))


@then("no date claims a drive time")
def _no_drive(world):
    """There is no origin to measure from, so a number here would be invented."""
    assert all(show["drive_hours"] is None for show in _dates(world))


@then(parsers.parse("{country} holds {count:d} dates"))
def _country_count(world, country, count):
    groups = [
        entry
        for artist in world["feed"]["artists"]
        for entry in artist["countries"]
        if entry["name"] == country
    ]
    assert sum(len(entry["shows"]) for entry in groups) == count


@then(parsers.parse("{first} is listed before {second}"))
def _country_order(world, first, second):
    for artist in world["feed"]["artists"]:
        names = [entry["name"] for entry in artist["countries"]]
        if first in names and second in names:
            assert names.index(first) < names.index(second), names
            return
    raise AssertionError(f"no artist plays both {first} and {second}")


def _trip_of(world, city: str) -> int | None:
    for show in _dates(world):
        if show["city"] == city:
            return show["cluster"]
    raise AssertionError(f"no date in {city}")


def _trip(world, trip_id: int) -> dict:
    return next(t for t in world["feed"]["clusters"] if t["id"] == trip_id)


@then(parsers.parse("{first} and {second} are the same trip"))
def _same_trip(world, first, second):
    left, right = _trip_of(world, first), _trip_of(world, second)
    assert left is not None and left == right, f"{first} in {left}, {second} in {right}"
    world["trip"] = left


@then(parsers.parse("{first} and {second} are different trips"))
def _different_trips(world, first, second):
    left, right = _trip_of(world, first), _trip_of(world, second)
    assert left != right, f"{first} and {second} both landed in trip {left}"


@then(parsers.parse("that trip covers {count:d} favourites"))
def _trip_covers(world, count):
    names = {
        show["artist"] for show in _dates(world) if show["cluster"] == world["trip"]
    }
    assert len(names) == count, names


@then(parsers.parse('that trip is named "{label}"'))
def _trip_named(world, label):
    trip_id = world.get("trip")
    if trip_id is None:
        assert len(world["feed"]["clusters"]) == 1, "which trip? none was established"
        trip_id = world["feed"]["clusters"][0]["id"]
    assert " + ".join(_trip(world, trip_id)["places"]) == label


@then(parsers.parse('"{name}" is still being searched'))
def _searching(world, name):
    assert _artist(world, name)["searching"] is True


@then(parsers.parse('"{name}" is not still being searched'))
def _not_searching(world, name):
    assert _artist(world, name)["searching"] is False


@then(parsers.parse('"{name}" is marked as slipped'))
def _slipped(world, name):
    assert _artist(world, name)["slipped"] is True


@then("no provider was called")
def _no_calls(routes):
    assert routes.calls == [], [str(call.url) for call in routes.calls]
