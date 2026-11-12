"""H9 headless CLI tests (taskbook §11).

``atlas run`` must complete a real file-modification task against the fake
model stack, drive ``--resume`` across two invocations, auto-deny approvals in
non-interactive mode with exit code 3, and survive a Chinese-path workspace on
Windows. Boot tests spawn the CLI as a subprocess exactly like a user would;
parsing/help tests stay in-process via ``click.testing``.

The CLI owns no business logic: it starts the regular ``atlas.server`` app
in-process and drives the existing ``/ws/chat`` Runtime Event Protocol, so
these tests double as protocol-contract checks for the headless path.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner

from atlas.cli import _prepare_exec_images, main
from tests.fakes.fake_llm_provider import (
    Error,
    FakeLLMServer,
    Text,
    ToolCall,
    write_atlas_home,
)

CORE_ROOT = Path(__file__).resolve().parents[1]
CLI_TIMEOUT = 240.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _atlas_root() -> Path:
    import hermes_state

    return Path(hermes_state.__file__).resolve().parent


def _clean_child_env(root: Path, fake_url: str, **extra: str) -> dict[str, str]:
    """Isolated env for a CLI subprocess: one fresh data root, fake gateway."""
    data = root / "atlas"
    engine = root / "engine"
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    (data / "config").mkdir(parents=True, exist_ok=True)
    engine.mkdir(parents=True, exist_ok=True)
    (data / "config" / "atlas.toml").write_text(
        '[models]\ndefault="fake-model"\n'
        f'[models.gateway]\nbase_url="{fake_url}"\napi_key="sk-fake-e2e"\n'
        '[[models.custom]]\nid="fake-model"\nname="Fake fixture"\nprovider="openai"\n'
        'litellm_model="openai/fake-model"\nmax_output_tokens=512\n'
        '[agent]\nengine="hermes"\nverify_before_stop=false\n'
        '[tools]\nauto_start=[]\n[tools.servers]\n'
        '[scheduler]\nenabled=false\n',
        encoding="utf-8",
    )
    write_atlas_home(
        engine, fake_url,
        extra_config=(
            "tools:\n  tool_search:\n    enabled: off\n"
            "auxiliary:\n  title_generation:\n    model_upgrade_enabled: false\n"
        ),
    )
    env = dict(os.environ)
    for key in list(env):
        upper = key.upper()
        if (any(marker in upper for marker in
                ("API_KEY", "ACCESS_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD",
                 "CREDENTIAL", "AUTH"))
                or upper.startswith("HERMES_SESSION_")
                or upper.endswith("_PROXY")):
            env.pop(key, None)
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        env[key] = str(home)
    paths = [str(CORE_ROOT), str(_hermes_root())]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.update(
        ATLAS_DATA_DIR=str(data),
        HERMES_HOME=str(engine),
        ATLAS_SCHEDULER_ENABLED="false",
        ATLAS_API_TOKEN="cli-headless-token",
        NO_PROXY="127.0.0.1,localhost",
        HERMES_TEST_MODE="1",
        PYTHONIOENCODING="utf-8",
        **extra,
    )
    return env


def _run_cli(env: dict[str, str], *args: str, timeout: float = CLI_TIMEOUT,
             cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "atlas.cli", *args],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, cwd=cwd,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _parse_stream(stdout: str) -> list[dict[str, Any]]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    parsed = [json.loads(line) for line in lines]  # raises on non-JSON lines
    assert parsed, "expected at least one stdout line"
    return parsed


@pytest.fixture
def cli_backend(tmp_path: Path):
    """Fake model + isolated child env; tests script ``fake._responder``."""
    with FakeLLMServer() as fake:
        env = _clean_child_env(tmp_path, fake.base_url)
        yield SimpleNamespace(fake=fake, env=env, root=tmp_path)


# ---------------------------------------------------------------------------
# Unit: argument surface (no runtime boot)
# ---------------------------------------------------------------------------


def test_run_help_documents_headless_options():
    result = CliRunner().invoke(main, ["run", "--help"])
    assert result.exit_code == 0
    for needle in ("-p", "--print", "--workspace", "--model", "--permission-mode",
                   "--output-format", "stream-json", "--max-turns", "--resume",
                   "--server"):
        assert needle in result.output, needle


def test_doctor_help_documents_checks():
    result = CliRunner().invoke(main, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


def test_exec_help_exposes_repeatable_image_input():
    result = CliRunner().invoke(main, ["exec", "--help"])
    assert result.exit_code == 0
    assert "--image" in result.output


def test_exec_images_become_inline_multimodal_data_urls(tmp_path):
    first = tmp_path / "one.png"
    first.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fixture")
    second = tmp_path / "two.jpg"
    second.write_bytes(b"\xff\xd8\xff" + b"fixture")

    data_urls, manifest = _prepare_exec_images((first, second))

    assert data_urls[0].startswith("data:image/png;base64,")
    assert data_urls[1].startswith("data:image/jpeg;base64,")
    assert [item["name"] for item in manifest] == ["one.png", "two.jpg"]
    assert [item["size"] for item in manifest] == [15, 10]


def test_exec_jsonl_reports_image_validation_error_as_parseable_events(tmp_path):
    missing = tmp_path / "missing.png"
    result = CliRunner().invoke(main, ["exec", "describe", "--image", str(missing), "--output-format", "jsonl"])

    assert result.exit_code == 2
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[0]["type"] == "error"
    assert events[0]["code"] == "invalid_image"
    assert events[1]["type"] == "turn.failed"
    assert events[-1]["type"] == "end" and events[-1]["status"] == "failed"
    assert all(event["protocol"] == "atlas.exec.events" and event["version"] == 1
               for event in events)


def test_exec_passes_images_to_orchestrator_and_emits_jsonl_input(tmp_path, monkeypatch):
    image = tmp_path / "fixture.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    seen: dict[str, Any] = {}

    class Memory:
        async def init(self): pass
        async def save_conversation_metadata(self, *_args, **_kwargs): pass
        async def close(self): pass

    class Orchestrator:
        def __init__(self, **_kwargs): pass
        def run(self, _prompt, _conversation, **kwargs):
            seen["images"] = kwargs["image_attachments"]
            async def events():
                yield {"type": "chunk", "content": "looked at it"}
            return events()

    monkeypatch.setattr("atlas.memory.MemoryStore", Memory)
    monkeypatch.setattr("atlas.agent.AgentOrchestrator", Orchestrator)
    monkeypatch.setattr("atlas.cli._daybreak_enabled", lambda: False)
    async def migration_ready(*_args): return SimpleNamespace(status="ready", error="")
    monkeypatch.setattr("atlas.engine.session_migration.migrate_legacy_sessions", migration_ready)
    async def passthrough(_project_id, events, **_kwargs):
        async for event in events:
            yield event
    monkeypatch.setattr("atlas.project_context.project_scoped_events", passthrough)

    result = CliRunner().invoke(main, ["exec", "What is shown?", "--image", str(image), "--json"])

    assert result.exit_code == 0, result.output
    events = [json.loads(line) for line in result.stdout.splitlines()]
    input_event = next(item for item in events if item["type"] == "input")
    assert input_event["text"] == "What is shown?"
    assert input_event["images"] == [{"name": "fixture.png", "mime": "image/png", "size": 15}]
    assert seen["images"][0].startswith("data:image/png;base64,")


def test_run_without_prompt_exits_2_with_json_error():
    result = CliRunner().invoke(main, ["run"], input="")
    assert result.exit_code == 2
    assert '"scope": "arguments"' in result.stderr
    assert "-p" in result.stderr


def test_run_rejects_unknown_output_format_and_permission_mode():
    bad_format = CliRunner().invoke(main, ["run", "-p", "hi", "--output-format", "yaml"])
    assert bad_format.exit_code == 2
    assert "output-format" in bad_format.stderr
    bad_mode = CliRunner().invoke(main, ["run", "-p", "hi", "--permission-mode", "yolo"])
    assert bad_mode.exit_code == 2
    assert "permission-mode" in bad_mode.stderr


def test_run_rejects_missing_or_relative_workspace(tmp_path):
    result = CliRunner().invoke(
        main, ["run", "-p", "hi", "--workspace", str(tmp_path / "没有这个目录")])
    assert result.exit_code == 2
    assert '"scope": "arguments"' in result.stderr


def test_run_rejects_non_positive_max_turns(tmp_path):
    result = CliRunner().invoke(main, ["run", "-p", "hi", "--max-turns", "0",
                                       "--workspace", str(tmp_path)])
    assert result.exit_code == 2
    assert '"scope": "arguments"' in result.stderr


# ---------------------------------------------------------------------------
# Integration: real in-process runtime boots inside the CLI subprocess
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_run_writes_file_with_stream_json_and_chinese_workspace(cli_backend):
    backend = cli_backend
    workspace = backend.root / "工作区 中文"  # Chinese-path workspace on Windows
    workspace.mkdir()
    target = workspace / "notes.txt"
    calls = {"n": 0}

    def responder(record):
        calls["n"] += 1
        if calls["n"] == 1:
            return ToolCall("write_file",
                            {"path": str(target), "content": "ATLAS_CLI_H9 中文内容"})
        return Text("写入完成：notes.txt 已包含 ATLAS_CLI_H9")

    backend.fake._responder = responder

    proc = _run_cli(
        backend.env, "run",
        "-p", "把 ATLAS_CLI_H9 写入 notes.txt",
        "--workspace", str(workspace),
        "--model", "fake-model",
        "--output-format", "stream-json",
    )
    assert proc.returncode == 0, proc.stderr[-2000:]

    events = _parse_stream(proc.stdout)
    summaries = [item for item in events if item.get("type") == "summary"]
    envelopes = [item for item in events if item.get("type") == "agent_event"]
    assert len(summaries) == 1
    assert envelopes, "expected at least one protocol event"
    assert events[-1] is summaries[0]

    summary = summaries[0]
    assert summary["result"] == "completed"
    assert summary["conversation_id"]
    assert isinstance(summary["elapsed_seconds"], (int, float))
    assert isinstance(summary["usage"], dict) and summary["usage"]
    assert summary["usage"]["request_count"] >= 2
    purpose_totals = summary["usage"]["purpose_totals"]
    assert purpose_totals["conversation"]["request_count"] >= 2
    assert sum(item["request_count"] for item in purpose_totals.values()) == summary["usage"]["request_count"]
    assert {"files", "additions", "deletions"} <= set(summary["changes"])
    assert "写入完成" in summary["message"]

    assert target.read_text(encoding="utf-8") == "ATLAS_CLI_H9 中文内容"
    assert any(e["event"] == "tool.completed" and e["data"].get("name") == "write_file"
               and not e["data"].get("is_error") for e in envelopes)


@pytest.mark.integration
def test_run_resume_continues_the_previous_conversation(cli_backend):
    backend = cli_backend
    workspace = backend.root / "workspace"
    workspace.mkdir()

    # Turn 1: single JSON summary object on stdout; capture the conversation.
    backend.fake._responder = lambda record: Text("first-reply-唯一标记")
    first = _run_cli(
        backend.env, "run",
        "-p", "第一轮：记住唯一标记",
        "--workspace", str(workspace),
        "--model", "fake-model",
        "--output-format", "json",
    )
    assert first.returncode == 0, first.stderr[-2000:]
    summary = json.loads(first.stdout)
    assert summary["type"] == "summary"
    assert summary["result"] == "completed"
    conversation_id = summary["conversation_id"]
    assert conversation_id

    # Turn 2: --resume must reuse the same conversation and see turn 1 history.
    backend.fake._responder = lambda record: Text("second-reply-接着上一会话")
    second = _run_cli(
        backend.env, "run",
        "-p", "第二轮：继续",
        "--resume", conversation_id,
        "--workspace", str(workspace),
        "--model", "fake-model",
        "--output-format", "stream-json",
    )
    assert second.returncode == 0, second.stderr[-2000:]
    events = _parse_stream(second.stdout)
    summary = [e for e in events if e.get("type") == "summary"][-1]
    assert summary["conversation_id"] == conversation_id
    assert summary["result"] == "completed"

    # The resumed turn's model request carried the first turn's assistant reply.
    bodies = [json.dumps(request, ensure_ascii=False)
              for request in backend.fake.main_requests()]
    assert any("first-reply-唯一标记" in body for body in bodies)


@pytest.mark.integration
def test_run_non_interactive_approval_auto_denies_with_exit_3(cli_backend):
    backend = cli_backend
    workspace = backend.root / "workspace"
    workspace.mkdir()
    target = workspace / "forbidden.txt"
    calls = {"n": 0}

    def responder(record):
        calls["n"] += 1
        if calls["n"] == 1:
            return ToolCall("write_file", {"path": str(target), "content": "不应写入"})
        # After the denial the engine re-prompts; the task then gives up.
        return Text("好的，已放弃写文件")

    backend.fake._responder = responder

    proc = _run_cli(
        backend.env, "run",
        "-p", "把内容写入 forbidden.txt",
        "--workspace", str(workspace),
        "--model", "fake-model",
        "--permission-mode", "ask_writes",
        "--output-format", "stream-json",
    )
    assert proc.returncode == 3, proc.stderr[-2000:]

    events = _parse_stream(proc.stdout)
    kinds = [e.get("event") for e in events if e.get("type") == "agent_event"]
    assert "approval.required" in kinds
    assert "approval.responded" in kinds
    responded = next(e for e in events
                     if e.get("type") == "agent_event" and e["event"] == "approval.responded")
    assert responded["data"]["choice"] == "deny"

    summary = [e for e in events if e.get("type") == "summary"][-1]
    assert summary["approvals_denied"] == 1
    assert not target.exists()


@pytest.mark.integration
def test_run_max_turns_cancels_and_exits_0(cli_backend):
    backend = cli_backend
    workspace = backend.root / "workspace"
    workspace.mkdir()
    target = workspace / "loop.txt"
    calls = {"n": 0}

    def responder(record):
        calls["n"] += 1
        if calls["n"] == 1:
            return ToolCall("write_file", {"path": str(target), "content": "x"})
        return Text("继续下一步")

    backend.fake._responder = responder

    proc = _run_cli(
        backend.env, "run",
        "-p", "写文件后继续",
        "--workspace", str(workspace),
        "--model", "fake-model",
        "--max-turns", "1",
        "--output-format", "stream-json",
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    events = _parse_stream(proc.stdout)
    summary = [e for e in events if e.get("type") == "summary"][-1]
    assert summary["result"] == "cancelled"
    assert summary["stop_reason"] == "max_turns"


@pytest.mark.integration
def test_run_reports_permanent_model_failure_as_failed_exit_1(cli_backend):
    """H10.2-DEFECT-2: a non-retryable provider 404 must fail the run.

    The engine used to emit recovery notices and then `run.completed` with an
    empty message and null usage, so `atlas run` exited 0 on a turn that never
    produced any model output.
    """
    backend = cli_backend
    workspace = backend.root / "workspace"
    workspace.mkdir()
    # The engine makes api_max_retries+1 attempts even for a non-retryable
    # verdict; fail every attempt so the turn ends terminally failed.
    backend.fake.push(*[
        Error(
            status=404,
            message='Model "openai/fake-model" is not supported by any '
                    'configured account in this group',
        )
        for _ in range(3)
    ])

    proc = _run_cli(
        backend.env, "run",
        "-p", "在工作区创建 failure-probe.txt，内容为 unreachable。",
        "--workspace", str(workspace),
        "--model", "fake-model",
        "--output-format", "stream-json",
    )

    assert proc.returncode == 1, f"stdout={proc.stdout[-1500:]} stderr={proc.stderr[-1500:]}"
    events = _parse_stream(proc.stdout)
    kinds = [e.get("event") for e in events if e.get("type") == "agent_event"]
    assert "run.failed" in kinds
    assert "run.completed" not in kinds
    summary = [e for e in events if e.get("type") == "summary"][-1]
    assert summary["result"] == "failed"
    assert summary["detail"]
    assert not (workspace / "failure-probe.txt").exists()


@pytest.mark.integration
def test_run_relative_write_lands_in_workspace_not_launch_dir(cli_backend):
    """H10.2-DEFECT-3: a relative-path write anchors to --workspace.

    The real-model smoke wrote `hello.txt` into the process launch dir because
    neither the engine prompt nor the file tools knew the workspace. The CLI
    now runs with cwd=<launch dir> — deliberately NOT the workspace.
    """
    backend = cli_backend
    workspace = backend.root / "ws-relative"
    workspace.mkdir()
    launch_dir = backend.root / "launch-dir"
    launch_dir.mkdir()
    calls = {"n": 0}

    def responder(record):
        calls["n"] += 1
        if calls["n"] == 1:
            return ToolCall("write_file",
                            {"path": "relative-probe.txt", "content": "D3-ANCHOR"})
        return Text("已写入 relative-probe.txt")

    backend.fake._responder = responder

    proc = _run_cli(
        backend.env, "run",
        "-p", "在当前工作区创建 relative-probe.txt，内容为 D3-ANCHOR。",
        "--workspace", str(workspace),
        "--model", "fake-model",
        "--output-format", "stream-json",
        cwd=str(launch_dir),
    )

    assert proc.returncode == 0, proc.stderr[-2000:]
    assert (workspace / "relative-probe.txt").read_text(encoding="utf-8") == "D3-ANCHOR"
    assert not (launch_dir / "relative-probe.txt").exists(), (
        "the relative write leaked into the process launch dir"
    )


@pytest.mark.integration
def test_doctor_reports_all_checks_and_models_probe(cli_backend):
    backend = cli_backend

    ok_proc = _run_cli(backend.env, "doctor", "--json", timeout=120)
    assert ok_proc.returncode == 0, ok_proc.stderr[-2000:]
    report = json.loads(ok_proc.stdout)
    assert report["type"] == "doctor" and report["ok"] is True
    assert {"config", "sessions", "models", "mcp"} <= set(report["checks"])
    assert report["checks"]["config"]["ok"] is True
    assert report["checks"]["sessions"]["ok"] is True
    models = report["checks"]["models"]
    assert models["ok"] is True and models["http_status"] == 200
    assert models["gateway_base_url"] == backend.fake.base_url
    # The API key must never leak through doctor output.
    assert "sk-fake-e2e" not in ok_proc.stdout

    # Unreachable gateway -> models check fails, doctor exits 1.
    broken_env = _clean_child_env(backend.root / "doctor-broken", "http://127.0.0.1:1/v1")
    bad_proc = _run_cli(broken_env, "doctor", "--json", timeout=120)
    assert bad_proc.returncode == 1
    bad_report = json.loads(bad_proc.stdout)
    assert bad_report["ok"] is False
    assert bad_report["checks"]["models"]["ok"] is False


# ---------------------------------------------------------------------------
# Regression (h1r2 Lane G): the CLI process must end by itself once the turn
# is over. The h10 live round showed `atlas run` outliving its own summary
# (scenario 08: engine printed "Conversation completed", the CLI then sat in
# _drive_turn's ws.recv until the harness killed it at 600s — plan mode has no
# terminal event a headless client could wait for). These tests spawn the real
# CLI subprocess against the fake model stack and assert the process exits
# within 30s of the completion event, in both runtime topologies; a kill only
# ever happens on the failure path, never to fake a pass.
# ---------------------------------------------------------------------------

_EXIT_BUDGET_SECONDS = 30.0
_TERMINAL_OR_PLAN_EVENTS = {"run.completed", "run.failed", "run.cancelled",
                            "run.plan.proposed"}


def _run_cli_observed(env: dict[str, str], *args: str,
                      timeout: float = CLI_TIMEOUT) -> SimpleNamespace:
    """Run the CLI subprocess, timing how long it lives past its completion event.

    Returns returncode, parsed stdout events, stderr, the first completion-kind
    event seen and the seconds between that event and process exit (None when
    the process died before any completion event). Exceeding the exit budget
    kills the child and fails — the kill is the diagnostic, not the assertion.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "atlas.cli", *args],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    events: list[dict[str, Any]] = []
    stderr_lines: list[str] = []
    observed: dict[str, Any] = {"kind": "", "at": None}

    def _pump_err() -> None:
        assert proc.stderr is not None
        stderr_lines.extend(proc.stderr)

    def _pump_out() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            events.append(item)
            kind = str(item.get("event") or "")
            if item.get("type") == "summary" or kind in _TERMINAL_OR_PLAN_EVENTS:
                if observed["at"] is None:
                    observed["kind"] = kind or "summary"
                    observed["at"] = time.monotonic()

    out_thread = threading.Thread(target=_pump_out, daemon=True)
    err_thread = threading.Thread(target=_pump_err, daemon=True)
    out_thread.start()
    err_thread.start()

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if observed["at"] is not None or proc.poll() is not None:
            break
        time.sleep(0.05)
    else:
        proc.kill()
        proc.wait(timeout=30)
        pytest.fail(
            f"CLI never reached a completion event in {timeout}s; "
            f"tail={events[-5:]} stderr={''.join(stderr_lines)[-1500:]}"
        )

    exit_latency: float | None = None
    if observed["at"] is not None:
        budget = observed["at"] + _EXIT_BUDGET_SECONDS - time.monotonic()
        try:
            proc.wait(timeout=max(budget, 0.0))
            exit_latency = time.monotonic() - observed["at"]
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=30)
            pytest.fail(
                f"CLI was still alive {_EXIT_BUDGET_SECONDS}s after {observed['kind']}; "
                f"events_tail={events[-5:]} stderr={''.join(stderr_lines)[-1500:]}"
            )
    else:
        proc.wait(timeout=30)
    out_thread.join(timeout=30)
    err_thread.join(timeout=30)
    assert not out_thread.is_alive() and not err_thread.is_alive(), "CLI pipes did not close"
    return SimpleNamespace(
        returncode=int(proc.returncode), events=events,
        stderr="".join(stderr_lines), completion_kind=observed["kind"],
        exit_after_completion=exit_latency,
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def external_backend(cli_backend):
    """cli_backend plus the regular Atlas app served by a real uvicorn subprocess.

    Same topology as the h10 live Backend: the backend is its own process; the
    CLI child connects with ``--server`` instead of booting the in-process
    runtime. Both processes share the one isolated data root, like production.
    """
    import httpx

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_path = cli_backend.root / "backend.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "atlas.server:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            env=cli_backend.env, cwd=str(CORE_ROOT), stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + 90.0
        last = ""
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise AssertionError(
                    f"backend exited early rc={proc.returncode}: "
                    f"{log_path.read_text(encoding='utf-8', errors='replace')[-800:]}"
                )
            try:
                response = httpx.get(f"{base_url}/api/health", timeout=2.0)
                if response.status_code == 200 and response.json().get("status") == "ok":
                    break
                last = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            time.sleep(0.25)
        else:
            proc.terminate()
            proc.wait(timeout=30)
            raise AssertionError(f"backend not healthy in 90s: {last}")
        try:
            yield SimpleNamespace(
                fake=cli_backend.fake, env=cli_backend.env, root=cli_backend.root,
                base_url=base_url, proc=proc,
            )
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)


def _assert_prompt_exit(observed: SimpleNamespace, expected_code: int) -> dict[str, Any]:
    assert observed.completion_kind == "run.completed", (
        f"completion={observed.completion_kind} stderr={observed.stderr[-1500:]}"
    )
    assert observed.returncode == expected_code, (
        f"exit={observed.returncode} stderr={observed.stderr[-2000:]}"
    )
    assert observed.exit_after_completion is not None
    assert observed.exit_after_completion <= _EXIT_BUDGET_SECONDS
    summaries = [e for e in observed.events if e.get("type") == "summary"]
    assert summaries, observed.stderr[-1500:]
    return summaries[-1]


@pytest.mark.integration
def test_run_exits_within_30s_of_completion_in_process_mode(cli_backend):
    """Default topology: the headless runtime boots in the CLI process itself."""
    backend = cli_backend
    workspace = backend.root / "ws-exit-inproc"
    workspace.mkdir()
    observed = _run_cli_observed(
        backend.env, "run",
        "-p", "请直接回复两个字母：ok",
        "--workspace", str(workspace),
        "--model", "fake-model",
        "--output-format", "stream-json",
    )
    summary = _assert_prompt_exit(observed, 0)
    assert summary["result"] == "completed"
    assert summary["plan_denied"] is False


@pytest.mark.integration
def test_run_exits_within_30s_of_completion_server_mode(external_backend):
    """External topology: the CLI connects to an already-running backend."""
    backend = external_backend
    workspace = backend.root / "ws-exit-server"
    workspace.mkdir()
    observed = _run_cli_observed(
        backend.env, "run",
        "-p", "请直接回复两个字母：ok",
        "--workspace", str(workspace),
        "--model", "fake-model",
        "--output-format", "stream-json",
        "--server", backend.base_url,
    )
    summary = _assert_prompt_exit(observed, 0)
    assert summary["result"] == "completed"


@pytest.mark.integration
def test_run_plan_mode_ends_deterministically_with_exit_3_after_plan_proposed(cli_backend):
    """Scenario-08 regression: plan mode must not outlive its own proposal.

    The engine parks the run in `waiting` for a plan approval after emitting
    run.plan.proposed; headless has nobody to approve, so the CLI cancels the
    parked run (run.cancel -> run.cancelled) and exits 3 — it used to sit in
    ws.recv until --timeout, which the live harness reported as a 600s hang.
    """
    backend = cli_backend
    workspace = backend.root / "ws-exit-plan"
    workspace.mkdir()

    def aux(record: dict[str, Any]) -> Text:
        dumped = json.dumps(record.get("messages", []), ensure_ascii=False)
        if "Verify each pending subtask" in dumped:
            return Text(json.dumps({"results": [
                {"id": "s1", "completed": True, "evidence": "plan proposed"}]}))
        return Text(json.dumps({
            "goal": "创建 greet.py",
            "subtasks": [{"id": "s1", "title": "写 greet.py",
                          "verification": "greet.py 存在且可运行"}],
        }, ensure_ascii=False))

    backend.fake._aux = aux
    observed = _run_cli_observed(
        backend.env, "run",
        "-p", "第一阶段：只做计划，创建 greet.py，定义 greet(name)。",
        "--workspace", str(workspace),
        "--model", "fake-model",
        "--permission-mode", "plan",
        "--output-format", "stream-json",
    )
    kinds = [e.get("event") for e in observed.events if e.get("type") == "agent_event"]
    assert "run.plan.proposed" in kinds, f"events={kinds} stderr={observed.stderr[-1500:]}"
    assert "run.cancelled" in kinds, f"the parked run was never cancelled: {kinds}"
    assert "run.completed" not in kinds, "plan phase must not execute the task"

    assert observed.completion_kind == "run.plan.proposed"
    assert observed.returncode == 3, (
        f"exit={observed.returncode} stderr={observed.stderr[-2000:]}"
    )
    assert observed.exit_after_completion is not None
    assert observed.exit_after_completion <= _EXIT_BUDGET_SECONDS
    summary = [e for e in observed.events if e.get("type") == "summary"][-1]
    assert summary["result"] == "cancelled"
    assert summary["stop_reason"] == "plan_needs_approval"
    assert summary["plan_denied"] is True
