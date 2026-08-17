"""JamBase — gap-filler only, and treated as if every call costs money, because
it does.

Two facts from the Developer tier shape everything here:

  1. **Overage bills at $0.05/call instead of returning 429.** There is no
     protective error from the far end. Our own counter is the only thing
     between a bug and an invoice, so calls are reserved before dispatch, never
     retried, and capped at 500/month against a 1,000 free allowance — the gap
     is deliberate headroom.

  2. **External Identifiers are not included**, so MusicBrainz ids can't be used
     and this degrades to a name search. That removed the original reason to
     prefer it over Ticketmaster.

Hence its narrowed role: it is spent *only* on artists Ticketmaster returned
nothing for. Duplicating coverage we already have for free would be the worst
possible use of ~16 calls a day. Its future window is also 6 months, so queries
clamp to whichever is nearer, the horizon or that limit, rather than paying for
a question that cannot return an answer.

Disabled unless both the key and the base URL are configured — guessing at a
base URL costs real money.
"""

import logging
import os
from datetime import date, timedelta

from .. import http
from ..config import config
from ..util import today
from .base import Event, as_country, as_float, as_text

log = logging.getLogger("sondaro.jambase")

PROVIDER = "jambase"
FUTURE_WINDOW_DAYS = 183  # "Future Events: 6 Months" on the Developer tier
PER_PAGE = 50


def base_url() -> str:
    return os.getenv("JAMBASE_BASE_URL", "").strip().rstrip("/")


def available() -> bool:
    """Both the key and an explicit base URL. No default base: a wrong guess
    would spend billable calls discovering it was wrong."""
    return bool(config.jambase_api_key and base_url())


def window_end(requested_end: date) -> date:
    """Never ask beyond the plan's 6-month future window."""
    return min(requested_end, today() + timedelta(days=FUTURE_WINDOW_DAYS))


def parse_event(raw: dict) -> Event | None:
    event_id = str(raw.get("identifier") or raw.get("id") or "")
    stamp = str(raw.get("startDate") or raw.get("datetime") or "")
    if not event_id or not stamp:
        return None

    day, _, clock = stamp.partition("T")
    if not day:
        return None

    # schema.org endDate, same shape as startDate and just as optional. Like
    # the start, no absolute instant is taken from it: these stamps are not
    # reliably offset-bearing, and a made-up zone is worse than a floating one.
    end_stamp = str(raw.get("endDate") or "")
    end_day, _, end_clock = end_stamp.partition("T")

    venue = raw.get("location") or raw.get("venue") or {}
    address = venue.get("address") or {}
    geo = venue.get("geo") or {}

    performers = [
        name
        for p in (raw.get("performer") or raw.get("lineup") or [])
        if isinstance(p, dict) and (name := as_text(p.get("name")))
    ]
    title = as_text(raw.get("name")) or ""

    return Event(
        provider=PROVIDER,
        provider_event_id=event_id,
        artist_name=performers[0] if performers else title,
        title=title,
        date=day[:10],
        time=(clock[:5] or None),
        end_date=(end_day[:10] or None),
        end_time=(end_clock[:5] or None),
        # every one of these is a string *or* an object in JSON-LD, so none of
        # them may be taken at face value
        venue=as_text(venue.get("name")),
        city=as_text(address.get("addressLocality")),
        region=as_text(address.get("addressRegion")),
        country=as_country(address.get("addressCountry")),
        lat=as_float(geo.get("latitude")),
        lon=as_float(geo.get("longitude")),
        url=raw.get("url"),
        mbid=None,  # not available on this tier
        lineup=performers[1:],
    )


async def by_artist_name(name: str, start: date, end: date) -> list[Event]:
    """One artist, by name. Costs one billable call — callers must have already
    established that Ticketmaster has nothing."""
    if not available():
        return []

    clamped_end = window_end(end)
    if clamped_end < start:
        log.info("skipping %s: window is entirely beyond the 6-month limit", name)
        return []

    try:
        payload = await http.get_json(
            f"{base_url()}/events",
            params={
                "artistName": name,
                "eventDateFrom": start.isoformat(),
                "eventDateTo": clamped_end.isoformat(),
                "perPage": PER_PAGE,
            },
            # v3 takes a Bearer token. The old v1 API used ?apikey=, and their
            # docs now say explicitly that keys are not sent as query
            # parameters — which also keeps the key out of URLs, and therefore
            # out of logs and proxies.
            headers={"Authorization": f"Bearer {config.jambase_api_key}"},
            provider=PROVIDER,
        )
    except http.QuotaExhausted:
        log.warning("jambase monthly cap reached — skipping %s", name)
        return []

    if not payload:
        return []

    raw_events = payload.get("events") if isinstance(payload, dict) else payload
    if not isinstance(raw_events, list):
        return []

    events = []
    for raw in raw_events:
        parsed = parse_event(raw)
        if parsed:
            events.append(parsed)
    return events
