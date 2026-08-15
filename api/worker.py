"""The single background worker.

One task at a time, sleeping until the next `due_at` rather than polling. An
empty queue costs no CPU, which matters on a VM that will eventually host a lot
of other things.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from . import db, health, library, notify, queue, routing, scan, settings
from .providers import jambase, ticketmaster
from .util import now_iso, today

log = logging.getLogger("sondaro.worker")

IDLE_SLEEP = 300.0  # nothing scheduled: check back in five minutes
MAX_SLEEP = 900.0
HOME_RADIUS_MILES = 150.0
TARGETED_ARTISTS = 60


class Worker:
    def __init__(self) -> None:
        self.running = False
        self._wake = asyncio.Event()
        self.last_error: str | None = None
        self.processed = 0

    def nudge(self) -> None:
        """Wake early — used when a trip is created or settings change, so the
        UI doesn't sit behind a sleep it can't see."""
        self._wake.set()

    async def run(self) -> None:
        self.running = True
        log.info("worker started")
        try:
            while self.running:
                try:
                    worked = await self.step()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - a bad task must not kill the loop
                    log.exception("worker step failed")
                    self.last_error = str(exc)
                    worked = False

                if not worked:
                    await self._sleep_until_due()
        finally:
            self.running = False
            log.info("worker stopped")

    async def _sleep_until_due(self) -> None:
        due = queue.next_due_at()
        if due is None:
            delay = IDLE_SLEEP
        else:
            delay = (due - datetime.now(timezone.utc)).total_seconds()
            delay = max(1.0, min(delay, MAX_SLEEP))

        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass

    async def step(self) -> bool:
        """Run one task. False means the queue had nothing due."""
        task = queue.claim_next()
        if task is None:
            return False

        handler = {
            queue.SWEEP_GEO: self._sweep_geo,
            queue.SWEEP_COUNTRY: self._sweep_country,
            queue.ARTIST_LOOKUP: self._artist_lookup,
            queue.ROUTE_LOOKUP: self._route_lookup,
            queue.LIBRARY_SYNC: self._library_sync,
        }.get(task.kind)

        if handler is None:
            log.error("unknown task kind %s, retiring it", task.kind)
            queue.complete(task, next_due=None)
            return True

        try:
            await handler(task)
            self.processed += 1
        except Exception as exc:  # noqa: BLE001
            queue.fail(task, repr(exc))
            await health.report_provider_error(task.kind, str(exc))
        return True

    # --- handlers ----------------------------------------------------------

    async def _sweep_geo(self, task: queue.Task) -> None:
        start, end = queue.params_dates(task.params)
        events, notes = await ticketmaster.sweep(
            start,
            end,
            lat=task.params["lat"],
            lon=task.params["lon"],
            radius_miles=task.params.get("radius_miles", HOME_RADIUS_MILES),
            chunk_days=7,
        )
        artists = library.all_artists()
        matched, seen = scan.ingest(events, artists)
        log.info("sweep_geo %s..%s: %d listings, %d matched", start, end, seen, matched)

        queue.record_coverage(task.params["scope"], start, end, "ticketmaster")
        if notes:
            db.set_meta("last_sweep_notes", notes)
        queue.complete(task, next_due=queue.reschedule_for(start))
        await self._announce_new_home_shows()

    async def _sweep_country(self, task: queue.Task) -> None:
        start, end = queue.params_dates(task.params)
        events, notes = await ticketmaster.sweep(
            start, end, country=task.params["country"], chunk_days=3
        )
        artists = library.all_artists()
        matched, seen = scan.ingest(events, artists)
        log.info(
            "sweep_country %s %s..%s: %d listings, %d matched",
            task.params["country"],
            start,
            end,
            seen,
            matched,
        )

        queue.record_coverage(task.params["scope"], start, end, "ticketmaster")
        if notes:
            db.set_meta("last_sweep_notes", notes)
        queue.complete(task, next_due=queue.reschedule_for(start))

    async def _artist_lookup(self, task: queue.Task) -> None:
        """Ticketmaster first. JamBase only if Ticketmaster found nothing —
        it costs real money and duplicating free coverage would be the worst
        possible use of ~16 calls a day."""
        start, end = queue.params_dates(task.params)
        key = task.params["artist_key"]
        name = task.params["name"]
        worldwide = task.params.get("worldwide", False)

        events = await ticketmaster.by_artist(
            key,
            name,
            start,
            end,
            country=None if worldwide else task.params.get("country"),
        )

        if not events and jambase.available():
            events = await jambase.by_artist_name(name, start, end)
            if events:
                log.info("jambase filled a gap for %s (%d events)", name, len(events))

        artists = library.all_artists()
        scan.ingest(events, artists)
        queue.complete(task, next_due=queue.reschedule_for(start))

    async def _route_lookup(self, task: queue.Task) -> None:
        origin = tuple(task.params["origin"])
        dest = tuple(task.params["dest"])
        route = await routing.drive_time(origin, dest)
        if route and not route.estimated:
            queue.complete(task, next_due=None)  # roads don't move either
        else:
            # keep it queued in case routing comes back, but don't hammer it
            queue.complete(task, next_due=datetime.now(timezone.utc) + timedelta(days=1))

    async def _library_sync(self, task: queue.Task) -> None:
        before = {row["key"] for row in db.query("SELECT key FROM artists")}
        result = await library.sync()
        after = {row["key"] for row in db.query("SELECT key FROM artists")}

        if result.get("error"):
            await health.report_lidarr_down(result["error"])
        else:
            await health.clear_lidarr_alert()

        # Only matched listings are stored, so a newly added artist would
        # otherwise wait out a 14-day cadence before being noticed. Re-arm the
        # sweeps instead.
        if after - before:
            rearmed = db.execute(
                "UPDATE fetch_tasks SET due_at = ? WHERE kind IN (?, ?)",
                (now_iso(), queue.SWEEP_GEO, queue.SWEEP_COUNTRY),
            )
            log.info("library gained %d artists, re-armed sweeps", len(after - before))
            del rearmed

        self._plan_targeted_lookups()
        queue.complete(task, next_due=datetime.now(timezone.utc) + timedelta(days=1))

    # --- planning ----------------------------------------------------------

    def _plan_targeted_lookups(self) -> None:
        """Per-artist lookups for the top of the library, worldwide.

        This is what catches a favourite playing somewhere no sweep covers —
        including just over a border during a trip. It is affinity-gated by
        construction: only artists you'd travel for get looked up this way.
        """
        horizon = settings.horizon_end()
        scope = queue.home_scope(*settings.home())
        for artist in library.top_artists(TARGETED_ARTISTS):
            queue.plan_artist_lookup(
                artist.key,
                artist.name,
                artist.affinity,
                today(),
                horizon,
                scope=scope,
                worldwide=True,
            )

    async def _announce_new_home_shows(self) -> None:
        try:
            await notify.announce_new_shows()
        except Exception:  # noqa: BLE001 - a push failure must not fail a sweep
            log.exception("notification pass failed")


worker = Worker()


def bootstrap() -> None:
    """Seed the queue. Idempotent, so it runs on every start."""
    settings.seed()
    lat, lon = settings.home()
    queue.enqueue(queue.LIBRARY_SYNC, "library:sync", {}, priority=5.0)
    slices = queue.plan_home(lat, lon, settings.get("home_horizon_days"), HOME_RADIUS_MILES)

    for row in db.query("SELECT * FROM trips WHERE end_date >= ?", (today().isoformat(),)):
        countries = scan.trip_countries(row)
        _, _, window_start, window_end = scan.trip_window(row)
        queue.plan_trip(row["id"], countries, window_start, window_end)

    log.info("bootstrap: %d home slices queued", slices)


def relocate(lat: float, lon: float) -> None:
    """Home moved. Drive times are keyed on origin so they miss cleanly, but
    coverage must be invalidated or we'd serve results scored for the old place.
    """
    queue.clear_coverage("home:")
    queue.plan_home(lat, lon, settings.get("home_horizon_days"), HOME_RADIUS_MILES)
    db.set_meta("relocated_at", now_iso())
    worker.nudge()
