"""Office task pane pairing, active-selection handoff, and writeback queue."""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter(prefix="/api/office", tags=["office-addin"])
_MAX_CONTEXT_CHARS = 50_000
_PAIRING_TTL_SECONDS = 300


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sessions(services: AppServices) -> dict[str, str]:
    if services.office_sessions is None:
        services.office_sessions = {}
    return services.office_sessions


def _office_token(services: AppServices, token: str | None) -> tuple[str, str]:
    if not token:
        raise HTTPException(status_code=401, detail="Office add-in is not paired; enter the code from /office first")
    digest = _token_hash(token)
    conversation_id = _sessions(services).get(digest)
    if not conversation_id:
        raise HTTPException(status_code=401, detail="Office add-in session has expired; pair it again with /office")
    return digest, conversation_id


@router.post("/pairings")
async def create_office_pairing(
    services: Annotated[AppServices, Depends(get_app_services)], body: dict[str, Any],
) -> dict[str, Any]:
    conversation_id = body.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise HTTPException(status_code=422, detail="conversation_id is required")
    memory = services.memory
    if memory is None or await memory.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    code = f"{secrets.randbelow(100_000_000):08d}"
    expires_at = time.time() + _PAIRING_TTL_SECONDS
    services.office_pairing = {"code": code, "expires_at": expires_at, "conversation_id": conversation_id, "attempts_left": 5}
    return {"pairing_code": code, "expires_at": datetime.fromtimestamp(expires_at, UTC).isoformat(), "expires_in": _PAIRING_TTL_SECONDS}


@router.post("/pair")
async def pair_office_addin(
    services: Annotated[AppServices, Depends(get_app_services)], body: dict[str, Any],
) -> dict[str, str]:
    code = body.get("pairing_code")
    pairing = services.office_pairing
    if not pairing or float(pairing.get("expires_at", 0)) <= time.time():
        services.office_pairing = None
        raise HTTPException(status_code=400, detail="Pairing code is invalid or expired; generate a new code with /office")
    if not isinstance(code, str) or pairing.get("code") != code:
        pairing["attempts_left"] = int(pairing.get("attempts_left", 0)) - 1
        if pairing["attempts_left"] <= 0:
            services.office_pairing = None
        raise HTTPException(status_code=400, detail="Pairing code is invalid or expired; generate a new code with /office")
    token = secrets.token_urlsafe(32)
    session_id = _token_hash(token)
    _sessions(services)[session_id] = str(pairing["conversation_id"])
    services.office_pairing = None
    if services.office_handoffs is None:
        services.office_handoffs = deque(maxlen=32)
    if services.office_writebacks is None:
        services.office_writebacks = deque(maxlen=64)
    return {"session_token": token, "conversation_id": str(pairing["conversation_id"])}


@router.delete("/pair")
async def unpair_office_addin(
    services: Annotated[AppServices, Depends(get_app_services)],
    x_atlas_office_token: Annotated[str | None, Header(alias="X-Atlas-Office-Token")] = None,
) -> dict[str, bool]:
    digest, _ = _office_token(services, x_atlas_office_token)
    _sessions(services).pop(digest, None)
    if services.office_writebacks is not None:
        services.office_writebacks = deque(
            (item for item in services.office_writebacks if item.get("session_id") != digest), maxlen=64,
        )
    return {"unpaired": True}


@router.get("/status")
async def office_status(
    services: Annotated[AppServices, Depends(get_app_services)],
    x_atlas_office_token: Annotated[str | None, Header(alias="X-Atlas-Office-Token")] = None,
) -> dict[str, Any]:
    digest, conversation_id = _office_token(services, x_atlas_office_token)
    return {"paired": True, "conversation_id": conversation_id, "pending_writebacks": sum(
        1 for item in services.office_writebacks or () if item.get("session_id") == digest
    )}


@router.post("/context")
async def send_office_context(
    services: Annotated[AppServices, Depends(get_app_services)], body: dict[str, Any],
    x_atlas_office_token: Annotated[str | None, Header(alias="X-Atlas-Office-Token")] = None,
) -> dict[str, bool]:
    _, conversation_id = _office_token(services, x_atlas_office_token)
    selection = body.get("selection")
    host = body.get("host")
    document_name = body.get("document_name", "")
    address = body.get("address", "")
    if not isinstance(selection, str) or not selection.strip() or len(selection) > _MAX_CONTEXT_CHARS:
        raise HTTPException(status_code=422, detail=f"selection must contain 1 to {_MAX_CONTEXT_CHARS} characters")
    if host not in {"Word", "Excel"}:
        raise HTTPException(status_code=422, detail="host must be Word or Excel")
    if not isinstance(document_name, str) or len(document_name) > 300:
        raise HTTPException(status_code=422, detail="document_name is invalid")
    if not isinstance(address, str) or len(address) > 300:
        raise HTTPException(status_code=422, detail="address is invalid")
    if services.office_handoffs is None:
        services.office_handoffs = deque(maxlen=32)
    services.office_handoffs.append({
        "conversation_id": conversation_id, "host": host,
        "document_name": document_name, "address": address,
        "selection": selection,
    })
    return {"queued": True}


@router.get("/handoffs/next")
async def take_office_context(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    queue = services.office_handoffs
    return {"handoff": queue.popleft() if queue else None}


@router.post("/writebacks")
async def queue_office_writeback(
    services: Annotated[AppServices, Depends(get_app_services)], body: dict[str, Any],
) -> dict[str, int]:
    conversation_id = body.get("conversation_id")
    text = body.get("text")
    if not isinstance(conversation_id, str) or not isinstance(text, str) or not text.strip() or len(text) > _MAX_CONTEXT_CHARS:
        raise HTTPException(status_code=422, detail=f"conversation_id and text (up to {_MAX_CONTEXT_CHARS} characters) are required")
    sessions = [session_id for session_id, target in _sessions(services).items() if target == conversation_id]
    if not sessions:
        raise HTTPException(status_code=409, detail="No paired Office add-in is connected to this conversation")
    if services.office_writebacks is None:
        services.office_writebacks = deque(maxlen=64)
    for session_id in sessions:
        services.office_writebacks.append({"id": str(uuid.uuid4()), "session_id": session_id, "text": text})
    return {"queued": len(sessions)}


@router.get("/writebacks/next")
async def take_office_writeback(
    services: Annotated[AppServices, Depends(get_app_services)],
    x_atlas_office_token: Annotated[str | None, Header(alias="X-Atlas-Office-Token")] = None,
) -> dict[str, Any]:
    digest, _ = _office_token(services, x_atlas_office_token)
    queue = services.office_writebacks
    if not queue:
        return {"writeback": None}
    for index, item in enumerate(queue):
        if item.get("session_id") == digest:
            del queue[index]
            return {"writeback": {"id": item["id"], "text": item["text"]}}
    return {"writeback": None}
