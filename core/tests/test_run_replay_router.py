"""HTTP contract for run replay + resumable checkpoints (``run_replay_router``).

Two stores sit behind this router and both are exercised for real here:

* the replay reads go through :mod:`atlas.run_replay` over a synthetic JSONL
  archive written under ``tmp_path`` (``ATLAS_RUNS_DIR``), and
* the checkpoint reads/writes go through :mod:`atlas.run_checkpoints` against the
  per-test ``ATLAS_DATA_DIR`` the suite already isolates, so the operator's
  ``data/run_checkpoints.db`` is never touched.

The resume endpoint is the one place where a *decision* is made, and the live
end-to-end probe found a real defect there: POSTing resume for an already
completed run happily re-entered the executor and spent a whole extra model
turn. The tests below pin the corrected contract -- ``completed``/``cancelled``
are refused, ``failed`` (what a shutdown leaves behind) still resumes -- and
assert that a refused request never reaches ``resume_run_after_restart`` at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.app_services import AppServices
from atlas.api.runtime import MAX_RESUME_ATTEMPTS, RunState, RuntimeManager
from atlas.api.run_replay_router import router as replay_router
from atlas.run_checkpoints import write_checkpoint

RUN_ID = "run-aaaa-bbbb"
CONVERSATION = "conv-1234"
TS0 = "2026-11-07T21:18:29.752827+00:00"


# --------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the archive reader at a per-test directory, never the real one."""
    root = tmp_path / "runs"
    root.mkdir()
    monkeypatch.setenv("ATLAS_RUNS_DIR", str(root))
    return root


def _write_archive(root: Path, run_id: str, events: list[dict[str, Any]]) -> None:
    day = root / "2026-11-07"
    day.mkdir(parents=True, exist_ok=True)
    with (day / f"{run_id}.jsonl").open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")


def _recorded_run(run_id: str = RUN_ID) -> list[dict[str, Any]]:
    """A minimal but real run: two phases, one model call, one tool call.

    Field names and event names follow what ``atlas/logs.py::append_run_event``
    actually writes (``tool_start``/``tool_end`` carry ``name``, not
    ``tool_name``; the model usage row carries ``output_tokens``), which is what
    the reader keys on.
    """
    return [
        {"timestamp": TS0, "event": "run_start", "run_id": run_id, "session_id": "s-1",
         "model": "deepseek-v4.1-flash", "workspace": "D:/w", "kernel": "atlas"},
        {"timestamp": TS0, "event": "run_phase", "run_id": run_id,
         "phase": "execution", "previous": "preparing"},
        {"timestamp": TS0, "event": "model_request", "run_id": run_id, "purpose": "conversation",
         "model": "deepseek-v4.1-flash", "provider": "gw", "duration_ms": 1200,
         "input_tokens": 100, "output_tokens": 20, "cached_tokens": 0, "attempt": 1},
        {"timestamp": TS0, "event": "tool_start", "run_id": run_id,
         "tool_call_id": "call-1", "name": "grep", "arguments": {"length": 12}},
        {"timestamp": TS0, "event": "tool_end", "run_id": run_id,
         "tool_call_id": "call-1", "name": "grep", "state": "completed",
         "duration_ms": 40, "output_ref": "D:/t/tool-output/a.log", "output": {"length": 40}},
        {"timestamp": TS0, "event": "tool_result", "run_id": run_id,
         "tool_call_id": "call-1", "name": "grep", "state": "completed", "is_error": False,
         "output_ref": "D:/t/tool-output/a.log", "output": {"length": 40}},
        {"timestamp": TS0, "event": "run_phase", "run_id": run_id,
         "phase": "done", "previous": "execution"},
        {"timestamp": TS0, "event": "run_end", "run_id": run_id, "status": "completed",
         "duration_ms": 5000, "total_input_tokens": 100, "total_output_tokens": 20},
    ]


class _NeverFinishes:
    """Stand-in for the task a live run holds; only ``done()`` is consulted."""

    def done(self) -> bool:
        return False


class _FakeManager(RuntimeManager):
    """Real ``runs`` registry, no SQLite, no execution."""

    def __init__(self, *runs: RunState) -> None:
        super().__init__()
        for run in runs:
            self.runs[run.run_id] = run

    async def persist_run(self, run: RunState, recovery_event: dict[str, Any] | None = None) -> None:
        return None

    async def send_run(self, run: RunState, data: dict[str, Any], fallback_conn_id: str) -> None:
        return None


def _run(*, status: str = "failed", executor: str = "atlas",
         conversation: str = CONVERSATION, attempts: int = 0) -> RunState:
    run = RunState(RUN_ID, conversation, "deepseek-v4.1-flash")
    run.status = status
    run.executor = executor
    run.user_input = "把配置里的端口改一下"
    run.resume_context = {"workspace": "D:\\work", "mode": "act"}
    run.resume_attempts = attempts
    return run


@pytest.fixture()
def resume_calls(monkeypatch: pytest.MonkeyPatch) -> list[RunState]:
    """Replace the real continuation with a recorder, so nothing executes."""
    from atlas.api import run_drive

    taken: list[RunState] = []

    async def _fake(run: RunState, manager: Any = None) -> bool:
        taken.append(run)
        run.status = "running"
        return True

    monkeypatch.setattr(run_drive, "resume_run_after_restart", _fake)
    return taken


def _client(manager: Any) -> TestClient:
    app = FastAPI()
    app.state.services = AppServices(runtime_mgr=manager)
    app.include_router(replay_router)
    return TestClient(app)


# ---------------------------------------------------------------------- replay


def test_replay_lists_archived_runs(runs_dir: Path) -> None:
    _write_archive(runs_dir, RUN_ID, _recorded_run())
    body = _client(_FakeManager()).get("/api/run-replay").json()
    assert [item["run_id"] for item in body["items"]] == [RUN_ID]


def test_replay_reads_the_timeline_without_executing_anything(runs_dir: Path) -> None:
    _write_archive(runs_dir, RUN_ID, _recorded_run())
    res = _client(_FakeManager()).get(f"/api/run-replay/{RUN_ID}")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "completed"
    assert body["summary"]["tool_calls"] == 1
    assert body["summary"]["phases"] == ["execution", "done"]
    kinds = [item["kind"] for item in body["timeline"]]
    assert "tool_call" in kinds and "run_end" in kinds
    assert kinds[-1] == "run_end"


def test_replay_never_exposes_tool_argument_or_output_text(runs_dir: Path) -> None:
    """The archive stores lengths only; the replay surface must not invent more."""
    _write_archive(runs_dir, RUN_ID, _recorded_run())
    body = _client(_FakeManager()).get(f"/api/run-replay/{RUN_ID}").json()
    calls = [item for item in body["timeline"] if item["kind"] == "tool_call"]
    assert len(calls) == 1
    detail = calls[0]["detail"]
    # Arguments/output survive only as their *length* plus a path reference to
    # the stored artifact; the recorded bytes never travel through this surface.
    assert detail["arguments_length"] == 12
    assert "arguments" not in detail
    assert calls[0]["tool_name"] == "grep"
    result = next(item for item in body["timeline"] if item["kind"] == "tool_result")
    assert result["detail"]["output_length"] == 40
    assert result["detail"]["output_ref"].endswith("a.log")
    assert body["summary"]["tool_calls"] == 1


def test_replay_answers_404_for_an_unknown_run(runs_dir: Path) -> None:
    res = _client(_FakeManager()).get("/api/run-replay/no-such-run")
    assert res.status_code == 404


def test_replay_rejects_a_path_like_run_id(runs_dir: Path) -> None:
    assert _client(_FakeManager()).get("/api/run-replay/..%2F..%2Fetc").status_code in (400, 404)


# ----------------------------------------------------------------- checkpoints


def test_checkpoints_summarize_what_is_safe_to_replay() -> None:
    run_id = "cp-run-1"
    write_checkpoint(run_id, kind="phase", phase="execution")
    write_checkpoint(run_id, kind="tool", tool_call_id="c1", tool_name="grep",
                     state="succeeded", replay_safe=True, phase="execution")
    write_checkpoint(run_id, kind="tool", tool_call_id="c2", tool_name="write",
                     state="not_started", replay_safe=False, phase="execution")

    body = _client(_FakeManager()).get(f"/api/run-checkpoints/{run_id}").json()
    assert body["count"] == 3
    digest = body["digest"]
    assert digest["phase"] == "execution"
    assert digest["replay_safe_tool_count"] == 1
    assert digest["unsafe_tool_count"] == 1
    assert digest["unsafe_tools"] == ["write"]
    assert [row["tool_name"] for row in body["checkpoints"] if row["kind"] == "tool"] == [
        "grep", "write"
    ]


def test_checkpoint_overview_counts_runs() -> None:
    write_checkpoint("ov-run-1", kind="phase", phase="planning")
    body = _client(_FakeManager()).get("/api/run-checkpoints").json()
    assert "ov-run-1" in [item["run_id"] for item in body["items"]]


# --------------------------------------------------------------------- resume


def test_resume_refuses_a_completed_run_without_spending_a_turn(resume_calls: list[RunState]) -> None:
    """The live-probe regression: a finished run must not be re-entered."""
    run = _run(status="completed")
    # A finished run is terminal even though its task object is done.
    body = _client(_FakeManager(run)).post(f"/api/run-checkpoints/{RUN_ID}/resume").json()
    assert body["resumed"] is False
    assert body["skipped"] == "finished"
    assert body["status_before"] == "completed"
    assert resume_calls == []  # nothing was executed


def test_resume_refuses_a_cancelled_run(resume_calls: list[RunState]) -> None:
    body = _client(_FakeManager(_run(status="cancelled"))).post(
        f"/api/run-checkpoints/{RUN_ID}/resume"
    ).json()
    assert body["skipped"] == "finished"
    assert resume_calls == []


def test_resume_takes_over_the_failed_run_a_shutdown_leaves_behind(
    resume_calls: list[RunState],
) -> None:
    run = _run(status="failed")
    body = _client(_FakeManager(run)).post(f"/api/run-checkpoints/{RUN_ID}/resume").json()
    assert body["resumed"] is True
    assert body["skipped"] is None
    assert body["status_before"] == "failed"
    assert resume_calls == [run]


def test_resume_404s_when_the_runtime_state_is_gone(resume_calls: list[RunState]) -> None:
    res = _client(_FakeManager()).post(f"/api/run-checkpoints/{RUN_ID}/resume")
    assert res.status_code == 404


def test_resume_refuses_a_run_without_a_conversation(resume_calls: list[RunState]) -> None:
    body = _client(_FakeManager(_run(conversation=""))).post(
        f"/api/run-checkpoints/{RUN_ID}/resume"
    ).json()
    assert body["skipped"] == "no_conversation"
    assert resume_calls == []


def test_resume_refuses_a_non_atlas_executor(resume_calls: list[RunState]) -> None:
    body = _client(_FakeManager(_run(executor="hermes"))).post(
        f"/api/run-checkpoints/{RUN_ID}/resume"
    ).json()
    assert body["skipped"] == "not_atlas_executor"
    assert resume_calls == []


def test_resume_reports_the_unsafe_tools_in_its_answer(resume_calls: list[RunState]) -> None:
    """A resumed run must say which side effects may already have happened."""
    write_checkpoint(RUN_ID, kind="tool", tool_call_id="c1", tool_name="write",
                     state="not_started", replay_safe=False)
    body = _client(_FakeManager(_run())).post(f"/api/run-checkpoints/{RUN_ID}/resume").json()
    assert body["resumed"] is True
    assert body["digest"]["unsafe_tools"] == ["write"]
    assert "write" in body["notice"]


def test_resume_refuses_a_run_that_is_still_executing(
    resume_calls: list[RunState],
) -> None:
    """A live turn must not be taken over -- that would run two loops at once."""
    run = _run(status="running")
    run.task = _NeverFinishes()  # type: ignore[assignment]
    body = _client(_FakeManager(run)).post(f"/api/run-checkpoints/{RUN_ID}/resume").json()
    assert body["skipped"] == "already_active"
    assert resume_calls == []


def test_resume_reports_unknown_when_the_continuation_declines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``rules_need_trust`` is only visible from inside the continuation.

    That refusal sets no field on the run, so the router cannot name it; it must
    say "unknown" and keep the real reason in the run's recovery notice rather
    than inventing a code.
    """
    from atlas.api import run_drive

    async def _declines(run: RunState, manager: Any = None) -> bool:
        return False

    monkeypatch.setattr(run_drive, "resume_run_after_restart", _declines)
    body = _client(_FakeManager(_run())).post(f"/api/run-checkpoints/{RUN_ID}/resume").json()
    assert body["resumed"] is False
    assert body["skipped"] == "unknown"
    assert body["status_before"] == "failed"


def test_resume_rejects_a_path_like_run_id() -> None:
    res = _client(_FakeManager()).post("/api/run-checkpoints/..%2Fetc/resume")
    assert res.status_code in (400, 404)


def test_an_ordinary_resume_carries_no_warnings(resume_calls: list[RunState]) -> None:
    """Nothing to disclose when the explicit and automatic paths would agree."""
    body = _client(_FakeManager(_run())).post(f"/api/run-checkpoints/{RUN_ID}/resume").json()
    assert body["warnings"] == []


def test_resume_discloses_that_a_pending_question_was_dropped(
    resume_calls: list[RunState],
) -> None:
    """A run interrupted mid-approval comes back without its answer.

    The boot recovery refuses exactly this run (``_resumable`` requires
    ``interrupted_from == "running"``); an explicit resume goes ahead, so it has
    to say so rather than quietly treating silence as consent.
    """
    run = _run()
    run.waiting_for = "approval"
    body = _client(_FakeManager(run)).post(f"/api/run-checkpoints/{RUN_ID}/resume").json()
    assert body["resumed"] is True
    assert len(body["warnings"]) == 1
    assert "approval" in body["warnings"][0]


def test_resume_discloses_bypassing_the_crash_loop_budget(
    resume_calls: list[RunState],
) -> None:
    run = _run(attempts=MAX_RESUME_ATTEMPTS)
    body = _client(_FakeManager(run)).post(f"/api/run-checkpoints/{RUN_ID}/resume").json()
    assert body["resumed"] is True
    assert any(str(MAX_RESUME_ATTEMPTS) in warning for warning in body["warnings"])


def test_a_refused_resume_still_carries_its_warnings(resume_calls: list[RunState]) -> None:
    run = _run(status="completed")
    run.waiting_for = "plan"
    body = _client(_FakeManager(run)).post(f"/api/run-checkpoints/{RUN_ID}/resume").json()
    assert body["skipped"] == "finished"
    assert body["warnings"]  # the dropped-question fact is still true
    assert resume_calls == []
