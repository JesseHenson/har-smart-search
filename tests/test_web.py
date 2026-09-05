import re
from datetime import date

from starlette.testclient import TestClient

from har_search.core.models import Listing, ParamScore, ScoredListing, Valuation
from har_search.store.db import Database
from har_search.web.app import create_app, kpi_chip


def seed(tmp_path) -> tuple[object, int]:
    # Returns the db path (not the open Database) so client_for can hand
    # create_app a factory that opens a fresh connection per call, mirroring
    # ensure_dashboard_running's production factory. Starlette's TestClient
    # runs the app on its own background thread, and sqlite3 connections are
    # thread-affine, so a factory that closed over one shared Database built
    # here on the main thread would raise
    # "SQLite objects created in a thread can only be used in that same
    # thread" the moment a route handler touched it.
    path = tmp_path / "web.db"
    db = Database(path)
    db.init_schema()
    snapshot_id = db.create_snapshot(
        "spring", "fixture", 1, 1, {"lease": 1}, sold_exclusions={"lease": 6}
    )
    listing = Listing(
        listing_id="L1",
        address="5519 Lynngate Dr",
        subdivision="Greengate Place Sec 06",
        price=215_000,
        price_per_sqft=142.38,
        beds=3,
        baths_full=2,
        sqft=1510,
        lat=30.036,
        lon=-95.342,
    )
    # A mix of known and unknown criteria, matching the shape get_scored_rows
    # actually returns (dicts with name/score/weight/known/detail), so the
    # per-criterion breakdown loop in listing.html exercises both branches
    # under test instead of never running (params=[] would skip the loop
    # entirely and leave that render path untested).
    params = [
        ParamScore(name="beds", score=1.0, weight=0.3, known=True, detail="3 beds matches request"),
        ParamScore(name="garage", score=0.0, weight=0.2, known=False, detail="garage data not available"),
    ]
    db.insert_scored(
        snapshot_id,
        [ScoredListing(listing, 0.91, 0.85, params, "Matches every requested criterion.")],
        {
            "L1": Valuation(
                comp_estimate=231_000,
                comp_count=6,
                comp_basis="sold",
                confidence="medium",
                delta_pct=-0.069,
                spread_flag="single_source",
            )
        },
    )
    return path, snapshot_id


def client_for(tmp_path):
    path, snapshot_id = seed(tmp_path)
    return TestClient(create_app(lambda: Database(path))), snapshot_id


def test_kpi_chip_labels_below_and_above_comps():
    label, tone = kpi_chip(-0.069)
    assert "below" in label.lower()
    assert tone == "good"

    label, tone = kpi_chip(0.12)
    assert "above" in label.lower()
    assert tone == "bad"

    label, tone = kpi_chip(None)
    assert tone == "neutral"


def test_run_page_lists_the_listing_with_score_and_kpi(tmp_path):
    client, snapshot_id = client_for(tmp_path)
    response = client.get(f"/run/{snapshot_id}")
    assert response.status_code == 200
    assert "5519 Lynngate Dr" in response.text
    assert "$215,000" in response.text
    assert "231,000" in response.text


def test_run_page_shows_evidence_count_next_to_every_estimate(tmp_path):
    client, snapshot_id = client_for(tmp_path)
    response = client.get(f"/run/{snapshot_id}")
    assert "6 comps" in response.text


def test_run_page_reports_excluded_rows(tmp_path):
    client, snapshot_id = client_for(tmp_path)
    response = client.get(f"/run/{snapshot_id}")
    assert "lease" in response.text.lower()


def test_listing_page_renders_the_explanation(tmp_path):
    client, snapshot_id = client_for(tmp_path)
    response = client.get(f"/run/{snapshot_id}/listing/L1")
    assert response.status_code == 200
    assert "Matches every requested criterion." in response.text


def test_missing_listing_returns_404(tmp_path):
    client, snapshot_id = client_for(tmp_path)
    assert client.get(f"/run/{snapshot_id}/listing/NOPE").status_code == 404


def test_index_lists_saved_searches(tmp_path):
    client, _ = client_for(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "spring" in response.text


def test_index_reports_the_latest_runs_item_count_not_the_historical_max(tmp_path):
    """A per-column MAX() aggregate would report the largest item_count ever
    seen for a saved search, not the current one. Seed a second, later run
    with a SMALLER item_count and confirm the index shows that smaller,
    current number rather than the stale larger one.

    The assertions read the rendered table cells rather than the whole page.
    Substring-matching the page body made this test time-dependent: `run_at`
    is a `datetime.now()` timestamp rendered into its own cell, so any run
    during minute or second 40 put "40" on the page and failed the test for a
    reason it does not exist to catch.
    """
    path, _ = seed(tmp_path)
    db = Database(path)
    db.create_snapshot("spring", "fixture", 40, 0, {})
    db.create_snapshot("spring", "fixture", 12, 0, {})
    client = TestClient(create_app(lambda: Database(path)))
    response = client.get("/")
    assert response.status_code == 200
    cells = [c.strip() for c in re.findall(r"<td>(.*?)</td>", response.text, re.S)]
    assert "12" in cells
    assert "40" not in cells


def test_run_page_shows_criteria_counts_next_to_coverage(tmp_path):
    client, snapshot_id = client_for(tmp_path)
    response = client.get(f"/run/{snapshot_id}")
    assert response.status_code == 200
    assert "1 of 2 criteria" in response.text


def test_listing_page_shows_known_and_unknown_criteria(tmp_path):
    client, snapshot_id = client_for(tmp_path)
    response = client.get(f"/run/{snapshot_id}/listing/L1")
    assert response.status_code == 200
    text = response.text
    assert "beds" in text.lower()
    assert "garage" in text.lower()
    # The unknown criterion must render as "unknown", not as a 0% score bar.
    assert "unknown" in text.lower()
    garage_row_start = text.lower().index("garage")
    garage_row = text[garage_row_start : garage_row_start + 200]
    assert "unknown" in garage_row.lower()


# --- Data-quality footer (spec 4.2) --------------------------------------


def test_run_page_reports_sold_exclusions_separately_from_for_sale_ones(tmp_path):
    """Six leases inside a sold query used to vanish without trace.

    `pipeline` dropped sold rows on a bare `if sale is not None`, with no
    counter and no reason, while the footer reported only the for-sale count —
    a confidently smaller number than the truth.
    """
    client, snapshot_id = client_for(tmp_path)
    text = client.get(f"/run/{snapshot_id}").text
    assert "6 lease listings" in text
    assert "Comparable sales" in text


def test_run_page_footer_is_prose_not_a_json_blob(tmp_path):
    """The footer of the demo's main screen read `{"lease": 1}`."""
    client, snapshot_id = client_for(tmp_path)
    text = client.get(f"/run/{snapshot_id}").text
    assert '{"lease"' not in text
    assert "1 lease listing" in text


def test_run_page_says_so_when_no_sold_rows_were_excluded(tmp_path):
    path = tmp_path / "clean.db"
    db = Database(path)
    db.init_schema()
    snapshot_id = db.create_snapshot("spring", "fixture", 1, 0, {}, sold_exclusions={})
    client = TestClient(create_app(lambda: Database(path)))
    text = client.get(f"/run/{snapshot_id}").text
    assert "every sold row in this run was usable" in text.lower()


# --- Raw machine tokens must not reach the screen (spec 9) ---------------


def test_listing_page_renders_no_raw_literal_tokens(tmp_path):
    """The page read "Sources single_source." and "6 comps, sold, medium confidence"."""
    client, snapshot_id = client_for(tmp_path)
    text = client.get(f"/run/{snapshot_id}/listing/L1")
    body = text.text
    assert "single_source" not in body
    assert "6 closed sales, medium confidence" in body
    assert "Only one source of value" in body


def test_asking_basis_valuation_is_qualified_as_budget_bounded(tmp_path):
    """Tier 4's pool is this run's own listings, bounded by the user's budget.

    Every asking-basis estimate is therefore computed against a pool truncated
    near the budget, biasing estimates downward and making pricier candidates
    look systematically overpriced. The screen must say so.
    """
    path = tmp_path / "asking.db"
    db = Database(path)
    db.init_schema()
    snapshot_id = db.create_snapshot("spring", "fixture", 1, 0, {})
    listing = Listing(listing_id="L1", address="1 Main St", price=215_000)
    db.insert_scored(
        snapshot_id,
        [ScoredListing(listing, 0.9, 1.0, [], "why")],
        {
            "L1": Valuation(
                comp_estimate=200_000,
                comp_count=5,
                comp_basis="asking",
                confidence="medium",
                delta_pct=0.075,
            )
        },
    )
    client = TestClient(create_app(lambda: Database(path)))
    body = client.get(f"/run/{snapshot_id}/listing/L1").text
    assert "asking prices, not closed sales" in body
    assert "budget range you searched" in body
    assert "not the open market" in body


def test_diff_page_renders_change_types_as_english(tmp_path):
    """The screen printed the raw classification token `PRICE_CUT`."""
    path = tmp_path / "diff.db"
    db = Database(path)
    db.init_schema()
    first = db.create_snapshot("spring", "fixture", 1, 0, {})
    second = db.create_snapshot("spring", "fixture", 1, 0, {})
    for snapshot_id, price in ((first, 250_000), (second, 230_000)):
        db.insert_scored(
            snapshot_id,
            [
                ScoredListing(
                    Listing(listing_id="L1", address="1 Main St", price=price),
                    0.9,
                    1.0,
                    [],
                    "why",
                )
            ],
            {},
        )
    client = TestClient(create_app(lambda: Database(path)))
    body = client.get(f"/run/{second}/diff").text
    assert "PRICE_CUT" not in body
    assert "Price cut" in body
