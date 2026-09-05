from datetime import date

from starlette.testclient import TestClient

from har_search.core.models import Listing, ScoredListing, Valuation
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
    snapshot_id = db.create_snapshot("spring", "fixture", 1, 1, {"lease": 1})
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
    db.insert_scored(
        snapshot_id,
        [ScoredListing(listing, 0.91, 0.85, [], "Matches every requested criterion.")],
        {"L1": Valuation(comp_estimate=231_000, comp_count=6, confidence="medium", delta_pct=-0.069)},
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
