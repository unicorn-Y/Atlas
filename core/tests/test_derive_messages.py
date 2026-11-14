"""Model history must be reconstructable from the append-only event log.

The ledger's E1/S1 wants DSH's property: the session log is the source of truth
and history is derived from it. Atlas keeps history in mutable `messages` rows,
so the checkable question is narrower — can the log alone reproduce what the
model saw?

It can, because every `append_message` now writes a `message/append` event in the
same transaction, and compaction writes `messages.deactivated` for the rows it
hides. `compare_projection` reports the diff instead of returning a bare boolean,
so a divergence caused by an unrecorded deactivation stays visible.
"""

from __future__ import annotations

import pytest

from atlas.engine.state.derive_messages import (
    compare_projection,
    derive_messages,
)

pytestmark = pytest.mark.unit


def _append(message_id, role, **extra):
    return {"event_type": "message/append",
            "payload": {"message_id": message_id, "role": role, **extra}}


def test_appends_fold_in_order():
    events = [_append(1, "user"), _append(2, "assistant"), _append(3, "tool")]
    assert [m["id"] for m in derive_messages(events)] == [1, 2, 3]
    assert [m["role"] for m in derive_messages(events)] == ["user", "assistant", "tool"]


def test_deactivation_removes_the_message_without_erasing_the_append():
    events = [
        _append(1, "user"), _append(2, "assistant"),
        {"event_type": "messages.deactivated",
         "payload": {"message_ids": [1], "reason": "compaction"}},
    ]
    derived = derive_messages(events)
    assert [m["id"] for m in derived] == [2]
    # The append is still in the log: deactivation supersedes, it does not rewrite.
    assert sum(1 for e in events if e["event_type"] == "message/append") == 2


def test_compare_projection_matches_when_the_log_is_complete():
    events = [_append(1, "user"), _append(2, "assistant")]
    legacy = [{"_row_id": 1}, {"_row_id": 2}]
    result = compare_projection(events, legacy)
    assert result["match"] is True
    assert result["differences"] == []


def test_compare_projection_reports_a_missing_append():
    events = [_append(1, "user")]
    legacy = [{"_row_id": 1}, {"_row_id": 2}]
    result = compare_projection(events, legacy)
    assert result["match"] is False
    assert result["differences"][0]["legacy_id"] == "2"
    assert "missing from the log" in result["differences"][0]["reason"]


def test_compare_projection_reports_a_deactivation_the_rows_disagree_with():
    events = [_append(1, "user"), _append(2, "assistant"),
              {"event_type": "messages.deactivated", "payload": {"message_ids": [1]}}]
    legacy = [{"_row_id": 1}, {"_row_id": 2}]
    result = compare_projection(events, legacy)
    assert result["match"] is False, "a row the log deactivated must not match"
    # Index 0 is where they diverge: the log says 2, the live rows still say 1.
    assert result["differences"][0] == {
        "index": 0, "derived_id": "2", "legacy_id": "1",
        "reason": "order or identity differs",
    }


def test_unknown_event_types_are_ignored():
    events = [_append(1, "user"),
              {"event_type": "turn/start", "payload": {}},
              {"event_type": "workspace/changes", "payload": {}}]
    assert len(derive_messages(events)) == 1
