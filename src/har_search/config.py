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


def dashboard_port() -> int:
    return int(os.environ.get("HAR_DASHBOARD_PORT", "7788"))


def database_path() -> Path:
    raw = os.environ.get("HAR_DB_PATH")
    if raw:
        return Path(raw)
    directory = Path.home() / ".har-smart-search"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "har.db"
