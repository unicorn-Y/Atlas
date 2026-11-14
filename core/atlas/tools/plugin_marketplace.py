# Behavior references: OpenAI Codex plugin tools documentation (`list_plugins`,
# `request_plugin_install`) and Atlas's existing `PluginRuntime` API. This module
# adds a narrow adapter and does not copy third-party marketplace implementation.
"""Model-callable view of the Atlas plugin marketplace runtime."""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any

from atlas.approval_outcome import ALLOWED, normalize as normalize_approval


PLUGIN_MANAGER_TOOLS = frozenset({
    "list_plugins", "get_plugin", "list_plugin_marketplaces",
    "list_available_plugins_to_install", "request_plugin_install", "update_plugin",
    "set_plugin_enabled", "uninstall_plugin",
})
_PLUGIN_MANAGER_WRITES = frozenset({
    "request_plugin_install", "update_plugin", "set_plugin_enabled", "uninstall_plugin",
})


def plugin_runtime_for(agent: Any) -> Any:
    runtime = getattr(agent, "_plugin_runtime", None)
    if runtime is not None:
        return runtime
    from atlas.config import PROJECT_ROOT, get_config
    from atlas.plugins import PluginRuntime

    state_path = get_config().db_path.parent / "plugins" / "state.json"
    runtime = PluginRuntime(
        [PROJECT_ROOT / "plugins", state_path.parent], state_path,
    )
    agent._plugin_runtime = runtime
    return runtime


async def execute_plugin_manager_tool(
    name: str, arguments: dict[str, Any], *, agent: Any, approve: Any = None,
    permission_mode: str | None = None,
) -> dict[str, Any]:
    """Run one plugin-manager action; every mutation requires this-call approval.

    ``permission_mode`` mirrors the run's permission preset: ``read_only``
    denies every mutation outright, ``danger-full-access`` is the documented
    bypass that runs a mutation without prompting, and any other mode keeps
    the per-call approval gate.
    """
    if name not in PLUGIN_MANAGER_TOOLS:
        return {"content": f"Unknown plugin manager action: {name}", "is_error": True,
                "outcome": "failed"}
    plugin_runtime = plugin_runtime_for(agent)
    if name in _PLUGIN_MANAGER_WRITES:
        if permission_mode == "read_only":
            return {"content": "Plugin management writes are denied in read-only mode.",
                    "is_error": True, "outcome": "denied"}
        if permission_mode != "danger-full-access":
            if not callable(approve):
                return {"content": "Plugin management writes require per-call user approval.",
                        "is_error": True, "outcome": "denied"}
            try:
                decision = approve(name, dict(arguments))
                if hasattr(decision, "__await__"):
                    decision = await decision
            except Exception as exc:
                return {"content": f"Plugin management approval failed: {exc}", "is_error": True,
                        "outcome": "denied"}
            if normalize_approval(decision) != ALLOWED:
                return {"content": "Plugin management action was not approved.", "is_error": True,
                        "outcome": "denied"}

    try:
        if name == "list_plugins":
            query = str(arguments.get("query") or "").casefold()
            limit = max(1, min(100, int(arguments.get("limit", 50))))
            plugins = plugin_runtime.discover()
            if query:
                plugins = [item for item in plugins if query in (
                    f"{item.get('name', '')} {item.get('description', '')}"
                ).casefold()]
            result = {"plugins": plugins[:limit]}
        elif name == "get_plugin":
            plugin_name = str(arguments.get("plugin_name") or "")
            plugin = next((item for item in plugin_runtime.discover()
                           if item.get("name") == plugin_name), None)
            if plugin is None:
                raise KeyError(plugin_name)
            result = {"plugin": plugin}
        elif name == "list_plugin_marketplaces":
            result = {"marketplaces": plugin_runtime.list_marketplaces()}
        elif name == "list_available_plugins_to_install":
            marketplace_filter = str(arguments.get("marketplace") or "")
            query = str(arguments.get("query") or "").casefold()
            limit = max(1, min(100, int(arguments.get("limit", 50))))
            installed = {item.get("name") for item in plugin_runtime.discover()}
            plugins = []
            for marketplace in plugin_runtime.list_marketplaces():
                market_name = str(marketplace.get("name") or "")
                if marketplace_filter and market_name != marketplace_filter:
                    continue
                for item in plugin_runtime.list_marketplace_plugins(market_name):
                    plugin_name = str(item.get("name") or "")
                    if (not plugin_name or plugin_name in installed
                            or (query and query not in f"{plugin_name} {item.get('description', '')}".casefold())):
                        continue
                    plugins.append({key: item[key] for key in (
                        "name", "description", "version", "marketplace", "source",
                    ) if key in item})
            result = {"plugins": plugins[:limit]}
        elif name == "request_plugin_install":
            result = await asyncio.to_thread(
                plugin_runtime.install_marketplace_plugin,
                str(arguments.get("marketplace") or ""),
                str(arguments.get("plugin_name") or ""),
            )
            result["load_report"] = await plugin_runtime.load_all(
                hook_bus=getattr(agent, "hooks", None),
                mcp_client=getattr(agent, "_mcp", None),
                capabilities=getattr(agent, "capabilities", None),
            )
        elif name == "update_plugin":
            result = await asyncio.to_thread(
                plugin_runtime.update, str(arguments.get("plugin_name") or ""),
            )
            result["load_report"] = await plugin_runtime.load_all(
                hook_bus=getattr(agent, "hooks", None),
                mcp_client=getattr(agent, "_mcp", None),
                capabilities=getattr(agent, "capabilities", None),
            )
        elif name == "set_plugin_enabled":
            plugin_name = str(arguments.get("plugin_name") or "")
            enabled = arguments.get("enabled")
            if not isinstance(enabled, bool):
                raise ValueError("enabled must be a boolean")
            if enabled:
                plugin = next((item for item in plugin_runtime.discover()
                               if item.get("name") == plugin_name), None)
                if plugin is None:
                    raise KeyError(plugin_name)
                validation = await asyncio.to_thread(plugin_runtime.validate, plugin["path"])
                if not validation.get("valid"):
                    raise ValueError("plugin manifest validation failed")
            await plugin_runtime.set_enabled(plugin_name, enabled)
            result = {"name": plugin_name, "enabled": enabled}
            report = await plugin_runtime.load_all(
                hook_bus=getattr(agent, "hooks", None),
                mcp_client=getattr(agent, "_mcp", None),
                capabilities=getattr(agent, "capabilities", None),
            )
            result["load_report"] = report
            skipped = {item.get("name") for item in report.get("skipped", [])
                       if isinstance(item, dict)}
            result["applied"] = (
                plugin_name in report.get("loaded", []) if enabled
                else plugin_name in skipped and not report.get("errors", {}).get(plugin_name)
            )
            result["restart_required"] = False
        else:  # uninstall_plugin
            plugin_name = str(arguments.get("plugin_name") or "")
            if not any(item.get("name") == plugin_name for item in plugin_runtime.discover()):
                raise KeyError(plugin_name)
            await plugin_runtime.set_enabled(plugin_name, False)
            removed = await asyncio.to_thread(plugin_runtime.uninstall, plugin_name)
            result = {"name": plugin_name, "removed": bool(removed)}
            result["load_report"] = await plugin_runtime.load_all(
                hook_bus=getattr(agent, "hooks", None),
                mcp_client=getattr(agent, "_mcp", None),
                capabilities=getattr(agent, "capabilities", None),
            )
        return {"content": json.dumps(result, ensure_ascii=False, default=str),
                "data": result, "outcome": "completed"}
    except (KeyError, OSError, RuntimeError, ValueError, PermissionError,
            subprocess.SubprocessError) as exc:
        return {"content": str(exc), "is_error": True, "outcome": "failed"}
