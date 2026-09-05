from har_search.core.models import (
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
    assert payload["evidence"] == "6 comparable closed sales, medium confidence"


def test_search_response_keeps_tokens_and_adds_prose():
    payload = build_search_response(make_result(), limit=10, dashboard_url="http://x/run/7")
    row = payload["results"][0]
    assert row["comp_basis"] == "sold"  # still machine-readable
    assert row["evidence"] == "6 comparable closed sales, medium confidence"
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
