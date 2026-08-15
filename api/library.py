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
    listens: int = 0


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


async def sync() -> dict:
    """Refresh artists and affinity. Safe to run repeatedly."""
    artists = await lidarr.list_artists()
    if not artists:
        return {"artists": 0, "error": "no artists returned from Lidarr"}

    counts = await fetch_listenbrainz_counts()
    source = "listenbrainz"
    if not counts:
        counts = await fetch_lastfm_counts()
        source = "lastfm"
    if not counts:
        source = "none — every artist weighted equally"

    ceiling = max(counts.values()) if counts else 0
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
                scoring.affinity(listens, ceiling),
                stamp,
            )
        )

    db.executemany(
        "INSERT INTO artists(key, mbid, name, lidarr_id, monitored, listens, "
        "affinity, updated_at) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET mbid=excluded.mbid, name=excluded.name, "
        "lidarr_id=excluded.lidarr_id, monitored=excluded.monitored, "
        "listens=excluded.listens, affinity=excluded.affinity, "
        "updated_at=excluded.updated_at",
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
