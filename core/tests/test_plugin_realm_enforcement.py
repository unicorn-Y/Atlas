"""X8: the agent preset's plugin rows must confine the model-visible surface.

The realm built at ``run_phases`` was historically write-only. These tests pin
its three consumption seams: capability rows (existing), plugin-contributed MCP
tools in the kernel tool pool / dispatch (new), and the model-visible skill
catalog projection (new).
"""

from types import SimpleNamespace

import pytest

from atlas.agent.capabilities import AgentCapabilityRegistry
from atlas.agent.run_phases import RunRequest, _apply_agent_preset_capabilities
from atlas.engine.kernel.loop import (
    _plugin_realm_admits_skill,
    _plugin_realm_allows,
    runtime_tool_allowed,
)
from atlas.library.search import Bm25Index
from atlas.library import runtime as library_runtime
from atlas.plugins.runtime import PluginRealm, plugin_of_source


def _capabilities(**overrides):
    value = {
        "tools": {"allow": [], "allow_all": True, "deny": []},
        "skills": [], "mcp_servers": [], "model": "inherit", "mode": "act",
    }
    value.update(overrides)
    return value


def _realm(**kwargs) -> PluginRealm:
    return PluginRealm(AgentCapabilityRegistry(), kwargs.pop("rows", ["docs"]), **kwargs)


# -- realm primitives ---------------------------------------------------------


@pytest.mark.unit
def test_plugin_of_source_parses_skill_and_capability_sources():
    assert plugin_of_source("plugin:docs:search") == "docs"
    assert plugin_of_source("plugin:docs") == "docs"
    assert plugin_of_source("claude-user") is None
    assert plugin_of_source("") is None
    assert plugin_of_source("plugin:") is None


@pytest.mark.unit
def test_realm_admits_only_selected_child_rows_and_unowned_servers():
    realm = _realm(rows=["docs"], mcp_owners={"docs-server": "docs", "cal-server": "calendar"})

    assert realm.allows_plugin("docs")
    assert not realm.allows_plugin("calendar")
    assert realm.admits_plugin_source("plugin:docs:search")
    assert not realm.admits_plugin_source("plugin:calendar:create")
    assert realm.admits_plugin_source("claude-project")
    # Plugin-contributed servers follow their owner; configured servers pass.
    assert realm.allows_mcp_server("docs-server")
    assert not realm.allows_mcp_server("cal-server")
    assert realm.allows_mcp_server("filesystem-from-toml")


@pytest.mark.unit
def test_realm_allow_all_opens_every_plugin_row():
    realm = _realm(rows=[], allow_all=True,
                   mcp_owners={"cal-server": "calendar", "docs-server": "docs"})

    assert realm.allows_plugin("calendar")
    assert realm.admits_plugin_source("plugin:calendar:create")
    assert realm.allows_mcp_server("cal-server")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_realm_invoke_denies_out_of_realm_child_row():
    registry = AgentCapabilityRegistry()
    registry.register("plugin.docs.skill.search", description="d",
                      handler=lambda _: "docs", source="plugin:docs")
    registry.register("plugin.calendar.skill.create", description="d",
                      handler=lambda _: "calendar", source="plugin:calendar")
    realm = PluginRealm(registry, ["docs"])

    assert [row["name"] for row in realm.discover()] == ["plugin.docs.skill.search"]
    assert await realm.invoke("plugin.docs.skill.search") == "docs"
    with pytest.raises(KeyError):
        await realm.invoke("plugin.calendar.skill.create")


# -- preset wiring ------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_preset_wires_plugin_mcp_ownership_into_realm():
    """The realm must know which MCP servers a plugin contributed (X8)."""

    class PluginRuntime:
        def enabled_contributions(self):
            return [
                {"name": "docs", "mcp_servers": {"docs-server": {"command": "x"}}},
                {"name": "calendar", "mcp_servers": {"cal-server": {}}},
            ]

    request = RunRequest(
        message="x", conversation_id="c", agent_preset_id="research",
        agent_preset_capabilities=_capabilities(plugins=["docs"], plugin_allow_all=False),
    )
    runtime = SimpleNamespace(mode="act", model=None, mcp_server_allow=None)
    agent = SimpleNamespace(_skills=None, _capabilities=AgentCapabilityRegistry(),
                            _plugin_runtime=PluginRuntime())

    error = await _apply_agent_preset_capabilities(agent, request, runtime)

    assert error is None
    assert runtime.plugin_realm.allows_mcp_server("docs-server")
    assert not runtime.plugin_realm.allows_mcp_server("cal-server")
    # A configured server with no plugin owner is not the realm's business.
    assert runtime.plugin_realm.allows_mcp_server("toml-server")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_preset_realm_survives_plugin_runtime_failure():
    class BrokenRuntime:
        def enabled_contributions(self):
            raise RuntimeError("boom")

    request = RunRequest(
        message="x", conversation_id="c", agent_preset_id="research",
        agent_preset_capabilities=_capabilities(plugins=["docs"], plugin_allow_all=False),
    )
    runtime = SimpleNamespace(mode="act", model=None, mcp_server_allow=None)
    agent = SimpleNamespace(_skills=None, _capabilities=AgentCapabilityRegistry(),
                            _plugin_runtime=BrokenRuntime())

    error = await _apply_agent_preset_capabilities(agent, request, runtime)

    assert error is None
    assert runtime.plugin_realm is not None


# -- kernel tool pool / dispatch predicates -----------------------------------


@pytest.mark.unit
def test_kernel_predicate_confines_plugin_mcp_tools_and_spares_configured_ones():
    realm = _realm(rows=["docs"], mcp_owners={"docs-server": "docs", "cal-server": "calendar"})
    runtime = SimpleNamespace(plugin_realm=realm, mcp_server_allow=None)

    assert runtime_tool_allowed(runtime, "docs-server__search")
    assert not runtime_tool_allowed(runtime, "cal-server__create_event")
    assert runtime_tool_allowed(runtime, "toml-server__grep")
    assert runtime_tool_allowed(runtime, "local_file")  # no namespace → not confined
    assert _plugin_realm_allows(runtime, "toml-server__grep")


@pytest.mark.unit
def test_kernel_predicate_passes_through_without_realm():
    runtime = SimpleNamespace(plugin_realm=None, mcp_server_allow=None)
    assert runtime_tool_allowed(runtime, "cal-server__create_event")
    assert _plugin_realm_allows(runtime, "anything__here")


@pytest.mark.unit
def test_kernel_predicate_keeps_mcp_server_scope_independent_of_realm():
    realm = _realm(rows=["docs"], mcp_owners={})
    runtime = SimpleNamespace(plugin_realm=realm, mcp_server_allow=["docs"])
    # mcp_server_allow handles configured scopes; realm handles plugin rows.
    assert runtime_tool_allowed(runtime, "docs__search")
    assert not runtime_tool_allowed(runtime, "calendar__create_event")


@pytest.mark.unit
def test_use_skill_gate_denies_out_of_realm_plugin_skill_only():
    class Skills:
        def get_skill(self, name):
            sources = {
                "in-realm": "plugin:docs:search",
                "out-realm": "plugin:calendar:create",
                "builtin": "atlas",
            }
            source = sources.get(name)
            return None if source is None else SimpleNamespace(source=source)

    realm = _realm(rows=["docs"])
    runtime = SimpleNamespace(plugin_realm=realm)
    agent = SimpleNamespace(_skills=Skills())

    assert _plugin_realm_admits_skill(runtime, agent, {"name": "in-realm"})
    assert not _plugin_realm_admits_skill(runtime, agent, {"name": "out-realm"})
    assert _plugin_realm_admits_skill(runtime, agent, {"name": "builtin"})
    # Unknown skill: not confinable, activation falls through to normal 404.
    assert _plugin_realm_admits_skill(runtime, agent, {"name": "nope"})
    # Without a realm (no preset) everything passes.
    assert _plugin_realm_admits_skill(SimpleNamespace(plugin_realm=None), agent,
                                      {"name": "out-realm"})


# -- skill index projection ---------------------------------------------------


@pytest.mark.unit
def test_skill_index_projection_hides_out_of_realm_plugin_skills(monkeypatch):
    items = [
        {"name": "in-realm", "source": "plugin:docs:search", "description": "d",
         "title": "", "status": "installed"},
        {"name": "out-realm", "source": "plugin:calendar:create", "description": "d",
         "title": "", "status": "installed"},
        {"name": "builtin", "source": "atlas", "description": "d",
         "title": "", "status": "installed"},
    ]
    monkeypatch.setattr(library_runtime, "_skill_index",
                        lambda mgr: (Bm25Index(items), [dict(item) for item in items]))
    realm = _realm(rows=["docs"])

    text = library_runtime.skill_index_message(
        SimpleNamespace(), "anything", plugin_realm=realm,
    )
    assert text is not None
    assert "in-realm" in text
    assert "builtin" in text
    assert "out-realm" not in text

    # No realm → the shared index stays complete.
    full = library_runtime.skill_index_message(SimpleNamespace(), "anything")
    assert "out-realm" in full

    # allow_all realm keeps plugin rows visible.
    open_text = library_runtime.skill_index_message(
        SimpleNamespace(), "anything", plugin_realm=_realm(rows=[], allow_all=True),
    )
    assert "out-realm" in open_text


@pytest.mark.unit
def test_skill_index_projection_can_hide_every_plugin_entry(monkeypatch):
    items = [
        {"name": "out-realm", "source": "plugin:calendar:create", "description": "d",
         "title": "", "status": "installed"},
        {"name": "builtin", "source": "atlas", "description": "d",
         "title": "", "status": "installed"},
    ]
    monkeypatch.setattr(library_runtime, "_skill_index",
                        lambda mgr: (Bm25Index(items), [dict(item) for item in items]))
    realm = _realm(rows=["docs"])

    text = library_runtime.skill_index_message(
        SimpleNamespace(), "anything", plugin_realm=realm,
    )
    assert text is not None
    assert "out-realm" not in text and "builtin" in text
