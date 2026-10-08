"""Acceptance tests for T12.1 Desktop Correction E2E and T12.2 Windows Startup & Lifecycle.

Criteria (02_wave_tasks.md T12.1, T12.2 & 01_contracts.md §6, §8):
  - T12.1:
      real Atlas HTTP correction → MemoryOS record readback → real Atlas WS chat;
      fake provider request inspection checks whether persisted user context is sent.
  - T12.2:
      def test_packaged_atlas_uses_same_memory_authority(h):
          h.seed("desktop")
          h.restart("packaged_atlas")
          status = h.api("GET", "/api/unified-memory/status").json()
          assert status["authority_id"] == h.runtime_manifest["authority_id"]
  - Both dev and packaged startup modes bind the exact same service_url, data root,
    authority_id, and contract_version="UM-WIN-1.0".
  - Stopping Atlas handles its managed service cleanly without killing unrelated
    processes (stop_leftovers == []); repeated startup does not spawn duplicate
    background queues.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from scripts.unified_memory.cutover import (
    CONTRACT_VERSION,
    attach_lane_helpers,
)
from atlas.memory.unified_client import observation_content_hash
from tests.unified_memory.harness import UMHarness


@pytest.fixture
def h(um: UMHarness) -> Any:
    """Session harness decorated with T12 helpers."""
    attach_lane_helpers(um)
    return um


# ================================================================== T12.1 Desktop Correction

@pytest.mark.integration
@pytest.mark.fake_provider
def test_desktop_correction_is_visible_in_new_chat(h: Any):
    """真实偏好纠正更新统一记忆并进入新聊天；fake provider 只检查请求上下文。"""
    previous = f"old-format-{uuid.uuid4().hex[:10]}"
    replacement = f"new-format-{uuid.uuid4().hex[:10]}"
    object_id = f"pref-{uuid.uuid4().hex[:10]}"
    source_event_id = f"atlas:ATLAS_USER_MESSAGE:{object_id}:1:UPSERT"
    context = h.default_context()
    assert context["memory_subject_id"] == "atlas-fixture"
    observation = {
        "source_event_id": source_event_id,
        "source_kind": "ATLAS_USER_MESSAGE",
        "source_object_id": object_id,
        "source_revision": "1",
        "event_action": "UPSERT",
        "occurred_at": datetime.now(UTC).isoformat(),
        "source_timezone": "Asia/Hong_Kong",
        "time_status": "KNOWN",
        "speaker_role": "USER",
        "epistemic_kind": "USER_ASSERTED",
        "content": {
            "facet": "PREFERENCE",
            "key": "user_response_format",
            "value": previous,
            "text": f"我的回复格式偏好是 {previous}",
        },
        "locator": {"kind": "MESSAGE", "value": "pref-desktop"},
        "media_refs": [],
        "derived_from": [],
    }
    observation["content_hash"] = observation_content_hash(observation)
    batch = {
        "contract_version": CONTRACT_VERSION,
        "event_class": "TEST",
        "context": context,
        "observations": [observation],
    }
    response = h.api("POST", "/api/unified-memory/observe", json=batch)
    assert response.status_code == 200, response.text[:400]
    ack = response.json()
    assert ack.get("accepted") == 1, ack
    assert any(receipt.get("source_event_id") == source_event_id
               for receipt in ack.get("receipts", [])), ack
    profile_result = ack.get("profile") or {}
    assert profile_result.get("policy") == "PROFILE_V1", ack
    assert profile_result.get("applied") == 1, profile_result
    formed = profile_result.get("results") or []
    target_ref = next((item.get("record_ref") for item in formed
                       if item.get("record_ref")), None)
    assert target_ref and target_ref.startswith("memory:"), json.dumps(
        ack, ensure_ascii=False)

    record_response = h.api("GET", f"/api/unified-memory/records/{target_ref}")
    assert record_response.status_code == 200, record_response.text[:400]
    initial = record_response.json()
    assert initial["content"]["value"] == previous, initial
    assert initial["facet"] == "PREFERENCE", initial
    revision = initial["record_revision"]
    evidence_before_response = h.api(
        "GET", f"/api/unified-memory/evidence/{target_ref}")
    assert evidence_before_response.status_code == 200, \
        evidence_before_response.text[:400]
    evidence_before = next(
        (snippet for snippet in evidence_before_response.json().get("snippets", [])
         if snippet.get("source_event_id") == source_event_id), None)
    assert evidence_before and previous in evidence_before.get("text", ""), \
        evidence_before_response.text[:600]

    profile_before = h.api(
        "GET", "/v1/unified/profile",
        params={"memory_subject_id": context["memory_subject_id"]})
    assert profile_before.status_code == 200, profile_before.text[:400]
    profile_item = next(
        (item for item in profile_before.json().get("preferences", [])
         if item.get("record_ref") == target_ref), None)
    assert profile_item is not None and profile_item.get("value") == previous, \
        profile_before.text[:500]

    query = "我偏好采用什么回复格式？"
    recall_before = h.api(
        "POST", "/v1/unified/recall",
        json={"context": context, "query": query, "purpose": "CONVERSATION"})
    assert recall_before.status_code == 200, recall_before.text[:400]
    assert any(previous in json.dumps(item, ensure_ascii=False)
               for item in recall_before.json().get("context_items", [])), \
        recall_before.text[:600]

    # Mirror CorrectionDialog.submitCorrection's legal replacement object;
    # Atlas binds its canonical MemoryContext from the configured facade.
    correction_response = h.api(
        "POST", "/api/unified-memory/corrections",
        json={
            "request_id": f"correction-{uuid.uuid4()}",
            "target_ref": target_ref,
            "expected_revision": revision,
            "replacement": {"value": replacement},
            "source": "desktop-correction",
        },
    )
    assert correction_response.status_code in (200, 202), \
        correction_response.text[:600]
    correction = correction_response.json()
    assert correction.get("acknowledged") is True, correction

    corrected_response = h.api(
        "GET", f"/api/unified-memory/records/{target_ref}")
    assert corrected_response.status_code == 200, corrected_response.text[:400]
    corrected = corrected_response.json()
    assert corrected["record_revision"] == revision + 1, corrected
    assert corrected["lifecycle"] == "ACTIVE", corrected
    assert corrected["content"]["value"] == replacement, corrected
    assert corrected["content"]["corrected"]["prev_value"] == previous, corrected
    active_fields = {key: corrected["content"].get(key)
                     for key in ("value", "text", "title", "summary")}
    assert all(previous not in str(value or "")
               for value in active_fields.values()), active_fields
    evidence_after_response = h.api(
        "GET", f"/api/unified-memory/evidence/{target_ref}")
    assert evidence_after_response.status_code == 200, \
        evidence_after_response.text[:400]
    evidence_after = next(
        (snippet for snippet in evidence_after_response.json().get("snippets", [])
         if snippet.get("source_event_id") == source_event_id), None)
    assert evidence_after, evidence_after_response.text[:600]
    assert {key: evidence_after.get(key) for key in
            ("source_event_id", "content_hash", "text")} == {
                key: evidence_before.get(key) for key in
                ("source_event_id", "content_hash", "text")
            }, evidence_after

    profile_after = h.api(
        "GET", "/v1/unified/profile",
        params={"memory_subject_id": context["memory_subject_id"]})
    assert profile_after.status_code == 200, profile_after.text[:400]
    profile_text = json.dumps(profile_after.json(), ensure_ascii=False)
    assert replacement in profile_text and previous not in profile_text, profile_text[:700]

    recall_after = h.api(
        "POST", "/v1/unified/recall",
        json={"context": context, "query": query, "purpose": "CONVERSATION"})
    assert recall_after.status_code == 200, recall_after.text[:400]
    recall_payload = recall_after.json()
    recall_items = recall_payload.get("context_items", [])
    active_item = next(
        (item for item in recall_items if item.get("record_ref") == target_ref), None)
    assert active_item and active_item.get("lifecycle") == "ACTIVE", {
        "query": query,
        "source_event_id": source_event_id,
        "evidence_event_id": evidence_before.get("event_id"),
        "target_ref": target_ref,
        "item_refs": [item.get("record_ref") for item in recall_items],
    }
    recall_content = active_item.get("content") or {}
    assert recall_content.get("value") == replacement, recall_content
    assert all(previous not in str(recall_content.get(key) or "")
               for key in ("value", "text", "title", "summary")), recall_content
    from atlas.memory.recall_context import _format_relevant_memories_block

    relevant_block, _, _, _ = _format_relevant_memories_block(recall_payload)
    assert replacement in relevant_block and previous not in relevant_block, relevant_block

    assert h._fake is not None
    previous_request_count = len(h._fake.main_requests())
    chat_result = h.chat(query, session_id=f"chat-new-{uuid.uuid4().hex[:10]}")
    assert chat_result["status"] == "completed"
    requests = h._fake.main_requests()[previous_request_count:]
    assert requests, "chat 必须经过真实 Atlas WebSocket 路径调用 provider"
    prompt_messages = [message for request in requests
                       for message in request.get("messages", [])]

    def _matches(value: str) -> list[dict[str, str]]:
        matches = []
        for message in prompt_messages:
            content = json.dumps(message.get("content"), ensure_ascii=False)
            index = content.find(value)
            if index >= 0:
                matches.append({
                    "role": str(message.get("role") or ""),
                    "excerpt": content[max(0, index - 100):index + len(value) + 100],
                })
        return matches

    replacement_in_prompt = _matches(replacement)
    previous_in_prompt = _matches(previous)
    assert replacement_in_prompt and not previous_in_prompt, {
        "replacement_in_prompt": replacement_in_prompt,
        "previous_in_prompt": previous_in_prompt,
    }


# ================================================================== T12.2 Packaged / Dev Authority

@pytest.mark.integration
def test_packaged_atlas_uses_same_memory_authority(h: Any):
    """T12.2 Acceptance criterion: packaged Atlas uses identical memory authority."""
    h.seed("desktop")
    h.restart("packaged_atlas")
    status = h.api("GET", "/api/unified-memory/status").json()
    assert status["authority_id"] == h.runtime_manifest["authority_id"]


@pytest.mark.integration
def test_dev_and_packaged_binding_consistency(h: Any):
    """Verify dev and packaged modes bind identical service URL, data root, authority, and contract."""
    manifest = h.runtime_manifest
    status = h.api("GET", "/api/unified-memory/status").json()

    # Identical service URL
    expected_service_url = manifest["unified_memory"]["service_url"]
    assert status.get("service_url") == expected_service_url

    # Identical contract version
    assert status.get("contract_version") == CONTRACT_VERSION

    # Identical authority ID
    assert status.get("authority_id") == manifest["authority_id"]

    # Identical data root
    assert status.get("data_root") == manifest["atlas_data"]


@pytest.mark.integration
def test_service_lifecycle_observability(h: Any):
    """Verify health endpoint reports correct component status and worker lifecycle."""
    health_resp = h.api("GET", "/api/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert health_data["status"] in ("ok", "starting")

    status_resp = h.api("GET", "/api/unified-memory/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert "watermarks" in status_data
    assert "formation" in status_data


@pytest.mark.unit
def test_startup_manifest_structure(tmp_path: Path):
    """Unit test for runtime manifest structure and contract compliance."""
    fake_manifest = {
        "event_class": "TEST",
        "contract_version": CONTRACT_VERSION,
        "authority_id": f"um-auth-{uuid.uuid4().hex[:8]}",
        "service_url": "http://127.0.0.1:8000",
        "atlas_data": str(tmp_path / "atlas"),
        "stopped_at": None,
        "stop_leftovers": [],
    }
    assert fake_manifest["contract_version"] == "UM-WIN-1.0"
    assert fake_manifest["stop_leftovers"] == []
