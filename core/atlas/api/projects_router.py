"""Projects, project sources and message search surface (``/api/projects, /api/web/extract, /api/search``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import httpx
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()


def _server() -> Any:
    """Late-bound atlas.server: its module globals stay the seam tests patch."""
    import atlas.server

    return atlas.server


def _service(name: str, services: AppServices) -> Any:
    """Resolve an optional service: per-app container first, then the server module."""
    value = getattr(services, name, None)
    if value is None:
        value = getattr(_server(), name, None)
    return value


@router.get("/api/projects")
async def list_projects(
    services: Annotated[AppServices, Depends(get_app_services)],
    status: str | None = None,
    include_conversations: bool = Query(False),
) -> dict[str, Any]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    items = []
    for project in await projects.list_projects(status):
        item = project.to_dict()
        if include_conversations:
            item["conversation_ids"] = await projects.list_conversations(project.project_id)
        items.append(item)
    return {"projects": items}


@router.post("/api/projects", status_code=201)
async def create_project(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    try:
        project = await projects.create_project(
            str(req.get("name", "")),
            workspace_path=str(req.get("workspace_path", "") or ""),
            repo_url=str(req.get("repo_url", "") or ""),
            current_goal=str(req.get("current_goal", "") or ""),
            color=str(req.get("color", "") or ""),
            default_model=str(req.get("default_model", "") or ""),
            default_preset_id=str(req.get("default_preset_id", "") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return project.to_dict()


@router.post("/api/projects/import", status_code=201)
async def import_project(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    """Register an existing local directory without copying or changing its files."""
    projects = _service("projects", services)
    assert projects is not None
    raw_path = str(req.get("workspace_path") or "").strip()
    path = Path(raw_path)
    if not raw_path or not path.is_absolute() or not path.is_dir():
        raise HTTPException(status_code=400, detail="workspace_path must be an existing absolute directory")
    path = path.resolve()
    for existing in await projects.list_projects():
        if existing.workspace_path and Path(existing.workspace_path).resolve() == path:
            raise HTTPException(status_code=409, detail="workspace is already registered as a project")

    def origin_url() -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=3, check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    try:
        project = await projects.create_project(
            str(req.get("name") or path.name),
            workspace_path=str(path),
            repo_url=await asyncio.to_thread(origin_url),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return project.to_dict()


@router.get("/api/projects/recently-closed")
async def recently_closed_projects(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    projects = _service("projects", services)
    assert projects is not None
    return {"projects": [project.to_dict() for project in await projects.list_projects("archived")]}


@router.get("/api/projects/{project_id}")
async def get_project(
    services: Annotated[AppServices, Depends(get_app_services)],
    project_id: str,
) -> dict[str, Any]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    project = await projects.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = project.to_dict()
    result["conversation_ids"] = await projects.list_conversations(project_id)
    return result


@router.put("/api/projects/{project_id}")
async def update_project(
    services: Annotated[AppServices, Depends(get_app_services)],
    project_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    try:
        project = await projects.update_project(project_id, **req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.to_dict()


@router.post("/api/projects/{project_id}/close")
async def close_project(
    services: Annotated[AppServices, Depends(get_app_services)], project_id: str,
) -> dict[str, Any]:
    projects = _service("projects", services)
    assert projects is not None
    project = await projects.update_project(project_id, status="archived")
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.to_dict()


@router.post("/api/projects/{project_id}/reopen")
async def reopen_project(
    services: Annotated[AppServices, Depends(get_app_services)], project_id: str,
) -> dict[str, Any]:
    projects = _service("projects", services)
    assert projects is not None
    project = await projects.update_project(project_id, status="active")
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.to_dict()


@router.delete("/api/projects/{project_id}")
async def delete_project(
    services: Annotated[AppServices, Depends(get_app_services)],
    project_id: str,
    memory_action: str = Query(..., description="delete, global, or archive project memories"),
) -> dict[str, str]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    try:
        deleted = await projects.delete_project(project_id, memory_action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "ok", "project_id": project_id}


@router.get("/api/projects/{project_id}/memories")
async def project_memories(services: Annotated[AppServices, Depends(get_app_services)], project_id: str) -> dict[str, Any]:
    projects = _service("projects", services)
    rows = await projects.list_project_memories(project_id)
    if await projects.get(project_id) is None: raise HTTPException(404, "Project not found")
    return {"memories": rows}

@router.get("/api/projects/memories/global")
async def global_project_memories(services: Annotated[AppServices, Depends(get_app_services)], q: str = "") -> dict[str, Any]:
    projects = _service("projects", services)
    return {"memories": await projects.search_global_memories(q)}


@router.post("/api/projects/{project_id}/memories", status_code=201)
async def add_project_memory(services: Annotated[AppServices, Depends(get_app_services)], project_id: str, req: dict[str, Any]) -> dict[str, Any]:
    projects = _service("projects", services)
    try: return await projects.add_project_memory(project_id, str(req.get("text") or ""))
    except KeyError as exc: raise HTTPException(404, "Project not found") from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.post("/api/projects/{project_id}/memories/{memory_id}/move")
async def move_project_memory(services: Annotated[AppServices, Depends(get_app_services)], project_id: str, memory_id: str, req: dict[str, Any]) -> dict[str, Any]:
    projects = _service("projects", services)
    if not await projects.move_project_memory(memory_id, req.get("target_project_id")): raise HTTPException(404, "Memory not found")
    return {"status": "ok", "memory_id": memory_id}

@router.post("/api/projects/memories/global/{memory_id}/move/{project_id}")
async def move_global_project_memory(services: Annotated[AppServices, Depends(get_app_services)], memory_id: str, project_id: str) -> dict[str, Any]:
    projects = _service("projects", services)
    try: moved = await projects.move_global_memory(memory_id,project_id)
    except KeyError as exc: raise HTTPException(404,"Project not found") from exc
    if not moved: raise HTTPException(404,"Memory not found")
    return {"status":"ok","memory_id":memory_id}


@router.post("/api/projects/{project_id}/conversations", status_code=201)
async def attach_project_conversation(
    services: Annotated[AppServices, Depends(get_app_services)],
    project_id: str, req: dict[str, Any],
) -> dict[str, str]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    conversation_id = str(req.get("conversation_id", ""))
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")
    try:
        await projects.attach_conversation(project_id, conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "project_id": project_id, "conversation_id": conversation_id}


@router.delete("/api/projects/{project_id}/conversations/{conversation_id}")
async def detach_project_conversation(
    services: Annotated[AppServices, Depends(get_app_services)],
    project_id: str, conversation_id: str,
) -> dict[str, str]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    project = await projects.get(project_id)
    if project and project.memory_scope == "project-only":
        raise HTTPException(status_code=409, detail="This project uses project-only memory; move the project to global memory before detaching conversations")
    if not await projects.detach_conversation(project_id, conversation_id):
        raise HTTPException(status_code=404, detail="Association not found")
    return {"status": "ok"}


@router.get("/api/projects/{project_id}/recall")
async def project_recall(
    services: Annotated[AppServices, Depends(get_app_services)],
    project_id: str, query: str, limit: int = 8,
) -> dict[str, Any]:
    """Project-scoped raw session recall: project state + scoped session_search."""
    projects = _service("projects", services)
    assert projects is not None
    memory = _service("memory", services)
    assert memory is not None
    project = await projects.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    conversation_ids = await projects.list_conversations(project_id)
    results = await memory.session_search(
        query, limit=limit, conversation_ids=conversation_ids,
    )
    return {
        "project": project.to_dict(),
        "conversation_ids": conversation_ids,
        "results": results,
    }


@router.get("/api/projects/{project_id}/sources")
async def get_project_sources(
    services: Annotated[AppServices, Depends(get_app_services)],
    project_id: str,
) -> dict[str, Any]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    result = await projects.get_sources(project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="找不到这个项目。")
    return result


@router.put("/api/projects/{project_id}/sources/instructions")
async def put_project_source_instructions(
    services: Annotated[AppServices, Depends(get_app_services)],
    project_id: str, req: dict[str, Any],
) -> dict[str, str]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    instructions = req.get("instructions", "")
    if not isinstance(instructions, str):
        raise HTTPException(status_code=400, detail="项目指令必须是文字。")
    try:
        if not await projects.set_source_instructions(project_id, instructions):
            raise HTTPException(status_code=404, detail="找不到这个项目。")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "project_id": project_id}


async def _extract_project_url(
    services: Annotated[AppServices, Depends(get_app_services)],
    url: str,
) -> dict[str, Any]:
    return await _server().extract_web(url)


@router.post("/api/web/extract")
async def extract_web_endpoint(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    url = req.get("url")
    if not isinstance(url, str) or not url.strip():
        raise HTTPException(status_code=400, detail="请提供网页或视频地址。")
    allow_local = req.get("allow_local", False)
    if not isinstance(allow_local, bool):
        raise HTTPException(status_code=400, detail="本机页面选项无效。")
    try:
        return await _server().extract_web(url, allow_local=allow_local)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="暂时无法读取这个网页。") from exc


@router.post("/api/projects/{project_id}/sources", status_code=201)
async def post_project_source(
    services: Annotated[AppServices, Depends(get_app_services)],
    project_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    try:
        return await projects.add_source(
            project_id, str(req.get("kind", "")),
            title=str(req.get("title") or ""), path=req.get("path"),
            url=req.get("url"), text=req.get("text"),
            web_extractor=_extract_project_url,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="找不到这个项目。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/projects/{project_id}/sources/{source_id}")
async def delete_project_source(
    services: Annotated[AppServices, Depends(get_app_services)],
    project_id: str, source_id: str,
) -> dict[str, str]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    if not await projects.delete_source(project_id, source_id):
        raise HTTPException(status_code=404, detail="找不到这条项目资料。")
    return {"status": "deleted", "source_id": source_id}


@router.post("/api/projects/{project_id}/sources/{source_id}/refresh")
async def refresh_project_source(
    services: Annotated[AppServices, Depends(get_app_services)],
    project_id: str, source_id: str,
) -> dict[str, Any]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    try:
        result = await projects.refresh_source(
            project_id, source_id, web_extractor=_extract_project_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="找不到这条项目资料。")
    return result


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@router.get("/api/search")
async def search_messages(
    services: Annotated[AppServices, Depends(get_app_services)],
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Full-text search across all messages."""
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import search_session_messages

    matches = await asyncio.to_thread(
        search_session_messages, DATA_ROOT / "engine", q, limit=limit,
    )
    conversations = {
        str(item["id"]): item for item in await memory.list_conversations(limit=None)
    }
    return [{
        **item,
        "title": conversations.get(item["conversation_id"], {}).get("title", ""),
        "snippet": item.get("snippet") or item.get("context", ""),
    } for item in matches]
