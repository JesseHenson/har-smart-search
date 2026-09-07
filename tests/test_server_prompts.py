"""Prompts are how a bundle ships guidance.

MCPB has no `skills` field — the manifest schema allows `tools` and
`prompts` and nothing else — so anything that teaches a user how to drive
this extension has to arrive as an MCP prompt, which Claude Desktop lists
as a command.
"""

import asyncio
import json
from pathlib import Path

from har_search.server.__main__ import mcp

MANIFEST = json.loads((Path(__file__).parent.parent / "manifest.json").read_text())


def registered() -> dict:
    return {p.name: p for p in asyncio.run(mcp.list_prompts())}


def test_getting_started_and_plan_search_are_registered():
    assert set(registered()) == {"getting_started", "plan_search"}


def test_declared_prompts_match_registered_prompts():
    """Same contract the tools already have: the manifest is what Desktop
    shows in its command list, so a prompt missing from it is invisible no
    matter how well it is implemented.
    """
    declared = {p["name"] for p in MANIFEST.get("prompts", [])}

    assert declared == set(registered())


def test_getting_started_walks_to_a_dashboard_the_user_has_seen():
    """Onboarding is done when the user has looked at real results, not
    when the extension is installed.
    """
    rendered = asyncio.run(mcp.get_prompt("getting_started"))
    text = " ".join(
        m.content.text for m in rendered.messages if hasattr(m.content, "text")
    ).lower()

    assert "criteria" in text
    assert "dashboard" in text
    assert "weekly" in text or "schedule" in text


def test_plan_search_asks_for_the_scoring_criteria_by_name():
    """A good search is not "a house in Spring" — it is the five scoring
    parameters. The prompt has to name them or the user supplies two and
    wonders why the ranking looks arbitrary.
    """
    rendered = asyncio.run(mcp.get_prompt("plan_search"))
    text = " ".join(
        m.content.text for m in rendered.messages if hasattr(m.content, "text")
    ).lower()

    for term in ("area", "price", "beds", "baths", "sqft"):
        assert term in text
