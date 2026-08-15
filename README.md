# Sondaro

Concert tracking for a Lidarr/Navidrome library, with a trip planner.

Lidarr knows which artists you follow. Navidrome's scrobbles know which ones you
actually listen to. Neither knows when any of them are playing near you. Sondaro
joins those up and ranks shows by **how much you listen to the artist** and **how
far you'd realistically travel on that particular day**.

- **Near home** — everything reachable from where you live, with ntfy push for
  new announcements.
- **Trips** — pick countries and rough dates, get back who's playing. Trips are
  multi-country, cities are optional, and a show just over a border counts as a
  detour rather than a disqualification.

---

## The scoring model

```text
score = affinity × date_fit × reach_fit
```

Multiplicative, all three in `[0,1]`, so one bad axis kills a candidate without a
pile of tuning weights and every component stays explainable in the UI.

### affinity

Log-scaled lifetime play count from ListenBrainz, falling back to Last.fm,
floored at `0.25` for artists in Lidarr you've never scrobbled. Log rather than
linear so one obsessively-played artist doesn't flatten everything else to zero.

Artists you *don't* own can appear too, sourced from Last.fm's similarity graph
and capped at `0.45` affinity so a suggestion can never outrank a real favourite.
They're always flagged `not in your library`.

### reach_fit at home — measured in driving hours

```text
shape(A)  = 0.12 + 0.88·A²
reach     = base_hours × shape(affinity)
reach_fit = 1 / (1 + (drive_hours / reach)⁴)
```

**Hours, not miles.** Home→DC is 227 mi and Home→Millbrook is 356 mi; they
look far apart on a map and much closer from behind a wheel. Ranking on distance
would order them wrongly.

Base hours depend on the day, because a Saturday justifies a longer drive than a
Tuesday:

| Show falls on | Base |
| --- | --- |
| Mon–Thu | 3.0 h |
| Sun | 3.75 h |
| Fri–Sat | 4.5 h |

Anything past **5 hours** also carries a `major planning` flag — visible, just no
longer pretending to be a casual decision.

What that produces from Home:

| Artist | Springfield 0.5h | Nearby 1.3h | Fairview 2.6h | DC 4.4h | Millbrook 6.0h |
| --- | --- | --- | --- | --- | --- |
| favourite, weeknight | 1.00 | 0.97 | 0.64 | 0.18 | 0.06 ⚑ |
| favourite, weekend | 1.00 | 0.99 | 0.90 | 0.52 | 0.24 ⚑ |
| mid-tier, weeknight | 0.98 | 0.51 | 0.06 | ~0 | ~0 |
| mid-tier, weekend | 1.00 | 0.84 | 0.25 | 0.04 | ~0 |
| unlistened, weekend | 0.86 | 0.12 | ~0 | ~0 | ~0 |

The four base-hour values and the flag threshold are editable in Settings.

### reach_fit on a trip — measured from a border

No weekday split (you're already out) and a far gentler curve, since distance is
cheap once you're travelling.

- **Inside a country you're visiting** → `1.0`, flat. You pick countries first
  and cities afterwards, so nothing in-country is ever penalised.
- **Inside, with cities named** → decays from the nearest named city but is
  **floored at 0.6**, so elsewhere-in-country stays clearly viable.
- **Outside every visited country** → measured from the **nearest border** of any
  of them, base 100 mi, and always flagged `not on your itinerary (Country)`.

A France + Spain trip puts Geneva at ~2 mi from the French border, so it scores
≈1.0 and shows up flagged as Switzerland. Berlin is ~350 mi from the nearest
French border and drops out entirely.

Distance is to the **border**, not a centroid — France's centroid is 400 mi from
Geneva while its border is 2 mi away.

### date_fit

| Trip type | Behaviour |
| --- | --- |
| Home | always `1.0` |
| Flexible dates | `1.0` inside the window, decaying to a `0.5` floor across the slack, `0` beyond |
| Strict dates | binary — `1.0` inside, `0` outside |

Strict is for trips already booked and immovable.

---

## Providers

| Provider | Role | Budget |
| --- | --- | --- |
| **Ticketmaster Discovery** | primary; the only one that sweeps | free, 5,000/day |
| **JamBase** | gap-filler for artists Ticketmaster misses | free Developer tier, **1,000/month** |
| **OpenRouteService** | home → city driving times, geocoding | free, 2,000/day |

Only Ticketmaster is required. Without OpenRouteService, drive times fall back to
`great-circle × 1.25 ÷ 55 mph` and every affected row is marked *estimated*.

### ⚠ JamBase bills for overage

JamBase's Developer tier **does not return 429 above its monthly quota — it
charges $0.05 per call**. There is no protective error from their end, so
Sondaro's own counter is the only thing between a bug and an invoice. Because of
that:

- The cap is **500/month**, not 1,000. The gap is deliberate headroom.
- A hard ceiling of 900 is compiled in; no setting can raise the cap past it.
- Calls are reserved *before* dispatch, in a single guarded `UPDATE`, so two
  workers can't both take the last slot.
- **Attempts are counted, not successes**, and reservations are never refunded on
  failure — a failed call may still have been billed.
- **Retries are disabled** for it. A retry is another bill, not a free second go.
- It is **only ever called for artists Ticketmaster returned nothing for**.
  Duplicating free coverage would be the worst possible use of ~16 calls a day.
- Its future window is 6 months, so queries clamp to whichever is nearer — the
  horizon or that limit — rather than paying for an unanswerable question.
- It stays **disabled unless `JAMBASE_BASE_URL` is set explicitly**. Guessing at
  a base URL would spend real money discovering the guess was wrong.

Its Developer tier also has no External Identifiers, so it can't match on
MusicBrainz IDs and is a name search like Ticketmaster's — which is why it's a
gap-filler rather than the precision layer it first looked like.

### OpenRouteService host migration

HeiGIT is retiring `api.openrouteservice.org` in favour of `api.heigit.org`.
Sondaro tries the new host first, falls back to the old one, and remembers
whichever answered so the probe happens once. Set `ORS_BASE_URL` to pin a host.

Note that ORS takes coordinates as **lon,lat** — reversed from everywhere else in
this codebase. There is a test for it.

---

## Lidarr is read-only, enforced in code

Lidarr has no scoped API keys: one key, full access. So read-only can't be a
property of the credential and is a property of the client instead.

`api/providers/lidarr.py` allows exactly `GET` and exactly two paths
(`/api/v1/artist`, `/api/v1/health`). Anything else raises **before a socket is
opened**. Adding a write means deliberately editing an allowlist.

This protects against *this app* writing to Lidarr. It does not protect the key
— anyone holding it still has full access, which is why it lives in the env file
and nowhere else.

---

## Configuration: what lives where

**Secrets and wiring in env. Everything behavioural in the database.**

Env vars seed the settings table once on first run and are never consulted again
once a value has been set in the UI.

| UI-editable at `/settings` | env-only, never rendered |
| --- | --- |
| Home location and label | `LIDARR_API_KEY` |
| Horizon (default 180 days) | `TICKETMASTER_API_KEY` |
| Driving-hour bases (3.0 / 3.75 / 4.5) | `JAMBASE_API_KEY`, `JAMBASE_BASE_URL` |
| `major planning` threshold (5 h) | `ORS_API_KEY`, `ORS_BASE_URL` |
| Cross-border budget (100 mi) | `NTFY_TOKEN` |
| Alert threshold, per-run cap, mute-until | `LIDARR_URL`, `NTFY_URL`, topics |
| Whether suggestions can alert | `TZ` |

Settings shows keys as **configured / not configured** with live quota usage, and
never renders or accepts a value. Changing a key stays a deploy, which is the
right amount of friction for something that grants access.

### Moving house

Changing home invalidates work rather than just changing a number, so the UI says
so:

- Drive times are keyed on origin, so a new home simply misses and re-resolves.
  Old rows stay put — move back and they're reused rather than re-paid for.
- Home coverage is invalidated and a re-fill is queued.
- Status reports *re-indexing for &lt;new place&gt;* rather than quietly serving
  scores computed for where you used to live.

The location field is a search box backed by the ORS geocoder. Raw coordinates
remain editable as a fallback.

---

## How the index fills

Not a nightly scan. A persistent priority queue drained by a single worker that
sleeps until the next task is due, so an empty queue costs no CPU.

```text
priority = urgency × importance
urgency  = 1 / (1 + days_out/30)
```

Near-term windows and favourite artists drain first, so the UI is useful within
minutes of a cold start rather than hours.

Refresh cadence by horizon — this is what keeps steady-state cost flat:

| Horizon | Refetch every |
| --- | --- |
| 0–14 days | 1 day |
| 15–60 days | 3 days |
| 61+ days | 14 days |

A show four months out isn't going to change this week, so it doesn't get a call
this week. Steady state lands around 20–40 Ticketmaster calls/day against a
5,000/day budget. The cold fill is the expensive part, and it's deliberately
allowed to take its time.

Only listings that **match your library** are stored — keeping every music event
in a 450-mile radius would mean tens of thousands of rows about artists you've
never heard of, on a 256 MB container. The cost is that an artist added to Lidarr
today isn't matched against already-fetched listings, so a library sync re-arms
the sweeps when the roster changes rather than making you wait out a 14-day
cadence.

---

## Notifications

Two ntfy topics, deliberately separate:

| Topic | Carries | Gated? |
| --- | --- | --- |
| `sondaro` | new show matches | yes — by the alert threshold, and capped per run |
| `services` | health and degradation | **never** |

Gig alerts are frequent and optional; infrastructure alerts are rare and
actionable. Mixing them teaches you to ignore both. Muting silences gig alerts
only — it should never hide that Lidarr is down.

Health alerts dedupe on *state change*, so a six-hour outage is one push, not
seventy-two, and recovery is announced too.

---

## Calendar feeds

Format-neutral subscribe URLs — Google Calendar, Outlook, Fastmail, Thunderbird,
anything that speaks RFC 5545.

```text
/calendar.ics                  everything near home
/calendar.ics?min_score=0.5    only what's worth a drive
/trips/3.ics?min_score=0.35    one trip
```

`min_score` filters the subscription without changing what the app shows, so you
can keep a permissive UI and a strict calendar.

---

## API

```text
GET    /api/status                 coverage, queue depth, quotas, degradation
GET    /api/home                   ranked shows near home, grouped by month
POST   /api/sync                   force a library refresh now
GET    /api/trips                  list
POST   /api/trips                  create (multi-country)
GET    /api/trips/{id}             every option, grouped by date
POST   /api/trips/{id}/rescan      re-queue the country sweeps
DELETE /api/trips/{id}
GET    /api/settings               specs + values + credential presence
PATCH  /api/settings               takes effect next scan, no restart
POST   /api/settings/home          move house (invalidates coverage)
GET    /api/geocode?q=             place search
GET    /api/countries              from the border index
GET    /api/docs                   OpenAPI
```

---

## Development

```sh
# python
python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m pytest -q

# web
npm --prefix web install
npm --prefix web test
npm --prefix web run build

# both, from the repo root
make sondaro-test
```

**No test ever touches a real provider.** `tests/conftest.py` blocks
`connect`/`connect_ex` on the IP families plus DNS resolution for the whole
session, so httpx, urllib and raw sockets all fail loudly. It's deliberately
surgical — replacing `socket.socket` wholesale breaks asyncio's own self-pipe
before a test can run. An unstubbed URL raises rather than returning empty,
because a stub that silently returns nothing is indistinguishable from a quiet
weekend. `tests/test_harness.py` tests the guard itself.

`web/package.json` pins an `overrides` entry deduping `vite`, because vitest
ships a nested copy and plugin types otherwise resolve to two different modules
and fail typecheck.

### The border index

`scripts/build_borders.py` bakes Natural Earth 110m boundaries into a read-only
SQLite R\*Tree at image-build time. Countries don't move, so this is reference
data baked in, not a cache: nothing is parsed at startup, no polygons sit in
memory, and it never needs invalidating.

`fetch_geojson` is the only networked function and is separate from `build()` on
purpose, so tests exercise the real builder against inline polygons. One test
asserts the R\*Tree gives the same answer as a brute-force scan of every segment
— the index may change the work done, never the result.

---

## Deploying

```sh
make sondaro-deploy     # first install and every update
make sondaro-logs
make sondaro-restart
```

`deploy.sh` rsyncs this folder to the server and rebuilds. It excludes
`.env` from both the copy and the `--delete`, so the VM's keys survive every
deploy. On a first run it creates the `proxy` network, seeds `.env` from
`.env.example`, and stops with a message rather than starting a container that
would fail on missing keys.

`docker compose pull` is a no-op for
a locally-built image, so **`make sondaro-deploy` is the update path, not
`sondaro-update`**.

No host port is published. Caddy reaches the container by service name over the
shared `proxy` network, so Sondaro consumes no entry in the host port table. The
`7373` in the Caddyfile is the container-internal port: container network
namespaces are isolated, so any number of containers can listen on it at once.

The tradeoff is no direct `192.168.1.24:PORT` access for debugging — use
`make sondaro-logs` or `docker exec`.

---

## Known limits

- **Ticketmaster mostly sees larger ticketed venues.** For an indie-heavy library
  the results are a floor, not a ceiling. JamBase closes some of that gap; 500
  calls a month only closes so much.
- **JamBase can't use MusicBrainz IDs** on the free tier, so its matching is
  name-based and subject to the same ambiguity as Ticketmaster's.
- **Discovery paging caps at 1,000 results per query.** Sweeps halve their window
  and retry when they hit it, and say so on the status page if a single day still
  overflows — a truncated sweep and an empty one otherwise look identical.
- **Only matched listings are stored**, so the event cache is not a general
  concert database and can't be mined for artists you haven't added yet.
