"""Tests for Atlas REST API — FastAPI endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from atlas import server
from atlas.memory import MemoryStore
from atlas.server import app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    """Async test client using httpx + ASGI transport with lifespan."""
    import os
    from atlas import config

    monkeypatch.setattr(config, "USER_SETTINGS_PATH", tmp_path / "user-settings.json")
    for key in ("OPENAI_API_BASE", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    old_val = os.environ.get("ATLAS_SCHEDULER_ENABLED")
    os.environ["ATLAS_SCHEDULER_ENABLED"] = "false"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Manually trigger lifespan startup
        from atlas.server import lifespan

        async with lifespan(app):
            yield ac

    # Restore
    if old_val is None:
        os.environ.pop("ATLAS_SCHEDULER_ENABLED", None)
    else:
        os.environ["ATLAS_SCHEDULER_ENABLED"] = old_val


# ---------------------------------------------------------------------------
# Runtime Protocol
# ---------------------------------------------------------------------------

class TestRuntimeProtocol:
    async def test_protocol_version(self, client: AsyncClient) -> None:
        resp = await client.get("/api/runtime/protocol")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "1.2"

    async def test_run_metadata_survives_manager_restart(self, tmp_path) -> None:
        from atlas.server import RunState, RuntimeManager

        db_path = tmp_path / "runtime.db"
        first = RuntimeManager(db_path)
        await first.init()
        run = RunState("persisted-run", "persisted-conversation", "test-model")
        run.next_envelope("run.started", {"status": "running"})
        await first.persist_run(run)
        await first.close()

        restarted = RuntimeManager(db_path)
        await restarted.init()
        recovered = restarted.runs[run.run_id]
        assert recovered.conversation_id == "persisted-conversation"
        assert recovered.model == "test-model"
        assert recovered.sequence == 2
        assert recovered.status == "failed"
        assert recovered.events[-1]["event"] == "run.failed"
        await restarted.close()

    async def test_recovery_is_idempotent_and_never_reexecutes_run(
        self, tmp_path, monkeypatch,
    ) -> None:
        import asyncio
        import aiosqlite
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from atlas import server

        db_path = tmp_path / "runtime.db"
        async with aiosqlite.connect(str(db_path)) as legacy_db:
            await legacy_db.execute("""
                CREATE TABLE runtime_runs (
                    run_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    sequence INTEGER NOT NULL DEFAULT 0,
                    recovery_event TEXT
                )
            """)
            await legacy_db.commit()
        original = server.RuntimeManager(db_path)
        await original.init()
        run = server.RunState("recover-once", "conv-recover", "test-model")
        run.plan_state = {
            "goal": "Recover plan", "subtasks": [{
                "id": "step", "title": "Resume", "verification": "Evidence exists",
            }],
        }
        run.next_envelope("run.started", {"status": "running"})
        await original.persist_run(run)
        await original.close()

        recovered = server.RuntimeManager(db_path)
        await recovered.init()
        first_sequence = recovered.runs[run.run_id].sequence
        assert recovered.runs[run.run_id].plan_state == run.plan_state
        await recovered.close()

        restarted_again = server.RuntimeManager(db_path)
        await restarted_again.init()
        recovered_run = restarted_again.runs[run.run_id]
        assert recovered_run.sequence == first_sequence
        assert [event["event"] for event in recovered_run.events] == ["run.failed"]

        execute = AsyncMock()
        monkeypatch.setattr(server, "runtime_mgr", restarted_again)
        monkeypatch.setattr(server, "model_mgr", SimpleNamespace(current_model="test-model"))
        monkeypatch.setattr(server, "_execute_run", execute)
        try:
            await server._handle_run_start("recovery-connection", {
                "run_id": run.run_id,
                "content": "must not execute again",
                "conversation_id": run.conversation_id,
            })
            await asyncio.sleep(0)
            assert execute.await_count == 0
            assert restarted_again.runs[run.run_id].status == "failed"
        finally:
            restarted_again.disconnect("recovery-connection")
            await restarted_again.close()

    async def test_interrupted_plan_is_persisted_and_resumes_as_new_run(
        self, tmp_path, monkeypatch,
    ) -> None:
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from atlas import server

        db_path = tmp_path / "runtime.db"
        original = server.RuntimeManager(db_path)
        await original.init()
        run = server.RunState("plan-interrupted", "plan-conversation", "test-model")
        run.plan_state = {
            "goal": "Inspect then summarize",
            "subtasks": [{"id": "inspect", "title": "Inspect",
                          "verification": "Files inspected"}],
        }
        await original.persist_run(run)
        await original.close()

        recovered = server.RuntimeManager(db_path)
        await recovered.init()
        prior = recovered.runs[run.run_id]
        assert prior.status == "failed"
        assert prior.plan_state == run.plan_state
        execute = AsyncMock()
        monkeypatch.setattr(server, "runtime_mgr", recovered)
        monkeypatch.setattr(server, "model_mgr", SimpleNamespace(current_model="test-model"))
        monkeypatch.setattr(server, "_execute_run", execute)
        try:
            await server._handle_run_start("resume-connection", {
                "run_id": "plan-resumed",
                "resume_from": run.run_id,
            })
            await asyncio.sleep(0)
            assert execute.await_count == 1
            assert execute.await_args.kwargs["plan_state"] == run.plan_state
            assert execute.await_args.args[2] == "Inspect then summarize"
        finally:
            recovered.disconnect("resume-connection")
            await recovered.close()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    async def test_health(self, client: AsyncClient) -> None:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestAgentCapabilities:
    async def test_discover_and_activate_skill_capability(self, client: AsyncClient) -> None:
        discovered = await client.get("/api/agent/capabilities")

        assert discovered.status_code == 200
        capabilities = discovered.json()["capabilities"]
        skill = next(item for item in capabilities if item["name"] == "skill.coding-discipline")
        assert skill["source"] == "skill"

        invoked = await client.post(
            "/api/agent/capabilities/skill.coding-discipline/invoke",
            json={},
        )

        assert invoked.status_code == 200
        assert invoked.json()["name"] == "skill.coding-discipline"
        assert "## Instructions" in invoked.json()["result"]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestModels:
    async def test_list_models(self, client: AsyncClient) -> None:
        resp = await client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert "current" in data
        assert len(data["models"]) >= 7

    async def test_select_valid_model(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/models/select",
            json={"model": "gpt-4o"},
        )
        assert resp.status_code == 200
        assert resp.json()["model"] == "gpt-4o"

    async def test_select_invalid_model(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/models/select",
            json={"model": "nonexistent"},
        )
        assert resp.status_code == 400

    async def test_configuration_persists_provider_and_hides_secret(self, client: AsyncClient) -> None:
        saved = await client.put("/api/settings/configuration", json={
            "gateway_base_url": "https://api.example.test/v1",
            "api_key": "test-secret-value",
        })
        assert saved.status_code == 200
        assert saved.json()["api_key_configured"] is True
        assert saved.json()["gateway_base_url"] == "https://api.example.test/v1"
        assert "api_key" not in saved.json()

        loaded = await client.get("/api/settings/configuration")
        assert loaded.json()["api_key_configured"] is True
        assert "test-secret-value" not in loaded.text
        from atlas.models import ModelManager

        restarted = ModelManager()
        assert restarted.gateway_base_url == "https://api.example.test/v1"
        assert restarted.api_key_configured is True

    async def test_configuration_rejects_invalid_url(self, client: AsyncClient) -> None:
        response = await client.put("/api/settings/configuration", json={"gateway_base_url": "file:///tmp"})
        assert response.status_code == 400

    async def test_custom_model_persists_and_duplicate_is_rejected(self, client: AsyncClient) -> None:
        model = {"id": "custom-test", "name": "Custom Test", "provider": "openai", "litellm_model": "openai/custom-test"}
        response = await client.post("/api/models/custom", json=model)
        assert response.status_code == 200
        assert any(item["id"] == "custom-test" for item in response.json()["models"])
        from atlas.models import ModelManager

        assert any(item["id"] == "custom-test" for item in ModelManager().list_models())
        duplicate = await client.post("/api/models/custom", json=model)
        assert duplicate.status_code == 409

    async def test_connection_test_uses_litellm_and_does_not_change_selection(self, client: AsyncClient, monkeypatch) -> None:
        from atlas.server import model_mgr

        call = {}

        async def fake_completion(**kwargs):
            call.update(kwargs)
            return object()

        monkeypatch.setattr("litellm.acompletion", fake_completion)
        selected_before = model_mgr.current_model
        response = await client.post("/api/settings/test-connection", json={"model": "gpt-4o"})
        assert response.json()["ok"] is True
        assert call["model"] == "openai/gpt-4o"
        assert model_mgr.current_model == selected_before


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

class TestConversations:
    async def test_list_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/conversations")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_conversation(self, client: AsyncClient) -> None:
        created = await client.post("/api/conversations", json={"title": "Frontend session"})

        assert created.status_code == 200
        conversation = created.json()
        assert conversation["title"] == "Frontend session"
        assert conversation["id"]
        listed = await client.get("/api/conversations")
        assert any(item["id"] == conversation["id"] for item in listed.json())

    async def test_create_conversation_uses_default_title(self, client: AsyncClient) -> None:
        created = await client.post("/api/conversations", json={})

        assert created.status_code == 200
        assert created.json()["title"] == "New Conversation"

    async def test_get_messages_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/conversations/nonexistent/messages")
        assert resp.status_code == 404

    async def test_get_conversation_messages(self, client: AsyncClient) -> None:
        from atlas.server import memory

        assert memory is not None
        conversation_id = await memory.create_conversation("History test")
        await memory.save_message(conversation_id, "user", "hello")
        await memory.save_message(conversation_id, "assistant", "hi")

        resp = await client.get(f"/api/conversations/{conversation_id}/messages")

        assert resp.status_code == 200
        messages = resp.json()
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert [message["content"] for message in messages] == ["hello", "hi"]
        assert all({"id", "role", "content", "created_at"} <= message.keys() for message in messages)

    async def test_update_conversation_404(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/conversations/nonexistent",
            json={"title": "New Title"},
        )
        assert resp.status_code == 404

    async def test_delete_conversation_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/conversations/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    async def test_search_requires_query(self, client: AsyncClient) -> None:
        resp = await client.get("/api/search")
        assert resp.status_code == 422  # missing required 'q' param

    async def test_search_empty_results(self, client: AsyncClient) -> None:
        resp = await client.get("/api/search", params={"q": "xyznonexistent"})
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

class TestFacts:
    async def test_list_facts_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/facts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_and_list_fact(self, client: AsyncClient) -> None:
        # Create
        resp = await client.post(
            "/api/facts",
            json={"key": "test_key", "value": "test_value", "category": "test"},
        )
        assert resp.status_code == 200
        assert resp.json()["key"] == "test_key"

        # List
        resp = await client.get("/api/facts", params={"category": "test"})
        assert resp.status_code == 200
        facts = resp.json()
        assert len(facts) >= 1
        assert any(f["key"] == "test_key" for f in facts)

    async def test_delete_fact(self, client: AsyncClient) -> None:
        # Create first
        await client.post(
            "/api/facts",
            json={"key": "to_delete", "value": "temp"},
        )
        # Delete
        resp = await client.delete("/api/facts/to_delete")
        assert resp.status_code == 200

        # Delete again should 404
        resp = await client.delete("/api/facts/to_delete")
        assert resp.status_code == 404

    async def test_memory_candidate_requires_api_approval(
        self, client: AsyncClient, tmp_path
    ) -> None:
        original_memory = server.memory
        await original_memory.close()
        isolated_memory = MemoryStore(db_path=tmp_path / "candidate-review.db")
        await isolated_memory.init()
        server.memory = isolated_memory
        try:
            conversation_id = await isolated_memory.create_conversation()
            await isolated_memory.save_message(
                conversation_id, "user", "I prefer concise answers."
            )
            [candidate] = await isolated_memory.extract_conversation_candidates(
                conversation_id
            )

            listed = await client.get(
                "/api/memory/candidates", params={"status": "pending"}
            )
            assert listed.status_code == 200
            assert listed.json()[0]["id"] == candidate["id"]
            assert await isolated_memory.get_fact("user_preference") is None

            approved = await client.post(
                f"/api/memory/candidates/{candidate['id']}/approve"
            )
            assert approved.status_code == 200
            assert await isolated_memory.get_fact("user_preference") == "concise answers"
        finally:
            await isolated_memory.close()
            server.memory = original_memory


# ---------------------------------------------------------------------------
# MCP Server Management
# ---------------------------------------------------------------------------

class TestMCPServerManagement:
    async def test_list_mcp_servers_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/mcp/servers")
        assert resp.status_code == 200
        data = resp.json()
        assert "servers" in data
        assert isinstance(data["servers"], list)

    async def test_list_tools_exposes_connected_server_tools(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from atlas import server
        from atlas.tools.mcp_client import MCPClient, MCPServerHandle, ToolInfo

        mcp = MCPClient()
        tool = ToolInfo(
            name="read_file",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            server_name="filesystem",
        )
        mcp._servers["filesystem"] = MCPServerHandle(
            name="filesystem", transport="stdio", tools=[tool]
        )
        mcp._tool_index[tool.qualified_name] = tool
        monkeypatch.setattr(server, "mcp_client", mcp)

        resp = await client.get("/api/tools")

        assert resp.status_code == 200
        assert resp.json() == {
            "servers": ["filesystem"],
            "tool_count": 1,
            "tools": [{
                "name": "filesystem__read_file",
                "description": "Read a file",
                "server": "filesystem",
                "input_schema": tool.input_schema,
            }],
        }

    async def test_add_server_invalid_transport(self, client: AsyncClient) -> None:
        """Adding a server with bad config should return 500."""
        resp = await client.post("/api/mcp/servers", json={
            "name": "bad-server",
            "transport": "stdio",
            "command": "nonexistent-binary-xyz",
        })
        assert resp.status_code == 500

    async def test_remove_server_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/mcp/servers/nonexistent")
        assert resp.status_code == 404

    async def test_restart_server_404(self, client: AsyncClient) -> None:
        resp = await client.post("/api/mcp/servers/nonexistent/restart")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

class TestKnowledge:
    async def test_list_knowledge_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/knowledge")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_add_and_search_knowledge(self, client: AsyncClient) -> None:
        # Add entry
        resp = await client.post("/api/knowledge", json={
            "content": "Atlas uses LangGraph for agent orchestration",
            "source": "docs",
            "category": "architecture",
        })
        assert resp.status_code == 200
        entry = resp.json()
        assert "id" in entry
        assert entry["content"] == "Atlas uses LangGraph for agent orchestration"

        # Search
        resp = await client.get("/api/knowledge/search", params={"q": "LangGraph"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert any("LangGraph" in r["content"] for r in results)

    async def test_delete_knowledge(self, client: AsyncClient) -> None:
        # Create
        resp = await client.post("/api/knowledge", json={
            "content": "Temporary knowledge entry",
        })
        entry_id = resp.json()["id"]

        # Delete
        resp = await client.delete(f"/api/knowledge/{entry_id}")
        assert resp.status_code == 200

        # Delete again -> 404
        resp = await client.delete(f"/api/knowledge/{entry_id}")
        assert resp.status_code == 404

    async def test_search_requires_query(self, client: AsyncClient) -> None:
        resp = await client.get("/api/knowledge/search")
        assert resp.status_code == 422


class TestWebSocketProtocol:
    """Test the Runtime Event Protocol 1.2 WebSocket endpoint.

    Uses starlette's built-in WebSocket test client (via pytest + anyio).
    """

    def test_tool_events_map_to_runtime_events(self) -> None:
        from atlas.server import _map_tool_runtime_event

        assert _map_tool_runtime_event({
            "type": "tool_call", "id": "tc-1", "name": "filesystem__read_file",
            "arguments": {"path": "README.md"},
        }) == (
            "tool.started",
            {
                "tool_call_id": "tc-1",
                "name": "filesystem__read_file",
                "arguments": {"path": "README.md"},
            },
        )
        assert _map_tool_runtime_event({
            "type": "tool_result", "id": "tc-1", "name": "filesystem__read_file",
            "content": [{"type": "text", "text": "# Atlas"}], "is_error": False,
        }) == (
            "tool.completed",
            {
                "tool_call_id": "tc-1",
                "name": "filesystem__read_file",
                "result": [{"type": "text", "text": "# Atlas"}],
                "is_error": False,
            },
        )
        assert _map_tool_runtime_event({"type": "chunk", "content": "text"}) is None

    async def test_backend_failure_emits_terminal_protocol_event(self, monkeypatch) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from atlas import server

        class Socket:
            def __init__(self) -> None:
                self.events: list[dict] = []

            async def send_json(self, event: dict) -> None:
                self.events.append(event)

        socket = Socket()
        conn_id = "backend-failure-test"
        run = server.RunState("backend-failure-run", "conv-1", "test-model")
        memory_mock = SimpleNamespace(save_message=AsyncMock(side_effect=OSError("database unavailable")))
        monkeypatch.setattr(server, "memory", memory_mock)
        monkeypatch.setattr(server, "orchestrator", SimpleNamespace())
        monkeypatch.setitem(server.runtime_mgr.connections, conn_id, socket)

        try:
            await server._execute_run(conn_id, run, "hello", None)
        finally:
            server.runtime_mgr.connections.pop(conn_id, None)

        failed = next(event for event in socket.events if event["event"] == "run.failed")
        assert run.status == "failed"
        assert failed["data"]["category"] == "backend"
        assert failed["data"]["detail"] == "Unable to save user message: database unavailable"

    async def test_tool_failure_reaches_runtime_event_and_run_completes(self, monkeypatch) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from atlas import server

        class Socket:
            def __init__(self) -> None:
                self.events: list[dict] = []

            async def send_json(self, event: dict) -> None:
                self.events.append(event)

        async def events(**kwargs):
            yield {
                "type": "tool_result", "id": "tc-1", "name": "fs__read",
                "content": [{"type": "text", "text": "Tool call failed: tool timed out"}],
                "is_error": True, "error_category": "tool",
            }
            yield {"type": "done"}

        socket = Socket()
        conn_id = "tool-failure-test"
        run = server.RunState("tool-failure-run", "conv-2", "test-model")
        monkeypatch.setattr(server, "memory", SimpleNamespace(save_message=AsyncMock()))
        monkeypatch.setattr(server, "orchestrator", SimpleNamespace(run=events))
        monkeypatch.setitem(server.runtime_mgr.connections, conn_id, socket)

        try:
            await server._execute_run(conn_id, run, "read", None)
        finally:
            server.runtime_mgr.connections.pop(conn_id, None)

        tool_event = next(event for event in socket.events if event["event"] == "tool.completed")
        assert tool_event["data"]["is_error"] is True
        assert tool_event["data"]["error_category"] == "tool"
        assert any(event["event"] == "run.completed" for event in socket.events)
        assert run.status == "completed"

    async def test_run_start_emits_agent_events(self, monkeypatch) -> None:
        """A run.start message should produce agent_event envelopes."""
        import json as _json
        from types import SimpleNamespace
        from starlette.testclient import TestClient
        from atlas import server
        from atlas.server import app as _app

        async def fake_run(**kwargs):
            yield {"type": "chunk", "content": "Hello"}
            yield {"type": "done"}

        # Use sync TestClient for WebSocket (starlette limitation)
        with TestClient(_app) as tc:
            monkeypatch.setattr(server, "orchestrator", SimpleNamespace(run=fake_run))
            with tc.websocket_connect("/ws/chat") as ws:
                ws.send_text(_json.dumps({
                    "type": "run.start",
                    "run_id": "test-run-1",
                    "content": "Hello Atlas",
                    "conversation_id": "test-conv-1",
                }))

                # Collect events until run.completed or run.failed
                events: list[dict] = []
                for _ in range(100):  # safety limit
                    raw = ws.receive_text()
                    evt = _json.loads(raw)
                    events.append(evt)
                    if evt.get("event") in ("run.completed", "run.failed"):
                        break

                # All events must be agent_event envelopes
                for evt in events:
                    assert evt["type"] == "agent_event", f"Expected agent_event, got {evt}"
                    assert evt["run_id"] == "test-run-1"
                    assert "event_id" in evt
                    assert "sequence" in evt
                    assert "timestamp" in evt
                    assert "event" in evt
                    assert "data" in evt

                # Sequences must be monotonically increasing
                seqs = [e["sequence"] for e in events]
                assert seqs == sorted(seqs)
                assert len(set(seqs)) == len(seqs)  # all unique

                # First event should be run.started
                assert events[0]["event"] == "run.started"

                # Last event should be run.completed or run.failed
                assert events[-1]["event"] in ("run.completed", "run.failed")

    async def test_resume_routes_new_events_to_reconnected_socket(self, monkeypatch) -> None:
        from atlas import server

        class Socket:
            def __init__(self) -> None:
                self.events: list[dict] = []

            async def send_json(self, event: dict) -> None:
                self.events.append(event)

        old_socket = Socket()
        new_socket = Socket()
        run = server.RunState("reconnect-run", "conv-reconnect", "test-model")
        run.next_envelope("run.started", {"status": "running"})
        monkeypatch.setitem(server.runtime_mgr.runs, run.run_id, run)
        monkeypatch.setitem(server.runtime_mgr.connections, "old-connection", old_socket)
        monkeypatch.setitem(server.runtime_mgr.connections, "new-connection", new_socket)
        monkeypatch.setitem(server.runtime_mgr.conn_runs, "old-connection", run.run_id)

        await server._handle_resume("new-connection", {"run_id": run.run_id, "after_sequence": 1})
        next_event = run.next_envelope("message.delta", {"content": "continued"})
        await server.runtime_mgr.send_run(run, next_event, fallback_conn_id="old-connection")

        assert old_socket.events == []
        assert new_socket.events == [next_event]

    async def test_duplicate_run_start_reuses_existing_run_and_task(self, monkeypatch) -> None:
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from atlas import server

        run_id = "duplicate-start-run"
        gate = asyncio.Event()
        async def blocked_run(*args, **kwargs):
            await gate.wait()

        execute = AsyncMock(side_effect=blocked_run)
        monkeypatch.setattr(server, "model_mgr", SimpleNamespace(current_model="test-model"))
        monkeypatch.setattr(server, "_execute_run", execute)

        try:
            await server._handle_run_start("first-connection", {
                "run_id": run_id, "content": "hello", "conversation_id": "conv-duplicate",
            })
            original = server.runtime_mgr.runs[run_id]
            original_task = original.task

            await server._handle_run_start("second-connection", {
                "run_id": run_id, "content": "hello", "conversation_id": "conv-duplicate",
            })
            await asyncio.sleep(0)

            assert server.runtime_mgr.runs[run_id] is original
            assert server.runtime_mgr.runs[run_id].task is original_task
            assert execute.await_count == 1
            assert server.runtime_mgr.conn_runs["second-connection"] == run_id
        finally:
            gate.set()
            task = server.runtime_mgr.runs.pop(run_id, None)
            if task and task.task:
                task.task.cancel()
                await asyncio.gather(task.task, return_exceptions=True)
            server.runtime_mgr.conn_runs.pop("first-connection", None)
            server.runtime_mgr.conn_runs.pop("second-connection", None)

    async def test_resume_of_missing_run_emits_terminal_failure(self, monkeypatch) -> None:
        from atlas import server

        class Socket:
            def __init__(self) -> None:
                self.events: list[dict] = []

            async def send_json(self, event: dict) -> None:
                self.events.append(event)

        socket = Socket()
        monkeypatch.setitem(server.runtime_mgr.connections, "recovered-connection", socket)

        await server._handle_resume("recovered-connection", {
            "run_id": "lost-run", "after_sequence": 4,
        })

        assert len(socket.events) == 1
        assert socket.events[0]["run_id"] == "lost-run"
        assert socket.events[0]["sequence"] == 5
        assert socket.events[0]["event"] == "run.failed"
        assert socket.events[0]["data"]["category"] == "interrupted"
