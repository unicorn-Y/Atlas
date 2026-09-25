"""Atlas Agent Orchestrator — LangGraph-based task execution."""

from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

import structlog
from litellm import acompletion

from atlas.config import get_config
from atlas.models import ModelManager
from atlas.memory import MemoryStore

log = structlog.get_logger()

# System prompt for Atlas
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


class AgentOrchestrator:
    """Orchestrates agent execution.

    Currently implements a simple chat completion loop.
    Will be upgraded to full LangGraph state machine with:
    - Task decomposition
    - Tool selection and execution
    - Verification steps
    - Multi-agent coordination
    """

    def __init__(self, model_mgr: ModelManager, memory: MemoryStore) -> None:
        self._model_mgr = model_mgr
        self._memory = memory

    async def run(
        self,
        message: str,
        conversation_id: str,
        model: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run the agent on a user message, yielding streaming events.

        Args:
            message: The user's message
            conversation_id: ID of the conversation
            model: Optional model override (otherwise uses current selection)
        """
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

        # Build messages from conversation history
        cfg = get_config()
        history = await self._memory.get_conversation_messages(
            conversation_id, limit=cfg.max_context_messages
        )

        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in history:
            # Skip the current message (already in history from server.py)
            messages.append({"role": msg["role"], "content": msg["content"]})

        # Call LiteLLM with streaming
        try:
            response = await acompletion(
                model=litellm_model,
                messages=messages,
                stream=True,
                max_tokens=4096,
            )

            full_response = ""
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    full_response += delta.content
                    yield {
                        "type": "chunk",
                        "content": delta.content,
                    }

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
