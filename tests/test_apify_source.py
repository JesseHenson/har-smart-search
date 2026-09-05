import json
from pathlib import Path

from har_search.core.models import Criteria
from har_search.sources.apify_memo23 import ApifyMemo23Source, criteria_to_actor_input

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


def test_criteria_map_onto_actor_input():
    criteria = Criteria(
        area="Spring",
        beds=3,
        baths=2,
        max_price=250_000,
        max_price_per_sqft=120,
        property_types=["duplex"],
        no_hoa=True,
    )
    payload = criteria_to_actor_input(criteria, limit=25)
    assert payload["locations"] == ["Spring"]
    assert payload["listingType"] == "sale"
    # Vendor-side bounds are a fetch-volume cap, not a filter: they widen
    # past the criteria to the range core/scoring.py can still rank
    # (see test_ceiling_bounds_widen_to_scoring_tail and
    # test_target_minimums_step_down_to_scoring_tail below).
    assert payload["minBeds"] == 2
    assert payload["minBaths"] == 1
    assert payload["maxPrice"] == 312_500
    assert payload["maxPricePerSqft"] == 150
    assert payload["propertyTypes"] == ["multi-family"]
    assert payload["includeDetails"] is True
    assert payload["includeAvm"] is True
    assert payload["maxItems"] == 25


def test_criteria_omit_unset_filters():
    payload = criteria_to_actor_input(Criteria(area="Spring"), limit=10)
    assert "minBeds" not in payload
    assert "maxPrice" not in payload


def test_ceiling_bounds_widen_to_scoring_tail():
    """maxPrice/maxPricePerSqft widen 25% — the point where ceiling_score
    has decayed to ~0.29 (see CEILING_WIDEN_FACTOR). Before the fix these
    passed through unwidened: maxPrice=200_000, maxPricePerSqft=120."""
    payload = criteria_to_actor_input(
        Criteria(area="Spring", max_price=200_000, max_price_per_sqft=120),
        limit=10,
    )
    assert payload["maxPrice"] == 250_000
    assert payload["maxPricePerSqft"] == 150


def test_target_minimums_step_down_to_scoring_tail():
    """minBeds/minBaths drop by one unit — the point where target_score
    returns ~0.40 (see TARGET_MIN_STEPDOWN). Before the fix these passed
    through unwidened: minBeds=3, minBaths=2."""
    payload = criteria_to_actor_input(Criteria(area="Spring", beds=3, baths=2), limit=10)
    assert payload["minBeds"] == 2
    assert payload["minBaths"] == 1


def test_target_minimum_floors_at_one():
    """A one-bed/one-bath target must not step down to 0. Before the fix
    this criterion was untouched so it happened to already read minBeds=1
    — this test's point is that it stays 1, not that it becomes 0."""
    payload = criteria_to_actor_input(Criteria(area="Spring", beds=1, baths=1), limit=10)
    assert payload["minBeds"] == 1
    assert payload["minBaths"] == 1


def test_fetch_for_sale_returns_raw_rows():
    rows = json.loads((FIXTURES / "for_sale_spring.json").read_text())
    http = StubHttp(rows)
    source = ApifyMemo23Source(token="tok", http=http)
    result = source.fetch_for_sale(Criteria(area="Spring", beds=3), limit=25)
    assert len(result) == 3
    assert result[0]["address"] == "5519 Lynngate Dr"


def test_fetch_for_sale_sends_the_token_and_actor_path():
    http = StubHttp([])
    source = ApifyMemo23Source(token="tok", http=http)
    source.fetch_for_sale(Criteria(area="Spring"), limit=5)
    call = http.calls[0]
    assert "memo23~har-scraper" in call["url"]
    assert call["params"]["token"] == "tok"


def test_fetch_for_sale_honours_a_custom_actor():
    http = StubHttp([])
    source = ApifyMemo23Source(token="tok", actor="blackfalcondata/har-scraper", http=http)
    source.fetch_for_sale(Criteria(area="Spring"), limit=5)
    call = http.calls[0]
    assert "blackfalcondata~har-scraper" in call["url"]
    assert "memo23" not in call["url"]


def test_fetch_sold_requests_sold_listing_type():
    http = StubHttp([])
    source = ApifyMemo23Source(token="tok", http=http)
    source.fetch_sold(area="Spring", agent_depth=25, limit=200)
    assert http.calls[0]["json"]["listingType"] == "sold"
    assert http.calls[0]["json"]["maxSoldAgents"] == 25
