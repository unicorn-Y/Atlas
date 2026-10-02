"""Tests for Atlas tool execution adapters used by Hermes."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from atlas.agent import AgentOrchestrator, ToolExecutionState
from atlas.tools.computer_use import COMPUTER_TOOLS
from atlas.tools.mcp_client import MCPClient




def _agent_state(ai: AIMessage, *, runtime: Any | None = None) -> ToolExecutionState:
    return {
        "messages": [ai],
        "pending_events": [],
        "runtime": runtime or SimpleNamespace(
            cancel_event=None, pause_event=None, approval_callback=None
        ),
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def model_mgr():
    mgr = MagicMock()
    mgr.current_model = "test-model"
    mgr.current_litellm_model = "openai/test-model"
    return mgr


@pytest.fixture
def memory():
    mem = AsyncMock()
    mem.get_conversation_messages.return_value = []
    mem.save_message.return_value = "msg-123"
    mem.extract_memories.return_value = []
    mem.get_active_context.return_value = []
    mem.get_agent_context.return_value = []
    mem.get_agent_context_with_trace.return_value = {
        "memories": [],
        "knowledge_trace": {"query_terms": [], "results": [], "decisions": []},
    }
    mem.retrieve_agent_reflections.return_value = []
    mem.retrieve_approved_goal_experiences.return_value = []
    mem.retrieve_approved_goal_knowledge.return_value = []
    mem.apply_knowledge_consolidated_insights.return_value = []
    return mem


@pytest.fixture
def mcp_client():
    client = MagicMock(spec=MCPClient)
    client.get_tools_for_llm.return_value = []
    client.list_tools.return_value = []
    client.tool_count = 0
    return client


@pytest.fixture
def orchestrator(model_mgr, memory, mcp_client):
    return AgentOrchestrator(
        model_mgr=model_mgr, memory=memory, mcp_client=mcp_client
    )


# ---------------------------------------------------------------------------
# State machine structure
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Execute tools node
# ---------------------------------------------------------------------------

class TestExecuteTools:
    async def test_computer_screenshot_is_returned_as_multimodal_message(
        self, model_mgr, memory, mcp_client
    ) -> None:
        image = "data:image/png;base64,aW1hZ2U="
        computer = MagicMock()
        computer.call_tool = AsyncMock(
            return_value={
                "data": {
                    "observation_id": "obs-1",
                    "artifact_path": "screen.png",
                    "_image_data_url": image,
                },
                "content": [{"type": "text", "text": "observation metadata"}],
                "is_error": False,
            }
        )
        agent = AgentOrchestrator(model_mgr, memory, mcp_client=mcp_client, computer_use=computer)
        state: ToolExecutionState = {
            "messages": [AIMessage(content="", tool_calls=[{
                "name": "computer_observe", "args": {"target": "desktop"}, "id": "screen-1"
            }])],
            "pending_events": [],
            "runtime": SimpleNamespace(cancel_event=None, pause_event=None, approval_callback=None),
        }

        result = await agent._execute_tools_node(state)

        assert isinstance(result["messages"][0], ToolMessage)
        image_message = result["messages"][1]
        assert isinstance(image_message, HumanMessage)
        assert image_message.content[1] == {"type": "image_url", "image_url": {"url": image}}
        event = next(item for item in result["pending_events"] if item["type"] == "tool_result")
        assert event["data"] == {"observation_id": "obs-1", "artifact_path": "screen.png"}
        assert "computer_observe" in {item["function"]["name"] for item in COMPUTER_TOOLS}

    async def test_execute_single_tool(self, orchestrator, mcp_client) -> None:
        """Execute one tool call."""
        mcp_client.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "file contents here"}],
            "is_error": False,
        })

        ai = AIMessage(
            content="",
            tool_calls=[{"name": "fs__read", "args": {"path": "/a.txt"}, "id": "t1"}],
        )
        state: ToolExecutionState = {
            "messages": [HumanMessage(content="read a.txt"), ai],
            "pending_events": [],
            "runtime": SimpleNamespace(
                cancel_event=None, pause_event=None, approval_callback=None
            ),
        }

        result = await orchestrator._execute_tools_node(state)

        # Should produce a ToolMessage
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], ToolMessage)
        assert result["messages"][0].tool_call_id == "t1"
        assert "file contents here" in result["messages"][0].content

        # Should produce a tool_result event
        events = result["pending_events"]
        assert any(e["type"] == "tool_result" for e in events)
        tr = next(e for e in events if e["type"] == "tool_result")
        assert tr["name"] == "fs__read"
        assert tr["is_error"] is False


    async def test_execute_multiple_tools(self, orchestrator, mcp_client) -> None:
        """Execute multiple tool calls in one round."""
        mcp_client.call_tool = AsyncMock(
            side_effect=[
                {"content": [{"type": "text", "text": "result1"}], "is_error": False},
                {"content": [{"type": "text", "text": "result2"}], "is_error": False},
            ]
        )

        ai = AIMessage(
            content="",
            tool_calls=[
                {"name": "fs__read", "args": {"path": "/a"}, "id": "t1"},
                {"name": "fs__read", "args": {"path": "/b"}, "id": "t2"},
            ],
        )
        state: ToolExecutionState = {
            "messages": [ai],
            "pending_events": [],
            "runtime": SimpleNamespace(
                cancel_event=None, pause_event=None, approval_callback=None
            ),
        }

        result = await orchestrator._execute_tools_node(state)
        assert len(result["messages"]) == 2

    async def test_execute_tool_error(self, orchestrator, mcp_client) -> None:
        """Tool call that returns an error."""
        mcp_client.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "permission denied"}],
            "is_error": True,
        })

        ai = AIMessage(
            content="",
            tool_calls=[{"name": "fs__write", "args": {}, "id": "t1"}],
        )
        state: ToolExecutionState = {
            "messages": [ai],
            "pending_events": [],
            "runtime": SimpleNamespace(
                cancel_event=None, pause_event=None, approval_callback=None
            ),
        }

        result = await orchestrator._execute_tools_node(state)
        events = result["pending_events"]
        tr = next(e for e in events if e["type"] == "tool_result")
        assert tr["is_error"] is True

    async def test_execute_tool_exception_is_recoverable_error(
        self, orchestrator, mcp_client
    ) -> None:
        """A raised tool failure is returned to the model as a typed tool result."""
        mcp_client.call_tool = AsyncMock(side_effect=TimeoutError("tool timed out"))
        state = _agent_state(AIMessage(
            content="",
            tool_calls=[{"name": "fs__read", "args": {"path": "a"}, "id": "t2"}],
        ))

        result = await orchestrator._execute_tools_node(state)

        assert result["messages"][0].content == "Tool call failed: tool timed out"
        tool_result = next(e for e in result["pending_events"] if e["type"] == "tool_result")
        assert tool_result["is_error"] is True
        assert tool_result["error_category"] == "tool"


# ---------------------------------------------------------------------------
# Concurrent run control isolation
# ---------------------------------------------------------------------------

class TestConcurrentRunIsolation:
    async def test_concurrent_run_cancel_isolation(self, orchestrator, mcp_client) -> None:
        cancel_a = asyncio.Event()
        cancel_a.set()
        cancel_b = asyncio.Event()
        state_a = _agent_state(
            AIMessage(content="", tool_calls=[{
                "name": "fs__read", "args": {"path": "/a"}, "id": "a"
            }]),
            runtime=SimpleNamespace(
                cancel_event=cancel_a, pause_event=None, approval_callback=None
            ),
        )
        state_b = _agent_state(
            AIMessage(content="", tool_calls=[{
                "name": "fs__read", "args": {"path": "/b"}, "id": "b"
            }]),
            runtime=SimpleNamespace(
                cancel_event=cancel_b, pause_event=None, approval_callback=None
            ),
        )
        mcp_client.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "ok"}], "is_error": False,
        })

        await asyncio.gather(
            orchestrator._execute_tools_node(state_a),
            orchestrator._execute_tools_node(state_b),
        )

        mcp_client.call_tool.assert_awaited_once_with("fs__read", {"path": "/b"})

    async def test_concurrent_run_pause_isolation(self, orchestrator, mcp_client) -> None:
        pause_a = asyncio.Event()
        pause_b = asyncio.Event()
        pause_b.set()
        state_a = _agent_state(
            AIMessage(content="", tool_calls=[{
                "name": "fs__read", "args": {"path": "/a"}, "id": "a"
            }]),
            runtime=SimpleNamespace(
                cancel_event=None, pause_event=pause_a, approval_callback=None
            ),
        )
        state_b = _agent_state(
            AIMessage(content="", tool_calls=[{
                "name": "fs__read", "args": {"path": "/b"}, "id": "b"
            }]),
            runtime=SimpleNamespace(
                cancel_event=None, pause_event=pause_b, approval_callback=None
            ),
        )
        mcp_client.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "ok"}], "is_error": False,
        })

        task_a = asyncio.create_task(orchestrator._execute_tools_node(state_a))
        task_b = asyncio.create_task(orchestrator._execute_tools_node(state_b))
        await asyncio.sleep(0)
        assert not task_a.done()
        assert task_b.done()
        pause_a.set()
        await asyncio.gather(task_a, task_b)

        assert {call.args[1]["path"] for call in mcp_client.call_tool.await_args_list} == {
            "/a", "/b"
        }

    async def test_concurrent_run_approval_isolation(self, orchestrator) -> None:
        calls_a: list[str] = []
        calls_b: list[str] = []

        async def approve_a(event_id: str, tool_name: str, args: dict) -> str:
            calls_a.append(event_id)
            return "deny"

        async def approve_b(event_id: str, tool_name: str, args: dict) -> str:
            calls_b.append(event_id)
            return "deny"

        state_a = _agent_state(
            AIMessage(content="", tool_calls=[{
                "name": "execute_command", "args": {"command": "a"}, "id": "a"
            }]),
            runtime=SimpleNamespace(
                cancel_event=None, pause_event=None, approval_callback=approve_a
            ),
        )
        state_b = _agent_state(
            AIMessage(content="", tool_calls=[{
                "name": "execute_command", "args": {"command": "b"}, "id": "b"
            }]),
            runtime=SimpleNamespace(
                cancel_event=None, pause_event=None, approval_callback=approve_b
            ),
        )
        await asyncio.gather(
            orchestrator._execute_tools_node(state_a),
            orchestrator._execute_tools_node(state_b),
        )

        assert calls_a == ["approval:a"]
        assert calls_b == ["approval:b"]


# ---------------------------------------------------------------------------
# Full run() integration (mocked LLM)
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# use_skill: model-invocable skill activation
# ---------------------------------------------------------------------------


class TestUseSkill:
    def test_use_skill_in_tool_surface_when_skill_manager_present(self) -> None:
        from unittest.mock import MagicMock

        from atlas.agent import AgentOrchestrator

        skills = MagicMock()
        skills.list_skills.return_value = []
        orchestrator = AgentOrchestrator(
            model_mgr=MagicMock(), memory=AsyncMock(), mcp_client=None,
            skill_manager=skills,
        )
        names = {tool["function"]["name"] for tool in orchestrator._model_facing_tools()}
        assert "use_skill" in names

    def test_tool_surface_omits_use_skill_without_skill_manager(
        self, orchestrator,
    ) -> None:
        orchestrator._skills = None
        names = {tool["function"]["name"] for tool in orchestrator._model_facing_tools()}
        assert "use_skill" not in names

    async def test_use_skill_activates_and_wraps_content(self, orchestrator) -> None:
        orchestrator._skills = AsyncMock()
        orchestrator._skills.activate.return_value = "SKILL STEPS HERE"
        result = await orchestrator._use_skill_result("  demo  ")
        assert result["is_error"] is False
        assert result["data"] == {"skill": "demo", "loaded": True}
        assert "SKILL STEPS HERE" in result["content"][0]["text"]

    async def test_use_skill_unknown_name_is_structured_error(self, orchestrator) -> None:
        orchestrator._skills = AsyncMock()
        orchestrator._skills.activate.return_value = None
        result = await orchestrator._use_skill_result("nope")
        assert result["is_error"] is True
        assert "Unknown skill" in result["data"]["error"]

        empty = await orchestrator._use_skill_result("   ")
        assert empty["is_error"] is True


# ---------------------------------------------------------------------------
# remember: direct durable memory writes
# ---------------------------------------------------------------------------


class TestRemember:
    async def test_remember_persists_kind_namespaced_fact(self, tmp_path) -> None:
        from unittest.mock import MagicMock

        from atlas.agent import AgentOrchestrator
        from atlas.memory import MemoryStore

        memory = MemoryStore(db_path=tmp_path / "remember.db")
        await memory.init()
        try:
            orchestrator = AgentOrchestrator(
                model_mgr=MagicMock(), memory=memory, mcp_client=None,
            )
            names = {
                tool["function"]["name"] for tool in orchestrator._model_facing_tools()
            }
            assert "remember" in names

            result = await orchestrator._remember_result(
                "editor", "用户偏好 VS Code", "preference",
            )
            assert result["is_error"] is False
            stored = await memory.get_fact("agent-preference:editor")
            assert stored == "用户偏好 VS Code"
            facts = await memory.list_facts(category="agent-preference")
            assert facts[0]["memory_type"] == "identity"

            result = await orchestrator._remember_result(
                "deploy", "先跑 tests 再 push", "convention",
            )
            assert result["is_error"] is False
            assert await memory.get_fact("agent-convention:deploy") == "先跑 tests 再 push"

        finally:
            await memory.close()

    async def test_remember_rejects_empty_and_bad_kind(self, tmp_path) -> None:
        from unittest.mock import MagicMock

        from atlas.agent import AgentOrchestrator
        from atlas.memory import MemoryStore

        memory = MemoryStore(db_path=tmp_path / "remember2.db")
        await memory.init()
        try:
            orchestrator = AgentOrchestrator(
                model_mgr=MagicMock(), memory=memory, mcp_client=None,
            )
            empty = await orchestrator._remember_result("", "x")
            assert empty["is_error"] is True

            result = await orchestrator._remember_result("k", "v", "bogus-kind")
            assert result["is_error"] is False  # falls back to kind=fact
            assert result["data"]["kind"] == "fact"
        finally:
            await memory.close()
