<!-- cSpell:words pytest -->

# Sondaro

artists from Lidarr, listening from MusicBrainz. combine the 2 to find concerts near home and when traveling

## Providers

| Provider (\* required) | Role                                              | Limit     |
| ---------------------- | ------------------------------------------------- | --------- |
| Ticketmaster \*        | Everything. The only one that can search broadly. | 5,000/day |
| JamBase                | Only for artists Ticketmaster found nothing for   | 500/month |
| OpenRouteService       | Driving times, place search                       | 2,000/day |

## Configuration

secrets and urls live in `.env`, everything else lives in the database and is edited at `/settings`. env values only seed the database on first run, so after that, editing `.env` needs a redeploy

home comes from home assistant when `HASS_URL` and `HASS_TOKEN` are set — coordinates, name, country and timezone, all from the one `/api/config` call.

## Trips

a trip is an itinerary of **legs**, one row per country plus one per city once you know which cities. the distinction is the whole point:

- a country with **no city named** is one you're going to but haven't planned, so the whole country stays in play and a show just over its border still counts as a detour
- naming a city **anchors that country and no other**. booking Barcelona says nothing about France, so a Geneva show is still measured from the French border it sits on rather than 350 miles from Barcelona
- each leg can carry its own dates, so a fortnight split between two cities is swept and scored per city rather than per trip

trips share one page. everything they turned up is a single feed, filtered by trip, country or score from the sidebar. there is no per-trip page: "what could i see while i'm away" is one question, and it was being asked once per trip.

a country showing nothing says why, per country: still being swept, deliberately not swept because it's your home country, or genuinely nothing on. all three look identical as a blank list, and only the first is worth waiting out.

**a leg's dates bound what gets fetched and what gets scored.** a show a month after you leave a city is not "in that city", so it doesn't appear — widen the leg if you'd actually extend the trip.

cities are picked from a geocoder typeahead, never typed. a free-text city that doesn't resolve is a leg that silently matches nothing.

## Notifications

- the `sondaro` topic gets new shows, filtered by the alert threshold and capped per run.
- the `services` topic gets health problems only, and is never muted by the alert settings.

## Calendar

`/sondaro.ics` is the one subscribe url, for any calendar app. **only shows you've marked as bought are in it** — mark one and it appears, unmark it and it goes. suggestions stay in the app; a calendar full of maybes is one you stop trusting.

it's served inline with `no-cache` and a one-hour `REFRESH-INTERVAL`, so subscribe to it rather than downloading it. a downloaded copy was right the day you saved it and has been drifting ever since. the calendar button in the ui hands you the url and a `webcal://` handoff.

every entry is `CONFIRMED` and `OPAQUE`, because every entry is something you're actually doing.

times are absolute wherever ticketmaster gave us the instant, so an out-of-town show doesn't render hours out when you read it from home. listings with doors still tba stay floating rather than being given an invented timezone.

the feed reads `purchased` joined to `events` directly, not the scored feeds — a decision you made must not depend on the show still clearing a floor, still sitting inside a trip you might have deleted, or still being in range of a home you might have moved.

## Buying a ticket

marking a show as bought is a decision, not a score, so it overrides everything: it ignores every score floor, survives the events cache being swept and rewritten, and shows up even on days you're away.

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
- affinity is charged once in the score and once again in the driving radius it's measured against, so `shape_home` is deliberately shallow — see the comment on it before making it steeper
- every artist gets a ticketmaster lookup, but only the top 60 by affinity earn the jambase fall-through. jambase bills past its quota
- a task that fails *after* a jambase call completes is not retried, because the retry would buy the same listing again. `queue.discarded()` surfaces those instead
- `queue.enqueue` does **not** move an existing task's due date. planning is re-run on every start, so pulling dates forward would let a redeploy re-arm the whole library and re-buy answers. work that really needs re-arming deletes the tasks (`clear_coverage`) or re-dates them explicitly
- an artist lookup that came back empty waits a week, not a day. nothing anywhere on earth for six months does not change overnight, and on the gap-fill slice a daily recheck buys the same "nothing" from jambase every morning
