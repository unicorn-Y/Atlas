"""H10.2 §12.2 full live scenarios needing one persistent backend (08/09/10/12).

- 08 计划模式出计划，再按计划执行: a ``--permission-mode plan`` run proposes the
  plan (``run.plan.proposed``) and parks in ``waiting``; the desktop surface is
  the ``run.plan.approve`` WS message, so a second ``/ws/chat`` connection plays
  the desktop: approve → the engine executes the same run → greet.py works.
- 09 做到一半回退到某一步再继续: two ``atlas run --server`` turns, rewind the
  second turn through the production route (``POST /api/conversations/{id}/rewind``,
  files restored from the run checkpoints), retry with the corrected instruction.
- 10 运行中第 N 秒插话改需求: an ``atlas run --server`` turn grinding through a
  long command; a SECOND ``/ws/chat`` connection sends ``run.steer`` with
  ``send_now`` mid-run and the old requirement must be replaced.
- 12 Webhook 渠道入站任务（ask_writes）→ 审批 → 执行 → 渠道回执: signed inbound
  webhook event, the H7 approval request lands on the channel, the 「允许」
  channel reply unblocks the real model write, the receipt is POSTed back to a
  local receiver.

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

    def start(self) -> None:
        env = self.live.child_env()
        env.pop("ATLAS_LIVE_SMOKE_ROOT", None)  # harness knob, not for the backend
        env["PYTHONUNBUFFERED"] = "1"
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
                    return
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
        backend.start()
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


def _observe_run_line(line: str, state: dict[str, str], tool_started: threading.Event) -> None:
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
                             stderr_thread: threading.Thread, timeout: float) -> int:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=30)
    stdout_thread.join(timeout=30)
    stderr_thread.join(timeout=30)
    assert not stdout_thread.is_alive() and not stderr_thread.is_alive(), "CLI pipes did not close"
    return int(process.returncode)


# ---------------------------------------------------------------------------
# 08 — plan mode proposes, the desktop approves over WS, execution follows
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_08_plan_propose_approve_then_execute(server_live) -> None:
    live, backend = server_live
    scenario = "08-plan-execute"
    workspace = live.workspace("plan")
    prompt = _prompt(scenario)
    run_dir = live.evidence / scenario
    run_dir.mkdir(parents=True, exist_ok=True)

    process = subprocess.Popen(
        [sys.executable, "-m", "atlas.cli", "run",
         "-p", prompt,
         "--workspace", str(workspace),
         "--model", live.model,
         "--permission-mode", "plan",
         "--output-format", "stream-json",
         "--timeout", "480",
         "--server", backend.base_url],
        cwd=str(live.root), env=live.child_env(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lines: list[str] = []
    proposed: dict[str, Any] = {}
    live.processes.append(process)
    stderr_lines, stderr_pump = _pump_stderr(process)

    def _pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            if "run.plan.proposed" in line and not proposed:
                try:
                    event = json.loads(line)
                    proposed["run_id"] = str(event.get("run_id") or "")
                    proposed["event_id"] = str((event.get("data") or {}).get("event_id") or "")
                except json.JSONDecodeError:
                    continue

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()

    deadline = time.monotonic() + 420
    while time.monotonic() < deadline and not proposed:
        if process.poll() is not None:
            break
        time.sleep(0.2)
    assert proposed, (
        f"plan was never proposed in 420s: tail={lines[-3:] if lines else 'no output'}"
    )
    # Planning phase must not have executed the task.
    assert not (workspace / "greet.py").exists(), "plan phase executed instead of planning"

    async def _approve() -> None:
        import websockets

        async with websockets.connect(
            backend.base_url.replace("http", "ws", 1) + "/ws/chat",
            additional_headers={"x-atlas-api-token": "h10-live-smoke"},
            max_size=8_000_000,
        ) as ws:
            await ws.send(json.dumps({
                "type": "run.plan.approve", "run_id": proposed["run_id"],
                "event_id": proposed["event_id"], "edits": "",
            }, ensure_ascii=False))

    asyncio.run(_approve())
    exit_code = _finish_observed_process(process, pump, stderr_pump, 420)
    stdout, stderr = "", "".join(stderr_lines)

    (run_dir / "stream.jsonl").write_text(_redact("".join(lines) + (stdout or "")),
                                          encoding="utf-8")
    (run_dir / "stderr.log").write_text(_redact(stderr or ""), encoding="utf-8")
    (run_dir / "meta.json").write_text(json.dumps({
        "name": scenario, "exit_code": exit_code, "model": live.model,
        "plan_approved_via": "run.plan.approve (second WS connection)",
        "run_id": proposed.get("run_id"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    assert exit_code == 0, (
        f"approved plan run failed exit={exit_code} stderr={_redact(stderr or '')[-1200:]}"
    )
    stream_text = "".join(lines) + (stdout or "")
    assert "run.completed" in stream_text, "approved plan run never completed"
    _check(live, scenario, scenario, workspace)


# ---------------------------------------------------------------------------
# 09 — mid-task rewind to an earlier step, then continue
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_09_rewind_mid_task_then_continue(server_live) -> None:
    live, backend = server_live
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
    scenario = "10-steer-midrun"
    workspace = live.workspace("steer")
    prompt = _prompt(scenario)
    steer_text = (
        "需求变更（插话）：done.txt 的内容改为 V2-STEERED，不是 V1。"
        "命令跑完后按新要求写入。"
    )

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
    lines: list[str] = []
    stderr_lines, stderr_pump = _pump_stderr(process)

    def _pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            _observe_run_line(line, state, tool_started)

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not state.get("run_id"):
        time.sleep(0.1)
    run_id = state.get("run_id", "")
    assert run_id, f"no run_id observed in stream: {lines[-5:] if lines else 'no output'}"

    async def _steer() -> dict[str, Any]:
        import websockets

        # Wait until the long command actually started before steering.
        loop = asyncio.get_running_loop()
        while not tool_started.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        assert tool_started.is_set(), "no tool started; refusing to steer after the run ended"
        async with websockets.connect(
            backend.base_url.replace("http", "ws", 1) + "/ws/chat",
            additional_headers={"x-atlas-api-token": "h10-live-smoke"},
            max_size=8_000_000,
        ) as ws:
            await ws.send(json.dumps({"type": "run.steer", "run_id": run_id,
                                      "content": steer_text, "send_now": True,
                                      "immediate": False}, ensure_ascii=False))
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
    exit_code = _finish_observed_process(process, pump, stderr_pump, 600)
    stdout, stderr = "", "".join(stderr_lines)
    run_dir = live.evidence / scenario
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "steer-reply.json").write_text(
        _redact(json.dumps(steer_reply, ensure_ascii=False, default=str, indent=2)),
        encoding="utf-8")
    (run_dir / "stream.jsonl").write_text(_redact("".join(lines) + (stdout or "")),
                                          encoding="utf-8")
    (run_dir / "stderr.log").write_text(_redact(stderr or ""), encoding="utf-8")
    (run_dir / "meta.json").write_text(json.dumps({
        "name": scenario, "exit_code": exit_code, "run_id": run_id,
        "steered": True, "model": live.model,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    assert exit_code == 0, f"steered run failed exit={exit_code} stderr={_redact(stderr or '')[-1200:]}"
    rejected = [k for k in steer_reply if "rejected" in k]
    assert not rejected, f"steer was rejected: {steer_reply}"
    stream_text = "".join(lines) + (stdout or "")
    assert "run_steered" in stream_text, (
        "no run_steered event in the run stream; the steer never reached the turn"
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
    try:
        # Configure the webhook channel: non-secret config + secret credential.
        response = httpx.put(
            f"{backend.base_url}/api/channels/accounts",
            json={"configs": {"webhook": {"enabled": True, "url": receiver.url,
                                          "account": "live"}}},
            headers=headers, timeout=30,
        )
        assert response.status_code == 200, f"accounts PUT failed: {response.text[:300]}"
        response = httpx.post(
            f"{backend.base_url}/api/channels/credential",
            json={"channel": "webhook", "field": "secret", "value": secret},
            headers=headers, timeout=30,
        )
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
        assert response.status_code == 200, f"inbound failed: HTTP {response.status_code} {response.text[:300]}"
        accepted = response.json()
        (run_dir / "inbound.json").write_text(
            _redact(json.dumps(accepted, ensure_ascii=False, indent=2)), encoding="utf-8")

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
        assert response.status_code == 200, f"approval reply failed: {response.text[:300]}"

        # Finally the completion receipt must arrive on the channel: everything
        # after the approval ack that is not an approval request is the answer.
        deadline = time.monotonic() + 300
        receipt = ""
        while time.monotonic() < deadline:
            for payload in reversed(receiver.payloads):
                text = str(payload.get("text") or "")
                if "需要审批" in text or text.startswith("已允许"):
                    continue
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
        workspace = Path(live.root) / "channel-ws"
        done = workspace / "webhook-done.txt"
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
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        receiver.stop()
