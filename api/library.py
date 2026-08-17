"""The artist list and the affinity score that ranks everything.

Artists come from Lidarr, and only from Lidarr — sondaro never recommends
someone you haven't added yourself.

Affinity comes from actual listening: ListenBrainz first, Last.fm second.
"Monitored in Lidarr" says you were curious once, whereas a play count says you
keep coming back, and that distinction is what decides whether a show is worth a
three-hour drive.
"""

import logging
from dataclasses import dataclass

from . import db, http, scoring
from .config import config
from .match import artist_key, normalize
from .providers import lidarr
from .util import now_iso

log = logging.getLogger("sondaro.library")

LISTENBRAINZ = "https://api.listenbrainz.org/1"
LASTFM = "https://ws.audioscrobbler.com/2.0/"


@dataclass
class Artist:
    key: str
    name: str
    mbid: str | None
    affinity: float
    listens: int = 0  # scrobbles
    tracks: int = 0  # files on disk in Lidarr


async def fetch_listenbrainz_counts() -> dict[str, int]:
    """Normalised artist name -> lifetime listen count. The stats endpoint is
    public, so this needs a username but no token."""
    if not config.listenbrainz_user:
        return {}

    counts: dict[str, int] = {}
    offset = 0
    while offset < 1000:
        payload = await http.get_json(
            f"{LISTENBRAINZ}/stats/user/{config.listenbrainz_user}/artists",
            params={"count": 100, "offset": offset, "range": "all_time"},
            rate_limited=False,
        )
        rows = ((payload or {}).get("payload") or {}).get("artists") or []
        if not rows:
            break
        for row in rows:
            name = row.get("artist_name")
            if name:
                counts[normalize(name)] = int(row.get("listen_count") or 0)
        offset += len(rows)
        if len(rows) < 100:
            break

    if counts:
        log.info("listenbrainz: %d artists with play counts", len(counts))
    return counts


async def fetch_lastfm_counts() -> dict[str, int]:
    if not (config.lastfm_api_key and config.lastfm_user):
        return {}

    counts: dict[str, int] = {}
    page = 1
    while page <= 5:
        payload = await http.get_json(
            LASTFM,
            params={
                "method": "user.gettopartists",
                "user": config.lastfm_user,
                "api_key": config.lastfm_api_key,
                "format": "json",
                "limit": 200,
                "page": page,
                "period": "overall",
            },
            rate_limited=False,
        )
        rows = ((payload or {}).get("topartists") or {}).get("artist") or []
        if not rows:
            break
        for row in rows:
            name = row.get("name")
            if name:
                counts[normalize(name)] = int(row.get("playcount") or 0)
        if len(rows) < 200:
            break
        page += 1

    if counts:
        log.info("last.fm: %d artists with play counts", len(counts))
    return counts


async def pick_counts(artists: list[dict]) -> tuple[dict[str, int], str]:
    """Choose the scrobble source that actually knows your library.

    Trying one and falling back only when it's empty picks badly: a
    ListenBrainz account connected last month answers, so a Last.fm account
    with years of history never gets consulted, and affinity ends up driven by
    a handful of plays. So ask both (they're free, once a day) and keep
    whichever covers more of the library.
    """
    wanted = {normalize(a["name"]) for a in artists}

    candidates = [
        ("listenbrainz", await fetch_listenbrainz_counts()),
        ("lastfm", await fetch_lastfm_counts()),
    ]

    scored = []
    for name, counts in candidates:
        if not counts:
            continue
        covered = len(wanted & counts.keys())
        plays = sum(counts.get(key, 0) for key in wanted)
        scored.append((covered, plays, name, counts))

    if not scored:
        return {}, "none — every artist weighted equally"

    scored.sort(reverse=True)
    covered, _plays, name, counts = scored[0]

    if len(scored) > 1:
        loser = scored[1]
        log.info(
            "affinity from %s (%d of %d artists) over %s (%d)",
            name, covered, len(wanted), loser[2], loser[0],
        )
    return counts, f"{name} ({covered}/{len(wanted)} artists)"


async def sync() -> dict:
    """Refresh artists and affinity. Safe to run repeatedly."""
    # monitored is about whether Lidarr should be *downloading* an artist. It
    # says nothing about whether you'd go and see them, which is the only
    # question here.
    artists = await lidarr.list_artists(monitored_only=False)
    if not artists:
        return {"artists": 0, "error": "no artists returned from Lidarr"}

    counts, source = await pick_counts(artists)

    # normalise against your library's own distribution, not the whole scrobble
    # history — an artist you play constantly but never added to Lidarr should
    # not set the bar for the ones you did
    ceiling = scoring.affinity_ceiling(
        [counts.get(normalize(a["name"]), 0) for a in artists]
    )
    stamp = now_iso()

    rows = []
    for artist in artists:
        listens = counts.get(normalize(artist["name"]), 0)
        rows.append(
            (
                artist_key(artist["mbid"], artist["name"]),
                artist["mbid"],
                artist["name"],
                artist["lidarr_id"],
                artist["monitored"],
                listens,
                artist.get("tracks", 0),
                scoring.affinity(listens, ceiling),
                stamp,
            )
        )

    db.executemany(
        "INSERT INTO artists(key, mbid, name, lidarr_id, monitored, listens, "
        "tracks, affinity, updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET mbid=excluded.mbid, name=excluded.name, "
        "lidarr_id=excluded.lidarr_id, monitored=excluded.monitored, "
        "listens=excluded.listens, tracks=excluded.tracks, "
        "affinity=excluded.affinity, updated_at=excluded.updated_at",
        rows,
    )

    # drop artists that vanished from Lidarr
    keys = {row[0] for row in rows}
    for existing in db.query("SELECT key FROM artists"):
        if existing["key"] not in keys:
            db.execute("DELETE FROM artists WHERE key = ?", (existing["key"],))

    db.set_meta("library_synced_at", stamp)
    db.set_meta("affinity_source", source)

    scrobbled = sum(1 for row in rows if row[5] > 0)
    log.info("library sync: %d artists, %d with listens (%s)", len(rows), scrobbled, source)
    return {"artists": len(rows), "with_listens": scrobbled, "affinity_source": source}


def _row_to_artist(row) -> Artist:
    return Artist(
        key=row["key"],
        name=row["name"],
        mbid=row["mbid"],
        affinity=row["affinity"],
        listens=row["listens"] or 0,
        tracks=row["tracks"] or 0,
    )


def all_artists() -> list[Artist]:
    return [
        _row_to_artist(row)
        for row in db.query("SELECT * FROM artists ORDER BY affinity DESC, name")
    ]


def top_artists(limit: int) -> list[Artist]:
    return [
        _row_to_artist(row)
        for row in db.query(
            "SELECT * FROM artists ORDER BY affinity DESC, name LIMIT ?", (limit,)
        )
    ]


def get(key: str) -> Artist | None:
    row = db.query_one("SELECT * FROM artists WHERE key = ?", (key,))
    return _row_to_artist(row) if row else None


def index_by_name(artists: list[Artist]) -> dict[str, Artist]:
    """Normalised name -> artist, preferring the higher-affinity entry when two
    library artists normalise to the same key."""
    index: dict[str, Artist] = {}
    for artist in artists:
        key = normalize(artist.name)
        if not key:
            continue
        if key not in index or artist.affinity > index[key].affinity:
            index[key] = artist
    return index


def index_by_mbid(artists: list[Artist]) -> dict[str, Artist]:
    return {a.mbid.lower(): a for a in artists if a.mbid}
