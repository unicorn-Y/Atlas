from __future__ import annotations

from decimal import Decimal

import pytest

from atlas.usage import RunUsageBudget, UsageLedger, aggregate_run_usage
from atlas.usage_pricing import estimate_cost
from atlas.tools.output_limits import (
    _reset_tool_output_limits_cache,
    get_tool_output_limits,
)
from atlas.tools.output_truncate import truncate_head_tail


def test_price_calculation_supports_cached_and_custom_rates() -> None:
    assert estimate_cost("claude-sonnet-4", input_tokens=1_000_000,
                         output_tokens=0, cached_input_tokens=100_000) == Decimal("2.73")
    assert estimate_cost("gateway/private", input_tokens=10, output_tokens=2,
                         price={"input": 1, "output": 2, "cached_input": 0.5}) == Decimal("0.000014")
    assert estimate_cost("unknown", input_tokens=1, output_tokens=1) is None


def test_run_usage_budget_reserves_by_request_and_writes_safe_deduplicated_audit(tmp_path) -> None:
    audit_path = tmp_path / "usage.jsonl"
    budget = RunUsageBudget(100, str(audit_path), budget_id="scene-08")
    assert budget.reserve("request-1", 70)
    assert not budget.reserve("request-2", 40)
    row = {
        "request_id": "request-1", "purpose": "conversation", "model": "selected-id",
        "wire_model": "bare-model", "request_count": 1, "usage_available": True,
        "input_tokens": 80, "uncached_input_tokens": 70, "cached_input_tokens": 10,
        "cache_write_tokens": 0, "output_tokens": 20, "context_tokens": 80,
        "messages": "must not persist", "api_key": "must not persist",
    }
    assert budget.record(row)
    assert budget.used == 80 and budget.reserved == 0
    assert budget.record(row)
    import json

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert records == [{key: value for key, value in row.items()
                        if key not in {"messages", "api_key"}} | {
                            "estimated_input_tokens": 70,
                            "budget_input_tokens": 80,
                            "budget_usage_unknown": False,
                            "budget_id": "scene-08",
                        }]


def test_run_usage_budget_release_audits_unknown_usage_fail_closed(tmp_path) -> None:
    import json

    audit_path = tmp_path / "unknown-usage.jsonl"
    budget = RunUsageBudget(100, str(audit_path), budget_id="scene-12")
    assert budget.reserve(
        "request-missing-usage", 37, purpose="compression",
        model="summary-id", wire_model="summary-wire",
    )
    budget.release("request-missing-usage")
    assert budget.used == 37 and budget.reserved == 0 and budget.usage_unknown
    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [{
        "request_id": "request-missing-usage", "purpose": "compression",
        "model": "summary-id", "wire_model": "summary-wire", "request_count": 1,
        "usage_available": False, "input_tokens": None,
        "estimated_input_tokens": 37, "budget_input_tokens": 37,
        "budget_usage_unknown": True, "budget_id": "scene-12",
    }]
    assert not budget.reserve("next", 1)


def test_run_usage_aggregation_deduplicates_and_keeps_primary_context_window() -> None:
    def row(request_id, purpose, inputs, context, **extra):
        return {
            "request_id": request_id, "purpose": purpose,
            "input_tokens": inputs, "uncached_input_tokens": inputs,
            "output_tokens": 5, "cached_input_tokens": 0,
            "cache_write_tokens": 0, "request_count": 1,
            "context_tokens": context, "usage_available": True,
            "model": f"selected-{purpose}", **extra,
        }

    totals = aggregate_run_usage([
        row("main-1", "conversation", 100, 400),
        row("title-1", "title", 10, 8),
        row("child-1", "subagent", 20, 90),
        row("main-2", "conversation", 200, 350),
        row("main-1", "conversation", 100, 400, context_limit=64000),
    ])
    assert totals["input_tokens"] == 330
    assert totals["output_tokens"] == 20
    assert totals["request_count"] == 4
    assert totals["context_tokens"] == 350
    assert totals["context_limit"] == 64000
    assert totals["model"] == "selected-conversation"
    assert totals["purpose_totals"]["subagent"]["input_tokens"] == 20
    assert totals["purpose_totals"]["title"]["request_count"] == 1


def test_run_usage_aggregation_marks_missing_usage_unknown() -> None:
    totals = aggregate_run_usage([
        {"request_id": "known", "purpose": "conversation", "usage_available": True,
         "input_tokens": 20, "uncached_input_tokens": 20, "output_tokens": 4,
         "cached_input_tokens": 0, "cache_write_tokens": 0, "request_count": 1,
         "context_tokens": 120},
        {"request_id": "unknown", "purpose": "compression", "usage_available": False,
         "input_tokens": 0, "uncached_input_tokens": 0, "output_tokens": 0,
         "cached_input_tokens": 0, "cache_write_tokens": 0, "request_count": 1,
         "context_tokens": 0},
    ])
    assert totals["usage_available"] is False
    assert totals["input_tokens"] is None
    assert totals["request_count"] == 2


def test_output_limits_and_head_tail_truncation(monkeypatch) -> None:
    from atlas.tools import output_limits

    monkeypatch.setattr(output_limits, "get_config", lambda: {
        "tool_output": {"max_bytes": 30, "max_lines": 5, "max_line_length": 12},
    })
    _reset_tool_output_limits_cache()
    assert get_tool_output_limits() == {
        "max_bytes": 30, "max_lines": 5, "max_line_length": 12,
    }
    result = truncate_head_tail("0123456789" * 10, 20, label="TOOL")
    assert result.startswith("01234567")
    assert result.endswith("23456789")
    assert "TRUNCATED" in result
    _reset_tool_output_limits_cache()


@pytest.mark.asyncio
async def test_usage_groups_time_range_and_subtasks(tmp_path) -> None:
    ledger = UsageLedger(tmp_path / "usage.db")
    await ledger.init()
    common = dict(conversation_id="conv-a", model="claude-sonnet-4",
                  started_at="2026-10-01T10:00:00+00:00",
                  usage={"input_tokens": 100, "output_tokens": 20,
                         "cached_input_tokens": 25})
    await ledger.record(run_id="run-a", subtask_id=None, **common)
    await ledger.record(run_id="run-a", subtask_id="child-a", **common)
    await ledger.record(run_id="run-old", subtask_id=None,
                        **{**common, "started_at": "2026-09-30T10:00:00+00:00"})
    result = await ledger.query(start="2026-10-01", end="2026-10-02", group_by="conversation")
    assert result["rows"][0]["runs"] == 2
    assert result["rows"][0]["input_tokens"] == 200
    assert result["rows"][0]["cache_hit_rate"] == 0.25
    assert result["totals"]["runs"] == 2
    await ledger.close()
