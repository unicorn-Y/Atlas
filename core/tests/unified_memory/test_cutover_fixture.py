from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scripts.unified_memory.cutover import fixture_desktop_correct_preference


@dataclass
class _Response:
    status_code: int
    payload: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self.payload


class _Harness:
    def __init__(self, post_payload: dict[str, Any], record_payload: dict[str, Any] | None = None):
        self.post_payload = post_payload
        self.record_payload = record_payload
        self.source_event_id: str | None = None
        self.get_paths: list[str] = []

    def default_context(self) -> dict[str, Any]:
        return {
            "memory_subject_id": "test-subject",
            "owner_id": "test-owner",
            "runtime_session_id": "test-session",
        }

    def api(self, method: str, path: str, **kwargs: Any) -> _Response:
        if method == "POST" and path == "/api/unified-memory/observe":
            self.source_event_id = kwargs["json"]["observations"][0]["source_event_id"]
            return _Response(201, self.post_payload(self.source_event_id))
        if method == "GET":
            self.get_paths.append(path)
            return _Response(200 if self.record_payload is not None else 404,
                             self.record_payload or {})
        raise AssertionError(f"unexpected harness request: {method} {path}")


def _ack(source_event_id: str, record_ref: str | None) -> dict[str, Any]:
    formation = {"admitted": 0, "results": []}
    if record_ref:
        formation = {
            "admitted": 1,
            "results": [{
                "source_event_id": source_event_id,
                "record_ref": record_ref,
                "result": "CREATED",
                "created": True,
            }],
        }
    return {
        "accepted": 1,
        "created": 1,
        "duplicates": 0,
        "receipts": [{"source_event_id": source_event_id}],
        "formation": formation,
    }


def test_cutover_fixture_requires_accepted_source_and_readable_replacement() -> None:
    record_ref = "memory:formed-preference"
    harness = _Harness(
        post_payload=lambda source: _ack(source, record_ref),
        record_payload={
            "record_ref": record_ref,
            "record_revision": 1,
            "lifecycle": "ACTIVE",
            "facet": "PREFERENCE",
            "content": {"key": "user_response_format", "value": "简短中文"},
        },
    )

    result = fixture_desktop_correct_preference(harness, {"replacement": "简短中文"})

    assert result["status"] == "CORRECTED"
    assert result["applied"] is True
    assert result["persisted"] is True
    assert result["persistence_status"] == "PERSISTED"
    assert harness.get_paths == [f"/api/unified-memory/records/{record_ref}"]


def test_cutover_fixture_does_not_call_a_source_ack_a_correction() -> None:
    harness = _Harness(
        post_payload=lambda source: _ack(source, record_ref=None),
        record_payload=None,
    )

    result = fixture_desktop_correct_preference(harness, {"replacement": "简短中文"})

    assert result["status"] == "NOT_VERIFIED"
    assert result["applied"] is False
    assert result["persisted"] is True
    assert result["persistence_status"] == "PERSISTED"
    assert harness.get_paths == []


def test_cutover_fixture_reports_unverified_when_readback_differs() -> None:
    record_ref = "memory:formed-preference"
    harness = _Harness(
        post_payload=lambda source: _ack(source, record_ref),
        record_payload={
            "record_ref": record_ref,
            "record_revision": 1,
            "lifecycle": "ACTIVE",
            "facet": "PREFERENCE",
            "content": {"key": "user_response_format", "value": "旧格式"},
        },
    )

    result = fixture_desktop_correct_preference(harness, {"replacement": "简短中文"})

    assert result["status"] == "NOT_VERIFIED"
    assert result["applied"] is False
    assert result["persisted"] is True


def test_cutover_fixture_does_not_claim_persistence_without_matching_source_receipt() -> None:
    harness = _Harness(
        post_payload=lambda _source: {
            "accepted": 1,
            "created": 1,
            "duplicates": 0,
            "receipts": [{"source_event_id": "other-event"}],
            "formation": {"admitted": 0, "results": []},
        },
        record_payload=None,
    )

    result = fixture_desktop_correct_preference(harness, {"replacement": "简短中文"})

    assert result["status"] == "NOT_VERIFIED"
    assert result["applied"] is False
    assert result["persisted"] is False
    assert result["persistence_status"] == "NOT_PERSISTED"
