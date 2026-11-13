"""MCP server instructions belong to the server, not to every one of its tools.

They used to be pasted into each tool's ``description`` inside
``get_tools_for_llm()``. With an 8 KB instruction block and 20 tools that is
160 KB of identical text on every single request — and because a tokenizer sees
the same paragraph 20 times, it crowds out the tool's own description.

The fix is one prompt section plus a short pointer per tool. These tests pin
both halves, and the robustness rule that made the old code worse than it
looked: only a real string counts as instructions, because ``str()`` on some
non-string object produces repr text that would be injected as server guidance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from atlas.tools.mcp_client import MCPClient, MCPServerConfig

pytestmark = pytest.mark.unit


def _mock_tool(name: str, description: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.input_schema = {"type": "object", "properties": {}}
    return tool


async def _connect(client: MCPClient, *, instructions, tools: list[MagicMock]) -> None:
    session = AsyncMock()
    init = MagicMock(protocol_version="2025-03-26", server_info={"name": "srv"})
    # Only set the attribute this test cares about; leaving it out is what the
    # old ``str(getattr(...))`` path mishandled.
    if instructions is not None:
        init.instructions = instructions
    else:
        del init.instructions
        init.configure_mock(**{"instructions": None})
    session.initialize.return_value = init
    session.list_tools.return_value = MagicMock(tools=tools)

    async def connect_stdio(config, handle):
        handle.session = session

    with patch.object(client, "_connect_stdio", side_effect=connect_stdio):
        await client._connect_server(MCPServerConfig(name="srv"))


@pytest.mark.asyncio
async def test_instructions_are_not_inlined_into_tool_descriptions():
    client = MCPClient()
    long_text = "ALWAYS use absolute paths. " * 100
    await _connect(client, instructions=long_text, tools=[_mock_tool("read", "Read a file")])

    schema = client.get_tools_for_llm()[0]["function"]

    assert schema["description"].startswith("See the `MCP server: srv` prompt section")
    assert "Read a file" in schema["description"]
    # The whole point: the block is not repeated here.
    assert long_text.strip() not in schema["description"]
    assert len(schema["description"]) < 400


@pytest.mark.asyncio
async def test_tool_description_shrink_is_proportional_to_instruction_size():
    """A bigger instruction block must not make the tool schema bigger."""
    small = MCPClient()
    large = MCPClient()
    await _connect(small, instructions="short", tools=[_mock_tool("read", "Read a file")])
    await _connect(large, instructions="x" * 8000, tools=[_mock_tool("read", "Read a file")])

    small_len = len(small.get_tools_for_llm()[0]["function"]["description"])
    large_len = len(large.get_tools_for_llm()[0]["function"]["description"])

    assert large_len == small_len


@pytest.mark.asyncio
async def test_instructions_are_available_once_for_the_prompt_section():
    client = MCPClient()
    text = "Use this server for filesystem work."
    await _connect(client, instructions=text, tools=[_mock_tool("read", "Read a file")])

    rows = client.get_server_instructions()

    assert rows == [("srv", text)]


@pytest.mark.asyncio
async def test_a_server_without_instructions_contributes_no_section():
    client = MCPClient()
    await _connect(client, instructions="", tools=[_mock_tool("read", "Read a file")])

    assert client.get_server_instructions() == []
    # And with no instructions, the tool description is left untouched.
    assert client.get_tools_for_llm()[0]["function"]["description"] == "Read a file"


@pytest.mark.asyncio
async def test_non_string_instructions_are_ignored_not_stringified():
    """``str()`` on a non-string yields repr text; that must never become guidance."""
    client = MCPClient()
    await _connect(client, instructions=MagicMock(), tools=[_mock_tool("read", "Read a file")])

    assert client.get_server_instructions() == []
    assert client.get_tools_for_llm()[0]["function"]["description"] == "Read a file"


@pytest.mark.asyncio
async def test_instructions_are_ordered_by_server_name_for_a_stable_prompt():
    client = MCPClient()
    for name in ("zeta", "alpha"):
        session = AsyncMock()
        init = MagicMock(protocol_version="2025-03-26", server_info={"name": name})
        init.instructions = f"guidance for {name}"
        session.initialize.return_value = init
        session.list_tools.return_value = MagicMock(tools=[_mock_tool("t", "d")])

        async def connect_stdio(config, handle, _session=session):
            handle.session = _session

        with patch.object(client, "_connect_stdio", side_effect=connect_stdio):
            await client._connect_server(MCPServerConfig(name=name))

    assert [name for name, _ in client.get_server_instructions()] == ["alpha", "zeta"]
