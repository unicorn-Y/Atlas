import pytest

from atlas.agent.capabilities import AgentCapabilityRegistry
from atlas.plugins.runtime import PluginRealm

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_plugin_realm_only_exposes_selected_child_plugin_rows():
    registry = AgentCapabilityRegistry()
    registry.register("plugin.alpha.skill.docs", description="docs", handler=lambda _: "alpha", source="plugin:alpha")
    registry.register("plugin.beta.skill.shell", description="shell", handler=lambda _: "beta", source="plugin:beta")
    alpha = PluginRealm(registry, ["alpha"])
    beta = PluginRealm(registry, ["beta"])

    assert [row["name"] for row in alpha.discover()] == ["plugin.alpha.skill.docs"]
    assert await alpha.invoke("plugin.alpha.skill.docs") == "alpha"
    with pytest.raises(KeyError):
        await alpha.invoke("plugin.beta.skill.shell")
    assert [row["name"] for row in beta.discover()] == ["plugin.beta.skill.shell"]
