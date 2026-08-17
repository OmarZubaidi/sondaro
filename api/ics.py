"""iCalendar feeds.

Format-neutral by design: these are subscribe URLs that work in Google Calendar,
Outlook, Fastmail, Thunderbird or anything else that speaks RFC 5545. Both
accept `?min_score=` so you can subscribe to only what's worth your attention
without changing what the app itself shows.
"""

from datetime import datetime, timedelta, timezone

from .util import parse_date

DEFAULT_DOORS = "19:30"
DEFAULT_LENGTH = timedelta(hours=3)


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


def build(candidates, calendar_name: str, purchased: set[str] | None = None) -> str:
    """`candidates` are `scan.Candidate`s, already filtered by the caller.

    A show you hold a ticket for is a real commitment; everything else is a
    suggestion. RFC 5545 has words for exactly that distinction, and calendar
    apps grey out a TENTATIVE event, so the two don't look alike at a glance.
    """
    purchased = purchased or set()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//sondaro//homelab//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        _fold(f"X-WR-CALNAME:{_escape(calendar_name)}"),
        "X-PUBLISHED-TTL:PT12H",
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for candidate in candidates:
        event = candidate.event
        day = parse_date(event.date)
        if not day:
            continue

        clock = event.time or DEFAULT_DOORS
        try:
            start_dt = datetime.combine(day, datetime.strptime(clock, "%H:%M").time())
        except ValueError:
            start_dt = datetime.combine(day, datetime.strptime(DEFAULT_DOORS, "%H:%M").time())
        end_dt = start_dt + DEFAULT_LENGTH

        description = []
        if event.id in purchased:
            description.append("ticket bought")
        if candidate.score.drive_hours is not None:
            estimated = "estimated " if "estimated drive time" in candidate.score.flags else ""
            description.append(f"{candidate.score.drive_hours:.1f}h {estimated}drive")
        description.append(f"score {candidate.score.total:.2f}")
        description.extend(candidate.score.reasons)
        description.extend(candidate.score.flags)
        if event.url:
            description.append(event.url)

        lines += [
            "BEGIN:VEVENT",
            _fold(f"UID:{event.id}@sondaro"),
            f"DTSTAMP:{stamp}",
            # floating local time: doors are 8pm wherever the venue is, and
            # pinning a timezone would shift a show by hours on a trip
            f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}",
            _fold(f"SUMMARY:{_escape(candidate.artist.name)}"),
            _fold(f"LOCATION:{_escape(event.where)}"),
            _fold(f"DESCRIPTION:{_escape(' — '.join(description))}"),
        ]
        if event.url:
            lines.append(_fold(f"URL:{event.url}"))
        held = event.id in purchased
        lines += [
            f"STATUS:{'CONFIRMED' if held else 'TENTATIVE'}",
            f"TRANSP:{'OPAQUE' if held else 'TRANSPARENT'}",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
