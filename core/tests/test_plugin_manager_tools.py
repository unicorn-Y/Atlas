from __future__ import annotations

import pytest

from atlas.engine.kernel.tools import READ_ONLY_TOOLS, kernel_tool_schemas
from atlas.tools.plugin_marketplace import execute_plugin_manager_tool

pytestmark = pytest.mark.unit

TOOL_NAMES = {
    "list_plugins", "get_plugin", "list_plugin_marketplaces",
    "list_available_plugins_to_install", "request_plugin_install", "update_plugin",
    "set_plugin_enabled", "uninstall_plugin",
}


class _Runtime:
    def __init__(self):
        self.calls = []
        self.enabled = True

    def discover(self):
        return [{"name": "demo", "description": "Demo plugin", "enabled": self.enabled}]

    def list_marketplaces(self):
        return [{"name": "official"}]

    def list_marketplace_plugins(self, marketplace):
        return [{"name": "available", "description": "Available", "marketplace": marketplace}]

    def install_marketplace_plugin(self, marketplace, plugin_name):
        self.calls.append(("install", marketplace, plugin_name))
        return {"name": plugin_name}

    def update(self, plugin_name):
        self.calls.append(("update", plugin_name))
        return {"name": plugin_name}

    async def set_enabled(self, plugin_name, enabled):
        self.calls.append(("enabled", plugin_name, enabled))
        self.enabled = enabled
        return True

    def uninstall(self, plugin_name):
        self.calls.append(("uninstall", plugin_name))
        return True

    async def load_all(self, **_kwargs):
        self.calls.append(("load_all",))
        return {
            "loaded": ["demo"] if self.enabled else [],
            "skipped": [] if self.enabled else [{"name": "demo", "reason": "disabled"}],
            "errors": {},
        }

    def validate(self, _path):
        return {"valid": True}


class _Agent:
    def __init__(self):
        self._plugin_runtime = _Runtime()
        self.hooks = None
        self._mcp = None
        self.capabilities = None


def test_plugin_manager_exposes_eight_typed_actions():
    schemas = kernel_tool_schemas(include_workflow=False)
    declared = {item["function"]["name"] for item in schemas}

    assert TOOL_NAMES <= declared
    assert {"list_plugins", "get_plugin", "list_plugin_marketplaces",
            "list_available_plugins_to_install"} <= READ_ONLY_TOOLS


@pytest.mark.asyncio
async def test_plugin_manager_write_action_fails_closed_without_approval():
    agent = _Agent()

    cases = (
        ("request_plugin_install", {"marketplace": "official", "plugin_name": "new"}),
        ("update_plugin", {"plugin_name": "demo"}),
        ("set_plugin_enabled", {"plugin_name": "demo", "enabled": False}),
        ("uninstall_plugin", {"plugin_name": "demo"}),
    )
    for name, args in cases:
        result = await execute_plugin_manager_tool(name, args, agent=agent, approve=None)
        assert result["outcome"] == "denied"
    assert agent._plugin_runtime.calls == []


@pytest.mark.asyncio
async def test_plugin_manager_read_actions_return_runtime_inventory_without_approval():
    agent = _Agent()

    listed = await execute_plugin_manager_tool("list_plugins", {}, agent=agent)
    detail = await execute_plugin_manager_tool(
        "get_plugin", {"plugin_name": "demo"}, agent=agent,
    )
    marketplaces = await execute_plugin_manager_tool(
        "list_plugin_marketplaces", {}, agent=agent,
    )
    available = await execute_plugin_manager_tool(
        "list_available_plugins_to_install", {}, agent=agent,
    )

    assert listed["data"]["plugins"][0]["name"] == "demo"
    assert detail["data"]["plugin"]["name"] == "demo"
    assert marketplaces["data"]["marketplaces"] == [{"name": "official"}]
    assert available["data"]["plugins"][0]["name"] == "available"


@pytest.mark.asyncio
async def test_read_only_mode_allows_listing_and_rejects_writes():
    agent = _Agent()

    listing = await execute_plugin_manager_tool(
        "list_available_plugins_to_install", {}, agent=agent, permission_mode="read_only",
    )
    update = await execute_plugin_manager_tool(
        "update_plugin", {"plugin_name": "demo"}, agent=agent,
        permission_mode="read_only", approve=lambda *_: "allow",
    )

    assert listing["outcome"] == "completed"
    assert update["outcome"] == "denied"
    assert agent._plugin_runtime.calls == []


@pytest.mark.asyncio
async def test_danger_full_access_allows_plugin_management_write_without_prompt():
    agent = _Agent()

    result = await execute_plugin_manager_tool(
        "update_plugin", {"plugin_name": "demo"}, agent=agent,
        permission_mode="danger-full-access", approve=None,
    )

    assert result["outcome"] == "completed"
    assert ("update", "demo") in agent._plugin_runtime.calls


@pytest.mark.asyncio
async def test_each_plugin_manager_write_action_uses_per_call_approval():
    agent = _Agent()
    approvals = []

    async def approve(name, args):
        approvals.append((name, dict(args)))
        return "allow"

    for name, args in (
        ("request_plugin_install", {"marketplace": "official", "plugin_name": "new"}),
        ("update_plugin", {"plugin_name": "demo"}),
        ("set_plugin_enabled", {"plugin_name": "demo", "enabled": False}),
        ("uninstall_plugin", {"plugin_name": "demo"}),
    ):
        result = await execute_plugin_manager_tool(name, args, agent=agent, approve=approve)
        assert result["outcome"] == "completed"

    assert [name for name, _args in approvals] == [
        "request_plugin_install", "update_plugin", "set_plugin_enabled", "uninstall_plugin",
    ]
    assert all(args for _name, args in approvals)
    assert {call[0] for call in agent._plugin_runtime.calls} >= {
        "install", "update", "enabled", "uninstall", "load_all",
    }


@pytest.mark.asyncio
async def test_plugin_enable_toggle_reports_runtime_application_without_restart():
    agent = _Agent()

    result = await execute_plugin_manager_tool(
        "set_plugin_enabled", {"plugin_name": "demo", "enabled": False},
        agent=agent, approve=lambda *_: "allow",
    )

    assert result["data"]["applied"] is True
    assert result["data"]["restart_required"] is False
