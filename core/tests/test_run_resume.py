"""Restart recovery: interrupted runs continue from where they stopped (FIX #4).

The contract under test:

* a run the previous shutdown interrupted is marked failed-with-recoverable
  (unchanged) *and* queued for resume;
* only a run that was actually ``running`` is resumed — a run waiting on the
  user must never be resumed, because that would answer the user's question
  for them;
* a resume is bounded by ``MAX_RESUME_ATTEMPTS`` so a crash loop cannot
  restart the same work forever;
* the resume reuses ``_execute_run`` with ``continuation=True`` and a fresh
  continuation instruction, so the resumed turn neither duplicates the
  original user bubble nor replays side effects.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from atlas.api import run_drive
from atlas.api.runtime import MAX_RESUME_ATTEMPTS, RunState, RuntimeManager


class _FakeManager(RuntimeManager):
    """Real bookkeeping, no SQLite: the resume logic is what's under test."""

    def __init__(self) -> None:
        super().__init__()
        self.persisted: list[str] = []
        self.sent: list[dict[str, Any]] = []

    async def persist_run(self, run: RunState, recovery_event: dict[str, Any] | None = None) -> None:
        self.persisted.append(run.run_id)

    async def send_run(self, run: RunState, data: dict[str, Any], fallback_conn_id: str) -> None:
        self.sent.append(data)


def _run(run_id: str = "run-1", *, conversation: str = "conv-1") -> RunState:
    return RunState(run_id, conversation, "model-1")


def _governing(run: RunState, *, attempts: int = 0) -> RunState:
    """A run in the state a restart leaves behind: interrupted mid-work."""
    run.status = "failed"
    run.user_input = "做成一个页面"
    run.resume_context = {"workspace": "D:\\work", "mode": "act"}
    run.resume_attempts = attempts
    return run


# ---------------------------------------------------------------------------
# What may be resumed
# ---------------------------------------------------------------------------

def test_a_running_run_with_a_request_is_resumable() -> None:
    assert RuntimeManager._resumable(_governing(_run()), "running") is True


def test_a_run_waiting_on_the_user_is_never_resumed() -> None:
    """Resuming an approval/plan/input wait would answer the question silently."""
    for waiting in ("waiting", "paused"):
        run = _governing(_run())
        assert RuntimeManager._resumable(run, waiting) is False, waiting


def test_a_run_without_its_original_request_is_not_resumed() -> None:
    run = _governing(_run())
    run.user_input = "   "
    assert RuntimeManager._resumable(run, "running") is False


def test_ephemeral_and_read_only_runs_are_not_resumed() -> None:
    ephemeral = _governing(_run())
    ephemeral.ephemeral = True
    assert RuntimeManager._resumable(ephemeral, "running") is False

    read_only = _governing(_run())
    read_only.read_only = True
    assert RuntimeManager._resumable(read_only, "running") is False


def test_resume_attempts_are_bounded_so_a_crash_loop_terminates() -> None:
    run = _governing(_run(), attempts=MAX_RESUME_ATTEMPTS - 1)
    assert RuntimeManager._resumable(run, "running") is True
    run.resume_attempts = MAX_RESUME_ATTEMPTS
    assert RuntimeManager._resumable(run, "running") is False


# ---------------------------------------------------------------------------
# Resume bookkeeping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_hands_each_pending_run_over_once_and_counts_the_attempt() -> None:
    manager = _FakeManager()
    run = _governing(_run())
    manager.runs[run.run_id] = run
    manager.pending_resumes = [run.run_id]
    taken: list[str] = []

    async def resume(candidate: RunState) -> bool:
        taken.append(candidate.run_id)
        return True

    resumed = await manager.resume_interrupted_runs(resume)

    assert resumed == [run.run_id]
    assert taken == [run.run_id]
    # The attempt is recorded before hand-off: a crash during the resume must
    # still consume an attempt, or the run would restart forever.
    assert run.resume_attempts == 1
    assert manager.persisted == [run.run_id]
    assert manager.pending_resumes == []


@pytest.mark.asyncio
async def test_a_run_superseded_in_its_conversation_is_not_resumed() -> None:
    manager = _FakeManager()
    stale = _governing(_run("stale"))
    stale.updated_at = "2026-01-01T00:00:00+00:00"
    newer = _run("newer")
    newer.updated_at = "2026-01-01T00:05:00+00:00"
    manager.runs = {stale.run_id: stale, newer.run_id: newer}
    manager.pending_resumes = [stale.run_id]

    async def resume(candidate: RunState) -> bool:  # pragma: no cover - must not run
        raise AssertionError("a superseded run must not be resumed")

    assert await manager.resume_interrupted_runs(resume) == []
    assert stale.resume_attempts == 0


@pytest.mark.asyncio
async def test_a_failing_resume_does_not_stop_the_others() -> None:
    manager = _FakeManager()
    first = _governing(_run("first", conversation="c1"))
    second = _governing(_run("second", conversation="c2"))
    manager.runs = {first.run_id: first, second.run_id: second}
    manager.pending_resumes = [first.run_id, second.run_id]
    seen: list[str] = []

    async def resume(candidate: RunState) -> bool:
        seen.append(candidate.run_id)
        if candidate.run_id == first.run_id:
            raise RuntimeError("boom")
        return True

    assert await manager.resume_interrupted_runs(resume) == [second.run_id]
    assert seen == [first.run_id, second.run_id]


# ---------------------------------------------------------------------------
# What the resume actually starts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_restarts_the_run_with_a_continuation_not_the_original_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _FakeManager()
    run = _governing(_run())
    manager.runs[run.run_id] = run
    started: list[dict[str, Any]] = []

    async def fake_execute(conn_id: str, target: RunState, content: str, model_id: str | None,
                           **kwargs: Any) -> None:
        started.append({"conn_id": conn_id, "content": content, "model_id": model_id, **kwargs})

    monkeypatch.setattr(run_drive, "_execute_run", fake_execute)
    monkeypatch.setattr(run_drive, "collect_workspace_rules", None, raising=False)

    rules_module = __import__("atlas.api.workspace_router", fromlist=["collect_workspace_rules"])

    async def fake_rules(root: str) -> dict[str, Any]:
        return {"root": root, "files": []}

    monkeypatch.setattr(rules_module, "collect_workspace_rules", fake_rules)
    monkeypatch.setattr(run_drive._server(), "_workspace_trust", lambda: {}, raising=False)

    assert await run_drive.resume_run_after_restart(run, manager) is True
    await asyncio.sleep(0)
    await asyncio.gather(*(t for t in [run.task] if t is not None), return_exceptions=True)

    assert len(started) == 1
    turn = started[0]
    # continuation=True is what suppresses run.started, hence no duplicate bubble.
    assert turn["continuation"] is True
    # The original request is already in the session history; re-sending it as
    # the turn message would persist it twice.
    assert turn["content"] == run_drive._RESUME_INSTRUCTION
    assert turn["content"] != run.user_input


@pytest.mark.asyncio
async def test_resume_announces_itself_on_the_recovery_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _FakeManager()
    run = _governing(_run())
    manager.runs[run.run_id] = run

    async def fake_execute(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(run_drive, "_execute_run", fake_execute)

    rules_module = __import__("atlas.api.workspace_router", fromlist=["collect_workspace_rules"])

    async def fake_rules(root: str) -> dict[str, Any]:
        return {"root": root, "files": []}

    monkeypatch.setattr(rules_module, "collect_workspace_rules", fake_rules)
    monkeypatch.setattr(run_drive._server(), "_workspace_trust", lambda: {}, raising=False)

    assert await run_drive.resume_run_after_restart(run, manager) is True
    await asyncio.sleep(0)
    if run.task is not None:
        await asyncio.gather(run.task, return_exceptions=True)

    notices = [event for event in manager.sent if event.get("event") == "run.recovery.notice"]
    assert len(notices) == 1
    assert notices[0]["data"]["reason"] == "service_restart"


@pytest.mark.asyncio
async def test_resume_declares_running_before_it_explains_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recovery notice is only a caption — it does not change the run status.

    The shutdown persisted this run as failed, so the resume has to say
    "running" itself; otherwise the client keeps showing a failed run that is
    visibly doing work again.
    """
    manager = _FakeManager()
    run = _governing(_run())
    manager.runs[run.run_id] = run

    async def fake_execute(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(run_drive, "_execute_run", fake_execute)

    rules_module = __import__("atlas.api.workspace_router", fromlist=["collect_workspace_rules"])

    async def fake_rules(root: str) -> dict[str, Any]:
        return {"root": root, "files": []}

    monkeypatch.setattr(rules_module, "collect_workspace_rules", fake_rules)
    monkeypatch.setattr(run_drive._server(), "_workspace_trust", lambda: {}, raising=False)

    assert await run_drive.resume_run_after_restart(run, manager) is True
    await asyncio.sleep(0)
    if run.task is not None:
        await asyncio.gather(run.task, return_exceptions=True)

    emitted = [event.get("event") for event in manager.sent]
    assert "run.status" in emitted
    statuses = [event for event in manager.sent if event.get("event") == "run.status"]
    assert statuses[-1]["data"]["status"] == "running"
    # Order matters: the pill must stop saying "failed" before the caption
    # explains the interruption.
    assert emitted.index("run.status") < emitted.index("run.recovery.notice")


@pytest.mark.asyncio
async def test_an_untrusted_workspace_is_handed_back_to_the_user_not_resumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resuming past an unanswered trust prompt would answer it for the user."""
    manager = _FakeManager()
    run = _governing(_run())
    manager.runs[run.run_id] = run

    started: list[Any] = []

    async def fake_execute(*args: Any, **kwargs: Any) -> None:  # pragma: no cover
        started.append(args)

    monkeypatch.setattr(run_drive, "_execute_run", fake_execute)

    rules_module = __import__("atlas.api.workspace_router", fromlist=["collect_workspace_rules"])

    async def fake_rules(root: str) -> dict[str, Any]:
        return {"root": root, "files": [{"path": f"{root}\\AGENTS.md", "bytes": 10, "content": "x"}]}

    monkeypatch.setattr(rules_module, "collect_workspace_rules", fake_rules)
    monkeypatch.setattr(run_drive._server(), "_workspace_trust", lambda: {}, raising=False)

    assert await run_drive.resume_run_after_restart(run, manager) is False
    assert started == []
    assert run.task is None if hasattr(run, "task") else True
    notices = [event for event in manager.sent if event.get("event") == "run.recovery.notice"]
    assert len(notices) == 1
    assert notices[0]["data"]["reason"] == "rules_need_trust"


@pytest.mark.asyncio
async def test_a_non_atlas_executor_is_not_resumed(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _FakeManager()
    run = _governing(_run())
    run.executor = "codex"
    manager.runs[run.run_id] = run

    async def fake_execute(*args: Any, **kwargs: Any) -> None:  # pragma: no cover
        raise AssertionError("a foreign executor must not run the Atlas loop")

    monkeypatch.setattr(run_drive, "_execute_run", fake_execute)

    assert await run_drive.resume_run_after_restart(run, manager) is False
