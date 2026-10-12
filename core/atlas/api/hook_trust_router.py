"""Per-hook review endpoints backed by HookStore's independent trust registry."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.runtime.hooks import HookStore

router = APIRouter()


def _server() -> Any:
    import atlas.server

    return atlas.server


class HookTrustRequest(BaseModel):
    trusted: bool
    fingerprint: str = Field(min_length=64, max_length=64)
    workspace: str | None = None


def _normalize_definition(raw: dict[str, Any], *, hook_id: str | None = None) -> dict[str, Any]:
    handler = raw.get("handler")
    if not isinstance(handler, dict):
        handler = {"type": "command", "command": raw.get("command", "")}
    kind = str(handler.get("type") or "command").lower()
    if kind == "command":
        command = str(handler.get("command") or "").strip()
        if not command:
            raise HTTPException(status_code=422, detail="command handler requires command")
        handler = {"type": "command", "command": command}
    elif kind == "http":
        url = str(handler.get("url") or "").strip()
        method = str(handler.get("method") or "POST").upper()
        headers = handler.get("headers", {})
        if not url.startswith(("https://", "http://")) or method not in {"POST", "PUT", "PATCH"} or not isinstance(headers, dict):
            raise HTTPException(status_code=422, detail="http handler requires an http(s) URL, supported method, and headers object")
        handler = {"type": "http", "url": url, "method": method, "headers": headers}
    elif kind == "mcp":
        server, tool = str(handler.get("server") or "").strip(), str(handler.get("tool") or "").strip()
        if not server or not tool:
            raise HTTPException(status_code=422, detail="mcp handler requires server and tool")
        handler = {"type": "mcp", "server": server, "tool": tool}
        if "arguments" in raw.get("handler", {}):
            arguments = raw["handler"]["arguments"]
            if not isinstance(arguments, dict):
                raise HTTPException(status_code=422, detail="mcp arguments must be an object")
            handler["arguments"] = arguments
    else:
        raise HTTPException(status_code=422, detail="handler type must be command, http, or mcp")
    event = str(raw.get("event") or "")
    timeout_s = int(raw.get("timeout_s", 30))
    if event not in HookStore.EVENTS or not 1 <= timeout_s <= 300:
        raise HTTPException(status_code=422, detail="valid Atlas event and timeout_s 1..300 are required")
    return {"id": hook_id or str(raw.get("id") or "").strip(), "event": event,
            "command": str(handler.get("command") or ""), "handler": handler,
            "timeout_s": timeout_s, "enabled": bool(raw.get("enabled", False))}


@router.get("/api/hooks/trust")
async def list_hook_trust(
    services: Annotated[AppServices, Depends(get_app_services)],
    workspace: str | None = None,
) -> dict[str, Any]:
    del services
    return {"hooks": _server()._hook_store().list_all(workspace)}


@router.put("/api/hooks/{hook_id}/trust")
async def set_hook_trust(
    services: Annotated[AppServices, Depends(get_app_services)],
    hook_id: str,
    request: HookTrustRequest,
) -> dict[str, Any]:
    del services
    try:
        return _server()._hook_store().set_hook_trust(
            hook_id,
            request.trusted,
            fingerprint=request.fingerprint,
            cwd=request.workspace,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Hook 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/hooks/definitions", status_code=201)
async def create_hook_definition(
    services: Annotated[AppServices, Depends(get_app_services)], request: dict[str, Any],
) -> dict[str, Any]:
    del services
    store = _server()._hook_store()
    hook = _normalize_definition(request)
    if not hook["id"] or any(row.get("id") == hook["id"] for row in store.list()):
        raise HTTPException(status_code=409, detail="missing or duplicate hook id")
    hook["enabled"] = False  # Every new revision is disabled until reviewed and explicitly enabled.
    store.save([*store.list(), hook])
    return hook


@router.put("/api/hooks/{hook_id}/definition")
async def update_hook_definition(
    services: Annotated[AppServices, Depends(get_app_services)], hook_id: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    del services
    store = _server()._hook_store()
    hooks = store.list()
    for index, old in enumerate(hooks):
        if old.get("id") == hook_id:
            updated = _normalize_definition(request, hook_id=hook_id)
            updated["enabled"] = bool(old.get("enabled", False))
            hooks[index] = updated
            store.save(hooks)
            return updated
    raise HTTPException(status_code=404, detail="Atlas hook not found")


@router.get("/api/hooks/export")
async def export_hook_definitions(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    del services
    hooks = _server()._hook_store().list()
    return {"format": "atlas.hooks/v1", "hooks": [
        {"id": h["id"], "event": h["event"],
         "handler": h.get("handler", {"type": "command", "command": h.get("command", "")}),
         "timeout_s": h.get("timeout_s", 30), "enabled": bool(h.get("enabled", False))}
        for h in hooks
    ]}


@router.post("/api/hooks/import")
async def import_hook_definitions(
    services: Annotated[AppServices, Depends(get_app_services)], request: dict[str, Any],
) -> dict[str, Any]:
    del services
    if request.get("format") != "atlas.hooks/v1" or not isinstance(request.get("hooks"), list):
        raise HTTPException(status_code=422, detail="expected atlas.hooks/v1 with a hooks array")
    store = _server()._hook_store()
    hooks = store.list()
    ids = {str(h.get("id")) for h in hooks}
    imported = []
    for raw in request["hooks"]:
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail="each imported hook must be an object")
        hook = _normalize_definition(raw)
        if not hook["id"] or hook["id"] in ids:
            raise HTTPException(status_code=409, detail=f"missing or duplicate hook id: {hook['id']}")
        ids.add(hook["id"])
        hook["enabled"] = False
        imported.append(hook)
    store.save([*hooks, *imported])
    return {"format": "atlas.hooks/v1", "imported": len(imported), "hooks": imported,
            "message": "Imported hooks are disabled and require per-hook approval."}
