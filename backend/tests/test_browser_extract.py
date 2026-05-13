"""merge_ads: GraphQL wins; SSR/DOM fill empty fields by ad_archive_id."""

from fb_ads_scraper.browser_extract import merge_ads
from fb_ads_scraper.models import Ad


def _ad(archive_id: str, **fields) -> Ad:
    base = dict(ad_archive_id=archive_id)
    base.update(fields)
    return Ad(**base)


def test_higher_priority_keeps_rich_fields_intact():
    gql = [_ad("1", page_name="Real Page", body_text="Real body", images=["a.png"])]
    dom = [_ad("1", page_name="Stale", body_text="Stale body", images=[])]
    merged = merge_ads(gql, dom)
    assert len(merged) == 1
    assert merged[0].page_name == "Real Page"
    assert merged[0].body_text == "Real body"
    assert merged[0].images == ["a.png"]


def test_lower_priority_fills_empty_fields():
    gql = [_ad("1", page_name=None, body_text=None, landing_url=None)]
    dom = [_ad("1", page_name="From DOM", body_text="From DOM", landing_url="https://x")]
    merged = merge_ads(gql, dom)
    assert merged[0].page_name == "From DOM"
    assert merged[0].body_text == "From DOM"
    assert merged[0].landing_url == "https://x"


def test_lower_priority_contributes_new_ids():
    gql = [_ad("1", page_name="A")]
    dom = [_ad("2", page_name="B")]
    merged = {a.ad_archive_id for a in merge_ads(gql, dom)}
    assert merged == {"1", "2"}


def test_empty_inputs_return_empty():
    assert merge_ads([], []) == []


def test_only_dom_returns_dom_unchanged():
    dom = [_ad("1", page_name="A"), _ad("2", page_name="B")]
    out = merge_ads([], dom)
    assert len(out) == 2
    assert {a.ad_archive_id for a in out} == {"1", "2"}
