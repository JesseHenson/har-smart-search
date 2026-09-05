"""Comparable selection and valuation.

Every number produced here carries the count of evidence behind it. A
valuation with no comps is not a small number, it is no number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import asin, cos, radians, sin, sqrt

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
