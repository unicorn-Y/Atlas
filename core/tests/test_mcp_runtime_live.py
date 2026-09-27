"""Opt-in end-to-end MCP verification against the official filesystem server."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.mark.skipif(
    os.environ.get("ATLAS_P16A_RUN_LIVE_MCP") != "1",
    reason="set ATLAS_P16A_RUN_LIVE_MCP=1 to run the bundled Node MCP smoke",
)
async def test_bundled_node_filesystem_mcp_discovery_agent_call_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.messages import AIMessage

    from atlas.agent import AgentOrchestrator, AgentRunContext
    from atlas.tools.mcp_client import MCPClient

    runtime_dir_value = os.environ.get("ATLAS_P16A_NODE_RUNTIME_DIR")
    assert runtime_dir_value, "ATLAS_P16A_NODE_RUNTIME_DIR must point to the packaged Node runtime"
    runtime_dir = Path(runtime_dir_value)
    assert (runtime_dir / "node.exe").is_file()
    monkeypatch.setenv("ATLAS_NODE_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("npm_config_cache", str(tmp_path / "npm-cache"))

    search_path = os.environ.get("PATH", "").split(os.pathsep)
    search_path = [
        item for item in search_path
        if not item or not any((Path(item.strip('"')) / name).is_file()
                               for name in ("node.exe", "node.cmd", "node"))
    ]
    monkeypatch.setenv("PATH", os.pathsep.join(search_path))
    assert shutil.which("node") is None, "smoke PATH must not expose system Node"

    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    expected = "Bundled Node MCP readback"
    (allowed_dir / "sample.txt").write_text(expected, encoding="utf-8")

    class Config:
        def get(self, key: str, default=None):
            return {
                "tools.servers": {
                    "filesystem": {
                        "transport": "stdio", "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", str(allowed_dir)],
                    },
                },
                "tools.auto_start": ["filesystem"],
            }.get(key, default)

    client = MCPClient()
    with patch("atlas.tools.mcp_client.get_config", return_value=Config()):
        await client.start()
        try:
            tools = client.list_tools()
            assert tools, "filesystem MCP should discover tools"
            tool_name = next(tool.qualified_name for tool in tools if tool.name == "read_file")
            orchestrator = AgentOrchestrator(MagicMock(), MagicMock(), mcp_client=client)
            tool_call = {
                "name": tool_name, "args": {"path": str(allowed_dir / "sample.txt")},
                "id": "p16a-filesystem-call",
            }
            result = await orchestrator._execute_tools_node({
                "messages": [AIMessage(content="", tool_calls=[tool_call])],
                "pending_events": [], "tool_rounds": 0, "cancelled": False,
                "runtime": AgentRunContext(),
            })
            assert expected in result["messages"][0].content
            assert result["pending_events"][-1]["is_error"] is False

            await client.restart_server("filesystem")
            assert client.get_runtime_status()["servers"][0]["tool_discovery"] == "complete"
            second = await client.call_tool(tool_name, {"path": str(allowed_dir / "sample.txt")})
            assert second["is_error"] is False
            assert expected in second["content"][0]["text"]
        finally:
            await client.stop()


@pytest.mark.skipif(
    os.environ.get("ATLAS_P16A_RUN_PACKAGED_BACKEND") != "1",
    reason="set ATLAS_P16A_RUN_PACKAGED_BACKEND=1 to run the Windows bundle smoke",
)
def test_packaged_backend_starts_filesystem_mcp_without_system_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = Path(os.environ["ATLAS_P16A_RESOURCES_DIR"])
    executable = resources / "backend" / "atlas_backend.exe"
    node_dir = resources / "runtime" / "node"
    assert executable.is_file()
    assert (node_dir / "node.exe").is_file()
    assert (node_dir / "npm" / "bin" / "npx-cli.js").is_file()

    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    config_dir = tmp_path / "data" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "atlas.toml").write_text(
        "[tools]\nauto_start = ['filesystem']\n\n"
        "[tools.servers.filesystem]\ntransport = 'stdio'\ncommand = 'npx'\n"
        f"args = ['-y', '@modelcontextprotocol/server-filesystem', '{allowed_dir.as_posix()}']\n",
        encoding="utf-8",
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    search_path = os.environ.get("PATH", "").split(os.pathsep)
    search_path = [
        item for item in search_path
        if not item or not any((Path(item.strip('"')) / name).is_file()
                               for name in ("node.exe", "node.cmd", "node"))
    ]
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(search_path)
    env["ATLAS_ROOT"] = str(resources)
    env["ATLAS_DATA_DIR"] = str(tmp_path / "data")
    env["ATLAS_NODE_RUNTIME_DIR"] = str(node_dir)
    env["ATLAS_NODE_RUNTIME_REQUIRED"] = "1"
    env["ATLAS_PORT"] = str(port)
    env["ATLAS_SCHEDULER_ENABLED"] = "false"
    env["npm_config_cache"] = str(tmp_path / "npm-cache")
    env.pop("ATLAS_API_KEY", None)
    env.pop("ATLAS_API_BASE", None)

    log_path = tmp_path / "backend-smoke.log"
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            [str(executable)], cwd=tmp_path, env=env,
            stdout=log_file, stderr=subprocess.STDOUT,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 90
            health = None
            with httpx.Client(trust_env=False) as http:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    try:
                        health = http.get(f"{base_url}/api/health", timeout=2)
                        if health.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.5)
                assert health is not None and health.status_code == 200, log_path.read_text(
                    encoding="utf-8", errors="replace",
                )[-4000:]

                report = http.get(
                    f"{base_url}/api/runtime/dependency-check", timeout=10,
                ).json()
                assert report["node"]["source"] == "bundled"
                assert report["node"]["version"] == "v22.23.3"
                servers = report["mcp_servers"]
                assert servers and servers[0]["connected"] is True, report
                tools = http.get(f"{base_url}/api/tools", timeout=10).json()
                assert any(tool["server"] == "filesystem" for tool in tools["tools"]), tools
        finally:
            if process.poll() is None:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False, capture_output=True, timeout=10,
                )
            process.wait(timeout=10)
