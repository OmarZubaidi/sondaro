"""Status model and health alerting to the `services` ntfy topic.

Alerts here are deduped on state, not sent per occurrence: a provider that has
been down for six hours is one push, not seventy-two. The dedupe key stores the
last state seen, so a *change* is what pushes — including recovery, because
"it's working again" is information too.

Health alerts ignore the mute setting. Muting is for gig alerts on a quiet week;
it should never silence the fact that Lidarr is unreachable.
"""

import logging

from . import db, notify, queue, settings, usage
from .config import config
from .util import now_iso, today

log = logging.getLogger("sondaro.health")

LIDARR_KEY = "lidarr"
QUOTA_KEY = "quota"
PROVIDER_KEY = "provider"


async def _alert_on_change(key: str, state: str, title: str, body: str, tags: str) -> bool:
    """Push only when the state differs from the last one recorded."""
    row = db.query_one("SELECT state FROM alerts WHERE key = ?", (key,))
    if row is not None and row["state"] == state:
        return False

    db.execute(
        "INSERT INTO alerts(key, state, last_sent_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET state = excluded.state, "
        "last_sent_at = excluded.last_sent_at",
        (key, state, now_iso()),
    )
    if row is None and state == "ok":
        return False  # don't announce health on a fresh install

    return await notify.send(
        config.ntfy_topic_status, title=title, body=body, tags=tags, priority="high"
    )


async def report_lidarr_down(reason: str) -> None:
    await _alert_on_change(
        LIDARR_KEY,
        "down",
        "Sondaro: Lidarr unreachable",
        f"{reason}\nCached artists are still being served, but the library "
        "will drift until this recovers.",
        "warning",
    )


async def clear_lidarr_alert() -> None:
    await _alert_on_change(
        LIDARR_KEY, "ok", "Sondaro: Lidarr recovered", "Library sync is working again.", "white_check_mark"
    )


async def report_provider_error(kind: str, error: str) -> None:
    await _alert_on_change(
        f"{PROVIDER_KEY}:{kind}",
        "error",
        f"Sondaro: {kind} failing",
        f"{error}\nThe task will retry with backoff.",
        "warning",
    )


async def check_quotas() -> None:
    """JamBase bills for overage rather than refusing, so approaching the cap is
    worth knowing about before it matters."""
    for row in usage.snapshot():
        provider = row["provider"]
        if row["exhausted"]:
            state = "exhausted"
            body = (
                f"{provider}: {row['used']}/{row['cap']} calls used this "
                f"{row['period']}. Scanning continues on the remaining providers."
            )
        elif row["fraction"] >= 0.8:
            state = "nearing"
            body = f"{provider}: {row['used']}/{row['cap']} calls used this {row['period']}."
        else:
            state = "ok"
            body = ""

        if state == "ok":
            await _alert_on_change(f"{QUOTA_KEY}:{provider}", "ok", "", "", "")
            continue

        await _alert_on_change(
            f"{QUOTA_KEY}:{provider}",
            state,
            f"Sondaro: {provider} quota {state}",
            body,
            "chart_with_upwards_trend",
        )


def status() -> dict:
    """Everything the status page shows, and the same model that drives alerts."""
    from . import worker as worker_module

    lat, lon = settings.home()
    horizon_days = settings.get("home_horizon_days")
    expected_slices = len(queue.slice_windows(today(), settings.horizon_end()))
    scope = queue.home_scope(lat, lon)

    stalled = queue.stalled()
    quotas = usage.snapshot()

    degraded = []
    if not config.ticketmaster_api_key:
        degraded.append("Ticketmaster is not configured — no events can be found")
    if not config.ors_api_key:
        degraded.append("OpenRouteService is not configured — drive times are estimates")
    if not config.lidarr_api_key:
        degraded.append("Lidarr is not configured — the library cannot sync")
    for row in quotas:
        if row["exhausted"]:
            degraded.append(f"{row['provider']} quota exhausted for this {row['period']}")
    if stalled:
        degraded.append(f"{len(stalled)} queue tasks have exhausted their retries")

    return {
        "home": {"lat": lat, "lon": lon, "label": settings.get("home_label")},
        "horizon_days": horizon_days,
        "coverage": queue.coverage_fraction(scope, expected_slices),
        "coverage_slices": {"expected": expected_slices},
        "reindexing": db.get_meta("relocated_at") is not None
        and queue.coverage_fraction(scope, expected_slices) < 1.0,
        "queue": queue.depth(),
        "stalled": stalled,
        "quotas": quotas,
        "providers": config.credential_status(),
        "library": {
            "artists": int(db.scalar("SELECT COUNT(*) FROM artists WHERE source='lidarr'")),
            "discovery": int(
                db.scalar("SELECT COUNT(*) FROM artists WHERE source='discovery'")
            ),
            "synced_at": db.get_meta("library_synced_at"),
            "affinity_source": db.get_meta("affinity_source", "unknown"),
        },
        "events_cached": int(db.scalar("SELECT COUNT(*) FROM events")),
        "routing_host": db.get_meta("ors_working_base"),
        "sweep_notes": db.get_meta("last_sweep_notes", []),
        "worker": {
            "running": worker_module.worker.running,
            "processed": worker_module.worker.processed,
            "last_error": worker_module.worker.last_error,
        },
        "alerts": {
            "threshold": settings.get("notify_min_score"),
            "muted": settings.alerts_muted(),
            "mute_until": settings.get("mute_until"),
        },
        "degraded": degraded,
    }
