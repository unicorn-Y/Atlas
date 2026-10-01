from __future__ import annotations

from decimal import Decimal

import pytest

from atlas.usage import UsageLedger
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
