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
    listens     INTEGER DEFAULT 0,   -- scrobbles, from ListenBrainz or Last.fm
    tracks      INTEGER DEFAULT 0,   -- files on disk, from Lidarr
    affinity    REAL    DEFAULT 0.25,
    updated_at  TEXT,
    -- last time this artist was in the slice the Favorites page follows. Affinity is
    -- recomputed from scratch on every sync, so rank 10 and rank 11 can trade
    -- places during the week you spent planning around one of them; this is
    -- what keeps the one that slipped on the page instead of dropping it.
    top_seen_at TEXT
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
    -- The same moment as an absolute instant, when the provider gave us one.
    -- Venue-local alone can't be put in a calendar correctly: 8pm in Toronto
    -- read from a phone at home is 8pm at home, which is the wrong evening's
    -- worth of hours out.
    starts_at    TEXT,               -- ISO 8601 with an offset, nullable
    -- When it's over, in the same three shapes, and all nullable for the same
    -- reason: most listings never say. NULL means unknown, so anything that
    -- needs a length assumes one rather than reading a missing end as zero.
    end_date     TEXT,               -- YYYY-MM-DD, venue-local; later for a festival
    end_time     TEXT,               -- HH:MM, venue-local
    ends_at      TEXT,               -- ISO 8601 with an offset
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
    km          REAL,
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
    start_date   TEXT NOT NULL,     -- the whole trip; legs may narrow it
    end_date     TEXT NOT NULL,
    flex_before  INTEGER DEFAULT 0,
    flex_after   INTEGER DEFAULT 0,
    strict_dates INTEGER DEFAULT 0, -- booked and immovable
    created_at   TEXT,
    scanned_at   TEXT
);

-- Where a trip goes, and when. One row per country, plus one per city once
-- you know which cities.
--
-- A country with no city row is *loosely planned*: you're going, you don't yet
-- know where, so the whole country stays in play and a show just over its
-- border is still a detour worth knowing about. Naming a city anchors that
-- country and nothing else — booking Barcelona shouldn't make France, which
-- you haven't planned at all, measure its distance from Spain.
CREATE TABLE IF NOT EXISTS trip_legs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id    INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    country    TEXT NOT NULL,      -- ISO-2
    city       TEXT,               -- NULL = the country itself, unplanned
    start_date TEXT,               -- NULL = the trip's own dates
    end_date   TEXT
);
CREATE INDEX IF NOT EXISTS trip_legs_trip ON trip_legs(trip_id);

-- Tickets you've actually bought. Separate from `events` because that table is
-- a provider cache that ingest rewrites; a decision you made must outlive it.
CREATE TABLE IF NOT EXISTS purchased (
    event_id  TEXT PRIMARY KEY,
    marked_at TEXT
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
            _migrate(_conn)
            _conn.commit()
        return _conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Small, idempotent fixups for databases written by an earlier version.

    Worth doing rather than starting clean: the index costs hundreds of API
    calls to rebuild, some of them billable.
    """
    # the local scope was called "home" before the page was renamed. Rewriting
    # the key keeps coverage attached to the work already done rather than
    # orphaning it and re-sweeping the whole horizon.
    conn.execute(
        "UPDATE OR IGNORE coverage SET scope_key = 'local:' || substr(scope_key, 6) "
        "WHERE scope_key LIKE 'home:%'"
    )
    conn.execute("DELETE FROM coverage WHERE scope_key LIKE 'home:%'")
    conn.execute(
        "UPDATE OR IGNORE fetch_tasks SET task_key = 'local:' || substr(task_key, 6) "
        "WHERE task_key LIKE 'home:%'"
    )
    conn.execute("DELETE FROM fetch_tasks WHERE task_key LIKE 'home:%'")

    # Absolute start instants arrived after the event cache did. Backfilling
    # would mean re-fetching every listing, so existing rows stay floating and
    # fill in on their next refresh.
    if "starts_at" not in {row["name"] for row in conn.execute("PRAGMA table_info(events)")}:
        conn.execute("ALTER TABLE events ADD COLUMN starts_at TEXT")

    # End times arrived later still, and fill in the same way: on the next
    # refresh of each listing. Until then the row reads "unknown", which is
    # what it was before the columns existed.
    event_columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
    for column in ("end_date", "end_time", "ends_at"):
        if column not in event_columns:
            conn.execute(f"ALTER TABLE events ADD COLUMN {column} TEXT")

    # Track counts arrived later too, and the next library sync fills them in.
    artist_columns = {row["name"] for row in conn.execute("PRAGMA table_info(artists)")}
    if "tracks" not in artist_columns:
        conn.execute("ALTER TABLE artists ADD COLUMN tracks INTEGER DEFAULT 0")

    # The Favorites page's follow window. Left NULL rather than backfilled from the
    # current ranking: an unstamped artist still shows while they're in the top
    # slice, and the next sync stamps whoever is actually in it.
    if "top_seen_at" not in artist_columns:
        conn.execute("ALTER TABLE artists ADD COLUMN top_seen_at TEXT")

    # Distances moved to km. The cached drive times cost real API calls, so
    # they are converted in place rather than thrown away and re-fetched.
    route_columns = {row["name"] for row in conn.execute("PRAGMA table_info(routes)")}
    if "km" not in route_columns:
        conn.execute("ALTER TABLE routes ADD COLUMN km REAL")
        if "miles" in route_columns:
            conn.execute("UPDATE routes SET km = miles * 1.609344 WHERE miles IS NOT NULL")
    if "miles" in route_columns:
        conn.execute("ALTER TABLE routes DROP COLUMN miles")

    # Same for the two distance settings that were stated in miles.
    for old, new in (("cluster_miles", "cluster_km"),
                     ("trip_border_base_miles", "trip_border_base_km")):
        conn.execute(
            "UPDATE OR IGNORE settings SET key = ?, "
            "  value = CAST(ROUND(CAST(value AS REAL) * 1.609344) AS TEXT) "
            "WHERE key = ?",
            (new, old),
        )
        conn.execute("DELETE FROM settings WHERE key = ?", (old,))
    # The page was called Tours first. Carry the value over rather than leaving
    # it orphaned and silently reverting to the default.
    conn.execute(
        "UPDATE OR IGNORE settings SET key = 'favorite_artists' WHERE key = 'tour_artists'"
    )
    conn.execute("DELETE FROM settings WHERE key = 'tour_artists'")

    # Trips used to hold comma-separated countries and cities in two columns,
    # which couldn't say *when* you'd be in a city or which country a city
    # belonged to. Fold them into trip_legs, then drop the columns — a city
    # lands on the country it geocodes to, or on the only country if there's
    # one, and otherwise stays a country-level leg.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(trips)")}
    if "countries" in columns:
        for trip in conn.execute("SELECT id, countries, cities FROM trips").fetchall():
            countries = [c.strip().upper() for c in (trip["countries"] or "").split(",") if c.strip()]
            cities = [c.strip() for c in (trip["cities"] or "").split(",") if c.strip()]
            placed: set[str] = set()
            for city in cities:
                row = conn.execute(
                    "SELECT country FROM places WHERE query = ?", (city.lower(),)
                ).fetchone()
                owner = (row["country"] if row else None) or (
                    countries[0] if len(countries) == 1 else None
                )
                if owner in countries:
                    conn.execute(
                        "INSERT INTO trip_legs(trip_id, country, city) VALUES(?,?,?)",
                        (trip["id"], owner, city),
                    )
                    placed.add(owner)
            for country in countries:
                if country not in placed:
                    conn.execute(
                        "INSERT INTO trip_legs(trip_id, country, city) VALUES(?,?,NULL)",
                        (trip["id"], country),
                    )
        conn.execute("ALTER TABLE trips DROP COLUMN countries")
        conn.execute("ALTER TABLE trips DROP COLUMN cities")


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


def executemany(sql: str, rows: Iterable[tuple | dict]) -> None:
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
