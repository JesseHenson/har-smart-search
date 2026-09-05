"""FastMCP entrypoint.

The model fills in criteria and narrates results. It never computes a KPI —
every number in a response was produced by har_search.core.
"""

from __future__ import annotations

from datetime import date

from mcp.server.mcpserver import MCPServer

from har_search import config
from har_search.core.diff import diff_snapshots
from har_search.core.models import Criteria, ListingChange
from har_search.pipeline import SearchResult, run_search
from har_search.sources.apify_memo23 import ApifyMemo23Source
from har_search.store.db import Database
from har_search.web.app import ensure_dashboard_running

mcp = MCPServer("har-smart-search")


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
