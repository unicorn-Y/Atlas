"""Fake stream checks for live orchestration; these make no model requests."""

import json
import subprocess
import sys
import threading

import pytest

from tests.test_live_full_run_server import (
    _finish_observed_process,
    _observe_run_line,
    _pump_stderr,
)
from tests.test_live_model_smoke import _remaining_live_input_budget

pytestmark = pytest.mark.unit


def test_steer_observes_tool_after_run_id_was_already_received():
    state = {}
    started = threading.Event()
    _observe_run_line(json.dumps({"event": "run.started", "run_id": "run-1"}), state, started)
    assert state == {"run_id": "run-1"}
    assert not started.is_set()
    _observe_run_line(json.dumps({"event": "tool.started", "run_id": "run-1",
                                 "data": {"name": "terminal"}}), state, started)
    assert started.is_set()


def test_observed_cli_drains_both_pipes_without_losing_events():
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stderr.write('x'*131072); "
         "print('first'); print('second')"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    stdout = []
    stderr, stderr_thread = _pump_stderr(process)
    stdout_thread = threading.Thread(target=lambda: stdout.extend(process.stdout), daemon=True)
    stdout_thread.start()
    try:
        assert _finish_observed_process(process, stdout_thread, stderr_thread, 10) == 0
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
