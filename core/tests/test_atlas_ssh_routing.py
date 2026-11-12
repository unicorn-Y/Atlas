from types import SimpleNamespace

import pytest

from atlas.engine.atlas_runtime import AtlasRuntime


def test_ssh_workspace_maps_to_atlas_terminal_scope_without_network():
    cwd, policy = AtlasRuntime._ssh_workspace_terminal_policy(
        "ssh://build-host/srv/project",
        [{"alias": "build-host", "hostname": "build.example.test", "user": "builder"}],
    )
    assert cwd == "/srv/project"
    assert policy == {
        "TERMINAL_ENV": "ssh",
        "TERMINAL_SSH_HOST": "build-host",
        "TERMINAL_SSH_USER": "builder",
        "TERMINAL_SSH_PERSISTENT": "true",
        "TERMINAL_CWD": "/srv/project",
    }


@pytest.mark.asyncio
async def test_ssh_workspace_scope_is_bound_to_atlas_turn_without_network(tmp_path, monkeypatch):
    from atlas.ssh import SSHWorkspaceManager
    from tools.terminal_scope import get_terminal_scope

    monkeypatch.setattr(SSHWorkspaceManager, "hosts", lambda _self: [
        {"alias": "build-host", "hostname": "build.example.test", "user": "builder"},
    ])
    settings = SimpleNamespace(
        current_model="fake-model", current_litellm_model="fake-model",
        gateway_base_url=None, _api_key="sk-fake", list_models=lambda: [{"id": "fake-model"}],
    )
    observed = {}

    class StubAtlasAgent:
        def __init__(self, **kwargs):
            observed["cwd"] = kwargs["cwd"]
            observed["init_scope"] = get_terminal_scope()
            self.session_id = kwargs["session_id"]
            self._last_turn_usage = None

        def _build_system_prompt(self, system_message=None):
            return system_message or "Atlas"

        def run_conversation(self, **_kwargs):
            observed["run_scope"] = get_terminal_scope()
            return {"final_response": "ssh scope ready", "messages": []}

        def close(self):
            pass

    runtime = AtlasRuntime(
        data_dir=tmp_path, model_manager=settings,
        agent_factory=lambda **kwargs: StubAtlasAgent(**kwargs),
    )
    events = [event async for event in runtime.run_turn(
        message="use ssh workspace", conversation_id="ssh-scope", workspace="ssh://build-host/srv/project",
        history=[],
    )]
    assert events[-1]["result"]["final_response"] == "ssh scope ready"
    expected = {
        "TERMINAL_ENV": "ssh", "TERMINAL_SSH_HOST": "build-host", "TERMINAL_SSH_USER": "builder",
        "TERMINAL_SSH_PERSISTENT": "true", "TERMINAL_CWD": "/srv/project",
    }
    assert observed == {"cwd": "/srv/project", "init_scope": expected, "run_scope": expected}
    assert get_terminal_scope() is None
