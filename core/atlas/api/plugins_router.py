"""Plugin lifecycle, marketplaces and external import surface (``/api/plugins, /api/plugin-marketplaces, /api/import``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import asyncio
import subprocess
from pathlib import Path

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



@router.get("/api/plugins")
async def list_plugins(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    """List discovered local plugin bundles with their runtime state."""
    if plugin_runtime is None:
        return {"plugins": []}
    return {"plugins": plugin_runtime.discover()}


@router.post("/api/plugins/install-local")
async def install_local_plugin(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    """Install a plugin from a local directory into the user plugin folder."""
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="Plugin runtime unavailable")
    source = str(req.get("path", ""))
    if not source:
        raise HTTPException(status_code=400, detail="path is required")
    try:
        result = plugin_runtime.install_local(source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["report"] = await _server()._reload_extensions()
    return result


@router.post("/api/plugins/install")
async def install_plugin(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        result = await asyncio.to_thread(
            plugin_runtime.install, str(req.get("source", "")),
            name=req.get("name"), ref=req.get("ref"),
        )
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "report": await _server()._reload_extensions()}


@router.post("/api/plugins/{name}/update")
async def update_plugin(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        result = await asyncio.to_thread(plugin_runtime.update, name)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "report": await _server()._reload_extensions()}


@router.delete("/api/plugins/{name}")
async def uninstall_plugin(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        removed = await asyncio.to_thread(plugin_runtime.uninstall, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="插件不存在")
    return {"name": name, "removed": True, "report": await _server()._reload_extensions()}


@router.get("/api/plugin-marketplaces")
async def list_plugin_marketplaces(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    return {"marketplaces": plugin_runtime.list_marketplaces() if plugin_runtime else []}


@router.post("/api/plugin-marketplaces")
async def add_plugin_marketplace(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        return await asyncio.to_thread(
            plugin_runtime.add_marketplace, str(req.get("source", "")),
            name=req.get("name"), ref=req.get("ref"),
        )
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/plugin-marketplaces/{name}/update")
async def update_plugin_marketplace(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    """Update a registered git marketplace without accepting a caller-supplied path."""
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        return await asyncio.to_thread(plugin_runtime.update_marketplace, name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0] if exc.args else exc)) from exc
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/plugin-marketplaces/{name}/validate")
async def validate_plugin_marketplace(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        return plugin_runtime.validate_marketplace(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0] if exc.args else exc)) from exc


@router.delete("/api/plugin-marketplaces/{name}")
async def remove_plugin_marketplace(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        return plugin_runtime.remove_marketplace(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0] if exc.args else exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/plugin-marketplaces/{name}/plugins")
async def list_marketplace_plugins(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        return {"plugins": plugin_runtime.list_marketplace_plugins(name)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0] if exc.args else exc)) from exc


@router.post("/api/plugin-marketplaces/{name}/install")
async def install_marketplace_plugin(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str, req: dict[str, Any],
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        result = await asyncio.to_thread(
            plugin_runtime.install_marketplace_plugin, name, str(req.get("plugin", "")),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0] if exc.args else exc)) from exc
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "report": await _server()._reload_extensions()}


@router.post("/api/plugins/{name}/enabled")
async def set_plugin_enabled(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str, req: dict[str, Any],
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    """Enable or disable a plugin and reapply every plugin to the runtime."""
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="Plugin runtime unavailable")
    scope = req.get("scope", "user")
    if scope != "user":
        raise HTTPException(status_code=422, detail={
            "code": "scope_unavailable",
            "message": "Atlas loads plugins through a process-wide PluginRuntime and has no request-scoped workspace loader; only user scope can be changed.",
        })
    enabled = req.get("enabled", True)
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="enabled must be a boolean")
    if not any(item["name"] == name for item in plugin_runtime.discover()):
        raise HTTPException(status_code=404, detail="插件不存在")
    plugin_runtime.set_enabled(name, enabled)
    report = await _server()._reload_extensions()
    return {"name": name, "scope": "user", "enabled": enabled, "report": report}


@router.post("/api/plugins/reset")
async def reset_plugin_overrides(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    scope = str((req or {}).get("scope", "user"))
    if scope != "user":
        raise HTTPException(status_code=422, detail={
            "code": "scope_unavailable",
            "message": "Atlas loads plugins through a process-wide PluginRuntime and has no request-scoped workspace loader; only user scope can be reset.",
        })
    result = plugin_runtime.reset_user_overrides()
    result["report"] = await _server()._reload_extensions()
    return result


_EXTERNAL_IMPORT_SOURCES = {"claude", "codex"}


@router.get("/api/import/external/scan")
async def scan_external_import(
    services: Annotated[AppServices, Depends(get_app_services)],
    source: str, workspace: str | None = None,
) -> dict[str, Any]:
    """Scan a Claude Code / Codex profile and list the importable items."""
    if source not in _EXTERNAL_IMPORT_SOURCES:
        raise HTTPException(status_code=422, detail="source must be claude or codex")
    try:
        from atlas.runtime.external_import import scan_external
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail=f"external import module unavailable: {exc}",
        ) from exc
    return await asyncio.to_thread(
        scan_external, source,
        workspace=Path(workspace).expanduser() if workspace else None,
    )


@router.post("/api/import/external")
async def run_external_import(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    """Import user-selected items from Claude Code / Codex; source dirs are read-only."""
    source = str(req.get("source", ""))
    items = req.get("items")
    if source not in _EXTERNAL_IMPORT_SOURCES or not isinstance(items, list):
        raise HTTPException(
            status_code=422,
            detail="source must be claude or codex and items must be a list",
        )
    try:
        from atlas.runtime.external_import import import_external
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail=f"external import module unavailable: {exc}",
        ) from exc
    return await asyncio.to_thread(
        import_external, source, items,
        workspace=Path(str(req["workspace"])).expanduser() if req.get("workspace") else None,
    )
