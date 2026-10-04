import os

import pytest

from atlas.engine.hermes_runtime import HermesRuntime


def test_hermes_stdio_npx_uses_atlas_node_runtime(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    npm_bin = runtime / "npm" / "bin"
    npm_bin.mkdir(parents=True)
    node = runtime / "node.exe"
    npx_script = npm_bin / "npx-cli.js"
    node.write_bytes(b"fixture")
    npx_script.write_text("", encoding="utf-8")
    monkeypatch.setenv("ATLAS_NODE_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("ATLAS_NODE_RUNTIME_REQUIRED", "1")
    monkeypatch.setenv("PATH", "existing-path")

    adapted = HermesRuntime._adapt_atlas_mcp_servers({
        "filesystem": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "allowed"],
            "env": {"PATH": "server-path", "NPM_CONFIG_CACHE": "isolated-cache"},
            "enabled": True,
        },
    })

    assert adapted["filesystem"]["command"] == str(node)
    assert adapted["filesystem"]["args"] == [
        str(npx_script), "-y", "@modelcontextprotocol/server-filesystem", "allowed",
    ]
    assert adapted["filesystem"]["env"] == {
        "PATH": os.pathsep.join((str(runtime), "server-path")),
        "NPM_CONFIG_CACHE": "isolated-cache",
    }


def test_hermes_stdio_node_command_fails_closed_without_required_bundled_runtime(monkeypatch):
    monkeypatch.delenv("ATLAS_NODE_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("ATLAS_NODE_RUNTIME_REQUIRED", "1")

    with pytest.raises(FileNotFoundError, match="Node-based MCP server requires"):
        HermesRuntime._adapt_atlas_mcp_servers({
            "filesystem": {"transport": "stdio", "command": "npx", "enabled": True},
        })


def test_disabled_hermes_stdio_npx_does_not_resolve_missing_runtime(monkeypatch):
    monkeypatch.delenv("ATLAS_NODE_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("ATLAS_NODE_RUNTIME_REQUIRED", "1")

    adapted = HermesRuntime._adapt_atlas_mcp_servers({
        "filesystem": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "fixture-mcp"],
            "enabled": False,
        },
        "remote": {
            "transport": "http",
            "url": "https://mcp.example.invalid/endpoint",
            "enabled": True,
        },
    })

    assert adapted["filesystem"]["enabled"] is False
    assert adapted["filesystem"]["command"] == "npx"
    assert adapted["remote"]["enabled"] is True


def test_atlas_mcp_http_oauth_config_is_preserved_for_hermes():
    adapted = HermesRuntime._adapt_atlas_mcp_servers({
        "remote": {
            "transport": "streamable-http",
            "url": "https://mcp.example.invalid/endpoint",
            "headers": {"X-Atlas-Test": "fixture"},
            "auth": "oauth",
            "oauth": {"client_id": "fixture-client", "scopes": ["tools:read"]},
            "enabled": True,
        },
        "stdio": {"url": "https://must-be-ignored.invalid", "command": "fake", "args": ["server"], "env": {"FAKE": "1"}},
    }, auto_start=["remote"])

    assert adapted["remote"] == {
        "transport": "http",
        "url": "https://mcp.example.invalid/endpoint",
        "headers": {"X-Atlas-Test": "fixture"},
        "auth": "oauth",
        "oauth": {"client_id": "fixture-client", "scopes": ["tools:read"]},
        "enabled": True,
    }
    assert adapted["stdio"]["enabled"] is False
    assert "url" not in adapted["stdio"]


def test_atlas_compression_model_setting_maps_to_hermes_without_copying_credentials(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr("atlas.config.load_user_settings", lambda: {"compression_model": "cheap"})
    compressor = SimpleNamespace(summary_model="")
    agent = SimpleNamespace(context_compressor=compressor)
    models = SimpleNamespace(list_models=lambda: [
        {"id": "cheap", "litellm_model": "openai/cheap-model", "api_key": "must-not-copy"},
    ])

    HermesRuntime._apply_compression_model_setting(agent, models)

    assert compressor.summary_model == "openai/cheap-model"


def test_hermes_policy_recognizes_atlas_state_and_workspace_mutations():
    from atlas.engine.hermes_policy import _write_tool

    assert _write_tool("project_note", {})
    assert _write_tool("create_document", {})
    assert _write_tool("kanban_update_task", {})
    assert _write_tool("restore_checkpoint", {})
    assert _write_tool("mcp__fixture__read", {})
    assert not _write_tool("kanban_list", {})
    assert not _write_tool("read_file", {})
    assert _write_tool("process_manage", {"action": "kill"})


def test_mcp_write_creates_one_workspace_checkpoint_before_dispatch(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from atlas.engine import hermes_policy

    snapshots = []
    agent = SimpleNamespace(
        checkpoints=SimpleNamespace(create_checkpoint=lambda *args, **kwargs: snapshots.append((args, kwargs))),
        _model_facing_tools=lambda: [],
    )
    runtime = SimpleNamespace(
        workspace=str(tmp_path), run_id="run-1", conversation_id="conversation-1",
        permission_mode="full_access", mode="act", read_only=False,
    )
    loop = object()
    monkeypatch.setattr(hermes_policy, "_active", lambda _session_id="": (agent, runtime, loop))

    assert hermes_policy._pre_tool_call("mcp__fixture__first", {"path": "written.txt"}) is None
    assert hermes_policy._pre_tool_call("mcp__fixture__second", {}) is None

    assert len(snapshots) == 1
    assert snapshots[0][0] == (str(tmp_path), ["."])
    assert snapshots[0][1] == {"run_id": "run-1", "conversation_id": "conversation-1"}


def test_mcp_write_requires_checkpoint_and_approval_before_dispatch(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from atlas.engine import hermes_policy

    snapshots = []
    choices = []
    agent = SimpleNamespace(
        checkpoints=SimpleNamespace(create_checkpoint=lambda *args, **kwargs: snapshots.append(args)),
        _model_facing_tools=lambda: [],
    )
    runtime = SimpleNamespace(
        workspace=str(tmp_path), run_id="run-2", conversation_id="conversation-2",
        permission_mode="ask_writes", mode="act", read_only=False,
        approval_callback=lambda *args: choices.append(args) or "deny",
    )
    monkeypatch.setattr(hermes_policy, "_active", lambda _session_id="": (agent, runtime, object()))

    blocked = hermes_policy._pre_tool_call(
        "mcp__fixture__write", {"path": "written.txt"}, tool_call_id="call-1",
    )
    assert blocked["action"] == "block"
    assert snapshots == []
    assert choices[0][0] == "approval:call-1"

    runtime.approval_callback = lambda *_args: "allow"
    assert hermes_policy._pre_tool_call("mcp__fixture__write", {}) is None
    assert len(snapshots) == 1
