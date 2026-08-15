"""Scoring. Pure functions, no I/O, no database — everything here is testable
against a table of numbers.

    score = affinity × date_fit × reach_fit

Multiplicative on purpose: one bad axis kills a candidate without needing a pile
of tuning weights, and every component stays independently explainable in the UI.

The two reach models are deliberately different curves:

  home — measured in **driving hours**, not miles. Home→DC is 227 mi and
         Home→Millbrook is 356 mi, which look far apart on a map and much
         closer from behind a wheel. Distance would rank them wrongly.
  trip — measured in miles from the nearest border of a country you're
         visiting, on a far gentler curve, because distance is cheap once
         you're already travelling and cities get picked after countries.
"""

import math
from dataclasses import dataclass, field
from datetime import date

# --- affinity ---------------------------------------------------------------

LIBRARY_FLOOR = 0.25  # in Lidarr, never scrobbled

# --- home reach -------------------------------------------------------------

# base driving hours by day of week; a Saturday is worth further than a Tuesday
BASE_HOURS_WEEKNIGHT = 3.0  # Mon-Thu
BASE_HOURS_SUNDAY = 3.75
BASE_HOURS_WEEKEND = 4.5  # Fri-Sat

# --- trip reach -------------------------------------------------------------

TRIP_BORDER_BASE_MILES = 100.0
IN_COUNTRY_FLOOR = 0.6  # elsewhere-in-country stays viable when cities are named
NAMED_CITY_BASE_MILES = 150.0

# --- date fit ---------------------------------------------------------------

FLEX_FLOOR = 0.5

DECAY_EXPONENT = 4  # plateau near home, then a fast cliff


class Flag:
    OFF_ITINERARY = "not on your itinerary"
    OUTSIDE_DATES = "outside your dates"
    ESTIMATED_DRIVE = "estimated drive time"


@dataclass
class Score:
    """A scored candidate, with every component kept so the UI can explain it."""

    total: float
    affinity: float
    date_fit: float
    reach_fit: float
    flags: list[str] = field(default_factory=list)
    drive_hours: float | None = None
    miles: float | None = None
    reasons: list[str] = field(default_factory=list)


def affinity(listens: int, ceiling: int) -> float:
    """Log-scaled play count in [LIBRARY_FLOOR, 1.0].

    Log rather than linear so one obsessively-played artist doesn't flatten the
    rest of the library to zero.
    """
    if listens <= 0 or ceiling <= 0:
        return LIBRARY_FLOOR
    scaled = math.log1p(listens) / math.log1p(ceiling)
    return round(LIBRARY_FLOOR + (1.0 - LIBRARY_FLOOR) * min(scaled, 1.0), 4)


def shape_home(a: float) -> float:
    """How much of the full driving reach this artist earns. Superlinear, so
    the difference between a favourite and a passing interest is a real one."""
    a = max(0.0, min(a, 1.0))
    return 0.12 + 0.88 * a * a


def shape_trip(a: float) -> float:
    """Gentler than `shape_home` — on a trip even a mid-tier artist is worth a
    short hop across a border."""
    a = max(0.0, min(a, 1.0))
    return 0.45 + 0.55 * a * a


def base_hours_for(day: date) -> float:
    """Fri/Sat justify the furthest drive, Sunday sits between, Mon-Thu least."""
    weekday = day.weekday()  # Mon=0 .. Sun=6
    if weekday in (4, 5):
        return BASE_HOURS_WEEKEND
    if weekday == 6:
        return BASE_HOURS_SUNDAY
    return BASE_HOURS_WEEKNIGHT


def _decay(distance: float, reach: float) -> float:
    """1 / (1 + (d/reach)^4) — flat near zero, then falls off a cliff."""
    if reach <= 0:
        return 0.0
    if distance <= 0:
        return 1.0
    return round(1.0 / (1.0 + (distance / reach) ** DECAY_EXPONENT), 4)


def reach_fit_home(
    drive_hours: float,
    artist_affinity: float,
    day: date,
    base_hours: float | None = None,
) -> float:
    """How gettable this show is from home, given the artist and the day.

    `base_hours` is passed in by callers that read it from live settings; the
    default keeps this function usable standalone in tests.
    """
    base = base_hours_for(day) if base_hours is None else base_hours
    reach = base * shape_home(artist_affinity)
    return _decay(drive_hours, reach)


def reach_fit_trip(
    *,
    artist_affinity: float,
    in_visited_country: bool,
    miles_to_border: float | None = None,
    miles_to_named_city: float | None = None,
    border_base_miles: float = TRIP_BORDER_BASE_MILES,
) -> float:
    """Geography fit for a trip.

    Inside a visited country with no cities named, this is flat 1.0 — you pick
    cities after countries, so nothing in-country is ever penalised. Naming
    cities biases toward them without ever dropping the rest of the country
    below `IN_COUNTRY_FLOOR`.
    """
    if in_visited_country:
        if miles_to_named_city is None:
            return 1.0
        reach = NAMED_CITY_BASE_MILES * shape_trip(artist_affinity)
        raw = _decay(miles_to_named_city, reach)
        return round(IN_COUNTRY_FLOOR + (1.0 - IN_COUNTRY_FLOOR) * raw, 4)

    if miles_to_border is None:
        return 0.0
    reach = border_base_miles * shape_trip(artist_affinity)
    return _decay(miles_to_border, reach)


def date_fit(
    day: date,
    start: date,
    end: date,
    *,
    flex_before: int = 0,
    flex_after: int = 0,
    strict: bool = False,
) -> float:
    """1.0 inside the trip window.

    Strict trips are binary — for dates already booked and immovable. Flexible
    trips decay to `FLEX_FLOOR` at the edge of the slack and 0 beyond it.
    """
    if start <= day <= end:
        return 1.0
    if strict:
        return 0.0

    if day < start:
        out, window = (start - day).days, flex_before
    else:
        out, window = (day - end).days, flex_after

    if window <= 0 or out > window:
        return 0.0
    return round(FLEX_FLOOR + (1.0 - FLEX_FLOOR) * (1 - out / window), 4)


def score_home(
    *,
    artist_affinity: float,
    day: date,
    drive_hours: float,
    miles: float | None = None,
    estimated: bool = False,
    listens: int = 0,
    base_hours: float | None = None,
) -> Score:
    fit = reach_fit_home(drive_hours, artist_affinity, day, base_hours=base_hours)

    # A show that's too far simply scores low and sinks. It gets no badge:
    # flagging it would draw the eye to the thing you're least likely to do.
    flags: list[str] = [Flag.ESTIMATED_DRIVE] if estimated else []

    return Score(
        total=round(artist_affinity * fit, 4),
        affinity=artist_affinity,
        date_fit=1.0,
        reach_fit=fit,
        flags=flags,
        drive_hours=drive_hours,
        miles=miles,
        reasons=_reasons(listens),
    )


def score_trip(
    *,
    artist_affinity: float,
    day: date,
    start: date,
    end: date,
    flex_before: int = 0,
    flex_after: int = 0,
    strict: bool = False,
    in_visited_country: bool,
    country_name: str | None = None,
    miles_to_border: float | None = None,
    miles_to_named_city: float | None = None,
    listens: int = 0,
    border_base_miles: float = TRIP_BORDER_BASE_MILES,
) -> Score:
    fit_date = date_fit(
        day, start, end, flex_before=flex_before, flex_after=flex_after, strict=strict
    )
    fit_reach = reach_fit_trip(
        artist_affinity=artist_affinity,
        in_visited_country=in_visited_country,
        miles_to_border=miles_to_border,
        miles_to_named_city=miles_to_named_city,
        border_base_miles=border_base_miles,
    )

    flags: list[str] = []
    if not in_visited_country:
        where = country_name or "another country"
        flags.append(f"{Flag.OFF_ITINERARY} ({where})")
    if 0 < fit_date < 1.0:
        flags.append(Flag.OUTSIDE_DATES)

    return Score(
        total=round(artist_affinity * fit_date * fit_reach, 4),
        affinity=artist_affinity,
        date_fit=fit_date,
        reach_fit=fit_reach,
        flags=flags,
        miles=miles_to_border if not in_visited_country else miles_to_named_city,
        reasons=_reasons(listens),
    )


def _reasons(listens: int) -> list[str]:
    if listens > 0:
        return [f"{listens:,} scrobbles"]
    return ["in your library"]
