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
    # the same moment as an absolute instant, when the provider hands one over.
    # Only this can be put in a calendar without guessing the venue's zone.
    starts_at: str | None = None  # ISO 8601 with an offset
    # When it's over, in the same three shapes. Mostly absent — a promoter
    # publishes an end for a festival and rarely for a club night — so an
    # unset end means "unknown", never "same evening".
    end_date: str | None = None  # YYYY-MM-DD, venue-local; a later day for a festival
    end_time: str | None = None  # HH:MM, venue-local
    ends_at: str | None = None  # ISO 8601 with an offset
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
        """Every act this listing could be matched against. Filtered to real
        strings: matching normalises these, and a provider that hands over a
        JSON-LD object instead would fail the whole listing there."""
        names = [self.artist_name, *self.lineup]
        if self.title and self.title != self.artist_name:
            names.append(self.title)
        return [n for n in names if n and isinstance(n, str)]


def as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# schema.org names a thing with any of these, in the order we'd rather have
_NAME_KEYS = ("identifier", "alternateName", "name")


def as_text(value) -> str | None:
    """A plain string from a schema.org field that may be a string or an object.

    Every addressable field in JSON-LD has this shape: `addressRegion` is
    "KS" or `{"@type": "State", "name": "Kansas"}`, and the same goes
    for locality, country and venue name. A provider that assumes the string
    form works right up until the listing where it doesn't.
    """
    if isinstance(value, dict):
        value = next((value[k] for k in _NAME_KEYS if isinstance(value.get(k), str)), None)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def as_country(value) -> str | None:
    """An alpha-2 code from whatever a provider called a country.

    Everything downstream stores and compares alpha-2, so the shape is
    flattened here rather than at each use site.
    """
    text = as_text(value)
    if not text:
        return None
    # alpha-2 and alpha-3 first; a spelled-out name is the fallback because it
    # needs a table lookup that codes mostly don't
    return borders.alpha2_for(text) or borders.alpha2_for_name(text)
