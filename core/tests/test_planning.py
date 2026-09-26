"""Tests for structured Agent planning and plan recovery."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from atlas.agent import AgentOrchestrator
from atlas.agent.planning import PlanSubtask, TaskPlan, requires_plan


def _completion(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=text)
    )])


def _stream(text: str):
    async def chunks():
        yield SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=text, tool_calls=None)
        )])
    return chunks()


def _orchestrator():
    model = MagicMock()
    model.current_model = "test"
    model.current_litellm_model = "openai/test"
    memory = AsyncMock()
    memory.get_conversation_messages.return_value = []
    memory.get_agent_context_with_trace.return_value = {
        "memories": [], "knowledge_trace": {"decisions": [], "query_terms": []},
    }
    mcp = MagicMock()
    mcp.get_tools_for_llm.return_value = []
    return AgentOrchestrator(model, memory, mcp)


def test_requires_plan_only_for_explicit_sequences():
    assert requires_plan("First inspect the files, then summarize them.")
    assert requires_plan("先检查文件，再总结结果。")
    assert requires_plan("Do these steps:\n- inspect\n- summarize")
    assert not requires_plan("What is the current status?")


def test_plan_round_trip_and_verification_require_evidence():
    plan = TaskPlan("Ship result", [PlanSubtask("a", "Inspect", "List files")])
    recovered = TaskPlan.from_dict(plan.to_dict())
    recovered.apply_verification([
        {"id": "a", "completed": True, "evidence": ""},
        {"id": "unknown", "completed": True, "evidence": "ignored"},
    ])
    assert recovered.subtasks[0].status == "pending"
    recovered.apply_verification([
        {"id": "a", "completed": True, "evidence": "file list reviewed"},
    ])
    assert recovered.subtasks[0].status == "completed"
    assert recovered.subtasks[0].evidence == "file list reviewed"


@pytest.mark.asyncio
async def test_multi_step_run_plans_persists_and_verifies():
    orchestrator = _orchestrator()
    persisted = []
    plan_payload = {
        "goal": "Inspect and summarize",
        "subtasks": [{
            "id": "inspect", "title": "Inspect files",
            "verification": "Relevant files were inspected",
        }],
    }

    async def fake_acompletion(**kwargs):
        if kwargs.get("stream") is False:
            if "Break the user's multi-step task" in kwargs["messages"][0]["content"]:
                return _completion(json.dumps(plan_payload))
            return _completion(json.dumps({"results": [{
                "id": "inspect", "completed": True, "evidence": "README inspected",
            }]}))
        return _stream("Summary ready")

    with patch("atlas.agent.acompletion", side_effect=fake_acompletion):
        events = [event async for event in orchestrator.run(
            "First inspect the files, then summarize them.",
            "planning-conversation",
            plan_update_callback=lambda value: persisted.append(value.copy()),
        )]

    plan_events = [event for event in events if event["type"] == "plan_updated"]
    assert len(plan_events) == 2
    assert len(persisted) == 2
    assert plan_events[-1]["plan"]["subtasks"][0]["status"] == "completed"
    assert plan_events[-1]["plan"]["subtasks"][0]["evidence"] == "README inspected"
    assert any(event["type"] == "done" for event in events)


@pytest.mark.asyncio
async def test_resumed_plan_skips_generation_and_only_verifies_pending_items():
    orchestrator = _orchestrator()
    recovered = {
        "goal": "Inspect then summarize",
        "subtasks": [
            {"id": "inspect", "title": "Inspect", "verification": "Inspected",
             "status": "completed", "evidence": "Already inspected"},
            {"id": "summarize", "title": "Summarize", "verification": "Summary exists"},
        ],
    }
    verifier_inputs = []

    async def fake_acompletion(**kwargs):
        if kwargs.get("stream") is False:
            verifier_inputs.append(kwargs["messages"][-1]["content"])
            return _completion(json.dumps({"results": [{
                "id": "summarize", "completed": True, "evidence": "Summary emitted",
            }]}))
        assert "Already inspected" in json.dumps(kwargs["messages"], ensure_ascii=False)
        return _stream("Summary emitted")

    with patch("atlas.agent.acompletion", side_effect=fake_acompletion) as completion:
        events = [event async for event in orchestrator.run(
            "Continue the saved plan",
            "planning-conversation",
            plan_state=recovered,
        )]

    assert completion.await_count == 2
    assert "summarize" in verifier_inputs[0]
    updated = [event for event in events if event["type"] == "plan_updated"][-1]
    assert updated["resumed"] is True
    assert all(item["status"] == "completed" for item in updated["plan"]["subtasks"])
