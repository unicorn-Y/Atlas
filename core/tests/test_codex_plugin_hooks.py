import json

import pytest

from atlas.plugins import PluginRuntime
from atlas.agent.enrichment import HookBus
from atlas.runtime.hooks import HookStore, codex_hook_settings

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


def test_codex_user_and_project_hook_sources_keep_separate_identity(tmp_path) -> None:
    user_path = tmp_path / "user-hooks.json"
    user_path.write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python user.py"},
        ]}],
    }}), encoding="utf-8")
    project = tmp_path / "project"
    project_hooks = project / ".codex" / "hooks.json"
    project_hooks.parent.mkdir(parents=True)
    project_hooks.write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python project.py"},
        ]}],
    }}), encoding="utf-8")

    hooks = codex_hook_settings(project, user_path)

    assert [hook["source"] for hook in hooks] == [
        f"codex:user:{user_path}", f"codex:project:{project_hooks}",
    ]
    assert all(hook["id"].startswith("codex-") for hook in hooks)
    assert hooks[0]["id"] != hooks[1]["id"]


@pytest.mark.asyncio
async def test_codex_project_hooks_use_fail_closed_trust_review(tmp_path, monkeypatch) -> None:
    project_hooks = tmp_path / ".codex" / "hooks.json"
    project_hooks.parent.mkdir()
    project_hooks.write_text(json.dumps({"hooks": {
        "PreToolUse": [{"hooks": [
            {"type": "command", "command": "must-not-run"},
        ]}],
    }}), encoding="utf-8")
    calls = []

    async def run_command(*args, **kwargs):
        calls.append(args)
        return 0, "", ""

    monkeypatch.setattr("atlas.runtime.hooks._run_command", run_command)
    store = HookStore(tmp_path / "hooks.toml")
    listed = store.list_all(str(tmp_path))

    assert len(listed) == 1
    assert listed[0]["source"] == f"codex:project:{project_hooks}"
    assert listed[0]["trust_state"] == "unreviewed"
    result = await store.execute("tool.before", {"tool_name": "Bash"}, cwd=str(tmp_path))

    assert result["blocked"] is True
    assert "信任审查" in result["reason"]
    assert calls == []


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
