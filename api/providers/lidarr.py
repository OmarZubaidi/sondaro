"""Lidarr client — structurally incapable of writing.

Lidarr has no scoped API keys: one key, full access. So "read only" cannot be a
property of the credential and has to be a property of this module instead, and
it should be structural rather than a promise in a comment.

Every request goes through `_request`, which validates the method and the path
against frozen allowlists and raises **before a socket is opened**. Adding a
write would mean deliberately editing the allowlist, which is exactly the kind
of change that should be hard to make by accident.

What this does not do: protect the key itself. Anyone holding it still has full
access to Lidarr — this only guarantees that *this app* never writes.
"""

import logging

from .. import http
from ..config import config

log = logging.getLogger("sondaro.lidarr")

ALLOWED_METHODS = frozenset({"GET"})
ALLOWED_PATHS = frozenset({"/api/v1/artist", "/api/v1/health"})


class ReadOnlyViolation(RuntimeError):
    """Raised when something tries to make Lidarr do anything but read."""


def available() -> bool:
    return bool(config.lidarr_api_key and config.lidarr_url)


async def _request(method: str, path: str) -> dict | list | None:
    verb = method.upper()
    if verb not in ALLOWED_METHODS:
        raise ReadOnlyViolation(
            f"{verb} is not permitted against Lidarr. This client is read-only; "
            f"allowed methods are {sorted(ALLOWED_METHODS)}."
        )
    if path not in ALLOWED_PATHS:
        raise ReadOnlyViolation(
            f"{path} is not an allowed Lidarr path. Allowed: {sorted(ALLOWED_PATHS)}."
        )

    return await http.get_json(
        f"{config.lidarr_url}{path}",
        headers={"X-Api-Key": config.lidarr_api_key},
        rate_limited=False,  # it's on the LAN and it's ours
    )


async def list_artists(monitored_only: bool = True) -> list[dict]:
    """Every artist Lidarr knows about, with its MusicBrainz id."""
    if not available():
        log.error("LIDARR_API_KEY is not set — cannot read the library")
        return []

    payload = await _request("GET", "/api/v1/artist")
    if not isinstance(payload, list):
        log.error("unexpected response shape from Lidarr")
        return []

    artists = []
    for raw in payload:
        name = raw.get("artistName")
        if not name:
            continue
        monitored = bool(raw.get("monitored", True))
        if monitored_only and not monitored:
            continue
        # trackFileCount is what's actually on disk, which is the honest answer
        # to "how much of them do I have" — trackCount includes everything
        # Lidarr merely knows exists.
        statistics = raw.get("statistics") or {}
        images = _images(raw.get("images"))
        artists.append(
            {
                "name": name,
                "mbid": raw.get("foreignArtistId"),
                "lidarr_id": raw.get("id"),
                "monitored": 1 if monitored else 0,
                "tracks": int(statistics.get("trackFileCount") or 0),
                "image_poster": images.get("poster"),
                "image_fanart": images.get("fanart"),
            }
        )
    return artists


def _images(raw) -> dict[str, str]:
    """coverType -> remote URL, for the two kinds the pages use.

    Only https survives. The browser loads these straight from the source, so
    a plain-http one would be blocked as mixed content on the tailnet's https
    page, and Lidarr's own relative `url` needs the API key to read.
    """
    found: dict[str, str] = {}
    for image in raw if isinstance(raw, list) else []:
        if not isinstance(image, dict):
            continue
        kind = image.get("coverType")
        url = str(image.get("remoteUrl") or "")
        if kind in ("poster", "fanart") and kind not in found and url.startswith("https://"):
            found[kind] = url
    return found


async def healthy() -> bool:
    if not available():
        return False
    return await _request("GET", "/api/v1/health") is not None
