"""Provider call accounting and hard quota enforcement.

This exists because of a genuinely dangerous property of the JamBase free tier:
**it does not return 429 when you exceed 1,000 calls in a month — it bills you
$0.05 per call instead.** There is no protective error from the far end, so our
own counter is the only thing between a runaway loop and a surprise invoice.

Counts are bucketed by **day** and summed over a **rolling window**, not a
calendar period. A calendar month resets on the 1st, so 500 calls on 31 July
and 500 on 1 August is 1,000 in two days while every counter reads "half used".
A rolling 30-day window cannot be gamed that way, and is never more permissive
than the calendar version.

Consequences baked in below:

  * `reserve()` claims a call **before** it is dispatched, in a single guarded
    INSERT, so concurrent workers can't both slip through the last slot.
  * Attempts are counted, not successes. A call that fails may still have been
    billed, so we must assume it was.
  * Reservations are never refunded on failure, for the same reason.
  * Callers fail **closed**: no reservation means the provider is skipped, not
    called anyway.
"""

import logging
from datetime import date, timedelta

from . import db
from .util import day_key, now_iso, today

log = logging.getLogger("sondaro.usage")

# Window each provider's quota is measured over, in days.
MONTHLY = 30
DAILY = 1

# Default caps. JamBase's is set well below the 1,000 free-tier ceiling on
# purpose: the gap is the safety margin that absorbs a bug before it costs money.
DEFAULT_CAPS: dict[str, tuple[int, int]] = {
    "jambase": (MONTHLY, 500),
    "ticketmaster": (DAILY, 4500),
    "openrouteservice": (DAILY, 1800),
}

# Nothing may raise these, whatever a setting says — a typo in the UI must not
# be able to authorize spending.
HARD_CEILINGS: dict[str, int] = {
    "jambase": 900,
}

# how long to keep daily rows around; a little history is useful on the status
# page and it stops the table growing forever
RETENTION_DAYS = 120


def cap_for(provider: str) -> tuple[int, int]:
    """(window_days, cap)."""
    window, cap = DEFAULT_CAPS.get(provider, (DAILY, 10_000))
    ceiling = HARD_CEILINGS.get(provider)
    if ceiling is not None:
        cap = min(cap, ceiling)
    return window, cap


def window_start(window_days: int, end: date | None = None) -> str:
    """First day counted. A 1-day window is today only."""
    finish = end or today()
    return (finish - timedelta(days=window_days - 1)).isoformat()


def used(provider: str) -> int:
    window, _cap = cap_for(provider)
    return int(
        db.scalar(
            "SELECT COALESCE(SUM(calls), 0) FROM provider_usage "
            "WHERE provider = ? AND period >= ?",
            (provider, window_start(window)),
            0,
        )
    )


def remaining(provider: str) -> int:
    _window, cap = cap_for(provider)
    return max(0, cap - used(provider))


def reserve(provider: str, count: int = 1) -> bool:
    """Claim `count` calls up front. False means the cap is reached.

    The check and the increment happen inside one cursor, and SQLite serializes
    writes, so two workers racing for the final slot cannot both win.
    """
    window, cap = cap_for(provider)
    start = window_start(window)
    period = day_key()

    with db.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(calls), 0) FROM provider_usage "
            "WHERE provider = ? AND period >= ?",
            (provider, start),
        )
        spent = int(cur.fetchone()[0] or 0)
        if spent + count > cap:
            granted = False
        else:
            cur.execute(
                "INSERT INTO provider_usage(provider, period, calls) VALUES(?,?,?) "
                "ON CONFLICT(provider, period) DO UPDATE SET calls = calls + ?",
                (provider, period, count, count),
            )
            granted = True

    if not granted:
        log.warning(
            "%s quota exhausted (%d/%d over %d days) — skipping rather than calling",
            provider,
            spent,
            cap,
            window,
        )
    return granted


def prune(retention_days: int = RETENTION_DAYS) -> int:
    cutoff = (today() - timedelta(days=retention_days)).isoformat()
    return db.execute("DELETE FROM provider_usage WHERE period < ?", (cutoff,))


def snapshot() -> list[dict]:
    """Per-provider usage for the status page."""
    out = []
    for provider in DEFAULT_CAPS:
        window, cap = cap_for(provider)
        spent = used(provider)
        out.append(
            {
                "provider": provider,
                "window_days": window,
                "window_start": window_start(window),
                "used": spent,
                "cap": cap,
                "remaining": max(0, cap - spent),
                "fraction": round(spent / cap, 4) if cap else 0.0,
                "exhausted": spent >= cap,
            }
        )
    return out


def nearing_cap(provider: str, at: float = 0.8) -> bool:
    _window, cap = cap_for(provider)
    return cap > 0 and used(provider) >= cap * at


def record_note(key: str, state: str) -> None:
    db.execute(
        "INSERT INTO alerts(key, state, last_sent_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET state = excluded.state",
        (key, state, now_iso()),
    )
