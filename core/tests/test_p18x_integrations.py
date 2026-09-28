from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest

from atlas.runtime.capability_bus import CapabilityBus
from atlas.runtime.external_process import ExternalProcessAdapter


def test_capability_bus_reports_normalized_records_and_upstream_metadata() -> None:
    bus = CapabilityBus()
    with (
        patch.object(bus, "_package_version", return_value="1.2.3"),
        patch.object(bus, "_node_version", return_value="4.5.6"),
        patch.object(bus, "_command_version", return_value=("7.8.9", None)),
    ):
        result = bus.status()

    ids = {item["id"] for item in result["capabilities"]}
    assert {"local.full_access", "computer.cua", "browser.browser_use", "durable.dbos"} <= ids
    assert {"agent.codex", "agent.claude", "agent.hermes", "agent.pi", "agent.zcode"} <= ids
    assert all(
        item["kind"] and item["source"] and item["adapter"] for item in result["capabilities"]
    )
    assert result["ready"] > 0


def test_capability_bus_can_disable_and_reenable_optional_integrations() -> None:
    bus = CapabilityBus()
    assert bus.set_enabled("coding.ast_grep", False)
    with (
        patch.object(bus, "_package_version", return_value="1.0"),
        patch.object(bus, "_node_version", return_value="1.0"),
        patch.object(bus, "_command_version", return_value=("1.0", None)),
    ):
        item = next(row for row in bus.status()["capabilities"] if row["id"] == "coding.ast_grep")
        assert item["status"] == "disabled"
        assert not item["enabled"]
    assert bus.set_enabled("coding.ast_grep", True)
    assert not bus.set_enabled("unknown.integration", False)


def test_packaged_node_versions_are_reported_from_electron_manifest(monkeypatch) -> None:
    monkeypatch.setenv(
        "ATLAS_NPM_PACKAGE_VERSIONS",
        json.dumps({"@playwright/mcp": "0.0.45"}),
    )
    assert CapabilityBus._node_version("@playwright/mcp") == "0.0.45"


def test_capability_probe_errors_are_not_reported_as_missing_packages() -> None:
    bus = CapabilityBus()
    item = bus._record(
        id="agent.zcode", kind="agent_backend", source="zcode-ai/zcode",
        capabilities=["session"], error="zcode version probe exited 1",
    )
    assert item.status == "failed"
    assert not item.available


@pytest.mark.asyncio
async def test_external_process_adapter_streams_output_and_closes_session() -> None:
    adapter = ExternalProcessAdapter(
        "echo-agent",
        sys.executable,
        ["-u", "-c", "import sys; print(sys.stdin.readline().strip(), flush=True)"],
    )
    session = await adapter.start_session()
    await adapter.send(session, "marker-42")
    events = [event async for event in adapter.stream_events(session)]
    assert any(event.type == "text" and event.data["text"] == "marker-42" for event in events)
    assert events[-1].type == "done"
    await adapter.close(session)


@pytest.mark.asyncio
async def test_pi_rpc_adapter_encodes_prompt_and_streams_json_events() -> None:
    adapter = ExternalProcessAdapter(
        "pi",
        sys.executable,
        [
            "-u",
            "-c",
            "import json,sys; m=json.loads(sys.stdin.readline()); "
            "print(json.dumps({'type':'message_update','message':m['message']}),flush=True); "
            "print(json.dumps({'type':'agent_end'}),flush=True)",
        ],
        protocol="pi-rpc",
    )
    session = await adapter.start_session()
    await adapter.send(session, "marker-42")
    events = [event async for event in adapter.stream_events(session)]
    assert any(
        event.type == "message_update" and event.data["message"] == "marker-42" for event in events
    )
    assert any(event.type == "agent_end" for event in events)
    await adapter.close(session)
