"""Atlas FastAPI + WebSocket server."""

from __future__ import annotations

import asyncio
import base64
import fnmatch
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shlex
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

import aiosqlite
import httpx
import structlog
from fastapi import (
    Body,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import BaseModel

from atlas.agent.capabilities import (
    AgentCapabilityRegistry,
    register_skill_capabilities,
    register_skill_catalog_capabilities,
    register_skill_dependency_capability,
    register_skill_discovery_capability,
)
from atlas.agent.checkpoints import ShadowGitCheckpointStore
from atlas.agent.enrichment import (
    AtlasToolBridge,
    CodeActRuntime,
    DelegationService,
    MemoryReflectionBridge,
)
from atlas.agent.orchestrator import AgentOrchestrator
from atlas.agent.planning import TaskPlan
from atlas.asr import ASRManager
from atlas.automation import (
    AutomationEngine,
    AutomationStore,
    get_automation_engine,
    set_automation_engine,
)
from atlas.capabilities.browser.browser_use import BrowserUseAdapter
from atlas.capabilities.coding import ast_grep as ast_grep_capability
from atlas.capabilities.coding.repo_map import repo_map
from atlas.capabilities.computer.cua_backend import CuaBackend
from atlas.capabilities.computer.uia_backend import list_windows as list_uia_windows
from atlas.capabilities.durable.dbos_backend import DurableBackend
from atlas.capabilities.durable.dbos_backend import status as dbos_status
from atlas.channels import ChannelManager
from atlas.channels.adapters import register_builtin_channels
from atlas.config import get_config, load_user_settings, save_user_settings
from atlas.api.runtime import RunState, RuntimeManager
from atlas.api.app_services import AppServices
from atlas.api.application import create_app
from atlas.api.runtime_ws_router import ws_chat
from atlas.api.tools_router import ws_terminal  # noqa: E402 — compat re-export
from atlas.api.models_settings_router import (
    _model_supports_reasoning,  # noqa: E402 — used by run assembly below
)
from atlas.api.usage_router import runtime_protocol  # noqa: E402 — compat re-export
from atlas.devices import DeviceRegistry
from atlas.devices.takeover import TakeoverStateMachine
from atlas.gateway_service import GatewayBridge
from atlas.groups import DispatcherNotBound, GroupOrchestrator, TurnConflict
from atlas.groups.store import GroupService, GroupStore
from atlas.heartbeat import HeartbeatService
from atlas.memory.store import MemoryStore
from atlas.models.manager import ModelManager
from atlas.office import MAX_PREVIEW_BYTES, render_office
from atlas.notifications import NotificationBus
from atlas.persistent_agents import PersistentAgentService
from atlas.plugins import PluginRuntime
from atlas.projects import ProjectStore
from atlas.runtime import hub_control
from atlas.runtime.commands import (
    CommandSource,
    UserCommand,
    list_user_commands,
    render_user_command,
)
from atlas.runtime.hooks import HookStore
from atlas.runtime.backend_host import AgentBackendHost
from atlas.runtime.capability_bus import CapabilityBus
from atlas.runtime.external_agents import external_agent_status, normalize_external_event
from atlas.scheduler import AtlasScheduler, ScheduledTask, TaskStatus, TriggerType
from atlas.sandbox import DockerSandboxManager
from atlas.skills import (
    PROJECT_ROOT,
    SKILLS_DIR,
    SkillManager,
    default_skill_sources,
    plugin_skill_sources,
)
from atlas.skills.acquisition import (
    CatalogUnavailableError,
    SkillsShProvider,
    inspect_github_source,
    install_acquisition,
)
from atlas.skills.bundles import PluginBundleDiscovery
from atlas.skills.dependencies import dependency_preflight
from atlas.skills.discovery import SkillDiscovery
from atlas.skills.distribution import inspect_skill_package
from atlas.skills.lifecycle import (
    dependency_states,
    transition_pin,
    transition_trust,
)
from atlas.skills.lifecycle import (
    inspect_skill as inspect_skill_lifecycle,
)
from atlas.skills.lifecycle import (
    remove_skill as remove_lifecycle_skill,
)
from atlas.skills.lifecycle import (
    rollback_skill as rollback_lifecycle_skill,
)
from atlas.skills.lifecycle import (
    update_skill as update_lifecycle_skill,
)
from atlas.skills.registry import SkillRegistry
from atlas.safety.policy import (
    get_log as get_safety_log, get_settings as get_safety_settings,
    rule_catalog as get_safety_rules, update_settings as update_safety_settings,
)
from atlas.ssh import ssh_workspaces
from atlas.tools.computer_use import ComputerUseRuntime
from atlas.tools.custom_tools import CustomToolStore
from atlas.tools.local_execution import LocalExecutionRuntime
from atlas.tools.mcp_client import MCPClient
from atlas.tools.node_runtime import get_node_runtime_status
from atlas.tools.web import WebRuntime
from atlas.tools.web_extract import extract_web
from atlas.usage import UsageLedger
from atlas.telegram import TelegramService
from atlas.task_artifacts import TomlRecordStore, WorktreeService, seed_profiles

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Singletons (populated by lifespan)
# ---------------------------------------------------------------------------

model_mgr: ModelManager | None = None
memory: MemoryStore | None = None
projects: ProjectStore | None = None
durable: DurableBackend | None = None
plugin_runtime: PluginRuntime | None = None
notifications: NotificationBus | None = None
orchestrator: AgentOrchestrator | None = None
mcp_client: MCPClient | None = None
local_execution: LocalExecutionRuntime | None = None
sandbox_manager = DockerSandboxManager()
computer_use: ComputerUseRuntime | None = None
capability_bus: CapabilityBus | None = None
cua_backend: CuaBackend | None = None
browser_use: BrowserUseAdapter | None = None
agent_backend_host: AgentBackendHost | None = None
web_runtime: WebRuntime | None = None
custom_tools: CustomToolStore | None = None
telegram_service: TelegramService | None = None
skill_mgr: SkillManager | None = None
skill_registry: SkillRegistry | None = None
skill_catalog_provider = SkillsShProvider()
SKILL_ACQUISITION_TTL = timedelta(minutes=10)
SKILL_CENTER_TOKEN = os.environ.get("ATLAS_SKILL_CENTER_TOKEN")
skill_acquisitions: dict[str, dict[str, Any]] = {}
skill_dependency_plans: dict[str, dict[str, Any]] = {}
scheduler: AtlasScheduler | None = None
external_agent_status_cache: dict[str, Any] = {}
external_conversation_sessions: dict[tuple[str, str], str] = {}
usage_ledger: UsageLedger | None = None
asr_manager: ASRManager | None = None
# W10 persistent-always-on singletons (populated by lifespan).
channel_manager: ChannelManager | None = None
gateway_bridge: GatewayBridge | None = None
heartbeat_service: HeartbeatService | None = None


def _task_store(kind: str) -> TomlRecordStore:
    return TomlRecordStore(get_config().db_path.parent, kind)


def _kanban_store():
    from atlas.kanban import atlas_kanban_store

    return atlas_kanban_store()


def _profile_store() -> TomlRecordStore:
    store = _task_store("profiles")
    seed_profiles(store)
    return store


def _owns_scheduler_lease() -> bool:
    if scheduler is None:
        return False
    try:
        lease = json.loads(scheduler._lease_path.read_text(encoding="utf-8"))
        return lease.get("token") == scheduler._lease_token
    except (OSError, ValueError, TypeError):
        return False


async def _telegram_submit_task(text: str, user_id: int, service: TelegramService) -> dict[str, str]:
    if memory is None:
        raise RuntimeError("Atlas 资料服务尚未就绪。")
    settings = service.settings()
    title = (text.strip()[:30] or "手机任务").strip()
    conversation_id = await memory.create_conversation(title)
    await memory.update_conversation(
        conversation_id, workspace=settings["default_workspace"] or None,
        permission_mode="ask_writes", source="telegram",
    )
    run_id = uuid.uuid4().hex
    await _handle_run_start("telegram", {
        "run_id": run_id, "conversation_id": conversation_id, "content": text,
        "workspace": settings["default_workspace"] or None,
        "permission_mode": "ask_writes", "telegram_user_id": user_id,
    })
    run = runtime_mgr.runs.get(run_id)
    if run is None or run.task is None:
        raise RuntimeError("任务没有成功启动。")
    await run.task
    messages = await memory.get_conversation_messages(conversation_id, limit=1000)
    answer = next((item["content"] for item in reversed(messages)
                   if item["role"] == "assistant"), "")
    summary = str(answer)[:1500]
    if run.status == "failed":
        failed = next((env.get("data", {}).get("detail", "") for env in reversed(run.events)
                       if env.get("event") == "run.failed"), "任务执行失败。")
        raise RuntimeError(str(failed))
    if run.status == "cancelled":
        raise RuntimeError("任务已停止。")
    changes = _run_change_summary(run_id)
    return {"conversation_id": conversation_id, "run_id": run_id,
            "summary": f"{summary}\n\n改动文件数：{changes['files']}"}


async def _telegram_command(command: str, user_id: int) -> str:
    del user_id
    if memory is None:
        return "Atlas 资料服务尚未就绪。"
    name = command.split(maxsplit=1)[0].split("@", 1)[0].casefold()
    conversations = [item for item in await memory.list_conversations(limit=100)
                     if item.get("source") == "telegram"]
    runs = {run.conversation_id: run for run in runtime_mgr.runs.values()
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
    value = load_user_settings().get("default_workspace")
    return Path(str(value)).expanduser() if value else None


def _require_skill_center_authority(request: Request) -> None:
    supplied = request.headers.get("x-atlas-skill-center-token", "")
    origin = request.headers.get("origin")
    trusted_origin = origin in {
        "null", "http://127.0.0.1:5173", "http://localhost:5173",
        "http://127.0.0.1:4173", "http://localhost:4173",
    }
    if (not SKILL_CENTER_TOKEN or not supplied
            or not secrets.compare_digest(supplied, SKILL_CENTER_TOKEN) or not trusted_origin):
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
    await _run_scheduled_goal(task_id, message)
    return {"status": "completed", "task_id": task_id}


async def _scheduled_goal(task_id: str, message: str) -> None:
    """Durable-first scheduler callback with direct fallback and user notify."""
    if durable is not None and durable.started:
        try:
            await durable.run_agent_task({"task_id": task_id, "message": message})
            if notifications is not None:
                await notifications.notify(
                    "Atlas task finished",
                    f"Scheduled task {task_id} completed. Message: {message[:200]}",
                )
            return
        except Exception as exc:
            log.error("durable.agent_task_failed", task_id=task_id, error=str(exc))
            if notifications is not None:
                await notifications.notify(
                    "Atlas task failed",
                    f"Scheduled task {task_id} failed: {str(exc)[:300]}",
                )
    await _run_scheduled_goal(task_id, message)


_goal_run_locks: dict[str, asyncio.Lock] = {}


def _goal_session_id(task_id: str) -> str:
    return f"scheduled-goal-{task_id}"


async def _persist_hermes_goal_outcome(task_id: str, session_id: str, run_id: str) -> None:
    if memory is None:
        return
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import goal_state

    state = await asyncio.to_thread(goal_state, DATA_ROOT / "engine", session_id)
    if not state:
        return
    if state.get("status") not in {"done", "paused"}:
        return
    verdict = state.get("last_verdict")
    done = state.get("status") == "done" and verdict == "done"
    if state.get("status") == "done":
        status = "completed"
    elif verdict == "blocked" or (
        state.get("status") == "paused" and state.get("paused_reason") != "user-paused"
    ):
        status = "blocked"
    else:
        status = str(state.get("status") or "paused")
    evaluation = {
        "satisfied": done,
        "evidence": str(state.get("last_reason") or "") if done else "",
        "reason": str(state.get("last_reason") or state.get("paused_reason") or ""),
    }
    try:
        await memory.record_goal_outcome(
            goal_id=task_id, goal=str(state.get("goal") or ""), status=status,
            evaluation=evaluation, steps=[], source_conversation_id=session_id,
            source_run_id=run_id,
        )
    except Exception as exc:
        log.warning("goal.outcome_persist_failed", task_id=task_id, error=str(exc))


async def _ensure_goal_migrated(task: ScheduledTask) -> None:
    """Import a pre-C3R schedule objective into Hermes once, then discard its copy."""
    if not task.legacy_goal:
        return
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import goal_state, mutate_goal, record_goal_event, set_goal

    session_id = _goal_session_id(task.id)
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
    await scheduler.update_task(task.id, action="goal", status=TaskStatus.ACTIVE)


async def _run_scheduled_goal(task_id: str, message: str = "") -> None:
    """Run a scheduled goal using Hermes GoalManager as its only lifecycle authority."""
    del message
    if scheduler is None:
        return
    task = scheduler.get_task(task_id)
    if task is None:
        return
    await _ensure_goal_migrated(task)

    session_id = _goal_session_id(task_id)
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import (
        evaluate_goal_after_turn, goal_state, mutate_goal, record_goal_event,
    )
    home = DATA_ROOT / "engine"
    if orchestrator is None:
        state = await asyncio.to_thread(goal_state, home, session_id)
        detail = "Agent orchestrator is unavailable."
        await asyncio.to_thread(record_goal_event, home, session_id, "execution.error", {"detail": detail})
        await asyncio.to_thread(mutate_goal, home, session_id, "pause", detail)
        await _record_goal_failure(task_id, uuid.uuid4().hex, str((state or {}).get("goal", "")),
                                  "runtime", detail)
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
                async for event in orchestrator.run(
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
                failed = True
                failure_detail = "Goal execution raised an exception."
            if failed:
                await asyncio.to_thread(record_goal_event, home, session_id, "execution.error", {
                    "detail": failure_detail,
                }, run_id)
                await _record_goal_failure(task_id, run_id, objective, "runtime", failure_detail)
                await asyncio.to_thread(
                    mutate_goal, home, session_id, "pause", failure_detail,
                )
                await _persist_hermes_goal_outcome(task_id, session_id, run_id)
                return

            # Reload before evaluating: pause, clear, or replace may have happened while the
            # model was running. Never apply an old response to a replacement goal.
            if not response and memory is not None and message_id:
                messages = await memory.get_conversation_messages(session_id, limit=1000)
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
            )
            await asyncio.to_thread(record_goal_event, home, session_id, "goal.evaluated", {
                "verdict": decision.get("verdict"),
                "reason": decision.get("reason", ""),
                "status": decision.get("status"),
            }, run_id)
            if decision.get("verdict") == "blocked":
                await _persist_hermes_goal_outcome(task_id, session_id, run_id)
                return
            if not decision.get("should_continue"):
                await _persist_hermes_goal_outcome(task_id, session_id, run_id)
                return
            prompt = decision.get("continuation_prompt") or objective


async def _record_goal_failure(
    task_id: str, run_id: str, message: str, category: str, detail: str,
) -> None:
    """Store goal failures in the P10B advisory reflection store."""
    if memory is None:
        return
    try:
        await memory.record_agent_reflection(
            category=category,
            component="goal_scheduler",
            summary=f"Goal {task_id} failed: {detail}",
            resolution_hint="Review the failure and validate a retry before continuing.",
            source_conversation_id=f"scheduled-goal-{task_id}",
            source_run_id=run_id,
            model=getattr(getattr(orchestrator, "_model_mgr", None), "current_model", None),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# W10 persistent-always-on seams (heartbeat host / automation / channel bridge)
# ---------------------------------------------------------------------------


def _agent_service() -> PersistentAgentService:
    """The lifespan-injected persistent-agent singleton (router accessor)."""
    from atlas.api.agent_router import get_agent_service

    return get_agent_service()


def _resolve_agent_for_run(agent_id: str) -> dict[str, Any] | None:
    """agent_id → run-start merge config; ``None`` = unknown / not persistent."""
    try:
        return _agent_service().resolve_agent_run_config(agent_id)
    except KeyError:
        return None


def _set_agent_status_quiet(agent_id: str, status: str, error: str = "") -> None:
    """Persistent-agent status projection that never breaks a run."""
    try:
        _agent_service().set_status(agent_id, status, error)
    except Exception as exc:  # noqa: BLE001 — projection is best-effort
        log.debug("agent.status_projection_failed", agent_id=agent_id, error=str(exc))


def _channel_agent_profile(agent_id: str) -> dict[str, Any] | None:
    """Agent profile for the gateway's permission-mode ladder (binding → profile → default)."""
    try:
        return _agent_service().get(agent_id)
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
            return _agent_service().get_heartbeat(agent_id)
        except KeyError:
            return {}  # unknown agent → disabled default (HeartbeatService merges)

    def is_agent_busy(self, agent_id: str) -> bool:
        try:
            return _agent_service().get_status(agent_id)["status"] == "working"
        except KeyError:
            return False

    async def dispatch_heartbeat_turn(self, agent_id: str, prompt: str, session: str) -> str:
        return await _collect_orchestrator_text(prompt, session)

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
        if notifications is not None:
            await notifications.notify("Atlas heartbeat", text)
        return
    channel, _, chat_id = target.partition(":")
    if channel_manager is None:
        return
    try:
        await channel_manager.send(channel, chat_id, text)
    except Exception as exc:  # noqa: BLE001 — delivery failure must not crash the tick
        log.warning("heartbeat.channel_delivery_failed", channel=channel, error=str(exc))


async def _collect_orchestrator_text(
    message: str, conversation_id: str, *,
    model: str | None = None,
    active_skill_instructions: list[dict[str, str]] | None = None,
) -> str:
    """One unattended orchestrator turn (heartbeat / automation / group); assistant text."""
    if orchestrator is None:
        raise RuntimeError("Agent orchestrator 尚未就绪")

    async def deny_unapproved(_event_id: str, _tool_name: str, _payload: dict[str, Any]) -> str:
        return "deny"

    response: list[str] = []
    message_id = ""
    async for event in orchestrator.run(
        message=message,
        conversation_id=conversation_id,
        model=model,
        approval_callback=deny_unapproved,
        source_run_id=uuid.uuid4().hex,
        active_skill_instructions=active_skill_instructions,
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
    if not response and message_id and memory is not None:
        # Same fallback as _run_scheduled_goal: a turn that produced no streamed
        # chunks still has its saved assistant message (heartbeat/automation
        # outcomes depend on the model text, not on streaming behaviour).
        messages = await memory.get_conversation_messages(conversation_id, limit=1000)
        saved = next((item.get("content", "") for item in reversed(messages)
                      if item.get("id") == message_id and item.get("role") == "assistant"), "")
        if isinstance(saved, str):
            response.append(saved)
    return "".join(response)


async def _automation_heartbeat_tick(agent_id: str, reason: str) -> Any:
    """Automation ``payload.kind=heartbeat`` → HeartbeatService.tick (W3↔W4 seam)."""
    if heartbeat_service is None:
        raise RuntimeError("heartbeat service 尚未就绪")
    return await heartbeat_service.tick(agent_id, reason)


async def _automation_dispatch_turn(payload: dict[str, Any]) -> str:
    """Automation ``payload.kind=agent_turn`` → orchestrator turn in an isolated session."""
    automation_id = str(payload.get("automation_id") or "adhoc")
    return await _collect_orchestrator_text(
        str(payload.get("message") or ""), f"automation-{automation_id}",
    )


async def _automation_deliver(record: dict[str, Any], outcome: dict[str, Any]) -> bool:
    """Automation delivery: owner → apprise, channel → gateway (§4 delivery spec)."""
    text = str(outcome.get("result") or "").strip()
    if not text:
        return False
    delivery = record.get("delivery") or {}
    channel = str(delivery.get("channel") or "").strip()
    target = str(delivery.get("target") or "").strip()
    if channel in ("", "owner", "notification"):
        if notifications is None:
            return False
        await notifications.notify("Atlas automation", text)
        return True
    if channel_manager is None or not target:
        return False
    await channel_manager.send(channel, target, text)
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
            if existing is not None and _heartbeat_automation_current(existing, desired):
                continue
            saved = engine.store.put(desired)
            await engine.sync_automation(saved)
            log.info("heartbeat.automation_reconciled", agent_id=agent_id,
                     every_seconds=every_seconds)
        except Exception as exc:  # noqa: BLE001 — one bad agent never blocks startup
            log.warning("heartbeat.reconcile_failed", agent_id=agent_id, error=str(exc))


async def _create_channel_conversation(session: str, event: Any) -> str:
    """Create the memory conversation backing a new channel session key."""
    if memory is None:
        raise RuntimeError("memory service unavailable")
    label = f"{event.channel}:{event.chat_id}" if event is not None else session
    conversation_id = await memory.create_conversation(f"渠道会话 {label}")
    workspace = _default_workspace()
    await memory.update_conversation(conversation_id,
                                     workspace=str(workspace) if workspace else None,
                                     source="channel")
    return conversation_id


async def _read_conversation_answer(conversation_id: str) -> str:
    """Last assistant message of a conversation (channel reply payload)."""
    if memory is None:
        return ""
    messages = await memory.get_conversation_messages(conversation_id, limit=1000)
    return next((item["content"] for item in reversed(messages)
                 if item.get("role") == "assistant"), "")


async def _conversation_summary(conversation_id: str) -> dict[str, Any] | None:
    """Conversation metadata for agent-scoped session lineage (W10 sessions view)."""
    if memory is None or getattr(memory, "_db", None) is None:
        return None
    try:
        return await memory.get_conversation(conversation_id)
    except Exception as exc:  # noqa: BLE001 — metadata is best-effort in a listing
        log.debug("agent.conversation_summary_failed", conversation_id=conversation_id,
                  error=str(exc))
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
    except Exception as exc:  # noqa: BLE001 — the bridge must never fail a run
        log.warning("agent.skills_bridge_unavailable", agent_id=agent_id, error=str(exc))
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


# ---------------------------------------------------------------------------
# W8 group chat dispatch (room engine ⇄ engine seam)
# ---------------------------------------------------------------------------


async def _resolve_group_member_conversation(session: str, context: dict[str, Any]) -> str:
    """Create/reuse the conversation backing one group member session key.

    Same SessionMapper the gateway uses (``agent:<id>:group:<room>`` lineage), so
    a member's group thread survives restarts and shows up in the agent's
    /sessions lineage.
    """
    if gateway_bridge is None:
        raise RuntimeError("gateway session map 尚未就绪")
    known = gateway_bridge.sessions.get(session)
    if known:
        return known
    if memory is None:
        raise RuntimeError("memory service 尚未就绪")
    label = str(context.get("group_id") or session)
    conversation_id = await memory.create_conversation(f"群聊会话 {label}")
    workspace = _default_workspace()
    await memory.update_conversation(
        conversation_id, workspace=str(workspace) if workspace else None, source="channel",
    )
    gateway_bridge.sessions.put(session, conversation_id)
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
    conversation_id = await _resolve_group_member_conversation(session, context)
    profile = _resolve_agent_for_run(agent_id)
    skills = list((profile or {}).get("active_skills") or [])
    if profile is not None:
        skills = _merge_agent_collection_skills(agent_id, skills)
    skill_instructions = await _resolve_active_skill_instructions(skills)
    instructions = str((profile or {}).get("instructions") or "")
    if instructions:
        skill_instructions = [*skill_instructions,
            {"name": f"profile:{agent_id}", "content": instructions}]
    return await _collect_orchestrator_text(
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
        await runtime_mgr.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": f"group not found: {group_id}",
        }))
        return
    from_actor = agent_key or "user"
    if agent_key and agent_key not in (group.get("member_agent_ids") or []):
        invalid.status = "failed"
        await runtime_mgr.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation",
            "detail": f"agent {agent_key} is not a member of group {group_id}",
        }))
        return
    content = data.get("content", "")
    if not isinstance(content, str) or not content.strip():
        invalid.status = "failed"
        await runtime_mgr.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": "group turn requires non-empty text",
        }))
        return
    thread_id = data.get("thread_id")
    group_orch = get_group_orchestrator()
    model_id = data.get("model")
    run = RunState(
        run_id, str(data.get("conversation_id") or uuid.uuid4()),
        str(model_id) if model_id else (model_mgr.current_model if model_mgr else ""),
    )
    run.user_input = content
    runtime_mgr.runs[run_id] = run
    runtime_mgr.conn_runs[conn_id] = run_id
    await runtime_mgr.persist_run(run)

    async def _drive() -> None:
        try:
            report = await group_orch.run_turn(group_id, {
                "from_actor": from_actor,
                "text": content,
                **({"thread_id": thread_id} if thread_id else {}),
            })
        except asyncio.CancelledError:
            run.status = "cancelled"
            await runtime_mgr.send_run(run, run.next_envelope("run.cancelled", {}), conn_id)
        except DispatcherNotBound as exc:
            run.status = "failed"
            await runtime_mgr.send_run(run, run.next_envelope("run.failed", {
                "category": "backend", "detail": str(exc),
            }), conn_id)
        except TurnConflict as exc:
            run.status = "failed"
            await runtime_mgr.send_run(run, run.next_envelope("run.failed", {
                "category": "conflict", "detail": str(exc),
            }), conn_id)
        except KeyError as exc:
            run.status = "failed"
            await runtime_mgr.send_run(run, run.next_envelope("run.failed", {
                "category": "validation", "detail": str(exc).strip("'"),
            }), conn_id)
        except ValueError as exc:
            run.status = "failed"
            await runtime_mgr.send_run(run, run.next_envelope("run.failed", {
                "category": "validation", "detail": str(exc),
            }), conn_id)
        except Exception as exc:  # noqa: BLE001 — drive failure reports in-band
            run.status = "failed"
            await runtime_mgr.send_run(run, run.next_envelope("run.failed", {
                "category": "backend", "detail": str(exc),
            }), conn_id)
        else:
            run.status = "completed"
            await runtime_mgr.send_run(run, run.next_envelope("run.completed", {
                "result": "completed", "model": run.model,
                "group_turn": report.to_dict(),
            }), conn_id)

    run.task = asyncio.create_task(_drive())


# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated @app.on_event)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    services = app.state.services
    manager = services.runtime_mgr
    global model_mgr, memory, orchestrator, mcp_client, local_execution, computer_use
    global skill_mgr, skill_registry, scheduler
    global capability_bus, cua_backend, browser_use, agent_backend_host
    global projects, durable, plugin_runtime, notifications, web_runtime, custom_tools, telegram_service
    global usage_ledger
    # W10 persistent-always-on singletons (module-level, reset per lifespan).
    global channel_manager, gateway_bridge, heartbeat_service

    model_mgr = ModelManager()
    memory = MemoryStore()
    await memory.init()
    usage_ledger = UsageLedger(get_config().db_path)
    await usage_ledger.init()
    projects = ProjectStore(get_config().db_path.parent / "projects.db")
    await projects.init()
    durable = DurableBackend(get_config().db_path.parent / "dbos.sqlite")
    durable.set_dispatcher(_durable_dispatcher, asyncio.get_running_loop())
    durable.start()
    # W10: durable.start() constructed + launched the process-global DBOS
    # singleton; the automation engine reuses that same instance (never a second
    # DBOS per process). NOTE: _dbos_global_instance lives on the dbos._dbos
    # MODULE, not on the DBOS class — a class-level getattr always misses.
    from dbos import _dbos as _dbos_module

    dbos_instance = getattr(_dbos_module, "_dbos_global_instance", None)

    # W6: pin HERMES_HOME before the hermes engine initializes — importing this
    # module pins the machine-level local-runtime home exactly once (setdefault).
    import atlas.engine.local_runtime_adapter  # noqa: F401  # W6 integration touchpoint

    await manager.init(get_config().db_path)

    mcp_client = MCPClient()
    await mcp_client.start()
    local_execution = LocalExecutionRuntime()
    cua_backend = CuaBackend()
    computer_use = ComputerUseRuntime(cua_backend=cua_backend)
    capability_bus = CapabilityBus(dict(get_config().raw.get("integrations", {})))
    browser_use = BrowserUseAdapter()
    agent_backend_host = AgentBackendHost()

    skill_mgr = SkillManager()
    cfg = get_config()
    # E2: feed the one shared skill index from every source. Hermes skills are
    # strictly opt-in via `extensions.hermes_skills = "<hermes skills dir>"` in
    # atlas.toml; plugin skill dirs join through _refresh_extension_sources
    # once plugin_runtime exists below.
    hermes_skills = cfg.get("extensions.hermes_skills")
    for source in default_skill_sources(
        workspace=_default_workspace(),
        hermes_skills_dir=(
            Path(str(hermes_skills).strip()) if isinstance(hermes_skills, str) and hermes_skills.strip() else None
        ),
    ):
        skill_mgr.register_skill_source(source)
    await skill_mgr.scan_skills()
    custom_tools = CustomToolStore(cfg.db_path.parent / "tools")
    skill_registry = SkillRegistry(cfg.db_path.parent / "skill-registry.db")
    _register_local_skills(skill_mgr, skill_registry)
    capabilities = AgentCapabilityRegistry()
    register_skill_capabilities(capabilities, skill_mgr, skill_registry, mcp_client)
    register_skill_dependency_capability(capabilities, skill_mgr, skill_registry, mcp_client)
    register_skill_discovery_capability(capabilities, skill_registry)
    register_skill_catalog_capabilities(capabilities, skill_catalog_provider, skill_registry)
    checkpoints = ShadowGitCheckpointStore(cfg.db_path.parent / "checkpoints")
    bundles = PluginBundleDiscovery()
    capabilities.register(
        "local.full_access",
        description="Canonical P18A local execution tools (PowerShell, process, files, Git).",
        handler=lambda _inputs: local_execution.get_tools_for_llm(),
        source="atlas-p18a",
    )
    capabilities.register(
        "computer.cua.status", description="Connect to Cua Driver and return runtime metadata.",
        handler=lambda _inputs: cua_backend.connect(), source="trycua/cua",
    )
    capabilities.register(
        "computer.cua.tools", description="List installed Cua Driver computer tools.",
        handler=lambda _inputs: cua_backend.tools(), source="trycua/cua",
    )
    capabilities.register(
        "computer.cua.call", description="Call a Cua Driver computer tool by name.",
        handler=lambda inputs: cua_backend.call(
            str(inputs["name"]), dict(inputs.get("arguments", {})),
        ), source="trycua/cua",
    )
    capabilities.register(
        "computer.pywinauto.windows", description="List visible Windows UIA windows.",
        handler=lambda _inputs: list_uia_windows(), source="pywinauto",
    )
    capabilities.register(
        "browser.use.open", description="Open a URL in Browser Use and return page state.",
        handler=lambda inputs: browser_use.open(
            str(inputs["url"]), cdp_url=inputs.get("cdp_url"),
        ), source="browser-use/browser-use",
    )
    capabilities.register(
        "browser.use.task", description="Run a Browser Use Agent task against a web page.",
        handler=lambda inputs: browser_use.task(
            str(inputs["goal"]),
            start_url=inputs.get("start_url"),
            model=inputs.get("model"),
            session_options=dict(inputs.get("session_options", {})),
        ), source="browser-use/browser-use",
    )
    capabilities.register(
        "coding.ast_grep.run", description="Run ast-grep against a repository path.",
        handler=lambda inputs: ast_grep_capability.run(
            list(inputs.get("arguments", [])), cwd=str(inputs["cwd"]),
        ), source="ast-grep/ast-grep",
    )
    capabilities.register(
        "coding.repo_map", description="Generate an Aider repository map.",
        handler=lambda inputs: repo_map(str(inputs["path"]), int(inputs.get("budget", 1024))),
        source="Aider-AI/aider",
    )
    capabilities.register(
        "durable.dbos.status", description="Report DBOS installation and database readiness.",
        handler=lambda _inputs: dbos_status(), source="dbos-inc/dbos-transact-py",
    )
    web_runtime = WebRuntime()
    capabilities.register(
        "web.search",
        description="Search the public web (DuckDuckGo) and return result links.",
        handler=lambda inputs: web_runtime.web_search(
            str(inputs.get("query", "")), int(inputs.get("max_results", 5)),
        ),
        source="duckduckgo/html",
    )
    capabilities.register(
        "web.fetch",
        description="Download a web page and return readable text.",
        handler=lambda inputs: web_runtime.web_fetch(
            str(inputs.get("url", "")), int(inputs.get("max_chars", 8000)),
        ),
        source="duckduckgo/html",
    )
    capabilities.register(
        "notifications.send",
        description="Send a user notification through the configured Apprise targets.",
        handler=lambda inputs: notifications.notify(
            str(inputs.get("title", "Atlas")), str(inputs.get("body", "")),
        ),
        source="caronc/apprise",
    )
    capabilities.register(
        "durable.agent_task.run",
        description="Run one agent task as a DBOS durable workflow (crash-resumable).",
        handler=lambda inputs: durable.run_agent_task({
            "task_id": str(inputs.get("task_id", "adhoc")),
            "message": str(inputs.get("message", "")),
        }),
        source="dbos-inc/dbos-transact-py",
    )
    capabilities.register(
        "memory.session_search",
        description="Search past conversation messages (raw history) with surrounding context.",
        handler=lambda inputs: memory.session_search(
            str(inputs.get("query", "")),
            limit=int(inputs.get("limit", 8)),
            context=int(inputs.get("context", 2)),
        ),
        source="atlas-memory",
    )
    capabilities.register(
        "agent.execute_code",
        description="Run a bounded Python workflow through the shared Atlas tool bridge.",
        handler=lambda inputs: CodeActRuntime(
            AtlasToolBridge(local_execution, computer_use, mcp_client, checkpoints),
        ).execute(str(inputs["code"])),
        source="Hermes execute_code pattern",
    )
    capabilities.register(
        "agent.compact_context",
        description="Snapshot resume-critical task context before compaction.",
        handler=lambda inputs: orchestrator.context_maintenance.compact(inputs),
        source="Codex/OpenCode context maintenance",
    )
    capabilities.register(
        "agent.compaction.should_trigger",
        description="Return whether a session has reached its configured compaction threshold.",
        handler=lambda inputs: {
            "should_compact": orchestrator.context_maintenance.should_compact(
                list(inputs.get("messages", [])),
                message_limit=int(inputs.get("message_limit", 80)),
                character_limit=int(inputs.get("character_limit", 80_000)),
            ),
        },
        source="Codex/OpenCode context maintenance",
    )
    capabilities.register(
        "agent.memory.reflect",
        description="Propose task learning through the governed MemoryOS candidate path.",
        handler=lambda inputs: MemoryReflectionBridge(memory).reflect(
            conversation_id=str(inputs.get("conversation_id", "")),
            goal=str(inputs["goal"]), task_result=str(inputs["task_result"]),
            reviewer_evidence=list(inputs.get("reviewer_evidence", [])),
        ),
        source="Letta/Hermes reflection pattern",
    )
    capabilities.register(
        "workspace.checkpoint.create",
        description="Snapshot explicitly scoped workspace paths outside the repository.",
        handler=lambda inputs: checkpoints.create_checkpoint(
            str(inputs["workspace"]), list(inputs["paths"]),
        ),
        source="google-gemini/gemini-cli",
    )
    capabilities.register(
        "workspace.checkpoint.list",
        description="List Atlas shadow checkpoints, optionally for one workspace.",
        handler=lambda inputs: checkpoints.list_checkpoints(inputs.get("workspace")),
        source="google-gemini/gemini-cli",
    )
    capabilities.register(
        "workspace.checkpoint.restore",
        description="Restore the scoped paths in an Atlas shadow checkpoint.",
        handler=lambda inputs: checkpoints.restore_checkpoint(str(inputs["checkpoint_id"])),
        source="google-gemini/gemini-cli",
    )
    capabilities.register(
        "plugin.bundle.discover",
        description="Discover normalized plugin bundle declarations and plain Atlas Skills.",
        handler=lambda _inputs: bundles.discover([SKILLS_DIR], skill_mgr.list_skills()),
        source="ZCode/Gemini plugin manifest pattern",
    )
    if agent_backend_host:
        capabilities.register(
            "agent.delegate_task",
            description="Delegate one bounded investigation to a disposable Agent session.",
            handler=lambda inputs: DelegationService(
                agent_backend_host, orchestrator.hooks,
            ).delegate_task(
                str(inputs["goal"]), inputs.get("context"), inputs.get("tool_profile"),
            ),
            source="Claude/Hermes disposable delegation pattern",
        )

    orchestrator = AgentOrchestrator(
        model_mgr=model_mgr, memory=memory, mcp_client=mcp_client,
        capability_registry=capabilities,
        local_execution=local_execution,
        computer_use=computer_use,
        agent_backend_host=agent_backend_host,
        web_runtime=web_runtime,
        skill_manager=skill_mgr,
        projects=projects,
        # One store: the Agent's automatic snapshots must be the ones restore and diff read.
        checkpoint_store=checkpoints,
        custom_tools=custom_tools,
        web_extractor=extract_web,
    )

    plugin_runtime = PluginRuntime(
        [PROJECT_ROOT / "plugins", get_config().db_path.parent / "plugins"],
        get_config().db_path.parent / "plugins" / "state.json",
    )
    plugin_load_report = await plugin_runtime.load_all(
        hook_bus=orchestrator.hooks,
        mcp_client=mcp_client,
        capabilities=capabilities,
    )
    _refresh_extension_sources()

    # H3/H5 seam: run the once-per-process registrations (Atlas policy plugin +
    # Hermes MCP servers) at startup so the first user turn does not pay for
    # them. Idempotent and fingerprint-checked; a failure only means the first
    # turn re-runs the registration, so it must never break startup.
    try:
        from atlas.config import DATA_ROOT
        from atlas.engine import HermesRuntime

        HermesRuntime(data_dir=DATA_ROOT, model_manager=model_mgr).startup_registrations()
    except Exception:  # noqa: BLE001 — degraded to a warning; first turn retries
        log.exception("engine.startup_registrations_failed")

    notifications = NotificationBus()
    if plugin_load_report.get("errors"):
        log.warning("plugins.load_errors", errors=plugin_load_report["errors"])

    # -- W10 persistent-always-on wiring (agents / channels / heartbeat / automation) --
    agents_service = PersistentAgentService()
    from atlas.api.agent_router import set_agent_service, set_conversation_lookup

    set_agent_service(agents_service)
    set_conversation_lookup(_conversation_summary)
    app.state.services.persistent_agents = agents_service
    app.state.services.agent_conversation_lookup = _conversation_summary

    channel_manager = ChannelManager(
        db_path=cfg.db_path.parent / "channels.sqlite",
        config_path=cfg.db_path.parent / "channel-configs.json",
    )
    register_builtin_channels(channel_manager.register_channel)
    channel_workspace = _default_workspace()

    async def submit_channel_run(conn_id: str, data: dict[str, Any]) -> None:
        await _handle_run_start(conn_id, data, manager)

    async def channel_recovery_notice(run_id: str, message: str) -> None:
        run = manager.runs.get(run_id)
        if run is None:
            return
        env = run.next_envelope("run.recovery.notice", {"message": message})
        await manager.send_run(run, env, "channel")

    gateway_bridge = GatewayBridge(
        manager=channel_manager,
        db_path=cfg.db_path.parent / "channels.sqlite",
        submit_run=submit_channel_run,
        get_run=manager.runs.get,
        recovery_notice=channel_recovery_notice,
        read_answer=_read_conversation_answer,
        create_conversation=_create_channel_conversation,
        default_workspace=str(channel_workspace) if channel_workspace else None,
        set_agent_status=_set_agent_status_quiet,
        # H7 §9.1/§9.2: the configured defaults and the per-agent profile rung
        # of the permission ladder finally reach production wiring.
        default_permission_mode=get_config().gateway_default_permission_mode,
        approval_timeout_seconds=get_config().gateway_approval_timeout_seconds,
        get_agent=_channel_agent_profile,
    )
    channel_manager.set_dispatcher(gateway_bridge.dispatch)
    _sync_channel_routing(agents_service, channel_manager)
    from atlas.api.channel_router import set_channel_manager

    set_channel_manager(channel_manager)

    heartbeat_service = HeartbeatService(_AtlasHeartbeatHost(), root=cfg.db_path.parent / "heartbeat")

    # W8 group chat: singletons bound in order (service → orchestrator). The real
    # dispatcher drives member turns through the same engine seam as
    # heartbeat/automation — never a second agent core. Room log + watermarks
    # live under data/groups/<group_id>/ (the orchestrator's store.root).
    group_service = GroupService(GroupStore(cfg.db_path.parent), lookup=agents_service)
    group_orchestrator = GroupOrchestrator(
        group_service, dispatcher=_dispatch_group_member_turn,
    )
    from atlas.api.group_router import set_group_orchestrator, set_group_service

    set_group_service(group_service)
    set_group_orchestrator(group_orchestrator)

    automation_engine = AutomationEngine(
        AutomationStore(cfg.db_path.parent / "automations.toml"),
        heartbeat_tick=_automation_heartbeat_tick,
        dispatch_turn=_automation_dispatch_turn,
        deliver=_automation_deliver,
    )
    set_automation_engine(automation_engine)
    if dbos_instance is not None:
        await automation_engine.start_async(dbos_instance)
        await _reconcile_agent_heartbeats(agents_service, automation_engine)
    else:
        # durable.start() failed: automation CRUD keeps working (store only),
        # but triggers/runs report 503 until the next restart.
        log.warning("automation.engine_not_started", reason="dbos_instance_unavailable")

    from atlas.api import agent_skills_router, device_router, local_models_router
    from atlas.engine.local_runtime_adapter import LocalRuntimeAdapter
    from atlas.skills.agent_collections import AgentSkillCollections
    from atlas.skills.proposals import SkillProposalStore

    local_models_router.set_adapter(LocalRuntimeAdapter(cfg.get("local_runtime", {})))
    device_registry = DeviceRegistry(cfg.db_path.parent / "devices" / "devices.json")
    device_registry.register_self()
    takeover_machine = TakeoverStateMachine()
    # Legacy singletons stay queryable for standalone mounts; the app's own
    # request handlers read the same instances through app.state services.
    device_router.set_registry(device_registry)
    device_router.set_takeover(takeover_machine)
    services.device_registry = device_registry
    services.takeover = takeover_machine
    agent_skills_router.set_collections(AgentSkillCollections(skill_registry))
    # The proposal apply path writes skill payloads through the ONE market save
    # path (register_local + rescan) — without it approve() reports 503 market_unwired.
    from atlas.api.skills_market_router import get_market

    agent_skills_router.set_proposals(SkillProposalStore(
        skill_registry, market=get_market(),
        collections=agent_skills_router.get_collections(),
    ))
    # -- end W10 wiring --

    if cfg.scheduler_enabled:
        scheduler = AtlasScheduler(agent_callback=_scheduled_goal)
        await scheduler.start()

    # DEPRECATED (W10): the legacy TelegramService polling loop is retired in
    # favour of the channel gateway's telegram adapter (atlas.channels.adapters
    # .telegram + ChannelManager + gateway bridge). The service object stays —
    # /api/telegram settings/test_token and run approval keyboards depend on it —
    # but its getUpdates poll only starts when the gateway's telegram channel is
    # NOT enabled, so the two stacks never double-poll the same bot token.
    telegram_service = TelegramService(
        cfg.db_path.parent / "telegram.json",
        owns_lease=_owns_scheduler_lease,
        submit_task=_telegram_submit_task,
        command_handler=_telegram_command,
    )
    if not (channel_manager.configs.get("telegram") or {}).get("enabled"):
        telegram_service.start()

    await channel_manager.start()

    # C6:注册 /init 与 /review 的路由和工具。这些模块由独立子模块提供,可能晚于
    # 服务启动落地——注册失败只降级告警,绝不能拖垮 Atlas 本体启动。
    try:
        from atlas.commands.init import register_init_routes

        register_init_routes(app)
    except Exception as exc:  # noqa: BLE001 — /init 模块缺失或注册失败只降级
        log.warning("C6 启动注册 /init 路由失败，/init 功能暂不可用", error=str(exc))
    try:
        from atlas.review.engine import register_review_tools

        register_review_tools()
    except Exception as exc:  # noqa: BLE001 — review 模块缺失或注册失败只降级
        log.warning("C6 启动注册审查工具失败，/review 功能暂不可用", error=str(exc))
    try:
        from atlas.review.engine import register_review_routes

        register_review_routes(app)
    except Exception as exc:  # noqa: BLE001 — review 路由注册失败只降级
        log.warning("C6 启动注册 /review 路由失败，/review 功能暂不可用", error=str(exc))

    # Keep request and WebSocket dependencies bound to this lifespan's service root.
    services.config = get_config()
    for service_name in (
        "model_mgr", "memory", "orchestrator", "mcp_client", "local_execution",
        "computer_use", "skill_mgr", "skill_registry", "scheduler", "capability_bus",
        "cua_backend", "browser_use", "agent_backend_host", "projects", "durable",
        "plugin_runtime", "notifications", "web_runtime", "custom_tools",
        "telegram_service", "usage_ledger", "channel_manager", "gateway_bridge",
        "heartbeat_service",
    ):
        setattr(services, service_name, globals().get(service_name))
    # persistent_agents / group_service / group_orchestrator live only as
    # lifespan locals — the globals sweep above can never see them, so bind
    # them explicitly (globals().get() would clobber them back to None).
    services.persistent_agents = agents_service
    services.agent_conversation_lookup = _conversation_summary
    services.group_service = group_service
    services.group_orchestrator = group_orchestrator
    manager.services = services

    yield  # app is running

    # Shutdown
    if telegram_service:
        await telegram_service.stop()
    if scheduler:
        await scheduler.stop()
    # W10 reverse order: gateway → automation engine → heartbeat, all before
    # durable.stop() (the engine owns DBOS objects, not the DBOS instance).
    if channel_manager is not None:
        await channel_manager.stop()
        channel_manager.close()
    if gateway_bridge is not None:
        gateway_bridge.sessions.close()
    automation_engine = get_automation_engine()
    if automation_engine is not None:
        automation_engine.shutdown()
    if heartbeat_service is not None:
        await heartbeat_service.aclose()
    # W8 group chat singletons: reset so a stale orchestrator (and its bound
    # dispatcher over this lifespan's services) never leaks into a restart.
    from atlas.api import group_router as _group_router

    _group_router.set_group_orchestrator(None)
    _group_router.set_group_service(None)
    if mcp_client:
        await mcp_client.stop()
    if local_execution:
        await local_execution.shutdown()
    if computer_use:
        await computer_use.shutdown()
    # X2 bridges: cancel pending human cards + release Hermes desktop/browser sessions.
    from atlas.tools.x2 import browser as x2browser
    from atlas.tools.x2 import computer as x2computer

    await x2computer.shutdown()
    await x2browser.shutdown()
    if cua_backend:
        await cua_backend.close()
    if browser_use:
        for session_id in list(browser_use._sessions):
            await browser_use.close(session_id)
    await ssh_workspaces.close()
    if agent_backend_host:
        await agent_backend_host.shutdown()
    if durable:
        durable.stop()
    if projects:
        await projects.close()
    if usage_ledger:
        await usage_ledger.close()
    if memory:
        await memory.close()
    await manager.close()


# ---------------------------------------------------------------------------
# App factory and lifecycle-owned service root
# ---------------------------------------------------------------------------

runtime_mgr = RuntimeManager()
app = create_app(lifespan=lifespan, services=AppServices(runtime_mgr=runtime_mgr))


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


_WORKSPACE_IGNORES = {".git", "node_modules", ".venv", "__pycache__", ".atlas-checkpoints"}
_RULE_FILES = ("AGENTS.md", "CLAUDE.md", ".atlas/rules.md", ".atlas/NOTES.md")
_LOADED_RULE_WORKSPACES: set[str] = set()


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
        value = json.loads(_workspace_trust_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _set_workspace_trusted(root: str, trust: bool) -> None:
    values = _workspace_trust()
    if trust:
        values[root] = True
    else:
        values.pop(root, None)
    path = _workspace_trust_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _validated_file_attachments(
    value: Any, run_id: str, content: str,
) -> tuple[str, list[str]]:
    if value is None:
        return content, []
    if not isinstance(value, list):
        raise ValueError("files must be an array")
    total = 0
    inlined: list[str] = []
    stored: list[str] = []
    allowed_text = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts",
                    ".tsx", ".jsx", ".html", ".css", ".yaml", ".yml", ".toml",
                    ".xml", ".sql", ".sh", ".ps1", ".go", ".rs", ".java", ".c",
                    ".h", ".cpp", ".hpp", ".rb", ".php", ".swift", ".kt"}
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
        if mime.startswith("text/") or mime in {"application/json", "text/markdown"} \
                or Path(name).suffix.lower() in allowed_text:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError(f"text attachment is not valid UTF-8: {name}") from None
            inlined.append(f"--- Attached file: {name} ---\n{text}")
        else:
            directory = Path.home() / ".atlas" / "attachments" / run_id
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / name
            path.write_bytes(raw)
            stored.append(str(path.resolve()))
    if inlined:
        content += "\n\n" + "\n\n".join(inlined)
    return content, stored


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
    _, target = _workspace_path(root, relative)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="context file not found")
    raw = target.read_bytes()
    chunk = raw[:min(64 * 1024, max(0, remaining_bytes))]
    block = f"\n\n[Context file: {relative}]\n{chunk.decode('utf-8', errors='replace')}"
    if len(raw) > len(chunk):
        block += "\n[Context file truncated.]"
    return block, len(chunk)


def _run_changes(run_id: str, workspace: str | None = None) -> dict[str, Any]:
    store = getattr(orchestrator, "checkpoints", None) if orchestrator is not None else None
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
    files = _run_changes(run_id)["files"]
    return {"files": len(files), "additions": sum(item["additions"] for item in files),
            "deletions": sum(item["deletions"] for item in files)}


def _sum_usage(calls: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("input_tokens", "output_tokens", "context_tokens")
    totals = {}
    for key in keys:
        values = [item.get(key) for item in calls]
        totals[key] = sum(values) if values and all(isinstance(value, int) for value in values) else None
    for key in ("cached_input_tokens", "cache_write_tokens"):
        present = [item.get(key) for item in calls if item.get(key) is not None]
        totals[key] = sum(value for value in present if isinstance(value, int)) if present else None
    totals["cache_hit_rate"] = (
        round(totals["cached_input_tokens"] / totals["input_tokens"], 4)
        if isinstance(totals["cached_input_tokens"], int)
        and isinstance(totals["input_tokens"], int) and totals["input_tokens"] > 0
        else None
    )
    totals["context_limit"] = next(
        (item.get("context_limit") for item in reversed(calls)
         if item.get("context_limit") is not None), None,
    )
    totals["model"] = next((item.get("model") for item in reversed(calls)), None)
    return totals


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Tools (MCP)
# ---------------------------------------------------------------------------


    return {"urls": notifications.urls}


async def _reload_extensions() -> dict[str, Any]:
    assert plugin_runtime is not None
    report = await plugin_runtime.load_all(
        hook_bus=orchestrator.hooks if orchestrator else None,
        mcp_client=mcp_client,
        capabilities=orchestrator.capabilities if orchestrator else None,
    )
    _refresh_extension_sources()
    return report


# ---------------------------------------------------------------------------
# External import (E6)
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

def _plugin_contributions() -> list[dict[str, Any]]:
    return plugin_runtime.enabled_contributions() if plugin_runtime else []


def _plugin_skill_sources() -> dict[str, list[Path]]:
    return {
        plugin["name"]: [Path(item) for item in plugin["skills"]]
        for plugin in _plugin_contributions()
    }


def _refresh_extension_sources() -> None:
    """Re-apply plugin contributions to the shared registries (E2/E4).

    Hooks flow through the lazy ``_plugin_hooks`` supplier and MCP/capabilities
    through ``load_all``; here only the skill index needs re-assembly, always
    via ``register_skill_source`` — never a second registry.
    """
    if skill_mgr is None:
        return
    skill_mgr.replace_skill_sources("plugin:", plugin_skill_sources(_plugin_skill_sources()))


def _plugin_command_sources() -> list[CommandSource]:
    return [
        CommandSource(f"plugin:{plugin['name']}", Path(path), 60, plugin=True)
        for plugin in _plugin_contributions()
        for path in plugin["command_sources"]
    ]


def _plugin_agent_dirs() -> list[Path]:
    """Directories holding plugin agent files, for the shared agent discovery."""
    dirs: list[Path] = []
    for plugin in _plugin_contributions():
        for agent_file in plugin["agents"]:
            agents_dir = Path(agent_file).parent
            if agents_dir not in dirs:
                dirs.append(agents_dir)
    return dirs


def _plugin_hooks() -> list[dict[str, Any]]:
    return [hook for plugin in _plugin_contributions() for hook in plugin["hooks"]]


_active_hook_store: HookStore | None = None


def _hook_store() -> HookStore:
    global _active_hook_store
    path = get_config().db_path.parent / "hooks.toml"
    if _active_hook_store is None or _active_hook_store.path != path:
        _active_hook_store = HookStore(path, plugin_hooks=_plugin_hooks)
    return _active_hook_store


# ---------------------------------------------------------------------------
# WebSocket chat — Runtime Event Protocol 1.2
# ---------------------------------------------------------------------------



# Compatibility helper for tests and external imports; production HTTP requests
# are handled by atlas.api.runtime_router with request-scoped AppServices.
async def cancel_subtask(run_id: str, subtask_id: str) -> dict[str, str]:
    run = runtime_mgr.runs.get(run_id)
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
    manager = manager or runtime_mgr
    run_id = str(data.get("run_id", ""))
    run = manager.runs.get(run_id)
    if run and run.trust_future and not run.trust_future.done() and run.trust_event_id:
        # One RunState has one outstanding trust request, so a stale event_id
        # after reconnect can safely fall back to run_id.
        trusted = data.get("trust") is True
        if trusted:
            for root in run.trust_roots or ([run.workspace] if run.workspace else []):
                _set_workspace_trusted(root, True)
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
    manager = manager or runtime_mgr
    services = manager.services
    model_mgr = getattr(services, "model_mgr", None) or globals().get("model_mgr")
    memory = getattr(services, "memory", None) or globals().get("memory")
    orchestrator = getattr(services, "orchestrator", None) or globals().get("orchestrator")
    projects = getattr(services, "projects", None) or globals().get("projects")
    run_id = data.get("run_id") or str(uuid.uuid4())
    existing = manager.runs.get(run_id)
    if existing:
        manager.conn_runs[conn_id] = run_id
        async with existing.event_lock:
            for env in list(existing.events):
                await manager.send(conn_id, env)
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
        agent_profile = _resolve_agent_for_run(agent_key)
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
        await _start_group_turn_run(conn_id, run_id, data, str(data["group_id"]), agent_key)
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
    profile = _profile_store().get(str(profile_id)) if profile_id else None
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
    effective_skills = data.get("active_skills", (profile or {}).get("active_skills", []))
    if agent_profile is not None:
        # W7→W10 bridge (scenario 16): learned/approved per-agent skills join the
        # run's active set; an explicit per-agent opt-out wins over the profile.
        effective_skills = _merge_agent_collection_skills(agent_key, effective_skills)
    effective_mode = data.get("mode", (profile or {}).get("mode", "act"))
    model_id = data.get("model", (profile or {}).get("model"))
    reasoning_effort = data.get("reasoning_effort", (profile or {}).get("reasoning_effort"))
    permission_mode = data.get("permission_mode")
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
    if reasoning_effort not in {None, "minimal", "low", "medium", "high"}:
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": "invalid reasoning_effort",
        }))
        return
    try:
        active_skill_instructions = await _resolve_active_skill_instructions(
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
        image_attachments = _validated_image_attachments(data.get("attachments"))
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
    try:
        content, file_paths = _validated_file_attachments(
            data.get("files"), run_id, content,
        )
        if file_paths:
            content += "\n\nAttached files stored at:\n" + "\n".join(file_paths)
    except ValueError as exc:
        invalid_run = RunState(run_id, str(data.get("conversation_id", "")), "")
        await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": str(exc),
        }))
        return
    resume_from = data.get("resume_from")
    recovered_plan = None
    prior_run = manager.runs.get(resume_from) if isinstance(resume_from, str) else None
    if resume_from is not None:
        if not prior_run or prior_run.status != "failed" or not prior_run.plan_state:
            raise ValueError("resume_from must reference an interrupted run with a saved plan")
        recovered_plan = prior_run.plan_state
        if not content:
            content = str(recovered_plan.get("goal", ""))
    conv_id = data.get("conversation_id") or (
        prior_run.conversation_id if prior_run else str(uuid.uuid4())
    )
    # C6:/review 拦截——命中审查指令时把正文改写为派发提示词，并固定审查配置。
    # 放在正文（含附件）就绪之后、档案合并之前，让后续统一的 run 组装吃到强制值。
    try:
        from atlas.review.engine import (
            build_dispatch_prompt, collect_diff, is_review_request, parse_scope,
        )
    except Exception as exc:  # noqa: BLE001 — review 模块未就绪时按普通消息放行
        log.warning("C6 /review 拦截模块不可用，按普通消息处理", error=str(exc))
    else:
        if is_review_request(content):
            review_conv = None
            if memory is not None and getattr(memory, "_db", None) is not None:
                try:
                    review_conv = await memory.get_conversation(conv_id)
                except Exception:
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
            run_tool_allow = ["delegate_task", "submit_findings", "local_file", "review_command",
                              "coding.repo_map", "coding.ast_grep.run", "read_office"]
            run_tool_deny = []
            log.info("review.intercepted", run_id=run_id,
                     workspace=str(review_workspace), scope=review_scope.get("scope"))
    assert model_mgr is not None
    run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
    if isinstance(data.get("telegram_user_id"), int):
        run.telegram_user_id = data["telegram_user_id"]
    if effective_mode not in {"act", "plan"}:
        run.status = "failed"
        await manager.send(conn_id, run.next_envelope("run.failed", {
            "category": "validation", "detail": "mode must be 'act' or 'plan'",
        }))
        return
    run.mode = effective_mode
    run.reasoning_effort = reasoning_effort
    run.permission_mode = permission_mode
    run.allowed_paths = [str(Path(item).expanduser().resolve()) for item in allowed_paths or []]
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
        if "permission_mode" not in data:
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
            external_agent_status(external_agent_status_cache)["agents"]
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
            workspace = None
    # Project instructions are extra context: if the project store can't answer, run without them
    # rather than failing the run.
    project = None
    if projects is not None:
        try:
            project = await projects.find_by_conversation(conv_id)
            source_data = await projects.get_sources(project.project_id) if project is not None else None
        except Exception as exc:
            log.warning("run.project_context_unavailable", error=str(exc))
            project, source_data = None, None
        if project is not None:
            run.project_id = project.project_id
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
                    worktree_data = _worktrees().create(
                        workspace_path, conv_id, worktree_request.get("base_branch"),
                        worktree_request.get("name"),
                    )
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
        if memory is not None and getattr(memory, "_db", None) is not None and not (conversation and conversation.get("worktree_path")):
            await memory.update_conversation(conv_id, workspace=str(Path(workspace).expanduser().resolve()))
        context_files = data.get("context_files", [])
        if not isinstance(context_files, list):
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "validation", "detail": "context_files must be a list",
            }))
            return
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
                        _context_file_block, run.workspace, str(relative), remaining,
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
        context_conversations = data.get("context_conversations", [])
        if not isinstance(context_conversations, list) or len(context_conversations) > 3:
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "validation", "detail": "context_conversations must contain at most three conversation ids",
            }))
            return
        for other_id in context_conversations:
            other = await memory.get_conversation(str(other_id)) if memory else None
            if other is None:
                invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
                await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                    "category": "validation", "detail": f"context conversation not found: {other_id}",
                }))
                return
            messages = (await memory.get_conversation_messages(str(other_id), limit=1000))[-20:]
            compacted = await orchestrator.context_maintenance.compact({
                "goal": other.get("title", "Referenced conversation"),
                "session_summary": "\n".join(f"{m['role']}: {m['content'][:1000]}" for m in messages),
            }) if orchestrator else {"session_summary": "\n".join(m["content"][:500] for m in messages)}
            content += f"\n\n[Referenced conversation: {other.get('title', other_id)}]\n{compacted.get('session_summary', '')}"
        run.user_input = content
        if data.get("ephemeral") is True:
            if memory is None:
                invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
                await manager.send(conn_id, invalid_run.next_envelope("run.failed", {
                    "category": "backend", "detail": "memory service unavailable",
                }))
                return
            source_messages = await memory.get_conversation_messages(conv_id, limit=1000)
            temp_conversation = await memory.create_conversation("Ephemeral side chat")
            for message in source_messages:
                await memory.save_message(temp_conversation, message["role"], message["content"], message.get("metadata"))
            run.ephemeral = True
            run.ephemeral_source = temp_conversation
            run.read_only = True
            run.conversation_id = temp_conversation
        rule_roots = list(dict.fromkeys([*([run.workspace] if run.workspace else []), *run.extra_roots]))
        run.workspace_rules = []
        untrusted_roots = []
        for root in rule_roots:
            from atlas.api.workspace_router import collect_workspace_rules

            rules = await collect_workspace_rules(root)
            root_key = rules.get("root", root)
            root_files = [{**item, "root": root_key} for item in rules["files"]]
            run.workspace_rules.extend(root_files)
            if root_files and not _workspace_trust().get(root_key):
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
    manager.runs[run_id] = run
    manager.conn_runs[conn_id] = run_id
    await manager.persist_run(run)

    # Start the run in background so we can keep receiving messages
    execute = _execute_run(
            conn_id, run, content, model_id,
            plan_state=recovered_plan,
            image_attachments=image_attachments,
            active_skill_instructions=active_skill_instructions,
            workspace=run.workspace,
            workspace_rules=run.workspace_rules,
            mode=run.mode,
            manager=manager,
        )
    execution = _execute_after_rule_trust(run, execute) if run.trust_future else execute
    if agent_profile is not None:
        # W10: project the persistent agent's runtime status around the run
        # (working while it lives → idle/waiting_user once it settles).
        _set_agent_status_quiet(agent_key, "working")
        run.task = asyncio.create_task(
            _project_agent_run_status(run, agent_key, execution))
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
        _set_agent_status_quiet(agent_id, status, detail)


async def _execute_after_rule_trust(run: RunState, execution: Any) -> None:
    if run.trust_future is None or not await run.trust_future:
        run.status = "cancelled"
        await runtime_mgr.send_run(run, run.next_envelope("run.cancelled", {}), "")
        return
    run.trust_future = None
    run.status = "running"
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
    if skill_mgr is None:
        if names:
            raise ValueError("Skill Manager is unavailable")
        return []

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    connected = mcp_client.get_server_names() if mcp_client else None
    configured = mcp_client.get_configured_server_names() if mcp_client else None
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        info = skill_mgr.get_skill(name)
        if info is None:
            raise ValueError(f"Skill not found: {name}")
        record = skill_registry.get(name, info.version) if skill_registry else None
        lifecycle = (record or {}).get("lifecycle", {})
        if lifecycle.get("trust_state") in {"revoked", "blocked"} or lifecycle.get(
            "state"
        ) in {"quarantined", "removed"}:
            raise PermissionError(f"Skill lifecycle policy blocks activation: {name}")
        content = await skill_mgr.activate(
            name,
            connected_servers=connected,
            configured_servers=configured,
            registry=skill_registry,
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
    if agent_backend_host is None:
        raise RuntimeError("外部 Agent 服务当前不可用。")
    if not workspace:
        raise RuntimeError("运行外部 Agent 前，请先为当前对话选择工作目录。")
    if workspace.startswith("ssh://"):
        raise RuntimeError("外部 Agent 目前不能在 SSH 工作目录中运行。")

    store = getattr(orchestrator, "checkpoints", None) if orchestrator else None
    if store is not None:
        store.create_checkpoint(
            workspace, ["."], run_id=run.run_id,
            conversation_id=run.conversation_id,
        )

    key = (run.conversation_id, run.executor)
    session_id = external_conversation_sessions.get(key)
    if session_id not in agent_backend_host.sessions:
        session = await agent_backend_host.start(run.executor, workspace)
        session_id = session.id
        external_conversation_sessions[key] = session_id
    await agent_backend_host.send(session_id, content)

    response: list[str] = []
    tools: dict[str, dict[str, Any]] = {}

    async def consume() -> None:
        async for event in agent_backend_host.events(session_id):
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
                await agent_backend_host.cancel(session_id)
            with suppress(Exception):
                await agent_backend_host.close(session_id)
            external_conversation_sessions.pop(key, None)
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
    manager = manager or runtime_mgr
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
) -> None:
    """Execute agent run, emitting Runtime Event envelopes."""
    manager = manager or runtime_mgr
    services = manager.services
    model_mgr = getattr(services, "model_mgr", None) or globals().get("model_mgr")
    memory = getattr(services, "memory", None) or globals().get("memory")
    orchestrator = getattr(services, "orchestrator", None) or globals().get("orchestrator")
    local_execution = getattr(services, "local_execution", None) or globals().get("local_execution")
    sandbox_manager = getattr(services, "sandbox_manager", None) or globals().get("sandbox_manager")
    scheduler = getattr(services, "scheduler", None) or globals().get("scheduler")
    usage_ledger = getattr(services, "usage_ledger", None) or globals().get("usage_ledger")
    assert orchestrator is not None
    assert memory is not None
    had_tool_failure = False
    async def emit(event: str, data: dict[str, Any]) -> None:
        """Emit an event envelope to the client."""
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
        if event in {"run.started", "run.completed", "run.failed"}:
            hooks = _hook_store()
            asyncio.create_task(hooks.execute(event, {
                "run_id": run.run_id, "conversation_id": run.conversation_id,
                "tool_name": "", "parameters": {}, "result": data,
            }, cwd=workspace, emit=emit))
        if event in {"run.completed", "run.failed"} and scheduler is not None:
            asyncio.create_task(scheduler.dispatch_event(event, {
                "run_id": run.run_id, "conversation_id": run.conversation_id,
                "workspace": workspace or "",
            }))

    async def record_reflection(
        category: str, component: str, summary: str, resolution_hint: str,
    ) -> None:
        recorder = getattr(memory, "record_agent_reflection", None)
        if not callable(recorder):
            return
        try:
            await recorder(
                category=category,
                component=component,
                summary=summary,
                resolution_hint=resolution_hint,
                source_conversation_id=run.conversation_id,
                source_run_id=run.run_id,
                model=run.model,
            )
        except Exception as exc:
            log.warning("agent.reflection_record_failed", run_id=run.run_id, error=str(exc))

    async def mark_reflections_recovered() -> None:
        marker = getattr(memory, "mark_agent_reflections_recovered", None)
        if not callable(marker):
            return
        try:
            await marker(run.run_id)
        except Exception as exc:
            log.warning("agent.reflection_recovery_failed", run_id=run.run_id, error=str(exc))

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

    try:
        if run.sandbox:
            docker_status = await sandbox_manager.status()
            if not docker_status["available"]:
                raise RuntimeError(docker_status["detail"])
            await sandbox_manager.start(run.run_id, workspace or "", run.sandbox)
        # Emit run.started
        if not continuation:
            await emit("run.started", {
                "status": "running", "phase": "planning", "content": content,
            })

        # Save user message
        try:
            if continuation:
                if content.strip():
                    await memory.save_message(
                        conversation_id=run.conversation_id, role="user", content=content,
                        metadata={"run_id": run.run_id},
                    )
            else:
                await memory.save_message(
                    conversation_id=run.conversation_id, role="user", content=content,
                    metadata={"run_id": run.run_id},
                )
        except Exception as e:
            run.status = "failed"
            await emit("run.failed", {
                "category": "backend",
                "detail": f"Unable to save user message: {e}",
            })
            return

        if run.executor != "atlas":
            if await check_pause_cancel():
                run.status = "cancelled"
                await emit("run.cancelled", {})
                return
            await emit("run.status", {"status": "running"})
            await emit("run.phase", {"phase": "execution"})
            try:
                response, _changed_files = await _execute_external_agent(
                    run, content, workspace, emit,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                run.status = "failed"
                await emit("run.failed", {
                    "category": "external_agent", "detail": str(exc),
                })
                return
            if response:
                with suppress(Exception):
                    await memory.save_message(
                        conversation_id=run.conversation_id, role="assistant", content=response,
                        metadata={"executor": run.executor, "run_id": run.run_id},
                    )
                await emit("message.completed", {"content": response})
            run.status = "completed"
            await emit("run.completed", {
                "result": "completed", "model": run.model,
                "usage": _sum_usage(run.usage),
                "changes": _run_change_summary(run.run_id),
            })
            return

        if await check_pause_cancel():
            run.status = "cancelled"
            await cancel_local_foreground()
            await emit("run.cancelled", {})
            return

        await emit("run.status", {"status": "running"})
        await emit("run.phase", {"phase": "execution"})

        # Run the agent orchestrator
        full_response = ""

        # Build approval callback that emits approval.required and waits for response
        async def approval_callback(
            approval_event_id: str, tool_name: str, tool_args: dict[str, Any]
        ) -> str:
            """Emit approval.required and wait for client response."""
            approval_payload = {
                "approval_id": approval_event_id,
                "description": f"Agent 请求执行工具 {tool_name}，需要你的确认。",
                "input": {key: value for key, value in tool_args.items()
                          if key not in {"subtask_id", "_reviewer_reason"}},
                "tool": tool_name,
            }
            if tool_args.get("_reviewer_reason"):
                approval_payload["reviewer_reason"] = str(tool_args["_reviewer_reason"])
            if tool_args.get("subtask_id"):
                approval_payload["subtask_id"] = tool_args["subtask_id"]
            approval_future = run.approval_futures.get(approval_event_id)
            if approval_future is None:
                approval_future = asyncio.get_running_loop().create_future()
                run.approval_futures[approval_event_id] = approval_future
            run.status = "waiting"
            await emit("approval.required", approval_payload)

            services = manager.services
            bridge = getattr(services, "gateway_bridge", None) if services else None
            try:
                if bridge is not None and bridge.owns_run(run.run_id):
                    return await bridge.request_approval(
                        run, approval_event_id, approval_payload["description"],
                    )
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
                            return telegram_future.result()
                        if not approval_future.done():
                            approval_future.set_result("deny")
                        return "deny"
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
                        return approval_future.result()
                    if not approval_future.done():
                        approval_future.set_result("deny")
                    return "deny"
                finally:
                    cancel_waiter.cancel()
                    await asyncio.gather(cancel_waiter, return_exceptions=True)
            finally:
                run.approval_futures.pop(approval_event_id, None)
                if run.status == "waiting":
                    run.status = "running"

        async def input_callback(
            call_id: str, question: str, options: list[str] | None,
        ) -> str:
            event_id = f"input:{run.run_id}:{call_id}"
            loop = asyncio.get_running_loop()
            future: asyncio.Future[str] = loop.create_future()
            run.input_futures[event_id] = future
            run.status = "waiting"
            await emit("input.required", {
                "event_id": event_id, "question": question,
                "options": options if isinstance(options, list) else None,
            })
            while not future.done():
                if run.cancel_event.is_set():
                    run.input_futures.pop(event_id, None)
                    raise asyncio.CancelledError
                await asyncio.sleep(0.1)
            answer = future.result()
            run.status = "running"
            return answer

        async def subtask_started(
            subtask_id: str, goal: str, backend: str,
            group_data: dict[str, Any] | None = None,
        ) -> asyncio.Event:
            cancel_event = asyncio.Event()
            run.subtasks[subtask_id] = {
                "subtask_id": subtask_id, "status": "running", "progress": "子 Agent 已启动。",
                "cancel_event": cancel_event, **(group_data or {}),
            }
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
            await emit("subtask.completed", {
                "subtask_id": subtask_id, "status": status,
                "summary": summary, "duration_ms": duration_ms,
                **(group_data or {}),
            })
            if entry and entry.get("background") and not entry.get("group_id"):
                if memory is not None and run.conversation_id:
                    with suppress(Exception):
                        await memory.save_message(
                            run.conversation_id, "assistant",
                            f"后台子 Agent {subtask_id} 已完成：\n{summary}",
                            {"kind": "subtask.background_completed", "subtask_id": subtask_id},
                        )
                await emit("subtask.background_completed", {
                    "subtask_id": subtask_id, "summary": summary,
                })

        async def subtask_group_completed(payload: dict[str, Any]) -> None:
            await emit("subtask.group_completed", payload)
            if payload.get("background"):
                summary = str(payload.get("summary", ""))[:2000]
                if memory is not None and run.conversation_id:
                    with suppress(Exception):
                        await memory.save_message(
                            run.conversation_id, "assistant",
                            f"后台 Worker 组 {payload.get('subtask_id', '')} 已完成：\n{summary}",
                            {"kind": "subtask.background_completed",
                             "subtask_id": payload.get("subtask_id", "")},
                        )
                await emit("subtask.background_completed", {
                    "subtask_id": payload.get("subtask_id", ""), "summary": summary,
                })

        async def user_hook(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
            return await _hook_store().execute(event_name, {
                "run_id": run.run_id, "conversation_id": run.conversation_id,
                **payload,
            }, cwd=workspace, emit=emit)

        async def publish_runtime_event(event: dict[str, Any]) -> None:
            if event.get("type") == "session.title":
                await emit("session.title", {
                    "title": event.get("title", ""),
                    "title_source": event.get("title_source", ""),
                    "accepted": bool(event.get("accepted", False)),
                })

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
            return await sandbox_manager.call_tool(run_id, name, arguments)

        async for event in orchestrator.run(
            message=content,
            conversation_id=run.conversation_id,
            model=model_id,
            cancel_event=run.cancel_event,
            pause_event=run.pause_event,
            approval_callback=approval_callback,
            plan_state=plan_state,
            plan_update_callback=persist_plan,
            source_run_id=run.run_id,
            image_attachments=image_attachments,
            active_skill_instructions=active_skill_instructions,
            run_id=run.run_id,
            steer_queue=run.steer_queue,
            input_callback=input_callback,
            runtime_event_callback=publish_runtime_event,
            workspace=workspace,
            workspace_trusted=bool(workspace and _workspace_trust().get(
                str(Path(workspace).expanduser().resolve()), False,
            )),
            workspace_rules=workspace_rules,
            mode=mode,
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
            reasoning_effort=(run.reasoning_effort if _model_supports_reasoning(
                {"litellm_model": model_id or run.model}
            ) else None),
            subtask_started=subtask_started,
            subtask_progress=subtask_progress,
            subtask_completed=subtask_completed,
            subtask_group_completed=subtask_group_completed,
            force_plan=(mode == "plan"),
        ):
            if await check_pause_cancel():
                run.status = "cancelled"
                await cancel_local_foreground()
                await emit("run.cancelled", {})
                return

            # Map orchestrator events to runtime protocol
            etype = event.get("type", "")

            if etype == "chunk":
                chunk_content = event.get("content", "")
                full_response += chunk_content
                await emit("message.delta", {"content": chunk_content})

            elif etype == "artifact_created":
                await emit("artifact.created", {
                    "path": event.get("path", ""),
                    "kind": event.get("kind", "document"),
                    "bytes": event.get("bytes", 0),
                })

            elif etype == "check.results":
                await emit("check.results", event.get("data", {}))

            elif etype in ("tool_call", "tool_result", "tool_output"):
                mapped = _map_tool_runtime_event(event)
                if mapped is not None:
                    await emit(*mapped)
                if etype == "tool_result" and event.get("error_category") == "tool":
                    had_tool_failure = True
                    detail = "\n".join(
                        str(block.get("text", block))
                        if isinstance(block, dict) else str(block)
                        for block in event.get("content", [])
                    )
                    await record_reflection(
                        "tool",
                        str(event.get("name", "unknown")),
                        detail,
                        "Review the tool error and validate a corrected request before retrying.",
                    )

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
                "lsp.diagnostics", "review.findings",
            }:
                await emit(etype, event.get("data", {}))

            elif etype == "safety_reviewed":
                await emit("safety.reviewed", event.get("data", {}))

            elif etype == "run_verify_nudge":
                await emit("run.verify_nudge", event.get("data", {}))

            elif etype == "run_usage":
                usage = event.get("usage", {})
                if run.reasoning_effort and run.reasoning_effort_applied is None:
                    run.reasoning_effort_applied = _model_supports_reasoning(
                        {"litellm_model": model_id or run.model}
                    )
                    usage["reasoning_effort_applied"] = run.reasoning_effort_applied
                run.usage.append(usage)
                if usage_ledger is not None:
                    event_model = str(usage.get("model") or model_id or run.model)
                    model_config = next((item for item in model_mgr.list_models()
                                         if item.get("litellm_model") == event_model
                                         or item.get("id") == event_model), {}) if model_mgr else {}
                    with suppress(Exception):
                        await usage_ledger.record(
                            run_id=run.run_id, conversation_id=run.conversation_id,
                            subtask_id=None, model=event_model, started_at=run.started_at,
                            usage=usage, price=model_config.get("price"),
                        )
                await emit("run.usage", usage)

            elif etype == "context.window.switched":
                await emit("context.window.switched", event.get("data", {}))

            elif etype == "approval_required":
                # Already emitted by the approval_callback above;
                # no need to re-emit here.
                pass

            elif etype == "plan_updated":
                # The plan state is persisted and emitted by persist_plan.
                pass

            elif etype == "done":
                if mode == "plan":
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
                            await emit("run.cancelled", {})
                            return
                        await asyncio.sleep(0.1)
                    approval = run.plan_future.result()
                    run.plan_future = None
                    if approval.get("action") != "approve":
                        run.status = "cancelled"
                        await emit("run.cancelled", {})
                        return
                    run.status = "running"
                    edits = approval.get("edits", "").strip()
                    await _execute_run(
                        conn_id, run, ("Approved plan. " + edits) if edits else "",
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
                if category in {"tool", "model", "runtime"}:
                    await record_reflection(
                        category,
                        run.model if category == "model" else category,
                        str(event.get("detail", "Unknown error")),
                        "Review failure evidence and validate a proposed resolution before reuse.",
                    )
                await emit("run.failed", {
                    "category": category,
                    "detail": event.get("detail", "Unknown error"),
                })
                return

        # Run completed successfully
        run.status = "completed"
        if had_tool_failure:
            await mark_reflections_recovered()
        if full_response.strip() and run.conversation_id:
            try:
                from atlas.config import DATA_ROOT
                from atlas.engine.session_sync import evaluate_goal_after_turn

                goal_decision = await asyncio.to_thread(
                    evaluate_goal_after_turn, DATA_ROOT / "engine",
                    run.conversation_id, full_response,
                )
            except Exception as exc:
                log.warning("conversation.goal_evaluation_failed",
                            conversation_id=run.conversation_id, error=str(exc))
                goal_decision = None
            if goal_decision is not None:
                if goal_decision.get("message"):
                    await emit("goal.updated", {
                        "status": goal_decision.get("status"),
                        "verdict": goal_decision.get("verdict"),
                        "reason": goal_decision.get("reason"),
                        "message": goal_decision.get("message"),
                    })
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
            "usage": _sum_usage(run.usage),
            "changes": _run_change_summary(run.run_id),
        })

    except asyncio.CancelledError:
        run.status = "cancelled"
        await emit("run.cancelled", {})
    except Exception as e:
        run.status = "failed"
        await record_reflection(
            "runtime", "runtime", str(e),
            "Review the runtime failure evidence and validate a proposed resolution before reuse.",
        )
        await emit("run.failed", {"category": "runtime", "detail": str(e)})
    finally:
        if run.sandbox:
            with suppress(Exception):
                await sandbox_manager.stop(run.run_id)
        if run.ephemeral and run.ephemeral_source and memory is not None:
            with suppress(Exception):
                await memory.delete_conversation(run.ephemeral_source)


# W10: agent_router must mount AFTER the literal /api/agents/... routes above
# (/api/agents/external, /api/agents/types): its GET /api/agents/{agent_id}
# would otherwise shadow them, because FastAPI matches routes in registration
# order and the mount block above runs before those literals are declared.
from atlas.api.agent_router import router as agent_router  # noqa: E402

app.include_router(agent_router)

app.state.services.runtime_start_handler = _handle_run_start
app.state.services.runtime_resume_handler = _handle_resume
app.state.services.rules_trust_handler = _handle_rules_trust
