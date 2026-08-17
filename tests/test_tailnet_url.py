"""Where the calendar subscription link points.

A subscription added on a phone has to keep resolving when that phone leaves
the house, so the link can't be the LAN address you happen to be browsing
from. Nothing in this container knows the tailnet name — the sidecar expands
`${TS_CERT_DOMAIN}` privately — so it's assembled from the two halves we do
have: the machine name, handed over by docker-compose, and the domain,
borrowed from whatever ntfy is addressed as.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.config import Config  # noqa: E402


def a_config(**env) -> Config:
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, env, clear=False):
        return Config()


def test_the_domain_is_borrowed_from_ntfy():
    cfg = a_config(NTFY_URL="https://ntfy.example-tailnet.ts.net", TS_HOSTNAME="sondaro")

    assert cfg.tailnet_domain() == "example-tailnet.ts.net"
    assert cfg.tailnet_url() == "https://sondaro.example-tailnet.ts.net"


def test_a_lan_ntfy_is_not_mistaken_for_a_tailnet():
    """A confident wrong answer is worse than no answer: this link gets pasted
    into a calendar app and then never looked at again."""
    cfg = a_config(NTFY_URL="http://192.168.1.50:8080", TS_HOSTNAME="sondaro")

    assert cfg.tailnet_domain() == ""
    assert cfg.tailnet_url() == ""


def test_notifications_being_off_leaves_the_url_unknown():
    """The coupling is real and worth knowing about — an empty NTFY_URL, which
    is how this ships, takes the tailnet domain with it."""
    cfg = a_config(NTFY_URL="", TS_HOSTNAME="sondaro")

    assert cfg.tailnet_url() == ""


def test_a_sidecar_without_a_hostname_leaves_it_unknown_too():
    cfg = a_config(NTFY_URL="https://ntfy.example-tailnet.ts.net", TS_HOSTNAME="")

    assert cfg.tailnet_url() == ""


@pytest.mark.parametrize(
    "url",
    [
        "https://ntfy.example-tailnet.ts.net/",
        "https://ntfy.example-tailnet.ts.net/core",
        "http://ntfy.example-tailnet.ts.net:8080",
    ],
)
def test_the_path_port_and_scheme_are_all_ignored(url):
    """Only the host matters, and only the part of it after the machine."""
    assert a_config(NTFY_URL=url, TS_HOSTNAME="sondaro").tailnet_domain() == "example-tailnet.ts.net"


def test_the_api_hands_the_url_to_the_settings_page(monkeypatch):
    from fastapi.testclient import TestClient

    from api import config as config_module
    from api.main import app

    monkeypatch.setattr(config_module.config, "worker_enabled", False)
    monkeypatch.setattr(config_module.config, "ntfy_url", "https://ntfy.example-tailnet.ts.net")
    monkeypatch.setattr(config_module.config, "ts_hostname", "sondaro")

    with TestClient(app) as client:
        assert (
            client.get("/api/settings").json()["tailnet_url"]
            == "https://sondaro.example-tailnet.ts.net"
        )
