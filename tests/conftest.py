"""Test harness.

**No test may ever touch a real provider.** That is enforced here rather than
left to discipline: the `no_network` fixture is autouse and session-wide, and it
breaks `socket` itself, so anything that tries to open a connection fails loudly
with a pointer to this file — httpx, urllib, or something we haven't thought of.

Provider responses come from `httpx.MockTransport` handlers registered per test.
An unregistered URL is an error, not an empty result, so a stub that drifts out
of date fails instead of silently returning nothing.
"""

import json
import socket
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class NetworkAccessAttempted(RuntimeError):
    """Raised when a test tries to reach the network."""


@pytest.fixture(autouse=True, scope="session")
def no_network():
    """Block outbound connections for the whole session.

    Belt and braces over the httpx mocking below — it also catches urllib, raw
    sockets and anything vendored.

    Deliberately surgical rather than replacing `socket.socket` wholesale:
    asyncio builds its event loop around an internal socketpair, so breaking
    socket construction breaks the loop before a test ever runs. Blocking
    `connect` on the IP families plus DNS resolution stops anything leaving the
    machine while leaving AF_UNIX socketpairs alone.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    ip_families = {socket.AF_INET, socket.AF_INET6}

    def _refuse(target):
        raise NetworkAccessAttempted(
            f"a test tried to reach {target}. Tests must never hit a real "
            "provider — register a MockTransport route instead. "
            "See tests/conftest.py"
        )

    def guarded_connect(self, address, *args, **kwargs):
        if self.family in ip_families:
            _refuse(address)
        return real_connect(self, address, *args, **kwargs)

    def guarded_connect_ex(self, address, *args, **kwargs):
        if self.family in ip_families:
            _refuse(address)
        return real_connect_ex(self, address, *args, **kwargs)

    def guarded_create_connection(address, *args, **kwargs):
        _refuse(address)

    def guarded_getaddrinfo(host, *args, **kwargs):
        _refuse(host)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.create_connection = guarded_create_connection
    socket.getaddrinfo = guarded_getaddrinfo
    try:
        yield
    finally:
        socket.socket.connect = real_connect
        socket.socket.connect_ex = real_connect_ex
        socket.create_connection = real_create_connection
        socket.getaddrinfo = real_getaddrinfo


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Every test gets its own database and a clean settings table."""
    monkeypatch.setenv("SONDARO_DB", str(tmp_path / "sondaro.db"))

    from api import config as config_module

    monkeypatch.setattr(config_module.config, "db_path", str(tmp_path / "sondaro.db"))

    from api import db

    db.close()
    db.connect()

    from api import settings

    settings.seed()
    yield
    db.close()


class Routes:
    """A tiny registry of URL-prefix -> response for MockTransport."""

    def __init__(self) -> None:
        self._routes: list[tuple[str, object]] = []
        self.calls: list[httpx.Request] = []

    def add(self, url_contains: str, payload, status: int = 200) -> "Routes":
        self._routes.append((url_contains, (payload, status)))
        return self

    def add_fixture(self, url_contains: str, name: str, status: int = 200) -> "Routes":
        data = json.loads((FIXTURES / name).read_text())
        return self.add(url_contains, data, status)

    def add_error(self, url_contains: str, status: int) -> "Routes":
        return self.add(url_contains, {"error": "stubbed failure"}, status)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = str(request.url)
        for fragment, (payload, status) in self._routes:
            if fragment in url:
                if isinstance(payload, (dict, list)):
                    return httpx.Response(status, json=payload)
                return httpx.Response(status, text=str(payload))
        raise AssertionError(
            f"unstubbed request to {url}\n"
            "Every outbound call in a test must have a registered route."
        )

    def count(self, url_contains: str) -> int:
        return sum(1 for call in self.calls if url_contains in str(call.url))


@pytest.fixture
def routes(monkeypatch):
    """Install a MockTransport-backed client into the shared http module."""
    registry = Routes()

    from api import http as http_module

    client = httpx.AsyncClient(transport=httpx.MockTransport(registry.handler))
    monkeypatch.setattr(http_module, "_client", client)
    # the limiter would otherwise pace tests at the real request rate, and the
    # retry backoff would genuinely sleep through it
    monkeypatch.setattr(http_module.limiter, "rate", 10_000.0)
    monkeypatch.setattr(http_module, "BACKOFF_SECONDS", 0.0)
    yield registry
