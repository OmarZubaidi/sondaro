"""Turning raw listings into ranked, explainable recommendations.

Ingest matches listings against the library and stores only the ones that hit.
Storing every music event in the sweep radius would mean tens of thousands of
rows about artists you've never heard of, on a container capped at 256 MB. The
cost of that choice is that an artist added to Lidarr today isn't matched
against already-fetched listings — so `library.sync` re-arms the sweeps when the
roster changes, rather than leaving you to wait out a 14-day cadence.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from . import borders, db, geo, queue, routing, scoring, settings
from .library import Artist
from .match import event_key, normalize, split_billing
from .providers.base import Event
from .util import now_iso, parse_date, today

log = logging.getLogger("sondaro.scan")

# how far out to pull events before scoring decides what's reachable. Generous:
# the decay curve does the filtering, this is just the SQL prefilter.
HOME_QUERY_MILES = 450.0


@dataclass
class Candidate:
    event: Event
    artist: Artist
    score: scoring.Score
    provider: str = ""

    @property
    def total(self) -> float:
        return self.score.total


# --------------------------------------------------------------------------
# matching and ingest
# --------------------------------------------------------------------------


def match_one(event: Event, by_name: dict, by_mbid: dict) -> Artist | None:
    """A MusicBrainz id beats any amount of string cleverness, so try it first."""
    if event.mbid and event.mbid.lower() in by_mbid:
        return by_mbid[event.mbid.lower()]

    best: Artist | None = None
    for raw_name in event.candidate_names():
        for billed in split_billing(raw_name):
            found = by_name.get(normalize(billed))
            if found and (best is None or found.affinity > best.affinity):
                best = found
        if best is not None:
            break
    return best


def ingest(events: list[Event], artists: list[Artist]) -> tuple[int, int]:
    """Store the listings that match the library. Returns (matched, seen)."""
    if not events:
        return 0, 0

    from .library import index_by_mbid, index_by_name

    by_name = index_by_name(artists)
    by_mbid = index_by_mbid(artists)

    stamp = now_iso()
    rows: dict[str, tuple] = {}
    matched = 0

    for event in events:
        artist = match_one(event, by_name, by_mbid)
        if artist is None:
            continue
        matched += 1
        # collapse the same show reported twice by different providers
        dedupe = event_key(artist.name, event.date, event.city, event.venue)
        existing = rows.get(dedupe)
        if existing is not None and existing[13]:  # already has a url
            continue
        rows[dedupe] = (
            event.id,
            event.provider,
            artist.key,
            artist.name,
            event.title,
            event.date,
            event.time,
            event.venue,
            event.city,
            event.region,
            (event.country or "").upper() or None,
            event.lat,
            event.lon,
            event.url,
            stamp,
            stamp,
        )

    db.executemany(
        "INSERT INTO events(id, provider, artist_key, artist_name, title, date, time, "
        "venue, city, region, country, lat, lon, url, first_seen, last_seen) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET date=excluded.date, time=excluded.time, "
        "venue=excluded.venue, city=excluded.city, url=excluded.url, "
        "last_seen=excluded.last_seen",
        rows.values(),
    )
    return matched, len(events)


def prune_past() -> int:
    """Yesterday's shows are not news."""
    return db.execute("DELETE FROM events WHERE date < ?", (today().isoformat(),))


# --------------------------------------------------------------------------
# home
# --------------------------------------------------------------------------


def away_windows() -> list[tuple[date, date]]:
    """Dates you're demonstrably somewhere else.

    Only the booked window counts, not the flex days: slack is "I could move
    this", whereas start..end is "I am not at home". Recommending a hometown
    show for a night you're in another country is just wrong.
    """
    windows = []
    for row in db.query(
        "SELECT start_date, end_date FROM trips WHERE end_date >= ?",
        (today().isoformat(),),
    ):
        start, end = parse_date(row["start_date"]), parse_date(row["end_date"])
        if start and end:
            windows.append((start, end))
    return windows


def is_away(day: date, windows: list[tuple[date, date]]) -> bool:
    return any(start <= day <= end for start, end in windows)


def _destinations(rows) -> dict[str, tuple[float, float]]:
    """Distinct venue cities. Routing is per city, never per event — that's the
    difference between a few hundred lifetime lookups and a few hundred a day."""
    out: dict[str, tuple[float, float]] = {}
    for row in rows:
        if row["lat"] is None or row["lon"] is None:
            continue
        key = routing.point_key(row["lat"], row["lon"])
        out.setdefault(key, (row["lat"], row["lon"]))
    return out


def home_candidates() -> list[Candidate]:
    """Everything reachable from home, scored and ranked."""
    lat, lon = settings.home()
    horizon = settings.horizon_end()
    min_lat, max_lat, min_lon, max_lon = geo.bounding_box(lat, lon, HOME_QUERY_MILES)

    rows = db.query(
        "SELECT e.*, a.affinity, a.listens "
        "FROM events e JOIN artists a ON a.key = e.artist_key "
        "WHERE e.date >= ? AND e.date <= ? "
        "  AND e.lat BETWEEN ? AND ? AND e.lon BETWEEN ? AND ? "
        "ORDER BY e.date",
        (today().isoformat(), horizon.isoformat(), min_lat, max_lat, min_lon, max_lon),
    )

    origin = (lat, lon)
    origin_key = routing.point_key(lat, lon)
    destinations = _destinations(rows)

    # queue anything not yet routed; meanwhile the estimate keeps results useful
    if routing.available():
        for dest_key, dest in destinations.items():
            if routing.cached(origin_key, dest_key) is None:
                queue.plan_route(origin, dest, dest_key)

    floor = settings.get("min_score")
    away = away_windows()
    candidates: list[Candidate] = []

    for row in rows:
        day = parse_date(row["date"])
        if day is None or row["lat"] is None:
            continue
        if is_away(day, away):
            continue  # you're on a trip; you cannot be at this show

        dest_key = routing.point_key(row["lat"], row["lon"])
        route = routing.cached(origin_key, dest_key) or routing.estimate(
            origin, (row["lat"], row["lon"])
        )

        score = scoring.score_home(
            artist_affinity=row["affinity"],
            day=day,
            drive_hours=route.drive_hours,
            miles=route.miles,
            estimated=route.estimated,
            listens=row["listens"] or 0,
            base_hours=settings.base_hours_for(day),
        )
        if score.total < floor:
            continue
        candidates.append(_candidate(row, score))

    candidates.sort(key=lambda c: (c.event.date, -c.total))
    return candidates


# --------------------------------------------------------------------------
# trips
# --------------------------------------------------------------------------


def trip_countries(trip) -> list[str]:
    return [c.strip().upper() for c in (trip["countries"] or "").split(",") if c.strip()]


def trip_cities(trip) -> list[str]:
    return [c.strip() for c in (trip["cities"] or "").split(",") if c.strip()]


def trip_window(trip) -> tuple[date, date, date, date]:
    """(start, end, window_start, window_end) — the trip and its slack."""
    start = parse_date(trip["start_date"])
    end = parse_date(trip["end_date"])
    strict = bool(trip["strict_dates"])
    before = 0 if strict else int(trip["flex_before"] or 0)
    after = 0 if strict else int(trip["flex_after"] or 0)
    return start, end, start - timedelta(days=before), end + timedelta(days=after)


def _named_city_points(cities: list[str]) -> list[tuple[float, float, str | None]]:
    """(lat, lon, country) for named cities, from the place cache or from
    listings we already hold. The worker resolves anything still missing."""
    points = []
    for city in cities:
        point = routing.cached_place(city)
        if point:
            points.append(point)
    return points


def _nearest(lat: float, lon: float, points) -> float | None:
    """Miles to the closest of a set of (lat, lon, country) points."""
    if not points:
        return None
    return min(geo.haversine_miles(lat, lon, plat, plon) for plat, plon, _c in points)


def _points_in(points, country: str):
    """Named cities that actually belong to a given country.

    Cities are matched per country, not globally. Naming only Toronto on a
    US+Canada trip must not make it the anchor for US shows too — that's the
    common case where half a trip is booked and the rest isn't.
    """
    return [p for p in points if (p[2] or "").upper() == country]


def trip_candidates(trip) -> list[Candidate]:
    """Everything worth seeing on a trip, scored and ranked. Nothing is hidden
    and nothing is chosen — the UI shows every option."""
    countries = trip_countries(trip)
    cities = trip_cities(trip)
    start, end, window_start, window_end = trip_window(trip)
    if not (start and end):
        return []

    strict = bool(trip["strict_dates"])
    border_base = settings.get("trip_border_base_miles")
    floor = settings.get("min_score")
    home = settings.home_country()

    rows = db.query(
        "SELECT e.*, a.affinity, a.listens "
        "FROM events e JOIN artists a ON a.key = e.artist_key "
        "WHERE e.date >= ? AND e.date <= ? ORDER BY e.date",
        (max(window_start, today()).isoformat(), window_end.isoformat()),
    )

    named_points = _named_city_points(cities)

    # A country we aren't actually searching must not anchor anything either.
    # Your home country with no city named contributes nothing, so measuring a
    # Canadian show's distance to the US border on a "trip to the US" would
    # offer results from a border we just declined to search.
    home_has_cities = bool(home) and bool(_points_in(named_points, home))
    anchor_countries = [c for c in countries if c != home or home_has_cities]

    candidates: list[Candidate] = []

    for row in rows:
        day = parse_date(row["date"])
        if day is None:
            continue

        country = (row["country"] or "").upper()
        inside = country in countries

        # Your home country is not "somewhere you're visiting". Going to one
        # city in it doesn't put the rest of the country in play, so only the
        # cities you named there count, and there's no country-wide floor.
        at_home_country = bool(home) and country == home
        local_points = _points_in(named_points, country) if inside else []
        miles_to_border = None
        miles_to_named = None

        if inside:
            if local_points:
                if row["lat"] is None:
                    continue
                miles_to_named = _nearest(row["lat"], row["lon"], local_points)
            elif at_home_country:
                # home country with no city named in it contributes nothing;
                # api_trip says so rather than leaving it looking empty
                continue
            # else: a country you're visiting with no cities named stays flat
        else:
            if row["lat"] is None:
                continue
            if named_points:
                # Once you've named cities, they are the anchor. Measuring to
                # the country border instead puts Toronto 27 miles from a New
                # York trip, because it is 27 miles from *a* US border — which
                # is true and completely useless.
                miles_to_border = _nearest(row["lat"], row["lon"], named_points)
            elif anchor_countries:
                miles_to_border = borders.distance_to_border(
                    row["lat"], row["lon"], anchor_countries
                )
            if miles_to_border is None:
                continue  # can't place it, so don't guess

        score = scoring.score_trip(
            artist_affinity=row["affinity"],
            day=day,
            start=start,
            end=end,
            flex_before=int(trip["flex_before"] or 0),
            flex_after=int(trip["flex_after"] or 0),
            strict=strict,
            in_visited_country=inside,
            country_name=borders.country_name(country) if country else None,
            miles_to_border=miles_to_border,
            miles_to_named_city=miles_to_named,
            listens=row["listens"] or 0,
            border_base_miles=border_base,
            country_floor=not at_home_country,
        )
        if score.total < floor:
            continue
        candidates.append(_candidate(row, score))

    candidates.sort(key=lambda c: -c.total)
    return candidates


def _candidate(row, score: scoring.Score) -> Candidate:
    return Candidate(
        event=Event(
            provider=row["provider"],
            provider_event_id=row["id"].split(":", 1)[-1],
            artist_name=row["artist_name"],
            title=row["title"] or "",
            date=row["date"],
            time=row["time"],
            venue=row["venue"],
            city=row["city"],
            region=row["region"],
            country=row["country"],
            lat=row["lat"],
            lon=row["lon"],
            url=row["url"],
        ),
        artist=Artist(
            key=row["artist_key"],
            name=row["artist_name"],
            mbid=None,
            affinity=row["affinity"],
            listens=row["listens"] or 0,
        ),
        score=score,
        provider=row["provider"],
    )


def serialise(candidate: Candidate) -> dict:
    event = candidate.event
    score = candidate.score
    return {
        "id": event.id,
        "artist": candidate.artist.name,
        "listens": candidate.artist.listens,
        "score": score.total,
        "affinity": score.affinity,
        "date_fit": score.date_fit,
        "reach_fit": score.reach_fit,
        "flags": score.flags,
        "reasons": score.reasons,
        "drive_hours": score.drive_hours,
        "miles": score.miles,
        "date": event.date,
        "time": event.time,
        "venue": event.venue,
        "city": event.city,
        "region": event.region,
        "country": event.country,
        "lat": event.lat,
        "lon": event.lon,
        "url": event.url,
        "provider": event.provider,
    }
