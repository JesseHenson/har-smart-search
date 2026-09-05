from datetime import date, timedelta

from har_search.core.models import Listing, PropertyType, Sale, ScoredListing, Valuation
from har_search.store.db import Database

TODAY = date(2026, 9, 4)


def make_db(tmp_path) -> Database:
    db = Database(tmp_path / "test.db")
    db.init_schema()
    return db


def make_scored(listing_id="L1", price=215_000) -> ScoredListing:
    return ScoredListing(
        listing=Listing(
            listing_id=listing_id,
            address="5519 Lynngate Dr",
            subdivision="Greengate Place Sec 06",
            lat=30.036,
            lon=-95.342,
            price=price,
            sqft=1510,
            beds=3,
            property_type=PropertyType.SINGLE_FAMILY,
        ),
        score=0.91,
        coverage=0.85,
        params=[],
        why="Matches every requested criterion.",
    )


def test_snapshot_round_trip(tmp_path):
    db = make_db(tmp_path)
    snapshot_id = db.create_snapshot(
        saved_search="spring-investment",
        source="apify_memo23",
        item_count=1,
        excluded_count=2,
        exclusions={"lease": 1, "price_below_floor": 1},
    )
    db.insert_scored(snapshot_id, [make_scored()], {"L1": Valuation(comp_estimate=231_000)})

    listings = db.get_snapshot_listings(snapshot_id)
    assert len(listings) == 1
    assert listings[0].price == 215_000
    assert listings[0].property_type is PropertyType.SINGLE_FAMILY


def test_scored_rows_carry_score_and_valuation(tmp_path):
    db = make_db(tmp_path)
    snapshot_id = db.create_snapshot("s", "apify_memo23", 1, 0, {})
    db.insert_scored(
        snapshot_id,
        [make_scored()],
        {"L1": Valuation(comp_estimate=231_000, comp_count=6, delta_pct=-0.069)},
    )
    row = db.get_scored_rows(snapshot_id)[0]
    assert row["score"] == 0.91
    assert row["valuation"]["comp_estimate"] == 231_000
    assert row["valuation"]["comp_count"] == 6


def test_sales_accumulate_across_runs_and_deduplicate(tmp_path):
    db = make_db(tmp_path)
    sale = Sale(
        mls_number="M1",
        sold_price=460_000,
        sold_date=TODAY,
        subdivision="Harmony",
        lat=30.10,
        lon=-95.38,
        sqft=3110,
        property_type=PropertyType.SINGLE_FAMILY,
    )
    db.upsert_sales([sale])
    db.upsert_sales([sale])
    found = db.sales_near(30.10, -95.38, miles=2.0, since=TODAY - timedelta(days=180))
    assert len(found) == 1
    assert found[0].sold_price == 460_000


def test_sales_near_filters_by_distance_and_recency(tmp_path):
    db = make_db(tmp_path)
    db.upsert_sales(
        [
            Sale("NEAR", 400_000, TODAY, lat=30.10, lon=-95.38, sqft=2000),
            Sale("FAR", 400_000, TODAY, lat=31.50, lon=-97.00, sqft=2000),
            Sale("STALE", 400_000, TODAY - timedelta(days=400), lat=30.10, lon=-95.38, sqft=2000),
        ]
    )
    found = db.sales_near(30.10, -95.38, miles=2.0, since=TODAY - timedelta(days=180))
    assert {s.mls_number for s in found} == {"NEAR"}


def test_recent_snapshots_returns_newest_first(tmp_path):
    db = make_db(tmp_path)
    first = db.create_snapshot("s", "apify_memo23", 1, 0, {})
    second = db.create_snapshot("s", "apify_memo23", 2, 0, {})
    snapshots = db.recent_snapshots("s", limit=2)
    assert [s["id"] for s in snapshots] == [second, first]
