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


def register_skill_capabilities(registry: AgentCapabilityRegistry, skill_manager: Any) -> None:
    """Expose each indexed skill as an agent capability that activates it."""
    for skill in skill_manager.list_skills():
        skill_name = skill.name

        async def activate(_inputs: dict[str, Any], name: str = skill_name) -> str | None:
            return await skill_manager.activate(name)

        registry.register(
            f"skill.{skill_name}",
            description=skill.description,
            handler=activate,
            source="skill",
        )
