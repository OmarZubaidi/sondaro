"""ntfy push for newly announced shows.

Goes to the `sondaro` topic, gated by the alert threshold you set in the UI and
capped per run — the first fill discovers hundreds of shows at once and a
hundred pushes would train you to ignore the app permanently.

Health and degradation go to `services` instead, via `health.py`. Two topics
because they have completely different urgencies: gig alerts are frequent and
optional, infrastructure alerts are rare and actionable, and mixing them means
learning to ignore both.
"""

import logging
from email.header import Header

from . import db, http, scan, settings
from .config import config
from .util import now_iso, parse_date

log = logging.getLogger("sondaro.notify")


def _header_safe(text: str) -> str:
    """HTTP headers can't carry raw UTF-8, and artist names routinely have
    accents (Sigur Rós, Beyoncé, Mötley Crüe). Anything non-ASCII goes out
    RFC 2047 encoded, which ntfy decodes back for the notification title."""
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        return Header(text, "utf-8").encode()


async def send(
    topic: str,
    title: str,
    body: str,
    *,
    tags: str = "musical_note",
    click: str | None = None,
    priority: str = "default",
) -> bool:
    endpoint = config.ntfy_endpoint(topic)
    if not endpoint:
        return False

    headers = {"Title": _header_safe(title), "Tags": tags, "Priority": priority}
    if config.ntfy_token:
        headers["Authorization"] = f"Bearer {config.ntfy_token}"
    if click:
        headers["Click"] = click

    return await http.post(endpoint, body.encode("utf-8"), headers)


def _pretty(day: str) -> str:
    parsed = parse_date(day)
    return parsed.strftime("%a %-d %b") if parsed else day


async def announce_new_shows() -> int:
    """Push shows we haven't pushed before, best first."""
    if settings.alerts_muted():
        log.info("alerts muted until %s", settings.get("mute_until"))
        return 0

    threshold = settings.get("notify_min_score")
    cap = settings.get("notify_max_per_run")

    already = {row["event_id"] for row in db.query("SELECT event_id FROM notified")}
    candidates = [
        c
        for c in scan.home_candidates()
        if c.event.id not in already and c.total >= threshold
    ]
    if not candidates:
        return 0

    candidates.sort(key=lambda c: -c.total)
    sent = 0

    for candidate in candidates[:cap]:
        event = candidate.event
        drive = candidate.score.drive_hours
        lines = [_pretty(event.date) + (f" · {event.time}" if event.time else "")]
        if event.where:
            lines.append(event.where)
        if drive is not None:
            estimate = " (est.)" if "estimated drive time" in candidate.score.flags else ""
            lines.append(f"{drive:.1f}h drive{estimate}")
        lines.append(" · ".join(candidate.score.reasons))

        ok = await send(
            config.ntfy_topic_alerts,
            title=f"{candidate.artist.name} · {event.city or 'nearby'}",
            body="\n".join(lines),
            click=event.url,
            priority="high" if candidate.total >= 0.7 else "default",
        )
        if ok:
            sent += 1

    overflow = len(candidates) - cap
    if overflow > 0:
        await send(
            config.ntfy_topic_alerts,
            title="More shows found",
            body=f"{overflow} further matches above your threshold — open Sondaro for the rest.",
            tags="mag",
        )

    # mark everything considered, not just what we pushed, so the overflow
    # doesn't re-announce itself on the next sweep
    db.executemany(
        "INSERT INTO notified(event_id, sent_at) VALUES(?, ?) "
        "ON CONFLICT(event_id) DO NOTHING",
        [(c.event.id, now_iso()) for c in candidates],
    )
    log.info("announced %d shows (%d suppressed by the per-run cap)", sent, max(overflow, 0))
    return sent
