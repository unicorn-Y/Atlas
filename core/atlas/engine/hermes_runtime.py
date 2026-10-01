"""Run Atlas turns on the Hermes synchronous conversation loop.

Hermes source: NousResearch/hermes-agent@aea969677c60a1bb72fe227fdfb98f196a2092cc
(MIT). Atlas-specific model, session, callback, and event adaptation lives here.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any, Callable
import uuid

_DONE = object()


class HermesRuntime:
    """Adapt Hermes callbacks and its blocking turn API to Atlas async events."""

    def __init__(
        self,
        *,
        data_dir: str | Path,
        model_manager: Any,
        agent_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.home = Path(data_dir).expanduser().resolve() / "engine"
        self.model_manager = model_manager
        self.agent_factory = agent_factory

    def _agent_factory(self) -> Callable[..., Any]:
        if self.agent_factory is not None:
            return self.agent_factory
        # HERMES_HOME must be set before importing modules that resolve its state root.
        os.environ["HERMES_HOME"] = str(self.home)
        from run_agent import AIAgent

        return AIAgent

    async def run_turn(
        self,
        *,
        message: str,
        conversation_id: str,
        workspace: str | None,
        history: list[dict[str, Any]],
        system_message: str | None = None,
        cancel_event: asyncio.Event | None = None,
        input_callback: Callable[[str, str, list[str] | None], Any] | None = None,
        steer_queue: asyncio.Queue[dict[str, str]] | None = None,
        atlas_agent: Any = None,
        atlas_context: Any = None,
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
        enabled_toolsets: list[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute one Hermes turn on a worker thread and yield callback events."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue()

        def emit(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def on_tool_start(tool_call_id: str, name: str, arguments: dict[str, Any]) -> None:
            emit({"type": "tool_call", "id": tool_call_id, "name": name,
                  "arguments": arguments})

        def on_tool_complete(
            tool_call_id: str, name: str, _arguments: dict[str, Any], result: Any,
        ) -> None:
            if isinstance(result, dict):
                text = str(result.get("content", result))
                is_error = bool(result.get("is_error", False))
            else:
                text = str(result)
                is_error = False
            emit({"type": "tool_result", "id": tool_call_id, "name": name,
                  "content": [{"type": "text", "text": text}], "is_error": is_error})

        def on_event(name: str, data: dict[str, Any]) -> None:
            mapping = {
                "session:compress": "run.compaction.progress",
                "process.completed": "process.completed",
                "usage": "run_usage",
            }
            event_type = mapping.get(str(name))
            if event_type:
                if event_type == "run_usage":
                    emit({"type": event_type, "usage": dict(data)})
                else:
                    emit({"type": event_type, "data": dict(data)})

        def on_clarify(questions: Any) -> None:
            if input_callback is None:
                emit({"type": "input.required", "questions": questions})
                return None
            answers = []
            for question in questions if isinstance(questions, list) else [questions]:
                if isinstance(question, dict):
                    title = str(question.get("question") or question.get("text") or "")
                    options = question.get("options")
                    options = options if isinstance(options, list) else None
                else:
                    title, options = str(question), None
                call_id = f"hermes:{uuid.uuid4().hex}"
                response = input_callback(call_id, title, options)
                if asyncio.iscoroutine(response):
                    response = asyncio.run_coroutine_threadsafe(response, loop).result()
                answers.append(response)
            return answers

        def on_status(kind: str, text: str | None = None) -> None:
            if str(kind) in {"recovery", "retry", "fallback"}:
                emit({"type": "run.recovery.notice", "data": {"message": text or str(kind)}})
            else:
                emit({"type": "run.status", "status": str(kind), "text": text or ""})

        settings = self.model_manager
        current = settings.current_model
        model_config = next(
            (item for item in settings.list_models() if item.get("id") == current), {},
        )
        api_key = getattr(settings, "_api_key", None)
        base_url = getattr(settings, "gateway_base_url", None)
        agent = None
        task: asyncio.Task[Any] | None = None
        try:
            self.home.mkdir(parents=True, exist_ok=True)
            os.environ["HERMES_HOME"] = str(self.home)
            factory = self._agent_factory()
            if atlas_agent is not None and atlas_context is not None:
                from atlas.engine.tool_registry import bind_atlas_tools

                bind_atlas_tools(atlas_agent, atlas_context, loop)
            agent = factory(
                model=settings.current_litellm_model,
                provider="openai",
                api_mode="openai",
                base_url=base_url,
                api_key=api_key,
                session_id=conversation_id,
                cwd=workspace,
                skip_memory=True,
                checkpoints_enabled=False,
                enabled_toolsets=enabled_toolsets or [
                    "file", "terminal", "todo", "clarify", "code_execution",
                    "session_search", "delegation", "atlas",
                ],
                fallback_model=model_config.get("fallback"),
                max_tokens=max_output_tokens or model_config.get("max_output_tokens"),
                reasoning_config={"effort": reasoning_effort} if reasoning_effort else None,
                stream_delta_callback=lambda text: emit({"type": "chunk", "content": str(text)}),
                reasoning_callback=lambda text: emit({"type": "thinking", "content": str(text)}),
                tool_start_callback=(None if atlas_agent is not None else on_tool_start),
                tool_complete_callback=(None if atlas_agent is not None else on_tool_complete),
                clarify_callback=on_clarify,
                status_callback=on_status,
                event_callback=on_event,
            )
            # Hermes opens SessionDB lazily for tools when no gateway supplied one. Atlas
            # always needs its durable turn transcript, even with Hermes memory disabled.
            open_session_db = getattr(agent, "_get_session_db_for_recall", None)
            if callable(open_session_db) and getattr(agent, "_session_db", None) is None:
                open_session_db()

            def run_sync() -> dict[str, Any]:
                if atlas_agent is not None and atlas_context is not None:
                    from atlas.engine.tool_registry import activate_atlas_tool_context

                    activate_atlas_tool_context(atlas_agent, atlas_context, loop)
                try:
                    turn_history = history
                    session_db = getattr(agent, "_session_db", None)
                    if session_db is not None:
                        try:
                            stored = session_db.get_messages_as_conversation(
                                conversation_id, include_ancestors=True,
                            )
                        except TypeError:
                            stored = session_db.get_messages_as_conversation(conversation_id)
                        if stored:
                            # Hermes SessionDB is the canonical cross-turn history. Atlas text
                            # history is passed only once to import pre-C1 conversations.
                            turn_history = stored
                    result = agent.run_conversation(
                        user_message=message,
                        system_message=system_message,
                        conversation_history=turn_history,
                    )
                    usage = getattr(agent, "_last_turn_usage", None)
                    if isinstance(usage, dict):
                        compressor = getattr(agent, "context_compressor", None)
                        context_limit = getattr(compressor, "context_length", None)
                        if not isinstance(context_limit, int) or context_limit <= 0:
                            context_limit = getattr(agent, "_config_context_length", None)
                        emit({"type": "run_usage", "usage": {
                            "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
                            "output_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
                            "cached_input_tokens": usage.get("cached_input_tokens", 0),
                            "context_tokens": usage.get("total_tokens", usage.get("prompt_tokens")),
                            "context_limit": context_limit,
                            "model": getattr(agent, "model", current),
                        }})
                    return result
                finally:
                    if atlas_agent is not None:
                        from atlas.engine.tool_registry import clear_atlas_tool_context

                        clear_atlas_tool_context()
                    loop.call_soon_threadsafe(queue.put_nowait, _DONE)

            task = asyncio.create_task(asyncio.to_thread(run_sync))
            while True:
                if cancel_event is not None and cancel_event.is_set() and not task.done():
                    agent.interrupt(hard_cancel=True)
                if steer_queue is not None:
                    while True:
                        try:
                            steer = steer_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        text = str(steer.get("content") or steer.get("text") or "").strip()
                        if text and agent.steer(text):
                            yield {"type": "run_steered", "content": text,
                                   "event_id": steer.get("event_id", "")}
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.05)
                except TimeoutError:
                    continue
                if event is _DONE:
                    break
                yield event
            result = await task
            if not isinstance(result, dict):
                result = {"final_response": str(result or ""), "messages": []}
            yield {"type": "hermes.result", "result": result}
        finally:
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            close = getattr(agent, "close", None) if agent is not None else None
            if callable(close):
                await asyncio.to_thread(close)
