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
LOCAL_QUERY_MILES = 450.0


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


def _text(value) -> str | None:
    """Last stop before sqlite. Providers are supposed to hand over strings and
    normalise their own quirks, but one that doesn't must not be able to fail
    this task: sqlite refuses to bind anything but a scalar, and a failed task
    is retried, which re-spends the API call that fetched the listing."""
    return value.strip() or None if isinstance(value, str) else None


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
        # once, up front: the dedupe key reads these too, so coercing them at
        # the row would still leave a malformed one to blow up on the way there
        venue, city = _text(event.venue), _text(event.city)
        country = _text(event.country)

        # collapse the same show reported twice by different providers
        dedupe = event_key(artist.name, event.date, city, venue)
        existing = rows.get(dedupe)
        if existing is not None and existing[13]:  # already has a url
            continue
        rows[dedupe] = (
            event.id,
            event.provider,
            artist.key,
            artist.name,
            _text(event.title) or "",
            event.date,
            _text(event.time),
            venue,
            city,
            _text(event.region),
            country.upper() if country else None,
            event.lat,
            event.lon,
            _text(event.url),
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


def _base_hours(day: date, overrides: dict) -> float:
    """Drive budget for a day, preferring a live UI override."""
    weekday = day.weekday()
    key = "weekend_hours" if weekday in (4, 5) else (
        "sunday_hours" if weekday == 6 else "weeknight_hours"
    )
    value = overrides.get(key)
    return float(value) if value is not None else settings.base_hours_for(day)


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


def local_candidates(overrides: dict | None = None) -> list[Candidate]:
    """Everything reachable from home, scored and ranked.

    `overrides` lets the UI drive the drive-time budgets and score floor live.
    Scoring happens here against already-cached events, so moving a slider
    re-ranks what we hold and never costs an API call.
    """
    overrides = overrides or {}
    lat, lon = settings.home()
    horizon = settings.horizon_end()
    min_lat, max_lat, min_lon, max_lon = geo.bounding_box(lat, lon, LOCAL_QUERY_MILES)

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

    floor = overrides.get("min_score")
    if floor is None:
        floor = settings.get("min_score")
    away = away_windows()
    bought = purchased_ids()
    candidates: list[Candidate] = []

    for row in rows:
        day = parse_date(row["date"])
        if day is None or row["lat"] is None:
            continue
        if is_away(day, away) and row["id"] not in bought:
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
            base_hours=_base_hours(day, overrides),
        )
        # a ticket you've bought is never filtered away: the score is advice
        # about whether to go, and you've already decided
        if score.total < floor and row["id"] not in bought:
            continue
        candidates.append(_candidate(row, score))

    candidates.sort(key=lambda c: (c.event.date, -c.total))
    return candidates


# --------------------------------------------------------------------------
# trips
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Leg:
    """One country of a trip, optionally narrowed to a city and to dates."""

    country: str
    city: str | None = None
    start: date | None = None
    end: date | None = None

    def window(self, trip_start: date, trip_end: date) -> tuple[date, date]:
        """A leg with no dates of its own spans the whole trip."""
        return (self.start or trip_start, self.end or trip_end)


def trip_legs(trip_id: int) -> list[Leg]:
    return [
        Leg(
            country=(row["country"] or "").strip().upper(),
            city=(row["city"] or "").strip() or None,
            start=parse_date(row["start_date"]),
            end=parse_date(row["end_date"]),
        )
        for row in db.query(
            # dated legs read as an itinerary; undated ones keep the order you
            # entered them, which is the only order they have
            "SELECT country, city, start_date, end_date FROM trip_legs "
            "WHERE trip_id = ? ORDER BY start_date IS NULL, start_date, id",
            (trip_id,),
        )
    ]


def trip_countries(trip) -> list[str]:
    """Every country the trip touches, in the order the legs were given."""
    seen: list[str] = []
    for leg in trip_legs(trip["id"]):
        if leg.country and leg.country not in seen:
            seen.append(leg.country)
    return seen


def trip_cities(trip) -> list[str]:
    return [leg.city for leg in trip_legs(trip["id"]) if leg.city]


def anchored_countries(legs: list[Leg]) -> set[str]:
    """Countries you've named a city in. Those are planned; the rest are not,
    and being unplanned is what keeps a whole country in play."""
    return {leg.country for leg in legs if leg.city}


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


def _leg_city_points(legs: list[Leg], country: str):
    """Geocoded points for the cities named in one country."""
    return _named_city_points([leg.city for leg in legs if leg.country == country and leg.city])


def _leg_window(
    legs: list[Leg], country: str, trip_start: date, trip_end: date
) -> tuple[date, date]:
    """The dates you'd be in a country, across all its legs.

    Two weeks in Spain split into Madrid then Barcelona is still two weeks in
    Spain, so the country's window is the span of its legs. A show outside the
    trip entirely is judged against the whole trip, since there's no leg it
    belongs to.
    """
    windows = [
        leg.window(trip_start, trip_end) for leg in legs if leg.country == country
    ]
    if not windows:
        return trip_start, trip_end
    return min(w[0] for w in windows), max(w[1] for w in windows)


def trip_candidates(trip) -> list[Candidate]:
    """Everything worth seeing on a trip, scored and ranked. Nothing is hidden
    and nothing is chosen — the UI shows every option.

    `min_score` is deliberately not consulted — that setting keeps the everyday
    local feed short, and turning it up shouldn't quietly narrow a trip you're
    planning once. A fixed `TRIP_FLOOR` drops the unreachable instead, so an
    artist you've never played still surfaces in a city you'll be standing in.
    """
    legs = trip_legs(trip["id"])
    countries = [c for c in {leg.country for leg in legs} if c]
    start, end, window_start, window_end = trip_window(trip)
    if not (start and end) or not legs:
        return []

    strict = bool(trip["strict_dates"])
    border_base = settings.get("trip_border_base_miles")
    home = settings.home_country()
    anchored = anchored_countries(legs)
    bought = purchased_ids()

    rows = db.query(
        "SELECT e.*, a.affinity, a.listens "
        "FROM events e JOIN artists a ON a.key = e.artist_key "
        "WHERE e.date >= ? AND e.date <= ? ORDER BY e.date",
        (max(window_start, today()).isoformat(), window_end.isoformat()),
    )

    # Anchors, per country rather than pooled. Booking Barcelona anchors Spain
    # and says nothing about France, so a Geneva show is still measured from
    # the French border it's actually near.
    city_points = {c: _leg_city_points(legs, c) for c in anchored}

    # Countries still open, whose borders can pull in a show from outside. Your
    # home country never qualifies: flying to one city in the country you live
    # in doesn't put the rest of it, or its neighbours, in play.
    loose_countries = [
        c for c in countries if c not in anchored and (not home or c != home)
    ]

    candidates: list[Candidate] = []

    for row in rows:
        day = parse_date(row["date"])
        if day is None:
            continue

        country = (row["country"] or "").upper()
        inside = country in countries
        at_home_country = bool(home) and country == home
        miles_to_border = None
        miles_to_named = None

        # Dates come from the leg you'd be there for, so a Barcelona show on
        # the day you're in Toronto scores as being outside your dates.
        leg_start, leg_end = _leg_window(legs, country, start, end)

        if inside:
            if country in anchored:
                if row["lat"] is None:
                    continue
                miles_to_named = _nearest(row["lat"], row["lon"], city_points[country])
                if miles_to_named is None:
                    continue  # cities named but not yet geocoded; the worker will
            elif at_home_country:
                # home country with no city named in it contributes nothing;
                # api_trips says so rather than leaving it looking empty
                continue
            # else: a country you're visiting but haven't planned stays flat
        else:
            if row["lat"] is None:
                continue
            # nearest of: a border you haven't planned behind, or a city you
            # have. Whichever is genuinely closer is the honest answer.
            options = [
                m
                for m in (
                    borders.distance_to_border(row["lat"], row["lon"], loose_countries)
                    if loose_countries
                    else None,
                    _nearest(
                        row["lat"],
                        row["lon"],
                        [p for pts in city_points.values() for p in pts],
                    ),
                )
                if m is not None
            ]
            if not options:
                continue  # can't place it, so don't guess
            miles_to_border = min(options)

        score = scoring.score_trip(
            artist_affinity=row["affinity"],
            day=day,
            start=leg_start,
            end=leg_end,
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
        if score.total < scoring.TRIP_FLOOR and row["id"] not in bought:
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


def purchased_ids() -> set[str]:
    return {row["event_id"] for row in db.query("SELECT event_id FROM purchased")}


def is_purchased(event_id: str) -> bool:
    return (
        db.query_one("SELECT 1 FROM purchased WHERE event_id = ?", (event_id,))
        is not None
    )


def set_purchased(event_id: str, purchased: bool) -> bool:
    if purchased:
        db.execute(
            "INSERT INTO purchased(event_id, marked_at) VALUES(?,?) "
            "ON CONFLICT(event_id) DO NOTHING",
            (event_id, now_iso()),
        )
    else:
        db.execute("DELETE FROM purchased WHERE event_id = ?", (event_id,))
    return purchased


def serialise(candidate: Candidate, purchased: set[str] | None = None) -> dict:
    event = candidate.event
    score = candidate.score
    return {
        "purchased": event.id in purchased if purchased is not None else is_purchased(event.id),
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
