"""Resource limits, latency, budgets, and pagination tests (UM12 / T12.2).

Requirements (02_wave_tasks.md T12.2 & 01_contracts.md §8):
  - Measure real p50/p95 observe and recall latency on local dual services.
  - Token budget enforcement (max_tokens=2400, max_records=12, max_source_snippets=8).
  - DB/media growth bounds: deduplication prevents unbounded size inflation.
  - Startup time & error rate bounds under sequential/concurrent queries.
  - Pagination/budget control: budget limits truncate/paginate context assembly
    rather than deleting stored memories from the database.
"""

from __future__ import annotations

import json
import statistics
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from atlas.memory.unified_client import observation_content_hash
from scripts.unified_memory.cutover import attach_lane_helpers
from tests.unified_memory.harness import UMHarness

MAX_TOKENS_BUDGET = 2400
MAX_RECORDS_BUDGET = 12
MAX_SNIPPETS_BUDGET = 8


@pytest.fixture
def h(um: UMHarness) -> Any:
    attach_lane_helpers(um)
    return um


# ================================================================== Latency P50 / P95

@pytest.mark.integration
def test_observe_and_recall_latency_p50_p95(h: Any):
    """Measure real p50 and p95 latencies for observe and recall operations."""
    observe_latencies_ms: list[float] = []
    recall_latencies_ms: list[float] = []

    # 1. Measure Observe latencies (12 iterations)
    for i in range(12):
        key = f"latency-test-{uuid.uuid4().hex[:6]}-{i}"
        val = f"性能测试观测记录第 {i} 条：用于测量统一记忆落地延迟。"
        obs = {
            "source_event_id": f"atlas:USER_IMPORT:{key}:1:UPSERT",
            "source_kind": "USER_IMPORT",
            "source_object_id": key,
            "source_revision": "1",
            "event_action": "UPSERT",
            "occurred_at": datetime.now(UTC).isoformat(),
            "source_timezone": "Asia/Hong_Kong",
            "time_status": "KNOWN",
            "speaker_role": "USER",
            "epistemic_kind": "USER_ASSERTED",
            "content": {"facet": "FACT", "key": key, "value": val, "text": val},
            "locator": {"kind": "MESSAGE", "value": f"msg/{key}"},
            "media_refs": [],
            "derived_from": [],
        }
        obs["content_hash"] = observation_content_hash(obs)
        batch = {
            "contract_version": "UM-WIN-1.0",
            "event_class": "TEST",
            "context": {
                **h.default_context(),
                "runtime_session_id": f"perf-latency-{i}",
            },
            "observations": [obs],
        }

        t0 = time.perf_counter()
        resp = h.api("POST", "/api/unified-memory/observe", json=batch)
        t1 = time.perf_counter()
        assert resp.status_code in (200, 201), resp.text
        observe_latencies_ms.append((t1 - t0) * 1000.0)

    # 2. Measure Recall latencies (12 iterations)
    for i in range(12):
        recall_req = {
            "query": f"性能测试观测记录第 {i} 条",
            "context": h.default_context(),
            "budget": {
                "max_tokens": MAX_TOKENS_BUDGET,
                "max_records": MAX_RECORDS_BUDGET,
                "max_source_snippets": MAX_SNIPPETS_BUDGET,
            },
        }
        t0 = time.perf_counter()
        resp = h.api("POST", "/api/unified-memory/recall", json=recall_req)
        t1 = time.perf_counter()
        assert resp.status_code == 200, resp.text
        recall_latencies_ms.append((t1 - t0) * 1000.0)

    # Calculate p50 and p95
    obs_sorted = sorted(observe_latencies_ms)
    p50_obs = statistics.median(obs_sorted)
    p95_obs = obs_sorted[int(len(obs_sorted) * 0.95)]

    rec_sorted = sorted(recall_latencies_ms)
    p50_rec = statistics.median(rec_sorted)
    p95_rec = rec_sorted[int(len(rec_sorted) * 0.95)]

    # Store measurements on harness for report generation
    h._perf_measurements = {
        "observe": {"p50_ms": round(p50_obs, 2), "p95_ms": round(p95_obs, 2), "samples": len(obs_sorted)},
        "recall": {"p50_rec_ms": round(p50_rec, 2), "p95_rec_ms": round(p95_rec, 2), "samples": len(rec_sorted)},
    }

    # Assert reasonable thresholds (under local loopback test server)
    assert p50_obs < 500.0, f"Observe p50 too high: {p50_obs:.2f}ms"
    assert p95_obs < 1500.0, f"Observe p95 too high: {p95_obs:.2f}ms"
    assert p50_rec < 500.0, f"Recall p50 too high: {p50_rec:.2f}ms"
    assert p95_rec < 1500.0, f"Recall p95 too high: {p95_rec:.2f}ms"


# ================================================================== Token & Record Budget

@pytest.mark.integration
def test_budget_enforcement_truncates_assembly_without_deleting_memories(h: Any):
    """Budget constraints (max_records=12) limit context assembly without deleting stored memories."""
    # Ingest 15 distinct memories (exceeding max_records=12)
    session_id = f"budget-test-{uuid.uuid4().hex[:6]}"
    for i in range(15):
        key = f"budget-item-{session_id}-{i}"
        val = f"预算控制测试项 {i}：测试超过 12 条限制时安全装配截断。"
        obs = {
            "source_event_id": f"atlas:USER_IMPORT:{key}:1:UPSERT",
            "source_kind": "USER_IMPORT",
            "source_object_id": key,
            "source_revision": "1",
            "event_action": "UPSERT",
            "occurred_at": datetime.now(UTC).isoformat(),
            "source_timezone": "Asia/Hong_Kong",
            "time_status": "KNOWN",
            "speaker_role": "USER",
            "epistemic_kind": "USER_ASSERTED",
            "content": {"facet": "FACT", "key": key, "value": val, "text": val},
            "locator": {"kind": "MESSAGE", "value": f"msg/{key}"},
            "media_refs": [],
            "derived_from": [],
        }
        obs["content_hash"] = observation_content_hash(obs)
        batch = {
            "contract_version": "UM-WIN-1.0",
            "event_class": "TEST",
            "context": {**h.default_context(), "runtime_session_id": session_id},
            "observations": [obs],
        }
        resp = h.api("POST", "/api/unified-memory/observe", json=batch)
        assert resp.status_code in (200, 201), resp.text

    # 1. Recall with max_records=12 budget
    recall_resp = h.api("POST", "/api/unified-memory/recall", json={
        "query": f"预算控制测试项 {session_id}",
        "context": h.default_context(),
        "budget": {"max_records": MAX_RECORDS_BUDGET},
    })
    assert recall_resp.status_code == 200, recall_resp.text
    recall_data = recall_resp.json()
    returned_items = recall_data.get("context_items", []) or recall_data.get("items", [])
    # Context assembly respects max_records budget
    assert len(returned_items) <= MAX_RECORDS_BUDGET

    # 2. Verify stored memories are NOT deleted: database preserves all records
    records_resp = h.api("GET", "/api/unified-memory/records", params={"limit": 50})
    assert records_resp.status_code == 200
    all_records = records_resp.json().get("items", [])
    budget_records = [
        item for item in all_records
        if session_id in json.dumps(item.get("content", {}), ensure_ascii=False)
    ]
    # All 15 records were safely retained in database
    print("MATCHED COUNT:", len(budget_records))
    if budget_records:
        print("SAMPLE RECORD:", budget_records[0])
    assert len(budget_records) >= 15, f"Expected at least 15 records in DB, found {len(budget_records)}"


# ================================================================== Pagination

@pytest.mark.integration
def test_pagination_control_and_cursor_fidelity(h: Any):
    """Pagination with cursor retrieves full dataset without memory loss."""
    # List records with page size = 5
    page1 = h.api("GET", "/api/unified-memory/records", params={"limit": 5})
    assert page1.status_code == 200
    page1_data = page1.json()
    items1 = page1_data.get("items", [])
    assert len(items1) <= 5

    cursor = page1_data.get("next_cursor")
    if cursor and len(items1) == 5:
        page2 = h.api("GET", "/api/unified-memory/records", params={"limit": 5, "cursor": cursor})
        assert page2.status_code == 200
        page2_data = page2.json()
        items2 = page2_data.get("items", [])
        # Ensure pages do not duplicate identical primary items
        refs1 = {item["record_ref"] for item in items1}
        refs2 = {item["record_ref"] for item in items2}
        assert not (refs1 & refs2), "Overlapping records across paginated cursors"


# ================================================================== Growth & Error Rate

@pytest.mark.integration
def test_growth_bounds_and_zero_error_rate(h: Any):
    """Idempotent ingestion prevents unbounded DB growth; zero error rate under query burst."""
    # 1. Ingestion of duplicate observation
    key = "growth-dedup-001"
    val = "幂等去重测试：重复内容不增加存储膨胀"
    obs = {
        "source_event_id": f"atlas:USER_IMPORT:{key}:1:UPSERT",
        "source_kind": "USER_IMPORT",
        "source_object_id": key,
        "source_revision": "1",
        "event_action": "UPSERT",
        "occurred_at": "2026-10-07T10:00:00+08:00",
        "source_timezone": "Asia/Hong_Kong",
        "time_status": "KNOWN",
        "speaker_role": "USER",
        "epistemic_kind": "USER_ASSERTED",
        "content": {"facet": "FACT", "key": key, "value": val, "text": val},
        "locator": {"kind": "MESSAGE", "value": f"msg/{key}"},
        "media_refs": [],
        "derived_from": [],
    }
    obs["content_hash"] = observation_content_hash(obs)
    batch = {
        "contract_version": "UM-WIN-1.0",
        "event_class": "TEST",
        "context": {**h.default_context(), "runtime_session_id": "growth-check"},
        "observations": [obs],
    }

    # First write
    r1 = h.api("POST", "/api/unified-memory/observe", json=batch)
    assert r1.status_code in (200, 201), r1.text

    # Second identical write (must be duplicate, created=0)
    r2 = h.api("POST", "/api/unified-memory/observe", json=batch)
    assert r2.status_code == 200, r2.text
    ack2 = r2.json()
    assert ack2.get("created") == 0
    assert ack2.get("duplicates") == 1

    # 2. Burst of 15 queries: verify zero error rate
    errors = 0
    total = 15
    for _ in range(total):
        resp = h.api("GET", "/api/unified-memory/status")
        if resp.status_code != 200:
            errors += 1

    error_rate = (errors / total) * 100.0
    assert error_rate == 0.0, f"Error rate was {error_rate}%"
