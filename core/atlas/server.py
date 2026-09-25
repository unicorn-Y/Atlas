"""Atlas FastAPI + WebSocket server."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from atlas.config import get_config
from atlas.models.manager import ModelManager
from atlas.memory.store import MemoryStore
from atlas.agent.orchestrator import AgentOrchestrator
from atlas.tools.mcp_client import MCPClient
from atlas.scheduler import AtlasScheduler, ScheduledTask, TaskStatus, TriggerType
from atlas.skills import SkillManager

# ---------------------------------------------------------------------------
# Singletons (populated by lifespan)
# ---------------------------------------------------------------------------

model_mgr: ModelManager | None = None
memory: MemoryStore | None = None
orchestrator: AgentOrchestrator | None = None
mcp_client: MCPClient | None = None
skill_mgr: SkillManager | None = None
scheduler: AtlasScheduler | None = None


# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated @app.on_event)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    global model_mgr, memory, orchestrator, mcp_client, skill_mgr, scheduler

    model_mgr = ModelManager()
    memory = MemoryStore()
    await memory.init()

    mcp_client = MCPClient()
    await mcp_client.start()

    skill_mgr = SkillManager()
    await skill_mgr.scan_skills()

    orchestrator = AgentOrchestrator(
        model_mgr=model_mgr, memory=memory, mcp_client=mcp_client,
    )

    cfg = get_config()
    if cfg.scheduler_enabled:
        scheduler = AtlasScheduler()
        await scheduler.start()

    yield  # app is running

    # Shutdown
    if scheduler:
        await scheduler.stop()
    if mcp_client:
        await mcp_client.stop()
    if memory:
        await memory.close()


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


class ConversationUpdateRequest(BaseModel):
    title: str


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


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


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


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

@app.get("/api/conversations")
async def list_conversations() -> list[dict[str, Any]]:
    """Return all conversation summaries."""
    assert memory is not None
    return await memory.list_conversations()


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
# Skills
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# WebSocket chat
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self) -> None:
        self.active: dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket, conn_id: str) -> None:
        await ws.accept()
        self.active[conn_id] = ws

    def disconnect(self, conn_id: str) -> None:
        self.active.pop(conn_id, None)

    async def send_json(self, conn_id: str, data: dict[str, Any]) -> None:
        ws = self.active.get(conn_id)
        if ws:
            await ws.send_json(data)


ws_manager = ConnectionManager()


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    """Main chat WebSocket endpoint.

    Client sends:
        {"type": "message", "content": "...", "conversation_id": "..."}
        {"type": "cancel"}

    Server sends:
        {"type": "chunk", "content": "..."}          # streaming token
        {"type": "tool_call", "name": "...", ...}    # tool invocation
        {"type": "tool_result", "name": "...", ...}  # tool result
        {"type": "done", "message_id": "..."}         # turn complete
        {"type": "error", "detail": "..."}            # error
    """
    conn_id = str(uuid.uuid4())
    await ws_manager.connect(ws, conn_id)

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)

            if data.get("type") == "message":
                content = data.get("content", "")
                conv_id = data.get("conversation_id") or str(uuid.uuid4())
                model_override = data.get("model")  # optional per-message model

                # Save user message
                assert memory is not None
                await memory.save_message(
                    conversation_id=conv_id,
                    role="user",
                    content=content,
                )

                # Run agent
                assert orchestrator is not None
                try:
                    async for event in orchestrator.run(
                        message=content,
                        conversation_id=conv_id,
                        model=model_override,
                    ):
                        await ws_manager.send_json(conn_id, event)
                except Exception as e:
                    await ws_manager.send_json(conn_id, {
                        "type": "error",
                        "detail": str(e),
                    })

            elif data.get("type") == "cancel":
                # TODO: implement cancellation
                await ws_manager.send_json(conn_id, {
                    "type": "cancelled",
                })

    except WebSocketDisconnect:
        ws_manager.disconnect(conn_id)
