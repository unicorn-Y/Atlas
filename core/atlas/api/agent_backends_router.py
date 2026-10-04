"""Agent capability registry and external backend sessions surface (``/api/agent, /api/agents``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.config import get_config
from atlas.runtime.external_agents import external_agent_status

router = APIRouter()


class AgentSessionStartRequest(BaseModel):
    cwd: str | None = None


class AgentPromptRequest(BaseModel):
    prompt: str


def _server() -> Any:
    """Late-bound atlas.server: its module globals stay the seam tests patch."""
    import atlas.server

    return atlas.server


def _service(name: str, services: AppServices) -> Any:
    """Resolve an optional service: per-app container first, then the server module."""
    value = getattr(services, name, None)
    if value is None:
        value = getattr(_server(), name, None)
    return value


@router.get("/api/agent/capabilities")
async def list_agent_capabilities(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Return the capabilities registered for the agent."""
    orchestrator = services.orchestrator
    if orchestrator is None:
        from atlas import server as _atlas_server

        orchestrator = _atlas_server.orchestrator
    assert orchestrator is not None
    capabilities = orchestrator.discover_capabilities()
    return {"count": len(capabilities), "capabilities": capabilities}


@router.post("/api/agent/capabilities/{name}/invoke")
async def invoke_agent_capability(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
    inputs: dict[str, Any] | None = Body(default=None),
) -> dict[str, Any]:
    """Invoke a registered capability through the agent capability registry."""
    orchestrator = services.orchestrator
    if orchestrator is None:
        from atlas import server as _atlas_server

        orchestrator = _atlas_server.orchestrator
    assert orchestrator is not None
    try:
        result = await orchestrator.invoke_capability(name, inputs or {})
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Capability not found: {name}") from None
    return {"name": name, "result": result}


@router.get("/api/agent/backends")
async def list_agent_backends(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    agent_backend_host = _service("agent_backend_host", services)
    """List external Agent adapters without starting their processes."""
    return {"backends": agent_backend_host.names() if agent_backend_host else []}


@router.get("/api/agents/external")
async def list_external_agents(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    return external_agent_status(_server().external_agent_status_cache)


@router.get("/api/agents/types")
async def list_agent_types(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str | None = Query(default=None),
) -> dict[str, Any]:
    """List built-in and imported sub-agent definitions for a workspace."""
    from atlas.agent.definitions import list_agent_types as load_types

    workspace = Path(root).expanduser().resolve() if root else None
    trusted = bool(workspace and _server()._workspace_trust().get(str(workspace), False))
    # Plugin agents join the same discovery layer — no second child runtime.
    types = load_types(
        get_config().db_path.parent, workspace, trusted,
        plugin_agent_dirs=_server()._plugin_agent_dirs(),
    )
    return {"types": types[:20]}


@router.post("/api/agent/backends/{name}/sessions")
async def start_agent_backend_session(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str, req: AgentSessionStartRequest,
) -> dict[str, Any]:
    agent_backend_host = _service("agent_backend_host", services)
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


@router.post("/api/agent/backends/{name}/sessions/{session_id}/resume")
async def resume_agent_backend_session(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str, session_id: str, req: AgentSessionStartRequest,
) -> dict[str, Any]:
    agent_backend_host = _service("agent_backend_host", services)
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


@router.post("/api/agent/sessions/{session_id}/prompt")
async def prompt_agent_backend(
    services: Annotated[AppServices, Depends(get_app_services)],
    session_id: str, req: AgentPromptRequest,
) -> StreamingResponse:
    agent_backend_host = _service("agent_backend_host", services)
    agent_backend_host = _service("agent_backend_host", services)
    if agent_backend_host is None:
        raise HTTPException(status_code=503, detail="Agent backend host is unavailable")
    try:
        await agent_backend_host.send(session_id, req.prompt)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent session not found") from None

    async def stream_events() -> AsyncIterator[str]:
        async for event in agent_backend_host.events(session_id):
            payload = {"type": event.type, **event.data}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream_events(), media_type="text/event-stream")


@router.post("/api/agent/sessions/{session_id}/cancel")
async def cancel_agent_backend_session(
    services: Annotated[AppServices, Depends(get_app_services)],
    session_id: str,
) -> dict[str, str]:
    agent_backend_host = _service("agent_backend_host", services)
    if agent_backend_host is None:
        raise HTTPException(status_code=503, detail="Agent backend host is unavailable")
    try:
        await agent_backend_host.cancel(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent session not found") from None
    return {"status": "cancelled", "session_id": session_id}


@router.delete("/api/agent/sessions/{session_id}")
async def close_agent_backend_session(
    services: Annotated[AppServices, Depends(get_app_services)],
    session_id: str,
) -> dict[str, str]:
    agent_backend_host = _service("agent_backend_host", services)
    if agent_backend_host is None:
        raise HTTPException(status_code=503, detail="Agent backend host is unavailable")
    try:
        await agent_backend_host.close(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent session not found") from None
    return {"status": "closed", "session_id": session_id}
