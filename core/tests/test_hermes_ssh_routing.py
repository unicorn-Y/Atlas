from types import SimpleNamespace

import pytest

from atlas.engine.hermes_runtime import HermesRuntime
from atlas.engine.tool_registry import _append_remote_lsp_notice


def test_ssh_workspace_maps_to_hermes_terminal_scope_without_network():
    cwd, policy = HermesRuntime._ssh_workspace_terminal_policy(
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


def test_ssh_write_result_discloses_missing_remote_lsp_but_local_result_does_not():
    remote = SimpleNamespace(workspace="ssh://build-host/srv/project")
    local = SimpleNamespace(workspace="C:/work/project")

    notice = _append_remote_lsp_notice(remote, "write_file", "写入完成")
    assert notice.startswith("写入完成")
    assert "未执行 Atlas LSP 诊断" in notice
    assert "language-server/session transport" in notice
    assert _append_remote_lsp_notice(remote, "read_file", "读取完成") == "读取完成"
    assert _append_remote_lsp_notice(local, "write_file", "写入完成") == "写入完成"


@pytest.mark.asyncio
async def test_ssh_workspace_scope_is_bound_to_hermes_turn_without_network(tmp_path, monkeypatch):
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

    class StubHermesAgent:
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

    runtime = HermesRuntime(
        data_dir=tmp_path, model_manager=settings,
        agent_factory=lambda **kwargs: StubHermesAgent(**kwargs),
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
