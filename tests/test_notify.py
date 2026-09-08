"""ntfy push.

The header encoding is not a nicety: HTTP headers cannot carry raw UTF-8, and
a huge share of artist names are accented. Sending one unencoded raises
UnicodeEncodeError inside httpx and kills the whole notification pass, so a
single Sigur Rós show would silence alerts entirely.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import notify  # noqa: E402
from api.config import config  # noqa: E402


@pytest.fixture(autouse=True)
def _ntfy(monkeypatch):
    monkeypatch.setattr(config, "ntfy_url", "https://ntfy.test")
    monkeypatch.setattr(config, "ntfy_token", "tk_test")


def test_ascii_titles_pass_through_unchanged():
    assert notify._header_safe("The National") == "The National"


@pytest.mark.parametrize(
    "name",
    ["Sigur Rós", "Beyoncé", "Mötley Crüe", "Björk", "Sinéad O'Connor", "Röyksopp"],
)
def test_accented_names_are_encoded_rather_than_raising(name):
    encoded = notify._header_safe(f"{name} · Fairview")

    encoded.encode("ascii")  # would raise before the fix
    assert encoded.startswith("=?utf-8?")


async def test_sending_an_accented_title_does_not_blow_up(routes):
    routes.add("ntfy.test", "ok")

    sent = await notify.send("sondaro", title="Sigur Rós · Fairview", body="tonight")

    assert sent is True
    assert routes.calls[0].headers["Title"].startswith("=?utf-8?")


async def test_the_body_keeps_real_utf8(routes):
    """Only headers are constrained; the body is free to be UTF-8."""
    routes.add("ntfy.test", "ok")

    await notify.send("sondaro", title="plain", body="Sigur Rós at Cat's Cradle")

    assert "Sigur Rós".encode("utf-8") in routes.calls[0].content


async def test_no_ntfy_url_is_a_no_op_rather_than_an_error(routes, monkeypatch):
    monkeypatch.setattr(config, "ntfy_url", "")

    assert await notify.send("sondaro", title="x", body="y") is False
    assert routes.calls == []
