from datetime import date

from har_search.core.models import (
    Criteria,
    DuplexScope,
    GarageInfo,
    Listing,
    MoneyRange,
    PropertyType,
    Sale,
)


def test_listing_defaults_unknown_fields_to_none():
    listing = Listing(listing_id="abc123")
    assert listing.beds is None
    assert listing.garage is None
    assert listing.hoa is None
    assert listing.duplex_scope is DuplexScope.UNKNOWN
    assert listing.flags == ()


def test_garage_info_holds_parsed_parts():
    garage = GarageInfo(spaces=3, attached=True, tags=("oversized", "tandem"))
    assert garage.spaces == 3
    assert garage.attached is True


def test_money_range_preserves_imprecision():
    rng = MoneyRange(low=1_000_000, high=1_099_999)
    assert rng.high - rng.low == 99_999
    assert rng.midpoint == 1_049_999


def test_criteria_defaults_area_and_budget_to_hard_constraints():
    criteria = Criteria(area="Spring", beds=3)
    assert criteria.must == ["area", "max_price"]
    assert criteria.max_price is None


def test_sale_requires_sold_price_and_date():
    sale = Sale(
        mls_number="12345678",
        sold_price=460_000,
        sold_date=date(2026, 8, 27),
    )
    assert sale.sold_price == 460_000
    assert sale.property_type is None


def test_property_type_enum_covers_duplex_family():
    assert PropertyType.DUPLEX.value == "duplex"
    assert PropertyType.FOURPLEX.value == "fourplex"
