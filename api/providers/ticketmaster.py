"""Ticketmaster Discovery — the primary provider and the only one that sweeps.

Two access patterns:

  sweep()     every music event in a geography and date window. Cheap per event
              and blind to who you like, so it finds artists a per-artist lookup
              would never think to ask about. Deep paging is capped at 1000
              results, so callers chunk by time and this module halves the
              window and retries when a chunk hits that ceiling — silently
              truncating would look identical to "there's nothing on".

  by_artist() precise lookup via a resolved attraction id, for the top of the
              library and for anywhere a sweep can't reach (a whole country, or
              worldwide when hunting for cross-border detours).
"""

import logging
from datetime import date, timedelta

from .. import db, http
from ..config import config
from ..geo import geohash
from ..match import normalize
from ..util import now_iso
from .base import Event, as_float, as_text

log = logging.getLogger("sondaro.ticketmaster")

BASE = "https://app.ticketmaster.com/discovery/v2"
PAGE_SIZE = 200
MAX_PAGES = 5  # Discovery refuses page * size > 1000
PROVIDER = "ticketmaster"


def available() -> bool:
    return bool(config.ticketmaster_api_key)


def _iso(day: date, end: bool = False) -> str:
    return f"{day.isoformat()}T{'23:59:59' if end else '00:00:00'}Z"


def _end(dates: dict) -> tuple[str | None, str | None, str | None]:
    """(end_date, end_time, ends_at) from `dates.end`, all None when absent.

    Discovery carries an end for multi-day runs and for anything the promoter
    bothered to state a curfew for; most listings have none at all. It also
    sets `noSpecificTime` when the block is a whole day rather than a time,
    which is a date masquerading as an end and no use as one.
    """
    end = dates.get("end") or {}
    if not end or end.get("noSpecificTime"):
        return None, None, None
    clock = (end.get("localTime") or "")[:5] or None
    if not clock:
        return None, None, None
    return as_text(end.get("localDate")), clock, as_text(end.get("dateTime"))


def parse_event(raw: dict) -> Event | None:
    event_id = raw.get("id")
    dates = raw.get("dates") or {}
    start = dates.get("start") or {}
    day = start.get("localDate")
    if not event_id or not day:
        return None

    end_date, end_time, ends_at = _end(dates)

    embedded = raw.get("_embedded") or {}
    venues = embedded.get("venues") or []
    venue = venues[0] if venues else {}
    location = venue.get("location") or {}

    attractions = embedded.get("attractions") or []
    headliner = attractions[0] if attractions else {}

    # Discovery sometimes carries a MusicBrainz id, which beats name matching
    mbid = None
    for link in (headliner.get("externalLinks") or {}).get("musicbrainz") or []:
        if link.get("id"):
            mbid = link["id"]
            break

    return Event(
        provider=PROVIDER,
        provider_event_id=event_id,
        artist_name=headliner.get("name") or raw.get("name") or "",
        title=raw.get("name") or "",
        date=day,
        time=(start.get("localTime") or "")[:5] or None,
        # Discovery hands over the absolute instant alongside the venue-local
        # clock, and omits it when the time is still TBA. Taking it means the
        # calendar never has to guess a venue's timezone.
        starts_at=as_text(start.get("dateTime")),
        end_date=end_date,
        end_time=end_time,
        ends_at=ends_at,
        venue=venue.get("name"),
        city=(venue.get("city") or {}).get("name"),
        region=(venue.get("state") or {}).get("stateCode")
        or (venue.get("state") or {}).get("name"),
        country=(venue.get("country") or {}).get("countryCode"),
        lat=as_float(location.get("latitude")),
        lon=as_float(location.get("longitude")),
        url=raw.get("url"),
        mbid=mbid,
        lineup=[a.get("name") for a in attractions[1:] if a.get("name")],
    )


async def _page_through(params: dict) -> tuple[list[Event], bool]:
    """Returns (events, truncated). truncated means results were cut off."""
    events: list[Event] = []
    truncated = False
    page = 0

    while page < MAX_PAGES:
        payload = await http.get_json(
            f"{BASE}/events.json",
            params={
                **params,
                "apikey": config.ticketmaster_api_key,
                "size": PAGE_SIZE,
                "page": page,
            },
            provider=PROVIDER,
        )
        if not payload:
            break

        for raw in ((payload.get("_embedded") or {}).get("events")) or []:
            parsed = parse_event(raw)
            if parsed:
                events.append(parsed)

        total_pages = (payload.get("page") or {}).get("totalPages") or 0
        page += 1
        if page >= total_pages:
            break
        if page >= MAX_PAGES and total_pages > MAX_PAGES:
            truncated = True

    return events, truncated


async def sweep(
    start: date,
    end: date,
    *,
    country: str | None = None,
    city: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
    chunk_days: int = 7,
    _depth: int = 0,
) -> tuple[list[Event], list[str]]:
    """All music events in a window, walked in chunks to stay under the 1000 cap."""
    if not available():
        return [], ["ticketmaster: no API key configured"]

    events: list[Event] = []
    notes: list[str] = []
    cursor = start

    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        params: dict = {
            "classificationName": "music",
            "startDateTime": _iso(cursor),
            "endDateTime": _iso(chunk_end, end=True),
            "sort": "date,asc",
        }
        if country:
            params["countryCode"] = country.upper()
        if city:
            params["city"] = city
        if lat is not None and lon is not None:
            params["geoPoint"] = geohash(lat, lon)
            params["radius"] = str(int(radius_km or 240))
            params["unit"] = "km"

        chunk_events, truncated = await _page_through(params)
        events.extend(chunk_events)

        if truncated:
            # Halve the window and retry rather than silently dropping shows.
            # A truncated sweep and an empty one look identical from the outside,
            # which is exactly the failure mode worth spending calls to avoid.
            if chunk_days > 1 and _depth < 4:
                finer = max(chunk_days // 2, 1)
                notes.append(
                    f"ticketmaster: {cursor}..{chunk_end} exceeded 1000 results, "
                    f"re-scanned at {finer}-day resolution"
                )
                sub_events, sub_notes = await sweep(
                    cursor,
                    chunk_end,
                    country=country,
                    city=city,
                    lat=lat,
                    lon=lon,
                    radius_km=radius_km,
                    chunk_days=finer,
                    _depth=_depth + 1,
                )
                events.extend(sub_events)
                notes.extend(sub_notes)
            else:
                notes.append(
                    f"ticketmaster: more than 1000 music events on {cursor}; "
                    "the tail was not retrieved"
                )

        cursor = chunk_end + timedelta(days=1)

    return events, notes


async def attraction_id(key: str, name: str) -> str | None:
    """Resolve an artist to an attraction id. Cached permanently, including
    misses — re-searching a name Discovery doesn't know is pure waste."""
    row = db.query_one(
        "SELECT provider_id FROM provider_ids WHERE key = ? AND provider = ?",
        (key, PROVIDER),
    )
    if row is not None:
        return row["provider_id"]

    payload = await http.get_json(
        f"{BASE}/attractions.json",
        params={
            "apikey": config.ticketmaster_api_key,
            "keyword": name,
            "classificationName": "music",
            "size": 5,
        },
        provider=PROVIDER,
    )

    target = normalize(name)
    resolved = None
    for attraction in ((payload or {}).get("_embedded") or {}).get("attractions") or []:
        if normalize(attraction.get("name", "")) == target:
            resolved = attraction.get("id")
            break

    db.execute(
        "INSERT INTO provider_ids(key, provider, provider_id, checked_at) "
        "VALUES(?,?,?,?) ON CONFLICT(key, provider) DO UPDATE SET "
        "provider_id = excluded.provider_id, checked_at = excluded.checked_at",
        (key, PROVIDER, resolved, now_iso()),
    )
    return resolved


async def by_artist(
    key: str,
    name: str,
    start: date,
    end: date,
    *,
    country: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
) -> list[Event]:
    """One artist's shows. Omit every geography argument for worldwide, which is
    how cross-border detours get found for artists worth detouring for."""
    if not available():
        return []

    resolved = await attraction_id(key, name)
    if not resolved:
        return []

    params: dict = {
        "attractionId": resolved,
        "startDateTime": _iso(start),
        "endDateTime": _iso(end, end=True),
        "sort": "date,asc",
    }
    if country:
        params["countryCode"] = country.upper()
    if lat is not None and lon is not None:
        params["geoPoint"] = geohash(lat, lon)
        params["radius"] = str(int(radius_km or 480))
        params["unit"] = "km"

    events, _ = await _page_through(params)
    return events
