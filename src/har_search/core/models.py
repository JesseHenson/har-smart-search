"""Shared data model. No logic lives here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Literal


class PropertyType(str, Enum):
    SINGLE_FAMILY = "single_family"
    TOWNHOUSE_CONDO = "townhouse_condo"
    DUPLEX = "duplex"
    FOURPLEX = "fourplex"
    MULTI_FAMILY = "multi_family"
    LOTS = "lots"
    OTHER = "other"


class DuplexScope(str, Enum):
    WHOLE = "whole"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GarageInfo:
    spaces: int
    attached: bool | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class HOA:
    monthly_usd: float


@dataclass(frozen=True)
class MoneyRange:
    low: int
    high: int

    @property
    def midpoint(self) -> int:
        return (self.low + self.high) // 2


@dataclass
class Listing:
    listing_id: str
    address: str | None = None
    city: str | None = None
    zip: str | None = None
    subdivision: str | None = None
    lat: float | None = None
    lon: float | None = None
    price: int | None = None
    price_per_sqft: float | None = None
    beds: int | None = None
    baths_full: int | None = None
    baths_half: int | None = None
    sqft: int | None = None
    lot_sqft: int | None = None
    year_built: int | None = None
    garage: GarageInfo | None = None
    hoa: HOA | None = None
    property_type: PropertyType | None = None
    duplex_scope: DuplexScope = DuplexScope.UNKNOWN
    status: str | None = None
    days_on_market: int | None = None
    school_rating: float | None = None
    tax_rate: float | None = None
    appraisal: MoneyRange | None = None
    mls_number: str | None = None
    url: str | None = None
    flags: tuple[str, ...] = ()
    raw: dict = field(default_factory=dict)


@dataclass
class Sale:
    mls_number: str
    sold_price: int
    sold_date: date
    address: str | None = None
    city: str | None = None
    zip: str | None = None
    subdivision: str | None = None
    lat: float | None = None
    lon: float | None = None
    list_price: int | None = None
    sold_price_per_sqft: float | None = None
    sqft: int | None = None
    beds: int | None = None
    baths_full: int | None = None
    year_built: int | None = None
    lot_sqft: int | None = None
    property_type: PropertyType | None = None
    flags: tuple[str, ...] = ()


@dataclass
class Criteria:
    area: str
    beds: int | None = None
    baths: int | None = None
    garage_spaces: int | None = None
    sqft: int | None = None
    max_price: int | None = None
    max_price_per_sqft: float | None = None
    property_types: list[str] | None = None
    no_hoa: bool | None = None
    max_age_years: int | None = None
    min_school_rating: str | None = None
    # Radius search. `area` still names the net the vendor fetches — the
    # actor takes a location string and nothing geographic — while these two
    # decide what survives. `center_address` is geocoded by the caller and
    # handed to scoring as the centroid; `radius_miles` turns the geo decay
    # into a hard edge, so a listing past it fails the `area` must outright
    # rather than merely ranking low.
    center_address: str | None = None
    radius_miles: float | None = None
    # Location is the only hard default. Budget is deliberately SOFT: spec 5.2
    # advertises graceful decay to +50% over budget as a rankable outcome
    # ("then you may show me some houses above $200,000, if the search result
    # is not there for below"), and a `must` on max_price deletes that tail
    # outright at +16% over. Any parameter can still be made hard by naming it
    # in `must`.
    must: list[str] = field(default_factory=lambda: ["area"])
    weights: dict[str, float] | None = None


@dataclass(frozen=True)
class ParamScore:
    name: str
    score: float
    weight: float
    known: bool
    detail: str


@dataclass
class ScoredListing:
    listing: Listing
    score: float
    coverage: float
    params: list[ParamScore]
    why: str


@dataclass(frozen=True)
class Comp:
    id: str
    price: int
    sqft: int
    price_per_sqft: float
    basis: Literal["sold", "asking"]
    beds: int | None = None
    baths_full: int | None = None
    year_built: int | None = None
    lot_sqft: int | None = None
    distance_miles: float | None = None
    sold_date: date | None = None
    subdivision: str | None = None


@dataclass
class Valuation:
    comp_estimate: int | None = None
    comp_count: int = 0
    comp_ids: list[str] = field(default_factory=list)
    comp_basis: Literal["sold", "asking", "none"] = "none"
    confidence: Literal["high", "medium", "low", "insufficient"] = "insufficient"
    appraisal_district: MoneyRange | None = None
    subdivision_list_to_sold: float | None = None
    delta_pct: float | None = None
    spread_flag: Literal["clustered", "scattered", "single_source"] = "single_source"


@dataclass(frozen=True)
class ListingChange:
    listing_id: str
    change_type: Literal["NEW", "PRICE_CUT", "PRICE_UP", "GONE", "UNCHANGED"]
    old_price: int | None = None
    new_price: int | None = None
    address: str | None = None


@dataclass(frozen=True)
class NormalizeResult:
    listing: Listing | None
    exclusion: str | None = None


@dataclass(frozen=True)
class NormalizeSaleResult:
    """`NormalizeResult`'s shape for sold rows.

    Sold rows are excluded for the same reasons for-sale rows are, and the
    reason matters just as much: six leases arriving inside a *sold* query is
    the most dangerous data defect in this domain, and a bare `None` return
    cannot say so.
    """

    sale: Sale | None
    exclusion: str | None = None
