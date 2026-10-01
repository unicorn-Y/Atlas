from __future__ import annotations

import asyncio
from types import SimpleNamespace
import time
from unittest.mock import MagicMock

import pytest

from atlas.agent import AgentOrchestrator
from atlas.engine.hermes_runtime import HermesRuntime
from atlas.memory import MemoryStore
from atlas.tools.local_execution import LocalExecutionRuntime
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, write_hermes_home


async def _run_title_turn(
    tmp_path, monkeypatch, *, starting_title="New Conversation",
    delayed_title=False, runtime_events=None, rename_after_run=False,
):
    class FixtureConfig(dict):
        db_path = tmp_path / "config.db"

    monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
        "tools.servers": {}, "tools.auto_start": [], "agent.engine": "hermes",
        "agent.verify_before_stop": True,
    }))
    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path / "atlas-data")
    monkeypatch.setattr("atlas.config.load_user_settings", lambda: {"agent_engine": "hermes"})
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "atlas-data"))
    def title_response(_request):
        if delayed_title:
            time.sleep(1.0)
        return Text("Generated session title")

    with FakeLLMServer([Text("Session work completed")], aux=title_response) as fake:
        home = tmp_path / "atlas-data" / "engine"
        write_hermes_home(
            home, fake.base_url,
            extra_config=(
                "auxiliary:\n"
                "  title_generation:\n"
                "    provider: custom\n"
                "    model: openai/parent-model\n"
                f"    base_url: {fake.base_url}\n"
                "    api_key: sk-fake-e2e\n"
            ),
        )
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="parent-model", current_litellm_model="openai/parent-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{
                "id": "parent-model", "litellm_model": "openai/parent-model",
                "max_output_tokens": 256,
            }],
        )
        memory = MemoryStore(db_path=tmp_path / "atlas-memory.sqlite3")
        await memory.init()
        conversation_id = await memory.create_conversation(starting_title)
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        local = LocalExecutionRuntime()
        agent = AgentOrchestrator(models, memory, mcp_client=mcp, local_execution=local)
        run_finished = False

        async def on_runtime_event(event):
            runtime_events.append({**event, "after_run": run_finished})

        try:
            events = [event async for event in agent.run(
                "Explain the title lifecycle for this conversation", conversation_id,
                workspace=str(tmp_path),
                runtime_event_callback=on_runtime_event if runtime_events is not None else None,
            )]
            run_finished = True
            if rename_after_run:
                await memory.update_conversation_title(conversation_id, "User chosen during title upgrade")
            if delayed_title:
                deadline = asyncio.get_running_loop().time() + 3
                while asyncio.get_running_loop().time() < deadline:
                    current = await memory.get_conversation(conversation_id)
                    if current["title"] == "Generated session title" and runtime_events:
                        break
                    await asyncio.sleep(0.03)
            return events, fake, await memory.get_conversation(conversation_id), memory
        finally:
            await local.shutdown()
            await memory.close()


@pytest.mark.asyncio
async def test_real_hermes_title_callback_updates_atlas_and_exposes_upgrade(tmp_path, monkeypatch):
    events, fake, conversation, _memory = await _run_title_turn(tmp_path, monkeypatch)

    title_events = [event for event in events if event.get("type") == "session.title"]
    assert any(event["title_source"] == "derived" and event["accepted"] for event in title_events)
    assert any(event["title_source"] == "llm" and event["accepted"] for event in title_events)
    assert fake.main_requests() and fake.aux_requests()
    assert conversation["title"] == title_events[-1]["title"]


@pytest.mark.asyncio
async def test_real_hermes_title_callback_preserves_manual_atlas_title(tmp_path, monkeypatch):
    events, _fake, conversation, _memory = await _run_title_turn(
        tmp_path, monkeypatch, starting_title="User chosen title",
    )

    title_events = [event for event in events if event.get("type") == "session.title"]
    assert title_events
    assert not any(event["accepted"] for event in title_events)
    assert conversation["title"] == "User chosen title"


@pytest.mark.asyncio
async def test_late_aux_title_updates_atlas_and_publishes_after_main_run(tmp_path, monkeypatch):
    published = []
    events, fake, conversation, _memory = await _run_title_turn(
        tmp_path, monkeypatch, delayed_title=True, runtime_events=published,
    )

    assert any(event.get("type") == "done" for event in events)
    assert fake.main_requests() and fake.aux_requests()
    assert conversation["title"] == "Generated session title"
    assert any(
        event.get("type") == "session.title" and event.get("accepted") is True
        and event.get("after_run") is True
        for event in published
    )


@pytest.mark.asyncio
async def test_late_aux_title_does_not_overwrite_manual_rename(tmp_path, monkeypatch):
    published = []
    _events, fake, conversation, _memory = await _run_title_turn(
        tmp_path, monkeypatch, delayed_title=True, runtime_events=published,
        rename_after_run=True,
    )

    assert fake.main_requests() and fake.aux_requests()
    assert conversation["title"] == "User chosen during title upgrade"
    assert any(
        event.get("type") == "session.title" and event.get("title_source") == "llm"
        and event.get("accepted") is False and event.get("after_run") is True
        for event in published
    )
