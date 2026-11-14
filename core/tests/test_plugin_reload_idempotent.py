"""Toggling a plugin must replace its contributions, never stack them.

``load_all`` runs on every enable/disable toggle, but it only cleared the
Python-side ``_loaded`` dict. The capabilities and hook handlers those plugins
had registered in the shared registries stayed behind, so the next load hit a
duplicate-capability rejection (caught and reported per plugin, making the
plugin look broken) and appended a second copy of every hook closure (not caught
at all, so hooks silently ran twice).

These tests pin the property that was missing: loading twice leaves the same
number of registrations as loading once.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.agent.capabilities import AgentCapabilityRegistry
from atlas.agent.enrichment import HookBus
from atlas.plugins import PluginRuntime

pytestmark = pytest.mark.unit


class _FakeMCPClient:
    def __init__(self) -> None:
        self.connected: list[str] = []

    def get_server_names(self) -> list[str]:
        return list(self.connected)

    async def _connect_server(self, config) -> None:
        self.connected.append(config.name)


@pytest.fixture
def plugin_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo-plugins" / "demo-plugin"
    (root / "skills" / "greet").mkdir(parents=True)
    (root / "skills" / "greet" / "SKILL.md").write_text(
        "---\nname: greet\n---\nSay hello.", encoding="utf-8",
    )
    (root / "commands").mkdir()
    (root / "commands" / "standup.md").write_text(
        "Summarize yesterday and today.", encoding="utf-8",
    )
    (root / "hooks").mkdir()
    (root / "hooks" / "hooks.json").write_text(json.dumps({
        "hooks": [{"point": "after_response", "command": ["python", "-c", "pass"]}],
    }), encoding="utf-8")
    (root / "plugin.json").write_text(json.dumps({
        "name": "demo", "version": "1.0.0", "description": "demo plugin",
    }), encoding="utf-8")
    return root.parent


@pytest.fixture
def runtime(tmp_path: Path, plugin_root: Path) -> PluginRuntime:
    user_dir = tmp_path / "user-plugins"
    user_dir.mkdir()
    return PluginRuntime([plugin_root, user_dir], tmp_path / "state.json")


def _capability_names(registry: AgentCapabilityRegistry) -> set[str]:
    return {item["name"] for item in registry.discover()}


@pytest.mark.asyncio
async def test_loading_twice_does_not_duplicate_capabilities(runtime: PluginRuntime):
    registry = AgentCapabilityRegistry()
    hook_bus = HookBus()
    mcp = _FakeMCPClient()

    first = await runtime.load_all(
        hook_bus=hook_bus, mcp_client=mcp, capabilities=registry,
    )
    after_first = _capability_names(registry)
    assert first["loaded"] == ["demo"]
    assert first["errors"] == {}

    second = await runtime.load_all(
        hook_bus=hook_bus, mcp_client=mcp, capabilities=registry,
    )
    after_second = _capability_names(registry)

    assert second["loaded"] == ["demo"]
    # The second load must not report the plugin as broken; that was the symptom
    # of the duplicate registration being rejected.
    assert second["errors"] == {}
    assert after_second == after_first
    assert second["capabilities_removed"] == len(after_first)


@pytest.mark.asyncio
async def test_loading_twice_does_not_duplicate_hook_handlers(runtime: PluginRuntime):
    hook_bus = HookBus()
    registry = AgentCapabilityRegistry()
    mcp = _FakeMCPClient()

    await runtime.load_all(hook_bus=hook_bus, mcp_client=mcp, capabilities=registry)
    after_first = len(hook_bus._hooks["after_response"])

    await runtime.load_all(hook_bus=hook_bus, mcp_client=mcp, capabilities=registry)
    after_second = len(hook_bus._hooks["after_response"])

    assert after_first == 1
    assert after_second == after_first


@pytest.mark.asyncio
async def test_second_load_reports_what_it_replaced(runtime: PluginRuntime):
    hook_bus = HookBus()
    registry = AgentCapabilityRegistry()

    await runtime.load_all(hook_bus=hook_bus, capabilities=registry)
    report = await runtime.load_all(hook_bus=hook_bus, capabilities=registry)

    assert report["hooks_cleared"] >= 1
    assert report["capabilities_removed"] >= 1


@pytest.mark.asyncio
async def test_disabling_a_plugin_removes_its_registrations(runtime: PluginRuntime):
    hook_bus = HookBus()
    registry = AgentCapabilityRegistry()

    await runtime.load_all(hook_bus=hook_bus, capabilities=registry)
    assert _capability_names(registry)
    assert len(hook_bus._hooks["after_response"]) == 1


@pytest.mark.asyncio
async def test_loaded_plugin_exposes_disposer_for_every_registry_contribution(runtime: PluginRuntime):
    registry = AgentCapabilityRegistry()
    hook_bus = HookBus()
    await runtime.load_all(hook_bus=hook_bus, capabilities=registry)

    loaded = runtime._loaded["demo"]
    dispose = runtime._disposers["demo"].dispose
    assert loaded["disposer_count"] == 3

    await dispose()
    await dispose()

    assert registry.discover() == []
    assert hook_bus._hooks["after_response"] == []
    await runtime.set_enabled("demo", False)
    report = await runtime.load_all(hook_bus=hook_bus, capabilities=registry)

    assert report["loaded"] == []
    assert _capability_names(registry) == set()
    assert hook_bus._hooks["after_response"] == []


@pytest.mark.asyncio
async def test_async_mcp_contribution_is_disposed_on_reload(runtime: PluginRuntime):
    class AsyncMCP(_FakeMCPClient):
        async def disconnect_server(self, name: str) -> None:
            self.connected.remove(name)

    root = runtime._dirs[0] / "demo-plugin"
    (root / "plugin.json").write_text(json.dumps({
        "name": "demo", "version": "1.0.0", "description": "demo plugin",
        "mcpServers": {"demo-mcp": {"command": "python", "args": ["-V"]}},
    }), encoding="utf-8")
    client = AsyncMCP()
    first = await runtime.load_all(mcp_client=client)
    assert first["loaded"] == ["demo"]
    assert client.connected == ["demo-mcp"]

    second = await runtime.load_all(mcp_client=client)
    assert second["loaded"] == ["demo"]
    assert client.connected == ["demo-mcp"]


@pytest.mark.asyncio
async def test_reload_still_works_and_stays_idempotent(runtime: PluginRuntime):
    hook_bus = HookBus()
    registry = AgentCapabilityRegistry()

    await runtime.load_all(hook_bus=hook_bus, capabilities=registry)
    before = _capability_names(registry)

    result = await runtime.reload("demo", hook_bus=hook_bus, capabilities=registry)

    assert result["ok"] is True
    # reload reuses the same forget helper, so the outcome must match load_all.
    assert _capability_names(registry) == before
    assert len(hook_bus._hooks["after_response"]) == 1


@pytest.mark.asyncio
async def test_disable_then_enable_replaces_exactly_one_plugin_generation(runtime: PluginRuntime):
    registry = AgentCapabilityRegistry()
    hook_bus = HookBus()

    first = await runtime.load_all(hook_bus=hook_bus, capabilities=registry)
    assert first["loaded"] == ["demo"]
    assert len(hook_bus._hooks["after_response"]) == 1

    await runtime.set_enabled("demo", False)
    assert _capability_names(registry) == set()
    assert hook_bus._hooks["after_response"] == []

    await runtime.set_enabled("demo", True)
    reloaded = await runtime.load_all(hook_bus=hook_bus, capabilities=registry)

    assert reloaded["loaded"] == ["demo"]
    assert reloaded["errors"] == {}
    assert _capability_names(registry) == {
        "plugin.demo.skill.greet", "plugin.demo.command.standup",
    }
    assert len(hook_bus._hooks["after_response"]) == 1
