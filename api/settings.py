"""Live settings — the behavioural half of the configuration split.

Everything here is editable from the UI and takes effect on the next scan with
no restart. Env vars in `config.SEEDS` populate the table once on first run and
are never consulted again, so a fresh container comes up sane while a running
one stays under your control.

Credentials deliberately do **not** live here. Changing a key stays a deploy,
which is the correct amount of friction for something that grants access.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from . import db, scoring
from .config import SEEDS
from .util import now_iso, parse_date, today


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    kind: str  # float | int | str | bool | date
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    help: str = ""


# The full editable surface. Order is the order the Settings page renders in.
SPECS: tuple[Spec, ...] = (
    Spec("home_lat", "Home latitude", "float", 38.0, -90, 90),
    Spec("home_lon", "Home longitude", "float", -95.0, -180, 180),
    Spec("home_label", "Home", "str", "Home",
         help="Shown on the status page. Set by the location search."),
    Spec("home_horizon_days", "How far ahead to look", "int", 180, 30, 365,
         help="Longer horizons cost more API calls on the first fill only."),
    Spec("base_hours_weeknight", "Weeknight drive budget (hours)", "float",
         scoring.BASE_HOURS_WEEKNIGHT, 0.5, 12,
         help="How far you'd drive on a Mon-Thu for an artist you love."),
    Spec("base_hours_sunday", "Sunday drive budget (hours)", "float",
         scoring.BASE_HOURS_SUNDAY, 0.5, 12),
    Spec("base_hours_weekend", "Fri/Sat drive budget (hours)", "float",
         scoring.BASE_HOURS_WEEKEND, 0.5, 16),
    Spec("trip_border_base_miles", "Cross-border detour budget (miles)", "float",
         scoring.TRIP_BORDER_BASE_MILES, 10, 500,
         help="How far outside a country you're visiting still counts as a detour."),
    Spec("notify_min_score", "Alert threshold", "float", 0.35, 0.0, 1.0,
         help="Shows scoring below this never push. Raise it on a quiet week."),
    Spec("notify_max_per_run", "Most alerts per scan", "int", 12, 1, 100),
    Spec("mute_until", "Mute alerts until", "date", "",
         help="Silence with an end date. Health alerts are never muted."),
    Spec("min_score", "Hide results below", "float", 0.05, 0.0, 1.0),
)

_BY_KEY = {spec.key: spec for spec in SPECS}

_CASTS: dict[str, Callable[[Any], Any]] = {
    "float": float,
    "int": int,
    "str": str,
    "bool": lambda v: str(v).strip().lower() in ("1", "true", "yes", "on"),
    "date": lambda v: str(v).strip(),
}


def seed() -> None:
    """Copy env seeds and spec defaults into the table. Idempotent, and never
    overwrites a value already set — that's the whole point of the one-way door."""
    existing = {row["key"] for row in db.query("SELECT key FROM settings")}
    stamp = now_iso()
    rows = []
    for spec in SPECS:
        if spec.key in existing:
            continue
        raw = SEEDS.get(spec.key, spec.default)
        rows.append((spec.key, str(raw), stamp))
    db.executemany(
        "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO NOTHING",
        rows,
    )


def get(key: str) -> Any:
    spec = _BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"unknown setting: {key}")
    row = db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
    raw = row["value"] if row else SEEDS.get(key, spec.default)
    try:
        return _CASTS[spec.kind](raw)
    except (TypeError, ValueError):
        return _CASTS[spec.kind](spec.default)


def set_value(key: str, value: Any) -> Any:
    spec = _BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"unknown setting: {key}")

    cast = _CASTS[spec.kind](value)
    if spec.kind in ("float", "int"):
        if spec.minimum is not None and cast < spec.minimum:
            raise ValueError(f"{key} must be at least {spec.minimum}")
        if spec.maximum is not None and cast > spec.maximum:
            raise ValueError(f"{key} must be at most {spec.maximum}")
    if spec.kind == "date" and cast and parse_date(cast) is None:
        raise ValueError(f"{key} must be YYYY-MM-DD or empty")

    db.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
        "updated_at = excluded.updated_at",
        (key, str(cast), now_iso()),
    )
    return cast


def all_values() -> dict[str, Any]:
    return {spec.key: get(spec.key) for spec in SPECS}


def describe() -> list[dict[str, Any]]:
    """Spec plus current value, for the Settings page to render generically."""
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "kind": spec.kind,
            "value": get(spec.key),
            "minimum": spec.minimum,
            "maximum": spec.maximum,
            "help": spec.help,
        }
        for spec in SPECS
    ]


# --- convenience accessors used all over the codebase ----------------------


def home() -> tuple[float, float]:
    return get("home_lat"), get("home_lon")


def origin_key() -> str:
    """Routing cache key for the current home. Rounded to ~100m, so nudging the
    pin by a few metres doesn't invalidate every cached drive time."""
    lat, lon = home()
    return f"{lat:.3f},{lon:.3f}"


def horizon_end() -> date:
    from datetime import timedelta

    return today() + timedelta(days=get("home_horizon_days"))


def alerts_muted() -> bool:
    until = parse_date(get("mute_until"))
    return bool(until and until >= today())


def base_hours_for(day: date) -> float:
    weekday = day.weekday()
    if weekday in (4, 5):
        return get("base_hours_weekend")
    if weekday == 6:
        return get("base_hours_sunday")
    return get("base_hours_weeknight")
