#!/usr/bin/env python3
"""Bake country borders into a read-only SQLite R*Tree.

Run once at image-build time. Countries do not move, so this is reference data
baked in, not a cache: nothing is parsed at startup, no polygon set sits in
memory, and the file never needs invalidating. Regenerating it is a rebuild,
which is the right cadence for data that changes every few decades.

`fetch_geojson` is the only function that touches the network, and it is
deliberately separate from `build` so tests can exercise the real builder
against inline geometry without ever reaching out.

`--world <path>` writes the trip maps' country shapes from the same file
instead. That one is run by hand and committed as `web/public/world.json`,
since the browser needs it and the web build has no Python.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from pathlib import Path
from typing import Any, Iterable

# Natural Earth 110m admin-0. ~5-10km accurate, which is noise against the
# 100-mile detour threshold this feeds.
SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_admin_0_countries.geojson"
)

SCHEMA = """
PRAGMA journal_mode=DELETE;

CREATE TABLE countries (
    code  TEXT PRIMARY KEY,   -- ISO 3166-1 alpha-2
    code3 TEXT,               -- alpha-3; Pelias geocoding answers in these
    name  TEXT NOT NULL
);
CREATE INDEX countries_code3 ON countries(code3);

CREATE TABLE segments (
    id      INTEGER PRIMARY KEY,
    country TEXT NOT NULL,
    lon1    REAL NOT NULL,
    lat1    REAL NOT NULL,
    lon2    REAL NOT NULL,
    lat2    REAL NOT NULL
);
CREATE INDEX segments_country ON segments(country);

-- x = longitude, y = latitude
CREATE VIRTUAL TABLE segment_bbox USING rtree(
    id, min_lon, max_lon, min_lat, max_lat
);
"""


def fetch_geojson(url: str = SOURCE_URL) -> dict[str, Any]:
    """The only networked function here. Never called from tests."""
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _rings(geometry: dict[str, Any]) -> Iterable[list[list[float]]]:
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Polygon":
        yield from coords
    elif kind == "MultiPolygon":
        for polygon in coords:
            yield from polygon


def _country_code(props: dict[str, Any]) -> str | None:
    """Natural Earth spells the ISO code differently across releases, and uses
    -99 for disputed or unrecognized territories."""
    for field in ("ISO_A2_EH", "ISO_A2", "iso_a2", "WB_A2"):
        value = props.get(field)
        if value and value not in ("-99", "-999"):
            return str(value).upper()
    return None


def _country_code3(props: dict[str, Any]) -> str | None:
    for field in ("ISO_A3_EH", "ISO_A3", "iso_a3", "ADM0_A3"):
        value = props.get(field)
        if value and value not in ("-99", "-999"):
            return str(value).upper()
    return None


def _country_name(props: dict[str, Any]) -> str:
    for field in ("NAME_EN", "NAME", "ADMIN", "name"):
        value = props.get(field)
        if value:
            return str(value)
    return "Unknown"


def build(geojson: dict[str, Any], out_path: str | Path) -> dict[str, int]:
    """Write the border index. Pure apart from the file it creates."""
    out = Path(out_path)
    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(out)
    conn.executescript(SCHEMA)

    countries: dict[str, tuple[str | None, str]] = {}
    segments: list[tuple[int, str, float, float, float, float]] = []
    boxes: list[tuple[int, float, float, float, float]] = []
    next_id = 1

    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        code = _country_code(props)
        if not code:
            continue
        countries.setdefault(code, (_country_code3(props), _country_name(props)))

        for ring in _rings(feature.get("geometry") or {}):
            previous = None
            for point in ring:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                current = (float(point[0]), float(point[1]))
                if previous is not None and current != previous:
                    lon1, lat1 = previous
                    lon2, lat2 = current
                    segments.append((next_id, code, lon1, lat1, lon2, lat2))
                    boxes.append(
                        (
                            next_id,
                            min(lon1, lon2),
                            max(lon1, lon2),
                            min(lat1, lat2),
                            max(lat1, lat2),
                        )
                    )
                    next_id += 1
                previous = current

    conn.executemany(
        "INSERT INTO countries(code, code3, name) VALUES(?,?,?)",
        [(code, code3, name) for code, (code3, name) in countries.items()],
    )
    conn.executemany(
        "INSERT INTO segments(id, country, lon1, lat1, lon2, lat2) VALUES(?,?,?,?,?,?)",
        segments,
    )
    conn.executemany(
        "INSERT INTO segment_bbox(id, min_lon, max_lon, min_lat, max_lat) "
        "VALUES(?,?,?,?,?)",
        boxes,
    )
    conn.commit()
    conn.execute("VACUUM")
    conn.close()

    return {"countries": len(countries), "segments": len(segments)}


# --- the map's country shapes ----------------------------------------------

# Two decimals is about a kilometer: finer than 110m geometry is anyway, and it
# roughly halves the file the browser downloads.
WORLD_PRECISION = 2


def _polygons(geometry: dict[str, Any]) -> Iterable[list]:
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Polygon":
        yield coords
    elif kind == "MultiPolygon":
        yield from coords


def _signed_area(ring: list[tuple[float, float]]) -> float:
    """Shoelace area in lon/lat. Negative is clockwise with north up."""
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:])) / 2


def _compact_ring(ring: list) -> list[tuple[float, float]] | None:
    """Rounded, with the points rounding merged dropped. None once too little
    is left to enclose anything."""
    out: list[tuple[float, float]] = []
    for point in ring:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        current = (
            round(float(point[0]), WORLD_PRECISION),
            round(float(point[1]), WORLD_PRECISION),
        )
        if not out or current != out[-1]:
            out.append(current)
    if out and out[0] != out[-1]:
        out.append(out[0])
    if len(out) < 4 or _signed_area(out) == 0:
        return None
    return out


def build_world(geojson: dict[str, Any], out_path: str | Path) -> dict[str, int]:
    """Write the map's country shapes as {alpha-2: [polygon, ...]}.

    Rings are wound the way d3-geo reads them: exteriors clockwise, holes the
    other way. GeoJSON winds them the opposite way, and d3 reads a backwards
    ring as everything *except* the country, so one would fill the globe.
    """
    world: dict[str, list] = {}
    points = 0

    for feature in geojson.get("features", []):
        code = _country_code(feature.get("properties") or {})
        if not code:
            continue
        for polygon in _polygons(feature.get("geometry") or {}):
            rings = []
            for index, ring in enumerate(polygon):
                compact = _compact_ring(ring)
                if compact is None:
                    if index == 0:
                        break  # no outline left, so its holes mean nothing
                    continue
                if (_signed_area(compact) < 0) != (index == 0):
                    compact.reverse()
                rings.append([list(point) for point in compact])
                points += len(compact)
            if rings:
                world.setdefault(code, []).append(rings)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(world, separators=(",", ":"), sort_keys=True))
    return {"countries": len(world), "points": points}


def main(argv: list[str]) -> int:
    if len(argv) > 2 and argv[1] == "--world":
        out_path = argv[2]
        print(f"fetching {SOURCE_URL}")
        stats = build_world(fetch_geojson(), out_path)
        size_kb = Path(out_path).stat().st_size / 1000
        print(
            f"wrote {out_path}: {stats['countries']} countries, "
            f"{stats['points']} points, {size_kb:.0f} KB"
        )
        return 0

    out_path = argv[1] if len(argv) > 1 else "borders.db"
    print(f"fetching {SOURCE_URL}")
    geojson = fetch_geojson()
    stats = build(geojson, out_path)
    size_mb = Path(out_path).stat().st_size / 1_000_000
    print(
        f"wrote {out_path}: {stats['countries']} countries, "
        f"{stats['segments']} segments, {size_mb:.1f} MB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
