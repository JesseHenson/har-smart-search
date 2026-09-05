"""Local dashboard.

Every estimate is rendered with the number of comps behind it. A bare
figure would imply a confidence the data does not support.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import RedirectResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from har_search.core.diff import diff_snapshots
from har_search.core.labels import (
    basis_note,
    change_phrase,
    describe_exclusions,
    evidence_phrase,
    param_label,
    spread_phrase,
)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_server_thread: threading.Thread | None = None
_server_lock = threading.Lock()


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


def criteria_counts(params: list[dict]) -> tuple[int, int]:
    """Return (known, total) criteria counts backing a coverage percentage.

    A bare percentage doesn't say what it's a fraction of: 92% computed from
    3 of 7 requested criteria is a different claim than 92% from all 7.
    """
    total = len(params)
    known = sum(1 for p in params if p.get("known"))
    return known, total


def exclusion_summary(snapshot: dict) -> tuple[str, str]:
    """Return (for-sale prose, sold prose) for the data-quality footer.

    The two are rendered separately and deliberately. For-sale exclusions thin
    the results table; sold exclusions thin the comp evidence behind every KPI
    in that table. Six leases arriving inside a sold query is the most
    dangerous data defect in this domain, and it used to leave no trace at all
    while the footer reported a confidently smaller number.
    """
    return (
        describe_exclusions(json.loads(snapshot.get("exclusions_json") or "{}")),
        describe_exclusions(json.loads(snapshot.get("sold_exclusions_json") or "{}")),
    )


def create_app(db_factory) -> Starlette:
    def index(request):
        db = db_factory()
        searches = db.latest_snapshots()
        return TEMPLATES.TemplateResponse(
            request, "index.html", {"searches": searches}
        )

    def run_page(request):
        db = db_factory()
        snapshot_id = int(request.path_params["snapshot_id"])
        snapshot = db.get_snapshot(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No such snapshot")
        rows = db.get_scored_rows(snapshot_id)
        for row in rows:
            row["chip"] = kpi_chip(row["valuation"].get("delta_pct"))
            known, total = criteria_counts(row["params"])
            row["criteria_known"] = known
            row["criteria_total"] = total
        excluded, sold_excluded = exclusion_summary(snapshot)
        return TEMPLATES.TemplateResponse(
            request,
            "run.html",
            {
                "snapshot": snapshot,
                "rows": rows,
                "snapshot_id": snapshot_id,
                "excluded_summary": excluded,
                "sold_excluded_summary": sold_excluded,
            },
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
        valuation = row["valuation"]
        for param in row["params"]:
            param["label"] = param_label(param.get("name", ""))
        return TEMPLATES.TemplateResponse(
            request,
            "listing.html",
            {
                "row": row,
                "snapshot_id": snapshot_id,
                "evidence": evidence_phrase(
                    valuation.get("comp_count"),
                    valuation.get("comp_basis", "none"),
                    valuation.get("confidence", "insufficient"),
                ),
                "basis_note": basis_note(valuation.get("comp_basis")),
                "spread_note": spread_phrase(valuation.get("spread_flag")),
            },
        )

    def diff_page(request):
        db = db_factory()
        snapshot_id = int(request.path_params["snapshot_id"])
        snapshot = db.get_snapshot(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No such snapshot")
        previous_id = db.previous_snapshot_id(snapshot["saved_search"], snapshot_id)
        previous = db.get_snapshot_listings(previous_id) if previous_id else []
        changes = diff_snapshots(previous, db.get_snapshot_listings(snapshot_id))
        return TEMPLATES.TemplateResponse(
            request,
            "diff.html",
            {
                "changes": [
                    {"change": c, "label": change_phrase(c.change_type)}
                    for c in changes
                    if c.change_type != "UNCHANGED"
                ],
                "has_previous": previous_id is not None,
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
    """Start the dashboard in a background thread, once.

    The check-and-set (is a server already running? if not, start one) has
    to be atomic: Task 12 calls this from both its `search` and
    `open_dashboard` tools, and two threads racing the check would both see
    no live server and both try to bind the port. The lock makes the whole
    check-and-start one critical section; the fast path (server already
    running) still just acquires an uncontended lock and returns.
    """
    global _server_thread
    base = f"http://127.0.0.1:{port}"
    with _server_lock:
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
