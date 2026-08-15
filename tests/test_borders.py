"""Border index: built from inline geometry, never downloaded.

`build_borders.fetch_geojson` is the only networked function in the builder and
it is never called here — these tests exercise the real `build()` against
hand-written polygons, so the index format and the query path are both covered
without a single byte crossing the wire.
"""

import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import borders  # noqa: E402
from api.config import config  # noqa: E402
from api.geo import EARTH_RADIUS_MILES  # noqa: E402
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


def _brute_force_miles(lat, lon, countries):
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
        borders._point_to_segment_miles(lat, lon, *row[:1] + row[1:2] + row[2:3] + row[3:4])
        for row in rows
    )


def test_build_skips_unrecognised_codes(index):
    assert index["countries"] == 2
    assert index["segments"] > 0


def test_geneva_is_a_short_hop_from_france(index):
    miles = borders.distance_to_border(*GENEVA, ["FR"])

    # arithmetic we can check by hand: the eastern edge is a meridian at 6.10
    expected = (GENEVA[1] - FRANCE_EAST_LON) * math.cos(math.radians(GENEVA[0])) * (
        math.pi * EARTH_RADIUS_MILES / 180.0
    )
    assert miles == pytest.approx(expected, abs=0.1)
    assert miles < 3  # "barely a detour", as specified


def test_berlin_is_not_a_detour(index):
    miles = borders.distance_to_border(*BERLIN, ["FR"])
    assert miles > 300


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
        brute = _brute_force_miles(lat, lon, ["FR"])
        assert indexed == pytest.approx(brute, abs=0.5), f"disagreed at {lat},{lon}"


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
