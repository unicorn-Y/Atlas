"""Local plugin bundle runtime coverage."""

from __future__ import annotations

import json
import stat
import subprocess
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


@pytest.fixture
def claude_plugin_dir(tmp_path: Path) -> Path:
    """A Claude Code format plugin with one contribution of each of the five kinds."""
    root = tmp_path / "market-plugins" / "claude-kit"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "claude-kit", "displayName": "Claude Kit", "version": "0.2.0",
        "description": "claude format plugin",
        "commands": "./commands", "agents": "./agents", "skills": "./skills",
        "hooks": "./hooks/hooks.json",
    }), encoding="utf-8")
    (root / "skills" / "ping").mkdir(parents=True)
    (root / "skills" / "ping" / "SKILL.md").write_text(
        "---\nname: ping\n---\nPong.", encoding="utf-8",
    )
    (root / "commands").mkdir()
    (root / "commands" / "ship.md").write_text("Ship it: $ARGUMENTS", encoding="utf-8")
    (root / "agents").mkdir()
    (root / "agents" / "reviewer.md").write_text(
        "---\nname: reviewer\ndescription: Reviews code\n---\nReview the diff.", encoding="utf-8",
    )
    (root / "hooks").mkdir()
    (root / "hooks" / "hooks.json").write_text(json.dumps({
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo check"}]}]},
    }), encoding="utf-8")
    (root / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"kit-mcp": {"command": "python", "args": ["-c", "x"]}},
    }), encoding="utf-8")
    return root.parent


async def test_claude_format_plugin_full_chain(
    tmp_path: Path, claude_plugin_dir: Path,
) -> None:
    from atlas.agent.capabilities import AgentCapabilityRegistry

    user_dir = tmp_path / "user-plugins"
    user_dir.mkdir()
    runtime = PluginRuntime([claude_plugin_dir, user_dir], tmp_path / "state.json")

    installed = runtime.install_local(claude_plugin_dir / "claude-kit")
    assert installed["name"] == "claude-kit"
    assert (user_dir / "claude-kit" / ".claude-plugin" / "plugin.json").is_file()

    plugin = runtime.discover()[0]
    assert plugin["name"] == "claude-kit"
    assert plugin["path"] == str(user_dir / "claude-kit")  # installed copy wins by name
    assert plugin["skills"] == ["ping"]  # declared skills dir not double-counted
    assert plugin["commands"] == ["ship"]
    assert plugin["agents"] == ["reviewer"]
    assert plugin["hooks"] == 1
    assert plugin["mcp_servers"] == ["kit-mcp"]

    registry = AgentCapabilityRegistry()
    report = await runtime.load_all(capabilities=registry)
    assert report["loaded"] == ["claude-kit"]
    names = {item["name"] for item in registry.discover()}
    assert "plugin.claude-kit.skill.ping" in names
    assert "plugin.claude-kit.command.ship" in names
    assert (await registry.invoke("plugin.claude-kit.command.ship"))["prompt"].startswith("Ship it")

    contributions = runtime.enabled_contributions()
    assert contributions[0]["agents"] == [str(user_dir / "claude-kit" / "agents" / "reviewer.md")]
    assert contributions[0]["hooks"][0]["event"] == "PreToolUse"
    assert set(contributions[0]["mcp_servers"]) == {"kit-mcp"}

    runtime.set_enabled("claude-kit", False)
    report = await runtime.load_all(capabilities=registry)
    assert report["skipped"] == [{"name": "claude-kit", "reason": "disabled"}]

    assert runtime.uninstall("claude-kit") is True
    remaining = runtime.discover()
    assert [item["path"] for item in remaining] == [str(claude_plugin_dir / "claude-kit")]
    assert runtime._state["sources"] == {}


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _unlock(path: Path) -> None:
    """Clear git's read-only object bits so Windows tmp cleanup can rmtree."""
    for item in path.rglob("*"):
        if item.is_file():
            item.chmod(stat.S_IWRITE)


def test_git_source_update_available(tmp_path: Path) -> None:
    origin = tmp_path / "origin-repo"
    origin.mkdir()
    try:
        (origin / "plugin.json").write_text(
            json.dumps({"name": "gitsrc", "version": "1.0.0"}), encoding="utf-8",
        )
        _git("init", cwd=origin)
        _git("config", "user.email", "test@example.com", cwd=origin)
        _git("config", "user.name", "Test", cwd=origin)
        _git("add", "-A", cwd=origin)
        _git("-c", "commit.gpgsign=false", "commit", "-m", "v1", cwd=origin)

        user_dir = tmp_path / "user-plugins"
        user_dir.mkdir()
        runtime = PluginRuntime([user_dir], tmp_path / "state.json")
        runtime.install_git(origin.resolve().as_uri(), name="gitsrc")

        assert runtime.check_updates() == {"gitsrc": False}
        assert runtime.discover()[0]["update_available"] is False

        (origin / "plugin.json").write_text(
            json.dumps({"name": "gitsrc", "version": "1.1.0"}), encoding="utf-8",
        )
        _git("add", "-A", cwd=origin)
        _git("-c", "commit.gpgsign=false", "commit", "-m", "v2", cwd=origin)

        assert runtime.check_updates() == {"gitsrc": True}
        assert runtime.discover()[0]["update_available"] is True

        runtime.update("gitsrc")
        plugin = runtime.discover()[0]
        assert plugin["version"] == "1.1.0"
        assert plugin["update_available"] is False
    finally:
        _unlock(tmp_path)
