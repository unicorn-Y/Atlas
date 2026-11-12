"""Provider-neutral agent capability registration and invocation."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

CapabilityHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class AgentCapability:
    """A discoverable capability and its independent invocation handler."""

    name: str
    description: str
    handler: CapabilityHandler
    source: str = "agent"

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
        }


class AgentCapabilityRegistry:
    """Store capabilities separately from the agent's model execution."""

    def __init__(self) -> None:
        self._capabilities: dict[str, AgentCapability] = {}

    def register(
        self,
        name: str,
        *,
        description: str,
        handler: CapabilityHandler,
        source: str = "agent",
    ) -> None:
        if name in self._capabilities:
            raise ValueError(f"Capability already registered: {name}")
        self._capabilities[name] = AgentCapability(
            name=name,
            description=description,
            handler=handler,
            source=source,
        )

    def unregister(self, name: str) -> bool:
        """Drop one capability. Returns whether it existed.

        Needed for reload: :meth:`register` refuses a duplicate name, so a plugin
        that is reloaded must clear its old entries first. Returning a bool rather
        than raising keeps "unload something already gone" an ordinary outcome.
        """
        return self._capabilities.pop(name, None) is not None

    def unregister_source(self, source: str) -> int:
        """Drop every capability from one source, e.g. ``plugin:foo``.

        A plugin can change how many skills/commands it contributes between
        reloads, so removing by source is the only way to guarantee no stale entry
        survives when the list gets shorter.
        """
        stale = [
            name for name, capability in self._capabilities.items()
            if capability.source == source
        ]
        for name in stale:
            del self._capabilities[name]
        return len(stale)

    def sources(self) -> dict[str, int]:
        """Capability count per source, for reload diagnostics."""
        counts: dict[str, int] = {}
        for capability in self._capabilities.values():
            counts[capability.source] = counts.get(capability.source, 0) + 1
        return counts

    def discover(self) -> list[dict[str, str]]:
        return [
            capability.to_dict()
            for capability in sorted(self._capabilities.values(), key=lambda item: item.name)
        ]

    async def invoke(self, name: str, inputs: dict[str, Any] | None = None) -> Any:
        capability = self._capabilities.get(name)
        if capability is None:
            raise KeyError(name)
        result = capability.handler(inputs or {})
        if inspect.isawaitable(result):
            return await result
        return result


def register_skill_capabilities(
    registry: AgentCapabilityRegistry, skill_manager: Any, skill_registry: Any | None = None,
    mcp_client: Any | None = None,
) -> None:
    """Expose each indexed skill as an agent capability that activates it."""
    for skill in skill_manager.list_skills():
        skill_name = skill.name

        async def activate(_inputs: dict[str, Any], name: str = skill_name) -> str | None:
            if skill_registry is not None:
                info = skill_manager.get_skill(name)
                record = skill_registry.get(name, info.version) if info is not None else None
                lifecycle = (record or {}).get("lifecycle", {})
                if lifecycle.get("trust_state") in {"revoked", "blocked"} or lifecycle.get(
                    "state"
                ) in {"quarantined", "removed"}:
                    raise PermissionError("skill lifecycle policy blocks activation")
            connected = mcp_client.get_server_names() if mcp_client is not None else None
            configured = (
                mcp_client.get_configured_server_names() if mcp_client is not None else None
            )
            if hasattr(skill_manager, "preflight_dependencies"):
                dependencies = skill_manager.preflight_dependencies(
                    name, connected_servers=connected, configured_servers=configured,
                    registry=skill_registry,
                )
            else:
                dependencies = []
            blockers = [item for item in dependencies if item["state"] != "satisfied"]
            if blockers:
                detail = ", ".join(
                    f"{item['kind']}:{item['name']} ({item['state']})" for item in blockers
                )
                raise PermissionError("skill dependencies block activation: " + detail)
            if hasattr(skill_manager, "preflight_dependencies"):
                return await skill_manager.activate(
                    name, connected_servers=connected, configured_servers=configured,
                    registry=skill_registry,
                )
            return await skill_manager.activate(name)

        registry.register(
            f"skill.{skill_name}",
            description=skill.description,
            handler=activate,
            source="skill",
        )



def register_skill_dependency_capability(
    registry: AgentCapabilityRegistry, skill_manager: Any,
    skill_registry: Any | None = None, mcp_client: Any | None = None,
) -> None:
    """Expose read-only dependency preflight; no mutation or approval handlers exist."""

    async def inspect_dependencies(inputs: dict[str, Any]) -> dict[str, Any]:
        name = inputs.get("name")
        if not isinstance(name, str):
            raise ValueError("name is required")
        items = skill_manager.preflight_dependencies(
            name,
            connected_servers=mcp_client.get_server_names() if mcp_client else None,
            configured_servers=(mcp_client.get_configured_server_names() if mcp_client else None),
            registry=skill_registry,
        )
        return {
            "name": name,
            "dependencies": items,
            "blocking": [item for item in items if item["state"] != "satisfied"],
            "read_only": True,
        }

    registry.register(
        "skill.dependencies.inspect",
        description=("Read dependency declarations and preflight status without changing "
                    "the environment."),
        handler=inspect_dependencies,
        source="skill-registry",
    )


def register_skill_discovery_capability(
    capabilities: AgentCapabilityRegistry, skill_registry: Any,
) -> None:
    """Expose an explicit, read-only discovery primitive to Planner and Agent callers."""
    from atlas.skills.discovery import SkillDiscovery

    discovery = SkillDiscovery(skill_registry)

    def discover(inputs: dict[str, Any]) -> dict[str, Any]:
        accepted = {
            key: inputs[key]
            for key in (
                "query", "name", "capability", "tool", "status", "source", "limit", "offset",
            )
            if key in inputs
        }
        if "query" not in accepted and isinstance(inputs.get("task"), str):
            accepted["query"] = inputs["task"]
        return discovery.discover(**accepted)

    capabilities.register(
        "skill.discovery.search",
        description=(
            "Search registered skills for a task and return ranked candidates "
            "without activating them."
        ),
        handler=discover,
        source="skill-registry",
    )

    def inspect_lifecycle(inputs: dict[str, Any]) -> dict[str, Any]:
        name, version = inputs.get("name"), inputs.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("name and version are required")
        skill = skill_registry.get(name, version)
        if skill is None:
            raise KeyError(name)
        return {
            "name": name, "version": version, "status": skill.get("status"),
            "lifecycle": skill.get("lifecycle", {
                "trust_state": "unreviewed", "pin_policy": "unpinned",
            }),
            "provenance": skill.get("provenance", {}),
            "dependencies": skill.get("requirements", []),
            "history": skill_registry.lifecycle_history(name),
        }

    capabilities.register(
        "skill.lifecycle.inspect",
        description="Inspect installed skill lifecycle state and provenance; read-only.",
        handler=inspect_lifecycle,
        source="skill-registry",
    )


def register_skill_catalog_capabilities(
    capabilities: AgentCapabilityRegistry,
    provider: Any,
    skill_registry: Any | None = None,
) -> None:
    """Expose remote search and inspection only; installation remains a UI/API approval action."""

    async def search(inputs: dict[str, Any]) -> dict[str, Any]:
        query = inputs.get("query", inputs.get("q", ""))
        if not isinstance(query, str):
            raise ValueError("query must be text")
        return await provider.search(query, page=int(inputs.get("page", 0)))

    async def inspect(inputs: dict[str, Any]) -> dict[str, Any]:
        external_id = inputs.get("external_id")
        if not isinstance(external_id, str):
            raise ValueError("external_id is required")
        acquisition = await provider.inspect(external_id)
        result = {
            "record": acquisition.record,
            "files": acquisition.files,
            "validation": acquisition.validation,
            "security": acquisition.security,
            "computed_sha256": acquisition.computed_hash,
        }
        if skill_registry is not None:
            existing = next((item for item in skill_registry.list()
                             if (item.get("provenance") or {}).get("external_id") == external_id),
                            None)
            if existing:
                provenance = existing.get("provenance") or {}
                result["lifecycle_update"] = {
                    "available": provenance.get("computed_sha256") != acquisition.computed_hash,
                    "current_version": existing.get("version"),
                    "current_hash": provenance.get("computed_sha256"),
                    "trust_state": (existing.get("lifecycle") or {}).get(
                        "trust_state", "unreviewed",
                    ),
                    "pin_policy": (existing.get("lifecycle") or {}).get(
                        "pin_policy", "unpinned",
                    ),
                }
        return result

    def install(_inputs: dict[str, Any]) -> None:
        raise PermissionError(
            "skill.catalog.install requires the explicit Skill Center approval flow"
        )

    capabilities.register(
        "skill.catalog.search",
        description="Search external skills without installing them.",
        handler=search,
        source="external-catalog",
    )
    capabilities.register(
        "skill.catalog.inspect",
        description=(
            "Inspect external skill files and report validation and risk evidence "
            "without installing them."
        ),
        handler=inspect,
        source="external-catalog",
    )
    capabilities.register(
        "skill.catalog.install",
        description="Installation is denied here; use Skill Center review and explicit approval.",
        handler=install,
        source="external-catalog",
    )
