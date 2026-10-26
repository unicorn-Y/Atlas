import json

from atlas.plugins import PluginRuntime


def _plugin(root, manifest, *, commands=(), mcp=None, hooks=None):
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    if commands:
        folder = root / "commands"
        folder.mkdir()
        for name, body in commands:
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
    if mcp is not None:
        (root / ".mcp.json").write_text(json.dumps({"mcpServers": mcp}), encoding="utf-8")
    if hooks is not None:
        folder = root / "hooks"
        folder.mkdir()
        (folder / "hooks.json").write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    return root


def test_validate_reports_schema_paths_commands_mcp_and_hook_errors(tmp_path):
    root = _plugin(
        tmp_path / "candidate-src",
        {
            "name": "candidate", "version": "not-semver", "skills": {"wrong": "shape"},
            "commands": ["../outside.md", "commands/a", "commands/b", "commands/candidate.md"], "mcpServers": {"invalid": {"args": "bad"}},
            "hooks": 42, "keywords": "not-an-array",
        },
        commands=[("a/shared.md", "one"), ("b/shared.md", "two"), ("candidate.md", "candidate")],
        mcp={"server-a": {"args": ["--ok"]}},
        hooks={"NotAnEvent": []},
    )
    plugins = tmp_path / "plugins"
    _plugin(
        plugins / "installed",
        {"name": "installed", "version": "1.0.0"},
        commands=[("candidate.md", "existing command")],
        mcp={"server-a": {"command": "python"}},
    )
    runtime = PluginRuntime([plugins], tmp_path / "state.json")

    report = runtime.validate(root)
    codes = {item["code"] for item in report["diagnostics"]}
    assert report["valid"] is False
    assert {
        "invalid_version", "invalid_component_declaration", "component_path_escape",
        "hooks_declaration_invalid", "invalid_field_type", "duplicate_command",
        "command_conflict", "mcp_transport_missing", "hook_event_unknown",
        "mcp_name_conflict",
    }.issubset(codes), f"missing diagnostics: {sorted({ 'invalid_version', 'invalid_component_declaration', 'component_path_escape', 'hooks_declaration_invalid', 'invalid_field_type', 'duplicate_command', 'command_conflict', 'mcp_transport_missing', 'hook_event_unknown' } - codes)}; got {sorted(codes)}"


def test_validate_reports_duplicate_mcp_and_invalid_mcp_transport(tmp_path):
    root = _plugin(
        tmp_path / "plugins" / "broken",
        {"name": "broken", "version": "1.0.0", "mcpServers": {"inline": {"args": []}}},
        mcp={"duplicate": {"command": "python"}},
    )
    (root / "plugin.json").write_text(json.dumps({
        "name": "broken", "version": "1.0.0",
        "mcpServers": {"duplicate": {"command": "python"}, "inline": {"args": []}},
    }), encoding="utf-8")
    runtime = PluginRuntime([root.parent], tmp_path / "state.json")

    codes = {item["code"] for item in runtime.validate(root)["diagnostics"]}
    assert "mcp_duplicate_name" in codes
    assert "mcp_transport_missing" in codes
