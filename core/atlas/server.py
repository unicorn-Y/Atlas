"""Atlas FastAPI + WebSocket server."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import httpx
from fastapi import Body, FastAPI, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from atlas.agent.capabilities import (
    AgentCapabilityRegistry,
    register_skill_capabilities,
    register_skill_catalog_capabilities,
    register_skill_discovery_capability,
)
from atlas.agent.orchestrator import AgentOrchestrator
from atlas.agent.planning import TaskPlan
from atlas.config import get_config
from atlas.memory.store import MemoryStore
from atlas.models.manager import ModelManager
from atlas.scheduler import AtlasScheduler, ScheduledTask, TaskStatus, TriggerType
from atlas.skills import SKILLS_DIR, SkillManager
from atlas.skills.acquisition import (
    Acquisition,
    CatalogUnavailableError,
    SkillsShProvider,
    inspect_github_source,
    install_acquisition,
)
from atlas.skills.discovery import SkillDiscovery
from atlas.skills.registry import SkillRegistry
from atlas.tools.mcp_client import MCPClient

# ---------------------------------------------------------------------------
# Singletons (populated by lifespan)
# ---------------------------------------------------------------------------

model_mgr: ModelManager | None = None
memory: MemoryStore | None = None
orchestrator: AgentOrchestrator | None = None
mcp_client: MCPClient | None = None
skill_mgr: SkillManager | None = None
skill_registry: SkillRegistry | None = None
skill_catalog_provider = SkillsShProvider()
skill_acquisitions: dict[str, Acquisition] = {}
scheduler: AtlasScheduler | None = None


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
    global model_mgr, memory, orchestrator, mcp_client, skill_mgr, skill_registry, scheduler

    model_mgr = ModelManager()
    memory = MemoryStore()
    await memory.init()
    await runtime_mgr.init(get_config().db_path)

    mcp_client = MCPClient()
    await mcp_client.start()

    skill_mgr = SkillManager()
    await skill_mgr.scan_skills()
    cfg = get_config()
    skill_registry = SkillRegistry(cfg.db_path.parent / "skill-registry.db")
    for skill in skill_mgr.list_skills():
        if skill_registry.get(skill.name, skill.version) is None:
            skill_registry.register({
                "name": skill.name,
                "version": skill.version,
                "description": skill.description,
                "capabilities": [],
                "tools": [],
                "requirements": skill.dependencies,
                "examples": [],
                "aliases": [],
                "tags": skill.tags,
                "category": skill.category,
                "keywords": skill.tags,
                "use_cases": [],
            }, source="local")
    capabilities = AgentCapabilityRegistry()
    register_skill_capabilities(capabilities, skill_mgr)
    register_skill_discovery_capability(capabilities, skill_registry)
    register_skill_catalog_capabilities(capabilities, skill_catalog_provider)

    orchestrator = AgentOrchestrator(
        model_mgr=model_mgr, memory=memory, mcp_client=mcp_client,
        capability_registry=capabilities,
    )

    if cfg.scheduler_enabled:
        scheduler = AtlasScheduler(agent_callback=_run_scheduled_goal)
        await scheduler.start()

    yield  # app is running

    # Shutdown
    if scheduler:
        await scheduler.stop()
    if mcp_client:
        await mcp_client.stop()
    if memory:
        await memory.close()
    await runtime_mgr.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Atlas", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class CustomModelRequest(BaseModel):
    id: str
    name: str
    provider: str
    litellm_model: str


class ConnectionTestRequest(BaseModel):
    model: str | None = None


class ConversationUpdateRequest(BaseModel):
    title: str


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


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


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
    return ModelListResponse(
        models=model_mgr.list_models(),
        current=model_mgr.current_model,
    )


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
    return {
        "gateway_base_url": model_mgr.gateway_base_url,
        "api_key_configured": model_mgr.api_key_configured,
        "models": model_mgr.list_models(),
        "current": model_mgr.current_model,
    }


@app.put("/api/settings/configuration")
async def update_configuration(req: ProviderSettingsRequest) -> dict[str, Any]:
    assert model_mgr is not None
    base_url = req.gateway_base_url.strip()
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="服务地址必须以 http:// 或 https:// 开头")
    model_mgr.update_provider(base_url, req.api_key.strip() if req.api_key and req.api_key.strip() else None)
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
    """Update a conversation's title."""
    assert memory is not None
    ok = await memory.update_conversation_title(conversation_id, req.title)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "ok", "conversation_id": conversation_id}


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict[str, str]:
    """Delete a conversation and all its messages."""
    assert memory is not None
    ok = await memory.delete_conversation(conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "ok", "conversation_id": conversation_id}


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
    skill_acquisitions[acquisition_id] = acquisition
    existing = (
        skill_registry.get(acquisition.record["name"], acquisition.record["version"])
        if skill_registry else None
    )
    return {
        "acquisition_id": acquisition_id, "record": acquisition.record,
        "files": acquisition.files, "validation": acquisition.validation,
        "security": acquisition.security, "computed_sha256": acquisition.computed_hash,
        "already_installed": existing is not None,
        "existing_local": existing,
        "install_target": f"skills/community/{acquisition.record['name']}",
    }


@app.post("/api/skill-catalog/install")
async def install_catalog_skill(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    acquisition_id = payload.get("acquisition_id")
    acquisition = (
        skill_acquisitions.get(acquisition_id) if isinstance(acquisition_id, str) else None
    )
    if acquisition is None:
        raise HTTPException(status_code=404, detail="Reviewed acquisition not found; inspect again")
    if payload.get("approved") is not True or not isinstance(payload.get("approval_event_id"), str):
        raise HTTPException(status_code=403, detail="Explicit user approval is required")
    if acquisition.security["result"] == "WARN" and payload.get("warnings_confirmed") is not True:
        raise HTTPException(status_code=403, detail="WARN risks require explicit confirmation")
    assert skill_registry is not None
    try:
        result = await install_acquisition(
            acquisition, skills_dir=skill_mgr._skills_dir if skill_mgr else SKILLS_DIR,
            registry=skill_registry, approval_event_id=payload["approval_event_id"],
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
    body = await skill_mgr.activate(name)
    if body is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")

    skill = skill_mgr.get_skill(name)
    deps = skill_mgr.check_dependencies(
        name,
        connected_servers=mcp_client.get_server_names() if mcp_client else [],
    )
    return {
        "name": name,
        "content": body,
        "dependencies": deps,
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
    return {"version": "1.2"}


# ---------------------------------------------------------------------------
# WebSocket chat — Runtime Event Protocol 1.2
# ---------------------------------------------------------------------------

class RunState:
    """Tracks a single agent run's state for the runtime protocol."""

    __slots__ = (
        "run_id", "conversation_id", "model", "sequence",
        "status", "events", "cancel_event", "pause_event",
        "approval_futures", "task", "plan_state",
        "event_lock",
    )

    def __init__(self, run_id: str, conversation_id: str, model: str) -> None:
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.model = model
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


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    """Runtime Event Protocol 1.2 WebSocket endpoint.

    Client sends:
        {"type": "run.start", "run_id": "...", "content": "...", "conversation_id": "...", "model": "..."}
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

            elif msg_type == "run.cancel":
                run_id = data.get("run_id", "")
                run = runtime_mgr.runs.get(run_id)
                if run and run.status not in ("completed", "failed", "cancelled"):
                    run.cancel_event.set()

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
    model_id = data.get("model")

    assert model_mgr is not None
    run = RunState(run_id, conv_id, model_id or model_mgr.current_model)
    runtime_mgr.runs[run_id] = run
    runtime_mgr.conn_runs[conn_id] = run_id
    await runtime_mgr.persist_run(run)

    # Start the run in background so we can keep receiving messages
    run.task = asyncio.create_task(
        _execute_run(
            conn_id, run, content, model_id,
            plan_state=recovered_plan,
            image_attachments=image_attachments,
        )
    )


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
        if data["is_error"]:
            data["error_category"] = event.get("error_category", "tool")
        return "tool.completed", data
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
) -> None:
    """Execute agent run, emitting Runtime Event envelopes."""
    assert orchestrator is not None
    assert memory is not None
    had_tool_failure = False
    async def emit(event: str, data: dict[str, Any]) -> None:
        """Emit an event envelope to the client."""
        env = run.next_envelope(event, data)
        await runtime_mgr.send_run(run, env, fallback_conn_id=conn_id)

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
        # Emit run.started
        await emit("run.started", {
            "status": "running",
            "phase": "planning",
            "content": content,
        })

        # Save user message
        try:
            await memory.save_message(
                conversation_id=run.conversation_id,
                role="user",
                content=content,
            )
        except Exception as e:
            run.status = "failed"
            await emit("run.failed", {
                "category": "backend",
                "detail": f"Unable to save user message: {e}",
            })
            return

        if await check_pause_cancel():
            run.status = "cancelled"
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
            await emit("approval.required", {
                "approval_id": approval_event_id,
                "description": f"Agent 请求执行工具 {tool_name}，需要你的确认。",
                "input": tool_args,
                "tool": tool_name,
            })
            run.status = "waiting"
            # Create a future for this approval
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[str] = loop.create_future()
            run.approval_futures[approval_event_id] = fut
            choice = await fut
            run.status = "running"
            return choice

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
        ):
            if await check_pause_cancel():
                run.status = "cancelled"
                await emit("run.cancelled", {})
                return

            # Map orchestrator events to runtime protocol
            etype = event.get("type", "")

            if etype == "chunk":
                chunk_content = event.get("content", "")
                full_response += chunk_content
                await emit("message.delta", {"content": chunk_content})

            elif etype in ("tool_call", "tool_result"):
                mapped = _map_tool_runtime_event(event)
                assert mapped is not None
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

            elif etype == "approval_required":
                # Already emitted by the approval_callback above;
                # no need to re-emit here.
                pass

            elif etype == "plan_updated":
                # The plan state is persisted and emitted by persist_plan.
                pass

            elif etype == "done":
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
                        "Review the failure evidence and validate any proposed resolution before reuse.",
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
