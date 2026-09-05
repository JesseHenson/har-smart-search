# HAR Smart Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a demo-ready MCP bundle that searches HAR listings by loose criteria, ranks them by similarity, and attaches a comps-derived value KPI to every result, with a local dashboard and real week-over-week diffing.

**Architecture:** A Python MCP server (FastMCP) wraps four pure-logic modules — normalize, scoring, comps, diff — that never touch the network. A swappable source adapter fetches raw rows from an Apify actor. SQLite stores per-run snapshots plus a permanently accumulating table of closed sales. A Starlette app serves the dashboard on localhost.

**Tech Stack:** Python 3.11+, uv, FastMCP, Starlette, Jinja2, pytest, SQLite (stdlib `sqlite3`), `httpx` for the Apify REST API.

**Spec:** `docs/superpowers/specs/2026-09-04-har-smart-search-design.md`

## Global Constraints

- Python 3.11 or newer. Use `uv` for all dependency and environment management — never `pip`, `poetry`, `virtualenv`, or `conda`.
- The project root is `/Users/jessehenson/Development/HAR Real Estate Work`. **This path contains spaces — quote it in every shell command.**
- `None` means unknown. Unknown values must never be coerced to `0`, `False`, or a default. This rule governs `core/normalize.py`, `core/scoring.py`, and `core/comps.py`.
- No module under `src/har_search/core/` may import `httpx`, `sqlite3`, or anything from `sources/`, `store/`, `server/`, or `web/`. Core is pure logic and must be testable with no I/O.
- No network calls in the test suite. Source-adapter tests run against recorded JSON fixtures.
- Money is stored as integer USD. Ratios and scores are floats in `[0, 1]`.
- Every scoring constant in the spec (`τ_over = 2.4`, `τ_under = 0.82`, ceiling `τ = 0.16`, geo `τ = 3.0`) is a binding requirement, and the score tables in spec §5.2 are the acceptance tests.
- Commit after every task with a conventional-commit message.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | uv project definition, dependencies, pytest config |
| `manifest.json` | MCPB bundle manifest and user config |
| `src/har_search/core/models.py` | Every dataclass and enum. No logic. |
| `src/har_search/core/normalize.py` | Field parsers and sanity guards; raw dict → `Listing` |
| `src/har_search/core/scoring.py` | Similarity scoring primitives and aggregation |
| `src/har_search/core/comps.py` | Comparable selection, valuation, confidence |
| `src/har_search/core/diff.py` | Snapshot comparison |
| `src/har_search/sources/base.py` | `ListingSource` protocol |
| `src/har_search/sources/apify_memo23.py` | Apify actor adapter |
| `src/har_search/store/schema.sql` | Table definitions |
| `src/har_search/store/db.py` | SQLite access layer |
| `src/har_search/server/__main__.py` | FastMCP entrypoint and tool definitions |
| `src/har_search/web/app.py` | Starlette dashboard routes |
| `src/har_search/web/templates/` | Jinja2 templates |
| `tests/fixtures/` | Recorded Apify JSON from the three live recon runs |

---

## Task 1: Project scaffolding and the shared data model

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/har_search/__init__.py`, `src/har_search/core/__init__.py`, `src/har_search/core/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing
- Produces: `PropertyType`, `DuplexScope`, `GarageInfo`, `HOA`, `MoneyRange`, `Listing`, `Sale`, `Criteria`, `ParamScore`, `ScoredListing`, `Comp`, `Valuation`, `ListingChange`, `NormalizeResult` — every later task imports from `har_search.core.models`.

- [ ] **Step 1: Initialise the repository and uv project**

The project directory already contains `README.md`, `RECON.md`, `meeting_saved_closed_caption.txt` and `docs/`. It is not yet a git repository.

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git init
uv init --lib --name har-search --python 3.11 .
```

If `uv init` refuses because the directory is non-empty, create `pyproject.toml` by hand with the content in Step 2 and skip the `uv init` call.

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "har-search"
version = "0.1.0"
description = "Similarity search and comps valuation over HAR listings"
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]>=1.2.0",
    "httpx>=0.27",
    "starlette>=0.37",
    "uvicorn>=0.30",
    "jinja2>=3.1",
]

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/har_search"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 3: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
*.db
dist/
build/
```

- [ ] **Step 4: Write the failing test**

Create `tests/test_models.py`:

```python
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
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'har_search'`

- [ ] **Step 6: Write `src/har_search/core/models.py`**

Create empty `src/har_search/__init__.py` and `src/har_search/core/__init__.py`, then:

```python
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
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: 6 passed

- [ ] **Step 8: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add pyproject.toml .gitignore src tests docs README.md RECON.md meeting_saved_closed_caption.txt
git commit -m "feat: scaffold har-search project and shared data model"
```

---

## Task 2: Field parsers

**Files:**
- Create: `src/har_search/core/normalize.py`
- Test: `tests/test_normalize_parsers.py`

**Interfaces:**
- Consumes: `har_search.core.models`
- Produces: `parse_garage(str|None) -> GarageInfo|None`, `parse_hoa(str|None) -> HOA|None`, `parse_lot(str|None) -> int|None`, `parse_money_abbrev(str|None) -> MoneyRange|None`, `canon_property_type(str|None) -> tuple[PropertyType|None, bool]`, `parse_unit_designator(str|None) -> DuplexScope`, `letter_to_score(str|None) -> float|None`

Every input string in these tests was observed in the live recon runs. Do not invent new shapes.

- [ ] **Step 1: Write the failing test**

Create `tests/test_normalize_parsers.py`:

```python
import pytest

from har_search.core.models import DuplexScope, PropertyType
from har_search.core.normalize import (
    canon_property_type,
    letter_to_score,
    parse_garage,
    parse_hoa,
    parse_lot,
    parse_money_abbrev,
    parse_unit_designator,
)


@pytest.mark.parametrize(
    "raw,spaces,attached",
    [
        ("2 Attached", 2, True),
        ("3 Attached ,Oversized ,Tandem", 3, True),
        ("2 Detached ,Oversized", 2, False),
        ("3 Attached", 3, True),
    ],
)
def test_parse_garage_extracts_spaces_and_attachment(raw, spaces, attached):
    garage = parse_garage(raw)
    assert garage is not None
    assert garage.spaces == spaces
    assert garage.attached is attached


def test_parse_garage_keeps_extra_tags():
    garage = parse_garage("3 Attached ,Oversized ,Tandem")
    assert garage.tags == ("oversized", "tandem")


def test_parse_garage_returns_none_for_missing():
    assert parse_garage(None) is None
    assert parse_garage("") is None


def test_parse_hoa_normalises_to_monthly():
    assert parse_hoa("$1075 Annually").monthly_usd == pytest.approx(89.583, abs=0.01)
    assert parse_hoa("$325 Monthly").monthly_usd == pytest.approx(325.0)


def test_parse_hoa_null_is_unknown_not_zero():
    """A missing fee means we do not know, never that there is no HOA."""
    assert parse_hoa(None) is None


def test_parse_lot_handles_sqft_and_acres():
    assert parse_lot("13,987 sqft") == 13_987
    assert parse_lot("1.1 acre(s)") == 47_916
    assert parse_lot("6,600 sqft") == 6_600


def test_parse_lot_treats_zero_as_unknown():
    assert parse_lot("0 sqft") is None
    assert parse_lot(None) is None


def test_parse_money_abbrev_preserves_imprecision():
    """The displayed figure is treated as truncated at its own precision,
    so the range always contains the true value."""
    rng = parse_money_abbrev("$1.0M")
    assert rng.low == 1_000_000
    assert rng.high == 1_099_999

    rng = parse_money_abbrev("$352K")
    assert rng.low == 352_000
    assert rng.high == 352_999


def test_parse_money_abbrev_returns_none_for_missing():
    assert parse_money_abbrev(None) is None


def test_canon_property_type_catches_the_hyphen_trap():
    """'Single-Family' is a sale record; 'Single Family' is a lease record."""
    assert canon_property_type("Single-Family") == (PropertyType.SINGLE_FAMILY, False)
    assert canon_property_type("Single Family") == (PropertyType.SINGLE_FAMILY, True)


def test_canon_property_type_maps_multi_family_subtypes():
    assert canon_property_type("Multi-Family - Duplex") == (PropertyType.DUPLEX, False)
    assert canon_property_type("Multi-Family - Fourplex") == (PropertyType.FOURPLEX, False)
    assert canon_property_type("Multi-Family") == (PropertyType.MULTI_FAMILY, False)
    assert canon_property_type("Multi-Family - Multiple Detached Dw") == (
        PropertyType.MULTI_FAMILY,
        False,
    )
    assert canon_property_type("Townhouse/Condo - Townhouse") == (
        PropertyType.TOWNHOUSE_CONDO,
        False,
    )
    assert canon_property_type("Lots") == (PropertyType.LOTS, False)
    assert canon_property_type(None) == (None, False)


@pytest.mark.parametrize(
    "address,scope",
    [
        ("5013 Longmeadow St A/b", DuplexScope.WHOLE),
        ("8445 Furray Rd A/b", DuplexScope.WHOLE),
        ("214 E 32nd St C-d", DuplexScope.WHOLE),
        ("5058 Mallow St A-b", DuplexScope.WHOLE),
        ("7840 Nashville Unit A/b St", DuplexScope.WHOLE),
        ("2116 Berry St", DuplexScope.UNKNOWN),
        ("3204 Napoleon St", DuplexScope.UNKNOWN),
        (None, DuplexScope.UNKNOWN),
    ],
)
def test_parse_unit_designator(address, scope):
    assert parse_unit_designator(address) is scope


def test_letter_to_score_maps_har_ratings():
    assert letter_to_score("A") == 1.0
    assert letter_to_score("B") == 0.8
    assert letter_to_score("C") == 0.6
    assert letter_to_score("D") == 0.35
    assert letter_to_score("F") == 0.0
    assert letter_to_score(None) is None
    assert letter_to_score("N/A") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_normalize_parsers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'har_search.core.normalize'`

- [ ] **Step 3: Write `src/har_search/core/normalize.py`**

```python
"""Raw vendor fields into typed values.

Contract: None means unknown. Unknown never becomes zero or a default.
"""

from __future__ import annotations

import re

from har_search.core.models import DuplexScope, GarageInfo, HOA, MoneyRange, PropertyType

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
        digits = re.sub(r"[^\d]", "", raw)
        if not digits:
            return None
        exact = int(digits)
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_normalize_parsers.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add src/har_search/core/normalize.py tests/test_normalize_parsers.py
git commit -m "feat: add field parsers for HAR vendor data"
```

---

## Task 3: Sanity guards and whole-listing normalization

**Files:**
- Modify: `src/har_search/core/normalize.py`
- Test: `tests/test_normalize_listing.py`

**Interfaces:**
- Consumes: parsers from Task 2
- Produces: `normalize_listing(raw: dict) -> NormalizeResult`, `normalize_sale(raw: dict) -> Sale | None`

Every fixture below is a real row from the recon runs.

- [ ] **Step 1: Write the failing test**

Create `tests/test_normalize_listing.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_normalize_listing.py -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_listing'`

- [ ] **Step 3: Append to `src/har_search/core/normalize.py`**

Add these imports at the top of the file alongside the existing ones:

```python
from datetime import date, datetime

from har_search.core.models import Listing, NormalizeResult, Sale
```

Then append:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/ -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add src/har_search/core/normalize.py tests/test_normalize_listing.py
git commit -m "feat: add sanity guards and listing normalization"
```

---

## Task 4: Scoring primitives

**Files:**
- Create: `src/har_search/core/scoring.py`
- Test: `tests/test_scoring_primitives.py`

**Interfaces:**
- Consumes: `har_search.core.models`
- Produces: `target_score(actual, target, tau_over, tau_under) -> float`, `ceiling_score(actual, ceiling, tau=0.16) -> float`, `geo_score(subdivision_match, miles) -> float`, `categorical_score(actual, wanted) -> float`, `TAU`, `DEFAULT_WEIGHTS`

The score tables in spec §5.2 are the requirement. These tests encode them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scoring_primitives.py`:

```python
import pytest

from har_search.core.models import PropertyType
from har_search.core.scoring import (
    DEFAULT_WEIGHTS,
    TAU,
    categorical_score,
    ceiling_score,
    geo_score,
    target_score,
)


@pytest.mark.parametrize(
    "actual,expected",
    [(3, 1.00), (4, 0.85), (5, 0.59), (2, 0.40), (1, 0.14)],
)
def test_bedroom_target_scores_match_spec_table(actual, expected):
    """Spec 5.2: a 4-bed against a 3-bed target must stay competitive."""
    tau_over, tau_under = TAU["beds"]
    assert target_score(actual, 3, tau_over, tau_under) == pytest.approx(
        expected, abs=0.01
    )


def test_target_score_is_asymmetric():
    tau_over, tau_under = TAU["beds"]
    over = target_score(4, 3, tau_over, tau_under)
    under = target_score(2, 3, tau_over, tau_under)
    assert over > under


@pytest.mark.parametrize(
    "price,expected",
    [(200_000, 1.00), (180_000, 1.00), (220_000, 0.72), (250_000, 0.29), (300_000, 0.09)],
)
def test_ceiling_scores_match_spec_table(price, expected):
    """Spec 5.2: 'show me some above $200,000 if there is nothing below'."""
    assert ceiling_score(price, 200_000) == pytest.approx(expected, abs=0.01)


def test_geo_score_rewards_subdivision_match():
    assert geo_score(subdivision_match=True, miles=12.0) == 1.0


@pytest.mark.parametrize(
    "miles,expected", [(0.0, 1.00), (1.0, 0.90), (3.0, 0.50), (6.0, 0.20)]
)
def test_geo_score_decays_with_distance(miles, expected):
    assert geo_score(subdivision_match=False, miles=miles) == pytest.approx(
        expected, abs=0.01
    )


def test_categorical_score_exact_sibling_and_mismatch():
    assert categorical_score(PropertyType.DUPLEX, [PropertyType.DUPLEX]) == 1.0
    assert categorical_score(PropertyType.FOURPLEX, [PropertyType.DUPLEX]) == 0.5
    assert categorical_score(PropertyType.MULTI_FAMILY, [PropertyType.DUPLEX]) == 0.5
    assert categorical_score(PropertyType.SINGLE_FAMILY, [PropertyType.DUPLEX]) == 0.0


def test_default_weights_make_location_and_budget_heaviest():
    assert DEFAULT_WEIGHTS["area"] == 3.0
    assert DEFAULT_WEIGHTS["max_price"] == 3.0
    assert DEFAULT_WEIGHTS["beds"] == 2.0
    assert max(DEFAULT_WEIGHTS.values()) == 3.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_scoring_primitives.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'har_search.core.scoring'`

- [ ] **Step 3: Write `src/har_search/core/scoring.py`**

```python
"""Similarity scoring.

One rational family throughout: s = 1 / (1 + (delta / tau)^2). It decays
gently near the target and keeps a long tolerant tail, which is what
"similarity finder, not filter" means in practice.
"""

from __future__ import annotations

from har_search.core.models import PropertyType

# (tau_over, tau_under) per target parameter, in that parameter's own units.
TAU: dict[str, tuple[float, float]] = {
    "beds": (2.4, 0.82),
    "baths": (2.4, 0.82),
    "garage_spaces": (1.8, 0.75),
    "sqft": (1400.0, 520.0),
    "max_age_years": (14.0, 40.0),
}

CEILING_TAU = 0.16
GEO_TAU_MILES = 3.0

DEFAULT_WEIGHTS: dict[str, float] = {
    "area": 3.0,
    "max_price": 3.0,
    "beds": 2.0,
    "sqft": 1.5,
    "baths": 1.5,
    "property_types": 1.5,
    "max_price_per_sqft": 1.5,
    "garage_spaces": 1.0,
    "max_age_years": 1.0,
    "no_hoa": 1.0,
    "min_school_rating": 1.0,
}

_MULTI_FAMILY_FAMILY = {
    PropertyType.DUPLEX,
    PropertyType.FOURPLEX,
    PropertyType.MULTI_FAMILY,
}


def _rational(delta: float, tau: float) -> float:
    if tau <= 0:
        return 1.0 if delta == 0 else 0.0
    return 1.0 / (1.0 + (delta / tau) ** 2)


def target_score(actual: float, target: float, tau_over: float, tau_under: float) -> float:
    """Overshooting a target is cheap; undershooting it is not."""
    delta = actual - target
    tau = tau_over if delta >= 0 else tau_under
    return _rational(abs(delta), tau)


def ceiling_score(actual: float, ceiling: float, tau: float = CEILING_TAU) -> float:
    """At or under the ceiling is perfect; over it decays."""
    if ceiling <= 0:
        return 0.0
    if actual <= ceiling:
        return 1.0
    over = (actual - ceiling) / ceiling
    return _rational(over, tau)


def geo_score(subdivision_match: bool, miles: float | None) -> float:
    if subdivision_match:
        return 1.0
    if miles is None:
        return 0.0
    return _rational(miles, GEO_TAU_MILES)


def categorical_score(
    actual: PropertyType | None, wanted: list[PropertyType]
) -> float:
    if actual is None or not wanted:
        return 0.0
    if actual in wanted:
        return 1.0
    if actual in _MULTI_FAMILY_FAMILY and any(w in _MULTI_FAMILY_FAMILY for w in wanted):
        return 0.5
    return 0.0
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_scoring_primitives.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add src/har_search/core/scoring.py tests/test_scoring_primitives.py
git commit -m "feat: add similarity scoring primitives"
```

---

## Task 5: Score aggregation, coverage, and explanations

**Files:**
- Modify: `src/har_search/core/scoring.py`
- Test: `tests/test_scoring_listing.py`

**Interfaces:**
- Consumes: primitives from Task 4
- Produces: `score_listing(listing: Listing, criteria: Criteria, area_centroid: tuple[float, float] | None = None) -> ScoredListing | None` — returns `None` when a `must` parameter scores below `0.5`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scoring_listing.py`:

```python
import pytest

from har_search.core.models import Criteria, DuplexScope, GarageInfo, Listing, PropertyType
from har_search.core.scoring import score_listing

SPRING = (30.06, -95.42)


def make_listing(**overrides) -> Listing:
    base = dict(
        listing_id="L1",
        city="Spring",
        subdivision="Greengate Place Sec 06",
        lat=30.036156,
        lon=-95.342447,
        price=215_000,
        price_per_sqft=142.38,
        beds=3,
        baths_full=2,
        sqft=1510,
        year_built=1979,
        garage=GarageInfo(spaces=2, attached=True),
        property_type=PropertyType.SINGLE_FAMILY,
    )
    base.update(overrides)
    return Listing(**base)


def test_perfect_match_scores_near_one():
    criteria = Criteria(area="Spring", beds=3, baths=2, max_price=250_000)
    scored = score_listing(make_listing(), criteria, SPRING)
    assert scored.score > 0.95
    assert scored.coverage == 1.0


def test_four_bedroom_still_ranks_well_against_three_bedroom_request():
    """The call's headline example, expressed as a test."""
    criteria = Criteria(area="Spring", beds=3, baths=2, max_price=250_000)
    three = score_listing(make_listing(beds=3), criteria, SPRING)
    four = score_listing(make_listing(beds=4), criteria, SPRING)
    assert four.score > 0.85
    assert four.score < three.score


def test_slightly_over_budget_listing_still_appears():
    criteria = Criteria(area="Spring", beds=3, max_price=200_000, must=["area"])
    scored = score_listing(make_listing(price=215_000), criteria, SPRING)
    assert scored is not None
    assert scored.score > 0.6


def test_must_parameter_below_threshold_removes_the_listing():
    criteria = Criteria(area="Spring", max_price=200_000, must=["area", "max_price"])
    assert score_listing(make_listing(price=400_000), criteria, SPRING) is None


def test_unknown_parameters_are_excluded_from_the_mean_and_lower_coverage():
    """A duplex with no bed/bath data must not score as a zero-bedroom house."""
    criteria = Criteria(
        area="Spring", beds=3, baths=2, garage_spaces=1, max_price=700_000
    )
    duplex = make_listing(
        beds=None,
        baths_full=None,
        garage=None,
        property_type=PropertyType.DUPLEX,
        duplex_scope=DuplexScope.WHOLE,
        price=579_900,
    )
    scored = score_listing(duplex, criteria, SPRING)
    assert scored.score > 0.9
    assert scored.coverage < 0.6
    unknown = [p.name for p in scored.params if not p.known]
    assert set(unknown) == {"beds", "baths", "garage_spaces"}


def test_no_hoa_request_treats_missing_fee_as_unknown():
    criteria = Criteria(area="Spring", no_hoa=True, max_price=250_000)
    scored = score_listing(make_listing(hoa=None), criteria, SPRING)
    hoa_param = next(p for p in scored.params if p.name == "no_hoa")
    assert hoa_param.known is False


def test_why_names_the_deviation_and_the_matches():
    criteria = Criteria(area="Spring", beds=3, baths=2, max_price=250_000)
    scored = score_listing(make_listing(beds=4), criteria, SPRING)
    assert "beds" in scored.why.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_scoring_listing.py -v`
Expected: FAIL with `ImportError: cannot import name 'score_listing'`

- [ ] **Step 3: Append to `src/har_search/core/scoring.py`**

Add to the imports at the top:

```python
from datetime import date

from har_search.core.models import Criteria, Listing, ParamScore, PropertyType, ScoredListing
```

Then append:

```python
MUST_THRESHOLD = 0.5
_EARTH_RADIUS_MILES = 3958.8


def _haversine_miles(lat1, lon1, lat2, lon2) -> float:
    from math import asin, cos, radians, sin, sqrt

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_MILES * asin(sqrt(a))


def _weight(criteria: Criteria, name: str) -> float:
    overrides = criteria.weights or {}
    return float(overrides.get(name, DEFAULT_WEIGHTS.get(name, 1.0)))


def _param(name, score, weight, known, detail) -> ParamScore:
    return ParamScore(name=name, score=score, weight=weight, known=known, detail=detail)


def _target_param(criteria, name, target, actual, unit) -> ParamScore:
    weight = _weight(criteria, name)
    if actual is None:
        return _param(name, 0.0, weight, False, f"{name} not published")
    tau_over, tau_under = TAU[name]
    score = target_score(actual, target, tau_over, tau_under)
    return _param(name, score, weight, True, f"{actual}{unit} vs {target}{unit} wanted")


def score_listing(
    listing: Listing,
    criteria: Criteria,
    area_centroid: tuple[float, float] | None = None,
) -> ScoredListing | None:
    params: list[ParamScore] = []

    # Location.
    weight = _weight(criteria, "area")
    subdivision_match = bool(
        listing.subdivision
        and criteria.area.strip().lower() in listing.subdivision.lower()
    ) or bool(
        listing.city and criteria.area.strip().lower() == listing.city.strip().lower()
    ) or bool(listing.zip and criteria.area.strip() == listing.zip.strip())
    miles = None
    if area_centroid and listing.lat is not None and listing.lon is not None:
        miles = _haversine_miles(area_centroid[0], area_centroid[1], listing.lat, listing.lon)
    if subdivision_match or miles is not None:
        params.append(
            _param(
                "area",
                geo_score(subdivision_match, miles),
                weight,
                True,
                listing.subdivision or listing.city or criteria.area,
            )
        )
    else:
        params.append(_param("area", 0.0, weight, False, "no location data"))

    # Ceiling parameters.
    if criteria.max_price is not None:
        weight = _weight(criteria, "max_price")
        if listing.price is None:
            params.append(_param("max_price", 0.0, weight, False, "no price"))
        else:
            params.append(
                _param(
                    "max_price",
                    ceiling_score(listing.price, criteria.max_price),
                    weight,
                    True,
                    f"${listing.price:,} vs ${criteria.max_price:,} budget",
                )
            )

    if criteria.max_price_per_sqft is not None:
        weight = _weight(criteria, "max_price_per_sqft")
        if listing.price_per_sqft is None:
            params.append(
                _param("max_price_per_sqft", 0.0, weight, False, "no price per sqft")
            )
        else:
            params.append(
                _param(
                    "max_price_per_sqft",
                    ceiling_score(listing.price_per_sqft, criteria.max_price_per_sqft),
                    weight,
                    True,
                    f"${listing.price_per_sqft:.0f}/sqft vs ${criteria.max_price_per_sqft:.0f} wanted",
                )
            )

    # Target parameters.
    if criteria.beds is not None:
        params.append(_target_param(criteria, "beds", criteria.beds, listing.beds, " bd"))
    if criteria.baths is not None:
        params.append(
            _target_param(criteria, "baths", criteria.baths, listing.baths_full, " ba")
        )
    if criteria.garage_spaces is not None:
        actual = listing.garage.spaces if listing.garage else None
        params.append(
            _target_param(criteria, "garage_spaces", criteria.garage_spaces, actual, " car")
        )
    if criteria.sqft is not None:
        params.append(_target_param(criteria, "sqft", criteria.sqft, listing.sqft, " sqft"))
    if criteria.max_age_years is not None:
        weight = _weight(criteria, "max_age_years")
        if listing.year_built is None:
            params.append(_param("max_age_years", 0.0, weight, False, "no year built"))
        else:
            age = date.today().year - listing.year_built
            params.append(
                _param(
                    "max_age_years",
                    ceiling_score(age, criteria.max_age_years),
                    weight,
                    True,
                    f"{age} years old",
                )
            )

    # Property type.
    if criteria.property_types:
        weight = _weight(criteria, "property_types")
        wanted = [PropertyType(value) for value in criteria.property_types]
        if listing.property_type is None:
            params.append(_param("property_types", 0.0, weight, False, "no type"))
        else:
            params.append(
                _param(
                    "property_types",
                    categorical_score(listing.property_type, wanted),
                    weight,
                    True,
                    listing.property_type.value,
                )
            )

    # HOA. A missing fee is unknown, never "no HOA".
    if criteria.no_hoa:
        weight = _weight(criteria, "no_hoa")
        if listing.hoa is None:
            params.append(_param("no_hoa", 0.0, weight, False, "HOA not published"))
        else:
            params.append(
                _param(
                    "no_hoa",
                    0.0,
                    weight,
                    True,
                    f"HOA ${listing.hoa.monthly_usd:.0f}/mo",
                )
            )

    # School rating.
    if criteria.min_school_rating:
        weight = _weight(criteria, "min_school_rating")
        if listing.school_rating is None:
            params.append(
                _param("min_school_rating", 0.0, weight, False, "no school data")
            )
        else:
            params.append(
                _param(
                    "min_school_rating",
                    listing.school_rating,
                    weight,
                    True,
                    f"schools {listing.school_rating:.2f}",
                )
            )

    for param in params:
        if param.name in criteria.must and param.score < MUST_THRESHOLD:
            return None

    known = [p for p in params if p.known]
    known_weight = sum(p.weight for p in known)
    total_weight = sum(p.weight for p in params)
    score = (
        sum(p.score * p.weight for p in known) / known_weight if known_weight else 0.0
    )
    coverage = known_weight / total_weight if total_weight else 0.0

    return ScoredListing(
        listing=listing,
        score=score,
        coverage=coverage,
        params=params,
        why=_build_why(params),
    )


def _build_why(params: list[ParamScore]) -> str:
    known = [p for p in params if p.known]
    if not known:
        return "No comparable attributes published for this listing."
    weakest = min(known, key=lambda p: p.score)
    strong = [p.name for p in known if p.score >= 0.9 and p.name != weakest.name]
    if weakest.score >= 0.9:
        return "Matches every requested criterion: " + ", ".join(
            p.name for p in known
        ) + "."
    if strong:
        return (
            f"Included despite {weakest.name} ({weakest.detail}) — "
            + ", ".join(strong)
            + " all match."
        )
    return f"Closest on {weakest.name} ({weakest.detail})."
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/ -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add src/har_search/core/scoring.py tests/test_scoring_listing.py
git commit -m "feat: aggregate similarity scores with coverage and explanations"
```

---

## Task 6: Comparable selection cascade

**Files:**
- Create: `src/har_search/core/comps.py`
- Test: `tests/test_comps_selection.py`

**Interfaces:**
- Consumes: `har_search.core.models`
- Produces: `haversine_miles(lat1, lon1, lat2, lon2) -> float`, `comps_from_sales(subject, sales, today) -> list[Comp]`, `comps_from_listings(subject, listings) -> list[Comp]`, `select_comps(subject, sales, active, today) -> tuple[list[Comp], str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_comps_selection.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_comps_selection.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'har_search.core.comps'`

- [ ] **Step 3: Write `src/har_search/core/comps.py`**

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_comps_selection.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add src/har_search/core/comps.py tests/test_comps_selection.py
git commit -m "feat: add comparable selection cascade"
```

---

## Task 7: Valuation, adjustments, and the KPI

**Files:**
- Modify: `src/har_search/core/comps.py`
- Test: `tests/test_comps_valuation.py`

**Interfaces:**
- Consumes: `select_comps` from Task 6
- Produces: `trimmed_median(values) -> float`, `confidence_label(n) -> str`, `subdivision_list_to_sold(sales) -> float | None`, `value_listing(subject, sales, active, today) -> Valuation`

- [ ] **Step 1: Write the failing test**

Create `tests/test_comps_valuation.py`:

```python
from datetime import date, timedelta

import pytest

from har_search.core.comps import (
    confidence_label,
    subdivision_list_to_sold,
    trimmed_median,
    value_listing,
)
from har_search.core.models import Listing, MoneyRange, PropertyType, Sale

TODAY = date(2026, 9, 4)


def make_sale(mls, sold_price, sqft=2400, days_ago=30, list_price=None) -> Sale:
    return Sale(
        mls_number=mls,
        sold_price=sold_price,
        list_price=list_price,
        sold_date=TODAY - timedelta(days=days_ago),
        subdivision="Harmony",
        lat=30.10,
        lon=-95.38,
        sqft=sqft,
        beds=4,
        baths_full=2,
        year_built=2014,
        property_type=PropertyType.SINGLE_FAMILY,
    )


def subject(price=390_000, **kw) -> Listing:
    base = dict(
        listing_id="S1",
        subdivision="Harmony",
        lat=30.10,
        lon=-95.38,
        price=price,
        sqft=2400,
        beds=4,
        baths_full=2,
        year_built=2014,
        property_type=PropertyType.SINGLE_FAMILY,
    )
    base.update(kw)
    return Listing(**base)


def test_trimmed_median_ignores_extremes():
    values = [100.0, 145.0, 150.0, 155.0, 900.0]
    assert trimmed_median(values) == pytest.approx(150.0)


def test_trimmed_median_handles_short_lists():
    assert trimmed_median([150.0]) == pytest.approx(150.0)
    assert trimmed_median([140.0, 160.0]) == pytest.approx(150.0)


@pytest.mark.parametrize(
    "n,label",
    [(9, "high"), (8, "high"), (6, "medium"), (4, "low"), (2, "insufficient")],
)
def test_confidence_label_thresholds(n, label):
    assert confidence_label(n) == label


def test_value_listing_produces_estimate_and_kpi():
    sales = [make_sale(f"M{i}", 360_000) for i in range(6)]
    valuation = value_listing(subject(price=390_000), sales, active=[], today=TODAY)
    assert valuation.comp_count == 6
    assert valuation.comp_basis == "sold"
    assert valuation.confidence == "medium"
    assert valuation.comp_estimate == pytest.approx(360_000, rel=0.02)
    # Asking above comps means a positive delta.
    assert valuation.delta_pct > 0.07


def test_planted_outlier_does_not_move_the_estimate():
    """A 10-bedroom typo priced at $2M must not drag the neighbourhood."""
    sales = [make_sale(f"M{i}", 360_000) for i in range(6)]
    sales.append(make_sale("OUTLIER", 2_000_000))
    valuation = value_listing(subject(), sales, active=[], today=TODAY)
    assert valuation.comp_estimate == pytest.approx(360_000, rel=0.05)


def test_too_few_comps_returns_insufficient_and_no_number():
    sales = [make_sale("M0", 360_000), make_sale("M1", 365_000)]
    valuation = value_listing(subject(), sales, active=[], today=TODAY)
    assert valuation.confidence == "insufficient"
    assert valuation.comp_estimate is None
    assert valuation.delta_pct is None


def test_bedroom_adjustment_is_applied_and_capped():
    sales = [make_sale(f"M{i}", 360_000) for i in range(6)]
    more_beds = value_listing(subject(beds=6), sales, active=[], today=TODAY)
    baseline = value_listing(subject(beds=4), sales, active=[], today=TODAY)
    assert more_beds.comp_estimate > baseline.comp_estimate
    assert more_beds.comp_estimate <= baseline.comp_estimate * 1.10


def test_subdivision_list_to_sold_ratio():
    sales = [
        make_sale("M0", 400_000, list_price=475_000),
        make_sale("M1", 460_000, list_price=470_000),
        make_sale("M2", 375_000, list_price=360_000),
    ]
    ratio = subdivision_list_to_sold(sales)
    assert 0.90 < ratio < 1.00


def test_appraisal_district_value_is_carried_through():
    sales = [make_sale(f"M{i}", 360_000) for i in range(6)]
    subj = subject()
    subj.appraisal = MoneyRange(low=352_000, high=352_999)
    valuation = value_listing(subj, sales, active=[], today=TODAY)
    assert valuation.appraisal_district.low == 352_000
    assert valuation.spread_flag == "clustered"


def test_scattered_flag_when_sources_disagree():
    sales = [make_sale(f"M{i}", 360_000) for i in range(6)]
    subj = subject()
    subj.appraisal = MoneyRange(low=200_000, high=200_999)
    valuation = value_listing(subj, sales, active=[], today=TODAY)
    assert valuation.spread_flag == "scattered"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_comps_valuation.py -v`
Expected: FAIL with `ImportError: cannot import name 'trimmed_median'`

- [ ] **Step 3: Append to `src/har_search/core/comps.py`**

```python
from statistics import median

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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/ -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add src/har_search/core/comps.py tests/test_comps_valuation.py
git commit -m "feat: add comps valuation, adjustments and value KPI"
```

---

## Task 8: Snapshot diffing

**Files:**
- Create: `src/har_search/core/diff.py`
- Test: `tests/test_diff.py`

**Interfaces:**
- Consumes: `har_search.core.models`
- Produces: `diff_snapshots(previous: list[Listing], current: list[Listing]) -> list[ListingChange]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_diff.py`:

```python
from har_search.core.diff import diff_snapshots
from har_search.core.models import Listing


def listing(listing_id, price, address="1 Main St") -> Listing:
    return Listing(listing_id=listing_id, price=price, address=address)


def by_type(changes):
    return {c.listing_id: c.change_type for c in changes}


def test_new_listing_is_detected():
    changes = diff_snapshots([], [listing("A", 200_000)])
    assert by_type(changes) == {"A": "NEW"}


def test_gone_listing_is_detected():
    changes = diff_snapshots([listing("A", 200_000)], [])
    assert by_type(changes) == {"A": "GONE"}


def test_price_cut_and_rise_are_distinguished():
    previous = [listing("A", 200_000), listing("B", 300_000)]
    current = [listing("A", 190_000), listing("B", 310_000)]
    assert by_type(diff_snapshots(previous, current)) == {
        "A": "PRICE_CUT",
        "B": "PRICE_UP",
    }


def test_unchanged_listing_is_reported_as_unchanged():
    previous = [listing("A", 200_000)]
    current = [listing("A", 200_000)]
    assert by_type(diff_snapshots(previous, current)) == {"A": "UNCHANGED"}


def test_change_carries_both_prices_and_the_address():
    changes = diff_snapshots(
        [listing("A", 200_000, "5519 Lynngate Dr")],
        [listing("A", 190_000, "5519 Lynngate Dr")],
    )
    change = changes[0]
    assert change.old_price == 200_000
    assert change.new_price == 190_000
    assert change.address == "5519 Lynngate Dr"


def test_missing_price_does_not_produce_a_false_change():
    previous = [listing("A", None)]
    current = [listing("A", None)]
    assert by_type(diff_snapshots(previous, current)) == {"A": "UNCHANGED"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_diff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'har_search.core.diff'`

- [ ] **Step 3: Write `src/har_search/core/diff.py`**

```python
"""Compare two snapshots of the same saved search."""

from __future__ import annotations

from har_search.core.models import Listing, ListingChange


def diff_snapshots(
    previous: list[Listing], current: list[Listing]
) -> list[ListingChange]:
    before = {listing.listing_id: listing for listing in previous}
    after = {listing.listing_id: listing for listing in current}

    changes: list[ListingChange] = []

    for listing_id, listing in after.items():
        old = before.get(listing_id)
        if old is None:
            changes.append(
                ListingChange(
                    listing_id=listing_id,
                    change_type="NEW",
                    old_price=None,
                    new_price=listing.price,
                    address=listing.address,
                )
            )
            continue

        if old.price is not None and listing.price is not None:
            if listing.price < old.price:
                change_type = "PRICE_CUT"
            elif listing.price > old.price:
                change_type = "PRICE_UP"
            else:
                change_type = "UNCHANGED"
        else:
            change_type = "UNCHANGED"

        changes.append(
            ListingChange(
                listing_id=listing_id,
                change_type=change_type,
                old_price=old.price,
                new_price=listing.price,
                address=listing.address,
            )
        )

    for listing_id, listing in before.items():
        if listing_id not in after:
            changes.append(
                ListingChange(
                    listing_id=listing_id,
                    change_type="GONE",
                    old_price=listing.price,
                    new_price=None,
                    address=listing.address,
                )
            )

    return changes
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_diff.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add src/har_search/core/diff.py tests/test_diff.py
git commit -m "feat: add snapshot diffing"
```

---

## Task 9: SQLite store

**Files:**
- Create: `src/har_search/store/__init__.py`, `src/har_search/store/schema.sql`, `src/har_search/store/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `har_search.core.models`
- Produces: `Database(path)` with `init_schema()`, `create_snapshot(saved_search, source, item_count, excluded_count, exclusions) -> int`, `insert_scored(snapshot_id, scored, valuations)`, `get_snapshot_listings(snapshot_id) -> list[Listing]`, `get_scored_rows(snapshot_id) -> list[dict]`, `upsert_sales(sales)`, `sales_near(lat, lon, miles, since) -> list[Sale]`, `recent_snapshots(saved_search, limit) -> list[dict]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_db.py`:

```python
from datetime import date, timedelta

from har_search.core.models import Listing, PropertyType, Sale, ScoredListing, Valuation
from har_search.store.db import Database

TODAY = date(2026, 9, 4)


def make_db(tmp_path) -> Database:
    db = Database(tmp_path / "test.db")
    db.init_schema()
    return db


def make_scored(listing_id="L1", price=215_000) -> ScoredListing:
    return ScoredListing(
        listing=Listing(
            listing_id=listing_id,
            address="5519 Lynngate Dr",
            subdivision="Greengate Place Sec 06",
            lat=30.036,
            lon=-95.342,
            price=price,
            sqft=1510,
            beds=3,
            property_type=PropertyType.SINGLE_FAMILY,
        ),
        score=0.91,
        coverage=0.85,
        params=[],
        why="Matches every requested criterion.",
    )


def test_snapshot_round_trip(tmp_path):
    db = make_db(tmp_path)
    snapshot_id = db.create_snapshot(
        saved_search="spring-investment",
        source="apify_memo23",
        item_count=1,
        excluded_count=2,
        exclusions={"lease": 1, "price_below_floor": 1},
    )
    db.insert_scored(snapshot_id, [make_scored()], {"L1": Valuation(comp_estimate=231_000)})

    listings = db.get_snapshot_listings(snapshot_id)
    assert len(listings) == 1
    assert listings[0].price == 215_000
    assert listings[0].property_type is PropertyType.SINGLE_FAMILY


def test_scored_rows_carry_score_and_valuation(tmp_path):
    db = make_db(tmp_path)
    snapshot_id = db.create_snapshot("s", "apify_memo23", 1, 0, {})
    db.insert_scored(
        snapshot_id,
        [make_scored()],
        {"L1": Valuation(comp_estimate=231_000, comp_count=6, delta_pct=-0.069)},
    )
    row = db.get_scored_rows(snapshot_id)[0]
    assert row["score"] == 0.91
    assert row["valuation"]["comp_estimate"] == 231_000
    assert row["valuation"]["comp_count"] == 6


def test_sales_accumulate_across_runs_and_deduplicate(tmp_path):
    db = make_db(tmp_path)
    sale = Sale(
        mls_number="M1",
        sold_price=460_000,
        sold_date=TODAY,
        subdivision="Harmony",
        lat=30.10,
        lon=-95.38,
        sqft=3110,
        property_type=PropertyType.SINGLE_FAMILY,
    )
    db.upsert_sales([sale])
    db.upsert_sales([sale])
    found = db.sales_near(30.10, -95.38, miles=2.0, since=TODAY - timedelta(days=180))
    assert len(found) == 1
    assert found[0].sold_price == 460_000


def test_sales_near_filters_by_distance_and_recency(tmp_path):
    db = make_db(tmp_path)
    db.upsert_sales(
        [
            Sale("NEAR", 400_000, TODAY, lat=30.10, lon=-95.38, sqft=2000),
            Sale("FAR", 400_000, TODAY, lat=31.50, lon=-97.00, sqft=2000),
            Sale("STALE", 400_000, TODAY - timedelta(days=400), lat=30.10, lon=-95.38, sqft=2000),
        ]
    )
    found = db.sales_near(30.10, -95.38, miles=2.0, since=TODAY - timedelta(days=180))
    assert {s.mls_number for s in found} == {"NEAR"}


def test_recent_snapshots_returns_newest_first(tmp_path):
    db = make_db(tmp_path)
    first = db.create_snapshot("s", "apify_memo23", 1, 0, {})
    second = db.create_snapshot("s", "apify_memo23", 2, 0, {})
    snapshots = db.recent_snapshots("s", limit=2)
    assert [s["id"] for s in snapshots] == [second, first]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'har_search.store'`

- [ ] **Step 3: Write `src/har_search/store/schema.sql`**

Create an empty `src/har_search/store/__init__.py`, then:

```sql
CREATE TABLE IF NOT EXISTS saved_searches (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  criteria_json TEXT NOT NULL,
  weights_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY,
  saved_search TEXT NOT NULL,
  run_at TEXT NOT NULL,
  source TEXT NOT NULL,
  item_count INTEGER NOT NULL,
  excluded_count INTEGER NOT NULL,
  exclusions_json TEXT
);

CREATE TABLE IF NOT EXISTS listings (
  snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
  listing_id TEXT NOT NULL,
  mls_number TEXT,
  address TEXT, city TEXT, zip TEXT, subdivision TEXT,
  lat REAL, lon REAL,
  price INTEGER, price_per_sqft REAL,
  beds INTEGER, baths_full INTEGER, baths_half INTEGER,
  sqft INTEGER, lot_sqft INTEGER, year_built INTEGER,
  garage_spaces INTEGER, hoa_monthly REAL,
  property_type TEXT, duplex_scope TEXT, status TEXT, days_on_market INTEGER,
  school_rating REAL, tax_rate REAL,
  appraisal_low INTEGER, appraisal_high INTEGER,
  url TEXT,
  score REAL, coverage REAL, why TEXT,
  score_breakdown_json TEXT, valuation_json TEXT, flags_json TEXT,
  PRIMARY KEY (snapshot_id, listing_id)
);

CREATE TABLE IF NOT EXISTS sold_history (
  mls_number TEXT PRIMARY KEY,
  address TEXT, city TEXT, zip TEXT, subdivision TEXT,
  lat REAL, lon REAL,
  list_price INTEGER, sold_price INTEGER NOT NULL, sold_date TEXT NOT NULL,
  sold_price_per_sqft REAL, sqft INTEGER, beds INTEGER, baths_full INTEGER,
  year_built INTEGER, lot_sqft INTEGER, property_type TEXT,
  first_seen TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sold_geo ON sold_history (lat, lon);
CREATE INDEX IF NOT EXISTS idx_sold_sub ON sold_history (subdivision, sold_date);
CREATE INDEX IF NOT EXISTS idx_snapshot_search ON snapshots (saved_search, run_at);
```

- [ ] **Step 4: Write `src/har_search/store/db.py`**

```python
"""SQLite persistence.

sold_history is deliberately never scoped to a run. Comp density is the
binding constraint on the product, so closed sales accumulate permanently
and every scan makes the next valuation better.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from har_search.core.comps import haversine_miles
from har_search.core.models import (
    DuplexScope,
    GarageInfo,
    HOA,
    Listing,
    MoneyRange,
    PropertyType,
    Sale,
    ScoredListing,
    Valuation,
)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA_PATH.read_text())
        self._conn.commit()

    def create_snapshot(
        self,
        saved_search: str,
        source: str,
        item_count: int,
        excluded_count: int,
        exclusions: dict,
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO snapshots (saved_search, run_at, source, item_count,"
            " excluded_count, exclusions_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                saved_search,
                datetime.now().isoformat(timespec="seconds"),
                source,
                item_count,
                excluded_count,
                json.dumps(exclusions),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def insert_scored(
        self,
        snapshot_id: int,
        scored: list[ScoredListing],
        valuations: dict[str, Valuation],
    ) -> None:
        for item in scored:
            listing = item.listing
            valuation = valuations.get(listing.listing_id, Valuation())
            self._conn.execute(
                "INSERT OR REPLACE INTO listings (snapshot_id, listing_id, mls_number,"
                " address, city, zip, subdivision, lat, lon, price, price_per_sqft,"
                " beds, baths_full, baths_half, sqft, lot_sqft, year_built,"
                " garage_spaces, hoa_monthly, property_type, duplex_scope, status,"
                " days_on_market, school_rating, tax_rate, appraisal_low,"
                " appraisal_high, url, score, coverage, why, score_breakdown_json,"
                " valuation_json, flags_json)"
                " VALUES (" + ",".join("?" * 34) + ")",
                (
                    snapshot_id,
                    listing.listing_id,
                    listing.mls_number,
                    listing.address,
                    listing.city,
                    listing.zip,
                    listing.subdivision,
                    listing.lat,
                    listing.lon,
                    listing.price,
                    listing.price_per_sqft,
                    listing.beds,
                    listing.baths_full,
                    listing.baths_half,
                    listing.sqft,
                    listing.lot_sqft,
                    listing.year_built,
                    listing.garage.spaces if listing.garage else None,
                    listing.hoa.monthly_usd if listing.hoa else None,
                    listing.property_type.value if listing.property_type else None,
                    listing.duplex_scope.value,
                    listing.status,
                    listing.days_on_market,
                    listing.school_rating,
                    listing.tax_rate,
                    listing.appraisal.low if listing.appraisal else None,
                    listing.appraisal.high if listing.appraisal else None,
                    listing.url,
                    item.score,
                    item.coverage,
                    item.why,
                    json.dumps([asdict(p) for p in item.params]),
                    json.dumps(_valuation_to_json(valuation)),
                    json.dumps(list(listing.flags)),
                ),
            )
        self._conn.commit()

    def _row_to_listing(self, row: sqlite3.Row) -> Listing:
        return Listing(
            listing_id=row["listing_id"],
            mls_number=row["mls_number"],
            address=row["address"],
            city=row["city"],
            zip=row["zip"],
            subdivision=row["subdivision"],
            lat=row["lat"],
            lon=row["lon"],
            price=row["price"],
            price_per_sqft=row["price_per_sqft"],
            beds=row["beds"],
            baths_full=row["baths_full"],
            baths_half=row["baths_half"],
            sqft=row["sqft"],
            lot_sqft=row["lot_sqft"],
            year_built=row["year_built"],
            garage=GarageInfo(spaces=row["garage_spaces"])
            if row["garage_spaces"] is not None
            else None,
            hoa=HOA(monthly_usd=row["hoa_monthly"])
            if row["hoa_monthly"] is not None
            else None,
            property_type=PropertyType(row["property_type"])
            if row["property_type"]
            else None,
            duplex_scope=DuplexScope(row["duplex_scope"] or "unknown"),
            status=row["status"],
            days_on_market=row["days_on_market"],
            school_rating=row["school_rating"],
            tax_rate=row["tax_rate"],
            appraisal=MoneyRange(low=row["appraisal_low"], high=row["appraisal_high"])
            if row["appraisal_low"] is not None
            else None,
            url=row["url"],
            flags=tuple(json.loads(row["flags_json"] or "[]")),
        )

    def get_snapshot_listings(self, snapshot_id: int) -> list[Listing]:
        rows = self._conn.execute(
            "SELECT * FROM listings WHERE snapshot_id = ? ORDER BY score DESC",
            (snapshot_id,),
        ).fetchall()
        return [self._row_to_listing(row) for row in rows]

    def get_scored_rows(self, snapshot_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM listings WHERE snapshot_id = ? ORDER BY score DESC",
            (snapshot_id,),
        ).fetchall()
        return [
            {
                "listing": self._row_to_listing(row),
                "score": row["score"],
                "coverage": row["coverage"],
                "why": row["why"],
                "params": json.loads(row["score_breakdown_json"] or "[]"),
                "valuation": json.loads(row["valuation_json"] or "{}"),
            }
            for row in rows
        ]

    def upsert_sales(self, sales: list[Sale]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        for sale in sales:
            self._conn.execute(
                "INSERT OR REPLACE INTO sold_history (mls_number, address, city, zip,"
                " subdivision, lat, lon, list_price, sold_price, sold_date,"
                " sold_price_per_sqft, sqft, beds, baths_full, year_built, lot_sqft,"
                " property_type, first_seen)"
                " VALUES (" + ",".join("?" * 18) + ")",
                (
                    sale.mls_number,
                    sale.address,
                    sale.city,
                    sale.zip,
                    sale.subdivision,
                    sale.lat,
                    sale.lon,
                    sale.list_price,
                    sale.sold_price,
                    sale.sold_date.isoformat(),
                    sale.sold_price_per_sqft,
                    sale.sqft,
                    sale.beds,
                    sale.baths_full,
                    sale.year_built,
                    sale.lot_sqft,
                    sale.property_type.value if sale.property_type else None,
                    now,
                ),
            )
        self._conn.commit()

    def sales_near(
        self, lat: float, lon: float, miles: float, since: date
    ) -> list[Sale]:
        # A generous bounding box first, then exact distance in Python.
        degrees = miles / 55.0
        rows = self._conn.execute(
            "SELECT * FROM sold_history WHERE sold_date >= ?"
            " AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
            (since.isoformat(), lat - degrees, lat + degrees, lon - degrees, lon + degrees),
        ).fetchall()

        sales = []
        for row in rows:
            if row["lat"] is None or row["lon"] is None:
                continue
            if haversine_miles(lat, lon, row["lat"], row["lon"]) > miles:
                continue
            sales.append(
                Sale(
                    mls_number=row["mls_number"],
                    sold_price=row["sold_price"],
                    sold_date=date.fromisoformat(row["sold_date"]),
                    address=row["address"],
                    city=row["city"],
                    zip=row["zip"],
                    subdivision=row["subdivision"],
                    lat=row["lat"],
                    lon=row["lon"],
                    list_price=row["list_price"],
                    sold_price_per_sqft=row["sold_price_per_sqft"],
                    sqft=row["sqft"],
                    beds=row["beds"],
                    baths_full=row["baths_full"],
                    year_built=row["year_built"],
                    lot_sqft=row["lot_sqft"],
                    property_type=PropertyType(row["property_type"])
                    if row["property_type"]
                    else None,
                )
            )
        return sales

    def recent_snapshots(self, saved_search: str, limit: int = 2) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM snapshots WHERE saved_search = ?"
            " ORDER BY id DESC LIMIT ?",
            (saved_search, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def _valuation_to_json(valuation: Valuation) -> dict:
    data = asdict(valuation)
    appraisal = data.get("appraisal_district")
    if appraisal is not None:
        data["appraisal_district"] = {"low": appraisal["low"], "high": appraisal["high"]}
    return data
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add src/har_search/store tests/test_db.py
git commit -m "feat: add SQLite store with accumulating sold history"
```

---

## Task 10: Source adapter

**Files:**
- Create: `src/har_search/sources/__init__.py`, `src/har_search/sources/base.py`, `src/har_search/sources/apify_memo23.py`, `tests/fixtures/for_sale_spring.json`, `tests/fixtures/sold_spring.json`
- Test: `tests/test_apify_source.py`

**Interfaces:**
- Consumes: `har_search.core.models`
- Produces: `ListingSource` protocol; `ApifyMemo23Source(token, actor="memo23/har-scraper", http=None)` with `fetch_for_sale(criteria, limit) -> list[dict]` and `fetch_sold(area, agent_depth, limit) -> list[dict]`; `criteria_to_actor_input(criteria, limit) -> dict`

No network calls in tests. `ApifyMemo23Source` takes an injectable HTTP client so tests pass a stub.

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/for_sale_spring.json` — rows recorded from the live recon run:

```json
[
  {
    "listingId": "F1",
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
    "schools": {"E": {"rating_letter": "D"}, "M": {"rating_letter": "D"}, "S": {"rating_letter": "F"}},
    "taxInfo": {"tax_rate": 2.47421}
  },
  {
    "listingId": "F2",
    "address": "22307 Roseville Dr",
    "city": "Spring",
    "zip": "77389",
    "subdivision": "Forest North",
    "latitude": 30.087666,
    "longitude": -95.470677,
    "price": 220000,
    "pricePerSqft": 171.34,
    "beds": 3,
    "bathsFull": 2,
    "bathsHalf": 0,
    "sqft": 1284,
    "lotSize": "6,600 sqft",
    "yearBuilt": 1978,
    "garage": "2 Attached",
    "maintenanceFee": "$550 Annually",
    "propertyType": "Single-Family",
    "status": "Active",
    "daysOnMarket": 1,
    "avmValue": "$174K",
    "mlsNumber": "22222222",
    "schools": {"E": {"rating_letter": "B"}, "M": {"rating_letter": "B"}, "S": {"rating_letter": "B"}},
    "taxInfo": {"tax_rate": 2.73791}
  },
  {
    "listingId": "F3",
    "address": "9642 Intervale St",
    "city": "Houston",
    "zip": "77075",
    "price": 1325,
    "pricePerSqft": 0.79,
    "beds": 0,
    "bathsFull": 0,
    "sqft": 1684,
    "lotSize": "5,680 sqft",
    "yearBuilt": 1965,
    "garage": null,
    "maintenanceFee": null,
    "propertyType": "Multi-Family - Duplex",
    "status": "Active",
    "mlsNumber": "33333333"
  }
]
```

`tests/fixtures/sold_spring.json` — including the lease rows that bleed into sold results:

```json
[
  {
    "mlsNumber": "S1",
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
    "status": "Sold"
  },
  {
    "mlsNumber": "S2",
    "address": "3502 Gambel Dr",
    "city": "Spring",
    "zip": "77386",
    "subdivision": "Harmony",
    "latitude": 30.10322,
    "longitude": -95.371695,
    "price": 4200,
    "soldPrice": 4000,
    "soldDate": "2026-09-01",
    "soldPricePerSqft": 1.22,
    "sqft": 3287,
    "beds": 5,
    "bathsFull": 3,
    "yearBuilt": 2016,
    "propertyType": "Single Family",
    "status": "Rented"
  },
  {
    "mlsNumber": "S3",
    "address": "2322 Shadow Glen",
    "city": "Spring",
    "zip": "77386",
    "subdivision": "Spring Forest",
    "latitude": 30.118776,
    "longitude": -95.407421,
    "price": 475000,
    "soldPrice": 400000,
    "soldDate": "2026-08-11",
    "soldPricePerSqft": 88.75,
    "sqft": 4507,
    "beds": 10,
    "bathsFull": 5,
    "yearBuilt": 1978,
    "lotSize": "40,000 sqft",
    "propertyType": "Single-Family",
    "status": "Sold"
  }
]
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_apify_source.py`:

```python
import json
from pathlib import Path

from har_search.core.models import Criteria
from har_search.sources.apify_memo23 import ApifyMemo23Source, criteria_to_actor_input

FIXTURES = Path(__file__).parent / "fixtures"


class StubHttp:
    """Stands in for httpx.Client. Records calls, returns canned rows."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def post(self, url, json=None, params=None, timeout=None):
        self.calls.append({"url": url, "json": json, "params": params})
        return StubResponse(self.rows)


class StubResponse:
    def __init__(self, rows):
        self._rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return self._rows


def test_criteria_map_onto_actor_input():
    criteria = Criteria(
        area="Spring",
        beds=3,
        baths=2,
        max_price=250_000,
        max_price_per_sqft=120,
        property_types=["duplex"],
        no_hoa=True,
    )
    payload = criteria_to_actor_input(criteria, limit=25)
    assert payload["locations"] == ["Spring"]
    assert payload["listingType"] == "sale"
    assert payload["minBeds"] == 3
    assert payload["minBaths"] == 2
    assert payload["maxPrice"] == 250_000
    assert payload["maxPricePerSqft"] == 120
    assert payload["propertyTypes"] == ["multi-family"]
    assert payload["includeDetails"] is True
    assert payload["includeAvm"] is True
    assert payload["maxItems"] == 25


def test_criteria_omit_unset_filters():
    payload = criteria_to_actor_input(Criteria(area="Spring"), limit=10)
    assert "minBeds" not in payload
    assert "maxPrice" not in payload


def test_fetch_for_sale_returns_raw_rows():
    rows = json.loads((FIXTURES / "for_sale_spring.json").read_text())
    http = StubHttp(rows)
    source = ApifyMemo23Source(token="tok", http=http)
    result = source.fetch_for_sale(Criteria(area="Spring", beds=3), limit=25)
    assert len(result) == 3
    assert result[0]["address"] == "5519 Lynngate Dr"


def test_fetch_for_sale_sends_the_token_and_actor_path():
    http = StubHttp([])
    source = ApifyMemo23Source(token="tok", http=http)
    source.fetch_for_sale(Criteria(area="Spring"), limit=5)
    call = http.calls[0]
    assert "memo23~har-scraper" in call["url"]
    assert call["params"]["token"] == "tok"


def test_fetch_sold_requests_sold_listing_type():
    http = StubHttp([])
    source = ApifyMemo23Source(token="tok", http=http)
    source.fetch_sold(area="Spring", agent_depth=25, limit=200)
    assert http.calls[0]["json"]["listingType"] == "sold"
    assert http.calls[0]["json"]["maxSoldAgents"] == 25
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_apify_source.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'har_search.sources'`

- [ ] **Step 4: Write `src/har_search/sources/base.py`**

Create an empty `src/har_search/sources/__init__.py`, then:

```python
"""The only outward-facing layer.

Recon established three possible data paths — a licensed MLS feed, managed
scraping vendors, or nothing viable. We build on a vendor today because the
prospect's MLS status is unknown. When that answer arrives, a new adapter
lands here and nothing above it changes.
"""

from __future__ import annotations

from typing import Protocol

from har_search.core.models import Criteria


class ListingSource(Protocol):
    name: str

    def fetch_for_sale(self, criteria: Criteria, limit: int) -> list[dict]: ...

    def fetch_sold(self, area: str, agent_depth: int, limit: int) -> list[dict]: ...
```

- [ ] **Step 5: Write `src/har_search/sources/apify_memo23.py`**

```python
"""Adapter for the memo23/har-scraper Apify actor."""

from __future__ import annotations

from har_search.core.models import Criteria

ACTOR_PATH = "memo23~har-scraper"
RUN_SYNC_URL = f"https://api.apify.com/v2/acts/{ACTOR_PATH}/run-sync-get-dataset-items"

# Criteria property types map onto the actor's own vocabulary.
_TYPE_TO_ACTOR = {
    "single_family": "single-family",
    "townhouse_condo": "townhouse-condo",
    "duplex": "multi-family",
    "fourplex": "multi-family",
    "multi_family": "multi-family",
    "lots": "lots",
}


def criteria_to_actor_input(criteria: Criteria, limit: int) -> dict:
    payload: dict = {
        "listingType": "sale",
        "locations": [criteria.area],
        "includeDetails": True,
        "includeAvm": True,
        "maxItems": limit,
        "sortBy": "newest",
    }
    if criteria.beds is not None:
        payload["minBeds"] = criteria.beds
    if criteria.baths is not None:
        payload["minBaths"] = criteria.baths
    if criteria.max_price is not None:
        payload["maxPrice"] = criteria.max_price
    if criteria.max_price_per_sqft is not None:
        payload["maxPricePerSqft"] = int(criteria.max_price_per_sqft)
    if criteria.sqft is not None:
        payload["minSqft"] = int(criteria.sqft * 0.75)
    if criteria.property_types:
        mapped = {
            _TYPE_TO_ACTOR[value]
            for value in criteria.property_types
            if value in _TYPE_TO_ACTOR
        }
        if mapped:
            payload["propertyTypes"] = sorted(mapped)
    return payload


class ApifyMemo23Source:
    name = "apify_memo23"

    def __init__(self, token: str, http=None, timeout: float = 180.0):
        self._token = token
        self._timeout = timeout
        if http is None:
            import httpx

            http = httpx.Client(timeout=timeout)
        self._http = http

    def _run(self, payload: dict) -> list[dict]:
        response = self._http.post(
            RUN_SYNC_URL,
            json=payload,
            params={"token": self._token},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def fetch_for_sale(self, criteria: Criteria, limit: int) -> list[dict]:
        return self._run(criteria_to_actor_input(criteria, limit))

    def fetch_sold(self, area: str, agent_depth: int = 25, limit: int = 200) -> list[dict]:
        return self._run(
            {
                "listingType": "sold",
                "locations": [area],
                "maxSoldAgents": agent_depth,
                "maxItems": limit,
            }
        )
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_apify_source.py -v`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add src/har_search/sources tests/test_apify_source.py tests/fixtures
git commit -m "feat: add Apify source adapter with recorded fixtures"
```

---

## Task 11: Pipeline orchestration

**Files:**
- Create: `src/har_search/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `normalize_listing`, `normalize_sale`, `score_listing`, `value_listing`, `Database`, `ListingSource`
- Produces: `SearchResult` dataclass and `run_search(source, db, criteria, saved_search, limit, today) -> SearchResult`

This is where fetch, normalize, score, value and persist are wired together. It is the only place that knows the order of operations, and it is pure of transport concerns because the source is injected.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline.py`:

```python
import json
from datetime import date
from pathlib import Path

from har_search.core.models import Criteria
from har_search.pipeline import run_search
from har_search.store.db import Database

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 9, 4)


class FixtureSource:
    name = "fixture"

    def __init__(self):
        self.for_sale = json.loads((FIXTURES / "for_sale_spring.json").read_text())
        self.sold = json.loads((FIXTURES / "sold_spring.json").read_text())

    def fetch_for_sale(self, criteria, limit):
        return self.for_sale

    def fetch_sold(self, area, agent_depth=25, limit=200):
        return self.sold


def make_db(tmp_path) -> Database:
    db = Database(tmp_path / "pipeline.db")
    db.init_schema()
    return db


def test_run_search_returns_scored_listings(tmp_path):
    result = run_search(
        source=FixtureSource(),
        db=make_db(tmp_path),
        criteria=Criteria(area="Spring", beds=3, max_price=250_000),
        saved_search="spring",
        limit=25,
        today=TODAY,
    )
    assert len(result.scored) == 2
    assert result.scored[0].score > 0.5


def test_run_search_records_exclusions_with_reasons(tmp_path):
    """The $1,325 duplex must be excluded and counted, never silently dropped."""
    result = run_search(
        source=FixtureSource(),
        db=make_db(tmp_path),
        criteria=Criteria(area="Spring", max_price=250_000, must=["area"]),
        saved_search="spring",
        limit=25,
        today=TODAY,
    )
    assert result.exclusions["price_below_floor"] == 1


def test_run_search_persists_a_snapshot_that_can_be_read_back(tmp_path):
    db = make_db(tmp_path)
    result = run_search(
        source=FixtureSource(),
        db=db,
        criteria=Criteria(area="Spring", beds=3, max_price=250_000),
        saved_search="spring",
        limit=25,
        today=TODAY,
    )
    rows = db.get_scored_rows(result.snapshot_id)
    assert len(rows) == 2
    assert rows[0]["valuation"] is not None


def test_sold_rows_land_in_permanent_history_and_leases_are_dropped(tmp_path):
    db = make_db(tmp_path)
    run_search(
        source=FixtureSource(),
        db=db,
        criteria=Criteria(area="Spring", beds=3, max_price=250_000),
        saved_search="spring",
        limit=25,
        today=TODAY,
    )
    sales = db.sales_near(30.10, -95.38, miles=5.0, since=date(2026, 1, 1))
    assert {s.mls_number for s in sales} == {"S1", "S3"}


def test_every_result_carries_a_valuation_even_when_insufficient(tmp_path):
    result = run_search(
        source=FixtureSource(),
        db=make_db(tmp_path),
        criteria=Criteria(area="Spring", beds=3, max_price=250_000),
        saved_search="spring",
        limit=25,
        today=TODAY,
    )
    for scored in result.scored:
        valuation = result.valuations[scored.listing.listing_id]
        assert valuation.confidence in {"high", "medium", "low", "insufficient"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'har_search.pipeline'`

- [ ] **Step 3: Write `src/har_search/pipeline.py`**

```python
"""Fetch, normalize, score, value, persist — in that order, once."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from har_search.core.comps import value_listing
from har_search.core.models import Criteria, Listing, ScoredListing, Valuation
from har_search.core.normalize import normalize_listing, normalize_sale
from har_search.core.scoring import score_listing
from har_search.store.db import Database

COMP_LOOKBACK_DAYS = 365
COMP_RADIUS_MILES = 2.0


@dataclass
class SearchResult:
    snapshot_id: int
    scored: list[ScoredListing]
    valuations: dict[str, Valuation]
    exclusions: dict[str, int] = field(default_factory=dict)
    dropped_by_must: int = 0


def _area_centroid(listings: list[Listing]) -> tuple[float, float] | None:
    points = [(l.lat, l.lon) for l in listings if l.lat is not None and l.lon is not None]
    if not points:
        return None
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def run_search(
    source,
    db: Database,
    criteria: Criteria,
    saved_search: str,
    limit: int = 25,
    today: date | None = None,
) -> SearchResult:
    today = today or date.today()

    # 1. Sold history first, so comps are available for this run's listings.
    for raw in source.fetch_sold(area=criteria.area):
        sale = normalize_sale(raw)
        if sale is not None:
            db.upsert_sales([sale])

    # 2. For-sale rows, normalized with every exclusion counted.
    exclusions: Counter[str] = Counter()
    listings: list[Listing] = []
    for raw in source.fetch_for_sale(criteria, limit):
        result = normalize_listing(raw)
        if result.listing is None:
            exclusions[result.exclusion or "unknown"] += 1
            continue
        listings.append(result.listing)

    # 3. Score. A listing failing a `must` parameter is removed, and counted.
    centroid = _area_centroid(listings)
    scored: list[ScoredListing] = []
    dropped_by_must = 0
    for listing in listings:
        result = score_listing(listing, criteria, centroid)
        if result is None:
            dropped_by_must += 1
            continue
        scored.append(result)
    scored.sort(key=lambda s: s.score, reverse=True)

    # 4. Value each survivor against accumulated sold history.
    since = today - timedelta(days=COMP_LOOKBACK_DAYS)
    valuations: dict[str, Valuation] = {}
    for item in scored:
        listing = item.listing
        sales = (
            db.sales_near(listing.lat, listing.lon, COMP_RADIUS_MILES, since)
            if listing.lat is not None and listing.lon is not None
            else []
        )
        others = [s.listing for s in scored if s.listing.listing_id != listing.listing_id]
        valuations[listing.listing_id] = value_listing(listing, sales, others, today)

    # 5. Persist.
    snapshot_id = db.create_snapshot(
        saved_search=saved_search,
        source=getattr(source, "name", "unknown"),
        item_count=len(scored),
        excluded_count=sum(exclusions.values()) + dropped_by_must,
        exclusions=dict(exclusions),
    )
    db.insert_scored(snapshot_id, scored, valuations)

    return SearchResult(
        snapshot_id=snapshot_id,
        scored=scored,
        valuations=valuations,
        exclusions=dict(exclusions),
        dropped_by_must=dropped_by_must,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/ -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add src/har_search/pipeline.py tests/test_pipeline.py
git commit -m "feat: wire fetch, normalize, score, value and persist into a pipeline"
```

---

## Task 12: MCP server and tools

**Files:**
- Create: `src/har_search/server/__init__.py`, `src/har_search/server/__main__.py`, `src/har_search/config.py`
- Test: `tests/test_server_tools.py`

**Interfaces:**
- Consumes: `run_search`, `Database`, `ApifyMemo23Source`, `diff_snapshots`
- Produces: `build_search_response(result, limit, dashboard_url) -> dict`, `build_explain_response(row, comps_rows) -> dict`, `build_whats_new_response(changes) -> dict`, and the FastMCP tools `search`, `explain`, `whats_new`, `open_dashboard`

The response builders are pure functions so they can be tested without starting a server. The MCP tool bodies stay thin wrappers around them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_server_tools.py`:

```python
from har_search.core.models import (
    Listing,
    ListingChange,
    MoneyRange,
    ParamScore,
    ScoredListing,
    Valuation,
)
from har_search.pipeline import SearchResult
from har_search.server.__main__ import (
    build_explain_response,
    build_search_response,
    build_whats_new_response,
)


def make_result() -> SearchResult:
    listing = Listing(
        listing_id="L1",
        address="5519 Lynngate Dr",
        subdivision="Greengate Place Sec 06",
        price=215_000,
        price_per_sqft=142.38,
        beds=3,
        baths_full=2,
        sqft=1510,
        days_on_market=1,
    )
    scored = ScoredListing(
        listing=listing,
        score=0.91,
        coverage=0.85,
        params=[ParamScore("beds", 1.0, 2.0, True, "3 bd vs 3 bd wanted")],
        why="Matches every requested criterion.",
    )
    valuation = Valuation(
        comp_estimate=231_000,
        comp_count=6,
        comp_basis="sold",
        confidence="medium",
        delta_pct=-0.069,
        appraisal_district=MoneyRange(205_000, 205_999),
        spread_flag="clustered",
    )
    return SearchResult(
        snapshot_id=7,
        scored=[scored],
        valuations={"L1": valuation},
        exclusions={"lease": 2},
        dropped_by_must=1,
    )


def test_search_response_includes_score_kpi_and_coverage():
    payload = build_search_response(make_result(), limit=10, dashboard_url="http://x/run/7")
    row = payload["results"][0]
    assert row["address"] == "5519 Lynngate Dr"
    assert row["score"] == 0.91
    assert row["coverage"] == 0.85
    assert row["estimated_value"] == 231_000
    assert row["comp_count"] == 6
    assert row["delta_pct"] == -0.069


def test_search_response_surfaces_data_quality_counts():
    payload = build_search_response(make_result(), limit=10, dashboard_url="http://x/run/7")
    assert payload["excluded"]["lease"] == 2
    assert payload["dropped_by_must"] == 1


def test_search_response_carries_the_dashboard_url_and_snapshot():
    payload = build_search_response(make_result(), limit=10, dashboard_url="http://x/run/7")
    assert payload["dashboard_url"] == "http://x/run/7"
    assert payload["snapshot_id"] == 7


def test_search_response_respects_limit():
    result = make_result()
    result.scored = result.scored * 5
    payload = build_search_response(result, limit=2, dashboard_url="http://x/run/7")
    assert len(payload["results"]) == 2


def test_explain_response_returns_breakdown_and_comps():
    row = {
        "listing": Listing(listing_id="L1", address="5519 Lynngate Dr", price=215_000),
        "score": 0.91,
        "coverage": 0.85,
        "why": "Matches every requested criterion.",
        "params": [
            {"name": "beds", "score": 1.0, "weight": 2.0, "known": True, "detail": "3 bd"}
        ],
        "valuation": {"comp_estimate": 231_000, "comp_count": 6, "confidence": "medium"},
    }
    comps = [{"id": "M1", "price": 360_000, "distance_miles": 0.4}]
    payload = build_explain_response(row, comps)
    assert payload["why"]
    assert payload["params"][0]["name"] == "beds"
    assert payload["valuation"]["comp_count"] == 6
    assert payload["comps"][0]["id"] == "M1"


def test_whats_new_groups_changes_by_type():
    changes = [
        ListingChange("A", "NEW", None, 200_000, "1 Main"),
        ListingChange("B", "PRICE_CUT", 300_000, 280_000, "2 Main"),
        ListingChange("C", "UNCHANGED", 400_000, 400_000, "3 Main"),
        ListingChange("D", "GONE", 500_000, None, "4 Main"),
    ]
    payload = build_whats_new_response(changes)
    assert len(payload["new"]) == 1
    assert len(payload["price_cut"]) == 1
    assert len(payload["gone"]) == 1
    assert payload["unchanged_count"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_server_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'har_search.server'`

- [ ] **Step 3: Write `src/har_search/config.py`**

```python
"""User configuration, supplied by the MCPB host as environment variables."""

from __future__ import annotations

import os
from pathlib import Path


def apify_token() -> str:
    token = os.environ.get("HAR_APIFY_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "No Apify token configured. Set it in the extension's settings."
        )
    return token


def default_area() -> str:
    return os.environ.get("HAR_DEFAULT_AREA", "Spring")


def dashboard_port() -> int:
    return int(os.environ.get("HAR_DASHBOARD_PORT", "7788"))


def database_path() -> Path:
    raw = os.environ.get("HAR_DB_PATH")
    if raw:
        return Path(raw)
    directory = Path.home() / ".har-smart-search"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "har.db"
```

- [ ] **Step 4: Write `src/har_search/server/__main__.py`**

Create an empty `src/har_search/server/__init__.py`, then:

```python
"""FastMCP entrypoint.

The model fills in criteria and narrates results. It never computes a KPI —
every number in a response was produced by har_search.core.
"""

from __future__ import annotations

from datetime import date

from mcp.server.fastmcp import FastMCP

from har_search import config
from har_search.core.diff import diff_snapshots
from har_search.core.models import Criteria, ListingChange
from har_search.pipeline import SearchResult, run_search
from har_search.sources.apify_memo23 import ApifyMemo23Source
from har_search.store.db import Database
from har_search.web.app import ensure_dashboard_running

mcp = FastMCP("har-smart-search")


def _db() -> Database:
    db = Database(config.database_path())
    db.init_schema()
    return db


def _change_row(change: ListingChange) -> dict:
    return {
        "listing_id": change.listing_id,
        "address": change.address,
        "old_price": change.old_price,
        "new_price": change.new_price,
    }


def build_search_response(
    result: SearchResult, limit: int, dashboard_url: str
) -> dict:
    rows = []
    for scored in result.scored[:limit]:
        listing = scored.listing
        valuation = result.valuations.get(listing.listing_id)
        rows.append(
            {
                "listing_id": listing.listing_id,
                "address": listing.address,
                "subdivision": listing.subdivision,
                "price": listing.price,
                "price_per_sqft": listing.price_per_sqft,
                "beds": listing.beds,
                "baths_full": listing.baths_full,
                "sqft": listing.sqft,
                "days_on_market": listing.days_on_market,
                "score": scored.score,
                "coverage": scored.coverage,
                "why": scored.why,
                "estimated_value": valuation.comp_estimate if valuation else None,
                "comp_count": valuation.comp_count if valuation else 0,
                "comp_basis": valuation.comp_basis if valuation else "none",
                "confidence": valuation.confidence if valuation else "insufficient",
                "delta_pct": valuation.delta_pct if valuation else None,
            }
        )
    return {
        "snapshot_id": result.snapshot_id,
        "dashboard_url": dashboard_url,
        "results": rows,
        "excluded": result.exclusions,
        "dropped_by_must": result.dropped_by_must,
    }


def build_explain_response(row: dict, comps: list[dict]) -> dict:
    listing = row["listing"]
    return {
        "listing_id": listing.listing_id,
        "address": listing.address,
        "price": listing.price,
        "score": row["score"],
        "coverage": row["coverage"],
        "why": row["why"],
        "params": row["params"],
        "valuation": row["valuation"],
        "comps": comps,
    }


def build_whats_new_response(changes: list[ListingChange]) -> dict:
    buckets: dict[str, list[dict]] = {
        "new": [],
        "price_cut": [],
        "price_up": [],
        "gone": [],
    }
    unchanged = 0
    for change in changes:
        if change.change_type == "UNCHANGED":
            unchanged += 1
            continue
        buckets[change.change_type.lower()].append(_change_row(change))
    return {**buckets, "unchanged_count": unchanged}


@mcp.tool()
def search(
    area: str,
    beds: int | None = None,
    baths: int | None = None,
    garage_spaces: int | None = None,
    sqft: int | None = None,
    max_price: int | None = None,
    max_price_per_sqft: float | None = None,
    property_types: list[str] | None = None,
    no_hoa: bool | None = None,
    max_age_years: int | None = None,
    limit: int = 25,
) -> dict:
    """Search HAR listings by loose criteria and rank them by similarity.

    Every result carries a similarity score, a coverage figure showing how
    many requested criteria were actually published, and a value KPI derived
    from comparable sales.
    """
    criteria = Criteria(
        area=area,
        beds=beds,
        baths=baths,
        garage_spaces=garage_spaces,
        sqft=sqft,
        max_price=max_price,
        max_price_per_sqft=max_price_per_sqft,
        property_types=property_types,
        no_hoa=no_hoa,
        max_age_years=max_age_years,
    )
    db = _db()
    source = ApifyMemo23Source(token=config.apify_token())
    result = run_search(source, db, criteria, saved_search=area, limit=limit)
    base = ensure_dashboard_running(config.dashboard_port())
    return build_search_response(
        result, limit, dashboard_url=f"{base}/run/{result.snapshot_id}"
    )


@mcp.tool()
def explain(listing_id: str, snapshot_id: int) -> dict:
    """Show the full similarity breakdown and comparable sales for one listing."""
    db = _db()
    rows = db.get_scored_rows(snapshot_id)
    row = next((r for r in rows if r["listing"].listing_id == listing_id), None)
    if row is None:
        return {"error": f"No listing {listing_id} in snapshot {snapshot_id}."}

    listing = row["listing"]
    comps = []
    if listing.lat is not None and listing.lon is not None:
        from datetime import timedelta

        sales = db.sales_near(
            listing.lat, listing.lon, 2.0, date.today() - timedelta(days=365)
        )
        wanted = set(row["valuation"].get("comp_ids", []))
        comps = [
            {
                "id": sale.mls_number,
                "address": sale.address,
                "sold_price": sale.sold_price,
                "sold_date": sale.sold_date.isoformat(),
                "sqft": sale.sqft,
                "price_per_sqft": sale.sold_price_per_sqft,
            }
            for sale in sales
            if sale.mls_number in wanted
        ]
    return build_explain_response(row, comps)


@mcp.tool()
def whats_new(saved_search: str) -> dict:
    """Compare the two most recent runs of a saved search."""
    db = _db()
    snapshots = db.recent_snapshots(saved_search, limit=2)
    if len(snapshots) < 2:
        return {
            "error": "Only one snapshot exists so far. Run the search again later"
            " to see what changed."
        }
    current = db.get_snapshot_listings(snapshots[0]["id"])
    previous = db.get_snapshot_listings(snapshots[1]["id"])
    return build_whats_new_response(diff_snapshots(previous, current))


@mcp.tool()
def open_dashboard() -> dict:
    """Return the URL of the local dashboard."""
    return {"dashboard_url": ensure_dashboard_running(config.dashboard_port())}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_server_tools.py -v`
Expected: all passed. This task depends on `har_search.web.app.ensure_dashboard_running`, which Task 13 creates — if the import fails, complete Task 13 first and rerun.

- [ ] **Step 6: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add src/har_search/server src/har_search/config.py tests/test_server_tools.py
git commit -m "feat: expose search, explain and whats_new as MCP tools"
```

---

## Task 13: Local dashboard

**Files:**
- Create: `src/har_search/web/__init__.py`, `src/har_search/web/app.py`, `src/har_search/web/templates/base.html`, `src/har_search/web/templates/index.html`, `src/har_search/web/templates/run.html`, `src/har_search/web/templates/listing.html`, `src/har_search/web/templates/diff.html`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `Database`, `diff_snapshots`
- Produces: `create_app(db_factory) -> Starlette`, `ensure_dashboard_running(port) -> str`, `kpi_chip(delta_pct) -> tuple[str, str]`

Build this task before Task 12 if you are working strictly in order — Task 12 imports `ensure_dashboard_running`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_web.py`:

```python
from datetime import date

from starlette.testclient import TestClient

from har_search.core.models import Listing, ScoredListing, Valuation
from har_search.store.db import Database
from har_search.web.app import create_app, kpi_chip


def seed(tmp_path) -> tuple[Database, int]:
    db = Database(tmp_path / "web.db")
    db.init_schema()
    snapshot_id = db.create_snapshot("spring", "fixture", 1, 1, {"lease": 1})
    listing = Listing(
        listing_id="L1",
        address="5519 Lynngate Dr",
        subdivision="Greengate Place Sec 06",
        price=215_000,
        price_per_sqft=142.38,
        beds=3,
        baths_full=2,
        sqft=1510,
        lat=30.036,
        lon=-95.342,
    )
    db.insert_scored(
        snapshot_id,
        [ScoredListing(listing, 0.91, 0.85, [], "Matches every requested criterion.")],
        {"L1": Valuation(comp_estimate=231_000, comp_count=6, confidence="medium", delta_pct=-0.069)},
    )
    return db, snapshot_id


def client_for(tmp_path):
    db, snapshot_id = seed(tmp_path)
    return TestClient(create_app(lambda: db)), snapshot_id


def test_kpi_chip_labels_below_and_above_comps():
    label, tone = kpi_chip(-0.069)
    assert "below" in label.lower()
    assert tone == "good"

    label, tone = kpi_chip(0.12)
    assert "above" in label.lower()
    assert tone == "bad"

    label, tone = kpi_chip(None)
    assert tone == "neutral"


def test_run_page_lists_the_listing_with_score_and_kpi(tmp_path):
    client, snapshot_id = client_for(tmp_path)
    response = client.get(f"/run/{snapshot_id}")
    assert response.status_code == 200
    assert "5519 Lynngate Dr" in response.text
    assert "$215,000" in response.text
    assert "231,000" in response.text


def test_run_page_shows_evidence_count_next_to_every_estimate(tmp_path):
    client, snapshot_id = client_for(tmp_path)
    response = client.get(f"/run/{snapshot_id}")
    assert "6 comps" in response.text


def test_run_page_reports_excluded_rows(tmp_path):
    client, snapshot_id = client_for(tmp_path)
    response = client.get(f"/run/{snapshot_id}")
    assert "lease" in response.text.lower()


def test_listing_page_renders_the_explanation(tmp_path):
    client, snapshot_id = client_for(tmp_path)
    response = client.get(f"/run/{snapshot_id}/listing/L1")
    assert response.status_code == 200
    assert "Matches every requested criterion." in response.text


def test_missing_listing_returns_404(tmp_path):
    client, snapshot_id = client_for(tmp_path)
    assert client.get(f"/run/{snapshot_id}/listing/NOPE").status_code == 404


def test_index_lists_saved_searches(tmp_path):
    client, _ = client_for(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "spring" in response.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'har_search.web'`

- [ ] **Step 3: Write `src/har_search/web/app.py`**

Create an empty `src/har_search/web/__init__.py`, then:

```python
"""Local dashboard.

Every estimate is rendered with the number of comps behind it. A bare
figure would imply a confidence the data does not support.
"""

from __future__ import annotations

import threading
from pathlib import Path

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import RedirectResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from har_search.core.diff import diff_snapshots

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_server_thread: threading.Thread | None = None


def kpi_chip(delta_pct: float | None) -> tuple[str, str]:
    """Return (label, tone) for the value KPI."""
    if delta_pct is None:
        return ("No estimate", "neutral")
    percent = abs(delta_pct) * 100
    if delta_pct < 0:
        return (f"{percent:.0f}% below comps", "good")
    if delta_pct > 0:
        return (f"{percent:.0f}% above comps", "bad")
    return ("At comps", "neutral")


def create_app(db_factory) -> Starlette:
    def index(request):
        db = db_factory()
        rows = db._conn.execute(
            "SELECT saved_search, MAX(id) AS id, MAX(run_at) AS run_at,"
            " MAX(item_count) AS item_count FROM snapshots GROUP BY saved_search"
        ).fetchall()
        return TEMPLATES.TemplateResponse(
            request, "index.html", {"searches": [dict(r) for r in rows]}
        )

    def run_page(request):
        db = db_factory()
        snapshot_id = int(request.path_params["snapshot_id"])
        snapshot = db._conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No such snapshot")
        rows = db.get_scored_rows(snapshot_id)
        for row in rows:
            row["chip"] = kpi_chip(row["valuation"].get("delta_pct"))
        return TEMPLATES.TemplateResponse(
            request,
            "run.html",
            {"snapshot": dict(snapshot), "rows": rows, "snapshot_id": snapshot_id},
        )

    def listing_page(request):
        db = db_factory()
        snapshot_id = int(request.path_params["snapshot_id"])
        listing_id = request.path_params["listing_id"]
        rows = db.get_scored_rows(snapshot_id)
        row = next((r for r in rows if r["listing"].listing_id == listing_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail="No such listing")
        row["chip"] = kpi_chip(row["valuation"].get("delta_pct"))
        return TEMPLATES.TemplateResponse(
            request, "listing.html", {"row": row, "snapshot_id": snapshot_id}
        )

    def diff_page(request):
        db = db_factory()
        snapshot_id = int(request.path_params["snapshot_id"])
        snapshot = db._conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No such snapshot")
        previous_row = db._conn.execute(
            "SELECT id FROM snapshots WHERE saved_search = ? AND id < ?"
            " ORDER BY id DESC LIMIT 1",
            (snapshot["saved_search"], snapshot_id),
        ).fetchone()
        previous = (
            db.get_snapshot_listings(previous_row["id"]) if previous_row else []
        )
        changes = diff_snapshots(previous, db.get_snapshot_listings(snapshot_id))
        return TEMPLATES.TemplateResponse(
            request,
            "diff.html",
            {
                "changes": [c for c in changes if c.change_type != "UNCHANGED"],
                "has_previous": previous_row is not None,
                "snapshot_id": snapshot_id,
            },
        )

    return Starlette(
        routes=[
            Route("/", index),
            Route("/run/{snapshot_id:int}", run_page),
            Route("/run/{snapshot_id:int}/listing/{listing_id:str}", listing_page),
            Route("/run/{snapshot_id:int}/diff", diff_page),
        ]
    )


def ensure_dashboard_running(port: int) -> str:
    """Start the dashboard in a background thread, once."""
    global _server_thread
    base = f"http://127.0.0.1:{port}"
    if _server_thread is not None and _server_thread.is_alive():
        return base

    import uvicorn

    from har_search import config
    from har_search.store.db import Database

    def factory():
        db = Database(config.database_path())
        db.init_schema()
        return db

    app = create_app(factory)

    def serve():
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

    _server_thread = threading.Thread(target=serve, daemon=True)
    _server_thread.start()
    return base
```

- [ ] **Step 4: Write the templates**

`src/har_search/web/templates/base.html`:

```html
<!doctype html>
<title>{% block title %}HAR Smart Search{% endblock %}</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 14px/1.5 system-ui, sans-serif; margin: 0; padding: 24px; }
  h1, h2 { margin: 0 0 12px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #8883; }
  th { font-weight: 600; font-size: 12px; text-transform: uppercase; opacity: .7; }
  .chip { padding: 2px 8px; border-radius: 999px; font-size: 12px; white-space: nowrap; }
  .good { background: #16a34a22; color: #16a34a; }
  .bad { background: #dc262622; color: #dc2626; }
  .neutral { background: #8881; opacity: .8; }
  .bar { height: 6px; background: #8883; border-radius: 3px; width: 90px; }
  .bar > span { display: block; height: 100%; background: #2563eb; border-radius: 3px; }
  .muted { opacity: .65; font-size: 12px; }
  a { color: inherit; }
</style>
<body>{% block body %}{% endblock %}</body>
```

`src/har_search/web/templates/index.html`:

```html
{% extends "base.html" %}
{% block body %}
<h1>Saved searches</h1>
<table>
  <tr><th>Search</th><th>Last run</th><th>Results</th></tr>
  {% for s in searches %}
  <tr>
    <td><a href="/run/{{ s.id }}">{{ s.saved_search }}</a></td>
    <td>{{ s.run_at }}</td>
    <td>{{ s.item_count }}</td>
  </tr>
  {% endfor %}
</table>
{% endblock %}
```

`src/har_search/web/templates/run.html`:

```html
{% extends "base.html" %}
{% block body %}
<h1>Results — {{ snapshot.saved_search }}</h1>
<p class="muted">
  Run {{ snapshot.run_at }} · {{ snapshot.item_count }} results ·
  <a href="/run/{{ snapshot_id }}/diff">what changed</a>
</p>
<table>
  <tr>
    <th>Address</th><th>Price</th><th>$/sqft</th><th>Bd/Ba</th>
    <th>Match</th><th>Coverage</th><th>Value KPI</th><th>DOM</th>
  </tr>
  {% for row in rows %}
  {% set l = row.listing %}
  <tr>
    <td><a href="/run/{{ snapshot_id }}/listing/{{ l.listing_id }}">{{ l.address }}</a>
        <div class="muted">{{ l.subdivision or "" }}</div></td>
    <td>{% if l.price %}${{ "{:,}".format(l.price) }}{% else %}—{% endif %}</td>
    <td>{% if l.price_per_sqft %}${{ "%.0f"|format(l.price_per_sqft) }}{% else %}—{% endif %}</td>
    <td>{{ l.beds if l.beds is not none else "?" }}/{{ l.baths_full if l.baths_full is not none else "?" }}</td>
    <td><div class="bar"><span style="width: {{ (row.score * 100)|round }}%"></span></div>
        <span class="muted">{{ "%.2f"|format(row.score) }}</span></td>
    <td class="muted">{{ (row.coverage * 100)|round|int }}%</td>
    <td>
      <span class="chip {{ row.chip[1] }}">{{ row.chip[0] }}</span>
      {% if row.valuation.comp_estimate %}
      <div class="muted">${{ "{:,}".format(row.valuation.comp_estimate) }}, {{ row.valuation.comp_count }} comps</div>
      {% endif %}
    </td>
    <td class="muted">{{ l.days_on_market if l.days_on_market is not none else "—" }}</td>
  </tr>
  {% endfor %}
</table>
<p class="muted">
  {{ snapshot.excluded_count }} rows excluded for data quality
  {% if snapshot.exclusions_json %}— {{ snapshot.exclusions_json }}{% endif %}
</p>
{% endblock %}
```

`src/har_search/web/templates/listing.html`:

```html
{% extends "base.html" %}
{% block body %}
{% set l = row.listing %}
<h1>{{ l.address }}</h1>
<p class="muted">{{ l.subdivision or "" }} · <a href="/run/{{ snapshot_id }}">back to results</a></p>

<h2>Why this appeared</h2>
<p>{{ row.why }}</p>
<table>
  <tr><th>Criterion</th><th>Score</th><th>Detail</th></tr>
  {% for p in row.params %}
  <tr>
    <td>{{ p.name }}</td>
    <td>{% if p.known %}<div class="bar"><span style="width: {{ (p.score * 100)|round }}%"></span></div>{% else %}<span class="muted">unknown</span>{% endif %}</td>
    <td class="muted">{{ p.detail }}</td>
  </tr>
  {% endfor %}
</table>

<h2>Valuation</h2>
<p>
  <span class="chip {{ row.chip[1] }}">{{ row.chip[0] }}</span>
</p>
<table>
  <tr><th>Source</th><th>Value</th><th>Evidence</th></tr>
  <tr>
    <td>Comparable sales</td>
    <td>{% if row.valuation.comp_estimate %}${{ "{:,}".format(row.valuation.comp_estimate) }}{% else %}Not enough comps{% endif %}</td>
    <td class="muted">{{ row.valuation.comp_count }} comps, {{ row.valuation.comp_basis }}, {{ row.valuation.confidence }} confidence</td>
  </tr>
  {% if row.valuation.appraisal_district %}
  <tr>
    <td>Appraisal district</td>
    <td>${{ "{:,}".format(row.valuation.appraisal_district.low) }}–${{ "{:,}".format(row.valuation.appraisal_district.high) }}</td>
    <td class="muted">county assessment, lags the market</td>
  </tr>
  {% endif %}
  {% if row.valuation.subdivision_list_to_sold %}
  <tr>
    <td>Subdivision list-to-sold</td>
    <td>{{ "%.1f"|format(row.valuation.subdivision_list_to_sold * 100) }}%</td>
    <td class="muted">median of closed sales nearby</td>
  </tr>
  {% endif %}
</table>
<p class="muted">Sources {{ row.valuation.spread_flag }}.</p>
{% endblock %}
```

`src/har_search/web/templates/diff.html`:

```html
{% extends "base.html" %}
{% block body %}
<h1>What changed</h1>
<p class="muted"><a href="/run/{{ snapshot_id }}">back to results</a></p>
{% if not has_previous %}
<p>Only one run so far. Run this search again later to see what changed.</p>
{% else %}
<table>
  <tr><th>Change</th><th>Address</th><th>Was</th><th>Now</th></tr>
  {% for c in changes %}
  <tr>
    <td>{{ c.change_type }}</td>
    <td>{{ c.address }}</td>
    <td>{% if c.old_price %}${{ "{:,}".format(c.old_price) }}{% else %}—{% endif %}</td>
    <td>{% if c.new_price %}${{ "{:,}".format(c.new_price) }}{% else %}—{% endif %}</td>
  </tr>
  {% endfor %}
</table>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_web.py -v`
Expected: all passed

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -v`
Expected: all passed, including Task 12's tests which import from this module

- [ ] **Step 7: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add src/har_search/web tests/test_web.py
git commit -m "feat: add local dashboard with results, listing and diff screens"
```

---

## Task 14: MCPB packaging and a smoke run

**Files:**
- Create: `manifest.json`, `BUNDLE.md`, `scripts/smoke_run.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: everything
- Produces: a loadable `manifest.json` and a manual smoke script

- [ ] **Step 1: Write the failing test**

Create `tests/test_manifest.py`:

```python
import json
from pathlib import Path

MANIFEST = Path(__file__).parent.parent / "manifest.json"


def test_manifest_is_valid_json_with_required_keys():
    data = json.loads(MANIFEST.read_text())
    assert data["name"] == "har-smart-search"
    assert data["server"]["type"] == "python"
    assert data["server"]["entry_point"].endswith("server/__main__.py")


def test_apify_token_is_marked_sensitive_and_required():
    data = json.loads(MANIFEST.read_text())
    token = data["user_config"]["apify_token"]
    assert token["sensitive"] is True
    assert token["required"] is True


def test_token_is_passed_to_the_server_as_an_env_var():
    data = json.loads(MANIFEST.read_text())
    env = data["server"]["mcp_config"]["env"]
    assert env["HAR_APIFY_TOKEN"] == "${user_config.apify_token}"
    assert env["HAR_DASHBOARD_PORT"] == "${user_config.dashboard_port}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: FAIL with `FileNotFoundError`

- [ ] **Step 3: Write `manifest.json`**

```json
{
  "manifest_version": "0.1",
  "name": "har-smart-search",
  "display_name": "HAR Smart Search",
  "version": "0.1.0",
  "description": "Similarity search and comparable-sales valuation over HAR listings.",
  "author": { "name": "Jesse Henson" },
  "server": {
    "type": "python",
    "entry_point": "src/har_search/server/__main__.py",
    "mcp_config": {
      "command": "python",
      "args": ["${__dirname}/src/har_search/server/__main__.py"],
      "env": {
        "PYTHONPATH": "${__dirname}/src:${__dirname}/lib",
        "HAR_APIFY_TOKEN": "${user_config.apify_token}",
        "HAR_DEFAULT_AREA": "${user_config.default_area}",
        "HAR_DASHBOARD_PORT": "${user_config.dashboard_port}"
      }
    }
  },
  "tools": [
    { "name": "search", "description": "Search HAR listings by loose criteria and rank by similarity." },
    { "name": "explain", "description": "Show the similarity breakdown and comparable sales for one listing." },
    { "name": "whats_new", "description": "Compare the two most recent runs of a saved search." },
    { "name": "open_dashboard", "description": "Return the local dashboard URL." }
  ],
  "user_config": {
    "apify_token": {
      "type": "string",
      "title": "Apify API token",
      "description": "Used to fetch HAR listing data. Stored locally, never shared.",
      "sensitive": true,
      "required": true
    },
    "default_area": {
      "type": "string",
      "title": "Default area",
      "default": "Spring",
      "required": false
    },
    "dashboard_port": {
      "type": "number",
      "title": "Dashboard port",
      "default": 7788,
      "required": false
    }
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: all passed

- [ ] **Step 5: Write `scripts/smoke_run.py`**

This is the only code that touches the network, run by hand before the demo.

```python
"""Manual smoke run against live data. Not part of the test suite.

Usage:
    HAR_APIFY_TOKEN=... uv run python scripts/smoke_run.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, "src")

from har_search.core.models import Criteria
from har_search.pipeline import run_search
from har_search.sources.apify_memo23 import ApifyMemo23Source
from har_search.store.db import Database


def main() -> None:
    token = os.environ.get("HAR_APIFY_TOKEN")
    if not token:
        raise SystemExit("Set HAR_APIFY_TOKEN first.")

    db = Database("smoke.db")
    db.init_schema()

    criteria = Criteria(
        area="Spring",
        beds=3,
        baths=2,
        garage_spaces=1,
        max_price_per_sqft=120,
        no_hoa=True,
        must=["area"],
    )
    result = run_search(
        source=ApifyMemo23Source(token=token),
        db=db,
        criteria=criteria,
        saved_search="spring-investment",
        limit=25,
    )

    print(f"snapshot {result.snapshot_id}: {len(result.scored)} results")
    print(f"excluded: {result.exclusions}, dropped by must: {result.dropped_by_must}")
    for scored in result.scored[:10]:
        listing = scored.listing
        valuation = result.valuations[listing.listing_id]
        delta = (
            f"{valuation.delta_pct * 100:+.0f}%" if valuation.delta_pct is not None else "n/a"
        )
        print(
            f"  {scored.score:.2f}  cov {scored.coverage:.0%}  "
            f"${listing.price or 0:,}  {listing.address}  "
            f"KPI {delta} ({valuation.comp_count} comps)"
        )
        print(f"        {scored.why}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Write `BUNDLE.md`**

```markdown
# HAR Smart Search — build and install

## Build

    cd "/Users/jessehenson/Development/HAR Real Estate Work"
    uv sync
    uv pip install --target lib -r <(uv export --no-hashes --no-dev)
    npx @anthropic-ai/mcpb pack

Dependencies are vendored into `lib/` so the bundle installs without a
Python environment on the host.

## Install

Open the generated `.mcpb` in Claude Desktop and supply an Apify API token
when prompted.

## Smoke test before a demo

    HAR_APIFY_TOKEN=... uv run python scripts/smoke_run.py

Run this once several days before the demo and again on the day, so
`whats_new` has two genuine snapshots to compare.
```

- [ ] **Step 7: Run the whole suite and the smoke script**

Run: `uv run pytest -v`
Expected: every test passes

Then, with a real token:

Run: `HAR_APIFY_TOKEN=... uv run python scripts/smoke_run.py`
Expected: a printed ranked list where at least one result is a 4-bedroom scoring above 0.8 against a 3-bedroom request, and at least one result carries a non-null KPI with a comp count

- [ ] **Step 8: Commit**

```bash
cd "/Users/jessehenson/Development/HAR Real Estate Work"
git add manifest.json BUNDLE.md scripts tests/test_manifest.py
git commit -m "feat: package as an MCPB bundle with a live smoke run"
```

---

## Task Order Note

Task 12 imports `ensure_dashboard_running` from Task 13's module. If you are executing strictly in numeric order, complete Task 13 before running Task 12's test suite, or stub the import temporarily. Every other task depends only on tasks numbered below it.
