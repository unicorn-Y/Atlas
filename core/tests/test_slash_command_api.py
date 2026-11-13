from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from atlas import server
from atlas.runtime.commands import CommandInvocationStore, SlashCommandRegistry

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_plugin_slash_command_is_listed_and_invoked_without_rendering_prompt(tmp_path) -> None:
    registry = SlashCommandRegistry()
    registry.register(
        "audit", "Audit a target", {"type": "object", "required": ["target"]},
        lambda args: {"audited": args["target"]},
    )
    services = server.app.state.services
    previous = services.slash_command_registry
    services.slash_command_registry = registry
    try:
        async with AsyncClient(
            transport=ASGITransport(app=server.app), base_url="http://test",
        ) as client:
            listing = await client.get("/api/commands")
            command = next(item for item in listing.json()["commands"] if item["source"] == "plugin-handler")
            invoked = await client.post("/api/commands/invoke", json={
                "id": command["id"], "arguments": {"target": "core"},
            })
        assert listing.status_code == 200
        assert command["input"] == {"type": "object", "required": ["target"]}
        assert invoked.status_code == 200
        assert invoked.json()["result"] == {"audited": "core"}
        log = CommandInvocationStore(server.get_config().db_path.parent / "command-invocations.sqlite3")
        events = log.events(invoked.json()["invocation_id"])
        assert [event["event"] for event in events] == ["command/run", "command/done"]
    finally:
        services.slash_command_registry = previous
