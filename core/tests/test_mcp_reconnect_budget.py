"""The reconnect loop must reach a terminal state instead of retrying forever.

A permanently dead MCP server used to loop ``while not self._stopping`` with a
30s cap: its tools left and re-entered the model's schema indefinitely, and the
status never left ``reconnecting``, so "still starting" and "gone for good"
were indistinguishable. These tests pin the budget, the terminal state, and the
two ways out of it (an explicit restart, or a reconnect that stays up).
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from atlas.tools import mcp_client as mcp_client_module
from atlas.tools.mcp_client import MCPClient, MCPServerConfig, MCPServerHandle

pytestmark = pytest.mark.unit


class _StubHandle(MCPServerHandle):
    """A handle whose owner task models a connection that dropped."""

    def __init__(self, owner: asyncio.Task[None]) -> None:
        super().__init__(name="flaky", transport="stdio")
        self._owner_task = owner
        self.tools = []


async def _no_sleep(_seconds: float) -> None:
    """Replace backoff with an immediate yield so the test stays fast."""


@pytest.mark.asyncio
async def test_reconnect_gives_up_after_budget_and_reports_terminal_state(monkeypatch):
    monkeypatch.setattr(mcp_client_module.asyncio, "sleep", _no_sleep)
    client = MCPClient()
    cfg = MCPServerConfig(name="flaky", transport="stdio")
    client._configured_configs["flaky"] = cfg

    async def dropped() -> None:
        return None

    owner = asyncio.create_task(dropped())
    handle = _StubHandle(owner)
    client._servers["flaky"] = handle

    attempts = 0

    async def always_fails(_cfg) -> None:
        nonlocal attempts
        attempts += 1
        raise ConnectionError("refused")

    client._connect_server = always_fails  # type: ignore[assignment]

    await client._monitor_connection(cfg, handle)

    assert attempts == mcp_client_module._MCP_MAX_RECONNECT_ATTEMPTS
    status = client._server_status["flaky"]
    assert status["state"] == "unreachable"
    assert status["tool_discovery"] == "failed"
    assert "retry explicitly" in status["blocking_reason"]
    # The server is out of the live map, so its tools are gone from the schema.
    assert "flaky" not in client._servers


@pytest.mark.asyncio
async def test_reconnect_backoff_starts_at_half_a_second_and_caps_at_thirty(monkeypatch):
    delays = []

    async def record_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(mcp_client_module.asyncio, "sleep", record_sleep)
    client = MCPClient()
    cfg = MCPServerConfig(name="flaky", transport="stdio")
    client._configured_configs["flaky"] = cfg

    async def dropped() -> None:
        return None

    handle = _StubHandle(asyncio.create_task(dropped()))
    client._servers["flaky"] = handle

    async def always_fails(_cfg) -> None:
        raise ConnectionError("refused")

    client._connect_server = always_fails  # type: ignore[assignment]
    await client._monitor_connection(cfg, handle)

    assert delays == [0.5, 1, 2, 4, 8, 16, 30, 30, 30, 30]


@pytest.mark.asyncio
async def test_monitor_does_not_start_a_second_episode_after_giving_up(monkeypatch):
    monkeypatch.setattr(mcp_client_module.asyncio, "sleep", _no_sleep)
    client = MCPClient()
    cfg = MCPServerConfig(name="flaky", transport="stdio")
    client._unreachable["flaky"] = "gave up earlier"

    async def dropped() -> None:
        return None

    owner = asyncio.create_task(dropped())
    handle = _StubHandle(owner)
    client._servers["flaky"] = handle

    attempts = 0

    async def always_fails(_cfg) -> None:
        nonlocal attempts
        attempts += 1
        raise ConnectionError("refused")

    client._connect_server = always_fails  # type: ignore[assignment]
    await client._monitor_connection(cfg, handle)

    assert attempts == 0


@pytest.mark.asyncio
async def test_reconnect_success_reports_connected_and_schedules_budget_reset(monkeypatch):
    monkeypatch.setattr(mcp_client_module.asyncio, "sleep", _no_sleep)
    client = MCPClient()
    cfg = MCPServerConfig(name="flaky", transport="stdio")

    async def dropped() -> None:
        return None

    owner = asyncio.create_task(dropped())
    handle = _StubHandle(owner)
    client._servers["flaky"] = handle
    client._reconnect_attempts["flaky"] = 4

    async def reconnects(cfg_arg) -> None:
        client._servers[cfg_arg.name] = handle

    client._connect_server = reconnects  # type: ignore[assignment]
    await client._monitor_connection(cfg, handle)

    assert "flaky" in client._servers
    # The successful attempt is itself counted (4 prior failures + this one).
    # The counter is not cleared on connect; a server that drops right after
    # would otherwise retry forever. It is cleared by the deferred reset.
    assert client._reconnect_attempts.get("flaky") == 5
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_explicit_restart_clears_terminal_state(monkeypatch):
    client = MCPClient()
    cfg = MCPServerConfig(name="flaky", transport="stdio")
    client._configured_configs["flaky"] = cfg
    client._unreachable["flaky"] = "gave up"
    client._reconnect_attempts["flaky"] = 10
    client._server_status["flaky"] = {
        "name": "flaky", "state": "unreachable", "blocking_reason": "gave up",
    }

    async def noop_disconnect(_name: str) -> None:
        return None

    connected: list[str] = []

    async def reconnects(cfg_arg) -> None:
        connected.append(cfg_arg.name)

    client.disconnect_server = noop_disconnect  # type: ignore[assignment]
    client._connect_server = reconnects  # type: ignore[assignment]

    await client.restart_server("flaky")

    assert connected == ["flaky"]
    assert "flaky" not in client._unreachable
    assert "flaky" not in client._reconnect_attempts
    assert client._server_status["flaky"]["blocking_reason"] is None


@pytest.mark.asyncio
async def test_deferred_reset_clears_budget_only_while_still_connected(monkeypatch):
    """The reset is deferred so a connect-drop-connect loop cannot retry forever."""
    recorded: list[str] = []

    async def immediate_sleep(_seconds: float) -> None:
        recorded.append("slept")

    monkeypatch.setattr(mcp_client_module.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(mcp_client_module, "_MCP_RECONNECT_STABLE_SECONDS", 0.0)

    client = MCPClient()
    client._reconnect_attempts["flaky"] = 3
    client._servers["flaky"] = MCPServerHandle(name="flaky", transport="stdio")
    client._note_stable_reconnect("flaky")

    pending = list(client._startup_tasks)
    assert len(pending) == 1
    await asyncio.gather(*pending)

    assert recorded == ["slept"]
    assert "flaky" not in client._reconnect_attempts


@pytest.mark.asyncio
async def test_deferred_reset_leaves_budget_when_server_dropped_again(monkeypatch):
    async def immediate_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(mcp_client_module.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(mcp_client_module, "_MCP_RECONNECT_STABLE_SECONDS", 0.0)

    client = MCPClient()
    client._reconnect_attempts["flaky"] = 3
    client._note_stable_reconnect("flaky")
    await asyncio.gather(*list(client._startup_tasks))

    assert client._reconnect_attempts.get("flaky") == 3
