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
    must: list[str] = field(default_factory=lambda: ["area", "max_price"])
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
