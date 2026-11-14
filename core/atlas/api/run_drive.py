"""Run assembly and drive loop + W10 service callbacks, extracted from ``atlas.server`` (H5 A9).

Mechanical move (behavior-preserving): run-start/resume/trust handlers, the
``_execute_run`` drive loop, scheduler-goal callbacks, telegram/heartbeat/
automation/group seams. Every name that still lives in the ``atlas.server``
module namespace (service singletons and the helpers tests monkeypatch) is
resolved through ``_server()`` at call time, so late binding — and therefore
existing monkeypatch seams and ``from atlas.server import X`` imports — keep
working unchanged.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import secrets
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import structlog
from fastapi import HTTPException, Request

from atlas.api.runtime import RunState, RuntimeManager
from atlas.approval_policy import PERMISSION_PRESETS
from atlas.approval_policy import is_allowed as approval_always_allowed
from atlas.approval_policy import permission_scope as approval_permission_scope
from atlas.automation import AutomationEngine
from atlas.channels import ChannelManager
from atlas.config import get_config
from atlas.groups import DispatcherNotBound, TurnConflict
from atlas.persistent_agents import PersistentAgentService
from atlas.runtime.commands import CommandSource
from atlas.runtime.external_agents import normalize_external_event
from atlas.runtime.hooks import HookStore
from atlas.scheduler import ScheduledTask, TaskStatus
from atlas.session_projections import SessionProjections
from atlas.skills import SkillManager, plugin_skill_sources
from atlas.skills.registry import SkillRegistry
from atlas.ssh import ssh_workspaces
from atlas.task_artifacts import TomlRecordStore, WorktreeService, seed_profiles
from atlas.telegram import TelegramService
from atlas.usage import aggregate_run_usage

log = structlog.get_logger()

# Strong references to fire-and-forget tasks so the event loop cannot
# garbage-collect them mid-flight; each task drops itself on completion (RUF006).
_background_tasks: set[asyncio.Task[Any]] = set()


def _spawn_background(coro: Any) -> asyncio.Task[Any]:
    """Schedule ``coro`` and keep it alive until it finishes."""
    task = asyncio.get_running_loop().create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def _server() -> Any:
    """Late-bound ``atlas.server``: its module globals stay the seam tests patch."""
    import atlas.server

    return atlas.server


def _task_store(kind: str) -> TomlRecordStore:
    return TomlRecordStore(get_config().db_path.parent, kind)


def _resolve_permission_policy(data: dict[str, Any]) -> dict[str, Any]:
    """Resolve a preset across permission, sandbox and approval dimensions."""
    from atlas.approval_policy import preset, preset_for_policy

    named = preset(data.get("permission_preset")) if data.get("permission_preset") is not None else None
    permission_mode = data.get("permission_mode")
    sandbox_mode = data.get("sandbox_mode")
    approval_policy = data.get("approval_policy")
    if named is not None:
        permission_mode = permission_mode if permission_mode is not None else named["mode"]
        sandbox_mode = sandbox_mode if sandbox_mode is not None else named["sandbox_mode"]
        approval_policy = approval_policy if approval_policy is not None else named["approval_policy"]
    if approval_policy is not None and approval_policy not in {"ask", "never"}:
        raise ValueError("approval_policy must be 'ask' or 'never'")
    if sandbox_mode is not None and sandbox_mode not in {
        "read-only", "workspace-write", "danger-full-access",
    }:
        raise ValueError("sandbox_mode must be read-only, workspace-write, or danger-full-access")
    resolved = preset_for_policy(
        permission_mode=permission_mode,
        sandbox_mode=sandbox_mode,
        approval_policy=approval_policy,
    )
    return resolved


def _requested_tool_mode(data: dict[str, Any]) -> str:
    """Validate the per-run tool transport mode before assembling a run."""
    tool_mode = data.get("tool_mode", "native")
    if not isinstance(tool_mode, str) or tool_mode not in {"native", "ptc"}:
        raise ValueError("tool_mode must be 'native' or 'ptc'")
    return tool_mode


def _restore_permission_policy(run: RunState, context: dict[str, Any]) -> None:
    """Restore the independent permission dimensions for an interrupted run."""
    run.sandbox_mode = context.get("sandbox_mode") or run.sandbox_mode
    run.approval_policy = context.get("approval_policy") or run.approval_policy
    run.permission_preset = context.get("permission_preset") or run.permission_preset


async def _session_messages(conversation_id: str, limit: int = 1000) -> list[dict[str, Any]]:
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import read_session_messages

    return await asyncio.to_thread(
        read_session_messages, DATA_ROOT / "engine", conversation_id, limit=limit,
    )


async def _persist_approval_lifecycle(
    conversation_id: str, event_type: str, payload: dict[str, Any],
) -> None:
    """Commit approval state in the append-only session event log."""
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import append_session_event

    await asyncio.to_thread(
        append_session_event, DATA_ROOT / "engine", conversation_id, event_type, payload,
    )


async def _capture_evolution_outcome(run: RunState, event: str) -> None:
    """Record terminal outcome; successful runs become pending skill candidates."""
    from atlas.evolution.run_learning import record_terminal_run, transcript_excerpt

    user_text = str(getattr(run, "user_input", "") or "")
    assistant_text = ""
    if event == "run.completed":
        try:
            messages = await _session_messages(run.conversation_id, limit=500)
            transcript_user, assistant_text = transcript_excerpt(messages, run.run_id)
            user_text = user_text or transcript_user
            if not assistant_text:
                assistant_text = next((str(env.get("data", {}).get("content") or "").strip()
                                       for env in reversed(run.events)
                                       if env.get("event") == "message.completed"
                                       and str(env.get("data", {}).get("content") or "").strip()), "")
        except Exception:
            log.exception("evolution.run_transcript_read_failed", run_id=run.run_id)
    try:
        await asyncio.to_thread(
            record_terminal_run, run_id=run.run_id,
            conversation_id=run.conversation_id,
            status=event.removeprefix("run."), project_id=getattr(run, "project_id", None),
            agent_id=getattr(run, "agent_id", None), user_text=user_text,
            assistant_text=assistant_text,
        )
    except Exception:
        # Learning is best-effort and must never turn a finished run into failure.
        log.exception("evolution.run_outcome_capture_failed", run_id=run.run_id,
                      status=event.removeprefix("run."))


async def _resolve_project_skill_scope(
    data: dict[str, Any], manager: RuntimeManager, projects: Any, *,
    ignore_project_config: bool,
) -> tuple[str | None, list[str]]:
    """Resolve explicit/project-linked Skills for one run, honoring config opt-out."""
    project_id = str(data.get("project_id") or "").strip() or None
    conversation_id = str(data.get("conversation_id") or "").strip()
    if not conversation_id and data.get("resume_from"):
        prior = manager.runs.get(str(data.get("resume_from")))
        conversation_id = str(getattr(prior, "conversation_id", "") or "")
    if not project_id and conversation_id and projects is not None:
        try:
            project = await projects.find_by_conversation(conversation_id)
            project_id = str(getattr(project, "project_id", "") or "") or None
        except Exception:
            log.exception("run.project_skill_scope_lookup_failed", conversation_id=conversation_id)
    names: list[str] = []
    if project_id and not ignore_project_config:
        try:
            from atlas.project_settings import load_project_config

            configured = load_project_config(project_id).get("active_skills", [])
            if isinstance(configured, list):
                names = list(dict.fromkeys(
                    name.strip() for name in configured
                    if isinstance(name, str) and name.strip()))
        except (OSError, ValueError):
            log.exception("run.project_skills_unavailable", project_id=project_id)
    return project_id, names


def _kanban_store():
    from atlas.kanban import atlas_kanban_store

    return atlas_kanban_store()


def _profile_store() -> TomlRecordStore:
    store = _server()._task_store("profiles")
    seed_profiles(store)
    return store


def _owns_scheduler_lease() -> bool:
    if _server().scheduler is None:
        return False
    try:
        lease = json.loads(_server().scheduler._lease_path.read_text(encoding="utf-8"))
        return lease.get("token") == _server().scheduler._lease_token
    except (OSError, ValueError, TypeError):
        return False


async def _telegram_submit_task(text: str, user_id: int, service: TelegramService) -> dict[str, str]:
    if _server().memory is None:
        raise RuntimeError("Atlas 资料服务尚未就绪。")
    settings = service.settings()
    title = (text.strip()[:30] or "手机任务").strip()
    conversation_id = await _server().memory.create_conversation(title)
    await _server().memory.update_conversation(
        conversation_id, workspace=settings["default_workspace"] or None,
        permission_mode="full_access", source="telegram",
    )
    run_id = uuid.uuid4().hex
    await _server()._handle_run_start("telegram", {
        "run_id": run_id, "conversation_id": conversation_id, "content": text,
        "workspace": settings["default_workspace"] or None,
        "permission_mode": "full_access", "telegram_user_id": user_id,
    })
    run = _server().runtime_mgr.runs.get(run_id)
    if run is None or run.task is None:
        raise RuntimeError("任务没有成功启动。")
    await run.task
    messages = await _session_messages(conversation_id)
    answer = next((item["content"] for item in reversed(messages)
                   if item["role"] == "assistant"), "")
    summary = str(answer)[:1500]
    if run.status == "failed":
        failed = next((env.get("data", {}).get("detail", "") for env in reversed(run.events)
                       if env.get("event") == "run.failed"), "任务执行失败。")
        raise RuntimeError(str(failed))
    if run.status == "cancelled":
        raise RuntimeError("任务已停止。")
    changes = _server()._run_change_summary(run_id)
    return {"conversation_id": conversation_id, "run_id": run_id,
            "summary": f"{summary}\n\n改动文件数：{changes['files']}"}


async def _telegram_command(command: str, user_id: int) -> str:
    del user_id
    if _server().memory is None:
        return "Atlas 资料服务尚未就绪。"
    name = command.split(maxsplit=1)[0].split("@", 1)[0].casefold()
    conversations = [item for item in await _server().memory.list_conversations(limit=100)
                     if item.get("source") == "telegram"]
    runs = {run.conversation_id: run for run in _server().runtime_mgr.runs.values()
            if run.status in {"running", "waiting", "paused"}}
    if name == "/list":
        if not conversations:
            return "还没有手机任务。"
        return "\n".join(
            f"{item['title']} · {(runs.get(item['id']).status if item['id'] in runs else '已结束')}"
            for item in conversations[:5]
        )
    current = next((item for item in conversations if item["id"] in runs), None)
    if name == "/status":
        return f"正在运行：{current['title']}" if current else "目前没有运行中的任务。"
    if name == "/stop":
        if current is None:
            return "目前没有可停止的任务。"
        runs[current["id"]].cancel_event.set()
        return f"已请求停止：{current['title']}"
    return "可用命令：/list、/stop、/status"


def _worktrees() -> WorktreeService:
    return WorktreeService(get_config().db_path.parent)


def _default_workspace() -> Path | None:
    """The user-configured default workspace, if any (workspace-level sources)."""
    value = _server().load_user_settings().get("default_workspace")
    return Path(str(value)).expanduser() if value else None


def _require_skill_center_authority(request: Request) -> None:
    supplied = request.headers.get("x-atlas-skill-center-token", "")
    origin = request.headers.get("origin")
    trusted_origin = origin in {
        "null", "http://127.0.0.1:5173", "http://localhost:5173",
        "http://127.0.0.1:4173", "http://localhost:4173",
    }
    if (not _server().SKILL_CENTER_TOKEN or not supplied
            or not secrets.compare_digest(supplied, _server().SKILL_CENTER_TOKEN) or not trusted_origin):
        raise HTTPException(status_code=403, detail="trusted Skill Center decision is required")


def _register_local_skills(skill_manager: SkillManager, registry: SkillRegistry) -> None:
    """Register local Skills with their canonical dependency contract."""
    for skill in skill_manager.list_skills():
        if registry.get(skill.name, skill.version) is not None:
            continue
        registry.register({
            "name": skill.name,
            "version": skill.version,
            "description": skill.description,
            "capabilities": [],
            "tools": [],
            "requirements": skill.dependency_contract,
            "examples": [],
            "aliases": [],
            "tags": skill.tags,
            "category": skill.category,
            "keywords": skill.tags,
            "use_cases": [],
        }, source="local")


async def _durable_dispatcher(payload: dict[str, Any]) -> dict[str, Any]:
    """Bridge a durable workflow step back onto the live server runtime."""
    task_id = str(payload.get("task_id", ""))
    message = str(payload.get("message", ""))
    await _server()._run_scheduled_goal(task_id, message)
    return {"status": "completed", "task_id": task_id}


async def _scheduled_goal(task_id: str, message: str) -> None:
    """Durable-first scheduler callback with direct fallback and user notify."""
    if _server().durable is not None and _server().durable.started:
        try:
            await _server().durable.run_agent_task({"task_id": task_id, "message": message})
            if _server().notifications is not None:
                await _server().notifications.notify(
                    "Atlas task finished",
                    f"Scheduled task {task_id} completed. Message: {message[:200]}",
                )
            return
        except Exception as exc:
            log.exception("durable.agent_task_failed", task_id=task_id)
            if _server().notifications is not None:
                await _server().notifications.notify(
                    "Atlas task failed",
                    f"Scheduled task {task_id} failed: {str(exc)[:300]}",
                )
    await _server()._run_scheduled_goal(task_id, message)


_goal_run_locks: dict[str, asyncio.Lock] = {}


def _goal_session_id(task_id: str) -> str:
    return f"scheduled-goal-{task_id}"


async def _ensure_goal_migrated(task: ScheduledTask) -> None:
    """Import a pre-C3R schedule objective into the engine once, then discard its copy."""
    if not task.legacy_goal:
        return
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import goal_state, mutate_goal, record_goal_event, set_goal

    session_id = _server()._goal_session_id(task.id)
    home = DATA_ROOT / "engine"
    state = await asyncio.to_thread(goal_state, home, session_id)
    if state is None:
        await asyncio.to_thread(set_goal, home, session_id, task.legacy_goal)
        legacy_status = task.legacy_goal_status.strip().casefold()
        legacy_reason = task.legacy_goal_reason.strip()
        if legacy_status == "completed":
            await asyncio.to_thread(
                mutate_goal, home, session_id, "done",
                legacy_reason or "Migrated completed legacy goal.",
            )
        elif (
            legacy_status in {"blocked", "awaiting_approval", "paused"}
            or task.status == TaskStatus.PAUSED
        ):
            await asyncio.to_thread(
                mutate_goal, home, session_id, "pause",
                legacy_reason or f"legacy schedule {legacy_status or 'paused'}",
            )
        await asyncio.to_thread(record_goal_event, home, session_id, "goal.created", {"migrated": True})
    task.legacy_goal = ""
    task.legacy_goal_status = ""
    task.legacy_goal_reason = ""
    await _server().scheduler.update_task(task.id, action="goal", status=TaskStatus.ACTIVE)


async def _run_scheduled_goal(task_id: str, message: str = "") -> None:
    """Run a scheduled goal using the engine GoalManager as its only lifecycle authority."""
    del message
    if _server().scheduler is None:
        return
    task = _server().scheduler.get_task(task_id)
    if task is None:
        return
    await _server()._ensure_goal_migrated(task)

    session_id = _server()._goal_session_id(task_id)
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import (
        evaluate_goal_after_turn,
        goal_state,
        mutate_goal,
        record_goal_event,
    )
    home = DATA_ROOT / "engine"
    if _server().orchestrator is None:
        state = await asyncio.to_thread(goal_state, home, session_id)
        detail = "Agent orchestrator is unavailable."
        await asyncio.to_thread(record_goal_event, home, session_id, "execution.error", {"detail": detail})
        await asyncio.to_thread(mutate_goal, home, session_id, "pause", detail)
        return
    lock = _goal_run_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        active_objective = ""
        prompt = ""
        await asyncio.to_thread(record_goal_event, home, session_id, "goal.triggered")
        while True:
            state = await asyncio.to_thread(goal_state, home, session_id)
            if not state or state.get("status") != "active":
                return
            objective = str(state.get("goal") or "").strip()
            if not objective:
                return
            if objective != active_objective:
                active_objective = objective
                prompt = objective
            response: list[str] = []
            failed = False
            failure_detail = ""
            run_id = uuid.uuid4().hex
            message_id = ""

            async def deny_unapproved(_event_id: str, _tool_name: str, _payload: dict[str, Any]) -> str:
                return "deny"

            try:
                async for event in _server().orchestrator.run(
                    message=prompt,
                    conversation_id=session_id,
                    approval_callback=deny_unapproved,
                    source_run_id=run_id,
                ):
                    event_type = event.get("type")
                    if event_type == "error":
                        failed = True
                        failure_detail = str(event.get("detail") or "Goal execution failed.")
                        break
                    if event_type == "chunk":
                        piece = event.get("content", "")
                        if isinstance(piece, str):
                            response.append(piece)
                    elif event_type in {"token", "text", "response_delta"}:
                        piece = event.get("content", event.get("text", event.get("delta", "")))
                        if isinstance(piece, str):
                            response.append(piece)
                    if event_type == "done":
                        message_id = str(event.get("message_id") or "")
            except Exception:
                log.exception("goal.execution_failed")
                failed = True
                failure_detail = "Goal execution raised an exception."
            if failed:
                await asyncio.to_thread(record_goal_event, home, session_id, "execution.error", {
                    "detail": failure_detail,
                }, run_id)
                await asyncio.to_thread(
                    mutate_goal, home, session_id, "pause", failure_detail,
                )
                return

            # Reload before evaluating: pause, clear, or replace may have happened while the
            # model was running. Never apply an old response to a replacement goal.
            if not response and _server().memory is not None and message_id:
                messages = await _session_messages(session_id)
                saved = next((item.get("content", "") for item in reversed(messages)
                              if item.get("id") == message_id and item.get("role") == "assistant"), "")
                if isinstance(saved, str):
                    response.append(saved)
            current = await asyncio.to_thread(goal_state, home, session_id)
            if not current or current.get("status") != "active":
                return
            if current.get("goal") != objective:
                continue
            decision = await asyncio.to_thread(
                evaluate_goal_after_turn, home, session_id, "".join(response),
                _atlas_goal_judge(_server().model_mgr),
            )
            await asyncio.to_thread(record_goal_event, home, session_id, "goal.evaluated", {
                "verdict": decision.get("verdict"),
                "reason": decision.get("reason", ""),
                "status": decision.get("status"),
            }, run_id)
            if decision.get("planning_turn"):
                await asyncio.to_thread(record_goal_event, home, session_id, "goal.planning_turn", {
                    "attempt": decision.get("plan_attempts"),
                    "max_attempts": decision.get("max_plan_attempts"),
                    "milestones": decision.get("milestones", 0),
                    "expiring": decision.get("plan_gate_expiring", False),
                }, run_id)
            if decision.get("verdict") == "blocked":
                return
            if not decision.get("should_continue"):
                return
            prompt = decision.get("continuation_prompt") or objective


def _agent_service() -> PersistentAgentService:
    """The lifespan-injected persistent-agent singleton (router accessor)."""
    from atlas.api.agent_router import get_agent_service

    return get_agent_service()


def _atlas_goal_judge(model_manager: Any):
    """Return a conservative goal judge backed by Atlas' routed model API."""
    if model_manager is None or getattr(model_manager, "model_router", None) is None:
        # No model wiring yet (e.g. before lifespan, or in an isolated test app).
        # Returning None makes this an explicitly unwired judge, so the goal layer
        # reports "judge_unavailable" instead of dying on an AttributeError.
        return None

    def judge(goal: str, response: str, state: Any) -> tuple[str, str]:
        contract = state.contract.render_block() if state.has_contract() else "(no completion contract)"
        prompt = (
            "Determine whether the user's goal is fully complete based only on the assistant's "
            "latest turn and the completion contract. Return one JSON object with keys verdict "
            "(done, continue, or blocked) and reason. Use done only when the requested outcome "
            "is demonstrably achieved; use blocked only for a real blocker; otherwise use continue.\n\n"
            f"GOAL:\n{goal[:4000]}\n\nCONTRACT:\n{contract[:4000]}\n\n"
            f"LATEST TURN:\n{response[-10000:]}"
        )
        result = asyncio.run(model_manager.model_router.complete_for(
            model_manager.current_model, "goal_judge",
            [{"role": "user", "content": prompt}], max_tokens=300,
        ))
        text = str(result.text or "")
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return "continue", "Goal judge returned no valid JSON verdict."
        try:
            verdict_data = json.loads(text[start:end + 1])
        except (TypeError, ValueError):
            return "continue", "Goal judge returned malformed JSON."
        verdict = str(verdict_data.get("verdict") or "").strip().lower()
        if verdict not in {"done", "continue", "blocked"}:
            return "continue", "Goal judge returned an unknown verdict."
        return verdict, str(verdict_data.get("reason") or "")[:1000]

    return judge


def _resolve_agent_for_run(agent_id: str) -> dict[str, Any] | None:
    """agent_id → run-start merge config; ``None`` = unknown / not persistent."""
    try:
        return _server()._agent_service().resolve_agent_run_config(agent_id)
    except KeyError:
        return None


def _set_agent_status_quiet(agent_id: str, status: str, error: str = "") -> None:
    """Persistent-agent status projection that never breaks a run."""
    try:
        _server()._agent_service().set_status(agent_id, status, error)
    except Exception:  # projection is best-effort
        log.exception("agent.status_projection_failed", agent_id=agent_id)


def _channel_agent_profile(agent_id: str) -> dict[str, Any] | None:
    """Agent profile for the gateway's permission-mode ladder (binding → profile → default)."""
    try:
        return _server()._agent_service().get(agent_id)
    except sqlite3.Error:  # unreadable profile store → ladder falls back to defaults
        return None


def _sync_channel_routing(agents_service: PersistentAgentService, manager: ChannelManager) -> None:
    """Project per-agent channel bindings onto the gateway routing table."""
    roster = agents_service.list_agents(include_roles=False)
    bindings: list[dict[str, Any]] = []
    for record in roster:
        for row in (record.get("agent") or {}).get("channels") or []:
            binding = {
                "agent_id": str(record["id"]),
                "channel": str(row.get("channel", "")),
                "account": str(row.get("account", "")),
                "peer_id": str(row.get("target", "")),
                "mention_names": list(dict.fromkeys([
                    str(name) for name in (row.get("mention_names") or []) if str(name).strip()
                ] + [str(record["id"]), str((record.get("agent") or {}).get("name") or "")])),
            }
            # H7 §9.1: per-binding permission-mode override (validated by the
            # profile store; routing ignores unknown keys — behavior-neutral).
            if row.get("permission_mode"):
                binding["permission_mode"] = str(row["permission_mode"])
            bindings.append(binding)
    manager.set_bindings(bindings)
    manager.set_agent_ids([str(record["id"]) for record in roster])


class _AtlasHeartbeatHost:
    """HeartbeatHost port backed by live Atlas services (W10 wiring)."""

    def get_heartbeat_config(self, agent_id: str) -> dict:
        try:
            return _server()._agent_service().get_heartbeat(agent_id)
        except KeyError:
            return {}  # unknown agent → disabled default (HeartbeatService merges)

    def is_agent_busy(self, agent_id: str) -> bool:
        try:
            return _server()._agent_service().get_status(agent_id)["status"] == "working"
        except KeyError:
            return False

    async def dispatch_heartbeat_turn(self, agent_id: str, prompt: str, session: str) -> str:
        return await _server()._collect_orchestrator_text(prompt, session)

    def deliver(self, agent_id: str, text: str, target: str) -> None:
        del agent_id
        asyncio.get_running_loop().create_task(_deliver_agent_notification(text, target))

    @staticmethod
    def now() -> float:
        return time.time()


async def _deliver_agent_notification(text: str, target: str) -> None:
    """Heartbeat delivery: ``owner`` → apprise, ``<channel:target>`` → gateway."""
    target = (target or "").strip()
    if not text:
        return
    if target == "owner" or ":" not in target:
        if _server().notifications is not None:
            await _server().notifications.notify("Atlas heartbeat", text)
        return
    channel, _, chat_id = target.partition(":")
    if _server().channel_manager is None:
        return
    try:
        await _server().channel_manager.send(channel, chat_id, text)
    except Exception:  # delivery failure must not crash the tick
        log.exception("heartbeat.channel_delivery_failed", channel=channel)


async def _collect_orchestrator_text(
    message: str, conversation_id: str, *,
    model: str | None = None,
    reasoning_effort: str | None = None,
    workspace: str | None = None,
    active_skill_instructions: list[dict[str, str]] | None = None,
    agent_preset_id: str = "default",
    permission_preset: str = "ask",
    agent_preset_capabilities: dict[str, Any] | None = None,
    mode: str = "act",
    mode_explicit: bool = False,
) -> str:
    """One unattended orchestrator turn (heartbeat / automation / group); assistant text."""
    if _server().orchestrator is None:
        raise RuntimeError("Agent orchestrator 尚未就绪")

    async def deny_unapproved(_event_id: str, _tool_name: str, _payload: dict[str, Any]) -> str:
        return "deny"

    response: list[str] = []
    message_id = ""
    async for event in _server().orchestrator.run(
        message=message,
        conversation_id=conversation_id,
        model=model,
        reasoning_effort=reasoning_effort,
        approval_callback=deny_unapproved,
        source_run_id=uuid.uuid4().hex,
        active_skill_instructions=active_skill_instructions,
        workspace=workspace,
        agent_preset_id=agent_preset_id,
        permission_preset=permission_preset,
        agent_preset_capabilities=agent_preset_capabilities,
        mode=mode,
        mode_explicit=mode_explicit,
    ):
        event_type = event.get("type")
        if event_type == "error":
            raise RuntimeError(str(event.get("detail") or "orchestrator turn failed"))
        if event_type == "chunk":
            piece = event.get("content", "")
            if isinstance(piece, str):
                response.append(piece)
        elif event_type in {"token", "text", "response_delta"}:
            piece = event.get("content", event.get("text", event.get("delta", "")))
            if isinstance(piece, str):
                response.append(piece)
        elif event_type == "done":
            message_id = str(event.get("message_id") or "")
    if not response and message_id and _server().memory is not None:
        # Same fallback as _run_scheduled_goal: a turn that produced no streamed
        # chunks still has its saved assistant message (heartbeat/automation
        # outcomes depend on the model text, not on streaming behaviour).
        messages = await _session_messages(conversation_id)
        saved = next((item.get("content", "") for item in reversed(messages)
                      if item.get("id") == message_id and item.get("role") == "assistant"), "")
        if isinstance(saved, str):
            response.append(saved)
    return "".join(response)


async def _automation_heartbeat_tick(agent_id: str, reason: str) -> Any:
    """Automation ``payload.kind=heartbeat`` → HeartbeatService.tick (W3↔W4 seam)."""
    if _server().heartbeat_service is None:
        raise RuntimeError("heartbeat service 尚未就绪")
    return await _server().heartbeat_service.tick(agent_id, reason)


async def _automation_dispatch_turn(payload: dict[str, Any]) -> dict[str, str]:
    """Automation ``payload.kind=agent_turn`` → orchestrator turn in its target conversation."""
    automation_id = str(payload.get("automation_id") or "adhoc")
    conversation_id = str(payload.get("conversation_id") or f"automation-{automation_id}")
    agent_id = str(payload.get("agent_id") or "").strip()
    model = str(payload.get("model") or "").strip() or None
    reasoning_effort = str(payload.get("reasoning_effort") or "").strip() or None
    agent_preset_id = str(payload.get("agent_preset_id") or "default").strip()
    permission_preset = str(payload.get("permission_preset") or "ask").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", agent_preset_id):
        raise ValueError("payload.agent_preset_id must be a valid preset ID")
    if permission_preset not in PERMISSION_PRESETS:
        raise ValueError("payload.permission_preset must be a known permission preset")
    from atlas.task_artifacts import AgentPresetStore

    preset_store = AgentPresetStore(get_config().db_path.parent)
    capabilities = preset_store.resolve(agent_preset_id)
    if "mode" in payload:
        mode = str(payload.get("mode") or "").strip()
        if mode not in {"act", "plan"}:
            raise ValueError("payload.mode must be act or plan")
        mode_explicit = True
    else:
        mode = str(capabilities.get("mode") or "act")
        mode_explicit = False
    preset_model = str(capabilities.get("model") or "inherit").strip()
    if model is None and preset_model.lower() != "inherit":
        model = preset_model
    app = getattr(_server(), "app", None)
    services = getattr(getattr(app, "state", None), "services", None)
    agents = getattr(services, "persistent_agents", None)
    if agent_id and agents is not None:
        # Explicit automation choices win; otherwise honor the selected Agent profile.
        config = agents.resolve_agent_run_config(agent_id)
        model = model or config.get("model") or None
        reasoning_effort = reasoning_effort or config.get("reasoning_effort") or None
    preset_skills = capabilities.get("skills")
    requested_skills = payload.get("skills")
    skills = list(dict.fromkeys([
        *([str(skill) for skill in preset_skills] if isinstance(preset_skills, list) else []),
        *([str(skill) for skill in requested_skills] if isinstance(requested_skills, list) else []),
    ]))
    skill_instructions = await _server()._resolve_active_skill_instructions(skills) if skills else []
    text = await _server()._collect_orchestrator_text(
        str(payload.get("message") or ""), conversation_id,
        model=model,
        reasoning_effort=reasoning_effort,
        workspace=str(payload.get("workspace") or "") or None,
        agent_preset_id=agent_preset_id,
        permission_preset=permission_preset,
        agent_preset_capabilities=capabilities,
        mode=mode,
        mode_explicit=mode_explicit,
        active_skill_instructions=skill_instructions,
    )
    return {"text": text, "conversation_id": conversation_id}


async def _automation_deliver(record: dict[str, Any], outcome: dict[str, Any]) -> bool:
    """Automation delivery: owner → apprise, channel → gateway (§4 delivery spec)."""
    result = outcome.get("result")
    text = str((result.get("text") or "") if isinstance(result, dict) else result or "").strip()
    if not text:
        return False
    delivery = record.get("delivery") or {}
    channel = str(delivery.get("channel") or "").strip()
    target = str(delivery.get("target") or "").strip()
    if channel in ("", "owner", "notification"):
        if _server().notifications is None:
            return False
        is_reminder = str(record.get("name") or "").startswith("提醒：")
        await _server().notifications.notify("Atlas 提醒" if is_reminder else "Atlas automation", text)
        return True
    if _server().channel_manager is None or not target:
        return False
    await _server().channel_manager.send(channel, target, text)
    return True


def _heartbeat_automation_current(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
    """True when the stored heartbeat automation already matches the desired shape."""
    return (
        bool(existing.get("enabled"))
        and existing.get("owner_agent_id") == desired["owner_agent_id"]
        and (existing.get("trigger") or {}).get("kind") == "interval"
        and abs(float((existing.get("trigger") or {}).get("every_seconds") or 0)
                - float(desired["trigger"]["every_seconds"])) < 0.5
        and (existing.get("payload") or {}).get("kind") == "heartbeat"
        and (existing.get("payload") or {}).get("agent_id") == desired["payload"]["agent_id"]
        and (existing.get("delivery") or {}).get("mode") == "none"
    )


async def _reconcile_agent_heartbeats(
    agents_service: PersistentAgentService, engine: AutomationEngine,
) -> None:
    """Idempotent W1↔W4 reconcile: one ``heartbeat-<agent_id>`` automation per agent.

    heartbeat.enabled → upsert (interval = interval_minutes·60s, payload
    kind=heartbeat, delivery=none — the heartbeat sends its own notifications);
    heartbeat off → delete the automation when present.
    """
    for record in agents_service.list_agents(include_roles=False):
        agent_id = str(record.get("id") or "")
        if not agent_id:
            continue
        automation_id = f"heartbeat-{agent_id}"
        heartbeat = (record.get("agent") or {}).get("heartbeat") or {}
        try:
            if not heartbeat.get("enabled"):
                if engine.store.get(automation_id) is not None:
                    await engine.remove(automation_id)
                    engine.store.delete(automation_id)
                continue
            interval_minutes = float(heartbeat.get("interval_minutes") or 30)
            every_seconds = interval_minutes * 60.0
            if every_seconds <= 0:
                every_seconds = 1800.0
            desired = {
                "id": automation_id,
                "name": f"heartbeat:{record.get('name') or agent_id}",
                "enabled": True,
                "owner_agent_id": agent_id,
                "trigger": {"kind": "interval", "every_seconds": every_seconds},
                "payload": {"kind": "heartbeat", "agent_id": agent_id},
                "delivery": {"mode": "none"},
            }
            existing = engine.store.get(automation_id)
            if existing is not None and _server()._heartbeat_automation_current(existing, desired):
                continue
            saved = engine.store.put(desired)
            await engine.sync_automation(saved)
            log.info("heartbeat.automation_reconciled", agent_id=agent_id,
                     every_seconds=every_seconds)
        except Exception:  # one bad agent never blocks startup
            log.exception("heartbeat.reconcile_failed", agent_id=agent_id)


async def _create_channel_conversation(session: str, event: Any) -> str:
    """Create the memory conversation backing a new channel session key."""
    if _server().memory is None:
        raise RuntimeError("memory service unavailable")
    label = f"{event.channel}:{event.chat_id}" if event is not None else session
    conversation_id = await _server().memory.create_conversation(f"渠道会话 {label}")
    workspace = _server()._default_workspace()
    await _server().memory.update_conversation(conversation_id,
                                     workspace=str(workspace) if workspace else None,
                                     source="channel")
    return conversation_id


async def _read_conversation_answer(conversation_id: str) -> str:
    """Last assistant message of a conversation (channel reply payload)."""
    if _server().memory is None:
        return ""
    messages = await _session_messages(conversation_id)
    return next((item["content"] for item in reversed(messages)
                 if item.get("role") == "assistant"), "")


async def _conversation_summary(conversation_id: str) -> dict[str, Any] | None:
    """Conversation metadata for agent-scoped session lineage (W10 sessions view)."""
    if _server().memory is None or getattr(_server().memory, "_db", None) is None:
        return None
    try:
        return await _server().memory.get_conversation(conversation_id)
    except Exception:  # metadata is best-effort in a listing
        log.exception("agent.conversation_summary_failed", conversation_id=conversation_id)
        return None


def _merge_agent_collection_skills(agent_id: str, base: Any) -> Any:
    """W7 skill-workshop bridge (scenario 16): per-agent collections reach the run.

    Explicit relation rows decide (frozen semantics in
    ``atlas.skills.agent_collections``): a per-agent ``enabled=1`` row — e.g. the
    ``learned`` row a proposal approval writes — joins the run's active set; an
    explicit ``enabled=0`` row wins over the profile (opt-out). Rows the
    collections only project from the global registry (``decision="global"``)
    never inject or evict: the repo registers every discovered skill as
    globally active, and force-activating all of them would blow the run's
    eight-skill cap — global activation stays the activation gate's business.
    Stable order, no duplicates; non-list input passes through so the
    activation gate below reports it unchanged.
    """
    if not isinstance(base, list):
        return base
    from atlas.api.agent_skills_router import get_collections

    try:
        rows = get_collections().effective_skills(agent_id)
    except Exception:  # the bridge must never fail a run
        log.exception("agent.skills_bridge_unavailable", agent_id=agent_id)
        return list(dict.fromkeys(str(item) for item in base))
    merged = [str(item) for item in base]
    for row in rows:
        name = str(row.get("skill_name") or "")
        if not name or row.get("decision") != "per_agent":
            continue
        if row.get("enabled"):
            merged.append(name)
        else:
            merged = [item for item in merged if item != name]
    return list(dict.fromkeys(merged))


async def _resolve_group_member_conversation(session: str, context: dict[str, Any]) -> str:
    """Create/reuse the conversation backing one group member session key.

    Same SessionMapper the gateway uses (``agent:<id>:group:<room>`` lineage), so
    a member's group thread survives restarts and shows up in the agent's
    /sessions lineage.
    """
    if _server().gateway_bridge is None:
        raise RuntimeError("gateway session map 尚未就绪")
    known = _server().gateway_bridge.sessions.get(session)
    if known:
        return known
    if _server().memory is None:
        raise RuntimeError("memory service 尚未就绪")
    label = str(context.get("group_id") or session)
    conversation_id = await _server().memory.create_conversation(f"群聊会话 {label}")
    workspace = _server()._default_workspace()
    await _server().memory.update_conversation(
        conversation_id, workspace=str(workspace) if workspace else None, source="channel",
    )
    _server().gateway_bridge.sessions.put(session, conversation_id)
    return conversation_id


async def _dispatch_group_member_turn(
    agent_id: str, prompt: str, session: str, context: dict[str, Any],
) -> str:
    """GroupOrchestrator TurnDispatcher (W8): one member model turn.

    Reuses the heartbeat/automation engine seam (``_collect_orchestrator_text``)
    — the member's own model, instructions and skills resolve from its
    persistent-agent record and the reply lands in the member's per-group
    conversation. Never a second agent core.
    """
    conversation_id = await _server()._resolve_group_member_conversation(session, context)
    profile = _server()._resolve_agent_for_run(agent_id)
    skills = list((profile or {}).get("active_skills") or [])
    if profile is not None:
        skills = _server()._merge_agent_collection_skills(agent_id, skills)
    skill_instructions = await _server()._resolve_active_skill_instructions(skills)
    instructions = str((profile or {}).get("instructions") or "")
    if instructions:
        skill_instructions = [*skill_instructions,
            {"name": f"profile:{agent_id}", "content": instructions}]
    return await _server()._collect_orchestrator_text(
        prompt, conversation_id,
        model=(profile or {}).get("model"),
        active_skill_instructions=skill_instructions,
    )


async def _start_group_turn_run(
    conn_id: str, run_id: str, data: dict[str, Any], group_id: str, agent_key: str,
) -> None:
    """W8 group turn as a run: one inbound message → orchestrated rounds.

    Validation failures report ``run.failed(category=validation)``; the drive
    runs in a tracked background task like any other run and its
    ``GroupTurnReport`` rides the run.completed envelope (no per-member
    websocket streaming — the room log is the shared timeline).
    """
    from atlas.api.group_router import get_group_orchestrator, get_group_service

    invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
    group = get_group_service().get(group_id)
    if group is None:
        invalid.status = "failed"
        await _server().runtime_mgr.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": f"group not found: {group_id}",
        }))
        return
    from_actor = agent_key or "user"
    if agent_key and agent_key not in (group.get("member_agent_ids") or []):
        invalid.status = "failed"
        await _server().runtime_mgr.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation",
            "detail": f"agent {agent_key} is not a member of group {group_id}",
        }))
        return
    content = data.get("content", "")
    if not isinstance(content, str) or not content.strip():
        invalid.status = "failed"
        await _server().runtime_mgr.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": "group turn requires non-empty text",
        }))
        return
    thread_id = data.get("thread_id")
    group_orch = get_group_orchestrator()
    model_id = data.get("model")
    run = RunState(
        run_id, str(data.get("conversation_id") or uuid.uuid4()),
        str(model_id) if model_id else (_server().model_mgr.current_model if _server().model_mgr else ""),
    )
    run.user_input = content
    _server().runtime_mgr.runs[run_id] = run
    _server().runtime_mgr.conn_runs[conn_id] = run_id
    await _server().runtime_mgr.persist_run(run)

    async def _drive() -> None:
        try:
            report = await group_orch.run_turn(group_id, {
                "from_actor": from_actor,
                "text": content,
                **({"thread_id": thread_id} if thread_id else {}),
            })
        except asyncio.CancelledError:
            run.status = "cancelled"
            await _server().runtime_mgr.send_run(run, run.next_envelope("run.cancelled", {}), conn_id)
        except DispatcherNotBound as exc:
            run.status = "failed"
            await _server().runtime_mgr.send_run(run, run.next_envelope("run.failed", {
                "category": "backend", "detail": str(exc),
            }), conn_id)
        except TurnConflict as exc:
            run.status = "failed"
            await _server().runtime_mgr.send_run(run, run.next_envelope("run.failed", {
                "category": "conflict", "detail": str(exc),
            }), conn_id)
        except KeyError as exc:
            run.status = "failed"
            await _server().runtime_mgr.send_run(run, run.next_envelope("run.failed", {
                "category": "validation", "detail": str(exc).strip("'"),
            }), conn_id)
        except ValueError as exc:
            run.status = "failed"
            await _server().runtime_mgr.send_run(run, run.next_envelope("run.failed", {
                "category": "validation", "detail": str(exc),
            }), conn_id)
        except Exception as exc:  # drive failure reports in-band
            log.exception("group_turn.drive_failed")
            run.status = "failed"
            await _server().runtime_mgr.send_run(run, run.next_envelope("run.failed", {
                "category": "backend", "detail": str(exc),
            }), conn_id)
        else:
            run.status = "completed"
            await _server().runtime_mgr.send_run(run, run.next_envelope("run.completed", {
                "result": "completed", "model": run.model,
                "group_turn": report.to_dict(),
            }), conn_id)

    run.task = asyncio.create_task(_drive())


def _bounded_project_notes(content: str) -> str:
    if len(content.encode("utf-8")) <= 8192:
        return content
    sections: list[tuple[str, list[str]]] = []
    heading = "Project notes"
    lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("## "):
            if lines:
                sections.append((heading, lines))
            heading, lines = line, []
        elif line.strip():
            lines.append(line)
    if lines:
        sections.append((heading, lines))
    selected = ["# Project notes (recent entries)"]
    for heading, entries in sections:
        selected.extend([heading, *entries[-20:]])
    result = "\n".join(selected)
    while len(result.encode("utf-8")) > 8192 and sections:
        heading, entries = sections.pop(0)
        selected = ["# Project notes (recent entries)"]
        for section, rows in sections:
            selected.extend([section, *rows[-20:]])
        result = "\n".join(selected)
    return result[-8192:]


def _workspace_trust_path() -> Path:
    return get_config().db_path.parent / "trusted-workspaces.json"


def _workspace_trust() -> dict[str, bool]:
    try:
        value = json.loads(_server()._workspace_trust_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _set_workspace_trusted(root: str, trust: bool) -> None:
    values = _server()._workspace_trust()
    if trust:
        values[root] = True
    else:
        values.pop(root, None)
    path = _server()._workspace_trust_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _validated_file_attachments(
    value: Any, run_id: str, content: str, *, include_audit: bool = False,
) -> tuple[str, list[str]] | tuple[str, list[str], list[dict[str, Any]]]:
    if value is None:
        return (content, [], []) if include_audit else (content, [])
    if not isinstance(value, list):
        raise ValueError("files must be an array")
    total = 0
    inlined: list[str] = []
    stored: list[str] = []
    media_audit: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each file attachment must be an object")
        name = Path(str(item.get("name", "attachment"))).name
        data = item.get("data_base64")
        if not isinstance(data, str) or len(data) > 14 * 1024 * 1024:
            raise ValueError("file attachment data_base64 is invalid or exceeds 10 MB")
        try:
            raw = base64.b64decode(data, validate=True)
        except ValueError as exc:
            raise ValueError("file attachment has invalid base64 data") from exc
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError("single file attachment exceeds 10 MB")
        total += len(raw)
        if total > 20 * 1024 * 1024:
            raise ValueError("file attachments exceed 20 MB total")
        mime = str(item.get("mime", "application/octet-stream")).lower()
        from atlas.runtime.media_understanding import extract_document, media_context_block

        text, audit = extract_document(name, mime, raw)
        media_audit.append(audit)
        extracted = media_context_block(audit, text)
        if extracted:
            inlined.append(extracted)
        if audit["extractor"] != "utf-8":
            directory = Path.home() / ".atlas" / "attachments" / run_id
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / name
            path.write_bytes(raw)
            stored.append(str(path.resolve()))
    if inlined:
        content += "\n\n" + "\n\n".join(inlined)
    return (content, stored, media_audit) if include_audit else (content, stored)


async def _transcribe_audio_attachments(
    file_paths: list[str], media_audit: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Transcribe uploaded audio through the existing local SenseVoice ASR service."""
    audio_extensions = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".webm"}
    audio_audits = [item for item in media_audit
                    if Path(str(item.get("name") or "")).suffix.lower() in audio_extensions
                    or str(item.get("mime") or "").startswith("audio/")]
    if not audio_audits:
        return "", []
    from atlas import server as atlas_server
    from atlas.asr import ASRManager
    from atlas.runtime.media_understanding import media_context_block

    app = getattr(atlas_server, "app", None)
    services = getattr(getattr(app, "state", None), "services", None)
    asr = getattr(services, "asr_manager", None)
    if asr is None:
        asr = ASRManager()
        if services is not None:
            services.asr_manager = asr
    blocks: list[str] = []
    for item in audio_audits:
        path = next((candidate for candidate in file_paths if Path(candidate).name == item.get("name")), "")
        if not path:
            continue
        try:
            payload = await asyncio.to_thread(Path(path).read_bytes)
            transcript = await asr.transcribe_audio_bytes_async(payload)
            item.update({"extractor": "SenseVoice local ASR", "status": "complete" if transcript else "no_speech",
                         "characters": len(transcript)})
            block = media_context_block(item, transcript)
            if block:
                blocks.append(block)
        except Exception as exc:
            item.update({"extractor": "SenseVoice local ASR", "status": f"failed:{type(exc).__name__}"})
    return "\n\n".join(blocks), audio_audits

def _plan_mode_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [json.loads(json.dumps(item)) for item in tools
                if item.get("function", {}).get("name") in {"local_file", "web_fetch"}]
    for item in selected:
        if item["function"]["name"] == "local_file":
            item["function"]["parameters"]["properties"]["action"]["enum"] = [
                "read", "list", "glob", "search", "stat",
            ]
    return selected


def _queue_run_steer(
    run: "RunState", content: Any, event_id: Any, immediate: Any = False,
) -> str | None:
    if run.status in {"completed", "failed", "cancelled"}:
        return "run_not_active"
    if not isinstance(content, str) or not content.strip():
        return "invalid_content"
    if not isinstance(immediate, bool):
        return "invalid_immediate"
    run.steer_queue.put_nowait({"content": content, "event_id": str(event_id or uuid.uuid4()),
                                "immediate": immediate})
    return None


async def _run_inbox(run: RunState) -> Any:
    """Return the shared durable inbox attached to a live API run."""
    if not run.conversation_id or run.ephemeral:
        return None
    if run.inbox is None:
        from atlas.config import DATA_ROOT
        from atlas.engine.kernel.inbox import DurableInbox

        run.inbox = DurableInbox(DATA_ROOT / "engine", run.conversation_id)
    await run.inbox.restore()
    return run.inbox


async def _inject_run_message(run: RunState, data: Any) -> tuple[str | None, str | None]:
    """Durably inject into an ordered lane without waking the active run."""
    if run.status in {"completed", "failed", "cancelled"}:
        return "run_not_active", None
    if not isinstance(data, dict) or data.get("inject") is not True:
        return "invalid_inject", None
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return "invalid_content", None
    lane = data.get("lane", "next-step")
    if lane not in {"next-turn", "next-step"}:
        return "invalid_lane", None
    inbox = await _run_inbox(run)
    if inbox is None:
        return "inbox_unavailable", None
    return None, await inbox.inject(content, lane=lane)


def _workspace_path(root: str, relative: str = "") -> tuple[Path, Path]:
    root_path = Path(root).expanduser()
    if not root_path.is_absolute():
        raise HTTPException(status_code=400, detail="root must be an absolute path")
    base = root_path.resolve()
    target = (base / relative).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(status_code=400, detail="path escapes workspace root")
    return base, target


def _context_file_block(root: str, relative: str, remaining_bytes: int) -> tuple[str, int]:
    _, target = _server()._workspace_path(root, relative)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="context file not found")
    raw = target.read_bytes()
    chunk = raw[:min(64 * 1024, max(0, remaining_bytes))]
    block = f"\n\n[Context file: {relative}]\n{chunk.decode('utf-8', errors='replace')}"
    if len(raw) > len(chunk):
        block += "\n[Context file truncated.]"
    return block, len(chunk)


def _run_changes(run_id: str, workspace: str | None = None) -> dict[str, Any]:
    store = getattr(_server().orchestrator, "checkpoints", None) if _server().orchestrator is not None else None
    if store is None:
        return {"run_id": run_id, "files": []}
    manifests = [item for item in store.list_checkpoints(run_id=run_id, workspace=workspace)]
    if not manifests:
        return {"run_id": run_id, "files": []}
    first = min(manifests, key=lambda item: item["created_at"])
    last = max(manifests, key=lambda item: item["created_at"])
    root = Path(first["workspace"]).resolve()
    manifest_path = store.storage_dir / first["id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    last_manifest = json.loads(
        (store.storage_dir / last["id"] / "manifest.json").read_text(encoding="utf-8")
    )
    before_entries = {
        entry["path"]: entry for entry in manifest.get("files", [])
        if not entry.get("directory")
    }
    after_entries = {
        entry["path"]: entry for entry in last_manifest.get("files", [])
        if not entry.get("directory")
    }
    results = []
    for relative in sorted(before_entries.keys() | after_entries.keys()):
        entry = before_entries.get(relative, {"exists": False})
        current = (root / relative).resolve()
        if root not in current.parents:
            continue
        baseline = store.storage_dir / first["id"] / "files" / relative
        before = baseline.read_text(encoding="utf-8", errors="replace") if entry.get("exists") and baseline.is_file() else ""
        after = current.read_text(encoding="utf-8", errors="replace") if current.is_file() else ""
        if bool(entry.get("exists")) == current.is_file() and before == after:
            continue
        status = "added" if not entry.get("exists") else "deleted" if not current.exists() else "modified"
        diff = list(__import__("difflib").unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=f"a/{relative}", tofile=f"b/{relative}",
        ))
        diff_text = "".join(diff)
        truncated = len(diff_text.encode("utf-8")) > 200 * 1024
        if truncated:
            diff_text = diff_text.encode("utf-8")[:200 * 1024].decode("utf-8", errors="ignore")
        additions = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
        item = {"path": relative, "workspace": str(root), "status": status,
                "additions": additions, "deletions": deletions, "diff": diff_text}
        if truncated:
            item["truncated"] = True
        results.append(item)
    return {"run_id": run_id, "files": results}


def _run_change_summary(run_id: str) -> dict[str, int]:
    files = _server()._run_changes(run_id)["files"]
    return {"files": len(files), "additions": sum(item["additions"] for item in files),
            "deletions": sum(item["deletions"] for item in files)}


def _sum_usage(calls: list[dict[str, Any]]) -> dict[str, Any]:
    return aggregate_run_usage(calls)


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Tools (MCP)
# ---------------------------------------------------------------------------


async def _reload_extensions() -> dict[str, Any]:
    assert _server().plugin_runtime is not None
    report = await _server().plugin_runtime.load_all(
        hook_bus=_server().orchestrator.hooks if _server().orchestrator else None,
        mcp_client=_server().mcp_client,
        capabilities=_server().orchestrator.capabilities if _server().orchestrator else None,
    )
    _server()._refresh_extension_sources()
    return report


def _plugin_contributions() -> list[dict[str, Any]]:
    return _server().plugin_runtime.enabled_contributions() if _server().plugin_runtime else []


def _plugin_skill_sources() -> dict[str, list[Path]]:
    return {
        plugin["name"]: [Path(item) for item in plugin["skills"]]
        for plugin in _server()._plugin_contributions()
    }


def _refresh_extension_sources() -> None:
    """Re-apply plugin contributions to the shared registries (E2/E4).

    Hooks flow through the lazy ``_plugin_hooks`` supplier and MCP/capabilities
    through ``load_all``; here only the skill index needs re-assembly, always
    via ``register_skill_source`` — never a second registry. When the plugin
    source set is unchanged (the common reload), the full index rebuild is
    skipped — a cold start pays one scan, not two (H8).
    """
    skill_mgr = _server().skill_mgr
    if skill_mgr is None:
        return
    sources = plugin_skill_sources(_server()._plugin_skill_sources())
    if not sources and not any(
        name.startswith("plugin:") and name != "atlas"
        for name in skill_mgr._sources
    ):
        # No plugin contributes skills on either side: replace+rebuild would
        # reproduce the identical index — skip the redundant full rescan (H8).
        return
    skill_mgr.replace_skill_sources("plugin:", sources)


def _plugin_command_sources() -> list[CommandSource]:
    return [
        CommandSource(f"plugin:{plugin['name']}", Path(path), 60, plugin=True)
        for plugin in _server()._plugin_contributions()
        for path in plugin["command_sources"]
    ]


def _plugin_agent_dirs() -> list[Path]:
    """Directories holding plugin agent files, for the shared agent discovery."""
    dirs: list[Path] = []
    for plugin in _server()._plugin_contributions():
        for agent_file in plugin["agents"]:
            agents_dir = Path(agent_file).parent
            if agents_dir not in dirs:
                dirs.append(agents_dir)
    return dirs


def _plugin_hooks() -> list[dict[str, Any]]:
    return [hook for plugin in _server()._plugin_contributions() for hook in plugin["hooks"]]


_active_hook_store: HookStore | None = None


def _hook_store() -> HookStore:
    global _active_hook_store
    path = get_config().db_path.parent / "hooks.toml"
    if _active_hook_store is None or _active_hook_store.path != path:
        _active_hook_store = HookStore(path, plugin_hooks=_server()._plugin_hooks)
    return _active_hook_store


async def cancel_subtask(run_id: str, subtask_id: str) -> dict[str, str]:
    run = _server().runtime_mgr.runs.get(run_id)
    subtask = run.subtasks.get(subtask_id) if run else None
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")
    if subtask.get("status") in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Subtask is already finished")
    subtask["cancel_event"].set()
    return {"status": "cancelling", "subtask_id": subtask_id}


async def _handle_rules_trust(
    conn_id: str, data: dict[str, Any], manager: RuntimeManager | None = None,
) -> None:
    manager = manager or _server().runtime_mgr
    run_id = str(data.get("run_id", ""))
    run = manager.runs.get(run_id)
    if run and run.trust_future and not run.trust_future.done() and run.trust_event_id:
        # One RunState has one outstanding trust request, so a stale event_id
        # after reconnect can safely fall back to run_id.
        trusted = data.get("trust") is True
        if trusted:
            for root in run.trust_roots or ([run.workspace] if run.workspace else []):
                _server()._set_workspace_trusted(root, True)
        run.trust_future.set_result(trusted)
        return
    await manager.send(conn_id, {
        "type": "error", "run_id": run_id,
        "detail": "没有可匹配的待处理规则信任请求。",
    })


async def _handle_run_start(
    conn_id: str, data: dict[str, Any], manager: RuntimeManager | None = None,
) -> None:
    """Start a new agent run."""
    request_received_at = time.perf_counter()
    manager = manager or _server().runtime_mgr
    services = manager.services
    model_mgr = getattr(services, "model_mgr", None) or getattr(_server(), "model_mgr", None)
    memory = getattr(services, "memory", None) or getattr(_server(), "memory", None)
    orchestrator = getattr(services, "orchestrator", None) or getattr(_server(), "orchestrator", None)
    projects = getattr(services, "projects", None) or getattr(_server(), "projects", None)
    from atlas.project_context import project_scope, validate_config_override

    try:
        config_override = validate_config_override(data.get("config_override", {})) if "config_override" in data else None
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    ignore_project_config = data.get("ignore_project_config", False)
    ignore_workspace_rules = data.get("ignore_workspace_rules", False)
    if not isinstance(ignore_project_config, bool) or not isinstance(ignore_workspace_rules, bool):
        raise ValueError("ignore_project_config and ignore_workspace_rules must be booleans")
    run_id = data.get("run_id") or str(uuid.uuid4())
    existing = manager.runs.get(run_id)
    if existing:
        manager.conn_runs[conn_id] = run_id
        async with existing.event_lock:
            for env in list(existing.events):
                await manager.send(conn_id, env)
        return

    try:
        tool_mode = _requested_tool_mode(data)
    except ValueError as exc:
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        invalid.status = "failed"
        await manager.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": str(exc),
        }))
        return

    content = data.get("content", "")
    if not isinstance(content, str):
        content = str(content)
    requested_workspace = data.get("workspace")
    # W10: resolve the persistent agent first — an empty workspace falls back to
    # the agent's workspace, and its profile merges in at the profile_id block
    # below, so the rest of the run assembly is untouched.
    agent_profile: dict[str, Any] | None = None
    agent_key = ""
    if data.get("agent_id"):
        agent_key = str(data["agent_id"])
        agent_profile = _server()._resolve_agent_for_run(agent_key)
        if agent_profile is None:
            invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
            await manager.send(conn_id, invalid.next_envelope("run.failed", {
                "category": "validation", "detail": f"persistent agent not found: {agent_key}",
            }))
            return
        if not requested_workspace:
            requested_workspace = agent_profile.get("workspace")
    if data.get("group_id"):
        # W8: real group-chat dispatch — validate group/membership, then drive
        # the orchestrated rounds (timeline = the shared group room log).
        await _server()._start_group_turn_run(conn_id, run_id, data, str(data["group_id"]), agent_key)
        return
    ssh_requested = isinstance(requested_workspace, str) and requested_workspace.startswith("ssh://")
    try:
        if ssh_requested:
            ssh_workspaces.parse_workspace(requested_workspace)
        elif requested_workspace is not None and (
            not isinstance(requested_workspace, str) or not Path(requested_workspace).is_absolute()
        ):
            raise ValueError("workspace must be an absolute path")
    except ValueError:
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": "workspace must be an absolute path",
        }))
        return
    extra_roots = data.get("extra_roots")
    if extra_roots is not None:
        try:
            if not isinstance(extra_roots, list) or len(extra_roots) > 5:
                raise ValueError
            normalized_roots = []
            for root in extra_roots:
                if isinstance(root, str) and root.startswith("ssh://"):
                    ssh_workspaces.parse_workspace(root)
                    normalized_roots.append(root)
                elif isinstance(root, str) and Path(root).is_absolute():
                    normalized_roots.append(str(Path(root).expanduser().resolve()))
                else:
                    raise ValueError
            extra_roots = normalized_roots
        except ValueError:
            invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
            await manager.send(conn_id, invalid.next_envelope("run.failed", {
                "category": "validation", "detail": "附加目录必须是绝对路径或 SSH 地址，且最多 5 个。",
            }))
            return
    profile_id = data.get("profile_id")
    profile = _server()._profile_store().get(str(profile_id)) if profile_id else None
    if profile_id and profile is None:
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": f"profile not found: {profile_id}",
        }))
        return
    if agent_profile is not None:
        # W10: a persistent agent runs on its own record as the profile — the
        # synthetic dict mirrors the profile shape, so the effective_skills /
        # effective_mode / model / instructions / tools chain below is unchanged.
        profile_id = agent_profile["profile_id"]
        profile = {
            "active_skills": agent_profile.get("active_skills", []),
            "mode": agent_profile.get("mode", "act"),
            "model": agent_profile.get("model"),
            "reasoning_effort": agent_profile.get("reasoning_effort"),
            "instructions": agent_profile.get("instructions", ""),
            "tools": {
                "allow": (agent_profile.get("tools") or {}).get("allow"),
                "deny": (agent_profile.get("tools") or {}).get("deny", []),
            },
        }
    # Project-scoped skills are additive to this run's explicit/profile selection.
    # Resolve the conversation's project before instruction loading so these Skills
    # pass through the same lifecycle/activation gate as all other selected Skills.
    project_scope_id, project_skills = await _resolve_project_skill_scope(
        data, manager, projects, ignore_project_config=ignore_project_config,
    )
    effective_skills = data.get("active_skills", (profile or {}).get("active_skills", []))
    message_skills = data.get("message_skills", [])
    if (not isinstance(message_skills, list)
            or any(not isinstance(name, str) or not name for name in message_skills)
            or len(message_skills) > 8):
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": "message_skills must contain at most eight Skill names",
        }))
        return
    if not isinstance(effective_skills, list):
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": "active_skills must be a list of Skill names",
        }))
        return
    # Message-level mentions join the effective set for this run only; they are
    # never written back to the profile or conversation's global active Skills.
    effective_skills = list(dict.fromkeys([*effective_skills, *project_skills, *message_skills]))
    if len(effective_skills) > 8:
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": "at most eight Skills may be active for one run",
        }))
        return
    if agent_profile is not None:
        # W7→W10 bridge (scenario 16): learned/approved per-agent skills join the
        # run's active set; an explicit per-agent opt-out wins over the profile.
        effective_skills = _server()._merge_agent_collection_skills(agent_key, effective_skills)
    effective_mode = data.get("mode", (profile or {}).get("mode", "act"))
    model_id = data.get("model", (profile or {}).get("model"))
    reasoning_effort = data.get("reasoning_effort", (profile or {}).get("reasoning_effort"))
    try:
        resolved_permission_policy = _resolve_permission_policy(data)
    except ValueError as exc:
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": str(exc),
        }))
        return
    permission_mode = resolved_permission_policy["mode"]
    sandbox_mode = resolved_permission_policy["sandbox_mode"]
    approval_policy = resolved_permission_policy["approval_policy"]
    run_tool_allow = data.get("tool_allow")
    run_tool_deny = data.get("tool_deny")
    if (run_tool_allow is not None and (not isinstance(run_tool_allow, list)
            or any(not isinstance(item, str) or not item for item in run_tool_allow))) or (
            run_tool_deny is not None and (not isinstance(run_tool_deny, list)
            or any(not isinstance(item, str) or not item for item in run_tool_deny))):
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": "tool_allow/tool_deny 必须是非空字符串列表",
        }))
        return
    allowed_paths = data.get("allowed_paths")
    if allowed_paths is not None and (not isinstance(allowed_paths, list) or any(
            not isinstance(item, str) or not Path(item).is_absolute() for item in allowed_paths)):
        permission_mode = "invalid"
    if permission_mode is None:
        permission_mode = "full_access"
    if permission_mode == "plan":
        effective_mode = "plan"
    if permission_mode not in {"full_access", "ask_each", "ask_writes", "auto_file", "plan", "read_only"}:
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": "invalid permission_mode or allowed_paths",
        }))
        return
    if reasoning_effort not in {None, "off", "minimal", "low", "medium", "high"}:
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": "invalid reasoning_effort",
        }))
        return
    daybreak = data.get("daybreak", False)
    if not isinstance(daybreak, bool):
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": "daybreak must be a boolean",
        }))
        return
    try:
        active_skill_instructions = await _server()._resolve_active_skill_instructions(
            effective_skills
        )
    except (TypeError, ValueError, PermissionError) as exc:
        invalid_run = RunState(
            run_id,
            str(data.get("conversation_id", "")),
            str(data.get("model", "")),
        )
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "skill", "detail": str(exc),
        }))
        return
    try:
        image_attachments = _server()._validated_image_attachments(data.get("attachments"))
    except ValueError as exc:
        invalid_run = RunState(
            run_id,
            str(data.get("conversation_id", "")),
            str(data.get("model", "")),
        )
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": str(exc),
        }))
        return
    media_sources: list[dict[str, Any]] = []
    from atlas.runtime.media_understanding import media_context_block, ocr_image_data_url, ocr_runtime_status
    preparation_run = RunState(run_id, str(data.get("conversation_id") or ""), str(data.get("model") or ""))
    image_context: list[str] = []
    for image_index, image in enumerate(image_attachments):
        ocr_task = asyncio.create_task(asyncio.to_thread(ocr_image_data_url, image, image_index))
        last_progress: tuple[str, int, str] | None = None
        while not ocr_task.done():
            status = ocr_runtime_status()
            progress_key = (str(status.get("state")), int(float(status.get("progress", 0)) * 100), str(status.get("detail")))
            if status.get("state") != "not_started" and progress_key != last_progress:
                await manager.send(conn_id, preparation_run.next_envelope("media.ocr.progress", {
                    "state": status.get("state"), "progress": status.get("progress", 0),
                    "detail": status.get("detail") or "正在准备本地 OCR",
                }))
                last_progress = progress_key
            await asyncio.sleep(0.25)
        text, audit = await ocr_task
        final_ocr_status = ocr_runtime_status()
        await manager.send(conn_id, preparation_run.next_envelope("media.ocr.progress", {
            "state": final_ocr_status.get("state", "failed"),
            "progress": final_ocr_status.get("progress", 0),
            "detail": final_ocr_status.get("detail") or audit.get("status", "OCR 完成"),
        }))
        audit["vision"] = "原图随消息传给所选模型"
        media_sources.append(audit)
        block = media_context_block(audit, text)
        if block:
            image_context.append(block)
    if image_attachments:
        content += (
            f"\n\n--- Media summary: {len(image_attachments)} image attachment(s) ---\n"
            "The original image payloads are supplied to the selected vision model. Inspect their visual content "
            "and transcribe visible text (OCR) when relevant to the user's request. Local OCR status and any extracted "
            "text follow as auditable media sources."
        )
    if image_context:
        content += "\n\n" + "\n\n".join(image_context)
    try:
        content, file_paths, file_media_sources = _server()._validated_file_attachments(
            data.get("files"), run_id, content, include_audit=True,
        )
        media_sources.extend(file_media_sources)
        transcript, _audio_sources = await _transcribe_audio_attachments(file_paths, file_media_sources)
        if transcript:
            content += "\n\n" + transcript
        if file_paths:
            content += "\n\nAttached files stored at:\n" + "\n".join(file_paths)
    except ValueError as exc:
        invalid_run = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": str(exc),
        }))
        return
    if daybreak:
        from atlas.daybreak import daybreak_prompt
        content = daybreak_prompt(content)
    resume_from = data.get("resume_from")
    recovered_plan = None
    prior_run = manager.runs.get(resume_from) if isinstance(resume_from, str) else None
    if resume_from is not None:
        if not prior_run or prior_run.status != "failed":
            raise ValueError("resume_from must reference a failed or interrupted run")
        if data.get("conversation_id") and prior_run.conversation_id != str(data["conversation_id"]):
            raise ValueError("resume_from must belong to the same conversation")
        recovered_plan = prior_run.plan_state
        if not content and recovered_plan:
            content = str(recovered_plan.get("goal", ""))
    conv_id = data.get("conversation_id") or (
        prior_run.conversation_id if prior_run else str(uuid.uuid4())
    )
    run_project_id = str(data.get("project_id") or project_scope_id or "").strip() or None
    if run_project_id and projects is not None and await projects.get(run_project_id) is None:
        invalid_run = RunState(run_id, str(conv_id), str(model_id or ""))
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": "project_id does not reference an existing project",
        }))
        return
    if not run_project_id and projects is not None:
        try:
            project_db = projects._require_db()
            cursor = await project_db.execute(
                "SELECT project_id FROM project_conversations WHERE conversation_id=? "
                "ORDER BY rowid DESC LIMIT 1", (conv_id,),
            )
            project_row = await cursor.fetchone()
            run_project_id = str(project_row["project_id"]) if project_row else None
        except Exception:
            log.exception("run.project_scope_lookup_failed", conversation_id=conv_id)
    if run_project_id and projects is not None:
        await projects.attach_conversation(run_project_id, str(conv_id))
    # C6:/review 拦截——命中审查指令时把正文改写为派发提示词，并固定审查配置。
    # 放在正文（含附件）就绪之后、档案合并之前，让后续统一的 run 组装吃到强制值。
    try:
        from atlas.review.engine import (
            build_dispatch_prompt,
            collect_diff,
            is_review_request,
            parse_scope,
        )
    except Exception:  # review 模块未就绪时按普通消息放行
        log.exception("C6 /review 拦截模块不可用，按普通消息处理")
    else:
        if is_review_request(content):
            review_conv = None
            if memory is not None and getattr(memory, "_db", None) is not None:
                try:
                    review_conv = await memory.get_conversation(conv_id)
                except Exception:
                    log.exception("review.conversation_lookup_failed", conv_id=conv_id)
                    review_conv = None
            review_workspace = (requested_workspace
                                or (review_conv or {}).get("workspace")
                                or None)
            if review_workspace is None and projects is not None:
                try:
                    review_db = projects._require_db()
                    review_cursor = await review_db.execute(
                        "SELECT p.workspace_path FROM projects p JOIN project_conversations pc "
                        "ON p.project_id=pc.project_id WHERE pc.conversation_id=? "
                        "ORDER BY p.updated_at DESC LIMIT 1",
                        (conv_id,),
                    )
                    review_row = await review_cursor.fetchone()
                    review_workspace = review_row["workspace_path"] if review_row else None
                except Exception:
                    log.exception("review.workspace_lookup_failed", conv_id=conv_id)
                    review_workspace = None
            if review_conv and review_conv.get("worktree_path"):
                review_worktree = str(review_conv["worktree_path"])
                if Path(review_worktree).is_dir():
                    review_workspace = review_worktree
            if not review_workspace or str(review_workspace).startswith("ssh://"):
                invalid_run = RunState(run_id, conv_id, str(data.get("model", "")))
                await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                    "category": "validation",
                    "detail": "/review 需要本机 git 工作目录才能读取改动；请先为本对话选择一个本机工作目录。",
                }))
                return
            try:
                review_scope = parse_scope(content)
                review_diff = collect_diff(str(review_workspace), review_scope)
                review_diff["mode"] = review_scope.get("mode", "general")
            except ValueError as exc:
                invalid_run = RunState(run_id, conv_id, str(data.get("model", "")))
                await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                    "category": "validation", "detail": str(exc),
                }))
                return
            content = build_dispatch_prompt(review_diff, str(review_scope.get("user_prompt", "")))
            # 审查员（子代理）的只读由 delegate 的 permission_mode=read_only 保证；
            # 父运行也是 read_only：只读门禁按显式 tool_allow 放行 delegate/submit/review_command
            #（agent 只读门禁的审查例外），写操作被结构性拒绝且不弹任何审批卡。
            profile_id = None
            profile = None
            permission_mode = "read_only"
            run_tool_allow = ["delegate_task", "submit_findings", "ReportFindings", "local_file", "review_command",
                              "coding.repo_map", "coding.ast_grep.run", "read_office"]
            run_tool_deny = []
            log.info("review.intercepted", run_id=run_id,
                     workspace=str(review_workspace), scope=review_scope.get("scope"))
    assert model_mgr is not None
    with project_scope(run_project_id, config_override=config_override,
                       ignore_project_config=ignore_project_config, session_id=str(conv_id)):
        model_id = model_id or model_mgr.current_model
    run = preparation_run
    run.tool_mode = tool_mode
    run.conversation_id = conv_id
    run.ephemeral = data.get("ephemeral") is True
    if "bypass_prompt_cache" in data and not isinstance(data.get("bypass_prompt_cache"), bool):
        raise HTTPException(status_code=400, detail="bypass_prompt_cache must be a boolean")
    run.bypass_prompt_cache = data.get("bypass_prompt_cache") is True
    # RunState stores the selected model in ``model``; it is slotted and has no
    # separate model_id field. Keep the resolved project model on that field.
    run.model = model_id
    try:
        from atlas.logs import append_run_event
        if not run.ephemeral:
            append_run_event(run_id, "api_timing", stage="request_received", elapsed_ms=0)
            append_run_event(run_id, "api_timing", stage="run_created",
                             elapsed_ms=round((time.perf_counter() - request_received_at) * 1000))
    except Exception:
        log.debug("run.timing_log_failed", run_id=run_id, stage="run_created", exc_info=True)
    run.project_id = run_project_id
    run.agent_id = agent_key or getattr(prior_run, "agent_id", None)
    run.config_override = config_override
    run.ignore_project_config = ignore_project_config
    run.ignore_workspace_rules = ignore_workspace_rules
    session_env = data.get("session_env", {})
    if not isinstance(session_env, dict) or len(session_env) > 64 or any(
        not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key)
        or not isinstance(value, str) or len(value) > 2048
        for key, value in session_env.items()
    ):
        await manager.send(conn_id, run.next_envelope("run.failed", {
            "category": "validation", "detail": "会话预设环境变量格式无效。",
        }))
        return
    run.session_env = dict(session_env)
    if isinstance(data.get("telegram_user_id"), int):
        run.telegram_user_id = data["telegram_user_id"]
    # T06.2：任务焦点绑定 —— run.start 可显式携带 task_id（调度任务 / 续接
    # 请求）；未携带为 None，普通聊天不进焦点接续链路。
    run.task_id = str(data.get("task_id") or "").strip() or None
    if effective_mode not in {"act", "plan"}:
        run.status = "failed"
        await manager.send(conn_id, run.next_envelope("run.failed", {
            "category": "validation", "detail": "mode must be 'act' or 'plan'",
        }))
        return
    run.mode = effective_mode
    run.dynamic_plan_mode = effective_mode == "plan"
    run.reasoning_effort = reasoning_effort
    run.permission_mode = permission_mode
    run.sandbox_mode = sandbox_mode
    run.approval_policy = approval_policy
    run.permission_preset = resolved_permission_policy["name"]
    run.allowed_paths = [
        str(item) if str(item).startswith("ssh://") else str(Path(item).expanduser().resolve())
        for item in allowed_paths or []
    ]
    run.read_only = permission_mode == "read_only" or profile_id in {"architect", "reviewer"}
    run.active_skills = list(effective_skills) if isinstance(effective_skills, list) else []
    run.profile_id = str(profile_id) if profile_id else None
    if profile:
        run.tool_allow = profile.get("tools", {}).get("allow")
        run.tool_deny = profile.get("tools", {}).get("deny", [])
        run.read_only = profile_id in {"architect", "reviewer"}
        if profile.get("instructions"):
            active_skill_instructions = [*active_skill_instructions,
                {"name": f"profile:{profile_id}", "content": profile["instructions"]}]
    # A one-run override (e.g. custom command frontmatter) wins over the profile for this run only.
    if run_tool_allow is not None:
        run.tool_allow = run_tool_allow
    if run_tool_deny is not None:
        run.tool_deny = run_tool_deny
    workspace = requested_workspace
    conversation = None
    if memory is not None and getattr(memory, "_db", None) is not None:
        conversation = await memory.get_conversation(conv_id)
    if not workspace and conversation:
        workspace = conversation.get("workspace")
    run.extra_roots = list(extra_roots if extra_roots is not None
                           else (conversation or {}).get("extra_roots") or [])
    if conversation:
        if "permission_mode" not in data and "permission_preset" not in data:
            run.permission_mode = conversation.get("permission_mode", "full_access")
            run.read_only = run.permission_mode == "read_only" or profile_id in {"architect", "reviewer"}
        if "allowed_paths" not in data:
            run.allowed_paths = list(conversation.get("allowed_paths") or [])
        if "extra_roots" not in data:
            run.extra_roots = list(conversation.get("extra_roots") or [])
        run.executor = str(data.get("executor", conversation.get("executor") or "atlas"))
        run.sandbox = data.get("sandbox", conversation.get("sandbox"))
    else:
        run.executor = str(data.get("executor", "atlas"))
        run.sandbox = data.get("sandbox")
    from atlas.api.wsl_policy_router import apply_wsl_session_policy
    try:
        run.sandbox = apply_wsl_session_policy(run.sandbox)
    except PermissionError:
        invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "policy", "detail": "本机策略已禁用 WSL 会话。请在设置中重新启用，或改用原生 Atlas 运行时。",
        }))
        return
    if run.allowed_paths:
        local_roots = [root for root in run.extra_roots if not root.startswith("ssh://")]
        run.allowed_paths = list(dict.fromkeys([*run.allowed_paths, *local_roots]))
    if run.sandbox is not None and (
        not isinstance(run.sandbox, dict) or run.sandbox.get("type") != "docker"
        or not isinstance(run.sandbox.get("network", False), bool)
        or (run.sandbox.get("image") is not None and not isinstance(run.sandbox.get("image"), str))
    ):
        invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": "Docker 沙箱配置无效。",
        }))
        return
    if run.sandbox and run.executor != "atlas":
        invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": "Docker 沙箱目前只支持 Atlas Agent 执行。",
        }))
        return
    if run.executor not in {"atlas", "codex", "claude", "hermes", "pi", "zcode"}:
        invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": "所选执行 Agent 不受支持。",
        }))
        return
    if run.ephemeral and run.executor != "atlas":
        invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": "临时聊天只支持 Atlas 内核，以避免外部 Agent 写入会话或运行记录。",
        }))
        return
    if run.executor != "atlas":
        # External Agents get every permission request auto-approved (runtime/backends.py), so
        # Atlas can't honour "ask before changes" for them either; only full access may start one.
        if run.permission_mode != "full_access" or run.read_only:
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            mode = ("只读" if run.permission_mode == "read_only" or run.read_only
                    else "改前问我" if run.permission_mode == "ask_writes" else "需要确认")
            await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "permission",
                "detail": f"当前对话是「{mode}」模式，外部 Agent 的操作不经过 Atlas 确认，所以不能启动。"
                          "请把对话权限切到「完全访问」后重试。",
            }))
            return
        if workspace and str(workspace).startswith("ssh://"):
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "validation",
                "detail": "外部 Agent 目前不能在 SSH 工作目录中运行，请选择本机工作目录。",
            }))
            return
        available = {
            item["id"]: item for item in
            _server().external_agent_status(_server().external_agent_status_cache)["agents"]
        }.get(run.executor)
        if not available or not available["available"]:
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "external_agent",
                "detail": (available or {}).get("detail", "所选外部 Agent 当前不可用，请先安装对应命令行程序。"),
            }))
            return
    if permission_mode == "full_access" and conversation and "permission_mode" not in data:
        run.permission_mode = conversation.get("permission_mode", "full_access")
        run.read_only = (run.permission_mode == "read_only"
                         or profile_id in {"architect", "reviewer"})
    if memory is not None and conversation:
        updates: dict[str, Any] = {}
        for field in ("workspace", "permission_mode", "allowed_paths", "executor", "sandbox", "extra_roots"):
            if field in data:
                updates[field] = data[field]
        if updates:
            await memory.update_conversation(
                conv_id, **updates, sandbox_set="sandbox" in updates,
            )
    if not workspace and projects is not None:
        try:
            db = projects._require_db()
            cursor = await db.execute(
                "SELECT p.workspace_path FROM projects p JOIN project_conversations pc "
                "ON p.project_id=pc.project_id WHERE pc.conversation_id=? ORDER BY p.updated_at DESC LIMIT 1",
                (conv_id,),
            )
            project_row = await cursor.fetchone()
            workspace = project_row["workspace_path"] if project_row else None
        except Exception:
            log.exception("run.project_workspace_lookup_failed", conv_id=conv_id)
            workspace = None
    # Project instructions are extra context: if the project store can't answer, run without them
    # rather than failing the run.
    project = None
    if projects is not None:
        try:
            project = await projects.get(run_project_id) if run_project_id else await projects.find_by_conversation(conv_id)
            source_data = await projects.get_sources(project.project_id) if project is not None else None
        except Exception:
            log.exception("run.project_context_unavailable")
            project, source_data = None, None
        if project is not None:
            run.project_id = project.project_id
            project_roots = [str(item) for item in getattr(project, "workspace_paths", []) if str(item)]
            run.extra_roots = list(dict.fromkeys([*run.extra_roots, *project_roots]))
            # A project run is scoped to its declared working directories. The
            # primary workspace remains available, alongside any explicitly
            # configured conversation roots.
            remote_workspace = bool(run.workspace and str(run.workspace).startswith("ssh://"))
            project_access_roots = ([] if remote_workspace else
                                    [*([run.workspace] if run.workspace else []),
                                     *[root for root in project_roots if not root.startswith("ssh://")]])
            project_ssh_roots = [root for root in project_roots if root.startswith("ssh://")]
            if project_access_roots:
                run.allowed_paths = list(dict.fromkeys([
                    *[str(Path(item).expanduser().resolve()) for item in run.allowed_paths if not str(item).startswith("ssh://")],
                    *[str(Path(item).expanduser().resolve()) for item in project_access_roots],
                ]))
            if project_ssh_roots:
                if remote_workspace:
                    active_host, _ = ssh_workspaces.parse_workspace(str(run.workspace))
                    project_ssh_roots = [root for root in project_ssh_roots
                                         if ssh_workspaces.parse_workspace(root)[0] == active_host]
                run.allowed_paths = list(dict.fromkeys([*run.allowed_paths, *project_ssh_roots]))
            instructions = (source_data or {}).get("instructions", "")
            if instructions:
                active_skill_instructions = [*active_skill_instructions, {
                    "name": "项目指令", "content": str(instructions),
                }]
    if run.sandbox and (not workspace or str(workspace).startswith("ssh://")):
        invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": "Docker 沙箱需要本机工作目录，不能与 ssh:// 同时使用。",
        }))
        return
    # Bind before the workspace branches: the run.context.sources envelope at the
    # end of this handler reads context_files for every run, including the
    # no-workspace and ssh:// paths that never entered the "elif workspace" block.
    # Bound only inside that branch it raised UnboundLocalError, which killed the
    # websocket for every workspace-less run before the model was ever called.
    context_files = data.get("context_files") or []
    if not isinstance(context_files, list):
        invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": "context_files must be a list",
        }))
        return
    # Same reason as context_files above: run.context.sources reads this for every
    # run, but it was only bound inside the "elif workspace" branch.
    context_conversations = data.get("context_conversations") or []
    if not isinstance(context_conversations, list) or len(context_conversations) > 3:
        invalid_run = RunState(run_id, str(data.get("conversation_id", "")),
                               model_id or getattr(model_mgr, "current_model", ""))
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation",
            "detail": "context_conversations must contain at most three conversation ids",
        }))
        return
    if workspace and str(workspace).startswith("ssh://"):
        try:
            host, remote_root = ssh_workspaces.parse_workspace(str(workspace))
        except ValueError as exc:
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "validation", "detail": str(exc),
            }))
            return
        if data.get("worktree") is not None:
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "validation", "detail": "SSH worktrees are not supported",
            }))
            return
        run.workspace = str(workspace)
        if memory is not None:
            await memory.update_conversation(conv_id, workspace=run.workspace)
    elif workspace:
        workspace_path = Path(workspace).expanduser().resolve()
        if not workspace_path.is_dir():
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "validation", "detail": "workspace directory does not exist",
            }))
            return
        if conversation and conversation.get("worktree_path"):
            workspace_path = Path(conversation["worktree_path"]).resolve()
            if not workspace_path.is_dir():
                invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
                await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                    "category": "validation", "detail": "conversation worktree is missing",
                }))
                return
        worktree_request = data.get("worktree")
        if worktree_request is not None:
            if not isinstance(worktree_request, dict):
                invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
                await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                    "category": "validation", "detail": "worktree must be an object",
                }))
                return
            if not conversation or not conversation.get("worktree_path"):
                try:
                    worktree_data = _server()._worktrees().create(
                        workspace_path, conv_id, worktree_request.get("base_branch"),
                        worktree_request.get("name"),
                    )
                    worktree_hook = await _server()._hook_store().execute("WorktreeCreate", {
                        "conversation_id": conv_id, "worktree_path": worktree_data["worktree_path"],
                        "worktree_branch": worktree_data["worktree_branch"],
                        "base_branch": worktree_data["base_branch"], "cwd": str(workspace_path),
                    }, cwd=str(workspace_path))
                    if worktree_hook.get("blocked"):
                        _server()._worktrees().remove(
                            workspace_path, Path(worktree_data["worktree_path"]),
                            worktree_data["worktree_branch"], force=True,
                        )
                        raise ValueError(str(worktree_hook.get("reason") or "WorktreeCreate hook blocked creation"))
                    if memory is not None:
                        await memory.update_conversation(
                            conv_id, workspace=str(workspace_path), **worktree_data,
                        )
                    workspace_path = Path(worktree_data["worktree_path"])
                except (OSError, ValueError) as exc:
                    invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
                    await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                        "category": "validation", "detail": str(exc),
                    }))
                    return
        run.workspace = str(workspace_path)
        if run.sandbox:
            run.allowed_paths = [str(workspace_path.resolve())]
        if not run.ephemeral and memory is not None and getattr(memory, "_db", None) is not None and not (conversation and conversation.get("worktree_path")):
            await memory.update_conversation(conv_id, workspace=str(Path(workspace).expanduser().resolve()))
        if context_files and not run.workspace:
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "validation", "detail": "context_files require a workspace",
            }))
            return
        context_blocks: list[str] = []
        total_context_bytes = 0
        for relative in context_files:
            try:
                remaining = max(0, 256 * 1024 - total_context_bytes)
                if run.workspace and run.workspace.startswith("ssh://"):
                    host, remote_root = ssh_workspaces.parse_workspace(run.workspace)
                    rel = Path(str(relative))
                    if rel.is_absolute() or ".." in rel.parts:
                        raise HTTPException(status_code=400, detail="context path escapes workspace")
                    raw = await ssh_workspaces.read_bytes(
                        host, str(PurePosixPath(remote_root).joinpath(*rel.parts)),
                    )
                    chunk = raw[:min(64 * 1024, remaining)]
                    label = f"\n\n[Context file: {relative}]\n{chunk.decode('utf-8', errors='replace')}"
                    if len(raw) > len(chunk):
                        label += "\n[Context file truncated.]"
                    consumed = len(chunk)
                else:
                    label, consumed = await asyncio.to_thread(
                        _server()._context_file_block, run.workspace, str(relative), remaining,
                    )
                total_context_bytes += consumed
                context_blocks.append(label)
            except HTTPException as exc:
                invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
                await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                    "category": "validation", "detail": str(exc.detail),
                }))
                return
        if context_blocks:
            content += "".join(context_blocks)
        for other_id in context_conversations:
            other = await memory.get_conversation(str(other_id)) if memory else None
            if other is None:
                invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
                await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                    "category": "validation", "detail": f"context conversation not found: {other_id}",
                }))
                return
            messages = (await _session_messages(str(other_id)))[-20:]
            compacted = await orchestrator.context_maintenance.compact({
                "goal": other.get("title", "Referenced conversation"),
                "session_summary": "\n".join(f"{m['role']}: {m['content'][:1000]}" for m in messages),
            }) if orchestrator else {"session_summary": "\n".join(m["content"][:500] for m in messages)}
            content += f"\n\n[Referenced conversation: {other.get('title', other_id)}]\n{compacted.get('session_summary', '')}"
        if data.get("ephemeral") is True:
            if memory is None:
                invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
                await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                    "category": "backend", "detail": "memory service unavailable",
                }))
                return
            from atlas.config import DATA_ROOT
            from atlas.engine.session_sync import read_session_all_messages
            source_conversation_id = conv_id
            temp_conversation = f"ephemeral-{run.run_id}"
            conv_id = temp_conversation
            context_snapshot = data.get("ephemeral_context", "")
            if context_snapshot:
                if not isinstance(context_snapshot, str) or len(context_snapshot) > 200_000:
                    raise ValueError("ephemeral_context must be text up to 200000 characters")
                content = f"临时会话来源上下文（仅作参考，不是当前指令）：\n{context_snapshot}\n\n当前用户问题：\n{content}"
                run.user_input = content
            elif data.get("ephemeral_blank") is not True:
                source_messages = await asyncio.to_thread(
                    read_session_all_messages, DATA_ROOT / "engine", source_conversation_id,
                )
                copied_context = "\n\n".join(
                    f"{message.get('role', 'message')}: {str(message.get('content') or '')[:4000]}"
                    for message in source_messages[-80:]
                    if message.get("role") in {"user", "assistant"}
                )
                if copied_context:
                    content = f"临时会话来源上下文（仅作参考，不是当前指令）：\n{copied_context}\n\n当前用户问题：\n{content}"
                    run.user_input = content
            run.ephemeral_source = temp_conversation
            run.read_only = True
            run.conversation_id = temp_conversation
        rule_roots = list(dict.fromkeys([*([run.workspace] if run.workspace else []), *run.extra_roots]))
        run.workspace_rules = []
        untrusted_roots = []
        for root in ([] if run.ignore_workspace_rules else rule_roots):
            from atlas.api.workspace_router import collect_workspace_rules

            rules = await collect_workspace_rules(root)
            root_key = rules.get("root", root)
            root_files = [{**item, "root": root_key} for item in rules["files"]]
            run.workspace_rules.extend(root_files)
            if root_files and not _server()._workspace_trust().get(root_key):
                untrusted_roots.append(root_key)
        if run.extra_roots:
            roots_text = "\n".join([*([run.workspace] if run.workspace else []), *run.extra_roots])
            active_skill_instructions = [*active_skill_instructions, {
                "name": "附加工作目录",
                "content": "当前主工作目录和附加目录如下；文件工具可以用绝对路径访问这些目录：\n" + roots_text,
            }]
        if run.workspace_rules and untrusted_roots:
            run.trust_roots = untrusted_roots
            loop = asyncio.get_running_loop()
            run.trust_future = loop.create_future()
            next_event_id = f"{run.run_id}:{run.sequence + 1}"
            run.trust_event_id = next_event_id
            trust_env = run.next_envelope("rules.trust_required", {
                "event_id": next_event_id, "root": untrusted_roots[0],
                "roots": untrusted_roots,
                "files": [{"path": item["path"], "bytes": item["bytes"]}
                          | {"root": item["root"]} for item in run.workspace_rules
                          if item["root"] in untrusted_roots],
            })
            run.status = "waiting"
            await manager.send(conn_id, trust_env)
        else:
            await manager.send(conn_id, run.next_envelope("rules.loaded", {
                "files": [{"path": item["path"], "bytes": item["bytes"]}
                          for item in run.workspace_rules],
            }))
    # Bind the prompt to the run outside every workspace branch. It used to be set
    # only inside the ``elif workspace`` block, so any run without a workspace
    # reached ``persist_run`` below with ``user_input`` still "", and the stored
    # transcript lost the request itself (436 rows in runtime_runs, 432 of them
    # blank — every blank one was workspace-less). Bind it after the ephemeral
    # rewrite so the persisted text matches what the model actually received.
    run.user_input = content
    await manager.send(conn_id, run.next_envelope("run.context.sources", {
        "sources": [
            *[{"kind": "context_file", "path": str(path), "loaded": True} for path in context_files],
            *[{"kind": "user_file", "path": str(item.get("name") or item.get("path") or "attachment"), "loaded": True}
              for item in data.get("files", []) if isinstance(item, dict)],
            *[{"kind": "user_attachment", "path": str(item.get("name") or "attachment"), "loaded": True}
              for item in data.get("attachments", []) if isinstance(item, dict)],
            *([{"kind": "image_attachment", "path": f"{len(image_attachments)} image attachment(s)", "loaded": True}] if image_attachments else []),
            *media_sources,
            *[{"kind": "workspace_rule", "path": str(item.get("path") or ""), "bytes": item.get("bytes"), "loaded": True}
              for item in run.workspace_rules],
            *[{"kind": "referenced_conversation", "id": str(item)} for item in context_conversations],
            *[{"kind": "skill", "name": str(item.get("name") or "")}
              for item in active_skill_instructions if isinstance(item, dict) and item.get("name")],
            {"kind": "workspace", "path": str(run.workspace or "No workspace"), "loaded": bool(run.workspace)},
            {"kind": "system_prompt", "path": "Atlas runtime prompt and conversation policy", "loaded": "runtime-generated"},
            {"kind": "memory", "path": "Retrieved memory (conditional on conversation memory settings)", "loaded": "runtime-dependent"},
            {"kind": "tool_schema", "path": "Registered tools for this run", "loaded": "runtime-dependent"},
            {"kind": "tool_reads", "path": "Files read by tools appear as tool.started/tool.completed events", "loaded": True},
        ],
    }))
    manager.runs[run_id] = run
    manager.conn_runs[conn_id] = run_id
    if not run.ephemeral:
        await manager.persist_run(run)

    # MCP is an optional enrichment. Never put its process launch/handshake on
    # the first-turn critical path: a run can begin with the tools already
    # registered, or without them while background startup continues.
    startup = getattr(services, "startup", None)
    if startup is not None and "mcp" in startup.snapshot():
        if startup.state("mcp") == "failed":
            notice = run.next_envelope("run.recovery.notice", {
                "message": "MCP 启动失败，本次运行继续使用当前可用工具；可在设置→工具中检查 MCP 服务。",
            })
            await manager.send(conn_id, notice)

    # Standing orders are matching-turn guidance. They never create a scheduled
    # run; selection also writes a bounded audit receipt for each matched order.
    try:
        from atlas.standing_orders import DEFAULT_OWNER_ID, matching_orders

        standing_owner_id = agent_key or DEFAULT_OWNER_ID
        matched_orders = matching_orders(standing_owner_id, run.workspace, content)
        if matched_orders:
            active_skill_instructions = list(active_skill_instructions or [])
            active_skill_instructions.extend({
                "name": f"standing-order:{item['id']}",
                "content": "常驻指令（仅在匹配的 Agent turn 中生效）：\n" + item["instruction"],
            } for item in matched_orders)
    except Exception:
        log.exception("standing_orders.inject_failed", agent_id=agent_key or "atlas")

    # Start the run in background so we can keep receiving messages
    execute = _server()._execute_run(
            conn_id, run, content, model_id,
            plan_state=recovered_plan,
            image_attachments=image_attachments,
            active_skill_instructions=active_skill_instructions,
            workspace=run.workspace,
            workspace_rules=run.workspace_rules,
            mode=run.mode,
            manager=manager,
            resume_from=resume_from if isinstance(resume_from, str) else None,
        )
    execution = _server()._execute_after_rule_trust(run, execute) if run.trust_future else execute
    if agent_profile is not None:
        # W10: project the persistent agent's runtime status around the run
        # (working while it lives → idle/waiting_user once it settles).
        _server()._set_agent_status_quiet(agent_key, "working")
        run.task = asyncio.create_task(
            _server()._project_agent_run_status(run, agent_key, execution))
    else:
        run.task = asyncio.create_task(execution)


async def _project_agent_run_status(run: RunState, agent_id: str, execution: Any) -> None:
    """Persistent-agent status projection wrapper (W10): working → idle/waiting_user."""
    try:
        await execution
    finally:
        status = "waiting_user" if run.status == "waiting" else "idle"
        detail = ""
        if run.status == "failed":
            for envelope in reversed(run.events):
                if envelope.get("event") == "run.failed":
                    detail = str((envelope.get("data") or {}).get("detail") or "")
                    break
        _server()._set_agent_status_quiet(agent_id, status, detail)


async def _execute_after_rule_trust(run: RunState, execution: Any) -> None:
    if run.trust_future is None or not await run.trust_future:
        run.status = "cancelled"
        await _server().runtime_mgr.send_run(run, run.next_envelope("run.cancelled", {}), "")
        return
    run.trust_future = None
    run.status = "running"
    run.waiting_for = None
    run.updated_at = datetime.now(UTC).isoformat()
    await _server().runtime_mgr.persist_run(run)
    await execution


async def _resolve_active_skill_instructions(
    names: Any,
) -> list[dict[str, str]]:
    """Resolve client-selected Skill names through the canonical activation gate."""
    if names is None:
        names = []
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError("active_skills must be a list of Skill names")
    if len(names) > 8:
        raise ValueError("at most eight Skills may be active for one run")
    if _server().skill_mgr is None:
        if names:
            raise ValueError("Skill Manager is unavailable")
        return []

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    connected = _server().mcp_client.get_server_names() if _server().mcp_client else None
    configured = _server().mcp_client.get_configured_server_names() if _server().mcp_client else None
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        info = _server().skill_mgr.get_skill(name)
        if info is None:
            raise ValueError(f"Skill not found: {name}")
        record = _server().skill_registry.get(name, info.version) if _server().skill_registry else None
        lifecycle = (record or {}).get("lifecycle", {})
        if lifecycle.get("trust_state") in {"revoked", "blocked"} or lifecycle.get(
            "state"
        ) in {"quarantined", "removed"}:
            raise PermissionError(f"Skill lifecycle policy blocks activation: {name}")
        content = await _server().skill_mgr.activate(
            name,
            connected_servers=connected,
            configured_servers=configured,
            registry=_server().skill_registry,
        )
        if content is None:
            raise ValueError(f"Skill content is unavailable: {name}")
        result.append({"name": name, "version": info.version, "content": content})
    return result


async def _execute_external_agent(
    run: RunState,
    content: str,
    workspace: str | None,
    emit: Any,
) -> tuple[str, list[str]]:
    """Run the selected external Agent and translate its events into Atlas events."""
    if _server().agent_backend_host is None:
        raise RuntimeError("外部 Agent 服务当前不可用。")
    if not workspace:
        raise RuntimeError("运行外部 Agent 前，请先为当前对话选择工作目录。")
    if workspace.startswith("ssh://"):
        raise RuntimeError("外部 Agent 目前不能在 SSH 工作目录中运行。")

    store = getattr(_server().orchestrator, "checkpoints", None) if _server().orchestrator else None
    if store is not None:
        store.create_checkpoint(
            workspace, ["."], run_id=run.run_id,
            conversation_id=run.conversation_id,
        )

    key = (run.conversation_id, run.executor)
    session_id = _server().external_conversation_sessions.get(key)
    if session_id not in _server().agent_backend_host.sessions:
        session = await _server().agent_backend_host.start(run.executor, workspace)
        session_id = session.id
        _server().external_conversation_sessions[key] = session_id
    await _server().agent_backend_host.send(session_id, content)

    response: list[str] = []
    tools: dict[str, dict[str, Any]] = {}

    async def consume() -> None:
        async for event in _server().agent_backend_host.events(session_id):
            if event.type in {"done", "agent_end"}:
                continue
            normalized = normalize_external_event(event.type, event.data, tools)
            for name, payload in normalized:
                if name == "reply.delta":
                    response.append(str(payload.get("content", "")))
                    # Same stream event Atlas's own replies use, so clients render it unchanged.
                    name = "message.delta"
                if name == "run.failed":
                    raise RuntimeError(str(payload.get("detail", "外部 Agent 执行失败。")))
                await emit(name, payload)

    stream_task = asyncio.create_task(consume())
    cancel_task = asyncio.create_task(run.cancel_event.wait())
    try:
        done, _pending = await asyncio.wait(
            {stream_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_task in done and run.cancel_event.is_set():
            with suppress(Exception):
                await _server().agent_backend_host.cancel(session_id)
            with suppress(Exception):
                await _server().agent_backend_host.close(session_id)
            _server().external_conversation_sessions.pop(key, None)
            stream_task.cancel()
            await asyncio.gather(stream_task, return_exceptions=True)
            raise asyncio.CancelledError
        await stream_task
    finally:
        cancel_task.cancel()
        await asyncio.gather(cancel_task, return_exceptions=True)

    if store is not None:
        store.create_checkpoint(
            workspace, ["."], run_id=run.run_id,
            conversation_id=run.conversation_id,
        )
    changed: list[str] = []
    try:
        result = await asyncio.to_thread(
            subprocess.run, ["git", "-C", workspace, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        changed = [
            line[3:].strip().replace("\\", "/")
            for line in result.stdout.splitlines() if len(line) > 3
        ]
    except (OSError, subprocess.SubprocessError):
        pass
    return "".join(response), changed


async def _handle_resume(
    conn_id: str, data: dict[str, Any], manager: RuntimeManager | None = None,
) -> None:
    """Replay events after a given sequence number."""
    manager = manager or _server().runtime_mgr
    run_id = data.get("run_id", "")
    try:
        after_seq = max(0, int(data.get("after_sequence", 0)))
    except (TypeError, ValueError):
        after_seq = 0
    run = manager.runs.get(run_id)
    if not run:
        missing = RunState(run_id, "", "")
        missing.sequence = after_seq
        env = missing.next_envelope("run.failed", {
            "category": "interrupted",
            "detail": "Run state is no longer available; start a new run to continue.",
        })
        await manager.send(conn_id, env)
        return

    manager.conn_runs[conn_id] = run_id

    # Keep live events behind the replay so sequence order is preserved.
    async with run.event_lock:
        for env in list(run.events):
            if env["sequence"] > after_seq:
                await manager.send(conn_id, env)


def _resume_notice(run: RunState) -> str:
    """Human wording for a resumed run, chosen by where it was interrupted."""
    if run.resume_attempts > 1:
        return (
            f"后台服务再次中断了这次任务，已第 {run.resume_attempts} 次自动续跑。"
            "已完成的步骤不会重做。"
        )
    return (
        "后台服务中断，这次任务已自动续跑。已完成的步骤不会重做，"
        "中断时未拿到结果的工具会被重新检查。"
    )


# The resumed turn's own user message. The original request is already in the
# session history, so this only has to say "keep going from where it stopped" —
# the same shape as the plan-approval continuation.
_RESUME_INSTRUCTION = (
    "后台服务刚刚中断了这次任务（不是你的操作导致的，也不是用户的新要求）。"
    "请从中断处继续完成原来那件事，不要重新开始：\n"
    "1. 先检查工作区和已完成的部分，确认中断前到底做到了哪一步；\n"
    "2. 只做还没完成的部分，不要重复已经完成的改动；\n"
    "3. 中断时没有拿到结果的工具调用，要重新确认它当前的实际状态，不要假设它成功或失败；\n"
    "4. 做完后照常验证并汇报。"
)


async def resume_run_after_restart(
    run: RunState, manager: RuntimeManager | None = None,
) -> bool:
    """Continue a run that a service restart interrupted. Returns True if taken.

    The resume reuses the normal execution path (``_execute_run``) so the
    resumed run has exactly the same tools, permissions, hooks and event
    contract as any other run — there is no second executor to keep in sync.
    ``continuation=True`` suppresses ``run.started``, so the client does not
    render a duplicate bubble for a request it already shows, and the kernel's
    per-turn repair fills in any tool call whose result was lost, so side
    effects are never replayed.
    """
    manager = manager or _server().runtime_mgr
    active = manager.runs.get(run.run_id)
    if active is not None and active.task is not None and not active.task.done():
        log.info("run.resume_skipped", run_id=run.run_id, reason="already_active")
        return False
    if not (run.conversation_id or "").strip():
        log.info("run.resume_skipped", run_id=run.run_id, reason="no_conversation")
        return False
    if run.executor != "atlas":
        # A non-Atlas executor (external agent, group turn) drives its own
        # thread; replaying it here would run the wrong loop.
        log.info("run.resume_skipped", run_id=run.run_id, reason="not_atlas_executor")
        return False

    context = dict(run.resume_context or {})
    workspace = context.get("workspace") or run.workspace
    run.workspace = workspace
    run.mode = context.get("mode") or run.mode or "act"
    run.permission_mode = context.get("permission_mode") or run.permission_mode
    _restore_permission_policy(run, context)
    run.allowed_paths = context.get("allowed_paths") or run.allowed_paths
    run.extra_roots = context.get("extra_roots") or run.extra_roots
    run.read_only = bool(context.get("read_only"))
    run.profile_id = context.get("profile_id") or run.profile_id
    run.project_id = context.get("project_id") or run.project_id
    run.reasoning_effort = context.get("reasoning_effort") or run.reasoning_effort
    try:
        from atlas.project_context import validate_config_override

        run.config_override = validate_config_override(context.get("config_override")) if context.get("config_override") else None
    except ValueError:
        log.warning("run.resume_invalid_config_override", run_id=run.run_id)
        run.config_override = None
    run.ignore_project_config = bool(context.get("ignore_project_config"))
    run.ignore_workspace_rules = bool(context.get("ignore_workspace_rules"))

    # Rebuild the workspace rule context the same way a fresh run does, so a
    # resumed run is subject to the rules that exist now rather than the ones
    # that existed before the restart. A root that is no longer trusted must
    # NOT be replayed silently: the original turn asked the user, and asking
    # again on their behalf is the same as answering for them.
    run.workspace_rules = []
    rule_roots = list(dict.fromkeys([*([workspace] if workspace else []), *run.extra_roots]))
    untrusted_roots = []
    for root in ([] if run.ignore_workspace_rules else rule_roots):
        from atlas.api.workspace_router import collect_workspace_rules

        try:
            rules = await collect_workspace_rules(root)
        except Exception:
            log.exception("run.resume_rules_failed", run_id=run.run_id, root=root)
            continue
        root_key = rules.get("root", root)
        root_files = [{**item, "root": root_key} for item in rules["files"]]
        run.workspace_rules.extend(root_files)
        if root_files and not _server()._workspace_trust().get(root_key):
            untrusted_roots.append(root_key)

    if untrusted_roots:
        # Hand the decision back to the user instead of resuming: leave the run
        # failed (it is already observable) and say why.
        log.info(
            "run.resume_skipped", run_id=run.run_id,
            reason="rules_need_trust", roots=untrusted_roots,
        )
        skipped = run.next_envelope("run.recovery.notice", {
            "message": (
                "这次任务的中断恢复被跳过了：工作区规则文件需要你重新确认信任后才能继续。"
                "请重新发送这条消息。"
            ),
            "reason": "rules_need_trust",
            "roots": untrusted_roots,
        })
        await manager.send_run(run, skipped, fallback_conn_id=f"resume:{run.run_id}")
        return False

    # A resumed run keeps the extra roots it was started with; the model needs
    # to be told they exist, exactly as the original turn told it.
    active_skill_instructions = None
    if run.extra_roots:
        roots_text = "\n".join([*([workspace] if workspace else []), *run.extra_roots])
        active_skill_instructions = [{
            "name": "附加工作目录",
            "content": "当前主工作目录和附加目录如下；文件工具可以用绝对路径访问这些目录：\n" + roots_text,
        }]

    # No live WebSocket is attached to a recovered run: send_run's fallback id
    # keeps every envelope persisted against the right conversation.
    conn_id = f"resume:{run.run_id}"
    manager.runs[run.run_id] = run
    manager.conn_runs[conn_id] = run.run_id
    run.status = "running"
    run.waiting_for = None
    await manager.persist_run(run)

    # The shutdown persisted this run as failed. Nothing the resume emits
    # overwrites that status on the client — a recovery notice is only a
    # caption — so say "running" explicitly, before the notice, or the run
    # stays failed in the UI while it is visibly working again.
    await manager.send_run(
        run,
        run.next_envelope("run.status", {"status": "running"}),
        fallback_conn_id=conn_id,
    )

    notice = run.next_envelope("run.recovery.notice", {
        "message": _resume_notice(run),
        "reason": "service_restart",
        "resume_attempt": run.resume_attempts,
    })
    await manager.send_run(run, notice, fallback_conn_id=conn_id)

    run.task = asyncio.create_task(
        _execute_run(
            conn_id, run, _RESUME_INSTRUCTION, None,
            plan_state=run.plan_state,
            active_skill_instructions=active_skill_instructions,
            workspace=workspace,
            workspace_rules=run.workspace_rules,
            mode=run.mode,
            continuation=True,
            manager=manager,
        ),
        name=f"atlas-resume-{run.run_id}",
    )
    return True


def _effective_reasoning_effort(model_mgr: Any, model_id: str, requested: str | None) -> str | None:
    """The effort to send for this run, or None when the model cannot reason.
    Aliases such as ``wb-pool`` are not litellm names, so look the model up first and trust its
    declared capabilities. "Default" means medium (OpenAI's own default): some providers
    (DeepSeek behind the WorkBuddy proxy) only think, and stream their reasoning, when an
    effort is sent at all.
    """
    # The request path is already validated before it reaches this helper.
    # Avoid ModelManager.list_models(): it enriches every catalog row with
    # models.dev capabilities and costs seconds on a warm desktop run.
    if requested:
        return requested
    config: dict[str, Any] = {}
    if model_mgr is not None:
        with suppress(Exception):
            finder = getattr(model_mgr, "_find_model", None)
            found = finder(model_id) if callable(finder) else None
            if isinstance(found, dict):
                config = found
    capabilities = config.get("capabilities") if isinstance(config.get("capabilities"), dict) else {}
    # The model's own setting (atlas.toml / user settings) applies when the run picks none.
    # "off" must reach the wire as an explicit switch: DeepSeek-family models think when
    # nothing is sent, so dropping to None (or the old "medium" default) left it on.
    configured = str(config.get("reasoning_effort") or capabilities.get("reasoning_effort") or "").strip().lower()
    if configured in {"off", "none", "disabled"} or config.get("supports_reasoning") is False:
        return "off"
    efforts = None
    if model_mgr is not None and config:
        with suppress(Exception):
            resolver = getattr(model_mgr, "_model_reasoning_efforts", None)
            efforts = resolver(config) if callable(resolver) else None
    supported = bool(
        capabilities.get("supports_reasoning")
        or config.get("supports_reasoning")
        or (isinstance(efforts, list) and efforts)
    )
    if not supported:
        return None
    return configured or "medium"


def _map_tool_runtime_event(
    event: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    """Map Agent tool events to the Runtime Event Protocol payloads."""
    event_type = event.get("type")
    if event_type == "tool_call":
        return "tool.started", {
            "tool_call_id": event.get("id", ""),
            "name": event.get("name", ""),
            "arguments": event.get("arguments", {}),
        }
    if event_type == "tool_result":
        data = {
            "tool_call_id": event.get("id", ""),
            "name": event.get("name", ""),
            "result": event.get("content", []),
            "is_error": event.get("is_error", False),
        }
        output_contract = event.get("output_contract")
        if not isinstance(output_contract, dict):
            from atlas.agent.tool_catalog import output_contracts_for_tools

            output_contract = output_contracts_for_tools([{
                "function": {"name": str(event.get("name") or "")},
            }]).get(str(event.get("name") or ""))
        if isinstance(output_contract, dict):
            data["output_contract"] = output_contract
        if event.get("data") is not None:
            data["execution"] = event["data"]
            if isinstance(event["data"], dict) and event["data"].get("full_output_path"):
                data["full_output_path"] = event["data"]["full_output_path"]
        if data["is_error"]:
            data["error_category"] = event.get("error_category", "tool")
        return "tool.completed", data
    if event_type == "tool_output":
        return "tool.output", {
            "tool_call_id": event.get("id", ""),
            "name": event.get("name", ""),
            "execution_id": event.get("execution_id", ""),
            "stream": event.get("stream", "stdout"),
            "text": event.get("text", ""),
        }
    return None


def _validated_image_attachments(value: Any) -> list[str]:
    """Accept a small set of inline raster images for a single model run."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 4:
        raise ValueError("attachments must contain at most four images")
    result: list[str] = []
    total_bytes = 0
    pattern = re.compile(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})\Z")
    for item in value:
        if not isinstance(item, str):
            raise ValueError("image attachments must be data URLs")
        match = pattern.fullmatch(item)
        if not match:
            raise ValueError("only PNG, JPEG, and WebP data URLs are accepted")
        try:
            decoded = base64.b64decode(match.group(2), validate=True)
        except ValueError as exc:
            raise ValueError("image attachment has invalid base64 data") from exc
        total_bytes += len(decoded)
        if len(decoded) > 4 * 1024 * 1024 or total_bytes > 8 * 1024 * 1024:
            raise ValueError("image attachments exceed the 8 MiB run limit")
        result.append(item)
    return result


async def _execute_run(
    conn_id: str,
    run: RunState,
    content: str,
    model_id: str | None,
    plan_state: dict[str, Any] | None = None,
    image_attachments: list[str] | None = None,
    active_skill_instructions: list[dict[str, str]] | None = None,
    workspace: str | None = None,
    workspace_rules: list[dict[str, Any]] | None = None,
    mode: str = "act",
    continuation: bool = False,
    manager: RuntimeManager | None = None,
    resume_from: str | None = None,
) -> None:
    """Execute agent run, emitting Runtime Event envelopes."""
    execution_started_at = time.perf_counter()
    timing_tool_starts: dict[str, float] = {}
    try:
        from atlas.logs import append_run_event
        append_run_event(run.run_id, "api_timing", stage="execute_run_entered", elapsed_ms=0)
    except Exception:
        append_run_event = None

    def record_api_timing(stage: str, **fields: Any) -> None:
        if append_run_event is None or run.ephemeral:
            return
        try:
            append_run_event(run.run_id, "api_timing", stage=stage,
                             elapsed_ms=round((time.perf_counter() - execution_started_at) * 1000),
                             **fields)
        except Exception:
            log.debug("run.timing_log_failed", run_id=run.run_id, stage=stage, exc_info=True)
    dependency_mark = time.perf_counter()

    def dependency_timing(stage: str) -> None:
        nonlocal dependency_mark
        now = time.perf_counter()
        record_api_timing(stage, duration_ms=round((now - dependency_mark) * 1000))
        dependency_mark = now

    manager = manager or _server().runtime_mgr
    dependency_timing("runtime_manager_resolved")
    services = manager.services
    dependency_timing("services_resolved")
    model_mgr = getattr(services, "model_mgr", None) or getattr(_server(), "model_mgr", None)
    dependency_timing("model_manager_resolved")
    reasoning_effort = _effective_reasoning_effort(model_mgr, model_id or run.model, run.reasoning_effort)
    dependency_timing("reasoning_effort_resolved")
    memory = getattr(services, "memory", None) or getattr(_server(), "memory", None)
    dependency_timing("memory_resolved")
    orchestrator = getattr(services, "orchestrator", None) or getattr(_server(), "orchestrator", None)
    dependency_timing("orchestrator_resolved")
    local_execution = getattr(services, "local_execution", None) or getattr(_server(), "local_execution", None)
    dependency_timing("local_execution_resolved")
    sandbox_manager = getattr(services, "sandbox_manager", None) or getattr(_server(), "sandbox_manager", None)
    dependency_timing("sandbox_manager_resolved")
    scheduler = getattr(services, "scheduler", None) or getattr(_server(), "scheduler", None)
    dependency_timing("scheduler_resolved")
    usage_ledger = getattr(services, "usage_ledger", None) or getattr(_server(), "usage_ledger", None)
    dependency_timing("usage_ledger_resolved")
    assert orchestrator is not None
    assert memory is not None
    orchestrator_events = None
    record_api_timing("execution_dependencies_ready")
    checkpoint_task: asyncio.Task[Any] | None = None

    def kernel_owns_lifecycle_hooks() -> bool:
        return run.executor == "atlas"

    async def emit(event: str, data: dict[str, Any]) -> None:
        """Emit an event envelope to the client."""
        # Derived session views depend on run events, so drop the affected cache
        # entries here — this is the one funnel every run event passes through, so
        # a projection never has to remember to invalidate itself.
        try:
            SessionProjections.invalidate_for(services, event)
        except Exception:  # noqa: BLE001 - a cache miss must never fail a run
            log.warning("session_projections.invalidate_failed", evt=event, exc_info=True)
        if not run.ephemeral and event in {"subtask.started", "subtask.progress", "subtask.output", "subtask.completed",
                     "subtask.group_completed", "subtask.background_completed"}:
            try:
                from atlas.config import DATA_ROOT
                from atlas.engine.session_sync import append_session_message

                await asyncio.to_thread(
                    append_session_message, DATA_ROOT / "engine", run.conversation_id,
                    "system", "", {
                        "display_kind": "subtask_activity",
                        "activity": {"event": event, **data},
                        "run_id": run.run_id, "sequence": run.sequence + 1,
                    },
                )
            except Exception:
                log.exception("subtask_activity.persist_failed", evt=event,
                              subtask_id=data.get("subtask_id"), run_id=run.run_id)
        if event == "run.started":
            record_api_timing("run_started_emitted")
        elif event in {"run.completed", "run.failed", "run.cancelled"}:
            record_api_timing("terminal_event", terminal=event)
        if not run.ephemeral and event in {"component.push", "canvas.update"}:
            # Runtime events live in memory only. Keep interactive components and
            # shared-canvas updates in the canonical transcript for reopen/reload.
            try:
                from atlas.config import DATA_ROOT
                from atlas.engine.session_sync import append_session_message
                await asyncio.to_thread(
                    append_session_message, DATA_ROOT / "engine", run.conversation_id,
                    "system", "", {"display_kind": "structured_component" if event == "component.push" else "agent_canvas",
                                   "component" if event == "component.push" else "canvas": data,
                                   "run_id": run.run_id, "sequence": run.sequence + 1},
                )
            except Exception:
                log.exception("runtime_widget.persist_failed", evt=event, run_id=run.run_id)
        event_kind = {"run.completed": "completion", "run.failed": "failure", "approval.required": "approval"}.get(event)
        if event_kind and not run.ephemeral:
            try:
                from atlas.api.u4_router import _read, push_event_enabled
                from atlas.api.channel_router import get_channel_manager

                push = ((_read().get("settings") or {}).get("mobile_push") or {})
                if push_event_enabled({"mobile_push": push}, event_kind):
                    channel = str(push.get("channel") or "").strip()
                    chat_id = str(push.get("chat_id") or "").strip()
                    if channel and chat_id:
                        channel_manager = get_channel_manager()
                        text = f"Atlas {event_kind}：{str(data.get('title') or data.get('message') or run.user_input or run.run_id)[:300]}"
                        await channel_manager.send(channel, chat_id, text)
            except Exception:
                log.warning("u4.mobile_push_failed", evt=event, run_id=run.run_id, exc_info=True)
        if event == "run.started":
            data = {
                **data,
                "environment": "docker" if run.sandbox else
                    "ssh" if (workspace or "").startswith("ssh://") else "local",
                "executor": run.executor,
            }
            if run.sandbox:
                data["image"] = run.sandbox.get("image") or "python:3.12-slim"
            if (workspace or "").startswith("ssh://"):
                with suppress(Exception):
                    data["host"] = ssh_workspaces.parse_workspace(workspace)[0]
        env = run.next_envelope(event, data)
        await manager.send_run(run, env, fallback_conn_id=conn_id)
        if event in {"run.completed", "run.failed", "run.cancelled"}:
            _spawn_background(_capture_evolution_outcome(run, event))
        if event in {"run.started", "run.completed", "run.failed"}:
            hooks = _server()._hook_store()
            bridge_event_alias = not kernel_owns_lifecycle_hooks()
            _spawn_background(hooks.execute(event, {
                "run_id": run.run_id, "conversation_id": run.conversation_id,
                "tool_name": "", "parameters": {}, "result": data,
            }, cwd=workspace, emit=emit, bridge_event_alias=bridge_event_alias))
        if event in {"run.completed", "run.failed"} and scheduler is not None:
            _spawn_background(scheduler.dispatch_event(event, {
                "run_id": run.run_id, "conversation_id": run.conversation_id,
                "workspace": workspace or "",
            }))

    usage_positions = {
        str(row.get("request_id")): index for index, row in enumerate(run.usage)
        if row.get("request_id")
    }

    async def record_usage(raw_usage: dict[str, Any]) -> None:
        if raw_usage.get("request_sent") is False:
            # Failure report for a request that never reached the provider: not a
            # model request, so it must not enter run.usage (it would inflate
            # request counts and null the aggregated totals).
            return
        row = dict(raw_usage)
        # Provider usage reports the actual prompt token count. Pair it with
        # Atlas's capability metadata so the UI can show truthful window use.
        # Do not invent a limit when the model catalog has no capability data.
        if not row.get("context_limit") and model_mgr is not None:
            usage_model = str(row.get("model") or model_id or run.model or "")
            context_limit = model_mgr.context_window_for_model(usage_model)
            if context_limit:
                row["context_limit"] = context_limit
        request_id = str(row.get("request_id") or "")
        duplicate = bool(request_id and request_id in usage_positions)
        if duplicate:
            run.usage[usage_positions[request_id]] = row
        else:
            if request_id:
                usage_positions[request_id] = len(run.usage)
            run.usage.append(row)
        if run.reasoning_effort and run.reasoning_effort_applied is None:
            run.reasoning_effort_applied = reasoning_effort is not None
            row["reasoning_effort_applied"] = run.reasoning_effort_applied
        if usage_ledger is not None and not duplicate and not run.ephemeral:
            event_model = str(row.get("model") or model_id or run.model)
            model_config = {}
            if model_mgr is not None:
                with suppress(Exception):
                    model_config = model_mgr._find_model(event_model) or {}
                if not model_config:
                    model_config = next((item for item in getattr(model_mgr, "_models", ())
                                         if item.get("litellm_model") == event_model
                                         or item.get("id") == event_model
                                         or str(item.get("litellm_model") or "").rsplit("/", 1)[-1] == event_model
                                         or str(item.get("native_model") or "") == event_model), {})
            try:
                await usage_ledger.record(
                    run_id=run.run_id, conversation_id=run.conversation_id,
                    subtask_id=row.get("subtask_id"), model=event_model,
                    started_at=run.started_at, usage=row,
                    price=model_config.get("price"),
                    native_model=model_config.get("native_model"),
                )
            except Exception:
                log.exception(
                    "run.usage_record_failed", run_id=run.run_id,
                    request_id=request_id,
                )
        await emit("run.usage", row)

    async def cancel_local_foreground() -> None:
        if local_execution is not None:
            await local_execution.cancel_run(run.run_id)

    async def check_pause_cancel() -> bool:
        """Wait while paused; return True if cancelled."""
        if run.cancel_event.is_set():
            return True
        # Wait for unpause
        while not run.pause_event.is_set():
            if run.cancel_event.is_set():
                return True
            await asyncio.sleep(0.1)
        return run.cancel_event.is_set()

    async def persist_plan(value: dict[str, Any]) -> None:
        run.plan_state = value
        await manager.persist_run(run)
        await emit("run.plan.updated", {
            "plan": value,
            "resumed": plan_state is not None,
        })

    record_api_timing("run_callback_setup_complete")
    try:
        if run.sandbox:
            docker_status = await sandbox_manager.status()
            if not docker_status["available"]:
                raise RuntimeError(docker_status["detail"])
            await sandbox_manager.start(run.run_id, workspace or "", run.sandbox)
        # Emit run.started
        if not continuation:
            started_data = {
                "status": "running", "phase": "planning", "content": content,
            }
            await emit("run.started", started_data)
            record_api_timing("run_start_setup_complete")
            mcp_client = getattr(services, "mcp_client", None) or getattr(_server(), "mcp_client", None)
            if mcp_client is not None:
                try:
                    progress = mcp_client.get_runtime_status().get("startup_progress", [])
                    for item in progress[-24:]:
                        if isinstance(item, dict) and item.get("state") in {
                            "connecting", "initializing", "discovering_tools", "ready", "failed",
                        }:
                            await emit("mcp.startup.progress", item)
                except Exception as exc:
                    log.warning("mcp.startup_progress_unavailable", reason=type(exc).__name__)

        # Keep only Atlas metadata; the engine SessionDB owns the transcript.
        try:
            await memory.save_conversation_metadata(run.conversation_id, title_hint=content)
            record_api_timing("conversation_metadata_saved")
        except Exception as e:
            log.exception("run.user_message_save_failed")
            run.status = "failed"
            await emit("run.failed", {
                "category": "backend",
                "detail": f"Unable to save user message: {e}",
            })
            return

        if workspace and not workspace.startswith("ssh://"):
            try:
                from atlas.config import DATA_ROOT
                from atlas.engine.session_sync import read_session_all_messages
                from atlas.rewind import checkpoint_before_turn

                prior_messages = await asyncio.to_thread(
                    read_session_all_messages, DATA_ROOT / "engine", run.conversation_id,
                )
                tail_id = prior_messages[-1].get("id") if prior_messages else None
                after_message_id = tail_id if isinstance(tail_id, str) and tail_id else None
                checkpoint_cancel = threading.Event()
                checkpoint_task = asyncio.create_task(asyncio.to_thread(
                    checkpoint_before_turn,
                    run.conversation_id,
                    run.run_id,
                    workspace,
                    after_message_id=after_message_id,
                    cancel_event=checkpoint_cancel,
                ))
                def checkpoint_done(task: asyncio.Task[Any]) -> None:
                    try:
                        checkpoint_id = task.result()
                        record_api_timing("workspace_checkpoint_saved", checkpoint_id=bool(checkpoint_id))
                        log.info("rewind.checkpoint_created", conversation_id=run.conversation_id,
                                 run_id=run.run_id, checkpoint_id=checkpoint_id)
                    except Exception as exc:
                        record_api_timing("workspace_checkpoint_failed", error_type=type(exc).__name__)
                        log.exception("rewind.checkpoint_before_turn_failed", conversation_id=run.conversation_id,
                                      run_id=run.run_id, workspace=workspace)
                checkpoint_task.add_done_callback(checkpoint_done)
            except Exception:
                log.exception(
                    "rewind.checkpoint_before_turn_failed",
                    conversation_id=run.conversation_id,
                    run_id=run.run_id,
                    workspace=workspace,
                )

        if run.executor != "atlas":
            if await check_pause_cancel():
                run.status = "cancelled"
                await emit("run.cancelled", {"reason": run.end_conversation_reason}
                            if run.end_conversation_reason else {})
                return
            await emit("run.status", {"status": "running"})
            await emit("run.phase", {"phase": "execution"})
            try:
                response, _changed_files = await _server()._execute_external_agent(
                    run, content, workspace, emit,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("run.external_agent_failed")
                run.status = "failed"
                await emit("run.failed", {
                    "category": "external_agent", "detail": str(exc),
                })
                return
            if response and not run.ephemeral:
                with suppress(Exception):
                    from atlas.config import DATA_ROOT
                    from atlas.engine.session_sync import append_session_message
                    await asyncio.to_thread(
                        append_session_message, DATA_ROOT / "engine", run.conversation_id,
                        "assistant", response, {"executor": run.executor, "run_id": run.run_id},
                    )
                await emit("message.completed", {"content": response})
            run.status = "completed"
            await emit("run.completed", {
                "result": "completed", "model": run.model,
                "usage": _server()._sum_usage(run.usage),
                "changes": _server()._run_change_summary(run.run_id),
            })
            return

        if await check_pause_cancel():
            run.status = "cancelled"
            await cancel_local_foreground()
            await emit("run.cancelled", {"reason": run.end_conversation_reason}
                        if run.end_conversation_reason else {})
            return

        await emit("run.status", {"status": "running"})
        await emit("run.phase", {"phase": "execution"})

        # Run the agent orchestrator
        full_response = ""
        record_api_timing("orchestrator_setup_complete")

        # Build approval callback that emits approval.required and waits for response
        async def approval_callback(
            approval_event_id: str, tool_name: str, tool_args: dict[str, Any]
        ) -> str:
            """Emit approval.required and wait for client response."""
            approval_policy = getattr(run, "approval_policy", None)
            if approval_policy == "never":
                return "rejected" if "sandbox_permissions" in tool_args else "allowed-once"
            if (approval_policy != "ask" and
                    str(getattr(run, "permission_mode", "") or "").lower() in {"full_access", "yolo"}):
                return "allow"
            public_input = {key: value for key, value in tool_args.items()
                            if key not in {"subtask_id", "_reviewer_reason", "_approval_reason",
                                           "_approval_scope", "_approval_resource",
                                           "_approval_no_always"}}
            resource = tool_args.get("_approval_resource") or tool_args.get("resource")
            permission = None if run.ephemeral or tool_args.get("_approval_no_always") else approval_permission_scope(
                run.workspace, tool_name, public_input,
                str(resource) if resource else None,
            )
            approval_payload = {
                "approval_id": approval_event_id,
                "description": str(tool_args.get("_approval_reason") or tool_args.get("reason") or
                                    f"Agent 请求执行工具 {tool_name}，需要你的确认。"),
                "input": public_input,
                "tool": tool_name,
                "allow_always_available": permission is not None,
            }
            if tool_args.get("_approval_scope") or tool_args.get("scope"):
                approval_payload["scope"] = str(tool_args.get("_approval_scope") or tool_args["scope"])
            if tool_args.get("_approval_resource") or tool_args.get("resource"):
                approval_payload["resource"] = str(tool_args.get("_approval_resource") or tool_args["resource"])
            if tool_args.get("_reviewer_reason"):
                approval_payload["reviewer_reason"] = str(tool_args["_reviewer_reason"])
            if tool_args.get("subtask_id"):
                approval_payload["subtask_id"] = tool_args["subtask_id"]

            async def record_decision(value: Any, source: str) -> str:
                from atlas.approval_outcome import normalize as normalize_approval

                outcome = normalize_approval(value)
                await _persist_approval_lifecycle(run.conversation_id, "approval/decided", {
                    "approval_id": approval_event_id,
                    "tool": tool_name,
                    "outcome": outcome,
                    "source": source,
                })
                return outcome

            async def record_asked() -> None:
                await _persist_approval_lifecycle(run.conversation_id, "approval/asked", {
                    "approval_id": approval_event_id,
                    "tool": tool_name,
                    "description": approval_payload["description"],
                    "permission_scope": permission,
                })

            if permission is not None:
                approval_payload["permission_scope"] = permission
                if approval_always_allowed(permission):
                    await record_asked()
                    await emit("approval.required", {**approval_payload, "previously_allowed": True})
                    await emit("approval.responded", {
                        "event_id": approval_event_id, "choice": "allow_always",
                        "permission_scope": permission, "source": "persisted_grant",
                    })
                    return await record_decision("allowed-once", "persisted_grant")
            approval_future = run.approval_futures.get(approval_event_id)
            if approval_future is None:
                approval_future = asyncio.get_running_loop().create_future()
                run.approval_futures[approval_event_id] = approval_future
            run.approval_contexts[approval_event_id] = {
                "permission_scope": permission,
                "allow_always_available": permission is not None,
            }
            run.status = "waiting"
            await record_asked()
            await emit("approval.required", approval_payload)

            services = manager.services
            bridge = getattr(services, "gateway_bridge", None) if services else None
            try:
                if bridge is not None and bridge.owns_run(run.run_id):
                    decision = await bridge.request_approval(
                        run, approval_event_id, approval_payload["description"],
                    )
                    return await record_decision(decision, "gateway")
                telegram = getattr(services, "telegram_service", None) if services else None
                if run.telegram_user_id is not None and telegram is not None:
                    telegram_future = await telegram.request_approval(
                    run.telegram_user_id, run.run_id, approval_event_id,
                    f"需要确认执行 {tool_name}。",
                    )
                    cancel_waiter = asyncio.create_task(run.cancel_event.wait())
                    try:
                        done, _ = await asyncio.wait(
                            {telegram_future, cancel_waiter}, timeout=600,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if telegram_future in done:
                            return await record_decision(telegram_future.result(), "telegram")
                        if not approval_future.done():
                            approval_future.set_result("unavailable")
                        return await record_decision("unavailable", "timeout")
                    finally:
                        cancel_waiter.cancel()
                        await asyncio.gather(cancel_waiter, return_exceptions=True)
                cancel_waiter = asyncio.create_task(run.cancel_event.wait())
                try:
                    done, _ = await asyncio.wait(
                        {approval_future, cancel_waiter}, timeout=600,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if approval_future in done:
                        return await record_decision(approval_future.result(), "user")
                    if not approval_future.done():
                        approval_future.set_result("cancelled" if run.cancel_event.is_set() else "unavailable")
                    outcome = "cancelled" if run.cancel_event.is_set() else "unavailable"
                    return await record_decision(outcome, "cancel" if outcome == "cancelled" else "timeout")
                finally:
                    cancel_waiter.cancel()
                    await asyncio.gather(cancel_waiter, return_exceptions=True)
            finally:
                run.approval_futures.pop(approval_event_id, None)
                run.approval_contexts.pop(approval_event_id, None)
                if run.status == "waiting":
                    run.status = "running"
                    run.waiting_for = None
                    run.updated_at = datetime.now(UTC).isoformat()
                    await manager.persist_run(run)

        async def input_callback(
            call_id: str, question: str, options: list[str] | None,
            details: dict[str, Any] | None = None,
        ) -> str:
            event_id = f"input:{run.run_id}:{call_id}"
            loop = asyncio.get_running_loop()
            future: asyncio.Future[str] = loop.create_future()
            run.input_futures[event_id] = future
            run.status = "waiting"
            await emit("input.required", {
                "event_id": event_id, "question": question,
                "options": options if isinstance(options, list) else None,
                **(details or {}),
            })
            while not future.done():
                if run.cancel_event.is_set():
                    run.input_futures.pop(event_id, None)
                    raise asyncio.CancelledError
                await asyncio.sleep(0.1)
            answer = future.result()
            run.status = "running"
            run.waiting_for = None
            run.updated_at = datetime.now(UTC).isoformat()
            await manager.persist_run(run)
            return answer

        async def plan_approval_callback(plan: dict[str, Any]) -> bool:
            if run.cancel_event.is_set():
                return False
            future = asyncio.get_running_loop().create_future()
            run.plan_future = future
            run.status = "waiting"
            await emit("run.plan.proposed", {
                "plan": plan, "event_id": f"plan:{run.run_id}",
            })
            try:
                while not future.done():
                    if run.cancel_event.is_set():
                        return False
                    await asyncio.sleep(0.1)
                return future.result().get("action") == "approve"
            finally:
                run.plan_future = None
                if run.status == "waiting":
                    run.status = "running"

        run.plan_approval_callback = plan_approval_callback

        def plan_mode_callback(active: bool) -> None:
            run.dynamic_plan_mode = active
            # The kernel hands tools a shallow copy of the run, so a mode write
            # inside a tool handler never reaches this object. The callback is
            # the shared channel: keeping ``mode`` in sync here means the prompt
            # builder sees the same live value the tool gate enforces.
            run.mode = "plan" if active else "act"

        run.plan_mode_callback = plan_mode_callback

        def end_conversation_callback(reason: str) -> None:
            run.end_conversation_reason = reason
            run.cancel_event.set()

        run.end_conversation_callback = end_conversation_callback

        async def subtask_started(
            subtask_id: str, goal: str, backend: str,
            group_data: dict[str, Any] | None = None,
        ) -> asyncio.Event:
            cancel_event = asyncio.Event()
            run.subtasks[subtask_id] = {
                "subtask_id": subtask_id, "status": "running", "progress": "子 Agent 已启动。",
                "cancel_event": cancel_event, **(group_data or {}),
            }
            await manager.save_subtask({
                "parent_run_id": run.run_id, "subtask_id": subtask_id,
                "status": "running", "goal": goal, "backend": backend,
                "workspace": run.workspace or "", "model": run.model,
                "recovery_point": {
                    "conversation_id": run.conversation_id,
                    "workspace": run.workspace or "", "goal": goal,
                    "backend": backend, "model": run.model,
                },
            })
            await emit("subtask.started", {
                "subtask_id": subtask_id, "goal": goal, "backend": backend,
                "parent_run_id": run.run_id, **(group_data or {}),
            })
            return cancel_event

        async def subtask_progress(
            subtask_id: str, text: str, group_data: dict[str, Any] | None = None,
        ) -> None:
            if subtask_id in run.subtasks:
                run.subtasks[subtask_id]["progress"] = text
            event = "subtask.output" if group_data else "subtask.progress"
            await emit(event, {
                "subtask_id": subtask_id, "text": text, **(group_data or {}),
            })

        async def subtask_completed(
            subtask_id: str, status: str, summary: str, duration_ms: int,
            group_data: dict[str, Any] | None = None,
        ) -> None:
            entry = run.subtasks.get(subtask_id)
            if entry:
                entry.update({"status": status, "progress": summary, "result": summary})
            persisted = await manager.get_subtask(run.run_id, subtask_id) or {}
            await manager.save_subtask({
                **persisted,
                "parent_run_id": run.run_id, "subtask_id": subtask_id,
                "status": status, "goal": persisted.get("goal", ""),
                "backend": persisted.get("backend", "atlas"),
                "workspace": persisted.get("workspace", run.workspace or ""),
                "model": persisted.get("model", run.model),
                "session_id": str((group_data or {}).get("session_id") or ""),
                "recovery_point": persisted.get("recovery_point") or {},
            })
            await emit("subtask.completed", {
                "subtask_id": subtask_id, "status": status,
                "summary": summary, "duration_ms": duration_ms,
                **(group_data or {}),
            })
            if entry and entry.get("background") and not entry.get("group_id"):
                if not run.ephemeral and memory is not None and run.conversation_id:
                    with suppress(Exception):
                        from atlas.config import DATA_ROOT
                        from atlas.engine.session_sync import append_session_message
                        await asyncio.to_thread(
                            append_session_message, DATA_ROOT / "engine", run.conversation_id,
                            "assistant", f"后台子 Agent {subtask_id} 已完成：\n{summary}",
                            {"kind": "subtask.background_completed", "subtask_id": subtask_id},
                        )
                await emit("subtask.background_completed", {
                    "subtask_id": subtask_id, "title": str(persisted.get("goal") or subtask_id),
                    "summary": summary,
                })

        async def subtask_group_completed(payload: dict[str, Any]) -> None:
            await emit("subtask.group_completed", payload)
            if payload.get("background"):
                summary = str(payload.get("summary", ""))[:2000]
                if not run.ephemeral and memory is not None and run.conversation_id:
                    with suppress(Exception):
                        from atlas.config import DATA_ROOT
                        from atlas.engine.session_sync import append_session_message
                        await asyncio.to_thread(
                            append_session_message, DATA_ROOT / "engine", run.conversation_id,
                            "assistant", f"后台 Worker 组 {payload.get('subtask_id', '')} 已完成：\n{summary}",
                            {"kind": "subtask.background_completed",
                             "subtask_id": payload.get("subtask_id", "")},
                        )
                await emit("subtask.background_completed", {
                    "subtask_id": payload.get("subtask_id", ""),
                    "title": payload.get("title") or payload.get("goal") or "Worker 组",
                    "summary": summary,
                })

        checkpoint_failure_reported = False

        async def user_hook(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
            nonlocal checkpoint_failure_reported
            if (event_name == "PreToolUse" and checkpoint_task is not None
                    and not checkpoint_failure_reported):
                done, _ = await asyncio.wait({checkpoint_task}, timeout=0.5)
                if not done:
                    checkpoint_cancel.set()
                    if not checkpoint_failure_reported:
                        checkpoint_failure_reported = True
                        await emit("run.recovery.notice", {
                            "message": "执行前工作区快照超过 0.5 秒预算，已取消快照并继续执行。",
                            "detail": "InterruptedError: pre-tool checkpoint time budget exceeded",
                        })
                else:
                    try:
                        await checkpoint_task
                    except Exception as exc:
                        # A failed optional rewind snapshot must never turn every
                        # tool invocation into a tool error. The background
                        # completion callback records the traceback and timing.
                        if not checkpoint_failure_reported:
                            checkpoint_failure_reported = True
                            await emit("run.recovery.notice", {
                                "message": "执行前工作区快照失败，本轮继续执行。",
                                "detail": f"{type(exc).__name__}: {exc}",
                            })
            hook_payload = dict(payload)
            bridge_event_alias = bool(hook_payload.pop("__atlas_bridge_event_alias__", True))
            hook_store = _server()._hook_store()
            event_result = await hook_store.execute(event_name, {
                "run_id": run.run_id, "conversation_id": run.conversation_id,
                **hook_payload,
            }, cwd=workspace, emit=emit, bridge_event_alias=bridge_event_alias)
            session_key = run.conversation_id or run.run_id
            if event_name == "SessionStart":
                old_cwd = hook_store._watch_cwds.get(str(session_key))
                if old_cwd and old_cwd != str(Path(workspace or os.getcwd()).resolve()):
                    cwd_result = await hook_store.execute("CwdChanged", {
                        "conversation_id": run.conversation_id, "session_id": run.conversation_id,
                        "run_id": run.run_id, "old_cwd": old_cwd,
                        "new_cwd": workspace or os.getcwd(), "cwd": workspace or os.getcwd(),
                    }, cwd=workspace, emit=emit)
                    event_result["watch_paths"] = list(dict.fromkeys([
                        *(event_result.get("watch_paths") or []),
                        *(cwd_result.get("watch_paths") or []),
                    ]))
                hook_store.start_file_watcher(
                    str(session_key), event_result.get("watch_paths") or [],
                    cwd=workspace, callback=user_hook,
                )
            elif event_name == "CwdChanged":
                hook_store.start_file_watcher(
                    str(session_key), event_result.get("watch_paths") or [],
                    cwd=workspace, callback=user_hook,
                )
            elif event_name == "SessionEnd":
                hook_store.stop_file_watcher(str(session_key))
            return event_result

        async def publish_runtime_event(event: dict[str, Any]) -> None:
            if event.get("type") == "session.title":
                await emit("session.title", {
                    "title": event.get("title", ""),
                    "title_source": event.get("title_source", ""),
                    "accepted": bool(event.get("accepted", False)),
                })
            elif event.get("type") == "run_usage":
                usage = event.get("usage")
                if isinstance(usage, dict):
                    await record_usage(usage)

        async def ssh_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if not workspace or not workspace.startswith("ssh://"):
                raise RuntimeError("SSH workspace is unavailable")
            return await ssh_workspaces.call_tool(name, arguments, workspace, run_id=run.run_id)

        async def ssh_checkpoint(action: str, arguments: dict[str, Any]) -> Any:
            if not workspace or not workspace.startswith("ssh://"):
                raise RuntimeError("SSH workspace is unavailable")
            if action == "create":
                return await ssh_workspaces.create_checkpoint(
                    workspace, list(arguments.get("paths", [])), run.run_id,
                )
            if action == "list":
                target = str(arguments.get("workspace") or workspace)
                return await ssh_workspaces.list_checkpoints(target)
            return await ssh_workspaces.restore_checkpoint(
                workspace, str(arguments.get("checkpoint_id", "")),
            )

        async def sandbox_tool(run_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            from atlas.engine.tool_permissions import authorize_sandbox_escalation

            call_args = dict(arguments)
            if "sandbox_permissions" in call_args:
                authorization = await authorize_sandbox_escalation(
                    call_args, approval_callback, tool_name=name,
                    tool_call_id=str(call_args.get("tool_call_id") or f"sandbox:{run_id}:{uuid.uuid4()}"),
                )
                if not authorization["approved"]:
                    outcome = authorization["approval_outcome"]
                    detail = (
                        f"Sandbox permission request was not approved ({outcome})."
                    )
                    return {"data": {"error": detail, **authorization},
                            "content": [{"type": "text", "text": detail}], "is_error": True}
            else:
                call_args["sandbox_permissions"] = run.sandbox_mode or "workspace-write"
            return await sandbox_manager.call_tool(run_id, name, call_args)

        orchestrator_events = orchestrator.run(
            message=content,
            conversation_id=run.conversation_id,
            model=model_id,
            cancel_event=run.cancel_event,
            pause_event=run.pause_event,
            approval_callback=approval_callback,
            plan_state=plan_state,
            plan_update_callback=persist_plan,
            source_run_id=str(resume_from or run.run_id),
            image_attachments=image_attachments,
            active_skill_instructions=active_skill_instructions,
            inbox=await _run_inbox(run),
            run_id=run.run_id,
            steer_queue=run.steer_queue,
            input_callback=input_callback,
            runtime_event_callback=publish_runtime_event,
            workspace=workspace,
            workspace_trusted=bool(workspace and _server()._workspace_trust().get(
                str(Path(workspace).expanduser().resolve()), False,
            )),
            workspace_rules=workspace_rules,
            ignore_workspace_rules=run.ignore_workspace_rules,
            mode=mode,
            tool_mode=run.tool_mode,
            tool_allow=run.tool_allow,
            tool_deny=run.tool_deny,
            read_only=run.read_only or run.ephemeral,
            permission_mode=run.permission_mode,
            allowed_paths=run.allowed_paths,
            user_hook_callback=user_hook,
            ssh_tool_callback=ssh_tool,
            ssh_checkpoint_callback=ssh_checkpoint,
            sandbox_tool_callback=sandbox_tool if run.sandbox else None,
            sandbox_enabled=bool(run.sandbox),
            project_id=run.project_id,
            task_id=run.task_id,
            reasoning_effort=reasoning_effort,
            session_env=run.session_env,
            subtask_started=subtask_started,
            subtask_progress=subtask_progress,
            subtask_completed=subtask_completed,
            subtask_group_completed=subtask_group_completed,
            force_plan=(mode == "plan"),
            ephemeral=run.ephemeral,
            bypass_prompt_cache=run.bypass_prompt_cache,
        )
        from atlas.project_context import project_scoped_events

        async for event in project_scoped_events(
            run.project_id, orchestrator_events, config_override=run.config_override,
            ignore_project_config=run.ignore_project_config,
            session_id=run.conversation_id,
        ):
            if await check_pause_cancel():
                run.status = "cancelled"
                await cancel_local_foreground()
                await emit("run.cancelled", {"reason": run.end_conversation_reason}
                            if run.end_conversation_reason else {})
                return

            # Map orchestrator events to runtime protocol
            etype = event.get("type", "")

            if etype == "tool_call":
                tool_id = str(event.get("id") or event.get("call_id") or "")
                if tool_id:
                    timing_tool_starts[tool_id] = time.perf_counter()
                    record_api_timing("tool_started", tool_id=tool_id,
                                      tool=str(event.get("name") or "tool"))
            elif etype == "tool_result":
                tool_id = str(event.get("id") or event.get("call_id") or "")
                started = timing_tool_starts.pop(tool_id, None)
                if started is not None:
                    record_api_timing("tool_completed", tool_id=tool_id,
                                      tool=str(event.get("name") or "tool"),
                                      duration_ms=round((time.perf_counter() - started) * 1000))

            if etype == "chunk":
                chunk_content = event.get("content", "")
                full_response += chunk_content
                await emit("message.delta", {"content": chunk_content})

            elif etype == "artifact_created":
                artifact = {
                    "path": event.get("path", ""),
                    "kind": event.get("kind", "document"),
                    "bytes": event.get("bytes", 0),
                }
                # ``present`` declares a title and summary for the deliverable
                # card; Office creators only supply a path.
                for key in ("title", "summary"):
                    if event.get(key):
                        artifact[key] = event[key]
                await emit("artifact.created", artifact)

            elif etype == "check.results":
                await emit("check.results", event.get("data", {}))

            elif etype in ("tool_call", "tool_result", "tool_output"):
                mapped = _server()._map_tool_runtime_event(event)
                if mapped is not None:
                    await emit(*mapped)

            elif etype == "tool_preparing":
                await emit("tool.preparing", {
                    "index": event.get("index", 0),
                    "attempt": event.get("attempt", 1),
                    "tool_call_id": event.get("call_id", ""),
                    "name": event.get("name", ""),
                    "chars": event.get("chars", 0),
                    "preview": event.get("preview", ""),
                })

            elif etype == "run_steered":
                await emit("run.steered", {
                    "content": event.get("content", ""),
                    "event_id": event.get("event_id", ""),
                    "immediate": bool(event.get("immediate", False)),
                })

            elif etype == "subtask_steered":
                await emit("subtask.steered", {
                    "subtask_id": event.get("subtask_id", ""),
                    "text": event.get("text", ""),
                })

            elif etype == "run_todos":
                await emit("run.todos", {
                    "revision": event.get("revision", 0),
                    "todos": event.get("todos", []),
                })

            elif etype == "moa_references":
                await emit("moa.references", {
                    "models": event.get("models", []),
                    "references": event.get("references", []),
                    "latency_ms": event.get("latency_ms", 0),
                })

            elif etype == "run_model_switched":
                await emit("run.model_switched", event.get("data", {}))

            elif etype == "computer_frame":
                await emit("computer.frame", event.get("data", {}))

            elif etype == "session.title":
                await emit("session.title", {
                    "title": event.get("title", ""),
                    "title_source": event.get("title_source", ""),
                    "accepted": bool(event.get("accepted", False)),
                })

            elif etype == "run_status":
                await emit("run.status", {
                    "status": event.get("status", "running"),
                    "text": event.get("text", ""),
                })

            elif etype in {
                "process.completed", "process.notification", "run.compaction.progress", "run.recovery.notice",
                # C6 新增队列事件：wire 事件与内部 type 同名，data 原样透传。
                "lsp.diagnostics", "review.findings", "application_receipt",
            }:
                await emit(etype, event.get("data", {}))

            elif etype == "safety_reviewed":
                await emit("safety.reviewed", event.get("data", {}))

            elif etype == "run_verify_nudge":
                await emit("run.verify_nudge", event.get("data", {}))

            elif etype == "run_usage":
                usage = event.get("usage", {})
                if isinstance(usage, dict):
                    await record_usage(usage)

            elif etype == "context_sources":
                await emit("run.context.sources", {
                    "sources": event.get("sources", []),
                })

            elif etype == "context.window.switched":
                await emit("context.window.switched", event.get("data", {}))

            elif etype == "chapter.marked":
                await emit("chapter.marked", event.get("data", {}))

            elif etype == "canvas.update":
                await emit("canvas.update", event.get("data", {}))

            elif etype == "component.push":
                await emit("component.push", event.get("data", {}))

            elif etype == "approval_required":
                # Already emitted by the approval_callback above;
                # no need to re-emit here.
                pass

            elif etype == "plan_updated":
                # The plan state is persisted and emitted by persist_plan.
                pass

            elif etype == "done":
                if mode == "plan" and run.dynamic_plan_mode:
                    run.status = "waiting"
                    loop = asyncio.get_running_loop()
                    run.plan_future = loop.create_future()
                    plan_event_id = f"plan:{run.run_id}"
                    await emit("run.plan.proposed", {
                        "plan": run.plan_state or {
                            "goal": content, "steps": full_response,
                        },
                        "event_id": plan_event_id,
                    })
                    await manager.persist_run(run)
                    while not run.plan_future.done():
                        if run.cancel_event.is_set():
                            run.status = "cancelled"
                            await emit("run.cancelled", {"reason": run.end_conversation_reason}
                                        if run.end_conversation_reason else {})
                            return
                        await asyncio.sleep(0.1)
                    approval = run.plan_future.result()
                    run.plan_future = None
                    if approval.get("action") != "approve":
                        run.status = "cancelled"
                        await emit("run.cancelled", {"reason": run.end_conversation_reason}
                                    if run.end_conversation_reason else {})
                        return
                    run.status = "running"
                    run.waiting_for = None
                    run.updated_at = datetime.now(UTC).isoformat()
                    await manager.persist_run(run)
                    edits = approval.get("edits", "").strip()
                    # The approval itself must tell the model to act: the continuation
                    # used to send an empty user message, and real models answered it
                    # with a summary instead of running a single tool.
                    instruction = (
                        "The plan above is approved. Execute it now: carry out every step "
                        "with the tools (do not only describe it), verify the result, "
                        "then report what was done."
                    )
                    if edits:
                        instruction += f"\n\nApply these changes to the plan first: {edits}"
                    await _execute_run(
                        conn_id, run, instruction,
                        model_id, plan_state=run.plan_state,
                        image_attachments=image_attachments,
                        active_skill_instructions=active_skill_instructions,
                        workspace=workspace, workspace_rules=workspace_rules,
                        mode="act", continuation=True, manager=manager,
                    )
                    return
                if full_response:
                    await emit("message.completed", {"content": full_response})
                await emit("run.phase", {"phase": "final"})

            elif etype == "error":
                run.status = "failed"
                category = event.get("category", "runtime")
                failure_event = {
                    "category": category,
                    "detail": event.get("detail", "Unknown error"),
                }
                for key in ("service", "reason", "retry_after_seconds", "status", "limit_event"):
                    if event.get(key) is not None:
                        failure_event[key] = event[key]
                await emit("run.failed", failure_event)
                return

        # Run completed successfully
        run.status = "completed"
        if full_response.strip() and run.conversation_id and not run.ephemeral:
            try:
                from atlas.config import DATA_ROOT
                from atlas.engine.session_sync import evaluate_goal_after_turn

                goal_decision = await asyncio.to_thread(
                    evaluate_goal_after_turn, DATA_ROOT / "engine",
                    run.conversation_id, full_response,
                    _atlas_goal_judge(_server().model_mgr),
                )
            except Exception:
                log.exception("conversation.goal_evaluation_failed",
                            conversation_id=run.conversation_id)
                goal_decision = None
            if goal_decision is not None:
                if goal_decision.get("message"):
                    await emit("goal.updated", {
                        "status": goal_decision.get("status"),
                        "verdict": goal_decision.get("verdict"),
                        "reason": goal_decision.get("reason"),
                        "message": goal_decision.get("message"),
                        "planning_turn": bool(goal_decision.get("planning_turn")),
                        "plan_attempts": goal_decision.get("plan_attempts"),
                        "milestones": goal_decision.get("milestones"),
                    })
                if goal_decision.get("planning_turn"):
                    try:
                        from atlas.engine.session_sync import record_goal_event

                        await asyncio.to_thread(
                            record_goal_event, DATA_ROOT / "engine", run.conversation_id,
                            "goal.planning_turn", {
                                "attempt": goal_decision.get("plan_attempts"),
                                "max_attempts": goal_decision.get("max_plan_attempts"),
                                "milestones": goal_decision.get("milestones", 0),
                                "expiring": goal_decision.get("plan_gate_expiring", False),
                            }, getattr(run, "run_id", None),
                        )
                    except Exception:
                        log.warning("conversation.goal_planning_event_failed",
                                    conversation_id=run.conversation_id)
                continuation_prompt = goal_decision.get("continuation_prompt")
                if goal_decision.get("should_continue") and continuation_prompt:
                    run.status = "running"
                    await emit("goal.continuation", {
                        "status": goal_decision.get("status"),
                        "reason": goal_decision.get("reason"),
                    })
                    await _execute_run(
                        conn_id, run, str(continuation_prompt), model_id,
                        image_attachments=image_attachments,
                        active_skill_instructions=active_skill_instructions,
                        workspace=workspace, workspace_rules=workspace_rules,
                        mode="act", continuation=True, manager=manager,
                    )
                    return
        await emit("run.completed", {
            "result": "completed",
            "model": run.model,
            "usage": _server()._sum_usage(run.usage),
            "changes": _server()._run_change_summary(run.run_id),
        })

    except asyncio.CancelledError:
        run.status = "cancelled"
        await cancel_local_foreground()
        await emit("run.cancelled", {"reason": run.end_conversation_reason}
                    if run.end_conversation_reason else {})
    except Exception as e:
        log.exception("run.runtime_failed")
        run.status = "failed"
        await emit("run.failed", {"category": "runtime", "detail": str(e)})
    finally:
        close_events = getattr(orchestrator_events, "aclose", None)
        if close_events is not None:
            await close_events()
        if run.sandbox:
            with suppress(Exception):
                await sandbox_manager.stop(run.run_id)
        if run.ephemeral:
            manager.runs.pop(run.run_id, None)
            if manager.conn_runs.get(conn_id) == run.run_id:
                manager.conn_runs.pop(conn_id, None)
