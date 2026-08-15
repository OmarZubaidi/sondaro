"""Provider call accounting and hard quota enforcement.

This exists because of a genuinely dangerous property of the JamBase free tier:
**it does not return 429 when you exceed 1,000 calls in a month — it bills you
$0.05 per call instead.** There is no protective error from the far end, so our
own counter is the only thing between a runaway loop and a surprise invoice.

Consequences baked in below:

  * `reserve()` claims a call **before** it is dispatched, in a single guarded
    UPDATE so concurrent workers can't both slip through the last slot.
  * Attempts are counted, not successes. A call that fails may still have been
    billed, so we must assume it was.
  * Reservations are never refunded on failure, for the same reason.
  * Callers fail **closed**: no reservation means the provider is skipped, not
    called anyway.
"""

import logging

from . import db
from .util import day_key, month_key, now_iso

log = logging.getLogger("sondaro.usage")

# Period each provider's quota is measured over.
MONTHLY = "monthly"
DAILY = "daily"

# Default caps. JamBase's is set well below the 1,000 free-tier ceiling on
# purpose: the gap is the safety margin that absorbs a bug before it costs money.
DEFAULT_CAPS: dict[str, tuple[str, int]] = {
    "jambase": (MONTHLY, 500),
    "ticketmaster": (DAILY, 4500),
    "openrouteservice": (DAILY, 1800),
}

# Nothing may raise these, whatever a setting says — a typo in the UI must not
# be able to authorise spending.
HARD_CEILINGS: dict[str, int] = {
    "jambase": 900,
}


def period_key(kind: str) -> str:
    return month_key() if kind == MONTHLY else day_key()


def cap_for(provider: str) -> tuple[str, int]:
    kind, cap = DEFAULT_CAPS.get(provider, (DAILY, 10_000))
    ceiling = HARD_CEILINGS.get(provider)
    if ceiling is not None:
        cap = min(cap, ceiling)
    return kind, cap


def used(provider: str) -> int:
    kind, _ = cap_for(provider)
    return int(
        db.scalar(
            "SELECT calls FROM provider_usage WHERE provider = ? AND period = ?",
            (provider, period_key(kind)),
            0,
        )
    )


def remaining(provider: str) -> int:
    _, cap = cap_for(provider)
    return max(0, cap - used(provider))


def reserve(provider: str, count: int = 1) -> bool:
    """Claim `count` calls up front. False means the cap is reached.

    The UPDATE carries its own guard (`calls + ? <= cap`), so two workers racing
    for the final slot cannot both win — SQLite serialises the write and the
    loser's rowcount is 0.
    """
    kind, cap = cap_for(provider)
    period = period_key(kind)

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO provider_usage(provider, period, calls) VALUES(?,?,0) "
            "ON CONFLICT(provider, period) DO NOTHING",
            (provider, period),
        )
        cur.execute(
            "UPDATE provider_usage SET calls = calls + ? "
            "WHERE provider = ? AND period = ? AND calls + ? <= ?",
            (count, provider, period, count, cap),
        )
        granted = cur.rowcount == 1

    if not granted:
        log.warning(
            "%s quota exhausted for %s (%d/%d) — skipping rather than calling",
            provider,
            period,
            used(provider),
            cap,
        )
    return granted


def snapshot() -> list[dict]:
    """Per-provider usage for the status page."""
    out = []
    for provider in DEFAULT_CAPS:
        kind, cap = cap_for(provider)
        spent = used(provider)
        out.append(
            {
                "provider": provider,
                "period": kind,
                "period_key": period_key(kind),
                "used": spent,
                "cap": cap,
                "remaining": max(0, cap - spent),
                "fraction": round(spent / cap, 4) if cap else 0.0,
                "exhausted": spent >= cap,
            }
        )
    return out


def nearing_cap(provider: str, at: float = 0.8) -> bool:
    _, cap = cap_for(provider)
    return cap > 0 and used(provider) >= cap * at


def record_note(key: str, state: str) -> None:
    db.execute(
        "INSERT INTO alerts(key, state, last_sent_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET state = excluded.state",
        (key, state, now_iso()),
    )
