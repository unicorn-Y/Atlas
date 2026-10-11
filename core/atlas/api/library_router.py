"""技能与工具库：分类浏览、一键整理、导入网页 GPT 搜罗结果、按需安装。"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.library import runtime as lib

router = APIRouter()


def _svc(services: AppServices, name: str) -> Any:
    value = getattr(services, name, None)
    if value is None:
        import atlas.server

        value = getattr(atlas.server, name, None)
    return value


def _items(services: AppServices, kind: str) -> list[dict[str, Any]]:
    store = lib.get_store()
    if kind == "skill":
        return lib.skill_items(_svc(services, "skill_mgr"), store)
    mcp = _svc(services, "mcp_client")
    return lib.tool_items(lib.all_tool_schemas(_svc(services, "orchestrator")),
                          lib._configured_servers(mcp), store)


@router.get("/api/library")
async def get_library(
    services: Annotated[AppServices, Depends(get_app_services)],
    kind: str = Query("skill", pattern="^(skill|tool)$"),
) -> dict[str, Any]:
    store = lib.get_store()
    items = await asyncio.to_thread(_items, services, kind)
    counts: dict[str, int] = {}
    for item in items:
        counts[item["category"] or ""] = counts.get(item["category"] or "", 0) + 1
    categories = [row | {"count": counts.get(row["id"], 0)} for row in store.categories()]
    return {
        "kind": kind, "items": items, "categories": categories,
        "unorganized": counts.get("", 0), "installed": sum(i["status"] == "installed" for i in items),
        "available": sum(i["status"] == "available" for i in items),
        "inbox": str(store.inbox), "last_report": store.last_report(),
    }


class OrganizeRequest(BaseModel):
    full: bool = False
    use_model: bool = True


@router.post("/api/library/organize")
async def organize(services: Annotated[AppServices, Depends(get_app_services)],
                   req: OrganizeRequest = Body(default_factory=OrganizeRequest)) -> dict[str, Any]:
    return await lib.organize_library(
        _svc(services, "skill_mgr"), _svc(services, "orchestrator"), _svc(services, "mcp_client"),
        _svc(services, "model_mgr"), full=req.full, use_model=req.use_model,
    )


class ImportRequest(BaseModel):
    text: str = ""


@router.post("/api/library/import")
async def import_catalog(req: ImportRequest = Body(default_factory=ImportRequest)) -> dict[str, Any]:
    store = lib.get_store()
    try:
        if req.text.strip():
            result = await asyncio.to_thread(store.import_text, req.text)
        else:
            result = await asyncio.to_thread(store.import_inbox)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"内容不是合法的 JSON / JSONL：{exc}") from exc
    return result | {"inbox": str(store.inbox)}


class CategoryRequest(BaseModel):
    name: str
    description: str = ""


@router.post("/api/library/categories")
async def add_category(req: CategoryRequest) -> dict[str, Any]:
    try:
        return lib.get_store().add_category(req.name, description=req.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class CategoryPatch(BaseModel):
    name: str | None = None
    description: str | None = None


@router.patch("/api/library/categories/{category_id}")
async def update_category(category_id: str, req: CategoryPatch) -> dict[str, Any]:
    try:
        return lib.get_store().update_category(category_id, name=req.name, description=req.description)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分类不存在") from exc


@router.delete("/api/library/categories/{category_id}")
async def delete_category(category_id: str) -> dict[str, Any]:
    try:
        return {"released": lib.get_store().delete_category(category_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分类不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class AssignRequest(BaseModel):
    key: str
    category: str | None = None


@router.post("/api/library/assign")
async def assign(req: AssignRequest) -> dict[str, Any]:
    store = lib.get_store()
    if not req.category:
        store.clear_assignment(req.key)
        return {"key": req.key, "category": None}
    try:
        store.assign(req.key, req.category, by="manual")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分类不存在") from exc
    return {"key": req.key, "category": req.category}


@router.post("/api/library/skills/{name}/install")
async def install_skill(services: Annotated[AppServices, Depends(get_app_services)], name: str) -> dict[str, Any]:
    try:
        ok = await lib.ensure_skill(_svc(services, "skill_mgr"), name)
    except Exception as exc:  # noqa: BLE001 — network / GitHub errors go back to the UI
        raise HTTPException(status_code=502, detail=f"下载失败：{exc}") from exc
    if not ok:
        raise HTTPException(status_code=404, detail="库里没有这个技能，或者下载后解析失败")
    return {"name": name, "installed": True}


class ToolInstallRequest(BaseModel):
    env: dict[str, str] = {}


@router.post("/api/library/tools/{name}/install")
async def install_tool(services: Annotated[AppServices, Depends(get_app_services)], name: str,
                       req: ToolInstallRequest = Body(default_factory=ToolInstallRequest)) -> dict[str, Any]:
    from atlas.api.tools_router import MCPServerAddRequest, add_mcp_server

    entry = lib.get_store().catalog_entry(f"tool:{name}")
    if entry is None:
        raise HTTPException(status_code=404, detail="库里没有这个工具")
    if entry.get("kind", "mcp") != "mcp":
        raise HTTPException(status_code=400, detail="命令行工具请按说明手动安装")
    missing = [key for key in entry.get("env_required") or [] if not str(req.env.get(key, "")).strip()]
    if missing:
        raise HTTPException(status_code=400, detail="需要先填：" + "、".join(missing))
    install = entry.get("install") if isinstance(entry.get("install"), dict) else None
    if install and install.get("command"):
        add = MCPServerAddRequest(name=name, transport="stdio", command=str(install["command"]),
                                  args=[str(a) for a in install.get("args") or []], env=req.env)
    elif entry.get("remote_url"):
        add = MCPServerAddRequest(name=name, transport="http", url=str(entry["remote_url"]), env=req.env)
    else:
        raise HTTPException(status_code=400, detail="这个条目没有可用的启动方式")
    return await add_mcp_server(services, add)


class RemoveRequest(BaseModel):
    key: str


@router.post("/api/library/catalog/remove")
async def remove_catalog_entry(req: RemoveRequest) -> dict[str, Any]:
    return {"removed": lib.get_store().remove_catalog_entry(req.key)}
