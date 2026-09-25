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

# ---------------------------------------------------------------------------
# Singletons (populated by lifespan)
# ---------------------------------------------------------------------------

model_mgr: ModelManager | None = None
memory: MemoryStore | None = None
orchestrator: AgentOrchestrator | None = None


# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated @app.on_event)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    global model_mgr, memory, orchestrator

    model_mgr = ModelManager()
    memory = MemoryStore()
    await memory.init()
    orchestrator = AgentOrchestrator(model_mgr=model_mgr, memory=memory)

    yield  # app is running

    # Shutdown
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
