# Sondaro

Finds concerts for the artists in your Lidarr library, ranked by how much you
actually listen to them and how far you'd realistically travel to see them.

Two views:

- Near home: what's reachable from where you live, with ntfy push for new
  announcements.
- Trips: pick countries and dates, get back who's playing while you're there.

It only ever suggests artists you added to Lidarr yourself.

## Where things are

| Path | What's in it |
| --- | --- |
| `api/scoring.py` | The ranking rules. Pure functions, no I/O. Start here. |
| `api/settings.py` | Everything tunable from the UI, with defaults and ranges |
| `api/scan.py` | Matches listings to your library, builds ranked results |
| `api/queue.py` | Which API calls to make, in what order, how often |
| `api/worker.py` | Background loop that drains the queue |
| `api/providers/` | One file per external service |
| `api/main.py` | HTTP routes |
| `web/src/` | React UI |
| `tests/features/` | Behavior specs in plain English, good for orientation |

## How ranking works

```text
score = affinity × date_fit × reach_fit
```

All three are 0 to 1, multiplied together, so one bad axis sinks a result.

`affinity` is a log-scaled play count from ListenBrainz, with Last.fm as a
fallback. Artists with no scrobbles floor at 0.25.

`reach_fit` at home is based on driving hours rather than miles. Home to DC
and Home to Millbrook differ by 129 miles but much less in hours, so ranking on
distance gets them backwards. How far you'll go scales with how much you like
the artist, and with the day of week, since Friday and Saturday justify a longer
drive than a Tuesday. A show that's too far just scores low and sinks. Nothing
badges it.

`reach_fit` on a trip is a flat 1.0 anywhere inside a country you're visiting,
because you pick countries first and cities later. Outside those countries it's
measured from the nearest border, not the centroid. France's center is 400 miles
from Geneva while its border is 2, so Geneva during a France trip shows up
flagged as a detour, and Berlin doesn't show up at all.

`date_fit` is 1.0 inside the trip window. Flexible trips decay to 0.5 across the
slack days, and strict trips are all or nothing.

To change any of this, edit `api/scoring.py`. The numbers you're most likely to
want to touch are already exposed in Settings via `api/settings.py`.

## Providers

| Provider | Role | Limit |
| --- | --- | --- |
| Ticketmaster | Everything. The only one that can search broadly. | 5,000/day |
| JamBase | Only for artists Ticketmaster found nothing for | 500/month |
| OpenRouteService | Driving times, place search | 2,000/day |

Only Ticketmaster is required. Without OpenRouteService, drive times become
rough estimates and are labeled as such.

### JamBase costs money if you exceed the quota

It bills $0.05 per call past 1,000 a month instead of returning an error.
Sondaro caps itself at 500 so there's headroom for a bug, counts attempts rather
than successes, never retries, and won't run at all unless `JAMBASE_BASE_URL` is
set explicitly. If you're changing anything in `api/providers/jambase.py` or
`api/usage.py`, that's why it's written so defensively.

## Configuration

Secrets and URLs live in `.env`. Everything else lives in the database and is
edited at `/settings`. Env values only seed the database on first run, so after
that, editing `.env` does nothing for those fields.

Editable in the UI: home location, how far ahead to look, the driving-hour
budgets, cross-border distance, alert threshold, mute-until.

Env only: every API key and token, plus `LIDARR_URL`, `NTFY_URL` and `TZ`.

API keys are never shown in the UI or returned by the API, only whether they're
present. Changing one means a redeploy.

Moving home invalidates cached coverage and re-resolves drive times. They're
keyed by origin, so the old ones stay on file if you move back.

## Notifications

The `sondaro` topic gets new shows, filtered by the alert threshold and capped
per run. The `services` topic gets health problems only, and is never muted by
the alert settings.

## Calendar

`/calendar.ics` and `/trips/{id}.ics` are subscribe URLs for any calendar app.
Add `?min_score=0.5` to filter the subscription without changing what the UI
shows.

## How it fills its index

A background worker drains a priority queue instead of doing one big nightly
scan. Near-term dates and favorite artists get fetched first, so it's useful
within minutes of starting even though a full 6-month fill takes hours.

Things get refetched at a rate matching how fast they change: daily inside two
weeks, every 3 days out to two months, every 2 weeks beyond that. Steady state is
20 to 40 Ticketmaster calls a day out of 5,000.

Only listings matching your library are stored, which keeps the database small.
The tradeoff is that adding an artist to Lidarr doesn't retroactively match
listings already fetched, so a library sync re-arms the sweeps when your roster
changes.

## Running it

```sh
make sondaro-deploy    # from the repo root, first install and every update
make sondaro-logs
make sondaro-test
```

a pull-based updater does not work here. It runs
`docker compose pull`, which does nothing for a locally built image.

Local development:

```sh
python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m pytest -q
npm --prefix web install && npm --prefix web test
```

No test ever contacts a real API. `tests/conftest.py` blocks outbound
connections for the whole session, and an unstubbed URL raises. If you add a
test that needs a provider response, register a stub route rather than loosening
the guard.

## Things that will confuse you later

- ORS takes coordinates as `lon,lat`, backwards from everywhere else in the
  codebase.
- `borders.db` is built during `docker build`, not at runtime. Country borders
  don't change, so it's baked into the image. Rebuild to regenerate it.
- Ticketmaster caps paging at 1,000 results, so sweeps split their date window
  and retry when they hit it. Otherwise a truncated search looks exactly like a
  quiet week.
- `api/queue.py` is a database table, not Python's `queue` module.
- Lidarr access is locked to GET plus two specific paths in
  `api/providers/lidarr.py`, and anything else raises. Lidarr has no read-only
  API keys, so it's enforced here instead.
