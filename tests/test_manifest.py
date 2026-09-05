import json
from pathlib import Path

MANIFEST = Path(__file__).parent.parent / "manifest.json"


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
