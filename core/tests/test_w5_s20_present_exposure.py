"""W5 S20 — the ``present`` deliverable tool must survive tier pruning.

Ledger S20: the catalog ships ``present`` (``atlas/agent/tool_catalog.py``) and
the dispatcher executes it (``atlas/agent/tool_node.py``), but
``select_tools_for_tier`` cut it in every bucket because ``present`` has no
family, no prior, and was absent from the kernel's ``_ALWAYS_KEEP_TOOLS``.
That is why the W3 live turn never called it. This file pins the exposure:
with the production always-keep tuple, ``present`` is offered in all three
buckets, and its family mapping is declared.
"""

from __future__ import annotations

import pytest

from atlas.agent.tool_catalog import PRESENT_TOOL
from atlas.engine.kernel.tool_pruning import (
    TIER_CODE,
    TIER_DEFAULT,
    TIER_DISCUSS,
    explain_selection,
    family_of,
    select_tools_for_tier,
    schema_name,
)

pytestmark = pytest.mark.unit


def _production_always_keep() -> tuple[str, ...]:
    """Import the kernel's real always-keep tuple (not a test copy)."""
    from atlas.engine.kernel.loop import _ALWAYS_KEEP_TOOLS

    return tuple(_ALWAYS_KEEP_TOOLS)


def _realistic_pool() -> list[dict]:
    """A pool shaped like the live one: kernel tools + catalog extras."""
    def tool(name: str, desc: str = "") -> dict:
        return {"type": "function", "function": {
            "name": name,
            "description": desc or f"The {name} tool.",
            "parameters": {"type": "object", "properties": {}},
        }}

    names = [
        "read_file", "write", "edit", "glob", "grep", "exec_command",
        "list_directory", "apply_patch", "update_plan", "memory_search",
        "memory_supersede", "session_search", "read_session", "send_to_session",
        "session_event_search", "session_event_read", "session_trace",
        "web_search", "web_fetch", "web_extract", "deep_research",
        "image_generate", "video_analyze", "create_document",
        "create_spreadsheet", "create_presentation", "read_office",
        "lsp_diagnostics", "build_repo_map", "run_checks", "workflow",
        "automation_manage", "propose_settings_change", "ask_advisor",
        "request_user_input", "AskUserQuestion", "tool_search",
        "view_image", "notebook_edit", "local_shell", "local_edit",
    ]
    return [tool(name) for name in names] + [PRESENT_TOOL]


def test_s20_present_present_in_catalog():
    assert schema_name(PRESENT_TOOL) == "present"


def test_s20_present_has_family_mapping():
    assert family_of("present") == "deliverable"


@pytest.mark.parametrize("tier", [TIER_CODE, TIER_DISCUSS, TIER_DEFAULT])
def test_s20_present_survives_tier_pruning(tier: str):
    pool = _realistic_pool()
    kept = select_tools_for_tier(pool, tier, always_keep=_production_always_keep())
    names = {schema_name(schema) for schema in kept}
    assert "present" in names, (
        f"tier={tier}: 'present' was pruned from the model-visible pool; "
        f"kept={sorted(names)}"
    )


def test_s20_present_scored_without_always_keep():
    """Even without the always-keep list, present must not be a no_signal drop."""
    pool = _realistic_pool()
    for tier in (TIER_CODE, TIER_DISCUSS, TIER_DEFAULT):
        report = explain_selection(pool, message="", always_keep=())
        entry = report["tools"]["present"]
        assert entry["score"] > 0, f"tier={tier}: present scored 0 (no_signal)"
        assert entry["reason"] != "no_signal", (
            f"tier={tier}: present dropped with no_signal despite the prior"
        )
