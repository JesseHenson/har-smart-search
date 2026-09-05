"""Fetch, normalize, score, value, persist — in that order, once."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from har_search.core.comps import value_listing
from har_search.core.keys import snapshot_key
from har_search.core.models import Criteria, Listing, ScoredListing, Valuation
from har_search.core.normalize import normalize_listing, normalize_sale
from har_search.core.scoring import score_listing
from har_search.store.db import Database

COMP_LOOKBACK_DAYS = 365
COMP_RADIUS_MILES = 2.0


@dataclass
class SearchResult:
    snapshot_id: int
    saved_search: str
    scored: list[ScoredListing]
    valuations: dict[str, Valuation]
    exclusions: dict[str, int] = field(default_factory=dict)
    # Sold-row exclusions are counted separately from for-sale ones. They mean
    # something different: a for-sale exclusion thins the results table, a sold
    # exclusion thins the comp evidence behind every KPI in it. Folding them
    # into one number would let six leases inside a sold query disappear behind
    # a confidently smaller for-sale count.
    sold_exclusions: dict[str, int] = field(default_factory=dict)
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
    saved_search: str | None = None,
    limit: int = 25,
    today: date | None = None,
) -> SearchResult:
    today = today or date.today()
    # Snapshots are keyed on the criteria, not the area. Keying on the area
    # alone put every search in a city into one bucket, so `whats_new` diffed
    # unrelated searches against each other and called every listing NEW or
    # GONE. An explicit `saved_search` is still honoured for callers that
    # manage their own buckets (the tests do).
    saved_search = saved_search or snapshot_key(criteria)

    # 1. Sold history first, so comps are available for this run's listings.
    sold_exclusions: Counter[str] = Counter()
    sales: list = []
    for raw in source.fetch_sold(area=criteria.area):
        result = normalize_sale(raw)
        if result.sale is None:
            sold_exclusions[result.exclusion or "unknown"] += 1
            continue
        sales.append(result.sale)
    if sales:
        db.upsert_sales(sales)

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
    # Build the active comp pool once; comps_from_listings handles subject exclusion.
    all_listings = [s.listing for s in scored]
    for item in scored:
        listing = item.listing
        sales = (
            db.sales_near(listing.lat, listing.lon, COMP_RADIUS_MILES, since)
            if listing.lat is not None and listing.lon is not None
            else []
        )
        valuations[listing.listing_id] = value_listing(listing, sales, all_listings, today)

    # 5. Persist.
    snapshot_id = db.create_snapshot(
        saved_search=saved_search,
        source=getattr(source, "name", "unknown"),
        item_count=len(scored),
        excluded_count=sum(exclusions.values()) + dropped_by_must,
        exclusions=dict(exclusions),
        sold_exclusions=dict(sold_exclusions),
    )
    db.insert_scored(snapshot_id, scored, valuations)

    return SearchResult(
        snapshot_id=snapshot_id,
        saved_search=saved_search,
        scored=scored,
        valuations=valuations,
        exclusions=dict(exclusions),
        sold_exclusions=dict(sold_exclusions),
        dropped_by_must=dropped_by_must,
    )
