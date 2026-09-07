import json
from datetime import date, timedelta
from pathlib import Path

from har_search.core.models import Criteria
from har_search.pipeline import SOLD_REFRESH_DAYS, run_search
from har_search.store.db import Database

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 9, 4)


class FixtureSource:
    name = "fixture"

    def __init__(self):
        self.for_sale = json.loads((FIXTURES / "for_sale_spring.json").read_text())
        self.sold = json.loads((FIXTURES / "sold_spring.json").read_text())

    def fetch_for_sale(self, criteria, limit):
        return self.for_sale

    def fetch_sold(self, area, agent_depth=25, limit=200):
        return self.sold


def make_db(tmp_path) -> Database:
    db = Database(tmp_path / "pipeline.db")
    db.init_schema()
    return db


def test_run_search_returns_scored_listings(tmp_path):
    result = run_search(
        source=FixtureSource(),
        db=make_db(tmp_path),
        criteria=Criteria(area="Spring", beds=3, max_price=250_000),
        saved_search="spring",
        limit=25,
        today=TODAY,
    )
    assert len(result.scored) == 2
    assert result.scored[0].score > 0.5


def test_run_search_records_exclusions_with_reasons(tmp_path):
    """The $1,325 duplex must be excluded and counted, never silently dropped."""
    result = run_search(
        source=FixtureSource(),
        db=make_db(tmp_path),
        criteria=Criteria(area="Spring", max_price=250_000, must=["area"]),
        saved_search="spring",
        limit=25,
        today=TODAY,
    )
    assert result.exclusions["price_below_floor"] == 1


def test_run_search_persists_a_snapshot_that_can_be_read_back(tmp_path):
    db = make_db(tmp_path)
    result = run_search(
        source=FixtureSource(),
        db=db,
        criteria=Criteria(area="Spring", beds=3, max_price=250_000),
        saved_search="spring",
        limit=25,
        today=TODAY,
    )
    rows = db.get_scored_rows(result.snapshot_id)
    assert len(rows) == 2
    assert rows[0]["valuation"] is not None


def test_sold_rows_land_in_permanent_history_and_leases_are_dropped(tmp_path):
    db = make_db(tmp_path)
    run_search(
        source=FixtureSource(),
        db=db,
        criteria=Criteria(area="Spring", beds=3, max_price=250_000),
        saved_search="spring",
        limit=25,
        today=TODAY,
    )
    sales = db.sales_near(30.10, -95.38, miles=5.0, since=date(2026, 1, 1))
    assert {s.mls_number for s in sales} == {"S1", "S3"}


def test_every_result_carries_a_valuation_even_when_insufficient(tmp_path):
    result = run_search(
        source=FixtureSource(),
        db=make_db(tmp_path),
        criteria=Criteria(area="Spring", beds=3, max_price=250_000),
        saved_search="spring",
        limit=25,
        today=TODAY,
    )
    for scored in result.scored:
        valuation = result.valuations[scored.listing.listing_id]
        assert valuation.confidence in {"high", "medium", "low", "insufficient"}


def test_sold_history_is_fetched_as_wide_as_the_widest_comp_tier(tmp_path):
    """The pipeline pre-filters sold history by radius before `select_comps`
    ever runs, so a tier reaching further than that filter can never fire.

    Adding the four-mile tier to `comps.TIERS` changed nothing in a real run
    for exactly this reason: the candidate pool had already been cut at two
    miles one layer up. Two radius constants in two modules will drift again,
    so the pipeline derives its own from the tier list.
    """
    from har_search.core.comps import TIERS
    from har_search.pipeline import COMP_RADIUS_MILES

    widest_sold_tier = max(
        tier.max_miles for tier in TIERS if tier.basis == "sold" and tier.max_miles
    )
    assert COMP_RADIUS_MILES >= widest_sold_tier


def test_a_run_records_the_criteria_that_produced_it(tmp_path):
    """The saved_searches table has existed since the first schema and
    nothing ever wrote to it, so a run was recoverable only as a hash.

    Criteria are what the dashboard header has to show — "Katy #f8023fe1"
    does not tell a reader what was asked for — and the hash is derived from
    them, so they cannot be reconstructed from it.
    """
    db = make_db(tmp_path)
    criteria = Criteria(area="Spring", beds=3, baths=2, max_price=250_000)
    result = run_search(
        source=FixtureSource(), db=db, criteria=criteria, limit=25, today=TODAY
    )

    stored = db.get_saved_search(result.saved_search)

    assert stored["area"] == "Spring"
    assert stored["beds"] == 3
    assert stored["max_price"] == 250_000


def test_rerunning_a_search_does_not_duplicate_its_saved_record(tmp_path):
    db = make_db(tmp_path)
    criteria = Criteria(area="Spring", beds=3)
    for _ in range(2):
        run_search(source=FixtureSource(), db=db, criteria=criteria, today=TODAY)

    assert len(db.list_saved_searches()) == 1


def test_supplied_center_replaces_the_centroid_derived_from_results(tmp_path):
    """The derived centroid is circular: it is the mean of whatever the fetch
    returned, so a fetch that lands in the wrong part of the metro cannot be
    corrected by it. A geocoded center is the fixed point the request named.

    Centered 40 miles from the Spring fixtures with a 1-mile radius, every
    listing must fail the `area` must and be counted as such.
    """
    result = run_search(
        source=FixtureSource(),
        db=make_db(tmp_path),
        criteria=Criteria(
            area="Houston",
            center_address="5255 Beaverbrook Dr",
            radius_miles=1.0,
            max_price=250_000,
        ),
        saved_search="beaverbrook",
        limit=25,
        today=TODAY,
        center=(29.83, -95.66),
    )
    assert result.scored == []
    assert result.dropped_by_must > 0


def test_a_radius_covering_both_listings_keeps_both(tmp_path):
    """The other half of the pair: without it the test above would pass on any
    bug that merely empties the result set. The two Spring fixtures sit 8.5
    miles apart, so the radius has to reach past that to hold both."""
    result = run_search(
        source=FixtureSource(),
        db=make_db(tmp_path),
        criteria=Criteria(
            area="Spring",
            center_address="a Spring address",
            radius_miles=10.0,
            max_price=250_000,
        ),
        saved_search="spring-centered",
        limit=25,
        today=TODAY,
        center=(30.036, -95.342),
    )
    assert len(result.scored) == 2
    assert result.dropped_by_must == 0


def test_the_radius_overrides_a_city_name_match(tmp_path):
    """Both fixtures are in Spring and the search says Spring, so the name
    match alone would score each a perfect 1.0 on location. The one 8.5 miles
    from the center still has to go: the address and radius are the more
    specific request, and a city name cannot widen them back out."""
    result = run_search(
        source=FixtureSource(),
        db=make_db(tmp_path),
        criteria=Criteria(
            area="Spring",
            center_address="a Spring address",
            radius_miles=2.0,
            max_price=250_000,
        ),
        saved_search="spring-tight",
        limit=25,
        today=TODAY,
        center=(30.036, -95.342),
    )
    assert [s.listing.address for s in result.scored] == ["5519 Lynngate Dr"]
    assert result.dropped_by_must == 1


class CountingSource(FixtureSource):
    """Counts vendor round trips. Each one is a separate actor run."""

    def __init__(self):
        super().__init__()
        self.sold_calls = []
        self.for_sale_calls = 0

    def fetch_sold(self, area, agent_depth=25, limit=200):
        self.sold_calls.append(area)
        return self.sold

    def fetch_for_sale(self, criteria, limit):
        self.for_sale_calls += 1
        return self.for_sale


def run(source, db, area="Spring", today=TODAY, **kwargs):
    return run_search(
        source=source,
        db=db,
        criteria=Criteria(area=area, max_price=250_000, **kwargs),
        limit=25,
        today=today,
    )


def test_sold_history_is_not_refetched_for_the_same_area_the_same_day(tmp_path):
    """Two actor runs per search is the whole latency budget, and sold history
    barely moves day to day. Re-running a search an hour later must not pay
    for the sold leg twice."""
    source, db = CountingSource(), make_db(tmp_path)
    run(source, db)
    run(source, db)
    assert source.sold_calls == ["Spring"]
    assert source.for_sale_calls == 2


def test_stale_sold_history_is_refetched(tmp_path):
    """The cache is a freshness window, not a one-shot. Past it the sold leg
    runs again, or estimates quietly drift onto months-old sales."""
    source, db = CountingSource(), make_db(tmp_path)
    run(source, db, today=TODAY)
    run(source, db, today=TODAY + timedelta(days=SOLD_REFRESH_DAYS + 1))
    assert source.sold_calls == ["Spring", "Spring"]


def test_freshness_is_tracked_per_area(tmp_path):
    """A fresh Spring fetch says nothing about Katy's comps."""
    source, db = CountingSource(), make_db(tmp_path)
    run(source, db, area="Spring")
    run(source, db, area="Katy")
    assert source.sold_calls == ["Spring", "Katy"]
