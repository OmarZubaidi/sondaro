"""Driving times and the OpenRouteService host migration."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db, routing  # noqa: E402
from api.config import config  # noqa: E402

HOME = (38.0, -95.0)
FAIRVIEW = (37.5, -97.0)
MILLBROOK = (35.5, -100.5)


def directions(meters: float, seconds: float) -> dict:
    return {"features": [{"properties": {"summary": {"distance": meters, "duration": seconds}}}]}


@pytest.fixture(autouse=True)
def _no_pinned_host(monkeypatch):
    monkeypatch.delenv("ORS_BASE_URL", raising=False)


async def test_prefers_the_new_heigit_host(routes, monkeypatch):
    monkeypatch.setattr(config, "ors_api_key", "key")
    routes.add("api.heigit.org/v2/directions", directions(265_000, 9_360))

    route = await routing.drive_time(HOME, FAIRVIEW)

    assert route.estimated is False
    assert route.drive_hours == pytest.approx(2.6, abs=0.05)
    assert route.miles == pytest.approx(164.7, abs=1.0)
    assert routes.count("api.heigit.org") == 1


async def test_falls_back_to_the_legacy_host_and_remembers_it(routes, monkeypatch):
    """HeiGIT is retiring the old host, but the docs still describe it, so the
    new one is tried first and the old one catches us if it isn't live yet."""
    monkeypatch.setattr(config, "ors_api_key", "key")
    routes.add_error("api.heigit.org", 404)
    routes.add("api.openrouteservice.org/v2/directions", directions(265_000, 9_360))

    route = await routing.drive_time(HOME, FAIRVIEW)
    assert route.estimated is False
    assert db.get_meta("ors_working_base") == "https://api.openrouteservice.org"

    # the probe happens once; the next lookup goes straight to the winner
    routes.calls.clear()
    await routing.drive_time(HOME, MILLBROOK)
    assert routes.count("api.heigit.org") == 0


async def test_an_explicit_base_url_pins_the_host(routes, monkeypatch):
    monkeypatch.setattr(config, "ors_api_key", "key")
    monkeypatch.setenv("ORS_BASE_URL", "https://ors.internal")
    routes.add("ors.internal/v2/directions", directions(100_000, 3_600))

    await routing.drive_time(HOME, FAIRVIEW)
    assert routes.count("ors.internal") == 1
    assert routes.count("heigit") == 0


async def test_ors_authenticates_with_an_api_key_query_param(routes, monkeypatch):
    """ORS documents ?api_key=<key> for the GET endpoints. Unlike JamBase, it
    is a query parameter, so the two providers must not be made to match."""
    monkeypatch.setattr(config, "ors_api_key", "ors-secret")
    routes.add("api.heigit.org/v2/directions", directions(1000, 100))

    await routing.drive_time(HOME, FAIRVIEW)

    assert "api_key=ors-secret" in str(routes.calls[0].url)


async def test_coordinates_are_sent_lon_lat(routes, monkeypatch):
    """ORS reverses the coordinate order used everywhere else in this codebase."""
    monkeypatch.setattr(config, "ors_api_key", "key")
    routes.add("api.heigit.org/v2/directions", directions(1000, 100))

    await routing.drive_time(HOME, FAIRVIEW)

    url = str(routes.calls[0].url)
    assert "start=-95.0%2C38.0" in url or "start=-95.0,38.0" in url
    assert "end=-97.0%2C37.5" in url or "end=-97.0,37.5" in url


async def test_routes_are_cached_and_never_resolved_twice(routes, monkeypatch):
    monkeypatch.setattr(config, "ors_api_key", "key")
    routes.add("api.heigit.org/v2/directions", directions(265_000, 9_360))

    first = await routing.drive_time(HOME, FAIRVIEW)
    second = await routing.drive_time(HOME, FAIRVIEW)

    assert first.drive_hours == second.drive_hours
    assert routes.count("directions") == 1


async def test_without_a_key_it_estimates_and_says_so(routes, monkeypatch):
    monkeypatch.setattr(config, "ors_api_key", "")

    route = await routing.drive_time(HOME, MILLBROOK)

    assert route.estimated is True
    assert route.miles == pytest.approx(350, abs=2)
    # great-circle * 1.25 / 55mph
    assert route.drive_hours == pytest.approx(7.95, abs=0.1)
    assert routes.calls == []


async def test_a_failed_lookup_degrades_to_an_estimate(routes, monkeypatch):
    monkeypatch.setattr(config, "ors_api_key", "key")
    routes.add_error("api.heigit.org", 500)
    routes.add_error("api.openrouteservice.org", 500)

    route = await routing.drive_time(HOME, FAIRVIEW)
    assert route.estimated is True


async def test_a_cached_estimate_is_upgraded_once_routing_works(routes, monkeypatch):
    monkeypatch.setattr(config, "ors_api_key", "")
    estimated = await routing.drive_time(HOME, FAIRVIEW)
    assert estimated.estimated is True

    monkeypatch.setattr(config, "ors_api_key", "key")
    routes.add("api.heigit.org/v2/directions", directions(265_000, 9_360))

    upgraded = await routing.drive_time(HOME, FAIRVIEW)
    assert upgraded.estimated is False


async def test_moving_house_misses_cleanly_and_keeps_the_old_rows(routes, monkeypatch):
    monkeypatch.setattr(config, "ors_api_key", "key")
    routes.add("api.heigit.org/v2/directions", directions(265_000, 9_360))
    await routing.drive_time(HOME, FAIRVIEW)

    springfield = (38.2, -95.2)
    await routing.drive_time(springfield, FAIRVIEW)

    # keyed on origin, so the new home is a miss and the old row survives
    assert routing.cached(routing.point_key(*HOME), routing.point_key(*FAIRVIEW))
    assert routing.cached(routing.point_key(*springfield), routing.point_key(*FAIRVIEW))
    assert routes.count("directions") == 2


async def test_geocoding_powers_the_home_search_box(routes, monkeypatch):
    monkeypatch.setattr(config, "ors_api_key", "key")
    routes.add(
        "/geocode/search",
        {
            "features": [
                {
                    "geometry": {"coordinates": [-95.0, 38.0]},
                    "properties": {"label": "Fairview, KS, USA", "country_a": "USA"},
                }
            ]
        },
    )

    results = await routing.geocode("Fairview")
    assert results == [
        {"label": "Fairview, KS, USA", "lat": 38.0, "lon": -95.0, "country": "USA"}
    ]


async def test_geocoding_without_a_key_returns_nothing(routes, monkeypatch):
    monkeypatch.setattr(config, "ors_api_key", "")
    assert await routing.geocode("Fairview") == []
    assert routes.calls == []


# --------------------------------------------------------------------------
# the city picker
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def spain_index(tmp_path, monkeypatch):
    """Pelias answers in alpha-3 and everything downstream speaks alpha-2, so
    the picker needs the border index to translate."""
    from api import borders
    from scripts import build_borders

    path = tmp_path / "borders.db"
    build_borders.build(
        {
            "features": [
                {
                    "properties": {"ISO_A2_EH": "ES", "ISO_A3_EH": "ESP", "NAME_EN": "Spain"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0.0, 40.0], [3.0, 40.0], [3.0, 42.0], [0.0, 40.0]]],
                    },
                }
            ]
        },
        path,
    )
    monkeypatch.setattr(config, "borders_db", str(path))
    borders.reset()
    borders.alpha2_for.cache_clear()
    yield
    borders.reset()
    borders.alpha2_for.cache_clear()


PICKER_RESPONSE = {
    "features": [
        {
            "geometry": {"type": "Point", "coordinates": [2.1686, 41.3874]},
            "properties": {
                "name": "Barcelona",
                "label": "Barcelona, Catalonia, Spain",
                "country_a": "ESP",
            },
        }
    ]
}


async def test_the_picker_narrows_to_cities_in_the_trips_countries(routes, monkeypatch):
    """Unrestricted, "Barcelona" offers streets and a Barcelona in Venezuela."""
    monkeypatch.setattr(config, "ors_api_key", "key")
    routes.add("/geocode/autocomplete", PICKER_RESPONSE)

    results = await routing.search_cities("Barcel", ["ES", "FR"])

    assert results[0]["name"] == "Barcelona"
    assert results[0]["country"] == "ES"  # alpha-3 in, alpha-2 out
    url = str(routes.calls[0].url)
    assert "layers=locality%2Clocaladmin" in url or "layers=locality,localadmin" in url
    assert "boundary.country=ES%2CFR" in url or "boundary.country=ES,FR" in url


async def test_picking_a_city_caches_where_it_is(routes, monkeypatch):
    """So scoring, which reads places synchronously, never has to look it up."""
    monkeypatch.setattr(config, "ors_api_key", "key")
    routes.add("/geocode/autocomplete", PICKER_RESPONSE)

    await routing.search_cities("Barcel", ["ES"])

    assert routing.cached_place("Barcelona") == (41.3874, 2.1686, "ES")


async def test_a_deployment_without_autocomplete_falls_back_once(routes, monkeypatch):
    """A missing path costs a quota call per host per keystroke, and looks
    exactly like an empty result. Find out once, then stop asking."""
    monkeypatch.setattr(config, "ors_api_key", "key")
    routes.add_error("/geocode/autocomplete", 404)
    routes.add("/geocode/search", PICKER_RESPONSE)

    assert await routing.search_cities("Barcel", ["ES"])
    tried_first_time = routes.count("/geocode/autocomplete")

    assert await routing.search_cities("Madr", ["ES"])
    assert routes.count("/geocode/autocomplete") == tried_first_time


async def test_the_picker_is_off_without_a_key(routes, monkeypatch):
    monkeypatch.setattr(config, "ors_api_key", "")

    assert await routing.search_cities("Barcel", ["ES"]) == []
    assert routes.calls == []


async def test_one_character_is_not_a_search(routes, monkeypatch):
    """Every keystroke is a billable-ish call; a single letter can't be useful."""
    monkeypatch.setattr(config, "ors_api_key", "key")

    assert await routing.search_cities("B", ["ES"]) == []
    assert routes.calls == []
