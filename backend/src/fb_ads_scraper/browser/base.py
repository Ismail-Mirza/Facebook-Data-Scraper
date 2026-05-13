from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from playwright.async_api import Browser, BrowserContext, Page

from fb_ads_scraper.models import ProxyEntry


class BrowserBackend(ABC):
    name: ClassVar[str]
    supports_per_request_proxy: ClassVar[bool] = False

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def connect(self, proxy: ProxyEntry | None = None) -> Browser: ...

    @abstractmethod
    async def close(self) -> None: ...


CONSENT_SELECTOR = (
    "button:has-text('Allow all cookies'),"
    "button:has-text('Allow all'),"
    "button:has-text('Accept all'),"
    "button:has-text('Accept'),"
    "[data-cookiebanner='accept_button'],"
    "[data-testid='cookie-policy-manage-dialog-accept-button']"
)


async def new_context(browser: Browser) -> BrowserContext:
    # Intentionally NOT overriding user_agent — the underlying Chromium's
    # default UA matches its real Sec-CH-UA / userAgentData fingerprint.
    # Hardcoding a UA string that disagrees with the browser version (e.g.
    # "Chrome/145" on a Chrome/121 binary) is a strong bot signal: FB
    # serves a blank shell. Same reasoning for locale — let the browser
    # report what it actually is.
    return await browser.new_context(
        viewport={"width": 1366, "height": 900},
    )


async def dismiss_consent(page: Page) -> None:
    try:
        button = page.locator(CONSENT_SELECTOR).first
        if await button.is_visible(timeout=1500):
            await button.click(timeout=2000)
    except Exception:
        pass
