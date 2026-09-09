"""Finding the trip-shaped clumps in a pile of dates.

The cases that matter are the two ways a naive grouping gets it wrong: a
country is not a place (Boston and Los Angeles), and a border is not a
distance (Cologne and Amsterdam). Both are asserted here against real
coordinates rather than through the API.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import clusters  # noqa: E402

DAY = date(2026, 10, 5)

CITIES = {
    "Berlin": (52.5200, 13.4050, "DE", None),
    "Munich": (48.1351, 11.5820, "DE", None),
    "Cologne": (50.9375, 6.9603, "DE", None),
    "Amsterdam": (52.3676, 4.9041, "NL", None),
    "Lisbon": (38.7223, -9.1393, "PT", None),
    "Tokyo": (35.6762, 139.6503, "JP", None),
    "Boston": (42.3601, -71.0589, "US", "MA"),
    "New York": (40.7128, -74.0060, "US", "NY"),
    "Los Angeles": (34.0522, -118.2437, "US", "CA"),
    "Chicago": (41.8781, -87.6298, "US", "IL"),
    "Denver": (39.7392, -104.9903, "US", "CO"),
}


def at(city: str, offset: int = 0) -> clusters.Dated:
    lat, lon, country, region = CITIES[city]
    return clusters.Dated(
        day=DAY + timedelta(days=offset),
        lat=lat,
        lon=lon,
        country=country,
        region=region,
        ref=f"{city}+{offset}",
    )


def grouped(*items: clusters.Dated) -> list[set[str]]:
    """Each cluster as the set of cities in it, so assertions read as places."""
    return [
        {str(item.ref).split("+")[0] for item in cluster.items}
        for cluster in clusters.build(list(items))
    ]


def test_one_country_is_not_one_place():
    """The correction that prompted distance clustering: these are both the US
    and 4,200km apart, so they are not a trip."""
    found = grouped(at("Boston"), at("Los Angeles"))

    # they fall on the same day, so the order between them carries no meaning
    assert len(found) == 2
    assert {"Boston"} in found
    assert {"Los Angeles"} in found


def test_two_countries_can_be_one_place():
    """Cologne to Amsterdam is 240km and a border. It is one trip."""
    assert grouped(at("Cologne"), at("Amsterdam", 2)) == [{"Cologne", "Amsterdam"}]


def test_ten_days_apart_in_the_same_place_still_clusters():
    assert grouped(at("Berlin"), at("Munich", 10)) == [{"Berlin", "Munich"}]


def test_far_enough_apart_in_time_does_not():
    assert grouped(at("Berlin"), at("Munich", 40)) == [{"Berlin"}, {"Munich"}]


def test_a_dense_tour_does_not_chain_across_a_continent():
    """Single-link clustering would walk Boston -> New York -> Chicago ->
    Denver -> LA in ~600km hops and call the whole country one trip. Measuring
    from the running centroid is what stops it."""
    found = grouped(
        at("Boston"),
        at("New York", 2),
        at("Chicago", 4),
        at("Denver", 6),
        at("Los Angeles", 8),
    )

    assert {"Boston", "New York"} in found
    assert not any({"Boston", "Los Angeles"} <= cluster for cluster in found)
    assert len(found) > 1


def test_clusters_come_back_in_date_order():
    found = clusters.build([at("Tokyo", 20), at("Berlin"), at("Lisbon", 60)])

    assert [cluster.start for cluster in found] == [
        DAY,
        DAY + timedelta(days=20),
        DAY + timedelta(days=60),
    ]


def test_a_date_joins_the_nearest_open_cluster_not_the_first():
    """Two tours running in parallel. Munich belongs with Berlin, not with the
    Lisbon cluster that happened to open first."""
    found = grouped(at("Lisbon"), at("Berlin", 1), at("Munich", 2))

    assert {"Berlin", "Munich"} in found
    assert {"Lisbon"} in found


def test_the_us_is_labeled_by_state():
    found = clusters.build([at("Boston"), at("New York", 2)])

    assert found[0].places() == [
        clusters.Place("US", "MA"),
        clusters.Place("US", "NY"),
    ]


def test_everywhere_else_is_labeled_by_country():
    """"Bayern" locates a cluster worse than "Germany" does."""
    found = clusters.build([at("Cologne"), at("Amsterdam", 2)])

    assert found[0].places() == [clusters.Place("DE"), clusters.Place("NL")]


def test_a_region_code_stays_distinguishable_from_a_country_code():
    """MA is Massachusetts here and Morocco in ISO-3166. The place carries its
    country so whoever renders it can never confuse the two."""
    place = clusters.build([at("Boston")])[0].places()[0]

    assert place == clusters.Place(country="US", region="MA")


def test_an_unplaceable_date_rides_along_on_time_alone():
    """A listing with no coordinates must not be dropped or given a location we
    made up."""
    homeless = clusters.Dated(day=DAY + timedelta(days=1), lat=None, lon=None, ref="?")

    found = clusters.build([at("Berlin"), homeless])

    assert len(found) == 1
    assert "?" in {str(item.ref) for item in found[0].items}


def test_the_radius_still_applies_after_the_first_measurement():
    """Regression. The loop's own distance variable was named after the radius
    parameter, which shadowed it — so from the first comparison onward the
    threshold became whatever distance had just been measured, and passing a
    different radius changed nothing. Two dates never show it; a list does.
    """
    spread = [
        at("Boston"),
        at("New York", 2),
        at("Chicago", 4),
        at("Denver", 6),
        at("Los Angeles", 8),
    ]

    assert len(clusters.build(spread, days=60, km=5000)) == 1
    # 150 rather than 350: Boston to New York is 306km, and a radius that
    # admits it would be testing the wrong thing
    assert len(clusters.build(spread, days=60, km=150)) == 5


def test_a_tighter_window_splits_what_a_looser_one_joined():
    pair = [at("Berlin"), at("Munich", 10)]

    assert len(clusters.build(pair, days=12)) == 1
    assert len(clusters.build(pair, days=5)) == 2


def test_nothing_in_means_nothing_out():
    assert clusters.build([]) == []


def test_the_span_covers_every_date_in_the_cluster():
    found = clusters.build([at("Berlin", 4), at("Munich"), at("Cologne", 2)])

    assert found[0].start == DAY
    assert found[0].end == DAY + timedelta(days=4)
