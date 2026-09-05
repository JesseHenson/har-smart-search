import pytest

from har_search.core.models import Criteria, DuplexScope, GarageInfo, HOA, Listing, PropertyType
from har_search.core.scoring import score_listing

SPRING = (30.06, -95.42)


def make_listing(**overrides) -> Listing:
    base = dict(
        listing_id="L1",
        city="Spring",
        subdivision="Greengate Place Sec 06",
        lat=30.036156,
        lon=-95.342447,
        price=215_000,
        price_per_sqft=142.38,
        beds=3,
        baths_full=2,
        sqft=1510,
        year_built=1979,
        garage=GarageInfo(spaces=2, attached=True),
        property_type=PropertyType.SINGLE_FAMILY,
    )
    base.update(overrides)
    return Listing(**base)


def test_perfect_match_scores_near_one():
    criteria = Criteria(area="Spring", beds=3, baths=2, max_price=250_000)
    scored = score_listing(make_listing(), criteria, SPRING)
    assert scored.score > 0.95
    assert scored.coverage == 1.0


def test_four_bedroom_still_ranks_well_against_three_bedroom_request():
    """The call's headline example, expressed as a test."""
    criteria = Criteria(area="Spring", beds=3, baths=2, max_price=250_000)
    three = score_listing(make_listing(beds=3), criteria, SPRING)
    four = score_listing(make_listing(beds=4), criteria, SPRING)
    assert four.score > 0.85
    assert four.score < three.score


def test_slightly_over_budget_listing_still_appears():
    criteria = Criteria(area="Spring", beds=3, max_price=200_000, must=["area"])
    scored = score_listing(make_listing(price=215_000), criteria, SPRING)
    assert scored is not None
    assert scored.score > 0.6


def test_must_parameter_below_threshold_removes_the_listing():
    criteria = Criteria(area="Spring", max_price=200_000, must=["area", "max_price"])
    assert score_listing(make_listing(price=400_000), criteria, SPRING) is None


def test_unknown_parameters_are_excluded_from_the_mean_and_lower_coverage():
    """A duplex with no bed/bath data must not score as a zero-bedroom house."""
    criteria = Criteria(
        area="Spring", beds=3, baths=2, garage_spaces=1, max_price=700_000
    )
    duplex = make_listing(
        beds=None,
        baths_full=None,
        garage=None,
        property_type=PropertyType.DUPLEX,
        duplex_scope=DuplexScope.WHOLE,
        price=579_900,
    )
    scored = score_listing(duplex, criteria, SPRING)
    assert scored.score > 0.9
    assert scored.coverage < 0.6
    unknown = [p.name for p in scored.params if not p.known]
    assert set(unknown) == {"beds", "baths", "garage_spaces"}


def test_no_hoa_request_treats_missing_fee_as_unknown():
    criteria = Criteria(area="Spring", no_hoa=True, max_price=250_000)
    scored = score_listing(make_listing(hoa=None), criteria, SPRING)
    hoa_param = next(p for p in scored.params if p.name == "no_hoa")
    assert hoa_param.known is False


def test_why_names_the_deviation_and_the_matches():
    criteria = Criteria(area="Spring", beds=3, baths=2, max_price=250_000)
    scored = score_listing(make_listing(beds=4), criteria, SPRING)
    assert "beds" in scored.why.lower()


def test_no_hoa_zero_fee_scores_perfectly():
    """A listing with $0/mo HOA should score 1.0, not 0.0."""
    criteria = Criteria(area="Spring", no_hoa=True, max_price=250_000)
    scored = score_listing(make_listing(hoa=HOA(monthly_usd=0.0)), criteria, SPRING)
    hoa_param = next(p for p in scored.params if p.name == "no_hoa")
    assert hoa_param.known is True
    assert hoa_param.score == 1.0
    assert "no HOA" in hoa_param.detail


def test_no_hoa_positive_fee_scores_zero():
    """A listing with a positive HOA fee should score 0.0 when no_hoa is requested."""
    criteria = Criteria(area="Spring", no_hoa=True, max_price=250_000)
    scored = score_listing(make_listing(hoa=HOA(monthly_usd=150.0)), criteria, SPRING)
    hoa_param = next(p for p in scored.params if p.name == "no_hoa")
    assert hoa_param.known is True
    assert hoa_param.score == 0.0
    assert "$150/mo" in hoa_param.detail


# --- Default `must` behaviour --------------------------------------------
#
# The tests above that pass `must=["area"]` explicitly document the OVERRIDE
# path and are kept for that reason. The tests below deliberately pass no
# `must` at all, so they exercise Criteria's default. No test did that before,
# which is how a default of ["area", "max_price"] — deleting every listing
# more than ~16% over budget — survived the whole build.


def test_over_budget_listing_survives_the_default_must_gate():
    """Spec 5.2: $250,000 against a $200,000 budget is a rankable outcome.

    ceiling_score(250_000, 200_000) is 0.29, below MUST_THRESHOLD. With
    max_price in the default `must` this listing is deleted outright and the
    user never sees the tail the discovery call asked for by name.
    """
    criteria = Criteria(area="Spring", beds=3, max_price=200_000)
    assert criteria.must == ["area"]
    scored = score_listing(make_listing(price=250_000), criteria, SPRING)
    assert scored is not None
    price = next(p for p in scored.params if p.name == "max_price")
    assert price.score == pytest.approx(0.29, abs=0.01)


def test_over_budget_listings_still_rank_below_in_budget_ones_by_default():
    """Soft, not ignored: the over-budget tail surfaces and sorts to the bottom."""
    criteria = Criteria(area="Spring", beds=3, max_price=200_000)
    in_budget = score_listing(make_listing(price=195_000), criteria, SPRING)
    over = score_listing(make_listing(price=250_000), criteria, SPRING)
    far_over = score_listing(make_listing(price=300_000), criteria, SPRING)
    assert None not in (in_budget, over, far_over)
    assert in_budget.score > over.score > far_over.score


def test_default_must_still_deletes_a_listing_outside_the_area():
    """Location stays hard by default — only budget was relaxed."""
    criteria = Criteria(area="Spring", beds=3, max_price=200_000)
    elsewhere = make_listing(
        city="Dallas", subdivision="Somewhere Else", lat=32.78, lon=-96.80
    )
    assert score_listing(elsewhere, criteria, SPRING) is None


def test_budget_can_still_be_made_hard_by_naming_it_in_must():
    """The default is soft; the override is still available and still works."""
    criteria = Criteria(
        area="Spring", beds=3, max_price=200_000, must=["area", "max_price"]
    )
    assert score_listing(make_listing(price=250_000), criteria, SPRING) is None


# --- No machine identifiers in user-facing prose (spec 9) ----------------


def test_unknown_ceiling_parameter_reads_as_english_not_an_identifier():
    """This rendered "no price_per_sqft" on screen.

    It is reachable in the demo itself: the prospect's own example specifies a
    $/sqft ceiling, and multi-family listings do not publish one.
    """
    criteria = Criteria(area="Spring", max_price=250_000, max_price_per_sqft=120)
    scored = score_listing(make_listing(price_per_sqft=None), criteria, SPRING)
    param = next(p for p in scored.params if p.name == "max_price_per_sqft")
    assert param.known is False
    assert param.detail == "price per sqft not published"
    assert "_" not in param.detail


def test_no_scoring_detail_or_explanation_contains_a_raw_identifier():
    """A sweep, so a new parameter cannot quietly reintroduce the habit."""
    criteria = Criteria(
        area="Spring",
        beds=3,
        baths=2,
        garage_spaces=2,
        sqft=1500,
        max_price=250_000,
        max_price_per_sqft=120,
        max_age_years=20,
        property_types=["single_family"],
        no_hoa=True,
        min_school_rating="B",
    )
    bare = Listing(listing_id="L2", city="Spring", price=215_000)
    for listing in (make_listing(), bare):
        scored = score_listing(listing, criteria, SPRING)
        assert scored is not None
        for param in scored.params:
            assert "_" not in param.detail, f"{param.name}: {param.detail}"
        assert "_" not in scored.why, scored.why
