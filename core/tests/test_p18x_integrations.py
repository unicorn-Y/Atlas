from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from atlas.capabilities.computer.cua_backend import CuaBackend
from atlas.runtime.backends import ACPBackend, full_access_permission_response
from atlas.runtime.capability_bus import CapabilityBus
from atlas.runtime.external_process import ExternalProcessAdapter
from atlas.tools.agent_bridge import create_server


def test_capability_bus_reports_normalized_records_and_upstream_metadata() -> None:
    bus = CapabilityBus()
    with (
        patch.object(bus, "_package_version", return_value="1.2.3"),
        patch.object(bus, "_node_version", return_value="4.5.6"),
        patch.object(bus, "_command_version", return_value=("7.8.9", None)),
        patch("atlas.runtime.capability_bus.subprocess.run", return_value=SimpleNamespace(
            returncode=0, stdout="", stderr="",
        )),
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
        patch("atlas.runtime.capability_bus.subprocess.run", return_value=SimpleNamespace(
            returncode=0, stdout="", stderr="",
        )),
    ):
        item = next(row for row in bus.status()["capabilities"] if row["id"] == "coding.ast_grep")
        assert item["status"] == "disabled"
        assert not item["enabled"]
    assert bus.set_enabled("coding.ast_grep", True)
    assert not bus.set_enabled("unknown.integration", False)


def test_capability_status_cache_can_be_forced_and_toggle_invalidates() -> None:
    bus = CapabilityBus()
    calls = 0

    def discover():
        nonlocal calls
        calls += 1
        return [bus._record(
            id="coding.ast_grep", kind="coding_backend", source="test",
            capabilities=["search"], version="1.0",
        )]

    bus.discover = discover
    assert bus.status() == bus.status()
    assert calls == 1
    bus.status(refresh=True)
    assert calls == 2
    assert bus.set_enabled("coding.ast_grep", False)
    bus.status()
    assert calls == 4


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


def test_windows_cli_shims_use_cmd_call_for_version_probes() -> None:
    from atlas.runtime import capability_bus

    shim = r"C:\Program Files\Atlas CLI\zcode.cmd"
    completed = capability_bus.subprocess.CompletedProcess(
        args=[], returncode=0, stdout="0.16.9\n", stderr=""
    )
    with (
        patch.object(capability_bus.shutil, "which", return_value=shim),
        patch.object(capability_bus.subprocess, "run", return_value=completed) as run,
    ):
        version, error = CapabilityBus._command_version("zcode")

    assert version == "0.16.9"
    assert error is None
    assert run.call_args.args[0] == ["cmd.exe", "/d", "/c", "call", shim, "--version"]


def test_npx_acp_launch_resolves_windows_cmd_shim(monkeypatch) -> None:
    from atlas.tools import mcp_client, node_runtime

    runtime = node_runtime.NodeRuntime(
        executable=Path(r"C:\Program Files\nodejs\node.exe"),
        source="system",
        npm_script=None,
        npx_script=None,
    )
    monkeypatch.setattr(mcp_client, "resolve_node_runtime", lambda: runtime)
    monkeypatch.setattr(
        mcp_client.shutil, "which", lambda command: r"C:\Program Files\nodejs\npx.CMD"
    )

    command, args = mcp_client._resolve_stdio_command(
        "npx", ["--yes", "@agentclientprotocol/claude-agent-acp@0.81.2"]
    )

    assert command == "cmd.exe"
    assert args == [
        "/d",
        "/c",
        "call",
        r"C:\Program Files\nodejs\npx.CMD",
        "--yes",
        "@agentclientprotocol/claude-agent-acp@0.81.2",
    ]


def test_acp_permission_uses_broadest_offered_allow_option() -> None:
    from acp.schema import AllowedOutcome, PermissionOption

    response = full_access_permission_response(
        [
            PermissionOption(kind="allow_once", name="Allow once", optionId="once"),
            PermissionOption(kind="reject_always", name="Reject", optionId="reject"),
            PermissionOption(kind="allow_always", name="Allow always", optionId="always"),
        ]
    )
    assert isinstance(response.outcome, AllowedOutcome)
    assert response.outcome.option_id == "always"


def test_acp_permission_denies_only_when_protocol_offers_no_allow() -> None:
    from acp.schema import DeniedOutcome, PermissionOption

    response = full_access_permission_response(
        [PermissionOption(kind="reject_once", name="Reject", optionId="reject")]
    )
    assert isinstance(response.outcome, DeniedOutcome)


def test_acp_backend_has_shared_atlas_mcp_server() -> None:
    backend = ACPBackend("test", "agent", [])
    descriptor = backend.mcp_servers[0]
    assert descriptor.name == "Atlas capabilities"
    assert descriptor.args == ["-m", "atlas.tools.agent_bridge"]


@pytest.mark.asyncio
async def test_acp_backend_cleans_manager_when_process_startup_fails(monkeypatch) -> None:
    import acp

    class Manager:
        exited = False

        async def __aenter__(self):
            raise FileNotFoundError("isolated startup failure")

        async def __aexit__(self, *_args):
            self.exited = True

    manager = Manager()
    monkeypatch.setattr(acp, "spawn_agent_process", lambda *_args, **_kwargs: manager)
    backend = ACPBackend("test", "npx", ["--version"])

    with pytest.raises(FileNotFoundError, match="isolated startup failure"):
        await backend.start_session()

    assert manager.exited


@pytest.mark.asyncio
async def test_cua_backend_preserves_structured_snapshot_handles() -> None:
    class Driver:
        async def list_tools_json(self):
            return json.dumps({"tools": [{"name": "get_window_state", "inputSchema": {
                "type": "object", "properties": {"window_id": {"type": "integer"}},
                "required": ["window_id"],
            }}]})

        async def call_tool(self, _name: str, _arguments: str) -> SimpleNamespace:
            assert json.loads(_arguments) == {"window_id": 77}
            return SimpleNamespace(
                text="window snapshot",
                is_error=False,
                structured_json=json.dumps(
                    {"snapshot_id": "s12345678", "elements": [{"element_token": "s12345678:0"}]}
                ),
            )

    backend = CuaBackend()
    backend._driver = Driver()
    result = await backend.call("get_window_state", {"window_id": 77, "unknown": "ignored"})

    assert result["structured_content"]["snapshot_id"] == "s12345678"
    assert result["structured_content"]["elements"][0]["element_token"] == "s12345678:0"


@pytest.mark.asyncio
async def test_targeted_cua_observation_returns_snapshot_handles_and_image() -> None:
    from atlas.tools.computer_use import ComputerUseRuntime

    class Cua:
        async def call(self, name, arguments):
            assert name == "get_window_state"
            assert arguments == {"pid": 12, "window_id": 34}
            return {
                "text": "target snapshot",
                "content": [],
                "is_error": False,
                "structured_content": {
                    "snapshot_id": "s12345678",
                    "elements": [{"element_token": "s12345678:0"}],
                    "screenshot_base64": "c2NyZWVu",
                },
            }

    result = await ComputerUseRuntime(cua_backend=Cua()).call_tool(
        "computer_observe", {"target": "window", "pid": 12, "window_id": 34},
    )
    assert not result["is_error"]
    assert result["data"]["snapshot_id"] == "s12345678"
    assert result["data"]["_image_data_url"] == "data:image/png;base64,c2NyZWVu"


@pytest.mark.asyncio
async def test_integrations_api_keeps_unconfigured_agent_misconfigured(monkeypatch) -> None:
    from atlas import server
    # H5: integrations handlers live on the integrations router now; the bus
    # seams are still resolved through atlas.server.
    from atlas.api.integrations_router import list_integrations

    class Bus:
        def status(self, _refresh=False):
            return {
                "capabilities": [
                    {
                        "id": "agent.zcode",
                        "status": "misconfigured",
                        "authenticated": None,
                        "configured": False,
                    }
                ]
            }

    class Host:
        smoke_verified: set[str] = set()

        @staticmethod
        def connected_names() -> set[str]:
            return set()

    monkeypatch.setattr(server, "capability_bus", Bus())
    monkeypatch.setattr(server, "agent_backend_host", Host())

    result = await list_integrations(SimpleNamespace())

    assert result["capabilities"][0]["status"] == "misconfigured"
    assert result["capabilities"][0]["configured"] is False


@pytest.mark.asyncio
async def test_blocking_integration_probe_does_not_block_health(monkeypatch) -> None:
    from atlas import server
    # H5: integrations/health handlers live on their routers now.
    from atlas.api.health_router import health
    from atlas.api.integrations_router import list_integrations

    class SlowBus:
        def status(self, _refresh=False):
            time.sleep(0.25)
            return {"count": 0, "ready": 0, "degraded": 0, "capabilities": []}

    monkeypatch.setattr(server, "capability_bus", SlowBus())
    started = time.monotonic()
    task = asyncio.create_task(list_integrations(SimpleNamespace()))
    await asyncio.sleep(0.01)
    assert (await health(SimpleNamespace()))["status"] == "ok"
    assert time.monotonic() - started < 0.15
    await task


@pytest.mark.asyncio
async def test_atlas_bridge_lists_and_invokes_canonical_local_file_tool(tmp_path) -> None:
    target = tmp_path / "bridge.txt"
    server = create_server()
    names = {item.name for item in await server.list_tools()}
    assert {"local_file", "computer_keyboard", "coding_ast_grep", "coding_repo_map"} <= names

    result = await server.call_tool(
        "local_file",
        {"arguments": {"action": "write", "path": str(target), "content": "bridge-ok"}},
    )
    assert result.content
    assert target.read_text(encoding="utf-8") == "bridge-ok"


def test_ast_grep_resolves_bundled_cli_from_atlas_root(tmp_path, monkeypatch) -> None:
    from atlas.capabilities.coding.ast_grep import _executable

    executable = (
        tmp_path
        / "node_modules"
        / "@ast-grep"
        / "cli-win32-x64-msvc"
        / "ast-grep.exe"
    )
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("ATLAS_ROOT", str(tmp_path))

    with patch("atlas.capabilities.coding.ast_grep.shutil.which", return_value=None):
        assert _executable() == str(executable)


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
