"""Driving times and geocoding via OpenRouteService.

Driving time, not distance, is what decides whether a show is gettable from
home: Home→DC and Home→Millbrook differ by 129 miles and far less in hours.

The cost is kept trivial by never routing per event. Routes are resolved home →
each *distinct venue city* and cached permanently, keyed on the origin — so a
few hundred lookups cover the whole horizon, and moving house misses cleanly and
re-resolves while the old rows stay put in case you move back.

Host migration: HeiGIT is deprecating `api.openrouteservice.org` in favour of
`api.heigit.org`. The new host is tried first as a drop-in, and the old one is
the fallback. Whichever answers is remembered, so the probe happens once rather
than on every call.
"""

import logging
import os
from dataclasses import dataclass

from . import db, http
from .config import config
from .geo import estimate_drive_hours, haversine_miles
from .util import now_iso

log = logging.getLogger("sondaro.routing")

PRIMARY_BASE = "https://api.heigit.org"
FALLBACK_BASE = "https://api.openrouteservice.org"
PROVIDER = "openrouteservice"
_WORKING_BASE_KEY = "ors_working_base"

METERS_PER_MILE = 1609.344


@dataclass
class Route:
    drive_hours: float
    miles: float
    estimated: bool


def available() -> bool:
    return bool(config.ors_api_key)


def _bases() -> list[str]:
    """Remembered host first, then the others. An explicit ORS_BASE_URL wins."""
    override = os.getenv("ORS_BASE_URL", "").strip().rstrip("/")
    if override:
        return [override]

    remembered = db.get_meta(_WORKING_BASE_KEY)
    ordered = [PRIMARY_BASE, FALLBACK_BASE]
    if remembered in ordered:
        ordered.remove(remembered)
        ordered.insert(0, remembered)
    return ordered


async def _ors_get(path: str, params: dict) -> dict | None:
    for base in _bases():
        try:
            payload = await http.get_json(
                f"{base}{path}",
                params={**params, "api_key": config.ors_api_key},
                provider=PROVIDER,
            )
        except http.QuotaExhausted:
            log.warning("openrouteservice daily cap reached")
            return None

        if payload is not None:
            if db.get_meta(_WORKING_BASE_KEY) != base:
                log.info("openrouteservice: using %s", base)
                db.set_meta(_WORKING_BASE_KEY, base)
            return payload

    return None


def point_key(lat: float, lon: float) -> str:
    """~100m precision. Nudging a pin by a few metres must not invalidate the
    entire cache."""
    return f"{lat:.3f},{lon:.3f}"


def cached(origin_key: str, dest_key: str) -> Route | None:
    row = db.query_one(
        "SELECT drive_hours, miles, estimated FROM routes "
        "WHERE origin_key = ? AND dest_key = ?",
        (origin_key, dest_key),
    )
    if row is None or row["drive_hours"] is None:
        return None
    return Route(row["drive_hours"], row["miles"], bool(row["estimated"]))


def store(origin_key: str, dest_key: str, route: Route) -> None:
    db.execute(
        "INSERT INTO routes(origin_key, dest_key, drive_hours, miles, estimated, "
        "resolved_at) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(origin_key, dest_key) DO UPDATE SET "
        "drive_hours = excluded.drive_hours, miles = excluded.miles, "
        "estimated = excluded.estimated, resolved_at = excluded.resolved_at",
        (
            origin_key,
            dest_key,
            route.drive_hours,
            route.miles,
            1 if route.estimated else 0,
            now_iso(),
        ),
    )


def estimate(origin: tuple[float, float], dest: tuple[float, float]) -> Route:
    """Great-circle fallback. Always marked estimated — the UI says so rather
    than presenting a guess as a measurement."""
    miles = haversine_miles(origin[0], origin[1], dest[0], dest[1])
    return Route(round(estimate_drive_hours(miles), 3), round(miles, 1), True)


async def drive_time(
    origin: tuple[float, float], dest: tuple[float, float], *, allow_estimate: bool = True
) -> Route | None:
    """Cached-or-resolved driving time. Never routes the same pair twice."""
    origin_key, dest_key = point_key(*origin), point_key(*dest)

    hit = cached(origin_key, dest_key)
    # a cached estimate is worth replacing once routing becomes available
    if hit and not (hit.estimated and available()):
        return hit

    if available():
        payload = await _ors_get(
            "/v2/directions/driving-car",
            {
                # ORS takes lon,lat — the reverse of every other coordinate
                # in this codebase, which is a good way to lose an afternoon
                "start": f"{origin[1]},{origin[0]}",
                "end": f"{dest[1]},{dest[0]}",
            },
        )
        summary = _summary(payload)
        if summary:
            meters, seconds = summary
            route = Route(round(seconds / 3600.0, 3), round(meters / METERS_PER_MILE, 1), False)
            store(origin_key, dest_key, route)
            return route
        log.info("routing unavailable for %s -> %s, estimating", origin_key, dest_key)

    if not allow_estimate:
        return hit

    route = estimate(origin, dest)
    store(origin_key, dest_key, route)
    return route


def _summary(payload: dict | None) -> tuple[float, float] | None:
    """(meters, seconds) from the GeoJSON directions response."""
    if not payload:
        return None
    features = payload.get("features") or []
    if not features:
        return None
    summary = (features[0].get("properties") or {}).get("summary") or {}
    distance, duration = summary.get("distance"), summary.get("duration")
    if distance is None or duration is None:
        return None
    return float(distance), float(duration)


async def geocode(text: str, limit: int = 5) -> list[dict]:
    """Forward geocode for the home-location search box, so nobody has to type
    raw coordinates."""
    if not (available() and text.strip()):
        return []

    payload = await _ors_get("/geocode/search", {"text": text.strip(), "size": limit})
    results = []
    for feature in (payload or {}).get("features") or []:
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        props = feature.get("properties") or {}
        if len(coords) < 2:
            continue
        results.append(
            {
                "label": props.get("label") or props.get("name") or text,
                "lat": float(coords[1]),
                "lon": float(coords[0]),
                "country": props.get("country_a"),
            }
        )
    return results
