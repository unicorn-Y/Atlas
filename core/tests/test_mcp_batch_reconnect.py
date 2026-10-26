import pytest

from atlas.api.app_services import AppServices
from atlas.api.tools_router import reconnect_failed_mcp_servers


class FakeMCPClient:
    def __init__(self):
        self.servers = [
            {"name": "failed-a", "enabled": True, "state": "failed", "connected": False},
            {"name": "auth-b", "enabled": True, "state": "auth-needed", "connected": False},
            {"name": "healthy", "enabled": True, "state": "connected", "connected": True},
            {"name": "disabled", "enabled": False, "state": "error", "connected": False},
        ]
        self.restarted = []

    def get_runtime_status(self):
        return {"servers": [dict(item) for item in self.servers]}

    async def restart_server(self, name):
        self.restarted.append(name)
        row = next(item for item in self.servers if item["name"] == name)
        if name == "failed-a":
            row.update({"state": "connected", "connected": True})
        else:
            row.update({"state": "failed", "connected": False, "blocking_reason": "test auth required"})

    def get_server_tools(self, name):
        return [object()] if name == "failed-a" else []


@pytest.mark.asyncio
async def test_batch_reconnect_selects_only_enabled_servers_needing_attention():
    mcp = FakeMCPClient()
    result = await reconnect_failed_mcp_servers(AppServices(mcp_client=mcp))

    assert set(mcp.restarted) == {"failed-a", "auth-b"}
    assert result["selected"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["concurrency_limit"] == 3
    rows = {item["name"]: item for item in result["results"]}
    assert rows["failed-a"]["ok"] is True and rows["failed-a"]["tool_count"] == 1
    assert rows["auth-b"]["reason"] == "test auth required"


@pytest.mark.asyncio
async def test_batch_reconnect_returns_empty_result_when_no_server_needs_attention():
    mcp = FakeMCPClient()
    mcp.servers = [mcp.servers[2]]
    result = await reconnect_failed_mcp_servers(AppServices(mcp_client=mcp))

    assert result["selected"] == 0
    assert result["results"] == []
