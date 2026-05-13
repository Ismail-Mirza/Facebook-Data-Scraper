"""Handle Facebook's `__rd_verify_*` JS challenge.

When FB sees what looks like an unverified browser, it serves a tiny HTML
page that POSTs to `/__rd_verify_<token>?challenge=N` to set an
`rd_challenge` cookie, then reloads. Real Chromium auto-handles it; we
only need to wait. A manual fallback (fetch via page.evaluate) is kept
for CDP shims that don't execute inline <script> tags.
"""

from __future__ import annotations

import asyncio
import logging
import re

from playwright.async_api import Page

log = logging.getLogger(__name__)

_CHALLENGE_FETCH_RE = re.compile(r"fetch\('(/__rd_verify_[^']+)'", re.IGNORECASE)


async def _challenge_present(page: Page) -> bool:
    try:
        html = await page.content()
    except Exception:
        return False
    return "__rd_verify_" in html


async def maybe_solve_challenge(page: Page, original_url: str) -> bool:
    """If FB served the challenge stub, ensure it gets resolved.

    First step: give the browser 5s of breathing room to run the inline
    `<script>` and navigate to the real page itself. Real Chromium does
    this on its own and we shouldn't interfere — that just races the
    browser's own navigation, throws "Execution context was destroyed"
    errors, and leaves the page in a half-loaded state. Only fall back to
    manual fetch+re-navigate on CDP shims that don't run inline scripts.
    """
    if not await _challenge_present(page):
        return False
    log.info("FB challenge stub detected — sleeping 5s for browser auto-resolve")
    await asyncio.sleep(5.0)
    # Capability check: did the browser actually clear the challenge?
    try:
        present_now = await _challenge_present(page)
    except Exception:
        # Navigation in progress — let it settle and call it good.
        try:
            await page.wait_for_load_state("load", timeout=15000)
        except Exception:
            pass
        log.info("FB challenge resolved during navigation")
        return True
    if not present_now:
        # Browser handled it. Wait for the post-challenge page to fully
        # load so callers don't race against an empty body.
        try:
            await page.wait_for_load_state("load", timeout=15000)
        except Exception:
            pass
        log.info("FB challenge auto-resolved by browser")
        return True

    # Still stuck — manual fallback for shims that don't execute <script>.
    try:
        html = await page.content()
    except Exception:
        return False
    m = _CHALLENGE_FETCH_RE.search(html)
    if not m:
        return False
    challenge_path = m.group(1)
    log.info("Manual verify required — POST %s", challenge_path)
    try:
        status = await page.evaluate(
            "async (p) => { const r = await fetch(p, {method:'POST'}); return r.status; }",
            challenge_path,
        )
        log.info("Manual verify response: %s", status)
    except Exception as exc:
        log.info("Manual verify interrupted (probably navigating): %s", exc)
        try:
            await page.wait_for_load_state("load", timeout=15000)
            return True
        except Exception:
            return False
    try:
        await page.goto(original_url, wait_until="load", timeout=45000)
        return True
    except Exception as exc:
        log.warning("Post-challenge navigation failed: %s", exc)
        return False
