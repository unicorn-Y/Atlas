"""Plugin lifecycle, marketplaces and external import surface (``/api/plugins, /api/plugin-marketplaces, /api/import``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

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


@router.post("/api/plugins/check-updates")
async def check_plugin_updates(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Refresh remote Git source state and return any retryable network failures."""
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        updates = await asyncio.to_thread(plugin_runtime.check_updates)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=502, detail=f"插件来源检查失败：{exc}") from exc
    return {"updates": updates, "plugins": plugin_runtime.discover()}


@router.post("/api/plugins/validate")
async def validate_plugin_manifest(
    services: Annotated[AppServices, Depends(get_app_services)], req: dict[str, Any],
) -> dict[str, Any]:
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    source = str(req.get("source") or req.get("path") or "").strip()
    if not source:
        raise HTTPException(status_code=422, detail="source is required")
    try:
        return await asyncio.to_thread(plugin_runtime.validate, source)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"插件清单校验失败：{exc}") from exc


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
        validation = await asyncio.to_thread(plugin_runtime.validate_source, source)
        if not validation["valid"]:
            raise HTTPException(status_code=422, detail={"message": "插件清单校验未通过", "validation": validation})
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
        validation = await asyncio.to_thread(
            plugin_runtime.validate_source, str(req.get("source", "")), ref=req.get("ref"),
        )
        if not validation["valid"]:
            raise HTTPException(status_code=422, detail={"message": "插件清单校验未通过", "validation": validation})
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


@router.post("/api/plugins/{name}/reload")
async def reload_plugin(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    """Re-read one plugin's files without restarting the backend.

    Editing a plugin meant restarting everything before this: the skill text is
    read once at load time, so a saved edit had no effect until the process died.
    This reuses the same wiring ``load_all`` built (hook bus, MCP client, capability
    registry), so a reload also *removes* the capabilities the old version
    registered — without that, every reload would stack a duplicate set and
    ``register`` would start refusing names.
    """
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        result = await plugin_runtime.reload(name)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("ok"):
        # 404 only when the plugin genuinely is not there; a malformed edit is a
        # 400, because "not found" would send the user looking in the wrong place.
        status = 404 if "not found" in str(result.get("error", "")) else 400
        raise HTTPException(status_code=status, detail=result.get("error"))
    return {**result, "report": await _server()._reload_extensions()}


@router.get("/api/plugins/{name}/patches")
async def list_plugin_patches(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    """List local overrides that survive an upgrade of this plugin."""
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        return plugin_runtime.list_patches(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="插件不存在") from exc


@router.put("/api/plugins/{name}/patches")
async def write_plugin_patch(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
    req: dict[str, Any],
) -> dict[str, Any]:
    """Save a local edit as a patch instead of editing the installed file.

    Editing ``plugins/<name>/skills/x/SKILL.md`` directly looks like it works and
    then loses the change on the next upgrade, because ``_copy_replace`` swaps the
    directory. Writing here keeps the original recoverable and re-applies the edit
    after upgrading, which is the behaviour a user expects from "my tweak".

    The response carries the re-load report because a patched ``SKILL.md`` that
    nobody re-read is invisible until restart; reloading here makes the edit
    actually take effect in the running process.
    """
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    relative = str(req.get("path") or "").strip()
    content = req.get("content")
    if not relative or not isinstance(content, str):
        raise HTTPException(status_code=400, detail="需要 path 与 content")
    try:
        result = plugin_runtime.patch_file(
            name, relative, content, note=str(req.get("note") or ""),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="插件不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    report = await _server()._reload_extensions()
    reloaded = await plugin_runtime.reload(name)
    return {**result, "report": report, "reload": reloaded}


@router.delete("/api/plugins/{name}/patches")
async def revert_plugin_patch(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
    path: str | None = None,
) -> dict[str, Any]:
    """Drop one override (``?path=``) or every override for the plugin."""
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        result = plugin_runtime.revert_patch(name, path or None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="插件不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    report = await _server()._reload_extensions()
    return {**result, "report": report}


@router.get("/api/plugins/{name}/file")
async def read_plugin_file(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
    path: str,
) -> dict[str, Any]:
    """Read a plugin file *as it currently behaves*, patch included.

    Reading the file off disk would show the shipped bytes while the plugin runs
    the patched ones — the reader and the runtime would disagree, which is how a
    patch ends up looking like it did nothing.
    """
    plugin_runtime = _service("plugin_runtime", services)
    if plugin_runtime is None:
        raise HTTPException(status_code=503, detail="插件服务尚未就绪")
    try:
        content = plugin_runtime.effective_text(name, path)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="插件不存在") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": name, "path": path, "content": content}


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
        validation = await asyncio.to_thread(plugin_runtime.validate_marketplace_plugin, name, str(req.get("plugin", "")))
        if not validation["valid"]:
            raise HTTPException(status_code=422, detail={"message": "插件清单校验未通过", "validation": validation})
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
    if not any(item["name"] == name for item in plugin_runtime.discover()):
        raise HTTPException(status_code=404, detail="插件不存在")
    enabled = bool(req.get("enabled", True))
    if enabled:
        plugin = next(item for item in plugin_runtime.discover() if item["name"] == name)
        validation = await asyncio.to_thread(plugin_runtime.validate, str(plugin["path"]))
        if not validation["valid"]:
            raise HTTPException(status_code=409, detail={"message": "插件清单校验未通过，已保持停用", "validation": validation})
    await plugin_runtime.set_enabled(name, enabled)
    report = await _server()._reload_extensions()
    return {"name": name, "enabled": enabled, "report": report}


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
