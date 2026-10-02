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
    memory.retrieve_agent_reflections.return_value = []
    memory.retrieve_approved_goal_experiences.return_value = []
    memory.retrieve_approved_goal_knowledge.return_value = []
    memory.apply_knowledge_consolidated_insights.return_value = []
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
