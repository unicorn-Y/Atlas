from atlas.engine.hermes_runtime import HermesRuntime


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
        "stdio": {"command": "fake", "args": ["server"], "env": {"FAKE": "1"}},
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


async def test_atlas_compression_model_setting_maps_to_bare_wire_id(monkeypatch):
    """Host-shaped config (prefixed litellm id) -> compressor pins the BARE id.

    The compressor sends ``summary_model`` verbatim to the provider; the
    litellm-style routing prefix 404s on real relays (H10.2-DEFECT-1 residual).
    """
    from types import SimpleNamespace

    monkeypatch.setattr("atlas.config.load_user_settings", lambda: {"compression_model": "cheap"})
    compressor = SimpleNamespace(summary_model="")
    agent = SimpleNamespace(context_compressor=compressor)
    models = SimpleNamespace(list_models=lambda: [
        {"id": "cheap", "litellm_model": "openai/cheap-model", "api_key": "must-not-copy"},
    ])

    await HermesRuntime._apply_compression_model_setting(agent, models)

    assert compressor.summary_model == "cheap-model"
    assert "api_key" not in str(compressor.summary_model)


async def test_atlas_compression_model_setting_honors_native_model(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr("atlas.config.load_user_settings", lambda: {"compression_model": "cheap"})
    compressor = SimpleNamespace(summary_model="")
    agent = SimpleNamespace(context_compressor=compressor)
    models = SimpleNamespace(list_models=lambda: [
        {"id": "cheap", "litellm_model": "anthropic/cheap-model",
         "native_model": "cheap-model-native"},
    ])

    await HermesRuntime._apply_compression_model_setting(agent, models)

    assert compressor.summary_model == "cheap-model-native"


async def test_atlas_compression_model_setting_uses_route_wire_model(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr("atlas.config.load_user_settings", lambda: {"compression_model": "cheap"})
    compressor = SimpleNamespace(summary_model="")
    agent = SimpleNamespace(context_compressor=compressor)
    class Router:
        async def resolve(self, model_id, purpose):
            assert (model_id, purpose) == ("cheap", "compression")
            return SimpleNamespace(
                wire_model="cheap-wire-model", model="openai/cheap-model", model_id="cheap",
            )

    models = SimpleNamespace(model_router=Router())

    await HermesRuntime._apply_compression_model_setting(agent, models)

    assert compressor.summary_model == "cheap-wire-model"


def test_compaction_agent_pins_bare_wire_id_from_host_shaped_config(tmp_path, monkeypatch):
    """Manual compaction builds its Hermes agent on the bare wire id.

    ``_compact_session_sync`` used to pass ``settings.current_litellm_model``
    (the prefixed routing label) straight to the agent transport — real relays
    404 the whole compaction (H10.2-DEFECT-1 residual).
    """
    from types import SimpleNamespace

    history = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "done"}]

    class FakeSessionDB:
        def get_messages_as_conversation(self, conversation_id, include_ancestors=True):
            return list(history)

        def get_session(self, conversation_id):
            return {"system_prompt": "system-prompt-from-session"}

    built_kwargs: dict = {}

    def fake_agent_factory(**kwargs):
        built_kwargs.update(kwargs)
        return SimpleNamespace(
            context_compressor=None,
            _session_db=FakeSessionDB(),
            _compress_context=lambda hist, prompt, **kw: (list(hist), None),
            close=lambda: None,
        )

    monkeypatch.setattr("atlas.config.load_user_settings", lambda: {})
    models = SimpleNamespace(
        current_model="main",
        current_litellm_model="openai/deepseek-v4.1-flash",
        list_models=lambda: [
            {"id": "main", "litellm_model": "openai/deepseek-v4.1-flash"},
        ],
    )
    runtime = HermesRuntime(
        data_dir=tmp_path, model_manager=models, agent_factory=fake_agent_factory,
    )

    result = runtime._compact_session_sync("conv-1", str(tmp_path), None)

    assert built_kwargs["model"] == "deepseek-v4.1-flash"
    assert result["compressed"] is False  # unchanged transcript: wiring-only probe


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
