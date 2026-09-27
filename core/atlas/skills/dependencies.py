"""Structured, read-only skill dependency declarations and preflight checks."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import re
import shutil
from dataclasses import dataclass
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


@dataclass(frozen=True)
class SkillDependency:
    name: str
    kind: str
    requested: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "requested": self.requested}


_KINDS = {"mcp_servers", "python_packages", "commands"}
_LEGACY = re.compile(r"^(mcp|python|command|skill):([^@]+)(?:@(.+))?$")


def parse_dependencies(declarations: Any) -> list[SkillDependency]:
    """Normalize modern kind mappings and historical ``kind:name@constraint`` strings."""
    items: list[SkillDependency] = []
    if isinstance(declarations, dict):
        aliases = {"mcp": "mcp_servers", "python": "python_packages", "command": "commands"}
        for raw_kind, values in declarations.items():
            kind = aliases.get(str(raw_kind), str(raw_kind))
            if kind not in _KINDS:
                items.append(SkillDependency(str(raw_kind), "unknown"))
                continue
            values = values if isinstance(values, list) else [values]
            for value in values:
                if isinstance(value, str) and value.strip():
                    name, requested = _split_requested(value.strip())
                    items.append(SkillDependency(name, kind, requested))
                elif isinstance(value, dict) and isinstance(value.get("name"), str):
                    requested = value.get("version", value.get("constraint"))
                    items.append(SkillDependency(
                        value["name"], kind, requested if isinstance(requested, str) else None,
                    ))
                else:
                    items.append(SkillDependency(str(value), "unknown"))
        return _deduplicate(items)
    if isinstance(declarations, list):
        for value in declarations:
            if not isinstance(value, str) or not value.strip():
                items.append(SkillDependency(str(value), "unknown"))
                continue
            match = _LEGACY.fullmatch(value.strip())
            if match:
                kind = {"mcp": "mcp_servers", "python": "python_packages",
                        "command": "commands", "skill": "skills"}[match.group(1)]
                items.append(SkillDependency(match.group(2), kind, match.group(3)))
            else:
                items.append(SkillDependency(value.strip(), "unknown"))
    return _deduplicate(items)


def _split_requested(value: str) -> tuple[str, str | None]:
    if "@" not in value:
        return value, None
    name, requested = value.split("@", 1)
    return name, requested or None


def _deduplicate(items: list[SkillDependency]) -> list[SkillDependency]:
    unique = {(item.kind, item.name, item.requested): item for item in items}
    return list(unique.values())


def dependency_preflight(
    declarations: Any,
    *,
    connected_servers: set[str] | None = None,
    configured_servers: set[str] | None = None,
    registry: Any | None = None,
) -> list[dict[str, Any]]:
    """Inspect dependencies without changing the process, filesystem, or environment."""
    result: list[dict[str, Any]] = []
    for dependency in parse_dependencies(declarations):
        detected: str | None = None
        source = "skill declaration"
        reason: str | None = None
        state = "unknown"
        if dependency.kind == "mcp_servers":
            if connected_servers is None or configured_servers is None:
                reason = "MCP server configuration or connection state is unavailable"
            elif dependency.name in connected_servers:
                detected, state, source = "connected", "satisfied", "registered MCP configuration"
            elif dependency.name in configured_servers:
                detected, state = "configured, disconnected", "missing"
                source = "registered MCP configuration"
                reason = "configured MCP server is not connected"
            else:
                detected, state = "not configured", "missing"
                source = "registered MCP configuration"
                reason = "no trusted MCP server configuration is registered"
            if dependency.requested and state == "satisfied":
                detected = None
                state, reason = "unknown", "connected MCP server version cannot be verified"
        elif dependency.kind == "python_packages":
            try:
                version = _installed_package_version(dependency.name)
            except (importlib.metadata.PackageNotFoundError, ImportError, ValueError):
                version = None
            if version is None:
                detected, state, source = False, "missing", "current Python environment"
                reason = "package is not installed in the current Python environment"
            else:
                detected, source = version, "current Python environment"
                if dependency.requested:
                    try:
                        matches = Version(version) in SpecifierSet(dependency.requested)
                    except (InvalidSpecifier, InvalidVersion):
                        matches = None
                    if matches is None:
                        state, reason = "unknown", "declared version constraint cannot be evaluated"
                    elif matches:
                        state = "satisfied"
                    else:
                        state = "incompatible"
                        reason = (f"installed version {version} does not match "
                                  f"{dependency.requested}")
                else:
                    state = "unknown" if version == "unknown" else "satisfied"
        elif dependency.kind == "commands":
            command_path = shutil.which(dependency.name)
            source = "current PATH"
            if command_path:
                detected = command_path
                if dependency.requested:
                    state, reason = "unknown", "system command version cannot be verified"
                else:
                    state = "satisfied"
            else:
                detected, state = False, "missing"
                reason = "command is not available on the current PATH"
        elif dependency.kind == "skills":
            source = "local Skill Registry"
            if registry is None:
                reason = "Skill Registry is unavailable"
            else:
                records = [item for item in registry.list() if item.get("name") == dependency.name]
                matching = [
                    item for item in records if item.get("status") == "active"
                    and (not dependency.requested
                         or item.get("version") == dependency.requested)
                ]
                detected = matching[0].get("version") if matching else None
                if matching:
                    state = "satisfied"
                elif records:
                    state = "incompatible" if dependency.requested else "missing"
                    reason = "no active registered version satisfies the declaration"
                else:
                    state, reason = "missing", "required Skill is not registered"
        else:
            reason = "dependency kind is not recognized"
        result.append({
            **dependency.to_dict(), "detected": detected, "state": state,
            "source": source, "blocking_reason": reason,
        })
    return result


def _installed_package_version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        # Manifests may use an import name rather than its distribution name.
        try:
            spec = importlib.util.find_spec(package.replace("-", "_"))
        except (ImportError, ValueError, ModuleNotFoundError):
            spec = None
        if spec is None:
            return None
        distributions = importlib.metadata.packages_distributions().get(
            package.replace("-", "_"), [],
        )
        for distribution in distributions:
            try:
                return importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                continue
        return "present"
