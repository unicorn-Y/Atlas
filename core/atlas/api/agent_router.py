"""REST surface for persistent agents (``/api/agents/*``).

Contract: integration-map §5 — list/create/get/patch/delete, heartbeat config,
session lineage placeholder, plus status projection and channel bindings.
The service singleton is module-level; server wiring (``app.state``) happens
during integration via :func:`set_agent_service`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from atlas.origin_guard import TOKEN_HEADER, is_trusted
from atlas.persistent_agents import PersistentAgentService
from atlas.persistent_agents.store import BUILTIN_ROLE_IDS

T = TypeVar("T")

_service: PersistentAgentService | None = None


def _require_trusted_origin(request: Request) -> None:
    """Mirror of the app-level OriginGuard rule for standalone mounts."""
    trusted = is_trusted(
        request.headers.get("origin"),
        request.headers.get(TOKEN_HEADER),
        fetch_site=request.headers.get("sec-fetch-site"),
    )
    if not trusted:
        raise HTTPException(status_code=403, detail="Requests from this origin are not allowed")


router = APIRouter(
    prefix="/api/agents", tags=["agents"], dependencies=[Depends(_require_trusted_origin)],
)


def get_agent_service() -> PersistentAgentService:
    global _service
    if _service is None:
        _service = PersistentAgentService()
    return _service


def set_agent_service(service: PersistentAgentService | None) -> None:
    """Swap the singleton (app.state injection at integration; test isolation)."""
    global _service
    _service = service


def _call(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _with_status(service: PersistentAgentService, record: dict[str, Any]) -> dict[str, Any]:
    if record.get("kind") != "persistent":
        return record
    return {**record, "status": service.get_status(record["id"])["status"]}


@router.get("")
async def list_agents(include_roles: bool = Query(default=False)) -> dict[str, Any]:
    service = get_agent_service()
    agents = [
        _with_status(service, record) for record in service.list_agents(include_roles=include_roles)
    ]
    return {"agents": agents}


@router.post("", status_code=201)
async def create_agent(req: dict[str, Any]) -> dict[str, Any]:
    return _call(lambda: get_agent_service().create(req))


@router.get("/{agent_id}")
async def get_agent(agent_id: str) -> dict[str, Any]:
    service = get_agent_service()
    record = _call(lambda: service.get(agent_id))
    if record is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")
    return _with_status(service, record)


@router.patch("/{agent_id}")
async def patch_agent(agent_id: str, req: dict[str, Any]) -> dict[str, Any]:
    return _call(lambda: get_agent_service().update(agent_id, req))


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str) -> dict[str, str]:
    if agent_id in BUILTIN_ROLE_IDS:
        raise HTTPException(status_code=409, detail="Built-in profiles cannot be deleted")
    _call(lambda: get_agent_service().delete(agent_id))
    return {"status": "deleted"}


@router.put("/{agent_id}/heartbeat")
async def put_heartbeat(agent_id: str, req: dict[str, Any]) -> dict[str, Any]:
    record = _call(lambda: get_agent_service().set_heartbeat(agent_id, req))
    return {"agent_id": agent_id, "heartbeat": record["agent"]["heartbeat"]}


@router.get("/{agent_id}/sessions")
async def list_agent_sessions(agent_id: str) -> dict[str, Any]:
    _call(lambda: get_agent_service().get_status(agent_id))  # 404 unless persistent agent
    return {"agent_id": agent_id, "sessions": [], "note": "wired by integration"}


@router.get("/{agent_id}/status")
async def get_agent_status(agent_id: str) -> dict[str, Any]:
    return _call(lambda: get_agent_service().get_status(agent_id))


@router.put("/{agent_id}/status")
async def put_agent_status(agent_id: str, req: dict[str, Any]) -> dict[str, Any]:
    status = req.get("status", "")
    error = req.get("error")
    record = _call(lambda: get_agent_service().set_status(agent_id, str(status), error))
    return {"agent_id": agent_id, "status": record["agent"]["last_status"]}


@router.get("/{agent_id}/channels")
async def list_agent_channels(agent_id: str) -> dict[str, Any]:
    channels = _call(lambda: get_agent_service().list_channels(agent_id))
    return {"agent_id": agent_id, "channels": channels}


@router.post("/{agent_id}/channels", status_code=201)
async def add_agent_channel(agent_id: str, req: dict[str, Any]) -> dict[str, Any]:
    channels = _call(lambda: get_agent_service().add_channel(
        agent_id,
        str(req.get("channel", "")),
        str(req.get("target", "")),
        str(req.get("account", "")),
    ))
    return {"agent_id": agent_id, "channels": channels}


@router.delete("/{agent_id}/channels")
async def remove_agent_channel(
    agent_id: str,
    channel: str = Query(...),
    target: str = Query(...),
    account: str | None = Query(default=None),
) -> dict[str, Any]:
    channels = _call(lambda: get_agent_service().remove_channel(agent_id, channel, target, account))
    return {"agent_id": agent_id, "channels": channels}


__all__ = ["get_agent_service", "router", "set_agent_service"]
