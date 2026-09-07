import json
from datetime import date
from pathlib import Path

from har_search.core.models import Criteria
from har_search.pipeline import run_search
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
