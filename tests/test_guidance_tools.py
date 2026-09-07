"""Guidance has to be reachable by asking, not only by clicking.

Claude Desktop surfaces MCP prompts in the attachment menu, never as
something the user can type. A user who does not know the menu exists has
no way to reach onboarding at all. The same text is therefore also exposed
as tools, which Claude selects from a plain request like "help me get
started with HAR".
"""

import asyncio

from har_search.server.__main__ import mcp


def tools() -> dict:
    return {t.name: t for t in asyncio.run(mcp.list_tools())}


def test_guidance_is_available_as_tools_not_only_prompts():
    assert {"getting_started", "plan_search"} <= set(tools())


def test_the_tool_and_prompt_forms_carry_the_same_text():
    """One source of truth. Two copies of a walkthrough drift, and the
    drift is invisible because nobody reads both.
    """
    from har_search.server.__main__ import GETTING_STARTED, PLAN_SEARCH

    prompts = {p.name: p for p in asyncio.run(mcp.list_prompts())}
    rendered = asyncio.run(mcp.get_prompt("getting_started"))

    assert prompts["getting_started"] is not None
    assert rendered.messages[0].content.text == GETTING_STARTED
    assert PLAN_SEARCH.strip().startswith("Help me build a complete HAR search")


def test_descriptions_say_when_to_use_them():
    """Claude picks a tool off its description, so the description has to
    contain the words a user would actually say.
    """
    described = tools()

    assert "start" in described["getting_started"].description.lower()
    assert "criteria" in described["plan_search"].description.lower()
