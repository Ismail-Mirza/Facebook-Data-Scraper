from __future__ import annotations

import logging

import httpx

from fb_ads_scraper.config import settings

from .base import BrowserBackend, dismiss_consent, new_context
from .chrome import ChromeBackend
from .playwright_local import PlaywrightLocalBackend

log = logging.getLogger(__name__)


def get_backend(name: str | None = None, *, headless: bool | None = None) -> BrowserBackend:
    chosen = (name or settings.browser_backend).lower()
    if chosen == "chrome":
        return ChromeBackend()
    if chosen == "playwright":
        return PlaywrightLocalBackend(headless=headless)
    raise ValueError(f"Unknown backend: {chosen!r}")


async def is_chrome_healthy(cdp_url: str | None = None, timeout: float = 2.0) -> bool:
    url = (cdp_url or settings.chrome_cdp_url).rstrip("/") + "/json/version"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
            return r.status_code == 200
    except Exception:
        return False


def is_playwright_available() -> bool:
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except Exception:
        return False
    import os
    import pathlib

    base = pathlib.Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright"))
    if base.exists() and any(base.glob("chromium-*")):
        return True
    home = pathlib.Path.home() / ".cache" / "ms-playwright"
    return home.exists() and any(home.glob("chromium-*"))


__all__ = [
    "BrowserBackend",
    "ChromeBackend",
    "PlaywrightLocalBackend",
    "get_backend",
    "is_chrome_healthy",
    "is_playwright_available",
    "dismiss_consent",
    "new_context",
]
