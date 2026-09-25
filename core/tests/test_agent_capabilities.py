"""Tests for the agent capability registry and invocation path."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from atlas.agent import AgentOrchestrator
from atlas.agent.capabilities import AgentCapabilityRegistry


@pytest.fixture
def model_mgr():
    return MagicMock()


@pytest.fixture
def memory():
    return MagicMock()


class TestAgentCapabilityRegistry:
    async def test_registered_capability_is_discoverable_and_invokable(
        self, model_mgr, memory,
    ) -> None:
        registry = AgentCapabilityRegistry()
        registry.register(
            "echo",
            description="Return the supplied value.",
            handler=lambda inputs: inputs["value"],
        )
        agent = AgentOrchestrator(
            model_mgr=model_mgr,
            memory=memory,
            capability_registry=registry,
        )

        assert agent.discover_capabilities() == [{
            "name": "echo",
            "description": "Return the supplied value.",
            "source": "agent",
        }]
        assert await agent.invoke_capability("echo", {"value": "ready"}) == "ready"

    async def test_skill_capabilities_use_skill_activation(self, model_mgr, memory) -> None:
        from atlas.agent.capabilities import register_skill_capabilities

        class Skills:
            def list_skills(self):
                return [type("Skill", (), {
                    "name": "research", "description": "Find papers."
                })()]

            async def activate(self, name: str) -> str:
                return f"instructions for {name}"

        registry = AgentCapabilityRegistry()
        register_skill_capabilities(registry, Skills())
        agent = AgentOrchestrator(
            model_mgr=model_mgr,
            memory=memory,
            capability_registry=registry,
        )

        assert agent.discover_capabilities() == [{
            "name": "skill.research",
            "description": "Find papers.",
            "source": "skill",
        }]
        assert await agent.invoke_capability("skill.research") == "instructions for research"

    async def test_unknown_capability_is_not_invokable(self) -> None:
        registry = AgentCapabilityRegistry()

        with pytest.raises(KeyError, match="unknown"):
            await registry.invoke("unknown")
