"""Comparable selection and valuation.

Every number produced here carries the count of evidence behind it. A
valuation with no comps is not a small number, it is no number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import asin, cos, radians, sin, sqrt
from statistics import median

from har_search.core.models import Comp, Listing, Sale, Valuation

_EARTH_RADIUS_MILES = 3958.8

MIN_COMPS_FOR_ESTIMATE = 3
TARGET_COMPS = 5


@dataclass(frozen=True)
class Tier:
    name: str
    max_miles: float | None
    max_days: int | None
    sqft_tolerance: float
    basis: str


TIERS = [
    Tier("subdivision", None, 180, 0.25, "sold"),
    Tier("one_mile", 1.0, 180, 0.25, "sold"),
    Tier("two_miles", 2.0, 365, 0.35, "sold"),
    Tier("active", 2.0, None, 0.35, "asking"),
]


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_MILES * asin(sqrt(a))


def _distance(subject: Listing, lat: float | None, lon: float | None) -> float | None:
    if None in (subject.lat, subject.lon, lat, lon):
        return None
    return haversine_miles(subject.lat, subject.lon, lat, lon)


def _size_ok(subject_sqft: int | None, other_sqft: int | None, tolerance: float) -> bool:
    if not subject_sqft or not other_sqft:
        return False
    return abs(other_sqft - subject_sqft) / subject_sqft <= tolerance


def comps_from_sales(subject: Listing, sales: list[Sale], today: date) -> list[Comp]:
    comps = []
    for sale in sales:
        if not sale.sqft or not sale.sold_price:
            continue
        comps.append(
            Comp(
                id=sale.mls_number,
                price=sale.sold_price,
                sqft=sale.sqft,
                price_per_sqft=sale.sold_price_per_sqft or sale.sold_price / sale.sqft,
                basis="sold",
                beds=sale.beds,
                baths_full=sale.baths_full,
                year_built=sale.year_built,
                lot_sqft=sale.lot_sqft,
                distance_miles=_distance(subject, sale.lat, sale.lon),
                sold_date=sale.sold_date,
                subdivision=sale.subdivision,
            )
        )
    return comps


def comps_from_listings(subject: Listing, listings: list[Listing]) -> list[Comp]:
    comps = []
    for listing in listings:
        if listing.listing_id == subject.listing_id:
            continue
        if not listing.sqft or not listing.price:
            continue
        comps.append(
            Comp(
                id=listing.listing_id,
                price=listing.price,
                sqft=listing.sqft,
                price_per_sqft=listing.price_per_sqft or listing.price / listing.sqft,
                basis="asking",
                beds=listing.beds,
                baths_full=listing.baths_full,
                year_built=listing.year_built,
                lot_sqft=listing.lot_sqft,
                distance_miles=_distance(subject, listing.lat, listing.lon),
                sold_date=None,
                subdivision=listing.subdivision,
            )
        )
    return comps


def _tier_matches(subject: Listing, comp: Comp, tier: Tier, today: date) -> bool:
    if not _size_ok(subject.sqft, comp.sqft, tier.sqft_tolerance):
        return False
    if tier.max_days is not None:
        if comp.sold_date is None:
            return False
        if comp.sold_date < today - timedelta(days=tier.max_days):
            return False
    if tier.name == "subdivision":
        return bool(
            subject.subdivision
            and comp.subdivision
            and subject.subdivision.lower() == comp.subdivision.lower()
        )
    if tier.max_miles is not None:
        return comp.distance_miles is not None and comp.distance_miles <= tier.max_miles
    return True


def _same_type(subject: Listing, sales: list[Sale]) -> list[Sale]:
    if subject.property_type is None:
        return sales
    return [s for s in sales if s.property_type == subject.property_type]


def _same_type_listings(subject: Listing, listings: list[Listing]) -> list[Listing]:
    if subject.property_type is None:
        return listings
    return [l for l in listings if l.property_type == subject.property_type]


def select_comps(
    subject: Listing,
    sales: list[Sale],
    active: list[Listing],
    today: date,
) -> tuple[list[Comp], str]:
    """Walk the tiers in order; stop at the first that reaches TARGET_COMPS.

    If every tier falls short, return the widest non-empty result and let
    the confidence label describe how thin it is.
    """
    sold_comps = comps_from_sales(subject, _same_type(subject, sales), today)
    active_comps = comps_from_listings(subject, _same_type_listings(subject, active))

    best: list[Comp] = []
    best_basis = "none"
    for tier in TIERS:
        pool = active_comps if tier.basis == "asking" else sold_comps
        matched = [c for c in pool if _tier_matches(subject, c, tier, today)]
        if len(matched) > len(best):
            best, best_basis = matched, tier.basis
        if len(matched) >= TARGET_COMPS:
            return matched, tier.basis
    return best, best_basis if best else "none"


ADJUSTMENTS = {
    "beds": (0.03, 0.09),
    "baths": (0.025, 0.075),
    "age": (0.0035, 0.10),
    "lot": (0.0002, 0.05),
}
SPREAD_TOLERANCE = 0.10


def trimmed_median(values: list[float]) -> float:
    """Drop the extremes before taking the median.

    This is what keeps one bad source row from moving a whole
    neighbourhood's estimate.
    """
    ordered = sorted(values)
    if len(ordered) >= 5:
        drop = max(1, int(len(ordered) * 0.10))
        ordered = ordered[drop:-drop]
    return float(median(ordered))


def confidence_label(n: int) -> str:
    if n >= 8:
        return "high"
    if n >= 5:
        return "medium"
    if n >= MIN_COMPS_FOR_ESTIMATE:
        return "low"
    return "insufficient"


def _clamp(value: float, cap: float) -> float:
    return max(-cap, min(cap, value))


def _median_of(values: list) -> float | None:
    present = [v for v in values if v is not None]
    return float(median(present)) if present else None


def _adjustment_factor(subject: Listing, comps: list[Comp]) -> float:
    factor = 0.0

    comp_beds = _median_of([c.beds for c in comps])
    if subject.beds is not None and comp_beds is not None:
        rate, cap = ADJUSTMENTS["beds"]
        factor += _clamp((subject.beds - comp_beds) * rate, cap)

    comp_baths = _median_of([c.baths_full for c in comps])
    if subject.baths_full is not None and comp_baths is not None:
        rate, cap = ADJUSTMENTS["baths"]
        factor += _clamp((subject.baths_full - comp_baths) * rate, cap)

    comp_year = _median_of([c.year_built for c in comps])
    if subject.year_built is not None and comp_year is not None:
        rate, cap = ADJUSTMENTS["age"]
        years_older = comp_year - subject.year_built
        factor += _clamp(-years_older * rate, cap)

    comp_lot = _median_of([c.lot_sqft for c in comps])
    if subject.lot_sqft is not None and comp_lot:
        rate, cap = ADJUSTMENTS["lot"]
        pct_diff = (subject.lot_sqft - comp_lot) / comp_lot * 100
        factor += _clamp(pct_diff * rate, cap)

    return factor


def subdivision_list_to_sold(sales: list[Sale]) -> float | None:
    ratios = [
        sale.sold_price / sale.list_price
        for sale in sales
        if sale.list_price and sale.sold_price
    ]
    return float(median(ratios)) if ratios else None


def _spread_flag(estimate: int | None, appraisal) -> str:
    if estimate is None or appraisal is None:
        return "single_source"
    difference = abs(appraisal.midpoint - estimate) / estimate
    return "clustered" if difference <= SPREAD_TOLERANCE else "scattered"


def value_listing(
    subject: Listing,
    sales: list[Sale],
    active: list[Listing],
    today: date,
) -> Valuation:
    comps, basis = select_comps(subject, sales, active, today)

    valuation = Valuation(
        comp_count=len(comps),
        comp_ids=[c.id for c in comps],
        comp_basis=basis if comps else "none",
        confidence=confidence_label(len(comps)),
        appraisal_district=subject.appraisal,
        subdivision_list_to_sold=subdivision_list_to_sold(
            [s for s in sales if s.subdivision and s.subdivision == subject.subdivision]
        ),
    )

    if len(comps) < MIN_COMPS_FOR_ESTIMATE or not subject.sqft:
        valuation.spread_flag = "single_source"
        return valuation

    base = trimmed_median([c.price_per_sqft for c in comps]) * subject.sqft
    estimate = int(round(base * (1 + _adjustment_factor(subject, comps))))
    valuation.comp_estimate = estimate

    if subject.price:
        valuation.delta_pct = (subject.price - estimate) / estimate

    valuation.spread_flag = _spread_flag(estimate, subject.appraisal)
    return valuation
