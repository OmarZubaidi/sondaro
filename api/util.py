"""Small shared helpers. Time is centralised here so nothing reaches for a
naive `datetime.utcnow()` — every stored timestamp is timezone-aware UTC, and
every user-facing date is rendered in the configured local zone.
"""

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_UTC = timezone.utc

# How long a show runs when nobody has said. Providers publish an end for
# festivals and almost never for a club night, so this is the assumption behind
# both the calendar block and the end time on a card — one number, in one
# place, so the two can never disagree.
SET_LENGTH = timedelta(hours=3)


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


def shift_clock(clock: str | None, delta: timedelta) -> tuple[str, int] | None:
    """`("22:30", 0)` — an HH:MM clock moved by `delta`, plus how many days it
    rolled over. None when the clock is missing or unparseable.

    Deliberately zone-free: a set is the same three hours long whatever the
    venue's offset, and adding them needs no timezone. The rollover count is
    what stops a 23:00 doors quietly ending at 02:00 the same morning.
    """
    try:
        base = datetime.strptime((clock or "").strip(), "%H:%M")
    except (ValueError, TypeError):
        return None
    moved = base + delta
    return moved.strftime("%H:%M"), (moved.date() - base.date()).days


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
