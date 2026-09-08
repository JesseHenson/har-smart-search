from datetime import date, datetime, timedelta

from har_search.core.models import (
    GarageInfo,
    Listing,
    PropertyType,
    Sale,
    ScoredListing,
    Valuation,
)
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


def test_latest_snapshots_reports_the_newest_runs_item_count(tmp_path):
    """id/run_at rise together with insertion order, but item_count does not:
    a later run can legitimately return fewer results than an earlier one.

    Seed a later snapshot with a SMALLER item_count than the earlier one and
    assert latest_snapshots() reports the later run's count.

    Against a naive `SELECT saved_search, MAX(id), MAX(run_at),
    MAX(item_count) ... GROUP BY saved_search` query (the old, wrong query
    this replaces) this assertion fails: that query would independently
    aggregate MAX(item_count) across both rows and report 40, the
    historical max, not 12, the current count. It only passes against the
    corrected `WHERE id IN (SELECT MAX(id) FROM snapshots GROUP BY
    saved_search)` query, which selects the whole row belonging to the
    newest id.
    """
    db = make_db(tmp_path)
    db.create_snapshot("spring", "apify_memo23", 40, 0, {})
    later_id = db.create_snapshot("spring", "apify_memo23", 12, 0, {})

    rows = {row["saved_search"]: row for row in db.latest_snapshots()}

    assert rows["spring"]["id"] == later_id
    assert rows["spring"]["item_count"] == 12


def test_get_snapshot_returns_row_or_none(tmp_path):
    db = make_db(tmp_path)
    snapshot_id = db.create_snapshot("spring", "apify_memo23", 1, 0, {})
    assert db.get_snapshot(snapshot_id)["saved_search"] == "spring"
    assert db.get_snapshot(snapshot_id + 999) is None


def test_previous_snapshot_id_finds_the_immediately_prior_run(tmp_path):
    db = make_db(tmp_path)
    first = db.create_snapshot("spring", "apify_memo23", 1, 0, {})
    second = db.create_snapshot("spring", "apify_memo23", 2, 0, {})
    assert db.previous_snapshot_id("spring", second) == first
    assert db.previous_snapshot_id("spring", first) is None


def test_recent_snapshots_returns_newest_first(tmp_path):
    db = make_db(tmp_path)
    first = db.create_snapshot("s", "apify_memo23", 1, 0, {})
    second = db.create_snapshot("s", "apify_memo23", 2, 0, {})
    snapshots = db.recent_snapshots("s", limit=2)
    assert [s["id"] for s in snapshots] == [second, first]


def test_upsert_sales_preserves_first_seen_on_reupsert(tmp_path, monkeypatch):
    """first_seen must record original discovery, not the latest scan.

    Task 11's pipeline calls upsert_sales on every run for every sold row it
    fetches, so a re-upsert must not reset first_seen to "now". We control
    the clock so the two upserts get distinguishable timestamps: if the fix
    were reverted (a blind INSERT OR REPLACE), SQLite implements that as a
    delete-and-insert on the primary-key conflict, and first_seen would come
    back equal to the *second* call's timestamp instead of the first's.
    """
    import har_search.store.db as db_module

    fake_now_values = [datetime(2026, 1, 1, 8, 0, 0), datetime(2026, 6, 1, 9, 30, 0)]

    class FakeDatetime:
        _values = iter(fake_now_values)

        @classmethod
        def now(cls):
            return next(cls._values)

    monkeypatch.setattr(db_module, "datetime", FakeDatetime)

    db = make_db(tmp_path)
    sale = Sale(
        mls_number="M2",
        sold_price=300_000,
        sold_date=TODAY,
        subdivision="Harmony",
        lat=30.10,
        lon=-95.38,
        sqft=2000,
        property_type=PropertyType.SINGLE_FAMILY,
    )
    db.upsert_sales([sale])

    updated_sale = Sale(
        mls_number="M2",
        sold_price=305_000,
        sold_date=TODAY,
        subdivision="Harmony",
        lat=30.10,
        lon=-95.38,
        sqft=2000,
        property_type=PropertyType.SINGLE_FAMILY,
    )
    db.upsert_sales([updated_sale])

    row = db._conn.execute(
        "SELECT first_seen, sold_price FROM sold_history WHERE mls_number = ?",
        ("M2",),
    ).fetchone()
    assert row["sold_price"] == 305_000
    assert row["first_seen"] == fake_now_values[0].isoformat(timespec="seconds")


def test_garage_info_round_trips_attached_and_tags(tmp_path):
    """attached and tags must survive storage, not degrade to unknown/empty.

    If the fix were reverted (only garage_spaces persisted), the read-back
    GarageInfo would have attached=None and tags=(), which would not equal
    the original GarageInfo(spaces=3, attached=True, tags=(...)).
    """
    db = make_db(tmp_path)
    snapshot_id = db.create_snapshot("s", "apify_memo23", 1, 0, {})
    scored = make_scored()
    scored.listing.garage = GarageInfo(spaces=3, attached=True, tags=("oversized", "tandem"))
    db.insert_scored(snapshot_id, [scored], {})

    listings = db.get_snapshot_listings(snapshot_id)
    assert listings[0].garage == GarageInfo(spaces=3, attached=True, tags=("oversized", "tandem"))
    assert isinstance(listings[0].garage.tags, tuple)


def test_garage_attached_none_round_trips_as_none_not_false(tmp_path):
    """attached is tri-state: unknown (None) must not collapse to False.

    If None were coerced to False on the way in (or reconstructed as False
    on the way out), this equality would fail even though spaces/tags match.
    """
    db = make_db(tmp_path)
    snapshot_id = db.create_snapshot("s", "apify_memo23", 1, 0, {})
    scored = make_scored()
    scored.listing.garage = GarageInfo(spaces=2, attached=None, tags=())
    db.insert_scored(snapshot_id, [scored], {})

    listings = db.get_snapshot_listings(snapshot_id)
    assert listings[0].garage.attached is None
    assert listings[0].garage == GarageInfo(spaces=2, attached=None, tags=())


def make_active(listing_id, lat, lon, **kw):
    base = dict(
        listing_id=listing_id,
        address=f"{listing_id} Somewhere St",
        city="Houston",
        zip="77084",
        lat=lat,
        lon=lon,
        price=250_000,
        beds=3,
        baths_full=2,
        sqft=1600,
        property_type=PropertyType.SINGLE_FAMILY,
    )
    base.update(kw)
    return Listing(**base)


BEAVERBROOK = (29.8536, -95.6393)


def test_actives_come_back_by_distance_not_by_search(tmp_path):
    """The corpus outlives the run that fetched it. A listing put in by one
    search must be available as a comp to every later search that reaches it,
    which is the whole point of pooling them."""
    db = make_db(tmp_path)
    db.upsert_actives(
        [
            make_active("near", 29.8600, -95.6400),
            make_active("far", 29.9500, -95.4000),
        ]
    )
    near = db.actives_near(BEAVERBROOK[0], BEAVERBROOK[1], miles=2.0)
    assert [l.listing_id for l in near] == ["near"]


def test_reupserting_a_listing_updates_it_rather_than_duplicating(tmp_path):
    """Corpus rows are keyed on the listing, not the run. A price cut seen on
    today's refresh must replace yesterday's price, not sit beside it."""
    db = make_db(tmp_path)
    db.upsert_actives([make_active("L1", *BEAVERBROOK, price=250_000)])
    db.upsert_actives([make_active("L1", *BEAVERBROOK, price=239_000)])
    found = db.actives_near(BEAVERBROOK[0], BEAVERBROOK[1], miles=1.0)
    assert len(found) == 1
    assert found[0].price == 239_000


def test_corpus_freshness_is_recorded_per_area(tmp_path):
    db = make_db(tmp_path)
    assert db.corpus_fetched_on("77084") is None
    db.record_corpus_fetch("77084", "2026-09-07")
    assert db.corpus_fetched_on("77084") == "2026-09-07"
    assert db.corpus_fetched_on("77449") is None


def test_existing_snapshot_listings_are_adopted_into_the_corpus(tmp_path):
    """0.6.0 reads a corpus that only a successful fetch could fill, so an
    upgrade with a dry vendor account had a database full of listings and no
    way to reach any of them. Every listing a snapshot ever captured is
    already a listing we fetched; the corpus should start from them."""
    path = tmp_path / "legacy.db"
    db = Database(path)
    db.init_schema()
    snapshot_id = db.create_snapshot(
        saved_search="77084 #abc",
        source="apify_memo23",
        item_count=1,
        excluded_count=0,
        exclusions={},
        sold_exclusions={},
    )
    listing = make_active("legacy-1", 29.8600, -95.6400, zip="77084")
    db.insert_scored(snapshot_id, [ScoredListing(listing, 0.9, 1.0, [], "why")], {})
    db._conn.execute("DELETE FROM active_listings")
    db._conn.execute("DELETE FROM corpus_areas")
    db._conn.commit()

    Database(path).init_schema()

    adopted = Database(path).actives_in_area("77084")
    assert [l.listing_id for l in adopted] == ["legacy-1"]


def test_adoption_does_not_claim_the_area_was_just_refreshed(tmp_path):
    """Backfilled rows are as old as they are. Stamping them with today's date
    would suppress the next real refresh for a full day on data that could be
    months stale."""
    path = tmp_path / "legacy2.db"
    db = Database(path)
    db.init_schema()
    snapshot_id = db.create_snapshot(
        saved_search="77084 #abc", source="apify_memo23", item_count=1,
        excluded_count=0, exclusions={}, sold_exclusions={},
    )
    db.insert_scored(
        snapshot_id,
        [ScoredListing(make_active("legacy-1", 29.86, -95.64, zip="77084"), 0.9, 1.0, [], "w")],
        {},
    )
    db._conn.execute("DELETE FROM active_listings")
    db._conn.execute(
        "UPDATE snapshots SET run_at = ? WHERE id = ?",
        ("2026-03-01T09:00:00", snapshot_id),
    )
    db._conn.commit()

    fresh = Database(path)
    fresh.init_schema()
    assert fresh.corpus_fetched_on("77084") == "2026-03-01"
