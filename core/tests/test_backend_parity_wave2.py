"""Focused regression coverage for Backend Parity Wave 2 contracts."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from atlas import server
from atlas.agent.enrichment import DelegationService
from atlas.agent.enrichment import AtlasToolBridge
from atlas.agent.results import externalize_tool_output
from atlas.memory import MemoryStore
from atlas.scheduler import AtlasScheduler, ScheduledTask, TriggerType
from atlas.task_artifacts import TomlRecordStore, WorktreeService, seed_profiles


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _git_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    _git(root, "config", "user.email", "atlas-test@example.invalid")
    _git(root, "config", "user.name", "Atlas Test")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "initial")


def test_worktree_create_status_merge_and_dirty_remove(tmp_path: Path) -> None:
    repo = tmp_path / "sample"
    _git_repo(repo)
    service = WorktreeService(tmp_path)
    record = service.create(repo, "conversation-1234")
    path = Path(record["worktree_path"])
    assert path.is_dir()
    assert record["worktree_branch"] == "atlas/conversa"
    (path / "README.md").write_text("changed\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "change")
    status = service.status(repo, path, record["worktree_branch"], record["base_branch"])
    assert not status["dirty"] and status["ahead"] == 1
    service.merge(repo, path, record["worktree_branch"], record["base_branch"], "squash")
    assert (repo / "README.md").read_text("utf-8") == "changed\n"
    (path / "dirty.txt").write_text("dirty", encoding="utf-8")
    status = service.status(repo, path, record["worktree_branch"], record["base_branch"])
    assert status["dirty"] and "dirty.txt" in status["changed_files"]
    with pytest.raises(RuntimeError):
        service.remove(repo, path, record["worktree_branch"])
    service.remove(repo, path, record["worktree_branch"], force=True)


def test_worktree_rejects_non_git_workspace(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a git repository"):
        WorktreeService(tmp_path).create(tmp_path / "plain", "conversation")


@pytest.mark.parametrize("strategy", ["merge", "squash"])
def test_worktree_merge_conflict_leaves_base_without_merge_state(tmp_path: Path, strategy: str) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    service = WorktreeService(tmp_path)
    record = service.create(repo, "conflict-conversation")
    path = Path(record["worktree_path"])
    (path / "README.md").write_text("worktree\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "worktree change")
    (repo / "README.md").write_text("base change\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base change")
    with pytest.raises(FileExistsError) as conflict:
        service.merge(repo, path, record["worktree_branch"], "main", strategy)
    assert "README.md" in str(conflict.value)
    assert (repo / "README.md").read_text("utf-8") == "base change\n"
    assert not (repo / ".git" / "MERGE_HEAD").exists()
    service.remove(repo, path, record["worktree_branch"], keep_branch=True)


async def test_subtask_delegation_emits_lifecycle_and_throttled_progress() -> None:
    class Host:
        backends = {"fake": object()}

        async def start(self, name, cwd):
            return SimpleNamespace(id="child")

        async def send(self, session_id, prompt):
            return None

        async def close(self, session_id):
            return None

        async def events(self, session_id):
            yield SimpleNamespace(type="message", data={"text": "child output"})
            yield SimpleNamespace(type="message", data={"text": "immediate second chunk"})

    class Hooks:
        async def emit(self, *args, **kwargs):
            return None

    started, progress, completed = [], [], []

    async def on_started(*args):
        started.append(args)

    async def on_progress(*args):
        progress.append(args)

    async def on_completed(*args):
        completed.append(args)

    result = await DelegationService(Host(), Hooks()).delegate_task(
        "inspect", backend="fake", on_started=on_started,
        on_progress=on_progress, on_completed=on_completed,
    )
    assert result["status"] == "completed"
    assert started[0][1:3] == ("inspect", "fake")
    assert len(progress) == 1 and progress[0][1] == "child output"
    assert completed[0][1] == "completed"
    assert completed[0][2] == "child output\nimmediate second chunk"


async def test_subtask_cancel_emits_cancelled_completion() -> None:
    release = asyncio.Event()

    class Host:
        backends = {"fake": object()}

        async def start(self, name, cwd):
            return SimpleNamespace(id="child")

        async def send(self, session_id, prompt):
            return None

        async def close(self, session_id):
            return None

        async def events(self, session_id):
            await release.wait()
            if False:
                yield None

    class Hooks:
        async def emit(self, *args, **kwargs):
            return None

    done = []

    async def on_started(*args):
        cancel_event = asyncio.Event()
        asyncio.get_running_loop().call_later(0.02, cancel_event.set)
        return cancel_event

    async def on_completed(*args):
        done.append(args)

    result = await DelegationService(Host(), Hooks(), timeout=2).delegate_task(
        "cancel me", backend="fake", on_started=on_started,
        on_completed=on_completed,
    )
    assert result["status"] == "cancelled" and done[0][1] == "cancelled"


async def test_subtask_cancel_endpoint_sets_child_cancellation_only() -> None:
    run = server.RunState("parent", "conversation", "model")
    cancellation = asyncio.Event()
    run.subtasks["child"] = {"status": "running", "cancel_event": cancellation}
    server.runtime_mgr.runs[run.run_id] = run
    try:
        result = await server.cancel_subtask("parent", "child")
        assert result["status"] == "cancelling" and cancellation.is_set()
        with pytest.raises(HTTPException) as missing:
            await server.cancel_subtask("parent", "missing")
        assert missing.value.status_code == 404
    finally:
        server.runtime_mgr.runs.pop(run.run_id, None)


async def test_recipe_storage_render_and_missing_parameters(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(server, "_task_store", lambda kind: TomlRecordStore(tmp_path, kind))
    recipe = await server.create_recipe({
        "name": "Review", "description": "Review a module", "prompt": "Review {{target}}",
        "params": [{"name": "target", "label": "Target"}], "active_skills": ["code-review"],
        "mode": "plan",
    })
    rendered = await server.render_recipe(recipe["id"], {"params": {"target": "core"}})
    assert rendered["prompt"] == "Review core"
    assert rendered["mode"] == "plan"
    updated = await server.update_recipe(recipe["id"], {"description": "Updated"})
    assert updated["description"] == "Updated"
    assert len((await server.list_recipes())["recipes"]) == 1
    with pytest.raises(HTTPException) as error:
        await server.render_recipe(recipe["id"], {"params": {}})
    assert error.value.status_code == 422
    assert error.value.detail == {"missing": ["target"]}
    assert (await server.delete_recipe(recipe["id"]))["status"] == "deleted"


async def test_recipe_from_run_keeps_input_skills_mode_and_workspace(tmp_path: Path, monkeypatch) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    conversation_id = await store.create_conversation("saved run")
    await store.save_message(conversation_id, "user", "raw message")
    monkeypatch.setattr(server, "memory", store)
    monkeypatch.setattr(server, "_task_store", lambda kind: TomlRecordStore(tmp_path / "data", kind))
    run = server.RunState("saved-run", conversation_id, "model")
    run.user_input = "input with context"
    run.active_skills = ["skill-one"]
    run.mode = "plan"
    run.workspace = str(tmp_path)
    run.profile_id = "architect"
    monkeypatch.setitem(server.runtime_mgr.runs, run.run_id, run)
    recipe = await server.recipe_from_run({"run_id": run.run_id, "name": "Reusable"})
    assert recipe["prompt"] == "input with context"
    assert recipe["active_skills"] == ["skill-one"]
    assert recipe["mode"] == "plan" and recipe["workspace"] == str(tmp_path)
    assert recipe["profile_id"] == "architect"
    await store.close()


async def test_profile_builtins_and_validation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(server, "_task_store", lambda kind: TomlRecordStore(tmp_path, kind))
    profiles = (await server.list_profiles())["profiles"]
    assert {p["id"] for p in profiles} >= {"default", "architect", "reviewer"}
    architect = next(p for p in profiles if p["id"] == "architect")
    assert architect["mode"] == "plan" and architect["tools"]["allow"]
    created = await server.create_profile({"name": "Read only", "tools": {"allow": ["local_file"]}})
    assert created["tools"]["allow"] == ["local_file"]
    assert (await server.update_profile(created["id"], {"name": "Renamed"}))["name"] == "Renamed"
    assert (await server.delete_profile(created["id"]))["status"] == "deleted"
    with pytest.raises(HTTPException) as error:
        await server.delete_profile("default")
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as invalid:
        await server.create_profile({"name": "Broken", "mode": "unsafe"})
    assert invalid.value.status_code == 422
    bridge = AtlasToolBridge(local=SimpleNamespace(call_tool=lambda *args: None))
    with pytest.raises(PermissionError):
        await bridge.call_tool("local_edit", {}, tool_deny=["local_edit"])
    with pytest.raises(PermissionError):
        await bridge.call_tool("local_file", {"action": "write"}, read_only=True)


def test_reasoning_support_probe_uses_litellm_capability_and_fails_closed(monkeypatch) -> None:
    import litellm

    monkeypatch.setattr(litellm, "get_supported_openai_params", lambda **kwargs: ["reasoning_effort"])
    assert server._model_supports_reasoning({"litellm_model": "known/model"}) is True
    monkeypatch.setattr(litellm, "get_supported_openai_params", lambda **kwargs: None)
    assert server._model_supports_reasoning({"litellm_model": "unknown/model"}) is False


async def test_workspace_search_respects_gitignore_and_fuzzy_filename(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    (repo / ".gitignore").write_text("secret/\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "AgentConfig.py").write_text("x", encoding="utf-8")
    (repo / "secret").mkdir()
    (repo / "secret" / "AgentConfig.py").write_text("x", encoding="utf-8")
    result = await server.workspace_search(str(repo), "agcfg")
    assert result["files"] == [{"path": "src/AgentConfig.py", "name": "AgentConfig.py", "type": "file"}]


async def test_workspace_search_honors_gitignore_without_repository(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    (root / "secret").mkdir(parents=True)
    (root / "secret" / "Token.txt").write_text("x", encoding="utf-8")
    (root / "visible").mkdir()
    (root / "visible" / "Token.txt").write_text("x", encoding="utf-8")
    (root / ".gitignore").write_text("secret/\n", encoding="utf-8")
    results = await server.workspace_search(str(root), "token")
    assert [item["path"] for item in results["files"]] == ["visible/Token.txt"]


def test_context_file_injection_is_bounded_and_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "context.md").write_text("x" * (70 * 1024), encoding="utf-8")
    block, consumed = server._context_file_block(str(root), "context.md", 256 * 1024)
    assert consumed == 64 * 1024 and "Context file truncated" in block
    with pytest.raises(HTTPException):
        server._context_file_block(str(root), "../secret.md", 256 * 1024)


async def test_ephemeral_run_does_not_change_source_conversation(tmp_path: Path, monkeypatch) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    conversation_id = await store.create_conversation("source")
    await store.save_message(conversation_id, "user", "existing")
    temp_id = await store.create_conversation("temporary")
    await store.save_message(temp_id, "user", "existing")

    class Orchestrator:
        async def run(self, **kwargs):
            yield {"type": "chunk", "content": "answer"}
            yield {"type": "done"}

    monkeypatch.setattr(server, "memory", store)
    monkeypatch.setattr(server, "orchestrator", Orchestrator())
    run = server.RunState("ephemeral-run", temp_id, "model")
    run.ephemeral = True
    run.ephemeral_source = temp_id
    monkeypatch.setattr(server.runtime_mgr, "send_run", lambda *args, **kwargs: asyncio.sleep(0))
    await server._execute_run("test", run, "side question", "model")
    assert [m["content"] for m in await store.get_conversation_messages(conversation_id)] == ["existing"]
    assert await store.get_conversation(temp_id) is None
    await store.close()


async def test_fork_persists_parent_and_message_link(tmp_path: Path, monkeypatch) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    parent = await store.create_conversation("parent")
    message_id = await store.save_message(parent, "user", "question")
    monkeypatch.setattr(server, "memory", store)
    forked = await server.fork_conversation(parent, {"through_message_id": message_id})
    saved = await store.get_conversation(forked["id"])
    assert saved["parent_conversation_id"] == parent
    assert saved["fork_message_id"] == message_id
    await store.close()


async def test_fork_summary_is_first_system_message_and_duplicate_copies_all(tmp_path: Path, monkeypatch) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    parent = await store.create_conversation("summary parent")
    first = await store.save_message(parent, "user", "first")
    await store.save_message(parent, "assistant", "answer")
    monkeypatch.setattr(server, "memory", store)
    monkeypatch.setattr(server, "orchestrator", None)
    forked = await server.fork_conversation(parent, {"through_message_id": first, "summarize": True})
    messages = await store.get_conversation_messages(forked["id"], limit=10)
    assert messages[0]["role"] == "system" and messages[0]["metadata"]["kind"] == "fork_summary"
    duplicate = await server.duplicate_conversation(parent)
    duplicate_messages = await store.get_conversation_messages(duplicate["id"], limit=10)
    assert [m["content"] for m in duplicate_messages] == ["first", "answer"]
    await store.close()


async def test_run_start_reuses_profile_and_assigns_worktree(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    _git_repo(root)
    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    conversation_id = await store.create_conversation("worktree run")
    runtime = server.RuntimeManager()
    monkeypatch.setattr(server, "memory", store)
    monkeypatch.setattr(server, "runtime_mgr", runtime)
    monkeypatch.setattr(server, "model_mgr", SimpleNamespace(current_model="model"))
    monkeypatch.setattr(server, "_task_store", lambda kind: TomlRecordStore(tmp_path / "data", kind))
    captured = {}

    async def no_run(conn_id, run, content, model_id, **kwargs):
        captured.update(run=run, content=content, kwargs=kwargs)

    monkeypatch.setattr(server, "_execute_run", no_run)
    await server._handle_run_start("test", {
        "run_id": "worktree-run", "conversation_id": conversation_id,
        "workspace": str(root), "content": "inspect", "profile_id": "reviewer",
        "worktree": {"base_branch": "main"},
    })
    await runtime.runs["worktree-run"].task
    run = captured["run"]
    assert Path(run.workspace).is_dir() and Path(run.workspace) != root
    assert run.read_only and run.tool_allow
    conversation = await store.get_conversation(conversation_id)
    assert conversation["worktree_branch"] == "atlas/" + conversation_id.replace("-", "")[:8]
    status = await server.conversation_worktree(conversation_id)
    assert status["branch"] == conversation["worktree_branch"]
    branches = await server.git_branches(str(root))
    assert branches["current"] == "main"
    assert (await server.delete_conversation_worktree(conversation_id))["status"] == "removed"
    assert await store.get_conversation(conversation_id) is not None
    await store.close()


async def test_goal_replace_pause_resume(tmp_path: Path, monkeypatch) -> None:
    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    task = ScheduledTask("g", "Goal", "", TriggerType.INTERVAL, {"hours": 1}, "agent:old", goal="old")
    await scheduler.add_task(task)
    calls = []

    async def agent_callback(goal_id, message):
        calls.append((goal_id, message))

    scheduler._agent_callback = agent_callback
    monkeypatch.setattr(server, "scheduler", scheduler)
    result = await server.update_goal("g", {"goal": "new"})
    assert result["goal"] == "new" and result["goal_status"] == "pending"
    assert (await server.get_goal_trace("g", run_id=None))["events"][-1]["event"] == "goal.replaced"
    paused = await server.pause_goal("g")
    assert paused["goal_status"] == "paused" and paused["status"] == "paused"
    assert not await scheduler._invoke_goal_callback("g", "should not run")
    assert calls == []
    resumed = await server.resume_goal("g")
    assert resumed["goal_status"] == "pending" and resumed["status"] == "active"
    assert await scheduler._invoke_goal_callback("g", "now run")
    assert calls == [("g", "now run")]


async def test_workspace_raw_content_type_and_escape(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    sample = root / "preview.html"
    sample.write_text("<h1>preview</h1>", encoding="utf-8")
    response = await server.workspace_raw(str(root), "preview.html")
    body = b"".join([chunk async for chunk in response.body_iterator])
    assert response.media_type == "text/html" and body == b"<h1>preview</h1>"
    with pytest.raises(HTTPException):
        await server.workspace_raw(str(root), "../outside.html")


def test_large_tool_result_is_externalized_with_bounded_preview(tmp_path: Path) -> None:
    text = "A" * 9000 + "B" * 9000
    preview, full_path = externalize_tool_output(text, tmp_path, "run-1", "call-1")
    assert full_path is not None
    assert Path(full_path).read_text("utf-8") == text
    assert "Full tool output saved" in preview and len(preview) < 9000
    mapped = server._map_tool_runtime_event({"type": "tool_result", "id": "call-1", "name": "local_file",
                                              "content": [{"text": preview}],
                                              "data": {"full_output_path": full_path}})
    assert mapped[0] == "tool.completed" and mapped[1]["full_output_path"] == full_path
    assert externalize_tool_output("small", tmp_path, "run-1", "call-2") == ("small", None)


def test_worktree_placement_is_outside_workspace_and_protocol_is_18(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    record = WorktreeService(tmp_path).create(repo, "session-0001")
    assert Path(record["worktree_path"]).is_relative_to(repo.parent / ".atlas-worktrees" / repo.name)
    WorktreeService(tmp_path).remove(repo, Path(record["worktree_path"]), record["worktree_branch"])
    assert asyncio.run(server.runtime_protocol()) == {"version": "1.10"}
