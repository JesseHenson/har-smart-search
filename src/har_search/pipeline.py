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
