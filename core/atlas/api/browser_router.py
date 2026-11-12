"""REST surface for the X2 browser runtime (``/api/browser/*``).

Endpoints (shapes fixed by the frontend ``services/x2Api.ts`` client):

- ``POST /handoff``            — resolve a pending ``browser_handoff`` card
- ``GET/POST /settings``       — browser takeover mode (standalone / copied-profile / cdp / extension)
- ``POST /recordings``         — start/stop a learned-workflow recording
- ``GET  /recordings/{id}``    — full recording document (steps)
- ``DELETE /recordings/{id}``  — delete one recording
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

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_optional_app_services
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


def _vault_store(services: Any = None) -> Any:
    """The credential vault: container first, then module override, then default.

    ``AppServices.vault_store_factory`` existed as a declared-but-never-read
    field, so an application that wired a vault store there was silently served
    the process default instead. Reading the container first makes the wiring
    real; ``set_vault_store_factory`` stays for tests and standalone mounts.
    """
    supplier = getattr(services, "vault_store_factory", None)
    if callable(supplier):
        return supplier()
    if _vault_store_factory is not None:
        return _vault_store_factory()
    from atlas.engine.agent.vault_store import get_vault_store

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
    from atlas.tools.x2 import pending as x2pending
    from atlas.tools.x2.browser import resolve_handoff

    if req.resolution not in {"open_panel", "done", "give_up"}:
        raise HTTPException(status_code=422, detail="resolution 必须是 open_panel / done / give_up")
    broker_resolved = resolve_handoff(req.run_id, req.resolution)
    # The run-scoped X2Context blocks on the pending registry, not the broker:
    # both channels are resolved so either wiring resumes the blocked tool call.
    pending_resolved = x2pending.resolve(req.run_id, req.resolution)
    if not (broker_resolved or pending_resolved):
        raise HTTPException(status_code=404, detail="该运行没有等待中的人工交接")
    return {"status": "ok", "run_id": req.run_id, "resolution": req.resolution}


# ---------------------------------------------------------------------------
# Takeover settings (设置 → 浏览器)
# ---------------------------------------------------------------------------
class BrowserSettingsRequest(BaseModel):
    mode: str | None = None
    cdp_url: str | None = None
    proxy: str | None = None
    profile_browser: str | None = None
    profile: str | None = None
    profile_sync_interval_minutes: int | None = None
    incognito: bool | None = None


@router.get("/settings", dependencies=[Depends(_require_trusted_origin)])
async def get_settings() -> dict[str, Any]:
    from atlas.tools.x2.browser import get_browser_settings
    from atlas.engine.tools.browser_extension_bridge import connection_info
    from pathlib import Path
    extension = connection_info()
    manifest_path = Path(extension["extension_path"]) / "manifest.json"
    try:
        import json
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        extension.update({"installed": True, "version": str(manifest.get("version", "")),
                         "manifest_version": manifest.get("manifest_version")})
    except (OSError, ValueError):
        extension.update({"installed": False, "version": "", "manifest_version": None})
    return {**get_browser_settings(), "extension": extension}


@router.post("/settings", dependencies=[Depends(_require_trusted_origin)])
async def save_settings(req: BrowserSettingsRequest) -> dict[str, Any]:
    from atlas.tools.x2.browser import apply_browser_settings

    try:
        return apply_browser_settings(
            mode=req.mode or "", cdp_url=req.cdp_url or "", proxy=req.proxy or "",
            profile_browser=req.profile_browser, profile=req.profile,
            profile_sync_interval_minutes=req.profile_sync_interval_minutes, incognito=req.incognito)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/extension/disconnect", dependencies=[Depends(_require_trusted_origin)])
async def disconnect_extension() -> dict[str, Any]:
    from atlas.engine.tools.browser_extension_bridge import disconnect
    disconnect()
    return {"connected": False}


@router.post("/connection-check", dependencies=[Depends(_require_trusted_origin)])
async def browser_connection_check() -> dict[str, Any]:
    from atlas.engine.tools.browser_tool_real_profile import live_chrome_cdp
    endpoint, error = live_chrome_cdp()
    return {"connected": endpoint is not None, "endpoint": endpoint, "error": error}


# ---------------------------------------------------------------------------
# Learned-workflow recordings
# ---------------------------------------------------------------------------
class RecordingControlRequest(BaseModel):
    action: str  # start | stop
    recording_id: str | None = None


class BrowserUserStepRequest(BaseModel):
    action: str
    url: str = ""
    selector: str = ""
    target: str = ""
    value: str | None = None
    password_field: bool = False


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


@router.post("/recordings/{recording_id}/steps", dependencies=[Depends(_require_trusted_origin)])
async def append_user_recording_step(recording_id: str, req: BrowserUserStepRequest) -> dict[str, Any]:
    """Persist an interaction recorded in the embedded webview by its user."""
    from atlas.tools.x2.browser import get_runtime
    from atlas.tools.x2.recording import Recorder

    if req.action not in {"navigate", "click", "type", "wait"}:
        raise HTTPException(status_code=422, detail="unsupported browser recording action")
    runtime = get_runtime()
    doc = runtime.recordings.load(recording_id)
    if doc is None or doc.get("status") != "recording":
        raise HTTPException(status_code=404, detail="recording is not active")
    if req.action == "navigate":
        params = {"url": req.url[:4096]}
    elif req.action == "wait":
        params = {"reason": req.target[:256]}
    elif req.action == "click":
        params = {"selector": req.selector[:1024], "target": req.target[:300]}
    else:
        params = {"selector": req.selector[:1024], "target": req.target[:300], "password_field": req.password_field}
        if not req.password_field and req.value is not None:
            params["text"] = req.value[:2000]
    step = Recorder(doc, runtime.recordings).record(req.action, params)
    return {"step": step, "step_count": len(doc.get("steps") or [])}


@router.delete("/recordings/{recording_id}", dependencies=[Depends(_require_trusted_origin)])
async def delete_recording(recording_id: str) -> dict[str, Any]:
    from atlas.tools.x2.browser import get_runtime

    if not get_runtime().recordings.delete(recording_id):
        raise HTTPException(status_code=404, detail=f"没有 id 为 {recording_id!r} 的浏览器录制")
    return {"status": "ok"}


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
        "login_method": meta.get("login_method") if isinstance(meta.get("login_method"), dict) else None,
    }


@router.get("/vault", dependencies=[Depends(_require_trusted_origin)])
async def list_vault_entries(services: AppServices | None = Depends(get_optional_app_services)) -> dict[str, Any]:
    store = await asyncio.to_thread(_vault_store, services)
    metas = await asyncio.to_thread(store.list_items)
    return {"entries": [_vault_entry(meta) for meta in metas]}


@router.post("/vault", dependencies=[Depends(_require_trusted_origin)])
async def add_vault_entry(req: VaultNewEntry, services: AppServices | None = Depends(get_optional_app_services)) -> dict[str, Any]:
    if not req.label.strip():
        raise HTTPException(status_code=422, detail="label 不能为空")
    if not req.password:
        raise HTTPException(status_code=422, detail="password 不能为空")
    if not (req.url or "").strip():
        raise HTTPException(status_code=422, detail="网站 origin 不能为空，例如 https://example.com")
    store = await asyncio.to_thread(_vault_store, services)
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
            login_method={"fields": {"identifier": "username", "password": "current-password"},
                          "confirm_before_fill": True, "source": "Atlas 设置"},
        )
    except Exception as exc:  # noqa: BLE001 - vault errors carry no secret values
        raise HTTPException(status_code=400, detail=f"凭据保存失败：{exc}") from exc
    return _vault_entry(meta)


@router.delete("/vault/{item_id}", dependencies=[Depends(_require_trusted_origin)])
async def delete_vault_entry(item_id: str, services: AppServices | None = Depends(get_optional_app_services)) -> dict[str, Any]:
    store = await asyncio.to_thread(_vault_store, services)
    removed = await asyncio.to_thread(store.remove_item, item_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"没有 id 为 {item_id!r} 的凭据条目")
    return {"status": "ok"}


class VaultRotateRequest(BaseModel):
    password: str


@router.get("/vault/import-candidates", dependencies=[Depends(_require_trusted_origin)])
async def list_browser_password_candidates(browser: str = "chrome") -> dict[str, Any]:
    """List metadata from a local Chromium password manager; never return passwords."""
    from atlas.engine.agent.browser_password_import import list_candidates, list_profiles
    try:
        profiles = await asyncio.to_thread(list_profiles, browser)
        candidates = await asyncio.to_thread(list_candidates, browser)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"browser": browser, "profiles": [{"id": p.id, "label": p.label} for p in profiles],
            "candidates": candidates}


class VaultImportRequest(BaseModel):
    browser: str = "chrome"
    selected_ids: list[str]
    overwrite_confirmed: bool = False
    import_token: str | None = None


@router.post("/vault/import", dependencies=[Depends(_require_trusted_origin)])
async def import_browser_passwords(req: VaultImportRequest, services: AppServices | None = Depends(get_optional_app_services)) -> dict[str, Any]:
    """Import only explicitly selected browser rows into the encrypted local vault."""
    if len(req.selected_ids) > 500 or any(len(item) > 64 for item in req.selected_ids):
        raise HTTPException(status_code=422, detail="选择的条目数量或标识无效")
    from atlas.engine.agent.browser_password_import import import_selected
    store = await asyncio.to_thread(_vault_store, services)
    existing: dict[str, str] = {}
    for meta in await asyncio.to_thread(store.list_items):
        data = meta.to_dict() if hasattr(meta, "to_dict") else meta
        if data.get("kind") == "login" and data.get("origin"):
            existing[f"{data['origin']}\0{data.get('identifier') or ''}"] = str(data.get("id") or "")
    try:
        result = await asyncio.to_thread(import_selected, req.browser, req.selected_ids, store,
                                         existing_origins=existing,
                                         overwrite_confirmed=req.overwrite_confirmed)
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


class VaultCsvPreviewRequest(BaseModel):
    source: str = "Chrome / Edge CSV"
    csv_text: str


@router.post("/vault/import-preview", dependencies=[Depends(_require_trusted_origin)])
async def preview_browser_password_csv(req: VaultCsvPreviewRequest, services: AppServices | None = Depends(get_optional_app_services)) -> dict[str, Any]:
    """Keep an explicitly chosen password export in process memory for 15 minutes."""
    from atlas.engine.agent.browser_password_csv import preview_csv
    try:
        return await asyncio.to_thread(preview_csv, req.source, req.csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/vault/import-selected", dependencies=[Depends(_require_trusted_origin)])
async def import_selected_browser_passwords(req: VaultImportRequest, services: AppServices | None = Depends(get_optional_app_services)) -> dict[str, Any]:
    if not req.import_token:
        raise HTTPException(status_code=422, detail="缺少导入预览标识")
    from atlas.engine.agent.browser_password_csv import import_selected
    store = await asyncio.to_thread(_vault_store, services)
    try:
        return await asyncio.to_thread(import_selected, req.import_token, req.selected_ids, store,
                                       overwrite_confirmed=req.overwrite_confirmed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/vault/{item_id}/password", dependencies=[Depends(_require_trusted_origin)])
async def rotate_vault_password(item_id: str, req: VaultRotateRequest, services: AppServices | None = Depends(get_optional_app_services)) -> dict[str, bool]:
    if not req.password:
        raise HTTPException(status_code=422, detail="password is required")
    store = await asyncio.to_thread(_vault_store, services)
    try:
        updated = await asyncio.to_thread(store.rotate_login_password, item_id, req.password)
    except Exception as exc:  # noqa: BLE001 - vault errors contain metadata only
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="vault entry not found")
    return {"updated": True}


__all__ = ["router", "set_vault_store_factory"]
