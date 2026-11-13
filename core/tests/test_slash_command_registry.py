from __future__ import annotations

import pytest

from atlas.runtime.commands import CommandInvocationStore, SlashCommandRegistry

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_registered_slash_command_runs_and_appends_run_done_events(tmp_path) -> None:
    log = CommandInvocationStore(tmp_path / "commands.sqlite3")
    registry = SlashCommandRegistry()
    registry.register(
        name="audit", description="Audit a target", input={"required": ["target"]},
        handler=lambda args: {"audited": args["target"]},
    )

    result = await registry.invoke("audit", {"target": "core"}, event_store=log)

    assert result == {"audited": "core"}
    events = log.events()
    assert [event["event"] for event in events] == ["command/run", "command/done"]
    assert events[0]["invocation_id"] == events[1]["invocation_id"]
    assert events[0]["command_name"] == "audit"
    assert events[1]["status"] == "ok"


@pytest.mark.asyncio
async def test_command_disposer_unregisters_only_its_registration(tmp_path) -> None:
    registry = SlashCommandRegistry()
    dispose = registry.register("audit", "Audit", {}, lambda _args: None)
    assert registry.list()[0]["name"] == "audit"

    dispose()

    assert registry.list() == []
    with pytest.raises(KeyError, match="audit"):
        await registry.invoke("audit", {}, event_store=CommandInvocationStore(tmp_path / "log.sqlite3"))


def test_command_invocation_events_are_append_only(tmp_path) -> None:
    log = CommandInvocationStore(tmp_path / "commands.sqlite3")
    invocation_id = log.command_run("audit", {"target": "core"})
    log.command_done(invocation_id, status="ok", result={"audited": "core"})

    with pytest.raises(Exception):
        log._connect().execute("DELETE FROM command_invocation_events")
