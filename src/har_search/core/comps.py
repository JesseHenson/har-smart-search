"""Comparable selection and valuation.

Every number produced here carries the count of evidence behind it. A
valuation with no comps is not a small number, it is no number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import asin, cos, radians, sin, sqrt
from statistics import mean, median

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


# Ordered widest-last: each tier reaches further than the one above it, and
# selection stops as soon as the accumulated pool is deep enough. `four_miles`
# exists because measurement demanded it — across 103 real Spring sold rows,
# a 2-mile ceiling left four of five test listings with no estimate, while
# four miles doubled the number reaching a usable set. Four miles is still one
# suburban market; past that, comps cross school districts and price bands, so
# the tier list stops there rather than chasing coverage into another city.
TIERS = [
    Tier("subdivision", None, 180, 0.25, "sold"),
    Tier("one_mile", 1.0, 180, 0.25, "sold"),
    Tier("two_miles", 2.0, 365, 0.35, "sold"),
    Tier("four_miles", 4.0, 365, 0.35, "sold"),
    Tier("active", 2.0, None, 0.35, "asking"),
]

# Past this, a comp is still usable but the estimate should not claim to be
# well-evidenced. See `confidence_label`.
LOCAL_MILES = 2.0


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


def _same_subdivision(left: str | None, right: str | None) -> bool:
    """The single definition of "same subdivision".

    Vendor subdivision strings are free text. Tier matching normalized case
    while the list-to-sold filter compared with `==`, so six comps could agree
    they shared the subject's subdivision while the list-to-sold ratio — the
    most actionable number the tool produces — returned None on a
    capitalization difference alone.
    """
    if not left or not right:
        return False
    return left.strip().lower() == right.strip().lower()


def _tier_matches(subject: Listing, comp: Comp, tier: Tier, today: date) -> bool:
    if not _size_ok(subject.sqft, comp.sqft, tier.sqft_tolerance):
        return False
    if tier.max_days is not None:
        if comp.sold_date is None:
            return False
        if comp.sold_date < today - timedelta(days=tier.max_days):
            return False
    if tier.name == "subdivision":
        return _same_subdivision(subject.subdivision, comp.subdivision)
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


def _basis_of(comps: dict[str, Comp]) -> str:
    """The weakest basis present wins.

    The label must never overstate the evidence: an accumulated set holding
    four closed sales and two active listings is not a "sold" valuation, so
    one asking comp downgrades the whole set to asking.
    """
    if not comps:
        return "none"
    if any(c.basis == "asking" for c in comps.values()):
        return "asking"
    return "sold"


def select_comps(
    subject: Listing,
    sales: list[Sale],
    active: list[Listing],
    today: date,
) -> tuple[list[Comp], str]:
    """Walk the tiers in order, ACCUMULATING candidates (spec 6.1).

    Stop at the first tier where the accumulated pool reaches TARGET_COMPS. If
    every tier is exhausted below that, return everything accumulated and let
    the confidence label describe how thin it is.

    The tiers are not nested, so recomputing each independently and keeping
    the single largest one discards real evidence: a same-subdivision sale
    with no coordinates matches tier 1 and fails tiers 2-4, and vanishes the
    moment a later tier wins. In a product whose binding constraint is comp
    density, that is the difference between "medium" and "low" confidence on
    the same data.
    """
    sold_comps = comps_from_sales(subject, _same_type(subject, sales), today)
    active_comps = comps_from_listings(subject, _same_type_listings(subject, active))

    # dict rather than set: keyed on comp id to deduplicate across tiers, and
    # insertion-ordered so the closest, most recent tiers stay first.
    accumulated: dict[str, Comp] = {}
    for tier in TIERS:
        pool = active_comps if tier.basis == "asking" else sold_comps
        for comp in pool:
            if comp.id not in accumulated and _tier_matches(subject, comp, tier, today):
                accumulated[comp.id] = comp
        if len(accumulated) >= TARGET_COMPS:
            break

    return list(accumulated.values()), _basis_of(accumulated)


ADJUSTMENTS = {
    "beds": (0.03, 0.09),
    "baths": (0.025, 0.075),
    "age": (0.0035, 0.10),
    "lot": (0.0002, 0.05),
}
SPREAD_TOLERANCE = 0.10
AGGREGATE_ADJUSTMENT_CAP = 0.15


def trimmed_mean(values: list[float]) -> float:
    """Return the mean of `values` after dropping the top and bottom 10%.

    Why a mean over a median: Texas is a non-disclosure state, so a realistic
    comp set is thin -- five to eight sales is typical. A median of six values
    consults exactly two of them; this trimmed mean consults four. On thin
    evidence, using more of it is worth more than the median's extra
    robustness, and it makes the trim load-bearing rather than decorative --
    dropping the top and bottom 10% before averaging is what neutralizes
    source errors like the 10-bedroom, 4,507 sqft record found in recon,
    which a plain mean would not resist.

    Trade-off: a trimmed mean is less robust than a median to *multiple*
    outliers on the same side. With this trim rule, n < 20 drops exactly one
    value from each end, so one bad high (or low) comp is fully excluded, but
    two bad comps on the same side leave one of them in the retained set,
    skewing the average in a way that would not move a median. This function
    does not defend against that case on its own -- the sanity guards in
    `core/normalize.py` (the sale-price floor, the implausible-bedroom check)
    and the sqft/type constraints in comp selection above are what keep most
    such rows out of the pool before they ever reach here.
    """
    ordered = sorted(values)
    if len(ordered) >= 5:
        drop = max(1, int(len(ordered) * 0.10))
        ordered = ordered[drop:-drop]
    return float(mean(ordered))


def confidence_label(n: int, max_distance_miles: float | None = None) -> str:
    """Count sets the label; distance can only lower it.

    Count alone would let the wider `four_miles` tier launder distant sales
    into a "high" estimate — the reader sees the same word for eight sales
    on the subject's street and eight sales three miles away. Capping at
    "low" once the set reaches past LOCAL_MILES keeps the widened radius
    honest: still an estimate, visibly a weaker one.
    """
    if n < MIN_COMPS_FOR_ESTIMATE:
        return "insufficient"
    if max_distance_miles is not None and max_distance_miles > LOCAL_MILES:
        return "low"
    if n >= 8:
        return "high"
    if n >= 5:
        return "medium"
    return "low"


def _max_distance(comps: list) -> float | None:
    """Distance of the furthest comp, or None when none carry coordinates."""
    known = [c.distance_miles for c in comps if c.distance_miles is not None]
    return max(known) if known else None


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

    return _clamp(factor, AGGREGATE_ADJUSTMENT_CAP)


def subdivision_list_to_sold(sales: list[Sale], subdivision: str | None) -> float | None:
    """Median sold/list ratio across one subdivision's closed sales.

    `subdivision` is required, and an unknown one yields None rather than a
    ratio over every sale in range — this number is labelled "subdivision
    list-to-sold" on screen and must not quietly become an area-wide figure.

    The filter lives here, behind `_same_subdivision`, rather than at the call
    site: the call site used `==` while tier matching used `.lower()`, and the
    two disagreeing is exactly how this returned None on capitalization alone.
    """
    if not subdivision:
        return None
    sales = [s for s in sales if _same_subdivision(s.subdivision, subdivision)]
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
        confidence=confidence_label(
            len(comps),
            max_distance_miles=_max_distance(comps),
        ),
        appraisal_district=subject.appraisal,
        subdivision_list_to_sold=subdivision_list_to_sold(sales, subject.subdivision),
    )

    if len(comps) < MIN_COMPS_FOR_ESTIMATE or not subject.sqft:
        valuation.spread_flag = "single_source"
        return valuation

    base = trimmed_mean([c.price_per_sqft for c in comps]) * subject.sqft
    estimate = int(round(base * (1 + _adjustment_factor(subject, comps))))
    valuation.comp_estimate = estimate

    if subject.price:
        valuation.delta_pct = (subject.price - estimate) / estimate

    valuation.spread_flag = _spread_flag(estimate, subject.appraisal)
    return valuation
