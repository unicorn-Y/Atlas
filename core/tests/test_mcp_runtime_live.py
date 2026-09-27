"""Opt-in MCP checks against the packaged backend and official filesystem server."""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.mark.skipif(
    os.environ.get("ATLAS_P16A_RUN_LIVE_MCP") != "1",
    reason="set ATLAS_P16A_RUN_LIVE_MCP=1 to run the bundled Node MCP smoke",
)
async def test_bundled_node_filesystem_mcp_discovery_agent_call_and_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        item
        for item in search_path
        if not item
        or not any(
            (Path(item.strip('"')) / name).is_file() for name in ("node.exe", "node.cmd", "node")
        )
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
                        "transport": "stdio",
                        "command": "npx",
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
                "name": tool_name,
                "args": {"path": str(allowed_dir / "sample.txt")},
                "id": "p16a-filesystem-call",
            }
            result = await orchestrator._execute_tools_node(
                {
                    "messages": [AIMessage(content="", tool_calls=[tool_call])],
                    "pending_events": [],
                    "tool_rounds": 0,
                    "cancelled": False,
                    "runtime": AgentRunContext(),
                }
            )
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
    os.environ.get("ATLAS_P16B_RUN_PACKAGED_AGENT_E2E") != "1",
    reason="set ATLAS_P16B_RUN_PACKAGED_AGENT_E2E=1 to run the Windows packaged Agent E2E",
)
def test_packaged_backend_bundled_node_filesystem_agent_read_file_e2e(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = Path(os.environ["ATLAS_P16A_RESOURCES_DIR"])
    executable = resources / "backend" / "atlas_backend.exe"
    node_dir = resources / "runtime" / "node"
    assert executable.is_file()
    assert (node_dir / "node.exe").is_file()
    assert (node_dir / "npm" / "bin" / "npx-cli.js").is_file()

    marker = "ATLAS_PACKAGED_MCP_AGENT_E2E_OK"
    local_marker = "ATLAS_PACKAGED_LOCAL_EXECUTION_E2E_OK"
    fixture = Path(__file__).parent / "fixtures" / "packaged-mcp-agent-e2e.txt"
    assert fixture.read_text(encoding="utf-8").strip() == marker
    provider_requests: list[dict[str, object]] = []

    class CompletionHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            provider_requests.append(body)
            tool_messages = [
                message for message in body["messages"] if message.get("role") == "tool"
            ]
            is_local_run = any(
                local_marker in str(message.get("content", ""))
                for message in body["messages"]
                if message.get("role") == "user"
            )
            if is_local_run:
                step = len(tool_messages)
                local_calls = [
                    (
                        "local_file",
                        {"action": "write", "path": str(local_file), "content": local_marker},
                    ),
                    (
                        "local_shell",
                        {
                            "shell": "powershell",
                            "command": f"Get-Content -Raw -LiteralPath '{local_file}'",
                            "cwd": str(local_project),
                        },
                    ),
                    ("local_git", {"action": "status", "repo": str(local_project)}),
                ]
                if step < len(local_calls):
                    name, arguments = local_calls[step]
                    chunks = [
                        {
                            "tool_call": {
                                "id": f"p18-local-{step}",
                                "name": name,
                                "arguments": json.dumps(arguments),
                            }
                        },
                        {"content": None, "finish_reason": "tool_calls"},
                    ]
                else:
                    chunks = [{"content": local_marker}, {"content": None, "finish_reason": "stop"}]
            elif tool_messages:
                chunks = [{"content": marker}, {"content": None, "finish_reason": "stop"}]
            else:
                tool = next(
                    item
                    for item in body["tools"]
                    if item["function"]["name"] == "filesystem__read_file"
                )
                chunks = [
                    {
                        "tool_call": {
                            "id": "p16b-read-file",
                            "name": tool["function"]["name"],
                            "arguments": json.dumps({"path": str(allowed_fixture)}),
                        }
                    },
                    {"content": None, "finish_reason": "tool_calls"},
                ]

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for chunk in chunks:
                delta: dict[str, object] = {}
                if "content" in chunk and chunk["content"] is not None:
                    delta["content"] = chunk["content"]
                if "tool_call" in chunk:
                    call = chunk["tool_call"]
                    delta["tool_calls"] = [
                        {
                            "index": 0,
                            "id": call["id"],
                            "type": "function",
                            "function": {"name": call["name"], "arguments": call["arguments"]},
                        }
                    ]
                value = {
                    "id": "chatcmpl-p16b-smoke",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "gpt-4o-mini",
                    "choices": [
                        {"index": 0, "delta": delta, "finish_reason": chunk.get("finish_reason")}
                    ],
                }
                self.wfile.write(f"data: {json.dumps(value)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

        def log_message(self, format: str, *args: object) -> None:
            return

    provider = ThreadingHTTPServer(("127.0.0.1", 0), CompletionHandler)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    initial_node_pids = _windows_node_pids()
    npm_cache = tmp_path / "npm-cache"

    try:
        for iteration in range(2):
            run_dir = tmp_path / f"packaged-run-{iteration + 1}"
            allowed_dir = run_dir / "allowed"
            allowed_dir.mkdir(parents=True)
            local_project = run_dir / "任意工作目录 Project With Spaces"
            local_project.mkdir()
            local_file = local_project / "本机执行结果.txt"
            subprocess.run(["git", "init", "--quiet", str(local_project)], check=True)
            subprocess.run(
                ["git", "-C", str(local_project), "config", "user.email", "atlas@example.test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(local_project), "config", "user.name", "Atlas Test"], check=True
            )
            allowed_fixture = allowed_dir / fixture.name
            shutil.copyfile(fixture, allowed_fixture)
            data_dir = run_dir / "data"
            config_dir = data_dir / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "atlas.toml").write_text(
                "[tools]\nauto_start = ['filesystem']\n\n"
                "[tools.servers.filesystem]\ntransport = 'stdio'\ncommand = 'npx'\n"
                f"args = ['-y', '@modelcontextprotocol/server-filesystem', "
                f"'{allowed_dir.as_posix()}']\n",
                encoding="utf-8",
            )
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]

            search_path = os.environ.get("PATH", "").split(os.pathsep)
            search_path = [
                item
                for item in search_path
                if not item
                or not any(
                    (Path(item.strip('"')) / name).is_file()
                    for name in ("node.exe", "node.cmd", "node")
                )
            ]
            env = os.environ.copy()
            env.update(
                {
                    "PATH": os.pathsep.join(search_path),
                    "ATLAS_ROOT": str(resources),
                    "ATLAS_DATA_DIR": str(data_dir),
                    "ATLAS_NODE_RUNTIME_DIR": str(node_dir),
                    "ATLAS_NODE_RUNTIME_REQUIRED": "1",
                    "ATLAS_PORT": str(port),
                    "ATLAS_SCHEDULER_ENABLED": "false",
                    "npm_config_cache": str(npm_cache),
                    "npm_config_yes": "true",
                }
            )
            env.pop("ATLAS_API_KEY", None)
            env.pop("ATLAS_API_BASE", None)

            log_path = run_dir / "backend-smoke.log"
            with log_path.open("wb") as log_file:
                process = subprocess.Popen(
                    [str(executable)],
                    cwd=run_dir,
                    env=env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
                base_url = f"http://127.0.0.1:{port}"
                try:
                    deadline = time.monotonic() + 120
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
                            encoding="utf-8",
                            errors="replace",
                        )[-4000:]

                        report = http.get(
                            f"{base_url}/api/runtime/dependency-check",
                            timeout=10,
                        ).json()
                        assert report["node"]["source"] == "bundled", report
                        assert report["node"]["version"] == "v22.23.3", report
                        assert report["node"]["system"]["available"] is False, report
                        servers = report["mcp_servers"]
                        filesystem = next(item for item in servers if item["name"] == "filesystem")
                        assert filesystem["connected"] is True, report
                        assert filesystem["tool_discovery"] == "complete", report
                        tools = http.get(f"{base_url}/api/tools", timeout=10).json()
                        assert any(
                            tool["name"] == "filesystem__read_file" for tool in tools["tools"]
                        ), tools

                        configured = http.put(
                            f"{base_url}/api/settings/configuration",
                            json={
                                "gateway_base_url": f"http://127.0.0.1:{provider.server_port}/v1",
                                "api_key": "p16b-local-provider",
                            },
                            timeout=10,
                        )
                        assert configured.status_code == 200, configured.text

                    from websockets.sync.client import connect

                    events: list[dict[str, object]] = []
                    with connect(f"ws://127.0.0.1:{port}/ws/chat", open_timeout=10) as ws:
                        ws.send(
                            json.dumps(
                                {
                                    "type": "run.start",
                                    "run_id": f"p16b-run-{iteration}",
                                    "conversation_id": f"p16b-conversation-{iteration}",
                                    "model": "gpt-4o-mini",
                                    "content": (
                                        f"Read {allowed_fixture} with filesystem MCP read_file "
                                        "and return its exact marker."
                                    ),
                                }
                            )
                        )
                        deadline = time.monotonic() + 60
                        while time.monotonic() < deadline:
                            envelope = json.loads(
                                ws.recv(timeout=max(0.1, deadline - time.monotonic()))
                            )
                            events.append(envelope)
                            if envelope.get("event") in {"run.completed", "run.failed"}:
                                break
                    assert events[-1]["event"] == "run.completed", events
                    started = [
                        item["data"] for item in events if item.get("event") == "tool.started"
                    ]
                    completed = [
                        item["data"] for item in events if item.get("event") == "tool.completed"
                    ]
                    assert any(
                        item.get("name") == "filesystem__read_file"
                        and item.get("arguments", {}).get("path") == str(allowed_fixture)
                        for item in started
                    ), events
                    result = next(
                        item for item in completed if item.get("name") == "filesystem__read_file"
                    )
                    assert result["is_error"] is False, result
                    assert marker in json.dumps(result["result"]), result
                    assert any(
                        item.get("event") == "message.completed"
                        and marker in item.get("data", {}).get("content", "")
                        for item in events
                    ), events
                    assert any(
                        any(
                            tool["function"]["name"] == "filesystem__read_file"
                            for tool in request.get("tools", [])
                        )
                        and any(
                            message.get("role") == "user"
                            and str(allowed_fixture) in message.get("content", "")
                            for message in request.get("messages", [])
                        )
                        for request in provider_requests
                    ), provider_requests

                    local_events: list[dict[str, object]] = []
                    with connect(f"ws://127.0.0.1:{port}/ws/chat", open_timeout=10) as ws:
                        ws.send(
                            json.dumps(
                                {
                                    "type": "run.start",
                                    "run_id": f"p18-local-run-{iteration}",
                                    "conversation_id": f"p18-local-conversation-{iteration}",
                                    "model": "gpt-4o-mini",
                                    "content": f"Complete this local CLI smoke: {local_marker}",
                                }
                            )
                        )
                        deadline = time.monotonic() + 60
                        while time.monotonic() < deadline:
                            envelope = json.loads(
                                ws.recv(timeout=max(0.1, deadline - time.monotonic()))
                            )
                            local_events.append(envelope)
                            if envelope.get("event") in {"run.completed", "run.failed"}:
                                break
                    assert local_events[-1]["event"] == "run.completed", local_events
                    local_started = [
                        item["data"] for item in local_events if item.get("event") == "tool.started"
                    ]
                    local_completed = [
                        item["data"]
                        for item in local_events
                        if item.get("event") == "tool.completed"
                    ]
                    assert [item["name"] for item in local_started] == [
                        "local_file",
                        "local_shell",
                        "local_git",
                    ], local_events
                    assert local_file.read_text(encoding="utf-8") == local_marker
                    assert local_started[2]["arguments"]["repo"] == str(local_project)
                    shell_result = next(
                        item for item in local_completed if item["name"] == "local_shell"
                    )
                    assert shell_result["execution"]["exit_code"] == 0, shell_result
                    assert local_marker in json.dumps(shell_result["result"]), shell_result
                    git_result = next(
                        item for item in local_completed if item["name"] == "local_git"
                    )
                    assert git_result["execution"]["exit_code"] == 0, git_result
                    assert any(item.get("event") == "tool.output" for item in local_events), (
                        local_events
                    )
                    assert not any(
                        item.get("event") == "approval.required" for item in local_events
                    ), local_events
                    assert any(
                        item.get("event") == "message.completed"
                        and local_marker in item["data"].get("content", "")
                        for item in local_events
                    ), local_events
                finally:
                    if process.poll() is None:
                        try:
                            process.send_signal(signal.CTRL_BREAK_EVENT)
                            process.wait(timeout=30)
                        except (OSError, subprocess.TimeoutExpired):
                            subprocess.run(
                                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                check=False,
                                capture_output=True,
                                timeout=10,
                            )
                            process.wait(timeout=10)
                    shutdown_log = log_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )[-4000:]
                    assert (
                        "mcp.server_stopped" in shutdown_log and "server=filesystem" in shutdown_log
                    ), shutdown_log
                    assert process.returncode in (0, 3), shutdown_log
            assert _windows_node_pids() == initial_node_pids, (
                "MCP Node process remained after backend shutdown"
            )
    finally:
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=5)


def _windows_node_pids() -> set[str]:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq node.exe", "/FO", "CSV", "/NH"],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = csv.reader(io.StringIO(result.stdout))
    return {row[1] for row in rows if len(row) > 1 and row[0].lower() == "node.exe"}
