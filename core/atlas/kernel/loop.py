# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276ede: apps/zcode-cli/packages/core/src/agent/turn-machine.ts (Apache-2.0)
# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/core/src/session/turn.rs (Apache-2.0)
# Behavior from Claude Code v2.1.296 docs: https://code.claude.com/docs/en/how-claude-code-works
# SPDX-License-Identifier: Apache-2.0
"""Atlas-owned asynchronous model, tool and recovery loop."""

from __future__ import annotations

import asyncio
import copy
import contextlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from atlas.kernel.context import ContextManager, estimate_tokens
from atlas.kernel.model_call import ModelCallError, ModelCallResult, complete_stream
from atlas.kernel.plan import PlanMode
from atlas.kernel.prompt import build_prompt
from atlas.kernel.repair import repair_unpaired_tool_calls, started_call_ids
from atlas.kernel.state import KernelEvent, RunPhase, RunState
from atlas.kernel.stuck import StuckDetector
from atlas.kernel.tools import ToolExecutionResult, ToolScheduler

log = logging.getLogger(__name__)


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
        receipts: list[dict[str, Any]] = []
        failure = ""
        log_path: Path | None = None
        exec_manager: ExecManager | None = None
        scheduler: ToolScheduler | None = None
        messages: list[dict[str, Any]] = []
        partial_response_text: list[str] = []
        active_call_ids: set[str] = set()
        open_call_ids: set[str] = set()

        from atlas.config import get_config
        from atlas.logs import LOG_DIR, append_run_event

        app_config = get_config()
        raw_config = dict(getattr(app_config, "raw", {}) or request.runtime_config)
        engine_config = dict(raw_config.get("engine", {}))
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

        def persist(role: str, content: Any, metadata: dict[str, Any] | None = None) -> None:
            from atlas.engine.session_sync import append_session_message

            append_session_message(self.data_dir / "engine", session_id, role, content, metadata)

        async def persist_async(role: str, content: Any, metadata: dict[str, Any] | None = None) -> None:
            await asyncio.to_thread(persist, role, content, metadata)

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
                from agent.plan_prompt import build_plan_prompt

                system_prompt = "\n\n".join(filter(None, (
                    system_prompt, build_plan_prompt(request.message),
                )))
            volatile = "\n\n".join(item.strip() for item in request.volatile_context if item.strip())
            if volatile:
                system_prompt = "\n\n".join(filter(None, (
                    system_prompt, "Atlas session-start context:\n" + volatile,
                )))
            from atlas.engine.hermes_runtime import _model_family_guidance

            system_prompt = "\n\n".join(filter(None, (
                system_prompt,
                "Model-family guidance: " + _model_family_guidance(selected_model),
            )))

            def assemble_prompt(items: list[dict[str, Any]]):
                return build_prompt(identity=system_prompt, history=items, rules="")

            prompt = assemble_prompt(history)
            messages = prompt.messages
            if request.lifecycle_hook_callback is not None:
                await request.lifecycle_hook_callback("SessionStart", {
                    "source": "startup", "conversation_id": session_id, "run_id": run_id,
                })

            plan = PlanMode(runtime, engine_config, plan_state=request.plan_state,
                            plan_update_callback=request.plan_update_callback,
                            todo_store=getattr(runtime, "todo_store", None))
            edit_manager = None
            if (request.workspace and not request.workspace.startswith("ssh://")
                    and getattr(agent, "_local_execution", None) is not None):
                from atlas.kernel.edit import EditManager

                edit_manager = EditManager(
                    request.workspace,
                    allowed_paths=(
                        [*getattr(runtime, "allowed_paths", []), request.workspace]
                        if getattr(runtime, "allowed_paths", None) else None
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
            tool_allow = getattr(runtime, "tool_allow", None)
            tool_deny = getattr(runtime, "tool_deny", [])

            async def dispatch_tool(call_id: str, name: str, args: dict[str, Any]) -> Any:
                active_call_ids.add(call_id)
                record("tool_start", tool_call_id=call_id, name=name, arguments=args)
                return await self._dispatch(
                    agent, proxy_runtime, call_id, name, args, event_queue,
                    exec_manager=exec_manager,
                )

            scheduler = ToolScheduler(
                dispatch_tool,
                max_concurrency=int(engine_config.get("tool_concurrency", 10)),
                allow=tool_allow, deny=tool_deny,
            )
            context_manager = ContextManager(raw_config, output_dir=run_dir / "compact-output")
            stuck = StuckDetector()
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

            proxy_runtime.kernel_usage_budget = usage_budget
            proxy_runtime.workflow_usage_callback = record_workflow_usage
            max_turns = max(1, min(int(engine_config.get("max_turns", 64)), 256))
            final_response = ""
            steer_target = _SteerTarget()
            steer_messages: list[str] = []
            pending_nudges: list[dict[str, str]] = []

            def queue_nudge(message: str) -> None:
                nudge = {"role": "system", "content": message}
                pending_nudges.append(nudge)
                messages.append(copy.deepcopy(nudge))

            async def apply_pending_steers() -> list[dict[str, Any]]:
                if not request.steer_queue:
                    return []
                from atlas.engine.steer_dispatch import apply_steer_payload
                accepted: list[dict[str, Any]] = []
                while not request.steer_queue.empty():
                    payload = request.steer_queue.get_nowait()
                    steer_target.messages.clear()
                    steer_target.redirected = False
                    outcome = apply_steer_payload(steer_target, payload)
                    if outcome.get("accepted"):
                        message = outcome["text"]
                        accepted.append({"content": message, **outcome,
                                         "event_id": payload.get("event_id", "")})
                return accepted

            for turn_index in range(max_turns):
                await _wait_until_resumed(pause_event, request.cancel_event)
                if request.cancel_event is not None and request.cancel_event.is_set():
                    raise asyncio.CancelledError
                for steer in await apply_pending_steers():
                    steer_messages.append(str(steer["content"]))
                    messages.append({"role": "user", "content": steer["content"]})
                    await persist_async("user", steer["content"], {
                        "kernel_run_id": run_id, "steered": True,
                    })
                    stuck.observe_message(str(steer["content"]), role="user")
                    yield emit("run_steered", content=steer["content"],
                               event_id=steer["event_id"], immediate=steer["immediate"],
                               send_now=steer["send_now"],
                               yield_requested=steer["yield_requested"])

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
                        max_retries=int(engine_config.get("model_retries", 2)),
                        fallback_models=list(getattr(runtime, "fallback_models", []) or []),
                        usage_budget=usage_budget,
                    )
                    usage_rows.append(_usage_row(result, uuid.uuid4().hex))
                    return result.text

                compaction_lease: dict[str, Any] = {"holder": None, "watermark": None}
                held_messages = copy.deepcopy(durable_history)

                async def before_compact(compaction: Any) -> None:
                    hook = await self._run_hook(request, "PreCompact", {
                        "trigger": "automatic", "conversation_id": session_id,
                        "before_tokens": compaction.before_tokens,
                        "after_tokens": compaction.after_tokens,
                    })
                    if hook.get("blocked"):
                        raise RuntimeError(str(hook.get("reason") or "Compaction blocked by hook"))
                    if compaction_lease["holder"] is None:
                        if not held_messages:
                            raise RuntimeError("Cannot compact without a canonical SessionDB history snapshot")
                        from atlas.engine.session_sync import begin_session_compaction

                        holder = f"atlas:{run_id}:{uuid.uuid4().hex}"
                        watermark = await asyncio.to_thread(
                            begin_session_compaction, self.data_dir / "engine", session_id, holder,
                        )
                        compaction_lease.update({"holder": holder, "watermark": watermark})

                try:
                    compaction = await context_manager.prepare(
                        messages, model_window=model_window, summarize=summarize,
                        preserved={"goal": request.message, "plan": plan.plan.to_dict() if plan.plan else None,
                                   "receipts": receipts},
                        focus=request.message,
                        # build_prompt has already placed the stable prefix in messages.
                        # Counting it separately would reserve the system prompt twice.
                        prefix_tokens=0,
                        before_compact=before_compact,
                    )
                except BaseException:
                    if compaction_lease["holder"]:
                        from atlas.engine.session_sync import abort_session_compaction

                        with contextlib.suppress(Exception):
                            await asyncio.to_thread(
                                abort_session_compaction, self.data_dir / "engine", session_id,
                                compaction_lease["holder"],
                            )
                    raise
                if compaction.method != "none":
                    holder = compaction_lease["holder"]
                    if not holder:
                        raise ModelCallError("compaction has no SessionDB lease", category="context_budget")
                    compacted_messages, tail_count, carried = _compaction_payload(
                        compaction.messages, held_messages,
                        synthetic_system_prompt=prompt.system_prompt,
                        method=compaction.method,
                    )
                    try:
                        from atlas.engine.session_sync import compact_session_messages

                        await asyncio.to_thread(
                            compact_session_messages, self.data_dir / "engine", session_id,
                            holder, int(compaction_lease["watermark"]), held_messages,
                            compacted_messages, tail_count=tail_count, carried_messages=carried,
                        )
                    except Exception as exc:
                        compaction_lease["holder"] = None  # commit helper releases its lease on failure
                        raise ModelCallError(
                            f"SessionDB compaction publication failed: {exc}",
                            category="context_budget",
                        ) from exc
                    compaction_lease["holder"] = None
                    transition(RunPhase.COMPACTING)
                    yield emit("run.compaction.progress", data={
                        "phase": compaction.method, "before_tokens": compaction.before_tokens,
                        "after_tokens": compaction.after_tokens,
                    })
                    messages = compaction.messages
                    record("compaction", method=compaction.method,
                           before_tokens=compaction.before_tokens, after_tokens=compaction.after_tokens,
                           budget_tokens=compaction.budget_tokens)
                    if request.lifecycle_hook_callback is not None:
                        await request.lifecycle_hook_callback("PostCompact", {
                            "trigger": "automatic", "conversation_id": session_id,
                            "before_tokens": compaction.before_tokens,
                            "after_tokens": compaction.after_tokens,
                        })
                    transition(RunPhase.STREAMING)
                elif compaction_lease["holder"]:
                    from atlas.engine.session_sync import abort_session_compaction

                    await asyncio.to_thread(
                        abort_session_compaction, self.data_dir / "engine", session_id,
                        compaction_lease["holder"],
                    )
                    compaction_lease["holder"] = None
                if compaction.error and compaction.after_tokens > compaction.budget_tokens:
                    raise ModelCallError(compaction.error, category="context_budget")

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
                    available_tools = [*available_tools, *edit_manager.get_tools_for_llm()]
                tools = plan.filter_tools(available_tools, read_only_names=("build_repo_map",))
                tool_json = json.dumps(messages, ensure_ascii=False, default=str)
                record("model_request", model=turn_model, input_chars=len(tool_json),
                       input_tokens=estimate_tokens(messages), attempt=turn_index + 1)
                transition(RunPhase.STREAMING)
                yield emit("run_status", status="running", text="Calling model")

                async def on_text(delta: str) -> None:
                    partial_response_text.append(delta)
                    yield_event = emit("chunk", content=delta)
                    # Async callback cannot yield from its parent generator; queue it
                    # for the loop's event pump.
                    await event_queue.put(yield_event)

                async def on_attempt(event: dict[str, Any]) -> None:
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
                        record("model_request", model=event.get("model"),
                               provider=event.get("provider"),
                               duration_ms=event.get("duration_ms"),
                               output_tokens=output_tokens, input_tokens=input_tokens,
                               cached_tokens=cached_tokens)
                    else:
                        record("model_error", model=event.get("model"),
                               provider=event.get("provider"), category=event.get("category"),
                               status=event.get("status"), retry=event.get("retry"),
                               attempt=event.get("attempt"))

                model_task = asyncio.create_task(complete_stream(
                    agent, turn_model, messages, tools,
                    reasoning_effort=turn_effort,
                    max_output_tokens=request.max_output_tokens,
                    cancel_event=request.cancel_event,
                    max_retries=int(engine_config.get("model_retries", 2)),
                    fallback_models=list(getattr(runtime, "fallback_models", []) or []),
                    on_text=on_text, on_attempt=on_attempt, usage_budget=usage_budget,
                ))
                queue_get = asyncio.create_task(event_queue.get())
                try:
                    while not model_task.done() or not event_queue.empty():
                        done, _ = await asyncio.wait(
                            {model_task, queue_get}, return_when=asyncio.FIRST_COMPLETED,
                        )
                        if queue_get in done:
                            yield queue_get.result()
                            queue_get = asyncio.create_task(event_queue.get())
                    response = await model_task
                except asyncio.CancelledError:
                    model_task.cancel()
                    await asyncio.gather(model_task, return_exceptions=True)
                    raise
                finally:
                    queue_get.cancel()
                    await asyncio.gather(queue_get, return_exceptions=True)

                pending_nudges.clear()
                usage = _usage_row(response, uuid.uuid4().hex)
                usage_rows.append(usage)
                state.response_text = response.text
                state.usage = usage
                stuck.observe_message(response.text)
                partial_response_text.clear()

                if not response.tool_calls:
                    final_response = response.text
                    if final_response:
                        await persist_async("assistant", final_response, {
                            "kernel_run_id": run_id, "finish_reason": "stop",
                        })
                    decision = stuck.check()
                    if decision and decision.action == "nudge":
                        queue_nudge(decision.message)
                        record("stuck", action=decision.action, reason=decision.reason)
                        yield emit("run.recovery.notice", data={"message": decision.message})
                        continue
                    break

                calls = response.tool_calls
                state.tool_calls = calls
                open_call_ids.update(str(call["id"]) for call in calls)
                assistant_message = {
                    "role": "assistant", "content": response.text,
                    "tool_calls": [_tool_call_for_history(call) for call in calls],
                }
                messages.append(assistant_message)
                await persist_async("assistant", response.text, {
                    "tool_calls": assistant_message["tool_calls"], "kernel_run_id": run_id,
                })
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
                tool_task = asyncio.create_task(scheduler.run(tool_calls_wire))
                queue_get = asyncio.create_task(event_queue.get())
                try:
                    while not tool_task.done() or not event_queue.empty():
                        done, _ = await asyncio.wait(
                            {tool_task, queue_get}, return_when=asyncio.FIRST_COMPLETED,
                        )
                        if queue_get in done:
                            yield queue_get.result()
                            queue_get = asyncio.create_task(event_queue.get())
                    results: list[ToolExecutionResult] = await tool_task
                except asyncio.CancelledError:
                    tool_task.cancel()
                    await asyncio.gather(tool_task, return_exceptions=True)
                    raise
                finally:
                    queue_get.cancel()
                    await asyncio.gather(queue_get, return_exceptions=True)

                for result in results:
                    receipt = result.receipt.as_dict()
                    receipts.append(receipt)
                    record("tool_end", tool_call_id=result.call_id, name=result.name,
                           state=receipt["state"], duration_ms=receipt["duration_ms"],
                           output_ref=receipt.get("output_ref"),
                           output=_tool_output_text(result.output))
                    content = _tool_output_text(result.output)
                    is_error = (
                        bool(isinstance(result.output, dict) and (
                            result.output.get("is_error")
                            or result.output.get("error")
                            or result.output.get("success") is False
                        ))
                        or receipt["state"] not in {"completed", "cancelled"}
                    )
                    messages.append({"role": "tool", "tool_call_id": result.call_id,
                                     "name": result.name, "content": content})
                    active_call_ids.discard(result.call_id)
                    open_call_ids.discard(result.call_id)
                    await persist_async("tool", content, {
                        "tool_call_id": result.call_id, "tool_name": result.name,
                        "kernel_run_id": run_id, "output_ref": receipt.get("output_ref"),
                    })
                    stuck.observe_tool(result.name, next(
                        (call["args"] for call in calls if call["id"] == result.call_id), {}
                    ), result.output, is_error=is_error)
                    event_text = _tool_result_event_text(result)
                    execution = {
                        "state": receipt["state"],
                        "duration_ms": receipt["duration_ms"],
                    }
                    yield emit(
                        "tool_result",
                        id=result.call_id,
                        name=result.name,
                        content=[{"type": "text", "text": event_text}],
                        data=execution,
                        is_error=is_error,
                        **({"error_category": "tool"} if is_error else {}),
                    )
                batch_hook = await self._run_hook(request, "PostToolBatch", {
                    "tool_uses": [{
                        "tool_use_id": result.call_id,
                        "tool_name": result.name,
                        "tool_input": next((call["args"] for call in calls
                                            if call["id"] == result.call_id), {}),
                        "tool_response": _tool_output_text(result.output)[:4000],
                    } for result in results],
                    "conversation_id": session_id, "run_id": run_id,
                })
                if batch_hook.get("blocked"):
                    raise RuntimeError(str(batch_hook.get("reason") or "Tool batch blocked by hook"))
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
                    steer_messages.append(str(steer["content"]))
                    messages.append({"role": "user", "content": steer["content"]})
                    await persist_async("user", steer["content"], {
                        "kernel_run_id": run_id, "steered": True,
                    })
                    stuck.observe_message(str(steer["content"]), role="user")
                    yield emit("run_steered", content=steer["content"],
                               event_id=steer["event_id"], immediate=steer["immediate"],
                               send_now=steer["send_now"],
                               yield_requested=steer["yield_requested"])
            else:
                raise RuntimeError(f"Kernel reached its {max_turns}-turn limit")

            transition(RunPhase.DONE)
            elapsed = int((time.monotonic() - started_at) * 1000)
            record("run_end", status="completed",
                   duration_ms=elapsed, total_input_tokens=sum(int(row.get("input_tokens") or 0) for row in usage_rows),
                   total_output_tokens=sum(int(row.get("output_tokens") or 0) for row in usage_rows))
            await self._run_hook(request, "Stop", {"conversation_id": session_id,
                                                      "stop_hook_active": False})
            yield emit("hermes.result", result={"final_response": final_response,
                                                "usage": usage_rows})
        except asyncio.CancelledError:
            if state.phase not in {RunPhase.DONE, RunPhase.FAILED, RunPhase.INTERRUPTED}:
                transition(RunPhase.INTERRUPTED)
            try:
                if partial_response_text:
                    partial = "".join(partial_response_text)
                    await persist_async("assistant", partial, {
                        "kernel_run_id": run_id, "finish_reason": "interrupted",
                    })
                    record("repair", state="partial_response_preserved",
                           output_length=len(partial))
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
            log.exception("kernel.run_failed", extra={"run_id": run_id, "session_id": session_id})
            record("run_end", status="failed", duration_ms=int((time.monotonic() - started_at) * 1000),
                   total_input_tokens=sum(int(row.get("input_tokens") or 0) for row in usage_rows),
                   total_output_tokens=sum(int(row.get("output_tokens") or 0) for row in usage_rows),
                   reason=failure)
            try:
                await self._run_hook(request, "StopFailure", {
                    "error_type": type(exc).__name__, "error": failure,
                    "conversation_id": session_id, "run_id": run_id,
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
