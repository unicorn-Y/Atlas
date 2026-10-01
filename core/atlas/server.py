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
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
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
from fastapi.middleware.cors import CORSMiddleware
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
from atlas.capabilities.browser.browser_use import BrowserUseAdapter
from atlas.capabilities.coding import ast_grep as ast_grep_capability
from atlas.capabilities.coding.repo_map import repo_map
from atlas.capabilities.computer.cua_backend import CuaBackend
from atlas.capabilities.computer.uia_backend import list_windows as list_uia_windows
from atlas.capabilities.durable.dbos_backend import DurableBackend
from atlas.capabilities.durable.dbos_backend import status as dbos_status
from atlas.config import get_config, load_user_settings, save_user_settings
from atlas.memory.store import MemoryStore
from atlas.models.manager import ModelManager
from atlas.office import MAX_PREVIEW_BYTES, render_office
from atlas.notifications import NotificationBus
from atlas.origin_guard import DEV_ORIGINS, OriginGuard
from atlas.plugins import PluginRuntime
from atlas.projects import ProjectStore
from atlas.runtime import hub_control
from atlas.runtime.hooks import HookStore
from atlas.runtime.backend_host import AgentBackendHost
from atlas.runtime.capability_bus import CapabilityBus
from atlas.runtime.external_agents import external_agent_status, normalize_external_event
from atlas.scheduler import AtlasScheduler, ScheduledTask, TaskStatus, TriggerType
from atlas.sandbox import DockerSandboxManager
from atlas.skills import PROJECT_ROOT, SKILLS_DIR, SkillManager
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


def _task_store(kind: str) -> TomlRecordStore:
    return TomlRecordStore(get_config().db_path.parent, kind)


def _kanban_store():
    from atlas.kanban import KanbanStore

    return KanbanStore(get_config().db_path)


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


async def _run_scheduled_goal(task_id: str, message: str) -> None:
    """Run one verified goal iteration through the normal planner and tool gates."""
    if scheduler is None:
        return
    task = scheduler.get_task(task_id)
    if task is None or not task.goal:
        return
    run_id = str(uuid.uuid4())
    if orchestrator is None:
        await _record_goal_failure(
            task_id, run_id, message, "runtime", "Agent orchestrator is unavailable.",
        )
        progress = dict(task.goal_progress or {})
        prior_trace = progress.get("execution_trace", {})
        if not isinstance(prior_trace, dict):
            prior_trace = {}
        progress.update({
            "blocked": True,
            "blocked_reason": "orchestrator_unavailable",
            "reflection_run_ids": [*progress.get("reflection_run_ids", []), run_id],
            "execution_trace": {"run_id": run_id, "plan_id": prior_trace.get("plan_id")},
        })
        await scheduler.update_goal_state(task_id, status="blocked", progress=progress)
        await scheduler.record_goal_event(task_id, "goal.failed", {
            "detail": "Agent orchestrator is unavailable.",
        }, run_id=run_id)
        return

    prior_trace = task.goal_progress.get("execution_trace", {})
    if not isinstance(prior_trace, dict):
        prior_trace = {}
    active_plan_id = prior_trace.get("plan_id")
    progress = dict(task.goal_progress or {})
    progress["execution_trace"] = {"run_id": run_id, "plan_id": active_plan_id}
    await scheduler.update_goal_state(task_id, status="running", progress=progress)
    await scheduler.record_goal_event(task_id, "goal.triggered", {}, run_id=run_id,
                                      plan_id=active_plan_id)
    approval_required = False
    prior_reflection_runs = list(progress.get("reflection_run_ids", []))
    goal_evaluation_passed = False
    goal_evaluation_processed = False
    goal_evaluation_steps: list[dict[str, Any]] = []
    goal_outcome_recorded = False

    async def persist_goal_outcome(fallback_progress: dict[str, Any]) -> None:
        nonlocal goal_outcome_recorded
        if goal_outcome_recorded or not memory or not hasattr(memory, "record_goal_outcome"):
            return
        outcome_progress = dict(task.goal_progress or fallback_progress)
        try:
            await memory.record_goal_outcome(
                goal_id=task_id,
                goal=task.goal,
                status=task.goal_status,
                evaluation=outcome_progress.get("last_evaluation", {}),
                steps=(
                    goal_evaluation_steps
                    if goal_evaluation_processed
                    else outcome_progress.get("subtasks", [])
                ),
                source_conversation_id=f"scheduled-goal-{task_id}",
                source_run_id=run_id,
            )
            goal_outcome_recorded = True
        except Exception:
            log.warning("goal.outcome_persist_failed", task_id=task_id, run_id=run_id)

    async def approval_callback(
        event_id: str, tool_name: str, tool_args: dict[str, Any],
    ) -> str:
        nonlocal approval_required
        approval_required = True
        blocked_progress = dict(task.goal_progress or {})
        blocked_progress["blocked"] = True
        blocked_progress["blocked_reason"] = "approval_required"
        await scheduler.update_goal_state(
            task_id, status="awaiting_approval", progress=blocked_progress,
        )
        await scheduler.record_goal_event(task_id, "approval.required", {
            "approval_id": event_id,
            "tool": tool_name,
            "decision": "denied; explicit user approval is required",
        }, run_id=run_id, plan_id=active_plan_id)
        return "deny"

    async def persist_plan(value: dict[str, Any]) -> None:
        nonlocal active_plan_id
        plan = TaskPlan.from_dict(value)
        plan_value = plan.to_dict()
        plan_id = str(uuid.uuid5(
            uuid.UUID(run_id),
            json.dumps(plan_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        ))
        active_plan_id = plan_id
        completed = [item.id for item in plan.subtasks if item.status == "completed"]
        pending = [item.id for item in plan.subtasks if item.status != "completed"]
        state = {
            **dict(task.goal_progress or {}),
            **plan_value,
            "current_step": pending[0] if pending else None,
            "completed_steps": completed,
            "blocked": False,
            "reflection_run_ids": prior_reflection_runs,
            "execution_trace": {"run_id": run_id, "plan_id": plan_id},
        }
        await scheduler.update_goal_state(task_id, status="running", progress=state)
        await scheduler.record_goal_event(task_id, "plan.updated", {
            "step_ids": [item.id for item in plan.subtasks],
            "plan": value,
        }, run_id=run_id, plan_id=plan_id)

    async def persist_goal_evaluation(value: Any) -> None:
        nonlocal goal_evaluation_passed, goal_evaluation_processed, goal_evaluation_steps
        evaluation = value if isinstance(value, dict) else {}
        passed = (
            evaluation.get("satisfied") is True
            and isinstance(evaluation.get("evidence"), str)
            and bool(evaluation["evidence"].strip())
        )
        decision = {
            "satisfied": passed,
            "evidence": evaluation.get("evidence", "")
            if isinstance(evaluation.get("evidence"), str) else "",
            "reason": evaluation.get("reason", "")
            if isinstance(evaluation.get("reason"), str) else "",
        }
        goal_evaluation_passed = passed
        goal_evaluation_processed = True
        current_progress = dict(task.goal_progress or progress)
        goal_evaluation_steps = [
            step for step in current_progress.get("subtasks", [])
            if isinstance(step, dict)
        ]
        if passed:
            current_progress["last_evaluation"] = decision
            await scheduler.update_goal_state(
                task_id, status="running", progress=current_progress,
            )
            await scheduler.record_goal_event(
                task_id, "goal.evaluated", decision,
                run_id=run_id, plan_id=active_plan_id,
            )
            return

        next_replan_count = int(current_progress.get("replan_count", 0)) + 1
        replan_progress = {
            "goal": task.goal,
            "subtasks": [],
            "current_step": None,
            "completed_steps": [],
            "blocked": False,
            "reflection_run_ids": prior_reflection_runs,
            "replan_count": next_replan_count,
            "last_evaluation": decision,
            "execution_trace": {"run_id": run_id, "plan_id": active_plan_id},
        }
        await scheduler.update_goal_state(
            task_id, status="pending", progress=replan_progress,
        )
        await scheduler.record_goal_event(
            task_id, "goal.evaluation_failed", decision,
            run_id=run_id, plan_id=active_plan_id,
        )
        await scheduler.record_goal_event(task_id, "goal.replanned", {
            "replan_count": next_replan_count,
            "reason": decision["reason"] or "Goal evidence was insufficient.",
        }, run_id=run_id, plan_id=active_plan_id)

    saved_plan = task.goal_progress or None
    if saved_plan:
        try:
            TaskPlan.from_dict(saved_plan)
        except (TypeError, ValueError):
            saved_plan = None

    try:
        async for event in orchestrator.run(
            message=message,
            conversation_id=f"scheduled-goal-{task_id}",
            approval_callback=approval_callback,
            plan_state=saved_plan,
            plan_update_callback=persist_plan,
            force_plan=True,
            evaluate_goal=True,
            source_run_id=run_id,
        ):
            event_type = event.get("type", "unknown")
            if event_type == "goal_evaluated":
                await persist_goal_evaluation(event.get("evaluation"))
                continue
            if event_type not in {"plan_updated", "approval_required"}:
                event_step = event.get("step_id", event.get("subtask_id"))
                if not isinstance(event_step, str) and isinstance(event.get("step"), dict):
                    event_step = event["step"].get("id")
                await scheduler.record_goal_event(
                    task_id,
                    f"execution.{event_type}",
                    {key: event[key] for key in ("category",) if key in event},
                    run_id=run_id, plan_id=active_plan_id,
                    step_id=event_step if isinstance(event_step, str) else None,
                )
            if event_type == "error":
                category = event.get("category")
                await _record_goal_failure(
                    task_id, run_id, message,
                    category if category in {"tool", "model", "runtime"} else "runtime",
                    str(event.get("detail", "Goal execution failed.")),
                )
                progress = dict(task.goal_progress or progress)
                progress.update({"blocked": True, "blocked_reason": "execution_error"})
                progress["reflection_run_ids"] = [*prior_reflection_runs, run_id]
                await scheduler.update_goal_state(
                    task_id, status="blocked", progress=progress,
                )
                await persist_goal_outcome(progress)
            elif event_type == "done" and not approval_required:
                final_progress = dict(task.goal_progress or progress)
                subtasks = final_progress.get("subtasks", [])
                plan_complete = bool(subtasks) and all(
                    isinstance(item, dict) and item.get("status") == "completed"
                    and isinstance(item.get("evidence"), str)
                    and bool(item["evidence"].strip())
                    for item in subtasks
                )
                if plan_complete and not goal_evaluation_processed:
                    await persist_goal_evaluation({
                        "satisfied": False,
                        "evidence": "",
                        "reason": "No valid goal evaluation was produced.",
                    })
                final_progress = dict(task.goal_progress or progress)
                subtasks = final_progress.get("subtasks", [])
                verified = bool(subtasks) and all(
                    isinstance(item, dict) and item.get("status") == "completed"
                    and isinstance(item.get("evidence"), str)
                    and bool(item["evidence"].strip())
                    for item in subtasks
                )
                if verified and goal_evaluation_passed:
                    final_progress.update({
                        "current_step": None,
                        "completed_steps": [item["id"] for item in subtasks],
                        "blocked": False,
                    })
                    await scheduler.update_goal_state(
                        task_id, status="completed", progress=final_progress,
                    )
                    await scheduler.record_goal_event(task_id, "goal.verified", {
                        "completed_steps": final_progress["completed_steps"],
                    }, run_id=run_id, plan_id=active_plan_id)
                    if memory:
                        for failed_run_id in prior_reflection_runs:
                            try:
                                await memory.mark_agent_reflections_recovered(failed_run_id)
                            except Exception:
                                pass
                else:
                    pending = [
                        item.get("id") for item in subtasks
                        if isinstance(item, dict) and item.get("status") != "completed"
                    ]
                    final_progress.update({
                        "current_step": pending[0] if pending else None,
                        "completed_steps": [
                            item.get("id") for item in subtasks
                            if isinstance(item, dict) and item.get("status") == "completed"
                        ],
                        "blocked": False,
                    })
                    await scheduler.update_goal_state(
                        task_id, status="pending", progress=final_progress,
                    )
                    await scheduler.record_goal_event(task_id, "goal.continuation_pending", {
                        "current_step": final_progress["current_step"],
                    }, run_id=run_id, plan_id=active_plan_id,
                        step_id=final_progress["current_step"])
                await persist_goal_outcome(final_progress)
    except Exception as exc:
        status = "awaiting_approval" if approval_required else "blocked"
        if not approval_required:
            await _record_goal_failure(task_id, run_id, message, "runtime", str(exc))
        progress = dict(task.goal_progress or {})
        progress["blocked"] = True
        progress["blocked_reason"] = "approval_required" if approval_required else "execution_error"
        if not approval_required:
            progress["reflection_run_ids"] = [*prior_reflection_runs, run_id]
        await scheduler.update_goal_state(task_id, status=status, progress=progress)
        await scheduler.record_goal_event(task_id, "execution.error", {
            "detail": str(exc),
        }, run_id=run_id, plan_id=active_plan_id)
        await persist_goal_outcome(progress)


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
# Lifespan (replaces deprecated @app.on_event)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    global model_mgr, memory, orchestrator, mcp_client, local_execution, computer_use
    global skill_mgr, skill_registry, scheduler
    global capability_bus, cua_backend, browser_use, agent_backend_host
    global projects, durable, plugin_runtime, notifications, web_runtime, custom_tools, telegram_service
    global usage_ledger

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

    await runtime_mgr.init(get_config().db_path)

    mcp_client = MCPClient()
    await mcp_client.start()
    local_execution = LocalExecutionRuntime()
    cua_backend = CuaBackend()
    computer_use = ComputerUseRuntime(cua_backend=cua_backend)
    capability_bus = CapabilityBus(dict(get_config().raw.get("integrations", {})))
    browser_use = BrowserUseAdapter()
    agent_backend_host = AgentBackendHost()

    skill_mgr = SkillManager()
    await skill_mgr.scan_skills()
    cfg = get_config()
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

    notifications = NotificationBus()
    if plugin_load_report.get("errors"):
        log.warning("plugins.load_errors", errors=plugin_load_report["errors"])

    if cfg.scheduler_enabled:
        scheduler = AtlasScheduler(agent_callback=_scheduled_goal)
        await scheduler.start()

    telegram_service = TelegramService(
        cfg.db_path.parent / "telegram.json",
        owns_lease=_owns_scheduler_lease,
        submit_task=_telegram_submit_task,
        command_handler=_telegram_command,
    )
    telegram_service.start()

    yield  # app is running

    # Shutdown
    if telegram_service:
        await telegram_service.stop()
    if scheduler:
        await scheduler.stop()
    if mcp_client:
        await mcp_client.stop()
    if local_execution:
        await local_execution.shutdown()
    if computer_use:
        await computer_use.shutdown()
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
    await runtime_mgr.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Atlas", version="0.1.0", lifespan=lifespan)

def _configured_origins() -> list[str]:
    value = get_config().get("server.allowed_origins", [])
    return [str(item) for item in value] if isinstance(value, list) else []


# "null" is the packaged renderer (file://). CORS only decides who may read responses;
# OriginGuard, added last and therefore outermost, decides who may send requests at all.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[*sorted(DEV_ORIGINS), "null", *_configured_origins()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(OriginGuard, extra_origins=_configured_origins)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ModelListResponse(BaseModel):
    models: list[dict[str, Any]]
    current: str


class ModelSelectRequest(BaseModel):
    model: str


class ProviderSettingsRequest(BaseModel):
    gateway_base_url: str
    api_key: str | None = None
    agent_engine: str | None = None
    compression_model: str | None = None


class CustomModelRequest(BaseModel):
    id: str
    name: str
    provider: str
    litellm_model: str
    prompt_cache: str | None = None
    prompt_cache_ttl: str | None = None
    max_output_tokens: int | None = None
    price: dict[str, Any] | None = None


class ConnectionTestRequest(BaseModel):
    model: str | None = None


class ConversationUpdateRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    workspace: str | None = None
    permission_mode: str | None = None
    allowed_paths: list[str] | None = None
    executor: str | None = None
    sandbox: dict[str, Any] | None = None
    extra_roots: list[str] | None = None


class ConversationCreateRequest(BaseModel):
    title: str = "New Conversation"


class FactCreateRequest(BaseModel):
    key: str
    value: str
    category: str = "general"


class ScheduleCreateRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    trigger_type: str = "cron"  # cron | interval | date
    trigger_args: dict[str, Any] = {}
    action: str  # "agent:<message>"
    tags: list[str] = []


class ScheduleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_type: str | None = None
    trigger_args: dict[str, Any] | None = None
    action: str | None = None
    status: str | None = None  # "active" | "paused"
    tags: list[str] | None = None


class GoalCreateRequest(BaseModel):
    id: str
    name: str
    goal: str
    description: str = ""
    trigger_type: str = "cron"
    trigger_args: dict[str, Any] = {}
    tags: list[str] = []


class IntegrationToggleRequest(BaseModel):
    enabled: bool


class AgentSessionStartRequest(BaseModel):
    cwd: str | None = None


class AgentPromptRequest(BaseModel):
    prompt: str


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/sandbox/status")
async def sandbox_status() -> dict[str, Any]:
    return {"docker": await sandbox_manager.status()}


@app.get("/api/runtime/observability")
async def runtime_observability() -> dict[str, Any]:
    """Report runtime component availability and durable autonomous activity."""
    scheduler_snapshot = scheduler.observability_snapshot() if scheduler else None
    components = {
        "scheduler": {
            "available": scheduler is not None,
            "running": bool(scheduler_snapshot and scheduler_snapshot["scheduler_running"]),
        },
        "orchestrator": {"available": orchestrator is not None},
        "memory": {"available": memory is not None},
    }
    ready = all(component["available"] for component in components.values())
    ready = ready and components["scheduler"]["running"]
    return {
        "status": "ok" if ready else "degraded",
        "components": components,
        "autonomous": scheduler_snapshot,
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@app.get("/api/models")
async def list_models() -> ModelListResponse:
    """Return available models and currently selected one."""
    assert model_mgr is not None
    models = model_mgr.list_models()
    for item in models:
        item["supports_reasoning_effort"] = _model_supports_reasoning(item)
    return ModelListResponse(
        models=models,
        current=model_mgr.current_model,
    )


def _model_supports_reasoning(model: dict[str, Any]) -> bool:
    try:
        from litellm import get_supported_openai_params
        model_name = model.get("litellm_model", model.get("id", ""))
        provider = model.get("provider")
        params = get_supported_openai_params(model=model_name, custom_llm_provider=provider)
        return isinstance(params, list) and "reasoning_effort" in params
    except Exception:
        return False


@app.post("/api/models/select")
async def select_model(req: ModelSelectRequest) -> dict[str, str]:
    """Switch the active model."""
    assert model_mgr is not None
    try:
        model_mgr.select(req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "model": model_mgr.current_model}


@app.get("/api/settings/configuration")
async def get_configuration() -> dict[str, Any]:
    assert model_mgr is not None
    settings = load_user_settings()
    return {
        "gateway_base_url": model_mgr.gateway_base_url,
        "api_key_configured": model_mgr.api_key_configured,
        "models": model_mgr.list_models(),
        "current": model_mgr.current_model,
        "agent_engine": str(settings.get(
            "agent_engine", get_config().get("agent.engine", "hermes"),
        )),
        "compression_model": str(settings.get("compression_model", "")),
    }


class ImageGenerateRequest(BaseModel):
    prompt: str
    model: str = "gpt-image-1"
    size: str = "1024x1024"
    n: int = 1


@app.post("/api/images/generate")
async def generate_image(req: ImageGenerateRequest) -> dict[str, Any]:
    """Forward an image-generation request to the configured model gateway.

    Keeps the gateway API key server-side; the renderer never sees it.
    """
    assert model_mgr is not None
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="提示词不能为空")
    base = model_mgr.gateway_base_url.rstrip("/")
    key = getattr(model_mgr, "_api_key", "") or get_config().gateway_api_key
    if not key:
        raise HTTPException(status_code=400, detail="尚未配置模型网关密钥")
    payload = {"model": req.model, "prompt": prompt, "n": max(1, min(req.n, 4)), "size": req.size}
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{base}/images/generations",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
    except Exception as exc:  # noqa: BLE001 — surface any transport error to the UI
        raise HTTPException(status_code=502, detail=f"图像网关请求失败：{exc}")
    if resp.status_code >= 400:
        detail = resp.text
        try:
            detail = resp.json().get("error", {}).get("message", detail)
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(status_code=resp.status_code, detail=detail)
    data = resp.json()
    images: list[dict[str, str]] = []
    for item in data.get("data", []):
        if item.get("url"):
            images.append({"url": item["url"]})
        elif item.get("b64_json"):
            images.append({"b64": item["b64_json"]})
    return {"images": images, "model": req.model}


@app.put("/api/settings/configuration")
async def update_configuration(req: ProviderSettingsRequest) -> dict[str, Any]:
    assert model_mgr is not None
    base_url = req.gateway_base_url.strip()
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="服务地址必须以 http:// 或 https:// 开头")
    if req.agent_engine is not None and req.agent_engine not in {"hermes", "legacy"}:
        raise HTTPException(status_code=400, detail="agent_engine 只能是 hermes 或 legacy")
    if req.compression_model is not None and req.compression_model and not any(
        item.get("id") == req.compression_model for item in model_mgr.list_models()
    ):
        raise HTTPException(status_code=400, detail="压缩模型必须来自已配置的模型列表")
    api_key = req.api_key.strip() if req.api_key and req.api_key.strip() else None
    model_mgr.update_provider(base_url, api_key)
    if req.agent_engine is not None or req.compression_model is not None:
        settings = load_user_settings()
    if req.agent_engine is not None:
        settings["agent_engine"] = req.agent_engine
    if req.compression_model is not None:
        settings["compression_model"] = req.compression_model
    if req.agent_engine is not None or req.compression_model is not None:
        save_user_settings(settings)
    return await get_configuration()


@app.post("/api/models/custom")
async def add_custom_model(req: CustomModelRequest) -> dict[str, Any]:
    assert model_mgr is not None
    model_id = req.id.strip()
    if not model_id or not req.provider.strip() or not req.litellm_model.strip():
        raise HTTPException(status_code=400, detail="模型 ID、提供商和 LiteLLM 模型名均为必填项")
    try:
        model_mgr.add_model({
            "id": model_id,
            "name": req.name.strip() or model_id,
            "provider": req.provider.strip(),
            "litellm_model": req.litellm_model.strip(),
            "category": "custom",
            **({"prompt_cache": req.prompt_cache} if req.prompt_cache else {}),
            **({"prompt_cache_ttl": req.prompt_cache_ttl} if req.prompt_cache_ttl else {}),
            **({"max_output_tokens": req.max_output_tokens} if req.max_output_tokens else {}),
            **({"price": req.price} if req.price else {}),
        })
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await get_configuration()


@app.post("/api/settings/test-connection")
async def test_connection(req: ConnectionTestRequest) -> dict[str, Any]:
    assert model_mgr is not None
    selected = req.model or model_mgr.current_model
    model = next((item for item in model_mgr.list_models() if item["id"] == selected), None)
    if model is None:
        raise HTTPException(status_code=400, detail=f"Unknown model: {selected}")

    from litellm import acompletion

    try:
        await acompletion(
            model=str(model.get("litellm_model", selected)),
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=2,
        )
    except Exception as exc:
        return {"ok": False, "model": selected, "message": str(exc)}
    return {"ok": True, "model": selected, "message": "模型连接测试成功。"}


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

@app.get("/api/conversations")
async def list_conversations() -> list[dict[str, Any]]:
    """Return all conversation summaries."""
    assert memory is not None
    return await memory.list_conversations()


@app.post("/api/conversations")
async def create_conversation(req: ConversationCreateRequest) -> dict[str, Any]:
    """Create and return a conversation summary."""
    assert memory is not None
    conversation_id = await memory.create_conversation(req.title.strip() or "New Conversation")
    conversation = await memory.get_conversation(conversation_id)
    assert conversation is not None
    return conversation


@app.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Return messages for a conversation."""
    assert memory is not None
    conv = await memory.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await memory.get_conversation_messages(conversation_id, limit=limit)


@app.put("/api/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    req: ConversationUpdateRequest,
) -> dict[str, str]:
    """Persist conversation title and runtime preferences."""
    assert memory is not None
    values = req.model_dump(exclude_unset=True)
    if values.get("permission_mode") not in {
        None, "full_access", "ask_writes", "read_only",
    }:
        raise HTTPException(status_code=400, detail="invalid permission_mode")
    paths = values.get("allowed_paths")
    if paths is not None and any(
        not isinstance(path, str) or not Path(path).is_absolute() for path in paths
    ):
        raise HTTPException(status_code=400, detail="allowed_paths must contain absolute paths")
    workspace = values.get("workspace")
    if workspace:
        try:
            if workspace.startswith("ssh://"):
                ssh_workspaces.parse_workspace(workspace)
            elif not Path(workspace).is_absolute():
                raise ValueError("workspace must be absolute")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    roots = values.get("extra_roots")
    if roots is not None:
        if len(roots) > 5:
            raise HTTPException(status_code=400, detail="最多可添加 5 个附加目录。")
        try:
            normalized_roots = []
            for root in roots:
                if not isinstance(root, str):
                    raise ValueError("附加目录无效。")
                if root.startswith("ssh://"):
                    ssh_workspaces.parse_workspace(root)
                    normalized_roots.append(root)
                elif Path(root).is_absolute():
                    normalized_roots.append(str(Path(root).expanduser().resolve()))
                else:
                    raise ValueError("附加目录必须是绝对路径或 SSH 地址。")
            values["extra_roots"] = normalized_roots
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "sandbox" in values and values["sandbox"] is not None:
        sandbox = values["sandbox"]
        if sandbox.get("type") != "docker" or not isinstance(
            sandbox.get("network", False), bool
        ):
            raise HTTPException(status_code=400, detail="invalid sandbox settings")
    ok = await memory.update_conversation(
        conversation_id,
        title=values.get("title"), pinned=values.get("pinned"),
        archived=values.get("archived"), workspace=values.get("workspace"),
        permission_mode=values.get("permission_mode"),
        allowed_paths=values.get("allowed_paths"), executor=values.get("executor"),
        sandbox=values.get("sandbox"), sandbox_set="sandbox" in values,
        extra_roots=values.get("extra_roots"),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "ok", "conversation_id": conversation_id}


@app.post("/api/conversations/{conversation_id}/truncate")
async def truncate_conversation(conversation_id: str, req: dict[str, Any]) -> dict[str, str]:
    assert memory is not None
    message_id = str(req.get("from_message_id", ""))
    if not message_id:
        raise HTTPException(status_code=400, detail="from_message_id is required")
    messages = await memory.get_messages_with_rowid(conversation_id)
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import rewind_to_atlas_message, restore_session

    snapshot = await asyncio.to_thread(
        rewind_to_atlas_message, DATA_ROOT / "engine", conversation_id, messages, message_id,
    )
    if not await memory.truncate_conversation(conversation_id, message_id):
        if snapshot:
            await asyncio.to_thread(restore_session, DATA_ROOT / "engine", snapshot)
        raise HTTPException(status_code=404, detail="Conversation or message not found")
    return {"status": "ok", "conversation_id": conversation_id}


def _conversation_has_active_run(conversation_id: str) -> bool:
    return any(run.conversation_id == conversation_id and run.status in {
        "running", "waiting", "paused",
    } for run in runtime_mgr.runs.values())


async def _snapshot_rewind_files(
    run_ids: list[str], roots: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    checkpoints: list[tuple[str, str, str, str]] = []
    store = getattr(orchestrator, "checkpoints", None) if orchestrator else None
    for run_id in run_ids:
        if store is not None:
            for item in store.list_checkpoints(run_id=run_id):
                manifest_path = store.storage_dir / item["id"] / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                root = str(Path(manifest["workspace"]).resolve())
                checkpoints.append((manifest.get("created_at", ""), "local", root, item["id"]))
                for entry in manifest.get("files", []):
                    if entry.get("directory"):
                        continue
                    key = (root, str(entry["path"]))
                    target = (Path(root) / entry["path"]).resolve()
                    if Path(root) not in target.parents:
                        continue
                    exists = target.is_file()
                    data = await asyncio.to_thread(target.read_bytes) if exists else b""
                    snapshots[key] = {"root": root, "path": str(entry["path"]),
                                      "exists": exists,
                                      "data": base64.b64encode(data).decode("ascii")}
        for root in roots:
            if not root.startswith("ssh://"):
                continue
            with suppress(Exception):
                host, remote_root = ssh_workspaces.parse_workspace(root)
                for item in await ssh_workspaces.list_checkpoints(root, run_id=run_id):
                    checkpoints.append((str(item.get("created_at", "")), "ssh", root, item["id"]))
                    for entry in item.get("files", []):
                        if entry.get("directory"):
                            continue
                        relative = str(entry["path"])
                        target = str(PurePosixPath(remote_root) / relative)
                        exists = bool(entry.get("exists"))
                        data = await ssh_workspaces.read_bytes(host, target) if exists else b""
                        snapshots[(root, relative)] = {
                            "root": root, "path": relative, "exists": exists,
                            "data": base64.b64encode(data).decode("ascii"),
                        }
    checkpoints.sort(key=lambda item: item[0], reverse=True)
    return list(snapshots.values()), [
        {"kind": kind, "root": root, "checkpoint_id": checkpoint_id}
        for _created, kind, root, checkpoint_id in checkpoints
    ]


async def _restore_rewind_files(files: list[dict[str, Any]]) -> None:
    for item in files:
        root, relative = item["root"], item["path"]
        data = base64.b64decode(item.get("data", ""), validate=True)
        if root.startswith("ssh://"):
            host, remote_root = ssh_workspaces.parse_workspace(root)
            target = str(PurePosixPath(remote_root) / relative)
            if item["exists"]:
                await ssh_workspaces.write_bytes(host, target, data)
            else:
                await ssh_workspaces.call_tool(
                    "local_file", {"action": "delete", "path": target}, root,
                )
        else:
            base = Path(root).resolve()
            target = (base / relative).resolve()
            if target != base and base not in target.parents:
                raise ValueError("回退文件超出了工作目录。")
            if item["exists"]:
                target.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(target.write_bytes, data)
            elif target.is_file():
                await asyncio.to_thread(target.unlink)


async def _restore_run_checkpoints(
    checkpoints: list[dict[str, str]],
) -> tuple[list[str], list[dict[str, str]]]:
    restored: list[str] = []
    skipped: list[dict[str, str]] = []
    for item in checkpoints:
        try:
            if item["kind"] == "ssh":
                data = await ssh_workspaces.restore_checkpoint(item["root"], item["checkpoint_id"])
            else:
                data = await asyncio.to_thread(
                    orchestrator.checkpoints.restore_checkpoint, item["checkpoint_id"],
                )
            restored.extend(str(path) for path in data.get("restored", []))
        except Exception as exc:
            skipped.append({"path": item["root"], "reason": str(exc)[:500]})
    return restored, skipped


@app.post("/api/conversations/{conversation_id}/rewind")
async def rewind_conversation(conversation_id: str, req: dict[str, Any]) -> dict[str, Any]:
    assert memory is not None
    if _conversation_has_active_run(conversation_id):
        raise HTTPException(status_code=409, detail="这段对话仍在运行，请等它结束后再回退。")
    message_id = req.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        raise HTTPException(status_code=400, detail="请选择要回退到的消息。")
    if not isinstance(req.get("files"), bool):
        raise HTTPException(status_code=400, detail="请指定是否同时恢复文件。")
    messages = await memory.get_messages_with_rowid(conversation_id)
    boundary = next((index for index, item in enumerate(messages) if item["id"] == message_id), None)
    if boundary is None:
        raise HTTPException(status_code=404, detail="找不到这段对话或指定消息。")
    removed = messages[boundary:]
    run_ids = []
    for item in removed:
        with suppress(TypeError, ValueError):
            run_id = json.loads(item.get("metadata") or "{}").get("run_id")
            if run_id and run_id not in run_ids:
                run_ids.append(str(run_id))
    conversation = await memory.get_conversation(conversation_id) or {}
    roots = [*([conversation["workspace"]] if conversation.get("workspace") else []),
             *conversation.get("extra_roots", [])]
    file_snapshot, checkpoints = ([], [])
    if req["files"]:
        file_snapshot, checkpoints = await _snapshot_rewind_files(run_ids, roots)
    rewind_id = uuid.uuid4().hex
    snapshot = {"messages": messages, "files": file_snapshot,
                "checkpoints": checkpoints, "files_requested": req["files"]}
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import capture_session, restore_session, rewind_to_atlas_message

    hermes_snapshot = await asyncio.to_thread(
        capture_session, DATA_ROOT / "engine", conversation_id,
    )
    if hermes_snapshot:
        snapshot["hermes_session"] = hermes_snapshot
    await memory.save_rewind({
        "rewind_id": rewind_id, "conversation_id": conversation_id,
        "removed_messages": len(removed), "restored_files": 0, "snapshot": snapshot,
    })
    restored_files: list[str] = []
    skipped: list[dict[str, str]] = []
    try:
        if req["files"]:
            restored_files, skipped = await _restore_run_checkpoints(checkpoints)
        removed_row = await memory.remove_messages_from(conversation_id, message_id)
        if removed_row is None:
            if req["files"]:
                await _restore_rewind_files(file_snapshot)
            if hermes_snapshot:
                await asyncio.to_thread(restore_session, DATA_ROOT / "engine", hermes_snapshot)
            raise HTTPException(status_code=404, detail="找不到指定消息。")
        if hermes_snapshot:
            await asyncio.to_thread(
                rewind_to_atlas_message, DATA_ROOT / "engine", conversation_id, messages, message_id,
            )
    except HTTPException:
        raise
    except Exception:
        await memory.replace_messages(conversation_id, messages)
        if hermes_snapshot:
            await asyncio.to_thread(restore_session, DATA_ROOT / "engine", hermes_snapshot)
        if req["files"]:
            await _restore_rewind_files(file_snapshot)
        raise
    db = memory._db
    if db is not None:
        await db.execute(
            "UPDATE conversation_rewinds SET restored_files=? WHERE rewind_id=?",
            (len(restored_files), rewind_id),
        )
        await db.commit()
    return {"rewind_id": rewind_id, "removed_messages": len(removed),
            "restored_files": sorted(set(restored_files)), "skipped": skipped}


@app.post("/api/conversations/{conversation_id}/rewind/{rewind_id}/redo")
async def redo_conversation_rewind(conversation_id: str, rewind_id: str) -> dict[str, Any]:
    assert memory is not None
    if _conversation_has_active_run(conversation_id):
        raise HTTPException(status_code=409, detail="这段对话仍在运行，请等它结束后再重做。")
    if not re.fullmatch(r"[0-9a-f]{32}", rewind_id):
        raise HTTPException(status_code=404, detail="找不到这条回退记录。")
    record = await memory.get_rewind(conversation_id, rewind_id)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到这条回退记录。")
    if record["redone"]:
        raise HTTPException(status_code=409, detail="这次回退已经重做过了。")
    snapshot = record["snapshot"]
    if snapshot.get("files_requested"):
        await _restore_rewind_files(snapshot.get("files", []))
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import restore_session

    await asyncio.to_thread(
        restore_session, DATA_ROOT / "engine", snapshot.get("hermes_session"),
    )
    await memory.replace_messages(conversation_id, snapshot.get("messages", []))
    await memory.mark_rewind_redone(conversation_id, rewind_id)
    return {"status": "redone", "rewind_id": rewind_id}


@app.get("/api/conversations/{conversation_id}/rewinds")
async def list_conversation_rewinds(conversation_id: str) -> list[dict[str, Any]]:
    assert memory is not None
    if await memory.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="找不到这段对话。")
    return await memory.list_rewinds(conversation_id)


@app.post("/api/conversations/{conversation_id}/fork", status_code=201)
async def fork_conversation(conversation_id: str, req: dict[str, Any]) -> dict[str, Any]:
    assert memory is not None
    message_id = str(req.get("through_message_id", ""))
    source_messages = await memory.get_messages_with_rowid(conversation_id)
    result = await memory.fork_conversation(conversation_id, message_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation or message not found")
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import fork_session

    await asyncio.to_thread(
        fork_session, DATA_ROOT / "engine", conversation_id, str(result["id"]),
        source_messages, message_id,
    )
    await memory.update_conversation(
        result["id"], parent_conversation_id=conversation_id, fork_message_id=message_id,
        workspace=(await memory.get_conversation(conversation_id) or {}).get("workspace"),
    )
    persisted = await memory.get_conversation(result["id"])
    if persisted is not None:
        result = {**persisted, **{key: result[key] for key in ("files_shared",) if key in result}}
    if req.get("summarize") is True:
        source_messages = await memory.get_conversation_messages(conversation_id, limit=1000)
        boundary = next((i for i, item in enumerate(source_messages) if item["id"] == message_id), -1)
        before = source_messages[:boundary + 1]
        compacted = await orchestrator.context_maintenance.compact({
            "goal": result.get("title", "Conversation fork"),
            "session_summary": "\n".join(f"{m['role']}: {m['content'][:1000]}" for m in before[-20:]),
        }) if orchestrator else {"session_summary": "\n".join(m["content"][:300] for m in before[-10:])}
        await memory.save_message_first(
            result["id"], "system", compacted.get("session_summary", ""),
            {"kind": "fork_summary", "source_conversation_id": conversation_id},
        )
        result = await memory.get_conversation(result["id"]) or result
    return result


@app.post("/api/conversations/{conversation_id}/duplicate", status_code=201)
async def duplicate_conversation(conversation_id: str) -> dict[str, Any]:
    assert memory is not None
    messages = await memory.get_conversation_messages(conversation_id, limit=100000)
    if not messages:
        raise HTTPException(status_code=404, detail="Conversation has no messages")
    result = await memory.fork_conversation(conversation_id, messages[-1]["id"])
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import fork_session

    await asyncio.to_thread(
        fork_session, DATA_ROOT / "engine", conversation_id, str(result["id"]),
        messages, str(messages[-1]["id"]),
    )
    source = await memory.get_conversation(conversation_id) or {}
    await memory.update_conversation(result["id"], parent_conversation_id=conversation_id,
                                     fork_message_id=messages[-1]["id"],
                                     workspace=source.get("workspace"))
    return await memory.get_conversation(result["id"]) or result


@app.post("/api/conversations/{conversation_id}/compact")
async def compact_conversation(
    conversation_id: str, req: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert memory is not None and orchestrator is not None
    conv = await memory.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await memory.get_conversation_messages(conversation_id, limit=1000)
    before = sum(max(1, len(item["content"]) // 4) for item in messages)
    context = {
        "goal": conv["title"],
        "session_summary": "\n".join(
            f"{item['role']}: {item['content'][:1000]}" for item in messages[-20:]
        ),
    }
    from atlas.config import DATA_ROOT, load_user_settings

    engine = str(load_user_settings().get(
        "agent_engine", get_config().get("agent.engine", "hermes"),
    )).strip().lower()
    if engine == "hermes":
        from atlas.engine import HermesRuntime

        snapshot = await HermesRuntime(
            data_dir=DATA_ROOT, model_manager=orchestrator._model_mgr,
        ).compact_session(
            conversation_id=conversation_id, workspace=conv.get("workspace"),
            focus_topic=str((req or {}).get("focus_topic") or (req or {}).get("note") or "").strip() or None,
        )
        return snapshot
    snapshot = await orchestrator.context_maintenance.compact(context)
    summary = str(snapshot.get("session_summary", ""))
    return {"before_tokens": before, "after_tokens": max(1, len(summary) // 4),
            "summary": summary}


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict[str, str]:
    """Delete a conversation and all its messages."""
    assert memory is not None
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import delete_session

    await asyncio.to_thread(delete_session, DATA_ROOT / "engine", conversation_id)
    ok = await memory.delete_conversation(conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "ok", "conversation_id": conversation_id}


@app.get("/api/projects")
async def list_projects(status: str | None = None) -> dict[str, Any]:
    assert projects is not None
    return {"projects": [p.to_dict() for p in await projects.list_projects(status)]}


@app.post("/api/projects", status_code=201)
async def create_project(req: dict[str, Any]) -> dict[str, Any]:
    assert projects is not None
    try:
        project = await projects.create_project(
            str(req.get("name", "")),
            workspace_path=str(req.get("workspace_path", "") or ""),
            repo_url=str(req.get("repo_url", "") or ""),
            current_goal=str(req.get("current_goal", "") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return project.to_dict()


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    assert projects is not None
    project = await projects.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = project.to_dict()
    result["conversation_ids"] = await projects.list_conversations(project_id)
    return result


@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, req: dict[str, Any]) -> dict[str, Any]:
    assert projects is not None
    try:
        project = await projects.update_project(project_id, **req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.to_dict()


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, str]:
    assert projects is not None
    if not await projects.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "ok", "project_id": project_id}


@app.post("/api/projects/{project_id}/conversations", status_code=201)
async def attach_project_conversation(project_id: str, req: dict[str, Any]) -> dict[str, str]:
    assert projects is not None
    conversation_id = str(req.get("conversation_id", ""))
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")
    try:
        await projects.attach_conversation(project_id, conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "project_id": project_id, "conversation_id": conversation_id}


@app.delete("/api/projects/{project_id}/conversations/{conversation_id}")
async def detach_project_conversation(project_id: str, conversation_id: str) -> dict[str, str]:
    assert projects is not None
    if not await projects.detach_conversation(project_id, conversation_id):
        raise HTTPException(status_code=404, detail="Association not found")
    return {"status": "ok"}


@app.get("/api/projects/{project_id}/recall")
async def project_recall(project_id: str, query: str, limit: int = 8) -> dict[str, Any]:
    """Project-scoped raw session recall: project state + scoped session_search."""
    assert projects is not None and memory is not None
    project = await projects.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    conversation_ids = await projects.list_conversations(project_id)
    results = await memory.session_search(
        query, limit=limit, conversation_ids=conversation_ids,
    )
    return {
        "project": project.to_dict(),
        "conversation_ids": conversation_ids,
        "results": results,
    }


@app.get("/api/projects/{project_id}/sources")
async def get_project_sources(project_id: str) -> dict[str, Any]:
    assert projects is not None
    result = await projects.get_sources(project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="找不到这个项目。")
    return result


@app.put("/api/projects/{project_id}/sources/instructions")
async def put_project_source_instructions(project_id: str, req: dict[str, Any]) -> dict[str, str]:
    assert projects is not None
    instructions = req.get("instructions", "")
    if not isinstance(instructions, str):
        raise HTTPException(status_code=400, detail="项目指令必须是文字。")
    try:
        if not await projects.set_source_instructions(project_id, instructions):
            raise HTTPException(status_code=404, detail="找不到这个项目。")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "project_id": project_id}


async def _extract_project_url(url: str) -> dict[str, Any]:
    return await extract_web(url)


@app.post("/api/web/extract")
async def extract_web_endpoint(req: dict[str, Any]) -> dict[str, Any]:
    url = req.get("url")
    if not isinstance(url, str) or not url.strip():
        raise HTTPException(status_code=400, detail="请提供网页或视频地址。")
    allow_local = req.get("allow_local", False)
    if not isinstance(allow_local, bool):
        raise HTTPException(status_code=400, detail="本机页面选项无效。")
    try:
        return await extract_web(url, allow_local=allow_local)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="暂时无法读取这个网页。") from exc


@app.post("/api/projects/{project_id}/sources", status_code=201)
async def post_project_source(project_id: str, req: dict[str, Any]) -> dict[str, Any]:
    assert projects is not None
    try:
        return await projects.add_source(
            project_id, str(req.get("kind", "")),
            title=str(req.get("title") or ""), path=req.get("path"),
            url=req.get("url"), text=req.get("text"),
            web_extractor=_extract_project_url,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="找不到这个项目。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/projects/{project_id}/sources/{source_id}")
async def delete_project_source(project_id: str, source_id: str) -> dict[str, str]:
    assert projects is not None
    if not await projects.delete_source(project_id, source_id):
        raise HTTPException(status_code=404, detail="找不到这条项目资料。")
    return {"status": "deleted", "source_id": source_id}


@app.post("/api/projects/{project_id}/sources/{source_id}/refresh")
async def refresh_project_source(project_id: str, source_id: str) -> dict[str, Any]:
    assert projects is not None
    try:
        result = await projects.refresh_source(
            project_id, source_id, web_extractor=_extract_project_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="找不到这条项目资料。")
    return result


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@app.get("/api/search")
async def search_messages(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Full-text search across all messages."""
    assert memory is not None
    return await memory.search(q, limit=limit)


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


@app.get("/api/workspace/trust")
async def get_workspace_trust(root: str) -> dict[str, Any]:
    return {"root": root, "trusted": bool(_workspace_trust().get(root))}


@app.delete("/api/workspace/trust")
async def revoke_workspace_trust(root: str) -> dict[str, Any]:
    _set_workspace_trusted(root, False)
    return {"root": root, "trusted": False}


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
    run: "RunState", content: Any, event_id: Any,
) -> str | None:
    if run.status in {"completed", "failed", "cancelled"}:
        return "run_not_active"
    if not isinstance(content, str) or not content.strip():
        return "invalid_content"
    run.steer_queue.put_nowait({"content": content, "event_id": str(event_id or uuid.uuid4())})
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


@app.get("/api/workspace/tree")
async def workspace_tree(root: str, path: str = "") -> dict[str, Any]:
    if root.startswith("ssh://"):
        host, base = ssh_workspaces.parse_workspace(root)
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(status_code=400, detail="path escapes workspace root")
        remote = str(PurePosixPath(base).joinpath(*relative.parts))
        try:
            entries = await ssh_workspaces.list_dir(host, remote)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"root": root, "path": path, "entries": entries}
    base, directory = _workspace_path(root, path)
    if not base.is_dir() or not directory.is_dir():
        raise HTTPException(status_code=404, detail="Workspace directory not found")
    git_status: dict[str, str] = {}
    try:
        result = await asyncio.to_thread(
            subprocess.run, ["git", "-C", str(base), "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if len(line) > 3:
                code = line[:2].strip()
                git_status[line[3:].strip().replace("\\", "/")] = (
                    "?" if code == "??" else "A" if "A" in code else
                    "D" if "D" in code else "M"
                )
    except (OSError, subprocess.SubprocessError):
        pass
    entries = []
    for item in sorted(directory.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.casefold())):
        if item.name in _WORKSPACE_IGNORES:
            continue
        rel = item.relative_to(base).as_posix()
        entries.append({"name": item.name, "path": rel,
                        "type": "dir" if item.is_dir() else "file",
                        "size": None if item.is_dir() else item.stat().st_size,
                        "git": git_status.get(rel)})
    return {"root": str(base), "path": Path(path).as_posix() if path else "",
            "entries": entries}


@app.get("/api/workspace/file")
async def workspace_file(root: str, path: str) -> dict[str, Any]:
    if root.startswith("ssh://"):
        host, base = ssh_workspaces.parse_workspace(root)
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(status_code=400, detail="path escapes workspace root")
        try:
            raw = await ssh_workspaces.read_bytes(host, str(PurePosixPath(base).joinpath(*relative.parts)))
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Workspace file not found") from exc
        sample = raw[:512 * 1024]
        try:
            text = sample.decode("utf-8")
            binary = b"\x00" in sample
        except UnicodeDecodeError:
            text, binary = "", True
        return {"path": path, "content": "" if binary else text,
                "truncated": len(raw) > 512 * 1024, "binary": binary}
    base, target = _workspace_path(root, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Workspace file not found")
    raw = await asyncio.to_thread(target.read_bytes)
    sample = raw[: min(len(raw), 512 * 1024)]
    try:
        text = sample.decode("utf-8")
        binary = b"\x00" in sample
    except UnicodeDecodeError:
        text, binary = "", True
    return {"path": target.relative_to(base).as_posix(),
            "content": "" if binary else text,
            "truncated": len(raw) > 512 * 1024, "binary": binary}


@app.get("/api/workspace/raw")
async def workspace_raw(root: str, path: str) -> StreamingResponse:
    if root.startswith("ssh://"):
        host, base = ssh_workspaces.parse_workspace(root)
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(status_code=400, detail="path escapes workspace root")
        try:
            raw = await ssh_workspaces.read_bytes(host, str(PurePosixPath(base).joinpath(*relative.parts)))
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Workspace file not found") from exc
        if len(raw) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="file exceeds 50 MB limit")
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        headers = {"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"}
        if content_type in _SCRIPTABLE_TYPES:
            headers["Content-Security-Policy"] = "sandbox allow-scripts allow-forms allow-popups allow-modals"
        return StreamingResponse(iter([raw]), media_type=content_type, headers=headers)
    base, target = _workspace_path(root, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Workspace file not found")
    if target.stat().st_size > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file exceeds 50 MB limit")
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    headers = {"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"}
    if content_type in _SCRIPTABLE_TYPES:
        # Workspace files are untrusted. Sandboxing gives the document an opaque origin, so its
        # scripts still run for the preview but cannot read Atlas's API as same-origin.
        headers["Content-Security-Policy"] = (
            "sandbox allow-scripts allow-forms allow-popups allow-modals"
        )
    return StreamingResponse(target.open("rb"), media_type=content_type, headers=headers)


_OFFICE_SANDBOX_HEADERS = {
    "Content-Security-Policy": (
        "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Content-Disposition": "inline",
}


@app.get("/api/workspace/preview")
async def workspace_preview(root: str, path: str) -> Response:
    suffix = Path(path).suffix.casefold()
    if suffix not in {".docx", ".xlsx", ".pptx"}:
        raise HTTPException(status_code=415, detail="Only Office documents can use this preview")
    try:
        if root.startswith("ssh://"):
            host, remote_root = ssh_workspaces.parse_workspace(root)
            relative = Path(path)
            if relative.is_absolute() or ".." in relative.parts:
                raise HTTPException(status_code=400, detail="path escapes workspace root")
            remote_path = ssh_workspaces._remote_path(remote_root, path)
            raw = await ssh_workspaces.read_bytes(host, remote_path)
        else:
            _base, target = _workspace_path(root, path)
            if not target.is_file():
                raise HTTPException(status_code=404, detail="Workspace file not found")
            if target.stat().st_size > MAX_PREVIEW_BYTES:
                raise HTTPException(status_code=413, detail="Office preview is limited to 10 MB")
            raw = await asyncio.to_thread(target.read_bytes)
        rendered = await asyncio.to_thread(render_office, raw, suffix)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Office file could not be read") from exc
    return Response(rendered, media_type="text/html", headers=_OFFICE_SANDBOX_HEADERS)


def _history_checkpoint_manifest(store: Any, checkpoint_id: str) -> tuple[dict[str, Any], Path]:
    # The id comes from the query string and becomes a directory name; checkpoint ids are uuid4 hex.
    if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", checkpoint_id):
        raise HTTPException(status_code=400, detail="invalid workspace version")
    manifest_path = store.storage_dir / checkpoint_id / "manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="Workspace version not found")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")), manifest_path.parent
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Workspace version not found") from exc


async def _git_history(root: Path, relative: str) -> list[dict[str, Any]]:
    try:
        log_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", str(root), "log", "-20", "--format=%H%x09%cI", "--", relative],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if log_result.returncode:
        return []
    versions: list[dict[str, Any]] = []
    for line in log_result.stdout.splitlines():
        commit, _, created_at = line.partition("\t")
        if not commit or not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
            continue
        size = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", str(root), "cat-file", "-s", f"{commit}:{relative}"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        versions.append({
            "id": f"git:{commit}", "run_id": None, "conversation_id": None,
            "created_at": created_at,
            "bytes": int(size.stdout) if size.returncode == 0 and size.stdout.strip().isdigit() else 0,
            "source": "git",
        })
    return versions


@app.get("/api/workspace/history")
async def workspace_history(root: str, path: str) -> dict[str, Any]:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(status_code=400, detail="path escapes workspace root")
    normalized = relative.as_posix()
    versions: list[dict[str, Any]] = []
    if root.startswith("ssh://"):
        checkpoints = await ssh_workspaces.list_checkpoints(root)
        _host, remote_root = ssh_workspaces.parse_workspace(root)
        for item in checkpoints:
            entry = next((file for file in item.get("files", [])
                          if file.get("path") == normalized), None)
            if entry is None:
                continue
            size = 0
            if entry.get("exists"):
                with suppress(Exception):
                    raw = await ssh_workspaces.read_bytes(
                        _host, str(PurePosixPath(remote_root) / ".atlas-checkpoints"
                                   / item["id"] / "files" / normalized),
                    )
                    size = len(raw)
            versions.append({
                "id": f"checkpoint:{item['id']}", "run_id": item.get("run_id"),
                "conversation_id": None, "created_at": item.get("created_at", ""),
                "bytes": size, "source": "checkpoint",
            })
    else:
        base, _ = _workspace_path(root, normalized)
        if orchestrator is not None:
            store = orchestrator.checkpoints
            for item in store.list_checkpoints(str(base)):
                manifest, snapshot = _history_checkpoint_manifest(store, item["id"])
                entry = next((file for file in manifest.get("files", [])
                              if file.get("path") == normalized and not file.get("directory")), None)
                if entry is None:
                    continue
                saved = snapshot / "files" / normalized
                versions.append({
                    "id": f"checkpoint:{item['id']}",
                    "run_id": manifest.get("run_id"),
                    "conversation_id": manifest.get("conversation_id"),
                    "created_at": manifest.get("created_at", ""),
                    "bytes": saved.stat().st_size if entry.get("exists") and saved.is_file() else 0,
                    "source": "checkpoint",
                })
        versions.extend(await _git_history(base, normalized))
    versions.sort(key=lambda item: item["created_at"], reverse=True)
    return {"versions": versions}


async def _history_bytes(root: str, path: str, version: str) -> tuple[bytes, bool]:
    if version.startswith("checkpoint:"):
        checkpoint_id = version.removeprefix("checkpoint:")
        if root.startswith("ssh://"):
            host, remote_root = ssh_workspaces.parse_workspace(root)
            checkpoints = await ssh_workspaces.list_checkpoints(root)
            checkpoint = next((item for item in checkpoints if item["id"] == checkpoint_id), None)
            if checkpoint is None:
                raise HTTPException(status_code=404, detail="Workspace version not found")
            entry = next((file for file in checkpoint.get("files", [])
                          if file.get("path") == path), None)
            if entry is None:
                raise HTTPException(status_code=404, detail="File is absent from this version")
            if not entry.get("exists"):
                return b"", False
            raw_path = str(PurePosixPath(remote_root) / ".atlas-checkpoints"
                           / checkpoint_id / "files" / path)
            return await ssh_workspaces.read_bytes(host, raw_path), True
        base, _ = _workspace_path(root, path)
        if orchestrator is None:
            raise HTTPException(status_code=503, detail="Checkpoint service is unavailable")
        manifest, snapshot = _history_checkpoint_manifest(
            orchestrator.checkpoints, checkpoint_id,
        )
        entry = next((file for file in manifest.get("files", [])
                      if file.get("path") == path and not file.get("directory")), None)
        if entry is None:
            raise HTTPException(status_code=404, detail="File is absent from this version")
        saved = snapshot / "files" / path
        return (saved.read_bytes() if entry.get("exists") and saved.is_file() else b""), bool(entry.get("exists"))
    if version.startswith("git:"):
        if root.startswith("ssh://"):
            raise HTTPException(status_code=404, detail="Git history is unavailable for SSH workspaces")
        commit = version.removeprefix("git:")
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
            raise HTTPException(status_code=400, detail="invalid git version")
        base, _ = _workspace_path(root, path)
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", str(base), "show", f"{commit}:{path}"],
            capture_output=True, timeout=10, check=False,
        )
        if result.returncode:
            return b"", False
        return result.stdout, True
    raise HTTPException(status_code=400, detail="invalid workspace version")


def _content_description(raw: bytes, path: str, exists: bool = True) -> dict[str, Any]:
    try:
        text = raw[:512 * 1024].decode("utf-8")
        binary = b"\x00" in raw[:512 * 1024]
    except UnicodeDecodeError:
        text, binary = "", True
    return {
        "path": path, "content": "" if binary or not exists else text,
        "truncated": len(raw) > 512 * 1024,
        "binary": binary or not exists,
    }


@app.get("/api/workspace/history/content")
async def workspace_history_content(root: str, path: str, version: str) -> dict[str, Any]:
    raw, exists = await _history_bytes(root, path, version)
    return _content_description(raw, path, exists)


@app.get("/api/workspace/history/raw")
async def workspace_history_raw(root: str, path: str, version: str) -> Response:
    raw, _exists = await _history_bytes(root, path, version)
    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return Response(raw, media_type=media_type, headers=_OFFICE_SANDBOX_HEADERS)


@app.post("/api/workspace/history/restore")
async def restore_workspace_history(request: Request) -> dict[str, Any]:
    payload = await request.json()
    root, path, version = (
        str(payload.get("root", "")), str(payload.get("path", "")),
        str(payload.get("version", "")),
    )
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(status_code=400, detail="path escapes workspace root")
    normalized = relative.as_posix()
    raw, exists = await _history_bytes(root, normalized, version)
    checkpoint_id = str(uuid.uuid4())
    if root.startswith("ssh://"):
        await ssh_workspaces.create_checkpoint(root, [normalized], checkpoint_id)
        host, remote_root = ssh_workspaces.parse_workspace(root)
        target = ssh_workspaces._remote_path(remote_root, normalized)
        if exists:
            await ssh_workspaces.write_bytes(host, target, raw)
        else:
            await ssh_workspaces.call_tool("local_file", {
                "action": "delete", "path": normalized,
            }, root, run_id=None)
    else:
        base, target = _workspace_path(root, normalized)
        if orchestrator is None:
            raise HTTPException(status_code=503, detail="Checkpoint service is unavailable")
        checkpoint = orchestrator.checkpoints.create_checkpoint(
            base, [normalized], run_id=checkpoint_id,
        )
        checkpoint_id = checkpoint["id"]
        if exists:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        elif target.is_file():
            target.unlink()
        elif target.is_dir():
            raise HTTPException(status_code=409, detail="Cannot restore a file over a directory")
    return {"restored": True, "checkpoint_id": checkpoint_id}


_SCRIPTABLE_TYPES = {"text/html", "application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml"}


def _is_subsequence(needle: str, haystack: str) -> bool:
    pos = 0
    for char in haystack.casefold():
        if pos < len(needle) and char == needle[pos]:
            pos += 1
    return pos == len(needle)


@app.get("/api/workspace/search")
async def workspace_search(root: str, q: str, limit: int = 50) -> dict[str, Any]:
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    base, _ = _workspace_path(root)
    if not base.is_dir():
        raise HTTPException(status_code=404, detail="Workspace directory not found")
    needle = q.strip().casefold()
    if not needle:
        return {"files": []}
    if root.startswith("ssh://"):
        host, base = ssh_workspaces.parse_workspace(root)
        try:
            command = f"cd {shlex.quote(base)} && rg --files -g {shlex.quote('*' + needle + '*')} | head -n {limit}"
            output = await ssh_workspaces.run(host, command)
            files = [{"path": item, "name": PurePosixPath(item).name, "type": "file"}
                     for item in output.splitlines()]
            return {"files": files}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    try:
        listing = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", str(base), "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=15,
        )
        git_listing_ok = listing.returncode == 0
        paths = listing.stdout.splitlines() if listing.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        git_listing_ok = False
        paths = []
    if not git_listing_ok:
        paths = [p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()]
        patterns = []
        for ignore_file in base.rglob(".gitignore"):
            if any(part in _WORKSPACE_IGNORES for part in ignore_file.relative_to(base).parts[:-1]):
                continue
            try:
                patterns.extend((ignore_file.parent, line.strip()) for line in ignore_file.read_text("utf-8").splitlines()
                                if line.strip() and not line.lstrip().startswith("#"))
            except OSError:
                continue
        filtered = []
        for rel in paths:
            ignored = False
            rel_path = Path(rel)
            for ignore_dir, pattern in patterns:
                negated = pattern.startswith("!")
                value = pattern[1:] if negated else pattern
                target = (ignore_dir / value).relative_to(base).as_posix().lstrip("./")
                candidate = rel_path.as_posix()
                if (candidate == target or candidate.startswith(target.rstrip("/") + "/")
                        or ("/" not in value and fnmatch.fnmatch(rel_path.name, value))):
                    ignored = not negated
            if not ignored:
                filtered.append(rel)
        paths = filtered
    hits = []
    for rel in paths:
        parts = Path(rel).parts
        if any(part in _WORKSPACE_IGNORES for part in parts):
            continue
        name = Path(rel).name
        candidate = name.casefold()
        if needle not in candidate and not _is_subsequence(needle, candidate):
            continue
        score = (0 if candidate.startswith(needle) else 1 if needle in candidate else 2,
                 len(candidate) - len(needle), rel.casefold())
        hits.append((score, {"path": Path(rel).as_posix(), "name": name, "type": "file"}))
    hits.sort(key=lambda row: row[0])
    return {"files": [item for _, item in hits[:limit]]}


@app.get("/api/git/branches")
async def git_branches(root: str) -> dict[str, Any]:
    base, _ = _workspace_path(root)
    if not (base / ".git").exists():
        raise HTTPException(status_code=400, detail="workspace is not a git repository")
    try:
        current = _worktrees()._git(base, "branch", "--show-current")
        branches = _worktrees()._git(base, "branch", "--list", "--format=%(refname:short)").splitlines()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"current": current, "branches": branches}


def _gh_json(root: Path, *args: str) -> dict[str, Any]:
    try:
        auth = subprocess.run(["gh", "auth", "status"], cwd=root, capture_output=True,
                             text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=503, detail="GitHub CLI (gh) is unavailable") from exc
    if auth.returncode:
        raise HTTPException(status_code=503, detail="GitHub CLI is not authenticated")
    result = subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise HTTPException(status_code=502, detail=result.stderr.strip() or "gh command failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="gh returned invalid JSON") from exc


def _pr_shape(data: dict[str, Any]) -> dict[str, Any]:
    checks = []
    for item in data.get("statusCheckRollup", []):
        checks.append({"name": item.get("name", ""),
                       "status": item.get("status", ""),
                       "conclusion": item.get("conclusion"),
                       "url": item.get("detailsUrl", "")})
    return {"number": data.get("number"), "title": data.get("title"),
            "url": data.get("url"), "state": data.get("state"),
            "draft": data.get("isDraft", False), "base": data.get("baseRefName"),
            "head": data.get("headRefName"), "checks": checks}


@app.get("/api/git/pr")
async def get_git_pr(root: str) -> dict[str, Any]:
    base, _ = _workspace_path(root)
    try:
        data = _gh_json(base, "pr", "view", "--json",
                        "number,title,url,state,isDraft,baseRefName,headRefName,statusCheckRollup")
    except HTTPException as exc:
        if exc.status_code == 502 and "no pull requests found" in str(exc.detail).lower():
            return {"pr": None}
        raise
    return {"pr": _pr_shape(data)}


@app.post("/api/git/pr")
async def create_git_pr(req: dict[str, Any]) -> dict[str, Any]:
    base, _ = _workspace_path(str(req.get("root", "")))
    title, body = req.get("title"), req.get("body")
    if not isinstance(title, str) or not title.strip() or not isinstance(body, str):
        raise HTTPException(status_code=422, detail="title and body are required")
    try:
        auth = subprocess.run(["gh", "auth", "status"], cwd=base, capture_output=True,
                             text=True, timeout=15)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="GitHub CLI (gh) is unavailable") from exc
    if auth.returncode:
        raise HTTPException(status_code=503, detail="GitHub CLI is not authenticated")
    pushed = subprocess.run(["git", "push", "-u", "origin", "HEAD"], cwd=base,
                            capture_output=True, text=True, timeout=120)
    if pushed.returncode:
        raise HTTPException(status_code=502, detail=pushed.stderr.strip())
    command = ["gh", "pr", "create", "--title", title, "--body", body]
    if req.get("base"):
        command.extend(["--base", str(req["base"])])
    if req.get("draft") is True:
        command.append("--draft")
    created = subprocess.run(command, cwd=base, capture_output=True, text=True, timeout=60)
    if created.returncode:
        raise HTTPException(status_code=502, detail=created.stderr.strip())
    result = _gh_json(base, "pr", "view", "--json",
                      "number,title,url,state,isDraft,baseRefName,headRefName,statusCheckRollup")
    return {"pr": _pr_shape(result)}


@app.get("/api/git/pr/checks/{check_name}/log")
async def git_pr_check_log(check_name: str, root: str) -> dict[str, Any]:
    base, _ = _workspace_path(root)
    checks = _gh_json(base, "pr", "checks", "--json", "name,state,link")
    match = next((item for item in checks if item.get("name") == check_name), None) \
        if isinstance(checks, list) else None
    if not match or str(match.get("state", "")).upper() not in {"FAILURE", "CANCELLED", "ERROR"}:
        raise HTTPException(status_code=404, detail="failed check not found")
    result = subprocess.run(["gh", "run", "view", str(match["link"]), "--log-failed"],
                            cwd=base, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise HTTPException(status_code=502, detail=result.stderr.strip())
    raw = result.stdout.encode("utf-8")[-65536:].decode("utf-8", errors="replace")
    return {"name": check_name, "log": raw}


@app.get("/api/ssh/hosts")
async def ssh_hosts() -> dict[str, Any]:
    return {"hosts": ssh_workspaces.hosts()}


@app.post("/api/ssh/test")
async def ssh_test(req: dict[str, Any]) -> dict[str, Any]:
    host = str(req.get("host", "")).strip()
    if not host or not any(item["alias"] == host for item in ssh_workspaces.hosts()):
        raise HTTPException(status_code=400, detail="unknown SSH host alias")
    return await ssh_workspaces.test(host)


@app.get("/api/conversations/{conversation_id}/worktree")
async def conversation_worktree(conversation_id: str) -> dict[str, Any]:
    assert memory is not None
    conv = await memory.get_conversation(conversation_id)
    if not conv or not conv.get("worktree_path"):
        raise HTTPException(status_code=404, detail="Conversation worktree not found")
    try:
        return _worktrees().status(Path(conv["workspace"]), Path(conv["worktree_path"]),
                                   conv["worktree_branch"], conv["base_branch"])
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/conversations/{conversation_id}/worktree/merge")
async def merge_conversation_worktree(conversation_id: str, req: dict[str, Any]) -> dict[str, str]:
    assert memory is not None
    conv = await memory.get_conversation(conversation_id)
    if not conv or not conv.get("worktree_path"):
        raise HTTPException(status_code=404, detail="Conversation worktree not found")
    try:
        _worktrees().merge(Path(conv["workspace"]), Path(conv["worktree_path"]),
                           conv["worktree_branch"], conv["base_branch"],
                           str(req.get("strategy", "merge")), req.get("message"))
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail={"conflicts": str(exc).splitlines()}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "merged"}


@app.delete("/api/conversations/{conversation_id}/worktree")
async def delete_conversation_worktree(conversation_id: str, keep_branch: bool = False, force: bool = False) -> dict[str, str]:
    assert memory is not None
    conv = await memory.get_conversation(conversation_id)
    if not conv or not conv.get("worktree_path"):
        raise HTTPException(status_code=404, detail="Conversation worktree not found")
    try:
        _worktrees().remove(Path(conv["workspace"]), Path(conv["worktree_path"]),
                            conv["worktree_branch"], force=force, keep_branch=keep_branch)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await memory.update_conversation(conversation_id, worktree_path="", worktree_branch="", base_branch="")
    return {"status": "removed"}


@app.get("/api/workspace/rules")
async def workspace_rules(root: str) -> dict[str, Any]:
    if root.startswith("ssh://"):
        host, base = ssh_workspaces.parse_workspace(root)
        files = []
        for name in _RULE_FILES:
            path = str(PurePosixPath(base) / name)
            try:
                raw = await ssh_workspaces.read_bytes(host, path)
            except Exception:
                continue
            files.append({"path": path, "bytes": len(raw),
                          "content": raw[:65536].decode("utf-8", errors="replace"),
                          "truncated": len(raw) > 65536})
        return {"root": root, "files": files}
    base, _ = _workspace_path(root)
    candidates = [base / name for name in _RULE_FILES]
    for directory, pattern in (
        (".atlas/agents", "*.md"), (".claude/agents", "*.md"),
        (".opencode/agent", "*.md"), (".opencode/agents", "*.md"),
        (".codex/agents", "*.toml"), (".github/agents", "*.agent.md"),
    ):
        candidates.extend(sorted((base / directory).glob(pattern))[:20])
    candidates = list(dict.fromkeys(candidates))
    user_rules = Path.home() / ".atlas" / "AGENTS.md"
    candidates.append(user_rules)
    files = []
    for item in candidates:
        if not item.is_file():
            continue
        raw = await asyncio.to_thread(item.read_bytes)
        content = raw[:65536].decode("utf-8", errors="replace")
        if item.name == "NOTES.md" and item.parent.name == ".atlas":
            content = _bounded_project_notes(content)
        files.append({"path": str(item.resolve()), "bytes": len(raw),
                      "content": content,
                      "truncated": len(raw) > 65536})
    return {"root": str(base), "files": files}


@app.get("/api/workspace/notes")
async def get_workspace_notes(root: str) -> dict[str, Any]:
    base, _ = _workspace_path(root)
    root_key = str(base.resolve())
    if not _workspace_trust().get(root_key, False):
        raise HTTPException(status_code=403, detail="Workspace is not trusted")
    path = base / ".atlas" / "NOTES.md"
    if not path.is_file():
        return {"root": root_key, "content": ""}
    return {"root": root_key, "content": (await asyncio.to_thread(path.read_text, encoding="utf-8"))[:65536]}


@app.put("/api/workspace/notes")
async def put_workspace_notes(req: dict[str, Any]) -> dict[str, Any]:
    root = str(req.get("root", ""))
    content = req.get("content")
    if not isinstance(content, str) or len(content.encode("utf-8")) > 65536:
        raise HTTPException(status_code=422, detail="content must be a string up to 64 KiB")
    base, _ = _workspace_path(root)
    root_key = str(base.resolve())
    if not _workspace_trust().get(root_key, False):
        raise HTTPException(status_code=403, detail="Workspace is not trusted")
    path = base / ".atlas" / "NOTES.md"
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, content, encoding="utf-8")
    return {"root": root_key, "bytes": len(content.encode("utf-8"))}


@app.get("/api/checkpoints")
async def list_checkpoints(
    run_id: str | None = None, workspace: str | None = None,
) -> list[dict[str, Any]]:
    assert orchestrator is not None
    if workspace and workspace.startswith("ssh://"):
        return await ssh_workspaces.list_checkpoints(workspace, run_id=run_id)
    items = orchestrator.checkpoints.list_checkpoints(workspace, run_id=run_id)
    return [{key: item[key] for key in
             ("id", "workspace", "created_at", "run_id", "files")} for item in items]


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


@app.get("/api/runs/{run_id}/changes")
async def get_run_changes(run_id: str) -> dict[str, Any]:
    run = runtime_mgr.runs.get(run_id)
    if not run:
        return _run_changes(run_id)
    roots = [*([run.workspace] if run.workspace else []), *run.extra_roots]
    combined = []
    for index, root in enumerate(dict.fromkeys(roots)):
        if root.startswith("ssh://"):
            data = await ssh_workspaces.changes(root, run_id)
        else:
            data = _run_changes(run_id, workspace=root)
        for item in data.get("files", []):
            entry = {**item, "root": root}
            if index > 0:
                name = (PurePosixPath(root.split("?", 1)[0]).name
                        if root.startswith("ssh://") else Path(root).name)
                entry["path"] = f"{name or f'目录{index}'}/{item['path']}"
            combined.append(entry)
    return {"run_id": run_id, "files": combined}


@app.get("/api/processes")
async def list_agent_processes() -> list[dict[str, Any]]:
    runtime = local_execution
    if runtime is None:
        return []
    return [{"id": item.execution_id, "command": item.command, "cwd": item.cwd,
             "status": "running" if item.state == "running" else "exited",
             "exit_code": item.exit_code, "started_at": item.started_at,
             "run_id": item.owner_run_id}
            for item in runtime._processes.values()]


@app.get("/api/processes/{process_id}/output")
async def get_agent_process_output(process_id: str, after: int = Query(0, ge=0)) -> dict[str, Any]:
    runtime = local_execution
    record = runtime._processes.get(process_id) if runtime else None
    if record is None:
        raise HTTPException(status_code=404, detail="Process not found")
    stdout_size = record.stdout_path.stat().st_size
    stream_path = record.stdout_path if after < stdout_size else record.stderr_path
    stream_offset = after if after < stdout_size else after - stdout_size
    with stream_path.open("rb") as output_file:
        output_file.seek(stream_offset)
        chunk = output_file.read(65536)
    return {"output": chunk.decode("utf-8", errors="replace"), "next": after + len(chunk),
            "status": "running" if record.state == "running" else "exited"}


@app.post("/api/processes/{process_id}/kill")
async def kill_agent_process(process_id: str) -> dict[str, Any]:
    runtime = local_execution
    record = runtime._processes.get(process_id) if runtime else None
    if record is None:
        raise HTTPException(status_code=404, detail="Process not found")
    await runtime._cancel_process(record)
    return {"id": process_id, "status": "exited", "exit_code": record.exit_code}


@app.websocket("/ws/terminal")
async def ws_terminal(ws: WebSocket, cwd: str = Query(...)) -> None:
    await ws.accept()
    try:
        from winpty import PtyProcess
    except ImportError:
        await ws.send_json({"type": "error", "error": "pywinpty is not installed"})
        await ws.close(code=1011)
        return
    directory = Path(cwd).expanduser().resolve()
    if not directory.is_dir():
        await ws.send_json({"type": "error", "error": "cwd must be an existing directory"})
        await ws.close(code=1008)
        return
    try:
        pty = PtyProcess.spawn(["powershell.exe", "-NoLogo", "-NoProfile"], cwd=str(directory))
    except Exception as exc:
        await ws.send_json({"type": "error", "error": str(exc)})
        await ws.close(code=1011)
        return
    async def read_output() -> None:
        while pty.isalive():
            try:
                chunk = await asyncio.to_thread(pty.read, 4096)
                if chunk:
                    await ws.send_json({"type": "output", "data": chunk})
            except Exception:
                break
        await ws.send_json({"type": "exit", "code": pty.exitstatus})
    reader = asyncio.create_task(read_output())
    try:
        while True:
            item = await ws.receive_json()
            if item.get("type") == "input":
                pty.write(str(item.get("data", "")))
            elif item.get("type") == "resize":
                pty.setwinsize(int(item.get("rows", 24)), int(item.get("cols", 80)))
    except WebSocketDisconnect:
        pass
    finally:
        if pty.isalive():
            pty.terminate(force=True)
        reader.cancel()


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

@app.get("/api/facts")
async def list_facts(
    category: str | None = Query(None),
) -> list[dict[str, Any]]:
    """List all facts, optionally filtered by category."""
    assert memory is not None
    return await memory.list_facts(category=category)


@app.post("/api/facts")
async def create_or_update_fact(req: FactCreateRequest) -> dict[str, str]:
    """Create or update a fact (upsert by key)."""
    assert memory is not None
    await memory.set_fact(req.key, req.value, req.category)
    return {"status": "ok", "key": req.key}


@app.delete("/api/facts/{key}")
async def delete_fact(key: str) -> dict[str, str]:
    """Delete a fact by key."""
    assert memory is not None
    ok = await memory.delete_fact(key)
    if not ok:
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"status": "ok", "key": key}


@app.get("/api/memory/candidates")
async def list_memory_candidates(
    status: str | None = Query(None),
) -> list[dict[str, Any]]:
    """List extracted memory candidates for user review."""
    assert memory is not None
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid candidate status")
    return await memory.list_memory_candidates(status=status)


@app.post("/api/memory/optimization-reports")
async def create_memory_optimization_report() -> dict[str, Any]:
    """Generate and preserve a ranked, advisory memory optimization report."""
    assert memory is not None
    return await memory.create_memory_optimization_report()


@app.get("/api/memory/optimization-reports")
async def list_memory_optimization_reports(
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """Return preserved optimization report snapshots, newest first."""
    assert memory is not None
    return await memory.list_memory_optimization_reports(limit=limit)


@app.post("/api/memory/maturity-reports")
async def create_memory_maturity_report() -> dict[str, Any]:
    """Generate and preserve a deterministic, advisory knowledge maturity report."""
    assert memory is not None
    return await memory.create_knowledge_maturity_report()


@app.get("/api/memory/maturity-reports")
async def list_memory_maturity_reports(
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """Return preserved maturity report snapshots, newest first."""
    assert memory is not None
    return await memory.list_knowledge_maturity_reports(limit=limit)


@app.post("/api/memory/knowledge-health-reports")
async def create_knowledge_health_report() -> dict[str, Any]:
    assert memory is not None
    return await memory.create_knowledge_health_report()


@app.get("/api/memory/knowledge-health-reports")
async def list_knowledge_health_reports(
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    assert memory is not None
    return await memory.list_knowledge_health_reports(limit=limit)


@app.post("/api/memory/knowledge-health-reports/{report_id}/approve")
async def approve_knowledge_health_report(report_id: str) -> dict[str, str]:
    assert memory is not None
    if not await memory.review_knowledge_health_report(report_id, approved=True):
        raise HTTPException(status_code=404, detail="Pending knowledge health report not found")
    return {"status": "approved", "id": report_id}


@app.post("/api/memory/knowledge-health-reports/{report_id}/reject")
async def reject_knowledge_health_report(report_id: str) -> dict[str, str]:
    assert memory is not None
    if not await memory.review_knowledge_health_report(report_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending knowledge health report not found")
    return {"status": "rejected", "id": report_id}


@app.post("/api/memory/consolidated-insights")
async def create_knowledge_consolidated_insights() -> list[dict[str, Any]]:
    assert memory is not None
    return await memory.create_knowledge_consolidated_insights()


@app.get("/api/memory/consolidated-insights")
async def list_knowledge_consolidated_insights(
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    assert memory is not None
    return await memory.list_knowledge_consolidated_insights(limit=limit)


@app.get("/api/memory/insight-applications")
async def list_knowledge_insight_applications(
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    assert memory is not None
    return await memory.list_knowledge_insight_applications(limit=limit)


@app.post("/api/memory/self-steering-reports")
async def create_memory_self_steering_report() -> dict[str, Any]:
    """Create auditable suggestions from maturity and approved outcome signals."""
    assert memory is not None
    return await memory.create_knowledge_self_steering_report()


@app.get("/api/memory/self-steering-reports")
async def list_memory_self_steering_reports(
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """Return preserved self-steering snapshots, newest first."""
    assert memory is not None
    return await memory.list_knowledge_self_steering_reports(limit=limit)


@app.post("/api/memory/self-steering-reports/{report_id}/approve")
async def approve_memory_self_steering_report(report_id: str) -> dict[str, str]:
    assert memory is not None
    if not await memory.review_knowledge_self_steering_report(report_id, approved=True):
        raise HTTPException(status_code=404, detail="Pending self-steering report not found")
    return {"status": "approved", "id": report_id}


@app.post("/api/memory/self-steering-reports/{report_id}/reject")
async def reject_memory_self_steering_report(report_id: str) -> dict[str, str]:
    assert memory is not None
    if not await memory.review_knowledge_self_steering_report(report_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending self-steering report not found")
    return {"status": "rejected", "id": report_id}


@app.post("/api/memory/optimization-candidates")
async def create_memory_optimization_candidates() -> list[dict[str, Any]]:
    assert memory is not None
    return await memory.create_knowledge_optimization_candidates()


@app.get("/api/memory/optimization-candidates")
async def list_memory_optimization_candidates(
    status: str | None = Query(None), limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    assert memory is not None
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid optimization candidate status")
    return await memory.list_knowledge_optimization_candidates(status=status, limit=limit)


@app.post("/api/memory/optimization-candidates/{candidate_id}/approve")
async def approve_memory_optimization_candidate(candidate_id: str) -> dict[str, str]:
    assert memory is not None
    if not await memory.review_knowledge_optimization_candidate(candidate_id, approved=True):
        raise HTTPException(
            status_code=404, detail="Eligible pending optimization candidate not found"
        )
    return {"status": "approved", "id": candidate_id}


@app.post("/api/memory/optimization-candidates/{candidate_id}/reject")
async def reject_memory_optimization_candidate(candidate_id: str) -> dict[str, str]:
    assert memory is not None
    if not await memory.review_knowledge_optimization_candidate(candidate_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending optimization candidate not found")
    return {"status": "rejected", "id": candidate_id}


@app.post("/api/memory/consolidation-proposals")
async def create_memory_consolidation_proposals() -> list[dict[str, Any]]:
    assert memory is not None
    return await memory.create_knowledge_consolidation_proposals()


@app.get("/api/memory/consolidation-proposals")
async def list_memory_consolidation_proposals(
    status: str | None = Query(None), limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    assert memory is not None
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid consolidation proposal status")
    return await memory.list_knowledge_consolidation_proposals(status=status, limit=limit)


@app.post("/api/memory/consolidation-proposals/{proposal_id}/approve")
async def approve_memory_consolidation_proposal(proposal_id: str) -> dict[str, str]:
    assert memory is not None
    if not await memory.review_knowledge_consolidation_proposal(proposal_id, approved=True):
        raise HTTPException(status_code=404, detail="Pending consolidation proposal not found")
    return {"status": "approved", "id": proposal_id}


@app.post("/api/memory/consolidation-proposals/{proposal_id}/reject")
async def reject_memory_consolidation_proposal(proposal_id: str) -> dict[str, str]:
    assert memory is not None
    if not await memory.review_knowledge_consolidation_proposal(proposal_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending consolidation proposal not found")
    return {"status": "rejected", "id": proposal_id}


@app.post("/api/memory/consolidation-proposals/{proposal_id}/activate")
async def activate_memory_consolidation_proposal(proposal_id: str) -> dict[str, Any]:
    assert memory is not None
    activation = await memory.activate_knowledge_consolidation_proposal(proposal_id)
    if activation is None:
        raise HTTPException(status_code=404, detail="Approved consolidation proposal not found")
    return activation


@app.get("/api/memory/knowledge-activations")
async def list_memory_knowledge_activations(
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    assert memory is not None
    return await memory.list_knowledge_activations(limit=limit)


@app.post("/api/memory/knowledge-activations/{activation_id}/verify")
async def verify_memory_knowledge_activation_usage(
    activation_id: str,
    candidate_id: str = Body(...),
    evidence_refs: list[str] = Body(...),
    usage_id: str | None = Body(None),
) -> dict[str, Any]:
    """Verify a claimed advisory use against its activated evidence provenance."""
    assert memory is not None
    verification = await memory.verify_knowledge_activation_usage(
        activation_id,
        candidate_id=candidate_id,
        evidence_refs=evidence_refs,
        usage_id=usage_id,
    )
    if verification is None:
        raise HTTPException(status_code=404, detail="Knowledge activation not found")
    return verification


@app.get("/api/memory/knowledge-verifications")
async def list_memory_knowledge_verifications(
    activation_id: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """Query immutable advisory knowledge verification snapshots."""
    assert memory is not None
    return await memory.list_knowledge_verifications(activation_id=activation_id, limit=limit)


@app.get("/api/memory/goal-outcomes")
async def list_goal_outcomes(
    status: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """List durable goal results and pending experience-review candidates."""
    assert memory is not None
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid goal experience status")
    return await memory.list_goal_outcomes(experience_status=status, limit=limit)


@app.post("/api/memory/goal-outcomes/{outcome_id}/approve")
async def approve_goal_experience(outcome_id: str) -> dict[str, str]:
    """Approve one pending goal outcome for future advisory context."""
    assert memory is not None
    if not await memory.review_goal_experience(outcome_id, approved=True):
        raise HTTPException(status_code=404, detail="Pending goal outcome not found")
    return {"status": "approved", "id": outcome_id}


@app.post("/api/memory/goal-outcomes/{outcome_id}/reject")
async def reject_goal_experience(outcome_id: str) -> dict[str, str]:
    """Reject one pending goal outcome."""
    assert memory is not None
    if not await memory.review_goal_experience(outcome_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending goal outcome not found")
    return {"status": "rejected", "id": outcome_id}


@app.get("/api/memory/goal-knowledge/feedback")
async def list_goal_knowledge_feedback(
    knowledge_id: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """List helpful or failed usage outcomes with source provenance."""
    assert memory is not None
    return await memory.list_goal_knowledge_feedback(knowledge_id, limit)


@app.post("/api/memory/goal-knowledge/evolution/evaluate")
async def evaluate_goal_knowledge_evolution(
    knowledge_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Analyze approved advisory usage and persist review-only recommendations."""
    assert memory is not None
    return await memory.evaluate_goal_knowledge_evolution(knowledge_id)


@app.get("/api/memory/goal-knowledge/evolution/evaluations")
async def list_goal_knowledge_evolution_evaluations(
    knowledge_id: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    assert memory is not None
    return await memory.list_goal_knowledge_evolution_evaluations(knowledge_id, limit)


@app.get("/api/memory/goal-knowledge/evolution/recommendations")
async def list_goal_knowledge_evolution_recommendations(
    knowledge_id: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    assert memory is not None
    return await memory.list_goal_knowledge_evolution_recommendations(
        knowledge_id, limit,
    )


@app.get("/api/memory/goal-knowledge/proposals")
async def list_goal_knowledge_proposals(
    status: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """List improvement proposals separately from active advisory knowledge."""
    assert memory is not None
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid goal knowledge proposal status")
    return await memory.list_goal_knowledge_proposals(status=status, limit=limit)


@app.post("/api/memory/goal-knowledge/proposals/{proposal_id}/approve")
async def approve_goal_knowledge_proposal(proposal_id: str) -> dict[str, str]:
    """Promote a pending advisory improvement after explicit approval."""
    assert memory is not None
    if not await memory.review_goal_knowledge_proposal(proposal_id, approved=True):
        raise HTTPException(status_code=404, detail="Pending goal knowledge proposal not found")
    return {"status": "approved", "id": proposal_id}


@app.post("/api/memory/goal-knowledge/proposals/{proposal_id}/reject")
async def reject_goal_knowledge_proposal(proposal_id: str) -> dict[str, str]:
    """Reject a pending advisory improvement without changing active knowledge."""
    assert memory is not None
    if not await memory.review_goal_knowledge_proposal(proposal_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending goal knowledge proposal not found")
    return {"status": "rejected", "id": proposal_id}


@app.post("/api/memory/goal-knowledge/refinements/evaluate")
async def evaluate_goal_knowledge_refinements(
    knowledge_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Evaluate approved improvement candidates using the deterministic refinement gate."""
    assert memory is not None
    return await memory.evaluate_goal_knowledge_refinements(knowledge_id)


@app.get("/api/memory/goal-knowledge/refinements")
async def list_goal_knowledge_refinements(
    status: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """List refinement candidates separately from advisory knowledge."""
    assert memory is not None
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid goal knowledge refinement status")
    return await memory.list_goal_knowledge_refinements(status=status, limit=limit)


@app.get("/api/memory/goal-knowledge/refinement-evaluations")
async def list_goal_knowledge_refinement_evaluations(
    knowledge_id: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """List deterministic refinement decisions and their supporting candidates."""
    assert memory is not None
    return await memory.list_goal_knowledge_refinement_evaluations(
        knowledge_id=knowledge_id, limit=limit,
    )


@app.get("/api/memory/goal-knowledge/governance/evaluate")
async def evaluate_goal_knowledge_governance(
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Evaluate pending advisory reviews against deterministic provenance gates."""
    assert memory is not None
    try:
        return await memory.evaluate_goal_knowledge_governance(entity_type, entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/memory/goal-knowledge/governance/history")
async def list_goal_knowledge_governance_history(
    knowledge_id: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """List append-only review decisions and their provenance."""
    assert memory is not None
    return await memory.list_goal_knowledge_governance_history(knowledge_id, limit)


@app.post("/api/memory/goal-knowledge/refinements/{refinement_id}/approve")
async def approve_goal_knowledge_refinement(refinement_id: str) -> dict[str, str]:
    """Apply a reviewed refinement to advisory knowledge."""
    assert memory is not None
    if not await memory.review_goal_knowledge_refinement(refinement_id, approved=True):
        raise HTTPException(status_code=404, detail="Pending goal knowledge refinement not found")
    return {"status": "approved", "id": refinement_id}


@app.post("/api/memory/goal-knowledge/refinements/{refinement_id}/reject")
async def reject_goal_knowledge_refinement(refinement_id: str) -> dict[str, str]:
    """Reject a candidate without changing advisory or active knowledge."""
    assert memory is not None
    if not await memory.review_goal_knowledge_refinement(refinement_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending goal knowledge refinement not found")
    return {"status": "rejected", "id": refinement_id}


@app.post("/api/memory/candidates/{candidate_id}/approve")
async def approve_memory_candidate(candidate_id: str) -> dict[str, str]:
    """Promote a pending candidate after explicit user approval."""
    assert memory is not None
    if not await memory.promote_memory_candidate(candidate_id):
        raise HTTPException(
            status_code=404, detail="Pending memory candidate not found"
        )
    return {"status": "approved", "id": candidate_id}


@app.post("/api/memory/candidates/{candidate_id}/reject")
async def reject_memory_candidate(candidate_id: str) -> dict[str, str]:
    """Reject a pending memory candidate."""
    assert memory is not None
    if not await memory.reject_memory_candidate(candidate_id):
        raise HTTPException(
            status_code=404, detail="Pending memory candidate not found"
        )
    return {"status": "rejected", "id": candidate_id}


# ---------------------------------------------------------------------------
# Tools (MCP)
# ---------------------------------------------------------------------------

@app.get("/api/tools")
async def list_tools() -> dict[str, Any]:
    """Return all available MCP tools across connected servers."""
    assert mcp_client is not None
    tools = mcp_client.list_tools()
    return {
        "servers": mcp_client.get_server_names(),
        "tool_count": mcp_client.tool_count,
        "tools": [
            {
                "name": t.qualified_name,
                "description": t.description,
                "server": t.server_name,
                "input_schema": t.input_schema,
            }
            for t in tools
        ],
    }


@app.get("/api/custom-tools")
async def list_custom_tools() -> dict[str, Any]:
    assert custom_tools is not None
    return {"tools": custom_tools.list_tools()}


@app.post("/api/custom-tools", status_code=201)
async def create_custom_tool(req: dict[str, Any]) -> dict[str, Any]:
    assert custom_tools is not None
    try:
        return custom_tools.create(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/custom-tools/{tool_id}")
async def update_custom_tool(tool_id: str, req: dict[str, Any]) -> dict[str, Any]:
    assert custom_tools is not None
    try:
        result = custom_tools.update(tool_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="找不到这个自定义工具。")
    return result


@app.delete("/api/custom-tools/{tool_id}")
async def delete_custom_tool(tool_id: str) -> dict[str, str]:
    assert custom_tools is not None
    try:
        deleted = custom_tools.delete(tool_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="找不到这个自定义工具。")
    return {"status": "deleted", "id": tool_id}


@app.post("/api/custom-tools/{tool_id}/test")
async def test_custom_tool(tool_id: str, req: dict[str, Any]) -> dict[str, Any]:
    assert custom_tools is not None
    try:
        return await custom_tools.execute(
            tool_id, req.get("arguments", req), allow_disabled=True,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="找不到这个自定义工具。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/integrations")
async def list_integrations(refresh: bool = Query(False)) -> dict[str, Any]:
    """Return the shared upstream capability registry."""
    if capability_bus is None:
        return {"count": 0, "ready": 0, "degraded": 0, "capabilities": []}
    result = await asyncio.to_thread(capability_bus.status, refresh)
    runtime = mcp_client.get_runtime_status() if mcp_client else {"servers": []}
    server_states = {item["name"]: item for item in runtime.get("servers", [])}
    server_ids = {"playwright": "mcp.playwright", "chrome-devtools": "mcp.chrome_devtools"}
    for record in result["capabilities"]:
        server_name = next(
            (name for name, item_id in server_ids.items() if item_id == record["id"]), None,
        )
        if server_name and server_name in server_states:
            server = server_states[server_name]
            record["connected"] = bool(server.get("connected"))
            if not server.get("connected") and server.get("blocking_reason"):
                record["last_error"] = server["blocking_reason"]
        if record["id"].startswith("agent.") and agent_backend_host:
            backend_name = record["id"].split(".", 1)[1]
            record["connected"] = backend_name in agent_backend_host.connected_names()
            record["smoke_verified"] = backend_name in agent_backend_host.smoke_verified
            record["status"] = (
                "ready" if record["smoke_verified"] else
                "misconfigured"
                if record["authenticated"] is False or record["configured"] is False
                else "degraded"
            )
        if record["id"] == "browser.browser_use" and browser_use:
            record["connected"] = bool(browser_use._sessions)
            record["authenticated"] = browser_use.authenticated
            record["smoke_verified"] = browser_use.smoke_verified
            if browser_use.last_error:
                record["last_error"] = browser_use.last_error
            record["status"] = (
                "misconfigured" if browser_use.authenticated is False else
                "ready" if browser_use.smoke_verified else "degraded"
            )
    return result


@app.get("/api/notifications/status")
async def notification_status() -> dict[str, Any]:
    assert notifications is not None
    return notifications.status()


@app.get("/api/channels/telegram")
async def get_telegram_channel() -> dict[str, Any]:
    if telegram_service is None:
        raise HTTPException(status_code=503, detail="Telegram 通道尚未就绪。")
    return telegram_service.settings()


@app.put("/api/channels/telegram")
async def put_telegram_channel(req: dict[str, Any]) -> dict[str, Any]:
    if telegram_service is None:
        raise HTTPException(status_code=503, detail="Telegram 通道尚未就绪。")
    workspace = req.get("default_workspace")
    if workspace:
        try:
            if workspace.startswith("ssh://"):
                ssh_workspaces.parse_workspace(workspace)
            elif not Path(workspace).is_absolute():
                raise ValueError("工作目录必须是绝对路径或 SSH 地址。")
        except (AttributeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return telegram_service.update_settings(req)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/channels/telegram/test")
async def test_telegram_channel() -> dict[str, str]:
    if telegram_service is None:
        raise HTTPException(status_code=503, detail="Telegram 通道尚未就绪。")
    try:
        return await telegram_service.test_token()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/hub/status")
async def hub_status() -> dict[str, Any]:
    """Report the background Hub's running state and scheduler summary."""
    return await hub_control.status()


@app.post("/api/hub/start")
async def hub_start() -> dict[str, Any]:
    """Start the detached background Hub (no-op when already running)."""
    return await hub_control.start()


@app.post("/api/hub/stop")
async def hub_stop() -> dict[str, Any]:
    """Gracefully stop the background Hub."""
    return await hub_control.stop()


@app.get("/api/hub/tasks")
async def hub_tasks(response: Response) -> dict[str, Any]:
    response.headers["Deprecation"] = "true"
    assert scheduler is not None
    return {"tasks": [task.to_dict() for task in scheduler.list_tasks()]}


@app.post("/api/hub/tasks")
async def hub_create_task(req: dict[str, Any], response: Response) -> dict[str, Any]:
    response.headers["Deprecation"] = "true"
    assert scheduler is not None
    message = str(req.get("message", "")).strip()
    if not message or not str(req.get("id", "")).strip():
        raise HTTPException(status_code=400, detail="id and message are required")
    try:
        task = ScheduledTask.from_dict({
            "id": str(req["id"]), "name": str(req.get("name", req["id"])),
            "description": str(req.get("description", "")),
            "trigger_type": str(req.get("trigger_type", "interval")),
            "trigger_args": dict(req.get("trigger_args", {}) or {}),
            "action": f"agent:{message}", "goal": str(req.get("goal", "")),
        })
        return (await scheduler.add_task(task)).to_dict()
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/hub/tasks/{task_id}/run")
async def hub_run_task(task_id: str, response: Response) -> dict[str, Any]:
    response.headers["Deprecation"] = "true"
    assert scheduler is not None
    if not await scheduler.run_now(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "triggered", "task_id": task_id}


@app.delete("/api/hub/tasks/{task_id}")
async def hub_delete_task(task_id: str, response: Response) -> dict[str, Any]:
    response.headers["Deprecation"] = "true"
    assert scheduler is not None
    if not await scheduler.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok", "task_id": task_id}


@app.post("/api/notifications/test")
async def notification_test() -> dict[str, Any]:
    """Send a test notification to every configured target."""
    assert notifications is not None
    return await notifications.notify(
        "Atlas notification test", "If you can read this, notifications work.",
    )


@app.get("/api/notifications/urls")
async def get_notification_urls() -> dict[str, Any]:
    assert notifications is not None
    return {"urls": notifications.urls}


@app.put("/api/notifications/urls")
async def set_notification_urls(req: dict[str, Any]) -> dict[str, Any]:
    """Persist notification target URLs (Apprise) and apply them immediately."""
    assert notifications is not None
    urls = req.get("urls")
    if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
        raise HTTPException(status_code=400, detail="urls must be a list of strings")
    notifications.set_urls([u.strip() for u in urls if u.strip()])
    path = get_config().db_path.parent / "notification-urls.json"
    path.write_text(json.dumps({"urls": notifications.urls}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return {"urls": notifications.urls}


@app.get("/api/plugins")
async def list_plugins() -> dict[str, Any]:
    """List discovered local plugin bundles with their runtime state."""
    if plugin_runtime is None:
        return {"plugins": []}
    return {"plugins": plugin_runtime.discover()}


@app.post("/api/plugins/install-local")
async def install_local_plugin(req: dict[str, Any]) -> dict[str, Any]:
    """Install a plugin from a local directory into the user plugin folder."""
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="Plugin runtime unavailable")
    source = str(req.get("path", ""))
    if not source:
        raise HTTPException(status_code=400, detail="path is required")
    try:
        result = plugin_runtime.install_local(source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.post("/api/plugins/{name}/enabled")
async def set_plugin_enabled(name: str, req: dict[str, Any]) -> dict[str, Any]:
    """Enable or disable a plugin and reapply every plugin to the runtime."""
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="Plugin runtime unavailable")
    plugin_runtime.set_enabled(name, bool(req.get("enabled", True)))
    report = await plugin_runtime.load_all(
        hook_bus=orchestrator.hooks if orchestrator else None,
        mcp_client=mcp_client,
        capabilities=orchestrator.capabilities if orchestrator else None,
    )
    return {"name": name, "enabled": bool(req.get("enabled", True)), "report": report}


@app.patch("/api/integrations/{capability_id}/enabled")
async def set_integration_enabled(
    capability_id: str, req: IntegrationToggleRequest,
) -> dict[str, Any]:
    """Enable or disable an optional integration for this runtime."""
    if capability_bus is None or not await asyncio.to_thread(
        capability_bus.set_enabled, capability_id, req.enabled,
    ):
        raise HTTPException(status_code=404, detail=f"Integration not found: {capability_id}")
    server_names = {"mcp.playwright": "playwright", "mcp.chrome_devtools": "chrome-devtools"}
    server_name = server_names.get(capability_id)
    if server_name and mcp_client:
        configured = mcp_client.get_server_config(server_name)
        if configured is not None:
            if req.enabled:
                await mcp_client.restart_server(server_name)
            else:
                await mcp_client.disconnect_server(server_name)
    return next(
        item for item in (await list_integrations())["capabilities"]
        if item["id"] == capability_id
    )


# ---------------------------------------------------------------------------
# MCP Server Management
# ---------------------------------------------------------------------------

class MCPServerAddRequest(BaseModel):
    name: str
    transport: str = "stdio"  # "stdio" | "sse"
    command: str = ""
    args: list[str] = []
    env: dict[str, str] = {}
    cwd: str | None = None
    url: str = ""  # for SSE transport


@app.get("/api/mcp/servers")
async def list_mcp_servers() -> dict[str, Any]:
    """Return all connected MCP servers and their tools."""
    assert mcp_client is not None
    servers = []
    for name in mcp_client.get_server_names():
        tools = mcp_client.get_server_tools(name)
        servers.append({
            "name": name,
            "tool_count": len(tools),
            "tools": [t.qualified_name for t in tools],
        })
    return {"servers": servers}


@app.get("/api/runtime/dependency-check")
async def check_runtime_dependencies() -> dict[str, Any]:
    """Read the current bundled runtime, MCP lifecycle, and canonical Skill dependencies."""
    node_status = get_node_runtime_status()
    runtime_status = mcp_client.get_runtime_status() if mcp_client else {
        "available": False, "blocking_reason": "MCP runtime is unavailable", "servers": [],
    }
    server_states = runtime_status.get("servers", [])
    connected = {item["name"] for item in server_states if item.get("connected")}
    configured = {item["name"] for item in server_states if item.get("configured")}
    skills = []
    if skill_registry is not None:
        for record in skill_registry.list(status="active"):
            dependencies = dependency_preflight(
                record.get("requirements", []), connected_servers=connected,
                configured_servers=configured, registry=skill_registry,
            )
            blocking = [item for item in dependencies if item["state"] != "satisfied"]
            skills.append({
                "name": record["name"], "version": record["version"],
                "dependencies": dependencies, "blocking": blocking,
                "can_use": not blocking,
            })

    blockers = []
    if (not node_status["bundled"]["available"]
            or not node_status["bundled"]["npm_npx_available"]):
        blockers.append({
            "scope": "runtime", "reason": node_status["blocking_reason"]
            or node_status["bundled"]["blocking_reason"]
            or "Atlas bundled Node/npm/npx is unavailable",
        })
    if not runtime_status.get("available", False):
        blockers.append({
            "scope": "mcp_runtime",
            "reason": runtime_status.get("blocking_reason") or "MCP runtime is unavailable",
        })
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "node": node_status,
        "mcp_runtime": runtime_status,
        "mcp_servers": server_states,
        "skills": skills,
        "blocking": blockers,
    }


@app.post("/api/runtime/shutdown", status_code=202)
async def request_runtime_shutdown(request: Request) -> dict[str, str]:
    """Gracefully stop an Electron-managed packaged backend with its launch token."""
    expected = os.environ.get("ATLAS_SHUTDOWN_TOKEN", "")
    supplied = request.headers.get("x-atlas-backend-shutdown-token", "")
    callback = getattr(app.state, "desktop_shutdown_callback", None)
    if not expected or not secrets.compare_digest(supplied, expected) or not callable(callback):
        raise HTTPException(status_code=403, detail="Backend shutdown is not authorized")
    asyncio.get_running_loop().call_soon(callback)
    return {"status": "shutting_down"}


@app.post("/api/mcp/servers")
async def add_mcp_server(req: MCPServerAddRequest) -> dict[str, Any]:
    """Dynamically add and connect a new MCP server."""
    assert mcp_client is not None
    from atlas.tools.mcp_client import MCPServerConfig

    if req.name in mcp_client.get_server_names():
        raise HTTPException(status_code=409, detail=f"Server already exists: {req.name}")

    cfg = MCPServerConfig(
        name=req.name,
        transport=req.transport,
        command=req.command,
        args=req.args,
        env=req.env,
        cwd=req.cwd,
        url=req.url,
        enabled=True,
    )

    try:
        await mcp_client._connect_server(cfg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect: {e}")

    tools = mcp_client.get_server_tools(req.name)
    return {
        "name": req.name,
        "tool_count": len(tools),
        "tools": [t.qualified_name for t in tools],
    }


@app.delete("/api/mcp/servers/{server_name}")
async def remove_mcp_server(server_name: str) -> dict[str, str]:
    """Disconnect and remove an MCP server."""
    assert mcp_client is not None

    if server_name not in mcp_client.get_server_names():
        raise HTTPException(status_code=404, detail=f"Server not found: {server_name}")

    await mcp_client.disconnect_server(server_name)
    return {"status": "ok", "server": server_name}


@app.post("/api/mcp/servers/{server_name}/restart")
async def restart_mcp_server(server_name: str) -> dict[str, Any]:
    """Restart an MCP server (disconnect + reconnect)."""
    assert mcp_client is not None

    if server_name not in mcp_client.get_server_names():
        raise HTTPException(status_code=404, detail=f"Server not found: {server_name}")

    try:
        await mcp_client.restart_server(server_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Restart failed: {e}")

    tools = mcp_client.get_server_tools(server_name)
    return {
        "name": server_name,
        "tool_count": len(tools),
        "tools": [t.qualified_name for t in tools],
    }


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

class KnowledgeAddRequest(BaseModel):
    content: str
    source: str = ""
    category: str = "general"
    metadata: dict[str, Any] = {}


@app.get("/api/knowledge")
async def list_knowledge(
    category: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """List knowledge base entries."""
    assert memory is not None
    return await memory.list_knowledge(category=category, limit=limit)


@app.post("/api/knowledge")
async def add_knowledge(req: KnowledgeAddRequest) -> dict[str, Any]:
    """Add a knowledge entry."""
    assert memory is not None
    entry_id = await memory.add_knowledge(
        content=req.content,
        source=req.source,
        category=req.category,
        metadata=req.metadata,
    )
    return {"id": entry_id, "content": req.content, "source": req.source}


@app.get("/api/knowledge/search")
async def search_knowledge(
    q: str = Query(..., min_length=1),
    category: str | None = Query(None),
    limit: int = Query(10, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Search the knowledge base."""
    assert memory is not None
    return await memory.search_knowledge(query=q, category=category, limit=limit)


@app.delete("/api/knowledge/{entry_id}")
async def delete_knowledge(entry_id: str) -> dict[str, str]:
    """Delete a knowledge entry."""
    assert memory is not None
    ok = await memory.delete_knowledge(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Knowledge entry not found: {entry_id}")
    return {"status": "ok", "id": entry_id}


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

@app.get("/api/agent/capabilities")
async def list_agent_capabilities() -> dict[str, Any]:
    """Return the capabilities registered for the agent."""
    assert orchestrator is not None
    capabilities = orchestrator.discover_capabilities()
    return {"count": len(capabilities), "capabilities": capabilities}


@app.post("/api/agent/capabilities/{name}/invoke")
async def invoke_agent_capability(
    name: str,
    inputs: dict[str, Any] | None = Body(default=None),
) -> dict[str, Any]:
    """Invoke a registered capability through the agent capability registry."""
    assert orchestrator is not None
    try:
        result = await orchestrator.invoke_capability(name, inputs or {})
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Capability not found: {name}") from None
    return {"name": name, "result": result}


@app.get("/api/agent/backends")
async def list_agent_backends() -> dict[str, Any]:
    """List external Agent adapters without starting their processes."""
    return {"backends": agent_backend_host.names() if agent_backend_host else []}


@app.get("/api/agents/external")
async def list_external_agents() -> dict[str, Any]:
    return external_agent_status(external_agent_status_cache)


@app.get("/api/agents/types")
async def list_agent_types(root: str | None = Query(default=None)) -> dict[str, Any]:
    """List built-in and imported sub-agent definitions for a workspace."""
    from atlas.agent.definitions import list_agent_types as load_types

    workspace = Path(root).expanduser().resolve() if root else None
    trusted = bool(workspace and _workspace_trust().get(str(workspace), False))
    types = load_types(get_config().db_path.parent, workspace, trusted)
    return {"types": types[:20]}


@app.post("/api/agent/backends/{name}/sessions")
async def start_agent_backend_session(
    name: str, req: AgentSessionStartRequest,
) -> dict[str, Any]:
    if agent_backend_host is None:
        raise HTTPException(status_code=503, detail="Agent backend host is unavailable")
    try:
        session = await agent_backend_host.start(name, req.cwd)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent backend not found: {name}") from None
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"Agent backend failed to start: {type(exc).__name__}",
        ) from None
    return {"backend": name, "session_id": session.id, "cwd": session.cwd}


@app.post("/api/agent/backends/{name}/sessions/{session_id}/resume")
async def resume_agent_backend_session(
    name: str, session_id: str, req: AgentSessionStartRequest,
) -> dict[str, Any]:
    if agent_backend_host is None:
        raise HTTPException(status_code=503, detail="Agent backend host is unavailable")
    try:
        session = await agent_backend_host.resume(name, session_id, req.cwd)
    except (KeyError, NotImplementedError):
        raise HTTPException(
            status_code=404, detail="Agent backend session cannot be resumed",
        ) from None
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"Agent backend resume failed: {type(exc).__name__}",
        ) from None
    return {"backend": name, "session_id": session.id, "cwd": session.cwd}


@app.post("/api/agent/sessions/{session_id}/prompt")
async def prompt_agent_backend(
    session_id: str, req: AgentPromptRequest,
) -> StreamingResponse:
    if agent_backend_host is None:
        raise HTTPException(status_code=503, detail="Agent backend host is unavailable")
    try:
        await agent_backend_host.send(session_id, req.prompt)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent session not found") from None

    async def stream_events() -> AsyncIterator[str]:
        assert agent_backend_host is not None
        async for event in agent_backend_host.events(session_id):
            payload = {"type": event.type, **event.data}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream_events(), media_type="text/event-stream")


@app.post("/api/agent/sessions/{session_id}/cancel")
async def cancel_agent_backend_session(session_id: str) -> dict[str, str]:
    if agent_backend_host is None:
        raise HTTPException(status_code=503, detail="Agent backend host is unavailable")
    try:
        await agent_backend_host.cancel(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent session not found") from None
    return {"status": "cancelled", "session_id": session_id}


@app.delete("/api/agent/sessions/{session_id}")
async def close_agent_backend_session(session_id: str) -> dict[str, str]:
    if agent_backend_host is None:
        raise HTTPException(status_code=503, detail="Agent backend host is unavailable")
    try:
        await agent_backend_host.close(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent session not found") from None
    return {"status": "closed", "session_id": session_id}

@app.get("/api/skills")
async def list_skills(
    category: str | None = Query(None),
) -> dict[str, Any]:
    """Return all available skills, optionally filtered by category."""
    assert skill_mgr is not None
    skills = skill_mgr.list_skills(category=category)
    return {
        "count": len(skills),
        "categories": skill_mgr.categories,
        "skills": [s.to_dict() for s in skills],
    }


@app.get("/api/skills/{name}/dependencies")
async def inspect_skill_dependencies(name: str) -> dict[str, Any]:
    """Return a read-only dependency preflight for one indexed Skill."""
    assert skill_mgr is not None
    info = skill_mgr.get_skill(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    dependencies = skill_mgr.preflight_dependencies(
        name,
        connected_servers=mcp_client.get_server_names() if mcp_client else None,
        configured_servers=mcp_client.get_configured_server_names() if mcp_client else None,
        registry=skill_registry,
    )
    blockers = [item for item in dependencies if item["state"] != "satisfied"]
    return {"name": name, "dependencies": dependencies, "blocking": blockers,
            "can_activate": not blockers, "read_only": True}


@app.post("/api/skills/{name}/dependencies/prepare")
async def prepare_skill_dependencies(
    name: str, request: Request, payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Create a dependency plan; execution remains behind lifecycle approval."""
    _require_skill_center_authority(request)
    if skill_mgr is None:
        raise HTTPException(status_code=503, detail="Skill Manager is unavailable")
    info = skill_mgr.get_skill(name)
    if info is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    record = skill_registry.get(name, info.version) if skill_registry else None
    if record is None or not (record.get("provenance") or {}).get("installed_path"):
        raise HTTPException(
            status_code=409, detail="dependency installation requires a managed Skill",
        )
    _, _, lifecycle_state = _lifecycle_context(name, info.version)
    lifecycle = lifecycle_state["lifecycle"]
    if (lifecycle["drifted"] or lifecycle.get("trust_state") in {"revoked", "blocked"}
            or lifecycle.get("state") in {"removed", "quarantined"}
            or lifecycle.get("pin_policy") != "unpinned"):
        raise HTTPException(
            status_code=409, detail="Skill lifecycle policy blocks dependency preparation",
        )
    states = skill_mgr.preflight_dependencies(
        name, connected_servers=mcp_client.get_server_names() if mcp_client else None,
        configured_servers=mcp_client.get_configured_server_names() if mcp_client else None,
        registry=skill_registry,
    )
    selected = payload.get("dependencies")
    if selected is not None and (not isinstance(selected, list)
                                 or any(not isinstance(value, str) for value in selected)):
        raise HTTPException(status_code=422, detail="dependencies must be a list of names")
    targets = [item for item in states if item["state"] != "satisfied"
               and (selected is None or item["name"] in selected)]
    if selected is not None and set(selected) != {item["name"] for item in targets}:
        raise HTTPException(
            status_code=409, detail="selected dependency is absent or already satisfied",
        )
    plan_items = []
    for item in targets:
        supported = item["kind"] == "python_packages" and bool(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", item["name"])
        )
        if item["kind"] == "python_packages" and item.get("requested"):
            try:
                SpecifierSet(item["requested"])
            except InvalidSpecifier:
                supported = False
        plan_items.append({
            **item, "adapter": "pip" if supported else None,
            "source": "https://pypi.org/simple" if supported else item["source"],
            "executable": supported,
            "blocked_reason": None if supported else (
                "no approved adapter for this dependency kind or declaration"
            ),
        })
    if not plan_items:
        raise HTTPException(status_code=409, detail="no missing dependencies were selected")
    plan_id = str(uuid.uuid4())
    plan = {
        "plan_id": plan_id, "name": name, "version": info.version,
        "items": plan_items, "created_at": datetime.now(UTC),
        "expires_at": datetime.now(UTC) + SKILL_ACQUISITION_TTL,
        "approval_state": "pending",
    }
    skill_dependency_plans[plan_id] = plan
    return {**plan, "approval_state": "approval_required", "read_only": True}


@app.get("/api/skills/discover")
async def discover_skills(
    q: str = Query(""),
    name: str | None = Query(None),
    capability: str | None = Query(None),
    tool: str | None = Query(None),
    status: str = Query("active"),
    source: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Return explainable, ranked candidates from the local Skill Registry."""
    assert skill_registry is not None
    try:
        return SkillDiscovery(skill_registry).discover(
            query=q, name=name, capability=capability, tool=tool, status=status,
            source=source, limit=limit, offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/api/skill-catalog/search")
async def search_skill_catalog(
    q: str = Query(..., min_length=2), page: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Search remote candidates; failures are isolated from local discovery and chat."""
    try:
        result = await skill_catalog_provider.search(q, page=page)
        registry_items = skill_registry.list() if skill_registry else []
        installed = {
            (item.get("provenance") or {}).get("external_id") for item in registry_items
        }
        for item in result["results"]:
            if item["external_id"] in installed:
                item["installed"] = True
                item["state"] = "installed"
        return result
    except CatalogUnavailableError as exc:
        return {
            "provider": "skills.sh", "results": [],
            "pagination": {"page": page, "has_more": False},
            "status": "external-catalog-unavailable", "message": str(exc),
        }


@app.post("/api/skill-catalog/inspect")
async def inspect_skill_catalog(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Fetch and review a remote candidate without registry or activation side effects."""
    try:
        if payload.get("provider") == "github":
            acquisition = await inspect_github_source(
                str(payload.get("source_url", "")), str(payload.get("skill_path", "")),
            )
        else:
            acquisition = await skill_catalog_provider.inspect(str(payload.get("external_id", "")))
    except CatalogUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="GitHub source unavailable") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    acquisition_id = str(uuid.uuid4())
    created_at = datetime.now(UTC)
    expires_at = created_at + SKILL_ACQUISITION_TTL
    skill_acquisitions[acquisition_id] = {
        "acquisition_id": acquisition_id,
        "provider": acquisition.record["provider"],
        "external_id": acquisition.record["external_id"],
        "computed_sha256": acquisition.computed_hash,
        "name": acquisition.record["name"],
        "version": acquisition.record["version"],
        "security": acquisition.security,
        "created_at": created_at,
        "expires_at": expires_at,
        "approval_state": "pending",
        "acquisition": acquisition,
    }
    existing = None
    if skill_registry:
        candidates = [item for item in skill_registry.list()
                      if item.get("name") == acquisition.record["name"]]
        exact = skill_registry.get(acquisition.record["name"], acquisition.record["version"])
        existing = exact or next((item for item in candidates if
                                  (item.get("provenance") or {}).get("external_id") ==
                                  acquisition.record.get("external_id")), None)
        if existing and (existing.get("provenance") or {}).get("installed_path"):
            try:
                current_state = inspect_skill_lifecycle(
                    skill_registry, skill_mgr._skills_dir if skill_mgr else SKILLS_DIR,
                    existing["name"], existing["version"],
                )
                existing = {
                    **existing, "lifecycle_summary": current_state["lifecycle"],
                    "file_hashes": current_state["file_hashes"],
                }
            except (OSError, ValueError):
                pass
    prior_hashes = (existing or {}).get("file_hashes", {})
    incoming_hashes = {
        path: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for path, content in acquisition.files.items()
    }
    file_diff = {
        "added": sorted(set(incoming_hashes) - set(prior_hashes)),
        "removed": sorted(set(prior_hashes) - set(incoming_hashes)),
        "changed": sorted(path for path in set(incoming_hashes) & set(prior_hashes)
                           if incoming_hashes[path] != prior_hashes[path]),
        "unchanged": sorted(path for path in set(incoming_hashes) & set(prior_hashes)
                             if incoming_hashes[path] == prior_hashes[path]),
    }
    return {
        "acquisition_id": acquisition_id, "record": acquisition.record,
        "files": acquisition.files, "validation": acquisition.validation,
        "security": acquisition.security, "computed_sha256": acquisition.computed_hash,
        "dependency_state": dependency_states(
            skill_registry, acquisition.validation.get("dependencies", []),
        ) if skill_registry else [],
        "file_diff": file_diff,
        "already_installed": bool(skill_registry and skill_registry.get(
            acquisition.record["name"], acquisition.record["version"]
        )),
        "existing_local": existing,
        "install_target": f"skills/community/{acquisition.record['name']}",
    }


@app.post("/api/skill-packages/inspect")
async def inspect_local_skill_package(request: Request) -> dict[str, Any]:
    """Review a bounded ZIP package in memory; this route never extracts or installs it."""
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > 2_128_000):
        raise HTTPException(status_code=413, detail="package exceeds the upload size limit")
    try:
        acquisition = inspect_skill_package(
            await request.body(), request.headers.get("x-atlas-package-name", "skill-package.zip"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    acquisition_id = str(uuid.uuid4())
    created_at = datetime.now(UTC)
    skill_acquisitions[acquisition_id] = {
        "acquisition_id": acquisition_id, "provider": acquisition.record["provider"],
        "external_id": acquisition.record["external_id"],
        "computed_sha256": acquisition.computed_hash,
        "name": acquisition.record["name"], "version": acquisition.record["version"],
        "security": acquisition.security, "created_at": created_at,
        "expires_at": created_at + SKILL_ACQUISITION_TTL,
        "approval_state": "pending", "acquisition": acquisition, "local_package": True,
    }
    exact = skill_registry.get(acquisition.record["name"], acquisition.record["version"])
    same_name = any(item["name"] == acquisition.record["name"] for item in skill_registry.list())
    existing = next((item for item in skill_registry.list(status="active")
                     if item["name"] == acquisition.record["name"]), None)
    states = dependency_preflight(
        acquisition.validation.get("dependencies", []),
        connected_servers=set(mcp_client.get_server_names()) if mcp_client else None,
        configured_servers=(set(mcp_client.get_configured_server_names()) if mcp_client else None),
        registry=skill_registry,
    )
    return {
        "acquisition_id": acquisition_id, "record": acquisition.record,
        "files": acquisition.files, "validation": acquisition.validation,
        "security": acquisition.security, "computed_sha256": acquisition.computed_hash,
        "dependency_state": states, "already_installed": exact is not None,
        "name_conflict": exact is not None,
        "exact_version_conflict": exact is not None,
        "same_name_existing": same_name,
        "import_state": ("exact_version_conflict" if exact is not None else
                         "update_candidate" if existing is not None else "new_skill"),
        "existing_version": existing["version"] if existing is not None else None,
        "install_target": f"skills/community/{acquisition.record['name']}",
        "import_requires_lifecycle_approval": True,
    }


@app.post("/api/skill-catalog/approve")
async def approve_catalog_skill(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    acquisition_id = payload.get("acquisition_id")
    session = skill_acquisitions.get(acquisition_id) if isinstance(acquisition_id, str) else None
    if session is None:
        raise HTTPException(status_code=404, detail="Reviewed acquisition not found; inspect again")
    if datetime.now(UTC) >= session["expires_at"]:
        session["approval_state"] = "expired"
        raise HTTPException(status_code=410, detail="Reviewed acquisition expired; inspect again")
    acquisition = session["acquisition"]
    if acquisition.computed_hash != session["computed_sha256"]:
        raise HTTPException(status_code=409, detail="Reviewed payload changed; inspect again")
    if session["approval_state"] != "pending":
        raise HTTPException(status_code=409, detail="Acquisition approval is no longer pending")
    if acquisition.security["result"] == "BLOCK":
        raise HTTPException(status_code=403, detail="Blocked skill cannot be approved")
    if acquisition.security["result"] == "WARN" and payload.get("warnings_confirmed") is not True:
        raise HTTPException(
            status_code=403, detail="WARN risks require explicit second confirmation",
        )
    approved_at = datetime.now(UTC).isoformat()
    event = {
        "approval_event_id": str(uuid.uuid4()),
        "acquisition_id": acquisition_id,
        "computed_sha256": session["computed_sha256"],
        "approved_at": approved_at,
        "approval_state": "approved",
    }
    authorization = secrets.token_urlsafe(32)
    session["approval_event"] = event
    session["authorization_sha256"] = hashlib.sha256(authorization.encode("utf-8")).hexdigest()
    session["approval_state"] = "approved"
    session["approval_expires_at"] = datetime.now(UTC) + SKILL_ACQUISITION_TTL
    return {**event, "install_authorization": authorization}


@app.post("/api/skill-catalog/install")
async def install_catalog_skill(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    acquisition_id = payload.get("acquisition_id")
    session = skill_acquisitions.get(acquisition_id) if isinstance(acquisition_id, str) else None
    if session is None:
        raise HTTPException(status_code=404, detail="Reviewed acquisition not found; inspect again")
    acquisition = session["acquisition"]
    if "approval_event_id" in payload or "approved" in payload:
        raise HTTPException(
            status_code=403, detail="Client-supplied approval claims are not accepted",
        )
    if datetime.now(UTC) >= session["expires_at"]:
        session["approval_state"] = "expired"
        raise HTTPException(status_code=410, detail="Reviewed acquisition expired; inspect again")
    if acquisition.computed_hash != session["computed_sha256"]:
        raise HTTPException(status_code=409, detail="Reviewed payload changed; inspect again")
    authorization = payload.get("install_authorization")
    approval_event = session.get("approval_event")
    if (
        session["approval_state"] != "approved"
        or not isinstance(authorization, str)
        or not isinstance(approval_event, dict)
        or datetime.now(UTC) >= session.get("approval_expires_at", datetime.min.replace(tzinfo=UTC))
        or not secrets.compare_digest(
            hashlib.sha256(authorization.encode("utf-8")).hexdigest(),
            session.get("authorization_sha256", ""),
        )
    ):
        raise HTTPException(status_code=403, detail="Valid one-time server approval is required")
    if (
        approval_event["acquisition_id"] != acquisition_id
        or approval_event["computed_sha256"] != acquisition.computed_hash
    ):
        raise HTTPException(
            status_code=403, detail="Approval does not match the reviewed acquisition",
        )
    session["approval_state"] = "consumed"
    session.pop("authorization_sha256", None)
    assert skill_registry is not None
    try:
        result = await install_acquisition(
            acquisition, skills_dir=skill_mgr._skills_dir if skill_mgr else SKILLS_DIR,
            registry=skill_registry, approval_event=approval_event,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if skill_mgr:
        skill_mgr.scan_skills_sync()
    del skill_acquisitions[acquisition_id]
    return result


def _lifecycle_context(name: str, version: str) -> tuple[SkillRegistry, Path, dict[str, Any]]:
    if skill_registry is None:
        raise HTTPException(status_code=503, detail="Skill Registry is unavailable")
    record = skill_registry.get(name, version)
    if record is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not (record.get("provenance") or {}).get("installed_path"):
        raise HTTPException(
            status_code=404, detail="Skill is outside the external lifecycle manager",
        )
    skills_dir = skill_mgr._skills_dir if skill_mgr else SKILLS_DIR
    try:
        state = inspect_skill_lifecycle(skill_registry, skills_dir, name, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return skill_registry, skills_dir, state


@app.get("/api/skills/lifecycle/{name}/{version}")
async def get_skill_lifecycle(name: str, version: str) -> dict[str, Any]:
    _, _, state = _lifecycle_context(name, version)
    return state


@app.get("/api/skills/lifecycle/{name}/{version}/history")
async def get_skill_lifecycle_history(name: str, version: str) -> dict[str, Any]:
    registry, _, state = _lifecycle_context(name, version)
    return {"name": name, "version": version, "history": registry.lifecycle_history(name),
            "lifecycle": state["lifecycle"]}


@app.post("/api/skills/lifecycle/decision")
async def create_skill_lifecycle_decision(
    request: Request, payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    _require_skill_center_authority(request)
    action, name, version = (payload.get(key) for key in ("action", "name", "version"))
    reason = payload.get("reason")
    if action not in {"install", "update", "downgrade", "dependency-install", "rollback",
                      "remove", "trust", "pin", "unpin"}:
        raise HTTPException(status_code=422, detail="unsupported lifecycle action")
    if not all(isinstance(value, str) and value.strip() for value in (name, version, reason)):
        raise HTTPException(status_code=422, detail="name, version, and reason are required")
    acquisition_id = None
    if action == "install":
        acquisition_id = payload.get("acquisition_id")
        session = (skill_acquisitions.get(acquisition_id)
                   if isinstance(acquisition_id, str) else None)
        if (not session or not session.get("local_package")
                or datetime.now(UTC) >= session["expires_at"]):
            raise HTTPException(
                status_code=410, detail="reviewed local package is missing or expired",
            )
        acquisition = session["acquisition"]
        if acquisition.record["name"] != name or acquisition.record["version"] != version:
            raise HTTPException(status_code=403, detail="package review targets another Skill")
        if acquisition.security.get("result") == "BLOCK":
            raise HTTPException(status_code=403, detail="blocked package cannot be approved")
        if (acquisition.security.get("result") == "WARN"
                and payload.get("warnings_confirmed") is not True):
            raise HTTPException(
                status_code=403, detail="WARN package requires a second confirmation",
            )
        registry = skill_registry
        if registry is None:
            raise HTTPException(status_code=503, detail="Skill Registry is unavailable")
        if registry.get(name, version) is not None:
            raise HTTPException(
                status_code=409,
                detail="Skill package with this exact name and version already exists",
            )
        if session.get("computed_sha256") != acquisition.computed_hash:
            raise HTTPException(status_code=409, detail="reviewed package hash changed")
        skills_dir = skill_mgr._skills_dir if skill_mgr else SKILLS_DIR
        current_hash = ""
        content_hash = acquisition.computed_hash
    else:
        registry, skills_dir, state = _lifecycle_context(name, version)
        current_hash = (state["lifecycle"].get("actual_hash")
                        or state["lifecycle"].get("content_hash"))
        content_hash = current_hash
    rollback_event = None
    if action == "dependency-install":
        acquisition_id = payload.get("dependency_plan_id")
        plan = (skill_dependency_plans.get(acquisition_id)
                if isinstance(acquisition_id, str) else None)
        if (not plan or plan["name"] != name or plan["version"] != version
                or datetime.now(UTC) >= plan["expires_at"]):
            raise HTTPException(status_code=410, detail="dependency plan is missing or expired")
        state = _lifecycle_context(name, version)[2]
        if state["lifecycle"]["drifted"]:
            raise HTTPException(
                status_code=409, detail="filesystem drift blocks dependency installation",
            )
        current_hash = (state["lifecycle"].get("actual_hash")
                        or state["lifecycle"].get("content_hash"))
        content_hash = current_hash
    elif action == "rollback":
        requested_event = payload.get("event_id")
        rollback_event = next((item for item in registry.lifecycle_history(name)
                              if item["event_id"] == requested_event), None)
        if (rollback_event is None or rollback_event["action"] != "remove"
                or state["lifecycle"].get("actual_hash") is not None):
            if state["lifecycle"]["drifted"]:
                raise HTTPException(status_code=409, detail="filesystem drift blocks rollback")
        if rollback_event is None:
            raise HTTPException(status_code=404, detail="rollback record not found")
    elif action != "install" and state["lifecycle"]["drifted"]:
        raise HTTPException(status_code=409, detail="filesystem drift blocks lifecycle actions")
    if rollback_event is not None:
        content_hash = rollback_event["details"].get("snapshot_hash")
    if action in {"update", "downgrade"}:
        acquisition_id = payload.get("acquisition_id")
        session = (
            skill_acquisitions.get(acquisition_id)
            if isinstance(acquisition_id, str) else None
        )
        if not session or datetime.now(UTC) >= session["expires_at"]:
            raise HTTPException(status_code=410, detail="reviewed update is missing or expired")
        acquisition = session["acquisition"]
        if acquisition.record["name"] != name:
            raise HTTPException(status_code=403, detail="update review targets another skill")
        if acquisition.record["version"] == version:
            raise HTTPException(status_code=409, detail="exact name and version already exists")
        current_version = tuple(int(part.split("-")[0]) for part in version.split(".")[:3])
        incoming_version = tuple(
            int(part.split("-")[0]) for part in acquisition.record["version"].split(".")[:3]
        )
        expected_action = "downgrade" if incoming_version < current_version else "update"
        if action != expected_action:
            raise HTTPException(status_code=409, detail=f"review action must be {expected_action}")
        if acquisition.security.get("result") == "BLOCK":
            raise HTTPException(status_code=403, detail="blocked update cannot be approved")
        if (acquisition.security.get("result") == "WARN"
                and payload.get("warnings_confirmed") is not True):
            raise HTTPException(
                status_code=403, detail="WARN update requires a second confirmation",
            )
        content_hash = acquisition.computed_hash
        acquisition_id = session.get("acquisition_id", acquisition_id)
    if not isinstance(content_hash, str):
        raise HTTPException(status_code=409, detail="installed content hash is unavailable")
    now = datetime.now(UTC)
    decision_id = str(uuid.uuid4())
    target_trust_state = payload.get("trust_state") if action == "trust" else None
    target_pin_policy = payload.get("policy") if action in {"pin", "unpin"} else None
    if action == "trust" and target_trust_state not in {"trusted", "revoked", "blocked"}:
        raise HTTPException(status_code=422, detail="valid target trust state is required")
    if action in {"pin", "unpin"} and target_pin_policy not in {"exact", "hash", "unpinned"}:
        raise HTTPException(status_code=422, detail="valid target pin policy is required")
    try:
        registry.create_lifecycle_decision({
            "decision_id": decision_id,
            "action": action, "name": name, "version": version,
            "current_hash": current_hash or "", "content_hash": content_hash,
            "acquisition_id": acquisition_id, "target_trust_state": target_trust_state,
            "target_pin_policy": target_pin_policy,
            "rollback_event_id": rollback_event["event_id"] if rollback_event else None,
            "rollback_snapshot_hash": content_hash if rollback_event else None,
            "reason": reason.strip(),
            "created_at": now.isoformat(),
            "expires_at": (now + SKILL_ACQUISITION_TTL).isoformat(),
        })
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"decision_id": decision_id, "action": action, "name": name,
            "version": version, "content_hash": content_hash,
            "expires_at": (now + SKILL_ACQUISITION_TTL).isoformat()}


@app.post("/api/skills/lifecycle/approve")
async def approve_skill_lifecycle(
    request: Request, payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    _require_skill_center_authority(request)
    decision_id = payload.get("decision_id")
    if not isinstance(decision_id, str) or not decision_id:
        raise HTTPException(status_code=403, detail="server-held Skill Center decision is required")
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    approval_id = str(uuid.uuid4())
    assert skill_registry is not None
    approval_scope = skill_registry.issue_lifecycle_approval_from_decision(
        decision_id=decision_id, approval_event_id=approval_id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        created_at=now.isoformat(), expires_at=(now + SKILL_ACQUISITION_TTL).isoformat(),
    )
    if approval_scope is None:
        raise HTTPException(
            status_code=403, detail="valid unconsumed Skill Center decision is required",
        )
    return {"approval_event_id": approval_id, "approval_token": token, **approval_scope,
            "expires_at": (now + SKILL_ACQUISITION_TTL).isoformat()}


def _consume_lifecycle_approval(
    registry: SkillRegistry, payload: dict[str, Any], *, action: str, name: str,
    version: str, current_hash: str, content_hash: str,
    target_trust_state: str | None = None, target_pin_policy: str | None = None,
    rollback_event_id: str | None = None, rollback_snapshot_hash: str | None = None,
) -> dict[str, str]:
    token = payload.get("approval_token")
    if not isinstance(token, str):
        raise HTTPException(status_code=403, detail="server-issued lifecycle approval is required")
    approval = registry.consume_lifecycle_approval(
        token=token, action=action, name=name, version=version, content_hash=content_hash,
        current_hash=current_hash,
        acquisition_id=(payload.get("dependency_plan_id") if action == "dependency-install"
                        else payload.get("acquisition_id")
                        if action in {"install", "update", "downgrade"} else None),
        target_trust_state=target_trust_state, target_pin_policy=target_pin_policy,
        rollback_event_id=rollback_event_id,
        rollback_snapshot_hash=rollback_snapshot_hash,
    )
    if approval is None:
        raise HTTPException(
            status_code=403, detail="approval is invalid, expired, mismatched, or replayed",
        )
    return approval


@app.post("/api/skills/lifecycle/update")
async def update_skill_lifecycle(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    acquisition_id, version = payload.get("acquisition_id"), payload.get("version")
    session = skill_acquisitions.get(acquisition_id) if isinstance(acquisition_id, str) else None
    if not session or datetime.now(UTC) >= session["expires_at"]:
        raise HTTPException(status_code=410, detail="reviewed update is missing or expired")
    acquisition = session["acquisition"]
    name = acquisition.record["name"]
    if acquisition.record["version"] == version:
        raise HTTPException(status_code=409, detail="exact name and version already exists")
    registry, skills_dir, state = _lifecycle_context(name, str(version or ""))
    if state["lifecycle"]["drifted"]:
        raise HTTPException(status_code=409, detail="filesystem drift blocks update")
    current_tuple = tuple(int(part.split("-")[0]) for part in str(version).split(".")[:3])
    incoming_tuple = tuple(
        int(part.split("-")[0]) for part in acquisition.record["version"].split(".")[:3]
    )
    action = "downgrade" if incoming_tuple < current_tuple else "update"
    approval = _consume_lifecycle_approval(
        registry, payload, action=action, name=name, version=str(version),
        current_hash=str(state["lifecycle"].get("actual_hash")
                         or state["lifecycle"].get("content_hash") or ""),
        content_hash=acquisition.computed_hash,
    )
    try:
        result = await update_lifecycle_skill(
            acquisition, registry=registry, skills_dir=skills_dir, current_version=str(version),
            approval_event_id=approval["approval_event_id"], reason=approval["reason"],
        )
    except (ValueError, PermissionError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    if skill_mgr:
        skill_mgr.scan_skills_sync()
    skill_acquisitions.pop(acquisition_id, None)
    return result


@app.post("/api/skills/lifecycle/install")
async def install_local_skill_package(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    acquisition_id = payload.get("acquisition_id")
    session = skill_acquisitions.get(acquisition_id) if isinstance(acquisition_id, str) else None
    if (not session or not session.get("local_package")
            or datetime.now(UTC) >= session["expires_at"]):
        raise HTTPException(status_code=410, detail="reviewed local package is missing or expired")
    acquisition = session["acquisition"]
    if session.get("computed_sha256") != acquisition.computed_hash:
        raise HTTPException(status_code=409, detail="reviewed package hash changed")
    if acquisition.security.get("result") == "BLOCK":
        raise HTTPException(status_code=403, detail="blocked package cannot be installed")
    if (acquisition.security.get("result") == "WARN"
            and payload.get("warnings_confirmed") is not True):
        raise HTTPException(status_code=403, detail="WARN package requires a second confirmation")
    if "approval_event_id" in payload or "approved" in payload:
        raise HTTPException(
            status_code=403, detail="client-supplied approval claims are not accepted",
        )
    registry = skill_registry
    if registry is None:
        raise HTTPException(status_code=503, detail="Skill Registry is unavailable")
    name, version = acquisition.record["name"], acquisition.record["version"]
    if registry.get(name, version) is not None:
        raise HTTPException(
            status_code=409,
            detail="Skill package with this exact name and version already exists",
        )
    approval = _consume_lifecycle_approval(
        registry, payload, action="install", name=name, version=version,
        current_hash="", content_hash=acquisition.computed_hash,
    )
    try:
        result = await install_acquisition(
            acquisition, skills_dir=skill_mgr._skills_dir if skill_mgr else SKILLS_DIR,
            registry=registry,
            approval_event={
                "approval_event_id": approval["approval_event_id"],
                "approved_at": datetime.now(UTC).isoformat(),
                "computed_sha256": acquisition.computed_hash,
            },
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (PermissionError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if skill_mgr:
        skill_mgr.scan_skills_sync()
    skill_acquisitions.pop(acquisition_id, None)
    return {**result, "package_import": {"status": "installed", "lifecycle_approval": True}}


@app.post("/api/skills/dependencies/install")
async def install_prepared_dependencies(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    plan_id = payload.get("dependency_plan_id")
    plan = skill_dependency_plans.get(plan_id) if isinstance(plan_id, str) else None
    if not plan or datetime.now(UTC) >= plan["expires_at"]:
        raise HTTPException(status_code=410, detail="dependency plan is missing or expired")
    registry = skill_registry
    if registry is None:
        raise HTTPException(status_code=503, detail="Skill Registry is unavailable")
    current = _lifecycle_context(plan["name"], plan["version"])[2]
    current_lifecycle = current["lifecycle"]
    if (current_lifecycle["drifted"]
            or current_lifecycle.get("trust_state") in {"revoked", "blocked"}
            or current_lifecycle.get("state") in {"removed", "quarantined"}
            or current_lifecycle.get("pin_policy") != "unpinned"):
        raise HTTPException(
            status_code=409, detail="filesystem drift blocks dependency installation",
        )
    current_hash = str(current["lifecycle"].get("actual_hash")
                        or current["lifecycle"].get("content_hash") or "")
    approval = _consume_lifecycle_approval(
        registry, {**payload, "dependency_plan_id": plan_id},
        action="dependency-install", name=plan["name"], version=plan["version"],
        current_hash=current_hash, content_hash=current_hash,
    )
    plan["approval_state"] = "consumed"
    results: list[dict[str, Any]] = []
    for item in plan["items"]:
        if not item["executable"]:
            results.append({"name": item["name"], "kind": item["kind"],
                            "status": "unsupported", "reason": item["blocked_reason"]})
            continue
        requirement = item["name"] + (item.get("requested") or "")
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                 "--index-url", "https://pypi.org/simple", requirement],
                check=False, capture_output=True, text=True, timeout=180,
            )
            status = "installed" if completed.returncode == 0 else "failed"
            output = (completed.stderr or completed.stdout or "").splitlines()[-4:]
            results.append({"name": item["name"], "kind": item["kind"],
                            "status": status, "return_code": completed.returncode,
                            "output": output})
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append({"name": item["name"], "kind": item["kind"],
                            "status": "failed", "error": type(exc).__name__})
    return {
        "name": plan["name"], "version": plan["version"],
        "approval_event_id": approval["approval_event_id"],
        "status": "completed" if all(item["status"] == "installed" for item in results)
        else "partial_or_failed", "results": results,
    }


@app.post("/api/skills/lifecycle/remove")
async def remove_skill_lifecycle(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    name, version = str(payload.get("name", "")), str(payload.get("version", ""))
    registry, skills_dir, state = _lifecycle_context(name, version)
    actual_hash = state["lifecycle"].get("actual_hash")
    approval = _consume_lifecycle_approval(
        registry, payload, action="remove", name=name, version=version,
        current_hash=str(actual_hash or state["lifecycle"].get("content_hash") or ""),
        content_hash=str(actual_hash or ""),
    )
    try:
        result = remove_lifecycle_skill(
            registry, skills_dir, name, version,
            approval_event_id=approval["approval_event_id"], reason=approval["reason"],
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if skill_mgr:
        skill_mgr.scan_skills_sync()
    return result


@app.post("/api/skills/lifecycle/rollback")
async def rollback_skill_lifecycle(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    name, version, event_id = (str(payload.get(key, "")) for key in ("name", "version", "event_id"))
    registry, skills_dir, state = _lifecycle_context(name, version)
    rollback_event = next((item for item in registry.lifecycle_history(name)
                           if item["event_id"] == event_id), None)
    if rollback_event is None:
        raise HTTPException(status_code=404, detail="rollback record not found")
    rollback_hash = rollback_event["details"].get("snapshot_hash")
    approval = _consume_lifecycle_approval(
        registry, payload, action="rollback", name=name, version=version,
        current_hash=str(state["lifecycle"].get("actual_hash")
                         or state["lifecycle"].get("content_hash") or ""),
        content_hash=str(rollback_hash or ""), rollback_event_id=event_id,
        rollback_snapshot_hash=str(rollback_hash or ""),
    )
    try:
        result = rollback_lifecycle_skill(
            registry, skills_dir, name, version, event_id=event_id,
            approval_event_id=approval["approval_event_id"], reason=approval["reason"],
            expected_current_hash=str(state["lifecycle"].get("actual_hash")
                                      or state["lifecycle"].get("content_hash") or ""),
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if skill_mgr:
        skill_mgr.scan_skills_sync()
    return result


@app.post("/api/skills/lifecycle/trust")
async def trust_skill_lifecycle(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    name, version, target = (
        str(payload.get(key, "")) for key in ("name", "version", "trust_state")
    )
    registry, _, state = _lifecycle_context(name, version)
    action = "trust"
    approval = _consume_lifecycle_approval(
        registry, payload, action=action, name=name, version=version,
        current_hash=str(state["lifecycle"].get("actual_hash")
                         or state["lifecycle"].get("content_hash") or ""),
        content_hash=str(state["lifecycle"].get("actual_hash") or ""),
        target_trust_state=target,
    )
    try:
        return transition_trust(
            registry, name, version, target, reason=approval["reason"],
            approval_event_id=approval["approval_event_id"],
            content_hash=state["lifecycle"].get("actual_hash"),
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/skills/lifecycle/pin")
async def pin_skill_lifecycle(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    name, version, policy = (str(payload.get(key, "")) for key in ("name", "version", "policy"))
    registry, skills_dir, state = _lifecycle_context(name, version)
    action = "unpin" if policy == "unpinned" else "pin"
    approval = _consume_lifecycle_approval(
        registry, payload, action=action, name=name, version=version,
        current_hash=str(state["lifecycle"].get("actual_hash")
                         or state["lifecycle"].get("content_hash") or ""),
        content_hash=str(state["lifecycle"].get("actual_hash") or ""),
        target_pin_policy=policy,
    )
    try:
        return transition_pin(
            registry, skills_dir, name, version, policy, reason=approval["reason"],
            approval_event_id=approval["approval_event_id"],
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.get("/api/skills/discover/{name}")
async def get_discovered_skill(name: str, version: str | None = Query(None)) -> dict[str, Any]:
    """Return one registered skill with stable explainability and provenance fields."""
    assert skill_registry is not None
    result = SkillDiscovery(skill_registry).discover(name=name, status="all", limit=100)
    matches = result["results"]
    if version is not None:
        matches = [item for item in matches if item["version"] == version]
    if not matches:
        raise HTTPException(status_code=404, detail="Skill not found")
    return matches[0]


@app.post("/api/skill-registry")
async def register_skill(metadata: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Validate and persist descriptive skill metadata."""
    assert skill_registry is not None
    try:
        return skill_registry.register(metadata, source="api")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/api/skill-registry")
async def list_registered_skills(status: str | None = Query(None)) -> dict[str, Any]:
    """List registered skill versions in deterministic identity order."""
    assert skill_registry is not None
    if status not in (None, "active", "disabled"):
        raise HTTPException(status_code=422, detail="status must be active or disabled")
    skills = skill_registry.list(status=status)
    return {"count": len(skills), "skills": skills}


@app.get("/api/skill-registry/search")
async def search_registered_skills(q: str = Query(..., min_length=1)) -> dict[str, Any]:
    """Search active skill metadata by name, description, capability, or tool."""
    assert skill_registry is not None
    skills = skill_registry.search(q)
    return {"count": len(skills), "skills": skills}


@app.get("/api/skill-registry/{name}/{version}/status")
async def get_registered_skill_status(name: str, version: str) -> dict[str, Any]:
    assert skill_registry is not None
    status = skill_registry.status(name, version)
    if status is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"name": name, "version": version, "status": status}


@app.post("/api/skill-registry/{name}/{version}/disable")
async def disable_registered_skill(name: str, version: str) -> dict[str, Any]:
    assert skill_registry is not None
    skill = skill_registry.disable(name, version)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@app.delete("/api/skill-registry/{name}/{version}", status_code=204)
async def remove_registered_skill(name: str, version: str) -> Response:
    assert skill_registry is not None
    record = skill_registry.get(name, version)
    if record and (record.get("provenance") or {}).get("installed_path"):
        raise HTTPException(
            status_code=409,
            detail="installed skills require the audited lifecycle removal flow",
        )
    if not skill_registry.remove(name, version):
        raise HTTPException(status_code=404, detail="Skill not found")
    return Response(status_code=204)


@app.get("/api/skill-registry/{name}/{version}")
async def get_registered_skill(name: str, version: str) -> dict[str, Any]:
    assert skill_registry is not None
    skill = skill_registry.get(name, version)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@app.get("/api/skills/{name}")
async def get_skill(name: str) -> dict[str, Any]:
    """Return a single skill's metadata."""
    assert skill_mgr is not None
    skill = skill_mgr.get_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return skill.to_dict()


@app.get("/api/skills/{name}/activate")
async def activate_skill(name: str) -> dict[str, Any]:
    """Activate a skill and return its full content."""
    assert skill_mgr is not None
    info = skill_mgr.get_skill(name)
    record = skill_registry.get(name, info.version) if skill_registry and info else None
    lifecycle = (record or {}).get("lifecycle", {})
    if lifecycle.get("trust_state") in {"revoked", "blocked"} or lifecycle.get(
        "state"
    ) in {"quarantined", "removed"}:
        raise HTTPException(status_code=403, detail="skill lifecycle policy blocks activation")
    dependencies = skill_mgr.preflight_dependencies(
        name, connected_servers=mcp_client.get_server_names() if mcp_client else None,
        configured_servers=mcp_client.get_configured_server_names() if mcp_client else None,
        registry=skill_registry,
    )
    blockers = [item for item in dependencies if item["state"] != "satisfied"]
    if blockers:
        raise HTTPException(
            status_code=409,
            detail={"message": "skill dependencies block activation", "dependencies": blockers},
        )
    body = await skill_mgr.activate(
        name, connected_servers=mcp_client.get_server_names() if mcp_client else None,
        configured_servers=mcp_client.get_configured_server_names() if mcp_client else None,
        registry=skill_registry,
    )
    if body is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return {
        "name": name,
        "content": body,
        "dependencies": dependencies,
    }


@app.get("/api/skills/search/{query}")
async def search_skills(query: str) -> dict[str, Any]:
    """Search skills by name, description, or tags."""
    assert skill_mgr is not None
    results = skill_mgr.search_skills(query)
    return {
        "count": len(results),
        "skills": [s.to_dict() for s in results],
    }


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

def _hook_store() -> HookStore:
    return HookStore(get_config().db_path.parent / "hooks.toml")


@app.get("/api/hooks")
async def list_hooks() -> dict[str, Any]:
    return {"hooks": _hook_store().list()}


@app.post("/api/hooks", status_code=201)
async def create_hook(req: dict[str, Any]) -> dict[str, Any]:
    hooks = _hook_store().list()
    hook = {"id": str(req.get("id", "")).strip(),
            "event": str(req.get("event", "")),
            "command": str(req.get("command", "")),
            "timeout_s": int(req.get("timeout_s", 30)),
            "enabled": bool(req.get("enabled", True))}
    if not hook["id"] or hook["event"] not in HookStore.EVENTS or not hook["command"]:
        raise HTTPException(status_code=422, detail="id, valid event, and command are required")
    if not 1 <= hook["timeout_s"] <= 300 or any(item["id"] == hook["id"] for item in hooks):
        raise HTTPException(status_code=409, detail="invalid timeout or duplicate hook id")
    hooks.append(hook)
    _hook_store().save(hooks)
    return hook


@app.put("/api/hooks/{hook_id}")
async def update_hook(hook_id: str, req: dict[str, Any]) -> dict[str, Any]:
    store = _hook_store()
    hooks = store.list()
    for index, hook in enumerate(hooks):
        if hook["id"] != hook_id:
            continue
        updated = {**hook, **req, "id": hook_id}
        if updated.get("event") not in HookStore.EVENTS or not updated.get("command"):
            raise HTTPException(status_code=422, detail="valid event and command are required")
        updated["timeout_s"] = int(updated.get("timeout_s", 30))
        if not 1 <= updated["timeout_s"] <= 300:
            raise HTTPException(status_code=422, detail="timeout_s must be 1..300")
        hooks[index] = updated
        store.save(hooks)
        return updated
    raise HTTPException(status_code=404, detail="Hook not found")


@app.delete("/api/hooks/{hook_id}")
async def delete_hook(hook_id: str) -> dict[str, str]:
    store = _hook_store()
    hooks = store.list()
    filtered = [item for item in hooks if item.get("id") != hook_id]
    if len(filtered) == len(hooks):
        raise HTTPException(status_code=404, detail="Hook not found")
    store.save(filtered)
    return {"status": "ok", "hook_id": hook_id}


@app.post("/api/hooks/{hook_id}/test")
async def test_hook(hook_id: str) -> dict[str, Any]:
    try:
        return await _hook_store().test(hook_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Hook not found") from exc

@app.get("/api/schedules")
async def list_schedules(
    status: str | None = Query(None),
    tag: str | None = Query(None),
) -> dict[str, Any]:
    """Return all scheduled tasks."""
    assert scheduler is not None
    filter_status = TaskStatus(status) if status else None
    tasks = scheduler.list_tasks(status=filter_status, tag=tag)
    return {
        "count": len(tasks),
        "active_count": scheduler.active_count,
        "tasks": [t.to_dict() for t in tasks],
    }


@app.get("/api/schedules/{task_id}")
async def get_schedule(task_id: str) -> dict[str, Any]:
    """Return a single scheduled task."""
    assert scheduler is not None
    task = scheduler.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Scheduled task not found: {task_id}")
    return task.to_dict()


@app.post("/api/schedules/{task_id}/pause")
async def pause_schedule(task_id: str) -> dict[str, Any]:
    assert scheduler is not None
    task = await scheduler.update_task(task_id, status=TaskStatus.PAUSED)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Scheduled task not found: {task_id}")
    return task.to_dict()


@app.post("/api/schedules/{task_id}/resume")
async def resume_schedule(task_id: str) -> dict[str, Any]:
    assert scheduler is not None
    task = await scheduler.update_task(task_id, status=TaskStatus.ACTIVE)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Scheduled task not found: {task_id}")
    return task.to_dict()


@app.post("/api/schedules")
async def create_schedule(req: ScheduleCreateRequest) -> dict[str, Any]:
    """Create a new scheduled task."""
    assert scheduler is not None
    task = ScheduledTask(
        id=req.id,
        name=req.name,
        description=req.description,
        trigger_type=TriggerType(req.trigger_type),
        trigger_args=req.trigger_args,
        action=req.action,
        tags=req.tags,
    )
    try:
        result = await scheduler.add_task(task)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return result.to_dict()


@app.put("/api/schedules/{task_id}")
async def update_schedule(task_id: str, req: ScheduleUpdateRequest) -> dict[str, Any]:
    """Update an existing scheduled task."""
    assert scheduler is not None
    kwargs: dict[str, Any] = {}
    if req.name is not None:
        kwargs["name"] = req.name
    if req.description is not None:
        kwargs["description"] = req.description
    if req.trigger_type is not None:
        kwargs["trigger_type"] = TriggerType(req.trigger_type)
    if req.trigger_args is not None:
        kwargs["trigger_args"] = req.trigger_args
    if req.action is not None:
        kwargs["action"] = req.action
    if req.status is not None:
        kwargs["status"] = TaskStatus(req.status)
    if req.tags is not None:
        kwargs["tags"] = req.tags

    result = await scheduler.update_task(task_id, **kwargs)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Scheduled task not found: {task_id}")
    return result.to_dict()


@app.delete("/api/schedules/{task_id}")
async def delete_schedule(task_id: str) -> dict[str, str]:
    """Delete a scheduled task."""
    assert scheduler is not None
    ok = await scheduler.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Scheduled task not found: {task_id}")
    return {"status": "ok", "task_id": task_id}


@app.post("/api/schedules/{task_id}/run")
async def run_schedule_now(task_id: str) -> dict[str, str]:
    """Manually trigger a scheduled task immediately."""
    assert scheduler is not None
    ok = await scheduler.run_now(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Scheduled task not found: {task_id}")
    return {"status": "ok", "task_id": task_id}


@app.get("/api/goals")
async def list_goals() -> dict[str, Any]:
    assert scheduler is not None
    goals = [task for task in scheduler.list_tasks() if task.goal]
    return {"count": len(goals), "goals": [task.to_dict() for task in goals]}


@app.post("/api/goals", status_code=201)
async def create_goal(req: GoalCreateRequest) -> dict[str, Any]:
    assert scheduler is not None
    goal = req.goal.strip()
    if not goal:
        raise HTTPException(status_code=422, detail="Goal must not be empty")
    task = ScheduledTask(
        id=req.id,
        name=req.name,
        description=req.description,
        trigger_type=TriggerType(req.trigger_type),
        trigger_args=req.trigger_args,
        action=f"agent:{goal}",
        tags=req.tags,
        goal=goal,
    )
    try:
        result = await scheduler.add_task(task)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await scheduler.record_goal_event(result.id, "goal.created", {})
    return result.to_dict()


@app.get("/api/goals/{goal_id}")
async def get_goal(goal_id: str) -> dict[str, Any]:
    assert scheduler is not None
    task = scheduler.get_task(goal_id)
    if not task or not task.goal:
        raise HTTPException(status_code=404, detail=f"Scheduled goal not found: {goal_id}")
    return task.to_dict()


@app.put("/api/goals/{goal_id}")
async def update_goal(goal_id: str, req: dict[str, Any]) -> dict[str, Any]:
    assert scheduler is not None
    task = scheduler.get_task(goal_id)
    if not task or not task.goal:
        raise HTTPException(status_code=404, detail=f"Scheduled goal not found: {goal_id}")
    allowed = {key: req[key] for key in ("name", "description", "trigger_args", "tags") if key in req}
    if "trigger_type" in req:
        try:
            allowed["trigger_type"] = TriggerType(req["trigger_type"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid trigger_type") from exc
    if "goal" in req:
        value = req["goal"]
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=422, detail="goal must not be empty")
        if value != task.goal:
            task.goal = value
            task.action = f"agent:{value}"
            task.goal_status = "pending"
            await scheduler.record_goal_event(goal_id, "goal.replaced", {"goal": value})
    updated = await scheduler.update_task(goal_id, **allowed)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Scheduled goal not found: {goal_id}")
    return updated.to_dict()


@app.post("/api/goals/{goal_id}/pause")
async def pause_goal(goal_id: str) -> dict[str, Any]:
    assert scheduler is not None
    task = scheduler.get_task(goal_id)
    if not task or not task.goal:
        raise HTTPException(status_code=404, detail="Scheduled goal not found")
    task.goal_status = "paused"
    await scheduler.update_task(goal_id, status=TaskStatus.PAUSED)
    await scheduler.record_goal_event(goal_id, "goal.paused", {})
    return task.to_dict()


@app.post("/api/goals/{goal_id}/resume")
async def resume_goal(goal_id: str) -> dict[str, Any]:
    assert scheduler is not None
    task = scheduler.get_task(goal_id)
    if not task or not task.goal:
        raise HTTPException(status_code=404, detail="Scheduled goal not found")
    task.goal_status = "pending"
    await scheduler.update_task(goal_id, status=TaskStatus.ACTIVE)
    await scheduler.record_goal_event(goal_id, "goal.resumed", {})
    return task.to_dict()


def _validate_recipe(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"id", "name", "description", "prompt", "params", "active_skills", "mode",
               "workspace", "profile_id", "created_at", "updated_at"}
    if set(value) - allowed:
        raise ValueError("recipe contains unsupported fields")
    required = ("name", "description", "prompt")
    if any(not isinstance(value.get(key), str) for key in required):
        raise ValueError("name, description, and prompt must be strings")
    if value.get("mode", "act") not in {"act", "plan"}:
        raise ValueError("mode must be 'act' or 'plan'")
    params = value.get("params", [])
    if (not isinstance(params, list) or any(
        not isinstance(item, dict) or set(item) - {"name", "label", "default"}
        or not isinstance(item.get("name"), str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item["name"])
        for item in params
    )):
        raise ValueError("params must be a list of named parameter objects")
    names = [item["name"] for item in params]
    if len(names) != len(set(names)):
        raise ValueError("parameter names must be unique")
    if not isinstance(value.get("active_skills", []), list):
        raise ValueError("active_skills must be a list")
    if any(not isinstance(item, str) for item in value.get("active_skills", [])):
        raise ValueError("active_skills must contain strings")
    for key in ("workspace", "profile_id"):
        if value.get(key) is not None and not isinstance(value.get(key), str):
            raise ValueError(f"{key} must be a string")
    return {**value, "params": params, "active_skills": value.get("active_skills", []),
            "mode": value.get("mode", "act")}


@app.get("/api/kanban/boards")
async def list_kanban_boards() -> dict[str, Any]:
    return {"boards": _kanban_store().boards()}


@app.post("/api/kanban/boards", status_code=201)
async def create_kanban_board(req: dict[str, Any]) -> dict[str, Any]:
    try:
        board = _kanban_store().create_board(str(req.get("name", "")), req.get("id"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return board


@app.get("/api/kanban/boards/{board_id}/tasks")
async def list_kanban_tasks(board_id: str) -> dict[str, Any]:
    return {"tasks": _kanban_store().tasks(board_id)}


@app.post("/api/kanban/boards/{board_id}/tasks", status_code=201)
async def create_kanban_task(board_id: str, req: dict[str, Any]) -> dict[str, Any]:
    try:
        return _kanban_store().create_task(board_id, req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/kanban/boards/{board_id}/tasks/{task_id}")
async def update_kanban_task(board_id: str, task_id: str, req: dict[str, Any]) -> dict[str, Any]:
    try:
        return _kanban_store().update_task(board_id, task_id, req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/recipes")
async def list_recipes() -> dict[str, Any]:
    return {"recipes": _task_store("recipes").list()}


@app.post("/api/recipes", status_code=201)
async def create_recipe(req: dict[str, Any]) -> dict[str, Any]:
    try:
        return _task_store("recipes").put(_validate_recipe(req))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/recipes/{recipe_id}")
async def update_recipe(recipe_id: str, req: dict[str, Any]) -> dict[str, Any]:
    store = _task_store("recipes")
    old = store.get(recipe_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    try:
        return store.put(_validate_recipe({**old, **req, "id": recipe_id, "created_at": old["created_at"]}))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/recipes/{recipe_id}")
async def delete_recipe(recipe_id: str) -> dict[str, str]:
    if not _task_store("recipes").delete(recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {"status": "deleted"}


@app.post("/api/recipes/{recipe_id}/render")
async def render_recipe(recipe_id: str, req: dict[str, Any]) -> dict[str, Any]:
    recipe = _task_store("recipes").get(recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    supplied = req.get("params", {})
    if not isinstance(supplied, dict):
        raise HTTPException(status_code=422, detail="params must be an object")
    missing = []
    rendered = recipe["prompt"]
    for param in recipe.get("params", []):
        name = param["name"]
        value = supplied.get(name, param.get("default"))
        if value is None:
            missing.append(name)
        else:
            rendered = rendered.replace("{{" + name + "}}", str(value))
    if missing:
        raise HTTPException(status_code=422, detail={"missing": missing})
    return {key: recipe.get(key) for key in ("active_skills", "mode", "workspace", "profile_id")} | {"prompt": rendered}


@app.post("/api/recipes/from-run", status_code=201)
async def recipe_from_run(req: dict[str, Any]) -> dict[str, Any]:
    assert memory is not None
    run = runtime_mgr.runs.get(str(req.get("run_id", "")))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    conv = await memory.get_conversation(run.conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Run conversation not found")
    messages = await memory.get_conversation_messages(conv["id"], limit=1000)
    user_message = run.user_input or next((item["content"] for item in reversed(messages) if item["role"] == "user"), None)
    if not user_message:
        raise HTTPException(status_code=422, detail="Run has no user message")
    try:
        return _task_store("recipes").put(_validate_recipe({
            "name": req.get("name", "Saved run"), "description": "从一次任务生成",
            "prompt": user_message, "params": [], "active_skills": run.active_skills,
            "mode": run.mode, "workspace": conv.get("workspace") or run.workspace,
            "profile_id": run.profile_id,
        }))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/profiles")
async def list_profiles() -> dict[str, Any]:
    profiles = _profile_store().list()
    for profile in profiles:
        profile.setdefault("tools", {}).setdefault("allow", None)
        profile["tools"].setdefault("deny", [])
        profile.setdefault("model", None)
        profile.setdefault("reasoning_effort", None)
    return {"profiles": profiles}


@app.post("/api/profiles", status_code=201)
async def create_profile(req: dict[str, Any]) -> dict[str, Any]:
    try:
        return _profile_store().put(_validate_profile(req))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_profile(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"id", "name", "description", "model", "reasoning_effort", "instructions",
               "active_skills", "tools", "mode", "created_at", "updated_at"}
    if set(value) - allowed:
        raise ValueError("profile contains unsupported fields")
    if not isinstance(value.get("name"), str) or not value["name"].strip():
        raise ValueError("name is required")
    if value.get("mode", "act") not in {"act", "plan"}:
        raise ValueError("mode must be 'act' or 'plan'")
    if value.get("reasoning_effort") not in {None, "minimal", "low", "medium", "high"}:
        raise ValueError("invalid reasoning_effort")
    tools = value.get("tools", {"allow": None, "deny": []})
    if not isinstance(tools, dict) or (tools.get("allow") is not None and not isinstance(tools.get("allow"), list)):
        raise ValueError("tools.allow must be a list or null")
    if not isinstance(tools.get("deny", []), list):
        raise ValueError("tools.deny must be a list")
    tools = {"allow": tools.get("allow"), "deny": tools.get("deny", [])}
    if any(not isinstance(item, str) for item in (tools["allow"] or []) + tools["deny"]):
        raise ValueError("tool names must be strings")
    if not isinstance(value.get("active_skills", []), list):
        raise ValueError("active_skills must be a list")
    if any(not isinstance(item, str) for item in value.get("active_skills", [])):
        raise ValueError("active_skills must contain strings")
    if value.get("model") is not None and not isinstance(value.get("model"), str):
        raise ValueError("model must be a string")
    if not isinstance(value.get("description", ""), str) or not isinstance(value.get("instructions", ""), str):
        raise ValueError("description and instructions must be strings")
    return {**value, "description": value.get("description", ""), "instructions": value.get("instructions", ""),
            "active_skills": value.get("active_skills", []), "tools": tools, "mode": value.get("mode", "act")}


@app.put("/api/profiles/{profile_id}")
async def update_profile(profile_id: str, req: dict[str, Any]) -> dict[str, Any]:
    store = _profile_store()
    old = store.get(profile_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    try:
        return store.put(_validate_profile({**old, **req, "id": profile_id, "created_at": old["created_at"]}))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/profiles/{profile_id}")
async def delete_profile(profile_id: str) -> dict[str, str]:
    if profile_id in {"default", "architect", "reviewer"}:
        raise HTTPException(status_code=409, detail="Built-in profiles cannot be deleted")
    if not _profile_store().delete(profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"status": "deleted"}


@app.get("/api/goals/{goal_id}/trace")
async def get_goal_trace(
    goal_id: str, run_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return a goal's append-ordered execution audit trace."""
    assert scheduler is not None
    trace = scheduler.goal_trace(goal_id, run_id=run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Scheduled goal not found: {goal_id}")
    return trace


@app.post("/api/goals/{goal_id}/run")
async def run_goal_now(goal_id: str) -> dict[str, str]:
    assert scheduler is not None
    task = scheduler.get_task(goal_id)
    if not task or not task.goal:
        raise HTTPException(status_code=404, detail=f"Scheduled goal not found: {goal_id}")
    if task.goal_status == "blocked":
        progress = dict(task.goal_progress or {})
        progress.update({"blocked": False, "blocked_reason": ""})
        await scheduler.update_goal_state(goal_id, status="pending", progress=progress)
        await scheduler.record_goal_event(goal_id, "goal.retry_requested", {})
    await scheduler.run_now(goal_id)
    return {"status": "ok", "goal_id": goal_id}


# ---------------------------------------------------------------------------
# Runtime Protocol
# ---------------------------------------------------------------------------

@app.get("/api/runtime/protocol")
async def runtime_protocol() -> dict[str, str]:
    """Advertise Runtime Event Protocol version."""
    return {"version": "1.9"}


@app.get("/api/usage")
async def get_usage(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    group_by: str = Query(default="day", pattern="^(day|conversation|model)$"),
) -> dict[str, Any]:
    if usage_ledger is None:
        return {"rows": [], "totals": {"runs": 0, "input_tokens": 0,
                "output_tokens": 0, "cached_input_tokens": 0,
                "cache_hit_rate": None, "est_cost": 0}}
    return await usage_ledger.query(start=from_, end=to, group_by=group_by)


@app.get("/api/safety")
async def get_safety() -> dict[str, Any]:
    return {"settings": get_safety_settings(), "rules": get_safety_rules()}


@app.put("/api/safety")
async def put_safety(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"settings": update_safety_settings(body), "rules": get_safety_rules()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/safety/log")
async def get_safety_review_log(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    return {"rows": get_safety_log(limit)}


@app.get("/api/asr/status")
async def get_asr_status() -> dict[str, Any]:
    global asr_manager
    if asr_manager is None:
        asr_manager = ASRManager()
    return asr_manager.status()


@app.post("/api/asr/download")
async def download_asr_model() -> dict[str, Any]:
    global asr_manager
    if asr_manager is None:
        asr_manager = ASRManager()
    try:
        await asr_manager.download()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return asr_manager.status()


@app.websocket("/ws/asr")
async def asr_websocket(websocket: WebSocket) -> None:
    global asr_manager
    await websocket.accept()
    if asr_manager is None:
        asr_manager = ASRManager()
    if not asr_manager.status()["ready"]:
        await websocket.send_json({"type": "error", "detail": "请先下载本地语音模型。"})
        await websocket.close(code=1013)
        return
    try:
        while True:
            packet = await websocket.receive()
            if packet.get("bytes") is not None:
                data = packet["bytes"]
                if len(data) > 128 * 1024 or len(data) % 2:
                    await websocket.send_json({"type": "error", "detail": "音频帧大小或 PCM 格式无效。"})
                    continue
                partials, finals = await asyncio.to_thread(asr_manager.process_frame, data)
                for text in partials:
                    await websocket.send_json({"type": "partial", "text": text})
                for text in finals:
                    await websocket.send_json({"type": "final", "text": text})
            elif packet.get("text") is not None:
                try:
                    message = json.loads(packet["text"])
                except ValueError:
                    continue
                if message.get("type") == "end":
                    partials, finals = await asyncio.to_thread(asr_manager.process_frame, b"", final=True)
                    for text in finals:
                        await websocket.send_json({"type": "final", "text": text})
                    await websocket.send_json({"type": "ended"})
                    await websocket.close()
                    return
    except WebSocketDisconnect:
        return
    except Exception as exc:
        with suppress(Exception):
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close(code=1011)


@app.post("/api/runs/{run_id}/subtasks/{subtask_id}/cancel")
async def cancel_subtask(run_id: str, subtask_id: str) -> dict[str, str]:
    run = runtime_mgr.runs.get(run_id)
    subtask = run.subtasks.get(subtask_id) if run else None
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")
    if subtask.get("status") in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Subtask is already finished")
    subtask["cancel_event"].set()
    return {"status": "cancelling", "subtask_id": subtask_id}


# ---------------------------------------------------------------------------
# WebSocket chat — Runtime Event Protocol 1.2
# ---------------------------------------------------------------------------

class RunState:
    """Tracks a single agent run's state for the runtime protocol."""

    __slots__ = (
        "run_id", "conversation_id", "model", "started_at", "sequence",
        "status", "events", "cancel_event", "pause_event",
        "approval_futures", "task", "plan_state",
        "event_lock", "steer_queue", "input_futures", "mode", "workspace",
        "usage", "workspace_rules", "plan_future", "plan_edits",
        "tool_allow", "tool_deny", "reasoning_effort", "reasoning_effort_applied",
        "ephemeral", "ephemeral_source", "tool_output_dir", "subtasks",
        "read_only", "active_skills", "profile_id", "user_input",
        "permission_mode", "allowed_paths", "trust_future", "trust_event_id",
        "executor", "sandbox", "extra_roots",
        "trust_roots",
        "project_id",
        "telegram_user_id",
    )

    def __init__(self, run_id: str, conversation_id: str, model: str) -> None:
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.model = model
        self.started_at = datetime.now(UTC).isoformat()
        self.sequence = 0
        self.status = "running"  # running | paused | waiting | completed | failed | cancelled
        self.events: list[dict[str, Any]] = []  # full event log for replay
        self.cancel_event = asyncio.Event()
        self.pause_event = asyncio.Event()
        self.pause_event.set()  # not paused initially
        self.approval_futures: dict[str, asyncio.Future[str]] = {}
        self.task: asyncio.Task[None] | None = None
        self.plan_state: dict[str, Any] | None = None
        self.event_lock = asyncio.Lock()
        self.steer_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.input_futures: dict[str, asyncio.Future[str]] = {}
        self.mode = "act"
        self.workspace: str | None = None
        self.usage: list[dict[str, Any]] = []
        self.workspace_rules: list[dict[str, Any]] = []
        self.plan_future: asyncio.Future[dict[str, str]] | None = None
        self.plan_edits = ""
        self.tool_allow: list[str] | None = None
        self.tool_deny: list[str] = []
        self.reasoning_effort: str | None = None
        self.reasoning_effort_applied: bool | None = None
        self.ephemeral = False
        self.ephemeral_source: str | None = None
        self.tool_output_dir: Path | None = None
        self.subtasks: dict[str, dict[str, Any]] = {}
        self.read_only = False
        self.active_skills: list[str] = []
        self.profile_id: str | None = None
        self.user_input = ""
        self.permission_mode = "full_access"
        self.allowed_paths: list[str] = []
        self.trust_future: asyncio.Future[bool] | None = None
        self.trust_event_id: str | None = None
        self.executor = "atlas"
        self.sandbox: dict[str, Any] | None = None
        self.extra_roots: list[str] = []
        self.trust_roots: list[str] = []
        self.project_id: str | None = None
        self.telegram_user_id: int | None = None

    def next_envelope(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        """Build a Runtime Event envelope and append to log."""
        self.sequence += 1
        envelope = {
            "type": "agent_event",
            "run_id": self.run_id,
            "event_id": f"{self.run_id}:{self.sequence}",
            "sequence": self.sequence,
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "data": data,
        }
        self.events.append(envelope)
        return envelope


class RuntimeManager:
    """Manages active WebSocket connections and agent runs."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.connections: dict[str, WebSocket] = {}  # conn_id → ws
        self.runs: dict[str, RunState] = {}  # run_id → RunState
        self.conn_runs: dict[str, str] = {}  # conn_id → active run_id
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self, db_path: Path | None = None) -> None:
        """Load persisted lifecycle metadata and fail runs interrupted by restart."""
        if db_path is not None:
            self.db_path = db_path
        if self.db_path is None:
            self.db_path = get_config().db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS runtime_runs (
                run_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                sequence INTEGER NOT NULL DEFAULT 0,
                recovery_event TEXT,
                plan_state TEXT
            )
        """)
        async with self._db.execute("PRAGMA table_info(runtime_runs)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        if "plan_state" not in columns:
            await self._db.execute("ALTER TABLE runtime_runs ADD COLUMN plan_state TEXT")
        await self._db.commit()
        async with self._db.execute("SELECT * FROM runtime_runs") as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            run = RunState(row["run_id"], row["conversation_id"], row["model"])
            run.status = row["status"]
            run.sequence = row["sequence"]
            run.plan_state = json.loads(row["plan_state"]) if row["plan_state"] else None
            if run.status in ("running", "paused", "waiting"):
                run.status = "failed"
                recovery = run.next_envelope("run.failed", {
                    "category": "interrupted",
                    "detail": (
                        "The service restarted while this run was active; "
                        "execution was not resumed."
                    ),
                    "recoverable": True,
                })
                await self.persist_run(run, recovery_event=recovery)
            elif row["recovery_event"]:
                run.events.append(json.loads(row["recovery_event"]))
            self.runs[run.run_id] = run

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def persist_run(
        self, run: RunState, recovery_event: dict[str, Any] | None = None,
    ) -> None:
        if self._db is None:
            return
        await self._db.execute("""
            INSERT INTO runtime_runs (
                run_id, conversation_id, model, status, sequence, recovery_event, plan_state
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                conversation_id=excluded.conversation_id,
                model=excluded.model,
                status=excluded.status,
                sequence=excluded.sequence,
                recovery_event=COALESCE(excluded.recovery_event, runtime_runs.recovery_event),
                plan_state=COALESCE(excluded.plan_state, runtime_runs.plan_state)
        """, (
            run.run_id, run.conversation_id, run.model, run.status, run.sequence,
            json.dumps(recovery_event) if recovery_event else None,
            json.dumps(run.plan_state, ensure_ascii=False) if run.plan_state else None,
        ))
        await self._db.commit()

    async def connect(self, ws: WebSocket, conn_id: str) -> None:
        await ws.accept()
        self.connections[conn_id] = ws

    def disconnect(self, conn_id: str) -> None:
        self.connections.pop(conn_id, None)
        self.conn_runs.pop(conn_id, None)

    async def send(self, conn_id: str, data: dict[str, Any]) -> None:
        ws = self.connections.get(conn_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                pass  # connection may have closed

    async def send_run(self, run: RunState, data: dict[str, Any], fallback_conn_id: str) -> None:
        """Send to the most recently attached connection for this run."""
        conn_id = next(
            (
                conn for conn, active_run_id in reversed(self.conn_runs.items())
                if active_run_id == run.run_id
            ),
            fallback_conn_id,
        )
        async with run.event_lock:
            await self.persist_run(run)
            await self.send(conn_id, data)


runtime_mgr = RuntimeManager()


async def _handle_rules_trust(conn_id: str, data: dict[str, Any]) -> None:
    run_id = str(data.get("run_id", ""))
    run = runtime_mgr.runs.get(run_id)
    if run and run.trust_future and not run.trust_future.done() and run.trust_event_id:
        # One RunState has one outstanding trust request, so a stale event_id
        # after reconnect can safely fall back to run_id.
        trusted = data.get("trust") is True
        if trusted:
            for root in run.trust_roots or ([run.workspace] if run.workspace else []):
                _set_workspace_trusted(root, True)
        run.trust_future.set_result(trusted)
        return
    await runtime_mgr.send(conn_id, {
        "type": "error", "run_id": run_id,
        "detail": "没有可匹配的待处理规则信任请求。",
    })


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    """Runtime Event Protocol 1.2 WebSocket endpoint.

    Client sends:
        {"type": "run.start", "run_id": "...", "content": "...",
         "conversation_id": "...", "model": "..."}
        {"type": "resume", "run_id": "...", "after_sequence": N}
        {"type": "run.cancel", "run_id": "..."}
        {"type": "run.pause", "run_id": "..."}
        {"type": "run.resume", "run_id": "..."}
        {"type": "approval.response", "event_id": "...", "choice": "allow"|"deny"}

    Server sends:
        {"type": "agent_event", "run_id": "...", "event_id": "...", "sequence": N,
         "timestamp": "...", "event": "<event_type>", "data": {...}}

    Event types: run.started, run.status, run.phase, message.delta,
    message.completed, tool.started, tool.completed, approval.required,
    approval.responded, artifact.updated, run.paused, run.resumed,
    run.completed, run.failed, run.cancelled
    """
    conn_id = str(uuid.uuid4())
    await runtime_mgr.connect(ws, conn_id)

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type", "")

            if msg_type == "run.start":
                await _handle_run_start(conn_id, data)

            elif msg_type == "resume":
                await _handle_resume(conn_id, data)

            elif msg_type == "rules.trust":
                await _handle_rules_trust(conn_id, data)

            elif msg_type == "run.cancel":
                run_id = data.get("run_id", "")
                run = runtime_mgr.runs.get(run_id)
                if run and run.status not in ("completed", "failed", "cancelled"):
                    run.cancel_event.set()

            elif msg_type == "run.steer":
                run_id = str(data.get("run_id", ""))
                run = runtime_mgr.runs.get(run_id)
                if not run:
                    rejected = RunState(run_id, "", "")
                    await runtime_mgr.send(conn_id, rejected.next_envelope(
                        "run.steer.rejected", {"reason": "run_not_active"},
                    ))
                else:
                    reason = _queue_run_steer(run, data.get("content"), data.get("event_id"))
                    if reason:
                        rejected = RunState(run_id, "", "")
                        await runtime_mgr.send(conn_id, rejected.next_envelope(
                            "run.steer.rejected", {"reason": reason},
                        ))

            elif msg_type == "subtask.message":
                run_id = str(data.get("run_id", ""))
                subtask_id = str(data.get("subtask_id", ""))
                text = data.get("text")
                run = runtime_mgr.runs.get(run_id)
                service = getattr(orchestrator, "_delegation", None) if orchestrator else None
                if (run is None or service is None or not isinstance(text, str)
                        or not service.steer_subtask(subtask_id, text)):
                    if run is not None:
                        await runtime_mgr.send_run(run, run.next_envelope(
                            "subtask.steer_rejected", {"subtask_id": subtask_id,
                                                        "reason": "subtask_not_active"},
                        ), conn_id)
                else:
                    await runtime_mgr.send_run(run, run.next_envelope(
                        "subtask.steered", {"subtask_id": subtask_id, "text": text.strip()},
                    ), conn_id)

            elif msg_type == "input.response":
                event_id = str(data.get("event_id", ""))
                for run in runtime_mgr.runs.values():
                    future = run.input_futures.pop(event_id, None)
                    if future and not future.done():
                        future.set_result(str(data.get("text", "")))
                        break

            elif msg_type == "run.plan.approve":
                run = runtime_mgr.runs.get(str(data.get("run_id", "")))
                if (run and run.status == "waiting" and run.plan_future
                        and not run.plan_future.done()
                        and data.get("event_id") == f"plan:{run.run_id}"):
                    run.plan_future.set_result({
                        "action": "approve", "edits": str(data.get("edits", "")),
                    })

            elif msg_type == "run.pause":
                run_id = data.get("run_id", "")
                run = runtime_mgr.runs.get(run_id)
                if run and run.status == "running":
                    run.pause_event.clear()
                    run.status = "paused"
                    env = run.next_envelope("run.paused", {"status": "paused"})
                    await runtime_mgr.persist_run(run)
                    await runtime_mgr.send(conn_id, env)

            elif msg_type == "run.resume":
                run_id = data.get("run_id", "")
                run = runtime_mgr.runs.get(run_id)
                if run and run.status == "paused":
                    run.pause_event.set()
                    run.status = "running"
                    env = run.next_envelope("run.resumed", {"status": "running"})
                    await runtime_mgr.persist_run(run)
                    await runtime_mgr.send(conn_id, env)

            elif msg_type == "approval.response":
                event_id = data.get("event_id", "")
                choice = data.get("choice", "deny")
                # Find the run that has this approval
                for run in runtime_mgr.runs.values():
                    fut = run.approval_futures.pop(event_id, None)
                    if fut and not fut.done():
                        fut.set_result(choice)
                        env = run.next_envelope("approval.responded", {
                            "event_id": event_id, "choice": choice,
                        })
                        await runtime_mgr.persist_run(run)
                        await runtime_mgr.send(conn_id, env)
                        break

    except WebSocketDisconnect:
        runtime_mgr.disconnect(conn_id)


async def _handle_run_start(conn_id: str, data: dict[str, Any]) -> None:
    """Start a new agent run."""
    run_id = data.get("run_id") or str(uuid.uuid4())
    existing = runtime_mgr.runs.get(run_id)
    if existing:
        runtime_mgr.conn_runs[conn_id] = run_id
        async with existing.event_lock:
            for env in list(existing.events):
                await runtime_mgr.send(conn_id, env)
        return

    content = data.get("content", "")
    if not isinstance(content, str):
        content = str(content)
    requested_workspace = data.get("workspace")
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
        await runtime_mgr.send(conn_id, invalid.next_envelope("run.failed", {
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
            await runtime_mgr.send(conn_id, invalid.next_envelope("run.failed", {
                "category": "validation", "detail": "附加目录必须是绝对路径或 SSH 地址，且最多 5 个。",
            }))
            return
    profile_id = data.get("profile_id")
    profile = _profile_store().get(str(profile_id)) if profile_id else None
    if profile_id and profile is None:
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await runtime_mgr.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": f"profile not found: {profile_id}",
        }))
        return
    effective_skills = data.get("active_skills", (profile or {}).get("active_skills", []))
    effective_mode = data.get("mode", (profile or {}).get("mode", "act"))
    model_id = data.get("model", (profile or {}).get("model"))
    reasoning_effort = data.get("reasoning_effort", (profile or {}).get("reasoning_effort"))
    permission_mode = data.get("permission_mode")
    allowed_paths = data.get("allowed_paths")
    if allowed_paths is not None and (not isinstance(allowed_paths, list) or any(
            not isinstance(item, str) or not Path(item).is_absolute() for item in allowed_paths)):
        permission_mode = "invalid"
    if permission_mode is None:
        permission_mode = "full_access"
    if permission_mode not in {"full_access", "ask_writes", "read_only"}:
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await runtime_mgr.send(conn_id, invalid.next_envelope("run.failed", {
            "category": "validation", "detail": "invalid permission_mode or allowed_paths",
        }))
        return
    if reasoning_effort not in {None, "minimal", "low", "medium", "high"}:
        invalid = RunState(run_id, str(data.get("conversation_id", "")), "")
        await runtime_mgr.send(conn_id, invalid.next_envelope("run.failed", {
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
        await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
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
        await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
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
        await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": str(exc),
        }))
        return
    resume_from = data.get("resume_from")
    recovered_plan = None
    prior_run = runtime_mgr.runs.get(resume_from) if isinstance(resume_from, str) else None
    if resume_from is not None:
        if not prior_run or prior_run.status != "failed" or not prior_run.plan_state:
            raise ValueError("resume_from must reference an interrupted run with a saved plan")
        recovered_plan = prior_run.plan_state
        if not content:
            content = str(recovered_plan.get("goal", ""))
    conv_id = data.get("conversation_id") or (
        prior_run.conversation_id if prior_run else str(uuid.uuid4())
    )
    assert model_mgr is not None
    run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
    if isinstance(data.get("telegram_user_id"), int):
        run.telegram_user_id = data["telegram_user_id"]
    if effective_mode not in {"act", "plan"}:
        run.status = "failed"
        await runtime_mgr.send(conn_id, run.next_envelope("run.failed", {
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
        await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": "Docker 沙箱配置无效。",
        }))
        return
    if run.sandbox and run.executor != "atlas":
        invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
        await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": "Docker 沙箱目前只支持 Atlas Agent 执行。",
        }))
        return
    if run.executor not in {"atlas", "codex", "claude", "hermes", "pi", "zcode"}:
        invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
        await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": "所选执行 Agent 不受支持。",
        }))
        return
    if run.executor != "atlas":
        # External Agents get every permission request auto-approved (runtime/backends.py), so
        # Atlas can't honour "ask before changes" for them either; only full access may start one.
        if run.permission_mode in {"read_only", "ask_writes"} or run.read_only:
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            mode = "只读" if run.permission_mode == "read_only" or run.read_only else "改前问我"
            await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "permission",
                "detail": f"当前对话是「{mode}」模式，外部 Agent 的操作不经过 Atlas 确认，所以不能启动。"
                          "请把对话权限切到「完全访问」后重试。",
            }))
            return
        if workspace and str(workspace).startswith("ssh://"):
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
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
            await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
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
        await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
            "category": "validation", "detail": "Docker 沙箱需要本机工作目录，不能与 ssh:// 同时使用。",
        }))
        return
    if workspace and str(workspace).startswith("ssh://"):
        try:
            host, remote_root = ssh_workspaces.parse_workspace(str(workspace))
        except ValueError as exc:
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "validation", "detail": str(exc),
            }))
            return
        if data.get("worktree") is not None:
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
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
            await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "validation", "detail": "workspace directory does not exist",
            }))
            return
        if conversation and conversation.get("worktree_path"):
            workspace_path = Path(conversation["worktree_path"]).resolve()
            if not workspace_path.is_dir():
                invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
                await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
                    "category": "validation", "detail": "conversation worktree is missing",
                }))
                return
        worktree_request = data.get("worktree")
        if worktree_request is not None:
            if not isinstance(worktree_request, dict):
                invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
                await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
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
                    await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
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
            await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "validation", "detail": "context_files must be a list",
            }))
            return
        if context_files and not run.workspace:
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
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
                await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
                    "category": "validation", "detail": str(exc.detail),
                }))
                return
        if context_blocks:
            content += "".join(context_blocks)
        context_conversations = data.get("context_conversations", [])
        if not isinstance(context_conversations, list) or len(context_conversations) > 3:
            invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
            await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
                "category": "validation", "detail": "context_conversations must contain at most three conversation ids",
            }))
            return
        for other_id in context_conversations:
            other = await memory.get_conversation(str(other_id)) if memory else None
            if other is None:
                invalid_run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
                await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
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
                await runtime_mgr.send(conn_id, invalid_run.next_envelope("run.failed", {
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
            rules = await workspace_rules(root=root)
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
            await runtime_mgr.send(conn_id, trust_env)
        else:
            await runtime_mgr.send(conn_id, run.next_envelope("rules.loaded", {
                "files": [{"path": item["path"], "bytes": item["bytes"]}
                          for item in run.workspace_rules],
            }))
    runtime_mgr.runs[run_id] = run
    runtime_mgr.conn_runs[conn_id] = run_id
    await runtime_mgr.persist_run(run)

    # Start the run in background so we can keep receiving messages
    execute = _execute_run(
            conn_id, run, content, model_id,
            plan_state=recovered_plan,
            image_attachments=image_attachments,
            active_skill_instructions=active_skill_instructions,
            workspace=run.workspace,
            workspace_rules=run.workspace_rules,
            mode=run.mode,
        )
    run.task = asyncio.create_task(
        _execute_after_rule_trust(run, execute) if run.trust_future else execute
    )


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


async def _handle_resume(conn_id: str, data: dict[str, Any]) -> None:
    """Replay events after a given sequence number."""
    run_id = data.get("run_id", "")
    try:
        after_seq = max(0, int(data.get("after_sequence", 0)))
    except (TypeError, ValueError):
        after_seq = 0
    run = runtime_mgr.runs.get(run_id)
    if not run:
        missing = RunState(run_id, "", "")
        missing.sequence = after_seq
        env = missing.next_envelope("run.failed", {
            "category": "interrupted",
            "detail": "Run state is no longer available; start a new run to continue.",
        })
        await runtime_mgr.send(conn_id, env)
        return

    runtime_mgr.conn_runs[conn_id] = run_id

    # Keep live events behind the replay so sequence order is preserved.
    async with run.event_lock:
        for env in list(run.events):
            if env["sequence"] > after_seq:
                await runtime_mgr.send(conn_id, env)


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
) -> None:
    """Execute agent run, emitting Runtime Event envelopes."""
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
        await runtime_mgr.send_run(run, env, fallback_conn_id=conn_id)
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
        await runtime_mgr.persist_run(run)
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
            await emit("approval.required", approval_payload)
            run.status = "waiting"
            if run.telegram_user_id is not None and telegram_service is not None:
                approval_future = await telegram_service.request_approval(
                    run.telegram_user_id, run.run_id, approval_event_id,
                    f"需要确认执行 {tool_name}。",
                )
                cancel_waiter = asyncio.create_task(run.cancel_event.wait())
                try:
                    done, _ = await asyncio.wait(
                        {approval_future, cancel_waiter}, timeout=600,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if approval_future in done:
                        choice = approval_future.result()
                    else:
                        choice = "deny"
                finally:
                    cancel_waiter.cancel()
                    await asyncio.gather(cancel_waiter, return_exceptions=True)
                run.status = "running"
                return choice
            # Create a future for this approval
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[str] = loop.create_future()
            run.approval_futures[approval_event_id] = fut
            choice = await fut
            run.status = "running"
            return choice

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

            elif etype == "run_status":
                await emit("run.status", {
                    "status": event.get("status", "running"),
                    "text": event.get("text", ""),
                })

            elif etype in {
                "process.completed", "run.compaction.progress", "run.recovery.notice",
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
                    await runtime_mgr.persist_run(run)
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
                        mode="act", continuation=True,
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
