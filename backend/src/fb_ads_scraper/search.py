from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from collections.abc import Awaitable, Callable
from urllib.parse import quote, urlparse

from playwright.async_api import Browser, Page
from playwright.async_api import Error as PWError
from playwright.async_api import TimeoutError as PWTimeout

from fb_ads_scraper.browser import dismiss_consent, new_context
from fb_ads_scraper.browser_extract import (
    extract_ads_via_dom,
    extract_ads_via_ssr_json,
    merge_ads,
)
from fb_ads_scraper.config import settings
from fb_ads_scraper.fb_challenge import maybe_solve_challenge
from fb_ads_scraper.humanize import HumanCursor
from fb_ads_scraper.intercept import GraphQLInterceptor
from fb_ads_scraper.models import Ad, InputType, SearchRequest
from fb_ads_scraper.parser import (
    find_page_ids,
    page_id_from_html,
    parse_dom_fallback,
    parse_graphql_payload,
)
from fb_ads_scraper.selector_discovery import (
    PaginationStrategy,
    discover_pagination,
    execute_pagination,
)

log = logging.getLogger(__name__)

ADS_LIBRARY = "https://www.facebook.com/ads/library/"
_PAGE_ID_RE = re.compile(r"\b\d{6,20}\b")

ProgressCb = Callable[[int, int], Awaitable[None]]  # (pages_scrolled, ad_count) -> None


def slug_from_url(value: str) -> str:
    """Pull the slug off a facebook.com profile URL."""
    parsed = urlparse(value)
    parts = [p for p in (parsed.path or "").split("/") if p]
    return parts[0] if parts else value


def _encode_param(value: str) -> str:
    # FB keeps [] unescaped in sort_data[direction]; mirror that.
    return quote(str(value), safe="[]")


def _serialise_params(params: list[tuple[str, str]]) -> str:
    return "&".join(f"{_encode_param(k)}={_encode_param(v)}" for k, v in params if v != "")


def _derive_search_type(req: SearchRequest) -> str:
    if req.search_type:
        return req.search_type
    if req.input_type is InputType.keyword:
        return "keyword_unordered"
    return "page"


def build_url_from_request(req: SearchRequest, *, resolved_value: str | None = None) -> str:
    """Build the FB Ads Library URL with every configurable param wired in."""
    value = resolved_value if resolved_value is not None else req.value
    params: list[tuple[str, str]] = [
        ("active_status", req.active_status),
        ("ad_type", req.ad_type),
        ("country", req.country),
        ("is_targeted_country", "true" if req.is_targeted_country else "false"),
        ("media_type", req.media_type),
    ]

    search_type = _derive_search_type(req)
    if req.input_type is InputType.keyword:
        params.append(("q", value))
        params.append(("search_type", search_type))
    else:
        if value.isdigit():
            params.append(("view_all_page_id", value))
            params.append(("search_type", "page"))
        else:
            slug = slug_from_url(value) if req.input_type is InputType.page_url else value
            params.append(("q", slug))
            params.append(("search_type", search_type))

    params.append(("sort_data[direction]", req.sort_direction))
    params.append(("sort_data[mode]", req.sort_mode))
    if req.source:
        params.append(("source", req.source))
    for k, v in req.extra_params.items():
        params.append((k, v))
    return f"{ADS_LIBRARY}?{_serialise_params(params)}"


def build_url(
    *,
    input_type: InputType,
    value: str,
    country: str = "ALL",
    ad_type: str = "all",
    media_type: str = "all",
    active_status: str = "all",
    is_targeted_country: bool = False,
    search_type: str | None = None,
    sort_direction: str = "desc",
    sort_mode: str = "relevancy_monthly_grouped",
    source: str | None = None,
) -> str:
    """Back-compat thin wrapper. Prefer build_url_from_request."""
    req = SearchRequest(
        input_type=input_type,
        value=value,
        country=country,
        ad_type=ad_type,
        media_type=media_type,
        active_status=active_status,  # type: ignore[arg-type]
        is_targeted_country=is_targeted_country,
        search_type=search_type,  # type: ignore[arg-type]
        sort_direction=sort_direction,  # type: ignore[arg-type]
        sort_mode=sort_mode,  # type: ignore[arg-type]
        source=source,
    )
    return build_url_from_request(req)


async def resolve_slug_to_page_id(browser: Browser, slug_or_url: str) -> str | None:
    """Resolve a Facebook page slug to its numeric page_id via the Ads Library typeahead."""
    if slug_or_url.isdigit():
        return slug_or_url
    slug = slug_from_url(slug_or_url) if "/" in slug_or_url else slug_or_url

    ctx = await new_context(browser)
    page = await ctx.new_page()
    try:
        async with GraphQLInterceptor(page) as gql:
            url = (
                f"{ADS_LIBRARY}?active_status=all&ad_type=all&country=ALL"
                f"&q={quote(slug, safe='')}&search_type=page"
            )
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except PWTimeout:
                pass
            await dismiss_consent(page)
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except PWTimeout:
                pass
            await asyncio.sleep(1.5)
            payloads = await gql.drain(timeout=2.0)

        for payload in payloads:
            for pid, name in find_page_ids(payload):
                if slug.lower() in (name or "").lower() or pid == slug:
                    return pid
            ids = find_page_ids(payload)
            if ids:
                return ids[0][0]

        html = await page.content()
        return page_id_from_html(html)
    finally:
        await ctx.close()


async def _wait_for_card_growth(
    page: Page, *, baseline: int, timeout_s: float = 8.0, poll_s: float = 0.5
) -> int:
    """Block until the rendered card count exceeds `baseline` or timeout.

    FB's IntersectionObserver fires the pagination XHR ~100ms after scroll,
    then waits for the network round-trip + React rerender. networkidle
    pops too early (no requests in flight at scroll time, then a request
    starts after that), so we poll the DOM directly for new Library IDs.
    """
    deadline = time.monotonic() + timeout_s
    last = baseline
    while time.monotonic() < deadline:
        count, _, _ = await _measure_state(page)
        if count > baseline:
            return count
        last = count
        await asyncio.sleep(poll_s)
    return last


async def _measure_state(page: Page) -> tuple[int, int, int]:
    """Return (ad_card_count, document.body.scrollHeight, current scrollY).

    Counts ad cards by 'Library ID: <digits>' text nodes — FB removed the
    `a[href*="view_ad"]` anchors a while back, so the old selector always
    returned 0 and the idle detector bailed out before pagination could
    fire. Also picks up the SSR-rendered placeholder count via length of
    `data-ad-preview` cards as a backup signal.
    """
    try:
        return await page.evaluate(
            """() => {
              let count = 0;
              const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
              let n;
              while ((n = walker.nextNode())) {
                if (/Library ID:\\s*\\d{6,20}/.test(n.nodeValue || '')) count++;
              }
              if (count === 0) {
                count = document.querySelectorAll('[data-ad-preview], div[role=\"article\"]').length;
              }
              return [
                count,
                document.body.scrollHeight | 0,
                Math.floor(window.scrollY || window.pageYOffset || 0),
              ];
            }"""
        )
    except Exception:
        return (0, 0, 0)


async def _end_sentinel_visible(page: Page) -> bool:
    try:
        return await page.evaluate(
            """() => {
                const text = document.body.innerText || '';
                return /End of Results|No ads to show|no results/i.test(text);
            }"""
        )
    except Exception:
        return False


async def _human_pause(low: float = 0.6, high: float = 1.8) -> None:
    """Sleep a randomised, slightly long-tailed amount. Mimics reading time."""
    base = random.uniform(low, high)
    if random.random() < 0.12:  # ~12% chance of a longer pause
        base += random.uniform(1.0, 2.5)
    await asyncio.sleep(base)


async def _jitter_mouse(page: Page, cursor: HumanCursor) -> None:
    """Drift the cursor through a few nearby points on a bezier path."""
    try:
        for _ in range(random.randint(1, 3)):
            await cursor.jitter(page, radius=random.randint(40, 140))
            await asyncio.sleep(random.uniform(0.05, 0.18))
    except Exception:
        pass


async def _human_scroll_step(page: Page, cursor: HumanCursor, *, viewport_h: int) -> None:
    """One pagination step.

    Big enough to reach the IntersectionObserver sentinel at the bottom of
    the rendered list (FB pages are 10–35K px tall, growing as more cards
    load), but split into sub-events with variable timing so it doesn't
    look like one robotic `scrollTo(bottom)`. Trailing "land at bottom"
    guarantees the sentinel is hit even if cumulative wheel events fall
    short.
    """
    # Occasionally drift the cursor toward the lower half before scrolling.
    if random.random() < 0.4:
        vp = page.viewport_size or {"width": 1366, "height": 900}
        tx = random.uniform(vp["width"] * 0.2, vp["width"] * 0.8)
        ty = random.uniform(vp["height"] * 0.45, vp["height"] * 0.85)
        try:
            await cursor.move_to(page, tx, ty, duration=random.uniform(0.25, 0.6))
        except Exception:
            pass

    # 2–4× viewport per step (was 0.5–1.4 — too small to clear the sentinel).
    delta = random.randint(int(viewport_h * 2.0), int(viewport_h * 4.0))
    sub_steps = random.randint(3, 6)
    chunk = delta // sub_steps
    for _ in range(sub_steps):
        try:
            await page.mouse.wheel(0, chunk)
        except Exception:
            await page.evaluate(f"window.scrollBy(0, {chunk})")
        await asyncio.sleep(random.uniform(0.08, 0.22))

    # Make absolutely sure we land at (or past) the current page bottom so
    # the IntersectionObserver fires the next page XHR.
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    except Exception:
        pass


def _gemini_enabled() -> bool:
    """LLM-driven pagination is opt-in: enabled only when GEMINI_API_KEY is set."""
    return bool(os.getenv("GEMINI_API_KEY"))


async def scroll_until_done(
    page: Page,
    *,
    max_pages: int = 200,
    idle_rounds: int = 3,
    max_seconds: int | None = None,
    on_progress: ProgressCb | None = None,
    cursor: HumanCursor | None = None,
) -> int:
    """Paginate FB Ads Library results.

    Two paths:
    - **GEMINI_API_KEY set:** LLM-driven. Gemini 2.5 Flash inspects a
      screenshot once per session and decides whether to scroll or click a
      "Load more" selector. Re-prompts on idle to adapt to DOM changes.
    - **GEMINI_API_KEY unset (default):** original scroll-to-bottom loop
      with human-like wheel events. No external API calls.

    Idle-round detection bails when nothing new renders either way.
    """
    max_seconds = max_seconds or settings.scroll_max_seconds
    cursor = cursor or HumanCursor()
    started = time.monotonic()
    idle = 0
    last_count, last_height, _ = await _measure_state(page)
    vp = page.viewport_size or {"width": 1366, "height": 900}
    viewport_h = vp["height"]
    round_idx = 0

    use_llm = _gemini_enabled()
    strategy: PaginationStrategy | None = None
    if use_llm:
        strategy = await discover_pagination(page, task="load more ad results below the visible cards")
        log.info("LLM pagination strategy: %s", strategy)
    else:
        log.debug("GEMINI_API_KEY not set — using plain scroll pagination")

    for round_idx in range(1, max_pages + 1):
        if time.monotonic() - started > max_seconds:
            log.info("scroll_until_done: time cap %ds reached", max_seconds)
            break

        try:
            if random.random() < 0.18:
                await _jitter_mouse(page, cursor)

            if use_llm and strategy is not None:
                acted = await execute_pagination(page, strategy)
                if not acted:
                    log.info("scroll_until_done: strategy returned no-action; stopping")
                    break
                if random.random() < 0.5:
                    await _human_scroll_step(page, cursor, viewport_h=viewport_h)
            else:
                await _human_scroll_step(page, cursor, viewport_h=viewport_h)

            # Best-effort networkidle (often pops before XHR even starts).
            try:
                await page.wait_for_load_state(
                    "networkidle",
                    timeout=random.randint(2200, settings.networkidle_timeout_ms + 1200),
                )
            except PWTimeout:
                pass

            # The reliable signal: poll for new Library ID cards rendered.
            count = await _wait_for_card_growth(page, baseline=last_count, timeout_s=8.0)
            _, height, _ = await _measure_state(page)

            # Small human-feeling dwell *after* new cards have settled.
            await _human_pause(0.4, 1.1)
            if on_progress:
                await on_progress(round_idx, count)
        except PWError as exc:
            # Browser session ended mid-round (browserless TIMEOUT, OOM,
            # remote disconnect). Bail out cleanly so the caller can still
            # process whatever GraphQL XHRs were captured before death.
            log.warning("scroll_until_done: page closed mid-round %d (%s)", round_idx, exc)
            break

        unchanged = count == last_count and height == last_height
        end_visible = await _end_sentinel_visible(page) if unchanged else False
        if unchanged and end_visible:
            log.info("scroll_until_done: end-of-results sentinel reached")
            break
        if unchanged:
            idle += 1
            await _jitter_mouse(page, cursor)
            await _human_pause(1.5, 3.5)
            try:
                if random.random() < 0.5:
                    await page.keyboard.press("PageDown")
            except Exception:
                pass
            # If LLM mode and stuck, re-prompt — the DOM may have changed
            # (e.g. a "Load more" button just appeared).
            if use_llm and idle == max(1, idle_rounds - 1):
                log.info("Re-discovering pagination strategy after %d idle rounds", idle)
                strategy = await discover_pagination(
                    page,
                    task="load more ad results below the visible cards",
                    force_refresh=True,
                )
                log.info("New pagination strategy: %s", strategy)
            if idle >= idle_rounds:
                log.info("scroll_until_done: %d idle rounds, stopping", idle)
                break
        else:
            idle = 0
        last_count, last_height = count, height

    return round_idx


async def _human_warmup(page: Page, cursor: HumanCursor) -> None:
    """Pre-scroll dwell: drift cursor, then wait for the initial card list
    to render before any pagination scroll fires.

    The IntersectionObserver that loads more results gets attached only
    after the first batch of cards has mounted. If we scroll before that
    happens, the observer isn't watching the sentinel yet and no XHR
    fires. Polling for `Library ID:` text is the cleanest "ready" signal.
    """
    await _human_pause(0.6, 1.4)
    try:
        await cursor.move_into_viewport(page)
    except Exception:
        pass
    await _human_pause(0.4, 1.0)
    await _jitter_mouse(page, cursor)

    # Wait up to 20s for the React app to render its first batch of cards.
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        count, _, _ = await _measure_state(page)
        if count > 0:
            log.info("Initial card render detected (%d cards) — proceeding to scroll", count)
            await _human_pause(0.6, 1.4)  # one more beat
            return
        await asyncio.sleep(0.5)
    log.info("Warmup timed out waiting for cards — scrolling anyway")


async def run_search_request(
    *,
    browser: Browser,
    request: SearchRequest,
    on_progress: ProgressCb | None = None,
) -> list[Ad]:
    """Top-level scrape driven by a fully-configured SearchRequest."""
    input_type = request.input_type
    value = request.value
    resolved_value: str | None = None

    if input_type in (InputType.page_url, InputType.slug):
        if not value.isdigit():
            resolved = await resolve_slug_to_page_id(browser, value)
            if resolved:
                log.info("Resolved %r → page_id %s", value, resolved)
                resolved_value = resolved
            else:
                log.warning("Could not resolve %r to a page_id; falling back to keyword search", value)
                # Treat as keyword for URL building only.
                request = request.model_copy(update={"input_type": InputType.keyword})

    url = build_url_from_request(request, resolved_value=resolved_value)
    log.info("Opening %s", url)

    ctx = await new_context(browser)
    page = await ctx.new_page()
    cursor = HumanCursor()

    # State that survives any failure mid-flow — these accumulate as we go,
    # so even an unexpected exception (network blip, browserless OOM, FB
    # 5xx) can't take away ads we've already captured.
    payloads: list = []
    graphql_ads: dict[str, Ad] = {}
    ssr_ads: dict[str, Ad] = {}
    dom_ads: list[Ad] = []
    merged: list[Ad] = []

    try:
        async with GraphQLInterceptor(page) as gql:
            try:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                except PWTimeout:
                    log.warning("Initial goto timed out — continuing anyway")

                # FB serves a JS challenge stub before the real page. Real Chrome
                # auto-resolves it; the handler is a no-op there but kept as a
                # fallback for CDP shims that don't run inline <script> tags.
                if await maybe_solve_challenge(page, url):
                    log.info("Challenge solved; re-loaded ads library page")

                await dismiss_consent(page)
                await _human_warmup(page, cursor)

                await scroll_until_done(
                    page,
                    max_pages=request.max_pages,
                    idle_rounds=settings.scroll_idle_rounds,
                    on_progress=on_progress,
                    cursor=cursor,
                )
            except Exception as exc:
                # Any unexpected failure during scroll/navigation — we still
                # want whatever was captured up to this point.
                log.warning("Scrape interrupted mid-flow: %s: %s", type(exc).__name__, exc)

            # Always attempt to drain whatever the interceptor caught,
            # even on partial failure. The queue lives in api memory.
            try:
                payloads = await gql.drain(timeout=2.5)
            except Exception as exc:
                log.warning("gql.drain failed: %s", exc)

            # Strategy 1 — GraphQL XHR interception (richest fields).
            for payload in payloads:
                try:
                    for ad in parse_graphql_payload(payload):
                        graphql_ads.setdefault(ad.ad_archive_id, ad)
                except Exception as exc:
                    log.debug("parse_graphql_payload skipped a payload: %s", exc)
            log.info("Captured %d ads from GraphQL XHRs", len(graphql_ads))

            # Strategies 2 & 3 need the page alive. Wrap each independently
            # so one extractor's failure doesn't block the other or the merge.
            try:
                ssr_payloads = await extract_ads_via_ssr_json(page)
                for payload in ssr_payloads:
                    for ad in parse_graphql_payload(payload):
                        ssr_ads.setdefault(ad.ad_archive_id, ad)
                log.info("Captured %d ads from SSR inline JSON", len(ssr_ads))
            except Exception as exc:
                log.info("SSR extraction unavailable (%s): %s", type(exc).__name__, exc)

            try:
                dom_ads = await extract_ads_via_dom(page)
                log.info("Captured %d ads from live DOM", len(dom_ads))
            except Exception as exc:
                log.info("Live-DOM extraction unavailable (%s): %s", type(exc).__name__, exc)

        # Merge: GraphQL richest; fill empty fields from SSR then DOM.
        try:
            merged = merge_ads(list(graphql_ads.values()), list(ssr_ads.values()))
            merged = merge_ads(merged, dom_ads)
        except Exception as exc:
            # Merge errors are extremely unlikely but we'd rather return a
            # naive concatenation than 0 ads.
            log.warning("merge_ads failed (%s) — falling back to union", exc)
            seen: set[str] = set()
            merged = []
            for ad in list(graphql_ads.values()) + list(ssr_ads.values()) + dom_ads:
                if ad.ad_archive_id in seen:
                    continue
                seen.add(ad.ad_archive_id)
                merged.append(ad)

        # Strategy 4 — last-resort static HTML parse with selectolax.
        if not merged:
            try:
                log.info("All extractors empty — trying static HTML fallback")
                html = await page.content()
                merged = parse_dom_fallback(html)
            except Exception as exc:
                log.info("Static HTML fallback unavailable (%s): %s", type(exc).__name__, exc)
    except Exception as exc:
        # Catch-all guard: never let a scrape error surface as an empty
        # result. Anything we already accumulated in merged/{graphql,ssr,
        # dom}_ads wins over a hard failure.
        log.warning("Unexpected scrape error (%s): %s — returning partial results", type(exc).__name__, exc)
        if not merged:
            seen2: set[str] = set()
            for ad in list(graphql_ads.values()) + list(ssr_ads.values()) + dom_ads:
                if ad.ad_archive_id in seen2:
                    continue
                seen2.add(ad.ad_archive_id)
                merged.append(ad)
    finally:
        try:
            await ctx.close()
        except Exception:
            pass

    log.info("run_search_request returning %d ads", len(merged))
    return merged


async def run_search(
    *,
    browser: Browser,
    input_type: InputType,
    value: str,
    country: str = "ALL",
    ad_type: str = "all",
    max_pages: int = 50,
    on_progress: ProgressCb | None = None,
) -> list[Ad]:
    """Back-compat entry point. Prefer run_search_request."""
    req = SearchRequest(
        input_type=input_type,
        value=value,
        country=country,
        ad_type=ad_type,
        max_pages=max_pages,
    )
    return await run_search_request(browser=browser, request=req, on_progress=on_progress)
