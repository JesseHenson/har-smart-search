"""MCP server entrypoint.

The model fills in criteria and narrates results. It never computes a KPI —
every number in a response was produced by har_search.core.
"""

from __future__ import annotations

import os
import sys

# Vendored dependencies go on the path before any third-party import below.
# Claude Desktop runs this file directly, so sys.path[0] is this directory
# rather than the bundle's src/; both are derived from __file__ so the server
# starts the same way whether PYTHONPATH was set or not.
_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from har_search.server.libdir import vendored_lib_dirs  # noqa: E402

for _candidate in reversed(vendored_lib_dirs(os.path.dirname(_SRC))):
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from datetime import date  # noqa: E402

from mcp.server.mcpserver import MCPServer  # noqa: E402

from har_search import config
from har_search.core.diff import diff_snapshots
from har_search.core.keys import resolve_saved_search, snapshot_key
from har_search.core.labels import (
    basis_note,
    confidence_phrase,
    describe_exclusions,
    evidence_phrase,
    spread_phrase,
)
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
                # comp_basis / confidence stay machine-readable; the *_note
                # fields are what the model should read out loud.
                "comp_basis": valuation.comp_basis if valuation else "none",
                "confidence": valuation.confidence if valuation else "insufficient",
                "evidence": evidence_phrase(
                    valuation.comp_count if valuation else 0,
                    valuation.comp_basis if valuation else "none",
                    valuation.confidence if valuation else "insufficient",
                ),
                "basis_note": basis_note(valuation.comp_basis if valuation else "none"),
                "delta_pct": valuation.delta_pct if valuation else None,
            }
        )
    return {
        "snapshot_id": result.snapshot_id,
        "saved_search": result.saved_search,
        "dashboard_url": dashboard_url,
        "results": rows,
        "excluded": result.exclusions,
        "excluded_summary": describe_exclusions(result.exclusions),
        "sold_excluded": result.sold_exclusions,
        "sold_excluded_summary": describe_exclusions(result.sold_exclusions),
        "dropped_by_must": result.dropped_by_must,
    }


def build_explain_response(row: dict, comps: list[dict]) -> dict:
    listing = row["listing"]
    valuation = row["valuation"]
    return {
        "listing_id": listing.listing_id,
        "address": listing.address,
        "price": listing.price,
        "score": row["score"],
        "coverage": row["coverage"],
        "why": row["why"],
        "params": row["params"],
        "valuation": valuation,
        # The stored valuation keeps its Literal tokens. These are the same
        # facts in the words the model should use. `basis_note` in particular
        # carries the tier-4 caveat: an asking-basis estimate is computed
        # against this run's own listings, which were bounded by the searched
        # budget rather than drawn from the open market.
        "evidence": evidence_phrase(
            valuation.get("comp_count"),
            valuation.get("comp_basis", "none"),
            valuation.get("confidence", "insufficient"),
        ),
        "basis_note": basis_note(valuation.get("comp_basis")),
        "confidence_note": confidence_phrase(valuation.get("confidence")),
        "spread_note": spread_phrase(valuation.get("spread_flag")),
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

    Listings over the stated budget are included on purpose, ranked lower —
    that is the "show me some above $200,000 if there is nothing below"
    behaviour, not a bug.

    The response carries a `saved_search` key. Pass that same key to
    `whats_new` to compare this search against its own previous run.
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
    result = run_search(
        source, db, criteria, saved_search=snapshot_key(criteria), limit=limit
    )
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
    """Compare the two most recent runs of a saved search.

    Pass the `saved_search` key returned by `search`. A bare area name works
    too when only one search has been run in that area; when several have, the
    tool names them rather than guessing, because diffing two different
    searches against each other reports every listing as new or gone.
    """
    db = _db()
    key, error = resolve_saved_search(saved_search, db.saved_search_keys())
    if error is not None:
        return {"error": error}
    snapshots = db.recent_snapshots(key, limit=2)
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


# The walkthroughs live here rather than inside a decorated function because
# each is served twice: as an MCP prompt (Claude Desktop's attachment menu)
# and as a tool (reachable by simply asking). Two copies would drift, and the
# drift would be invisible because nobody reads both.
GETTING_STARTED = """Help me set up my first HAR Smart Search. Work through these in order,
one step at a time, and wait for me between steps.

1. Ask me what I am looking for in plain language, then fill in the five
   criteria that actually drive ranking: area, max price, beds, baths and
   square footage. A target price per square foot is optional and useful.
   If I skip one, ask once, then move on — missing criteria lower coverage
   rather than breaking the search.

2. Call `search` with what we have. Tell me how many listings came back and
   how many were excluded, and mention that listings over my budget are
   included on purpose, ranked lower.

3. Call `open_dashboard` and give me the URL. Walk me through one row:
   - the similarity score and what got stretched to earn it
   - the value KPI: the dollar gap between asking price and comparable sales
   - the confidence label, and that "low" means thin comp evidence, not a
     bad house
   - coverage, which counts how many of my criteria the listing published

4. Explain that comps come from recent sales near the listing, so a house
   with few nearby sales of similar size will show no estimate at all. That
   is the tool refusing to guess.

5. Offer to schedule this weekly. If I say yes, set up a scheduled task that
   re-runs the search and reports what is new, then tell me the saved search
   key so `whats_new` can diff runs.

6. Finish with what I can do next: adjust criteria and re-run, add a second
   saved search for a different area, or ask `explain` about any listing."""

PLAN_SEARCH = """Help me build a complete HAR search before running it. Ask me about
each of these, one message at a time, and suggest a sensible default when I
am unsure.

Scoring criteria — these move the ranking:
- area: a city or neighbourhood, e.g. Spring. This is the only hard filter;
  everything else is soft.
- max price: treated as a soft ceiling. Listings above it still appear,
  ranked lower, so give me your real number rather than padding it.
- beds and baths: targets, not minimums. A 4-bed can outrank a 3-bed when
  everything else fits better.
- sqft: the size you actually want. This one also gates which sold homes
  count as comparable, so a wrong number quietly weakens the value estimate.
- price per square foot: optional target. Useful when I care more about
  value than absolute price.

Context only — these appear on results but never change rank:
- garage, house age, HOA, property type.

Also ask whether I want to restrict property types (single family,
townhouse/condo, multi-family, lots), and whether I need to exclude HOAs.

Then read the whole set back to me in one short list, flag anything missing
that would weaken the ranking, and once I confirm, call `search` with it and
tell me the saved search key it returns."""


@mcp.tool()
def getting_started() -> str:
    """Start here. Walks through a first HAR search end to end: gather
    criteria, run the search, explain the dashboard, and set up a weekly
    schedule. Call this when the user is new to this extension or asks how
    to begin.
    """
    return GETTING_STARTED


@mcp.tool()
def plan_search() -> str:
    """Build a complete set of search criteria before running anything.
    Call this when the user wants help deciding what to search for, or has
    given only one or two criteria — a thin search ranks close to
    arbitrarily and reads as noise.
    """
    return PLAN_SEARCH


@mcp.prompt(
    name="getting_started",
    title="Set up my first HAR search",
    description="Walk through a first search end to end: gather criteria, run it, "
    "explain the dashboard, and offer a weekly schedule.",
)
def getting_started_prompt() -> str:
    """First-run guidance.

    Onboarding is not "the extension is installed" — it is "the user has
    looked at real houses and understood the value column". Criteria are
    gathered in conversation rather than on an empty dashboard, because a
    blank form asks the user to guess what good input looks like, and the
    first thing they should see is a ranked list of real listings.
    """
    return GETTING_STARTED


@mcp.prompt(
    name="plan_search",
    title="Build a good search from scratch",
    description="Assemble a complete, well-formed set of search criteria before "
    "running anything.",
)
def plan_search_prompt() -> str:
    """Criteria-building guidance.

    A two-parameter search ranks almost arbitrarily: with little to compare
    on, near-identical scores come back in essentially source order, and the
    result reads as noise. This prompt exists to get a full criteria set in
    place before the first run rather than after a disappointing one.
    """
    return PLAN_SEARCH


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
