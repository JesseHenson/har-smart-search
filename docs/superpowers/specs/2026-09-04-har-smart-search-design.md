# HAR Smart Search — Design Spec

**Date:** 2026-09-04
**Status:** Approved for implementation planning
**Inputs:** `meeting_saved_closed_caption.txt` (discovery call), `README.md` (requirements), `RECON.md` (verified data reality)

---

## 1. What we're building

A one-click-installable MCP bundle that lets a Texas real-estate investor describe a deal in loose language, get back a ranked shortlist of live HAR listings, and see for every result whether it is priced above or below what comparable nearby properties actually sold for — repeatable weekly, with a dashboard.

The division of labour is the whole design:

- **The model** turns "3 bed, 2 bath, one-car garage, Spring, around $120 a foot, no HOA" into structured criteria, and narrates results in plain language.
- **The server** does every piece of arithmetic — normalization, similarity scoring, comparable selection, valuation, week-over-week diffing — deterministically, in Python, where it can be unit-tested.

No KPI is ever produced by a language model.

## 2. Requirements traced to components

| Req | From the call | Component |
|---|---|---|
| **R1** Similarity search, not a filter | "you're not just doing a filter, you're actually doing a similarity finder" | `core/scoring.py` |
| **R2** Per-listing value KPI from nearby comps | "nearby houses, very similar, are going to go for maybe 20,000 more" | `core/comps.py` |
| **R3** Weekly re-runnable scan + dashboard | "every week I can run that, show me all the investments, everything that's come up" | `store/`, `web/` |

## 3. Architecture

```
har-smart-search/
  manifest.json            MCPB manifest
  pyproject.toml           uv-managed
  src/har_search/
    server/__main__.py     FastMCP entrypoint, tool definitions
    sources/
      base.py              ListingSource protocol
      apify_memo23.py      default adapter
    core/
      models.py            Listing, Sale, Criteria, ScoredListing, Valuation
      normalize.py         parsers + sanity guards
      scoring.py           similarity
      comps.py             comparable selection + valuation
      diff.py              snapshot comparison
    store/
      schema.sql
      db.py                SQLite access
    web/
      app.py               Starlette dashboard
      templates/
  tests/
```

Dependency direction is strictly inward: `server` and `web` depend on `core`; `core` depends on nothing but `models`. `sources` is the only outward-facing layer and is swappable.

### 3.1 Why the source layer is an interface

Recon established three possible data paths — a licensed MLS feed, managed scraping vendors, and nothing else viable. We are building on a vendor today because the prospect's MLS status is unknown. When that answer arrives the adapter is replaced and nothing above it changes.

```python
class ListingSource(Protocol):
    def fetch_for_sale(self, criteria: Criteria, limit: int) -> list[dict]: ...
    def fetch_sold(self, area: str, agent_depth: int, limit: int) -> list[dict]: ...
    def fetch_by_address(self, address: str) -> dict | None: ...
```

Adapters return raw vendor dicts. Normalization is deliberately *not* the adapter's job — it lives in `core` so every source gets the same guards.

## 4. Normalization contract

The single most important rule in the codebase:

> **`None` means unknown. Unknown never becomes zero, and never becomes a default.**

Recon found multi-family listings where `beds`, `garage` and `maintenanceFee` are all empty. Coercing those to zero would rank every duplex last — the exact opposite of what the user asked for.

### 4.1 Parsers

| Function | Input observed in live data | Output |
|---|---|---|
| `parse_garage` | `"3 Attached ,Oversized ,Tandem"`, `"2 Detached ,Oversized"`, `null` | `GarageInfo(spaces, attached, tags) \| None` |
| `parse_hoa` | `"$1075 Annually"`, `"$325 Monthly"`, `null` | `HOA(monthly_usd) \| None` — **null is unknown, not "no HOA"** |
| `parse_lot` | `"13,987 sqft"`, `"1.1 acre(s)"`, `"0 sqft"` | `int sqft \| None` (`"0 sqft"` → `None`) |
| `parse_money_abbrev` | `"$1.0M"`, `"$352K"`, `"$205K"` | `MoneyRange(low, high)` — the figure is treated as truncated at its own precision, so `"$1.0M"` becomes `1_000_000–1_099_999` and the range always contains the true value |
| `canon_property_type` | `"Single-Family"`, `"Single Family"`, `"Multi-Family - Duplex"` | `(PropertyType, is_lease: bool)` |
| `parse_unit_designator` | `"5013 Longmeadow St A/b"`, `"214 E 32nd St C-d"` | `DuplexScope.WHOLE \| DuplexScope.UNKNOWN` |

`canon_property_type` carries the hyphen trap. In HAR's data `"Single Family"` (no hyphen) marks a *lease* record and `"Single-Family"` marks a *sale* record. Anything matching on property type without this normalization silently mixes leases into comps.

### 4.2 Sanity guards

Applied after parsing, before anything reaches scoring or comps:

| Guard | Rule | Action |
|---|---|---|
| Lease bleed | `status == "Rented"` or `is_lease` | Exclude from sale results and from comps |
| Price floor | Sale-context price < $10,000 | Exclude, log |
| Implausible beds | `beds > 8` and `sqft < 5000` | Keep, set `beds = None`, flag `suspect_beds` |
| Missing area | `sqft is None` | Keep; `$/sqft` unavailable; excluded from comp *pool* but still scorable |
| Zero lot | `lotSize == "0 sqft"` | `None` |

Every excluded row is recorded with its reason and surfaced in the dashboard as a data-quality count. Silent dropping is not acceptable — the user needs to know when the market is thinner than it looks.

This applies to **sold** rows as much as for-sale ones, and the two counts are kept and shown separately. A for-sale exclusion thins the results table; a sold exclusion thins the comparable-sale evidence behind every KPI in that table. Leases arriving inside a sold query are the most dangerous defect in this domain, so `normalize_sale` returns a reason exactly as `normalize_listing` does, and the dashboard footer reports the two counts distinctly.

The implausible-beds guard applies on both paths for the same reason: recon's named bad row — 2322 Shadow Glen, 10 bedrooms on 4,507 sqft — is a *sold* record, and an unguarded copy of it feeds the bedroom-adjustment median in §6.2.

## 5. Similarity scoring (R1)

### 5.1 Shape

Each requested parameter produces a score in `[0, 1]` and carries a weight. The overall score is the weighted mean **over known parameters only**:

```
score    = Σ(wᵢ · sᵢ) / Σ(wᵢ)      for i where the listing's value is known
coverage = Σ(wᵢ known) / Σ(wᵢ requested)
```

`coverage` is reported alongside every score and rendered in the dashboard. A 0.92 computed from three of seven requested parameters is a materially different claim from a 0.92 computed from all seven, and the product says so.

### 5.2 Scoring functions

One rational family throughout, chosen because it decays gently near the target and has a long tolerant tail — which is what "similarity finder, not filter" means in practice.

**Target parameters** — beds, baths, garage spaces, sqft, year built. Overshooting is cheap; undershooting hurts.

```
δ = actual − target
s = 1 / (1 + (δ / τ_over)²)     if δ ≥ 0
s = 1 / (1 + (δ / τ_under)²)    if δ < 0
```

Defaults for bedrooms (`τ_over = 2.4`, `τ_under = 0.82`, δ in bedrooms):

| Actual vs target 3 | Score |
|---|---|
| 3 beds | 1.00 |
| 4 beds | 0.85 |
| 5 beds | 0.59 |
| 2 beds | 0.40 |
| 1 bed | 0.14 |

This is the call's example working: *"you might be able to show me a 4-bedroom house, but in the same price range, same area, same number of bathrooms."*

**Ceiling parameters** — price, price per sqft. At or under budget is perfect; over decays.

```
over = max(0, x − ceiling) / ceiling
s    = 1 / (1 + (over / τ)²)          τ = 0.16
```

| Over budget | Score |
|---|---|
| at or under | 1.00 |
| +10% | 0.72 |
| +25% | 0.29 |
| +50% | 0.09 |

This is *"then you may show me some houses above $200,000, if the search result is not there for below."*

**Geographic** — subdivision match is exact; otherwise straight-line distance from the search area centroid.

```
s = 1.0                                  if subdivision matches
s = 1 / (1 + (miles / 3.0)²)             otherwise
```

**Categorical** — property type. Exact match `1.0`; sibling within the same family (Duplex ↔ Fourplex ↔ Multi-Family) `0.5`; unrelated `0.0`.

**Ordinal** — school rating, averaged over whichever assigned levels are present:

`A → 1.0 · B → 0.8 · C → 0.6 · D → 0.35 · F → 0.0`

**Boolean** — HOA. `no_hoa` requested and `hoa is None` scores as **unknown, not satisfied** — this matters because multi-family listings never populate the field.

### 5.3 Default weights

| Parameter | Weight |
|---|---|
| Location | 3.0 |
| Price / budget | 3.0 |
| Bedrooms | 2.0 |
| Square footage | 1.5 |
| Bathrooms | 1.5 |
| Property type | 1.5 |
| Price per sqft | 1.5 |
| Garage | 1.0 |
| Year built | 1.0 |
| HOA | 1.0 |
| School rating | 1.0 |

Weights are per-saved-search and overridable. Every parameter also carries a `must` flag: when set, a score below `0.5` removes the listing entirely rather than penalizing it.

**Only location is hard by default. Budget is soft.** `must` defaults to `["area"]`. Budget is the one constraint this product exists to relax: §5.2's ceiling curve crosses `0.5` at roughly +16% over the ceiling, so making `max_price` a default `must` would delete the whole `+16%`–`+50%` tail that §5.2 advertises as rankable and that the discovery call asked for by name — *"then you may show me some houses above $200,000, if the search result is not there for below."* Over-budget listings therefore surface, rank low, carry their value KPI, and the user sorts them away. Any parameter, `max_price` included, can be made hard by naming it in `must`.

### 5.4 Explanation output

Each scored listing carries a `why` string assembled from the per-parameter breakdown, naming the strongest deviation and the compensating matches: *"Included despite 4 bedrooms — price per sqft, area and bathrooms all match."* This is assembled from numbers by template, not generated.

## 6. Comparable sales and valuation (R2)

### 6.1 Candidate cascade

Walk the tiers in order, accumulating candidates, and stop at the first tier where the pool reaches **≥ 5**. If every tier is exhausted below that, use whatever the widest tier produced and let §6.3 assign the resulting confidence:

| Tier | Radius | Recency | Other filters |
|---|---|---|---|
| 1 | Same subdivision | ≤ 180 days | sqft ±25%, same canonical type |
| 2 | ≤ 1 mile | ≤ 180 days | sqft ±25%, same canonical type |
| 3 | ≤ 2 miles | ≤ 365 days | sqft ±35%, same canonical type |
| 4 | ≤ 2 miles | active listings | **labeled asking-price comps** |

Tier 4 is a labelled fallback, never silent. When a valuation rests on active listings the dashboard says *"based on asking prices, not closed sales."*

If the widest tier still yields fewer than 3 candidates, the result is `insufficient_comps` with whatever was found. The product never invents a number to fill a cell.

### 6.2 Estimate

```
base = trimmed_median($/sqft over comps) × subject.sqft
```

Trimmed median drops the top and bottom 10% (at least one from each end when `n ≥ 5`). This is what neutralizes source errors like the 10-bedroom, 4,507 sqft record found in recon.

Then bounded adjustments against the comp medians:

| Adjustment | Rate | Cap |
|---|---|---|
| Bedroom delta | ±3% per bedroom | ±9% |
| Full bath delta | ±2.5% per bath | ±7.5% |
| Age delta | −0.35% per year older | ±10% |
| Lot size delta | ±0.02% per 1% difference | ±5% |

Adjustments are skipped, not guessed, when the subject's value is unknown.

### 6.3 Confidence

| Comps | Label |
|---|---|
| ≥ 8 | High |
| 5–7 | Medium |
| 3–4 | Low |
| < 3 | Insufficient — no estimate produced |

### 6.4 Output — the valuation spread

Recon showed HAR's available AVM is the county appraisal-district value, arriving pre-rounded as a string. It is a useful reference and a poor primary estimate. So the product shows several numbers instead of pretending to one:

```python
@dataclass
class Valuation:
    comp_estimate: int | None        # ours — the primary number
    comp_count: int
    comp_ids: list[str]
    comp_basis: Literal["sold", "asking"]
    confidence: Literal["high", "medium", "low", "insufficient"]
    appraisal_district: MoneyRange | None
    subdivision_list_to_sold: float | None
    delta_pct: float | None          # the headline KPI
    spread_flag: Literal["clustered", "scattered", "single_source"]
```

**Headline KPI** — `delta_pct = (asking − comp_estimate) / comp_estimate`. Negative means priced below comparable sales. This is the number the user asked to sort and prioritize by.

**Subdivision list-to-sold ratio** — median of `sold_price / list_price` over that subdivision's closed sales. Recon found spreads from −16% to +4% in a single Spring sample. Nothing in the brief asked for it and it is arguably the most actionable number the tool can produce, so it ships alongside the KPI.

**Spread flag** — when our estimate, the appraisal-district value and the list-to-sold implication agree within 10%, the property is `clustered`; when they diverge it is `scattered` and worth a closer look. The disagreement is the signal.

## 7. Storage (R3)

SQLite, in the user's data directory. Four tables.

```sql
CREATE TABLE saved_searches (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
  criteria_json TEXT NOT NULL, weights_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE snapshots (
  id INTEGER PRIMARY KEY, saved_search_id INTEGER REFERENCES saved_searches(id),
  run_at TEXT NOT NULL, source TEXT NOT NULL,
  item_count INTEGER NOT NULL, excluded_count INTEGER NOT NULL,
  exclusions_json TEXT, sold_exclusions_json TEXT
);

CREATE TABLE listings (
  snapshot_id INTEGER REFERENCES snapshots(id),
  listing_id TEXT NOT NULL, har_id TEXT, mls_number TEXT,
  address TEXT, city TEXT, zip TEXT, subdivision TEXT,
  lat REAL, lon REAL,
  price INTEGER, price_per_sqft REAL,
  beds INTEGER, baths_full INTEGER, baths_half INTEGER,
  sqft INTEGER, lot_sqft INTEGER, year_built INTEGER,
  garage_spaces INTEGER, hoa_monthly REAL,
  property_type TEXT, duplex_scope TEXT, status TEXT, days_on_market INTEGER,
  school_rating REAL, tax_rate REAL,
  appraisal_low INTEGER, appraisal_high INTEGER,
  score REAL, coverage REAL, score_breakdown_json TEXT,
  valuation_json TEXT, flags_json TEXT, raw_json TEXT,
  PRIMARY KEY (snapshot_id, listing_id)
);

CREATE TABLE sold_history (
  mls_number TEXT PRIMARY KEY,
  address TEXT, city TEXT, zip TEXT, subdivision TEXT,
  lat REAL, lon REAL,
  list_price INTEGER, sold_price INTEGER, sold_date TEXT,
  sold_price_per_sqft REAL, sqft INTEGER, beds INTEGER, baths_full INTEGER,
  year_built INTEGER, lot_sqft INTEGER, property_type TEXT,
  first_seen TEXT NOT NULL
);
CREATE INDEX idx_sold_geo ON sold_history (lat, lon);
CREATE INDEX idx_sold_sub ON sold_history (subdivision, sold_date);
```

### 7.1 Sold history accumulates permanently

`sold_history` is keyed on MLS number and is **never scoped to a run**. Every scan deposits closed sales into it; nothing is deleted.

This is the direct answer to recon's hardest finding — ten agents over five months yielded roughly sixteen genuine sales across six cities, nowhere near enough for a defensible comp set. Density is a function of how long the tool has been running, so the product gets measurably better every week at no extra cost, and repeat fetches get cheaper because we already hold the history.

### 7.2 Diffing

Compare the two most recent snapshots of a saved search by `listing_id`:

| Classification | Rule |
|---|---|
| `NEW` | present now, absent before |
| `PRICE_CUT` | present in both, price decreased |
| `PRICE_UP` | present in both, price increased |
| `GONE` | absent now, present before |
| `UNCHANGED` | everything else |

## 8. MCP tool surface

Six tools. Deliberately no raw-fetch passthrough — that omission is what keeps arithmetic out of the model.

| Tool | Signature | Returns |
|---|---|---|
| `search` | `(criteria: dict, saved_search: str \| None, limit: int = 25)` | Top N scored listings with KPI, plus snapshot id and dashboard URL |
| `explain` | `(listing_id: str, snapshot_id: int \| None)` | Full per-parameter breakdown, comps table, valuation spread |
| `compare` | `(listing_ids: list[str])` | Side-by-side table of scores, KPIs and key fields |
| `whats_new` | `(saved_search: str)` | Diff classification against the previous snapshot |
| `save_search` / `list_searches` | `(name, criteria, weights)` / `()` | Confirmation / list |
| `open_dashboard` | `()` | Localhost URL |

`criteria` is a typed structure the model fills in:

```python
@dataclass
class Criteria:
    area: str                              # "Spring", "77386"
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
    must: list[str] = field(default_factory=lambda: ["area"])
    weights: dict[str, float] | None = None
```

## 9. Dashboard

Starlette, server-rendered, started lazily by the MCP server on first use and advertised by `open_dashboard`.

| Route | Contents |
|---|---|
| `/` | Saved searches, last run time and result count for each |
| `/run/<id>` | Ranked table — address, price, $/sqft, beds/baths, score bar, coverage dot, KPI chip (green below comps, red above), days on market. Data-quality footer showing excluded rows and why. |
| `/listing/<id>` | Per-parameter score bars, the `why` sentence, comps table with distance and sold date, map pins, valuation spread showing all three numbers side by side |
| `/run/<id>/diff` | New, price-cut, price-up and gone since the previous snapshot |

Every KPI in the interface renders with its evidence count attached — *"$231K, 6 comps"* — never as a bare figure.

## 10. Packaging

MCPB bundle, Python server, dependencies vendored at build time so installation is genuinely one click.

```json
{
  "manifest_version": "0.1",
  "name": "har-smart-search",
  "display_name": "HAR Smart Search",
  "version": "0.1.0",
  "server": {
    "type": "python",
    "entry_point": "src/har_search/server/__main__.py"
  },
  "user_config": {
    "apify_token": { "type": "string", "sensitive": true, "required": true },
    "default_area": { "type": "string", "default": "Spring" },
    "dashboard_port": { "type": "number", "default": 7788 }
  }
}
```

The Apify token is user-supplied configuration, never bundled. Dependencies are managed with `uv`.

## 11. Demo scope

Built for the prospect demo:

- `search`, `explain`, `whats_new`, `open_dashboard`
- `/run/<id>`, `/listing/<id>` and `/run/<id>/diff`
- One source adapter (`apify_memo23`), for-sale plus sold ingestion
- Full normalization, scoring and comps — these *are* the product and cannot be faked

`whats_new` and the diff screen are in scope precisely because R3 is a third of the brief and the demo shows it running on real week-apart data.

Deferred until after the demo conversation:

- `compare`, `save_search`, `list_searches` — a single hardcoded search covers the demo
- Scheduling and notifications
- Weight-tuning interface
- Export

Week-over-week is demonstrated honestly: a snapshot is captured several days ahead of the meeting and another at demo time, so the diff shown is real data rather than a staged screen.

## 12. Testing

The math is the product, so the math is what gets tested.

- **Parsers** — table-driven tests over the exact strings observed in recon, including `"3 Attached ,Oversized ,Tandem"`, `"1.1 acre(s)"`, `"$1.0M"` and both spellings of Single-Family.
- **Guards** — fixtures built from the real bad rows: the $1,325 duplex, the 10-bedroom 4,507 sqft house, the `"0 sqft"` lot, the six lease records that arrived in a sold query.
- **Scoring** — every table in §5.2 becomes an assertion. The 4-bedroom-scores-0.85 case is the requirement, expressed as a test.
- **Comps** — synthetic neighbourhoods with known answers; explicit tests that a planted outlier does not move the trimmed median, and that fewer than three comps returns `insufficient_comps` rather than a number.
- **Diff** — snapshot pairs covering each classification.
- **Source adapter** — recorded fixtures from the three live runs already performed; no network in the test suite.

## 13. Assumptions to flag at the demo

Carried forward from `README.md` and revised by recon:

1. Data comes from a paid third-party vendor, because MLS membership is unconfirmed.
2. Comps use closed sales where available, falling back to asking prices with an on-screen label.
3. Sold-price coverage is a sample, not the complete market, and improves the longer the tool runs.
4. Estimates are modelled values with stated confidence, not appraisals.
5. Single user, running locally, data stored on their machine.
6. Weekly runs are user-triggered; no notifications in this build.
7. Bedroom and bathroom counts are unavailable on multi-family listings, so those criteria are scored as unknown rather than failed.
8. "Half duplex" cannot be distinguished reliably from public data; "whole duplex" is inferred from the address unit designator.

## 14. Open questions carried into the demo

- Are you, or a broker you work with, a HAR/MLS member? A yes replaces the vendor with a licensed feed and improves every number downstream.
- How much does complete sold coverage matter versus a good estimate from a sample?
- Houston only, or all of Texas?
- Which parameters should never flex?
- How important is the whole-versus-half duplex distinction, given it needs description parsing to resolve?
- Do you want investment math on top of the KPI — rent estimate, cap rate, cash-on-cash?

## 15. Risks

| Risk | Mitigation |
|---|---|
| Vendor actor breaks or is withdrawn | `ListingSource` interface; a second adapter already identified in recon |
| Sold-comp density too thin in a target area | Permanent accumulation; explicit `insufficient_comps`; deeper agent crawls |
| Source data errors | Trimmed statistics, sanity guards, visible exclusion counts |
| Vendor cost grows with usage | Cache-first reads, snapshot reuse, sold history never re-fetched |
| Prospect expects an appraisal-grade number | Confidence labels, comp counts and the valuation spread shown everywhere |
