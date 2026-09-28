"""Local plugin bundle runtime.

A plugin is a directory following the ZCode plugin layout::

    my-plugin/
        plugin.json          # {"name": ..., "version": ..., "description": ...}
        skills/<skill>/SKILL.md
        commands/<command>.md
        hooks/hooks.json     # {"hooks": [{"point": ..., "command": [...]}]}
        agents/              # recorded for later waves
        .mcp.json            # {"mcpServers": {name: {transport, command, args, ...}}}

Operations: discover, install-local, enable/disable, load/unload into the live
runtime (skills and commands become agent capabilities, hooks register on the
HookBus, MCP servers connect through MCPClient). Loaded plugins are reapplied
on every startup.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from atlas.agent.enrichment import HOOK_POINTS

MANIFEST_NAME = "plugin.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


class PluginRuntime:
    """Discover, enable/disable, and load local plugin bundles."""

    def __init__(self, plugin_dirs: list[Path], state_path: Path) -> None:
        self._dirs = [Path(d) for d in plugin_dirs]
        self._state_path = Path(state_path)
        self._enabled: dict[str, bool] = {}
        self._loaded: dict[str, dict[str, Any]] = {}
        self._load_state()

    # ----- state -----

    def _load_state(self) -> None:
        state = _read_json(self._state_path)
        enabled = state.get("enabled")
        self._enabled = enabled if isinstance(enabled, dict) else {}

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps({"enabled": self._enabled}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ----- discovery -----

    def _plugin_root(self, path: Path) -> Path | None:
        if (path / MANIFEST_NAME).is_file():
            return path
        nested = path / MANIFEST_NAME
        for child in sorted(path.glob(f"*/{MANIFEST_NAME}")) if path.is_dir() else []:
            if child.is_file():
                return child.parent
        del nested
        return None

    def discover(self) -> list[dict[str, Any]]:
        """Return every plugin manifest found, with current enabled/loaded state."""
        plugins: dict[str, dict[str, Any]] = {}
        for base in self._dirs:
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir()):
                root = self._plugin_root(child)
                if root is None:
                    continue
                manifest = _read_json(root / MANIFEST_NAME)
                name = str(manifest.get("name") or root.name)
                plugins[name] = {
                    "name": name,
                    "version": str(manifest.get("version", "0.0.0")),
                    "description": str(manifest.get("description", "")),
                    "path": str(root),
                    "skills": [
                        item.name for item in sorted((root / "skills").iterdir())
                        if item.is_dir() and (item / "SKILL.md").is_file()
                    ] if (root / "skills").is_dir() else [],
                    "commands": [
                        item.stem for item in sorted((root / "commands").glob("*.md"))
                    ] if (root / "commands").is_dir() else [],
                    "hooks": len([
                        spec for spec in self._hook_specs(root)
                        if str(spec.get("point", "")) in HOOK_POINTS
                    ]),
                    "mcp_servers": sorted(
                        (_read_json(root / ".mcp.json").get("mcpServers") or {}).keys(),
                    ),
                    "agents_dir": (root / "agents").is_dir(),
                    "enabled": self._enabled.get(name, True),
                    "loaded": name in self._loaded,
                }
        return list(plugins.values())

    @staticmethod
    def _hook_specs(root: Path) -> list[dict[str, Any]]:
        data = _read_json(root / "hooks" / "hooks.json")
        hooks = data.get("hooks")
        return [item for item in hooks if isinstance(item, dict)] if isinstance(
            hooks, list,
        ) else []

    # ----- install / enable -----

    def install_local(self, source: str | Path) -> dict[str, Any]:
        """Copy a local plugin directory into the user plugin directory."""
        source_root = self._plugin_root(Path(source))
        if source_root is None:
            raise ValueError(f"no {MANIFEST_NAME} found under {source}")
        manifest = _read_json(source_root / MANIFEST_NAME)
        name = str(manifest.get("name") or source_root.name)
        target_base = self._dirs[-1] if self._dirs else Path("data") / "plugins"
        target = target_base / source_root.name
        if target.exists():
            shutil.rmtree(target)
        target_base.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_root, target)
        return {"name": name, "path": str(target)}

    def set_enabled(self, name: str, enabled: bool) -> bool:
        self._enabled[name] = enabled
        self._save_state()
        if not enabled:
            self._loaded.pop(name, None)
        return True

    # ----- load -----

    async def load_all(
        self,
        *,
        hook_bus: Any = None,
        mcp_client: Any = None,
        capabilities: Any = None,
    ) -> dict[str, Any]:
        """(Re)apply every enabled plugin to the live runtime."""
        report: dict[str, Any] = {"loaded": [], "skipped": [], "errors": {}}
        self._loaded.clear()
        for plugin in self.discover():
            name = plugin["name"]
            if not plugin["enabled"]:
                report["skipped"].append({"name": name, "reason": "disabled"})
                continue
            try:
                self._loaded[name] = await self._load_one(
                    Path(plugin["path"]),
                    plugin_name=name,
                    hook_bus=hook_bus,
                    mcp_client=mcp_client,
                    capabilities=capabilities,
                )
                report["loaded"].append(name)
            except Exception as exc:
                report["errors"][name] = str(exc)
        return report

    async def _load_one(
        self,
        root: Path,
        *,
        plugin_name: str,
        hook_bus: Any,
        mcp_client: Any,
        capabilities: Any,
    ) -> dict[str, Any]:
        loaded: dict[str, Any] = {"skills": [], "commands": [], "hooks": 0, "mcp": []}

        for skill in (root / "skills").iterdir() if (root / "skills").is_dir() else []:
            skill_md = skill / "SKILL.md"
            if not skill_md.is_file():
                continue
            loaded["skills"].append(skill.name)
            if capabilities is not None:
                content = skill_md.read_text(encoding="utf-8", errors="replace")
                capabilities.register(
                    f"plugin.{plugin_name}.skill.{skill.name}",
                    description=f"Skill from plugin {plugin_name}.",
                    handler=lambda _inputs, _content=content: {"content": _content},
                    source=f"plugin:{plugin_name}",
                )

        for command in (root / "commands").glob("*.md"):
            loaded["commands"].append(command.stem)
            if capabilities is not None:
                content = command.read_text(encoding="utf-8", errors="replace")
                capabilities.register(
                    f"plugin.{plugin_name}.command.{command.stem}",
                    description=f"Command prompt from plugin {plugin_name}.",
                    handler=lambda _inputs, _content=content: {"prompt": _content},
                    source=f"plugin:{plugin_name}",
                )

        for spec in self._hook_specs(root):
            point = str(spec.get("point", ""))
            command = spec.get("command")
            if point not in HOOK_POINTS or not isinstance(command, list) or not command:
                continue
            argv = [str(arg) for arg in command]

            def _handler(_argv: list[str] = argv, **payload: Any) -> None:
                try:
                    subprocess.run(
                        _argv,
                        input=json.dumps(payload, ensure_ascii=False, default=str),
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError):
                    return

            if hook_bus is not None:
                hook_bus.register(point, _handler)
            loaded["hooks"] += 1

        mcp_servers = _read_json(root / ".mcp.json").get("mcpServers")
        if isinstance(mcp_servers, dict) and mcp_client is not None:
            from atlas.tools.mcp_client import MCPServerConfig

            for server_name, server in mcp_servers.items():
                if not isinstance(server, dict):
                    continue
                if server_name in mcp_client.get_server_names():
                    loaded["mcp"].append(server_name)
                    continue
                config = MCPServerConfig(
                    name=server_name,
                    transport=str(server.get("transport", "stdio")),
                    command=server.get("command"),
                    args=[str(arg) for arg in server.get("args", [])],
                    env={str(k): str(v) for k, v in (server.get("env") or {}).items()},
                    cwd=server.get("cwd"),
                    url=server.get("url"),
                    enabled=True,
                )
                await mcp_client._connect_server(config)
                loaded["mcp"].append(server_name)
        return loaded
