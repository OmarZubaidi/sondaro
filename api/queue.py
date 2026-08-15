"""The priority work queue.

The alternative — one big nightly scan — burns the API budget refetching a
6-month horizon that mostly hasn't changed, and makes a cold start useless until
it finishes. So work is sliced, prioritised, and re-polled at a rate that
matches how fast each slice actually changes.

    priority = urgency x importance
    urgency  = 1 / (1 + days_out/30)

Near-term slices and favourite artists drain first, which is why the UI is
useful within minutes of a cold start rather than hours.

Refresh cadence by horizon — this is what keeps steady-state cost flat:

    0-14 days   -> every day
    15-60 days  -> every 3 days
    61+ days    -> every 14 days

A show four months out is not going to change this week, so it is not worth a
call this week.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import db
from .util import now_iso, parse_iso, today

log = logging.getLogger("sondaro.queue")

# task kinds
SWEEP_GEO = "sweep_geo"
SWEEP_COUNTRY = "sweep_country"
ARTIST_LOOKUP = "artist_lookup"
ROUTE_LOOKUP = "route_lookup"
LIBRARY_SYNC = "library_sync"

# (max days out, slice length, refresh cadence) — ordered, first match wins
HORIZON_BANDS: tuple[tuple[int, int, int], ...] = (
    (14, 14, 1),
    (60, 15, 3),
    (10_000, 30, 14),
)

MAX_FAILURES = 5
BACKOFF_MINUTES = (5, 20, 60, 240, 720)


@dataclass
class Task:
    id: int
    kind: str
    task_key: str
    params: dict
    priority: float
    failures: int


def urgency(days_out: int) -> float:
    """Sooner matters more, on a curve that flattens rather than cliffs."""
    return round(1.0 / (1.0 + max(days_out, 0) / 30.0), 6)


def band_for(days_out: int) -> tuple[int, int]:
    """(slice_days, cadence_days) for a horizon distance."""
    for limit, slice_days, cadence in HORIZON_BANDS:
        if days_out <= limit:
            return slice_days, cadence
    return HORIZON_BANDS[-1][1], HORIZON_BANDS[-1][2]


def cadence_days(days_out: int) -> int:
    return band_for(days_out)[1]


def slice_windows(start: date, end: date) -> list[tuple[date, date, int]]:
    """Cut a horizon into (from, to, cadence) slices that get finer near today."""
    windows: list[tuple[date, date, int]] = []
    cursor = start
    while cursor <= end:
        days_out = (cursor - today()).days
        slice_days, cadence = band_for(days_out)
        window_end = min(cursor + timedelta(days=slice_days - 1), end)
        windows.append((cursor, window_end, cadence))
        cursor = window_end + timedelta(days=1)
    return windows


def enqueue(
    kind: str,
    task_key: str,
    params: dict,
    *,
    priority: float,
    due_at: datetime | None = None,
) -> None:
    """Idempotent. Re-enqueuing a pending task keeps the more urgent of the two
    rather than duplicating it — a trip created twice must not double the work."""
    when = (due_at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO fetch_tasks(kind, task_key, params, priority, due_at) "
        "VALUES(?,?,?,?,?) "
        "ON CONFLICT(task_key) DO UPDATE SET "
        "  priority = MAX(priority, excluded.priority), "
        "  due_at = MIN(due_at, excluded.due_at), "
        "  params = excluded.params",
        (kind, task_key, db.json_dumps(params), priority, when),
    )


def claim_next() -> Task | None:
    """Highest-priority task that is due. Single worker, so no locking needed."""
    row = db.query_one(
        "SELECT * FROM fetch_tasks WHERE due_at <= ? AND failures < ? "
        "ORDER BY priority DESC, due_at ASC LIMIT 1",
        (now_iso(), MAX_FAILURES),
    )
    if row is None:
        return None
    return Task(
        id=row["id"],
        kind=row["kind"],
        task_key=row["task_key"],
        params=db.json_loads(row["params"], {}),
        priority=row["priority"],
        failures=row["failures"] or 0,
    )


def next_due_at() -> datetime | None:
    """When the worker should next wake. None means nothing is scheduled, so it
    can sleep rather than spin."""
    row = db.query_one(
        "SELECT due_at FROM fetch_tasks WHERE failures < ? ORDER BY due_at ASC LIMIT 1",
        (MAX_FAILURES,),
    )
    return parse_iso(row["due_at"]) if row else None


def complete(task: Task, *, next_due: datetime | None) -> None:
    """Mark done. `next_due` None retires the task instead of rescheduling."""
    if next_due is None:
        db.execute("DELETE FROM fetch_tasks WHERE id = ?", (task.id,))
        return
    db.execute(
        "UPDATE fetch_tasks SET last_ok_at = ?, last_error = NULL, failures = 0, "
        "due_at = ? WHERE id = ?",
        (now_iso(), next_due.isoformat(timespec="seconds"), task.id),
    )


def fail(task: Task, error: str) -> None:
    """Back off exponentially. After MAX_FAILURES the task stops being claimed,
    which the status page surfaces rather than hiding."""
    failures = task.failures + 1
    minutes = BACKOFF_MINUTES[min(failures, len(BACKOFF_MINUTES)) - 1]
    retry_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    db.execute(
        "UPDATE fetch_tasks SET failures = ?, last_error = ?, due_at = ? WHERE id = ?",
        (failures, error[:400], retry_at.isoformat(timespec="seconds"), task.id),
    )
    log.warning("task %s failed (%d): %s", task.task_key, failures, error[:200])


def depth() -> dict[str, int]:
    rows = db.query(
        "SELECT kind, COUNT(*) AS n, SUM(due_at <= ?) AS due FROM fetch_tasks "
        "WHERE failures < ? GROUP BY kind",
        (now_iso(), MAX_FAILURES),
    )
    return {row["kind"]: {"total": row["n"], "due": row["due"] or 0} for row in rows}


def stalled() -> list[dict]:
    """Tasks that exhausted their retries. Visible, not swept under the rug."""
    return [
        {"task": row["task_key"], "error": row["last_error"], "failures": row["failures"]}
        for row in db.query(
            "SELECT task_key, last_error, failures FROM fetch_tasks WHERE failures >= ?",
            (MAX_FAILURES,),
        )
    ]


# --------------------------------------------------------------------------
# coverage
# --------------------------------------------------------------------------


def record_coverage(scope_key: str, start: date, end: date, provider: str) -> None:
    db.execute(
        "INSERT INTO coverage(scope_key, window_start, window_end, provider, fetched_at) "
        "VALUES(?,?,?,?,?) ON CONFLICT(scope_key, window_start, provider) DO UPDATE SET "
        "window_end = excluded.window_end, fetched_at = excluded.fetched_at",
        (scope_key, start.isoformat(), end.isoformat(), provider, now_iso()),
    )


def clear_coverage(scope_prefix: str) -> int:
    """Invalidate a scope — used when home moves, so results are never scored
    against a location you no longer live in."""
    rows = db.query(
        "SELECT COUNT(*) AS n FROM coverage WHERE scope_key LIKE ?", (f"{scope_prefix}%",)
    )
    db.execute("DELETE FROM coverage WHERE scope_key LIKE ?", (f"{scope_prefix}%",))
    db.execute("DELETE FROM fetch_tasks WHERE task_key LIKE ?", (f"{scope_prefix}%",))
    return rows[0]["n"] if rows else 0


def coverage_fraction(scope_prefix: str, expected: int) -> float:
    if expected <= 0:
        return 1.0
    covered = int(
        db.scalar(
            "SELECT COUNT(*) FROM coverage WHERE scope_key LIKE ?", (f"{scope_prefix}%",), 0
        )
    )
    return round(min(covered / expected, 1.0), 4)


# --------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------


def plan_home(lat: float, lon: float, horizon_days: int, radius_miles: float = 150.0) -> int:
    """Slice the home horizon into sweep tasks. Cheap to call repeatedly."""
    start = today()
    end = start + timedelta(days=horizon_days)
    scope = home_scope(lat, lon)

    for window_start, window_end, _cadence in slice_windows(start, end):
        days_out = (window_start - start).days
        enqueue(
            SWEEP_GEO,
            f"{scope}:{window_start.isoformat()}",
            {
                "lat": lat,
                "lon": lon,
                "radius_miles": radius_miles,
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
                "scope": scope,
            },
            priority=urgency(days_out),
        )
    return len(slice_windows(start, end))


def plan_trip(trip_id: int, countries: list[str], start: date, end: date) -> int:
    """Country sweeps for a trip, boosted so a trip you just created fills in
    while you are still looking at it."""
    planned = 0
    for country in countries:
        scope = trip_scope(trip_id, country)
        for window_start, window_end, _ in slice_windows(max(start, today()), end):
            days_out = (window_start - today()).days
            enqueue(
                SWEEP_COUNTRY,
                f"{scope}:{window_start.isoformat()}",
                {
                    "country": country,
                    "start": window_start.isoformat(),
                    "end": window_end.isoformat(),
                    "scope": scope,
                    "trip_id": trip_id,
                },
                # a trip is an explicit request, so it outranks background work
                priority=urgency(days_out) + 1.0,
            )
            planned += 1
    return planned


def plan_artist_lookup(
    artist_key_value: str,
    name: str,
    affinity: float,
    start: date,
    end: date,
    *,
    scope: str,
    country: str | None = None,
    worldwide: bool = False,
) -> None:
    """Per-artist lookups, prioritised by affinity — this is the mechanism that
    finds a favourite playing somewhere a sweep would never look."""
    enqueue(
        ARTIST_LOOKUP,
        f"{scope}:artist:{artist_key_value}",
        {
            "artist_key": artist_key_value,
            "name": name,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "country": country,
            "worldwide": worldwide,
            "scope": scope,
        },
        priority=urgency((start - today()).days) * max(affinity, 0.05),
    )


def plan_route(origin: tuple[float, float], dest: tuple[float, float], city: str) -> None:
    enqueue(
        ROUTE_LOOKUP,
        f"route:{origin[0]:.3f},{origin[1]:.3f}:{dest[0]:.3f},{dest[1]:.3f}",
        {"origin": list(origin), "dest": list(dest), "city": city},
        # routes gate whether anything can be scored, so they jump the queue
        priority=2.0,
    )


def home_scope(lat: float, lon: float) -> str:
    return f"home:{lat:.3f},{lon:.3f}"


def trip_scope(trip_id: int, country: str) -> str:
    return f"trip:{trip_id}:{country.upper()}"


def reschedule_for(window_start: date) -> datetime:
    """When a slice should next be refetched, from its distance in the future."""
    days_out = (window_start - today()).days
    return datetime.now(timezone.utc) + timedelta(days=cadence_days(days_out))


def params_dates(params: dict[str, Any]) -> tuple[date, date]:
    return date.fromisoformat(params["start"]), date.fromisoformat(params["end"])
