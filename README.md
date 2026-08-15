<!-- cSpell:words pytest -->

# Sondaro

artists from Lidarr, listening from MusicBrainz. combine the 2 to find concerts near home and when traveling

## Where things are

| Path              | What's in it                                             |
| ----------------- | -------------------------------------------------------- |
| `api/scoring.py`  | The ranking rules. Pure functions, no I/O. Start here.   |
| `api/settings.py` | Everything tunable from the UI, with defaults and ranges |
| `api/scan.py`     | Matches listings to your library, builds ranked results  |
| `api/queue.py`    | Which API calls to make, in what order, how often        |
| `api/worker.py`   | Background loop that drains the queue                    |
| `api/providers/`  | One file per external service                            |
| `api/main.py`     | HTTP routes                                              |
| `web/src/`        | React UI                                                 |
| `tests/features/` | Behavior specs in plain English, good for orientation    |

## Providers

| Provider (\* required) | Role                                              | Limit     |
| ---------------------- | ------------------------------------------------- | --------- |
| Ticketmaster \*        | Everything. The only one that can search broadly. | 5,000/day |
| JamBase                | Only for artists Ticketmaster found nothing for   | 500/month |
| OpenRouteService       | Driving times, place search                       | 2,000/day |

## Configuration

secrets and urls live in `.env`, everything else lives in the database and is edited at `/settings`. env values only seed the database on first run, so after that, editing `.env` needs a redeploy

- **editable in the UI**: home location, how far ahead to look, the driving-hour budgets, cross-border distance, alert threshold, mute-until
- **env only**: every api key and token, plus `LIDARR_URL`, `NTFY_URL` and `TZ`

## Notifications

- the `sondaro` topic gets new shows, filtered by the alert threshold and capped per run.
- the `services` topic gets health problems only, and is never muted by the alert settings.

## Calendar

`/calendar.ics` and `/trips/{id}.ics` are subscribe urls for any calendar app. add `?min_score=0.5` to filter the subscription without changing what the UI shows.

## Running it

```sh
make sondaro-deploy    # from the repo root, first install and every update
make sondaro-logs
make sondaro-test
```

a pull-based updater won't work here

local development:

```sh
python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m pytest -q
npm --prefix web install && npm --prefix web test
```

## Things that will confuse you later

- open route service takes coordinates as `lon,lat`, backwards from everywhere else in the codebase
- `borders.db` is built during `docker build`, not at runtime. rebuild to regenerate
- ticketmaster caps paging at 1,000 results, so sweeps split their date window and retry when they hit it
- `api/queue.py` is a database table, not python's `queue` module
- Lidarr access is locked to get plus two specific paths in `api/providers/lidarr.py`, and anything else raises
