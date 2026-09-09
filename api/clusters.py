"""Finding the trip-shaped clumps in a pile of dates.

Pure functions, no I/O — testable against a table of dates and coordinates.

The question this answers is "when are several of my favorites in the same
part of the world at once", which is a question about *distance*, not about
borders. Grouping by country gets it wrong in both directions: Boston and Los
Angeles are one country and nowhere near each other, while Cologne and
Amsterdam are two countries and a two-hour train apart. So dates cluster on
proximity to the group's center, and administrative names are used only to
label the result.

Single-link chaining is the trap here. With a 650km link and nothing else, a
dense US tour chains Boston to New York to Chicago to Denver to LA and calls it
one trip. Measuring against the running centroid instead bounds a cluster at
roughly twice the radius, which keeps it to somewhere you could actually base
yourself for a week.
"""

from dataclasses import dataclass, field
from datetime import date

from .geo import haversine_km

# A date joins a cluster when it is within this many days of the span the
# cluster already covers. Ten days apart in the same place is still one trip you
# could stretch to cover, so the window has to be at least that.
CLUSTER_DAYS = 12

# ...and within this far of the cluster's center. Berlin to Munich is 500km,
# Amsterdam to Cologne 240, Boston to New York 300 — all one trip. Boston to
# Chicago is 1,370, which is not.
CLUSTER_KM = 650.0

# Countries whose own name is too coarse to locate a cluster inside. For these
# the region is the label — "MA + NY" places a cluster, "United States" does
# not. Everywhere else the country is both smaller and better known than its
# subdivisions, so "Germany" beats "Bayern".
REGION_LABELED = frozenset({"US"})


@dataclass(frozen=True)
class Place:
    """One place a cluster covers.

    Kept as country plus optional region rather than a finished string: a bare
    two-letter label is ambiguous in exactly the case this exists for — `MA` is
    Massachusetts here and Morocco in ISO-3166 — so naming is left to the
    caller that can tell them apart.
    """

    country: str
    region: str | None = None


@dataclass
class Dated:
    """The minimum a date needs to be clustered. `ref` is handed back untouched."""

    day: date
    lat: float | None
    lon: float | None
    country: str | None = None
    region: str | None = None
    ref: object = None


@dataclass
class Cluster:
    items: list[Dated] = field(default_factory=list)
    _lat: float = 0.0
    _lon: float = 0.0

    @property
    def start(self) -> date:
        return self.items[0].day

    @property
    def end(self) -> date:
        return max(item.day for item in self.items)

    @property
    def center(self) -> tuple[float, float]:
        return self._lat, self._lon

    def add(self, item: Dated) -> None:
        """Append and re-center. Placeable items move the centroid; the rest
        ride along on the date window alone."""
        self.items.append(item)
        if item.lat is None or item.lon is None:
            return
        placed = [i for i in self.items if i.lat is not None and i.lon is not None]
        self._lat = sum(i.lat for i in placed) / len(placed)
        self._lon = sum(i.lon for i in placed) / len(placed)

    def accepts(self, item: Dated, days: int, km: float) -> bool:
        if (item.day - self.end).days > days:
            return False
        if item.lat is None or item.lon is None:
            # Nothing to measure. Keeping it with whatever it is closest to in
            # time beats inventing a location for it or dropping it.
            return True
        if not any(i.lat is not None for i in self.items):
            return True
        return haversine_km(item.lat, item.lon, self._lat, self._lon) <= km

    def places(self) -> list[Place]:
        """Distinct places, in the order they first appear."""
        out: list[Place] = []
        for item in self.items:
            place = _place_of(item)
            if place and place not in out:
                out.append(place)
        return out


def _place_of(item: Dated) -> Place | None:
    country = (item.country or "").upper()
    if not country:
        return None
    if country in REGION_LABELED and item.region:
        return Place(country, item.region)
    return Place(country)


def build(
    items: list[Dated], *, days: int = CLUSTER_DAYS, km: float = CLUSTER_KM
) -> list[Cluster]:
    """Group dates into trips, in chronological order.

    A date joins the *nearest* open cluster it qualifies for rather than the
    first, so two tours running in parallel through different regions don't
    swallow each other's dates on a coin toss.

    `days` and `km` are how much of a trip you're willing to make of it, and
    the UI drives them — the honest answer differs between someone who'll take
    a fortnight across three countries and someone with a long weekend.
    """
    clusters: list[Cluster] = []

    for item in sorted(items, key=lambda i: (i.day, i.country or "", i.region or "")):
        best: Cluster | None = None
        nearest = float("inf")

        for cluster in clusters:
            if not cluster.accepts(item, days, km):
                continue
            if item.lat is None or item.lon is None:
                best = cluster
                break
            # deliberately not named `km`: that is the radius, and shadowing it
            # here silently replaced the threshold with the last distance measured
            distance = haversine_km(item.lat, item.lon, *cluster.center)
            if distance < nearest:
                best, nearest = cluster, distance

        if best is None:
            best = Cluster()
            clusters.append(best)
        best.add(item)

    return sorted(clusters, key=lambda c: (c.start, c.end))
