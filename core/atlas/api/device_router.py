"""REST surface for the device registry and desktop takeover (``/api/devices/*``).

W5 of ATLAS-MEGA-PERSISTENT-ALWAYS-ON.  Endpoints:

- ``GET    /api/devices``                 — list devices (``online`` is a projection)
- ``POST   /api/devices``                 — register an ingress device (host/phone)
- ``GET    /api/devices/{id}``            — one device (404 when unknown)
- ``PATCH  /api/devices/{id}``            — display_name/os/notes/trusted/capabilities
- ``DELETE /api/devices/{id}``            — remove an ingress row (self → 409)
- ``PUT    /api/devices/{id}/presence``   — presence beat {activity?, last_seen?}
- ``GET    /api/devices/takeover``        — control state snapshot (FREE/HUMAN/AGENT)
- ``POST   /api/devices/takeover``        — {action: human_take|agent_take|release, agent_id?, note?}
- ``GET    /api/devices/activity``        — takeover activity ring buffer (newest last)
- ``GET    /api/devices/handoff``         — handoff cards
- ``POST   /api/devices/handoff``         — {action: open|done|give_up, card_id?, note?, actor?, run_id?}

CLOSEOUT-6: a handoff card opened with a non-empty ``run_id`` is linked to a
blocked X2 run (``atlas.tools.x2.pending``); resolving the card ``done`` wakes
that run's waiters with ``"done"``, ``give_up`` cancels the run (waiters
receive ``GIVE_UP``).  The bridge is lazily imported and failure-isolated —
a pending-side error can never turn an already-settled card into a 500.

Static segments (``takeover``/``activity``/``handoff``) are declared before the
``{device_id}`` routes so they never resolve as a device id.

OriginGuard: the whole ``atlas.server`` app sits behind ``atlas.origin_guard``.
The ``_require_trusted_origin`` dependency re-applies the same rule so the
router stays safe when mounted standalone (tests, tooling).

Integration note for the owner of ``atlas/server.py``::

    app.include_router(device_router)
    # First ``get_registry()`` call self-registers the atlas-laptop; the
    # integration owner may instead inject explicit instances at startup via
    # ``set_registry(...)`` / ``set_takeover(...)``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from atlas.devices import SELF_DEVICE_ID, DeviceError, DeviceRegistry
from atlas.devices.takeover import (
    AGENT,
    HUMAN,
    RESOLUTION_DONE,
    RESOLUTION_GIVE_UP,
    HUMAN_ACTOR,
    ObservationRequiredError,
    TakeoverError,
    TakeoverStateMachine,
    is_human_actor,
)
from atlas.origin_guard import TOKEN_HEADER, is_trusted

router = APIRouter(prefix="/api/devices", tags=["devices"])

logger = logging.getLogger("atlas.device_router")

# Injectable singletons (tests install tmp_path-isolated instances; production
# lazily builds the default registry and self-registers the local laptop).
_registry: DeviceRegistry | None = None
_takeover: TakeoverStateMachine | None = None


def set_registry(registry: DeviceRegistry | None) -> None:
    """Override the registry singleton (``None`` restores the lazy default)."""
    global _registry
    _registry = registry


def set_takeover(machine: TakeoverStateMachine | None) -> None:
    """Override the takeover state machine (``None`` restores the lazy default)."""
    global _takeover
    _takeover = machine


def get_registry() -> DeviceRegistry:
    global _registry
    if _registry is None:
        _registry = DeviceRegistry()
        _registry.register_self()  # idempotent built-in laptop row
    return _registry


def get_takeover() -> TakeoverStateMachine:
    global _takeover
    if _takeover is None:
        _takeover = TakeoverStateMachine(device_id=SELF_DEVICE_ID)
    return _takeover


def _require_trusted_origin(request: Request) -> None:
    """Mirror of the app-level OriginGuard rule for standalone mounts."""
    trusted = is_trusted(
        request.headers.get("origin"),
        request.headers.get(TOKEN_HEADER),
        fetch_site=request.headers.get("sec-fetch-site"),
    )
    if not trusted:
        raise HTTPException(status_code=403, detail="Requests from this origin are not allowed")


def _device_error(exc: DeviceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _takeover_error(exc: TakeoverError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


# ---------------------------------------------------------------------------
# Devices CRUD
# ---------------------------------------------------------------------------
@router.get("")
async def list_devices() -> dict[str, Any]:
    registry = await asyncio.to_thread(get_registry)
    devices = await asyncio.to_thread(registry.list_devices)
    return {"devices": devices, "self": SELF_DEVICE_ID}


class IngressRegistration(BaseModel):
    device_id: str
    display_name: str
    kind: str = "ingress"
    os: str = ""
    notes: str = ""
    capabilities: dict[str, Any] | None = None
    trusted: bool = False


@router.post("", dependencies=[Depends(_require_trusted_origin)])
async def register_device(req: IngressRegistration) -> dict[str, Any]:
    registry = await asyncio.to_thread(get_registry)
    try:
        device = await asyncio.to_thread(
            registry.add, req.device_id, req.display_name,
            kind=req.kind, os=req.os, notes=req.notes,
            capabilities=req.capabilities, trusted=req.trusted)
    except DeviceError as exc:
        raise _device_error(exc) from exc
    return device


@router.get("/takeover")
async def takeover_state() -> dict[str, Any]:
    return get_takeover().snapshot()


class TakeoverRequest(BaseModel):
    action: str  # human_take | agent_take | release
    agent_id: str | None = None
    note: str = ""


@router.post("/takeover", dependencies=[Depends(_require_trusted_origin)])
async def takeover_action(req: TakeoverRequest) -> dict[str, Any]:
    machine = get_takeover()
    if req.action == "human_take":
        actor: str = HUMAN_ACTOR
    elif req.action == "agent_take":
        actor = (req.agent_id or "").strip()
        if not actor or is_human_actor(actor):
            raise HTTPException(status_code=422, detail="agent_take 需要 agent_id（且不能是 user）")
    elif req.action == "release":
        state = machine.state
        if state == AGENT:
            actor = (req.agent_id or "").strip()
            if not actor or is_human_actor(actor):
                raise HTTPException(status_code=422,
                                    detail="释放 agent 控制权需要 agent_id（且不能是 user）")
        else:
            actor = HUMAN_ACTOR
    else:
        raise HTTPException(status_code=422,
                            detail="action 必须是 human_take / agent_take / release")
    try:
        snapshot = await asyncio.to_thread(
            machine.request if req.action != "release" else machine.release,
            actor, note=req.note)
    except ObservationRequiredError as exc:  # defensive: takeover itself never acts
        raise _takeover_error(exc) from exc
    except TakeoverError as exc:
        raise _takeover_error(exc) from exc
    return {"action": req.action, "granted": True, **snapshot}


@router.get("/activity")
async def activity_feed(limit: int = 0) -> dict[str, Any]:
    if limit < 0:
        raise HTTPException(status_code=422, detail="limit 不能为负")
    events = await asyncio.to_thread(get_takeover().activity, limit or None)
    return {"activity": events}


@router.get("/handoff")
async def list_handoff(status: str | None = None) -> dict[str, Any]:
    cards = await asyncio.to_thread(get_takeover().handoff_cards, status)
    return {"cards": cards}


class HandoffRequest(BaseModel):
    action: str  # open | done | give_up
    card_id: str | None = None
    note: str = ""
    actor: str = HUMAN_ACTOR
    run_id: str | None = None  # links the card to a blocked X2 run (CLOSEOUT-6)


def _bridge_x2_pending(resolution: str, card: dict[str, Any]) -> None:
    """Wake the blocked X2 run a settled handoff card was opened for.

    ``done`` → ``x2_pending.resolve(run_id, "done")``; ``give_up`` →
    ``x2_pending.cancel_run(run_id)`` (waiters receive ``GIVE_UP``).  Lazy
    import keeps the router light and cycle-free; any pending-side failure is
    logged and swallowed — the card is already settled and must still 200.
    """
    run_id = str(card.get("run_id") or "")
    if not run_id:
        return  # plain card: X2 is never touched
    try:
        from atlas.tools.x2 import pending as x2_pending

        if resolution == RESOLUTION_DONE:
            delivered = x2_pending.resolve(run_id, RESOLUTION_DONE)
        else:
            x2_pending.cancel_run(run_id)
            delivered = True
        logger.info("交接卡片 %s → x2 run %s（%s，delivered=%s）",
                    card.get("card_id"), run_id, resolution, delivered)
    except Exception:
        logger.exception("x2 pending 桥接失败（卡片 %s 已结算，不影响响应）: run=%s",
                         card.get("card_id"), run_id)


@router.post("/handoff", dependencies=[Depends(_require_trusted_origin)])
async def handoff_action(req: HandoffRequest) -> dict[str, Any]:
    machine = get_takeover()
    if req.action == "open":
        return await asyncio.to_thread(
            machine.open_handoff, req.note, actor=req.actor, run_id=req.run_id or "")
    if req.action in (RESOLUTION_DONE, RESOLUTION_GIVE_UP):
        if not (req.card_id or "").strip():
            raise HTTPException(status_code=422, detail=f"{req.action} 需要 card_id")
        try:
            card = await asyncio.to_thread(
                machine.resolve_handoff, req.card_id.strip(), req.action, actor=req.actor)
        except TakeoverError as exc:
            raise _takeover_error(exc) from exc
        _bridge_x2_pending(req.action, card)  # quick in-memory call, no to_thread
        return card
    raise HTTPException(status_code=422, detail="action 必须是 open / done / give_up")


@router.get("/{device_id}")
async def get_device(device_id: str) -> dict[str, Any]:
    registry = await asyncio.to_thread(get_registry)
    device = await asyncio.to_thread(registry.get, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"没有 id 为 {device_id!r} 的设备")
    return device


class DevicePatch(BaseModel):
    display_name: str | None = None
    os: str | None = None
    notes: str | None = None
    trusted: bool | None = None
    capabilities: dict[str, Any] | None = None


@router.patch("/{device_id}", dependencies=[Depends(_require_trusted_origin)])
async def patch_device(device_id: str, req: DevicePatch) -> dict[str, Any]:
    registry = await asyncio.to_thread(get_registry)
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        return await asyncio.to_thread(registry.update, device_id, **fields)
    except DeviceError as exc:
        raise _device_error(exc) from exc


class PresenceBeat(BaseModel):
    activity: str | None = None
    last_seen: float | None = Field(default=None, ge=0)


@router.put("/{device_id}/presence", dependencies=[Depends(_require_trusted_origin)])
async def put_presence(device_id: str, req: PresenceBeat) -> dict[str, Any]:
    registry = await asyncio.to_thread(get_registry)
    try:
        return await asyncio.to_thread(
            registry.set_presence, device_id,
            activity=req.activity, last_seen=req.last_seen)
    except DeviceError as exc:
        raise _device_error(exc) from exc


@router.delete("/{device_id}", dependencies=[Depends(_require_trusted_origin)])
async def delete_device(device_id: str) -> dict[str, Any]:
    registry = await asyncio.to_thread(get_registry)
    try:
        await asyncio.to_thread(registry.remove, device_id)
    except DeviceError as exc:
        raise _device_error(exc) from exc
    return {"status": "ok", "device_id": device_id}


__all__ = ["get_registry", "get_takeover", "router", "set_registry", "set_takeover"]
