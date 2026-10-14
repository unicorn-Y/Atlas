from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "diag" / "context_stats.py"
SPEC = importlib.util.spec_from_file_location("atlas_context_stats", SCRIPT)
assert SPEC and SPEC.loader
context_stats = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = context_stats
SPEC.loader.exec_module(context_stats)


def test_context_stats_aggregates_requests_compactions_handoffs_and_errors():
    events = [
        {
            "event": "model_request",
            "purpose": "conversation",
            "input_tokens": 100,
            "cached_tokens": 70,
        },
        {
            "event": "model_request",
            "purpose": "compaction",
            "input_tokens": 200,
            "cached_tokens": 100,
        },
        {
            "event": "model_request",
            "purpose": "conversation",
            "input_tokens": 300,
            "cached_tokens": 150,
        },
        {
            "event": "compaction",
            "method": "prune",
            "before_tokens": 1000,
            "after_tokens": 500,
            "ineffective_streak": 0,
        },
        {
            "event": "compaction",
            "method": "guard_rejected",
            "before_tokens": 800,
            "after_tokens": 800,
            "ineffective_streak": 1,
        },
        {"event": "handoff", "accepted": True},
        {"event": "handoff", "accepted": False},
        {"event": "model_error", "category": "rate_limit"},
        {"event": "model_error", "category": "rate_limit"},
        {"event": "model_error", "category": "connection"},
    ]
    result = context_stats.summarize(events)
    assert result["primary_request_count"] == 2
    assert result["primary_input_tokens"] == {"count": 2, "median": 200, "p75": 250}
    assert result["cache_hit_by_purpose"]["conversation"]["hit_rate"] == pytest.approx(0.55)
    assert result["compactions_by_method"]["prune"]["average_compression_ratio"] == pytest.approx(
        0.5
    )
    assert result["ineffective_compactions"] == 1
    assert result["quality_guard_rejections"] == 1
    assert result["handoffs"]["acceptance_rate"] == pytest.approx(0.5)
    assert result["model_error_top_reasons"] == [("rate_limit", 2), ("connection", 1)]


def test_read_events_skips_malformed_lines(tmp_path: Path):
    path = tmp_path / "run.jsonl"
    path.write_text('{"event":"model_error"}\nnot json\n[]\n', encoding="utf-8")
    assert context_stats.read_events([path]) == [{"event": "model_error"}]


@pytest.mark.asyncio
async def test_model_attempt_failure_includes_exception_text_and_status(monkeypatch):
    from atlas.models import tokens

    monkeypatch.setattr(tokens, "estimate_tokens", lambda *_args, **_kwargs: 1)
    auxiliary = ModuleType("agent.auxiliary_client")

    def fail(**_kwargs):
        raise RuntimeError("upstream exploded")

    auxiliary.call_llm = fail
    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", auxiliary)
    route = SimpleNamespace(
        provider="example",
        wire_model="wire-model",
        model="wire-model",
        key="",
        base_url="http://isolated.invalid",
        api_mode="chat_completions",
        model_id="test",
    )
    agent = SimpleNamespace(_model_router=SimpleNamespace(resolve=AsyncMock(return_value=route)))
    attempts = []
    from atlas.kernel.model_call import complete_stream

    with pytest.raises(Exception):
        await complete_stream(
            agent,
            "test",
            [],
            [],
            max_retries=0,
            unbounded_connection_retries=False,
            on_attempt=attempts.append,
        )
    assert len(attempts) == 1
    assert attempts[0]["error"] == "RuntimeError: upstream exploded"
    assert "status_code" in attempts[0]


def test_cli_reads_date_directory_and_prints_summary(tmp_path: Path, capsys, monkeypatch):
    date_dir = tmp_path / "2026-10-15"
    date_dir.mkdir()
    (date_dir / "r.jsonl").write_text(
        json.dumps(
            {
                "event": "model_request",
                "purpose": "conversation",
                "input_tokens": 100,
                "cached_tokens": 80,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--date", "2026-10-15", "--runs-dir", str(tmp_path)]
    )
    assert context_stats.main() == 0
    assert "Primary requests: 1" in capsys.readouterr().out
