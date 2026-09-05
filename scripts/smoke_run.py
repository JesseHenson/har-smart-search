"""Manual smoke run against live data. Not part of the test suite.

Usage:
    HAR_APIFY_TOKEN=... uv run python scripts/smoke_run.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, "src")

from har_search import config
from har_search.core.models import Criteria
from har_search.pipeline import run_search
from har_search.sources.apify_memo23 import ApifyMemo23Source
from har_search.store.db import Database


def main() -> None:
    token = os.environ.get("HAR_APIFY_TOKEN")
    if not token:
        raise SystemExit("Set HAR_APIFY_TOKEN first.")

    # Write to the same database the MCP server reads (config.database_path(),
    # not a file in the working directory), and let `run_search` derive the
    # saved_search key from the criteria itself rather than passing a
    # hardcoded override. A script that skips the tool's own default is
    # exactly the kind of gap that leaves `whats_new` nothing to diff.
    db = Database(config.database_path())
    db.init_schema()

    criteria = Criteria(
        area="Spring",
        beds=3,
        baths=2,
        garage_spaces=1,
        max_price_per_sqft=120,
        no_hoa=True,
    )
    result = run_search(
        source=ApifyMemo23Source(token=token),
        db=db,
        criteria=criteria,
        limit=25,
    )

    print(f"saved_search key: {result.saved_search}")
    print("Pass this exact key to `whats_new` to diff against the next run.")
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
