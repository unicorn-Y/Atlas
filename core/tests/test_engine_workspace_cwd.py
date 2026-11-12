"""H10.2-DEFECT-3: engine cwd surfaces anchor to the Atlas ``--workspace``.

The live-model smoke proved the defect: the engine system prompt reported the
CLI process launch dir as the working directory and the model wrote the file
there instead of into ``--workspace`` (artifacts/h10-live-smoke/runs/
01-probe-defect3-record.json). Root cause: ``atlas_runtime`` passed ``cwd=``
to the AIAgent constructor but never registered it with the fork's cwd seams,
so every resolver fell back to ``os.getcwd()``.

These tests pin the Atlas-side registration through the fork's public seams:

- ``tools.terminal_tool.record_session_cwd`` keyed by the conversation id, so
  the file/terminal relative-path chain (``_authoritative_workspace_root``)
  resolves against the workspace;
- ``task_id=conversation_id`` on ``run_conversation`` (the key those records
  are read back with — the gateway passes its session id the same way);
- ``agent.runtime_cwd.set_session_cwd`` pinned in the turn's worker thread so
  the system prompt's ``resolve_agent_cwd()`` reports the workspace;
- ``ssh://`` workspaces stay out of the local records (their cwd policy rides
  the terminal scope).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from atlas.engine.atlas_runtime import AtlasRuntime


class _CwdCapturingAgent:
    """Records the task id and every cwd surface it observes during the turn."""

    def __init__(self, **_kwargs) -> None:
        self.observed: dict[str, Any] = {}

    def run_conversation(self, *, user_message, system_message, conversation_history,
                         task_id=None):
        from agent.runtime_cwd import resolve_agent_cwd, scoped_session_cwd
        from tools.terminal_tool import get_session_cwd

        self.observed = {
            "task_id": task_id,
            "scoped_session_cwd": scoped_session_cwd(),
            "prompt_cwd": str(resolve_agent_cwd()),
            "recorded_cwd": get_session_cwd(task_id),
        }
        return {"final_response": "ok", "messages": []}

    def close(self) -> None:
        pass


class _MinimalModelManager:
    """Just enough surface for run_turn to resolve a legacy-shaped route."""

    def __init__(self) -> None:
        self.current_model = "test-model"
        self.list_models = lambda: [
            {"id": "test-model", "litellm_model": "openai/test-model"},
        ]

    provider_config = lambda self, _pid: {}  # noqa: E731
    resolve_api_key = lambda self, _pid: None  # noqa: E731
    credential_pool = lambda self, _pid: None  # noqa: E731
    get_api_mode_override = lambda self, _pid: None  # noqa: E731
    get_api_mode_probe = lambda self, _pid: None  # noqa: E731
    set_api_mode_probe = lambda self, _pid, _probe: None  # noqa: E731


def _runtime(tmp_path: Path) -> AtlasRuntime:
    return AtlasRuntime(
        data_dir=tmp_path / "data",
        model_manager=_MinimalModelManager(),
        agent_factory=_CwdCapturingAgent,
    )


@pytest.mark.asyncio
async def test_run_turn_anchors_every_cwd_surface_to_the_workspace(
    tmp_path, monkeypatch,
):
    """A relative write must resolve inside --workspace while cwd is elsewhere."""
    from tools.terminal_tool import clear_session_cwd, get_session_cwd
    from tools.file_tools_paths import _resolve_path_for_task

    workspace = tmp_path / "ws"
    workspace.mkdir()
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)

    conversation_id = "cwd-anchor-1"
    clear_session_cwd(conversation_id)

    runtime = _runtime(tmp_path)
    events = [event async for event in runtime.run_turn(
        message="hello", conversation_id=conversation_id,
        workspace=str(workspace), history=[],
    )]
    assert events[-1]["type"] == "atlas.result"

    agent = next(
        entry["agent"] for entry in runtime._agent_cache.values()
    ) if runtime._agent_cache else None
    observed = agent.observed if agent is not None else {}

    # The turn's task id is the conversation id, so the record is findable.
    assert observed.get("task_id") == conversation_id
    # The prompt-side resolver saw the workspace, not the launch dir.
    assert observed.get("scoped_session_cwd") == str(workspace)
    assert Path(observed.get("prompt_cwd")) == workspace
    # The file/terminal session record is registered under the same key.
    assert observed.get("recorded_cwd") == str(workspace)
    assert get_session_cwd(conversation_id) == str(workspace)
    # End to end: a RELATIVE path now resolves inside the workspace even
    # though the process cwd is still the launch dir.
    resolved = Path(str(_resolve_path_for_task("hello.txt", conversation_id)))
    assert resolved == workspace / "hello.txt"
    assert resolved.is_relative_to(workspace)

    # The worker-thread pin is gone once the turn ends (main thread untouched).
    from agent.runtime_cwd import scoped_session_cwd

    assert scoped_session_cwd() == ""


@pytest.mark.asyncio
async def test_session_workspace_helper_excludes_ssh_and_empty(tmp_path) -> None:
    assert AtlasRuntime._session_workspace(str(tmp_path)) == str(tmp_path)
    assert AtlasRuntime._session_workspace("ssh://host/remote/path") == ""
    assert AtlasRuntime._session_workspace("  ") == ""
    assert AtlasRuntime._session_workspace(None) == ""


@pytest.mark.asyncio
async def test_ssh_workspace_never_enters_local_session_records(tmp_path):
    from tools.terminal_tool import clear_session_cwd, get_session_cwd

    conversation_id = "cwd-anchor-ssh"
    clear_session_cwd(conversation_id)
    AtlasRuntime._register_session_workspace(conversation_id, "ssh://host/remote/path")
    AtlasRuntime._register_session_workspace(conversation_id, None)

    assert get_session_cwd(conversation_id) is None


@pytest.mark.asyncio
async def test_record_session_workspace_survives_record_failure(
    tmp_path, monkeypatch,
):
    """A failing fork import must not break the turn registration path."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "tools.terminal_tool":
            raise ImportError("simulated unavailable fork module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    # Must not raise.
    AtlasRuntime._register_session_workspace("cwd-anchor-blocked", str(tmp_path))


@pytest.mark.asyncio
async def test_worker_thread_pin_is_reset_after_each_turn(tmp_path, monkeypatch):
    """Two turns in a row: the ContextVar never leaks across turn threads."""
    from tools.terminal_tool import clear_session_cwd

    workspace = tmp_path / "ws2"
    workspace.mkdir()
    conversation_id = "cwd-anchor-2"
    clear_session_cwd(conversation_id)
    monkeypatch.chdir(tmp_path)

    runtime = _runtime(tmp_path)
    for index in range(2):
        events = [event async for event in runtime.run_turn(
            message=f"turn {index}", conversation_id=conversation_id,
            workspace=str(workspace), history=[],
        )]
        assert events[-1]["type"] == "atlas.result"

    # The agent cache retains the turn agent (H3); both turns observed the pin.
    agents = [entry["agent"] for entry in runtime._agent_cache.values()]
    assert agents, "expected the cached session agent"
    assert all(
        agent.observed.get("scoped_session_cwd") == str(workspace)
        for agent in agents
    )
