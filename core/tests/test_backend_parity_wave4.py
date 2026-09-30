from __future__ import annotations

import asyncio
import json
import sys
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas.memory import MemoryStore
from atlas.agent.checkpoints import ShadowGitCheckpointStore
from atlas.runtime.backend_host import AgentBackendHost
from atlas.runtime.external_agents import external_agent_status, normalize_external_event
from atlas.runtime.external_process import ExternalProcessAdapter
from atlas.agent.enrichment import DelegationService
from atlas.ssh import SSHWorkspaceManager
from atlas.agent import _ssh_paths_allowed
from atlas.task_artifacts import DEFAULT_PROFILES, TomlRecordStore, seed_profiles
from atlas.server import RunState, _execute_external_agent, _handle_rules_trust


def test_builtin_profile_names_and_descriptions_are_chinese() -> None:
    profiles = {profile["id"]: profile for profile in DEFAULT_PROFILES}
    assert set(profiles) >= {"default", "architect", "reviewer"}
    for profile_id in ("default", "architect", "reviewer"):
        assert any("\u4e00" <= char <= "\u9fff" for char in profiles[profile_id]["name"])
        assert any("\u4e00" <= char <= "\u9fff" for char in profiles[profile_id]["description"])


def test_profile_seeding_localizes_existing_builtin_records(tmp_path: Path) -> None:
    store = TomlRecordStore(tmp_path, "profiles")
    store.put({
        "id": "reviewer", "name": "Reviewer", "description": "Read-only code review",
        "instructions": "Review code for correctness, regressions, and security issues. Do not modify files.",
        "tools": {"allow": ["local_file"], "deny": []},
        "mode": "act", "active_skills": ["existing-skill"],
    })

    seed_profiles(store)
    reviewer = store.get("reviewer")
    assert reviewer["name"] == "审查员"
    assert reviewer["description"] == "只读代码审查"
    assert reviewer["tools"]["allow"] == ["local_file"]
    assert reviewer["active_skills"] == ["existing-skill"]


def test_allowed_paths_check_ssh_paths_after_remote_normalization() -> None:
    workspace = "ssh://host/D:/work/project"
    assert _ssh_paths_allowed(
        workspace, ["D:/work/project/src"], ["src/module.py"],
    )
    assert not _ssh_paths_allowed(
        workspace, ["D:/work/project/src"], ["../secrets.txt"],
    )


@pytest.mark.asyncio
async def test_conversation_runtime_settings_are_persisted(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    conversation_id = await store.create_conversation("settings")
    await store.update_conversation(
        conversation_id,
        workspace=r"D:\Atlas",
        permission_mode="ask_writes",
        allowed_paths=[r"D:\Atlas\core"],
        executor="codex",
        sandbox={"type": "docker", "network": False},
        sandbox_set=True,
    )

    conversation = await store.get_conversation(conversation_id)
    assert conversation["workspace"] == r"D:\Atlas"
    assert conversation["permission_mode"] == "ask_writes"
    assert conversation["allowed_paths"] == [r"D:\Atlas\core"]
    assert conversation["executor"] == "codex"
    assert conversation["sandbox"] == {"type": "docker", "network": False}
    assert (await store.list_conversations())[0]["sandbox"] == {
        "type": "docker", "network": False,
    }
    await store.close()


@pytest.mark.asyncio
async def test_rules_trust_falls_back_to_run_id_and_errors_when_unmatched(monkeypatch) -> None:
    from atlas import server

    run = RunState("trust-run", "conversation", "model")
    run.trust_future = asyncio.get_running_loop().create_future()
    run.trust_event_id = "trust-run:2"
    monkeypatch.setitem(server.runtime_mgr.runs, run.run_id, run)
    sent: list[dict] = []

    async def send(conn_id: str, frame: dict) -> None:
        sent.append(frame)

    monkeypatch.setattr(server.runtime_mgr, "send", send)
    await _handle_rules_trust("conn", {
        "run_id": run.run_id, "event_id": "stale-event", "trust": False,
    })
    assert run.trust_future.result() is False

    await _handle_rules_trust("conn", {
        "run_id": "missing-run", "event_id": "stale-event", "trust": True,
    })
    assert sent[-1]["type"] == "error"


def test_external_agent_status_uses_version_command_and_cache(monkeypatch) -> None:
    from atlas.runtime import external_agents

    calls: list[list[str]] = []
    monkeypatch.setattr(external_agents.shutil, "which", lambda _name: sys.executable)

    def run(argv, **_kwargs):
        calls.append(argv)
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0, stdout="fake-cli 1.2.3", stderr="")

    monkeypatch.setattr(external_agents.subprocess, "run", run)
    cache: dict = {}
    result = external_agent_status(cache, now=10)
    assert len(result["agents"]) == 5
    assert all(agent["available"] and agent["version"] == "fake-cli 1.2.3"
               for agent in result["agents"])
    assert len(calls) == 5
    assert external_agent_status(cache, now=30) == result
    assert len(calls) == 5
    external_agent_status(cache, now=71)
    assert len(calls) == 10


def test_external_agent_json_events_normalize_to_atlas_events() -> None:
    pending: dict = {}
    message = normalize_external_event("update", {
        "update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "Hello"},
        },
    }, pending)
    started = normalize_external_event("update", {
        "update": {
            "sessionUpdate": "tool_call", "toolCallId": "tc-1",
            "title": "run_command", "rawInput": {"command": "pytest"},
        },
    }, pending)
    completed = normalize_external_event("update", {
        "update": {
            "sessionUpdate": "tool_call_update", "toolCallId": "tc-1",
            "status": "completed", "content": "2 passed",
        },
    }, pending)

    assert message == [("reply.delta", {"content": "Hello"})]
    assert started[0][0] == "tool.started"
    assert started[0][1]["name"] == "external:run_command"
    assert completed[0][0] == "tool.completed"
    assert completed[0][1]["result"] == "2 passed"


@pytest.mark.asyncio
async def test_external_agent_fake_json_cli_emits_events_and_checkpoints(
    tmp_path: Path, monkeypatch,
) -> None:
    from atlas import server

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "--quiet", str(workspace)], check=True)
    fake = tmp_path / "fake_agent.py"
    fake.write_text(
        """import json, pathlib
pathlib.Path('external.txt').write_text('made by fake agent')
for item in [
 {'type':'agent_message_chunk','content':{'type':'text','text':'hello '}},
 {'type':'tool_call','toolCallId':'tool-1','title':'run_command','rawInput':{'command':'echo ok'}},
 {'type':'tool_call_update','toolCallId':'tool-1','status':'completed','content':'ok'},
 {'type':'agent_message_chunk','content':{'type':'text','text':'world'}},
 {'type':'agent_end'}]:
 print(json.dumps(item), flush=True)
""",
        encoding="utf-8",
    )
    backend = ExternalProcessAdapter(
        "codex", sys.executable, [str(fake)], protocol="pi-rpc",
    )
    monkeypatch.setattr(server, "agent_backend_host", AgentBackendHost({"codex": backend}))
    store = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(checkpoints=store))
    run = RunState("external-test-run", "conversation", "model")
    run.executor = "codex"
    events: list[tuple[str, dict]] = []

    async def emit(name: str, data: dict) -> None:
        events.append((name, data))

    response, changed = await _execute_external_agent(
        run, "original prompt", str(workspace), emit,
    )
    assert response == "hello world"
    assert changed == ["external.txt"]
    assert [name for name, _ in events] == [
        "reply.delta", "tool.started", "tool.completed", "reply.delta",
    ]
    snapshots = store.list_checkpoints(str(workspace), run_id=run.run_id)
    assert len(snapshots) == 2
    assert server._run_changes(run.run_id)["files"][0]["path"] == "external.txt"


@pytest.mark.asyncio
async def test_external_agent_cancel_closes_fake_cli_process(tmp_path: Path, monkeypatch) -> None:
    from atlas import server

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    fake = tmp_path / "fake_waiting_agent.py"
    fake.write_text(
        """import json, sys, time
line = sys.stdin.readline()
print(json.dumps({'type':'agent_message_chunk','content':{'type':'text','text':'working'}}), flush=True)
while True:
 line = sys.stdin.readline()
 if not line:
  time.sleep(.02)
  continue
 if json.loads(line).get('type') in {'abort', 'exit'}:
  break
""",
        encoding="utf-8",
    )
    backend = ExternalProcessAdapter(
        "codex", sys.executable, [str(fake)], protocol="pi-rpc",
    )
    host = AgentBackendHost({"codex": backend})
    monkeypatch.setattr(server, "agent_backend_host", host)
    monkeypatch.setattr(server, "orchestrator", None)
    run = RunState("external-cancel-run", "conversation", "model")
    run.executor = "codex"
    emitted: list[str] = []

    async def emit(name: str, _data: dict) -> None:
        emitted.append(name)

    task = asyncio.create_task(
        _execute_external_agent(run, "original prompt", str(workspace), emit),
    )
    for _ in range(50):
        if emitted:
            break
        await asyncio.sleep(0.02)
    run.cancel_event.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert host.sessions == {}
    assert "reply.delta" in emitted


@pytest.mark.asyncio
async def test_delegate_parallel_limits_workers_continues_failure_and_summarizes_once() -> None:
    class Hooks:
        async def emit(self, *_args, **_kwargs):
            return None

    class Service(DelegationService):
        def __init__(self):
            super().__init__(object(), Hooks())
            self.active = 0
            self.max_active = 0

        async def delegate_task(self, goal, context=None, tool_profile=None, **kwargs):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.02)
            self.active -= 1
            if goal == "fail":
                raise RuntimeError("worker failed")
            return {"status": "completed", "result": goal, "changed_files": [goal + ".py"]}

    service = Service()
    summary_calls: list[list[dict]] = []

    async def summarize(results):
        summary_calls.append(results)
        return "combined summary"

    result = await service.delegate_parallel(
        [
            {"title": "A", "goal": "alpha"},
            {"title": "B", "goal": "fail"},
            {"title": "C", "goal": "gamma"},
        ],
        max_concurrency=2,
        summarize=summarize,
    )
    assert service.max_active == 2
    assert [item["status"] for item in result["results"]] == [
        "completed", "failed", "completed",
    ]
    assert result["results"][0]["changed_files"] == ["alpha.py"]
    assert result["summary"] == "combined summary"
    assert len(summary_calls) == 1


@pytest.mark.asyncio
async def test_delegate_parallel_returns_isolated_worktree_patches(tmp_path: Path) -> None:
    class Hooks:
        async def emit(self, *_args, **_kwargs):
            return None

    class Service(DelegationService):
        async def delegate_task(
            self, goal, context=None, tool_profile=None, *, cwd=None,
            on_started=None, on_completed=None, event_metadata=None, **_kwargs,
        ):
            await on_started(goal, goal, "fake", event_metadata)
            Path(cwd, f"{goal}.txt").write_text(goal, encoding="utf-8")
            await on_completed(goal, "completed", goal, 1, event_metadata)
            return {"status": "completed", "result": goal}

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "seed"], check=True)

    service = Service(object(), Hooks())
    result = await service.delegate_parallel([
        {"title": "one", "goal": "one"},
        {"title": "two", "goal": "two"},
    ], cwd=str(repo), summarize=lambda _results: "patches ready")

    assert result["summary"] == "patches ready"
    assert all(item["status"] == "completed" for item in result["results"])
    assert all(f"{item['title']}.txt" in item["changed_files"] for item in result["results"])
    assert all(item["title"] in item["patch"] for item in result["results"])
    assert not (repo / "one.txt").exists()
    assert not (repo / "two.txt").exists()


@pytest.mark.asyncio
async def test_delegate_parallel_cancels_active_workers() -> None:
    class Hooks:
        async def emit(self, *_args, **_kwargs):
            return None

    child_events: list[asyncio.Event] = []

    class Service(DelegationService):
        async def delegate_task(
            self, goal, context=None, tool_profile=None, *, on_started=None,
            event_metadata=None, **_kwargs,
        ):
            child = await on_started(goal, goal, "fake", event_metadata)
            child_events.append(child)
            await child.wait()
            raise asyncio.CancelledError

    service = Service(object(), Hooks())
    parent = asyncio.Event()

    async def on_started(*_args):
        child = asyncio.Event()
        child_events.append(child)
        return child

    task = asyncio.create_task(service.delegate_parallel(
        [{"title": "one", "goal": "work"}], cancel_event=parent,
        summarize=lambda _results: "cancelled",
        on_started=on_started,
    ))
    for _ in range(50):
        if child_events:
            break
        await asyncio.sleep(0.01)
    parent.set()
    result = await task
    assert child_events and child_events[0].is_set()
    assert result["results"][0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_real_ssh_workspace_when_configured(monkeypatch) -> None:
    import os
    import uuid

    host = os.environ.get("ATLAS_SSH_TEST_HOST")
    root = os.environ.get("ATLAS_SSH_TEST_ROOT")
    if not host or not root:
        pytest.skip("set ATLAS_SSH_TEST_HOST and ATLAS_SSH_TEST_ROOT for a real SSH check")

    manager = SSHWorkspaceManager()
    workspace = f"ssh://{host}/{root.lstrip('/').replace(chr(92), '/')}"
    _host, remote_root = manager.parse_workspace(workspace)
    connection = await manager._connect(_host)
    assert connection.client
    remote_windows = await manager.remote_os(_host) == "windows"
    leaf = f"atlas-wave4-{uuid.uuid4().hex}"
    directory = manager._remote_path(remote_root, leaf)
    file_path = manager._remote_path(remote_root, f"{leaf}/roundtrip.txt")
    await manager.call_tool("local_file", {
        "action": "mkdir", "path": leaf,
    }, workspace)
    await manager.call_tool("local_file", {
        "action": "write", "path": f"{leaf}/roundtrip.txt", "content": "wave4",
    }, workspace)
    read = await manager.call_tool("local_file", {
        "action": "read", "path": f"{leaf}/roundtrip.txt",
    }, workspace)
    assert read["data"]["content"] == "wave4"

    nested = manager._remote_path(directory, "child")
    await manager.call_tool("local_file", {"action": "mkdir", "path": f"{leaf}/child"}, workspace)
    result = await manager.call_tool("local_shell", {
        "command": "Get-Location" if remote_windows else "pwd", "cwd": nested,
    }, workspace)
    assert result["data"]["exit_code"] == 0
    assert nested.casefold() in result["data"]["stdout"].replace("\\", "/").casefold()
    if remote_windows:
        windows_cwd = remote_root[1:] if remote_root.startswith("/") else remote_root
        cwd_result = await manager.call_tool("local_shell", {
            "command": "Get-Location", "cwd": windows_cwd,
        }, workspace)
        assert cwd_result["data"]["exit_code"] == 0
    with pytest.raises(ValueError):
        manager._remote_path(remote_root, "../outside")
    await manager.call_tool("local_file", {"action": "delete", "path": leaf}, workspace)

