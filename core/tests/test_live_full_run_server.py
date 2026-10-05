"""H10.2 §12.2 full live scenarios needing one persistent backend (08/09/10/12).

- 08 计划模式出计划，再按计划执行: one raw ``/ws/chat`` connection sends
  ``run.start`` with ``permission_mode=plan`` and the scenario task verbatim;
  the server proposes the plan (``run.plan.proposed``) and parks the run in
  ``waiting``. The harness then plays the desktop over the same socket —
  ``run.plan.approve`` → the engine executes the same run → greet.py works.
  (The headless CLI can no longer carry this scenario: it now denies the plan
  by design — run.cancel + exit 3 — see the test_cli_headless plan regression.)
- 09 做到一半回退到某一步再继续: two ``atlas run --server`` turns, rewind the
  second turn through the production route (``POST /api/conversations/{id}/rewind``,
  files restored from the run checkpoints), retry with the corrected instruction.
- 10 运行中第 N 秒插话改需求: an ``atlas run --server`` turn grinding through a
  long command; a SECOND ``/ws/chat`` connection sends ``run.steer`` with
  ``send_now`` mid-run and the old requirement must be replaced.
- 12 Webhook 渠道入站任务（ask_writes）→ 审批 → 执行 → 渠道回执: signed inbound
  webhook event, the H7 approval request lands on the channel, the 「允许」
  channel reply unblocks the real model write, the receipt is POSTed back to a
  local receiver. The webhook channel (enabled + secret) is seeded into the
  manager's own ``channel-configs.json`` before the backend boots, because
  adapters are only created at ``ChannelManager.start()`` for already-enabled
  channels and the /credential keyring value is never read back by
  ``handle_webhook`` (production gaps, see the H1R2 lane report).

The backend is the regular Atlas app (same one the desktop / ``atlas run``
in-process mode serve) started once per scenario on an ephemeral loopback port,
with the full-run live root as its data dir. Requires ``ATLAS_LIVE=1`` + ``-m live``.
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from tests.test_live_model_smoke import LiveSession, _redact

CORE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "live"
HEALTH_TIMEOUT = 120.0


def _fixture(scenario: str) -> Path:
    path = FIXTURES / scenario
    assert path.is_dir(), f"missing scenario fixture dir {path}"
    return path


def _prompt(scenario: str, part: str = "task.md") -> str:
    return (_fixture(scenario) / part).read_text(encoding="utf-8").strip()


def _check(live: LiveSession, scenario: str, name: str, workspace: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(_fixture(scenario) / "check.py"), str(workspace)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, cwd=str(_fixture(scenario)),
    )
    run_dir = live.evidence / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "check.log").write_text(
        _redact(f"exit={proc.returncode}\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"),
        encoding="utf-8",
    )
    assert proc.returncode == 0 and "CHECK-OK" in proc.stdout, (
        f"{scenario} check failed: {proc.stdout} {proc.stderr}"
    )


# ---------------------------------------------------------------------------
# persistent backend fixture
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Backend:
    """The regular Atlas app served for one scenario on 127.0.0.1."""

    def __init__(self, live: LiveSession) -> None:
        self.live = live
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        self.log_path = live.evidence / "backend.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        # Optional channel-gateway config seeded before uvicorn boots (scenario
        # 12). ``ChannelManager`` loads this file once at construction and only
        # starts adapters for channels already enabled in it, so runtime-only
        # ``PUT /accounts`` enabling cannot produce a working outbound channel.
        self.seed_channel_configs: dict[str, dict[str, Any]] | None = None

    def start(self) -> None:
        env = self.live.child_env()
        env.pop("ATLAS_LIVE_SMOKE_ROOT", None)  # harness knob, not for the backend
        env["PYTHONUNBUFFERED"] = "1"
        if self.seed_channel_configs:
            # Same path expression server.py uses (cfg.db_path.parent /
            # "channel-configs.json") under the same ATLAS_DATA_DIR env.
            from atlas.config import get_config

            seed_path = get_config().db_path.parent / "channel-configs.json"
            seed_path.parent.mkdir(parents=True, exist_ok=True)
            seed_path.write_text(
                json.dumps(self.seed_channel_configs, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        self._log = open(self.log_path, "w", encoding="utf-8", errors="replace")  # noqa: SIM115
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "atlas.server:app",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=str(CORE_ROOT), env=env, stdout=self._log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        import httpx

        deadline = time.monotonic() + HEALTH_TIMEOUT
        last = ""
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"backend exited early rc={self.proc.returncode}")
            try:
                response = httpx.get(f"{self.base_url}/api/health", timeout=2.0)
                if response.status_code == 200:
                    health = response.json()
                    if health.get("status") == "ok":
                        return
                    last = f"health={health.get('status')} components={health.get('components')}"
                else:
                    last = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            time.sleep(0.3)
        raise AssertionError(f"backend not healthy after {HEALTH_TIMEOUT}s: {last}")

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        self.proc = None
        if hasattr(self, "_log"):
            self._log.close()


@pytest.fixture
def server_live() -> tuple[LiveSession, Backend]:
    session = LiveSession()
    code, events, _stderr = session.run_cli("server-00-doctor", "doctor", "--json",
                                            cwd=session.root)
    report = next((e for e in events if e.get("type") == "doctor"), None)
    assert report is not None and code == 0 and report["checks"]["models"].get("ok"), (
        f"doctor gate failed: {report} (exit={code})"
    )
    backend = Backend(session)
    try:
        # Not started here: tests that need pre-boot state (scenario 12 seeds
        # the channel-gateway config file) set it up, then call backend.start().
        yield session, backend
    finally:
        session.close()
        backend.stop()


def _atlas_run_server(live: LiveSession, backend: Backend, name: str, prompt: str,
                      workspace: Path, *extra_args: str, timeout: str = "600") -> dict:
    code, events, stderr = live.run_cli(
        name, "run",
        "-p", prompt,
        "--workspace", str(workspace),
        "--model", live.model,
        "--output-format", "stream-json",
        "--timeout", timeout,
        "--server", backend.base_url,
        *extra_args,
        cwd=live.root,
    )
    summaries = [e for e in events if e.get("type") == "summary"]
    assert summaries, f"{name}: no summary (exit={code}) stderr={_redact(stderr)[-1200:]}"
    summary = summaries[-1]
    assert code == 0 and summary.get("result") == "completed", (
        f"{name}: exit={code} summary={summary} stderr={_redact(stderr)[-1200:]}"
    )
    usage = summary.get("usage") or {}
    assert usage.get("input_tokens") and usage.get("output_tokens"), (
        f"{name}: no real usage: {usage}"
    )
    return summary


def _messages(live: LiveSession, backend: Backend, conversation_id: str) -> list[dict]:
    import httpx

    response = httpx.get(
        f"{backend.base_url}/api/conversations/{conversation_id}/messages?limit=200",
        headers={"x-atlas-api-token": "h10-live-smoke"}, timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("messages") if isinstance(payload, dict) else payload


def _observe_run_line(line: str, state: dict[str, str], tool_started: threading.Event,
                      run_finished: threading.Event | None = None) -> None:
    """Observe every event, including tools arriving after run.started."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return
    if not isinstance(event, dict):
        return
    if not state.get("run_id") and event.get("run_id"):
        state["run_id"] = str(event["run_id"])
    kind = str(event.get("event") or event.get("type") or "")
    data = event.get("data") or {}
    if kind in {"tool_start", "tool.started", "run.tool.started"} and isinstance(data, dict):
        tool_started.set()
    if run_finished is not None and kind in {"run.completed", "run.failed", "run.cancelled"}:
        run_finished.set()


def _pump_stderr(process: subprocess.Popen) -> tuple[list[str], threading.Thread]:
    """Drain stderr while the stdout observer owns its pipe."""
    lines: list[str] = []

    def drain() -> None:
        assert process.stderr is not None
        lines.extend(process.stderr)

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    return lines, thread


def _finish_observed_process(process: subprocess.Popen, stdout_thread: threading.Thread,
                             stderr_thread: threading.Thread,
                             timeout: float) -> tuple[int, bool]:
    """Wait for the CLI; returns (exit_code, cli_hang).

    ``cli_hang`` is True when the timeout expired and the harness had to kill
    the process — recorded in meta.json so the next evidence round can tell a
    CLI teardown hang apart from a real non-zero exit.
    """
    hung = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        hung = True
        process.kill()
        process.wait(timeout=30)
    stdout_thread.join(timeout=30)
    stderr_thread.join(timeout=30)
    assert not stdout_thread.is_alive() and not stderr_thread.is_alive(), "CLI pipes did not close"
    return int(process.returncode), hung


# ---------------------------------------------------------------------------
# 08 — plan mode proposes over raw WS, the harness approves, execution follows
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_08_plan_propose_approve_then_execute(server_live) -> None:
    """08 driven over the raw Runtime Event Protocol (no CLI process).

    The headless CLI now treats ``run.plan.proposed`` as a denial (run.cancel +
    exit 3, per the H1 exit-code contract; covered by the test_cli_headless
    plan regression), so the harness itself plays the desktop surface: one
    ``/ws/chat`` connection sends ``run.start`` (``permission_mode=plan`` +
    the scenario task verbatim), receives ``run.plan.proposed``, proves the
    planning phase executed nothing, sends ``run.plan.approve`` (the same
    server-side contract the desktop uses: run_id + plan event_id + edits),
    and reads the resumed execution through to ``run.completed``.
    """
    live, backend = server_live
    backend.start()
    scenario = "08-plan-execute"
    workspace = live.workspace("plan")
    prompt = _prompt(scenario)
    run_dir = live.evidence / scenario
    run_dir.mkdir(parents=True, exist_ok=True)
    headers = {"x-atlas-api-token": "h10-live-smoke"}

    # Conversation id through the same REST seam the CLI headless mode uses.
    import httpx

    response = httpx.post(f"{backend.base_url}/api/conversations",
                          json={"title": "08 plan-execute"}, headers=headers, timeout=30)
    assert response.status_code == 200, (
        f"conversation create failed: HTTP {response.status_code} {response.text[:300]}")
    conversation_id = str(response.json().get("id", ""))
    assert conversation_id, "conversation create returned no id"

    trace: dict[str, Any] = {"events": [], "notes": []}

    def _write_evidence(meta_extra: dict[str, Any]) -> None:
        # Evidence lands BEFORE the strong asserts: a failed drive or a failed
        # assertion must leave a readable stream + meta, never an empty dir.
        stream_text = "".join(
            json.dumps(event, ensure_ascii=False) + "\n" for event in trace["events"])
        (run_dir / "stream.jsonl").write_text(_redact(stream_text), encoding="utf-8")
        (run_dir / "stderr.log").write_text(
            _redact("\n".join(str(note) for note in trace["notes"])), encoding="utf-8")
        meta = {
            "name": scenario,
            # CLI-side plan semantics are covered by the Lane-G fake regression
            # (test_cli_headless plan tests); this live scenario is WS-driven.
            "driven_via": "raw ws (CLI headless now denies plan by design; "
                          "see test_cli_headless plan regression)",
            "model": live.model,
            "conversation_id": conversation_id,
            "workspace": str(workspace),
            **meta_extra,
        }
        (run_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _drive() -> dict[str, Any]:
        import websockets

        run_id = uuid.uuid4().hex
        trace["run_id"] = run_id
        outcome: dict[str, Any] = {"run_id": run_id}
        t_start = time.monotonic()
        async with websockets.connect(
            backend.base_url.replace("http", "ws", 1) + "/ws/chat",
            additional_headers=headers, max_size=8_000_000,
        ) as ws:
            await ws.send(json.dumps({
                "type": "run.start", "run_id": run_id, "content": prompt,
                "conversation_id": conversation_id, "workspace": str(workspace),
                "model": live.model, "permission_mode": "plan",
            }, ensure_ascii=False))
            trace["notes"].append(f"run.start sent: run_id={run_id} permission_mode=plan")

            # --- phase 1: planning — read until the plan is proposed ----------
            plan_deadline = t_start + 420.0
            while True:
                remaining = plan_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "run.plan.proposed never arrived in 420s; "
                        f"last events: {trace['events'][-3:]}")
                raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
                if not isinstance(raw, dict):
                    continue
                trace["events"].append(raw)
                kind = str(raw.get("event") or "")
                if raw.get("type") == "error":
                    raise AssertionError(f"server rejected the run: {raw}")
                if raw.get("run_id") != run_id:
                    trace["notes"].append(f"ignored envelope for foreign run: {kind}")
                    continue
                if kind == "run.failed":
                    raise AssertionError(f"run failed during planning: {raw.get('data')}")
                if kind == "run.plan.proposed":
                    outcome["proposed"] = raw
                    outcome["proposed_at_s"] = round(time.monotonic() - t_start, 3)
                    break

            proposed = outcome["proposed"]
            proposed_data = proposed.get("data") or {}
            # Planning phase must not have executed the task: the workspace
            # artifact cannot exist before the approval. (Inspecting the
            # workspace with read-only tools during planning is allowed and
            # observed in real runs; writing greet.py is not.)
            assert not (workspace / "greet.py").exists(), (
                "plan phase executed instead of planning: greet.py already exists")
            plan = proposed_data.get("plan") or {}
            assert str(plan.get("goal") or "").strip(), (
                f"proposed plan has no goal: {proposed_data}")
            subtasks = plan.get("subtasks")
            assert isinstance(subtasks, list) and subtasks and all(
                str(item.get("title") or "").strip() for item in subtasks), (
                f"proposed plan has no actionable subtasks: {proposed_data}")

            # --- phase 2: approve on this socket, read execution to the end ---
            outcome["approved_at_s"] = round(time.monotonic() - t_start, 3)
            outcome["plan_event_id"] = str(proposed_data.get("event_id") or "")
            trace["notes"].append(
                f"run.plan.approve sent: event_id={outcome['plan_event_id']}")
            await ws.send(json.dumps({
                "type": "run.plan.approve", "run_id": run_id,
                "event_id": outcome["plan_event_id"], "edits": "",
            }, ensure_ascii=False))

            execute_deadline = time.monotonic() + 600.0
            while True:
                remaining = execute_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "approved plan run never reached a terminal event in 600s; "
                        f"last events: {trace['events'][-3:]}")
                raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
                if not isinstance(raw, dict):
                    continue
                trace["events"].append(raw)
                kind = str(raw.get("event") or "")
                if raw.get("run_id") != run_id:
                    trace["notes"].append(f"ignored envelope for foreign run: {kind}")
                    continue
                if kind in {"run.completed", "run.failed", "run.cancelled"}:
                    outcome["terminal"] = raw
                    outcome["terminal_at_s"] = round(time.monotonic() - t_start, 3)
                    trace["notes"].append(f"terminal event: {kind}")
                    break
        return outcome

    t0 = time.monotonic()
    try:
        outcome = asyncio.run(_drive())
    except BaseException as exc:  # evidence first, then re-raise
        _write_evidence({
            "run_id": trace.get("run_id"),
            "harness_error": f"{type(exc).__name__}: {exc}"[:1200],
            "result": "incomplete",
            "wall_seconds": round(time.monotonic() - t0, 3),
        })
        raise
    run_id = str(outcome["run_id"])
    proposed = outcome["proposed"]
    terminal = outcome["terminal"]
    events = trace["events"]
    run_events = [e for e in events if e.get("run_id") == run_id]
    kinds = [str(e.get("event") or "") for e in run_events]

    # Snapshot the measured outcome before asserting on it.
    proposed_data = proposed.get("data") or {}
    plan = proposed_data.get("plan") or {}
    completed_data = (terminal.get("data") or {}) if terminal else {}
    usage = completed_data.get("usage") or {}
    _write_evidence({
        "run_id": run_id,
        "plan_event_id": outcome["plan_event_id"],
        "plan_goal": str(plan.get("goal") or "")[:300],
        "plan_subtasks": len(plan.get("subtasks") or []),
        "proposed_at_s": outcome["proposed_at_s"],
        "approved_at_s": outcome["approved_at_s"],
        "completed_at_s": outcome.get("terminal_at_s"),
        "terminal_event": str(terminal.get("event") or "") if terminal else "",
        "result": "unverified",
        "usage": {"input_tokens": usage.get("input_tokens"),
                  "output_tokens": usage.get("output_tokens")},
        "changes": completed_data.get("changes"),
        "wall_seconds": round(time.monotonic() - t0, 3),
    })

    # --- the old assertions, preserved one-for-one on the WS protocol ---------
    # (old) plan was proposed within 420s:
    assert proposed.get("event") == "run.plan.proposed"
    # (old) exit 0 + "run.completed" in stream → the approved run completed:
    assert terminal is not None and terminal.get("event") == "run.completed", (
        f"approved plan run did not complete: terminal={terminal} "
        f"kinds_tail={kinds[-8:]}")
    assert completed_data.get("result") == "completed", (
        f"run.completed did not report success: {completed_data}")
    # Execution phase really executed the plan (tools ran after the approval):
    proposed_seq = int(proposed.get("sequence") or 0)
    executed_tools = [e for e in run_events if e.get("event") == "tool.started"
                      and int(e.get("sequence") or 0) > proposed_seq]
    assert executed_tools, (
        f"no tool ran after the approval; the plan was never executed "
        f"({len(run_events)} events, tail={kinds[-10:]})")
    # (old) the execution-phase artifact exists and check.py passes:
    assert (workspace / "greet.py").is_file(), (
        f"approved plan run did not produce greet.py: {kinds[-8:]}")

    # --- WS-native strengthening (real-model evidence, planning semantics) ----
    started = next((e for e in run_events if e.get("event") == "run.started"), None)
    assert started is not None and (started.get("data") or {}).get("phase") == "planning", (
        "plan-mode run.start did not open in the planning phase")
    assert str(plan.get("goal") or "").strip() and plan.get("subtasks"), (
        f"proposed plan was not a real plan: {proposed_data}")
    assert usage.get("input_tokens") and usage.get("output_tokens"), (
        f"no real provider usage on run.completed: {completed_data}")
    assert (completed_data.get("changes") or {}).get("files", 0) >= 1, (
        f"approved plan run reported no file changes: {completed_data}")

    _write_evidence({
        "run_id": run_id,
        "plan_event_id": outcome["plan_event_id"],
        "plan_goal": str(plan.get("goal") or "")[:300],
        "plan_subtasks": len(plan.get("subtasks") or []),
        "proposed_at_s": outcome["proposed_at_s"],
        "approved_at_s": outcome["approved_at_s"],
        "completed_at_s": outcome.get("terminal_at_s"),
        "terminal_event": "run.completed",
        "result": "completed",
        "usage": {"input_tokens": usage.get("input_tokens"),
                  "output_tokens": usage.get("output_tokens")},
        "changes": completed_data.get("changes"),
        "wall_seconds": round(time.monotonic() - t0, 3),
    })
    _check(live, scenario, scenario, workspace)


# ---------------------------------------------------------------------------
# 09 — mid-task rewind to an earlier step, then continue
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_09_rewind_mid_task_then_continue(server_live) -> None:
    live, backend = server_live
    backend.start()
    scenario = "09-rewind-continue"
    workspace = live.workspace("rewind")

    first = _atlas_run_server(live, backend, f"{scenario}-step1",
                              _prompt(scenario, "task.md"), workspace)
    conversation_id = str(first.get("conversation_id") or "")
    assert conversation_id, "step1 summary lacks conversation_id"
    _atlas_run_server(live, backend, f"{scenario}-step2",
                      _prompt(scenario, "redo.md"), workspace,
                      "--resume", conversation_id)
    assert (workspace / "step2.txt").read_text(encoding="utf-8").strip() == "WRONG-VERSION"

    # Rewind to the SECOND user turn (the wrong step-2 instruction), restoring files.
    import httpx

    messages = _messages(live, backend, conversation_id)
    user_messages = [m for m in messages if str(m.get("role")) == "user"]
    assert len(user_messages) >= 2, f"expected >=2 user turns: {[m.get('role') for m in messages]}"
    target = user_messages[-1]
    (live.evidence / f"{scenario}-rewind").mkdir(parents=True, exist_ok=True)
    (live.evidence / f"{scenario}-rewind" / "before.json").write_text(
        _redact(json.dumps(
            [{"id": m.get("id"), "role": m.get("role"),
              "content": str(m.get("content") or "")[:120]} for m in messages],
            ensure_ascii=False, indent=2)), encoding="utf-8")
    response = httpx.post(
        f"{backend.base_url}/api/conversations/{conversation_id}/rewind",
        json={"message_id": target["id"], "files": True},
        headers={"x-atlas-api-token": "h10-live-smoke"}, timeout=60,
    )
    assert response.status_code == 200, f"rewind failed: HTTP {response.status_code} {response.text[:400]}"
    rewind = response.json()
    (live.evidence / f"{scenario}-rewind" / "rewind.json").write_text(
        _redact(json.dumps(rewind, ensure_ascii=False, indent=2)), encoding="utf-8")

    # Continue from the rewound state with the corrected step 2.
    _atlas_run_server(live, backend, f"{scenario}-retry",
                      _prompt(scenario, "retry.md"), workspace,
                      "--resume", conversation_id)
    after = _messages(live, backend, conversation_id)
    (live.evidence / f"{scenario}-rewind" / "after.json").write_text(
        _redact(json.dumps(
            [{"id": m.get("id"), "role": m.get("role"),
              "content": str(m.get("content") or "")[:120]} for m in after],
            ensure_ascii=False, indent=2)), encoding="utf-8")
    contents = [str(m.get("content") or "") for m in after]
    assert not any("WRONG-VERSION" in text for text in contents), (
        "rewound step-2 turn is still present in the conversation"
    )
    _check(live, scenario, scenario, workspace)


# ---------------------------------------------------------------------------
# 10 — steer the requirement mid-run (send_now over the runtime WS)
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_10_steer_changes_requirement_mid_run(server_live) -> None:
    live, backend = server_live
    backend.start()
    scenario = "10-steer-midrun"
    workspace = live.workspace("steer")
    prompt = _prompt(scenario)
    steer_text = (
        "需求变更（插话）：done.txt 的内容改为 V2-STEERED，不是 V1。"
        "命令跑完后按新要求写入。"
    )

    t0 = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, "-m", "atlas.cli", "run",
         "-p", prompt,
         "--workspace", str(workspace),
         "--model", live.model,
         "--output-format", "stream-json",
         "--timeout", "600",
         "--server", backend.base_url],
        cwd=str(live.root), env=live.child_env(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    state: dict[str, str] = {}
    live.processes.append(process)
    tool_started = threading.Event()
    run_finished = threading.Event()
    lines: list[str] = []
    stderr_lines, stderr_pump = _pump_stderr(process)

    def _pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            had_tool = tool_started.is_set()
            _observe_run_line(line, state, tool_started, run_finished)
            if not had_tool and tool_started.is_set():
                state["tool_started_at_s"] = str(round(time.monotonic() - t0, 3))

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not state.get("run_id"):
        time.sleep(0.1)
    run_id = state.get("run_id", "")
    assert run_id, f"no run_id observed in stream: {lines[-5:] if lines else 'no output'}"

    async def _steer() -> dict[str, Any]:
        import websockets

        # Steer deterministically mid-run: as soon as the first tool event of
        # the long command is observed (never a fixed delay), and never after
        # the run itself finished.
        loop = asyncio.get_running_loop()
        while (not tool_started.is_set() and not run_finished.is_set()
               and time.monotonic() < deadline):
            await asyncio.sleep(0.2)
        assert not run_finished.is_set(), (
            "run finished before the first tool event; the steer would land late "
            f"(tool_started={tool_started.is_set()})"
        )
        assert tool_started.is_set(), "no tool started; refusing to steer after the run ended"
        async with websockets.connect(
            backend.base_url.replace("http", "ws", 1) + "/ws/chat",
            additional_headers={"x-atlas-api-token": "h10-live-smoke"},
            max_size=8_000_000,
        ) as ws:
            await ws.send(json.dumps({"type": "run.steer", "run_id": run_id,
                                      "content": steer_text, "send_now": True,
                                      "immediate": False}, ensure_ascii=False))
            state["steer_sent_at_s"] = str(round(time.monotonic() - t0, 3))
            # On acceptance the run_steered event goes to the run's own
            # connection (the CLI), not this one; this socket only learns about
            # rejections. A quiet window therefore means "not rejected".
            steer_reply: dict[str, Any] = {}
            try:
                reply_deadline = loop.time() + 15
                while loop.time() < reply_deadline:
                    raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    kind = str(raw.get("event") or raw.get("type") or "")
                    steer_reply[kind] = raw
                    if "steer" in kind:
                        break
            except (TimeoutError, asyncio.TimeoutError):
                pass
            return steer_reply

    steer_reply = asyncio.run(_steer())
    exit_code, cli_hang = _finish_observed_process(process, pump, stderr_pump, 600)
    stdout, stderr = "", "".join(stderr_lines)
    run_dir = live.evidence / scenario
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "steer-reply.json").write_text(
        _redact(json.dumps(steer_reply, ensure_ascii=False, default=str, indent=2)),
        encoding="utf-8")
    stream_text = "".join(lines) + (stdout or "")
    (run_dir / "stream.jsonl").write_text(_redact(stream_text), encoding="utf-8")
    (run_dir / "stderr.log").write_text(_redact(stderr or ""), encoding="utf-8")
    # meta.json must reflect what actually happened, never a hardcoded claim:
    # "steered" is only true when the steer was not rejected AND the CLI stream
    # shows the run picked it up (run.steered).
    rejections = {
        kind: reply for kind, reply in steer_reply.items() if "rejected" in kind
    }
    rejection_reasons = [
        str((reply.get("data") or {}).get("reason") or "unknown")
        for reply in rejections.values()
    ]
    run_steered_observed = '"run.steered"' in stream_text
    (run_dir / "meta.json").write_text(json.dumps({
        "name": scenario, "exit_code": exit_code, "cli_hang": cli_hang,
        "run_id": run_id,
        "steer_sent": True,
        "steer_rejected": bool(rejections),
        "steer_rejection_reasons": rejection_reasons,
        "run_steered_observed": run_steered_observed,
        "steered": run_steered_observed and not rejections,
        "tool_started_at_s": state.get("tool_started_at_s"),
        "steer_sent_at_s": state.get("steer_sent_at_s"),
        "model": live.model,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    assert exit_code == 0, f"steered run failed exit={exit_code} stderr={_redact(stderr or '')[-1200:]}"
    assert not rejections, (
        "steer was rejected — a run_not_active rejection means it landed after "
        f"the run ended: {rejections}"
    )
    assert run_steered_observed, (
        "no run.steered event in the CLI stream; the steer never reached the turn"
    )
    _check(live, scenario, scenario, workspace)


# ---------------------------------------------------------------------------
# 12 — webhook channel task under ask_writes: approval → execution → receipt
# ---------------------------------------------------------------------------


class _Receiver:
    """Local HTTP sink for the webhook channel's outbound envelopes."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        received = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 — http.server API
                length = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(length)
                try:
                    self.payloads = self.server.payloads  # type: ignore[attr-defined]
                    self.server.payloads.append(  # type: ignore[attr-defined]
                        json.loads(body.decode("utf-8")))
                except json.JSONDecodeError:
                    pass
                received.set()
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_args) -> None:  # silence
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.payloads = self.payloads  # type: ignore[attr-defined]
        self.received = received
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/hook"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)
        assert not self.thread.is_alive(), "webhook receiver did not stop"


def _webhook_headers(secret: str, body: str) -> dict[str, str]:
    from atlas.channels.adapters.webhook import sign_payload

    return {
        "content-type": "application/json",
        "x-atlas-signature": sign_payload(secret, int(time.time()), body),
    }


@pytest.mark.live
def test_full_12_webhook_ask_writes_approval_receipt(server_live) -> None:
    live, backend = server_live
    scenario = "12-webhook-approval"
    import httpx

    secret = f"live-secret-{uuid.uuid4().hex[:8]}"
    receiver = _Receiver()
    headers = {"x-atlas-api-token": "h10-live-smoke"}
    run_dir = live.evidence / scenario
    run_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(live.root) / "channel-ws"
    done = workspace / "webhook-done.txt"
    done.unlink(missing_ok=True)

    def _record(step: str, response: httpx.Response) -> None:
        # Evidence lands BEFORE any assert: a failed setup step must leave a
        # readable trace (status + body), never an empty scenario directory.
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text[:800]
        (run_dir / f"{step}.json").write_text(_redact(json.dumps(
            {"status_code": response.status_code, "body": body},
            ensure_ascii=False, default=str, indent=2)), encoding="utf-8")

    # The webhook channel must already be enabled (with its secret) when the
    # backend's channel stack boots: ChannelManager.start() only creates
    # adapters for channels enabled at startup, and handle_webhook verifies the
    # HMAC against configs["secret"] — the value POSTed to /credential is never
    # read back (production gaps, documented in the lane report). Seeding the
    # manager's own persisted config file (the same file PUT /accounts writes)
    # is fixture setup: the inbound below is still HMAC-verified, and
    # approval → execution → receipt stay fully live.
    backend.seed_channel_configs = {
        "webhook": {"enabled": True, "url": receiver.url, "account": "live",
                    "secret": secret},
    }
    try:
        backend.start()
        # Configure the webhook channel: non-secret config + secret credential.
        response = httpx.put(
            f"{backend.base_url}/api/channels/accounts",
            json={"configs": {"webhook": {"enabled": True, "url": receiver.url,
                                          "account": "live"}}},
            headers=headers, timeout=30,
        )
        _record("accounts-put", response)
        assert response.status_code == 200, f"accounts PUT failed: {response.text[:300]}"
        response = httpx.post(
            f"{backend.base_url}/api/channels/credential",
            json={"channel": "webhook", "field": "secret", "value": secret},
            headers=headers, timeout=30,
        )
        _record("credential-post", response)
        assert response.status_code == 200, f"credential POST failed: {response.text[:300]}"

        task_text = _prompt(scenario)
        body = json.dumps({
            "event_id": f"live-{uuid.uuid4().hex[:8]}",
            "chat_id": "live-chat-1",
            "sender_id": "owner",
            "text": task_text,
        }, ensure_ascii=False)
        response = httpx.post(
            f"{backend.base_url}/api/channels/webhook/inbound",
            content=body.encode("utf-8"),
            headers=_webhook_headers(secret, body), timeout=30,
        )
        _record("inbound", response)
        assert response.status_code == 200, f"inbound failed: HTTP {response.status_code} {response.text[:300]}"

        # Wait for the ask_writes approval request to land on the channel…
        deadline = time.monotonic() + 240
        approval_text = ""
        while time.monotonic() < deadline:
            for payload in receiver.payloads:
                if "需要审批" in str(payload.get("text") or ""):
                    approval_text = str(payload.get("text") or "")
                    break
            if approval_text:
                break
            time.sleep(0.5)
        (run_dir / "receiver-approval.json").write_text(
            _redact(json.dumps(receiver.payloads, ensure_ascii=False, indent=2)),
            encoding="utf-8")
        assert approval_text, (
            f"no approval request reached the channel; payloads={receiver.payloads!r}"
        )
        approval_id = approval_text.split("审批")[-1].strip("）。 ")

        # …then answer from the channel (H7: channel reply resolves the shared future).
        reply_text = f"允许 {approval_id}" if approval_id and " " not in approval_id else "允许"
        reply_body = json.dumps({
            "event_id": f"live-approve-{uuid.uuid4().hex[:8]}",
            "chat_id": "live-chat-1",
            "sender_id": "owner",
            "text": reply_text,
        }, ensure_ascii=False)
        response = httpx.post(
            f"{backend.base_url}/api/channels/webhook/inbound",
            content=reply_body.encode("utf-8"),
            headers=_webhook_headers(secret, reply_body), timeout=30,
        )
        _record("approval-reply", response)
        assert response.status_code == 200, f"approval reply failed: {response.text[:300]}"

        # A fresh receiver belongs to this inbound request; reject failed/stopped
        # task receipts rather than treating any non-approval text as success.
        deadline = time.monotonic() + 300
        receipt = ""
        while time.monotonic() < deadline:
            for payload in reversed(receiver.payloads):
                text = str(payload.get("text") or "")
                if "需要审批" in text or text.startswith("已允许"):
                    continue
                assert not text.startswith(("任务执行失败", "任务已停止")), (
                    f"channel task returned a failure receipt: {text}"
                )
                receipt = text
                break
            if receipt:
                break
            time.sleep(1.0)
        (run_dir / "receiver-all.json").write_text(
            _redact(json.dumps(receiver.payloads, ensure_ascii=False, indent=2)),
            encoding="utf-8")
        assert receipt, "no completion receipt arrived on the channel"

        # …and the write itself must have executed in the gateway workspace.
        assert done.is_file(), (
            f"channel task did not write its file in {workspace}; receipts={receiver.payloads!r}"
        )
        assert done.read_text(encoding="utf-8").strip() == "CHANNEL-RECEIPT-OK"
        _check(live, scenario, scenario, workspace)
        (run_dir / "meta.json").write_text(json.dumps({
            "name": scenario, "model": live.model,
            "approval_id": approval_id,
            "receipt": receipt[:200],
            "gateway_base_url": live.gateway_base_url,
            "webhook_signed_inbound": True,
            # How the channel got its secret: seeded via channel-configs.json at
            # backend boot. POST /api/channels/credential succeeded but its
            # keyring value is never consulted by ChannelManager.handle_webhook,
            # and a runtime-only accounts PUT cannot start the adapter either —
            # both are production gaps owned by the channels lane (H1R2 report).
            "secret_source": "channel-configs.json seed (pre-boot); "
                             "credential readback gap tracked separately",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        receiver.stop()
