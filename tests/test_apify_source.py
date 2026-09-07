import json
from pathlib import Path

from har_search.sources.apify_memo23 import ApifyMemo23Source, corpus_actor_input

FIXTURES = Path(__file__).parent / "fixtures"


class StubHttp:
    """Stands in for httpx.Client. Records calls, returns canned rows."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def post(self, url, json=None, params=None, timeout=None):
        self.calls.append({"url": url, "json": json, "params": params})
        return StubResponse(self.rows)


class StubResponse:
    def __init__(self, rows):
        self._rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return self._rows


def test_fetch_corpus_returns_raw_rows():
    rows = json.loads((FIXTURES / "for_sale_spring.json").read_text())
    http = StubHttp(rows)
    source = ApifyMemo23Source(token="tok", http=http)
    result = source.fetch_corpus(area="Spring", limit=100)
    assert len(result) == 3
    assert result[0]["address"] == "5519 Lynngate Dr"


def test_fetch_corpus_sends_the_token_and_actor_path():
    http = StubHttp([])
    source = ApifyMemo23Source(token="tok", http=http)
    source.fetch_corpus(area="Spring", limit=5)
    call = http.calls[0]
    assert "memo23~har-scraper" in call["url"]
    assert call["params"]["token"] == "tok"


def test_fetch_corpus_honours_a_custom_actor():
    http = StubHttp([])
    source = ApifyMemo23Source(token="tok", actor="blackfalcondata/har-scraper", http=http)
    source.fetch_corpus(area="Spring", limit=5)
    call = http.calls[0]
    assert "blackfalcondata~har-scraper" in call["url"]
    assert "memo23" not in call["url"]


def test_fetch_sold_requests_sold_listing_type():
    http = StubHttp([])
    source = ApifyMemo23Source(token="tok", http=http)
    source.fetch_sold(area="Spring", agent_depth=25, limit=200)
    assert http.calls[0]["json"]["listingType"] == "sold"
    assert http.calls[0]["json"]["maxSoldAgents"] == 25


def test_corpus_input_carries_no_criteria():
    """The corpus is the neighbourhood, not the answer.

    Narrowing this fetch by the caller's criteria is what made the active comp
    pool circular: the budget filter reached the vendor, so a listing was only
    ever compared against listings inside the same budget. The only knobs here
    are where and how many.
    """
    payload = corpus_actor_input(area="77084", limit=100)
    assert payload["locations"] == ["77084"]
    assert payload["maxItems"] == 100
    assert payload["listingType"] == "sale"
    forbidden = {
        "minBeds",
        "minBaths",
        "maxPrice",
        "maxPricePerSqft",
        "minSqft",
        "propertyTypes",
    }
    assert forbidden.isdisjoint(payload)


def test_corpus_fetch_asks_the_vendor_for_the_corpus_payload():
    http = StubHttp([{"mlsNumber": "1"}])
    source = ApifyMemo23Source(token="t", http=http)
    source.fetch_corpus(area="77084", limit=100)
    assert http.calls[0]["json"]["maxItems"] == 100
    assert "maxPrice" not in http.calls[0]["json"]
