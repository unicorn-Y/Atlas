"""Atlas Agent Orchestrator — LangGraph state-machine with tool calling."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, AsyncIterator, Callable, Literal

import structlog
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from litellm import acompletion
from typing_extensions import TypedDict

from atlas.config import get_config
from atlas.memory import MemoryStore
from atlas.models import ModelManager
from atlas.tools.mcp_client import MCPClient

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Atlas, an all-in-one AI personal assistant.

Core principles:
- Complete tasks fully — don't cut corners or stop early
- Be honest about what you know and don't know
- When using tools, report what you're doing and what you find
- Speak the user's language (Chinese or English, match their input)
- Be direct and concise — give results first, explanations after

You have access to various tools through MCP servers. Use them proactively
when they would help accomplish the user's goal.
"""

MAX_TOOL_ROUNDS = 10


# ---------------------------------------------------------------------------
# Agent State
# ---------------------------------------------------------------------------

@dataclass
class AgentRunContext:
    """Control hooks scoped to one agent run."""

    cancel_event: asyncio.Event | None = None
    pause_event: asyncio.Event | None = None
    approval_callback: Callable[[str, str, dict], Any] | None = None


class AgentState(TypedDict):
    """LangGraph state for the agent."""

    messages: Annotated[list[BaseMessage], add_messages]
    # Accumulates events to be yielded to the client
    pending_events: list[dict[str, Any]]
    # Tracks tool-call rounds to prevent infinite loops
    tool_rounds: int
    # Set when run is cancelled externally
    cancelled: bool
    # Per-run control hooks; never stored on the shared orchestrator.
    runtime: AgentRunContext


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """LangGraph-based agent with tool calling.

    Graph structure::

        START → think → (has tool_calls?) → execute_tools → think
                     ↘ (no tool_calls)  → END

    The orchestrator builds the graph once, then each ``run()`` call
    invokes it with the conversation's messages.
    """

    # Tools that require explicit user approval before execution
    APPROVAL_REQUIRED_TOOLS: set[str] = {
        "write_file", "delete_file", "move_file",
        "execute_command", "run_script",
    }

    def __init__(
        self,
        model_mgr: ModelManager,
        memory: MemoryStore,
        mcp_client: MCPClient | None = None,
    ) -> None:
        self._model_mgr = model_mgr
        self._memory = memory
        self._mcp = mcp_client
        self._graph = self._build_graph()

    # -- graph construction --------------------------------------------------

    def _build_graph(self) -> Any:
        """Build and compile the LangGraph state machine."""
        graph = StateGraph(AgentState)

        graph.add_node("think", self._think_node)
        graph.add_node("execute_tools", self._execute_tools_node)

        graph.add_edge(START, "think")
        graph.add_conditional_edges(
            "think",
            self._should_use_tools,
            {
                "execute_tools": "execute_tools",
                "end": END,
            },
        )
        graph.add_edge("execute_tools", "think")

        return graph.compile()

    # -- routing -------------------------------------------------------------

    def _should_use_tools(self, state: AgentState) -> Literal["execute_tools", "end"]:
        """Decide whether to execute tools or finish."""
        messages = state["messages"]
        if not messages:
            return "end"

        last = messages[-1]
        if (
            isinstance(last, AIMessage)
            and last.tool_calls
            and state["tool_rounds"] < MAX_TOOL_ROUNDS
        ):
            return "execute_tools"
        return "end"

    # -- nodes ---------------------------------------------------------------

    async def _think_node(self, state: AgentState) -> dict[str, Any]:
        """Call the LLM, possibly producing tool calls."""
        litellm_model = self._model_mgr.current_litellm_model
        tools = self._mcp.get_tools_for_llm() if self._mcp else []

        # Convert LangChain messages to dicts for LiteLLM
        lc_messages = self._to_litellm_messages(state["messages"])

        kwargs: dict[str, Any] = {
            "model": litellm_model,
            "messages": lc_messages,
            "max_tokens": 4096,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        events: list[dict[str, Any]] = []

        if tools:
            # Non-streaming when tools available (simplifies tool_call parsing)
            response = await acompletion(**kwargs, stream=False)
            choice = response.choices[0]
            msg = choice.message

            content = msg.content or ""
            tool_calls_raw = getattr(msg, "tool_calls", None) or []

            # Emit text chunks
            if content:
                events.append({"type": "chunk", "content": content})

            # Build AIMessage
            if tool_calls_raw:
                tc_list = [
                    {
                        "name": tc.function.name,
                        "args": json.loads(tc.function.arguments)
                        if isinstance(tc.function.arguments, str)
                        else tc.function.arguments,
                        "id": tc.id,
                    }
                    for tc in tool_calls_raw
                ]
                ai_msg = AIMessage(content=content, tool_calls=tc_list)

                # Emit tool_call events
                for tc in tc_list:
                    events.append({
                        "type": "tool_call",
                        "id": tc["id"],
                        "name": tc["name"],
                        "arguments": tc["args"],
                    })
            else:
                ai_msg = AIMessage(content=content)

        else:
            # Streaming when no tools
            response = await acompletion(**kwargs, stream=True)
            full_text = ""
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    full_text += delta.content
                    events.append({"type": "chunk", "content": delta.content})
            ai_msg = AIMessage(content=full_text)

        return {
            "messages": [ai_msg],
            "pending_events": state["pending_events"] + events,
        }

    async def _execute_tools_node(self, state: AgentState) -> dict[str, Any]:
        """Execute tool calls from the last AI message.

        For tools in APPROVAL_REQUIRED_TOOLS, emits an approval.required
        event and waits for the approval callback before executing.
        """
        messages = state["messages"]
        last = messages[-1]
        assert isinstance(last, AIMessage) and last.tool_calls

        events: list[dict[str, Any]] = []
        tool_messages: list[ToolMessage] = []
        ctx = state["runtime"]

        for tc in last.tool_calls:
            fn_name = tc["name"]
            fn_args = tc["args"]
            tc_id = tc["id"]

            # Check cancellation between tool calls
            if ctx.cancel_event and ctx.cancel_event.is_set():
                break

            # Wait if paused
            if ctx.pause_event:
                await ctx.pause_event.wait()

            # Approval gate for sensitive tools
            if fn_name in self.APPROVAL_REQUIRED_TOOLS and ctx.approval_callback:
                approval_event_id = f"approval:{tc_id}"
                events.append({
                    "type": "approval_required",
                    "event_id": approval_event_id,
                    "tool_call_id": tc_id,
                    "name": fn_name,
                    "arguments": fn_args,
                })

                # Ask server layer for approval
                choice = await ctx.approval_callback(
                    approval_event_id, fn_name, fn_args
                )

                if choice != "allow":
                    # Denied — skip this tool, return a synthetic error
                    events.append({
                        "type": "tool_result",
                        "id": tc_id,
                        "name": fn_name,
                        "content": [{"type": "text", "text": f"Tool '{fn_name}' denied by user."}],
                        "is_error": True,
                    })
                    tool_messages.append(
                        ToolMessage(
                            content=f"Tool '{fn_name}' denied by user.",
                            tool_call_id=tc_id,
                        )
                    )
                    continue

            # Call the MCP tool
            assert self._mcp is not None
            result = await self._mcp.call_tool(fn_name, fn_args)

            events.append({
                "type": "tool_result",
                "id": tc_id,
                "name": fn_name,
                "content": result["content"],
                "is_error": result["is_error"],
            })

            # Build ToolMessage for the LLM
            result_text = "\n".join(
                b.get("text", str(b)) for b in result["content"]
            )
            tool_messages.append(
                ToolMessage(content=result_text, tool_call_id=tc_id)
            )

        return {
            "messages": tool_messages,
            "pending_events": state["pending_events"] + events,
            "tool_rounds": state["tool_rounds"] + 1,
        }

    # -- public API ----------------------------------------------------------

    async def run(
        self,
        message: str,
        conversation_id: str,
        model: str | None = None,
        cancel_event: asyncio.Event | None = None,
        pause_event: asyncio.Event | None = None,
        approval_callback: Callable[[str, str, dict], Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run the agent on a user message, yielding streaming events.

        Args:
            message: The user's input text.
            conversation_id: Conversation to append to.
            model: Optional model override for this run.
            cancel_event: asyncio.Event — set to cancel the run.
            pause_event: asyncio.Event — clear to pause, set to resume.
            approval_callback: async (event_id, tool_name, args) -> 'allow'|'deny'

        Events yielded:
            {"type": "chunk", "content": "..."}
            {"type": "tool_call", "id": "...", "name": "...", "arguments": {...}}
            {"type": "tool_result", "id": "...", "name": "...", "content": [...], "is_error": bool}
            {"type": "approval_required", "event_id": "...", "tool_call_id": "...", ...}
            {"type": "done", "message_id": "...", "model": "..."}
            {"type": "error", "detail": "..."}
        """
        runtime = AgentRunContext(
            cancel_event=cancel_event,
            pause_event=pause_event,
            approval_callback=approval_callback,
        )

        # Resolve model
        if model:
            self._model_mgr.select(model)
        litellm_model = self._model_mgr.current_litellm_model

        log.info(
            "agent.run",
            model=litellm_model,
            conv=conversation_id,
            msg_len=len(message),
        )

        # Build initial messages from conversation history
        cfg = get_config()
        history = await self._memory.get_conversation_messages(
            conversation_id, limit=cfg.max_context_messages
        )

        initial_messages: list[BaseMessage] = [SystemMessage(content=SYSTEM_PROMPT)]
        for msg in history:
            if msg["role"] == "user":
                initial_messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                initial_messages.append(AIMessage(content=msg["content"]))

        # Run the graph
        try:
            result = await self._graph.ainvoke({
                "messages": initial_messages,
                "pending_events": [],
                "tool_rounds": 0,
                "runtime": runtime,
            })

            # Yield all accumulated events
            for event in result["pending_events"]:
                yield event

            # Extract the final assistant text from the last AIMessage
            full_response = ""
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage) and not msg.tool_calls:
                    full_response = msg.content
                    break

            # Save assistant response
            msg_id = await self._memory.save_message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_response,
                metadata={"model": litellm_model},
            )

            yield {
                "type": "done",
                "message_id": msg_id,
                "model": self._model_mgr.current_model,
            }

        except Exception as e:
            log.error("agent.run.error", error=str(e))
            yield {
                "type": "error",
                "detail": f"Model call failed: {e}",
            }

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _to_litellm_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
        """Convert LangChain messages to LiteLLM-compatible dicts."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or "",
                }
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["args"]),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                result.append(entry)
            elif isinstance(msg, ToolMessage):
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
            else:
                result.append({"role": "user", "content": str(msg.content)})
        return result
