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
import json
import logging
import re
import secrets
import threading
import time
from typing import Annotated, Any
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import HTMLResponse, StreamingResponse

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.devices import SELF_DEVICE_ID, DeviceError, DeviceRegistry
from atlas.devices.takeover import (
    AGENT,
    RESOLUTION_DONE,
    RESOLUTION_GIVE_UP,
    HUMAN_ACTOR,
    ObservationRequiredError,
    TakeoverError,
    TakeoverStateMachine,
    is_human_actor,
)
from atlas.devices.file_transfers import FileTransferStore, MAX_CHUNK_BYTES
from atlas.devices.pairing import PairingStore
from atlas.origin_guard import TOKEN_HEADER, is_trusted

router = APIRouter(prefix="/api/devices", tags=["devices"])

logger = logging.getLogger("atlas.device_router")

# Injectable singletons (tests install tmp_path-isolated instances; production
# lazily builds the default registry and self-registers the local laptop).
_registry: DeviceRegistry | None = None
_takeover: TakeoverStateMachine | None = None
_node_capability_lock = threading.RLock()
_NODE_CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_transfer_stores: dict[str, FileTransferStore] = {}
_transfer_store_lock = threading.Lock()
_pairing_stores: dict[str, PairingStore] = {}


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


def _registry_for(services: AppServices) -> DeviceRegistry:
    registry = services.device_registry
    if registry is None:
        raise RuntimeError("FastAPI app is missing its device registry")
    return registry


def _transfer_store(registry: DeviceRegistry) -> FileTransferStore:
    key = str(registry.path.resolve())
    with _transfer_store_lock:
        store = _transfer_stores.get(key)
        if store is None:
            store = FileTransferStore(registry.path.parent / "device-file-transfers")
            _transfer_stores[key] = store
        return store


def _pairing_store(registry: DeviceRegistry) -> PairingStore:
    key = str(registry.path.resolve())
    with _transfer_store_lock:
        store = _pairing_stores.get(key)
        if store is None:
            store = PairingStore(registry.path.parent / "device-pairing.sqlite")
            _pairing_stores[key] = store
        return store


def _require_transfer_access(request: Request, store: FileTransferStore, device_id: str) -> None:
    """Accept the local trusted UI or the one-time bearer bound to this device."""
    if is_trusted(request.headers.get("origin"), request.headers.get(TOKEN_HEADER),
                  fetch_site=request.headers.get("sec-fetch-site"),
                  client_host=request.client.host if request.client else None):
        return
    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not store.verify_credential(device_id, token):
        raise HTTPException(status_code=403, detail="设备传输凭据无效")


def _require_transfer_capability(registry: DeviceRegistry, device_id: str, capability: str) -> dict[str, Any]:
    device = registry.get(device_id, project=False)
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    if not device.get("trusted"):
        raise HTTPException(status_code=403, detail="设备尚未标记为可信配对设备")
    if device_id == SELF_DEVICE_ID:
        return device
    state = _node_capability_snapshot(registry, device_id)
    if capability not in state["approved"]:
        raise HTTPException(status_code=403, detail=f"设备尚未批准能力：{capability}")
    return device


def _takeover_for(services: AppServices) -> TakeoverStateMachine:
    machine = services.takeover
    if machine is None:
        raise RuntimeError("FastAPI app is missing its takeover state machine")
    return machine


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


def _node_state_path(registry: DeviceRegistry):
    """Keep node enrollment metadata beside, not inside, the legacy device store."""
    return registry.path.with_name(f"{registry.path.stem}.node-capabilities.json")


def _empty_node_capability_state(device: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_id": str(device.get("device_id") or ""),
        "declared": [],
        "pending": [],
        "approved": [],
        "revoked": [],
        "updated_at": None,
        "generation": int(device.get("generation") or 1),
        "execution_available": False,
    }


def _read_node_capability_store(registry: DeviceRegistry) -> dict[str, Any]:
    path = _node_state_path(registry)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": 1, "devices": {}}
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="节点能力状态文件不可读") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("devices"), dict):
        raise HTTPException(status_code=503, detail="节点能力状态文件格式无效")
    return value


def _write_node_capability_store(registry: DeviceRegistry, store: dict[str, Any]) -> None:
    path = _node_state_path(registry)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _node_entry_state(entry: Any, device: dict[str, Any]) -> dict[str, Any]:
    """Project only metadata belonging to this specific device registration."""
    empty = _empty_node_capability_state(device)
    if not isinstance(entry, dict) or entry.get("device_created_at") != device.get("created_at"):
        return empty
    declared = sorted({item for item in entry.get("declared", []) if isinstance(item, str)})
    revoked = sorted({item for item in entry.get("revoked", []) if item in declared})
    approved = sorted({item for item in entry.get("approved", []) if item in declared and item not in revoked})
    pending = sorted(set(declared) - set(approved) - set(revoked))
    return {
        **empty,
        "declared": declared,
        "pending": pending,
        "approved": approved,
        "revoked": revoked,
        "updated_at": entry.get("updated_at"),
    }


def _require_node_device(registry: DeviceRegistry, device_id: str, *, mutable: bool) -> dict[str, Any]:
    device = registry.get(device_id, project=False)
    if device is None:
        raise HTTPException(status_code=404, detail=f"没有 id 为 {device_id!r} 的设备")
    if mutable and (device_id == SELF_DEVICE_ID or device.get("kind") == "atlas-laptop"):
        raise HTTPException(status_code=409, detail="本机能力由 Atlas 本地注册，不接受远程节点审批")
    return device


def _validated_capability_names(values: list[str]) -> list[str]:
    if len(values) > 64:
        raise HTTPException(status_code=422, detail="最多声明 64 项节点能力")
    normalized: set[str] = set()
    for value in values:
        name = value.strip().lower()
        if not _NODE_CAPABILITY_ID.fullmatch(name):
            raise HTTPException(status_code=422, detail=f"无效的能力标识：{value!r}")
        normalized.add(name)
    return sorted(normalized)


def _node_capability_snapshot(registry: DeviceRegistry, device_id: str) -> dict[str, Any]:
    with _node_capability_lock:
        device = _require_node_device(registry, device_id, mutable=False)
        store = _read_node_capability_store(registry)
        return _node_entry_state(store["devices"].get(device_id), device)


def _save_node_capability_entry(
    registry: DeviceRegistry, device: dict[str, Any], state: dict[str, Any],
) -> dict[str, Any]:
    store = _read_node_capability_store(registry)
    entry = {
        "device_created_at": device.get("created_at"),
        "declared": state["declared"],
        "approved": state["approved"],
        "revoked": state["revoked"],
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    store["devices"][str(device["device_id"])] = entry
    _write_node_capability_store(registry, store)
    return _node_entry_state(entry, device)


class NodeCapabilityDeclaration(BaseModel):
    capabilities: list[str] = Field(default_factory=list, max_length=64)


class FileTransferRequest(BaseModel):
    source_device_id: str = Field(min_length=1, max_length=64)
    target_device_id: str = Field(min_length=1, max_length=64)
    filename: str = Field(min_length=1, max_length=512)
    size: int = Field(gt=0, le=100 * 1024 * 1024)
    sha256: str = Field(min_length=64, max_length=64)


@router.post("/{device_id}/file-transfer-credential", dependencies=[Depends(_require_trusted_origin)])
async def issue_file_transfer_credential(device_id: str,
                                         services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    """Rotate a paired device's transfer bearer; plaintext is returned only once."""
    registry = _registry_for(services)
    device = _require_node_device(registry, device_id, mutable=False)
    if not device.get("trusted"):
        raise HTTPException(status_code=403, detail="先将配对设备标记为可信")
    token = await asyncio.to_thread(_transfer_store(registry).issue_credential, device_id)
    logger.info("device.file_transfer_credential_rotated", device_id=device_id)
    return {"device_id": device_id, "token": token, "stored_as": "sha256"}


@router.get("/file-transfers")
async def list_file_transfers(services: Annotated[AppServices, Depends(get_app_services)],
                              request: Request,
                              device_id: str = Query(min_length=1, max_length=64)) -> dict[str, Any]:
    registry = _registry_for(services)
    store = _transfer_store(registry)
    _require_transfer_access(request, store, device_id)
    device = registry.get(device_id, project=False)
    if device is None or not device.get("trusted"):
        raise HTTPException(status_code=403, detail="仅可信配对设备可查看传输")
    if device_id != SELF_DEVICE_ID:
        state = _node_capability_snapshot(registry, device_id)
        if not ({"files.receive", "files.send"} & set(state["approved"])):
            raise HTTPException(status_code=403, detail="设备尚未批准文件传输能力")
    rows = await asyncio.to_thread(store.list, device_id)
    for row in rows:
        row["events"] = await asyncio.to_thread(store.events, row["id"])
    return {"transfers": rows}


@router.post("/file-transfers")
async def create_file_transfer(req: FileTransferRequest,
                               request: Request,
                               services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    registry = _registry_for(services)
    store = _transfer_store(registry)
    _require_transfer_access(request, store, req.source_device_id)
    _require_transfer_capability(registry, req.source_device_id, "files.send")
    _require_transfer_capability(registry, req.target_device_id, "files.receive")
    try:
        row = await asyncio.to_thread(store.create, req.source_device_id, req.target_device_id,
                                      req.filename, req.size, req.sha256)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"transfer": row}


@router.post("/file-transfers/{transfer_id}/accept")
async def accept_file_transfer(transfer_id: str, request: Request,
                               services: Annotated[AppServices, Depends(get_app_services)],
                               device_id: str = Query(min_length=1, max_length=64)) -> dict[str, Any]:
    registry = _registry_for(services)
    store = _transfer_store(registry)
    _require_transfer_access(request, store, device_id)
    _require_transfer_capability(registry, device_id, "files.receive")
    try:
        row = await asyncio.to_thread(store.accept, transfer_id, device_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409 if isinstance(exc, ValueError) else 403, detail=str(exc)) from exc
    return {"transfer": row}


@router.put("/file-transfers/{transfer_id}/chunks/{offset}")
async def upload_file_chunk(transfer_id: str, offset: int, request: Request,
                            services: Annotated[AppServices, Depends(get_app_services)],
                            device_id: str = Query(min_length=1, max_length=64)) -> dict[str, Any]:
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset cannot be negative")
    data = bytearray()
    async for block in request.stream():
        if len(data) + len(block) > MAX_CHUNK_BYTES:
            raise HTTPException(status_code=413, detail=f"chunk exceeds {MAX_CHUNK_BYTES} bytes")
        data.extend(block)
    registry = _registry_for(services)
    store = _transfer_store(registry)
    _require_transfer_access(request, store, device_id)
    _require_transfer_capability(registry, device_id, "files.send")
    try:
        row = await asyncio.to_thread(store.append_chunk, transfer_id, device_id, offset, bytes(data))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"transfer": row, "progress": row["received_size"] / row["expected_size"]}


@router.get("/file-transfers/{transfer_id}/download")
async def download_file_transfer(transfer_id: str, services: Annotated[AppServices, Depends(get_app_services)],
                                request: Request,
                                device_id: str = Query(min_length=1, max_length=64)):
    registry = _registry_for(services)
    store = _transfer_store(registry)
    _require_transfer_access(request, store, device_id)
    _require_transfer_capability(registry, device_id, "files.receive")
    try:
        row, path = await asyncio.to_thread(store.payload_path, transfer_id, device_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc

    async def payload():
        with path.open("rb") as stream:
            while data := await asyncio.to_thread(stream.read, 64 * 1024):
                yield data
        await asyncio.to_thread(store.complete, transfer_id, device_id)

    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(row['filename'])}",
               "X-Content-SHA256": row["actual_sha256"]}
    return StreamingResponse(payload(), media_type="application/octet-stream",
                             headers=headers, background=None)


@router.post("/file-transfers/{transfer_id}/cancel")
async def cancel_file_transfer(transfer_id: str, services: Annotated[AppServices, Depends(get_app_services)],
                               request: Request,
                               device_id: str = Query(min_length=1, max_length=64)) -> dict[str, Any]:
    registry = _registry_for(services)
    store = _transfer_store(registry)
    _require_transfer_access(request, store, device_id)
    device = registry.get(device_id, project=False)
    if device is None or not device.get("trusted"):
        raise HTTPException(status_code=403, detail="仅可信配对设备可取消传输")
    if device_id != SELF_DEVICE_ID:
        capabilities = set(_node_capability_snapshot(registry, device_id)["approved"])
        if not capabilities.intersection({"files.receive", "files.send"}):
            raise HTTPException(status_code=403, detail="设备尚未批准文件传输能力")
    try:
        row = await asyncio.to_thread(store.cancel, transfer_id, device_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"transfer": row}


@router.get("/{device_id}/node-capabilities")
async def node_capability_state(
    device_id: str, services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    return await asyncio.to_thread(_node_capability_snapshot, _registry_for(services), device_id)


@router.put("/{device_id}/node-capabilities", dependencies=[Depends(_require_trusted_origin)])
async def declare_node_capabilities(
    device_id: str, req: NodeCapabilityDeclaration,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    registry = _registry_for(services)
    names = _validated_capability_names(req.capabilities)

    def update() -> dict[str, Any]:
        with _node_capability_lock:
            device = _require_node_device(registry, device_id, mutable=True)
            store = _read_node_capability_store(registry)
            previous = _node_entry_state(store["devices"].get(device_id), device)
            declared = names
            approved = sorted(set(previous["approved"]) & set(declared))
            revoked = sorted(set(previous["revoked"]) & set(declared))
            state = {
                **previous,
                "declared": declared,
                "approved": approved,
                "revoked": revoked,
                "pending": sorted(set(declared) - set(approved) - set(revoked)),
            }
            if set(previous["approved"]) - set(approved):
                try:
                    registry.bump_generation(device_id, reason="node capability declaration removed approved capability")
                except DeviceError as exc:
                    raise _device_error(exc) from exc
                device = _require_node_device(registry, device_id, mutable=True)
            return _save_node_capability_entry(registry, device, state)

    return await asyncio.to_thread(update)


@router.post("/{device_id}/node-capabilities/{capability}/approve", dependencies=[Depends(_require_trusted_origin)])
async def approve_node_capability(
    device_id: str, capability: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    registry = _registry_for(services)
    name = _validated_capability_names([capability])[0]

    def approve() -> dict[str, Any]:
        with _node_capability_lock:
            device = _require_node_device(registry, device_id, mutable=True)
            store = _read_node_capability_store(registry)
            state = _node_entry_state(store["devices"].get(device_id), device)
            if name not in state["declared"]:
                raise HTTPException(status_code=404, detail="该能力未由节点声明")
            if name in state["approved"]:
                return state
            state["approved"] = sorted(set(state["approved"]) | {name})
            state["pending"] = sorted(set(state["pending"]) - {name})
            state["revoked"] = sorted(set(state["revoked"]) - {name})
            try:
                registry.bump_generation(device_id, reason=f"node capability approved: {name}")
            except DeviceError as exc:
                raise _device_error(exc) from exc
            device = _require_node_device(registry, device_id, mutable=True)
            return _save_node_capability_entry(registry, device, state)

    return await asyncio.to_thread(approve)


@router.delete("/{device_id}/node-capabilities/{capability}", dependencies=[Depends(_require_trusted_origin)])
async def revoke_node_capability(
    device_id: str, capability: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    registry = _registry_for(services)
    name = _validated_capability_names([capability])[0]

    def revoke() -> dict[str, Any]:
        with _node_capability_lock:
            device = _require_node_device(registry, device_id, mutable=True)
            store = _read_node_capability_store(registry)
            state = _node_entry_state(store["devices"].get(device_id), device)
            if name not in state["declared"]:
                raise HTTPException(status_code=404, detail="该能力未由节点声明")
            was_approved = name in state["approved"]
            state["approved"] = sorted(set(state["approved"]) - {name})
            state["pending"] = sorted(set(state["pending"]) - {name})
            state["revoked"] = sorted(set(state["revoked"]) | {name})
            if was_approved:
                try:
                    registry.bump_generation(device_id, reason=f"node capability revoked: {name}")
                except DeviceError as exc:
                    raise _device_error(exc) from exc
                device = _require_node_device(registry, device_id, mutable=True)
            return _save_node_capability_entry(registry, device, state)

    return await asyncio.to_thread(revoke)


def _takeover_error(exc: TakeoverError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


# ---------------------------------------------------------------------------
# Device / DM pairing and authenticated command delivery
# ---------------------------------------------------------------------------
class PairingChallengeRequest(BaseModel):
    ttl_seconds: int = Field(default=120, ge=30, le=600)
    api_base_url: str = Field(default="", max_length=300)


class DeviceClaimRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=8, max_length=8)
    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    display_name: str = Field(min_length=1, max_length=120)
    os: str = Field(default="", max_length=120)


class PairingDecision(BaseModel):
    action: str


class DeviceCommandRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)


class DeviceCommandResult(BaseModel):
    result: str = Field(max_length=12000)


def _bearer(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    return authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""


def _require_paired_device(request: Request, pairing: PairingStore, device_id: str) -> None:
    if not pairing.verify_credential(device_id, _bearer(request)):
        raise HTTPException(status_code=403, detail="设备配对凭据无效或已撤销")


@router.post("/pairing/challenge", dependencies=[Depends(_require_trusted_origin)])
async def create_pairing_challenge(
    req: PairingChallengeRequest,
    request: Request,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    registry = _registry_for(services)
    api_base = req.api_base_url.strip().rstrip("/") or str(request.base_url).rstrip("/")
    parsed = urlparse(api_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="设备可访问的 Atlas 地址必须是有效的 HTTP(S) URL")
    store = _pairing_store(registry)
    challenge = await asyncio.to_thread(store.create_device_challenge, req.ttl_seconds)
    enrollment_url = f"{api_base}/api/devices/pairing/enroll?challenge_id={quote(challenge['challenge_id'])}#code={quote(challenge['code'])}"
    return {**challenge, "qr_payload": enrollment_url}


@router.get("/pairing/enroll", response_class=HTMLResponse)
async def pairing_enrollment_page(challenge_id: str = Query(min_length=32, max_length=32)) -> HTMLResponse:
    if not re.fullmatch(r"[0-9a-f]{32}", challenge_id):
        raise HTTPException(status_code=404, detail="配对挑战不存在")
    page = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>Atlas 设备配对</title><style>
*{box-sizing:border-box}body{margin:0;background:#10141d;color:#edf1f7;font:16px system-ui,sans-serif}main{max-width:620px;margin:6vh auto;padding:24px}section{background:#1a202c;border:1px solid #353d4a;border-radius:18px;padding:24px}h1{font-size:22px;margin:0 0 8px}p{color:#b4bdcb;line-height:1.6}label{display:grid;gap:6px;margin:16px 0;color:#cbd3df}input,textarea,button{font:inherit;border-radius:9px;border:1px solid #414b5a;padding:10px;background:#111722;color:#f5f7fa;width:100%}button{background:#6c7dff;border:0;font-weight:600;cursor:pointer;margin-top:10px}.secondary{background:#303846}.hidden{display:none}.row{border-top:1px solid #353d4a;padding:12px 0}.small{font-size:13px;color:#aeb8c8}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:180px;overflow:auto}#status{min-height:24px;color:#b6c5ff}footer{margin-top:16px;font-size:12px;color:#9da8ba}
</style><main><section><h1>连接到 Atlas</h1><p>输入设备名称并提交配对申请。批准后，这个浏览器会在本机保存设备凭据并接收发给它的指令。</p><form id="pairForm"><label>设备标识<input id="deviceId" required maxlength="64" pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,63}" autocomplete="username" placeholder="例如 phone-kitchen"></label><label>设备名称<input id="deviceName" required maxlength="120" placeholder="我的手机"></label><label>配对码<input id="pairCode" required minlength="8" maxlength="8" inputmode="numeric" autocomplete="one-time-code"></label><button>发送配对申请</button></form><div id="status" role="status"></div><div id="commands" class="hidden"><h2>设备收件箱</h2><div id="commandList"></div><button id="refresh" class="secondary" type="button">刷新指令</button><button id="disconnect" class="secondary" type="button">在此浏览器撤销登录</button></div><footer>设备凭据只保存在这个浏览器的本地存储；撤销设备配对后凭据立即失效。</footer></section></main><script>
(()=>{const q=new URLSearchParams(location.search), challenge=q.get('challenge_id')||'', code=new URLSearchParams(location.hash.slice(1)).get('code')||'', $=id=>document.getElementById(id), status=$('status'), form=$('pairForm'), commands=$('commands'), headers=()=>({'Authorization':'Bearer '+localStorage.getItem('atlas-device-token')}); $('pairCode').value=code; $('deviceId').value=localStorage.getItem('atlas-device-id')||''; $('deviceName').value=localStorage.getItem('atlas-device-name')||''; let timer=0, seen=new Set(); const api=async(path,options={})=>{const response=await fetch(path,{...options,headers:{...(options.headers||{}),...(options.auth?headers():{})}});const body=await response.json().catch(()=>({detail:'Server returned an invalid response'}));if(!response.ok)throw new Error(body.detail||('HTTP '+response.status));return body}; const render=items=>{for(const item of items){if(seen.has(item.id))continue;seen.add(item.id);const article=document.createElement('article');article.className='row';const prompt=document.createElement('pre');prompt.textContent=item.prompt;const area=document.createElement('textarea');area.rows=3;area.placeholder='执行结果';const send=document.createElement('button');send.textContent='提交结果';send.onclick=async()=>{send.disabled=true;try{await api('/api/devices/node/'+encodeURIComponent(localStorage.getItem('atlas-device-id'))+'/commands/'+encodeURIComponent(item.id)+'/result',{method:'POST',auth:true,headers:{'Content-Type':'application/json'},body:JSON.stringify({result:area.value})});article.remove();status.textContent='结果已送回 Atlas。'}catch(error){status.textContent=String(error);send.disabled=false}};article.append(prompt,area,send);$('commandList').prepend(article)}}; const poll=async()=>{try{await api('/api/devices/node/'+encodeURIComponent(localStorage.getItem('atlas-device-id'))+'/presence',{method:'POST',auth:true});const result=await api('/api/devices/node/'+encodeURIComponent(localStorage.getItem('atlas-device-id'))+'/commands',{auth:true});render(result.commands)}catch(error){status.textContent=String(error)}}; const start=()=>{form.classList.add('hidden');commands.classList.remove('hidden');status.textContent='已配对；此页会定时检查指令。';void poll();timer=window.setInterval(()=>void poll(),5000)}; const saved=localStorage.getItem('atlas-device-token'),savedId=localStorage.getItem('atlas-device-id');if(saved&&savedId)start();form.addEventListener('submit',async event=>{event.preventDefault();status.textContent='正在发送申请…';try{const result=await api('/api/devices/pairing/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({challenge_id:challenge,code:$('pairCode').value.trim(),device_id:$('deviceId').value.trim(),display_name:$('deviceName').value.trim(),os:navigator.userAgent.slice(0,120)})});status.textContent='等待本机管理员批准…';const deadline=Date.now()+600000;while(Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,2000));const state=await api('/api/devices/pairing/claim/'+encodeURIComponent(result.request_id)+'?proof='+encodeURIComponent(result.proof));if(state.credential){localStorage.setItem('atlas-device-token',state.credential);localStorage.setItem('atlas-device-id',state.device_id);localStorage.setItem('atlas-device-name',$('deviceName').value.trim());history.replaceState(null,'',location.pathname);start();return}if(['rejected','expired'].includes(state.status)){throw new Error('配对申请已'+state.status)}}throw new Error('配对申请超时，请重新生成二维码')}catch(error){status.textContent=String(error)}});$('refresh').onclick=()=>void poll();$('disconnect').onclick=()=>{clearInterval(timer);localStorage.removeItem('atlas-device-token');localStorage.removeItem('atlas-device-id');localStorage.removeItem('atlas-device-name');location.reload()}})();
</script></html>'''
    return HTMLResponse(page, headers={
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/pairing/claim")
async def claim_pairing(req: DeviceClaimRequest,
                        services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    registry = _registry_for(services)
    if req.device_id == SELF_DEVICE_ID:
        raise HTTPException(status_code=409, detail="内置本机设备不能再次配对")
    if registry.get(req.device_id, project=False):
        raise HTTPException(status_code=409, detail="设备标识已登记，请使用其他标识")
    store = _pairing_store(registry)
    try:
        return await asyncio.to_thread(store.claim_device, req.challenge_id, req.code,
                                       req.device_id, req.display_name, req.os)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/pairing/claim/{request_id}")
async def poll_pairing_claim(request_id: str,
                             services: Annotated[AppServices, Depends(get_app_services)],
                             proof: str = Query(min_length=20, max_length=100)) -> dict[str, Any]:
    store = _pairing_store(_registry_for(services))
    try:
        result = await asyncio.to_thread(store.claim_status, request_id, proof)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result.get("status") == "approved" and result.get("device_id"):
        registry = _registry_for(services)
        device_id = str(result["device_id"])
        device = registry.get(device_id, project=False)
        if device:
            registry.set_presence(device_id, activity="paired")
    return result


@router.get("/pairing/requests", dependencies=[Depends(_require_trusted_origin)])
async def list_pairing_requests(services: Annotated[AppServices, Depends(get_app_services)],
                                kind: str = Query(default="", pattern="^(|device|dm)$")) -> dict[str, Any]:
    store = _pairing_store(_registry_for(services))
    return {"requests": await asyncio.to_thread(store.list_requests, kind)}


@router.post("/pairing/requests/{request_id}", dependencies=[Depends(_require_trusted_origin)])
async def decide_pairing_request(request_id: str, req: PairingDecision,
                                 services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    registry = _registry_for(services)
    store = _pairing_store(registry)
    credential = secrets.token_urlsafe(40) if req.action == "approve" else ""
    try:
        result = await asyncio.to_thread(store.decide, request_id, req.action, credential)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result["kind"] == "device" and req.action == "approve":
        device_id = str(result["device_id"])
        existing = registry.get(device_id, project=False)
        if existing is None:
            try:
                registry.add(device_id, str(result["display_name"] or device_id), kind="ingress",
                             os=str(result.get("os") or ""), trusted=True)
            except DeviceError as exc:
                store.revoke_credential(device_id)
                raise _device_error(exc) from exc
        else:
            registry.update(device_id, trusted=True)
        registry.set_presence(device_id, activity="paired")
    return {"request": result}


@router.post("/{device_id}/credential/rotate", dependencies=[Depends(_require_trusted_origin)])
async def rotate_pairing_credential(device_id: str,
                                    services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, str]:
    registry = _registry_for(services)
    device = registry.get(device_id, project=False)
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    if not device.get("trusted"):
        raise HTTPException(status_code=409, detail="设备未完成配对")
    return {"credential": _pairing_store(registry).rotate_credential(device_id)}


@router.post("/{device_id}/pairing/revoke", dependencies=[Depends(_require_trusted_origin)])
async def revoke_pairing_credential(device_id: str,
                                    services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    registry = _registry_for(services)
    device = registry.get(device_id, project=False)
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    _pairing_store(registry).revoke_credential(device_id)
    await asyncio.to_thread(_transfer_store(registry).revoke_device, device_id)
    registry.update(device_id, trusted=False)
    registry.set_presence(device_id, activity="", last_seen=0)
    return {"device_id": device_id, "revoked": True}


@router.post("/commands", dependencies=[Depends(_require_trusted_origin)])
async def create_device_command(device_id: str, req: DeviceCommandRequest,
                                services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    registry = _registry_for(services)
    device = registry.get(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    if not device.get("trusted"):
        raise HTTPException(status_code=403, detail="设备未完成配对")
    pairing = _pairing_store(registry)
    if not await asyncio.to_thread(pairing.has_credential, device_id):
        raise HTTPException(status_code=409, detail="设备没有有效的安全配对凭据")
    return await asyncio.to_thread(pairing.create_command, device_id, req.prompt)


@router.get("/node/{device_id}/commands")
async def poll_device_commands(device_id: str, request: Request,
                               services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    registry = _registry_for(services)
    store = _pairing_store(registry)
    _require_paired_device(request, store, device_id)
    await asyncio.to_thread(registry.set_presence, device_id, activity="polling commands")
    return {"commands": await asyncio.to_thread(store.pending_commands, device_id)}


@router.post("/node/{device_id}/presence")
async def paired_device_presence(device_id: str, request: Request,
                                 services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    registry = _registry_for(services)
    _require_paired_device(request, _pairing_store(registry), device_id)
    return await asyncio.to_thread(registry.set_presence, device_id, activity="paired")


@router.post("/node/{device_id}/commands/{command_id}/result")
async def complete_device_command(device_id: str, command_id: str, req: DeviceCommandResult,
                                  request: Request,
                                  services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    store = _pairing_store(_registry_for(services))
    _require_paired_device(request, store, device_id)
    try:
        return await asyncio.to_thread(store.complete_command, device_id, command_id, req.result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{device_id}/commands", dependencies=[Depends(_require_trusted_origin)])
async def list_device_commands(device_id: str,
                               services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    registry = _registry_for(services)
    return {"commands": await asyncio.to_thread(_pairing_store(registry).list_commands, device_id)}


# ---------------------------------------------------------------------------
# Devices CRUD
# ---------------------------------------------------------------------------
@router.get("")
async def list_devices(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    registry = _registry_for(services)
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
async def register_device(
    req: IngressRegistration,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    registry = _registry_for(services)
    try:
        device = await asyncio.to_thread(
            registry.add, req.device_id, req.display_name,
            kind=req.kind, os=req.os, notes=req.notes,
            capabilities=req.capabilities, trusted=req.trusted)
    except DeviceError as exc:
        raise _device_error(exc) from exc
    return device


@router.get("/takeover")
async def takeover_state(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    return _takeover_for(services).snapshot()


class TakeoverRequest(BaseModel):
    action: str  # human_take | agent_take | release
    agent_id: str | None = None
    note: str = ""


@router.post("/takeover", dependencies=[Depends(_require_trusted_origin)])
async def takeover_action(
    req: TakeoverRequest,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    machine = _takeover_for(services)
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
async def activity_feed(
    services: Annotated[AppServices, Depends(get_app_services)], limit: int = 0,
) -> dict[str, Any]:
    if limit < 0:
        raise HTTPException(status_code=422, detail="limit 不能为负")
    events = await asyncio.to_thread(_takeover_for(services).activity, limit or None)
    return {"activity": events}


@router.get("/handoff")
async def list_handoff(
    services: Annotated[AppServices, Depends(get_app_services)], status: str | None = None,
) -> dict[str, Any]:
    cards = await asyncio.to_thread(_takeover_for(services).handoff_cards, status)
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
async def handoff_action(
    req: HandoffRequest,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    machine = _takeover_for(services)
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
async def get_device(
    device_id: str, services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    registry = _registry_for(services)
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
async def patch_device(
    device_id: str, req: DevicePatch,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    registry = _registry_for(services)
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        saved = await asyncio.to_thread(registry.update, device_id, **fields)
    except DeviceError as exc:
        raise _device_error(exc) from exc
    if fields.get("trusted") is False:
        await asyncio.to_thread(_transfer_store(registry).revoke_device, device_id)
        await asyncio.to_thread(_pairing_store(registry).revoke_credential, device_id)
        await asyncio.to_thread(registry.set_presence, device_id, activity="", last_seen=0)
    return saved


class PresenceBeat(BaseModel):
    activity: str | None = None
    last_seen: float | None = Field(default=None, ge=0)


@router.put("/{device_id}/presence", dependencies=[Depends(_require_trusted_origin)])
async def put_presence(
    device_id: str, req: PresenceBeat,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    registry = _registry_for(services)
    try:
        return await asyncio.to_thread(
            registry.set_presence, device_id,
            activity=req.activity, last_seen=req.last_seen)
    except DeviceError as exc:
        raise _device_error(exc) from exc


@router.delete("/{device_id}", dependencies=[Depends(_require_trusted_origin)])
async def delete_device(
    device_id: str, services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    registry = _registry_for(services)
    try:
        await asyncio.to_thread(registry.remove, device_id)
    except DeviceError as exc:
        raise _device_error(exc) from exc
    await asyncio.to_thread(_transfer_store(registry).revoke_device, device_id)
    await asyncio.to_thread(_pairing_store(registry).revoke_credential, device_id)
    return {"status": "ok", "device_id": device_id}


__all__ = ["get_registry", "get_takeover", "router", "set_registry", "set_takeover"]
