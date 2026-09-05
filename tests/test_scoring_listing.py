import pytest

from har_search.core.models import Criteria, DuplexScope, GarageInfo, Listing, PropertyType
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
