"""Extract ads from the live, rendered Ads Library DOM via page.evaluate().

Runs inside Playwright against the actual DOM the user sees — picks
up ads even when GraphQL interception missed them (e.g. cached pages, pre-
rendered content, alternative render paths). Complements GraphQLInterceptor.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from playwright.async_api import Page

from fb_ads_scraper.models import Ad

log = logging.getLogger(__name__)


# JS that runs in the page context. Returns a list of raw ad dicts; Python
# side converts to Ad models. Kept as a single string so playwright can ship
# it across CDP in one shot.
_EXTRACT_JS = r"""
() => {
  const cards = [];
  const seen = new Set();

  // FB no longer renders ad-card detail links as anchor tags — the new DOM
  // wraps everything in clickable <div>s. The most reliable signal is the
  // "Library ID: <digits>" text that every card displays.
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const anchorNodes = [];
  let n;
  while ((n = walker.nextNode())) {
    const m = (n.nodeValue || "").match(/Library ID:\s*(\d{6,20})/);
    if (m) anchorNodes.push({ node: n, adId: m[1] });
  }

  for (const { node, adId } of anchorNodes) {
    if (seen.has(adId)) continue;
    seen.add(adId);

    // Walk up to find a container that holds exactly one Library ID node.
    // Stop just before the container starts including sibling cards.
    let card = node.parentElement;
    if (!card) continue;
    for (let depth = 0; depth < 14; depth++) {
      const parent = card.parentElement;
      if (!parent) break;
      const idMatches = (parent.textContent || "").match(/Library ID:\s*\d{6,20}/g) || [];
      if (idMatches.length > 1) break;
      card = parent;
    }
    const link = card;  // alias kept for downstream `card.querySelectorAll(...)`

    const text = (el) => (el ? (el.innerText || el.textContent || '').trim() : '');
    const cardText = text(card);

    // Page name: nearest strong/header link inside the card.
    let pageName = null;
    const pageHeader = card.querySelector(
      "a[href*='view_all_page_id'] span, a[role='link'] span[dir='auto'] strong, " +
      "a[role='link'] strong"
    );
    if (pageHeader) pageName = text(pageHeader) || null;
    if (!pageName) {
      const firstLink = card.querySelector("a[role='link']");
      if (firstLink) pageName = text(firstLink) || null;
    }

    // Page id: pull from any link with view_all_page_id.
    let pageId = null;
    const pageIdLink = card.querySelector("a[href*='view_all_page_id']");
    if (pageIdLink) {
      const pm = (pageIdLink.getAttribute('href') || '').match(/view_all_page_id=(\d+)/);
      if (pm) pageId = pm[1];
    }

    // Body text: the largest dir='auto' block in the card, excluding the header.
    let bodyText = null;
    const candidates = [...card.querySelectorAll("div[data-ad-preview] [dir='auto'], [dir='auto']")];
    let best = '';
    for (const c of candidates) {
      const t = text(c);
      if (t.length > best.length && t !== pageName) best = t;
    }
    if (best) bodyText = best;

    // CTA text
    let ctaText = null;
    const ctaEl = card.querySelector(
      "div[role='button'] span[dir='auto'], a[role='button'] span[dir='auto'], " +
      "div[role='button'] span, a[role='button'] span"
    );
    if (ctaEl) ctaText = text(ctaEl) || null;

    // Landing URL: FB wraps external destinations as l.facebook.com/l.php?u=<encoded>
    // Unwrap so we get the real URL. Fall back to any non-facebook link.
    let landingUrl = null;
    for (const a of card.querySelectorAll('a')) {
      const h = a.href || '';
      if (!/^https?:/i.test(h)) continue;
      if (h.includes('l.facebook.com/l.php')) {
        try {
          const u = new URL(h).searchParams.get('u');
          if (u) { landingUrl = decodeURIComponent(u); break; }
        } catch (e) {}
      }
      if (h.includes('facebook.com') || h.includes('fb.com') || h.includes('fb.me')) continue;
      landingUrl = h;
      break;
    }

    // Media
    const images = [];
    for (const img of card.querySelectorAll('img')) {
      const src = img.currentSrc || img.src || '';
      if (!src || src.startsWith('data:')) continue;
      // Skip page avatars + tiny tracking pixels.
      const w = img.naturalWidth || img.width || 0;
      const h = img.naturalHeight || img.height || 0;
      if (w > 0 && w < 60 && h < 60) continue;
      images.push(src);
    }
    const videos = [];
    for (const vid of card.querySelectorAll('video')) {
      const src = vid.currentSrc || vid.src || vid.poster || '';
      if (src && !src.startsWith('data:')) videos.push(src);
    }

    // Active / inactive — FB shows the badge somewhere in the card text.
    let isActive = null;
    const lower = cardText.toLowerCase();
    if (/\bactive\b/.test(lower) && !/\binactive\b/.test(lower)) isActive = true;
    else if (/\binactive\b/.test(lower)) isActive = false;

    // Date snippets — "Started running on Mar 5, 2024" style.
    let startDateRaw = null;
    let endDateRaw = null;
    let m1 = cardText.match(/(?:started\s+running\s+on|started)\s+([A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4})/i);
    if (m1) startDateRaw = m1[1];
    let m2 = cardText.match(/(?:ran\s+for|–\s|-\s)([A-Z][a-z]{2,9}\s+\d{1,2},\s+\d{4})\s*$/i);
    if (m2) endDateRaw = m2[1];

    // Platforms — small icons usually labelled "Facebook", "Instagram", etc.
    const platforms = new Set();
    for (const p of ['Facebook', 'Instagram', 'Audience Network', 'Messenger', 'Threads']) {
      if (new RegExp('\\b' + p + '\\b', 'i').test(cardText)) platforms.add(p.toLowerCase());
    }

    cards.push({
      ad_archive_id: adId,
      page_id: pageId,
      page_name: pageName,
      body_text: bodyText,
      cta_text: ctaText,
      landing_url: landingUrl,
      images,
      videos,
      is_active: isActive,
      start_date_raw: startDateRaw,
      end_date_raw: endDateRaw,
      platforms: [...platforms],
    });
  }

  return cards;
}
"""


_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
_DATE_RE = re.compile(r"([A-Z][a-z]{2,9})\s+(\d{1,2}),\s+(\d{4})")


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    m = _DATE_RE.search(raw)
    if not m:
        return None
    mon_name = m.group(1)[:3]
    mon = _MONTHS.get(mon_name.capitalize())
    if mon is None:
        return None
    try:
        return datetime(int(m.group(3)), mon, int(m.group(2)), tzinfo=UTC)
    except ValueError:
        return None


def _to_ad(raw: dict[str, Any]) -> Ad | None:
    ad_id = raw.get("ad_archive_id")
    if not ad_id:
        return None
    try:
        return Ad(
            ad_archive_id=str(ad_id),
            page_id=str(raw["page_id"]) if raw.get("page_id") else None,
            page_name=raw.get("page_name"),
            start_date=_parse_date(raw.get("start_date_raw")),
            end_date=_parse_date(raw.get("end_date_raw")),
            is_active=raw.get("is_active"),
            publisher_platforms=raw.get("platforms") or [],
            body_text=raw.get("body_text"),
            cta_text=raw.get("cta_text"),
            images=[u for u in (raw.get("images") or []) if u],
            videos=[u for u in (raw.get("videos") or []) if u],
            landing_url=raw.get("landing_url"),
        )
    except Exception as exc:
        log.debug("Skipping malformed DOM ad: %s", exc)
        return None


async def extract_ads_via_dom(page: Page) -> list[Ad]:
    """Run the in-page extractor and convert results to Ad models."""
    try:
        raw_ads = await page.evaluate(_EXTRACT_JS)
    except Exception as exc:
        log.warning("Live DOM extraction failed: %s", exc)
        return []
    out: list[Ad] = []
    for raw in raw_ads or []:
        ad = _to_ad(raw)
        if ad is not None:
            out.append(ad)
    return out


# Extract every <script> tag whose text JSON-parses and somewhere contains
# "ad_archive_id". FB SSR-renders the first page of results as inline JSON
# in `adp_AdLibraryFoundationRootQueryRelayPreloader_*` blobs — this picks
# them up without needing the React app to render anything.
_SSR_JSON_EXTRACT_JS = r"""
() => {
  const out = [];
  const scripts = document.querySelectorAll('script');
  for (const s of scripts) {
    const text = s.textContent || '';
    if (!text || !text.includes('"ad_archive_id"')) continue;
    try {
      out.push(JSON.parse(text));
    } catch (e) {
      // Some inline JSON is concatenated objects separated by newlines.
      for (const chunk of text.split(/\n(?=\{)/)) {
        const t = chunk.trim();
        if (!t || !t.includes('"ad_archive_id"')) continue;
        try { out.push(JSON.parse(t)); } catch (e2) {}
      }
    }
  }
  return out;
}
"""


async def extract_ads_via_ssr_json(page: Page):
    """Pull raw FB SSR JSON payloads out of inline <script> tags.

    Returns a list of dicts. Feed each one through
    `parser.parse_graphql_payload` — the existing walker handles them
    because it just descends any dict tree looking for ad_archive_id.
    """
    try:
        return await page.evaluate(_SSR_JSON_EXTRACT_JS) or []
    except Exception as exc:
        log.warning("SSR JSON extraction failed: %s", exc)
        return []


def merge_ads(graphql_ads: list[Ad], dom_ads: list[Ad]) -> list[Ad]:
    """Prefer GraphQL ads (richer), fill gaps from DOM by ad_archive_id."""
    by_id: dict[str, Ad] = {a.ad_archive_id: a for a in graphql_ads}
    for ad in dom_ads:
        if ad.ad_archive_id in by_id:
            existing = by_id[ad.ad_archive_id]
            # Promote DOM fields that GraphQL left empty.
            patch: dict[str, Any] = {}
            if not existing.page_name and ad.page_name:
                patch["page_name"] = ad.page_name
            if not existing.body_text and ad.body_text:
                patch["body_text"] = ad.body_text
            if not existing.cta_text and ad.cta_text:
                patch["cta_text"] = ad.cta_text
            if not existing.landing_url and ad.landing_url:
                patch["landing_url"] = ad.landing_url
            if not existing.images and ad.images:
                patch["images"] = ad.images
            if not existing.videos and ad.videos:
                patch["videos"] = ad.videos
            if patch:
                by_id[ad.ad_archive_id] = existing.model_copy(update=patch)
        else:
            by_id[ad.ad_archive_id] = ad
    return list(by_id.values())
