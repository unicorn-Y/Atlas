"""Fake stream checks for live orchestration; these make no model requests."""

import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.test_live_full_run_server import (
    Backend,
    _finish_observed_process,
    _fixture,
    _observe_run_line,
    _pump_stderr,
)
from tests.test_live_model_smoke import _remaining_live_input_budget

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("script", "expected_code"),
    [
        ('print("你好，Atlas！")', 0),
        ("print(chr(0xfffd))", 1),
        ("import sys; sys.stdout.write('错误'+chr(0xfffd)); "
         "sys.stderr.write('后台错误'+chr(0xfffd)); sys.exit(3)", 1),
    ],
)
def test_plan_scenario_checker_handles_gbk_child_and_diagnostic_output(
    tmp_path, script, expected_code,
):
    """The 08 fixture checker stays useful under the Windows GBK console encoding."""
    (tmp_path / "greet.py").write_text(script + "\n", encoding="utf-8")
    fixture = _fixture("08-plan-execute")
    env = {**os.environ, "PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0"}
    proc = subprocess.run(
        [sys.executable, str(fixture / "check.py"), str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, cwd=str(fixture), env=env,
    )

    assert proc.returncode == expected_code
    if expected_code == 0:
        assert proc.stdout.strip() == "CHECK-OK"
    else:
        assert "CHECK-FAIL" in proc.stdout
        assert r"\ufffd" in proc.stdout
        assert "UnicodeEncodeError" not in proc.stderr
        if "sys.exit(3)" in script:
            assert "rc=3" in proc.stdout


def test_live_backend_waits_for_ready_health_body(tmp_path, monkeypatch):
    import httpx

    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    statuses = iter(("starting", "ok"))
    probe = Mock(side_effect=lambda *_args, **_kwargs: SimpleNamespace(
        status_code=200, json=lambda: {"status": next(statuses)},
    ))
    monkeypatch.setattr(httpx, "get", probe)
    monkeypatch.setattr("tests.test_live_full_run_server.time.sleep", lambda _seconds: None)
    backend = Backend(SimpleNamespace(evidence=tmp_path, child_env=lambda: {}))
    try:
        backend.start()
        assert probe.call_count == 2
    finally:
        backend.stop()
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=30)


def test_steer_observes_tool_after_run_id_was_already_received():
    state = {}
    started = threading.Event()
    _observe_run_line(json.dumps({"event": "run.started", "run_id": "run-1"}), state, started)
    assert state == {"run_id": "run-1"}
    assert not started.is_set()
    _observe_run_line(json.dumps({"event": "tool.started", "run_id": "run-1",
                                 "data": {"name": "terminal"}}), state, started)
    assert started.is_set()


def test_steer_observer_flags_a_finished_run_so_the_steer_refuses_to_fire():
    state = {}
    started = threading.Event()
    finished = threading.Event()
    for event in ("run.started", "tool.started", "run.completed"):
        line = json.dumps({"event": event, "run_id": "run-1", "data": {}})
        _observe_run_line(line, state, started, finished)
    assert state == {"run_id": "run-1"}
    assert started.is_set() and finished.is_set()


def test_observed_cli_drains_both_pipes_without_losing_events():
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stderr.write('x'*131072); "
         "print('first'); print('second')"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    stdout = []
    stderr, stderr_thread = _pump_stderr(process)
    stdout_thread = threading.Thread(target=lambda: stdout.extend(process.stdout), daemon=True)
    stdout_thread.start()
    try:
        assert _finish_observed_process(process, stdout_thread, stderr_thread, 10) == (0, False)
        assert stdout == ["first\n", "second\n"]
        assert len("".join(stderr)) == 131072
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def test_steer_ignores_tool_completion_and_unrelated_stream_lines():
    state = {}
    started = threading.Event()
    for line in ("log message", "null", json.dumps({"event": "tool_end", "data": {"name": "terminal"}})):
        _observe_run_line(line, state, started)
    assert not started.is_set()


def test_live_budget_counts_prior_steps_retries_and_cached_prompt_tokens(tmp_path):
    (tmp_path / "05.jsonl").write_text(
        "\n".join(json.dumps(row) for row in [
            {"request_id": "main", "input_tokens": 100_000, "cached_input_tokens": 90_000},
            {"request_id": "child", "input_tokens": 120_000},
            {"request_id": "title", "input_tokens": 30_000},
            {"request_id": "main", "input_tokens": 100_000},
        ]), encoding="utf-8",
    )
    (tmp_path / "01.jsonl").write_text(
        json.dumps({"request_id": "previous-scene", "input_tokens": 400_000}), encoding="utf-8",
    )
    assert _remaining_live_input_budget(tmp_path, "05") == 250_000


def test_live_budget_stops_before_launch_when_total_or_scene_is_exhausted(tmp_path):
    for index in range(6):
        (tmp_path / f"{index:02}.jsonl").write_text(
            json.dumps({"request_id": str(index), "input_tokens": 500_000}), encoding="utf-8",
        )
    with pytest.raises(AssertionError, match="budget exhausted"):
        _remaining_live_input_budget(tmp_path, "12")
    with pytest.raises(AssertionError, match="budget exhausted"):
        _remaining_live_input_budget(tmp_path, "00")


def test_live_budget_does_not_treat_missing_provider_usage_as_free(tmp_path):
    (tmp_path / "01.jsonl").write_text(
        json.dumps({"request_id": "unknown", "input_tokens": 0, "usage_available": False,
                    "estimated_input_tokens": 10_000}), encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="omitted request usage"):
        _remaining_live_input_budget(tmp_path, "02")
