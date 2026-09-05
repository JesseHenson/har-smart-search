import pytest

from har_search.core.models import PropertyType
from har_search.core.scoring import (
    DEFAULT_WEIGHTS,
    TAU,
    categorical_score,
    ceiling_score,
    geo_score,
    target_score,
)


@pytest.mark.parametrize(
    "actual,expected",
    [(3, 1.00), (4, 0.85), (5, 0.59), (2, 0.40), (1, 0.14)],
)
def test_bedroom_target_scores_match_spec_table(actual, expected):
    """Spec 5.2: a 4-bed against a 3-bed target must stay competitive."""
    tau_over, tau_under = TAU["beds"]
    assert target_score(actual, 3, tau_over, tau_under) == pytest.approx(
        expected, abs=0.01
    )


def test_target_score_is_asymmetric():
    tau_over, tau_under = TAU["beds"]
    over = target_score(4, 3, tau_over, tau_under)
    under = target_score(2, 3, tau_over, tau_under)
    assert over > under


@pytest.mark.parametrize(
    "price,expected",
    [(200_000, 1.00), (180_000, 1.00), (220_000, 0.72), (250_000, 0.29), (300_000, 0.09)],
)
def test_ceiling_scores_match_spec_table(price, expected):
    """Spec 5.2: 'show me some above $200,000 if there is nothing below'."""
    assert ceiling_score(price, 200_000) == pytest.approx(expected, abs=0.01)


def test_geo_score_rewards_subdivision_match():
    assert geo_score(subdivision_match=True, miles=12.0) == 1.0


@pytest.mark.parametrize(
    "miles,expected", [(0.0, 1.00), (1.0, 0.90), (3.0, 0.50), (6.0, 0.20)]
)
def test_geo_score_decays_with_distance(miles, expected):
    assert geo_score(subdivision_match=False, miles=miles) == pytest.approx(
        expected, abs=0.01
    )


def test_categorical_score_exact_sibling_and_mismatch():
    assert categorical_score(PropertyType.DUPLEX, [PropertyType.DUPLEX]) == 1.0
    assert categorical_score(PropertyType.FOURPLEX, [PropertyType.DUPLEX]) == 0.5
    assert categorical_score(PropertyType.MULTI_FAMILY, [PropertyType.DUPLEX]) == 0.5
    assert categorical_score(PropertyType.SINGLE_FAMILY, [PropertyType.DUPLEX]) == 0.0


def test_default_weights_make_location_and_budget_heaviest():
    assert DEFAULT_WEIGHTS["area"] == 3.0
    assert DEFAULT_WEIGHTS["max_price"] == 3.0
    assert DEFAULT_WEIGHTS["beds"] == 2.0
    assert max(DEFAULT_WEIGHTS.values()) == 3.0


# Regression tests for the degenerate paths of the primitives. These pin the
# CURRENT behaviour of a "defensive default" (never treat unknown-as-0 in the
# aggregator itself) so a future change to these primitives can't silently
# alter that default without a test failing. See scoring.py docstrings on
# geo_score and categorical_score for the contract these defaults sit inside.


def test_ceiling_score_with_zero_ceiling_is_zero():
    assert ceiling_score(100, 0) == 0.0


def test_ceiling_score_with_negative_ceiling_is_zero():
    assert ceiling_score(100, -50) == 0.0


def test_target_score_with_zero_tau_is_exact_match_only():
    assert target_score(3, 3, 0.0, 0.0) == 1.0
    assert target_score(4, 3, 0.0, 0.0) == 0.0
    assert target_score(2, 3, 0.0, 0.0) == 0.0


def test_geo_score_unknown_location_defaults_to_zero():
    """geo_score(False, None) returns 0.0 as a defensive default — callers
    must branch on unknown location themselves rather than rely on this."""
    assert geo_score(subdivision_match=False, miles=None) == 0.0


def test_categorical_score_unknown_type_defaults_to_zero():
    """categorical_score(None, wanted) returns 0.0 as a defensive default —
    callers must branch on unknown property type themselves rather than
    rely on this."""
    assert categorical_score(None, [PropertyType.DUPLEX]) == 0.0
