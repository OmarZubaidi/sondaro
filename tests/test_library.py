"""Library sync and affinity source selection.

The source choice matters more than it looks. Affinity is one of the three
scoring axes, so picking a scrobble account that only knows a twelfth of your
library compresses the whole ranking into noise.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import library  # noqa: E402
from api.config import config  # noqa: E402

ARTISTS = [
    {"name": n, "mbid": None, "lidarr_id": i, "monitored": 1}
    for i, n in enumerate(
        ["Danheim", "Gorillaz", "Saint Levant", "System of a Down", "Radiohead"]
    )
]


def listenbrainz(rows):
    return {"payload": {"artists": [
        {"artist_name": n, "listen_count": c} for n, c in rows
    ]}}


def lastfm(rows):
    return {"topartists": {"artist": [
        {"name": n, "playcount": str(c)} for n, c in rows
    ]}}


@pytest.fixture(autouse=True)
def _accounts(monkeypatch):
    monkeypatch.setattr(config, "listenbrainz_user", "lb-user")
    monkeypatch.setattr(config, "lastfm_api_key", "lf-key")
    monkeypatch.setattr(config, "lastfm_user", "lf-user")


async def test_prefers_the_source_that_knows_more_of_the_library(routes):
    """The real case that prompted this: a ListenBrainz account connected last
    month answers first, while Last.fm holds years of history."""
    routes.add("listenbrainz.org", listenbrainz([("Danheim", 5)]))
    routes.add(
        "audioscrobbler.com",
        lastfm([("Danheim", 114), ("Gorillaz", 46), ("Saint Levant", 50),
                ("System of a Down", 36)]),
    )

    counts, source = await library.pick_counts(ARTISTS)

    assert source.startswith("lastfm")
    assert counts["danheim"] == 114


async def test_prefers_listenbrainz_when_it_knows_more(routes):
    routes.add(
        "listenbrainz.org",
        listenbrainz([("Danheim", 5), ("Gorillaz", 9), ("Radiohead", 3)]),
    )
    routes.add("audioscrobbler.com", lastfm([("Danheim", 114)]))

    _counts, source = await library.pick_counts(ARTISTS)

    assert source.startswith("listenbrainz")


async def test_falls_back_when_one_source_is_empty(routes):
    routes.add("listenbrainz.org", {"payload": {"artists": []}})
    routes.add("audioscrobbler.com", lastfm([("Danheim", 114)]))

    counts, source = await library.pick_counts(ARTISTS)

    assert source.startswith("lastfm")
    assert counts["danheim"] == 114


async def test_no_scrobbles_anywhere_weights_everyone_equally(routes):
    routes.add("listenbrainz.org", {"payload": {"artists": []}})
    routes.add("audioscrobbler.com", {"topartists": {"artist": []}})

    counts, source = await library.pick_counts(ARTISTS)

    assert counts == {}
    assert "every artist weighted equally" in source


async def test_coverage_beats_raw_play_count(routes):
    """One obsessively played artist shouldn't outrank broad coverage: the
    spread across your library is what makes affinity discriminate."""
    routes.add("listenbrainz.org", listenbrainz([
        ("Danheim", 3), ("Gorillaz", 2), ("Saint Levant", 4),
        ("System of a Down", 1), ("Radiohead", 2),
    ]))
    routes.add("audioscrobbler.com", lastfm([("Danheim", 99999)]))

    _counts, source = await library.pick_counts(ARTISTS)

    assert source.startswith("listenbrainz")
    assert "5/5" in source


async def test_the_chosen_source_is_reported_for_the_status_page(routes):
    routes.add("listenbrainz.org", listenbrainz([("Danheim", 5)]))
    routes.add("audioscrobbler.com", lastfm([("Danheim", 114), ("Gorillaz", 46)]))

    _counts, source = await library.pick_counts(ARTISTS)

    assert source == "lastfm (2/5 artists)"
