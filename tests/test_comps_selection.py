from datetime import date, timedelta

from har_search.core.comps import haversine_miles, select_comps
from har_search.core.models import Listing, PropertyType, Sale

TODAY = date(2026, 9, 4)
SUBJECT = Listing(
    listing_id="S1",
    subdivision="Harmony",
    lat=30.10,
    lon=-95.38,
    price=390_000,
    sqft=2400,
    property_type=PropertyType.SINGLE_FAMILY,
)


def make_sale(mls, *, sqft=2400, lat=30.10, lon=-95.38, days_ago=30,
              subdivision="Harmony", sold_price=380_000,
              property_type=PropertyType.SINGLE_FAMILY) -> Sale:
    return Sale(
        mls_number=mls,
        sold_price=sold_price,
        sold_date=TODAY - timedelta(days=days_ago),
        subdivision=subdivision,
        lat=lat,
        lon=lon,
        sqft=sqft,
        property_type=property_type,
    )


def test_haversine_is_accurate_over_short_distances():
    miles = haversine_miles(30.10, -95.38, 30.10, -95.36)
    assert 1.1 < miles < 1.3


def test_tier_one_prefers_same_subdivision_recent_sales():
    sales = [make_sale(f"M{i}") for i in range(6)]
    comps, basis = select_comps(SUBJECT, sales, active=[], today=TODAY)
    assert len(comps) == 6
    assert basis == "sold"
    assert all(c.subdivision == "Harmony" for c in comps)


def test_stale_sales_are_excluded_from_tier_one():
    sales = [make_sale(f"M{i}", days_ago=400) for i in range(6)]
    comps, _ = select_comps(SUBJECT, sales, active=[], today=TODAY)
    assert comps == []


def test_size_mismatch_is_excluded():
    sales = [make_sale(f"M{i}", sqft=800) for i in range(6)]
    comps, _ = select_comps(SUBJECT, sales, active=[], today=TODAY)
    assert comps == []


def test_property_type_mismatch_is_excluded():
    sales = [
        make_sale(f"M{i}", property_type=PropertyType.DUPLEX) for i in range(6)
    ]
    comps, _ = select_comps(SUBJECT, sales, active=[], today=TODAY)
    assert comps == []


def test_cascade_widens_to_one_mile_when_subdivision_is_thin():
    sales = [make_sale("M0")] + [
        make_sale(f"N{i}", subdivision="Other", lon=-95.37) for i in range(5)
    ]
    comps, basis = select_comps(SUBJECT, sales, active=[], today=TODAY)
    assert len(comps) >= 5
    assert basis == "sold"


def test_falls_back_to_active_listings_and_labels_the_basis():
    active = [
        Listing(
            listing_id=f"A{i}",
            subdivision="Harmony",
            lat=30.10,
            lon=-95.38,
            price=400_000,
            sqft=2400,
            property_type=PropertyType.SINGLE_FAMILY,
        )
        for i in range(6)
    ]
    comps, basis = select_comps(SUBJECT, sales=[], active=active, today=TODAY)
    assert basis == "asking"
    assert len(comps) == 6


def test_subject_itself_is_never_its_own_comp():
    active = [SUBJECT] + [
        Listing(
            listing_id=f"A{i}",
            subdivision="Harmony",
            lat=30.10,
            lon=-95.38,
            price=400_000,
            sqft=2400,
            property_type=PropertyType.SINGLE_FAMILY,
        )
        for i in range(5)
    ]
    comps, _ = select_comps(SUBJECT, sales=[], active=active, today=TODAY)
    assert all(c.id != "S1" for c in comps)


def test_fallback_returns_widest_non_empty_result_when_no_tier_reaches_target():
    # Construct a cascade where each tier matches fewer than TARGET_COMPS (5):
    # - Tier 1 (subdivision): 0 matches (no same-subdivision sales)
    # - Tier 2 (one_mile, 180 days): 2 matches (M0, M1 within 1 mile, recent)
    # - Tier 3 (two_miles, 365 days): 4 matches (M0, M1 from tier 2 + M2, M3 within 2 miles but older)
    # - Tier 4 (active): 0 matches (no active listings)
    # Expected: Returns the widest (4 comps) from tier 3, with basis="sold", without reaching TARGET_COMPS (5)
    sales = [
        make_sale("M0", subdivision="Other", lon=-95.37, days_ago=30),  # ~0.6 miles, 30 days → matches tier 2+
        make_sale("M1", subdivision="Other", lon=-95.37, days_ago=30),  # ~0.6 miles, 30 days → matches tier 2+
        make_sale("M2", subdivision="Other", lon=-95.36, days_ago=200),  # ~1.2 miles, 200 days → matches tier 3 only (outside tier 2's 180-day limit)
        make_sale("M3", subdivision="Other", lon=-95.36, days_ago=200),  # ~1.2 miles, 200 days → matches tier 3 only
    ]

    comps, basis = select_comps(SUBJECT, sales, active=[], today=TODAY)

    # Should return tier 3's widest non-empty result (4 comps), without reaching TARGET_COMPS
    assert len(comps) == 4, f"Expected 4 comps from tier 3 fallback, got {len(comps)}"
    assert basis == "sold", f"Expected basis 'sold', got '{basis}'"
    # Verify these are all the tier 3 matches
    assert all(c.id in ["M0", "M1", "M2", "M3"] for c in comps)


def test_fallback_returns_none_basis_when_no_tier_matches_anything():
    # All sales fail to match any tier due to property type mismatch
    sales = [
        make_sale(f"M{i}", property_type=PropertyType.DUPLEX)
        for i in range(6)
    ]

    comps, basis = select_comps(SUBJECT, sales, active=[], today=TODAY)

    # Should return empty comps with "none" basis (no tier produced a result)
    assert comps == []
    assert basis == "none", f"Expected basis 'none' for empty result, got '{basis}'"
