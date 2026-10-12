"""Read-only declarative contributions for installed Atlas plugins.

Plugins contribute data, never executable renderer code. Atlas renders only the
small widget/command vocabulary implemented by its own host.
"""

from __future__ import annotations

from typing import Annotated, Any
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.plugins.runtime import _manifest

router = APIRouter(prefix="/api/plugins/host", tags=["plugin-host"])
_SURFACES = ("settingsPages", "menuItems", "commands", "keybinds", "views")


class PluginHostAction(BaseModel):
    page_id: str = Field(min_length=1, max_length=128)
    widget_id: str = Field(min_length=1, max_length=128)
    confirmed: bool = False


def _enabled_plugin(runtime: Any, name: str) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    plugin = next((item for item in runtime.discover() if item.get("name") == name), None)
    if not plugin or not plugin.get("enabled"):
        raise HTTPException(status_code=404, detail="Enabled plugin not found")
    root = runtime._plugin_root(Path(str(plugin.get("path", ""))))
    if root is None:
        raise HTTPException(status_code=404, detail="Plugin directory is unavailable")
    _, manifest = _manifest(root)
    return plugin, root, manifest


def _runtime(services: AppServices) -> Any:
    if services.plugin_runtime is not None:
        return services.plugin_runtime
    import atlas.server

    return getattr(atlas.server, "plugin_runtime", None)


@router.get("")
async def list_host_contributions(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Return validated declarative contributions from enabled local plugins."""
    runtime = _runtime(services)
    if runtime is None:
        return {key: [] for key in _SURFACES}
    result: dict[str, list[dict[str, Any]]] = {key: [] for key in _SURFACES}
    for plugin in runtime.discover():
        if not plugin.get("enabled"):
            continue
        try:
            _, root, manifest = _enabled_plugin(runtime, str(plugin.get("name", "")))
        except HTTPException:
            continue
        declared = manifest.get("atlasHost", {})
        if not isinstance(declared, dict):
            continue
        for surface in _SURFACES:
            values = declared.get(surface, [])
            if not isinstance(values, list):
                continue
            for item in values[:100]:
                if not isinstance(item, dict):
                    continue
                identity = str(item.get("id", "")).strip()
                title = str(item.get("title", item.get("label", ""))).strip()
                if not identity or not title or len(identity) > 128 or len(title) > 160:
                    continue
                result[surface].append({
                    **{key: value for key, value in item.items()
                       if key in {"id", "title", "label", "description", "route", "command", "shortcut", "widgets", "action"}},
                    "id": identity,
                    "title": title,
                    "plugin": str(plugin.get("name", "")),
                    "plugin_title": str(plugin.get("display_name", plugin.get("name", ""))),
                })
    return result


@router.post("/{plugin_name}/actions/mcp")
async def call_confirmed_mcp_action(
    plugin_name: str,
    body: PluginHostAction,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Run only an MCP action declared on an enabled plugin widget after user confirmation."""
    if not body.confirmed:
        raise HTTPException(status_code=409, detail="User confirmation is required")
    runtime = _runtime(services)
    client = services.mcp_client
    if runtime is None or client is None:
        raise HTTPException(status_code=503, detail="Plugin or MCP host is unavailable")
    _, _, manifest = _enabled_plugin(runtime, plugin_name)
    host = manifest.get("atlasHost")
    pages = host.get("settingsPages", []) if isinstance(host, dict) else []
    page = next((item for item in pages if isinstance(item, dict) and item.get("id") == body.page_id), None) if isinstance(pages, list) else None
    widgets = page.get("widgets", []) if isinstance(page, dict) else []
    widget = next((item for item in widgets if isinstance(item, dict) and item.get("id") == body.widget_id), None) if isinstance(widgets, list) else None
    action = widget.get("action") if isinstance(widget, dict) else None
    if not isinstance(action, dict) or action.get("type") != "mcp_tool_call":
        raise HTTPException(status_code=422, detail="Widget does not declare a supported MCP action")
    server, tool = str(action.get("server", "")).strip(), str(action.get("tool", "")).strip()
    arguments = action.get("arguments", {})
    if not server or not tool or not isinstance(arguments, dict):
        raise HTTPException(status_code=422, detail="MCP action declaration is invalid")
    result = await client.call_tool(f"{server}__{tool}", arguments)
    text = "\n".join(str(item.get("text", "")) for item in result.get("content", []) if isinstance(item, dict))
    return {"is_error": bool(result.get("is_error")), "follow_up": text[:4000]}


__all__ = ["router"]
