"""Atlas in-process policy hooks for Hermes tool execution.

Hermes hook API source: ``hermes_cli/plugins.py::PluginContext.register_hook`` and
``agent/agent_runtime_helpers.py::_dispatch_pre_tool_call_hooks`` at
unicorn-Y/hermes-agent@562ad75baec0c8360f6ce2d48b7d9de56506956c (MIT).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import threading
from pathlib import Path
from typing import Any

_installed: set[int] = set()
_install_lock = threading.Lock()
_checkpoint_lock = threading.Lock()
_ATLAS_WRITE_TOOLS = {
    "remember", "project_note", "create_checkpoint", "restore_checkpoint",
    "kanban_create_board", "kanban_create_task", "kanban_update_task",
    "create_document", "create_spreadsheet", "create_presentation", "run_checks",
    "delegate_task", "delegate_parallel", "subtask_message",
    # X2 computer surface (legacy alias names); observe is read-only and
    # browser_*/clipboard-style names are classified via is_x2_write_tool.
    "computer_window", "computer_mouse", "computer_keyboard", "computer_clipboard",
}


def install_atlas_policy_plugin() -> None:
    """Register Atlas' pre/post tool hooks through Hermes' supported PluginContext API."""
    from hermes_cli.plugins import PluginContext, get_plugin_manager
    from hermes_cli.plugins_manifest import PluginManifest

    manager = get_plugin_manager()
    identity = id(manager)
    with _install_lock:
        if identity in _installed:
            return
        context = PluginContext(PluginManifest(name="atlas-workspace-policy"), manager)
        context.register_hook("pre_tool_call", _pre_tool_call)
        context.register_hook("post_tool_call", _post_tool_call)
        context.register_hook("pre_verify", _pre_verify)
        _installed.add(identity)


def _active(session_id: str = "") -> tuple[Any, Any, Any] | None:
    from atlas.engine.tool_registry import _active_contexts, _context

    if session_id and session_id in _active_contexts:
        return _active_contexts[session_id]

    agent = getattr(_context, "agent", None)
    runtime = getattr(_context, "runtime", None)
    loop = getattr(_context, "loop", None)
    return (agent, runtime, loop) if agent is not None and runtime is not None and loop else None


def _write_tool(name: str, args: dict[str, Any]) -> bool:
    if name in _ATLAS_WRITE_TOOLS or name in {
        "write_file", "patch", "terminal", "execute_code", "delegate_task", "delegate_parallel",
    }:
        return True
    try:
        from atlas.tools.x2.permissions import is_x2_write_tool

        if is_x2_write_tool(name):
            return True
    except ImportError:  # pragma: no cover - X2 module always ships with Atlas
        pass
    if name == "process_manage":
        return args.get("action", "list") in {
            "start", "write_stdin", "terminate", "kill", "submit", "close", "handoff",
        }
    if name == "local_file":
        return args.get("action") in {"write", "append", "mkdir", "copy", "move", "delete"}
    if name in {"local_edit", "local_shell", "local_exec", "execute_command", "run_script"}:
        return True
    return name.startswith(("custom_", "mcp-", "mcp_", "mcp__"))


_PLAN_READ_COMMAND = re.compile(
    r"^\s*(?:git\s+(?:-C\s+\S+\s+)?(?:status|log|diff|show)\b"
    r"|rg\b|ls\b|dir\b|cat\b|type\b|get-content\b)(?:\s|$)", re.I,
)


def _plan_command_is_read_only(command: str) -> bool:
    """Allow the small read-only shell surface used by plan mode."""
    if any(token in command for token in (";", "|", "&", "`", "$(", ">", "<", "\n", "\r")):
        return False
    return bool(_PLAN_READ_COMMAND.match(command))


def _call_async(loop: asyncio.AbstractEventLoop, callback: Any, *args: Any) -> Any:
    result = callback(*args)
    if inspect.isawaitable(result):
        async def await_result() -> Any:
            return await result

        return asyncio.run_coroutine_threadsafe(await_result(), loop).result(timeout=310)
    return result


async def _wait_if_paused(runtime: Any) -> bool:
    """Wait while paused; return True when cancellation wins the race."""
    pause_event = getattr(runtime, "pause_event", None)
    cancel_event = getattr(runtime, "cancel_event", None)
    if pause_event is None or pause_event.is_set():
        return bool(cancel_event is not None and cancel_event.is_set())
    if cancel_event is not None and cancel_event.is_set():
        return True
    pause_task = asyncio.create_task(pause_event.wait())
    cancel_task = asyncio.create_task(cancel_event.wait()) if cancel_event is not None else None
    tasks = {pause_task, *([cancel_task] if cancel_task else [])}
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        return cancel_task in done and cancel_task.result()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def wait_before_model_request(runtime: Any, loop: asyncio.AbstractEventLoop) -> bool:
    """Block Hermes' worker thread before a provider call while Atlas is paused."""
    return bool(_call_async(loop, _wait_if_paused, runtime))


def _blocked(
    runtime: Any,
    loop: asyncio.AbstractEventLoop,
    name: str,
    kwargs: dict[str, Any],
    message: str,
) -> dict[str, str]:
    """Bridge Hermes pre-hook blocks to Atlas' native failure event exactly once."""
    call_id = str(kwargs.get("tool_call_id") or "")
    event_queue = getattr(runtime, "event_queue", None)
    if call_id and event_queue is not None:
        _call_async(loop, event_queue.put, {
            "type": "tool_result", "id": call_id, "name": name,
            "content": [{"type": "text", "text": message}], "is_error": True,
        })
    return {"action": "block", "message": message}


def _checkpoint_first_write(agent: Any, runtime: Any, loop: asyncio.AbstractEventLoop) -> str | None:
    """Snapshot the current local or SSH workspace once before its first write."""
    if getattr(runtime, "hermes_write_checkpoint_created", False):
        return None
    workspace = str(getattr(runtime, "workspace", "") or "")
    try:
        with _checkpoint_lock:
            if getattr(runtime, "hermes_write_checkpoint_created", False):
                return None
            if workspace.startswith("ssh://"):
                callback = getattr(runtime, "ssh_checkpoint_callback", None)
                if callback is None:
                    return "SSH 写操作缺少检查点通道，操作已取消。"
                _call_async(loop, callback, "create", {"paths": ["."]})
            else:
                if not workspace:
                    return "当前对话没有工作目录，无法创建写前检查点。"
                store = getattr(agent, "checkpoints", None)
                if store is None:
                    return "当前对话没有检查点存储，写操作已取消。"
                store.create_checkpoint(
                    workspace, ["."], run_id=getattr(runtime, "run_id", None),
                    conversation_id=getattr(runtime, "conversation_id", None),
                )
            runtime.hermes_write_checkpoint_created = True
    except Exception as exc:
        return f"写前检查点创建失败，操作已取消：{exc}"
    return None


def _pre_tool_call(
    tool_name: str = "", args: dict[str, Any] | None = None, **kwargs: Any,
) -> dict[str, str] | None:
    active = _active(str(kwargs.get("session_id") or ""))
    if active is None:
        return None
    agent, runtime, loop = active
    arguments = dict(args or {})
    name = str(tool_name)
    if getattr(runtime, "pause_event", None) is not None and _call_async(loop, _wait_if_paused, runtime):
        return _blocked(runtime, loop, name, kwargs, "运行已取消，工具未执行。")
    from atlas.engine.tool_permissions import tool_allowed
    if name != "tool_call" and not tool_allowed(
        name, getattr(runtime, "tool_allow", None), getattr(runtime, "tool_deny", []),
    ):
        return _blocked(runtime, loop, name, kwargs, "当前子任务不允许使用这项工具。")
    mode = str(getattr(runtime, "permission_mode", "full_access"))
    is_write = _write_tool(name, arguments)
    if getattr(runtime, "mode", "act") == "plan" and name == "terminal":
        is_write = not _plan_command_is_read_only(str(arguments.get("command") or arguments.get("cmd") or ""))
    if (mode == "read_only" or getattr(runtime, "mode", "act") == "plan"
            or bool(getattr(runtime, "read_only", False))) and is_write:
        # 审查链例外：delegate/review/submit 工具**精确出现**在运行 tool_allow 里时放行
        # （目前只有 /review 拦截会这样配置只读运行）；普通只读会话 tool_allow 不含它们，照旧拦截。
        allow = getattr(runtime, "tool_allow", None)
        review_allowed = (
            name in {"delegate_task", "review_command", "submit_findings"}
            and isinstance(allow, (list, tuple)) and name in allow
        )
        if not review_allowed:
            return _blocked(runtime, loop, name, kwargs, "当前对话是只读模式，不能执行写操作。")

    workspace = str(getattr(runtime, "workspace", "") or "")
    if (workspace.startswith("ssh://") and name == "patch"
            and (arguments.get("patch") or arguments.get("replace_all")
                 or arguments.get("mode") == "patch")):
        return _blocked(
            runtime, loop, name, kwargs,
            "SSH 文件编辑仅支持唯一 old_string/new_string 精确替换；不支持 V4A patch 或 replace_all。",
        )

    callback = getattr(runtime, "user_hook_callback", None)
    from atlas.engine.tool_registry import _ALIASES, NATIVE_FILE_TOOLS

    if name in NATIVE_FILE_TOOLS:
        candidates = [str(arguments.get("path") or ".")]
        if arguments.get("destination"):
            candidates.append(str(arguments["destination"]))
        if name == "patch" and arguments.get("patch"):
            patch_text = str(arguments["patch"])
            candidates = re.findall(
                r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", patch_text, re.M,
            )
            for source, destination in re.findall(
                r"^\*\*\* Move File: (.+?)\s*->\s*(.+)$", patch_text, re.M,
            ):
                candidates.extend((source, destination))
            move_destinations = re.findall(r"^\*\*\* Move to: (.+)$", patch_text, re.M)
            candidates.extend(move_destinations)
        workspace = str(getattr(runtime, "workspace", "") or "")
        if not workspace.startswith("ssh://") and getattr(runtime, "allowed_paths", None):
            roots = [
                Path(item).expanduser().resolve()
                for item in [*runtime.allowed_paths, workspace] if item
            ]
            for candidate in candidates:
                path = Path(candidate).expanduser()
                resolved = (path if path.is_absolute() else Path(workspace) / path).resolve()
                if not any(resolved == root or root in resolved.parents for root in roots):
                    return _blocked(runtime, loop, name, kwargs, "这条路径超出了当前允许访问的目录范围。")

    atlas_tool_names = {
        str(item.get("function", {}).get("name", ""))
        for item in agent._model_facing_tools()
    }
    if callback and (
        name in NATIVE_FILE_TOOLS or (name not in _ALIASES and name not in atlas_tool_names)
    ):
        outcome = _call_async(loop, callback, "tool.before", {
            "tool_name": name, "parameters": arguments,
        })
        if isinstance(outcome, dict) and outcome.get("blocked"):
            return _blocked(
                runtime, loop, name, kwargs,
                str(outcome.get("reason", "Blocked by hook")),
            )

    ask_for_step = mode == "ask_each"
    ask_for_write = mode == "ask_writes" and is_write
    ask_for_non_file_write = mode == "auto_file" and is_write and name not in {"write_file", "patch"}
    if ask_for_step or ask_for_write or ask_for_non_file_write:
        approval = getattr(runtime, "approval_callback", None)
        if approval is None:
            return _blocked(runtime, loop, name, kwargs, "当前对话没有可用的审批通道，写操作已取消。")
        call_id = str(kwargs.get("tool_call_id") or "hermes-tool")
        choice = _call_async(loop, approval, f"approval:{call_id}", name, arguments)
        if choice != "allow":
            return _blocked(runtime, loop, name, kwargs, "操作未获允许，因此已取消。")
        if not name.startswith("mcp__"):
            from atlas.engine.tool_registry import _approval_fingerprint, _translate

            approved = getattr(runtime, "hermes_preapproved_writes", None)
            if approved is not None:
                atlas_name, atlas_args = _translate(name, arguments, runtime)
                approved.add(_approval_fingerprint(atlas_name, atlas_args))

    if is_write and name in NATIVE_FILE_TOOLS and not str(runtime.workspace or "").startswith("ssh://"):
        try:
            for candidate in candidates:
                checkpoint = agent._checkpoint_path(candidate, runtime.workspace, runtime.run_id, runtime.conversation_id)
                _call_async(loop, runtime.event_queue.put, {
                    "type": "checkpoint_created", "checkpoint": checkpoint, "tool": name,
                })
        except Exception as exc:
            return _blocked(runtime, loop, name, kwargs, f"写前检查点创建失败，操作已取消：{exc}")
    if is_write and name.startswith("mcp__"):
        failure = _checkpoint_first_write(agent, runtime, loop)
        if failure:
            return _blocked(runtime, loop, name, kwargs, failure)
    return None


def _post_tool_call(
    tool_name: str = "", args: dict[str, Any] | None = None, result: Any = None, **_kwargs: Any,
) -> None:
    active = _active(str(_kwargs.get("session_id") or ""))
    if active is None:
        return None
    agent, runtime, loop = active
    from atlas.agent.verification_stop import requires_verification
    from atlas.engine.tool_registry import NATIVE_FILE_TOOLS

    payload = result
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}
    if str(tool_name) in {"write_file", "patch"} and isinstance(payload, dict) and not payload.get("error"):
        path = str((args or {}).get("path") or "")
        if path and requires_verification(path):
            runtime.changed_paths.add(path)
            runtime.verification_passed = False
    callback = getattr(runtime, "user_hook_callback", None)
    atlas_tool_names = {
        str(item.get("function", {}).get("name", ""))
        for item in agent._model_facing_tools()
    }
    if callback and (str(tool_name) in NATIVE_FILE_TOOLS or str(tool_name) not in atlas_tool_names):
        _call_async(loop, callback, "tool.after", {
            "tool_name": str(tool_name), "parameters": dict(args or {}),
            "result": result,
        })
    return None


def _pre_verify(session_id: str = "", changed_paths: list[str] | None = None, attempt: int = 0, **_kwargs: Any) -> dict[str, str] | None:
    """Keep Hermes' real stop gate running until Atlas has fresh check evidence."""
    active = _active(session_id)
    if active is None:
        return None
    _, runtime, loop = active
    from atlas.agent.verification_stop import requires_verification
    from atlas.config import get_config

    paths = sorted(path for path in set(changed_paths or []) | runtime.changed_paths if requires_verification(path))
    if not paths or runtime.verification_passed or attempt >= 2 or not get_config().get("agent.verify_before_stop", True):
        return None
    runtime.verify_nudge_sent = True
    if runtime.event_queue is not None:
        _call_async(loop, runtime.event_queue.put, {"type": "run_verify_nudge", "data": {"changed_paths": paths[:8]}})
    return {"action": "continue", "message": "完成前请验证本次代码改动：运行相关测试或检查，修复失败，再报告验证结果。改动文件：" + ", ".join(paths[:8])}
