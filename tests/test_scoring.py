"""Scoring. Pure functions, so these are the cheapest tests in the suite and
the ones that pin the actual behaviour of the app.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import scoring  # noqa: E402

TUESDAY = date(2026, 9, 8)
SATURDAY = date(2026, 9, 12)

# hours from Home
SPRINGFIELD, NEARBY, FAIRVIEW, DC, MILLBROOK = 0.5, 1.3, 2.6, 4.4, 6.0


# --------------------------------------------------------------------------
# affinity
# --------------------------------------------------------------------------


# Shape of a real library: one runaway favourite, a handful of well-played
# artists, and a long tail. Normalising to the max squashes everything under
# the outlier, which is what the percentile exists to avoid.
REAL_LIBRARY = [114, 50, 46, 41, 36, 33, 19, 18, 17, 16] + [
    n for n in range(1, 37)
]


def test_the_ceiling_ignores_a_runaway_favourite():
    ceiling = scoring.affinity_ceiling(REAL_LIBRARY)

    assert ceiling < 114, "one outlier must not define the top of the scale"
    # the artists you genuinely love all count as favourites
    for plays in (114, 50, 46, 41):
        assert scoring.affinity(plays, ceiling) == 1.0


def test_normalising_to_the_max_would_have_compressed_the_scale():
    """Guards the actual regression: against the max, a 50-play favourite never
    reached the top of the scale and nothing cleared the alert threshold.

    Stated as a comparison rather than a number — the absolute value moves with
    LIBRARY_FLOOR, but the gap between the two ceilings is the whole point."""
    percentile = scoring.affinity_ceiling(REAL_LIBRARY)

    assert scoring.affinity(50, max(REAL_LIBRARY)) < 1.0
    assert scoring.affinity(50, percentile) == 1.0


def test_the_long_tail_still_ranks_below_the_favourites():
    """Raising the floor lifts the tail; it must not flatten it. Play counts
    still have to order the library or they mean nothing."""
    ceiling = scoring.affinity_ceiling(REAL_LIBRARY)

    assert scoring.affinity(1, ceiling) < scoring.affinity(5, ceiling)
    assert scoring.affinity(5, ceiling) < scoring.affinity(17, ceiling)
    assert scoring.affinity(17, ceiling) < scoring.affinity(41, ceiling)
    # and the spread stays wide enough to be a ranking, not a rounding error
    assert scoring.affinity(41, ceiling) - scoring.affinity(1, ceiling) > 0.3


def test_unlistened_artists_floor_rather_than_zero():
    """In Lidarr but never scrobbled still means you chose to follow them."""
    assert scoring.affinity(0, 100) == scoring.LIBRARY_FLOOR
    assert scoring.affinity(5, 0) == scoring.LIBRARY_FLOOR


def test_ceiling_of_an_empty_library_is_zero():
    assert scoring.affinity_ceiling([]) == 0
    assert scoring.affinity_ceiling([0, 0, 0]) == 0


def test_ceiling_survives_a_tiny_library():
    assert scoring.affinity_ceiling([7]) == 7
    assert scoring.affinity(7, scoring.affinity_ceiling([7])) == 1.0


def test_affinity_is_monotonic():
    ceiling = scoring.affinity_ceiling(list(range(1, 60)))
    values = [scoring.affinity(n, ceiling) for n in range(1, 60)]
    assert values == sorted(values)


# --------------------------------------------------------------------------
# reach
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hours,day,expected",
    [
        (SPRINGFIELD, TUESDAY, 1.00),
        (NEARBY, TUESDAY, 0.97),
        (FAIRVIEW, TUESDAY, 0.64),
        (DC, TUESDAY, 0.18),
        (MILLBROOK, TUESDAY, 0.06),
        (FAIRVIEW, SATURDAY, 0.90),
        (DC, SATURDAY, 0.52),
        (MILLBROOK, SATURDAY, 0.24),
    ],
)
def test_a_favourite_matches_the_calibration_table(hours, day, expected):
    assert scoring.reach_fit_home(hours, 1.0, day) == pytest.approx(expected, abs=0.01)


def test_a_weekend_justifies_a_longer_drive_than_a_weeknight():
    assert scoring.reach_fit_home(FAIRVIEW, 1.0, SATURDAY) > scoring.reach_fit_home(
        FAIRVIEW, 1.0, TUESDAY
    )


def test_liking_an_artist_more_extends_how_far_you_will_go():
    far = [scoring.reach_fit_home(FAIRVIEW, a, SATURDAY) for a in (0.3, 0.6, 1.0)]
    assert far == sorted(far)


# --------------------------------------------------------------------------
# trips
# --------------------------------------------------------------------------


def test_anywhere_in_a_visited_country_is_equally_in_play():
    assert scoring.reach_fit_trip(artist_affinity=0.3, in_visited_country=True) == 1.0


def test_naming_cities_never_drops_the_rest_of_the_country_below_the_floor():
    fit = scoring.reach_fit_trip(
        artist_affinity=0.3, in_visited_country=True, miles_to_named_city=9999
    )
    assert fit == pytest.approx(scoring.IN_COUNTRY_FLOOR, abs=0.01)


def test_just_over_a_border_is_barely_a_detour():
    assert scoring.reach_fit_trip(
        artist_affinity=0.6, in_visited_country=False, miles_to_border=7
    ) > 0.95


def test_far_outside_the_trip_is_not_a_detour():
    assert scoring.reach_fit_trip(
        artist_affinity=1.0, in_visited_country=False, miles_to_border=330
    ) < 0.05


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------


def test_strict_dates_are_all_or_nothing():
    start, end = date(2026, 9, 5), date(2026, 9, 20)
    assert scoring.date_fit(date(2026, 9, 10), start, end, strict=True) == 1.0
    assert scoring.date_fit(date(2026, 9, 21), start, end, strict=True) == 0.0


def test_flexible_dates_decay_to_the_floor_across_the_slack():
    start, end = date(2026, 9, 5), date(2026, 9, 20)
    just_after = scoring.date_fit(date(2026, 9, 21), start, end, flex_after=4)
    at_the_edge = scoring.date_fit(date(2026, 9, 24), start, end, flex_after=4)
    beyond = scoring.date_fit(date(2026, 9, 25), start, end, flex_after=4)

    assert 1.0 > just_after > at_the_edge
    assert at_the_edge == pytest.approx(scoring.FLEX_FLOOR, abs=0.01)
    assert beyond == 0.0
