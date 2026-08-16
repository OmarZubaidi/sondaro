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
