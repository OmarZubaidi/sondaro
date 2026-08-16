"""Provider-neutral event record."""

from dataclasses import dataclass, field

from .. import borders


@dataclass
class Event:
    provider: str
    provider_event_id: str
    artist_name: str  # the act as this provider billed it
    date: str  # YYYY-MM-DD, venue-local
    title: str = ""
    time: str | None = None  # HH:MM, venue-local
    venue: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    lat: float | None = None
    lon: float | None = None
    url: str | None = None
    mbid: str | None = None  # only when the provider hands one over
    lineup: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.provider_event_id}"

    @property
    def where(self) -> str:
        return ", ".join(b for b in (self.venue, self.city, self.region, self.country) if b)

    def candidate_names(self) -> list[str]:
        """Every act this listing could be matched against."""
        names = [self.artist_name, *self.lineup]
        if self.title and self.title != self.artist_name:
            names.append(self.title)
        return [n for n in names if n]


def as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# schema.org's Country object, in the order of how much we'd like to find
_COUNTRY_KEYS = ("identifier", "alternateName", "name")


def as_country(value) -> str | None:
    """An alpha-2 code from whatever a provider called a country.

    schema.org's `addressCountry` is *either* a string or a Country object, and
    JamBase sends both. Everything downstream stores and compares alpha-2, so
    the shape is flattened here rather than at each use site — the last one to
    assume a string crashed the ingest after the billable call had been spent.
    """
    if isinstance(value, dict):
        value = next((value[k] for k in _COUNTRY_KEYS if value.get(k)), None)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    # alpha-2 and alpha-3 first; a spelled-out name is the fallback because it
    # needs a table lookup that codes mostly don't
    return borders.alpha2_for(text) or borders.alpha2_for_name(text)
