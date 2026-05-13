"""WEBSHARE_PROXIES env-var parser handles the formats we expect."""

import pytest

from fb_ads_scraper.proxy import _load_proxies_from_env


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("WEBSHARE_PROXIES", raising=False)


def test_empty_env_returns_empty_list(monkeypatch):
    assert _load_proxies_from_env() == []


def test_parses_single_entry(monkeypatch):
    monkeypatch.setenv("WEBSHARE_PROXIES", "1.2.3.4:6754:user:pw")
    proxies = _load_proxies_from_env()
    assert len(proxies) == 1
    p = proxies[0]
    assert p.host == "1.2.3.4"
    assert p.port == 6754
    assert p.username == "user"
    assert p.password == "pw"
    assert p.protocol == "http"
    assert p.url == "http://user:pw@1.2.3.4:6754"


def test_parses_comma_separated(monkeypatch):
    monkeypatch.setenv(
        "WEBSHARE_PROXIES",
        "1.1.1.1:1111:u1:p1, 2.2.2.2:2222:u2:p2 , 3.3.3.3:3333:u3:p3",
    )
    proxies = _load_proxies_from_env()
    assert len(proxies) == 3
    assert [p.host for p in proxies] == ["1.1.1.1", "2.2.2.2", "3.3.3.3"]
    assert [p.username for p in proxies] == ["u1", "u2", "u3"]


def test_parses_newline_separated(monkeypatch):
    monkeypatch.setenv(
        "WEBSHARE_PROXIES",
        "1.1.1.1:1111:u:p\n2.2.2.2:2222:u:p\n3.3.3.3:3333:u:p",
    )
    assert len(_load_proxies_from_env()) == 3


def test_skips_malformed_entries(monkeypatch):
    monkeypatch.setenv(
        "WEBSHARE_PROXIES",
        "good:6754:u:p, garbage, also-bad:notaport:u:p, also-good:7777:u:p",
    )
    proxies = _load_proxies_from_env()
    assert {p.host for p in proxies} == {"good", "also-good"}


def test_entry_without_credentials(monkeypatch):
    """`host:port` (no auth) should still parse — public/proxy with no creds."""
    monkeypatch.setenv("WEBSHARE_PROXIES", "1.2.3.4:8080")
    proxies = _load_proxies_from_env()
    assert len(proxies) == 1
    assert proxies[0].username is None
    assert proxies[0].password is None
    assert proxies[0].url == "http://1.2.3.4:8080"


def test_url_encodes_special_chars_in_creds(monkeypatch):
    """Special chars in passwords (e.g. `@`, `:`) must be URL-encoded."""
    monkeypatch.setenv("WEBSHARE_PROXIES", "host:80:user:p@ss")
    proxies = _load_proxies_from_env()
    assert "p%40ss" in proxies[0].url
