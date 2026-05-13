"""LLM-driven pagination strategy discovery for resilient scraping.

FB changes its DOM frequently — hardcoded "See more" / "Load more" selectors
break. This module asks Gemini 2.5 Flash to look at the current page (via a
viewport screenshot) and decide how to load more results: scroll, button
click, or end-of-results. Results are cached per-URL with a 10-minute TTL
so we don't pay an API call per scroll round.

Usage:
    strategy = await discover_pagination(page, task="load more ad results")
    while ...:
        ok = await execute_pagination(page, strategy)
        if not ok: break

Falls back to plain-scroll if `GEMINI_API_KEY` is unset or the call fails.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from dataclasses import dataclass

import httpx
from playwright.async_api import Page

log = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
CACHE_TTL = 10 * 60  # 10 minutes


@dataclass
class PaginationStrategy:
    type: str  # "scroll" | "button" | "none"
    selector: str | None = None
    notes: str = ""
    via: str = "default"  # "gemini" | "default" | "fallback:<reason>"


_cache: dict[str, tuple[PaginationStrategy, float]] = {}


_PROMPT = """You are inspecting a screenshot of a search-results page (Facebook Ads Library).

Your task: identify how to load **more** results beyond what's currently visible.

Pick ONE of:
- "scroll" — pagination triggers automatically when you scroll to the bottom (infinite scroll / IntersectionObserver).
- "button" — there is a clickable element (button or div with role=button) at the bottom of results that loads more when clicked.
- "none" — the page shows an explicit end-of-results marker, OR the page is an error / login wall with no path to more data.

If you choose "button", provide a CSS selector that would uniquely match it. Prefer text-based or aria-label matches over class names (class names churn).

Reply with ONLY a JSON object — no markdown fences, no commentary:
{"type":"scroll"|"button"|"none", "selector": "...", "notes": "one short sentence"}
"""


async def discover_pagination(
    page: Page,
    task: str = "load more ad results",
    *,
    force_refresh: bool = False,
) -> PaginationStrategy:
    """Ask Gemini what triggers more results on the current page."""
    cache_key = f"{page.url}|{task}"
    now = time.time()
    if not force_refresh and cache_key in _cache:
        strat, when = _cache[cache_key]
        if now - when < CACHE_TTL:
            return strat

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log.info("GEMINI_API_KEY not set — defaulting to scroll strategy")
        return PaginationStrategy(type="scroll", via="fallback:no_api_key")

    # Scroll the page so the screenshot captures the *bottom* of current
    # content — that's where any load-more affordance would live.
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1.2)
        screenshot = await page.screenshot(full_page=False)
    except Exception as exc:
        log.warning("Screenshot capture failed: %s", exc)
        return PaginationStrategy(type="scroll", via=f"fallback:screenshot_err:{type(exc).__name__}")

    body = {
        "contents": [
            {
                "parts": [
                    {"text": _PROMPT + f"\n\n(Specific task hint: {task})"},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(screenshot).decode(),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0,
            "maxOutputTokens": 256,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{GEMINI_URL}?key={api_key}", json=body)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        log.warning("Gemini call failed: %s", exc)
        return PaginationStrategy(type="scroll", via=f"fallback:gemini_err:{type(exc).__name__}")

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except Exception as exc:
        log.warning("Gemini response parse failed: %s | raw: %s", exc, str(data)[:300])
        return PaginationStrategy(type="scroll", via=f"fallback:parse_err:{type(exc).__name__}")

    strat = PaginationStrategy(
        type=parsed.get("type", "scroll"),
        selector=parsed.get("selector") or None,
        notes=parsed.get("notes", ""),
        via="gemini",
    )
    _cache[cache_key] = (strat, now)
    log.info(
        "Pagination strategy via Gemini: type=%s selector=%s notes=%s",
        strat.type,
        strat.selector,
        strat.notes,
    )
    return strat


async def execute_pagination(page: Page, strategy: PaginationStrategy) -> bool:
    """Trigger one pagination step. Returns True if an action was performed."""
    if strategy.type == "none":
        return False
    if strategy.type == "button" and strategy.selector:
        try:
            locator = page.locator(strategy.selector).first
            await locator.scroll_into_view_if_needed(timeout=3000)
            await locator.click(timeout=5000)
            return True
        except Exception as exc:
            log.warning(
                "Pagination click on %r failed (%s) — falling back to scroll",
                strategy.selector,
                type(exc).__name__,
            )
            # Fall through to scroll as a safety net.
    # Default + fallback path: scroll to bottom.
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        return True
    except Exception:
        return False
