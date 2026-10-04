"""Real stdio child-process coverage for MCP task ownership during shutdown."""

from __future__ import annotations

import asyncio
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import psutil
import pytest

from atlas.tools import mcp_client as mcp_client_module
from atlas.tools.mcp_client import MCPClient, MCPServerConfig


def _matching_children(script_path: Path) -> list[psutil.Process]:
    expected = str(script_path).casefold()
    found = []
    for child in psutil.Process().children(recursive=True):
        try:
            if expected in " ".join(child.cmdline()).casefold():
                found.append(child)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _write_fake_server(tmp_path: Path) -> Path:
    server_script = tmp_path / "fake_mcp_server.py"
    server_script.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    method = request.get('method')\n"
        "    if method == 'initialize':\n"
        "        result = {\n"
        "            'protocolVersion': request['params']['protocolVersion'],\n"
        "            'capabilities': {'tools': {}},\n"
        "            'serverInfo': {'name': 'lifecycle-test', 'version': '1'},\n"
        "        }\n"
        "    elif method == 'tools/list':\n"
        "        result = {'tools': [{\n"
        "            'name': 'ping', 'description': 'test',\n"
        "            'inputSchema': {'type': 'object', 'properties': {}},\n"
        "        }]}\n"
        "    elif method == 'ping':\n"
        "        result = {}\n"
        "    else:\n"
        "        continue\n"
        "    if 'id' in request:\n"
        "        response = json.dumps({\n"
        "            'jsonrpc': '2.0', 'id': request['id'], 'result': result,\n"
        "        }) + '\\n'\n"
        "        sys.stdout.write(response)\n"
        "        sys.stdout.flush()\n",
        encoding="utf-8",
    )
    return server_script


async def test_stdio_session_shutdown_exits_its_real_child(tmp_path: Path) -> None:
    server_script = _write_fake_server(tmp_path)
    config = MCPServerConfig(
        name="lifecycle-test",
        command=sys.executable,
        args=[str(server_script)],
        cwd=str(tmp_path),
    )
    client = MCPClient()
    owner_tasks: dict[str, asyncio.Task[object] | None] = {"enter": None, "exit": None}
    original_stdio_client = mcp_client_module.stdio_client

    @asynccontextmanager
    async def record_stdio_owner(parameters, errlog):
        transport_cm = original_stdio_client(parameters, errlog)
        streams = await transport_cm.__aenter__()
        owner_tasks["enter"] = asyncio.current_task()
        try:
            yield streams
        finally:
            owner_tasks["exit"] = asyncio.current_task()
            await transport_cm.__aexit__(None, None, None)

    try:
        with (
            patch("atlas.tools.mcp_client._parse_server_configs", return_value=[config]),
            patch("atlas.tools.mcp_client.stdio_client", side_effect=record_stdio_owner),
        ):
            await client.start()
            assert client.get_server_names() == ["lifecycle-test"], client.get_runtime_status()
            assert _matching_children(server_script)

            await client.stop()
        assert owner_tasks["enter"] is owner_tasks["exit"], (
            "stdio transport context must exit in the task that entered it"
        )

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and _matching_children(server_script):
            await asyncio.sleep(0.05)
        assert not _matching_children(server_script), "MCP stdio child remained after client.stop()"
    finally:
        for child in _matching_children(server_script):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass


async def test_cancelled_mcp_discovery_stops_its_real_stdio_child(tmp_path: Path) -> None:
    server_script = _write_fake_server(tmp_path)
    config = MCPServerConfig(
        name="lifecycle-test",
        command=sys.executable,
        args=[str(server_script)],
        cwd=str(tmp_path),
    )
    client = MCPClient()
    discovery_started = asyncio.Event()

    async def wait_for_discovery(self):
        discovery_started.set()
        await asyncio.Event().wait()

    try:
        with (
            patch("atlas.tools.mcp_client._parse_server_configs", return_value=[config]),
            patch.object(mcp_client_module.ClientSession, "list_tools", wait_for_discovery),
        ):
            start_task = asyncio.create_task(client.start())
            await asyncio.wait_for(discovery_started.wait(), timeout=5)
            assert _matching_children(server_script)
            start_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await start_task

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and _matching_children(server_script):
            await asyncio.sleep(0.05)
        assert not _matching_children(server_script), (
            "cancelled MCP startup left its real stdio child running"
        )
    finally:
        for child in _matching_children(server_script):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass


async def test_cancelled_owner_does_not_skip_other_server_cleanup(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first_script = _write_fake_server(first_dir)
    second_script = _write_fake_server(second_dir)
    configs = [
        MCPServerConfig(
            name=name,
            command=sys.executable,
            args=[str(script)],
            cwd=str(script.parent),
        )
        for name, script in (("first", first_script), ("second", second_script))
    ]
    client = MCPClient()

    try:
        with patch("atlas.tools.mcp_client._parse_server_configs", return_value=configs):
            await client.start()
        assert len(_matching_children(first_script)) >= 1
        assert len(_matching_children(second_script)) >= 1

        client._servers["first"]._owner_task.cancel()
        await asyncio.sleep(0)
        await client.stop()

        assert not _matching_children(first_script)
        assert not _matching_children(second_script)
        statuses = {item["name"]: item["state"] for item in client.get_runtime_status()["servers"]}
        assert statuses == {"first": "stopped", "second": "stopped"}
    finally:
        for script in (first_script, second_script):
            for child in _matching_children(script):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
