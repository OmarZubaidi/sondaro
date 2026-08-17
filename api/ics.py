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
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .util import parse_date, parse_iso

DEFAULT_DOORS = "19:30"
DEFAULT_LENGTH = timedelta(hours=3)


@dataclass
class Entry:
    """One show you hold a ticket for."""

    uid: str
    artist: str
    date: str  # YYYY-MM-DD, venue-local
    time: str | None = None  # HH:MM, venue-local
    starts_at: str | None = None  # the same moment, absolute, when known
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


def _times(entry: Entry) -> tuple[str, str] | None:
    """(DTSTART, DTEND) property lines, or None if the date is unusable."""
    instant = parse_iso(entry.starts_at)
    if instant is not None:
        start = instant.astimezone(timezone.utc)
        end = start + DEFAULT_LENGTH
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
    end_dt = start_dt + DEFAULT_LENGTH
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
