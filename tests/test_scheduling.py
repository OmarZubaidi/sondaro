"""Replanning must not re-arm work that is already scheduled.

Planning is idempotent by design and gets re-run constantly: every container
start, every library sync, every settings change. That is only affordable if a
task that already has a date keeps it. When `enqueue` pulled every task forward
to now, a redeploy re-armed the entire library at once — hundreds of lookups
due simultaneously, and for the gap-fill slice each empty one buys a JamBase
call at $0.05. The refresh cadence in `queue.py` is the whole cost model; a
restart must not be able to bypass it.
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db, library, queue, worker  # noqa: E402
from api.match import artist_key  # noqa: E402
from api.util import now_iso, parse_iso  # noqa: E402

TODAY = date.today()


def _due(task_key: str) -> datetime:
    row = db.query_one("SELECT due_at FROM fetch_tasks WHERE task_key = ?", (task_key,))
    assert row is not None, f"no task {task_key}"
    return parse_iso(row["due_at"])


def _an_artist(name: str = "Palehound") -> None:
    db.execute(
        "INSERT INTO artists(key, name, affinity, listens, updated_at) VALUES(?,?,?,?,?)",
        (artist_key(None, name), name, 0.9, 500, now_iso()),
    )


def test_replanning_leaves_a_scheduled_task_where_it_is():
    queue.plan_local(38.0, -95.0, 30)
    key = db.query_one("SELECT task_key FROM fetch_tasks")["task_key"]

    later = (datetime.now(timezone.utc) + timedelta(days=14)).replace(microsecond=0)
    db.execute(
        "UPDATE fetch_tasks SET due_at = ?, last_ok_at = ? WHERE task_key = ?",
        (later.isoformat(timespec="seconds"), now_iso(), key),
    )

    queue.plan_local(38.0, -95.0, 30)

    assert _due(key) == later


def test_a_restart_does_not_re_arm_the_whole_library():
    """The reported symptom: every redeploy produced a burst of provider calls."""
    _an_artist()
    worker.worker._plan_targeted_lookups()

    task = queue.claim_next()
    assert task is not None and task.kind == queue.ARTIST_LOOKUP
    queue.complete(task, next_due=datetime.now(timezone.utc) + timedelta(days=7))

    worker.worker._plan_targeted_lookups()  # as a fresh container would

    assert queue.claim_next() is None


def test_an_explicit_due_date_still_wins():
    """Callers that mean "now" say so — bootstrap's library sync does exactly
    this, because a fresh container should re-read Lidarr."""
    queue.enqueue("sweep_geo", "local:x", {}, priority=1.0)
    db.execute(
        "UPDATE fetch_tasks SET due_at = ?",
        ((datetime.now(timezone.utc) + timedelta(days=9)).isoformat(timespec="seconds"),),
    )

    now = datetime.now(timezone.utc)
    queue.enqueue("sweep_geo", "local:x", {}, priority=1.0, due_at=now)

    assert _due("local:x") <= now


def test_a_new_artist_is_still_looked_up_immediately():
    """Preserving dates must not also freeze out work that has never run."""
    _an_artist()
    worker.worker._plan_targeted_lookups()
    first = queue.claim_next()
    assert first is not None
    queue.complete(first, next_due=datetime.now(timezone.utc) + timedelta(days=7))

    _an_artist("Emel Mathlouthi")
    worker.worker._plan_targeted_lookups()

    task = queue.claim_next()
    assert task is not None
    assert task.params["name"] == "Emel Mathlouthi"


async def test_an_artist_with_no_listings_is_not_asked_again_tomorrow(monkeypatch):
    """The steady-state half of the same bill. Ticketmaster draws a blank, the
    gap-fill goes to JamBase, JamBase has nothing either — and on a one-day
    cadence that empty answer gets bought again every morning."""
    from api.providers import jambase, ticketmaster

    async def nothing(*_args, **_kwargs):
        return []

    monkeypatch.setattr(ticketmaster, "by_artist", nothing)
    monkeypatch.setattr(jambase, "by_artist_name", nothing)
    monkeypatch.setattr(jambase, "available", lambda: True)

    _an_artist()
    queue.plan_artist_lookup(
        artist_key(None, "Palehound"),
        "Palehound",
        0.9,
        TODAY,
        TODAY + timedelta(days=180),
        scope="local:test",
        gap_fill=True,
    )
    task = queue.claim_next()
    assert task is not None

    await worker.worker._artist_lookup(task)

    assert _due(task.task_key) > datetime.now(timezone.utc) + timedelta(days=2)


async def test_a_lookup_that_found_something_keeps_the_near_term_cadence(monkeypatch):
    """Backing off must be about emptiness, not about lookups in general — an
    artist who is touring is exactly the one worth re-checking often."""
    from api.providers.base import Event
    from api.providers import ticketmaster

    async def one_show(*_args, **_kwargs):
        return [
            Event(
                provider="ticketmaster",
                provider_event_id="tm1",
                artist_name="Palehound",
                date=(TODAY + timedelta(days=20)).isoformat(),
                city="Springfield",
                country="US",
            )
        ]

    monkeypatch.setattr(ticketmaster, "by_artist", one_show)

    _an_artist()
    queue.plan_artist_lookup(
        artist_key(None, "Palehound"),
        "Palehound",
        0.9,
        TODAY,
        TODAY + timedelta(days=180),
        scope="local:test",
    )
    task = queue.claim_next()
    assert task is not None

    await worker.worker._artist_lookup(task)

    assert _due(task.task_key) < datetime.now(timezone.utc) + timedelta(days=2)
    assert len(library.all_artists()) == 1
