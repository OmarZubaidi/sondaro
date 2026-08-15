"""Provider-neutral event record."""

from dataclasses import dataclass, field


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
