import pytest

from har_search.sources.geocode import Place

from har_search.core.models import (
    Criteria,
    Listing,
    ListingChange,
    MoneyRange,
    ParamScore,
    ScoredListing,
    Valuation,
)
from har_search.pipeline import SearchResult
from har_search.server.__main__ import (
    build_explain_response,
    build_search_response,
    build_whats_new_response,
    resolve_center,
)


def make_result() -> SearchResult:
    listing = Listing(
        listing_id="L1",
        address="5519 Lynngate Dr",
        subdivision="Greengate Place Sec 06",
        price=215_000,
        price_per_sqft=142.38,
        beds=3,
        baths_full=2,
        sqft=1510,
        days_on_market=1,
    )
    scored = ScoredListing(
        listing=listing,
        score=0.91,
        coverage=0.85,
        params=[ParamScore("beds", 1.0, 2.0, True, "3 bd vs 3 bd wanted")],
        why="Matches every requested criterion.",
    )
    valuation = Valuation(
        comp_estimate=231_000,
        comp_count=6,
        comp_basis="sold",
        confidence="medium",
        delta_pct=-0.069,
        appraisal_district=MoneyRange(205_000, 205_999),
        spread_flag="clustered",
    )
    return SearchResult(
        snapshot_id=7,
        saved_search="Spring #a1b2c3d4",
        scored=[scored],
        valuations={"L1": valuation},
        exclusions={"lease": 2},
        sold_exclusions={"lease": 6, "missing_sold_price": 1},
        dropped_by_must=1,
    )


def test_search_response_includes_score_kpi_and_coverage():
    payload = build_search_response(make_result(), limit=10, dashboard_url="http://x/run/7")
    row = payload["results"][0]
    assert row["address"] == "5519 Lynngate Dr"
    assert row["score"] == 0.91
    assert row["coverage"] == 0.85
    assert row["estimated_value"] == 231_000
    assert row["comp_count"] == 6
    assert row["delta_pct"] == -0.069


def test_search_response_surfaces_data_quality_counts():
    payload = build_search_response(make_result(), limit=10, dashboard_url="http://x/run/7")
    assert payload["excluded"]["lease"] == 2
    assert payload["dropped_by_must"] == 1


def test_search_response_carries_the_dashboard_url_and_snapshot():
    payload = build_search_response(make_result(), limit=10, dashboard_url="http://x/run/7")
    assert payload["dashboard_url"] == "http://x/run/7"
    assert payload["snapshot_id"] == 7


def test_search_response_respects_limit():
    result = make_result()
    result.scored = result.scored * 5
    payload = build_search_response(result, limit=2, dashboard_url="http://x/run/7")
    assert len(payload["results"]) == 2


def test_explain_response_returns_breakdown_and_comps():
    row = {
        "listing": Listing(listing_id="L1", address="5519 Lynngate Dr", price=215_000),
        "score": 0.91,
        "coverage": 0.85,
        "why": "Matches every requested criterion.",
        "params": [
            {"name": "beds", "score": 1.0, "weight": 2.0, "known": True, "detail": "3 bd"}
        ],
        "valuation": {"comp_estimate": 231_000, "comp_count": 6, "confidence": "medium"},
    }
    comps = [{"id": "M1", "price": 360_000, "distance_miles": 0.4}]
    payload = build_explain_response(row, comps)
    assert payload["why"]
    assert payload["params"][0]["name"] == "beds"
    assert payload["valuation"]["comp_count"] == 6
    assert payload["comps"][0]["id"] == "M1"


def test_whats_new_groups_changes_by_type():
    changes = [
        ListingChange("A", "NEW", None, 200_000, "1 Main"),
        ListingChange("B", "PRICE_CUT", 300_000, 280_000, "2 Main"),
        ListingChange("C", "UNCHANGED", 400_000, 400_000, "3 Main"),
        ListingChange("D", "GONE", 500_000, None, "4 Main"),
    ]
    payload = build_whats_new_response(changes)
    assert len(payload["new"]) == 1
    assert len(payload["price_cut"]) == 1
    assert len(payload["gone"]) == 1
    assert payload["unchanged_count"] == 1


# --- Prose alongside the machine-readable values -------------------------


def test_explain_qualifies_an_asking_basis_comparison():
    """Spec 6.1 tier 4 fires most often, and its pool is budget-bounded.

    The tier-4 asking-comp pool is the run's own scored listings, which
    survived a vendor bound of budget x 1.25, a result limit and the `must`
    gate. `comp_basis` stays machine-readable; what the user is told changes.
    """
    row = {
        "listing": Listing(listing_id="L1", address="1 Main St", price=215_000),
        "score": 0.9,
        "coverage": 1.0,
        "why": "why",
        "params": [],
        "valuation": {
            "comp_count": 5,
            "comp_basis": "asking",
            "confidence": "medium",
            "spread_flag": "single_source",
        },
    }
    payload = build_explain_response(row, [])
    assert payload["valuation"]["comp_basis"] == "asking"
    note = payload["basis_note"]
    assert "asking prices, not closed sales" in note
    assert "budget range you searched" in note
    assert "not the open market" in note


def test_explain_of_a_sold_basis_makes_no_budget_caveat():
    row = {
        "listing": Listing(listing_id="L1", address="1 Main St", price=215_000),
        "score": 0.9,
        "coverage": 1.0,
        "why": "why",
        "params": [],
        "valuation": {
            "comp_count": 6,
            "comp_basis": "sold",
            "confidence": "medium",
            "spread_flag": "clustered",
        },
    }
    payload = build_explain_response(row, [])
    assert "budget range" not in payload["basis_note"]
    assert payload["evidence"] == "6 closed sales, medium confidence"


def test_search_response_keeps_tokens_and_adds_prose():
    payload = build_search_response(make_result(), limit=10, dashboard_url="http://x/run/7")
    row = payload["results"][0]
    assert row["comp_basis"] == "sold"  # still machine-readable
    assert row["evidence"] == "6 closed sales, medium confidence"
    assert "closed sales" in row["basis_note"]


def test_search_response_reports_sold_exclusions_distinctly():
    payload = build_search_response(make_result(), limit=10, dashboard_url="http://x/run/7")
    assert payload["excluded"] == {"lease": 2}
    assert payload["sold_excluded"] == {"lease": 6, "missing_sold_price": 1}
    assert "6 lease listings" in payload["sold_excluded_summary"]
    assert "2 lease listings" in payload["excluded_summary"]


def test_search_response_returns_the_saved_search_key_for_whats_new():
    """Keys carry a hash the model cannot invent, so `search` has to hand it back."""
    payload = build_search_response(make_result(), limit=10, dashboard_url="http://x/run/7")
    assert payload["saved_search"] == "Spring #a1b2c3d4"


class StubGeocoder:
    """Returns a fixed place, or nothing for an address it cannot place."""

    def __init__(self, point=None, city="Houston"):
        self.point = point
        self.city = city
        self.asked = []

    def locate_place(self, address):
        self.asked.append(address)
        if self.point is None:
            return None
        return Place(self.point[0], self.point[1], self.city)


def test_no_address_means_no_center_and_no_geocoder_call():
    """Area-only searches must not pay for a lookup they do not use."""
    geocoder = StubGeocoder(point=(29.83, -95.66))
    criteria = Criteria(area="Spring", beds=3)
    assert resolve_center(criteria, geocoder) is None
    assert geocoder.asked == []


def test_an_address_is_geocoded_into_a_center():
    geocoder = StubGeocoder(point=(29.8329, -95.6597))
    criteria = Criteria(area="Houston", center_address="5255 Beaverbrook Dr")
    assert resolve_center(criteria, geocoder) == (29.8329, -95.6597)
    assert geocoder.asked == ["5255 Beaverbrook Dr"]


def test_an_unplaceable_address_is_an_error_not_a_silent_area_search():
    """Falling through to the derived centroid would run a search the user did
    not ask for and report it as if they had — the radius would quietly stop
    applying while the response still looked like a radius search."""
    geocoder = StubGeocoder(point=None)
    criteria = Criteria(area="Houston", center_address="nowhere at all", radius_miles=2.0)
    with pytest.raises(ValueError, match="nowhere at all"):
        resolve_center(criteria, geocoder)


def test_a_radius_without_an_address_is_an_error():
    """A radius has no meaning without the point it is measured from."""
    criteria = Criteria(area="Houston", radius_miles=2.0)
    with pytest.raises(ValueError, match="radius_miles"):
        resolve_center(criteria, StubGeocoder())


def result_with(scored, areas_searched, area_of=None):
    base = make_result()
    return SearchResult(
        snapshot_id=base.snapshot_id,
        saved_search=base.saved_search,
        scored=scored,
        valuations=base.valuations,
        exclusions={},
        sold_exclusions={},
        dropped_by_must=0,
        areas_searched=areas_searched,
        area_of=area_of or {},
    )


def test_a_search_that_never_widened_says_nothing_about_coverage():
    """Brief means brief. The common case is one area answering, and a line
    reporting that is noise in every response that does not need it."""
    base = make_result()
    payload = build_search_response(
        result_with(base.scored, ["77084"], {"L1": "77084"}), 25, dashboard_url="x"
    )
    assert "coverage" not in payload


def test_widening_is_reported_in_one_line():
    base = make_result()
    payload = build_search_response(
        result_with(base.scored, ["77084", "77041", "77095"], {"L1": "77041"}),
        25,
        dashboard_url="x",
    )
    assert payload["coverage"] == (
        "77084 came up short, so the search widened to 77041, 77095."
    )


def test_a_match_from_a_widened_area_is_labelled_as_one():
    """A house found two rungs out is not the same answer as one in the area
    asked for, and a reader scanning a list cannot tell them apart otherwise."""
    base = make_result()
    payload = build_search_response(
        result_with(base.scored, ["77084", "77041"], {"L1": "77041"}), 25, dashboard_url="x"
    )
    assert payload["results"][0]["found_in"] == "77041"


def test_no_matches_says_how_far_it_looked():
    payload = build_search_response(
        result_with([], ["77084", "77041", "77095", "Houston"]), 25, dashboard_url="x"
    )
    assert payload["results"] == []
    assert payload["coverage"] == (
        "No matches. Searched 77084, then 77041, 77095, then Houston."
    )
