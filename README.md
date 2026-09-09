# Sondaro

artists from Lidarr, listening from MusicBrainz. combine the 2 to find concerts near home and when traveling

## Requirements

1. Lidarr setup with music in it
1. TicketMaster developer account
1. (Debian-based) Linux setup running docker and compose. i use a network accessible vm
1. Tailnet

optionally:

1. ListenBrainz and/or Last.fm accounts. if you get Lidarr to scrobble to them, your preferences are easier to understand
1. OpenRouteService for country border GIS data (i used [HeiGIT](https://account.heigit.org/))
1. Home Assistant for home location. since this is a project for me and i already have it set up, it's easier to change my location in 1 place rather than 2 when i move. it grabs lat/lon, country, and timezone
1. JamBase account for smaller venues and artists. 1000 api calls per month then $0.05 per call, so i've limited it to 500 in the app.
1. ntfy for notifications. i'll be honest i don't remember what i had in mind, the calendar subscription works better

## Providers

| Provider (\* required) | Role                                              | Limit     |
| ---------------------- | ------------------------------------------------- | --------- |
| Ticketmaster \*        | Everything. The only one that can search broadly. | 5,000/day |
| JamBase                | Only for artists Ticketmaster found nothing for   | 500/month |
| OpenRouteService       | Driving times, place search                       | 2,000/day |

## Configuration

secrets and urls live in `.env`, everything else lives in the database and is edited at `/settings`. env values only seed the database on first run, so after that, editing `.env` needs a redeploy

## Trips

if you book a trip to multiple countries and only select cities in one country, sondaro assumes you haven't booked that leg of the trip yet and will suggest all events in the country instead of just the ones in the named cities

## Notifications

- the `sondaro` topic gets new shows, filtered by the alert threshold and capped per run.
- the `services` topic gets health problems only, and is never muted by the alert settings.

## Calendar

a `webcal://` subscription of events you've marked as purchased

## Running it

```sh
make deploy SONDARO_HOST=you@your-vm    # first install and every update
make logs
make test
```

the image is built locally, so `docker compose pull` is a no-op — `make deploy` is the only update path

local development:

```sh
python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m pytest -q
npm --prefix web install && npm --prefix web test
```

## Things that will confuse you later

- open route service takes coordinates as `lon,lat`, backwards from everywhere else in the codebase
- every distance in the codebase is km. it was miles until the units were converted in one pass, and `_migrate` converts the cached drive times and the border budget rather than re-fetching them
- `borders.db` is built during `docker build`, not at runtime. rebuild to regenerate
- ticketmaster caps paging at 1,000 results, so sweeps split their date window and retry when they hit it
- `api/queue.py` is a database table, not python's `queue` module
- Lidarr access is locked to get plus two specific paths in `api/providers/lidarr.py`, and anything else raises
- only the top 60 artists by affinity get the jambase fall-through
- an artist lookup that came back empty waits a week
