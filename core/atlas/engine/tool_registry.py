"""Register Atlas-owned model tools in Hermes and dispatch through Atlas run policy."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import threading
import uuid
from typing import Any

_context = threading.local()
_lock = threading.Lock()
_registered: set[str] = set()
_plan_registered: set[str] = set()
_active_contexts: dict[str, tuple[Any, Any, asyncio.AbstractEventLoop]] = {}
_hermes_fallback_handlers: dict[str, Any] = {}

_ALIASES = {
    "read_file": ("local_file", "read"),
    "write_file": ("local_file", "write"),
    "search_files": ("local_file", "search"),
    "patch": ("local_edit", "patch"),
    "terminal": ("local_shell", None),
    "process_manage": ("local_process", None),
    "clarify": ("ask_user", None),
    "todo_list": ("todo_list", None),
    "execute_code": ("execute_code", None),
    "session_search": ("session_search", None),
    "delegate_task": ("delegate_task", None),
}

_HERMES_CORE_TOOLS = {
    "read_file", "write_file", "patch", "search_files", "terminal",
    "process_manage", "todo_list", "clarify", "execute_code",
    "session_search", "delegate_task",
}
_ATLAS_NATIVE_TOOLS = {
    "todo_list", "execute_code", "session_search", "delegate_task",
}


def _approval_fingerprint(name: str, arguments: dict[str, Any]) -> str:
    stable = {key: value for key, value in arguments.items() if key not in {"cwd", "workdir"}}
    payload = json.dumps([name, stable], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def bind_atlas_tools(agent: Any, runtime: Any, loop: asyncio.AbstractEventLoop) -> None:
    """Expose Atlas tool schemas and bind sync Hermes handlers to this async Atlas run."""
    from tools.registry import registry
    from toolsets import TOOLSETS

    schemas = agent._model_facing_tools()
    names: list[str] = []
    plan_mode = getattr(runtime, "mode", "act") == "plan"
    atlas_toolset = "atlas-plan" if plan_mode else "atlas"
    registered = _plan_registered if plan_mode else _registered
    plan_tools = {"read_file", "search_files", "web_fetch"}
    with _lock:
        indexed = {str(item.get("function", {}).get("name", "")): item for item in schemas}
        if plan_mode:
            indexed = {name: item for name, item in indexed.items() if name in plan_tools}
        for name in _ALIASES:
            if plan_mode and name not in plan_tools:
                continue
            if name in _ATLAS_NATIVE_TOOLS:
                continue
            hermes_schema = registry.get_schema(name)
            if hermes_schema:
                indexed[name] = {"function": hermes_schema}
            previous = registry.get_entry(name)
            if previous is not None and name in _HERMES_CORE_TOOLS:
                _hermes_fallback_handlers.setdefault(name, previous.handler)
        for entry in indexed.values():
            function = entry.get("function", {})
            name = str(function.get("name", ""))
            if not name or name.startswith("local_"):
                continue
            # Hermes supplies richer schemas for its own tools. Atlas only replaces
            # dispatch so those calls pass through Atlas permissions and checkpoints.
            if name in _HERMES_CORE_TOOLS and name not in _ALIASES:
                continue
            schema = {
                "name": name,
                "description": str(function.get("description", "Atlas tool")),
                "parameters": function.get("parameters", {"type": "object", "properties": {}}),
            }

            def handler(args: dict[str, Any], *, _name: str = name, **_kwargs: Any) -> str:
                session_id = str(_kwargs.get("session_id") or "")
                active = _active_contexts.get(session_id) if session_id else None
                bound_agent = active[0] if active else getattr(_context, "agent", None)
                bound_runtime = active[1] if active else getattr(_context, "runtime", None)
                bound_loop = active[2] if active else getattr(_context, "loop", None)
                if bound_agent is None or bound_runtime is None or bound_loop is None:
                    fallback = _hermes_fallback_handlers.get(_name)
                    if fallback is None:
                        return json.dumps({"error": "Atlas 工具不在活动运行中。"}, ensure_ascii=False)
                    try:
                        parameters = inspect.signature(fallback).parameters
                        accepted = {
                            key: value for key, value in _kwargs.items()
                            if key in parameters or any(
                                item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()
                            )
                        }
                    except (TypeError, ValueError):
                        accepted = {}
                    return fallback(args, **accepted)
                tool_name, tool_args = _translate(_name, args)
                from langchain_core.messages import AIMessage

                call_id = f"atlas:{uuid.uuid4().hex}"
                event_queue = getattr(bound_runtime, "event_queue", None)
                if event_queue is not None:
                    asyncio.run_coroutine_threadsafe(event_queue.put({
                        "type": "tool_call", "id": call_id, "name": tool_name,
                        "arguments": tool_args,
                    }), bound_loop).result()
                request = {"name": tool_name, "args": tool_args, "id": call_id, "type": "tool_call"}
                future = asyncio.run_coroutine_threadsafe(
                    bound_agent._execute_tools_node({
                        "messages": [AIMessage(content="", tool_calls=[request])],
                        "pending_events": [], "tool_rounds": 0, "runtime": bound_runtime,
                    }),
                    bound_loop,
                )
                result = future.result()
                messages = result.get("messages", [])
                return str(messages[-1].content) if messages else "工具没有返回内容。"

            registry.register(
                name=name, toolset=atlas_toolset, schema=schema, handler=handler,
                is_async=False, description=schema["description"], override=True,
            )
            registered.add(name)
            names.append(name)

        # `toolsets` is the shared resolver table; the schema source and handlers remain
        # registered through Hermes' canonical registry.
        TOOLSETS[atlas_toolset] = {
            "description": "Atlas 工作区、项目和运行工具",
            "tools": sorted(registered),
            "includes": [],
        }

def activate_atlas_tool_context(agent: Any, runtime: Any, loop: asyncio.AbstractEventLoop) -> None:
    _context.agent = agent
    _context.runtime = runtime
    _context.loop = loop
    session_id = str(getattr(runtime, "conversation_id", "") or "")
    if session_id:
        with _lock:
            _active_contexts[session_id] = (agent, runtime, loop)


def clear_atlas_tool_context() -> None:
    runtime = getattr(_context, "runtime", None)
    session_id = str(getattr(runtime, "conversation_id", "") or "")
    if session_id:
        with _lock:
            active = _active_contexts.get(session_id)
            if active is not None and active[1] is runtime:
                _active_contexts.pop(session_id, None)
    for name in ("agent", "runtime", "loop"):
        if hasattr(_context, name):
            delattr(_context, name)


def _translate(name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tool_name, action = _ALIASES.get(name, (name, None))
    args = dict(arguments)
    if action is not None and tool_name == "local_file":
        args["action"] = action
    elif tool_name == "local_shell":
        args["command"] = args.pop("command", args.pop("cmd", ""))
        args["shell"] = "powershell"
        args["cwd"] = args.pop("workdir", args.get("cwd", ""))
        background = bool(args.pop("background", False))
        args["detached"] = background
        if background:
            args["keep_stdin"] = True
        if args.pop("pty", False):
            args["pty"] = True
        args.pop("notify", None)
        args.pop("notify_on_complete", None)
        args.pop("watch_patterns", None)
        args.pop("heartbeat", None)
        args.pop("persist_on_release", None)
    if name == "search_files":
        args["query"] = args.pop("pattern", args.get("query", ""))
        args.setdefault("path", ".")
    if name == "patch":
        args.pop("mode", None)
        args.pop("patch", None)
        args.pop("replace_all", None)
    if name == "clarify":
        question = args.pop("questions", None)
        if question is None:
            question = args.get("question", "")
        if isinstance(question, list):
            question = question[0] if question else ""
        if isinstance(question, dict):
            args["options"] = question.get("options", args.get("options"))
            question = question.get("question") or question.get("text") or ""
        args["question"] = str(question)
    elif action is not None and tool_name == "ask_user":
        args.pop("action", None)
    if name == "process_manage":
        process_action = str(args.get("action", "list"))
        mapped_action = {
            "poll": "status", "log": "read", "kill": "cancel",
            "wait": "wait", "list": "list", "write": "write_stdin",
            "submit": "submit_stdin", "close": "close_stdin", "handoff": "handoff",
        }.get(process_action)
        if mapped_action:
            args["action"] = mapped_action
            args["execution_id"] = args.pop("session_id", args.get("execution_id", ""))
        else:
            args["action"] = process_action
    return tool_name, args
