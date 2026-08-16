"""Small shared helpers. Time is centralised here so nothing reaches for a
naive `datetime.utcnow()` — every stored timestamp is timezone-aware UTC, and
every user-facing date is rendered in the configured local zone.
"""

from datetime import date, datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_UTC = timezone.utc


@lru_cache(maxsize=8)
def known_timezone(name: str) -> ZoneInfo | None:
    """The zone, or None if this machine has never heard of it."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def local_tz() -> ZoneInfo:
    """The home timezone, which travels with the home location rather than
    being configured separately and left behind.

    `settings` is imported lazily because it imports this module.
    """
    from . import settings

    try:
        stored = str(settings.get("home_tz") or "")
    except Exception:  # noqa: BLE001 - time must work before the db does
        stored = ""

    return known_timezone(stored) or ZoneInfo("UTC")


def now() -> datetime:
    return datetime.now(local_tz())


def today() -> date:
    return now().date()


def now_iso() -> str:
    return datetime.now(_UTC).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_UTC)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except (ValueError, AttributeError):
        return None


def month_key(moment: datetime | None = None) -> str:
    """`2026-08` — the bucket JamBase's monthly quota is counted in."""
    stamp = moment or datetime.now(_UTC)
    return stamp.strftime("%Y-%m")


def day_key(moment: datetime | None = None) -> str:
    stamp = moment or datetime.now(_UTC)
    return stamp.strftime("%Y-%m-%d")
