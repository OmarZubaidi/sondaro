"""Border index: built from inline geometry, never downloaded.

`build_borders.fetch_geojson` is the only networked function in the builder and
it is never called here — these tests exercise the real `build()` against
hand-written polygons, so the index format and the query path are both covered
without a single byte crossing the wire.
"""

import json
import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import borders  # noqa: E402
from api.config import config  # noqa: E402
from api.geo import EARTH_RADIUS_KM  # noqa: E402
from scripts import build_borders  # noqa: E402

GENEVA = (46.2044, 6.1432)
BERLIN = (52.5200, 13.4050)

# A deliberately simplified France whose eastern edge sits at lon 6.10 near
# Geneva, so the expected distance is arithmetic we can verify by hand rather
# than a number copied from somewhere.
FRANCE_EAST_LON = 6.10

SAMPLE = {
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
        {
            # disputed territories carry -99 and must be skipped
            "properties": {"ISO_A2_EH": "-99", "NAME_EN": "Nowhere"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
            },
        },
    ]
}


@pytest.fixture
def index(tmp_path, monkeypatch):
    path = tmp_path / "borders.db"
    stats = build_borders.build(SAMPLE, path)
    monkeypatch.setattr(config, "borders_db", str(path))
    borders.reset()
    yield stats
    borders.reset()


def _brute_force_km(lat, lon, countries):
    """Independent implementation to check the R*Tree against."""
    import sqlite3

    conn = sqlite3.connect(config.borders_db)
    rows = conn.execute(
        "SELECT lat1, lon1, lat2, lon2 FROM segments WHERE country IN ({})".format(
            ",".join("?" for _ in countries)
        ),
        countries,
    ).fetchall()
    conn.close()
    return min(
        borders._point_to_segment_km(lat, lon, *row[:1] + row[1:2] + row[2:3] + row[3:4])
        for row in rows
    )


def test_build_skips_unrecognized_codes(index):
    assert index["countries"] == 2
    assert index["segments"] > 0


def test_geneva_is_a_short_hop_from_france(index):
    km = borders.distance_to_border(*GENEVA, ["FR"])

    # arithmetic we can check by hand: the eastern edge is a meridian at 6.10
    expected = (GENEVA[1] - FRANCE_EAST_LON) * math.cos(math.radians(GENEVA[0])) * (
        math.pi * EARTH_RADIUS_KM / 180.0
    )
    assert km == pytest.approx(expected, abs=0.1)
    assert km < 5  # "barely a detour", as specified


def test_berlin_is_not_a_detour(index):
    km = borders.distance_to_border(*BERLIN, ["FR"])
    assert km > 480


def test_multi_country_takes_the_nearest(index):
    # Barcelona sits inside Spain, so with both countries listed the answer
    # must come from the Spanish border, not the French one
    barcelona = (41.3874, 2.1686)
    both = borders.distance_to_border(*barcelona, ["FR", "ES"])
    france_only = borders.distance_to_border(*barcelona, ["FR"])
    assert both < france_only


def test_rtree_agrees_with_brute_force(index):
    """The index must not change the answer, only the work done to get it."""
    rng = random.Random(20260815)
    for _ in range(60):
        lat = rng.uniform(35.0, 55.0)
        lon = rng.uniform(-10.0, 20.0)
        indexed = borders.distance_to_border(lat, lon, ["FR"])
        brute = _brute_force_km(lat, lon, ["FR"])
        assert indexed == pytest.approx(brute, abs=0.8), f"disagreed at {lat},{lon}"


def test_unknown_country_returns_none_rather_than_guessing(index):
    assert borders.distance_to_border(*GENEVA, ["ZZ"]) is None
    assert borders.distance_to_border(*GENEVA, []) is None


def test_missing_index_degrades_instead_of_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "borders_db", str(tmp_path / "absent.db"))
    borders.reset()
    assert borders.available() is False
    assert borders.distance_to_border(*GENEVA, ["FR"]) is None
    assert borders.country_name("FR") == "FR"


def test_country_names_come_from_the_index(index):
    assert borders.country_name("FR") == "France"
    assert borders.country_name("es") == "Spain"
    assert [c["code"] for c in borders.known_countries()] == ["FR", "ES"]


# --------------------------------------------------------------------------
# the map's country shapes
# --------------------------------------------------------------------------


def _world(tmp_path, geojson):
    out = tmp_path / "world.json"
    stats = build_borders.build_world(geojson, out)
    return json.loads(out.read_text()), stats


def _area(ring):
    """Shoelace in lon/lat, written out again so the test doesn't trust the
    builder's own. Negative is clockwise with north up."""
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:])) / 2


def _country(code, *polygons):
    return {
        "properties": {"ISO_A2_EH": code},
        "geometry": {"type": "MultiPolygon", "coordinates": list(polygons)},
    }


def test_the_map_keys_its_shapes_by_two_letter_code(tmp_path):
    world, stats = _world(tmp_path, SAMPLE)

    # the -99 territory has no code a trip could name, so it isn't drawn
    assert sorted(world) == ["ES", "FR"]
    assert stats["countries"] == 2


def test_the_map_winds_rings_the_way_d3_reads_them(tmp_path):
    """GeoJSON's way round (exterior anticlockwise) would make d3 fill the
    whole globe except the country."""
    exterior = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]  # anticlockwise
    hole = [[2, 2], [2, 4], [4, 4], [4, 2], [2, 2]]  # clockwise
    world, _ = _world(tmp_path, {"features": [_country("ZA", [exterior, hole])]})

    outline, inner = world["ZA"][0]
    assert _area(outline) < 0
    assert _area(inner) > 0


def test_the_map_rounds_to_about_a_kilometer_and_drops_merged_points(tmp_path):
    ring = [[0.001, 0.0], [0.004, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0], [0.0, 0.0]]
    world, _ = _world(tmp_path, {"features": [_country("XX", [ring])]})

    outline = world["XX"][0][0]
    assert all(point == [round(v, 2) for v in point] for point in outline)
    assert all(a != b for a, b in zip(outline, outline[1:]))


def test_an_island_too_small_to_draw_is_left_out(tmp_path):
    speck = [[5.001, 5.001], [5.002, 5.001], [5.002, 5.002], [5.001, 5.001]]
    square = [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]
    world, _ = _world(
        tmp_path,
        {"features": [_country("AA", [square], [speck]), _country("BB", [speck])]},
    )

    assert len(world["AA"]) == 1
    assert "BB" not in world
