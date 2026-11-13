"""D13: an agent can declare a workspace file as a visible deliverable."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from atlas.agent.presentation import build_presented_file
from atlas.agent.tool_catalog import PRESENT_TOOL

pytestmark = pytest.mark.unit


def test_present_tool_is_part_of_the_agent_model_catalog_contract():
    function = PRESENT_TOOL["function"]
    assert function["name"] == "present"
    assert function["parameters"]["required"] == ["path"]
    assert function["parameters"]["additionalProperties"] is False


def test_present_declares_an_existing_workspace_file(tmp_path):
    target = tmp_path / "deliverables" / "plan.md"
    target.parent.mkdir()
    target.write_text("Plan", encoding="utf-8")

    event = build_presented_file(
        {"path": "deliverables/plan.md", "title": "Implementation plan", "summary": "Ready"},
        workspace=str(tmp_path),
    )

    assert event == {
        "path": str(target.resolve()), "kind": "document", "tool": "present",
        "title": "Implementation plan", "summary": "Ready",
    }


def test_present_rejects_paths_outside_the_workspace(tmp_path):
    outside = tmp_path.parent / "outside-present.md"
    outside.write_text("private", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="inside the current workspace"):
            build_presented_file({"path": str(outside)}, workspace=str(tmp_path))
    finally:
        outside.unlink()


def test_present_rejects_a_missing_file_and_a_remote_workspace(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        build_presented_file({"path": "missing.md"}, workspace=str(tmp_path))
    with pytest.raises(ValueError, match="local current workspace"):
        build_presented_file({"path": "plan.md"}, workspace="ssh://host/tmp/work")


@pytest.mark.asyncio
async def test_present_tool_call_emits_an_artifact_event_with_the_declared_title(tmp_path):
    from langchain_core.messages import AIMessage

    from atlas.agent import AgentOrchestrator

    target = tmp_path / "report.md"
    target.write_text("# Report", encoding="utf-8")
    agent = AgentOrchestrator(MagicMock(), MagicMock())
    events = asyncio.Queue()
    runtime = MagicMock(
        cancel_event=None, pause_event=None, approval_callback=None,
        event_queue=events, workspace=str(tmp_path), permission_mode="full_access",
        read_only=False, agent_role="general", agent_type="general",
        allowed_paths=[], run_id="present-run", conversation_id="conversation",
        tool_allow=None, tool_deny=[],
    )
    state = {
        "messages": [AIMessage(content="", tool_calls=[{
            "name": "present",
            "args": {"path": "report.md", "title": "Quarterly report", "summary": "Signed off"},
            "id": "present-call",
        }])],
        "pending_events": [], "tool_rounds": 0, "runtime": runtime,
    }

    await agent._execute_tools_node(state)

    queued = [await asyncio.wait_for(events.get(), timeout=5) for _ in range(events.qsize())]
    artifact_events = [item for item in queued if item.get("type") == "artifact_created"]
    assert artifact_events, queued
    event = artifact_events[0]
    assert event["type"] == "artifact_created"
    assert event["path"] == str(target.resolve())
    assert event["kind"] == "document"
    assert event["title"] == "Quarterly report"
    assert event["summary"] == "Signed off"
