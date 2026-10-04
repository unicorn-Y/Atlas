"""Projects, project sources and message search surface (``/api/projects, /api/web/extract, /api/search``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

import httpx
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

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
) -> dict[str, Any]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    return {"projects": [p.to_dict() for p in await projects.list_projects(status)]}


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
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return project.to_dict()


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


@router.delete("/api/projects/{project_id}")
async def delete_project(
    services: Annotated[AppServices, Depends(get_app_services)],
    project_id: str,
) -> dict[str, str]:
    projects = services.projects
    if projects is None:
        from atlas import server as _atlas_server

        projects = _atlas_server.projects
    assert projects is not None
    if not await projects.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "ok", "project_id": project_id}


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
    return await memory.search(q, limit=limit)
