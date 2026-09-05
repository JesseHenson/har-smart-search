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
