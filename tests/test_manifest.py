import asyncio
import json
from pathlib import Path

MANIFEST = Path(__file__).parent.parent / "manifest.json"
REPO_ROOT = MANIFEST.parent


def test_manifest_is_valid_json_with_required_keys():
    data = json.loads(MANIFEST.read_text())
    assert data["name"] == "har-smart-search"
    assert data["server"]["type"] == "python"
    assert data["server"]["entry_point"].endswith("server/__main__.py")


def test_apify_token_is_marked_sensitive_and_required():
    data = json.loads(MANIFEST.read_text())
    token = data["user_config"]["apify_token"]
    assert token["sensitive"] is True
    assert token["required"] is True


def test_token_is_passed_to_the_server_as_an_env_var():
    data = json.loads(MANIFEST.read_text())
    env = data["server"]["mcp_config"]["env"]
    assert env["HAR_APIFY_TOKEN"] == "${user_config.apify_token}"
    assert env["HAR_DASHBOARD_PORT"] == "${user_config.dashboard_port}"


def test_entry_point_file_exists():
    """Entry point file must exist on disk relative to repository root."""
    data = json.loads(MANIFEST.read_text())
    entry_point = data["server"]["entry_point"]

    # Verify suffix as a sanity check.
    assert entry_point.endswith("server/__main__.py")

    # Resolve relative to repository root and check it exists.
    path = REPO_ROOT / entry_point
    assert path.is_file(), f"Entry point not found: {path}"


def test_declared_tools_match_server_tools():
    """Manifest tools list must match tools the server actually registers."""
    data = json.loads(MANIFEST.read_text())
    declared_names = sorted(tool["name"] for tool in data["tools"])

    # Import the server module and list its registered tools.
    # This works without environment setup because database and HTTP client
    # are constructed inside tool bodies, not at import time.
    from har_search.server.__main__ import mcp

    registered_names = sorted(t.name for t in asyncio.run(mcp.list_tools()))

    assert declared_names == registered_names, (
        f"Tool mismatch: manifest declares {declared_names} "
        f"but server registers {registered_names}"
    )


def test_bundle_excludes_the_editable_install_pointer():
    """`uv pip install --target lib` leaves an editable .pth in lib/ holding
    an absolute path to this checkout.

    Shipping it is worse than untidy. On the developer's own machine the path
    resolves, so an installed bundle silently imports `har_search` from the
    working tree instead of from its own `src/` — a demo can pass while the
    bundle itself is broken, and nothing says so. On any other machine the
    path is simply dead.
    """
    ignore = (REPO_ROOT / ".mcpbignore").read_text().splitlines()
    patterns = {line.strip() for line in ignore if line.strip() and not line.startswith("#")}

    assert "lib/*.pth" in patterns
    assert "lib/bin/" in patterns
    assert "prototype/" in patterns
