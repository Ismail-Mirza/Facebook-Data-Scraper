from __future__ import annotations

import logging
from typing import ClassVar

from playwright.async_api import Browser, async_playwright

from fb_ads_scraper.config import settings
from fb_ads_scraper.models import ProxyEntry
from fb_ads_scraper.retry import cdp_connect_retry

from .base import BrowserBackend

log = logging.getLogger(__name__)


class ChromeBackend(BrowserBackend):
    """Connects to a headless Chrome container (browserless/chrome) over CDP.

    Per-request proxy rotation isn't possible — Chrome's proxy is set at
    process launch. To rotate, restart the container with a new CHROME_PROXY
    env value (`/proxies/rotate` on the API does this).
    """

    name: ClassVar[str] = "chrome"
    supports_per_request_proxy: ClassVar[bool] = False

    def __init__(self, cdp_url: str | None = None) -> None:
        self.cdp_url = cdp_url or settings.chrome_cdp_url
        self._pw = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        if self._pw is None:
            self._pw = await async_playwright().start()

    @cdp_connect_retry
    async def connect(self, proxy: ProxyEntry | None = None) -> Browser:
        await self.start()
        assert self._pw is not None
        if proxy is not None:
            log.warning(
                "Chrome backend ignores per-request proxy; set CHROME_PROXY and "
                "restart the container via /proxies/rotate."
            )
        log.info("Connecting to Chrome CDP at %s", self.cdp_url)
        self._browser = await self._pw.chromium.connect_over_cdp(self.cdp_url)
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
