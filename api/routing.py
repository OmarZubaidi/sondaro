"""Driving times and geocoding via OpenRouteService.

Driving time, not distance, is what decides whether a show is gettable from
home: two venues can differ by 150km and far less in hours.

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
from .geo import estimate_drive_hours, haversine_km
from .util import now_iso

log = logging.getLogger("sondaro.routing")

PRIMARY_BASE = "https://api.heigit.org"
FALLBACK_BASE = "https://api.openrouteservice.org"
PROVIDER = "openrouteservice"
_WORKING_BASE_KEY = "ors_working_base"

METERS_PER_KM = 1000.0


@dataclass
class Route:
    drive_hours: float
    km: float
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
        "SELECT drive_hours, km, estimated FROM routes "
        "WHERE origin_key = ? AND dest_key = ?",
        (origin_key, dest_key),
    )
    if row is None or row["drive_hours"] is None:
        return None
    return Route(row["drive_hours"], row["km"], bool(row["estimated"]))


def store(origin_key: str, dest_key: str, route: Route) -> None:
    db.execute(
        "INSERT INTO routes(origin_key, dest_key, drive_hours, km, estimated, "
        "resolved_at) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(origin_key, dest_key) DO UPDATE SET "
        "drive_hours = excluded.drive_hours, km = excluded.km, "
        "estimated = excluded.estimated, resolved_at = excluded.resolved_at",
        (
            origin_key,
            dest_key,
            route.drive_hours,
            route.km,
            1 if route.estimated else 0,
            now_iso(),
        ),
    )


def estimate(origin: tuple[float, float], dest: tuple[float, float]) -> Route:
    """Great-circle fallback. Always marked estimated — the UI says so rather
    than presenting a guess as a measurement."""
    km = haversine_km(origin[0], origin[1], dest[0], dest[1])
    return Route(round(estimate_drive_hours(km), 3), round(km, 1), True)


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
            route = Route(round(seconds / 3600.0, 3), round(meters / METERS_PER_KM, 1), False)
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


def cached_place(name: str) -> tuple[float, float, str | None] | None:
    """(lat, lon, country) for a named city, from the cache or from listings we
    already hold. Sync, so scoring can call it without doing I/O.

    The country matters: cities are matched to the trip country they belong to,
    so naming Toronto on a US+Canada trip doesn't make it the anchor for US
    shows as well.
    """
    key = name.strip().lower()
    if not key:
        return None

    row = db.query_one("SELECT lat, lon, country FROM places WHERE query = ?", (key,))
    if row and row["lat"] is not None:
        return row["lat"], row["lon"], (row["country"] or None)

    # an event in that city is as good an answer as a geocoder
    row = db.query_one(
        "SELECT lat, lon, country FROM events WHERE lower(city) = ? "
        "AND lat IS NOT NULL LIMIT 1",
        (key,),
    )
    return (row["lat"], row["lon"], row["country"]) if row else None


async def resolve_place(
    name: str, country: str | None = None
) -> tuple[float, float, str | None] | None:
    """Cached-or-geocoded (lat, lon, country) for a city name."""
    hit = cached_place(name)
    if hit:
        return hit

    query = f"{name}, {country}" if country else name
    results = await geocode(query, limit=1)
    if not results:
        return None

    best = results[0]
    # the geocoder answers in alpha-3; everything else here speaks alpha-2
    from . import borders

    resolved = borders.alpha2_for(best.get("country") or "") or (country or None)
    remember(name, best["lat"], best["lon"], resolved)
    return best["lat"], best["lon"], resolved


def remember(name: str, lat: float, lon: float, country: str | None) -> None:
    """Cache a place by the name it was typed as. Scoring reads this
    synchronously, so anything the picker resolves is free at score time."""
    key = name.strip().lower()
    if not key:
        return
    db.execute(
        "INSERT INTO places(query, lat, lon, country, resolved_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(query) DO UPDATE SET lat=excluded.lat, lon=excluded.lon, "
        "country=excluded.country, resolved_at=excluded.resolved_at",
        (key, lat, lon, country, now_iso()),
    )


_PICKER_ENDPOINT_KEY = "ors_picker_endpoint"


async def _search_endpoint(params: dict) -> dict | None:
    """Autocomplete if this deployment has it, plain search otherwise.

    Autocomplete is the right endpoint for a picker — it matches prefixes, so
    "Barcel" finds Barcelona. But it isn't on every ORS deployment, and a
    missing path returns the same `None` as an empty result while still
    spending a call against a 2,000/day quota, once per host tried, on every
    keystroke. So the working endpoint is remembered, the same way the working
    host already is.

    Only recorded when the fallback actually answers, which rules out blaming
    the endpoint for what was really an exhausted quota.
    """
    known = db.get_meta(_PICKER_ENDPOINT_KEY)
    if known:
        return await _ors_get(known, params)

    payload = await _ors_get("/geocode/autocomplete", params)
    if payload is not None:
        db.set_meta(_PICKER_ENDPOINT_KEY, "/geocode/autocomplete")
        return payload

    payload = await _ors_get("/geocode/search", params)
    if payload is not None:
        log.info("openrouteservice: no autocomplete here, using /geocode/search")
        db.set_meta(_PICKER_ENDPOINT_KEY, "/geocode/search")
    return payload


async def search_cities(text: str, countries: list[str], limit: int = 8) -> list[dict]:
    """Cities only, inside the countries a trip is actually going to.

    Both narrowings matter for the picker: unrestricted, "Barcelona" offers a
    street and a venue named Barcelona, and a trip to Spain offers Barcelona,
    Venezuela. Results are cached as places, so picking one costs nothing later
    when scoring needs its coordinates.
    """
    if not (available() and len(text.strip()) >= 2):
        return []

    params: dict[str, object] = {
        "text": text.strip(),
        "size": limit,
        "layers": "locality,localadmin",
    }
    if countries:
        params["boundary.country"] = ",".join(c.upper() for c in countries)

    payload = await _search_endpoint(params)
    from . import borders

    results = []
    for feature in (payload or {}).get("features") or []:
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        props = feature.get("properties") or {}
        name = props.get("name")
        country = borders.alpha2_for(props.get("country_a") or "")
        if len(coords) < 2 or not name or not country:
            continue
        results.append(
            {
                "name": name,
                # "Lyon, Auvergne-Rhône-Alpes, France" — two Springfields need
                # telling apart, and the region is how you do it
                "label": props.get("label") or name,
                "country": country,
                "lat": float(coords[1]),
                "lon": float(coords[0]),
            }
        )
        remember(name, float(coords[1]), float(coords[0]), country)
    return results


async def geocode(text: str, limit: int = 5) -> list[dict]:
    """Forward geocode, so a trip can name a city rather than coordinates."""
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
