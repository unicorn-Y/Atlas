"""REST surface for the X2 browser runtime (``/api/browser/*``).

Endpoints (shapes fixed by the frontend ``services/x2Api.ts`` client):

- ``POST /handoff``            — resolve a pending ``browser_handoff`` card
- ``GET/POST /settings``       — browser takeover mode (standalone / copied-profile / cdp / extension)
- ``POST /recordings``         — start/stop a learned-workflow recording
- ``GET  /recordings/{id}``    — full recording document (steps)
- ``POST /recordings/{id}/to-skill`` — SKILL.md preview (dry_run) or save
- ``GET/POST/DELETE /vault``   — credential vault; entries carry handles only,
  the password appears once in the POST body and is never echoed back.

OriginGuard: the whole ``atlas.server`` app sits behind the ``atlas.origin_guard``
ASGI middleware, which covers every route below once the integration owner mounts
this router.  The ``_require_trusted_origin`` dependency re-applies the same rule
so the router stays safe when mounted standalone (tests, tooling).

Integration note for the owner of ``atlas/server.py``:

- ``app.include_router(browser_router)`` next to the other routers.
- Bind the handoff channel when building a run's X2Context:
  ``X2Context(..., wait_input=atlas.tools.x2.browser.handoff_wait_input)`` so
  ``POST /handoff`` resolutions reach blocked ``browser_handoff`` tool calls.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from atlas.origin_guard import TOKEN_HEADER, is_trusted

router = APIRouter(prefix="/api/browser", tags=["browser"])

# Injectable credential-vault store (Hermes ``agent.vault_store.VaultStore`` by
# default; tests install a fake).  The store protocol used here: add_item,
# list_items, remove_item.
_vault_store_factory: Callable[[], Any] | None = None


def set_vault_store_factory(factory: Callable[[], Any] | None) -> None:
    """Override the vault store builder (tests, custom wiring)."""
    global _vault_store_factory
    _vault_store_factory = factory


def _vault_store() -> Any:
    if _vault_store_factory is not None:
        return _vault_store_factory()
    from agent.vault_store import get_vault_store

    return get_vault_store()


def _require_trusted_origin(request: Request) -> None:
    """Mirror of the app-level OriginGuard rule for standalone mounts."""
    trusted = is_trusted(
        request.headers.get("origin"),
        request.headers.get(TOKEN_HEADER),
        fetch_site=request.headers.get("sec-fetch-site"),
    )
    if not trusted:
        raise HTTPException(status_code=403, detail="Requests from this origin are not allowed")


# ---------------------------------------------------------------------------
# Handoff resolution
# ---------------------------------------------------------------------------
class HandoffResolution(BaseModel):
    run_id: str
    resolution: str  # open_panel | done | give_up


@router.post("/handoff", dependencies=[Depends(_require_trusted_origin)])
async def resolve_handoff_endpoint(req: HandoffResolution) -> dict[str, Any]:
    """Resolve a pending browser handoff card (browser.handoff_required)."""
    from atlas.tools.x2.browser import resolve_handoff

    if req.resolution not in {"open_panel", "done", "give_up"}:
        raise HTTPException(status_code=422, detail="resolution 必须是 open_panel / done / give_up")
    if not resolve_handoff(req.run_id, req.resolution):
        raise HTTPException(status_code=404, detail="该运行没有等待中的人工交接")
    return {"status": "ok", "run_id": req.run_id, "resolution": req.resolution}


# ---------------------------------------------------------------------------
# Takeover settings (设置 → 浏览器)
# ---------------------------------------------------------------------------
class BrowserSettingsRequest(BaseModel):
    mode: str | None = None
    cdp_url: str | None = None
    proxy: str | None = None


@router.get("/settings", dependencies=[Depends(_require_trusted_origin)])
async def get_settings() -> dict[str, Any]:
    from atlas.tools.x2.browser import get_browser_settings

    return get_browser_settings()


@router.post("/settings", dependencies=[Depends(_require_trusted_origin)])
async def save_settings(req: BrowserSettingsRequest) -> dict[str, Any]:
    from atlas.tools.x2.browser import apply_browser_settings

    try:
        return apply_browser_settings(
            mode=req.mode or "", cdp_url=req.cdp_url or "", proxy=req.proxy or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Learned-workflow recordings
# ---------------------------------------------------------------------------
class RecordingControlRequest(BaseModel):
    action: str  # start | stop
    recording_id: str | None = None


def _recording_summary(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "recording_id": doc.get("recording_id"),
        "status": doc.get("status"),
        "site": doc.get("site", ""),
        "step_count": len(doc.get("steps") or []),
    }


@router.post("/recordings", dependencies=[Depends(_require_trusted_origin)])
async def control_recording(req: RecordingControlRequest) -> dict[str, Any]:
    from atlas.tools.x2.browser import get_runtime

    if req.action == "start":
        doc = get_runtime().start_recording()
        return _recording_summary(doc)
    if req.action == "stop":
        doc = get_runtime().stop_recording()
        if doc is None:
            raise HTTPException(status_code=409, detail="当前没有进行中的浏览器录制")
        return _recording_summary(doc)
    raise HTTPException(status_code=422, detail="action 必须是 start 或 stop")


@router.get("/recordings/{recording_id}", dependencies=[Depends(_require_trusted_origin)])
async def get_recording(recording_id: str) -> dict[str, Any]:
    from atlas.tools.x2.browser import get_runtime

    doc = get_runtime().recordings.load(recording_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"没有 id 为 {recording_id!r} 的浏览器录制")
    return {**doc, "step_count": len(doc.get("steps") or [])}


class ToSkillRequest(BaseModel):
    dry_run: bool = True
    save: bool = False
    name: str | None = None


@router.post("/recordings/{recording_id}/to-skill", dependencies=[Depends(_require_trusted_origin)])
async def recording_to_skill(recording_id: str, req: ToSkillRequest) -> dict[str, Any]:
    from atlas.tools.x2.browser import get_runtime
    from atlas.tools.x2.recording import to_skill_bundle

    doc = get_runtime().recordings.load(recording_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"没有 id 为 {recording_id!r} 的浏览器录制")
    bundle = to_skill_bundle(doc, name=req.name or "")
    # 默认仍是纯预览（前端 dry_run 契约不变）；save=true 或显式 dry_run=false 才落盘。
    if not (req.save or not req.dry_run):
        return {"name": bundle["name"], "description": bundle["description"],
                "skill_md": bundle["skill_md"], "steps": bundle["steps"]}
    # 保存：写入用户技能目录（与市场安装同一布局 <user skills>/community/<name>），
    # 并经 register_local 以 origin_kind=local_recorded 记入唯一注册表。
    from atlas.api.skills_market_router import _http_error, save_local_skill_bundle
    from atlas.skills.market import MarketError

    def persist() -> dict[str, Any]:
        return save_local_skill_bundle(
            bundle["name"], {"SKILL.md": bundle["skill_md"]},
            origin_kind="local_recorded",
            reason=f"X2 浏览器录制保存为技能（录制 {doc.get('recording_id')}）")

    try:
        result = await asyncio.to_thread(persist)
    except MarketError as exc:
        raise _http_error(exc) from None
    return {"saved": True, "skill": bundle["name"], "skill_id": bundle["name"],
            "name": bundle["name"], "version": result["version"],
            "path": result["path"], "origin_kind": "local_recorded",
            "skill_md": bundle["skill_md"]}


# ---------------------------------------------------------------------------
# Credential vault (handles only; passwords write-only)
# ---------------------------------------------------------------------------
class VaultNewEntry(BaseModel):
    label: str
    username: str | None = None
    password: str
    url: str | None = None


def _vault_entry(meta: Any) -> dict[str, Any]:
    """VaultItemMeta (or dict) -> frontend VaultEntry shape — never a secret."""
    if hasattr(meta, "to_dict"):
        meta = meta.to_dict()
    return {
        "id": str(meta.get("id") or ""),
        "label": str(meta.get("label") or ""),
        "username": str(meta.get("identifier") or ""),
        "url": str(meta.get("origin") or ""),
        "created_at": str(meta.get("created_at") or ""),
        "kind": str(meta.get("kind") or "login"),
    }


@router.get("/vault", dependencies=[Depends(_require_trusted_origin)])
async def list_vault_entries() -> dict[str, Any]:
    store = await asyncio.to_thread(_vault_store)
    metas = await asyncio.to_thread(store.list_items)
    return {"entries": [_vault_entry(meta) for meta in metas]}


@router.post("/vault", dependencies=[Depends(_require_trusted_origin)])
async def add_vault_entry(req: VaultNewEntry) -> dict[str, Any]:
    if not req.label.strip():
        raise HTTPException(status_code=422, detail="label 不能为空")
    if not req.password:
        raise HTTPException(status_code=422, detail="password 不能为空")
    store = await asyncio.to_thread(_vault_store)
    try:
        meta = await asyncio.to_thread(
            store.add_item,
            "login",
            req.label.strip(),
            {
                "identifier_type": "username",
                "identifier": (req.username or "").strip(),
                "password": req.password,
            },
            (req.url or "").strip() or None,
        )
    except Exception as exc:  # noqa: BLE001 - vault errors carry no secret values
        raise HTTPException(status_code=400, detail=f"凭据保存失败：{exc}") from exc
    return _vault_entry(meta)


@router.delete("/vault/{item_id}", dependencies=[Depends(_require_trusted_origin)])
async def delete_vault_entry(item_id: str) -> dict[str, Any]:
    store = await asyncio.to_thread(_vault_store)
    removed = await asyncio.to_thread(store.remove_item, item_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"没有 id 为 {item_id!r} 的凭据条目")
    return {"status": "ok"}


__all__ = ["router", "set_vault_store_factory"]
