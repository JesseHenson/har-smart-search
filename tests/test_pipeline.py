import json
from datetime import date, timedelta
from pathlib import Path

from har_search.core.models import Criteria
from har_search.core.models import Listing, PropertyType
from har_search.pipeline import CORPUS_LIMIT, SOLD_REFRESH_DAYS, run_search
from har_search.store.db import Database

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 9, 4)


class FixtureSource:
    name = "fixture"

    def __init__(self):
        self.for_sale = json.loads((FIXTURES / "for_sale_spring.json").read_text())
        self.sold = json.loads((FIXTURES / "sold_spring.json").read_text())

    def fetch_corpus(self, area, limit):
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
        self.corpus_calls = []

    def fetch_sold(self, area, agent_depth=25, limit=200):
        self.sold_calls.append(area)
        return self.sold

    def fetch_corpus(self, area, limit):
        self.corpus_calls.append((area, limit))
        return self.for_sale


def run(source, db, area="Spring", today=TODAY, center=None, **kwargs):
    return run_search(
        source=source,
        db=db,
        criteria=Criteria(area=area, max_price=250_000, **kwargs),
        limit=25,
        today=today,
        center=center,
    )


def test_sold_history_is_not_refetched_for_the_same_area_the_same_day(tmp_path):
    """Two actor runs per search is the whole latency budget, and sold history
    barely moves day to day. Re-running a search an hour later must not pay
    for the sold leg twice."""
    source, db = CountingSource(), make_db(tmp_path)
    run(source, db)
    run(source, db)
    assert source.sold_calls == ["Spring"]
    assert len(source.corpus_calls) == 1


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


class CorpusSource(CountingSource):
    """Alias kept for the inversion tests; CountingSource counts both legs."""


def test_a_fresh_corpus_costs_no_vendor_calls_at_all(tmp_path):
    """The point of the inversion. Once an area is cached, changing the
    criteria is a local question — no actor run, so no deadline to miss."""
    source, db = CorpusSource(), make_db(tmp_path)
    run(source, db, area="Spring")
    calls_after_first = (len(source.corpus_calls), len(source.sold_calls))
    run(source, db, area="Spring", beds=4)
    assert (len(source.corpus_calls), len(source.sold_calls)) == calls_after_first


def test_results_come_from_the_corpus_not_from_this_run(tmp_path):
    """The second search fetches nothing and still answers."""
    source, db = CorpusSource(), make_db(tmp_path)
    run(source, db, area="Spring")
    result = run(source, db, area="Spring", beds=3)
    assert source.corpus_calls == [("Spring", CORPUS_LIMIT)]
    assert [s.listing.address for s in result.scored]


def test_an_area_with_a_corpus_of_its_own_does_not_borrow_another_areas(tmp_path):
    """The corpus is a union of areas, not one undifferentiated pile.

    Scoping candidates to the area asked for is what keeps a Katy search from
    ranking Spring houses: with the vendor no longer filtering by area, the
    only thing standing between the two is this. Empty is the correct answer
    here — it says the area has not been fetched, which the caller can fix.
    """
    source, db = CorpusSource(), make_db(tmp_path)
    run(source, db, area="Spring")
    db.record_corpus_fetch("Katy", TODAY.isoformat())
    result = run(source, db, area="Katy")
    assert result.scored == []


def test_listings_the_search_rejected_still_serve_as_comps(tmp_path):
    """The circularity, expressed as a test.

    The comp pool used to be this run's own survivors, so anything the search
    filtered out was also invisible to the valuation — the estimate could not
    see the market it was supposedly measuring against. Here the two
    neighbours sit 1.4 miles out: past the half-mile radius the caller asked
    for, so they are correctly absent from the results, and well inside the
    two-mile comp radius, so they are exactly the evidence the estimate needs.
    """
    db = make_db(tmp_path)
    subject = make_active("subject", 30.0362, -95.3424, price=245_000)
    neighbours = [
        make_active("neighbour-1", 30.0565, -95.3424, price=525_000, sqft=1600),
        make_active("neighbour-2", 30.0566, -95.3425, price=498_000, sqft=1560),
    ]
    db.upsert_actives([subject, *neighbours])
    db.tag_corpus_area("Spring", [l.listing_id for l in [subject, *neighbours]])
    db.record_corpus_fetch("Spring", TODAY.isoformat())

    result = run(
        CorpusSource(),
        db,
        area="Spring",
        center_address="the subject",
        radius_miles=0.5,
        center=(30.0362, -95.3424),
    )

    assert [s.listing.listing_id for s in result.scored] == ["subject"]
    assert result.valuations["subject"].comp_count == 2


def make_active(listing_id, lat, lon, **kw):
    base = dict(
        listing_id=listing_id,
        address=f"{listing_id} Somewhere St",
        city="Spring",
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


def test_a_listing_missing_from_a_refresh_stops_being_returned(tmp_path):
    """A corpus that only ever adds is a corpus that lies.

    Upserts never delete, so a house that sold and left the feed would sit in
    the cache forever — returned as an active result and, worse, counted as an
    asking comp against its neighbours. A refresh is therefore authoritative
    about its own area: whatever it did not return is no longer for sale
    there.
    """
    source, db = CorpusSource(), make_db(tmp_path)
    first = run(source, db, area="Spring")
    assert len(first.scored) == 2

    source.for_sale = [row for row in source.for_sale if row["listingId"] != "F2"]
    later = run(source, db, area="Spring", today=TODAY + timedelta(days=1))

    assert "F2" not in [s.listing.listing_id for s in later.scored]
    assert len(later.scored) == 1


def test_limit_trims_the_ranked_list_not_the_fetch(tmp_path):
    """`limit` used to cap the vendor fetch and the results at once. Now the
    corpus is the whole area and `limit` only says how much of the ranking to
    return — the two numbers came apart when the fetch stopped being per
    search, and conflating them again would quietly shrink the comp pool."""
    source, db = CorpusSource(), make_db(tmp_path)
    result = run_search(
        source=source,
        db=db,
        criteria=Criteria(area="Spring", max_price=250_000),
        limit=1,
        today=TODAY,
    )
    assert len(result.scored) == 1
    assert source.corpus_calls == [("Spring", CORPUS_LIMIT)]
