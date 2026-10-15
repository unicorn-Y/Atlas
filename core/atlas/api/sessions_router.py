"""REST surface for independent side sessions (cards, sidebar, stop/message)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from atlas.sessions import get_session_hub, public

router = APIRouter()


@router.get("/api/sessions")
async def list_sessions(
    parent: str | None = Query(None), limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    hub = get_session_hub()
    items = hub.list(parent)[:limit]
    return {"sessions": [public(item) for item in items]}


@router.post("/api/sessions", status_code=201)
async def create_session(req: dict[str, Any]) -> dict[str, Any]:
    """User-made side session (palette / composer): starts now unless ``start`` is false."""
    parent = str(req.get("parent_conversation_id") or "").strip() or None
    title = str(req.get("title") or "").strip()[:120]
    prompt = str(req.get("prompt") or "").strip()
    if not title or not prompt:
        raise HTTPException(status_code=422, detail="title and prompt are required")
    fields = {
        "parent_conversation_id": parent, "title": title, "prompt": prompt,
        "background": str(req.get("background") or ""),
        "context": "fork" if req.get("context") == "fork" and parent else "fresh",
        "use_worktree": bool(req.get("use_worktree")), "name": str(req.get("name") or title),
        "notify_parent": req.get("notify") is not False and parent is not None,
    }
    hub = get_session_hub()
    try:
        if req.get("start") is False:
            record = await hub.propose(initiation="offer", **fields)
        else:
            record = await hub.create_and_start(initiation="user_asked", **fields)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"session": public(record)}


@router.get("/api/sessions/active-run")
async def active_run(conversation_id: str) -> dict[str, Any]:
    """The live backend run of a conversation, so the desktop can attach to it.

    Covers runs no desktop socket started: side sessions, report wake-ups,
    automations and channel turns.
    """
    run = get_session_hub().active_run(conversation_id)
    if run is None:
        return {"run": None}
    return {"run": {"run_id": run.run_id, "status": run.status, "waiting_for": run.waiting_for,
                    "started_at": run.started_at}}


def _record(session_id: str) -> dict[str, Any]:
    record = get_session_hub().store.get(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="session not found")
    return record


@router.post("/api/sessions/{session_id}/start")
async def start_session(session_id: str) -> dict[str, Any]:
    _record(session_id)
    try:
        return {"session": public(await get_session_hub().start(session_id))}
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/sessions/{session_id}/dismiss")
async def dismiss_session(session_id: str, req: dict[str, Any] | None = None) -> dict[str, Any]:
    _record(session_id)
    reason = str((req or {}).get("reason") or "")
    return {"session": public(await get_session_hub().dismiss(session_id, reason))}


@router.post("/api/sessions/{session_id}/stop")
async def stop_session(session_id: str) -> dict[str, Any]:
    _record(session_id)
    return {"session": public(await get_session_hub().stop(session_id))}


@router.post("/api/sessions/{session_id}/message")
async def message_session(session_id: str, req: dict[str, Any]) -> dict[str, Any]:
    _record(session_id)
    text = str(req.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")
    try:
        return await get_session_hub().send(session_id, text, from_label="用户")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
