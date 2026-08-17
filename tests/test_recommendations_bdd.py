"""Behaviour tests for the home watch and the trip planner.

These drive the real pipeline — ingest, match, route, score — with providers
stubbed at the transport layer. Nothing here reaches the network; `conftest`
makes that impossible.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import borders, db, library, routing, scan, settings  # noqa: E402
from api.config import config  # noqa: E402
from api.match import artist_key  # noqa: E402
from api.providers.base import Event  # noqa: E402
from api.util import now_iso  # noqa: E402
from scripts import build_borders  # noqa: E402

scenarios("recommendations.feature")
scenarios("trips.feature")

HOME = (38.0, -95.0)
PLACES = {
    "Springfield": (38.2, -95.2, "US", 0.5),
    "New York": (40.7128, -74.0060, "US", 9.0),
    "Los Angeles": (34.0522, -118.2437, "US", 40.0),
    "Fairview": (37.5, -97.0, "US", 2.6),
    "Millbrook": (35.5, -100.5, "US", 6.0),
    "Lyon": (45.7640, 4.8357, "FR", 12.0),
    "Toronto": (43.6532, -79.3832, "CA", 11.0),
    "Barcelona": (41.3874, 2.1686, "ES", 14.0),
    "Geneva": (46.2044, 6.1432, "CH", 13.0),
    "Berlin": (52.5200, 13.4050, "DE", 15.0),
}

# A Tuesday and a Saturday in the same week, comfortably in the future.
TUESDAY = date(2026, 9, 8)
SATURDAY = date(2026, 9, 12)
TRIP_START = date(2026, 9, 5)
TRIP_END = date(2026, 9, 20)
AWAY_START = date(2026, 9, 7)
AWAY_END = date(2026, 9, 14)

FRANCE_EAST_LON = 6.10
BORDER_SAMPLE = {
    "features": [
        {
            "properties": {"ISO_A2_EH": "FR", "NAME_EN": "France"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-1.0, 43.0],
                        [FRANCE_EAST_LON, 43.0],
                        [FRANCE_EAST_LON, 49.0],
                        [-1.0, 49.0],
                        [-1.0, 43.0],
                    ]
                ],
            },
        },
        {
            "properties": {"ISO_A2_EH": "ES", "NAME_EN": "Spain"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[-9.0, 36.0], [3.0, 36.0], [3.0, 43.0], [-9.0, 43.0], [-9.0, 36.0]]
                ],
            },
        },
    ]
}


@pytest.fixture
def world():
    """Mutable scenario state."""
    return {"events": [], "trip": None, "results": [], "counter": 0}


# --------------------------------------------------------------------------
# Given
# --------------------------------------------------------------------------


@given("my home is Home")
def _home(monkeypatch):
    settings.set_value("home_lat", HOME[0])
    settings.set_value("home_lon", HOME[1])
    settings.set_value("home_label", "Home")
    # a real drive time for every place, so scoring is exercised rather than
    # the estimator
    origin = routing.point_key(*HOME)
    for name, (lat, lon, _country, hours) in PLACES.items():
        routing.store(
            origin,
            routing.point_key(lat, lon),
            routing.Route(drive_hours=hours, miles=hours * 60, estimated=False),
        )


@given("Ticketmaster is configured")
def _tm(monkeypatch):
    monkeypatch.setattr(config, "ticketmaster_api_key", "test-key")


@given("OpenRouteService is not configured")
def _no_ors(monkeypatch):
    monkeypatch.setattr(config, "ors_api_key", "")
    # drop the seeded routes so the estimator has to take over
    db.execute("DELETE FROM routes")


@given("the border index is loaded")
def _borders(tmp_path, monkeypatch):
    path = tmp_path / "borders.db"
    build_borders.build(BORDER_SAMPLE, path)
    monkeypatch.setattr(config, "borders_db", str(path))
    borders.reset()
    yield
    borders.reset()


def _add_artist(name: str, listens: int, ceiling: int) -> None:
    from api import scoring

    db.execute(
        "INSERT INTO artists(key, mbid, name, lidarr_id, monitored, listens, affinity, "
        "updated_at) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET listens=excluded.listens, affinity=excluded.affinity",
        (
            artist_key(None, name),
            None,
            name,
            1,
            1,
            listens,
            scoring.affinity(listens, ceiling),
            now_iso(),
        ),
    )


@given(parsers.parse('"{name}" is an artist I play constantly'))
def _favourite(name):
    _add_artist(name, listens=5000, ceiling=5000)


@given(parsers.parse('"{name}" is an artist I rarely play'))
def _midtier(name):
    # ~0.67 affinity: liked, not beloved
    _add_artist(name, listens=17, ceiling=5000)


def _make_event(world, name: str, place: str, day: date) -> None:
    lat, lon, country, _hours = PLACES[place]
    world["counter"] += 1
    event = Event(
        provider="ticketmaster",
        provider_event_id=f"e{world['counter']}",
        artist_name=name,
        title=f"{name} — 2026 Tour",
        date=day.isoformat(),
        time="20:00",
        venue=f"{place} Hall",
        city=place,
        country=country,
        lat=lat,
        lon=lon,
        url=f"https://example.test/e{world['counter']}",
    )
    world["events"].append(event)
    scan.ingest([event], library.all_artists())


@given(parsers.parse('"{name}" plays {place} on a Tuesday'))
def _plays_tuesday(world, name, place):
    _make_event(world, name, place, TUESDAY)


@given(parsers.parse('"{name}" plays {place} on a Saturday'))
def _plays_saturday(world, name, place):
    _make_event(world, name, place, SATURDAY)


@given(parsers.parse('"{name}" plays {place} during the trip'))
def _plays_during(world, name, place):
    _make_event(world, name, place, TRIP_START + timedelta(days=4))


@given(parsers.parse('"{name}" plays {place} two days after the trip ends'))
def _plays_after(world, name, place):
    _make_event(world, name, place, TRIP_END + timedelta(days=2))


def _make_trip(name: str, legs, start=None, end=None, **extra) -> int:
    """A trip and its legs. A leg is (country, city or None) — a country with
    no city is one you're going to but haven't planned."""
    trip_id = db.execute(
        "INSERT INTO trips(name, start_date, end_date, flex_before, flex_after, "
        "strict_dates, created_at) VALUES(?,?,?,?,?,?,?)",
        (
            name,
            (start or TRIP_START).isoformat(),
            (end or TRIP_END).isoformat(),
            extra.get("flex_before", 0),
            extra.get("flex_after", 0),
            extra.get("strict_dates", 0),
            now_iso(),
        ),
    )
    for country, city in legs:
        db.execute(
            "INSERT INTO trip_legs(trip_id, country, city) VALUES(?,?,?)",
            (trip_id, country, city),
        )
    return trip_id


@given("I am away on a trip that week")
def _away(world):
    world["away"] = _make_trip(
        "Away", [("FR", None)], AWAY_START, AWAY_END, flex_before=3, flex_after=3
    )


@given(parsers.parse('"{name}" plays {place} during that trip'))
def _plays_while_away(world, name, place):
    _make_event(world, name, place, AWAY_START + timedelta(days=2))


@given(parsers.parse('"{name}" plays {place} the day before that trip'))
def _plays_before_away(world, name, place):
    _make_event(world, name, place, AWAY_START - timedelta(days=1))


def _remember_places(*cities):
    from api import db as database

    for city in cities:
        lat, lon, country, _hours = PLACES[city]
        database.execute(
            "INSERT INTO places(query, lat, lon, country, resolved_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(query) DO NOTHING",
            (city.lower(), lat, lon, country, now_iso()),
        )


@given("I am going to Canada and France, but have only booked Toronto")
def _partial_trip(world):
    _remember_places("Toronto", "Lyon")
    world["trip"] = _make_trip(
        "Partly booked", [("CA", "Toronto"), ("FR", None)]
    )


@given("I am going to France and Spain, but have only booked Barcelona")
def _spain_booked_france_open(world):
    """The case the old pooled anchoring got wrong: once *any* city was named
    it became the anchor for everything, so Geneva was measured against
    Barcelona — 350 miles — rather than the French border it sits on."""
    _remember_places("Barcelona", "Lyon")
    world["trip"] = _make_trip("Europe", [("ES", "Barcelona"), ("FR", None)])


@given("I am going to the US with no cities named")
def _us_no_cities(world):
    _remember_places("Toronto")
    world["trip"] = _make_trip("US open", [("US", None)])


@given("my home country is the US")
def _home_country():
    settings.set_value("home_country", "US")


@given("I am going to New York in September")
def _domestic_trip(world):
    _remember_places("New York", "Los Angeles")
    world["trip"] = _make_trip("NYC", [("US", "New York")])


@given("I am going to France and Spain in September")
def _trip(world):
    world["trip"] = _make_trip("Europe", [("FR", None), ("ES", None)])


@given(parsers.parse("the trip has {days:d} days of slack either side"))
def _slack(world, days):
    db.execute(
        "UPDATE trips SET flex_before = ?, flex_after = ? WHERE id = ?",
        (days, days, world["trip"]),
    )


@given("the trip dates are strict")
def _strict(world):
    db.execute("UPDATE trips SET strict_dates = 1 WHERE id = ?", (world["trip"],))


# --------------------------------------------------------------------------
# When
# --------------------------------------------------------------------------


@when("I look at what's on near home")
def _look_home(world):
    world["results"] = scan.local_candidates()


@when("I look at the trip")
def _look_trip(world):
    row = db.query_one("SELECT * FROM trips WHERE id = ?", (world["trip"],))
    world["results"] = scan.trip_candidates(row)


# --------------------------------------------------------------------------
# Then
# --------------------------------------------------------------------------


def _find(world, name: str):
    return [c for c in world["results"] if c.artist.name == name]


@then(parsers.parse('"{name}" is recommended'))
def _recommended(world, name):
    assert _find(world, name), f"{name} missing from {[c.artist.name for c in world['results']]}"


@then(parsers.parse('"{name}" is not recommended'))
def _not_recommended(world, name):
    assert not _find(world, name)


@then("it carries no flags")
def _no_flags(world):
    assert all(not c.score.flags for c in world["results"])


@then("it ranks below anything closer to home")
def _ranks_low(world):
    ordered = sorted(world["results"], key=lambda c: -c.total)
    assert ordered[-1].event.city == "Millbrook"


@then("it is flagged as an estimated drive time")
def _estimated_flag(world):
    assert any("estimated drive time" in f for c in world["results"] for f in c.score.flags)


@then(parsers.parse('"{winner}" outranks "{loser}"'))
def _outranks(world, winner, loser):
    top = max(c.total for c in _find(world, winner))
    bottom = max(c.total for c in _find(world, loser))
    assert top > bottom, f"{winner} {top} did not outrank {loser} {bottom}"


@then("the Saturday show outranks the Tuesday show")
def _weekend_wins(world):
    saturday = next(c for c in world["results"] if c.event.date == SATURDAY.isoformat())
    tuesday = next(c for c in world["results"] if c.event.date == TUESDAY.isoformat())
    assert saturday.total > tuesday.total


@then(parsers.parse("the {city} show scores full marks on geography"))
def _city_full_geography(world, city):
    """France has no city named on this trip, so the whole country stays in
    play. Matching cities globally would anchor it on Toronto instead."""
    found = next(c for c in world["results"] if c.event.city == city)
    assert found.score.reach_fit == 1.0, f"{city} scored {found.score.reach_fit}"


@then("both shows score full marks on geography")
def _full_geography(world):
    cities = {c.event.city: c for c in world["results"]}
    assert "Lyon" in cities and "Barcelona" in cities
    assert cities["Lyon"].score.reach_fit == 1.0
    assert cities["Barcelona"].score.reach_fit == 1.0


@then(parsers.parse("the {city} show is recommended"))
def _city_in(world, city):
    assert any(c.event.city == city for c in world["results"]), \
        f"{city} missing from {[c.event.city for c in world['results']]}"


@then(parsers.parse("the {city} show is not recommended"))
def _city_out(world, city):
    assert not any(c.event.city == city for c in world["results"])


@then("the Geneva show is recommended")
def _geneva_in(world):
    assert any(c.event.city == "Geneva" for c in world["results"])


@then("the Berlin show is not recommended")
def _berlin_out(world):
    assert not any(c.event.city == "Berlin" for c in world["results"])


@then("it is flagged as not on my itinerary")
def _off_itinerary(world):
    assert any("not on your itinerary" in f for c in world["results"] for f in c.score.flags)


@then("the show is recommended")
def _some_show(world):
    assert world["results"]


@then("nothing is recommended")
def _nothing(world):
    assert world["results"] == [], [c.event.city for c in world["results"]]


@then("the show is not recommended")
def _no_show(world):
    assert not world["results"]


@then("it is flagged as outside my dates")
def _outside_dates(world):
    assert any("outside your dates" in f for c in world["results"] for f in c.score.flags)
