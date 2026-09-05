from datetime import date, timedelta

import pytest

from har_search.core.comps import (
    confidence_label,
    subdivision_list_to_sold,
    trimmed_median,
    value_listing,
)
from har_search.core.models import Listing, MoneyRange, PropertyType, Sale

TODAY = date(2026, 9, 4)


def make_sale(mls, sold_price, sqft=2400, days_ago=30, list_price=None, lot_sqft=None) -> Sale:
    return Sale(
        mls_number=mls,
        sold_price=sold_price,
        list_price=list_price,
        sold_date=TODAY - timedelta(days=days_ago),
        subdivision="Harmony",
        lat=30.10,
        lon=-95.38,
        sqft=sqft,
        beds=4,
        baths_full=2,
        year_built=2014,
        lot_sqft=lot_sqft,
        property_type=PropertyType.SINGLE_FAMILY,
    )


def subject(price=390_000, **kw) -> Listing:
    base = dict(
        listing_id="S1",
        subdivision="Harmony",
        lat=30.10,
        lon=-95.38,
        price=price,
        sqft=2400,
        beds=4,
        baths_full=2,
        year_built=2014,
        property_type=PropertyType.SINGLE_FAMILY,
    )
    base.update(kw)
    return Listing(**base)


def test_trimmed_median_ignores_extremes():
    values = [100.0, 145.0, 150.0, 155.0, 900.0]
    assert trimmed_median(values) == pytest.approx(150.0)


def test_trimmed_median_handles_short_lists():
    assert trimmed_median([150.0]) == pytest.approx(150.0)
    assert trimmed_median([140.0, 160.0]) == pytest.approx(150.0)


@pytest.mark.parametrize(
    "n,label",
    [(9, "high"), (8, "high"), (6, "medium"), (4, "low"), (2, "insufficient")],
)
def test_confidence_label_thresholds(n, label):
    assert confidence_label(n) == label


def test_value_listing_produces_estimate_and_kpi():
    sales = [make_sale(f"M{i}", 360_000) for i in range(6)]
    valuation = value_listing(subject(price=390_000), sales, active=[], today=TODAY)
    assert valuation.comp_count == 6
    assert valuation.comp_basis == "sold"
    assert valuation.confidence == "medium"
    assert valuation.comp_estimate == pytest.approx(360_000, rel=0.02)
    # Asking above comps means a positive delta.
    assert valuation.delta_pct > 0.07


def test_planted_outlier_does_not_move_the_estimate():
    """A 10-bedroom typo priced at $2M must not drag the neighbourhood."""
    sales = [make_sale(f"M{i}", 360_000) for i in range(6)]
    sales.append(make_sale("OUTLIER", 2_000_000))
    valuation = value_listing(subject(), sales, active=[], today=TODAY)
    assert valuation.comp_estimate == pytest.approx(360_000, rel=0.05)


def test_too_few_comps_returns_insufficient_and_no_number():
    sales = [make_sale("M0", 360_000), make_sale("M1", 365_000)]
    valuation = value_listing(subject(), sales, active=[], today=TODAY)
    assert valuation.confidence == "insufficient"
    assert valuation.comp_estimate is None
    assert valuation.delta_pct is None


def test_bedroom_adjustment_is_applied_and_capped():
    sales = [make_sale(f"M{i}", 360_000) for i in range(6)]
    more_beds = value_listing(subject(beds=6), sales, active=[], today=TODAY)
    baseline = value_listing(subject(beds=4), sales, active=[], today=TODAY)
    assert more_beds.comp_estimate > baseline.comp_estimate
    assert more_beds.comp_estimate <= baseline.comp_estimate * 1.10


def test_single_adjustment_saturates_its_individual_cap():
    """A 16-bedroom gap must be clamped to the beds cap (0.09), not applied raw.

    comp beds median is 4 (all six comps use the make_sale default). Subject
    beds=20 gives a raw delta of 16 * 0.03 = 0.48, far past the 0.09 cap.
    Baths and year_built match the comps exactly (delta 0), and the subject's
    lot_sqft is left unset, so no other adjustment contributes -- this isolates
    the beds cap specifically, distinct from the aggregate cap in the test
    below.

    If `_clamp` did not exist (or the beds cap were not enforced), the factor
    would be 0.48 and comp_estimate would be int(round(360_000 * 1.48)) ==
    532_800, not 392_400. The two numbers are far enough apart that this test
    fails hard if the individual cap is removed.
    """
    sales = [make_sale(f"M{i}", 360_000) for i in range(6)]
    valuation = value_listing(subject(beds=20), sales, active=[], today=TODAY)
    assert valuation.comp_estimate == 392_400


def test_aggregate_adjustment_cap_bounds_combined_factor():
    """Four adjustments, each saturating its own cap, must not simply add up.

    beds (+0.09), baths (+0.075), age (+0.10), and lot (+0.05) each hit their
    individual caps here, for an unclamped sum of 0.315 -- a ~32% swing on a
    $360,000 estimate. AGGREGATE_ADJUSTMENT_CAP=0.15 must bring the applied
    factor down to 0.15, giving comp_estimate = int(round(360_000 * 1.15)) ==
    414_000.

    If the aggregate cap in `_adjustment_factor` were removed, the factor
    would be 0.315 and comp_estimate would be int(round(360_000 * 1.315)) ==
    473_400 -- a $59,400 difference from the capped answer, so this test
    fails clearly if the aggregate clamp is deleted. It also confirms the
    existing bedroom test (0.06, well under 0.15) and outlier test (factor
    0.0) are undisturbed by the new cap.
    """
    sales = [make_sale(f"M{i}", 360_000, lot_sqft=8_000) for i in range(6)]
    subj = subject(beds=20, baths_full=10, year_built=2050, lot_sqft=100_000)
    valuation = value_listing(subj, sales, active=[], today=TODAY)
    assert valuation.comp_estimate == 414_000


def test_subdivision_list_to_sold_ratio():
    sales = [
        make_sale("M0", 400_000, list_price=475_000),
        make_sale("M1", 460_000, list_price=470_000),
        make_sale("M2", 375_000, list_price=360_000),
    ]
    ratio = subdivision_list_to_sold(sales, "Harmony")
    assert 0.90 < ratio < 1.00


def test_subdivision_list_to_sold_survives_a_capitalization_difference():
    """Vendor subdivision strings are free text.

    Tier matching normalized case; this filter used `==`. So six comps could
    agree they shared the subject's subdivision while the list-to-sold ratio —
    "arguably the most actionable number the tool can produce" — returned None
    because one row said "HARMONY" and the subject said "Harmony".
    """
    sales = [
        make_sale("M0", 400_000, list_price=475_000),
        make_sale("M1", 460_000, list_price=470_000),
        make_sale("M2", 375_000, list_price=360_000),
    ]
    for sale in sales:
        sale.subdivision = "  HARMONY "
    ratio = subdivision_list_to_sold(sales, "Harmony")
    assert ratio is not None
    assert 0.90 < ratio < 1.00


def test_subdivision_list_to_sold_is_none_when_the_subdivision_is_unknown():
    """An unknown subdivision must not silently become an area-wide ratio."""
    sales = [make_sale("M0", 400_000, list_price=475_000)]
    assert subdivision_list_to_sold(sales, None) is None


def test_valuation_ratio_survives_a_capitalization_difference_end_to_end():
    """The same defect through `value_listing`, where it actually bit."""
    sales = [make_sale(f"M{i}", 360_000, list_price=380_000) for i in range(6)]
    for sale in sales:
        sale.subdivision = "harmony"
    valuation = value_listing(subject(), sales, active=[], today=TODAY)
    assert valuation.subdivision_list_to_sold is not None


def test_appraisal_district_value_is_carried_through():
    sales = [make_sale(f"M{i}", 360_000) for i in range(6)]
    subj = subject()
    subj.appraisal = MoneyRange(low=352_000, high=352_999)
    valuation = value_listing(subj, sales, active=[], today=TODAY)
    assert valuation.appraisal_district.low == 352_000
    assert valuation.spread_flag == "clustered"


def test_scattered_flag_when_sources_disagree():
    sales = [make_sale(f"M{i}", 360_000) for i in range(6)]
    subj = subject()
    subj.appraisal = MoneyRange(low=200_000, high=200_999)
    valuation = value_listing(subj, sales, active=[], today=TODAY)
    assert valuation.spread_flag == "scattered"
