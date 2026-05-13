"""GraphQL walker + dedupe behavior on representative FB-shaped payloads."""

from fb_ads_scraper.parser import find_page_ids, page_id_from_html, parse_graphql_payload


def test_extracts_minimal_ad():
    payload = {
        "data": {
            "search_results_connection": {
                "edges": [
                    {
                        "node": {
                            "collated_results": [
                                {
                                    "ad_archive_id": "999000111",
                                    "page_id": "123",
                                    "is_active": True,
                                    "snapshot": {
                                        "page_name": "Test Page",
                                        "body": {"text": "Hello world"},
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        }
    }
    ads = parse_graphql_payload(payload)
    assert len(ads) == 1
    a = ads[0]
    assert a.ad_archive_id == "999000111"
    assert a.page_id == "123"
    assert a.page_name == "Test Page"
    assert a.body_text == "Hello world"
    assert a.is_active is True


def test_dedupes_repeated_ids_in_one_payload():
    payload = {
        "items": [
            {"ad_archive_id": "1", "snapshot": {}},
            {"ad_archive_id": "1", "snapshot": {}},  # duplicate
            {"ad_archive_id": "2", "snapshot": {}},
        ]
    }
    ids = sorted(a.ad_archive_id for a in parse_graphql_payload(payload))
    assert ids == ["1", "2"]


def test_finds_page_ids_in_typeahead_response():
    payload = {
        "results": [
            {"page_id": "111", "name": "Acme"},
            {"page_id": "222", "name": "Beta"},
        ]
    }
    pairs = find_page_ids(payload)
    assert ("111", "Acme") in pairs
    assert ("222", "Beta") in pairs


def test_page_id_from_html_finds_first_match():
    html = '<html><body data-page="x"> "page_id":"987654321" </body></html>'
    assert page_id_from_html(html) == "987654321"


def test_handles_empty_payload():
    assert parse_graphql_payload({}) == []
    assert parse_graphql_payload({"data": None}) == []
