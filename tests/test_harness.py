"""Tests for the test harness.

The guarantee that no test ever reaches a real provider rests entirely on
`conftest.no_network` and the MockTransport registry. An untested guard is a
guard that quietly stops working, so these assert that both actually bite.
"""

import socket
import sys
import urllib.request
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import NetworkAccessAttempted  # noqa: E402


def test_raw_sockets_cannot_connect():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(NetworkAccessAttempted):
        sock.connect(("example.com", 80))
    sock.close()


def test_dns_resolution_is_blocked():
    with pytest.raises(NetworkAccessAttempted):
        socket.getaddrinfo("example.com", 80)


def test_urllib_is_blocked_too():
    """The border builder uses urllib, so blocking httpx alone wouldn't be enough."""
    with pytest.raises((NetworkAccessAttempted, OSError, urllib.error.URLError)):
        urllib.request.urlopen("http://example.com", timeout=1)


async def test_httpx_without_a_mock_transport_is_blocked():
    async with httpx.AsyncClient() as client:
        with pytest.raises(Exception) as excinfo:
            await client.get("https://app.ticketmaster.com/discovery/v2/events.json")
    assert "NetworkAccessAttempted" in str(type(excinfo.value)) or isinstance(
        excinfo.value, (httpx.ConnectError, httpx.TransportError, NetworkAccessAttempted)
    )


async def test_an_unstubbed_url_is_an_error_not_an_empty_result(routes):
    """A stub that drifts out of date must fail, not silently return nothing —
    otherwise a broken provider client looks exactly like a quiet weekend."""
    from api import http

    with pytest.raises(AssertionError, match="unstubbed request"):
        await http.get_json("https://unexpected.example/api")


async def test_registered_routes_are_served_and_counted(routes):
    from api import http

    routes.add("/known", {"ok": True})
    assert await http.get_json("https://anything.example/known") == {"ok": True}
    assert routes.count("/known") == 1


def test_each_test_gets_a_fresh_database():
    """`isolated_db` is autouse; this asserts state does not leak between tests."""
    from api import db

    db.execute("INSERT INTO notified(event_id, sent_at) VALUES('leak-check', 'now')")
    assert db.query_one("SELECT 1 FROM notified WHERE event_id = 'leak-check'")


def test_the_previous_test_did_not_leak():
    from api import db

    assert db.query_one("SELECT 1 FROM notified WHERE event_id = 'leak-check'") is None
