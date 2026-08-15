"""Shared async HTTP client: one connection pool, a token bucket, and
quota-aware dispatch.

Every outbound call in the app goes through here, which is what makes the
JamBase spend cap enforceable — `usage.reserve()` is consulted before a request
is built, not after it fails.
"""

import asyncio
import logging
import time

import httpx

from . import usage
from .config import config

log = logging.getLogger("sondaro.http")

_client: httpx.AsyncClient | None = None

USER_AGENT = "sondaro/1.0 (self-hosted concert tracker)"

# first retry delay, doubling thereafter. Module-level so tests can flatten it
# rather than actually sleeping through a backoff.
BACKOFF_SECONDS = 1.0


class QuotaExhausted(RuntimeError):
    """The provider's cap is reached. Callers skip, they do not retry."""


class RateLimiter:
    """Token bucket. Ticketmaster documents 5 requests/second; we sit under it."""

    def __init__(self, rate: float, burst: int = 2):
        self.rate = max(rate, 0.1)
        self.burst = max(burst, 1)
        self.tokens = float(self.burst)
        self.updated = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


limiter = RateLimiter(config.requests_per_second)


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=10.0),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_json(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    *,
    provider: str | None = None,
    attempts: int = 3,
    rate_limited: bool = True,
) -> dict | list | None:
    """GET returning parsed JSON, or None if it never succeeded.

    `provider` opts the call into quota accounting. When a provider bills for
    overage instead of returning 429 — JamBase does exactly this — a reservation
    is claimed before dispatch and **retries are disabled**, because a retry is
    another billable call rather than a free second chance.
    """
    billed = provider in usage.DEFAULT_CAPS if provider else False
    if billed:
        if not usage.reserve(provider):
            raise QuotaExhausted(f"{provider} quota reached")
        if provider in usage.HARD_CEILINGS:
            attempts = 1  # never spend twice on one question

    delay = BACKOFF_SECONDS
    for attempt in range(1, attempts + 1):
        if rate_limited:
            await limiter.acquire()

        try:
            response = await client().get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("%s failed (%s) attempt %d/%d", url, exc, attempt, attempts)
            if attempt == attempts:
                return None
            await asyncio.sleep(delay)
            delay *= 2
            continue

        if response.status_code == 429:
            retry_after = _retry_after(response, delay)
            log.warning("rate limited on %s, waiting %.1fs", url, retry_after)
            if attempt == attempts:
                return None
            await asyncio.sleep(retry_after)
            delay *= 2
            continue

        if response.status_code == 404:
            return None

        if response.status_code >= 500:
            if attempt == attempts:
                log.error("%s returned %d", url, response.status_code)
                return None
            await asyncio.sleep(delay)
            delay *= 2
            continue

        if response.status_code >= 400:
            log.error("%s returned %d: %s", url, response.status_code, response.text[:300])
            return None

        try:
            return response.json()
        except ValueError:
            log.error("%s returned a non-JSON body", url)
            return None

    return None


async def post(url: str, content: bytes, headers: dict | None = None) -> bool:
    """Fire-and-check POST, used only for ntfy."""
    try:
        response = await client().post(url, content=content, headers=headers)
    except httpx.HTTPError as exc:
        log.error("POST %s failed: %s", url, exc)
        return False
    if response.status_code >= 400:
        log.error("POST %s returned %d", url, response.status_code)
        return False
    return True


def _retry_after(response: httpx.Response, fallback: float) -> float:
    raw = response.headers.get("Retry-After")
    if not raw:
        return fallback
    try:
        return min(float(raw), 60.0)
    except ValueError:
        return fallback
