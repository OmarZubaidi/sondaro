"""The artist list and the affinity score that ranks everything.

Artists come from Lidarr. Affinity comes from actual listening — ListenBrainz
first, Last.fm second — because "monitored in Lidarr" says you were curious
once, whereas a play count says you keep coming back. That distinction is what
decides whether a show is worth a three-hour drive.

Discovery candidates (artists you don't own) come from Last.fm's similarity
graph, seeded by your top listens and weighted so they can never outrank the
real thing.
"""

import asyncio
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

DISCOVERY_SEEDS = 40
DISCOVERY_PER_SEED = 15


@dataclass
class Artist:
    key: str
    name: str
    mbid: str | None
    affinity: float
    source: str
    listens: int = 0
    seed: str | None = None

    @property
    def is_discovery(self) -> bool:
        return self.source == "discovery"


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
                "lidarr",
                None,
                stamp,
            )
        )

    db.executemany(
        "INSERT INTO artists(key, mbid, name, lidarr_id, monitored, listens, "
        "affinity, source, seed, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET mbid=excluded.mbid, name=excluded.name, "
        "lidarr_id=excluded.lidarr_id, monitored=excluded.monitored, "
        "listens=excluded.listens, affinity=excluded.affinity, "
        "source='lidarr', updated_at=excluded.updated_at",
        rows,
    )

    # drop library artists that vanished from Lidarr, leaving discovery rows be
    keys = {row[0] for row in rows}
    for existing in db.query("SELECT key FROM artists WHERE source = 'lidarr'"):
        if existing["key"] not in keys:
            db.execute("DELETE FROM artists WHERE key = ?", (existing["key"],))

    db.set_meta("library_synced_at", stamp)
    db.set_meta("affinity_source", source)

    scrobbled = sum(1 for row in rows if row[5] > 0)
    log.info("library sync: %d artists, %d with listens (%s)", len(rows), scrobbled, source)
    return {"artists": len(rows), "with_listens": scrobbled, "affinity_source": source}


async def _similar(name: str, weight: float) -> list[tuple[str, str | None, float]]:
    payload = await http.get_json(
        LASTFM,
        params={
            "method": "artist.getsimilar",
            "artist": name,
            "api_key": config.lastfm_api_key,
            "format": "json",
            "limit": DISCOVERY_PER_SEED,
            "autocorrect": 1,
        },
        rate_limited=False,
    )
    out = []
    for row in ((payload or {}).get("similarartists") or {}).get("artist") or []:
        similar_name = row.get("name")
        if not similar_name:
            continue
        try:
            match = float(row.get("match") or 0)
        except (TypeError, ValueError):
            match = 0.0
        out.append((similar_name, row.get("mbid") or None, match * weight))
    return out


async def refresh_discovery() -> int:
    """Artists you don't own but would probably want to see."""
    if not config.lastfm_api_key:
        return 0

    seeds = db.query(
        "SELECT key, name, affinity FROM artists WHERE source = 'lidarr' "
        "ORDER BY affinity DESC, name LIMIT ?",
        (DISCOVERY_SEEDS,),
    )
    if not seeds:
        return 0

    owned_keys = {row["key"] for row in db.query("SELECT key FROM artists")}
    owned_names = {
        normalize(row["name"])
        for row in db.query("SELECT name FROM artists WHERE source = 'lidarr'")
    }

    semaphore = asyncio.Semaphore(config.max_concurrency)

    async def run(seed):
        async with semaphore:
            return seed["name"], await _similar(seed["name"], seed["affinity"])

    results = await asyncio.gather(*(run(s) for s in seeds), return_exceptions=True)

    best: dict[str, tuple] = {}
    stamp = now_iso()
    for result in results:
        if isinstance(result, BaseException):
            log.warning("discovery lookup failed: %s", result)
            continue
        seed_name, similar = result
        for name, mbid, similarity in similar:
            if normalize(name) in owned_names:
                continue
            key = artist_key(mbid, name)
            if key in owned_keys:
                continue
            value = scoring.discovery_affinity(similarity)
            if key not in best or value > best[key][6]:
                best[key] = (key, mbid, name, None, 0, 0, value, "discovery", seed_name, stamp)

    db.execute("DELETE FROM artists WHERE source = 'discovery'")
    db.executemany(
        "INSERT INTO artists(key, mbid, name, lidarr_id, monitored, listens, "
        "affinity, source, seed, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(key) DO NOTHING",
        best.values(),
    )
    log.info("discovery: %d candidates from %d seeds", len(best), len(seeds))
    return len(best)


def _row_to_artist(row) -> Artist:
    return Artist(
        key=row["key"],
        name=row["name"],
        mbid=row["mbid"],
        affinity=row["affinity"],
        source=row["source"],
        listens=row["listens"] or 0,
        seed=row["seed"],
    )


def all_artists(include_discovery: bool = True) -> list[Artist]:
    sql = "SELECT * FROM artists"
    if not include_discovery:
        sql += " WHERE source = 'lidarr'"
    sql += " ORDER BY affinity DESC, name"
    return [_row_to_artist(row) for row in db.query(sql)]


def top_artists(limit: int, include_discovery: bool = False) -> list[Artist]:
    sql = "SELECT * FROM artists"
    if not include_discovery:
        sql += " WHERE source = 'lidarr'"
    sql += " ORDER BY affinity DESC, name LIMIT ?"
    return [_row_to_artist(row) for row in db.query(sql, (limit,))]


def get(key: str) -> Artist | None:
    row = db.query_one("SELECT * FROM artists WHERE key = ?", (key,))
    return _row_to_artist(row) if row else None


def index_by_name(artists: list[Artist]) -> dict[str, Artist]:
    """Normalised name -> artist, preferring the higher-affinity entry when a
    library artist and a discovery candidate collide."""
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
