"""Authenticated HTTP proxies — loaded from the `WEBSHARE_PROXIES` env var.

Format: one entry per line *or* comma-separated. Each entry is
`host:port:username:password` (the format Webshare's dashboard hands you).
Whitespace is tolerated. Missing entries → empty pool.

Example:
    WEBSHARE_PROXIES="31.59.20.176:6754:user:pass, 45.38.107.97:6014:user:pass"

ProxyPool below health-checks them in parallel and hands out random working
ones.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from datetime import UTC, datetime

import httpx

from fb_ads_scraper.models import ProxyEntry

log = logging.getLogger(__name__)

PROXY_SOURCE = "webshare"
HEALTHCHECK_URL = "http://www.gstatic.com/generate_204"
CACHE_TTL = 15 * 60  # 15 minutes
HEALTHCHECK_TIMEOUT = 12.0  # seconds

_SPLIT_RE = re.compile(r"[,\n\r]+")


def _load_proxies_from_env() -> list[ProxyEntry]:
    """Parse WEBSHARE_PROXIES into ProxyEntry models.

    Each entry: `host:port:username:password`. Empty/malformed entries
    are skipped with a warning. Returns an empty list if the env var is
    unset — that's a supported state (the UI shows '0 healthy' and the
    scraper just doesn't route through a proxy unless asked to).
    """
    raw = os.getenv("WEBSHARE_PROXIES", "").strip()
    if not raw:
        return []
    out: list[ProxyEntry] = []
    for entry in _SPLIT_RE.split(raw):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) < 2:
            log.warning("Skipping malformed proxy entry: %r", entry)
            continue
        host = parts[0].strip()
        try:
            port = int(parts[1].strip())
        except ValueError:
            log.warning("Skipping proxy with bad port: %r", entry)
            continue
        username = parts[2].strip() if len(parts) > 2 else None
        password = parts[3].strip() if len(parts) > 3 else None
        try:
            out.append(
                ProxyEntry(
                    host=host,
                    port=port,
                    protocol="http",
                    username=username or None,
                    password=password or None,
                )
            )
        except Exception as exc:
            log.warning("Skipping invalid proxy entry %r: %s", entry, exc)
    return out


def _candidates() -> list[ProxyEntry]:
    """Materialize the env-defined proxy list into ProxyEntry models.

    Re-reads on every call so docker compose / .env reloads pick up
    changes without restarting the api container.
    """
    return _load_proxies_from_env()


class ProxyPool:
    """Health-check the configured proxies, hand out working ones."""

    def __init__(self) -> None:
        self._entries: list[ProxyEntry] = []
        self._working: list[ProxyEntry] = []
        self._refreshed_at: float = 0.0
        self._lock = asyncio.Lock()
        self._current: ProxyEntry | None = None

    async def refresh(self, force: bool = False) -> list[ProxyEntry]:
        async with self._lock:
            if not force and self._working and (time.time() - self._refreshed_at) < CACHE_TTL:
                return self._working
            entries = _candidates()
            log.info("Health-checking %d proxies", len(entries))
            self._entries = entries
            self._working = await self._health_check_all(entries)
            self._refreshed_at = time.time()
            log.info("%d proxies healthy", len(self._working))
            return self._working

    async def get_working(self) -> ProxyEntry | None:
        if not self._working or (time.time() - self._refreshed_at) > CACHE_TTL:
            await self.refresh()
        if not self._working:
            return None
        return random.choice(self._working)

    async def rotate(self) -> ProxyEntry | None:
        new = await self.get_working()
        if new is not None:
            self._current = new
        return new

    @property
    def current(self) -> ProxyEntry | None:
        return self._current

    def list_working(self) -> list[ProxyEntry]:
        return list(self._working)

    async def _health_check_all(self, entries: list[ProxyEntry]) -> list[ProxyEntry]:
        sem = asyncio.Semaphore(20)

        async def check(p: ProxyEntry) -> ProxyEntry | None:
            async with sem:
                ok = await _check_proxy(p)
                p.last_checked = datetime.now(UTC)
                p.healthy = ok
                return p if ok else None

        results = await asyncio.gather(*(check(p) for p in entries))
        return [r for r in results if r is not None]


async def _check_proxy(proxy: ProxyEntry, timeout: float = HEALTHCHECK_TIMEOUT) -> bool:
    try:
        async with httpx.AsyncClient(
            proxy=proxy.url,
            timeout=timeout,
            verify=False,
            follow_redirects=False,
        ) as client:
            r = await client.get(HEALTHCHECK_URL)
            return r.status_code in (200, 204)
    except Exception:
        return False


pool = ProxyPool()
