"""The iCalendar subscription.

One URL, added to a calendar app once, carrying **only the shows you've marked
as going**. That's the whole editorial decision here: a calendar is a record of
what you're doing, and filling it with suggestions turns a commitment you can
trust into a feed you learn to ignore. Suggestions live in the app, where
they're ranked and filterable and cost nothing to skim past.

Because everything in the feed is bought, every entry is CONFIRMED and OPAQUE —
it blocks your time, because it does.

Times are absolute wherever the provider gave us the instant. Floating local
time is the obvious-looking choice and it's wrong: it renders in whatever zone
the *reader* is in, so a Toronto show read from a phone at home shows up hours
out. Only listings whose doors are still TBA stay floating, since the
alternative is inventing a time.

The end works the same way, with one extra fallback: when a provider published
one it is used exactly, and otherwise the block is `SET_LENGTH` long. A
three-day festival that ends when it says it ends must not be a three-hour
block on its first evening.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .util import SET_LENGTH, parse_date, parse_iso

DEFAULT_DOORS = "19:30"
DEFAULT_LENGTH = SET_LENGTH


@dataclass
class Entry:
    """One show you hold a ticket for."""

    uid: str
    artist: str
    date: str  # YYYY-MM-DD, venue-local
    time: str | None = None  # HH:MM, venue-local
    starts_at: str | None = None  # the same moment, absolute, when known
    end_date: str | None = None  # YYYY-MM-DD, venue-local, when it differs
    end_time: str | None = None  # HH:MM, venue-local
    ends_at: str | None = None  # the same moment, absolute, when known
    where: str = ""
    url: str | None = None
    drive_hours: float | None = None
    estimated: bool = False
    tracks: int = 0  # how much of this artist is in Lidarr


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """RFC 5545 caps a line at 75 octets."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line

    chunks: list[str] = []
    start = 0
    while start < len(encoded):
        end = min(start + 74, len(encoded))
        # never split a multi-byte character
        while end > start and (encoded[end - 1] & 0xC0) == 0x80:
            end -= 1
        chunks.append(encoded[start:end].decode("utf-8"))
        start = end
    return "\r\n ".join(chunks)


def _hours(value: float) -> str:
    """Hours and minutes. Nobody reads 2.42 as a journey."""
    hours, minutes = divmod(round(value * 60), 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    return f"{hours}h" if hours else f"{minutes}m"


def _description(entry: Entry) -> str:
    """Two facts, both of which answer a question you'd have standing in front
    of the calendar entry: how long is the journey, and who is this again."""
    parts = []
    if entry.drive_hours is not None:
        prefix = "~" if entry.estimated else ""
        parts.append(f"{prefix}{_hours(entry.drive_hours)} drive")
    parts.append(f"{entry.tracks:,} song{'' if entry.tracks == 1 else 's'} in Lidarr")
    return " · ".join(parts)


def _local(day: str | None, clock: str, fallback: object = None) -> datetime | None:
    """A venue-local date and HH:MM as one naive datetime, or None."""
    parsed = parse_date(day) or fallback
    if parsed is None:
        return None
    try:
        return datetime.combine(parsed, datetime.strptime(clock, "%H:%M").time())
    except (ValueError, TypeError):
        return None


def _length(entry: Entry) -> timedelta:
    """How long the block runs.

    Measured as the gap between the two venue-local clocks rather than read off
    the end directly, which keeps it zone-free: both clocks are in the same
    zone whatever that zone is, so their difference is the true duration and
    can be added to an absolute start. Falls back to `DEFAULT_LENGTH` whenever
    the provider published no end, or published one that runs backwards.
    """
    if not entry.end_time:
        return DEFAULT_LENGTH

    start_local = _local(entry.date, entry.time or DEFAULT_DOORS)
    end_local = _local(entry.end_date, entry.end_time, fallback=parse_date(entry.date))
    if start_local is None or end_local is None:
        return DEFAULT_LENGTH

    # a curfew of 02:00 against doors at 23:00 is tomorrow morning, and only
    # says so when the provider didn't spell the date out
    if end_local <= start_local and not entry.end_date:
        end_local += timedelta(days=1)

    span = end_local - start_local
    return span if span > timedelta(0) else DEFAULT_LENGTH


def _times(entry: Entry) -> tuple[str, str] | None:
    """(DTSTART, DTEND) property lines, or None if the date is unusable."""
    length = _length(entry)

    instant = parse_iso(entry.starts_at)
    if instant is not None:
        start = instant.astimezone(timezone.utc)
        # a published absolute end beats deriving one, and is ignored if it
        # somehow lands before the doors
        finish = parse_iso(entry.ends_at)
        end = (
            finish.astimezone(timezone.utc)
            if finish is not None and finish > instant
            else start + length
        )
        return (
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
        )

    day = parse_date(entry.date)
    if day is None:
        return None

    # doors not announced: floating local time is the honest rendering of "that
    # evening, wherever you are", and beats inventing a zone
    clock = entry.time or DEFAULT_DOORS
    try:
        start_dt = datetime.combine(day, datetime.strptime(clock, "%H:%M").time())
    except ValueError:
        start_dt = datetime.combine(day, datetime.strptime(DEFAULT_DOORS, "%H:%M").time())
    end_dt = start_dt + length
    return (
        f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}",
    )


def build(entries: list[Entry], calendar_name: str = "Sondaro") -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//sondaro//homelab//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        _fold(f"X-WR-CALNAME:{_escape(calendar_name)}"),
        # marking a ticket as bought should show up in your calendar today, not
        # tomorrow, so ask for the tightest poll the clients honour
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for entry in entries:
        times = _times(entry)
        if times is None:
            continue
        start_line, end_line = times

        lines += [
            "BEGIN:VEVENT",
            _fold(f"UID:{entry.uid}@sondaro"),
            f"DTSTAMP:{stamp}",
            start_line,
            end_line,
            _fold(f"SUMMARY:{_escape(entry.artist)}"),
            _fold(f"LOCATION:{_escape(entry.where)}"),
            _fold(f"DESCRIPTION:{_escape(_description(entry))}"),
        ]
        if entry.url:
            lines.append(_fold(f"URL:{entry.url}"))
        lines += ["STATUS:CONFIRMED", "TRANSP:OPAQUE", "END:VEVENT"]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
