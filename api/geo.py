"""Geohash encoding (Ticketmaster's Discovery API wants one) and distance.

Everything here is metric. Distance used to be carried in miles and converted at
the edges, which is how a radius parameter ended up shadowed by a variable
holding a distance — one unit, everywhere, removes that whole class of mistake.
"""

import math

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

EARTH_RADIUS_KM = 6371.0
# crow-flies to road multiplier, used only when routing is unavailable
ROAD_FACTOR = 1.25
FALLBACK_KMH = 88.5
# one degree of latitude, near enough anywhere
KM_PER_DEGREE = 111.0


def geohash(lat: float, lon: float, precision: int = 9) -> str:
    lat_range, lon_range = [-90.0, 90.0], [-180.0, 180.0]
    out: list[str] = []
    bits = bit = 0
    even = True

    while len(out) < precision:
        if even:
            mid = (lon_range[0] + lon_range[1]) / 2
            if lon > mid:
                bits = (bits << 1) | 1
                lon_range[0] = mid
            else:
                bits <<= 1
                lon_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat > mid:
                bits = (bits << 1) | 1
                lat_range[0] = mid
            else:
                bits <<= 1
                lat_range[1] = mid
        even = not even
        bit += 1
        if bit == 5:
            out.append(_BASE32[bits])
            bits = bit = 0

    return "".join(out)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    # clamp: floating point can nudge `a` a hair above 1 for antipodal points
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(a, 1.0)))


def estimate_drive_hours(km: float) -> float:
    """Used when OpenRouteService is unconfigured or down.

    Callers must mark results derived from this as estimated — the UI says so
    explicitly rather than presenting a guess as a measurement.
    """
    return (km * ROAD_FACTOR) / FALLBACK_KMH


def bounding_box(lat: float, lon: float, km: float) -> tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lon, max_lon) — a cheap SQL prefilter before haversine."""
    lat_delta = km / KM_PER_DEGREE
    # longitude degrees shrink toward the poles; guard the cos at high latitude
    cos_lat = max(math.cos(math.radians(lat)), 0.01)
    lon_delta = km / (KM_PER_DEGREE * cos_lat)
    return (
        max(lat - lat_delta, -90.0),
        min(lat + lat_delta, 90.0),
        max(lon - lon_delta, -180.0),
        min(lon + lon_delta, 180.0),
    )
