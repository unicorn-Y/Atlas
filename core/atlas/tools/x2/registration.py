"""Bind the X2 computer / browser bridges into the Hermes tool registry.

One model-facing surface per domain: computer keeps the legacy Atlas alias
names (one shared handler), browser exposes its single 13-action surface.
Handlers run on Hermes' sync tool thread; each call sets the run-scoped
:class:`X2Context` (events → the run's event queue, human prompts → the
run-scoped pending registry that the frontend cards resolve through
``/api/computer/foreground`` and ``/api/browser/handoff``, approvals → the
run's approval callback), awaits the bridge on the Atlas loop with a 310 s
deadline, then restores.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import uuid
from typing import Any, Callable

from atlas.tools.x2 import pending as x2pending
from atlas.tools.x2.context import (
    X2Context,
    current_context,
    reset_context,
    set_context,
)

log = logging.getLogger(__name__)

# Mirrors the engine's tool-call deadline (atlas_policy._call_async): a bridge
# call stuck on a human card / desktop backend must not hang the tool thread.
_TOOL_CALL_TIMEOUT_SECONDS = 310

_REGISTERED = False
_X2_TOOL_NAMES: list[str] = []
_LOCK = None


def build_x2_context(bound_context: Any) -> X2Context:
    """Build the run-scoped X2Context from the bound Atlas AgentContext."""
    input_callback = getattr(bound_context, "input_callback", None)
    run_id = str(getattr(bound_context, "run_id", "") or "") or None
    cancel_event = (
        getattr(bound_context, "cancel_event", None)
        or getattr(bound_context, "_cancel_event", None)
    )

    async def wait_input(prompt: str, options: list[str] | None = None) -> str:
        if run_id:
            # Single resolution channel: the run's cards POST
            # /api/computer/foreground and /api/browser/handoff, which resolve
            # the pending registry for this run (input.response never carries
            # X2 card answers).
            return await x2pending.wait_for_resolution(
                run_id, prompt, options, cancel_event=cancel_event,
            )
        if input_callback is None:  # detached runs (tests / direct mode) only
            return "give_up"
        call_id = f"x2:{uuid.uuid4().hex}"
        answer = input_callback(call_id, prompt, options)
        if asyncio.iscoroutine(answer):
            answer = await answer
        return str(answer or "")

    return X2Context(
        run_id=run_id,
        session_id=str(getattr(bound_context, "conversation_id", "") or "") or None,
        emit=_make_emit(bound_context),
        approval_callback=getattr(bound_context, "approval_callback", None),
        wait_input=wait_input,
        metadata={
            "workspace": str(getattr(bound_context, "workspace", "") or ""),
        },
    )


def _make_emit(bound_context: Any) -> Callable[[str, dict[str, Any]], Any]:
    event_queue = getattr(bound_context, "event_queue", None)

    async def emit(event_type: str, data: dict[str, Any]) -> None:
        if event_queue is not None:
            await event_queue.put({"type": str(event_type), "data": dict(data or {})})

    return emit


def _make_sync_handler(
    name: str,
    bridge_call: Callable[[str, dict[str, Any]], Any],
    resolve: Callable[[str], tuple[Any, Any, asyncio.AbstractEventLoop] | None],
) -> Callable[..., str]:
    def handler(args: dict[str, Any], **kwargs: Any) -> str:
        session_id = str(kwargs.get("session_id") or "")
        bound = resolve(session_id)
        if bound is None:
            return json.dumps(
                {"error": "X2 工具不在活动运行中。"}, ensure_ascii=False,
            )
        _agent, bound_context, loop = bound
        token = set_context(build_x2_context(bound_context))
        try:
            try:
                result = asyncio.run_coroutine_threadsafe(
                    bridge_call(name, dict(args or {})), loop,
                ).result(timeout=_TOOL_CALL_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                log.warning("x2.tool_call_timeout", extra={"tool": name})
                return json.dumps(
                    {"error": f"X2 工具 {name} 执行超时：{_TOOL_CALL_TIMEOUT_SECONDS} 秒内未完成，"
                              "已中止等待。请检查目标应用/浏览器是否在等待人工处理，并告知用户。"},
                    ensure_ascii=False,
                )
        finally:
            reset_context(token)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    return handler


def bind_x2_tools(
    register: Callable[[dict[str, Any], Callable[..., str]], Any],
    register_toolset_name: Callable[[str], None],
    resolve: Callable[[str], tuple[Any, Any, asyncio.AbstractEventLoop] | None],
    toolset: str = "atlas",
) -> list[str]:
    """Register every X2 tool onto the Hermes registry.

    ``register(schema, handler)`` receives the raw ``{"type": "function",
    "function": {...}}`` schema (adapted to the registry shape) and ONE sync
    handler per tool; ``register_toolset_name(name)`` lets the engine add the
    tool to its Atlas toolset membership.
    """
    global _REGISTERED, _LOCK
    if _LOCK is None:
        import threading

        _LOCK = threading.Lock()
    names: list[str] = []
    with _LOCK:
        if _REGISTERED:
            return list(_X2_TOOL_NAMES)
        from atlas.tools.x2 import browser as x2browser
        from atlas.tools.x2 import computer as x2computer

        def make_register(bridge_call: Callable[[str, dict[str, Any]], Any]) -> Callable[..., None]:
            def _register(schema: dict[str, Any], _handler: Callable[..., Any]) -> None:
                function = dict(schema.get("function") or schema)
                name = str(function.get("name", ""))
                if not name:
                    return
                register(
                    name=name,
                    toolset=toolset,
                    schema={
                        "name": name,
                        "description": str(function.get("description", "")),
                        "parameters": function.get("parameters")
                        or {"type": "object", "properties": {}},
                    },
                    handler=_make_sync_handler(name, bridge_call, resolve),
                    is_async=False,
                    description=str(function.get("description", "")),
                    override=True,
                )
                register_toolset_name(name)
                names.append(name)

            return _register

        x2computer.register_computer_tools(make_register(x2computer.call_tool))
        x2browser.register_browser_tools(make_register(x2browser.call_tool))
        from atlas.tools.nodes import register_node_tools

        register_node_tools(
            lambda **kwargs: register(**kwargs), register_toolset_name, resolve, toolset,
        )
        names.extend(["node_status", "node_notify", "node_camera", "node_location", "node_media"])
        _X2_TOOL_NAMES[:] = names
        _REGISTERED = True
    return names


__all__ = ["bind_x2_tools", "build_x2_context", "current_context"]
