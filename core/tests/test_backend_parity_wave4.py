from __future__ import annotations

import asyncio
import json
import sys
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from atlas.memory import MemoryStore
from atlas.agent.checkpoints import ShadowGitCheckpointStore
from atlas.agent import AgentOrchestrator
from atlas.office import create_document, create_presentation, create_spreadsheet, read_office, render_office
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
        "message.delta", "tool.started", "tool.completed", "message.delta",
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
    assert "message.delta" in emitted


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


def test_office_files_generate_read_and_preview_without_scripts(tmp_path: Path) -> None:
    document = create_document(str(tmp_path), {
        "path": "brief.docx", "title": "Brief", "blocks": [
            {"type": "heading", "text": "Summary", "level": 1},
            {"type": "paragraph", "text": "<safe & escaped>"},
            {"type": "bullets", "items": ["one", "two"]},
            {"type": "table", "rows": [["Name", "Count"], ["Tasks", 3]]},
        ],
    })
    spreadsheet = create_spreadsheet(str(tmp_path), {
        "path": "data.xlsx", "sheets": [{
            "name": "Totals", "header": True,
            "rows": [["Amount"], [2], [3], ["=SUM(A2:A3)"]],
            "column_widths": [22],
        }],
    })
    presentation = create_presentation(str(tmp_path), {
        "path": "slides.pptx", "slides": [{
            "title": "Overview", "bullets": ["first", "second"], "notes": "speaker note",
        }],
    })

    assert document["kind"] == "document" and document["bytes"] > 0
    assert spreadsheet["kind"] == "spreadsheet" and spreadsheet["bytes"] > 0
    assert presentation["kind"] == "presentation" and presentation["bytes"] > 0
    assert "Summary" in str(read_office(str(tmp_path / "brief.docx")))
    assert "=SUM(A2:A3)" in str(read_office(str(tmp_path / "data.xlsx")))
    assert "Overview" in str(read_office(str(tmp_path / "slides.pptx")))
    for path in ("brief.docx", "data.xlsx", "slides.pptx"):
        html = render_office((tmp_path / path).read_bytes(), "." + path.split(".")[-1])
        assert "<script" not in html.casefold()
        assert "&lt;safe &amp; escaped&gt;" in html if path == "brief.docx" else True


@pytest.mark.asyncio
async def test_workspace_preview_uses_sandbox_headers(tmp_path: Path) -> None:
    from atlas.api.workspace_router import workspace_preview

    create_document(str(tmp_path), {
        "path": "preview.docx", "blocks": [{"type": "paragraph", "text": "safe"}],
    })
    response = await workspace_preview(SimpleNamespace(), str(tmp_path), "preview.docx")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == (
        "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    )
    assert b"<script" not in response.body.lower()


@pytest.mark.asyncio
async def test_office_tool_creates_checkpoint_and_artifact_event(tmp_path: Path) -> None:
    store = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    agent = AgentOrchestrator(
        MagicMock(), MagicMock(), checkpoint_store=store,
    )
    events = asyncio.Queue()
    runtime = SimpleNamespace(
        cancel_event=None, pause_event=None, approval_callback=None,
        event_queue=events, workspace=str(tmp_path), permission_mode="full_access",
        allowed_paths=[], run_id="office-run", conversation_id="conversation",
    )
    result = await agent._execute_tools_node({
        "messages": [AIMessage(content="", tool_calls=[{
            "name": "create_spreadsheet",
            "args": {"path": "result.xlsx", "sheets": [
                {"name": "Sheet1", "rows": [["value"], [1]]},
            ]},
            "id": "office-call",
        }])],
        "pending_events": [], "tool_rounds": 0, "runtime": runtime,
    })
    assert (tmp_path / "result.xlsx").is_file()
    checkpoint_event = await events.get()
    artifact_event = await events.get()
    assert checkpoint_event["type"] == "checkpoint_created"
    assert artifact_event == {
        "type": "artifact_created", "path": str(tmp_path / "result.xlsx"),
        "kind": "spreadsheet", "bytes": (tmp_path / "result.xlsx").stat().st_size,
    }
    assert result["messages"][0].tool_call_id == "office-call"


@pytest.mark.asyncio
async def test_workspace_history_orders_versions_and_snapshots_before_restore(
    tmp_path: Path, monkeypatch,
) -> None:
    from atlas import server

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"
    target.write_text("first", encoding="utf-8")
    store = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    first = store.create_checkpoint(workspace, ["note.txt"], run_id="first-run")
    target.write_text("second", encoding="utf-8")
    store.create_checkpoint(workspace, ["note.txt"], run_id="second-run")
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(checkpoints=store))

    # H5: the workspace history surface lives on atlas.api.workspace_router now;
    # its per-app services container falls back to atlas.server for the
    # orchestrator seam patched above.
    from atlas.api.workspace_router import (
        restore_workspace_history,
        workspace_history,
        workspace_history_content,
        workspace_history_raw,
    )

    services = SimpleNamespace()
    history = await workspace_history(services, str(workspace), "note.txt")
    assert [item["run_id"] for item in history["versions"]] == ["second-run", "first-run"]
    old = await workspace_history_content(
        services, str(workspace), "note.txt", f"checkpoint:{first['id']}",
    )
    assert old["content"] == "first"
    class RestoreRequest:
        async def json(self):
            return {
                "root": str(workspace), "path": "note.txt",
                "version": f"checkpoint:{first['id']}",
            }

    restored = await restore_workspace_history(services, RestoreRequest())
    assert restored["restored"] is True
    assert target.read_text(encoding="utf-8") == "first"
    assert any(item["id"] == restored["checkpoint_id"]
               for item in store.list_checkpoints(workspace))
    raw = await workspace_history_raw(
        services, str(workspace), "note.txt", f"checkpoint:{first['id']}",
    )
    assert raw.body == b"first"
    assert raw.headers["content-security-policy"].startswith("sandbox;")


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


@pytest.mark.asyncio
async def test_docker_sandbox_mounts_workspace_disables_network_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from atlas.sandbox import DockerSandboxManager
    import atlas.sandbox as sandbox_module

    manager = DockerSandboxManager()
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        if command[1] == "run":
            return SimpleNamespace(returncode=0, stdout="container-123\n", stderr="")
        if command[1] == "exec":
            return SimpleNamespace(returncode=0, stdout="/workspace/sub/file.py", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _name: "docker-mock")
    monkeypatch.setattr(sandbox_module.subprocess, "run", fake_run)
    await manager.start("run-1", str(tmp_path), {"type": "docker"})
    start_args = calls[0]
    assert "-v" in start_args and f"{tmp_path.resolve()}:/workspace" in start_args
    assert start_args[start_args.index("--network") + 1] == "none"
    result = await manager.call_tool("run-1", "local_exec", {
        "executable": "python", "args": ["-V"], "cwd": str(tmp_path / "sub"),
    })
    assert "-w" in calls[1] and calls[1][calls[1].index("-w") + 1] == "/workspace/sub"
    assert result["data"]["stdout"] == f"{tmp_path.resolve()}/sub/file.py"
    await manager.stop("run-1")
    assert calls[2][1:3] == ["rm", "-f"]
    assert "run-1" not in manager._containers


@pytest.mark.asyncio
async def test_docker_sandbox_cleanup_runs_after_failure_or_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from atlas.sandbox import DockerSandboxManager
    import atlas.sandbox as sandbox_module

    manager = DockerSandboxManager()
    removed: list[str] = []
    fail_start = False

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        if command[1] == "run":
            return SimpleNamespace(returncode=1 if fail_start else 0,
                                   stdout="" if fail_start else "container-123", stderr="start failed")
        if command[1] == "exec":
            return SimpleNamespace(returncode=1, stdout="", stderr="command failed")
        removed.append(command[-1])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _name: "docker-mock")
    monkeypatch.setattr(sandbox_module.subprocess, "run", fake_run)
    await manager.start("failed", str(tmp_path), {"type": "docker"})
    try:
        await manager.call_tool("failed", "local_shell", {
            "shell": "cmd", "command": "exit 1", "cwd": str(tmp_path),
        })
    finally:
        await manager.stop("failed")
    await manager.start("cancelled", str(tmp_path), {"type": "docker"})
    try:
        raise asyncio.CancelledError
    except asyncio.CancelledError:
        await manager.stop("cancelled")
    assert removed == ["container-123", "container-123"]


@pytest.mark.asyncio
async def test_docker_sandbox_rejects_paths_outside_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from atlas.sandbox import DockerSandboxManager
    import atlas.sandbox as sandbox_module

    manager = DockerSandboxManager()
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _name: "docker-mock")
    monkeypatch.setattr(sandbox_module.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout="container-123", stderr="",
    ))
    await manager.start("run", str(tmp_path), {"type": "docker"})
    with pytest.raises(PermissionError, match="工作目录内"):
        await manager.call_tool("run", "local_shell", {
            "shell": "cmd", "command": "echo unsafe", "cwd": str(tmp_path.parent),
        })


@pytest.mark.asyncio
async def test_agent_denies_computer_tools_in_docker_sandbox(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock

    agent = AgentOrchestrator(MagicMock(), MagicMock())
    runtime = SimpleNamespace(
        cancel_event=None, pause_event=None, approval_callback=None,
        event_queue=asyncio.Queue(), workspace=str(tmp_path), permission_mode="full_access",
        allowed_paths=[str(tmp_path)], run_id="sandbox-run", conversation_id="conversation",
        sandbox_enabled=True, sandbox_tool_callback=AsyncMock(), mode="act",
    )
    result = await agent._execute_tools_node({
        "messages": [AIMessage(content="", tool_calls=[{
            "name": "computer_click", "args": {"x": 10, "y": 20}, "id": "blocked-call",
        }])],
        "pending_events": [], "tool_rounds": 0, "runtime": runtime,
    })
    assert "Docker 沙箱模式下禁用 Web、浏览器、MCP 和电脑操作工具。" in result["messages"][0].content
    assert result["pending_events"][-1]["is_error"] is True



@pytest.fixture
def restore_app_services():
    """Snapshot ``app.state.services`` around the one TestClient test.

    ``TestClient(atlas.server.app)`` runs the module-level app's lifespan,
    which repopulates the shared container in place; its shutdown restores
    routes but never the container slots, so the lifespan-built services
    (bound to this test's tmp config) would leak into later tests.
    """
    from dataclasses import fields

    from atlas.api.app_services import AppServices

    from atlas.server import app

    services = app.state.services
    snapshot = {f.name: getattr(services, f.name) for f in fields(AppServices)}
    runtime_manager = services.runtime_mgr
    yield
    for field in fields(AppServices):
        setattr(services, field.name, snapshot[field.name])
    # create_app bound the container to its runtime manager; the lifespan's
    # shutdown path clears that back-reference, so restore the import-time one.
    runtime_manager.services = services


def test_external_agent_refused_unless_full_access(monkeypatch, tmp_path: Path, restore_app_services) -> None:
    """External Agents auto-approve their own permission prompts, so only full access may start one."""
    import json as _json

    from starlette.testclient import TestClient

    from atlas.config import AtlasConfig
    from atlas.telegram import TelegramService
    from atlas.server import app as _app

    monkeypatch.setattr("atlas.server.get_config", lambda: AtlasConfig({
        "memory": {"db_path": str(tmp_path / "atlas-test.sqlite3")},
        "scheduler": {"enabled": False},
    }))
    # This authorization test does not need a channel poller or any credential store.
    monkeypatch.setattr(TelegramService, "start", lambda _self: None)
    with TestClient(_app) as tc:
        for mode, label in (("ask_writes", "改前问我"), ("read_only", "只读")):
            with tc.websocket_connect("/ws/chat") as ws:
                ws.send_text(_json.dumps({
                    "type": "run.start", "run_id": f"external-{mode}", "content": "hi",
                    "conversation_id": f"external-{mode}-conv", "executor": "codex",
                    "permission_mode": mode,
                }))
                failed = None
                for _ in range(50):
                    event = _json.loads(ws.receive_text())
                    if event.get("event") == "run.failed":
                        failed = event["data"]
                        break
                assert failed is not None
                assert failed["category"] == "permission"
                assert label in failed["detail"]


@pytest.mark.asyncio
async def test_delegation_explains_when_no_external_agent_is_installed(monkeypatch) -> None:
    """Workers used to be sent to Hermes blindly and died with 'file not found'."""
    from atlas.runtime import external_agents

    class Hooks:
        async def emit(self, *_args, **_kwargs):
            return None

    host = SimpleNamespace(backends={"hermes": object(), "claude": object()})
    monkeypatch.setattr(external_agents, "external_agent_status", lambda cache: {"agents": [
        {"id": "hermes", "available": False}, {"id": "claude", "available": False},
    ]})
    service = DelegationService(host, Hooks())
    with pytest.raises(RuntimeError, match="没有装"):
        await service._pick_backend()

    monkeypatch.setattr(external_agents, "external_agent_status", lambda cache: {"agents": [
        {"id": "hermes", "available": False}, {"id": "claude", "available": True},
    ]})
    assert await DelegationService(host, Hooks())._pick_backend() == "claude"
