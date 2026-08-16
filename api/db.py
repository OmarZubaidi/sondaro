"""SQLite persistence. One connection, WAL, guarded by a lock.

`events` is a **global cache**, not partitioned per trip. Creating a trip is
therefore a query plus a few enqueued sweeps, never a fresh crawl, and two trips
to the same country share everything already fetched.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable

from .config import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
-- artists from Lidarr. This is the whole universe of what can be recommended:
-- sondaro never suggests anyone you haven't added yourself.
CREATE TABLE IF NOT EXISTS artists (
    key         TEXT PRIMARY KEY,   -- mbid when known, else name:<normalised>
    mbid        TEXT,
    name        TEXT NOT NULL,
    lidarr_id   INTEGER,
    monitored   INTEGER DEFAULT 1,
    listens     INTEGER DEFAULT 0,
    affinity    REAL    DEFAULT 0.25,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS artists_affinity ON artists(affinity DESC);

-- resolved provider identifiers, cached so we never re-search a known artist
CREATE TABLE IF NOT EXISTS provider_ids (
    key         TEXT NOT NULL,
    provider    TEXT NOT NULL,
    provider_id TEXT,
    checked_at  TEXT,
    PRIMARY KEY (key, provider)
);

-- the global event cache
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,   -- provider:provider_event_id
    provider     TEXT NOT NULL,
    artist_key   TEXT,
    artist_name  TEXT NOT NULL,
    title        TEXT,
    date         TEXT NOT NULL,      -- YYYY-MM-DD, venue-local
    time         TEXT,               -- HH:MM, venue-local, nullable
    venue        TEXT,
    city         TEXT,
    region       TEXT,
    country      TEXT,
    lat          REAL,
    lon          REAL,
    url          TEXT,
    first_seen   TEXT,
    last_seen    TEXT
);
CREATE INDEX IF NOT EXISTS events_date ON events(date);
CREATE INDEX IF NOT EXISTS events_artist ON events(artist_key);
CREATE INDEX IF NOT EXISTS events_country ON events(country, date);
CREATE INDEX IF NOT EXISTS events_latlon ON events(lat, lon);

-- driving times, keyed on origin so moving house misses cleanly and the old
-- rows stay put in case you move back
CREATE TABLE IF NOT EXISTS routes (
    origin_key  TEXT NOT NULL,      -- rounded "lat,lon"
    dest_key    TEXT NOT NULL,      -- rounded "lat,lon"
    drive_hours REAL,
    miles       REAL,
    estimated   INTEGER DEFAULT 0,  -- 1 = derived from great-circle, not routed
    resolved_at TEXT,
    PRIMARY KEY (origin_key, dest_key)
);

-- the work queue
CREATE TABLE IF NOT EXISTS fetch_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,      -- sweep_geo|sweep_country|artist_lookup|route_lookup
    task_key    TEXT NOT NULL UNIQUE,
    params      TEXT NOT NULL,      -- json
    priority    REAL NOT NULL DEFAULT 0,
    due_at      TEXT NOT NULL,
    last_ok_at  TEXT,
    last_error  TEXT,
    failures    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS tasks_due ON fetch_tasks(due_at, priority DESC);

-- which slices have been fetched, and when — drives the refresh cadence
CREATE TABLE IF NOT EXISTS coverage (
    scope_key    TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end   TEXT NOT NULL,
    provider     TEXT NOT NULL,
    fetched_at   TEXT,
    PRIMARY KEY (scope_key, window_start, provider)
);

CREATE TABLE IF NOT EXISTS trips (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    countries    TEXT NOT NULL,     -- comma separated ISO-2; trips are multi-country
    cities       TEXT DEFAULT '',   -- optional, chosen after the countries
    start_date   TEXT NOT NULL,
    end_date     TEXT NOT NULL,
    flex_before  INTEGER DEFAULT 0,
    flex_after   INTEGER DEFAULT 0,
    strict_dates INTEGER DEFAULT 0, -- booked and immovable
    created_at   TEXT,
    scanned_at   TEXT
);

CREATE TABLE IF NOT EXISTS notified (
    event_id TEXT PRIMARY KEY,
    sent_at  TEXT
);

-- behavioural configuration, seeded from env once then owned by the UI
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);

-- provider call counts, bucketed by the period each quota is measured in
CREATE TABLE IF NOT EXISTS provider_usage (
    provider TEXT NOT NULL,
    period   TEXT NOT NULL,        -- YYYY-MM-DD or YYYY-MM
    calls    INTEGER DEFAULT 0,
    PRIMARY KEY (provider, period)
);

-- resolved place names, so a named trip city has coordinates even when we
-- never sweep its country
CREATE TABLE IF NOT EXISTS places (
    query       TEXT PRIMARY KEY,   -- lowercased city name as typed
    lat         REAL,
    lon         REAL,
    country     TEXT,
    resolved_at TEXT
);

-- internal key/value: which ORS host answered, last library sync, and so on.
-- distinct from `settings`, which is the user-facing surface.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- health alert throttling, so a sustained outage is one push and not hundreds
CREATE TABLE IF NOT EXISTS alerts (
    key          TEXT PRIMARY KEY,
    state        TEXT,
    last_sent_at TEXT
);
"""


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            parent = os.path.dirname(config.db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            _conn = sqlite3.connect(config.db_path, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA synchronous=NORMAL")
            _conn.execute("PRAGMA foreign_keys=ON")
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


@contextmanager
def cursor():
    conn = connect()
    with _lock:
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.lastrowid or 0


def executemany(sql: str, rows: Iterable[tuple]) -> None:
    batch = list(rows)
    if not batch:
        return
    with cursor() as cur:
        cur.executemany(sql, batch)


def scalar(sql: str, params: tuple = (), default: Any = 0) -> Any:
    row = query_one(sql, params)
    if row is None:
        return default
    value = row[0]
    return default if value is None else value


def get_meta(key: str, default: Any = None) -> Any:
    row = query_one("SELECT value FROM meta WHERE key = ?", (key,))
    if row is None:
        return default
    return json_loads(row["value"], default)


def set_meta(key: str, value: Any) -> None:
    execute(
        "INSERT INTO meta(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json_dumps(value)),
    )


def json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default
