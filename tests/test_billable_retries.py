"""A retry must never re-buy what the failed attempt already paid for.

`jambase.py` promises calls are "reserved before dispatch, never retried". It
keeps that promise at the HTTP layer — but the *task* around it retries, and a
task that fails after the call has returned dispatches it again. Two parsing
bugs found this the expensive way: each one billed the same listing on every
attempt until the failure ceiling.
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db, health, queue, scan, usage, worker  # noqa: E402
from api.config import config  # noqa: E402
from api.util import parse_iso  # noqa: E402

TODAY = date.today()


def _explode(*_args, **_kwargs):
    raise RuntimeError("boom")


@pytest.fixture
def jambase_on(routes, monkeypatch):
    """JamBase configured and answering, Ticketmaster finding nothing — the
    only path on which an artist lookup costs money."""
    monkeypatch.setattr(config, "jambase_api_key", "key")
    monkeypatch.setattr(config, "ticketmaster_api_key", "tm")
    monkeypatch.setenv("JAMBASE_BASE_URL", "https://jb.test/v3")

    routes.add("/attractions.json", {"_embedded": {"attractions": []}})
    routes.add(
        "/events",
        {
            "events": [
                {
                    "identifier": "jb1",
                    "startDate": f"{TODAY + timedelta(days=30)}T20:30",
                    "performer": [{"name": "Palehound"}],
                    "location": {"address": {"addressLocality": "Springfield"}},
                }
            ]
        },
    )
    return routes


def _queue_lookup(gap_fill: bool = True) -> queue.Task:
    queue.plan_artist_lookup(
        "name:palehound",
        "Palehound",
        0.9,
        TODAY,
        TODAY + timedelta(days=90),
        scope="local:test",
        gap_fill=gap_fill,
    )
    task = queue.claim_next()
    assert task is not None and task.kind == queue.ARTIST_LOOKUP
    return task


async def test_the_long_tail_never_reaches_jambase(jambase_on):
    """Only the top of the library earns the fall-through. Without this, one
    pass over a few hundred artists would spend the whole month's allowance on
    the ones Ticketmaster has never heard of."""
    await worker.worker._artist_lookup(_queue_lookup(gap_fill=False))

    assert jambase_on.count("/events") == 0
    assert usage.used("jambase") == 0


async def test_a_failed_store_does_not_re_buy_the_listing(jambase_on, monkeypatch):
    """The whole point. Ingest blows up after the money is gone; the task must
    finish rather than queue itself up to pay again."""
    def explode(*_args, **_kwargs):
        raise RuntimeError("something downstream is broken")

    monkeypatch.setattr(scan, "ingest", explode)

    await worker.worker._artist_lookup(_queue_lookup())

    assert jambase_on.count("/events") == 1
    assert usage.used("jambase") == 1
    # rescheduled, not backed off: failures stays 0 so nothing re-claims it now
    row = db.query_one("SELECT failures, last_error FROM fetch_tasks")
    assert row["failures"] == 0
    assert "something downstream is broken" in row["last_error"]


async def test_the_failed_run_is_not_armed_to_fire_again_in_minutes(
    jambase_on, monkeypatch
):
    """Before the fix this is the loop that ran up the bill: fail, back off five
    minutes, re-dispatch, fail — up to the ceiling. What has to be true is that
    the next attempt is a whole scheduled run away, not a backoff away."""
    monkeypatch.setattr(scan, "ingest", _explode)

    _queue_lookup()
    db.execute("UPDATE fetch_tasks SET due_at = ?", (queue.now_iso(),))
    assert await worker.worker.step() is True

    due = parse_iso(db.query_one("SELECT due_at FROM fetch_tasks")["due_at"])
    assert due > datetime.now(timezone.utc) + timedelta(hours=1)
    assert jambase_on.count("/events") == 1


async def test_a_failure_before_the_call_still_retries(routes, monkeypatch):
    """Nothing has been bought yet, so backing off and trying again is right —
    the fix must not turn every error into a shrug."""
    monkeypatch.setattr(config, "ticketmaster_api_key", "tm")
    monkeypatch.setattr(config, "jambase_api_key", "")  # never reached
    routes.add_error("/attractions.json", 500)
    routes.add_error("/events.json", 500)

    def explode(*_args, **_kwargs):
        raise RuntimeError("free to try again")

    monkeypatch.setattr(scan, "ingest", explode)

    with pytest.raises(RuntimeError):
        await worker.worker._artist_lookup(_queue_lookup())


async def test_a_discarded_lookup_is_reported_rather_than_hidden(jambase_on, monkeypatch):
    """It never hits the failure ceiling, so `stalled` will never show it. If
    nothing else surfaced it, listings would vanish silently."""
    monkeypatch.setattr(scan, "ingest", _explode)

    await worker.worker._artist_lookup(_queue_lookup())

    assert queue.stalled() == []
    assert len(queue.discarded()) == 1
    assert any("paid for" in note for note in health.status()["degraded"])


async def test_a_clean_run_clears_the_warning(jambase_on, monkeypatch):
    monkeypatch.setattr(scan, "ingest", _explode)
    await worker.worker._artist_lookup(_queue_lookup())
    assert len(queue.discarded()) == 1

    monkeypatch.undo()
    db.execute("UPDATE fetch_tasks SET due_at = ?", (queue.now_iso(),))
    task = queue.claim_next()
    assert task is not None
    await worker.worker._artist_lookup(task)

    assert queue.discarded() == []
