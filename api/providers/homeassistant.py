"""Home Assistant as the source of truth for where you live.

Home Assistant already knows your latitude, longitude, location name and
country, and you already maintain them there. Keeping a second copy in
Sondaro's settings means two places to update and one of them silently going
stale, so when this is configured Home Assistant wins and the UI stops
offering a location search.

`/api/config` returns all four fields in one call, so this needs no entity
lookups and no polling of state.

Read-only, enforced the same way the Lidarr client is: a token that can drive
your whole house should not be usable by this app to do anything but read.
"""

import logging
import os

from .. import http

log = logging.getLogger("sondaro.homeassistant")

ALLOWED_METHODS = frozenset({"GET"})
ALLOWED_PATHS = frozenset({"/api/config"})


class ReadOnlyViolation(RuntimeError):
    """Raised when something tries to make Home Assistant do anything but read."""


def base_url() -> str:
    return os.getenv("HASS_URL", "").strip().rstrip("/")


def token() -> str:
    return os.getenv("HASS_TOKEN", "").strip()


def available() -> bool:
    return bool(base_url() and token())


async def _request(method: str, path: str) -> dict | None:
    verb = method.upper()
    if verb not in ALLOWED_METHODS:
        raise ReadOnlyViolation(
            f"{verb} is not permitted against Home Assistant. This client is "
            f"read-only; allowed methods are {sorted(ALLOWED_METHODS)}."
        )
    if path not in ALLOWED_PATHS:
        raise ReadOnlyViolation(
            f"{path} is not an allowed Home Assistant path. "
            f"Allowed: {sorted(ALLOWED_PATHS)}."
        )

    payload = await http.get_json(
        f"{base_url()}{path}",
        headers={"Authorization": f"Bearer {token()}"},
        rate_limited=False,  # it's on the LAN and it's ours
    )
    return payload if isinstance(payload, dict) else None


async def fetch_home() -> dict | None:
    """Latitude, longitude, label and country, or None if unavailable.

    Returns None rather than raising: Home Assistant being down should leave
    the last known home in place, not blank it out.
    """
    if not available():
        return None

    config = await _request("GET", "/api/config")
    if not config:
        log.warning("home assistant did not answer; keeping the stored home")
        return None

    lat, lon = config.get("latitude"), config.get("longitude")
    if lat is None or lon is None:
        log.warning("home assistant returned no coordinates")
        return None

    return {
        "lat": float(lat),
        "lon": float(lon),
        "label": str(config.get("location_name") or "").strip() or None,
        "country": str(config.get("country") or "").strip().upper() or None,
    }
