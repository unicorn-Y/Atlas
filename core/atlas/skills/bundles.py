"""Read-only discovery for lightweight Atlas plugin bundle manifests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COMPONENT_FIELDS = ("skills", "commands", "mcp_servers", "hooks", "agents")


@dataclass(frozen=True)
class PluginBundle:
    name: str
    version: str
    description: str
    root: str
    skills: tuple[Any, ...] = ()
    commands: tuple[Any, ...] = ()
    mcp_servers: tuple[Any, ...] = ()
    hooks: tuple[Any, ...] = ()
    agents: tuple[Any, ...] = ()
    ui: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "version": self.version,
            "description": self.description, "root": self.root,
            **{key: list(getattr(self, key)) for key in COMPONENT_FIELDS},
            "ui": self.ui, "discovery_only": True, "runtime_enabled": False,
        }


def parse_plugin_bundle(path: str | Path) -> PluginBundle:
    manifest_path = Path(path)
    if manifest_path.is_dir():
        manifest_path /= "atlas-plugin.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("plugin manifest must be an object")
    name, version = raw.get("name"), raw.get("version")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("plugin name must be kebab-case")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("plugin version must use MAJOR.MINOR.PATCH")
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise ValueError("plugin description must be text")
    components: dict[str, tuple[Any, ...]] = {}
    for field in COMPONENT_FIELDS:
        value = raw.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, (str, dict)) for item in value):
            raise ValueError(f"{field} must be an array of strings or objects")
        components[field] = tuple(value)
    ui = raw.get("ui")
    if ui is not None and not isinstance(ui, dict):
        raise ValueError("ui metadata must be an object")
    return PluginBundle(
        name=name, version=version, description=description.strip(),
        root=str(manifest_path.parent.resolve()), ui=ui, **components,
    )


class PluginBundleDiscovery:
    """Normalize bundle declarations alongside existing plain Atlas Skills."""

    def discover(
        self, roots: list[str | Path], skills: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for raw_root in roots:
            root = Path(raw_root)
            manifests = [root] if root.name == "atlas-plugin.json" else sorted(
                root.glob("*/atlas-plugin.json") if root.is_dir() else []
            )
            for manifest in manifests:
                bundle = parse_plugin_bundle(manifest)
                results.append({"kind": "plugin_bundle", **bundle.to_dict()})
        for skill in skills or []:
            item = skill.to_dict() if hasattr(skill, "to_dict") else dict(skill)
            results.append({
                "kind": "skill", "name": item["name"], "version": item.get("version", "0.0.0"),
                "description": item.get("description", ""), "source": "plain_skill",
            })
        return sorted(results, key=lambda item: (item["kind"], item["name"]))
