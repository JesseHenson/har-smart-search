"""Cross-layer requirement tests.

The suite is organized by module, and every defect found in this build lived
in a seam between modules — the `must` gate deleting the over-budget tail, the
sold-row exclusions with nowhere to go, the snapshot key colliding across
searches. None of those are visible from inside a single module's tests.

So these drive the real pipeline end to end — fixture source, normalization,
scoring, comps, SQLite, diff — one test per headline requirement from the
discovery call. They use **default** criteria on purpose: passing `must=` is
what hid the critical defect, because it disables the very gate under test.

No network: the source reads the same recorded fixtures `test_pipeline.py`
uses, plus rows defined here for cases the committed fixtures do not cover.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

from har_search.core.diff import diff_snapshots
from har_search.core.keys import resolve_saved_search, snapshot_key
from har_search.core.models import Criteria
from har_search.pipeline import run_search
from har_search.server.__main__ import build_whats_new_response
from har_search.store.db import Database

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 9, 4)

# A 4-bedroom clone of the committed F1 row. Identical in every other respect,
# so a score comparison between the two isolates the bedroom count — which is
# the requirement: "you might be able to show me a 4-bedroom house, but in the
# same price range, same area, same number of bathrooms."
FOUR_BEDROOM = {
    "listingId": "F4",
    "address": "5521 Lynngate Dr",
    "city": "Spring",
    "zip": "77373",
    "subdivision": "Greengate Place Sec 06",
    "latitude": 30.036200,
    "longitude": -95.342500,
    "price": 215000,
    "pricePerSqft": 142.38,
    "beds": 4,
    "bathsFull": 2,
    "bathsHalf": 0,
    "sqft": 1510,
    "lotSize": "6,600 sqft",
    "yearBuilt": 1979,
    "garage": "2 Attached",
    "maintenanceFee": "$374 Annually",
    "propertyType": "Single-Family",
    "status": "Active",
    "daysOnMarket": 1,
    "avmValue": "$205K",
    "mlsNumber": "44444444",
}


class FixtureSource:
    """The recorded fixtures, with rows overridable per run.

    Mutable between runs so requirement 3 can capture two genuinely different
    weeks rather than diffing a snapshot against itself.
    """

    name = "fixture"

    def __init__(self, extra_for_sale: list[dict] | None = None):
        self.for_sale = json.loads((FIXTURES / "for_sale_spring.json").read_text())
        self.for_sale += deepcopy(extra_for_sale or [])
        self.sold = json.loads((FIXTURES / "sold_spring.json").read_text())

    def fetch_for_sale(self, criteria, limit):
        return self.for_sale

    def fetch_sold(self, area, agent_depth=25, limit=200):
        return self.sold


def make_db(tmp_path, name="requirements.db") -> Database:
    db = Database(tmp_path / name)
    db.init_schema()
    return db


def by_id(result) -> dict:
    return {s.listing.listing_id: s for s in result.scored}


# --- R1: similarity search, not a filter ---------------------------------


def test_a_four_bedroom_surfaces_and_ranks_well_against_a_three_bedroom_request(tmp_path):
    """The discovery call's headline example, through the whole product.

    "you might be able to show me a 4-bedroom house, but in the same price
    range, same area, same number of bathrooms."

    A filter returns nothing here. A similarity finder returns the 4-bed,
    ranked just below the exact match rather than dropped.
    """
    result = run_search(
        source=FixtureSource(extra_for_sale=[FOUR_BEDROOM]),
        db=make_db(tmp_path),
        criteria=Criteria(area="Spring", beds=3, baths=2, max_price=250_000),
        today=TODAY,
    )

    scored = by_id(result)
    assert "F4" in scored, "the 4-bedroom must survive a 3-bedroom request"

    four = scored["F4"]
    three = scored["F1"]
    assert four.score > 0.85, "spec 5.2: a 4-bed against a 3-bed target scores 0.85"
    assert four.score < three.score, "it ranks below the exact match, not above it"

    beds = next(p for p in four.params if p.name == "beds")
    assert beds.known is True
    assert 0.84 < beds.score < 0.86

    # The explanation is prose, and names the deviation and the compensations.
    assert "beds" in four.why.lower()
    assert "_" not in four.why, f"machine identifier leaked into the why: {four.why}"


# --- R1: the over-budget tail (spec 5.2, and the controller's Critical) ---


def test_an_over_budget_listing_surfaces_when_nothing_under_budget_matches(tmp_path):
    """"then you may show me some houses above $200,000, if the search result
    is not there for below."

    Nothing in the fixtures is under $180,000. With `max_price` in the default
    `must`, `score_listing` deletes anything scoring below 0.5 on it, and
    `ceiling_score` crosses 0.5 at +16% over budget — so both listings here
    ($215k is +19%, $220k is +22%) were fetched, paid for, and discarded
    before the user saw them. This test asserts they arrive instead.
    """
    criteria = Criteria(area="Spring", beds=3, max_price=180_000)
    assert criteria.must == ["area"], "this test is about the DEFAULT gate"

    result = run_search(source=FixtureSource(), db=make_db(tmp_path), criteria=criteria, today=TODAY)

    scored = by_id(result)
    assert set(scored) == {"F1", "F2"}, "the over-budget tail must be shown, not deleted"
    assert result.dropped_by_must == 0

    # Over budget and known to be over budget: penalized, not hidden.
    price = next(p for p in scored["F1"].params if p.name == "max_price")
    assert price.known is True
    assert price.score < 0.5, (
        "if this rises above 0.5 the test stops covering the must gate"
    )
    assert "$215,000 vs $180,000 budget" in price.detail

    # Ranked, and still carrying the value KPI the user sorts by.
    assert result.scored[0].score >= result.scored[-1].score
    for item in result.scored:
        assert item.listing.listing_id in result.valuations


def test_a_hard_budget_is_still_available_and_still_deletes_the_tail(tmp_path):
    """The default is soft. The override the spec promises still works."""
    result = run_search(
        source=FixtureSource(),
        db=make_db(tmp_path),
        criteria=Criteria(
            area="Spring", beds=3, max_price=180_000, must=["area", "max_price"]
        ),
        today=TODAY,
    )
    assert result.scored == []
    assert result.dropped_by_must == 2


# --- R3: week over week --------------------------------------------------


def test_a_second_run_reports_what_changed_since_the_first(tmp_path):
    """"every week I can run that, show me all the investments, everything
    that's come up."

    Two runs of the same criteria against a moved market: one price cut, one
    new listing, one withdrawn. Both runs go through the real pipeline and
    land in the same SQLite database, and the diff is read back the way the
    `whats_new` tool reads it.
    """
    db = make_db(tmp_path)
    criteria = Criteria(area="Spring", beds=3, max_price=250_000)

    week_one = run_search(
        source=FixtureSource(), db=db, criteria=criteria, today=TODAY
    )

    # The market moves: F1 is cut, F2 goes away, the 4-bedroom appears.
    later = FixtureSource(extra_for_sale=[FOUR_BEDROOM])
    later.for_sale = [row for row in later.for_sale if row["listingId"] != "F2"]
    for row in later.for_sale:
        if row["listingId"] == "F1":
            row["price"] = 199_000
    week_two = run_search(source=later, db=db, criteria=criteria, today=TODAY)

    assert week_two.saved_search == week_one.saved_search, (
        "the same criteria must land in the same bucket week to week"
    )
    assert week_two.snapshot_id != week_one.snapshot_id

    key, error = resolve_saved_search("Spring", db.saved_search_keys())
    assert error is None
    snapshots = db.recent_snapshots(key, limit=2)
    assert len(snapshots) == 2

    changes = diff_snapshots(
        db.get_snapshot_listings(snapshots[1]["id"]),
        db.get_snapshot_listings(snapshots[0]["id"]),
    )
    payload = build_whats_new_response(changes)

    assert [row["listing_id"] for row in payload["new"]] == ["F4"]
    assert [row["listing_id"] for row in payload["gone"]] == ["F2"]
    assert len(payload["price_cut"]) == 1
    cut = payload["price_cut"][0]
    assert cut["listing_id"] == "F1"
    assert (cut["old_price"], cut["new_price"]) == (215_000, 199_000)


def test_two_different_searches_in_one_area_do_not_diff_against_each_other(tmp_path):
    """The snapshot key used to be the area string alone.

    A starter search and a family search in Spring wrote into one bucket, and
    the diff between them reported every listing in each as NEW or GONE — a
    week-over-week screen that is pure noise.
    """
    db = make_db(tmp_path)
    starter = Criteria(area="Spring", beds=3, max_price=250_000)
    family = Criteria(area="Spring", beds=5, max_price=600_000)

    first = run_search(source=FixtureSource(), db=db, criteria=starter, today=TODAY)
    second = run_search(
        source=FixtureSource(extra_for_sale=[FOUR_BEDROOM]),
        db=db,
        criteria=family,
        today=TODAY,
    )

    assert first.saved_search != second.saved_search
    assert first.saved_search == snapshot_key(starter)
    assert second.saved_search == snapshot_key(family)

    # Each bucket sees only its own runs, so neither has anything to diff yet.
    assert len(db.recent_snapshots(first.saved_search, limit=2)) == 1
    assert len(db.recent_snapshots(second.saved_search, limit=2)) == 1

    # And the ambiguous bare area name is refused rather than guessed at.
    key, error = resolve_saved_search("Spring", db.saved_search_keys())
    assert key is None
    assert first.saved_search in error and second.saved_search in error


# --- R2 / spec 4.2: the data-quality trail, end to end -------------------


def test_every_dropped_row_is_counted_with_its_reason(tmp_path):
    """Spec 4.2: "Silent dropping is not acceptable."

    The fixtures carry both defects recon found: a $1,325 for-sale duplex and
    a lease sitting inside the *sold* results. Both must arrive at the user as
    counts with reasons, on separate ledgers.
    """
    result = run_search(
        source=FixtureSource(),
        db=make_db(tmp_path),
        criteria=Criteria(area="Spring", beds=3, max_price=250_000),
        today=TODAY,
    )
    assert result.exclusions == {"price_below_floor": 1}
    assert result.sold_exclusions == {"lease": 1}


def test_the_implausible_bedroom_guard_holds_on_the_sold_path(tmp_path):
    """S3 is 2322 Shadow Glen: 10 bedrooms on 4,507 sqft, and it is a SOLD row.

    Unguarded it reaches the bedroom-adjustment median in `comps.py` and moves
    valuations by up to the full +/-9% cap in the wrong direction.
    """
    db = make_db(tmp_path)
    run_search(
        source=FixtureSource(),
        db=db,
        criteria=Criteria(area="Spring", beds=3, max_price=250_000),
        today=TODAY,
    )
    sales = db.sales_near(30.10, -95.38, miles=5.0, since=date(2026, 1, 1))
    shadow_glen = next(s for s in sales if s.mls_number == "S3")
    assert shadow_glen.beds is None
    # Real data on the same row is untouched.
    assert shadow_glen.sqft == 4507
    assert shadow_glen.sold_price == 400_000
