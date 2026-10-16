# Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: apps/zcode-cli/packages/core/src/agent/turn-machine.ts (Apache-2.0)
# Ported from openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/core/src/session/turn.rs (Apache-2.0)
# Behavior from Claude Code v2.1.296 docs: https://code.claude.com/docs/en/how-claude-code-works
# SPDX-License-Identifier: Apache-2.0
"""Atlas-owned asynchronous model, tool and recovery loop."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from atlas.kernel.context import CompactionResult, ContextManager, estimate_tokens
from atlas.kernel.model_call import ModelCallError, ModelCallResult, complete_stream
from atlas.kernel.plan import PlanMode
from atlas.kernel.prompt import build_prompt
from atlas.kernel.repair import repair_unpaired_tool_calls, started_call_ids
from atlas.kernel.state import KernelEvent, RunPhase, RunState
from atlas.kernel.stuck import StuckDetector
from atlas.kernel.tools import READ_ONLY_TOOLS, ToolExecutionResult, ToolScheduler

log = logging.getLogger(__name__)

# Tool-call rounds per run. The user asked for no practical cap: the default is
# high and the hard ceiling only guards against a runaway integer in config.
DEFAULT_MAX_TURNS = 1000
MAX_TURNS_CAP = 100_000


def _self_facts(agent: Any, model_id: str, workspace: str | None) -> tuple[str, str]:
    """Tell the model what it runs on: the real model behind the configured id, and where Atlas lives.

    Configured ids are often aliases (``wb-domestic-a``), so the provider and wire
    model are resolved from the model list instead of echoing the id.
    """
    import platform

    from atlas.config import CONFIG_PATH, DATA_ROOT, PROJECT_ROOT, USER_SETTINGS_PATH

    entry: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        entry = next((item for item in agent._model_mgr.list_models()
                      if item.get("id") == model_id), {})
    wire = str(entry.get("litellm_model") or entry.get("model") or "")
    lines = ["# Atlas self-knowledge", f"- Model id selected in Atlas: {model_id}"]
    if entry.get("name"):
        lines.append(f"- Display name: {entry['name']}")
    if entry.get("provider"):
        lines.append(f"- Provider: {entry['provider']}")
    if wire:
        lines.append(f"- Underlying model actually called: {wire}")
    if entry.get("base_url"):
        lines.append(f"- Endpoint: {entry['base_url']}")
    lines.append("- When asked which model you are, answer with these facts; they are authoritative.")
    if workspace:
        lines.append(f"- Working directory: {workspace}")
    else:
        lines.append(f"- No workspace is selected: relative paths resolve against {Path.home()}; "
                     "use absolute paths for anything elsewhere. Reading and editing files "
                     "anywhere on this machine is allowed.")
    shell = "PowerShell / cmd" if os.name == "nt" else os.environ.get("SHELL", "sh")
    lines.append(f"- Host: {platform.system()} {platform.release()} ({platform.version()}), "
                 f"Python {platform.python_version()}, shell {shell}")
    lines.append(f"- Atlas source checkout (your own code, editable): {PROJECT_ROOT}")
    lines.append(f"- Atlas config: {CONFIG_PATH}; user settings (models, providers): "
                 f"{USER_SETTINGS_PATH}; data dir: {DATA_ROOT / 'data'}")
    from atlas.memory.library import get_library

    library = get_library()
    if library is not None:
        lines.append(f"- Long-term memory: the memory library at {library.store.root} "
                     "(Markdown + git; search it with memory_search). It is the only memory system.")
    return "\n".join(lines), wire


@dataclass(slots=True)
class KernelRequest:
    agent: Any
    runtime: Any
    message: str
    conversation_id: str
    workspace: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    system_message: str = ""
    volatile_context: list[str] = field(default_factory=list)
    user_content: Any = None
    model_id: str | None = None
    reasoning_effort: str | None = None
    max_output_tokens: int | None = None
    cancel_event: asyncio.Event | None = None
    pause_event: asyncio.Event | None = None
    steer_queue: asyncio.Queue[dict[str, Any]] | None = None
    lifecycle_hook_callback: Callable[[str, dict[str, Any]], Any] | None = None
    plan_state: dict[str, Any] | None = None
    plan_update_callback: Callable[[dict[str, Any]], Any] | None = None
    moa_references: list[dict[str, str]] = field(default_factory=list)
    moa_latency_ms: int = 0
    initial_usage_rows: list[dict[str, Any]] = field(default_factory=list)
    usage_budget: Any = None
    runtime_config: dict[str, Any] = field(default_factory=dict)


def _message_text(message: dict[str, Any]) -> str:
    value = message.get("content", "")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(str(item.get("text") or "") for item in value if isinstance(item, dict))
    return str(value or "")


def _session_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for row in rows:
        role = str(row.get("role") or "")
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        message = copy.deepcopy(row)
        message["role"] = role
        message["content"] = row.get("content") or ""
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else row.get("display_metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        for key in ("tool_calls", "tool_call_id", "tool_name", "output_ref", "repair_state"):
            if key in metadata:
                message[key] = metadata[key]
            elif key in row:
                message[key] = row[key]
        if role == "assistant" and message.get("tool_calls"):
            message["tool_calls"] = message["tool_calls"]
        messages.append(message)
    return messages


def _compaction_payload(
    messages: list[dict[str, Any]], held: list[dict[str, Any]], *,
    synthetic_system_prompt: str, method: str,
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    """Strip the per-request prefix and identify durable rows carried verbatim."""
    compacted = copy.deepcopy(messages)
    for index, item in enumerate(compacted):
        if (item.get("role") == "system"
                and item.get("content") == synthetic_system_prompt):
            del compacted[index]
            break
    held_by_id = {item.get("_row_id"): item for item in held
                  if isinstance(item.get("_row_id"), int)}
    for item in compacted:
        prior = held_by_id.get(item.get("_row_id"))
        if prior is not None and item.get("role") == "user":
            # Runtime-only multimodal expansions are not transcript content.
            item["content"] = copy.deepcopy(prior.get("content", ""))
        if (item.get("role") == "user" and isinstance(item.get("content"), str)
                and item["content"].startswith("[Conversation continuation summary]")):
            item["_compressed_summary"] = True

    tail_count = 0
    carried: list[dict[str, Any]] = []
    if method == "summary":
        limit = min(len(compacted), len(held))
        for size in range(limit, 0, -1):
            candidate_tail, held_tail = compacted[-size:], held[-size:]
            if all(
                isinstance(item.get("_row_id"), int)
                and item.get("_row_id") == original.get("_row_id")
                and all(item.get(key) == original.get(key) for key in (
                    "role", "content", "tool_calls", "tool_call_id", "tool_name",
                ))
                for item, original in zip(candidate_tail, held_tail)
            ):
                tail_count = size
                break
        tail_ids = {item.get("_row_id") for item in compacted[-tail_count:]} if tail_count else set()
        carried = [
            item for item in compacted
            if isinstance(item.get("_row_id"), int)
            and item.get("_row_id") in held_by_id
            and item.get("_row_id") not in tail_ids
            and all(item.get(key) == held_by_id[item["_row_id"]].get(key) for key in (
                "role", "content", "tool_calls", "tool_call_id", "tool_name",
            ))
        ]
    return compacted, tail_count, carried


def _tool_call_for_history(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(call.get("id") or ""), "type": "function",
        "function": {"name": str(call.get("name") or ""),
                     "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False)},
    }


def _usage_row(result: ModelCallResult, call_id: str) -> dict[str, Any]:
    usage = dict(result.usage)
    in_tokens = usage.get("prompt_tokens", usage.get("input_tokens", usage.get("input", 0)))
    out_tokens = usage.get("completion_tokens", usage.get("output_tokens", usage.get("output", 0)))
    try:
        in_tokens, out_tokens = max(0, int(in_tokens or 0)), max(0, int(out_tokens or 0))
    except (TypeError, ValueError):
        in_tokens = out_tokens = 0
    row = {
        "request_id": call_id, "purpose": "conversation", "model": result.model,
        "provider": result.provider, "input_tokens": in_tokens,
        "output_tokens": out_tokens, "context_tokens": in_tokens,
        "usage_available": bool(result.usage), "duration_ms": result.duration_ms,
    }
    row.update({key: value for key, value in usage.items() if key not in row})
    return row


async def _wait_until_resumed(
    pause_event: asyncio.Event | None,
    cancel_event: asyncio.Event | None,
) -> None:
    """Wait at a kernel safe point, while keeping cancellation responsive."""
    if pause_event is None or pause_event.is_set():
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError
        return
    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError
    pause_waiter = asyncio.create_task(pause_event.wait())
    waiters: set[asyncio.Task[Any]] = {pause_waiter}
    if cancel_event is not None:
        waiters.add(asyncio.create_task(cancel_event.wait()))
    try:
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            if not waiter.done():
                waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError


class _SteerTarget:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.redirected = False

    def steer(self, text: str) -> bool:
        if text:
            self.messages.append(text)
            return True
        return False

    def redirect(self, text: str) -> bool:
        if text:
            self.messages.append(text)
            self.redirected = True
            return True
        return False


class AtlasKernel:
    """One loop per run; policy, tool bodies and durable history remain Atlas-owned."""

    def __init__(self, *, data_dir: str | Path, config: dict[str, Any] | None = None) -> None:
        self.data_dir = Path(data_dir)
        raw = dict(config or {})
        self.config = dict(raw.get("engine", raw))
        self.raw_config = raw

    async def run(self, request: KernelRequest) -> AsyncIterator[dict[str, Any]]:
        from atlas.kernel.exec import ExecManager
        from atlas.usage import env_run_usage_budget

        runtime = request.runtime
        agent = request.agent
        pause_event = request.pause_event or getattr(runtime, "pause_event", None)
        run_id = str(getattr(runtime, "run_id", None) or uuid.uuid4().hex)
        session_id = request.conversation_id
        selected_model = request.model_id or getattr(runtime, "model", None) or agent._model_mgr.current_model
        state = RunState(run_id=run_id, session_id=session_id)
        started_at = time.monotonic()
        usage_rows: list[dict[str, Any]] = copy.deepcopy(request.initial_usage_rows)
        state.usage_rows = usage_rows
        receipts: list[dict[str, Any]] = []
        failure = ""
        log_path: Path | None = None
        exec_manager: ExecManager | None = None
        scheduler: ToolScheduler | None = None
        messages: list[dict[str, Any]] = []
        partial_response_text: list[str] = []
        run_message_uids: list[str] = []
        consecutive_tool_failures = 0
        active_call_ids: set[str] = set()
        open_call_ids: set[str] = set()

        from atlas.config import get_config, load_user_settings
        from atlas.logs import LOG_DIR, append_run_event

        app_config = get_config()
        raw_config = dict(getattr(app_config, "raw", {}) or request.runtime_config)
        engine_config = dict(raw_config.get("engine", {}))
        configured_retries = engine_config.get("model_retries")
        model_retries = int(configured_retries) if configured_retries is not None else None
        retry_watchdog = os.environ.get("CLAUDE_CODE_RETRY_WATCHDOG") == "1"

        def retry_delay_env(name: str, default: float | None) -> float | None:
            try:
                return max(0.0, float(os.environ[name]) / 1000.0)
            except (KeyError, TypeError, ValueError):
                return default

        watchdog_max_wait = retry_delay_env("CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS", None)
        overloaded_retry_base_delay = retry_delay_env("CLAUDE_CODE_OVERLOADED_RETRY_BASE_DELAY_MS", 0.5)
        run_log_root = LOG_DIR

        def record(event: str, **fields: Any) -> None:
            nonlocal log_path
            try:
                log_path = append_run_event(run_id, event, **fields)
            except Exception:
                log.exception("kernel.run_log_write_failed", extra={"run_id": run_id, "event": event})

        def emit(event_type: str, **data: Any) -> dict[str, Any]:
            return KernelEvent(event_type, data).as_run_event()

        def transition(phase: RunPhase) -> None:
            if state.phase != phase:
                state.transition(phase)

        def persist(role: str, content: Any, metadata: dict[str, Any] | None = None) -> str:
            from atlas.engine.session_sync import append_session_message

            message_uid = append_session_message(
                self.data_dir / "engine", session_id, role, content, metadata,
            )
            if message_uid and message_uid not in run_message_uids:
                run_message_uids.append(message_uid)
            return message_uid

        async def persist_async(role: str, content: Any,
                                metadata: dict[str, Any] | None = None) -> str:
            return await asyncio.to_thread(persist, role, content, metadata)

        def schedule_lifecycle(event_kind: str, message_uids: list[str], *,
                               scope: str = "messages", tool_call_id: str | None = None) -> None:
            try:
                from atlas.memory.library import get_library

                library = get_library()
                if library is None:
                    return
                occurred_at = datetime.now(UTC)
                event = {
                    "conversation_id": str(session_id or ""),
                    "message_uids": message_uids,
                    "event_kind": event_kind,
                    "occurred_at": occurred_at.isoformat(),
                    "scope": scope,
                    "run_id": run_id,
                }
                if tool_call_id:
                    event["tool_call_id"] = tool_call_id
                library.schedule_lifecycle(event, model_mgr=getattr(agent, "_model_mgr", None))
                if event_kind == "turn_end":
                    library.schedule_lifecycle({**event, "event_kind": "session_idle",
                                                "occurred_at": (occurred_at + timedelta(minutes=30)).isoformat()},
                                               model_mgr=getattr(agent, "_model_mgr", None))
                record("memory_lifecycle_enqueued", conversation_id=session_id,
                       message_uids=message_uids, event_kind=event_kind,
                       run_id=run_id, tool_call_id=tool_call_id)
            except Exception as exc:
                log.warning("memory.lifecycle.schedule_failed", extra={
                    "run_id": run_id, "error_type": type(exc).__name__,
                })

        try:
            record("run_start", model=selected_model, session_id=session_id,
                   workspace=request.workspace or "", kernel="atlas")
            yield emit("run_status", status="preparing", text="Preparing Atlas kernel turn")
            for row in request.initial_usage_rows:
                record("model_request", purpose=row.get("purpose", "moa"),
                       model=row.get("model"), provider=row.get("provider"),
                       duration_ms=row.get("duration_ms"),
                       input_tokens=row.get("input_tokens", 0),
                       output_tokens=row.get("output_tokens", 0),
                       cached_tokens=row.get("cached_tokens", 0))
                yield emit("run_usage", usage=row)
            if request.moa_references:
                yield emit("moa_references", models=[item.get("model") for item in request.moa_references],
                           references=request.moa_references, latency_ms=request.moa_latency_ms)

            from atlas.engine.session_sync import read_session_model_messages
            try:
                canonical_rows = await asyncio.to_thread(
                    read_session_model_messages, self.data_dir / "engine", session_id,
                )
            except Exception:
                log.exception("kernel.session_read_failed", extra={"session_id": session_id})
                canonical_rows = []
            history = _session_history(canonical_rows) if canonical_rows else copy.deepcopy(request.history)
            if not any(m.get("role") == "user" and _message_text(m) == request.message for m in history[-3:]):
                await persist_async("user", request.message, {"kernel_run_id": run_id})
                history.append({"role": "user", "content": request.user_content or request.message})
            elif request.user_content is not None and history and history[-1].get("role") == "user":
                history[-1]["content"] = request.user_content
            current_user = next((row for row in reversed(canonical_rows[-3:])
                                 if row.get("role") == "user"
                                 and _message_text(row) == request.message), None)
            if current_user:
                user_uid = str(current_user.get("message_uid") or current_user.get("id") or "")
                if user_uid and user_uid not in run_message_uids:
                    run_message_uids.insert(0, user_uid)
            durable_history = copy.deepcopy(history)

            started = started_call_ids(canonical_rows, run_log_root)
            history, repairs = repair_unpaired_tool_calls(history, started_ids=started, run_id=run_id)
            for repair in repairs:
                record("repair", **repair)
                await persist_async("tool", next(
                    message["content"] for message in history
                    if message.get("role") == "tool" and message.get("tool_call_id") == repair["tool_call_id"]
                ), {"tool_call_id": repair["tool_call_id"], "tool_name": repair["name"],
                    "repair_state": repair["state"], "kernel_run_id": run_id})
                yield emit("run.recovery.notice", data={
                    "message": "已修复上次中断时未配对的工具调用。",
                    "tool_call_id": repair["tool_call_id"], "state": repair["state"],
                })

            try:
                canonical_rows = await asyncio.to_thread(
                    read_session_model_messages, self.data_dir / "engine", session_id,
                )
                if canonical_rows:
                    durable_history = _session_history(canonical_rows)
                    history = copy.deepcopy(durable_history)
                    if request.user_content is not None:
                        current_user = next((item for item in reversed(history)
                                             if item.get("role") == "user"
                                             and _message_text(item) == request.message), None)
                        if current_user is not None:
                            current_user["content"] = request.user_content
            except Exception:
                log.exception("kernel.session_refresh_failed", extra={"session_id": session_id})

            system_prompt = request.system_message or ""
            if getattr(runtime, "mode", "act") == "plan":
                from atlas.engine_core.agent.plan_prompt import build_plan_prompt

                system_prompt = "\n\n".join(filter(None, (
                    system_prompt, build_plan_prompt(request.message),
                )))
            volatile = "\n\n".join(item.strip() for item in request.volatile_context if item.strip())
            if volatile:
                system_prompt = "\n\n".join(filter(None, (
                    system_prompt, "Atlas session-start context:\n" + volatile,
                )))
            from atlas.engine.hermes_runtime import _model_family_guidance

            self_facts, wire_model = _self_facts(agent, selected_model, request.workspace)
            system_prompt = "\n\n".join(filter(None, (
                system_prompt,
                self_facts,
                "Model-family guidance: " + _model_family_guidance(wire_model or selected_model),
            )))

            def assemble_prompt(items: list[dict[str, Any]]):
                return build_prompt(identity=system_prompt, history=items, rules="")

            prompt = assemble_prompt(history)
            messages = prompt.messages
            if request.lifecycle_hook_callback is not None:
                session_start = await self._run_hook(request, "SessionStart", {
                    "source": "startup", "conversation_id": session_id,
                    "session_id": session_id, "run_id": run_id,
                    "cwd": request.workspace or "",
                })
                additional_context = session_start.get("additional_context")
                if isinstance(additional_context, str) and additional_context.strip():
                    system_prompt = "\n\n".join(filter(None, (
                        system_prompt,
                        "SessionStart hook context:\n" + additional_context.strip(),
                    )))
                    prompt = assemble_prompt(history)
                    messages = prompt.messages

            plan = PlanMode(runtime, engine_config, plan_state=request.plan_state,
                            plan_update_callback=request.plan_update_callback,
                            todo_store=getattr(runtime, "todo_store", None))
            edit_manager = None
            remote_workspace = bool(request.workspace and request.workspace.startswith("ssh://"))
            if not remote_workspace and getattr(agent, "_local_execution", None) is not None:
                from atlas.kernel.edit import EditManager

                # Without a workspace the kernel editor still serves the whole machine:
                # relative paths resolve against the home directory, absolute paths are
                # unrestricted (same scope local_file already has).
                edit_manager = EditManager(
                    request.workspace or Path.home(),
                    allowed_paths=(
                        [*getattr(runtime, "allowed_paths", []), request.workspace]
                        if request.workspace and getattr(runtime, "allowed_paths", None) else None
                    ),
                )
            run_dir = log_path.parent if log_path is not None else LOG_DIR / "runs" / "active" / run_id
            output_dir = run_dir / "tool-output"
            event_queue: asyncio.Queue[Any] = asyncio.Queue()

            async def dispatch_managed_process(name: str, arguments: dict[str, Any]) -> Any:
                from atlas.engine.tool_registry import _approval_fingerprint

                if (str(arguments.get("action") or "") == "start"
                        and getattr(runtime, "permission_mode", "") == "ask_writes"):
                    preapproved = getattr(runtime, "hermes_preapproved_writes", None)
                    if preapproved is not None:
                        preapproved.add(_approval_fingerprint(name, arguments))
                internal_events: asyncio.Queue[Any] = asyncio.Queue()
                # The outer shell/process invocation has already passed this run's
                # allow-list check. The inner local_process call implements that
                # exact approved action; retain deny rules and all tool-node checks.
                internal_runtime = copy.copy(runtime)
                internal_runtime.tool_allow = None
                result = await self._dispatch(
                    agent, internal_runtime, None, name, arguments, internal_events,
                    exec_manager=None, nested=True,
                )
                while not internal_events.empty():
                    event = internal_events.get_nowait()
                    if not isinstance(event, dict) or event.get("type") not in {
                        "tool_call", "tool_result", "approval_required",
                    }:
                        await event_queue.put(event)
                return result

            exec_manager = ExecManager(
                dispatch_managed_process,
                output_dir=output_dir, run_id=run_id,
                local_runtime=getattr(agent, "_local_execution", None),
                max_output_bytes=int(engine_config.get("exec_head_tail_bytes", 10_000)),
            )
            proxy_runtime = copy.copy(runtime)
            proxy_runtime.event_queue = event_queue
            proxy_runtime.exec_manager = exec_manager
            proxy_runtime.plan_state = request.plan_state
            proxy_runtime.plan_update_callback = request.plan_update_callback
            proxy_runtime.kernel_edit = edit_manager
            proxy_runtime.conversation_id = session_id
            proxy_runtime.tool_history_callback = lambda: list(messages)
            try:
                from atlas.config import get_config
                from atlas.task_artifacts import WorktreeService

                proxy_runtime.workspace_worktree_service = WorktreeService(
                    get_config().db_path.parent,
                )
            except Exception:
                proxy_runtime.workspace_worktree_service = None
            proxy_runtime._preapproved_tool_call_ids = set()
            tool_allow = getattr(runtime, "tool_allow", None)
            tool_deny = getattr(runtime, "tool_deny", [])
            tool_inputs: dict[str, dict[str, Any]] = {}
            pretool_blocked: set[str] = set()
            tool_hook_context: dict[str, list[str]] = {}
            bad_tool_args: dict[str, str] = {}

            async def dispatch_tool(call_id: str, name: str, args: dict[str, Any]) -> Any:
                if call_id in bad_tool_args:
                    # Unparseable arguments: answer this call only, the rest of the batch runs.
                    return {"content": bad_tool_args.pop(call_id), "is_error": True,
                            "outcome": "failed"}
                tool_args = copy.deepcopy(args)
                if (getattr(proxy_runtime, "dynamic_plan_mode", False)
                        and name not in {
                            "update_plan", "EnterPlanMode", "ExitPlanMode",
                            "get_context_remaining", "read_tool_history", "tool_search", "memory_search",
                            "list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource",
                            "request_user_input", "request_user_input_async",
                            "AskUserQuestion",
                        } and name not in READ_ONLY_TOOLS):
                    return {"content": "Plan mode is read-only. Submit the plan and wait for approval before using this tool.",
                            "is_error": True, "outcome": "denied"}
                pre_tool = await self._run_hook(request, "PreToolUse", {
                    "tool_name": name, "tool_use_id": call_id,
                    "tool_input": copy.deepcopy(tool_args), "conversation_id": session_id,
                    "run_id": run_id, "cwd": request.workspace or "",
                })
                if isinstance(pre_tool.get("updated_input"), dict):
                    tool_args = copy.deepcopy(pre_tool["updated_input"])
                tool_inputs[call_id] = tool_args
                additional_context = pre_tool.get("additional_context")
                if isinstance(additional_context, str) and additional_context.strip():
                    tool_hook_context.setdefault(call_id, []).append(additional_context.strip())
                permission_decision = str(
                    pre_tool.get("permission_decision")
                    or pre_tool.get("permissionDecision")
                    or ("ask" if pre_tool.get("ask_user") else "")
                ).lower()
                if pre_tool.get("blocked") or permission_decision in {"deny", "defer"}:
                    reason = str(pre_tool.get("reason") or (
                        f"Tool use blocked by PreToolUse hook ({permission_decision or 'blocked'})."
                    ))
                    pretool_blocked.add(call_id)
                    record("tool_blocked", tool_call_id=call_id, name=name,
                           decision=permission_decision or "blocked", reason=reason)
                    return {"content": reason, "is_error": True, "outcome": "denied"}
                if permission_decision == "ask":
                    permission_hook = await self._run_hook(request, "PermissionRequest", {
                        "tool_name": name, "tool_use_id": call_id,
                        "tool_input": copy.deepcopy(tool_args), "conversation_id": session_id,
                        "run_id": run_id, "cwd": request.workspace or "",
                    })
                    permission_context = permission_hook.get("additional_context")
                    if isinstance(permission_context, str) and permission_context.strip():
                        tool_hook_context.setdefault(call_id, []).append(permission_context.strip())
                    if isinstance(permission_hook.get("updated_input"), dict):
                        tool_args = copy.deepcopy(permission_hook["updated_input"])
                        tool_inputs[call_id] = tool_args
                    if permission_hook.get("blocked"):
                        reason = str(permission_hook.get("reason") or
                                     "PermissionRequest hook denied the tool call.")
                        pretool_blocked.add(call_id)
                        record("tool_blocked", tool_call_id=call_id, name=name,
                               decision="permission_request_denied", reason=reason)
                        return {"content": reason, "is_error": True, "outcome": "denied"}
                    if permission_hook.get("allowed"):
                        proxy_runtime._preapproved_tool_call_ids.add(call_id)
                    else:
                        approval_callback = getattr(proxy_runtime, "approval_callback", None)
                        if not callable(approval_callback):
                            reason = str(pre_tool.get("reason") or
                                         "PreToolUse requested approval, but this run has no approval callback.")
                            pretool_blocked.add(call_id)
                            record("tool_blocked", tool_call_id=call_id, name=name,
                                   decision="ask_unavailable", reason=reason)
                            return {"content": reason, "is_error": True, "outcome": "denied"}
                        approval_id = f"approval:{call_id}"
                        pretool_blocked.add(call_id)
                        await event_queue.put({
                            "type": "approval_required", "event_id": approval_id,
                            "tool_call_id": call_id, "name": name,
                            "arguments": copy.deepcopy(tool_args),
                        })
                        approval_args = {
                            **copy.deepcopy(tool_args),
                            "_approval_reason": str(permission_hook.get("reason")
                                                     or pre_tool.get("reason")
                                                     or "A permission hook requested approval."),
                            "_approval_scope": str(permission_hook.get("scope")
                                                   or pre_tool.get("scope")
                                                   or "this tool call"),
                            "_approval_resource": str(permission_hook.get("resource")
                                                      or pre_tool.get("resource") or ""),
                        }
                        choice = approval_callback(approval_id, name, approval_args)
                        if hasattr(choice, "__await__"):
                            choice = await choice
                        if choice != "allow":
                            reason = str(pre_tool.get("reason") or
                                         "Tool use was not approved after the PreToolUse hook requested permission.")
                            record("tool_blocked", tool_call_id=call_id, name=name,
                                   decision="ask_denied", reason=reason)
                            return {"content": reason, "is_error": True, "outcome": "denied"}
                        proxy_runtime._preapproved_tool_call_ids.add(call_id)
                        pretool_blocked.discard(call_id)
                active_call_ids.add(call_id)
                record("tool_start", tool_call_id=call_id, name=name, arguments=tool_args)
                return await self._dispatch(
                    agent, proxy_runtime, call_id, name, tool_args, event_queue,
                    exec_manager=exec_manager,
                )

            scheduler = ToolScheduler(
                dispatch_tool,
                max_concurrency=int(engine_config.get("tool_concurrency", 10)),
                allow=tool_allow, deny=tool_deny,
            )
            context_manager = ContextManager(raw_config, output_dir=run_dir / "compact-output")
            def context_remaining_callback() -> dict[str, Any]:
                budget = context_manager.budget(model_window)
                used = estimate_tokens(messages)
                return {
                    "remaining_tokens": max(0, budget - used),
                    "budget_tokens": budget, "estimated_used_tokens": used,
                    "estimate": True,
                }

            proxy_runtime.context_remaining_callback = context_remaining_callback

            async def new_context_window_callback() -> dict[str, Any]:
                result = await prepare_compaction(force=True)
                if result.error or result.method == "none":
                    raise RuntimeError(result.error or "No safe conversation history could be compacted.")
                return {"method": result.method, "before_tokens": result.before_tokens,
                        "after_tokens": result.after_tokens, "budget_tokens": result.budget_tokens}

            proxy_runtime.new_context_window_callback = new_context_window_callback
            from atlas.models.profiles import profile_for

            model_profile = profile_for(wire_model, selected_model)
            stuck = StuckDetector(**model_profile.stuck)
            output_token_limit = request.max_output_tokens or model_profile.max_output_tokens
            usage_budget = request.usage_budget or env_run_usage_budget()

            async def record_workflow_usage(row: dict[str, Any]) -> None:
                usage = dict(row)
                usage_rows.append(usage)
                record(
                    "model_request",
                    purpose=usage.get("purpose", "workflow_planner"),
                    model=usage.get("model"), provider=usage.get("provider"),
                    duration_ms=usage.get("duration_ms"),
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                )
                await event_queue.put({"type": "run_usage", "usage": usage})

            async def record_model_attempt(event: dict[str, Any], *, purpose: str) -> None:
                if event.get("ok"):
                    attempt_usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
                    input_tokens = attempt_usage.get("prompt_tokens", attempt_usage.get(
                        "input_tokens", attempt_usage.get("input", 0),
                    ))
                    output_tokens = attempt_usage.get("completion_tokens", attempt_usage.get(
                        "output_tokens", attempt_usage.get("output", 0),
                    ))
                    details = attempt_usage.get("prompt_tokens_details") or attempt_usage.get(
                        "input_tokens_details", {},
                    )
                    cached_tokens = (details.get("cached_tokens", details.get("cache_read", 0))
                                     if isinstance(details, dict) else 0)
                    if cached_tokens == 0:
                        cached_tokens = attempt_usage.get("cache_read_input_tokens", 0)
                    try:
                        input_count = max(0, int(input_tokens or 0))
                        output_count = max(0, int(output_tokens or 0))
                        cached_count = max(0, int(cached_tokens or 0))
                    except (TypeError, ValueError):
                        input_count = output_count = cached_count = 0
                    usage = {
                        "request_id": f"{run_id}:{uuid.uuid4().hex}",
                        "purpose": purpose, "model": event.get("model"),
                        "provider": event.get("provider"), "input_tokens": input_count,
                        "output_tokens": output_count, "context_tokens": input_count,
                        "cached_tokens": cached_count,
                        "usage_available": bool(attempt_usage),
                        "duration_ms": event.get("duration_ms"),
                        "attempt": event.get("attempt"),
                    }
                    usage.update({key: value for key, value in attempt_usage.items()
                                  if key not in usage})
                    usage_rows.append(usage)
                    record("model_request", purpose=purpose, model=event.get("model"),
                           provider=event.get("provider"), duration_ms=event.get("duration_ms"),
                           output_tokens=output_tokens, input_tokens=input_tokens,
                           cached_tokens=cached_tokens, attempt=event.get("attempt"))
                else:
                    if event.get("retry"):
                        failed_attempt = int(event.get("attempt") or 0)
                        for key in [key for key in state.streamed_tool_calls
                                    if key[0] == failed_attempt]:
                            state.streamed_tool_calls.pop(key, None)
                    record("model_error", purpose=purpose, model=event.get("model"),
                           provider=event.get("provider"), category=event.get("category"),
                           status=event.get("status"), retry=event.get("retry"),
                           attempt=event.get("attempt"),
                           retry_delay_s=event.get("retry_delay_s"),
                           retry_after_s=event.get("retry_after_s"),
                           retry_kind=event.get("retry_kind"),
                           retry_number=event.get("retry_number"))

            async def on_summary_attempt(event: dict[str, Any]) -> None:
                await record_model_attempt(event, purpose="compaction")

            proxy_runtime.kernel_usage_budget = usage_budget
            proxy_runtime.workflow_usage_callback = record_workflow_usage
            engine_max_turns = max(1, min(int(engine_config.get("max_turns", DEFAULT_MAX_TURNS)), MAX_TURNS_CAP))
            run_limits = load_user_settings().get("run_limits")
            user_max_turns = run_limits.get("max_turns") if isinstance(run_limits, dict) else None
            if (
                isinstance(user_max_turns, int)
                and not isinstance(user_max_turns, bool)
                and 1 <= user_max_turns <= MAX_TURNS_CAP
            ):
                # The user's own setting wins over the engine default in both directions.
                max_turns = user_max_turns
            else:
                max_turns = engine_max_turns
            final_response = ""
            steer_target = _SteerTarget()
            steer_messages: list[str] = []
            pending_nudges: list[dict[str, str]] = []
            pending_stop_responses: list[dict[str, str]] = []
            stop_hook_active = False
            compaction_trigger = "automatic"

            async def preserve_partial_output(finish_reason: str) -> None:
                partial = "".join(partial_response_text)
                for message in pending_stop_responses:
                    prior_response = _message_text(message)
                    if prior_response and prior_response not in partial:
                        partial = f"{partial}\n\n{prior_response}" if partial else prior_response
                refusal = state.streamed_refusal
                if refusal and refusal not in partial:
                    partial += refusal
                if partial:
                    await persist_async("assistant", partial, {
                        "kernel_run_id": run_id, "finish_reason": finish_reason,
                        "partial_output": True, "refusal_present": bool(refusal),
                    })
                if partial or state.streamed_reasoning or state.streamed_tool_calls:
                    record("repair", state="partial_response_preserved",
                           finish_reason=finish_reason, output_length=len(partial),
                           reasoning_length=len(state.streamed_reasoning),
                           tool_fragments=len(state.streamed_tool_calls))

            def queue_nudge(message: str) -> None:
                nudge = {"role": "system", "content": message}
                pending_nudges.append(nudge)
                messages.append(copy.deepcopy(nudge))

            async def accept_steer(payload: dict[str, Any]) -> dict[str, Any] | None:
                from atlas.engine.steer_dispatch import apply_steer_payload
                steer_target.messages.clear()
                steer_target.redirected = False
                outcome = apply_steer_payload(steer_target, payload)
                if not outcome.get("accepted"):
                    return None
                message = str(outcome["text"])
                steer = {"content": message, **outcome,
                         "event_id": payload.get("event_id", "")}
                steer_messages.append(message)
                messages.append({"role": "user", "content": message})
                await persist_async("user", message, {
                    "kernel_run_id": run_id, "steered": True,
                    "steer_event_id": steer["event_id"],
                })
                stuck.observe_message(message, role="user")
                steer["event"] = emit(
                    "run_steered", content=message, event_id=steer["event_id"],
                    immediate=steer["immediate"], send_now=steer["send_now"],
                    yield_requested=steer["yield_requested"],
                )
                return steer

            async def apply_pending_steers() -> list[dict[str, Any]]:
                if not request.steer_queue:
                    return []
                accepted: list[dict[str, Any]] = []
                while not request.steer_queue.empty():
                    steer = await accept_steer(request.steer_queue.get_nowait())
                    if steer is not None:
                        accepted.append(steer)
                return accepted

            for turn_index in range(max_turns):
                await _wait_until_resumed(pause_event, request.cancel_event)
                if request.cancel_event is not None and request.cancel_event.is_set():
                    raise asyncio.CancelledError
                for steer in await apply_pending_steers():
                    yield steer["event"]

                try:
                    canonical_rows = await asyncio.to_thread(
                        read_session_model_messages, self.data_dir / "engine", session_id,
                    )
                    if canonical_rows:
                        durable_history = _session_history(canonical_rows)
                        history = copy.deepcopy(durable_history)
                        if request.user_content is not None:
                            current_user = next((item for item in reversed(history)
                                                 if item.get("role") == "user"
                                                 and _message_text(item) == request.message), None)
                            if current_user is not None:
                                current_user["content"] = request.user_content
                        prompt = assemble_prompt(history)
                        messages = prompt.messages
                        messages.extend(copy.deepcopy(pending_stop_responses))
                        messages.extend(copy.deepcopy(pending_nudges))
                except Exception:
                    log.exception("kernel.session_refresh_failed", extra={"session_id": session_id})

                from atlas.models.reasoning_stages import effort_for_phase, load_stage_config

                stage_config = load_stage_config()
                model_phase = "planning" if plan.active or turn_index == 0 else "execution"
                selected_effort = effort_for_phase(stage_config, model_phase) or request.reasoning_effort
                turn_model, turn_effort = plan.model_settings(selected_model, selected_effort)
                model_config = next((item for item in agent._model_mgr.list_models()
                                     if item.get("id") == turn_model), {})
                model_window = int(model_config.get("context_window") or 200_000)

                async def summarize(old: list[dict[str, Any]], summary_prompt: str) -> str:
                    from atlas.models.reasoning_stages import effort_for_phase, load_stage_config

                    stage_config = load_stage_config()
                    summary_effort = effort_for_phase(stage_config, "planning")
                    result = await complete_stream(
                        agent, turn_model,
                        [*old, {"role": "user", "content": summary_prompt}], [],
                        reasoning_effort=summary_effort or turn_effort,
                        max_output_tokens=min(int(engine_config.get("summary_max_tokens", 4096)), 8192),
                        cancel_event=request.cancel_event,
                        max_retries=model_retries,
                        fallback_models=list(getattr(runtime, "fallback_models", []) or []),
                        retry_watchdog=retry_watchdog,
                        retry_watchdog_max_wait_s=watchdog_max_wait,
                        overloaded_retry_base_delay_s=overloaded_retry_base_delay,
                        on_attempt=on_summary_attempt,
                        usage_budget=usage_budget,
                    )
                    return result.text

                compaction_lease: dict[str, Any] = {"holder": None, "watermark": None}
                held_messages = copy.deepcopy(durable_history)

                async def before_compact(compaction: Any) -> None:
                    hook = await self._run_hook(request, "PreCompact", {
                        "trigger": compaction_trigger, "conversation_id": session_id,
                        "session_id": session_id, "run_id": run_id,
                        "cwd": request.workspace or "",
                        "before_tokens": compaction.before_tokens,
                        "after_tokens": compaction.after_tokens,
                    })
                    if hook.get("blocked"):
                        reason = str(hook.get("reason") or "Compaction blocked by PreCompact hook")
                        record("hook_blocked", hook="PreCompact", reason=reason)
                        raise ModelCallError(reason, category="hook_blocked")
                    if compaction_lease["holder"] is None:
                        if not held_messages:
                            raise RuntimeError("Cannot compact without a canonical SessionDB history snapshot")
                        from atlas.engine.session_sync import begin_session_compaction

                        holder = f"atlas:{run_id}:{uuid.uuid4().hex}"
                        watermark = await asyncio.to_thread(
                            begin_session_compaction, self.data_dir / "engine", session_id, holder,
                        )
                        compaction_lease.update({"holder": holder, "watermark": watermark})
                        held_uids = [str(item.get("id") or item.get("message_uid") or "")
                                     for item in held_messages]
                        held_uids = list(dict.fromkeys(uid for uid in held_uids if uid))
                        schedule_lifecycle("pre_compress", held_uids,
                                           scope="messages" if held_uids else "session")

                async def prepare_compaction(*, force: bool = False) -> Any:
                    nonlocal durable_history, held_messages, history, messages, prompt
                    nonlocal compaction_trigger
                    compaction_trigger = (
                        "provider_context_window_exceeded" if force else "automatic"
                    )
                    try:
                        result = await context_manager.prepare(
                            messages, model_window=model_window, summarize=summarize,
                            preserved={"goal": request.message,
                                       "plan": plan.plan.to_dict() if plan.plan else None,
                                       "receipts": receipts},
                            focus=request.message,
                            # build_prompt already placed the stable prefix in messages.
                            prefix_tokens=0,
                            before_compact=before_compact,
                            force=force,
                        )
                    except BaseException as exc:
                        if compaction_lease["holder"]:
                            from atlas.engine.session_sync import abort_session_compaction

                            with contextlib.suppress(Exception):
                                await asyncio.to_thread(
                                    abort_session_compaction, self.data_dir / "engine", session_id,
                                    compaction_lease["holder"],
                                )
                            compaction_lease["holder"] = None
                        if (isinstance(exc, ModelCallError)
                                and exc.category == "hook_blocked"):
                            size = estimate_tokens(messages)
                            return CompactionResult(
                                copy.deepcopy(messages), "none", size, size,
                                context_manager.budget(model_window),
                            )
                        raise
                    if result.method != "none":
                        holder = compaction_lease["holder"]
                        if not holder:
                            raise ModelCallError("compaction has no SessionDB lease",
                                                 category="context_budget")
                        compacted_messages, tail_count, carried = _compaction_payload(
                            result.messages, held_messages,
                            synthetic_system_prompt=prompt.system_prompt,
                            method=result.method,
                        )
                        try:
                            from atlas.engine.session_sync import compact_session_messages

                            await asyncio.to_thread(
                                compact_session_messages, self.data_dir / "engine", session_id,
                                holder, int(compaction_lease["watermark"]), held_messages,
                                compacted_messages, tail_count=tail_count, carried_messages=carried,
                            )
                        except Exception as exc:
                            compaction_lease["holder"] = None
                            raise ModelCallError(
                                f"SessionDB compaction publication failed: {exc}",
                                category="context_budget",
                            ) from exc
                        compaction_lease["holder"] = None
                        transition(RunPhase.COMPACTING)
                        record("compaction", method=result.method,
                               before_tokens=result.before_tokens, after_tokens=result.after_tokens,
                               budget_tokens=result.budget_tokens, forced=force)
                        if request.lifecycle_hook_callback is not None:
                            await self._run_hook(request, "PostCompact", {
                                "trigger": compaction_trigger, "conversation_id": session_id,
                                "session_id": session_id, "run_id": run_id,
                                "cwd": request.workspace or "",
                                "before_tokens": result.before_tokens,
                                "after_tokens": result.after_tokens,
                            })
                        canonical = await asyncio.to_thread(
                            read_session_model_messages, self.data_dir / "engine", session_id,
                        )
                        if canonical:
                            held_messages = _session_history(canonical)
                            durable_history = copy.deepcopy(held_messages)
                            history = copy.deepcopy(held_messages)
                            if request.user_content is not None:
                                current_user = next((item for item in reversed(history)
                                                     if item.get("role") == "user"
                                                     and _message_text(item) == request.message), None)
                                if current_user is not None:
                                    current_user["content"] = request.user_content
                            prompt = assemble_prompt(history)
                            messages = prompt.messages
                            messages.extend(copy.deepcopy(pending_stop_responses))
                            messages.extend(copy.deepcopy(pending_nudges))
                        else:
                            messages = result.messages
                    elif compaction_lease["holder"]:
                        from atlas.engine.session_sync import abort_session_compaction

                        await asyncio.to_thread(
                            abort_session_compaction, self.data_dir / "engine", session_id,
                            compaction_lease["holder"],
                        )
                        compaction_lease["holder"] = None
                    if result.error and result.after_tokens > result.budget_tokens:
                        raise ModelCallError(result.error, category="context_budget")
                    return result

                compaction = await prepare_compaction()
                if compaction.method != "none":
                    yield emit("run.compaction.progress", data={
                        "phase": compaction.method, "before_tokens": compaction.before_tokens,
                        "after_tokens": compaction.after_tokens,
                    })

                available_tools = agent._model_facing_tools()
                from atlas.kernel.tools import kernel_tool_schemas

                include_workflow = (
                    getattr(runtime, "agent_role", "general") != "leaf"
                    and int(getattr(runtime, "agent_depth", 0) or 0) < 1
                )
                schema_names = {
                    str((item.get("function") or item).get("name", ""))
                    for item in available_tools
                }
                from atlas.engine.tool_permissions import tool_allowed

                tool_allow = getattr(runtime, "tool_allow", None)
                tool_deny = getattr(runtime, "tool_deny", ())
                read_only = bool(getattr(runtime, "read_only", False))
                available_tools.extend(
                    schema for schema in kernel_tool_schemas(include_workflow=include_workflow)
                    if str(schema["function"]["name"]) not in schema_names
                    and tool_allowed(str(schema["function"]["name"]), tool_allow, tool_deny)
                    and not (read_only and schema["function"]["name"] == "workflow")
                )
                if edit_manager is not None:
                    # One way to edit text: the kernel editor (read-checked, fuzzy matching).
                    # The exact-match local_edit tools stay registered, just not offered.
                    available_tools = [
                        item for item in available_tools
                        if str((item.get("function") or item).get("name", ""))
                        not in {"local_edit", "local_edit_batch"}
                    ]
                    available_tools = [*available_tools, *edit_manager.get_tools_for_llm()]
                deferred_note = None
                schema_chars_before = len(json.dumps(available_tools, ensure_ascii=False, default=str))
                if not tool_allow:
                    # Library: rarely used / MCP schemas collapse to a stable name list.
                    from atlas.library.runtime import partition_tools

                    try:
                        available_tools, deferred_note = partition_tools(
                            available_tools, session_id=session_id, query=request.message,
                            config=raw_config,
                        )
                    except Exception:
                        log.warning("kernel.tool_deferral_failed", exc_info=True)
                record("tool_offer", offered=len(available_tools), deferred=bool(deferred_note),
                       schema_chars_before=schema_chars_before,
                       schema_chars=len(json.dumps(available_tools, ensure_ascii=False, default=str)))
                if deferred_note and not any(
                    item.get("role") == "system" and str(item.get("content", "")).startswith("Deferred tools:")
                    for item in messages
                ):
                    insert_at = 1 if messages and messages[0].get("role") == "system" else 0
                    messages = [*messages[:insert_at], {"role": "system", "content": deferred_note},
                                *messages[insert_at:]]
                tools = plan.filter_tools(available_tools, read_only_names=("build_repo_map",))
                tool_json = json.dumps(messages, ensure_ascii=False, default=str)
                record("model_request", model=turn_model, input_chars=len(tool_json),
                       input_tokens=estimate_tokens(messages), attempt=turn_index + 1)
                transition(RunPhase.AWAITING_MODEL_RESPONSE)
                transition(RunPhase.STREAMING)
                yield emit("run_status", status="running", text="Calling model")

                reasoning_buffer: list[str] = []

                async def flush_reasoning() -> None:
                    if reasoning_buffer:
                        pending = "".join(reasoning_buffer)
                        reasoning_buffer.clear()
                        await event_queue.put(emit("thinking", content=pending))

                async def on_text(delta: str) -> None:
                    await flush_reasoning()
                    partial_response_text.append(delta)
                    yield_event = emit("chunk", content=delta)
                    # Async callback cannot yield from its parent generator; queue it
                    # for the loop's event pump.
                    await event_queue.put(yield_event)

                async def on_event(event: dict[str, Any]) -> None:
                    kind = event.get("type")
                    attempt = int(event.get("attempt") or 1)
                    delta = str(event.get("delta") or "")
                    if kind == "text_delta":
                        state.streamed_text += delta
                    elif kind == "reasoning_delta":
                        state.streamed_reasoning += delta
                        # Stream the model's thinking to the UI in small batches (run_phases maps
                        # "thinking" to run.status/reasoning); per-token events would flood it.
                        reasoning_buffer.append(delta)
                        pending = "".join(reasoning_buffer)
                        if len(pending) >= 80 or "\n" in delta:
                            reasoning_buffer.clear()
                            await event_queue.put(emit("thinking", content=pending))
                    elif kind == "refusal_delta":
                        state.streamed_refusal += delta
                    elif kind == "tool_call_delta":
                        index = int(event.get("index") or 0)
                        fragments = state.streamed_tool_calls.setdefault((attempt, index), {})
                        for key in ("id", "name", "arguments"):
                            fragment = event.get(key)
                            if isinstance(fragment, str):
                                fragments[key] = fragments.get(key, "") + fragment

                async def on_attempt(event: dict[str, Any]) -> None:
                    await record_model_attempt(event, purpose="conversation")

                overflow_retry_used = False
                model_interrupted_by_steer = False
                response: ModelCallResult | None = None
                while True:
                    partial_response_text.clear()
                    state.streamed_text = ""
                    state.streamed_reasoning = ""
                    state.streamed_refusal = ""
                    state.streamed_tool_calls.clear()
                    model_cancel_event = asyncio.Event()
                    if request.cancel_event is not None and request.cancel_event.is_set():
                        model_cancel_event.set()
                    cancel_waiter = (
                        asyncio.create_task(request.cancel_event.wait())
                        if request.cancel_event is not None else None
                    )
                    steer_count_at_model_start = len(steer_messages)
                    model_task = asyncio.create_task(complete_stream(
                        agent, turn_model, messages, tools,
                        reasoning_effort=turn_effort,
                        max_output_tokens=output_token_limit,
                        cancel_event=model_cancel_event,
                        max_retries=model_retries,
                        fallback_models=list(getattr(runtime, "fallback_models", []) or []),
                        retry_watchdog=retry_watchdog,
                        retry_watchdog_max_wait_s=watchdog_max_wait,
                        overloaded_retry_base_delay_s=overloaded_retry_base_delay,
                        on_text=on_text, on_attempt=on_attempt, on_event=on_event,
                        usage_budget=usage_budget,
                    ))
                    queue_get = asyncio.create_task(event_queue.get())
                    steer_get = (
                        asyncio.create_task(request.steer_queue.get())
                        if request.steer_queue is not None else None
                    )
                    stream_error: ModelCallError | None = None
                    try:
                        while (not model_task.done() or not event_queue.empty()
                               or (steer_get is not None and steer_get.done())):
                            waiters: set[asyncio.Task[Any]] = {model_task, queue_get}
                            if steer_get is not None:
                                waiters.add(steer_get)
                            if cancel_waiter is not None:
                                waiters.add(cancel_waiter)
                            done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
                            if cancel_waiter is not None and cancel_waiter in done:
                                model_cancel_event.set()
                                cancel_waiter = None
                            if steer_get is not None and steer_get in done:
                                steer_payload = steer_get.result()
                                steer = await accept_steer(steer_payload)
                                if steer is not None:
                                    await event_queue.put(steer["event"])
                                    if steer["immediate"] and not steer["send_now"]:
                                        model_interrupted_by_steer = True
                                        if not model_task.done():
                                            model_cancel_event.set()
                                steer_get = (
                                    asyncio.create_task(request.steer_queue.get())
                                    if request.steer_queue is not None else None
                                )
                            if queue_get in done:
                                queued_event = queue_get.result()
                                if (isinstance(queued_event, dict)
                                        and queued_event.get("type") == "approval_required"
                                        and state.phase == RunPhase.TOOLS):
                                    transition(RunPhase.WAITING_APPROVAL)
                                yield queued_event
                                queue_get = asyncio.create_task(event_queue.get())
                        try:
                            response = await model_task
                        except ModelCallError as exc:
                            stream_error = exc
                    except asyncio.CancelledError:
                        if model_interrupted_by_steer:
                            await asyncio.gather(model_task, return_exceptions=True)
                        else:
                            model_task.cancel()
                            await asyncio.gather(model_task, return_exceptions=True)
                            raise
                    finally:
                        pending_tasks = [queue_get, steer_get, cancel_waiter]
                        for task in pending_tasks:
                            if task is not None and not task.done():
                                task.cancel()
                        await asyncio.gather(
                            *(task for task in pending_tasks if task is not None),
                            return_exceptions=True,
                        )

                    if model_interrupted_by_steer:
                        await preserve_partial_output("steered")
                        partial_response_text.clear()
                        state.streamed_text = ""
                        state.streamed_reasoning = ""
                        state.streamed_refusal = ""
                        state.streamed_tool_calls.clear()
                        try:
                            canonical_rows = await asyncio.to_thread(
                                read_session_model_messages, self.data_dir / "engine", session_id,
                            )
                            if canonical_rows:
                                durable_history = _session_history(canonical_rows)
                                history = copy.deepcopy(durable_history)
                                if request.user_content is not None:
                                    current_user = next((item for item in reversed(history)
                                                         if item.get("role") == "user"
                                                         and _message_text(item) == request.message), None)
                                    if current_user is not None:
                                        current_user["content"] = request.user_content
                                prompt = assemble_prompt(history)
                                messages = prompt.messages
                                messages.extend(copy.deepcopy(pending_stop_responses))
                                messages.extend(copy.deepcopy(pending_nudges))
                        except Exception:
                            log.exception("kernel.session_refresh_failed", extra={"session_id": session_id})
                        transition(RunPhase.AWAITING_MODEL_RESPONSE)
                        model_interrupted_by_steer = False
                        overflow_retry_used = False
                        continue
                    if stream_error is not None:
                        if (stream_error.category != "context_window_exceeded"
                                or overflow_retry_used):
                            raise stream_error
                        overflow_retry_used = True
                        compaction = await prepare_compaction(force=True)
                        if compaction.method == "none":
                            raise stream_error
                        yield emit("run.compaction.progress", data={
                            "phase": compaction.method,
                            "before_tokens": compaction.before_tokens,
                            "after_tokens": compaction.after_tokens,
                            "trigger": "provider_context_window_exceeded",
                        })
                        partial_response_text.clear()
                        state.streamed_text = ""
                        state.streamed_reasoning = ""
                        state.streamed_refusal = ""
                        state.streamed_tool_calls.clear()
                        transition(RunPhase.AWAITING_MODEL_RESPONSE)
                        record("model_request", model=turn_model,
                               input_chars=len(json.dumps(messages, ensure_ascii=False, default=str)),
                               input_tokens=estimate_tokens(messages), attempt=turn_index + 1,
                               context_retry=True)
                        continue
                    if response is None:
                        raise ModelCallError("Model stream ended without a response", category="stream")
                    break

                pending_nudges.clear()
                pending_stop_responses.clear()
                usage = _usage_row(response, uuid.uuid4().hex)
                await flush_reasoning()
                turn_reasoning = state.streamed_reasoning
                assistant_content = response.text or state.streamed_refusal
                state.response_text = assistant_content
                state.usage = usage
                stuck.observe_message(assistant_content)
                partial_response_text.clear()

                if not response.tool_calls:
                    final_response = assistant_content
                    if len(steer_messages) > steer_count_at_model_start:
                        if final_response:
                            await persist_async("assistant", final_response, {
                                "kernel_run_id": run_id, "finish_reason": "queued_steer", "reasoning": turn_reasoning or None,
                                "refusal_present": bool(state.streamed_refusal),
                            })
                        state.streamed_text = ""
                        state.streamed_reasoning = ""
                        state.streamed_refusal = ""
                        state.streamed_tool_calls.clear()
                        continue
                    stop_hook = await self._run_hook(request, "Stop", {
                        "last_assistant_message": final_response,
                        "stop_hook_active": stop_hook_active,
                        "conversation_id": session_id, "session_id": session_id,
                        "run_id": run_id, "cwd": request.workspace or "",
                    })
                    stop_blocked = bool(stop_hook.get("blocked")) or stop_hook.get("continue") is False
                    if stop_blocked and not stop_hook_active:
                        stop_hook_active = True
                        if final_response:
                            blocked_response = {
                                "role": "assistant", "content": final_response,
                            }
                            pending_stop_responses.append(blocked_response)
                            messages.append(copy.deepcopy(blocked_response))
                        feedback = str(stop_hook.get("reason") or
                                       stop_hook.get("additional_context") or
                                       stop_hook.get("feedback") or
                                       "Stop hook requested another assistant response.")
                        queue_nudge(feedback)
                        record("hook_blocked", hook="Stop", reason=feedback,
                               stop_hook_active=True)
                        yield emit("run.recovery.notice", data={"message": feedback})
                        continue
                    if stop_blocked:
                        record("hook_block_ignored", hook="Stop",
                               reason=str(stop_hook.get("reason") or ""),
                               stop_hook_active=True)
                    if final_response:
                        await persist_async("assistant", final_response, {
                            "kernel_run_id": run_id, "finish_reason": "stop", "reasoning": turn_reasoning or None,
                            "refusal_present": bool(state.streamed_refusal),
                        })
                    state.streamed_text = ""
                    state.streamed_reasoning = ""
                    state.streamed_refusal = ""
                    state.streamed_tool_calls.clear()
                    decision = stuck.check()
                    if decision and decision.action == "nudge":
                        queue_nudge(decision.message)
                        record("stuck", action=decision.action, reason=decision.reason)
                        yield emit("run.recovery.notice", data={"message": decision.message})
                        continue
                    break

                calls = response.tool_calls
                for call in calls:
                    diag = call.get("arg_diag") if isinstance(call.get("arg_diag"), dict) else {}
                    if call.get("arg_error"):
                        bad_tool_args[str(call["id"])] = str(call["arg_error"])
                        record("tool_args_invalid", tool_call_id=call["id"], name=call["name"],
                               truncated="output length limit" in str(call["arg_error"]), **diag)
                    elif call.get("args_repaired"):
                        record("tool_args_repaired", tool_call_id=call["id"], name=call["name"],
                               **diag)
                state.tool_calls.extend(calls)
                open_call_ids.update(str(call["id"]) for call in calls)
                assistant_message = {
                    "role": "assistant", "content": assistant_content,
                    "tool_calls": [_tool_call_for_history(call) for call in calls],
                }
                messages.append(assistant_message)
                await persist_async("assistant", assistant_content, {
                    "tool_calls": assistant_message["tool_calls"], "kernel_run_id": run_id, "reasoning": turn_reasoning or None,
                    "refusal_present": bool(state.streamed_refusal),
                })
                state.streamed_text = ""
                state.streamed_reasoning = ""
                state.streamed_refusal = ""
                state.streamed_tool_calls.clear()
                transition(RunPhase.SCHEDULING_TOOLS)
                for call in calls:
                    call_id, name, args = str(call["id"]), str(call["name"]), dict(call["args"])
                    plan.require_tool(name, read_only=scheduler.supports_parallel({
                        "id": call_id, "function": {"name": name, "arguments": args},
                    }))
                    yield emit("tool_call", id=call_id, name=name, arguments=args)
                transition(RunPhase.TOOLS)
                await _wait_until_resumed(pause_event, request.cancel_event)
                tool_calls_wire = [{"id": call["id"], "function": {
                    "name": call["name"], "arguments": json.dumps(call["args"], ensure_ascii=False),
                }} for call in calls]

                async def consume_tool_results(
                    results: list[ToolExecutionResult],
                ) -> list[dict[str, Any]]:
                    result_events: list[dict[str, Any]] = []
                    for result in results:
                        receipt = result.receipt.as_dict()
                        receipts.append(receipt)
                        tool_args = tool_inputs.get(result.call_id, next(
                            (call["args"] for call in calls if call["id"] == result.call_id), {}
                        ))
                        initial_error = (
                            bool(isinstance(result.output, dict) and (
                                result.output.get("is_error")
                                or result.output.get("error")
                                or result.output.get("success") is False
                            ))
                            or receipt["state"] not in {"completed", "cancelled"}
                        )
                        hook_payload = {
                            "tool_name": result.name, "tool_use_id": result.call_id,
                            "tool_input": copy.deepcopy(tool_args),
                            "tool_response": _tool_output_text(result.output),
                            "conversation_id": session_id, "run_id": run_id,
                            "cwd": request.workspace or "",
                        }
                        if not initial_error:
                            post_tool = await self._run_hook(request, "PostToolUse", hook_payload)
                            if post_tool.get("updated_tool_output") is not None:
                                result.output = post_tool["updated_tool_output"]
                            for key in ("additional_context", "feedback"):
                                value = post_tool.get(key)
                                if isinstance(value, str) and value.strip():
                                    tool_hook_context.setdefault(result.call_id, []).append(value.strip())
                            if post_tool.get("blocked") or post_tool.get("continue") is False:
                                value = post_tool.get("reason")
                                if isinstance(value, str) and value.strip():
                                    tool_hook_context.setdefault(result.call_id, []).append(value.strip())
                        elif result.call_id not in pretool_blocked:
                            failure_hook = await self._run_hook(request, "PostToolUseFailure", {
                                **hook_payload,
                                "error": (result.output.get("error") if isinstance(result.output, dict)
                                          else _tool_output_text(result.output)),
                                "error_type": receipt["state"],
                            })
                            for key in ("additional_context", "feedback"):
                                value = failure_hook.get(key)
                                if isinstance(value, str) and value.strip():
                                    tool_hook_context.setdefault(result.call_id, []).append(value.strip())
                            reason = failure_hook.get("reason")
                            if isinstance(reason, str) and reason.strip():
                                tool_hook_context.setdefault(result.call_id, []).append(reason.strip())
                        record("tool_end", tool_call_id=result.call_id, name=result.name,
                               state=receipt["state"], duration_ms=receipt["duration_ms"],
                               output_ref=receipt.get("output_ref"),
                               output=_tool_output_text(result.output))
                        content = _tool_output_text(result.output)
                        if tool_hook_context.get(result.call_id):
                            content += "\n\n" + "\n".join(tool_hook_context.pop(result.call_id))
                        is_error = (
                            bool(isinstance(result.output, dict) and (
                                result.output.get("is_error")
                                or result.output.get("error")
                                or result.output.get("success") is False
                            ))
                            or receipt["state"] not in {"completed", "cancelled"}
                        )
                        if is_error:
                            consecutive_tool_failures += 1
                        else:
                            consecutive_tool_failures = 0
                        if consecutive_tool_failures == 2:
                            try:
                                from atlas.memory.library.recall import recheck_memory

                                reread = await asyncio.to_thread(
                                    recheck_memory, content, limit=3,
                                )
                                memory_block = str(reread.get("block") or "").strip()
                                if memory_block:
                                    content += "\n\n" + memory_block
                            except Exception as exc:
                                log.warning("memory.recheck_after_tool_failures_failed", extra={
                                    "run_id": run_id, "error_type": type(exc).__name__,
                                })
                        record("tool_result", tool_call_id=result.call_id, name=result.name,
                               state=receipt["state"], is_error=is_error,
                               output_ref=receipt.get("output_ref"), output=content)
                        tool_content: Any = content
                        image_url = (
                            result.output.get("data", {}).get("_image_data_url")
                            if isinstance(result.output, dict)
                            and isinstance(result.output.get("data"), dict) else None
                        )
                        if isinstance(image_url, str):
                            tool_content = [
                                {"type": "text", "text": content},
                                {"type": "image_url", "image_url": {"url": image_url}},
                            ]
                        messages.append({"role": "tool", "tool_call_id": result.call_id,
                                         "name": result.name, "content": tool_content})
                        active_call_ids.discard(result.call_id)
                        open_call_ids.discard(result.call_id)
                        pretool_blocked.discard(result.call_id)
                        tool_message_uid = await persist_async("tool", content, {
                            "tool_call_id": result.call_id, "tool_name": result.name,
                            "kernel_run_id": run_id, "output_ref": receipt.get("output_ref"),
                            "receipt_state": receipt["state"],
                            "duration_ms": receipt["duration_ms"],
                        })
                        if (tool_message_uid and
                                (result.name.startswith("delegate_")
                                 or result.name.startswith("subagent_"))):
                            schedule_lifecycle("delegation_return", [tool_message_uid],
                                               scope="messages", tool_call_id=result.call_id)
                        stuck.observe_tool(result.name, tool_args, result.output, is_error=is_error)
                        result_events.append(emit(
                            "tool_result", id=result.call_id, name=result.name,
                            content=[{"type": "text", "text": _tool_result_event_text(result)}],
                            data={"state": receipt["state"],
                                  "duration_ms": receipt["duration_ms"]},
                            is_error=is_error,
                            **({"error_category": "tool"} if is_error else {}),
                        ))
                    return result_events

                tool_task = asyncio.create_task(scheduler.run(tool_calls_wire))
                queue_get = asyncio.create_task(event_queue.get())
                try:
                    while not tool_task.done() or not event_queue.empty():
                        done, _ = await asyncio.wait(
                            {tool_task, queue_get}, return_when=asyncio.FIRST_COMPLETED,
                        )
                        if queue_get in done:
                            queued_event = queue_get.result()
                            if (isinstance(queued_event, dict)
                                    and queued_event.get("type") == "approval_required"
                                    and state.phase == RunPhase.TOOLS):
                                transition(RunPhase.WAITING_APPROVAL)
                            yield queued_event
                            queue_get = asyncio.create_task(event_queue.get())
                    results: list[ToolExecutionResult] = await tool_task
                except asyncio.CancelledError:
                    tool_task.cancel()
                    settled = await asyncio.gather(tool_task, return_exceptions=True)
                    results = settled[0] if settled and isinstance(settled[0], list) else []
                    if state.phase in {RunPhase.TOOLS, RunPhase.WAITING_APPROVAL}:
                        transition(RunPhase.AGGREGATING_RESULTS)
                    await consume_tool_results(results)
                    record("tool_batch_cancelled", call_count=len(tool_calls_wire),
                           settled_count=len(results))
                    while not event_queue.empty():
                        queued_event = event_queue.get_nowait()
                        if isinstance(queued_event, dict):
                            record("tool_event", event_type=queued_event.get("type"),
                                   tool_call_id=queued_event.get("id"),
                                   name=queued_event.get("name"))
                    raise
                finally:
                    queue_get.cancel()
                    await asyncio.gather(queue_get, return_exceptions=True)

                transition(RunPhase.AGGREGATING_RESULTS)
                for result_event in await consume_tool_results(results):
                    yield result_event
                tool_batch_records = [{
                        "tool_use_id": result.call_id,
                        "tool_name": result.name,
                        "tool_input": copy.deepcopy(tool_inputs.get(result.call_id, next(
                            (call["args"] for call in calls if call["id"] == result.call_id), {}
                        ))),
                        "tool_response": _tool_output_text(result.output)[:4000],
                    } for result in results]
                batch_hook = await self._run_hook(request, "PostToolBatch", {
                    "tool_calls": tool_batch_records,
                    "tool_uses": tool_batch_records,
                    "conversation_id": session_id, "session_id": session_id,
                    "run_id": run_id, "cwd": request.workspace or "",
                })
                batch_blocked = bool(batch_hook.get("blocked")) or batch_hook.get("continue") is False
                if batch_blocked:
                    reason = str(batch_hook.get("reason") or
                                 batch_hook.get("additional_context") or
                                 "Tool batch blocked by PostToolBatch hook.")
                    final_response = reason
                    state.response_text = reason
                    record("hook_blocked", hook="PostToolBatch", reason=reason)
                    await persist_async("assistant", reason, {
                        "kernel_run_id": run_id, "finish_reason": "post_tool_batch_blocked",
                    })
                    yield emit("chunk", content=reason)
                    break
                batch_feedback = batch_hook.get("additional_context") or batch_hook.get("feedback")
                if isinstance(batch_feedback, str) and batch_feedback.strip():
                    queue_nudge(batch_feedback.strip())
                transition(RunPhase.STREAMING)

                decision = stuck.check()
                if decision is not None:
                    record("stuck", action=decision.action, reason=decision.reason)
                    if decision.action == "nudge":
                        queue_nudge(decision.message)
                        yield emit("run.recovery.notice", data={"message": decision.message})
                    else:
                        final_response = decision.message
                        await persist_async("assistant", final_response, {
                            "kernel_run_id": run_id, "finish_reason": "stuck_halt",
                        })
                        yield emit("chunk", content=final_response)
                        break
                for steer in await apply_pending_steers():
                    yield steer["event"]
            else:
                raise RuntimeError(f"Kernel reached its {max_turns}-turn limit")

            transition(RunPhase.DONE)
            if run_message_uids:
                schedule_lifecycle("turn_end", list(run_message_uids))
            elapsed = int((time.monotonic() - started_at) * 1000)
            record("run_end", status="completed",
                   duration_ms=elapsed, total_input_tokens=sum(int(row.get("input_tokens") or 0) for row in usage_rows),
                   total_output_tokens=sum(int(row.get("output_tokens") or 0) for row in usage_rows))
            yield emit("hermes.result", result={"final_response": final_response,
                                                "usage": usage_rows})
        except asyncio.CancelledError:
            if state.phase not in {RunPhase.DONE, RunPhase.FAILED, RunPhase.INTERRUPTED}:
                transition(RunPhase.INTERRUPTED)
            try:
                await preserve_partial_output("interrupted")
                if open_call_ids:
                    repaired, repairs = repair_unpaired_tool_calls(
                        messages, started_ids=active_call_ids, run_id=run_id,
                    )
                    for repair in repairs:
                        record("repair", **repair)
                        tool_message = next(item for item in repaired
                                            if item.get("role") == "tool"
                                            and item.get("tool_call_id") == repair["tool_call_id"])
                        await persist_async("tool", tool_message["content"], {
                            "tool_call_id": repair["tool_call_id"],
                            "tool_name": repair["name"], "repair_state": repair["state"],
                            "kernel_run_id": run_id,
                        })
                else:
                    record("repair", state="run_interrupted")
                record("run_end", status="interrupted", duration_ms=int((time.monotonic() - started_at) * 1000),
                       total_input_tokens=sum(int(row.get("input_tokens") or 0) for row in usage_rows),
                       total_output_tokens=sum(int(row.get("output_tokens") or 0) for row in usage_rows),
                       reason="cancelled")
            finally:
                if exec_manager is not None:
                    await exec_manager.shutdown()
            raise
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            if state.phase not in {RunPhase.DONE, RunPhase.FAILED, RunPhase.INTERRUPTED}:
                state.error = failure
                transition(RunPhase.FAILED)
            with contextlib.suppress(Exception):
                await preserve_partial_output("error")
            log.exception("kernel.run_failed", extra={"run_id": run_id, "session_id": session_id})
            record("run_end", status="failed", duration_ms=int((time.monotonic() - started_at) * 1000),
                   total_input_tokens=sum(int(row.get("input_tokens") or 0) for row in usage_rows),
                   total_output_tokens=sum(int(row.get("output_tokens") or 0) for row in usage_rows),
                   reason=failure)
            try:
                await self._run_hook(request, "StopFailure", {
                    "error_type": type(exc).__name__, "error": failure,
                    "conversation_id": session_id, "session_id": session_id,
                    "run_id": run_id, "cwd": request.workspace or "",
                    "log_path": str(log_path or ""),
                })
            except Exception:
                log.exception("kernel.stop_failure_hook_failed", extra={"run_id": run_id})
            log_detail = f"{failure} (run log: {log_path})" if log_path else failure
            yield emit("error", category="model" if isinstance(exc, ModelCallError) else "runtime",
                       detail=log_detail, log_path=str(log_path or ""))
        finally:
            if exec_manager is not None and state.phase in {RunPhase.FAILED, RunPhase.INTERRUPTED}:
                await exec_manager.shutdown()

    async def _run_hook(self, request: KernelRequest, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        callback = request.lifecycle_hook_callback
        if callback is None:
            return {}
        result = callback(name, payload)
        if asyncio.iscoroutine(result):
            result = await result
        return result if isinstance(result, dict) else {}

    async def _dispatch(
        self, agent: Any, runtime: Any, call_id: str | None, name: str, arguments: dict[str, Any],
        event_queue: asyncio.Queue[Any], *, exec_manager: Any = None, nested: bool = False,
    ) -> Any:
        async def dispatch_alias(target: str, args: dict[str, Any]) -> Any:
            internal_events: asyncio.Queue[Any] = asyncio.Queue()
            result = await self._dispatch(
                agent, runtime, call_id, target, args, internal_events,
                exec_manager=exec_manager, nested=nested,
            )
            while not internal_events.empty():
                event = internal_events.get_nowait()
                if not isinstance(event, dict) or event.get("type") not in {
                    "tool_call", "tool_result", "approval_required",
                }:
                    await event_queue.put(event)
            return result

        from atlas.kernel.lifecycle_tools import dispatch_lifecycle_tool
        lifecycle_result = await dispatch_lifecycle_tool(name, arguments, runtime)
        if lifecycle_result is not None:
            return lifecycle_result

        async def request_tool_approval(reason: str) -> bool:
            approved_ids = getattr(runtime, "_preapproved_tool_call_ids", set())
            if call_id and call_id in approved_ids:
                return True
            approval = getattr(runtime, "approval_callback", None)
            if not callable(approval):
                return False
            approval_id = f"approval:{call_id or uuid.uuid4().hex}"
            await event_queue.put({
                "type": "approval_required", "event_id": approval_id,
                "tool_call_id": call_id, "name": name,
                "arguments": dict(arguments), "reason": reason,
            })
            approval_args = {**dict(arguments), "_approval_reason": reason,
                             "_approval_scope": "this tool call"}
            decision = approval(approval_id, name, approval_args)
            if hasattr(decision, "__await__"):
                decision = await decision
            return decision == "allow"

        if name == "browser_use":
            operation = str(arguments.get("operation") or "").strip().lower()
            normalized = operation.removeprefix("browser.")
            browser_arguments = arguments.get("arguments")
            if not isinstance(browser_arguments, dict):
                browser_arguments = {}
            write_operations = {
                "browsers.open", "tabs.new", "tabs.open", "tabs.finalize", "tabs.finalise",
                "tab.goto", "tab.back", "tab.forward", "tab.reload", "tab.close",
                "tab.evaluate", "tab.cua.click", "tab.cua.double_click", "tab.cua.move",
                "tab.cua.scroll", "tab.cua.drag", "tab.cua.keypress", "tab.cua.type",
                "tab.dom_cua.click", "tab.dom_cua.double_click", "tab.dom_cua.scroll",
                "tab.dom_cua.keypress", "tab.dom_cua.type", "tab.markhandoff",
                "tab.mark_handoff", "tab.markdeliverable", "tab.mark_deliverable",
                "tab.respondjsdialog", "tab.respond_js_dialog", "recording.start",
                "recording.cancel", "capability.set", "capabilities.set",
                "capability.visibility.set", "capability.headless.set",
                "tab.setviewportsize", "tab.set_viewport_size",
                "tab.waitforfunction", "tab.wait_for_function",
            }
            action = str(browser_arguments.get("action") or "").lower()
            changes_page = normalized in write_operations or (
                normalized in {"tab.locator", "tab.getbyrole", "tab.getbytext",
                               "tab.getbylabel", "tab.getbyplaceholder", "tab.getbytestid",
                               "tab.getbyalttext", "tab.getbytitle"}
                and action in {"click", "fill", "check", "hover"}
            )
            if changes_page and not await request_tool_approval(
                "Browser navigation, page interaction, recording, or browser state changes require approval."
            ):
                return {"content": "Browser operation was not approved.", "is_error": True,
                        "outcome": "denied"}
            from atlas.tools.browser_use_compat import browser_use_call

            result = await browser_use_call(
                operation, browser_arguments, runtime=runtime,
            )
            return {"content": json.dumps(result, ensure_ascii=False, default=str),
                    "data": result, "is_error": not bool(result.get("success")),
                    "outcome": "completed" if result.get("success") else "failed"}

        if name in {
            "image_generate", "image_edit", "x_search", "video_analyze",
            "video_generate", "video_edit", "video_extend", "video_job_status",
            "text_to_speech", "music_generate", "security_scan",
        }:
            writes = {
                "image_generate", "image_edit", "video_generate", "video_edit",
                "video_extend", "text_to_speech", "music_generate", "x_search",
                "video_analyze",
            }
            sends_source_for_review = name == "security_scan" and bool(
                arguments.get("include_model_review")
            )
            if (name in writes or sends_source_for_review) and not await request_tool_approval(
                "This media operation contacts a provider, may incur charges, and/or writes an artifact."
            ):
                return {"content": f"{name} was not approved.", "is_error": True,
                        "outcome": "denied"}
            from atlas.tools.media_generation_search import f1_d_dispatch

            return await f1_d_dispatch(name, arguments, agent, runtime)

        if name in {
            "workflow_run_manage", "workspace_session_manage", "workspace_worktree_manage",
            "model_provider_discovery", "workspace_app_manage", "visualization_artifact",
            "focused_call_graph", "workspace_summarize", "recording_skill",
        }:
            if name == "workspace_worktree_manage" and not getattr(
                runtime, "workspace_worktree_service", None,
            ):
                try:
                    from atlas.config import get_config
                    from atlas.task_artifacts import WorktreeService

                    runtime.workspace_worktree_service = WorktreeService(
                        get_config().db_path.parent,
                    )
                except Exception:
                    pass
            from atlas.tools.workspace_workflows import workspace_workflow_dispatch

            return await workspace_workflow_dispatch(name, arguments, agent, runtime)

        if name == "clock.curr_time":
            from datetime import UTC, datetime

            return {"content": datetime.now(UTC).isoformat(), "outcome": "completed"}
        if name == "clock.sleep":
            seconds = max(0.0, min(300.0, float(arguments.get("seconds", 0))))
            await asyncio.sleep(seconds)
            return {"content": f"Waited {seconds:g} seconds.", "outcome": "completed"}
        if name == "view_image":
            from atlas.tools.local_image import view_workspace_image

            try:
                result = view_workspace_image(
                    str(getattr(runtime, "workspace", "") or ""),
                    str(arguments.get("path") or ""),
                    str(arguments.get("detail") or "auto"),
                )
            except (OSError, ValueError) as exc:
                return {"content": str(exc), "is_error": True, "outcome": "failed"}
            return {"content": result["content"], "data": result["data"], "outcome": "completed"}
        if name in {"glob", "grep"}:
            from atlas.tools.workspace_queries import glob_workspace, grep_workspace

            workspace = str(getattr(runtime, "workspace", "") or "")
            if not workspace:
                return {"content": "Workspace queries require an active workspace.", "is_error": True}
            try:
                if name == "glob":
                    data = await asyncio.to_thread(
                        glob_workspace, workspace,
                        pattern=arguments.get("pattern"), path=arguments.get("path"),
                        hidden=bool(arguments.get("hidden", False)),
                        limit=arguments.get("limit", 200),
                    )
                else:
                    data = await asyncio.to_thread(
                        grep_workspace, workspace,
                        pattern=arguments.get("pattern"), path=arguments.get("path"),
                        include=arguments.get("include"),
                        literal=bool(arguments.get("literal", False)),
                        case_sensitive=bool(arguments.get("caseSensitive", True)),
                        limit=arguments.get("limit", 200),
                    )
            except (OSError, RuntimeError, ValueError) as exc:
                return {"content": str(exc), "is_error": True, "outcome": "failed"}
            return {"content": json.dumps(data, ensure_ascii=False),
                    "data": data, "outcome": "completed"}
        if name in {"lsp_diagnostics", "lsp_hover", "lsp_definition",
                    "lsp_references", "lsp_document_symbols"}:
            from atlas.tools.workspace_lsp import query_lsp

            workspace = str(getattr(runtime, "workspace", "") or "")
            if not workspace:
                return {"content": "LSP queries require an active workspace.", "is_error": True}
            operation = {
                "lsp_diagnostics": "diagnostics", "lsp_hover": "hover",
                "lsp_definition": "definition", "lsp_references": "references",
                "lsp_document_symbols": "document_symbols",
            }[name]
            try:
                data = await asyncio.to_thread(
                    query_lsp, workspace, operation=operation,
                    path=arguments.get("path"), line=arguments.get("line"),
                    character=arguments.get("character"),
                    include_declaration=bool(arguments.get("includeDeclaration", True)),
                )
            except (OSError, RuntimeError, ValueError) as exc:
                return {"content": str(exc), "is_error": True, "outcome": "failed"}
            return {"content": json.dumps(data, ensure_ascii=False, default=str),
                    "data": data, "outcome": "completed"}
        if name == "update_plan":
            from atlas.agent.planning import TaskPlan

            entries = arguments.get("plan")
            if not isinstance(entries, list) or not entries:
                return {"content": "plan must contain at least one step.", "is_error": True}
            if len(entries) > 100:
                return {"content": "plan is limited to 100 steps.", "is_error": True}
            todos = []
            subtasks = []
            for index, item in enumerate(entries, start=1):
                if not isinstance(item, dict):
                    return {"content": "Each plan step must be an object.", "is_error": True}
                title = str(item.get("step") or "").strip()
                status = str(item.get("status") or "pending")
                if not title or status not in {"pending", "in_progress", "completed"}:
                    return {"content": f"Invalid plan step at index {index}.", "is_error": True}
                task_id = f"step-{index}"
                todos.append({"id": task_id, "content": title, "status": status})
                subtasks.append({
                    "id": task_id, "title": title,
                    "verification": "Completion status supplied through update_plan.",
                    "status": "completed" if status == "completed" else "pending",
                })
            goal = str(arguments.get("explanation") or getattr(runtime, "goal", "") or "Updated plan").strip()
            snapshot = TaskPlan.from_dict({"goal": goal, "subtasks": subtasks}).to_dict()
            runtime.plan_state = snapshot
            callback = getattr(runtime, "plan_update_callback", None)
            if callable(callback):
                result = callback(snapshot)
                if hasattr(result, "__await__"):
                    await result
            todo_store = getattr(runtime, "todo_store", None)
            if todo_store is not None:
                todo_snapshot = todo_store.write(todos)
                await event_queue.put({"type": "run_todos", **todo_snapshot})
            if not callable(callback) and todo_store is None:
                return {"content": "This run does not expose a plan or todo update channel.", "is_error": True}
            await event_queue.put({"type": "plan_updated", "plan": snapshot})
            return {"content": json.dumps(snapshot, ensure_ascii=False),
                    "data": {"plan": snapshot}, "outcome": "completed"}
        if name == "EnterPlanMode":
            runtime.dynamic_plan_mode = True
            mode_callback = getattr(runtime, "plan_mode_callback", None)
            if callable(mode_callback):
                mode_callback(True)
            await event_queue.put({"type": "plan_mode_changed", "mode": "plan",
                                  "reason": str(arguments.get("reason") or "")})
            return {"content": "Plan mode enabled. Tool execution is now restricted to read-only operations until the user approves the plan.",
                    "data": {"mode": "plan"}, "outcome": "completed"}
        if name == "ExitPlanMode":
            callback = getattr(runtime, "plan_approval_callback", None)
            plan = getattr(runtime, "plan_state", None)
            if not isinstance(plan, dict) or not plan:
                return {"content": "Create a plan with update_plan before requesting approval.",
                        "is_error": True, "outcome": "failed"}
            if not callable(callback):
                return {"content": "This runtime cannot request plan approval.",
                        "is_error": True, "outcome": "failed"}
            approved = callback(plan)
            if hasattr(approved, "__await__"):
                approved = await approved
            if not approved:
                return {"content": "The plan was not approved. Remain in plan mode and revise it or stop.",
                        "is_error": True, "outcome": "denied"}
            runtime.dynamic_plan_mode = False
            mode_callback = getattr(runtime, "plan_mode_callback", None)
            if callable(mode_callback):
                mode_callback(False)
            await event_queue.put({"type": "plan_mode_changed", "mode": "act"})
            return {"content": "The user approved the plan. Plan mode is off; continue with implementation.",
                    "data": {"mode": "act", "summary": str(arguments.get("summary") or "")},
                    "outcome": "completed"}
        if name in {"list_available_plugins_to_install", "request_plugin_install"}:
            from atlas.tools.plugin_marketplace import plugin_runtime_for

            try:
                plugin_runtime = plugin_runtime_for(agent)
                if name == "list_available_plugins_to_install":
                    marketplace_filter = str(arguments.get("marketplace") or "")
                    query = str(arguments.get("query") or "").casefold()
                    limit = max(1, min(100, int(arguments.get("limit", 50))))
                    marketplaces = plugin_runtime.list_marketplaces()
                    installed = {item.get("name") for item in plugin_runtime.discover()}
                    plugins = []
                    for marketplace in marketplaces:
                        market_name = str(marketplace.get("name") or "")
                        if marketplace_filter and market_name != marketplace_filter:
                            continue
                        for item in plugin_runtime.list_marketplace_plugins(market_name):
                            plugin_name = str(item.get("name") or "")
                            if not plugin_name or plugin_name in installed:
                                continue
                            if query and query not in f"{plugin_name} {item.get('description', '')}".casefold():
                                continue
                            plugins.append({key: item[key] for key in (
                                "name", "description", "version", "marketplace", "source",
                            ) if key in item})
                    return {"content": json.dumps(plugins[:limit], ensure_ascii=False),
                            "data": {"plugins": plugins[:limit]}}

                approved_ids = getattr(runtime, "_preapproved_tool_call_ids", set())
                if call_id not in approved_ids:
                    approval = getattr(runtime, "approval_callback", None)
                    if not callable(approval):
                        return {"content": "Plugin installation approval is unavailable in this run.",
                                "is_error": True, "outcome": "denied"}
                    approval_id = f"approval:{call_id or uuid.uuid4().hex}"
                    await event_queue.put({
                        "type": "approval_required", "event_id": approval_id,
                        "tool_call_id": call_id, "name": name, "arguments": dict(arguments),
                    })
                    choice = approval(approval_id, name, dict(arguments))
                    if hasattr(choice, "__await__"):
                        choice = await choice
                    if choice != "allow":
                        return {"content": "Plugin installation was not approved.",
                                "is_error": True, "outcome": "denied"}
                result = await asyncio.to_thread(
                    plugin_runtime.install_marketplace_plugin,
                    str(arguments.get("marketplace") or ""),
                    str(arguments.get("plugin_name") or ""),
                )
                report = await plugin_runtime.load_all(
                    hook_bus=getattr(agent, "hooks", None),
                    mcp_client=getattr(agent, "_mcp", None),
                    capabilities=getattr(agent, "capabilities", None),
                )
                result["loaded"] = result.get("name") in report.get("loaded", [])
                result["load_report"] = report
                return {"content": json.dumps(result, ensure_ascii=False),
                        "data": result, "outcome": "completed"}
            except (KeyError, OSError, RuntimeError, ValueError, PermissionError) as exc:
                return {"content": str(exc), "is_error": True, "outcome": "failed"}
        if name in {"list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource"}:
            client = getattr(agent, "_mcp", None)
            if client is None:
                return {"content": "No MCP client is attached to this run.", "is_error": True}
            if name == "list_mcp_resources":
                result = await client.list_resources(
                    arguments.get("server"), arguments.get("cursor"),
                )
            elif name == "list_mcp_resource_templates":
                result = await client.list_resource_templates(
                    arguments.get("server"), arguments.get("cursor"),
                )
            else:
                result = await client.read_resource(
                    str(arguments.get("server") or ""), str(arguments.get("uri") or ""),
                )
            return {
                "content": json.dumps(result, ensure_ascii=False),
                "data": result,
                "is_error": bool(result.get("is_error")) if isinstance(result, dict) else False,
                "outcome": "failed" if isinstance(result, dict) and result.get("is_error") else "completed",
            }
        if name == "memory_search":
            from atlas.memory.library import get_library

            library = get_library()
            if library is None:
                return {"content": "The memory library is turned off.", "is_error": True}
            open_value = str(arguments.get("open") or "").strip()
            if open_value:
                from atlas.memory.library.sources import open_ref

                opened = await asyncio.to_thread(open_ref, open_value,
                                                 max(1, min(2, int(arguments.get("window", 1) or 1))))
                return {"content": json.dumps(opened, ensure_ascii=False), "data": opened,
                        "outcome": "completed"}
            sources = arguments.get("sources")
            kinds = ("fact", "dream", "episode", "diary", "raw") if isinstance(sources, list) and "raw" in sources else (
                "fact", "dream", "episode", "diary")
            found = await asyncio.to_thread(
                library.search, str(arguments.get("query") or ""),
                max(1, min(20, int(arguments.get("limit", 8) or 8))),
                bool(arguments.get("include_history")),
                kinds,
            )
            return {"content": json.dumps(found, ensure_ascii=False) if found else "No matching memories.",
                    "data": found, "outcome": "completed"}
        if name == "tool_search":
            from atlas.kernel.tools import kernel_tool_schemas

            from atlas.library.runtime import search_tools

            query = str(arguments.get("query") or "").strip()
            limit = max(1, min(50, int(arguments.get("limit", 8) or 8)))
            candidates = list(agent._model_facing_tools())
            candidates.extend(kernel_tool_schemas(include_workflow=True))
            # Loads the matches into this conversation; the next model call offers their schemas.
            found = search_tools(candidates, query, limit=limit,
                                 session_id=str(getattr(runtime, "conversation_id", "") or ""))
            return {"content": json.dumps(found, ensure_ascii=False), "data": found}
        if name == "get_context_remaining":
            callback = getattr(runtime, "context_remaining_callback", None)
            if not callable(callback):
                return {"content": json.dumps({"available": False, "reason": "runtime has no measured token budget"})}
            remaining = callback()
            if asyncio.iscoroutine(remaining):
                remaining = await remaining
            return {"content": json.dumps(remaining, ensure_ascii=False), "data": remaining}
        if name == "read_tool_history":
            limit = max(1, min(100, int(arguments.get("limit", 30) or 30)))
            callback = getattr(runtime, "tool_history_callback", None)
            if not callable(callback):
                return {"content": "Tool history is unavailable for this runtime.", "is_error": True}
            history_messages = callback()
            if asyncio.iscoroutine(history_messages):
                history_messages = await history_messages
            history: list[dict[str, Any]] = []
            for message in history_messages:
                calls = message.get("tool_calls") or []
                if calls:
                    for call in calls:
                        fn = call.get("function") or {}
                        history.append({"kind": "call", "id": call.get("id"),
                                        "name": fn.get("name"), "arguments": fn.get("arguments")})
                elif message.get("role") == "tool":
                    history.append({"kind": "result", "id": message.get("tool_call_id"),
                                    "content": message.get("content", "")})
            result = history[-limit:]
            return {"content": json.dumps(result, ensure_ascii=False), "data": {"items": result}}
        if name == "new_context":
            callback = getattr(runtime, "new_context_window_callback", None)
            hermes_agent = getattr(runtime, "hermes_agent", None)
            if not callable(callback):
                return {"content": "A fresh-context handoff is unavailable for this runtime.", "is_error": True}
            try:
                handoff = await callback()
            except (RuntimeError, ValueError) as exc:
                return {"content": str(exc), "is_error": True, "outcome": "failed"}
            if hermes_agent is not None and isinstance(handoff, str):
                hermes_agent.set_context_handoff_summary(handoff)
            await event_queue.put({
                "type": "context.window.switched", "data": (
                    {"summary": handoff} if isinstance(handoff, str) else dict(handoff)
                ),
            })
            return {"content": "Compacted the current session history and prepared a fresh context.",
                    "data": handoff, "outcome": "completed"}
        if name == "request_permissions":
            approval = getattr(runtime, "approval_callback", None)
            if not callable(approval):
                return {"content": "Permission approval is unavailable in this run.", "is_error": True}
            approval_id = f"permission:{call_id or uuid.uuid4().hex}"
            request = {
                "permission": str(arguments.get("permission") or ""),
                "reason": str(arguments.get("reason") or ""),
                "scope": str(arguments.get("scope") or "this request"),
            }
            await event_queue.put({
                "type": "approval_required", "event_id": approval_id,
                "tool_call_id": call_id, "name": name, "arguments": request,
            })
            result = approval(approval_id, name, request)
            if hasattr(result, "__await__"):
                result = await result
            allowed = result == "allow"
            return {
                "content": "Permission approved for this request only." if allowed else "Permission was not approved.",
                "is_error": not allowed, "outcome": "completed" if allowed else "denied",
            }
        if name in {"request_user_input", "request_user_input_async", "AskUserQuestion"}:
            input_callback = getattr(runtime, "input_callback", None)
            questions = arguments.get("questions")
            if not callable(input_callback):
                return {"content": "This run has no interactive user-input channel.", "is_error": True}
            if not isinstance(questions, list) or not questions:
                return {"content": "questions must contain at least one question.", "is_error": True}
            answers: dict[str, Any] = {}
            for index, question_data in enumerate(questions, start=1):
                if not isinstance(question_data, dict):
                    return {"content": f"Question {index} must be an object.", "is_error": True}
                question = str(question_data.get("question") or "").strip()
                question_id = str(question_data.get("id") or f"question-{index}")
                options = [str(item.get("label") or "") for item in question_data.get("options", [])
                           if isinstance(item, dict) and str(item.get("label") or "").strip()]
                if not question:
                    return {"content": f"Question {index} is empty.", "is_error": True}
                multiple = bool(question_data.get("multi_select", question_data.get("multiSelect", False)))
                details = {
                    "id": question_id, "header": str(question_data.get("header") or "").strip(),
                    "multi_select": multiple,
                    "options": question_data.get("options", []),
                }
                answer = input_callback(f"{call_id or 'input'}:{question_id}", question, options or None, details)
                if hasattr(answer, "__await__"):
                    answer = await answer
                if multiple and isinstance(answer, str):
                    try:
                        decoded = json.loads(answer)
                    except json.JSONDecodeError:
                        decoded = [answer] if answer else []
                    answer = decoded if isinstance(decoded, list) else [str(decoded)]
                answers[question_id] = answer
            return {"content": json.dumps(answers, ensure_ascii=False),
                    "data": {"answers": answers}, "outcome": "completed"}
        if name == "send_message_to_user_async":
            message = str(arguments.get("message") or "").strip()
            if not message:
                return {"content": "message must not be empty.", "is_error": True}
            await event_queue.put({"type": "chunk", "content": message})
            return {"content": "Message sent to the user in the current run.",
                    "data": {"sent": True}, "outcome": "completed"}
        if name in {"TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "TodoWrite"}:
            from atlas.tools.claude_tasks import call_task_tool

            result = call_task_tool(name, arguments, runtime)
            if not result.get("is_error") and name in {"TaskCreate", "TaskUpdate", "TodoWrite"}:
                todo_store = getattr(runtime, "todo_store", None)
                if todo_store is not None:
                    await event_queue.put({"type": "run_todos", **todo_store.snapshot()})
            return result
        if name == "notebook_edit":
            if str(arguments.get("edit_mode") or "replace") != "read":
                approved_ids = getattr(runtime, "_preapproved_tool_call_ids", set())
                if call_id not in approved_ids:
                    approval = getattr(runtime, "approval_callback", None)
                    if not callable(approval):
                        return {"content": "Notebook edits require user approval in this run.",
                                "is_error": True, "outcome": "denied"}
                    approval_id = f"approval:{call_id or uuid.uuid4().hex}"
                    await event_queue.put({
                        "type": "approval_required", "event_id": approval_id,
                        "tool_call_id": call_id, "name": name, "arguments": dict(arguments),
                    })
                    choice = approval(approval_id, name, dict(arguments))
                    if hasattr(choice, "__await__"):
                        choice = await choice
                    if choice != "allow":
                        return {"content": "Notebook edit was not approved.",
                                "is_error": True, "outcome": "denied"}
            from atlas.tools.notebook_edit import notebook_edit

            try:
                result = await asyncio.to_thread(
                    notebook_edit,
                    str(getattr(runtime, "workspace", "") or ""),
                    str(arguments.get("notebook_path") or ""),
                    edit_mode=str(arguments.get("edit_mode") or "replace"),
                    cell_id=arguments.get("cell_id"),
                    cell_type=arguments.get("cell_type"),
                    new_source=arguments.get("new_source"),
                )
            except (OSError, RuntimeError, ValueError) as exc:
                return {"content": str(exc), "is_error": True, "outcome": "failed"}
            return {"content": json.dumps(result, ensure_ascii=False),
                    "data": result, "outcome": "completed"}
        if name == "wait_for_environment":
            import time
            from pathlib import Path

            target = Path(str(arguments.get("path") or getattr(runtime, "workspace", ""))).expanduser()
            timeout = max(0.0, min(60.0, float(arguments.get("timeout_seconds", 10))))
            deadline = time.monotonic() + timeout
            while not target.exists() and time.monotonic() < deadline:
                await asyncio.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
            ready = target.exists()
            result = {"ready": ready, "path": str(target), "waited_seconds": round(timeout - max(0.0, deadline - time.monotonic()), 3)}
            return {"content": json.dumps(result, ensure_ascii=False), "data": result,
                    "is_error": not ready, "outcome": "completed" if ready else "failed"}
        if name == "exec_command":
            command = str(arguments.get("cmd") or "")
            if not command.strip():
                return {"content": "cmd must not be empty.", "is_error": True}
            # "terminal" is a Hermes name the Atlas tool node doesn't register; local_shell
            # is the real tool and routes through this run's ExecManager.
            return await dispatch_alias("local_shell", {
                    "command": command, "cwd": arguments.get("workdir") or getattr(runtime, "workspace", None),
                })
        if name == "powershell":
            import os

            if os.name != "nt":
                return {"content": "The PowerShell tool is available only on Windows.", "is_error": True}
            command = str(arguments.get("command") or "")
            if not command.strip():
                return {"content": "command must not be empty.", "is_error": True}
            return await dispatch_alias("local_shell", {
                "command": command,
                "shell": "powershell",
                "cwd": arguments.get("cwd") or getattr(runtime, "workspace", None),
            })
        if name == "write_stdin":
            stop = bool(arguments.get("stop"))
            chars = str(arguments.get("chars") or "")
            # local_process is the registered tool (process_manage is a Hermes name);
            # its ExecManager actions are poll / write / kill keyed by execution_id.
            action = "kill" if stop else ("write" if chars else "poll")
            mapped = {
                "action": action, "execution_id": str(arguments.get("session_id") or ""),
                "data": chars,
            }
            return await dispatch_alias("local_process", mapped)
        if name in {"TaskOutput", "TaskStop"}:
            execution_id = str(arguments.get("task_id") or arguments.get("taskId") or "")
            if not execution_id:
                return {"content": f"{name} requires task_id.", "is_error": True}
            if name == "TaskStop":
                return await dispatch_alias("local_process", {
                    "action": "cancel", "execution_id": execution_id,
                })
            return await dispatch_alias("local_process", {
                "action": "read", "execution_id": execution_id,
                "stream": arguments.get("stream", "stdout"),
                "offset": arguments.get("offset", 0),
                "limit": arguments.get("limit", 65536),
            })
        if name in {"git_pr_create", "git_pr_comment"}:
            approved_ids = getattr(runtime, "_preapproved_tool_call_ids", set())
            if call_id not in approved_ids:
                approval = getattr(runtime, "approval_callback", None)
                if not callable(approval):
                    return {"content": "GitHub write approval is unavailable in this run.", "is_error": True}
                approval_id = f"approval:{call_id or uuid.uuid4().hex}"
                await event_queue.put({
                    "type": "approval_required", "event_id": approval_id,
                    "tool_call_id": call_id, "name": name, "arguments": dict(arguments),
                })
                result = approval(approval_id, name, dict(arguments))
                if hasattr(result, "__await__"):
                    result = await result
                if result != "allow":
                    return {"content": "GitHub write was not approved.", "is_error": True, "outcome": "denied"}
            from atlas.tools.git_platform import comment_pull_request, create_pull_request

            workspace = str(getattr(runtime, "workspace", "") or "")
            try:
                if name == "git_pr_create":
                    data = await asyncio.to_thread(
                        create_pull_request, workspace,
                        title=str(arguments.get("title") or ""),
                        body=str(arguments.get("body") or ""),
                        base=arguments.get("base"), draft=bool(arguments.get("draft", False)),
                    )
                else:
                    data = await asyncio.to_thread(
                        comment_pull_request, workspace,
                        body=str(arguments.get("body") or ""),
                        pr_number=arguments.get("pr_number"),
                    )
            except (OSError, RuntimeError, ValueError, PermissionError) as exc:
                return {"content": str(exc), "is_error": True, "outcome": "failed"}
            return {"content": json.dumps(data, ensure_ascii=False), "data": data, "outcome": "completed"}
        if name.startswith(("android_", "ios_")):
            from atlas.tools.mobile_simulator import (
                MOBILE_MUTATING_TOOLS,
                call_mobile_tool,
            )

            if name in MOBILE_MUTATING_TOOLS:
                approved_ids = getattr(runtime, "_preapproved_tool_call_ids", set())
                if call_id not in approved_ids:
                    approval = getattr(runtime, "approval_callback", None)
                    if not callable(approval):
                        return {"content": "Mobile simulator write approval is unavailable in this run.",
                                "is_error": True, "outcome": "denied"}
                    approval_id = f"approval:{call_id or uuid.uuid4().hex}"
                    await event_queue.put({
                        "type": "approval_required", "event_id": approval_id,
                        "tool_call_id": call_id, "name": name, "arguments": dict(arguments),
                    })
                    result = approval(approval_id, name, dict(arguments))
                    if hasattr(result, "__await__"):
                        result = await result
                    if result != "allow":
                        return {"content": "Mobile simulator operation was not approved.",
                                "is_error": True, "outcome": "denied"}
            try:
                data = await call_mobile_tool(
                    name, arguments, str(getattr(runtime, "workspace", "") or ""),
                )
            except (OSError, RuntimeError, ValueError, PermissionError, TimeoutError) as exc:
                return {"content": str(exc), "is_error": True, "outcome": "failed"}
            if isinstance(data.get("content"), list):
                return {"content": data["content"], "data": data.get("data", {}),
                        "outcome": "completed"}
            return {"content": json.dumps(data, ensure_ascii=False, default=str),
                    "data": data, "outcome": "completed"}
        if name == "build_repo_map":
            workspace = str(getattr(runtime, "workspace", "") or "")
            if not workspace or workspace.startswith("ssh://"):
                return {"content": "RepoMap requires a local workspace path.", "is_error": True}
            from atlas.repomap import build_repo_map

            result = await asyncio.to_thread(
                build_repo_map,
                workspace,
                focus_files=list(arguments.get("focus_files") or []),
                mentioned=list(arguments.get("mentioned") or []),
                max_tokens=int(arguments.get("max_tokens", 2048)),
            )
            return {"content": result, "outcome": "completed"}
        if name == "workflow":
            from atlas.kernel.workflow_tool import execute_workflow_tool

            result = await execute_workflow_tool(
                agent,
                runtime,
                arguments,
                usage_callback=getattr(runtime, "workflow_usage_callback", None),
            )
            return {
                "content": json.dumps(result, ensure_ascii=False),
                "data": result,
                "outcome": "failed" if result.get("status") == "failed" else "completed",
            }

        from langchain_core.messages import AIMessage

        from atlas.agent import ToolExecutionState

        proxy = copy.copy(runtime)
        proxy.event_queue = event_queue
        proxy.exec_manager = None if nested else exec_manager
        inner_user_hook = getattr(proxy, "user_hook_callback", None)
        if callable(inner_user_hook):
            async def kernel_user_hook(event: str, payload: dict[str, Any]) -> Any:
                if event == "PostToolUseFailure":
                    return {}
                if event in {"tool.before", "tool.after"}:
                    payload = {**payload, "__atlas_bridge_event_alias__": False}
                result = inner_user_hook(event, payload)
                if asyncio.iscoroutine(result):
                    result = await result
                return result

            proxy.user_hook_callback = kernel_user_hook
        call_id = call_id or f"kernel:{uuid.uuid4().hex}"
        message = AIMessage(content="", tool_calls=[{
            "name": name, "args": dict(arguments), "id": call_id, "type": "tool_call",
        }])
        result = await agent._execute_tools_node(ToolExecutionState({
            "messages": [message], "pending_events": [], "runtime": proxy,
        }))
        events = result.get("pending_events", [])
        event = next((item for item in reversed(events)
                      if item.get("type") == "tool_result" and item.get("id") == call_id), None)
        if event is None:
            messages = result.get("messages", [])
            tool_message = next((item for item in messages
                                 if getattr(item, "tool_call_id", None) == call_id), None)
            if tool_message is None:
                return {"content": "Tool returned no result", "is_error": True}
            return {"content": str(tool_message.content),
                    "is_error": getattr(tool_message, "status", "") == "error"}
        content = "\n".join(
            str(block.get("text", block)) if isinstance(block, dict) else str(block)
            for block in event.get("content", [])
        )
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        return {
            "content": content, "is_error": bool(event.get("is_error")),
            "data": data,
            "output_ref": data.get("full_output_path") or data.get("output_ref"),
            "outcome": str(data.get("outcome") or data.get("state") or (
                "failed" if event.get("is_error") else "completed"
            )),
        }


def _tool_output_text(output: Any) -> str:
    if isinstance(output, dict):
        content = output.get("content")
        if isinstance(content, list):
            return "\n".join(
                str(block.get("text", block)) if isinstance(block, dict) else str(block)
                for block in content
            )
        if isinstance(content, str):
            return content
        if "error" in output:
            return str(output.get("error"))
        if "data" in output:
            return json.dumps(output["data"], ensure_ascii=False, default=str)
    return str(output or "")


def _tool_result_event_text(result: ToolExecutionResult) -> str:
    """Expose completion status without forwarding successful raw tool output."""
    state = result.receipt.state
    if state == "completed":
        return "Tool completed."
    if state == "cancelled":
        return "Tool cancelled."
    output = result.output
    detail = output.get("error") if isinstance(output, dict) else None
    if not isinstance(detail, str) or not detail.strip():
        detail = _tool_output_text(output)
    from atlas.logs import _summary

    safe_detail = _summary(str(detail), key="result")
    return str(safe_detail or "Tool failed.")
