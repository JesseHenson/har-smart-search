"""Raw vendor fields into typed values.

Contract: None means unknown. Unknown never becomes zero or a default.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from har_search.core.models import DuplexScope, GarageInfo, HOA, Listing, MoneyRange, NormalizeResult, PropertyType, Sale

SQFT_PER_ACRE = 43_560

_GARAGE_RE = re.compile(r"^\s*(\d+)\s+(attached|detached)?", re.IGNORECASE)
_MONEY_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)\s*(Annually|Monthly)?", re.IGNORECASE)
_ABBREV_RE = re.compile(r"^\$?\s*([\d.]+)\s*([KMB])\s*$", re.IGNORECASE)
_LOT_SQFT_RE = re.compile(r"^\s*([\d,]+)\s*sqft\s*$", re.IGNORECASE)
_LOT_ACRE_RE = re.compile(r"^\s*([\d.,]+)\s*acre", re.IGNORECASE)
_UNIT_RE = re.compile(r"\b([a-z])\s*[/-]\s*([a-z])\b", re.IGNORECASE)

_LETTER_SCORES = {"A": 1.0, "B": 0.8, "C": 0.6, "D": 0.35, "F": 0.0}

_TYPE_MAP = [
    ("multi-family - duplex", PropertyType.DUPLEX),
    ("multi-family - fourplex", PropertyType.FOURPLEX),
    ("multi-family", PropertyType.MULTI_FAMILY),
    ("townhouse/condo", PropertyType.TOWNHOUSE_CONDO),
    ("mid/hi-rise condo", PropertyType.TOWNHOUSE_CONDO),
    ("single-family", PropertyType.SINGLE_FAMILY),
    ("single family", PropertyType.SINGLE_FAMILY),
    ("lots", PropertyType.LOTS),
    ("country homes/acreage", PropertyType.LOTS),
]


def parse_garage(raw: str | None) -> GarageInfo | None:
    if not raw:
        return None
    match = _GARAGE_RE.match(raw)
    if not match:
        return None
    spaces = int(match.group(1))
    attachment = match.group(2)
    attached = None if attachment is None else attachment.lower() == "attached"
    tags = tuple(
        part.strip().lower()
        for part in raw.split(",")[1:]
        if part.strip()
    )
    return GarageInfo(spaces=spaces, attached=attached, tags=tags)


def parse_hoa(raw: str | None) -> HOA | None:
    if not raw:
        return None
    match = _MONEY_RE.search(raw)
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))
    period = (match.group(2) or "monthly").lower()
    monthly = amount / 12 if period == "annually" else amount
    return HOA(monthly_usd=monthly)


def parse_lot(raw: str | None) -> int | None:
    if not raw:
        return None
    sqft_match = _LOT_SQFT_RE.match(raw)
    if sqft_match:
        value = int(sqft_match.group(1).replace(",", ""))
        return value or None
    acre_match = _LOT_ACRE_RE.match(raw)
    if acre_match:
        acres = float(acre_match.group(1).replace(",", ""))
        value = int(round(acres * SQFT_PER_ACRE))
        return value or None
    return None


def parse_money_abbrev(raw: str | None) -> MoneyRange | None:
    """'$1.0M' could be anything from 1,000,000 to 1,049,999. Keep the range."""
    if not raw:
        return None
    match = _ABBREV_RE.match(raw.strip())
    if not match:
        # Fallback for non-abbreviated formats like "$425,000.00" or "$425,000"
        # Strip currency symbols, whitespace, and thousands separators, but keep decimal point
        cleaned = re.sub(r"[$\s,]", "", raw.strip())
        if not cleaned:
            return None
        try:
            exact = int(round(float(cleaned)))
        except ValueError:
            # Invalid number (multiple decimals, garbage, etc.)
            return None
        return MoneyRange(low=exact, high=exact)
    number, suffix = match.group(1), match.group(2).upper()
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
    decimals = len(number.split(".")[1]) if "." in number else 0
    low = int(round(float(number) * multiplier))
    step = multiplier // (10 ** decimals) if decimals else multiplier
    return MoneyRange(low=low, high=low + step - 1)


def canon_property_type(raw: str | None) -> tuple[PropertyType | None, bool]:
    """Return (canonical type, is_lease).

    HAR spells the sale record 'Single-Family' and the lease record
    'Single Family'. A hyphen is the only difference, so it is decided here
    and nowhere else.
    """
    if not raw:
        return (None, False)
    lowered = raw.strip().lower()
    is_lease = lowered == "single family"
    for needle, canonical in _TYPE_MAP:
        if lowered.startswith(needle):
            return (canonical, is_lease)
    return (PropertyType.OTHER, is_lease)


def parse_unit_designator(address: str | None) -> DuplexScope:
    """'5013 Longmeadow St A/b' means both sides are being sold."""
    if not address:
        return DuplexScope.UNKNOWN
    match = _UNIT_RE.search(address)
    if match and match.group(1).lower() != match.group(2).lower():
        return DuplexScope.WHOLE
    return DuplexScope.UNKNOWN


def letter_to_score(letter: str | None) -> float | None:
    if not letter:
        return None
    return _LETTER_SCORES.get(letter.strip().upper())


SALE_PRICE_FLOOR = 10_000
MAX_PLAUSIBLE_BEDS = 8
BEDS_PLAUSIBILITY_SQFT = 5_000


def _positive_or_none(value) -> int | None:
    """Zero from this vendor means 'not populated', never 'actually zero'."""
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number or None


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _school_rating(schools: dict | None) -> float | None:
    if not schools:
        return None
    scores = [
        score
        for level in ("E", "M", "S")
        if (score := letter_to_score((schools.get(level) or {}).get("rating_letter")))
        is not None
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_listing(raw: dict) -> NormalizeResult:
    property_type, is_lease = canon_property_type(raw.get("propertyType"))
    status = raw.get("status")

    if is_lease or (status or "").strip().lower() == "rented":
        return NormalizeResult(listing=None, exclusion="lease")

    price = _positive_or_none(raw.get("price"))
    if price is not None and price < SALE_PRICE_FLOOR:
        return NormalizeResult(listing=None, exclusion="price_below_floor")

    flags: list[str] = []
    beds = _positive_or_none(raw.get("beds"))
    sqft = _positive_or_none(raw.get("sqft"))
    if beds is not None and beds > MAX_PLAUSIBLE_BEDS and (
        sqft is None or sqft < BEDS_PLAUSIBILITY_SQFT
    ):
        beds = None
        flags.append("suspect_beds")

    address = raw.get("address")
    listing = Listing(
        listing_id=str(raw.get("listingId") or raw.get("harId") or raw.get("mlsNumber")),
        address=address,
        city=raw.get("city"),
        zip=raw.get("zip"),
        subdivision=raw.get("subdivision"),
        lat=_float_or_none(raw.get("latitude")),
        lon=_float_or_none(raw.get("longitude")),
        price=price,
        price_per_sqft=_float_or_none(raw.get("pricePerSqft")),
        beds=beds,
        baths_full=_positive_or_none(raw.get("bathsFull")),
        baths_half=_positive_or_none(raw.get("bathsHalf")),
        sqft=sqft,
        lot_sqft=parse_lot(raw.get("lotSize")),
        year_built=_positive_or_none(raw.get("yearBuilt")),
        garage=parse_garage(raw.get("garage")),
        hoa=parse_hoa(raw.get("maintenanceFee")),
        property_type=property_type,
        duplex_scope=parse_unit_designator(address),
        status=status,
        days_on_market=_positive_or_none(raw.get("daysOnMarket")),
        school_rating=_school_rating(raw.get("schools")),
        tax_rate=_float_or_none((raw.get("taxInfo") or {}).get("tax_rate")),
        appraisal=parse_money_abbrev(raw.get("avmValue")),
        mls_number=raw.get("mlsNumber"),
        url=raw.get("url"),
        flags=tuple(flags),
        raw=raw,
    )
    return NormalizeResult(listing=listing, exclusion=None)


def normalize_sale(raw: dict) -> Sale | None:
    property_type, is_lease = canon_property_type(raw.get("propertyType"))
    if is_lease or (raw.get("status") or "").strip().lower() == "rented":
        return None

    sold_price = _positive_or_none(raw.get("soldPrice"))
    sold_date = _parse_date(raw.get("soldDate"))
    if sold_price is None or sold_date is None or sold_price < SALE_PRICE_FLOOR:
        return None

    return Sale(
        mls_number=str(raw.get("mlsNumber")),
        sold_price=sold_price,
        sold_date=sold_date,
        address=raw.get("address"),
        city=raw.get("city"),
        zip=raw.get("zip"),
        subdivision=raw.get("subdivision"),
        lat=_float_or_none(raw.get("latitude")),
        lon=_float_or_none(raw.get("longitude")),
        list_price=_positive_or_none(raw.get("price")),
        sold_price_per_sqft=_float_or_none(raw.get("soldPricePerSqft")),
        sqft=_positive_or_none(raw.get("sqft")),
        beds=_positive_or_none(raw.get("beds")),
        baths_full=_positive_or_none(raw.get("bathsFull")),
        year_built=_positive_or_none(raw.get("yearBuilt")),
        lot_sqft=parse_lot(raw.get("lotSize")),
        property_type=property_type,
    )
