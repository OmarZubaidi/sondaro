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
    routing,
    scan,
    settings,
    usage,
    worker,
)
from .config import config
from .util import now_iso, parse_date, today

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("sondaro")

_sync_lock = asyncio.Lock()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
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


@app.get("/api/home")
async def api_home(
    min_score: float | None = Query(None, ge=0.0, le=1.0),
    discovery: bool = Query(True),
):
    candidates = scan.home_candidates(include_discovery=discovery)
    if min_score is not None:
        candidates = [c for c in candidates if c.total >= min_score]

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
        result["discovery"] = await library.refresh_discovery()
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
    return {
        "id": row["id"],
        "name": row["name"],
        "countries": scan.trip_countries(row),
        "cities": scan.trip_cities(row),
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "flex_before": row["flex_before"],
        "flex_after": row["flex_after"],
        "strict_dates": bool(row["strict_dates"]),
        "discovery": bool(row["discovery"]),
        "scanned_at": row["scanned_at"],
    }


@app.get("/api/trips")
async def api_trips():
    rows = db.query("SELECT * FROM trips ORDER BY start_date DESC")
    return {"trips": [_trip_summary(row) for row in rows]}


@app.post("/api/trips", status_code=201)
async def api_create_trip(payload: dict = Body(...)):
    name = str(payload.get("name") or "").strip()
    countries = [str(c).strip().upper() for c in (payload.get("countries") or []) if str(c).strip()]
    start = parse_date(payload.get("start_date"))
    end = parse_date(payload.get("end_date"))

    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not countries:
        raise HTTPException(status_code=400, detail="at least one country is required")
    if any(len(c) != 2 for c in countries):
        raise HTTPException(status_code=400, detail="countries must be 2-letter ISO codes")
    if not (start and end):
        raise HTTPException(status_code=400, detail="dates must be YYYY-MM-DD")
    if end < start:
        raise HTTPException(status_code=400, detail="end date is before start date")

    strict = bool(payload.get("strict_dates", False))
    flex_before = 0 if strict else max(0, min(int(payload.get("flex_before") or 0), 30))
    flex_after = 0 if strict else max(0, min(int(payload.get("flex_after") or 0), 30))
    cities = ",".join(str(c).strip() for c in (payload.get("cities") or []) if str(c).strip())

    trip_id = db.execute(
        "INSERT INTO trips(name, countries, cities, start_date, end_date, flex_before, "
        "flex_after, strict_dates, discovery, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            name,
            ",".join(countries),
            cities,
            start.isoformat(),
            end.isoformat(),
            flex_before,
            flex_after,
            1 if strict else 0,
            1 if payload.get("discovery", True) else 0,
            now_iso(),
        ),
    )

    row = _trip_or_404(trip_id)
    _, _, window_start, window_end = scan.trip_window(row)
    queue.plan_trip(trip_id, countries, window_start, window_end)
    worker.worker.nudge()

    return _trip_summary(row)


@app.get("/api/trips/{trip_id}")
async def api_trip(trip_id: int):
    row = _trip_or_404(trip_id)
    candidates = scan.trip_candidates(row)

    # grouped by date, every option shown — the UI chooses nothing
    by_date: dict[str, list] = {}
    for candidate in candidates:
        by_date.setdefault(candidate.event.date, []).append(scan.serialise(candidate))

    scope_prefix = f"trip:{trip_id}:"
    _, _, window_start, window_end = scan.trip_window(row)
    expected = len(scan.trip_countries(row)) * len(
        queue.slice_windows(max(window_start, today()), window_end)
    )

    return {
        "trip": _trip_summary(row),
        "total": len(candidates),
        "dates": [
            {"date": day, "shows": shows} for day, shows in sorted(by_date.items())
        ],
        "coverage": queue.coverage_fraction(scope_prefix, expected),
    }


@app.post("/api/trips/{trip_id}/rescan")
async def api_rescan_trip(trip_id: int):
    row = _trip_or_404(trip_id)
    _, _, window_start, window_end = scan.trip_window(row)
    queue.clear_coverage(f"trip:{trip_id}:")
    planned = queue.plan_trip(trip_id, scan.trip_countries(row), window_start, window_end)
    db.execute("UPDATE trips SET scanned_at = ? WHERE id = ?", (now_iso(), trip_id))
    worker.worker.nudge()
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
        queue.plan_home(*settings.home(), settings.get("home_horizon_days"))
    worker.worker.nudge()
    return {"updated": updated}


@app.post("/api/settings/home")
async def api_set_home(payload: dict = Body(...)):
    """Moving house invalidates work rather than just changing a number, so
    this is a distinct endpoint that says so in its response."""
    lat, lon = payload.get("lat"), payload.get("lon")
    if lat is None or lon is None:
        raise HTTPException(status_code=400, detail="lat and lon are required")

    settings.set_value("home_lat", lat)
    settings.set_value("home_lon", lon)
    if payload.get("label"):
        settings.set_value("home_label", payload["label"])

    worker.relocate(settings.get("home_lat"), settings.get("home_lon"))
    return {
        "home": {
            "lat": settings.get("home_lat"),
            "lon": settings.get("home_lon"),
            "label": settings.get("home_label"),
        },
        "reindexing": True,
        "note": "drive times are keyed on origin, so they re-resolve for the new home",
    }


@app.get("/api/geocode")
async def api_geocode(q: str = Query(..., min_length=2)):
    return {"results": await routing.geocode(q)}


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
        headers={"Cache-Control": "public, max-age=1800"},
    )


@app.get("/calendar.ics")
async def home_calendar(min_score: float = Query(0.0, ge=0.0, le=1.0)):
    candidates = [c for c in scan.home_candidates() if c.total >= min_score]
    return _calendar_response(candidates, f"Sondaro — {settings.get('home_label')}")


@app.get("/trips/{trip_id}.ics")
async def trip_calendar(trip_id: int, min_score: float = Query(0.0, ge=0.0, le=1.0)):
    row = _trip_or_404(trip_id)
    candidates = [c for c in scan.trip_candidates(row) if c.total >= min_score]
    return _calendar_response(candidates, f"Sondaro — {row['name']}")


# --------------------------------------------------------------------------
# static SPA
# --------------------------------------------------------------------------

_static = Path(config.static_dir)
if _static.is_dir():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str, request: Request):
        """Client-side routing: anything not an API route serves the shell."""
        if full_path.startswith(("api/", "healthz", "calendar.ics")):
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
