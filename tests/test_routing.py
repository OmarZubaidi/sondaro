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
    assert route.miles == pytest.approx(355, abs=2)
    # great-circle * 1.25 / 55mph
    assert route.drive_hours == pytest.approx(8.07, abs=0.1)
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
                    "properties": {"label": "Home, USA", "country_a": "USA"},
                }
            ]
        },
    )

    results = await routing.geocode("Home")
    assert results == [
        {"label": "Home, USA", "lat": 38.0, "lon": -95.0, "country": "USA"}
    ]


async def test_geocoding_without_a_key_returns_nothing(routes, monkeypatch):
    monkeypatch.setattr(config, "ors_api_key", "")
    assert await routing.geocode("Home") == []
    assert routes.calls == []
