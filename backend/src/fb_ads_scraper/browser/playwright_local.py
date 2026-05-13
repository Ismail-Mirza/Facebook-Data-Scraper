from __future__ import annotations

import logging
import os
from typing import ClassVar

from playwright.async_api import Browser, async_playwright

from fb_ads_scraper.config import settings
from fb_ads_scraper.models import ProxyEntry

from .base import BrowserBackend

log = logging.getLogger(__name__)


class PlaywrightLocalBackend(BrowserBackend):
    """Launches Playwright's bundled Chromium directly.

    Heavier than the shared Chrome container but supports per-request proxy injection
    AND a visible browser window — pick this backend when you want to watch
    the automation happen.

    Visibility (`headless=False`) requires a display:
      - on the host (Linux desktop, macOS, Windows): works out of the box
      - in Docker: needs Xvfb or X11 forwarding. We auto-force headless when
        no DISPLAY env var is present so container runs don't crash.
    """

    name: ClassVar[str] = "playwright"
    supports_per_request_proxy: ClassVar[bool] = True

    def __init__(self, headless: bool | None = None, slow_mo_ms: int | None = None) -> None:
        if headless is None:
            headless = settings.playwright_headless
        # Safety net: no DISPLAY → silently force headless so we don't crash.
        if not headless and not os.environ.get("DISPLAY") and os.name == "posix":
            log.warning("No DISPLAY env var found; forcing headless=True for Playwright")
            headless = True
        self.headless = headless
        self.slow_mo_ms = slow_mo_ms if slow_mo_ms is not None else settings.playwright_slow_mo_ms
        self._pw = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        if self._pw is None:
            self._pw = await async_playwright().start()

    async def connect(self, proxy: ProxyEntry | None = None) -> Browser:
        await self.start()
        assert self._pw is not None
        launch_kwargs: dict = {
            "headless": self.headless,
            "slow_mo": self.slow_mo_ms,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--start-maximized",
            ],
        }
        if proxy is not None:
            launch_kwargs["proxy"] = {"server": proxy.url}
            log.info("Launching Chromium with proxy %s", proxy.url)
        log.info(
            "Launching Playwright Chromium (headless=%s, slow_mo=%dms)",
            self.headless,
            self.slow_mo_ms,
        )
        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        return self._browser

    async def close(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None
