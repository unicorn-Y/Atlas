"""Local plugin bundle runtime coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.agent.enrichment import HookBus
from atlas.plugins import PluginRuntime


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
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
        "hooks": [
            {"point": "after_response", "command": ["python", "-c", "pass"]},
            {"point": "not_a_real_point", "command": ["python", "-c", "pass"]},
        ],
    }), encoding="utf-8")
    (root / "plugin.json").write_text(json.dumps({
        "name": "demo", "version": "1.0.0", "description": "demo plugin",
    }), encoding="utf-8")
    (root / ".mcp.json").write_text(json.dumps({
        "mcpServers": {
            "demo-mcp": {"transport": "stdio", "command": "python", "args": ["-c", "x"]},
        },
    }), encoding="utf-8")
    return root.parent


class FakeMCPClient:
    def __init__(self) -> None:
        self.connected: list[str] = []

    def get_server_names(self) -> list[str]:
        return list(self.connected)

    async def _connect_server(self, config) -> None:
        self.connected.append(config.name)


@pytest.fixture
async def runtime(tmp_path: Path, plugin_dir: Path):
    user_dir = tmp_path / "user-plugins"
    user_dir.mkdir()
    state = tmp_path / "state.json"
    store = PluginRuntime([plugin_dir, user_dir], state)
    yield store


async def test_discover_reports_manifest_details(runtime: PluginRuntime) -> None:
    plugins = runtime.discover()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin["name"] == "demo"
    assert plugin["version"] == "1.0.0"
    assert plugin["skills"] == ["greet"]
    assert plugin["commands"] == ["standup"]
    assert plugin["hooks"] == 1  # invalid hook point ignored
    assert plugin["mcp_servers"] == ["demo-mcp"]
    assert plugin["enabled"] is True and plugin["loaded"] is False


async def test_load_all_registers_capabilities_hooks_and_mcp(
    runtime: PluginRuntime,
) -> None:
    from atlas.agent.capabilities import AgentCapabilityRegistry

    registry = AgentCapabilityRegistry()
    hook_bus = HookBus()
    mcp = FakeMCPClient()

    report = await runtime.load_all(
        hook_bus=hook_bus, mcp_client=mcp, capabilities=registry,
    )

    assert report["loaded"] == ["demo"]
    names = {item["name"] for item in registry.discover()}
    assert "plugin.demo.skill.greet" in names
    assert "plugin.demo.command.standup" in names
    result = await registry.invoke("plugin.demo.command.standup")
    assert "Summarize yesterday" in result["prompt"]
    assert mcp.connected == ["demo-mcp"]
    assert len(hook_bus._hooks["after_response"]) == 1


async def test_disable_skips_and_persists(runtime: PluginRuntime) -> None:
    runtime.set_enabled("demo", False)
    report = await runtime.load_all()
    assert report["loaded"] == []
    assert report["skipped"] == [{"name": "demo", "reason": "disabled"}]

    reloaded = PluginRuntime(runtime._dirs, runtime._state_path)
    assert reloaded.discover()[0]["enabled"] is False


async def test_install_local_copies_into_user_dir(
    tmp_path: Path, plugin_dir: Path,
) -> None:
    user_dir = tmp_path / "user-plugins"
    user_dir.mkdir()
    runtime = PluginRuntime([plugin_dir, user_dir], tmp_path / "state.json")

    source = tmp_path / "downloaded" / "gift-plugin"
    source.mkdir(parents=True)
    (source / "plugin.json").write_text(
        json.dumps({"name": "gift"}), encoding="utf-8",
    )
    result = runtime.install_local(source)
    assert result["name"] == "gift"
    assert (user_dir / "gift-plugin" / "plugin.json").is_file()
    assert any(p["name"] == "gift" for p in runtime.discover())

    with pytest.raises(ValueError, match="no plugin.json"):
        runtime.install_local(tmp_path / "empty")
