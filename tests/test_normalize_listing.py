from datetime import date

from har_search.core.models import DuplexScope, PropertyType
from har_search.core.normalize import normalize_listing, normalize_sale

GOOD_ROW = {
    "listingId": "L1",
    "address": "5519 Lynngate Dr",
    "city": "Spring",
    "zip": "77373",
    "subdivision": "Greengate Place Sec 06",
    "latitude": 30.036156,
    "longitude": -95.342447,
    "price": 215000,
    "pricePerSqft": 142.38,
    "beds": 3,
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
    "mlsNumber": "11111111",
    "schools": {
        "E": {"rating_letter": "D"},
        "M": {"rating_letter": "D"},
        "S": {"rating_letter": "F"},
    },
    "taxInfo": {"tax_rate": 2.47421},
}


def test_normalize_listing_maps_every_field():
    result = normalize_listing(GOOD_ROW)
    listing = result.listing
    assert result.exclusion is None
    assert listing.price == 215_000
    assert listing.beds == 3
    assert listing.garage.spaces == 2
    assert listing.hoa.monthly_usd > 0
    assert listing.lot_sqft == 6_600
    assert listing.property_type is PropertyType.SINGLE_FAMILY
    assert listing.appraisal.low == 205_000
    assert listing.tax_rate == 2.47421


def test_school_rating_averages_available_levels():
    listing = normalize_listing(GOOD_ROW).listing
    # D=0.35, D=0.35, F=0.0 -> 0.2333
    assert 0.23 < listing.school_rating < 0.24


def test_lease_records_are_excluded():
    """Six of 25 'sold' rows in recon were leases at $2,500 with status Rented."""
    row = dict(GOOD_ROW, propertyType="Single Family", status="Rented", price=2500)
    result = normalize_listing(row)
    assert result.listing is None
    assert result.exclusion == "lease"


def test_sale_priced_below_floor_is_excluded():
    """A $1,325 for-sale duplex is a data error, not a bargain."""
    row = dict(GOOD_ROW, price=1325)
    result = normalize_listing(row)
    assert result.listing is None
    assert result.exclusion == "price_below_floor"


def test_implausible_bedroom_count_becomes_unknown_and_is_flagged():
    """2322 Shadow Glen reported 10 bedrooms on 4,507 sqft."""
    row = dict(GOOD_ROW, beds=10, sqft=4507)
    listing = normalize_listing(row).listing
    assert listing.beds is None
    assert "suspect_beds" in listing.flags


def test_multifamily_zero_beds_becomes_unknown_not_zero():
    """Every duplex in recon reported beds=0, garage=null, HOA=null."""
    row = dict(
        GOOD_ROW,
        propertyType="Multi-Family - Duplex",
        address="5013 Longmeadow St A/b",
        beds=0,
        bathsFull=0,
        garage=None,
        maintenanceFee=None,
        price=579900,
    )
    listing = normalize_listing(row).listing
    assert listing.beds is None
    assert listing.baths_full is None
    assert listing.garage is None
    assert listing.hoa is None
    assert listing.property_type is PropertyType.DUPLEX
    assert listing.duplex_scope is DuplexScope.WHOLE


def test_zero_lot_is_unknown():
    row = dict(GOOD_ROW, lotSize="0 sqft")
    assert normalize_listing(row).listing.lot_sqft is None


def test_normalize_sale_reads_sold_fields():
    raw = {
        "mlsNumber": "22222222",
        "address": "27318 Pendleton Trace Dr",
        "city": "Spring",
        "zip": "77386",
        "subdivision": "Harmony",
        "latitude": 30.09936,
        "longitude": -95.380801,
        "price": 470000,
        "soldPrice": 460000,
        "soldDate": "2026-08-27",
        "soldPricePerSqft": 147.91,
        "sqft": 3110,
        "beds": 4,
        "bathsFull": 3,
        "yearBuilt": 2014,
        "lotSize": "6,534 sqft",
        "propertyType": "Single-Family",
        "status": "Sold",
    }
    sale = normalize_sale(raw)
    assert sale.sold_price == 460_000
    assert sale.list_price == 470_000
    assert sale.sold_date == date(2026, 8, 27)
    assert sale.lot_sqft == 6_534


def test_normalize_sale_rejects_rentals():
    raw = {
        "mlsNumber": "33333333",
        "soldPrice": 4000,
        "soldDate": "2026-09-01",
        "status": "Rented",
        "propertyType": "Single Family",
    }
    assert normalize_sale(raw) is None
