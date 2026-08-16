"""Home Assistant as the source of truth for home location."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import settings, worker  # noqa: E402
from api.providers import homeassistant  # noqa: E402

HASS_CONFIG = {
    "latitude": 38.2,
    "longitude": -95.2,
    "location_name": "Springfield",
    "country": "US",
    "time_zone": "UTC",
}


@pytest.fixture
def hass(monkeypatch):
    monkeypatch.setenv("HASS_URL", "https://hass.test")
    monkeypatch.setenv("HASS_TOKEN", "long-lived-token")


async def test_refuses_anything_but_reading(routes, hass):
    """A token that can drive your whole house shouldn't be usable here to do
    anything but read."""
    for verb in ("POST", "PUT", "DELETE"):
        with pytest.raises(homeassistant.ReadOnlyViolation):
            await homeassistant._request(verb, "/api/config")

    with pytest.raises(homeassistant.ReadOnlyViolation):
        await homeassistant._request("GET", "/api/services")

    assert routes.calls == []


async def test_reads_all_four_fields_in_one_call(routes, hass):
    routes.add("/api/config", HASS_CONFIG)

    home = await homeassistant.fetch_home()

    assert home == {"lat": 38.2, "lon": -95.2, "label": "Springfield", "country": "US"}
    assert routes.count("/api/config") == 1


async def test_authenticates_with_a_bearer_token(routes, hass):
    routes.add("/api/config", HASS_CONFIG)
    await homeassistant.fetch_home()
    assert routes.calls[0].headers["Authorization"] == "Bearer long-lived-token"


async def test_unconfigured_is_a_no_op(routes, monkeypatch):
    monkeypatch.delenv("HASS_URL", raising=False)
    monkeypatch.delenv("HASS_TOKEN", raising=False)

    assert homeassistant.available() is False
    assert await homeassistant.fetch_home() is None
    assert routes.calls == []


async def test_an_unreachable_hass_keeps_the_stored_home(routes, hass):
    """Home Assistant being down must not blank out where you live."""
    routes.add_error("/api/config", 500)
    settings.set_value("home_label", "Home")

    assert await homeassistant.fetch_home() is None
    assert settings.get("home_label") == "Home"


async def test_adopting_a_new_location_triggers_a_reindex(routes, hass):
    routes.add("/api/config", HASS_CONFIG)
    settings.set_value("home_lat", 38.0)
    settings.set_value("home_lon", -95.0)

    moved = await worker.worker.sync_home_from_hass()

    assert moved is True
    assert settings.get("home_label") == "Springfield"
    assert settings.get("home_country") == "US"
    assert settings.get("home_lat") == pytest.approx(38.2)


async def test_the_same_location_does_not_reindex(routes, hass):
    routes.add("/api/config", HASS_CONFIG)
    settings.set_value("home_lat", 38.2)
    settings.set_value("home_lon", -95.2)

    assert await worker.worker.sync_home_from_hass() is False


async def test_missing_coordinates_are_ignored(routes, hass):
    routes.add("/api/config", {"location_name": "Nowhere"})
    assert await homeassistant.fetch_home() is None
