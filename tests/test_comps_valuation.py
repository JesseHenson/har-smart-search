from datetime import date, timedelta

import pytest

from har_search.core.comps import (
    confidence_label,
    subdivision_list_to_sold,
    trimmed_mean,
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


def test_trimming_removes_the_top_and_bottom_decile_before_averaging():
    """Renamed from `test_trimmed_median_ignores_extremes`.

    A review of the old (median) estimator found this test passed identically
    against a plain `median()` with no trim at all -- the trim was provably a
    no-op on a median, so the name's claim of "ignores extremes" was not
    actually exercised by anything the trim did.

    Now that the estimator is a trimmed mean, the trim is load-bearing: the
    untrimmed mean of these five values is (100+145+150+155+900)/5 == 290.0,
    but dropping the one lowest and one highest value first leaves
    [145, 150, 155], whose mean is 150.0. The 290.0 -> 150.0 movement is the
    trim actually doing something, which is what this test now verifies.
    """
    values = [100.0, 145.0, 150.0, 155.0, 900.0]
    assert trimmed_mean(values) == pytest.approx(150.0)


def test_trimmed_mean_handles_short_lists():
    """n < 5 skips trimming entirely, so the mean runs over every value."""
    assert trimmed_mean([150.0]) == pytest.approx(150.0)
    assert trimmed_mean([140.0, 160.0]) == pytest.approx(150.0)


def test_trimmed_mean_diverges_from_a_median_on_a_skewed_retained_set():
    """Direct proof that mean and median now give different answers.

    Sorted input: [50, 100, 101, 102, 500, 900]. n=6 drops 1 from each end,
    retaining [100, 101, 102, 500]. A median of that retained set is
    (101 + 102) / 2 == 101.5 -- the old `trimmed_median` implementation's
    answer. The trimmed mean is (100+101+102+500)/4 == 200.75. The two
    disagree by nearly 100, so this is not one of the many inputs where a
    median and a trimmed mean happen to agree.
    """
    values = [50.0, 100.0, 101.0, 102.0, 500.0, 900.0]
    assert trimmed_mean(values) == pytest.approx(200.75)


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


def test_value_listing_uses_the_mean_of_a_skewed_comp_set():
    """End-to-end proof that `value_listing` now consults more than two comps.

    Six comps carry price/sqft of [50, 100, 101, 102, 500, 900] (sqft fixed at
    2400, so prices are those figures times 2400). Trimming drops 50 and 900,
    leaving [100, 101, 102, 500].

    Under the OLD median-based estimator this test would have asserted
    comp_estimate == 243_600: median([100,101,102,500]) == 101.5,
    101.5 * 2400 == 243_600.

    Under the new trimmed mean, mean([100,101,102,500]) == 200.75, and
    200.75 * 2400 == 481_800 -- nearly double the old answer, because the
    mean is pulled toward the one retained high value (500) in a way the
    median never was. That divergence is the point of this test.
    """
    ppsf_values = [50.0, 100.0, 101.0, 102.0, 500.0, 900.0]
    sales = [make_sale(f"M{i}", sold_price=ppsf * 2400) for i, ppsf in enumerate(ppsf_values)]
    valuation = value_listing(subject(), sales, active=[], today=TODAY)
    assert valuation.comp_estimate == 481_800


def test_two_same_side_outliers_survive_the_trim_and_skew_the_mean():
    """Pins the documented limitation: the trimmed mean is less robust than a
    median to *multiple* outliers on the same side.

    Four comps cluster near $150/sqft ([145, 148, 150, 152]) and two "bad"
    high comps ([400, 450]/sqft) survive comp selection -- exactly the
    scenario spec 6.2's tradeoff note describes: the sqft/type filters and
    the normalize.py sanity guards usually keep bad rows out, but they are
    not a guarantee, and this test assumes two get through anyway.

    With n=6, the trim drops exactly one value from each end: it removes the
    single lowest (145) and single highest (450), but the SECOND high
    outlier (400) survives into the retained set [148, 150, 152, 400].

    Old median-based estimator on that retained set: median == (150+152)/2
    == 151.0 -- effectively untouched by the surviving outlier, because a
    median needs a majority of bad values to move, not just one.

    New trimmed mean on the same retained set: mean == (148+150+152+400)/4
    == 212.5 -- pulled well above the true ~$150/sqft cluster by the single
    surviving outlier. That is a real, documented cost of preferring the
    mean on thin comp sets, not an oversight.
    """
    ppsf_values = [145.0, 148.0, 150.0, 152.0, 400.0, 450.0]
    sales = [make_sale(f"M{i}", sold_price=ppsf * 2400) for i, ppsf in enumerate(ppsf_values)]
    valuation = value_listing(subject(), sales, active=[], today=TODAY)
    assert valuation.comp_estimate == 510_000


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
