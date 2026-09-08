"""Behaviour tests for degradation, quotas, live settings and relocation."""

import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db, health, queue, routing, settings, usage, worker  # noqa: E402
from api.config import config  # noqa: E402
from api.providers import jambase  # noqa: E402
from api.util import day_key, now_iso, today  # noqa: E402

scenarios("operations.feature")

HOME = (38.0, -95.0)
SPRINGFIELD = (38.2, -95.2)
FAIRVIEW = (37.5, -97.0)


@pytest.fixture
def world():
    return {}


def run(coro):
    """pytest-bdd steps are synchronous, so async work is driven explicitly.
    Without this the coroutine is created, never awaited, and the step silently
    does nothing — which is worse than failing."""
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# Given
# --------------------------------------------------------------------------


@given("a cold queue over a six month horizon")
def _cold_queue(world):
    settings.set_value("home_lat", HOME[0])
    settings.set_value("home_lon", HOME[1])
    queue.plan_local(*HOME, 180)
    world["windows"] = queue.slice_windows(today(), today() + timedelta(days=180))


@given("JamBase is configured")
def _jambase(monkeypatch):
    monkeypatch.setattr(config, "jambase_api_key", "key")
    monkeypatch.setenv("JAMBASE_BASE_URL", "https://jb.test/v1")


@given("the JamBase monthly cap is already reached")
def _cap_reached():
    _, cap = usage.cap_for("jambase")
    db.execute(
        "INSERT INTO provider_usage(provider, period, calls) VALUES(?,?,?)",
        ("jambase", day_key(), cap),
    )


@given("I have artists cached from an earlier sync")
def _cached_artists():
    db.execute(
        "INSERT INTO artists(key, mbid, name, lidarr_id, monitored, listens, affinity, "
        "updated_at) VALUES('k1', NULL, 'Cached Band', 1, 1, 10, 0.5, ?)",
        (now_iso(),),
    )


@given("Lidarr is unreachable")
def _lidarr_down(routes, monkeypatch):
    monkeypatch.setattr(config, "lidarr_api_key", "key")
    routes.add_error("/api/v1/artist", 500)


@given(parsers.parse("the alert threshold is {value:f}"))
def _threshold(value):
    settings.set_value("notify_min_score", value)


@given("my home is set")
def _home_is_set():
    settings.set_value("home_lat", HOME[0])
    settings.set_value("home_lon", HOME[1])
    settings.set_value("home_label", "Home")


@given("the home horizon has been covered")
def _covered():
    scope = queue.local_scope(*HOME)
    for window_start, window_end, _ in queue.slice_windows(
        today(), today() + timedelta(days=180)
    ):
        queue.record_coverage(scope, window_start, window_end, "ticketmaster")
    # and a drive time resolved from the old home
    routing.store(
        routing.point_key(*HOME),
        routing.point_key(*FAIRVIEW),
        routing.Route(2.6, 165.0, False),
    )


@given("Ticketmaster is not configured")
def _no_tm(monkeypatch):
    monkeypatch.setattr(config, "ticketmaster_api_key", "")


# --------------------------------------------------------------------------
# When
# --------------------------------------------------------------------------


@when("I look at what the worker will do next")
def _inspect_queue(world):
    world["tasks"] = db.query(
        "SELECT task_key, priority, params FROM fetch_tasks WHERE kind = ? "
        "ORDER BY priority DESC",
        (queue.SWEEP_GEO,),
    )


@when("an artist lookup falls through to JamBase")
def _lookup(world, routes):
    routes.add("/events", {"events": []})
    world["result"] = run(
        jambase.by_artist_name("Obscure Band", today(), today() + timedelta(days=30))
    )
    world["routes"] = routes


@when("the library sync runs")
def _sync(world):
    from api import library

    async def _go():
        result = await library.sync()
        if result.get("error"):
            await health.report_lidarr_down(result["error"])
        return result

    world["result"] = run(_go())


@when(parsers.parse("I raise the alert threshold to {value:f}"))
def _raise_threshold(value):
    settings.set_value("notify_min_score", value)


@when("I move home to Springfield")
def _move(world):
    settings.set_value("home_lat", SPRINGFIELD[0])
    settings.set_value("home_lon", SPRINGFIELD[1])
    settings.set_value("home_label", "Springfield")
    worker.relocate(*SPRINGFIELD)


@when("I check the status page")
def _status(world):
    world["status"] = health.status()


# --------------------------------------------------------------------------
# Then
# --------------------------------------------------------------------------


@then("the nearest window is scheduled before the furthest")
def _order(world):
    tasks = world["tasks"]
    assert len(tasks) >= 2
    first = json.loads(tasks[0]["params"])["start"]
    last = json.loads(tasks[-1]["params"])["start"]
    assert first < last
    assert tasks[0]["priority"] > tasks[-1]["priority"]


@then("near-term windows refresh more often than distant ones")
def _cadence(world):
    near = queue.cadence_days(3)
    mid = queue.cadence_days(40)
    far = queue.cadence_days(150)
    assert near < mid < far
    assert (near, mid, far) == (1, 3, 14)


@then("no JamBase call is made")
def _no_call(world):
    assert world["result"] == []
    assert world["routes"].count("/events") == 0


@then("the status page reports the quota as exhausted")
def _quota_exhausted():
    row = next(r for r in usage.snapshot() if r["provider"] == "jambase")
    assert row["exhausted"] is True
    assert "jambase quota exhausted" in " ".join(health.status()["degraded"])


@then("the cached artists are still served")
def _still_served(world):
    from api import library

    assert world["result"].get("error")
    assert [a.name for a in library.all_artists()] == ["Cached Band"]


@then("a health alert is sent to the services topic")
def _alert_recorded():
    row = db.query_one("SELECT state FROM alerts WHERE key = 'lidarr'")
    assert row is not None and row["state"] == "down"


@then(parsers.parse("the new threshold is in effect immediately"))
def _in_effect():
    assert settings.get("notify_min_score") == 0.75


@then("it survives a restart")
def _survives():
    # a restart re-seeds from env; seeding must never clobber a set value
    settings.seed()
    assert settings.get("notify_min_score") == 0.75


@then("home coverage is invalidated")
def _invalidated():
    old_scope = queue.local_scope(*HOME)
    rows = db.query(
        "SELECT COUNT(*) AS n FROM coverage WHERE scope_key = ?", (old_scope,)
    )
    assert rows[0]["n"] == 0


@then("the status page reports re-indexing")
def _reindexing():
    assert health.status()["reindexing"] is True


@then("the old drive times are still on file")
def _old_routes_kept():
    """Keyed on origin, so moving back reuses them rather than re-paying."""
    assert routing.cached(routing.point_key(*HOME), routing.point_key(*FAIRVIEW))


@then("it reports Ticketmaster as not configured")
def _tm_missing(world):
    assert world["status"]["providers"]["ticketmaster"] is False
    assert any("Ticketmaster is not configured" in d for d in world["status"]["degraded"])


@then("no credential value appears anywhere in the response")
def _no_secrets(world, monkeypatch):
    """The status payload must never carry a key, only whether one exists."""
    secrets = [
        config.lidarr_api_key,
        config.jambase_api_key,
        config.ors_api_key,
        config.ntfy_token,
    ]
    blob = json.dumps(world["status"], default=str)
    for secret in secrets:
        if secret:
            assert secret not in blob
    assert all(isinstance(v, bool) for v in world["status"]["providers"].values())
