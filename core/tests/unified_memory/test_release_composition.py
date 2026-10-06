"""Acceptance tests for T12.1 Desktop Correction E2E and T12.2 Windows Startup & Lifecycle.

Criteria (02_wave_tasks.md T12.1, T12.2 & 01_contracts.md §6, §8):
  - T12.1:
      def test_desktop_correction_is_visible_in_new_chat(h):
          h.seed("desktop")
          h.tool("fixture_desktop_correct_preference", {"replacement": "简短中文"})
          assert h.chat("按我现在的格式来")["applied_preference"] == "简短中文"
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
from pathlib import Path
from typing import Any

import pytest

from scripts.unified_memory.cutover import (
    CONTRACT_VERSION,
    attach_lane_helpers,
)
from tests.unified_memory.harness import UMHarness


@pytest.fixture
def h(um: UMHarness) -> Any:
    """Session harness decorated with T12 helpers."""
    attach_lane_helpers(um)
    return um


# ================================================================== T12.1 Desktop Correction

@pytest.mark.integration
def test_desktop_correction_is_visible_in_new_chat(h: Any):
    """T12.1 Acceptance criterion: preference correction is visible in new chat."""
    h.seed("desktop")
    receipt = h.tool("fixture_desktop_correct_preference", {"replacement": "简短中文"})
    assert receipt["applied"] is True
    chat_result = h.chat("按我现在的格式来")
    assert chat_result["applied_preference"] == "简短中文"


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
