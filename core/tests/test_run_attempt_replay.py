"""Failed provider attempts survive durable log reload through the replay API."""

import pytest

from atlas import logs
from atlas.run_replay import load_run, replay

pytestmark = pytest.mark.unit


def test_failed_attempt_survives_success_and_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "LOG_DIR", tmp_path)
    run_id = "attempt-replay-w3"
    logs.append_run_event(run_id, "run_start", session_id="session-a", model="model-a")
    logs.append_run_event(run_id, "model_error", purpose="conversation", attempt=1,
                          category="rate_limit", status=429, retry=True,
                          retry_number=1, retry_delay_s=0.5, detail="retry observed")
    logs.append_run_event(run_id, "model_request", purpose="conversation", attempt=2,
                          duration_ms=12, input_tokens=3, output_tokens=4)
    logs.append_run_event(run_id, "run_end", status="completed")
    run = load_run(run_id, runs_dir=tmp_path / "runs")
    assert len(run.errors) == 1
    assert run.errors[0]["attempt"] == 1
    assert run.errors[0]["status"] == 429
    assert run.errors[0]["retry"] is True
    assert run.model_calls[0].attempt == 2
    assert any(item.is_error for item in replay(run))
    assert load_run(run_id, runs_dir=tmp_path / "runs").errors == run.errors
