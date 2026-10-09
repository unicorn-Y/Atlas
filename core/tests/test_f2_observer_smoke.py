from __future__ import annotations

import pytest

from scripts.f2_observer_smoke import (
    _matching_evidence_snippet,
    _stored_observation_text,
)


def test_smoke_reads_full_text_from_record_and_keeps_truncated_evidence_as_provenance() -> None:
    expected = "🔴 用户的女儿今年6岁。"
    record = {
        "record_ref": "episode:ev-test",
        "content": {"text": {"text": expected, "facet": "FACT"}},
    }
    truncated_snippet = {
        "source_event_id": "atlas:DERIVED:test:1:UPSERT",
        "text": '{"text":"🔴 用户的女儿今',
        "truncated": True,
    }

    assert _stored_observation_text(record) == expected
    assert _matching_evidence_snippet(
        {"snippets": [truncated_snippet]}, "atlas:DERIVED:test:1:UPSERT",
    ) is truncated_snippet


def test_smoke_rejects_missing_or_ambiguous_evidence_provenance() -> None:
    snippet = {"source_event_id": "atlas:DERIVED:test:1:UPSERT", "text": "{}"}

    with pytest.raises(RuntimeError, match="did not return the submitted"):
        _matching_evidence_snippet({"snippets": []}, "atlas:DERIVED:test:1:UPSERT")
    with pytest.raises(RuntimeError, match="did not return the submitted"):
        _matching_evidence_snippet(
            {"snippets": [snippet, dict(snippet)]}, "atlas:DERIVED:test:1:UPSERT",
        )
