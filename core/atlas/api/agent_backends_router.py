"""Agent capability registry and external backend sessions surface (``/api/agent, /api/agents``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

import hashlib
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
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
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
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
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
    if agent_backend_host is None:
        raise HTTPException(status_code=503, detail="Agent backend host is unavailable")
    try:
        backend_name, _session = agent_backend_host.sessions.get(session_id, (None, None))
        await agent_backend_host.send(session_id, req.prompt)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent session not found") from None

    # UM02/T02.3：一次 prompt 即一次被调 Agent 调用。API 面没有 LLM tool_call
    # ID，用会话+prompt 摘要派生**稳定**调用 ID（同会话重发同一 prompt 幂等，
    # 重试不产生重复观察）；后端会话 ID 与后端名进 log_refs —— 这条记录只记
    # 对方进入 Atlas 的经历，不替对方安装任何记忆插件。
    prompt_digest = hashlib.sha256(str(req.prompt).encode("utf-8")).hexdigest()[:12]
    agent_call_id = f"agentprompt-{session_id}-{prompt_digest}"

    async def stream_events() -> AsyncIterator[str]:
        claim_parts: list[str] = []
        stream_error: str | None = None
        try:
            async for event in agent_backend_host.events(session_id):
                payload = {"type": event.type, **event.data}
                if event.type in {"done", "agent_end"}:
                    text = next((str(event.data.get(key)) for key in
                                 ("text", "content", "message")
                                 if isinstance(event.data, dict)
                                 and event.data.get(key)), "")
                    if text:
                        claim_parts.append(text)
                elif event.type == "error":
                    stream_error = json.dumps(payload, ensure_ascii=False)[:2000]
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            _record_backend_agent_result(
                backend_name=backend_name, session_id=session_id,
                tool_call_id=agent_call_id,
                claim="".join(claim_parts), error=stream_error)

    return StreamingResponse(stream_events(), media_type="text/event-stream")


def _record_backend_agent_result(*, backend_name: str | None,
                                 session_id: str, tool_call_id: str,
                                 claim: str, error: str | None) -> None:
    """UM02/T02.3：外部后端会话的返回声明 → ATLAS_AGENT_TOOL_RESULT 观察。

    对方（zcode/codex/...）的完成声明按 THIRD_PARTY 自报记录，**不是验证**；
    Atlas 独立验证走 POST /api/unified-memory/verify-agent-result。记录失败只
    记日志（流已经结束，不再影响响应）。
    """
    try:
        from atlas.memory.windows_sources import get_windows_source_service

        service = get_windows_source_service()
        if service is None:
            return
        actor = f"tool-{backend_name}" if backend_name else "tool-external-agent"
        service.record_agent_tool_result(
            tool_name="agent_backend_prompt", actor_id=actor,
            tool_call_id=tool_call_id,
            result_payload={"status": "failed" if error else "completed",
                            "backend": backend_name},
            log_refs={"backend_session_id": session_id,
                      **({"error": error} if error else {})},
            session_id=None, text=claim, is_error=bool(error))
    except Exception as exc:  # noqa: BLE001 — 记录失败不影响已完成的流
        import structlog

        structlog.get_logger().debug(
            "memory.capture_backend_agent_result_failed", error=str(exc))


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
