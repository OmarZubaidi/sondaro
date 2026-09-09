"""Distance from a point to the nearest border of a set of countries.

Reads the read-only `borders.db` baked at image-build time. The R*Tree turns
"how far is Geneva from France" into an indexed range search over a handful of
segments instead of a scan of every vertex on Earth.

Only distance is needed, not point-in-polygon: providers already tell us which
country a venue is in, and their own answer is more reliable than inferring it
from 110m geometry.
"""

import math
import os
import sqlite3
import threading
from functools import lru_cache

from .config import config
from .geo import EARTH_RADIUS_KM, KM_PER_DEGREE

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

# search radii to try, in km. Most answers land in the first ring; the last is
# a backstop for a point in the middle of an ocean.
_SEARCH_RINGS = (50.0, 200.0, 650.0, 2000.0, 6500.0)


class BordersUnavailable(RuntimeError):
    """The index is missing — the caller should degrade, not crash."""


def available() -> bool:
    return os.path.exists(config.borders_db)


def _connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            if not available():
                raise BordersUnavailable(f"no border index at {config.borders_db}")
            _conn = sqlite3.connect(
                f"file:{config.borders_db}?mode=ro", uri=True, check_same_thread=False
            )
            _conn.row_factory = sqlite3.Row
        return _conn


def reset() -> None:
    """Drop the handle. Used by tests that swap in a different index."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
    country_name.cache_clear()
    alpha2_for.cache_clear()


def _point_to_segment_km(
    lat: float, lon: float, lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Equirectangular projection around the query point.

    Segments at 110m resolution are short enough that treating them as straight
    lines on a local plane costs far less accuracy than the source data already
    does.
    """
    cos_lat = math.cos(math.radians(lat))
    scale = math.pi * EARTH_RADIUS_KM / 180.0

    px, py = 0.0, 0.0
    ax = (lon1 - lon) * cos_lat * scale
    ay = (lat1 - lat) * scale
    bx = (lon2 - lon) * cos_lat * scale
    by = (lat2 - lat) * scale

    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(ax - px, ay - py)

    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    nx, ny = ax + t * dx, ay + t * dy
    return math.hypot(px - nx, py - ny)


def _query_box(
    conn: sqlite3.Connection, countries: list[str], box: tuple[float, float, float, float]
) -> list[sqlite3.Row]:
    min_lon, max_lon, min_lat, max_lat = box
    placeholders = ",".join("?" for _ in countries)
    return conn.execute(
        f"""
        SELECT s.lat1, s.lon1, s.lat2, s.lon2
        FROM segment_bbox b
        JOIN segments s ON s.id = b.id
        WHERE b.max_lon >= ? AND b.min_lon <= ?
          AND b.max_lat >= ? AND b.min_lat <= ?
          AND s.country IN ({placeholders})
        """,
        (min_lon, max_lon, min_lat, max_lat, *countries),
    ).fetchall()


def _box_around(lat: float, lon: float, km: float) -> tuple[float, float, float, float]:
    lat_delta = km / KM_PER_DEGREE
    cos_lat = max(math.cos(math.radians(lat)), 0.01)
    lon_delta = km / (KM_PER_DEGREE * cos_lat)
    return (lon - lon_delta, lon + lon_delta, lat - lat_delta, lat + lat_delta)


def distance_to_border(lat: float, lon: float, countries: list[str]) -> float | None:
    """Kilometres from (lat, lon) to the nearest border of any listed country.

    None if the index is unavailable or the countries are unknown, so callers
    can degrade rather than fabricate a number.
    """
    codes = [c.strip().upper() for c in countries if c and c.strip()]
    if not codes:
        return None

    try:
        conn = _connect()
    except BordersUnavailable:
        return None

    for radius in _SEARCH_RINGS:
        rows = _query_box(conn, codes, _box_around(lat, lon, radius))
        if not rows:
            continue

        best = min(
            _point_to_segment_km(lat, lon, r["lat1"], r["lon1"], r["lat2"], r["lon2"])
            for r in rows
        )

        # A bbox search finds boxes that intersect the window, so the true
        # nearest segment can sit just outside it. Re-query at the distance we
        # actually found, with margin, and take the better answer.
        if best > radius * 0.5:
            confirm = _query_box(conn, codes, _box_around(lat, lon, best * 1.2 + 5.0))
            if confirm:
                best = min(
                    _point_to_segment_km(
                        lat, lon, r["lat1"], r["lon1"], r["lat2"], r["lon2"]
                    )
                    for r in confirm
                )
        return round(best, 2)

    return None


@lru_cache(maxsize=512)
def country_name(code: str) -> str:
    """Display name for an ISO-2 code, for the `not on your itinerary` flag."""
    if not code:
        return ""
    try:
        conn = _connect()
    except BordersUnavailable:
        return code.upper()
    row = conn.execute(
        "SELECT name FROM countries WHERE code = ?", (code.strip().upper(),)
    ).fetchone()
    return row["name"] if row else code.upper()


@lru_cache(maxsize=512)
def alpha2_for_name(name: str) -> str | None:
    """ISO-2 for a country's spelled-out name. schema.org lets a provider send
    `{"name": "United States"}` where a code was expected."""
    if not name:
        return None
    try:
        conn = _connect()
    except BordersUnavailable:
        return None
    row = conn.execute(
        "SELECT code FROM countries WHERE name = ? COLLATE NOCASE LIMIT 1",
        (name.strip(),),
    ).fetchone()
    return row["code"] if row else None


@lru_cache(maxsize=512)
def alpha2_for(code: str) -> str | None:
    """ISO-2 for either an ISO-2 or ISO-3 code. Pelias geocoding answers in
    alpha-3, while every event provider uses alpha-2."""
    if not code:
        return None
    value = code.strip().upper()
    try:
        conn = _connect()
    except BordersUnavailable:
        return value if len(value) == 2 else None

    row = conn.execute(
        "SELECT code FROM countries WHERE code = ? OR code3 = ? LIMIT 1", (value, value)
    ).fetchone()
    return row["code"] if row else (value if len(value) == 2 else None)


def known_countries() -> list[dict[str, str]]:
    """Every country in the index, for the trip form's country picker."""
    try:
        conn = _connect()
    except BordersUnavailable:
        return []
    return [
        {"code": row["code"], "name": row["name"]}
        for row in conn.execute("SELECT code, name FROM countries ORDER BY name")
    ]
