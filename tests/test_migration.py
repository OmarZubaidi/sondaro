"""Schema migrations.

Rebuilding the index costs hundreds of API calls, some of them billable, so a
rename must carry existing work forward rather than orphaning it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db  # noqa: E402


def test_the_old_home_scope_is_carried_over_to_local():
    db.execute(
        "INSERT INTO coverage(scope_key, window_start, window_end, provider, fetched_at) "
        "VALUES('home:38.000,-95.000', '2026-09-01', '2026-09-14', 'ticketmaster', 'x')"
    )
    db.execute(
        "INSERT INTO fetch_tasks(kind, task_key, params, priority, due_at) "
        "VALUES('sweep_geo', 'home:38.000,-95.000:2026-09-01', '{}', 1.0, 'x')"
    )

    db.close()
    db.connect()  # runs the migration

    scopes = [r["scope_key"] for r in db.query("SELECT scope_key FROM coverage")]
    tasks = [r["task_key"] for r in db.query("SELECT task_key FROM fetch_tasks")]

    assert scopes == ["local:38.000,-95.000"]
    assert tasks == ["local:38.000,-95.000:2026-09-01"]


def test_migrating_twice_is_harmless():
    db.execute(
        "INSERT INTO coverage(scope_key, window_start, window_end, provider, fetched_at) "
        "VALUES('home:1,2', '2026-09-01', '2026-09-14', 'ticketmaster', 'x')"
    )
    db.close()
    db.connect()
    db.close()
    db.connect()

    assert [r["scope_key"] for r in db.query("SELECT scope_key FROM coverage")] == ["local:1,2"]


def test_a_collision_prefers_the_row_already_named_local():
    """If both keys exist the newer one wins, and the stale one is dropped
    rather than left behind to inflate coverage."""
    db.executemany(
        "INSERT INTO coverage(scope_key, window_start, window_end, provider, fetched_at) "
        "VALUES(?,?,?,?,?)",
        [
            ("home:1,2", "2026-09-01", "2026-09-14", "ticketmaster", "old"),
            ("local:1,2", "2026-09-01", "2026-09-14", "ticketmaster", "new"),
        ],
    )

    db.close()
    db.connect()

    rows = db.query("SELECT scope_key, fetched_at FROM coverage")
    assert len(rows) == 1
    assert rows[0]["scope_key"] == "local:1,2"
    assert rows[0]["fetched_at"] == "new"


def _drop_end_columns() -> None:
    """An event cache from before shows had an end."""
    with db.cursor() as cur:
        for column in ("end_date", "end_time", "ends_at"):
            cur.execute(f"ALTER TABLE events DROP COLUMN {column}")


def test_an_older_event_cache_gains_the_end_columns_without_being_refetched():
    """Every cached listing predates these columns. Rebuilding the cache to
    fill them in would spend the API calls this whole migration exists to
    protect, so they arrive empty and fill on the next refresh."""
    db.execute(
        "INSERT INTO events(id, provider, artist_name, date, time) "
        "VALUES('ticketmaster:tm1', 'ticketmaster', 'Sabaton', '2026-09-10', '19:30')"
    )
    _drop_end_columns()

    db.close()
    db.connect()  # runs the migration

    row = db.query_one("SELECT * FROM events WHERE id = 'ticketmaster:tm1'")
    assert row["time"] == "19:30", "the listing itself must survive untouched"
    assert (row["end_date"], row["end_time"], row["ends_at"]) == (None, None, None)


def test_adding_the_end_columns_twice_is_harmless():
    _drop_end_columns()

    db.close()
    db.connect()
    db.close()
    db.connect()

    columns = {row["name"] for row in db.query("PRAGMA table_info(events)")}
    assert {"end_date", "end_time", "ends_at"} <= columns
