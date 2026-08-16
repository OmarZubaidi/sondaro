"""Env-backed configuration.

The split is deliberate and enforced here: this module holds **secrets and
wiring only**, plus first-run seeds for the settings the UI owns afterwards.
Anything behavioural — horizon, driving-hour bases, alert threshold — is read
through `settings.py`, not from here, so changing it never requires a redeploy.
Home location and timezone aren't here either: those come from Home Assistant,
which already holds them.

`SEEDS` is the one-way door: those values are copied into the settings table on
first run and never consulted again.
"""

import os
from dataclasses import dataclass, field


def _str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _int(key: str, default: int) -> int:
    try:
        return int(_str(key) or default)
    except ValueError:
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(_str(key) or default)
    except ValueError:
        return default


# deliberately not frozen: tests point db_path and borders_db at a tmpdir, and a
# frozen dataclass would need object.__setattr__ gymnastics to allow it
@dataclass
class Config:
    # --- storage ------------------------------------------------------------
    db_path: str = field(default_factory=lambda: _str("SONDARO_DB", "/config/sondaro.db"))
    borders_db: str = field(
        default_factory=lambda: _str("SONDARO_BORDERS_DB", "/app/api/borders.db")
    )
    static_dir: str = field(default_factory=lambda: _str("SONDARO_STATIC_DIR", "/app/static"))

    # --- wiring -------------------------------------------------------------
    lidarr_url: str = field(
        default_factory=lambda: _str("LIDARR_URL", "http://192.168.1.10:8686").rstrip("/")
    )
    ntfy_url: str = field(default_factory=lambda: _str("NTFY_URL").rstrip("/"))
    ntfy_topic_alerts: str = field(default_factory=lambda: _str("NTFY_TOPIC_ALERTS", "sondaro"))
    ntfy_topic_status: str = field(default_factory=lambda: _str("NTFY_TOPIC_STATUS", "services"))

    # --- credentials --------------------------------------------------------
    lidarr_api_key: str = field(default_factory=lambda: _str("LIDARR_API_KEY"))
    ticketmaster_api_key: str = field(default_factory=lambda: _str("TICKETMASTER_API_KEY"))
    jambase_api_key: str = field(default_factory=lambda: _str("JAMBASE_API_KEY"))
    ors_api_key: str = field(default_factory=lambda: _str("ORS_API_KEY"))
    ntfy_token: str = field(default_factory=lambda: _str("NTFY_TOKEN"))

    # --- affinity sources (usernames are not secrets, but they are wiring) ---
    listenbrainz_user: str = field(default_factory=lambda: _str("LISTENBRAINZ_USER"))
    lastfm_api_key: str = field(default_factory=lambda: _str("LASTFM_API_KEY"))
    lastfm_user: str = field(default_factory=lambda: _str("LASTFM_USER"))

    # --- operational knobs that genuinely are deploy-time -------------------
    max_concurrency: int = field(default_factory=lambda: _int("MAX_CONCURRENCY", 3))
    requests_per_second: float = field(
        default_factory=lambda: _float("REQUESTS_PER_SECOND", 4.0)
    )
    worker_enabled: bool = field(
        default_factory=lambda: _str("WORKER_ENABLED", "true").lower() != "false"
    )

    def credential_status(self) -> dict[str, bool]:
        """Which keys are present. Never the values — see `main.api_settings`."""
        return {
            "lidarr": bool(self.lidarr_api_key),
            "ticketmaster": bool(self.ticketmaster_api_key),
            "jambase": bool(self.jambase_api_key),
            "openrouteservice": bool(self.ors_api_key),
            "ntfy": bool(self.ntfy_token),
        }

    def ntfy_endpoint(self, topic: str) -> str:
        return f"{self.ntfy_url}/{topic}" if self.ntfy_url else ""


config = Config()


# First-run seeds. Copied into the settings table once, then owned by the UI.
# Keep in sync with the settings schema in settings.py.
SEEDS: dict[str, str] = {
    "home_horizon_days": _str("HOME_HORIZON_DAYS", "180"),
    "notify_min_score": _str("NOTIFY_MIN_SCORE", "0.35"),
}
