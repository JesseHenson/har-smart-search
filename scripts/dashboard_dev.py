"""Serve the dashboard against a database of your choosing, for design work.

The extension starts its own dashboard on demand against the real database.
This is the version you point at a copy while changing templates or the
stylesheet, so a reload is a reload and not a reinstall.

    HAR_DB_PATH=~/.har-smart-search/har.db uv run python scripts/dashboard_dev.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import uvicorn  # noqa: E402

from har_search.store.db import Database  # noqa: E402
from har_search.web.app import create_app  # noqa: E402

DB_PATH = os.environ.get("HAR_DB_PATH") or str(Path.home() / ".har-smart-search" / "har.db")
PORT = int(os.environ.get("HAR_DASHBOARD_PORT", "8912"))

if __name__ == "__main__":
    print(f"dashboard: {DB_PATH} on http://127.0.0.1:{PORT}", file=sys.stderr)
    uvicorn.run(
        create_app(lambda: Database(DB_PATH)),
        host="127.0.0.1",
        port=PORT,
        log_level="warning",
    )
