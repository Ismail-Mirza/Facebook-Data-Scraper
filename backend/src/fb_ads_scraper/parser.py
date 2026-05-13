from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from selectolax.parser import HTMLParser

from fb_ads_scraper.models import Ad

log = logging.getLogger(__name__)


def _walk(obj: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict found anywhere inside the GraphQL response tree."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def _to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        # Meta returns unix seconds.
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(int(value), tz=UTC)
        if isinstance(value, str) and value.isdigit():
            return datetime.fromtimestamp(int(value), tz=UTC)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _media_urls(snapshot: dict[str, Any]) -> tuple[list[str], list[str]]:
    images: list[str] = []
    videos: list[str] = []
    for img in snapshot.get("images") or []:
        url = img.get("original_image_url") or img.get("resized_image_url")
        if url:
            images.append(url)
    for vid in snapshot.get("videos") or []:
        url = vid.get("video_hd_url") or vid.get("video_sd_url") or vid.get("video_preview_image_url")
        if url:
            videos.append(url)
    for card in snapshot.get("cards") or []:
        img = card.get("original_image_url") or card.get("resized_image_url")
        if img:
            images.append(img)
        vid = card.get("video_hd_url") or card.get("video_sd_url")
        if vid:
            videos.append(vid)
    return images, videos


def parse_graphql_payload(payload: dict[str, Any]) -> list[Ad]:
    """Recursively pull every Ad-shaped node out of a GraphQL response."""
    seen: set[str] = set()
    ads: list[Ad] = []
    for node in _walk(payload):
        ad_id = node.get("ad_archive_id") or node.get("adArchiveID")
        if not ad_id or str(ad_id) in seen:
            continue
        snapshot = node.get("snapshot") or {}
        body = snapshot.get("body") or {}
        body_text = body.get("text") if isinstance(body, dict) else None
        images, videos = _media_urls(snapshot)

        spend = node.get("spend")
        impressions = node.get("impressions") or node.get("impressions_with_index")

        try:
            ad = Ad(
                ad_archive_id=str(ad_id),
                page_id=str(node.get("page_id") or snapshot.get("page_id") or "") or None,
                page_name=node.get("page_name") or snapshot.get("page_name"),
                start_date=_to_dt(node.get("start_date") or node.get("start_date_string")),
                end_date=_to_dt(node.get("end_date") or node.get("end_date_string")),
                is_active=node.get("is_active"),
                publisher_platforms=node.get("publisher_platform") or node.get("publisher_platforms") or [],
                body_text=body_text,
                cta_text=snapshot.get("cta_text"),
                cta_type=snapshot.get("cta_type"),
                display_format=snapshot.get("display_format"),
                images=images,
                videos=videos,
                landing_url=snapshot.get("link_url") or snapshot.get("caption"),
                spend=spend if isinstance(spend, dict) else None,
                impressions=impressions if isinstance(impressions, dict) else None,
                currency=node.get("currency"),
                funded_by=snapshot.get("byline") or node.get("funded_by"),
                demographic_distribution=node.get("demographic_distribution"),
                region_distribution=node.get("region_distribution"),
                eu_total_reach=node.get("eu_total_reach"),
                raw=node,
            )
            seen.add(str(ad_id))
            ads.append(ad)
        except Exception as exc:
            log.debug("Skipping malformed ad node: %s", exc)
    return ads


def find_page_ids(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (page_id, page_name) tuples found in a typeahead response."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for node in _walk(payload):
        pid = node.get("page_id") or node.get("id")
        name = node.get("name") or node.get("page_name")
        if pid and name and str(pid) not in seen and str(pid).isdigit():
            seen.add(str(pid))
            out.append((str(pid), str(name)))
    return out


_PAGE_ID_RE = re.compile(r'"page_id":"?(\d{6,20})"?')
_FB_PROFILE_RE = re.compile(r"fb://page/(\d+)/")


def page_id_from_html(html: str) -> str | None:
    m = _PAGE_ID_RE.search(html) or _FB_PROFILE_RE.search(html)
    return m.group(1) if m else None


def parse_dom_fallback(html: str) -> list[Ad]:
    """Last-ditch extraction from the rendered DOM.

    Meta's markup churns constantly — we capture the bare minimum: an ad's
    archive id from the "view details" link, page name from card header,
    body text from the first paragraph, CTA text from the button.
    """
    tree = HTMLParser(html)
    ads: list[Ad] = []
    for card in tree.css("div[role='main'] a[href*='view_ad']"):
        href = card.attributes.get("href") or ""
        m = re.search(r"id=(\d+)", href)
        if not m:
            continue
        ad_id = m.group(1)
        container = card
        for _ in range(6):
            if container.parent is None:
                break
            container = container.parent
        page_name_node = container.css_first("a[href*='/ads/library/'] strong, span[dir='auto'] strong")
        body_node = container.css_first(
            "div[data-ad-preview] div[dir='auto'], div[role='article'] div[dir='auto']"
        )
        cta_node = container.css_first("div[role='button'] span, a[role='button'] span")
        try:
            ads.append(
                Ad(
                    ad_archive_id=ad_id,
                    page_name=page_name_node.text(strip=True) if page_name_node else None,
                    body_text=body_node.text(strip=True) if body_node else None,
                    cta_text=cta_node.text(strip=True) if cta_node else None,
                )
            )
        except Exception:
            continue
    return ads
