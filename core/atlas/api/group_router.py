"""REST surface for group chats (``/api/groups/*``).

Contract: integration-map §5 — group CRUD, ``/{id}/members``, a paginated
``/{id}/timeline``, ``/{id}/stop`` (epoch bump) and ``/{id}/turns`` (manual
drive). The service and orchestrator singletons are module-level; server wiring
happens during integration via :func:`set_group_service` (binds
:class:`atlas.persistent_agents.PersistentAgentService` as the member lookup)
followed by :func:`set_group_orchestrator` (binds the real turn dispatcher).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from atlas.config import get_config
from atlas.groups import DispatcherNotBound, GroupOrchestrator, TurnConflict
from atlas.groups.store import GroupService, GroupStore
from atlas.origin_guard import TOKEN_HEADER, is_trusted
from atlas.persistent_agents import PersistentAgentService

T = TypeVar("T")

_service: GroupService | None = None
_orchestrator: GroupOrchestrator | None = None


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
    prefix="/api/groups", tags=["groups"], dependencies=[Depends(_require_trusted_origin)],
)


def get_group_service() -> GroupService:
    global _service
    if _service is None:
        _service = GroupService(
            GroupStore(get_config().db_path.parent), lookup=PersistentAgentService(),
        )
    return _service


def set_group_service(service: GroupService | None) -> None:
    """Swap the service singleton; resets a lazily-resolved orchestrator.

    Bind order: service first, orchestrator second (integration sets both).
    """
    global _service, _orchestrator
    _service = service
    _orchestrator = None


def get_group_orchestrator() -> GroupOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = GroupOrchestrator(get_group_service())
    return _orchestrator


def set_group_orchestrator(orchestrator: GroupOrchestrator | None) -> None:
    """Swap the orchestrator singleton (real dispatcher at integration; tests)."""
    global _orchestrator
    _orchestrator = orchestrator


def _call(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# -- group CRUD ---------------------------------------------------------------


@router.get("")
async def list_groups() -> dict[str, Any]:
    return {"groups": get_group_service().list_groups()}


@router.post("", status_code=201)
async def create_group(req: dict[str, Any]) -> dict[str, Any]:
    return _call(lambda: get_group_service().create(req))


@router.get("/{group_id}")
async def get_group(group_id: str) -> dict[str, Any]:
    record = _call(lambda: get_group_service().get(group_id))
    if record is None:
        raise HTTPException(status_code=404, detail=f"group not found: {group_id}")
    return record


@router.patch("/{group_id}")
async def patch_group(group_id: str, req: dict[str, Any]) -> dict[str, Any]:
    return _call(lambda: get_group_service().update(group_id, req))


@router.delete("/{group_id}")
async def delete_group(group_id: str) -> dict[str, str]:
    _call(lambda: get_group_service().delete(group_id))
    return {"status": "deleted"}


# -- members ------------------------------------------------------------------


@router.get("/{group_id}/members")
async def list_members(group_id: str) -> dict[str, Any]:
    service = get_group_service()
    group = _call(lambda: service.get(group_id))
    if group is None:
        raise HTTPException(status_code=404, detail=f"group not found: {group_id}")
    lookup = service.lookup
    agents = []
    for agent_id in group["member_agent_ids"]:
        record = lookup.get(agent_id) if lookup is not None else None
        agents.append({
            "id": agent_id,
            "name": (record or {}).get("name") or agent_id,
            "kind": (record or {}).get("kind"),
            "resolved": record is not None,
        })
    return {
        "group_id": group_id,
        "members": group["member_agent_ids"],
        "agents": agents,
        "round_caps": group["round_caps"],
    }


@router.post("/{group_id}/members", status_code=201)
async def add_member(group_id: str, req: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(req.get("agent_id", ""))
    members = _call(lambda: get_group_service().add_member(group_id, agent_id))
    return {"group_id": group_id, "members": members}


@router.delete("/{group_id}/members")
async def remove_member(
    group_id: str, agent_id: str = Query(...),
) -> dict[str, Any]:
    members = _call(lambda: get_group_service().remove_member(group_id, agent_id))
    return {"group_id": group_id, "members": members}


# -- room log / runtime --------------------------------------------------------


@router.get("/{group_id}/timeline")
async def get_timeline(
    group_id: str,
    thread_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    before_seq: int | None = Query(default=None),
) -> dict[str, Any]:
    return _call(lambda: get_group_orchestrator().timeline(
        group_id, thread_id=thread_id, limit=limit, before_seq=before_seq,
    ))


@router.post("/{group_id}/stop")
async def stop_group(group_id: str, req: dict[str, Any] | None = None) -> dict[str, Any]:
    body = req or {}
    return _call(lambda: get_group_orchestrator().stop(group_id, body.get("thread_id")))


@router.post("/{group_id}/turns")
async def run_turn(group_id: str, req: dict[str, Any]) -> dict[str, Any]:
    orchestrator = get_group_orchestrator()
    try:
        report = await orchestrator.run_turn(group_id, req)
    except DispatcherNotBound as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TurnConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return report.to_dict()


__all__ = [
    "get_group_orchestrator",
    "get_group_service",
    "router",
    "set_group_orchestrator",
    "set_group_service",
]
