"""Tests for the LangGraph-based AgentOrchestrator."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from atlas.agent import AgentOrchestrator, AgentState, SYSTEM_PROMPT, MAX_TOOL_ROUNDS
from atlas.tools.mcp_client import MCPClient, ToolInfo


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

class TestGraphStructure:
    def test_graph_compiles(self, orchestrator) -> None:
        """Graph should compile without errors."""
        assert orchestrator._graph is not None

    def test_should_use_tools_no_messages(self, orchestrator) -> None:
        state: AgentState = {"messages": [], "pending_events": [], "tool_rounds": 0}
        assert orchestrator._should_use_tools(state) == "end"

    def test_should_use_tools_with_tool_calls(self, orchestrator) -> None:
        ai = AIMessage(
            content="Let me check",
            tool_calls=[{"name": "fs__read", "args": {}, "id": "t1"}],
        )
        state: AgentState = {
            "messages": [ai],
            "pending_events": [],
            "tool_rounds": 0,
        }
        assert orchestrator._should_use_tools(state) == "execute_tools"

    def test_should_use_tools_plain_ai(self, orchestrator) -> None:
        ai = AIMessage(content="Here is your answer")
        state: AgentState = {
            "messages": [ai],
            "pending_events": [],
            "tool_rounds": 0,
        }
        assert orchestrator._should_use_tools(state) == "end"

    def test_should_use_tools_max_rounds(self, orchestrator) -> None:
        """Should stop after MAX_TOOL_ROUNDS."""
        ai = AIMessage(
            content="",
            tool_calls=[{"name": "fs__read", "args": {}, "id": "t1"}],
        )
        state: AgentState = {
            "messages": [ai],
            "pending_events": [],
            "tool_rounds": MAX_TOOL_ROUNDS,
        }
        assert orchestrator._should_use_tools(state) == "end"


# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------

class TestMessageConversion:
    def test_system_message(self) -> None:
        msgs = AgentOrchestrator._to_litellm_messages(
            [SystemMessage(content="system")]
        )
        assert msgs == [{"role": "system", "content": "system"}]

    def test_human_message(self) -> None:
        msgs = AgentOrchestrator._to_litellm_messages(
            [HumanMessage(content="hello")]
        )
        assert msgs == [{"role": "user", "content": "hello"}]

    def test_ai_message_plain(self) -> None:
        msgs = AgentOrchestrator._to_litellm_messages(
            [AIMessage(content="world")]
        )
        assert msgs == [{"role": "assistant", "content": "world"}]

    def test_ai_message_with_tool_calls(self) -> None:
        ai = AIMessage(
            content="checking",
            tool_calls=[{"name": "read", "args": {"path": "/tmp"}, "id": "t1"}],
        )
        msgs = AgentOrchestrator._to_litellm_messages([ai])
        assert len(msgs) == 1
        m = msgs[0]
        assert m["role"] == "assistant"
        assert len(m["tool_calls"]) == 1
        tc = m["tool_calls"][0]
        assert tc["id"] == "t1"
        assert tc["function"]["name"] == "read"
        assert json.loads(tc["function"]["arguments"]) == {"path": "/tmp"}

    def test_tool_message(self) -> None:
        msgs = AgentOrchestrator._to_litellm_messages(
            [ToolMessage(content="file contents", tool_call_id="t1")]
        )
        assert msgs == [{"role": "tool", "tool_call_id": "t1", "content": "file contents"}]

    def test_roundtrip_conversation(self) -> None:
        """Full conversation roundtrip."""
        conversation = [
            SystemMessage(content="sys"),
            HumanMessage(content="read /tmp/a.txt"),
            AIMessage(
                content="",
                tool_calls=[{"name": "read", "args": {"path": "/tmp/a.txt"}, "id": "c1"}],
            ),
            ToolMessage(content="hello world", tool_call_id="c1"),
            AIMessage(content="The file contains: hello world"),
        ]
        msgs = AgentOrchestrator._to_litellm_messages(conversation)
        assert len(msgs) == 5
        roles = [m["role"] for m in msgs]
        assert roles == ["system", "user", "assistant", "tool", "assistant"]


# ---------------------------------------------------------------------------
# Execute tools node
# ---------------------------------------------------------------------------

class TestExecuteTools:
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
        state: AgentState = {
            "messages": [HumanMessage(content="read a.txt"), ai],
            "pending_events": [],
            "tool_rounds": 0,
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

        # tool_rounds incremented
        assert result["tool_rounds"] == 1

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
        state: AgentState = {
            "messages": [ai],
            "pending_events": [],
            "tool_rounds": 0,
        }

        result = await orchestrator._execute_tools_node(state)
        assert len(result["messages"]) == 2
        assert result["tool_rounds"] == 1

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
        state: AgentState = {
            "messages": [ai],
            "pending_events": [],
            "tool_rounds": 0,
        }

        result = await orchestrator._execute_tools_node(state)
        events = result["pending_events"]
        tr = next(e for e in events if e["type"] == "tool_result")
        assert tr["is_error"] is True


# ---------------------------------------------------------------------------
# Full run() integration (mocked LLM)
# ---------------------------------------------------------------------------

class TestRun:
    async def test_run_simple_response(self, orchestrator, memory) -> None:
        """Simple response with no tool calls."""
        # Mock acompletion to return a streaming response
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Hello!"

        mock_stream = AsyncMock()
        mock_stream.__aiter__ = lambda self: self
        chunks = [mock_chunk]
        mock_stream.__anext__ = AsyncMock(
            side_effect=chunks + [StopAsyncIteration()]
        )

        with patch("atlas.agent.acompletion") as mock_ac:
            # No tools → streaming path
            orchestrator._mcp.get_tools_for_llm.return_value = []
            mock_ac.return_value = mock_stream

            events = []
            async for event in orchestrator.run("hi", "conv-1"):
                events.append(event)

        # Should have chunk + done events
        types = [e["type"] for e in events]
        assert "done" in types
        memory.save_message.assert_called_once()

    async def test_run_with_tool_call(self, orchestrator, memory, mcp_client) -> None:
        """Response that includes tool calling."""
        # Set up tools
        mcp_client.get_tools_for_llm.return_value = [
            {"type": "function", "function": {
                "name": "fs__read", "description": "Read a file",
                "parameters": {"type": "object"},
            }}
        ]

        # First call: LLM returns tool call
        mock_tc = MagicMock()
        mock_tc.id = "tc1"
        mock_tc.function.name = "fs__read"
        mock_tc.function.arguments = '{"path": "/tmp/a.txt"}'

        mock_response_1 = MagicMock()
        mock_response_1.choices = [MagicMock()]
        mock_response_1.choices[0].message.content = ""
        mock_response_1.choices[0].message.tool_calls = [mock_tc]

        # Second call: LLM returns final text
        mock_response_2 = MagicMock()
        mock_response_2.choices = [MagicMock()]
        mock_response_2.choices[0].message.content = "The file says hello"
        mock_response_2.choices[0].message.tool_calls = None

        # MCP tool returns result
        mcp_client.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "hello"}],
            "is_error": False,
        })

        with patch("atlas.agent.acompletion") as mock_ac:
            mock_ac.side_effect = [mock_response_1, mock_response_2]

            events = []
            async for event in orchestrator.run("read /tmp/a.txt", "conv-2"):
                events.append(event)

        types = [e["type"] for e in events]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "chunk" in types
        assert "done" in types

        # Verify MCP was called
        mcp_client.call_tool.assert_called_once_with(
            "fs__read", {"path": "/tmp/a.txt"}
        )

    async def test_run_error_handling(self, orchestrator, memory) -> None:
        """LLM call failure yields error event."""
        orchestrator._mcp.get_tools_for_llm.return_value = []

        with patch("atlas.agent.acompletion") as mock_ac:
            mock_ac.side_effect = RuntimeError("API down")

            events = []
            async for event in orchestrator.run("hi", "conv-3"):
                events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "API down" in events[0]["detail"]
