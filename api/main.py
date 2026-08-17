"""FastAPI application: JSON API, calendar feeds, and the built SPA.

The API returns data only — no rendering, no scoring decisions. Every ranking
choice lives in `scoring.py` so it can be tested against a table of numbers
rather than through HTTP.
"""

import asyncio
import contextlib
import logging
from datetime import date, timedelta
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import (
    borders,
    db,
    health,
    http,
    ics,
    library,
    queue,
    scan,
    settings,
    usage,
    worker,
)
from .config import config
from .providers import homeassistant
from .util import now_iso, parse_date, today

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("sondaro")

_sync_lock = asyncio.Lock()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    # adopt Home Assistant's location first, so nothing is planned around a
    # home we're about to replace
    if homeassistant.available():
        try:
            await worker.worker.sync_home_from_hass()
        except Exception:  # noqa: BLE001 - a missing HA must not block startup
            log.exception("could not read home from home assistant")
    worker.bootstrap()

    task = None
    if config.worker_enabled:
        task = asyncio.create_task(worker.worker.run())

    try:
        yield
    finally:
        worker.worker.running = False
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await http.close()
        db.close()


app = FastAPI(title="Sondaro", version="1.0.0", lifespan=lifespan, docs_url="/api/docs")


# --------------------------------------------------------------------------
# health and status
# --------------------------------------------------------------------------


@app.get("/healthz")
async def healthz():
    return {"ok": True, "time": now_iso()}


@app.get("/api/status")
async def api_status():
    await health.check_quotas()
    return health.status()


# --------------------------------------------------------------------------
# home
# --------------------------------------------------------------------------


@app.get("/api/local")
async def api_local(
    min_score: float | None = Query(None, ge=0.0, le=1.0),
    weeknight_hours: float | None = Query(None, gt=0, le=24),
    sunday_hours: float | None = Query(None, gt=0, le=24),
    weekend_hours: float | None = Query(None, gt=0, le=24),
):
    """Filters are applied by re-scoring cached events, so they never fetch."""
    candidates = scan.local_candidates(
        {
            "min_score": min_score,
            "weeknight_hours": weeknight_hours,
            "sunday_hours": sunday_hours,
            "weekend_hours": weekend_hours,
        }
    )

    by_month: dict[str, list] = {}
    for candidate in candidates:
        day = parse_date(candidate.event.date)
        bucket = day.strftime("%B %Y") if day else "unknown"
        by_month.setdefault(bucket, []).append(scan.serialise(candidate))

    return {
        "total": len(candidates),
        "months": [{"label": label, "shows": shows} for label, shows in by_month.items()],
        "status": health.status(),
    }


@app.post("/api/sync")
async def api_sync():
    """Force a library refresh now rather than waiting for the daily task."""
    async with _sync_lock:
        result = await library.sync()
    worker.worker.nudge()
    return result


# --------------------------------------------------------------------------
# trips
# --------------------------------------------------------------------------


def _trip_or_404(trip_id: int):
    row = db.query_one("SELECT * FROM trips WHERE id = ?", (trip_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="trip not found")
    return row


def _trip_summary(row) -> dict:
    legs = scan.trip_legs(row["id"])
    return {
        "id": row["id"],
        "name": row["name"],
        "legs": [
            {
                "country": leg.country,
                "city": leg.city,
                "start_date": leg.start.isoformat() if leg.start else None,
                "end_date": leg.end.isoformat() if leg.end else None,
            }
            for leg in legs
        ],
        "countries": scan.trip_countries(row),
        "cities": scan.trip_cities(row),
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "flex_before": row["flex_before"],
        "flex_after": row["flex_after"],
        "strict_dates": bool(row["strict_dates"]),
        "scanned_at": row["scanned_at"],
    }


@app.get("/api/trips")
async def api_trips():
    """Every trip and everything they turned up, in one merged feed.

    Per-trip pages made you check each one in turn to answer "what is there to
    see while I'm away", which is a single question. The filtering that used to
    be a page each is a sidebar instead.
    """
    rows = db.query("SELECT * FROM trips ORDER BY start_date")
    trips = [_trip_summary(row) for row in rows]

    # An event can sit inside two trips — overlapping dates, or the same
    # country twice. It's still one show, so it's one card carrying both
    # labels, scored by whichever trip makes the better case for it.
    merged: dict[str, dict] = {}
    for row, summary in zip(rows, trips):
        for candidate in scan.trip_candidates(row):
            shown = scan.serialise(candidate)
            existing = merged.get(shown["id"])
            if existing is None:
                shown["trips"] = [{"id": summary["id"], "name": summary["name"]}]
                merged[shown["id"]] = shown
                continue
            existing["trips"].append({"id": summary["id"], "name": summary["name"]})
            if shown["score"] > existing["score"]:
                existing.update(
                    {k: v for k, v in shown.items() if k != "trips"}
                )

    shows = sorted(merged.values(), key=lambda s: (s["date"], -s["score"]))

    by_date: dict[str, list] = {}
    for show in shows:
        by_date.setdefault(show["date"], []).append(show)

    # only the countries that actually have something, so the filter can't
    # offer you an empty result
    present = sorted({s["country"] for s in shows if s["country"]})

    return {
        "trips": trips,
        "total": len(shows),
        "dates": [{"date": day, "shows": rows_} for day, rows_ in sorted(by_date.items())],
        "countries": [
            {"code": code, "name": borders.country_name(code)} for code in present
        ],
        "notes": [note for row in rows for note in _trip_notes(row)],
    }


def _trip_notes(row) -> list[str]:
    """Why a trip might be emptier than it looks."""
    legs = scan.trip_legs(row["id"])
    home = settings.home_country()
    if home and any(leg.country == home and not leg.city for leg in legs):
        return [
            f"{row['name']}: {home} is your home country, so only cities you "
            "name there are searched. Name one to see anything from it."
        ]
    return []


def _validate_trip(payload: dict) -> dict:
    """Shared by create and update so the two can't drift apart."""
    name = str(payload.get("name") or "").strip()
    start = parse_date(payload.get("start_date"))
    end = parse_date(payload.get("end_date"))

    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not (start and end):
        raise HTTPException(status_code=400, detail="dates must be YYYY-MM-DD")
    if end < start:
        raise HTTPException(status_code=400, detail="end date is before start date")

    strict = bool(payload.get("strict_dates", False))
    return {
        "name": name,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "flex_before": 0 if strict else max(0, min(int(payload.get("flex_before") or 0), 30)),
        "flex_after": 0 if strict else max(0, min(int(payload.get("flex_after") or 0), 30)),
        "strict_dates": 1 if strict else 0,
        "legs": _validate_legs(payload, start, end),
    }


def _validate_legs(payload: dict, start: date, end: date) -> list[dict]:
    """Legs are the whole itinerary: a country you're visiting, optionally
    narrowed to a city and to the days you'll be in it."""
    raw = payload.get("legs")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400, detail="at least one country is required")

    legs = []
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="each leg must be an object")
        country = str(item.get("country") or "").strip().upper()
        if len(country) != 2:
            raise HTTPException(
                status_code=400, detail="each leg needs a 2-letter ISO country"
            )

        city = str(item.get("city") or "").strip() or None
        leg_start = parse_date(item.get("start_date")) if item.get("start_date") else None
        leg_end = parse_date(item.get("end_date")) if item.get("end_date") else None

        if (item.get("start_date") and not leg_start) or (
            item.get("end_date") and not leg_end
        ):
            raise HTTPException(status_code=400, detail="leg dates must be YYYY-MM-DD")
        if leg_start and leg_end and leg_end < leg_start:
            raise HTTPException(
                status_code=400, detail=f"{city or country}: end date is before start date"
            )
        # a leg outside the trip it belongs to is a typo, not an itinerary
        for when in (leg_start, leg_end):
            if when and not (start <= when <= end):
                raise HTTPException(
                    status_code=400,
                    detail=f"{city or country}: {when} is outside the trip",
                )

        legs.append(
            {
                "country": country,
                "city": city,
                "start_date": leg_start.isoformat() if leg_start else None,
                "end_date": leg_end.isoformat() if leg_end else None,
            }
        )
    return legs


def _write_legs(trip_id: int, legs: list[dict]) -> None:
    db.execute("DELETE FROM trip_legs WHERE trip_id = ?", (trip_id,))
    db.executemany(
        "INSERT INTO trip_legs(trip_id, country, city, start_date, end_date) "
        "VALUES(?,?,?,?,?)",
        [
            (trip_id, leg["country"], leg["city"], leg["start_date"], leg["end_date"])
            for leg in legs
        ],
    )


# fields that change *what gets searched*; editing one means re-planning, while
# a rename does not need to spend a single API call
SCOPE_FIELDS = ("start_date", "end_date", "flex_before", "flex_after", "strict_dates")


def _replan(trip_id: int) -> int:
    row = _trip_or_404(trip_id)
    _, _, window_start, window_end = scan.trip_window(row)
    queue.clear_coverage(f"trip:{trip_id}:")
    planned = queue.plan_trip(
        trip_id,
        scan.trip_legs(trip_id),
        window_start,
        window_end,
        home_country=settings.home_country(),
    )
    worker.worker.nudge()
    return planned


@app.post("/api/trips", status_code=201)
async def api_create_trip(payload: dict = Body(...)):
    fields = _validate_trip(payload)

    trip_id = db.execute(
        "INSERT INTO trips(name, start_date, end_date, flex_before, flex_after, "
        "strict_dates, created_at) VALUES(?,?,?,?,?,?,?)",
        (
            fields["name"],
            fields["start_date"],
            fields["end_date"],
            fields["flex_before"],
            fields["flex_after"],
            fields["strict_dates"],
            now_iso(),
        ),
    )
    _write_legs(trip_id, fields["legs"])
    _replan(trip_id)

    return _trip_summary(_trip_or_404(trip_id))


@app.patch("/api/trips/{trip_id}")
async def api_update_trip(trip_id: int, payload: dict = Body(...)):
    """Edit a trip. Plans get narrowed once things are booked, and sometimes a
    leg is dropped entirely."""
    before = _trip_or_404(trip_id)
    before_legs = _trip_summary(before)["legs"]

    # merge over what's there, so a partial edit doesn't have to resend
    # everything just to rename a trip
    merged = {
        "name": payload.get("name", before["name"]),
        "legs": payload.get("legs", before_legs),
        "start_date": payload.get("start_date", before["start_date"]),
        "end_date": payload.get("end_date", before["end_date"]),
        "flex_before": payload.get("flex_before", before["flex_before"]),
        "flex_after": payload.get("flex_after", before["flex_after"]),
        "strict_dates": payload.get("strict_dates", bool(before["strict_dates"])),
    }
    fields = _validate_trip(merged)

    scope_changed = any(str(fields[f]) != str(before[f]) for f in SCOPE_FIELDS)
    scope_changed = scope_changed or fields["legs"] != before_legs

    db.execute(
        "UPDATE trips SET name=?, start_date=?, end_date=?, "
        "flex_before=?, flex_after=?, strict_dates=? WHERE id=?",
        (
            fields["name"],
            fields["start_date"],
            fields["end_date"],
            fields["flex_before"],
            fields["flex_after"],
            fields["strict_dates"],
            trip_id,
        ),
    )
    _write_legs(trip_id, fields["legs"])

    # dropping a country should take its cached events' relevance with it, and
    # narrowing to a city shouldn't leave the old country-wide sweep queued
    planned = _replan(trip_id) if scope_changed else 0

    return {
        **_trip_summary(_trip_or_404(trip_id)),
        "rescanned": scope_changed,
        "queued": planned,
    }


@app.post("/api/trips/{trip_id}/rescan")
async def api_rescan_trip(trip_id: int):
    _trip_or_404(trip_id)
    planned = _replan(trip_id)
    db.execute("UPDATE trips SET scanned_at = ? WHERE id = ?", (now_iso(), trip_id))
    return {"queued": planned}


@app.delete("/api/trips/{trip_id}", status_code=204)
async def api_delete_trip(trip_id: int):
    _trip_or_404(trip_id)
    queue.clear_coverage(f"trip:{trip_id}:")
    db.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
    return Response(status_code=204)


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------


@app.get("/api/settings")
async def api_get_settings():
    return {
        "settings": settings.describe(),
        # presence only — a key is never rendered or returned
        "credentials": config.credential_status(),
        "quotas": usage.snapshot(),
    }


@app.patch("/api/settings")
async def api_patch_settings(payload: dict = Body(...)):
    """Takes effect on the next scan. No restart, and env is never consulted
    again for anything set here."""
    updated = {}
    for key, value in payload.items():
        try:
            updated[key] = settings.set_value(key, value)
        except KeyError:
            raise HTTPException(status_code=400, detail=f"unknown setting: {key}")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    if "home_horizon_days" in updated:
        queue.plan_local(*settings.home(), settings.get("home_horizon_days"))
    worker.worker.nudge()
    return {"updated": updated}


@app.get("/api/countries")
async def api_countries():
    return {"countries": borders.known_countries()}


# --------------------------------------------------------------------------
# calendar feeds
# --------------------------------------------------------------------------


def _calendar_response(candidates, name: str) -> Response:
    return Response(
        content=ics.build(candidates, name),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=1800",
            'Content-Disposition': 'attachment; filename="Sondaro.ics"',
        },
    )


@app.get("/sondaro.ics")
async def calendar(min_score: float = Query(0.0, ge=0.0, le=1.0)):
    """One feed: near home, plus everywhere you're going.

    A subscription is set up once and then forgotten, so a per-trip URL was a
    calendar you had to remember to add for every trip and remove afterwards.
    Adding a trip now just makes shows appear in the feed you already have.
    """
    candidates = list(scan.local_candidates())
    for row in db.query("SELECT * FROM trips ORDER BY start_date"):
        candidates.extend(scan.trip_candidates(row))

    # the same show can be both near home and inside a trip; one event, one
    # entry, or the calendar shows it twice
    best: dict[str, object] = {}
    for candidate in candidates:
        if candidate.total < min_score:
            continue
        seen = best.get(candidate.event.id)
        if seen is None or candidate.total > seen.total:
            best[candidate.event.id] = candidate

    return _calendar_response(
        sorted(best.values(), key=lambda c: c.event.date),
        f"Sondaro — {settings.get('home_label')}",
    )


# --------------------------------------------------------------------------
# static SPA
# --------------------------------------------------------------------------

_static = Path(config.static_dir)
if _static.is_dir():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str, request: Request):
        """Client-side routing: anything not an API route serves the shell."""
        if full_path.startswith(("api/", "healthz", "sondaro.ics")):
            raise HTTPException(status_code=404, detail="not found")
        candidate = _static / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_static / "index.html")
else:

    @app.get("/")
    async def no_ui():
        return JSONResponse(
            {
                "detail": "UI not built. Run `npm run build` in web/, or use the "
                "docker image which builds it for you.",
                "api": "/api/docs",
            },
            status_code=200,
        )
