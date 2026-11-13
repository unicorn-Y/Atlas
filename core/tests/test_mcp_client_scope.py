import pytest

from atlas.tools.mcp_client import MCPClient, ToolInfo

pytestmark = pytest.mark.unit


def test_scoped_client_filters_tool_discovery() -> None:
    client = MCPClient()
    client._tool_index = {
        "alpha__read": ToolInfo("read", "alpha read", {}, "alpha"),
        "beta__read": ToolInfo("read", "beta read", {}, "beta"),
    }

    scoped = client.for_scope(["alpha"])

    assert [tool.qualified_name for tool in scoped.list_tools()] == ["alpha__read"]
    assert [tool["function"]["name"] for tool in scoped.get_tools_for_llm()] == ["alpha__read"]
    assert scoped.get_tool("beta__read") is None


@pytest.mark.asyncio
async def test_scoped_client_refuses_out_of_scope_tool_call(monkeypatch) -> None:
    client = MCPClient()
    calls = []

    async def call_tool(name, arguments=None, **kwargs):
        calls.append(name)
        return {"content": [], "is_error": False}

    monkeypatch.setattr(client, "call_tool", call_tool)
    result = await client.for_scope(["alpha"]).call_tool("beta__write", {"x": 1})

    assert result["is_error"] is True
    assert calls == []


@pytest.mark.asyncio
async def test_scoped_client_filters_resource_operations(monkeypatch) -> None:
    client = MCPClient()
    listed = []
    read = []

    async def list_resources(server_name=None, cursor=None):
        listed.append(server_name)
        return {server_name: {"resources": []}}

    async def read_resource(server_name, uri):
        read.append((server_name, uri))
        return {"contents": [], "is_error": False}

    monkeypatch.setattr(client, "list_resources", list_resources)
    monkeypatch.setattr(client, "read_resource", read_resource)
    scoped = client.for_scope(["alpha"])

    assert await scoped.list_resources() == {"alpha": {"resources": []}}
    assert await scoped.list_resources("beta") == {}
    assert (await scoped.read_resource("beta", "secret://item"))["is_error"] is True
    assert await scoped.read_resource("alpha", "file://item") == {"contents": [], "is_error": False}
    assert listed == ["alpha"]
    assert read == [("alpha", "file://item")]
