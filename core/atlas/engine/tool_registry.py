"""Register Atlas-owned model tools in Hermes and dispatch through Atlas run policy."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import math
import os
from pathlib import Path
import threading
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_context = threading.local()
_lock = threading.Lock()
_registered: set[str] = set()
_plan_registered: set[str] = set()
_atlas_mcp_registered: dict[str, set[str]] = {}
_active_contexts: dict[str, tuple[Any, Any, asyncio.AbstractEventLoop]] = {}
_engine_fallback_handlers: dict[str, Any] = {}
_engine_entries: dict[str, Any] = {}
_inline_wrapped: set[str] = set()
_TOOLSETS: dict[str, dict[str, Any]] = {}
NATIVE_FILE_TOOLS = {"read_file", "write_file", "patch", "search_files"}
_LSP_WRITE_TOOLS = {"write_file", "patch"}
_LSP_SKIP = object()  # sentinel: the LSP write seam did not apply to this call

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
    "new_context_window": ("new_context_window", None),
}

# Every Atlas alias above crosses the same host bridge, but its result has a
# tool-specific meaning. Most bridge handlers return text. Reading an image is
# the one exception: it may return the registry's multimodal envelope.
_ALIAS_OUTPUT_DESCRIPTIONS = {
    "read_file": "File contents, or a multimodal envelope when the file is an image.",
    "write_file": "Text receipt describing the file write outcome.",
    "search_files": "Text search results from the requested workspace paths.",
    "patch": "Text receipt describing the patch outcome and any diagnostics.",
    "terminal": "Text output from the requested terminal command.",
    "process_manage": "Text status or output for the requested background process operation.",
    "clarify": "Text result from the user clarification request.",
    "todo_list": "Text representation of the updated task list.",
    "execute_code": "Text output from the requested code execution.",
    "session_search": "Text search results from the requested session query.",
    "delegate_task": "Text result describing the delegated task outcome.",
    "new_context_window": "Text handoff summary for the next model context.",
}


def _alias_output_schema(name: str) -> dict[str, Any]:
    """Return the output shape declared for one Atlas alias registration."""
    description = _ALIAS_OUTPUT_DESCRIPTIONS[name]
    if name == "read_file":
        return {
            "title": "read_file output",
            "description": description,
            "oneOf": [
                {"type": "string"},
                {
                    "type": "object",
                    "properties": {
                        "_multimodal": {"const": True},
                        "content": {"type": "array"},
                    },
                    "required": ["_multimodal", "content"],
                    "additionalProperties": True,
                },
            ],
        }
    return {
        "title": f"{name} output",
        "description": description,
        "type": "string",
    }

_HERMES_CORE_TOOLS = {
    "read_file", "write_file", "patch", "search_files", "terminal",
    "process_manage", "todo_list", "clarify", "execute_code", "new_context_window",
    "session_search", "delegate_task",
}
_ATLAS_NATIVE_TOOLS = {
    "todo_list", "execute_code", "session_search", "delegate_task", "new_context_window",
}


def _approval_fingerprint(name: str, arguments: dict[str, Any]) -> str:
    stable = {key: value for key, value in arguments.items() if key not in {"cwd", "workdir"}}
    payload = json.dumps([name, stable], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _append_repetition_reminder(
    runtime: Any, name: str, arguments: dict[str, Any], result: str, *, threshold: int | None = None,
) -> str:
    if name not in {"patch", "write_file"} or not arguments.get("path"):
        return result
    if threshold is None:
        from atlas.config import get_config

        threshold = int(get_config().get("tools.same_file_edit_reminder_threshold", 6))
    path = str(arguments["path"])
    counts = runtime.file_edit_counts
    counts[path] = counts.get(path, 0) + 1
    if counts[path] >= threshold:
        return result + (
            "\n\n提醒：你已在本轮反复修改同一文件，请先重新读取并检查结果，再换一种思路继续。"
        )
    return result


def _read_text_for_lsp(raw_path: Any, runtime: Any) -> str | None:
    """Best-effort workspace-aware text read (``None`` = missing/unreadable)."""
    raw = str(raw_path or "")
    if not raw:
        return None
    try:
        resolved = Path(raw)
        if not resolved.is_absolute():
            workspace = str(getattr(runtime, "workspace", "") or "")
            if workspace:
                resolved = Path(workspace) / resolved
        if resolved.is_file():
            return resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return None


def _v4a_touched_paths(args: dict[str, Any], runtime: Any) -> list[str]:
    """Path-less V4A patch → local files named in its headers, workspace-resolved.

    Reuses Hermes' own V4A header collector (the same one its write-precheck uses);
    returns ``[]`` for anything that is not a V4A patch or whose headers are invalid
    (the native handler will surface that error itself).
    """
    if str(args.get("mode") or "") != "patch" or not str(args.get("patch") or ""):
        return []
    try:
        from atlas.engine.tools.file_tools import _collect_v4a_header_paths

        collected = _collect_v4a_header_paths(str(args["patch"]))
    except Exception:  # noqa: BLE001
        logger.debug("tool_registry.v4a_header_paths_unavailable", exc_info=True)
        return []
    if isinstance(collected, str) or not collected:
        return []
    workspace = str(getattr(runtime, "workspace", "") or "")
    resolved: list[str] = []
    for raw in collected[0]:
        path = Path(raw)
        if not path.is_absolute() and workspace:
            path = Path(workspace) / raw
        resolved.append(str(path))
    return resolved


def _lsp_pre_write(args: dict[str, Any], runtime: Any) -> Any:
    """C6 LSP seam (pre-write): capture current content + delta baseline.  Never raises.

    Returns the single-file pre-content, a ``{normalized path: pre-content}`` dict for a
    path-less V4A multi-file patch, or the ``_LSP_SKIP`` sentinel when the seam does not
    apply (no path and no V4A headers).
    """
    path = str(args.get("path") or "")
    if not path:
        touched = _v4a_touched_paths(args, runtime)
        if not touched:
            return _LSP_SKIP
        pre: dict[str, str | None] = {}
        try:
            from atlas.engine.lsp_bridge import snapshot_before_write

            for resolved in touched:
                key = os.path.normcase(os.path.abspath(resolved))
                pre[key] = _read_text_for_lsp(resolved, runtime)
                snapshot_before_write(resolved)
        except Exception:  # noqa: BLE001
            logger.debug("tool_registry.lsp_pre_write_snapshot_failed", exc_info=True)
            pass
        return pre or _LSP_SKIP
    pre = _read_text_for_lsp(path, runtime)
    try:
        from atlas.engine.lsp_bridge import snapshot_before_write

        snapshot_before_write(path)
    except Exception:  # noqa: BLE001
        logger.debug("tool_registry.lsp_snapshot_failed", exc_info=True)
        pass
    return pre


def _lsp_attach_report(
    runtime: Any, loop: asyncio.AbstractEventLoop | None, args: dict[str, Any],
    pre_content: Any, result: Any,
) -> Any:
    """C6 LSP seam (post-write): append the atlas.lsp delta report to a successful write."""
    try:
        if not isinstance(result, str):
            return result
        details = json.loads(result)
        if not isinstance(details, dict) or details.get("error"):
            return result  # 失败/被拒的写不上报
        if isinstance(pre_content, dict):
            return _lsp_attach_v4a_report(runtime, loop, pre_content, result, details)
        path = str(args.get("path") or "")
        if not path:
            return result
        from atlas.engine.lsp_bridge import report_after_edit

        report = report_after_edit(
            runtime, path, None if pre_content is _LSP_SKIP else pre_content,
            _read_text_for_lsp(args.get("path"), runtime), loop=loop,
        )
        if report:
            return result + "\n\n" + report
    except Exception:  # noqa: BLE001
        logger.debug("tool_registry.lsp_attach_report_failed", exc_info=True)
        pass
    return result


def _lsp_relative(path: str, workspace: str) -> str:
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(workspace)) if workspace else None
    except ValueError:  # 不同盘符
        rel = None
    if not rel or rel == "." or rel.startswith(".."):
        return str(path)
    return rel.replace(os.sep, "/")


def _lsp_attach_v4a_report(
    runtime: Any, loop: asyncio.AbstractEventLoop | None,
    pre_state: dict[str, str | None], result: str, details: dict[str, Any],
) -> str:
    """Path-less V4A patch: per-file delta over Hermes' own ``files_modified`` result metadata.

    Emits the normal per-file ``lsp.diagnostics`` events; zero-new-diagnostics files stay
    silent; unreadable (deleted/binary) files never crash the patch result.
    """
    modified = details.get("files_modified")
    if not isinstance(modified, list):
        return result
    workspace = str(getattr(runtime, "workspace", "") or "")
    from atlas.engine.lsp_bridge import report_after_edit

    sections: list[str] = []
    for touched in modified:
        path = str(touched or "")
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        pre = pre_state.get(key)
        if pre is None and key not in pre_state:
            continue  # 不在快照集合里的路径不报（防御：结果元数据异常扩张）
        block = report_after_edit(runtime, path, pre, _read_text_for_lsp(path, runtime), loop=loop)
        if block:
            sections.append(f"[{_lsp_relative(path, workspace)}]\n{block}")
    if not sections:
        return result
    return result + "\n\n本次 V4A 多文件补丁引入的诊断：\n\n" + "\n\n".join(sections)


def _multimodal_image_result(data_url: str, path: str) -> dict[str, Any]:
    return {
        "_multimodal": True,
        "content": [
            {"type": "text", "text": f"图片已读取：{Path(path).name}"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
        "text_summary": f"图片已读取：{Path(path).name}",
    }


def _read_file_result(agent: Any, arguments: dict[str, Any], result: str) -> str | dict[str, Any]:
    path = str(arguments.get("path") or "")
    if Path(path).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        return result
    try:
        details = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return result
    image_path = Path(path).expanduser()
    image_read_error = (
        image_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        and isinstance(details, dict)
        and bool(details.get("error"))
    )
    if not isinstance(details, dict) or not (details.get("is_image") or image_read_error):
        return result
    supports_vision = getattr(agent, "_model_supports_vision", None)
    if callable(supports_vision) and supports_vision():
        from atlas.engine.tools.vision_tools import _resize_image_for_vision

        if not image_path.is_absolute():
            image_path = Path(getattr(agent, "cwd", None) or Path.cwd()) / image_path
        if not image_path.is_file():
            return f"图片文件不存在：{path}"
        return _multimodal_image_result(
            _resize_image_for_vision(
                image_path.resolve(), max_base64_bytes=5 * 1024 * 1024,
                max_dimension=2048, force_jpeg=True,
            ),
            path,
        )
    from atlas.engine.tools.registry import registry

    vision_entry = registry.get_entry("vision_analyze")
    if vision_entry is not None and vision_entry.check_fn is not None and vision_entry.check_fn():
        from atlas.engine.utils import run_async

        return run_async(vision_entry.handler(
            {"image_url": path, "question": "请详细描述图片内容及其中可见的文字。"},
            session_id=str(getattr(agent, "session_id", "") or ""),
        ))
    return "当前模型不支持视觉，且没有配置视觉模型，无法读取这张图片。"


def bind_atlas_tools(agent: Any, runtime: Any, loop: asyncio.AbstractEventLoop) -> None:
    """Expose Atlas tool schemas and bind sync Hermes handlers to this async Atlas run."""
    from atlas.engine.tools.registry import registry
    from atlas.repomap import REPOMAP_TOOL_SPEC

    if registry.get_entry("new_context_window") is None:
        registry.register(
            name="new_context_window", toolset="atlas",
            schema={
                "name": "new_context_window",
                "description": "Summarize the current task and continue it in a clean model context while preserving the conversation history.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            handler=lambda _args, **_kwargs: "Context handoff is only available during an Atlas run.",
            is_async=False, override=True,
        )
    repo_map_name = str(REPOMAP_TOOL_SPEC["name"])
    repo_map_parameters = dict(REPOMAP_TOOL_SPEC["input_schema"])
    repo_map_parameters["properties"] = {
        key: value
        for key, value in dict(repo_map_parameters.get("properties", {})).items()
        if key != "root"
    }
    repo_map_parameters["required"] = [
        key for key in repo_map_parameters.get("required", []) if key != "root"
    ]
    schemas = [
        *agent._model_facing_tools(),
        {"type": "function", "function": {
            "name": repo_map_name,
            "description": (
                str(REPOMAP_TOOL_SPEC.get("description", ""))
                + " The repository root is inferred from the active Atlas workspace."
            ),
            "parameters": repo_map_parameters,
        }},
    ]
    names: list[str] = []
    plan_mode = getattr(runtime, "mode", "act") == "plan"
    atlas_toolset = "atlas-plan" if plan_mode else "atlas"
    registered = _plan_registered if plan_mode else _registered
    mcp_client = getattr(agent, "_mcp", None)
    mcp_names = {
        str(item.get("function", {}).get("name", ""))
        for item in (mcp_client.get_tools_for_llm() if mcp_client else [])
        if str(item.get("function", {}).get("name", ""))
    }
    scope = registry.current_scope_key()
    plan_tools = {
        "read_file", "search_files", "terminal", "web_fetch", "web_search", "web_extract",
        repo_map_name,
    }
    with _lock:
        # Atlas copies MCP schemas into its own toolset so every call passes through
        # Atlas approval/checkpoint policy. Remove copies whose source server vanished.
        if not plan_mode:
            previous_mcp_names = _atlas_mcp_registered.get(scope, set())
            stale_mcp_names = previous_mcp_names - mcp_names
            for stale_name in stale_mcp_names:
                entry = registry.get_entry(stale_name, scope=scope)
                if entry is not None and entry.toolset == "atlas":
                    registry.deregister(stale_name, scope=scope)
                if not any(stale_name in other for key, other in _atlas_mcp_registered.items() if key != scope):
                    _registered.discard(stale_name)
            _atlas_mcp_registered[scope] = set(mcp_names)
        _bind_inline_atlas_tools()
        indexed: dict[str, dict[str, Any]] = {}
        for item in schemas:
            function = item.get("function", {})
            name = str(function.get("name", ""))
            if not name or name == "read_office":
                continue
            if name in indexed:
                prior = indexed[name].get("function", {})
                logger.warning(
                    "tool_registry.schema_name_collision",
                    tool=name,
                    kept_description=str(prior.get("description", ""))[:120],
                    skipped_description=str(function.get("description", ""))[:120],
                    scope=scope,
                )
                continue
            indexed[name] = item
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
                _engine_fallback_handlers.setdefault(name, previous.handler)
                _engine_entries.setdefault(name, previous)
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
            if name == "terminal":
                try:
                    from atlas.tools.local_execution import _shell_identity

                    shell_name, shell_path = _shell_identity()
                    schema["description"] = (
                        f"Shell: {shell_name} ({shell_path}). This is the actual default shell for this run.\n"
                        + schema["description"]
                    )
                except (OSError, RuntimeError, ValueError):
                    schema["description"] = "Shell: unknown (unavailable).\n" + schema["description"]
                schema["parameters"].setdefault("properties", {})["shell"] = {
                    "type": "string", "enum": (["auto", "bash", "powershell", "cmd", "zsh"]
                                                    if os.name != "nt"
                                                    else ["auto", "bash", "powershell", "cmd"]),
                    "description": (
                        "Shell to use. Defaults to Git Bash when available, "
                        "otherwise PowerShell."
                    ),
                }

            def handler(args: dict[str, Any], *, _name: str = name, **_kwargs: Any) -> str:
                session_id = str(_kwargs.get("session_id") or "")
                active = _active_contexts.get(session_id) if session_id else None
                bound_agent = active[0] if active else getattr(_context, "agent", None)
                bound_runtime = active[1] if active else getattr(_context, "runtime", None)
                bound_loop = active[2] if active else getattr(_context, "loop", None)
                if bound_agent is None or bound_runtime is None or bound_loop is None:
                    fallback = _engine_fallback_handlers.get(_name)
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
                if _name == "new_context_window":
                    callback = getattr(bound_runtime, "new_context_window_callback", None)
                    if callback is None:
                        return "无法生成上下文交接摘要。"
                    summary = asyncio.run_coroutine_threadsafe(callback(), bound_loop).result()
                    atlas_agent = getattr(bound_runtime, "atlas_agent", None)
                    summary_text = summary if isinstance(summary, str) else summary.get("summary") if isinstance(summary, dict) else None
                    if atlas_agent is None or not isinstance(summary_text, str) or not summary_text.strip():
                        return "无法切换上下文：当前会话没有可用的 Atlas 引擎。"
                    atlas_agent.set_context_handoff_summary(summary_text)
                    event_queue = getattr(bound_runtime, "event_queue", None)
                    if event_queue is not None:
                        asyncio.run_coroutine_threadsafe(event_queue.put({
                            "type": "context.window.switched",
                            "data": {"summary": summary_text},
                        }), bound_loop).result()
                    return "已整理交接摘要，正在切换到新上下文。"
                if _name == "mark_chapter":
                    title = str(args.get("title") or "").strip()[:80]
                    if not title:
                        return "章节标题不能为空。"
                    event_queue = getattr(bound_runtime, "event_queue", None)
                    if event_queue is None:
                        return "当前运行无法通知界面添加章节。"
                    asyncio.run_coroutine_threadsafe(event_queue.put({
                        "type": "chapter.marked", "data": {"title": title},
                    }), bound_loop).result()
                    return f"已在当前对话添加章节：{title}"
                if _name == repo_map_name:
                    workspace = str(getattr(bound_runtime, "workspace", "") or "")
                    call_id = f"atlas:{uuid.uuid4().hex}"
                    event_queue = getattr(bound_runtime, "event_queue", None)
                    if event_queue is not None:
                        asyncio.run_coroutine_threadsafe(event_queue.put({
                            "type": "tool_call", "id": call_id, "name": _name,
                            "arguments": args,
                        }), bound_loop).result()
                    if not workspace:
                        result, is_error = "当前运行没有可用的工作区。", True
                    elif workspace.startswith("ssh://"):
                        result, is_error = "仓库地图目前需要本地工作区路径。", True
                    else:
                        from atlas.repomap import build_repo_map

                        try:
                            result = build_repo_map(
                                root=workspace,
                                focus_files=args.get("focus_files", []),
                                mentioned=args.get("mentioned", []),
                                max_tokens=args.get("max_tokens", 2048),
                            )
                            is_error = False
                        except Exception as exc:
                            result, is_error = f"{type(exc).__name__}: {exc}", True
                    result = str(result)
                    if event_queue is not None:
                        asyncio.run_coroutine_threadsafe(event_queue.put({
                            "type": "tool_result", "id": call_id, "name": _name,
                            "content": [{"type": "text", "text": result}],
                            "data": None, "is_error": is_error,
                        }), bound_loop).result()
                    return _append_repetition_reminder(bound_runtime, _name, args, result)
                if _name in NATIVE_FILE_TOOLS and not str(bound_runtime.workspace or "").startswith("ssh://"):
                    # Keep Hermes' complete file implementation: paging, ripgrep,
                    # stale-write guards, fuzzy/V4A patching and document readers.
                    lsp_pre = _lsp_pre_write(args, bound_runtime) if _name in _LSP_WRITE_TOOLS else _LSP_SKIP
                    native = _engine_fallback_handlers[_name]
                    result = native(args, **_kwargs)
                    if _name == "read_file":
                        result = _read_file_result(
                            getattr(bound_runtime, "atlas_agent", None) or bound_agent,
                            args, str(result),
                        )
                    if lsp_pre is not _LSP_SKIP:
                        result = _lsp_attach_report(bound_runtime, bound_loop, args, lsp_pre, result)
                    return _append_repetition_reminder(bound_runtime, _name, args, str(result)) if isinstance(result, str) else result
                tool_name, tool_args = _translate(_name, args, bound_runtime)
                if tool_name in {"local_shell", "local_exec", "local_process"}:
                    starts_process = (
                        tool_name != "local_process"
                        or str(tool_args.get("action", "")) == "start"
                    )
                    if starts_process and not tool_args.get("cwd"):
                        workspace = str(getattr(bound_runtime, "workspace", "") or "")
                        if workspace:
                            if workspace.startswith("ssh://"):
                                from atlas.ssh import SSHWorkspaceManager

                                _host, tool_args["cwd"] = SSHWorkspaceManager.parse_workspace(workspace)
                            else:
                                tool_args["cwd"] = workspace
                if tool_name in {"local_shell", "local_process"}:
                    tool_args["_atlas_conversation_id"] = str(bound_runtime.conversation_id or "")
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
                        "pending_events": [], "runtime": bound_runtime,
                    }),
                    bound_loop,
                )
                result = future.result()
                messages = result.get("messages", [])
                if _name == "todo_list" and getattr(bound_runtime, "atlas_agent", None) is not None:
                    bound_runtime.atlas_agent._todo_store.write([
                        {**item, "content": item["text"]}
                        for item in bound_runtime.todo_store.snapshot()["todos"]
                    ])
                result = str(messages[-1].content) if messages else "工具没有返回内容。"
                return _append_repetition_reminder(bound_runtime, _name, args, result)

            native_entry = _engine_entries.get(name)
            registry.register(
                name=name, toolset=atlas_toolset, schema=schema, handler=handler,
                is_async=False, description=schema["description"], override=True,
                output_schema=_alias_output_schema(name),
                check_fn=getattr(native_entry, "check_fn", None),
                max_result_size_chars=getattr(native_entry, "max_result_size_chars", None),
                dynamic_schema_overrides=getattr(native_entry, "dynamic_schema_overrides", None),
            )
            registered.add(name)
            names.append(name)

        # `toolsets` is the shared resolver table; the schema source and handlers remain
        # registered through Hermes' canonical registry.
        if not plan_mode:
            registered.add("new_context_window")
            # X2 computer/browser: one surface each, same approval/checkpoint
            # gates as the rest of the Atlas toolset (atlas_policy classifies
            # these names as writes via atlas.tools.x2.permissions).
            from atlas.tools.x2.registration import bind_x2_tools

            for x2_name in bind_x2_tools(
                lambda **kwargs: registry.register(**kwargs),
                registered.add,
                lambda session_id: _active_contexts.get(session_id),
            ):
                pass
        _TOOLSETS[atlas_toolset] = {
            "description": "Atlas 工作区、项目和运行工具",
            "tools": sorted(registered),
            "includes": [],
        }


def unregister_atlas_mcp_tools(names: set[str], scopes: set[str | None]) -> None:
    """Remove only Atlas registry copies of the specified MCP tools and scopes."""
    if not names or not scopes:
        return
    from atlas.engine.tools.registry import registry

    with _lock:
        scopes = set(scopes)
        scopes.update(
            scope for scope, tracked in _atlas_mcp_registered.items()
            if tracked.intersection(names)
        )
        scopes.add(registry.current_scope_key())
        for scope in scopes:
            for name in names:
                entry = registry.get_entry(name, scope=scope)
                if entry is not None and entry.toolset == "atlas":
                    registry.deregister(name, scope=scope)
            tracked = _atlas_mcp_registered.get(scope)
            if tracked is not None:
                tracked.difference_update(names)
                if not tracked:
                    _atlas_mcp_registered.pop(scope, None)
        still_tracked = (
            set().union(*_atlas_mcp_registered.values()) if _atlas_mcp_registered else set()
        )
        _registered.difference_update(names - still_tracked)


def _bind_inline_atlas_tools() -> None:
    """Compatibility no-op: Atlas native tools are dispatched by its registry."""
    return None

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


def _translate(
    name: str, arguments: dict[str, Any], runtime: Any = None,
) -> tuple[str, dict[str, Any]]:
    """Translate a Hermes tool call to its Atlas execution shape.

    ``runtime`` is the session-bound Atlas run context (resolved by session_id in
    the caller, H3); the thread-local is only a fallback for legacy callers.
    """
    if runtime is None:
        runtime = getattr(_context, "runtime", None)
    tool_name, action = _ALIASES.get(name, (name, None))
    args = dict(arguments)
    if action is not None and tool_name == "local_file":
        args["action"] = action
    elif tool_name == "local_shell":
        args["command"] = args.pop("command", args.pop("cmd", ""))
        args["shell"] = str(args.get("shell") or "auto")
        args["cwd"] = args.pop("workdir", args.get("cwd", ""))
        background = bool(args.pop("background", False))
        args["detached"] = background
        if background:
            args["keep_stdin"] = True
        if args.pop("pty", False):
            args["pty"] = True
        heartbeat = args.get("heartbeat", 0)
        if isinstance(heartbeat, bool):
            raise ValueError("heartbeat 必须是非负秒数。")
        try:
            heartbeat = float(heartbeat or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("heartbeat 必须是非负秒数。") from exc
        if heartbeat < 0 or not math.isfinite(heartbeat):
            raise ValueError("heartbeat 必须是非负秒数。")
        if heartbeat:
            args["heartbeat"] = heartbeat
        notify = args.get("notify")
        if isinstance(notify, bool):
            args["notify_on_complete"] = notify
        if "watch_patterns" in args and not isinstance(args["watch_patterns"], list):
            raise ValueError("watch_patterns 必须是字符串数组。")
        args["_atlas_conversation_id"] = str(getattr(runtime, "conversation_id", "") or "")
        args.pop("persist_on_release", None)
    if name == "search_files":
        args["query"] = args.pop("pattern", args.get("query", ""))
        args.setdefault("path", ".")
    if name == "delegate_task" and isinstance(args.get("tasks"), list):
        tool_name = "delegate_parallel"
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
            if process_action == "log":
                args["_line_offsets"] = True
            elif process_action == "poll":
                args["_native_poll"] = True
        else:
            args["action"] = process_action
        if tool_name == "local_process":
            args["_atlas_conversation_id"] = str(
                getattr(runtime, "conversation_id", "") or ""
            )
    return tool_name, args
