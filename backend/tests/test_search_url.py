"""URL builder reproduces the exact FB Ads Library URL format."""

from fb_ads_scraper.models import InputType, SearchRequest
from fb_ads_scraper.search import build_url_from_request, slug_from_url


def test_reproduces_target_url_byte_for_byte():
    """The keyword/country/sort/source combo round-trips to FB's exact format."""
    target = (
        "https://www.facebook.com/ads/library/"
        "?active_status=active&ad_type=all&country=BD"
        "&is_targeted_country=false&media_type=all"
        "&q=health&search_type=keyword_unordered"
        "&sort_data[direction]=desc&sort_data[mode]=total_impressions"
        "&source=fb-logo"
    )
    req = SearchRequest(
        input_type=InputType.keyword,
        value="health",
        country="BD",
        active_status="active",
        sort_mode="total_impressions",
        source="fb-logo",
    )
    assert build_url_from_request(req) == target


def test_keeps_sort_data_brackets_unescaped():
    """FB doesn't URL-encode the `[]` in sort_data — we mirror that."""
    req = SearchRequest(input_type=InputType.keyword, value="x")
    url = build_url_from_request(req)
    assert "sort_data[direction]=desc" in url
    assert "sort_data%5Bdirection%5D" not in url


def test_keyword_search_type_derived():
    req = SearchRequest(input_type=InputType.keyword, value="x")
    assert "search_type=keyword_unordered" in build_url_from_request(req)


def test_numeric_value_uses_view_all_page_id():
    req = SearchRequest(input_type=InputType.page_url, value="123456789")
    url = build_url_from_request(req)
    assert "view_all_page_id=123456789" in url
    assert "search_type=page" in url


def test_extra_params_appended():
    req = SearchRequest(
        input_type=InputType.keyword,
        value="x",
        extra_params={"sort_data[custom]": "foo"},
    )
    assert "sort_data[custom]=foo" in build_url_from_request(req)


def test_slug_from_url_strips_domain():
    assert slug_from_url("https://www.facebook.com/Nike/") == "Nike"
    assert slug_from_url("https://www.facebook.com/Nike") == "Nike"
    assert slug_from_url("Nike") == "Nike"


def test_targeted_country_flag_is_lowercase_string():
    req = SearchRequest(input_type=InputType.keyword, value="x", is_targeted_country=True)
    assert "is_targeted_country=true" in build_url_from_request(req)
    req2 = SearchRequest(input_type=InputType.keyword, value="x", is_targeted_country=False)
    assert "is_targeted_country=false" in build_url_from_request(req2)
