"""The disable path must end with the plugin actually gone.

``PUT /api/plugins/{name}` calls ``set_enabled(False)`` and then
``_reload_extensions()``, which re-runs ``load_all``. Two things can go wrong
between them and both are silent:

* ``set_enabled`` forgets only the Python-side record, so the capability and hook
  registrations survive and the plugin keeps working while the UI says disabled;
* the follow-up ``load_all`` re-registers everything from ``discover()``, which
  would undo the disable entirely if it did not honour the stored flag.

These tests drive the sequence the route drives and assert the end state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.agent.capabilities import AgentCapabilityRegistry
from atlas.agent.enrichment import HookBus
from atlas.plugins import PluginRuntime

pytestmark = pytest.mark.unit


def _make_plugin(root: Path) -> Path:
    plugin = root / "demo-plugin"
    (plugin / "skills" / "greet").mkdir(parents=True)
    (plugin / "skills" / "greet" / "SKILL.md").write_text(
        "---\nname: greet\n---\nSay hello.", encoding="utf-8",
    )
    (plugin / "hooks").mkdir()
    (plugin / "hooks" / "hooks.json").write_text(json.dumps({
        "hooks": [{"point": "after_response", "command": ["python", "-c", "pass"]}],
    }), encoding="utf-8")
    (plugin / "plugin.json").write_text(json.dumps({
        "name": "demo", "version": "1.0.0",
    }), encoding="utf-8")
    return root


@pytest.fixture
def runtime(tmp_path: Path) -> PluginRuntime:
    plugin_root = _make_plugin(tmp_path / "repo-plugins")
    user_dir = tmp_path / "user-plugins"
    user_dir.mkdir()
    return PluginRuntime([plugin_root, user_dir], tmp_path / "state.json")


def _names(registry: AgentCapabilityRegistry) -> set[str]:
    return {item["name"] for item in registry.discover()}


@pytest.mark.asyncio
async def test_disable_then_reload_leaves_nothing_registered(runtime: PluginRuntime):
    """The exact route sequence: set_enabled(False) then load_all()."""
    registry = AgentCapabilityRegistry()
    hook_bus = HookBus()

    await runtime.load_all(hook_bus=hook_bus, capabilities=registry)
    assert _names(registry)
    assert len(hook_bus._hooks["after_response"]) == 1

    await runtime.set_enabled("demo", False)
    report = await runtime.load_all(hook_bus=hook_bus, capabilities=registry)

    assert report["loaded"] == []
    assert report["skipped"] == [{"name": "demo", "reason": "disabled"}]
    assert _names(registry) == set()
    assert hook_bus._hooks["after_response"] == []


@pytest.mark.asyncio
async def test_disable_immediately_withdraws_before_any_reload(runtime: PluginRuntime):
    """A caller that only calls set_enabled must not leave the plugin active."""
    registry = AgentCapabilityRegistry()
    hook_bus = HookBus()

    await runtime.load_all(hook_bus=hook_bus, capabilities=registry)
    await runtime.set_enabled("demo", False)

    assert _names(registry) == set()
    assert hook_bus._hooks["after_response"] == []


@pytest.mark.asyncio
async def test_reenabling_restores_registrations_exactly_once(runtime: PluginRuntime):
    registry = AgentCapabilityRegistry()
    hook_bus = HookBus()

    await runtime.load_all(hook_bus=hook_bus, capabilities=registry)
    baseline = _names(registry)

    await runtime.set_enabled("demo", False)
    await runtime.load_all(hook_bus=hook_bus, capabilities=registry)
    assert _names(registry) == set()

    await runtime.set_enabled("demo", True)
    report = await runtime.load_all(hook_bus=hook_bus, capabilities=registry)

    assert report["loaded"] == ["demo"]
    assert _names(registry) == baseline
    assert len(hook_bus._hooks["after_response"]) == 1


@pytest.mark.asyncio
async def test_disable_before_first_load_is_safe(runtime: PluginRuntime):
    """No wiring captured yet: the call must not raise."""
    await runtime.set_enabled("demo", False)
    report = await runtime.load_all()
    assert report["loaded"] == []
