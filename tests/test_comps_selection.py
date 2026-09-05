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
