"""Wave 7 backend contract tests adapted from Hermes Agent interfaces.

Source commit: NousResearch/hermes-agent@330d9d6df9c7bffe125ba0ae64a0abc488a7d2c3 (MIT).
Atlas-specific contract checks use isolated files and the native Runtime Event Protocol.
"""

from __future__ import annotations

import asyncio
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from atlas.agent import subagent_worktree
from atlas.agent.enrichment import DelegationService, HookBus
from atlas.agent.delegation_output_schema import build_retry_message, validate_output
from atlas.agent.definitions import list_agent_types
from atlas.agent.todo_state import TodoStore
from atlas.kanban import KanbanStore


def test_agent_definition_imports_supported_markdown_and_opencode_tool_maps(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    (workspace / ".claude/agents").mkdir(parents=True)
    (workspace / ".claude/agents/claude-reviewer.md").write_text(
        "---\nname: claude-reviewer\ndescription: Review changes\ntools: Read, Search\nmodel: fast\n---\nReview only.",
        encoding="utf-8",
    )
    (workspace / ".opencode/agents").mkdir(parents=True)
    (workspace / ".opencode/agents/auditor.md").write_text(
        "---\nname: auditor\ndescription: Audit changes\ntools:\n  read: true\n  edit: false\nmode: subagent\n---\nAudit only.",
        encoding="utf-8",
    )
    (workspace / ".codex/agents").mkdir(parents=True)
    (workspace / ".codex/agents/scribe.toml").write_text(
        'name = "scribe"\ndescription = "Write notes"\ndeveloper_instructions = "Use concise prose."\nmodel = "inherit"\n',
        encoding="utf-8",
    )
    (workspace / ".github/agents").mkdir(parents=True)
    (workspace / ".github/agents/reviewer.agent.md").write_text(
        "---\nname: copilot-reviewer\ndescription: Copilot reviewer\ntools: [Read]\n---\nReview only.",
        encoding="utf-8",
    )
    (workspace / ".atlas/agents").mkdir(parents=True)
    (workspace / ".atlas/agents/reviewer.md").write_text(
        "---\nname: reviewer\ndescription: Atlas reviewer\ntools: Read\n---\nUse Atlas rules.",
        encoding="utf-8",
    )
    types = list_agent_types(tmp_path / "data", workspace, workspace_trusted=True)
    by_name = {item["name"]: item for item in types}
    assert by_name["claude-reviewer"]["tools"] == ["Read", "Search"]
    assert by_name["auditor"]["tools"] == ["read"]
    assert by_name["reviewer"]["source"] == "workspace"
    assert by_name["claude-reviewer"]["trusted"] is True
    assert by_name["reviewer"]["description"] == "Atlas reviewer"
    assert by_name["scribe"]["prompt"] == "Use concise prose."
    assert by_name["scribe"]["source"] == "codex"
    assert by_name["copilot-reviewer"]["source"] == "copilot"


def test_todo_store_revision_merge_limits_and_compaction_injection() -> None:
    store = TodoStore()
    first = store.write([{"id": "a", "content": "Run tests", "status": "pending"}])
    assert first["revision"] == 1
    merged = store.write([{"id": "a", "content": "Run focused tests", "status": "in_progress"}], merge=True)
    assert merged["revision"] == 2
    assert merged["todos"][0]["text"] == "Run focused tests"
    assert "across context compression" in (store.format_for_injection() or "")


def test_kanban_store_persists_dependencies_and_gates_running(tmp_path: Path) -> None:
    store = KanbanStore(tmp_path / "isolated.sqlite")
    board = store.create_board("W07")
    first = store.create_task(board["id"], {"title": "Inspect", "assignee": "explore"})
    second = store.create_task(board["id"], {"title": "Implement", "dependencies": [first["id"]]})
    try:
        store.update_task(board["id"], second["id"], {"status": "running"})
    except ValueError as exc:
        assert "dependencies" in str(exc)
    else:
        raise AssertionError("task ran before its dependency completed")
    store.update_task(board["id"], first["id"], {"status": "done"})
    assert store.update_task(board["id"], second["id"], {"status": "running"})["status"] == "running"


def test_kanban_concurrent_store_initialization_and_board_writes(tmp_path: Path) -> None:
    database = tmp_path / "isolated.sqlite"

    def create(index: int) -> str:
        return KanbanStore(database).create_board(f"Board {index}")["id"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        board_ids = list(pool.map(create, range(12)))

    assert len(set(board_ids)) == 12
    assert len(KanbanStore(database).boards()) == 12


def test_parallel_verification_retries_one_failed_worker(tmp_path: Path) -> None:
    async def run() -> None:
        service = DelegationService(None, HookBus())
        worker_runs = 0

        async def runner(**kwargs):
            nonlocal worker_runs
            if kwargs["goal"].startswith("验收"):
                return {"status": "completed", "result": '{"verified": false, "note": "missing evidence"}'}
            if kwargs["goal"].startswith("复验"):
                return {"status": "completed", "result": '{"verified": true, "note": "evidence present"}'}
            worker_runs += 1
            return {"status": "completed", "result": "worker result"}

        service.atlas_runner = runner
        group = await service.delegate_parallel(
            [{"title": "check", "goal": "produce evidence"}], cwd=str(tmp_path),
            verify={"criteria": "contains evidence"},
        )
        assert group["results"][0]["verified"] is True
        assert worker_runs == 2

    asyncio.run(run())


def test_background_parallel_group_emits_one_combined_completion(tmp_path: Path) -> None:
    async def run() -> None:
        service = DelegationService(None, HookBus())
        completions: list[dict] = []
        service.atlas_runner = lambda **kwargs: asyncio.sleep(0, result={
            "status": "completed", "result": kwargs["goal"],
        })
        group = await service.delegate_parallel(
            [{"title": "one", "goal": "result one"}, {"title": "two", "goal": "result two"}],
            cwd=str(tmp_path), background=True,
            on_group_completed=lambda payload: completions.append(payload),
        )
        assert group["status"] == "running"
        await service.wait_background(group["group_id"])
        assert len(completions) == 1
        assert "one" in completions[0]["summary"] and "two" in completions[0]["summary"]

    asyncio.run(run())


class _Host:
    backends: dict[str, object] = {}


def test_background_delegate_is_retrievable_without_waiting_for_completion() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        service = DelegationService(_Host(), HookBus())

        async def runner(**_kwargs):
            await gate.wait()
            return {"status": "completed", "result": "完成"}

        service.atlas_runner = runner
        started = await service.delegate_task("后台任务", background=True)

        assert started["status"] == "running"
        assert started["subtask_id"]
        assert service.subtask_status(started["subtask_id"])["status"] == "running"

        gate.set()
        await service.wait_background(started["subtask_id"])
        status = service.subtask_status(started["subtask_id"])
        assert status["status"] == "completed"
        assert status["result"] == "完成"

    asyncio.run(scenario())


def test_background_delegate_emits_completion_only_after_worker_finishes() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        completed: list[tuple[str, str]] = []
        service = DelegationService(_Host(), HookBus())

        async def runner(**_kwargs):
            await gate.wait()
            return {"status": "completed", "result": "结果"}

        async def on_completed(subtask_id, _status, summary, _duration, *_extra):
            completed.append((subtask_id, summary))

        service.atlas_runner = runner
        started = await service.delegate_task(
            "延迟任务", background=True, on_completed=on_completed,
        )
        assert completed == []
        gate.set()
        await service.wait_background(started["subtask_id"])
        assert completed == [(started["subtask_id"], "结果")]

    asyncio.run(scenario())


def test_structured_output_validation_keeps_retry_bounded_and_schema_out_of_retry() -> None:
    schema = {"type": "object", "required": ["answer"]}
    valid, errors = validate_output('{"other": "value"}', schema)
    assert not valid
    assert errors

    retry = build_retry_message(errors)
    assert "校验错误" in retry
    assert "OUTPUT CONTRACT" in retry
    assert '"required": ["answer"]' not in retry


def test_structured_output_retries_once_and_keeps_the_last_raw_result() -> None:
    async def scenario() -> None:
        service = DelegationService(_Host(), HookBus())
        contexts: list[str | None] = []
        responses = iter(["not json", "still not json"])

        async def runner(**kwargs):
            contexts.append(kwargs["context"])
            return {"status": "completed", "result": next(responses), "evidence": []}

        service.atlas_runner = runner
        result = await service.delegate_task(
            "Return an answer", output_schema={"type": "object", "required": ["answer"]},
        )
        assert len(contexts) == 2
        assert "structured output" not in (contexts[0] or "").casefold()
        assert "上一次回复" in (contexts[1] or "")
        assert result["result"] == "still not json"
        assert result["schema_valid"] is False
        assert result["schema_errors"]

    asyncio.run(scenario())


def test_subagent_worktree_is_preserved_when_it_contains_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "atlas@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Atlas Test"], check=True)
    (repo / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "seed"], check=True)

    info = subagent_worktree.create_subagent_worktree(str(repo), "dirty-case")
    assert info is not None
    changed = Path(info["path"]) / "new.txt"
    changed.write_text("keep me", encoding="utf-8")

    result = subagent_worktree.finalize_subagent_worktree(info)
    assert result["dirty"] is True
    assert result["pruned"] is False
    assert Path(info["path"]).is_dir()
    assert changed.read_text(encoding="utf-8") == "keep me"
