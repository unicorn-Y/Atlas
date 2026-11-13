import json

import pytest

from atlas.plugins import PluginRuntime
from atlas.agent.enrichment import HookBus

pytestmark = pytest.mark.unit


def test_codex_hooks_json_maps_supported_events_to_atlas_hook_specs(tmp_path) -> None:
    root = tmp_path / "plugin"
    hooks_dir = root / ".codex"
    hooks_dir.mkdir(parents=True)
    (hooks_dir / "hooks.json").write_text(json.dumps({
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{
                "type": "command", "command": 'python "${CLAUDE_PLUGIN_ROOT}/hook.py"',
            }]}],
            "SessionStart": [{"hooks": [{"type": "command", "command": "ignored"}]}],
        },
    }), encoding="utf-8")

    specs = PluginRuntime._codex_hook_specs(root)

    assert specs == [{
        "point": "before_tool",
        "command": ["python", (root / "hook.py").resolve().as_posix()],
        "matcher": "Bash",
    }]


@pytest.mark.asyncio
async def test_codex_plugin_hook_is_registered_and_matcher_is_enforced(tmp_path, monkeypatch) -> None:
    root = tmp_path / "plugins" / "demo"
    (root / ".codex").mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"name": "demo"}), encoding="utf-8")
    (root / ".codex" / "hooks.json").write_text(json.dumps({
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{
            "type": "command", "command": "python -c pass",
        }]}]},
    }), encoding="utf-8")
    calls = []
    monkeypatch.setattr("atlas.plugins.runtime.subprocess.run", lambda *args, **kwargs: calls.append(args[0]))
    runtime = PluginRuntime([root.parent], tmp_path / "plugins-state.json")
    bus = HookBus()

    report = await runtime.load_all(hook_bus=bus)
    await bus.emit("before_tool", tool_name="Read")
    await bus.emit("before_tool", tool_name="Bash")

    assert report["loaded"] == ["demo"]
    assert len(calls) == 1
