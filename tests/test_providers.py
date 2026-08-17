"""Provider clients. Every response is stubbed; `conftest.no_network` makes a
real connection impossible, so a drifting stub fails loudly rather than quietly
reaching out.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db, http, usage  # noqa: E402
from api.config import config  # noqa: E402
from api.util import day_key  # noqa: E402
from api.providers import jambase, lidarr, ticketmaster  # noqa: E402

TODAY = date(2026, 9, 1)


def tm_event(event_id="tm1", name="The National", day="2026-09-10", city="Fairview"):
    return {
        "id": event_id,
        "name": f"{name} — 2026 Tour",
        "url": f"https://ticketmaster.com/{event_id}",
        "dates": {"start": {"localDate": day, "localTime": "20:00:00"}},
        "_embedded": {
            "venues": [
                {
                    "name": "The Fillmore",
                    "city": {"name": city},
                    "state": {"stateCode": "KS"},
                    "country": {"countryCode": "US"},
                    "location": {"latitude": "37.5", "longitude": "-97.0"},
                }
            ],
            "attractions": [
                {
                    "name": name,
                    "id": "K8vZ917",
                    "externalLinks": {"musicbrainz": [{"id": "f22942a1-mbid"}]},
                }
            ],
        },
    }


def tm_page(events, total_pages=1):
    return {"_embedded": {"events": events}, "page": {"totalPages": total_pages}}


# --------------------------------------------------------------------------
# Lidarr: read-only enforced structurally
# --------------------------------------------------------------------------


async def test_lidarr_refuses_writes_before_opening_a_socket(routes, monkeypatch):
    monkeypatch.setattr(config, "lidarr_api_key", "key")

    for verb in ("POST", "PUT", "DELETE", "PATCH"):
        with pytest.raises(lidarr.ReadOnlyViolation):
            await lidarr._request(verb, "/api/v1/artist")

    # nothing was dispatched — the guard runs before any request is built
    assert routes.calls == []


async def test_lidarr_refuses_paths_outside_the_allowlist(routes, monkeypatch):
    monkeypatch.setattr(config, "lidarr_api_key", "key")

    for path in ("/api/v1/album", "/api/v1/command", "/api/v1/rootfolder"):
        with pytest.raises(lidarr.ReadOnlyViolation):
            await lidarr._request("GET", path)

    assert routes.calls == []


async def test_lidarr_lists_artists(routes, monkeypatch):
    monkeypatch.setattr(config, "lidarr_api_key", "key")
    routes.add(
        "/api/v1/artist",
        [
            {"artistName": "The National", "foreignArtistId": "abc", "id": 1, "monitored": True},
            {"artistName": "Unmonitored", "foreignArtistId": "def", "id": 2, "monitored": False},
            {"foreignArtistId": "ghi", "id": 3, "monitored": True},  # no name
        ],
    )

    artists = await lidarr.list_artists()
    assert [a["name"] for a in artists] == ["The National"]

    everything = await lidarr.list_artists(monitored_only=False)
    assert [a["name"] for a in everything] == ["The National", "Unmonitored"]


async def test_lidarr_reports_how_much_of_an_artist_is_on_disk(routes, monkeypatch):
    """Files, not the catalogue: trackCount is everything Lidarr knows exists,
    which says nothing about whether you own any of it."""
    monkeypatch.setattr(config, "lidarr_api_key", "key")
    routes.add(
        "/api/v1/artist",
        [
            {
                "artistName": "Sabaton",
                "foreignArtistId": "abc",
                "id": 1,
                "monitored": True,
                "statistics": {"trackCount": 300, "trackFileCount": 212},
            },
            {"artistName": "Nothing Yet", "foreignArtistId": "def", "id": 2, "monitored": True},
        ],
    )

    artists = await lidarr.list_artists()

    assert [a["tracks"] for a in artists] == [212, 0]


async def test_lidarr_without_a_key_returns_nothing_rather_than_erroring(routes, monkeypatch):
    monkeypatch.setattr(config, "lidarr_api_key", "")
    assert await lidarr.list_artists() == []
    assert routes.calls == []


# --------------------------------------------------------------------------
# Ticketmaster
# --------------------------------------------------------------------------


def test_ticketmaster_parses_a_listing():
    parsed = ticketmaster.parse_event(tm_event())
    assert parsed.artist_name == "The National"
    assert parsed.date == "2026-09-10"
    assert parsed.time == "20:00"
    assert parsed.city == "Fairview"
    assert parsed.country == "US"
    assert parsed.mbid == "f22942a1-mbid"
    assert parsed.id == "ticketmaster:tm1"


def test_ticketmaster_skips_undated_listings():
    assert ticketmaster.parse_event({"id": "x", "dates": {}}) is None
    assert ticketmaster.parse_event({"name": "no id"}) is None


def test_ticketmaster_keeps_the_absolute_start_instant():
    """The venue-local clock alone can't go in a calendar: 8pm in Toronto read
    from a phone at home is 8pm at home. Discovery gives the instant too."""
    raw = tm_event()
    raw["dates"]["start"]["dateTime"] = "2026-09-11T00:00:00Z"

    assert ticketmaster.parse_event(raw).starts_at == "2026-09-11T00:00:00Z"


def test_a_listing_with_the_time_still_tba_has_no_instant():
    """Discovery omits dateTime until doors are announced, and a made-up
    instant is worse than a floating one."""
    assert ticketmaster.parse_event(tm_event()).starts_at is None


def test_ticketmaster_keeps_a_published_end():
    """A curfew the promoter actually stated beats any assumption about it."""
    raw = tm_event()
    raw["dates"]["end"] = {
        "localDate": "2026-09-10",
        "localTime": "23:00:00",
        "dateTime": "2026-09-11T03:00:00Z",
    }

    parsed = ticketmaster.parse_event(raw)

    assert parsed.end_time == "23:00"
    assert parsed.end_date == "2026-09-10"
    assert parsed.ends_at == "2026-09-11T03:00:00Z"


def test_ticketmaster_keeps_the_last_day_of_a_festival():
    """A multi-day run ends on a different date than it starts, and losing that
    would compress three days into one evening."""
    raw = tm_event()
    raw["dates"]["end"] = {"localDate": "2026-09-13", "localTime": "22:00:00"}

    parsed = ticketmaster.parse_event(raw)

    assert parsed.date == "2026-09-10"
    assert parsed.end_date == "2026-09-13"


def test_a_listing_with_no_stated_end_has_none():
    """Most of them. The assumption about how long a show runs is made once,
    downstream, where it can be labelled as one."""
    parsed = ticketmaster.parse_event(tm_event())
    assert (parsed.end_date, parsed.end_time, parsed.ends_at) == (None, None, None)


def test_an_all_day_end_is_not_an_end():
    """`noSpecificTime` marks a date pretending to be a time. Reading 00:00 off
    it would end the show before it started."""
    raw = tm_event()
    raw["dates"]["end"] = {
        "localDate": "2026-09-10",
        "localTime": "00:00:00",
        "noSpecificTime": True,
    }

    assert ticketmaster.parse_event(raw).end_time is None


async def test_sweep_walks_the_window_in_chunks(routes, monkeypatch):
    monkeypatch.setattr(config, "ticketmaster_api_key", "key")
    routes.add("/events.json", tm_page([tm_event()]))

    events, notes = await ticketmaster.sweep(
        TODAY, TODAY + timedelta(days=13), country="US", chunk_days=7
    )

    assert notes == []
    assert len(events) == 2  # one chunk each for two 7-day windows
    assert routes.count("/events.json") == 2


async def test_sweep_halves_the_window_when_results_are_truncated(routes, monkeypatch):
    """A truncated sweep and an empty one look identical from outside, so this
    is the case worth spending extra calls to avoid."""
    monkeypatch.setattr(config, "ticketmaster_api_key", "key")
    routes.add("/events.json", tm_page([tm_event()], total_pages=99))

    _, notes = await ticketmaster.sweep(TODAY, TODAY + timedelta(days=3), chunk_days=4)

    assert any("re-scanned at" in note for note in notes)
    assert any("exceeded 1000 results" in note for note in notes)


async def test_sweep_without_a_key_says_so(routes, monkeypatch):
    monkeypatch.setattr(config, "ticketmaster_api_key", "")
    events, notes = await ticketmaster.sweep(TODAY, TODAY + timedelta(days=7))
    assert events == []
    assert "no API key" in notes[0]
    assert routes.calls == []


async def test_attraction_id_caches_misses_too(routes, monkeypatch):
    """Re-searching a name Discovery doesn't know is pure waste."""
    monkeypatch.setattr(config, "ticketmaster_api_key", "key")
    routes.add("/attractions.json", {"_embedded": {"attractions": []}})

    assert await ticketmaster.attraction_id("k1", "Obscure Band") is None
    assert await ticketmaster.attraction_id("k1", "Obscure Band") is None
    assert routes.count("/attractions.json") == 1


async def test_attraction_id_requires_an_exact_name_match(routes, monkeypatch):
    monkeypatch.setattr(config, "ticketmaster_api_key", "key")
    routes.add(
        "/attractions.json",
        {"_embedded": {"attractions": [{"name": "The National Parks", "id": "wrong"}]}},
    )
    assert await ticketmaster.attraction_id("k2", "The National") is None


# --------------------------------------------------------------------------
# JamBase: the provider that bills for overage
# --------------------------------------------------------------------------


async def test_jambase_is_off_without_an_explicit_base_url(routes, monkeypatch):
    """Guessing a base URL would spend billable calls discovering it was wrong."""
    monkeypatch.setattr(config, "jambase_api_key", "key")
    monkeypatch.delenv("JAMBASE_BASE_URL", raising=False)

    assert jambase.available() is False
    assert await jambase.by_artist_name("Band", TODAY, TODAY + timedelta(days=30)) == []
    assert routes.calls == []


async def test_jambase_clamps_to_the_six_month_window(routes, monkeypatch):
    monkeypatch.setattr(config, "jambase_api_key", "key")
    monkeypatch.setenv("JAMBASE_BASE_URL", "https://jb.test/v1")
    routes.add("/events", {"events": []})

    far = jambase.window_end(TODAY + timedelta(days=900))
    assert far <= jambase.today() + timedelta(days=jambase.FUTURE_WINDOW_DAYS)


async def test_jambase_skips_windows_entirely_beyond_the_limit(routes, monkeypatch):
    """Paying for a question that cannot return an answer is the worst outcome."""
    monkeypatch.setattr(config, "jambase_api_key", "key")
    monkeypatch.setenv("JAMBASE_BASE_URL", "https://jb.test/v1")

    start = jambase.today() + timedelta(days=400)
    assert await jambase.by_artist_name("Band", start, start + timedelta(days=10)) == []
    assert routes.calls == []
    assert usage.used("jambase") == 0


async def test_jambase_stops_dead_at_the_cap(routes, monkeypatch):
    monkeypatch.setattr(config, "jambase_api_key", "key")
    monkeypatch.setenv("JAMBASE_BASE_URL", "https://jb.test/v1")
    routes.add("/events", {"events": []})

    _, cap = usage.cap_for("jambase")
    db.execute(
        "INSERT INTO provider_usage(provider, period, calls) VALUES(?,?,?)",
        ("jambase", day_key(), cap),
    )

    assert await jambase.by_artist_name("Band", TODAY, TODAY + timedelta(days=30)) == []
    assert routes.calls == []


async def test_jambase_never_retries_because_a_retry_is_another_bill(routes, monkeypatch):
    monkeypatch.setattr(config, "jambase_api_key", "key")
    monkeypatch.setenv("JAMBASE_BASE_URL", "https://jb.test/v1")
    routes.add_error("/events", 500)

    result = await jambase.by_artist_name("Band", TODAY, TODAY + timedelta(days=30))

    assert result == []
    assert routes.count("/events") == 1  # one attempt, not three
    assert usage.used("jambase") == 1  # and it still counted, because it may still bill


async def test_jambase_authenticates_with_a_bearer_header(routes, monkeypatch):
    """v3 takes a Bearer token. The old v1 API used ?apikey=, and sending it
    that way returns 401 while still burning a reserved quota slot."""
    monkeypatch.setattr(config, "jambase_api_key", "secret-key")
    monkeypatch.setenv("JAMBASE_BASE_URL", "https://jb.test/v3")
    routes.add("/events", {"events": []})

    await jambase.by_artist_name("Band", TODAY, TODAY + timedelta(days=30))

    request = routes.calls[0]
    assert request.headers["Authorization"] == "Bearer secret-key"
    # a key in a query string leaks into logs and proxies
    assert "secret-key" not in str(request.url)
    assert "apikey" not in str(request.url)


async def test_jambase_parses_a_listing():
    parsed = jambase.parse_event(
        {
            "identifier": "jb99",
            "name": "Palehound at Local 506",
            "startDate": "2026-09-12T20:30",
            "url": "https://jambase.com/e/jb99",
            "performer": [{"name": "Palehound"}, {"name": "Support Act"}],
            "location": {
                "name": "Local 506",
                "address": {
                    "addressLocality": "Lakeside",
                    "addressRegion": "KS",
                    "addressCountry": "US",
                },
                "geo": {"latitude": 38.4, "longitude": -95.4},
            },
        }
    )
    assert parsed.artist_name == "Palehound"
    assert parsed.lineup == ["Support Act"]
    assert parsed.city == "Lakeside"
    assert parsed.date == "2026-09-12"
    assert parsed.country == "US"
    assert parsed.mbid is None  # External Identifiers are not on this tier
    assert parsed.end_time is None  # this listing never stated one


def test_jambase_takes_the_schema_org_end_date():
    parsed = jambase.parse_event(
        {
            "identifier": "jb99",
            "startDate": "2026-09-12T20:30",
            "endDate": "2026-09-13T01:00",
            "performer": [{"name": "Palehound"}],
        }
    )
    assert (parsed.end_date, parsed.end_time) == ("2026-09-13", "01:00")


def _listing_in(country) -> dict:
    return {
        "identifier": "jb99",
        "startDate": "2026-09-12T20:30",
        "performer": [{"name": "Palehound"}],
        "location": {"address": {"addressCountry": country}},
    }


def test_jambase_every_address_field_may_arrive_as_an_object(country_index):
    """JSON-LD lets any of these be a bare string or a typed object, and
    JamBase mixes both inside one response. Fixing them one at a time as each
    crashes costs a billable call per discovery, so they're covered together."""
    parsed = jambase.parse_event(
        {
            "identifier": "jb100",
            "startDate": "2026-09-12T20:30",
            "performer": [{"name": "Palehound"}],
            "location": {
                "name": {"@type": "Place", "name": "Local 506"},
                "address": {
                    "addressLocality": {"@type": "City", "name": "Lakeside"},
                    "addressRegion": {"@type": "State", "name": "Kansas"},
                    "addressCountry": {"@type": "Country", "name": "United States"},
                },
            },
        }
    )

    assert parsed.venue == "Local 506"
    assert parsed.city == "Lakeside"
    assert parsed.region == "Kansas"
    assert parsed.country == "US"


def test_ingest_never_hands_sqlite_something_it_cannot_bind(country_index):
    """The guard of last resort. sqlite raises on a dict, the task fails, and
    the retry pays JamBase again for a listing we already have."""
    from api import library, scan
    from api.providers.base import Event

    db.execute(
        "INSERT INTO artists(key, name, affinity, listens) VALUES(?,?,?,?)",
        ("name:palehound", "Palehound", 0.9, 100),
    )
    rogue = Event(
        provider="jambase",
        provider_event_id="rogue",
        artist_name="Palehound",
        date="2026-09-12",
        venue={"name": "Local 506"},  # type: ignore[arg-type]
        region={"name": "Kansas"},  # type: ignore[arg-type]
        country={"name": "United States"},  # type: ignore[arg-type]
    )

    matched, seen = scan.ingest([rogue], library.all_artists())

    assert (matched, seen) == (1, 1)
    stored = db.query_one("SELECT venue, region, country FROM events WHERE id = ?",
                          ("jambase:rogue",))
    assert (stored["venue"], stored["region"], stored["country"]) == (None, None, None)


@pytest.fixture
def country_index(tmp_path, monkeypatch):
    """Resolving an alpha-3 or a spelled-out name needs the border index, which
    is built during `docker build` and so isn't on disk here."""
    from api import borders
    from scripts import build_borders

    path = tmp_path / "borders.db"
    build_borders.build(
        {
            "features": [
                {
                    "properties": {
                        "ISO_A2_EH": "US",
                        "ISO_A3_EH": "USA",
                        "NAME_EN": "United States",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[-80.0, 35.0], [-79.0, 35.0], [-79.0, 36.0], [-80.0, 35.0]]
                        ],
                    },
                }
            ]
        },
        path,
    )
    monkeypatch.setattr(config, "borders_db", str(path))
    borders.reset()
    borders.alpha2_for.cache_clear()
    borders.alpha2_for_name.cache_clear()
    yield
    borders.reset()
    borders.alpha2_for.cache_clear()
    borders.alpha2_for_name.cache_clear()


@pytest.mark.parametrize(
    "raw",
    [
        "US",
        "us",
        "USA",
        {"@type": "Country", "identifier": "US"},
        {"@type": "Country", "name": "United States"},
        {"@type": "Country", "name": "united states"},
    ],
    ids=["alpha2", "lowercase", "alpha3", "object-code", "object-name", "object-case"],
)
def test_jambase_country_survives_every_shape_schema_org_allows(raw, country_index):
    """`addressCountry` is a string *or* a Country object, and JamBase sends
    both. Assuming a string crashed ingest *after* the billable call, so the
    retry paid for the same listing again."""
    assert jambase.parse_event(_listing_in(raw)).country == "US"


@pytest.mark.parametrize("raw", [None, "", {}, {"name": "Freedonia"}, 7, []])
def test_jambase_an_unusable_country_is_dropped_not_raised(raw, country_index):
    """No country is a listing we can still score. A crash is a bill."""
    assert jambase.parse_event(_listing_in(raw)).country is None


# --------------------------------------------------------------------------
# quota accounting
# --------------------------------------------------------------------------


def test_reserve_refuses_past_the_cap():
    _, cap = usage.cap_for("jambase")
    granted = sum(1 for _ in range(cap + 25) if usage.reserve("jambase"))

    assert granted == cap
    assert usage.remaining("jambase") == 0
    assert usage.used("jambase") == cap


def test_jambase_cap_sits_below_the_free_allowance():
    """The gap between our cap and their 1000 is the headroom that absorbs a
    bug before it costs money."""
    _, cap = usage.cap_for("jambase")
    assert cap == 500
    assert cap < 1000


def test_no_setting_can_raise_a_cap_past_its_hard_ceiling():
    assert usage.HARD_CEILINGS["jambase"] < 1000


def test_snapshot_reports_exhaustion():
    _, cap = usage.cap_for("ticketmaster")
    db.execute(
        "INSERT INTO provider_usage(provider, period, calls) VALUES(?,?,?)",
        ("ticketmaster", day_key(), cap),
    )
    row = next(r for r in usage.snapshot() if r["provider"] == "ticketmaster")
    assert row["exhausted"] is True
    assert row["remaining"] == 0


def test_the_window_rolls_rather_than_resetting_on_the_1st():
    """A calendar month would let 500 calls on the 31st and 500 on the 1st
    through as "half used" twice — 1000 billable calls in two days."""
    from datetime import timedelta

    from api.util import today

    _, cap = usage.cap_for("jambase")
    yesterday = (today() - timedelta(days=1)).isoformat()
    db.execute(
        "INSERT INTO provider_usage(provider, period, calls) VALUES(?,?,?)",
        ("jambase", yesterday, cap),
    )

    assert usage.used("jambase") == cap
    assert usage.reserve("jambase") is False


def test_calls_outside_the_window_stop_counting():
    from datetime import timedelta

    from api.util import today

    window, cap = usage.cap_for("jambase")
    long_ago = (today() - timedelta(days=window + 5)).isoformat()
    db.execute(
        "INSERT INTO provider_usage(provider, period, calls) VALUES(?,?,?)",
        ("jambase", long_ago, cap),
    )

    assert usage.used("jambase") == 0
    assert usage.reserve("jambase") is True


def test_a_daily_cap_only_counts_today():
    from datetime import timedelta

    from api.util import today

    yesterday = (today() - timedelta(days=1)).isoformat()
    db.execute(
        "INSERT INTO provider_usage(provider, period, calls) VALUES(?,?,?)",
        ("ticketmaster", yesterday, 4500),
    )

    assert usage.used("ticketmaster") == 0


def test_pruning_keeps_the_window_intact():
    from datetime import timedelta

    from api.util import today

    recent = (today() - timedelta(days=5)).isoformat()
    ancient = (today() - timedelta(days=200)).isoformat()
    db.executemany(
        "INSERT INTO provider_usage(provider, period, calls) VALUES(?,?,?)",
        [("jambase", recent, 10), ("jambase", ancient, 99)],
    )

    usage.prune()

    assert usage.used("jambase") == 10
    assert db.scalar("SELECT COUNT(*) FROM provider_usage WHERE period = ?", (ancient,)) == 0
