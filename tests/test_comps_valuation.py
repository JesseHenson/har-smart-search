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


def make_sale(mls, sold_price, sqft=2400, days_ago=30, list_price=None) -> Sale:
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


def test_subdivision_list_to_sold_ratio():
    sales = [
        make_sale("M0", 400_000, list_price=475_000),
        make_sale("M1", 460_000, list_price=470_000),
        make_sale("M2", 375_000, list_price=360_000),
    ]
    ratio = subdivision_list_to_sold(sales)
    assert 0.90 < ratio < 1.00


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
