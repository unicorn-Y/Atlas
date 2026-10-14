"""Tests for Atlas REST API — FastAPI endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from atlas import server
from atlas.server import app


@pytest.fixture(autouse=True)
def isolated_atlas_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep server tests off machine-local config and external MCP processes."""
    from atlas import config

    data_root = tmp_path / "atlas-data"
    config_path = tmp_path / "config" / "atlas.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "[scheduler]\nenabled = false\n\n[tools]\nauto_start = []\n\n"
        "[computer_use]\npermission_mode = \"full_access\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "DATA_ROOT", data_root)
    monkeypatch.setattr(config, "USER_SETTINGS_PATH", data_root / "data" / "user-settings.json")
    monkeypatch.setattr(config, "_config", None)


@pytest.fixture(autouse=True)
def restore_app_services():
    """Snapshot ``app.state.services`` around every test.

    Several tests swap fakes directly into the shared AppServices container
    (``server.app.state.services.<field> = ...``) instead of using monkeypatch.
    Without a restore, live service instances and fakes leak into later tests
    in this file and into standalone files that run afterwards (which assume
    unset container fields and patch only ``atlas.server`` module globals).
    """
    from dataclasses import fields

    from atlas.api.app_services import AppServices

    services = app.state.services
    snapshot = {f.name: getattr(services, f.name) for f in fields(AppServices)}
    yield
    for field in fields(AppServices):
        setattr(services, field.name, snapshot[field.name])


@pytest.fixture
async def client(monkeypatch):
    """Async test client using httpx + ASGI transport with lifespan."""
    import os
    for key in ("OPENAI_API_BASE", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    old_val = os.environ.get("ATLAS_SCHEDULER_ENABLED")
    os.environ["ATLAS_SCHEDULER_ENABLED"] = "false"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Manually trigger lifespan startup
        from atlas.server import lifespan

        async with lifespan(app):
            # H8 S2: component starts (DBOS/MCP/channels/...) run as the
            # deferred task after the lifespan yields. Wait for them so the
            # tests observe the fully started service graph deterministically.
            startup = app.state.services.startup
            if startup is not None:
                assert await startup.wait_all_ready(timeout=120.0), (
                    f"deferred startup did not become ready: {startup.snapshot()}"
                )
            yield ac

    current_task = asyncio.current_task()
    pending_tasks = [
        task for task in asyncio.all_tasks()
        if task is not current_task and not task.done()
    ]
    assert not pending_tasks, [
        f"{task.get_name()}: {task.get_coro().__qualname__}"
        for task in pending_tasks
    ]

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
        assert data["version"] == "1.10"


class TestH1R3LifecycleAndForkRegressions:
    async def test_lifespan_clears_runtime_services_after_shutdown(self) -> None:
        from atlas.server import lifespan

        async with lifespan(app):
            assert server.runtime_mgr.services is app.state.services
        assert server.runtime_mgr.services is None

    async def test_failed_fork_summary_does_not_create_orphan_conversation(
        self, client: AsyncClient,
    ) -> None:
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import append_session_message

        conversation_id = (await client.post(
            "/api/conversations", json={"title": "Fork summary failure"},
        )).json()["id"]
        cut_id = append_session_message(
            DATA_ROOT / "engine", conversation_id, "user", "keep this turn",
        )
        memory = server.app.state.services.memory
        before_ids = {item["id"] for item in await memory.list_conversations()}

        class BrokenContextMaintenance:
            async def compact(self, _context):
                raise RuntimeError("summary unavailable")

        server.app.state.services.orchestrator = SimpleNamespace(
            context_maintenance=BrokenContextMaintenance(),
        )
        with pytest.raises(RuntimeError, match="summary unavailable"):
            await client.post(
                f"/api/conversations/{conversation_id}/fork",
                json={"through_message_id": cut_id, "summarize": True},
            )

        after_ids = {item["id"] for item in await memory.list_conversations()}
        assert after_ids == before_ids

    async def test_summarized_fork_preamble_precedes_exact_carried_transcript(
        self, client: AsyncClient,
    ) -> None:
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import append_session_message, read_session_all_messages

        conversation_id = (await client.post(
            "/api/conversations", json={"title": "Fork order"},
        )).json()["id"]
        append_session_message(DATA_ROOT / "engine", conversation_id, "user", "first request")
        append_session_message(DATA_ROOT / "engine", conversation_id, "assistant", "first reply")
        cut_id = append_session_message(
            DATA_ROOT / "engine", conversation_id, "user", "second request",
        )
        append_session_message(DATA_ROOT / "engine", conversation_id, "assistant", "second reply")
        append_session_message(DATA_ROOT / "engine", conversation_id, "user", "after cut")

        class ContextMaintenance:
            async def compact(self, _context):
                return {"session_summary": "summary through second request"}

        server.app.state.services.orchestrator = SimpleNamespace(
            context_maintenance=ContextMaintenance(),
        )
        response = await client.post(
            f"/api/conversations/{conversation_id}/fork",
            json={"through_message_id": cut_id, "summarize": True},
        )
        assert response.status_code == 201
        fork_messages = read_session_all_messages(
            DATA_ROOT / "engine", response.json()["id"],
        )
        assert [(item["role"], item["content"]) for item in fork_messages] == [
            ("system", "summary through second request"),
            ("user", "first request"),
            ("assistant", "first reply"),
            ("user", "second request"),
            ("assistant", "second reply"),
        ]


class TestWave7WorkspaceOrchestration:
    async def test_agent_types_include_workspace_source_and_trust_state(
        self, client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = tmp_path / "project"
        agent_dir = workspace / ".claude" / "agents"
        agent_dir.mkdir(parents=True)
        (agent_dir / "reviewer.md").write_text(
            "---\nname: reviewer\ndescription: Review changes\ntools: local_file\n---\nReview only.",
            encoding="utf-8",
        )
        monkeypatch.setattr(server, "_workspace_trust", lambda: {str(workspace.resolve()): False})
        response = await client.get("/api/agents/types", params={"root": str(workspace)})
        assert response.status_code == 200
        reviewer = next(item for item in response.json()["types"] if item["name"] == "reviewer")
        assert reviewer["source"] == "claude"
        assert reviewer["trusted"] is False

    async def test_project_notes_api_requires_trust_and_roundtrips_isolated_workspace(
        self, client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = tmp_path / "project"
        workspace.mkdir()
        trust = {str(workspace.resolve()): False}
        monkeypatch.setattr(server, "_workspace_trust", lambda: trust)
        denied = await client.get("/api/workspace/notes", params={"root": str(workspace)})
        assert denied.status_code == 403
        trust[str(workspace.resolve())] = True
        saved = await client.put("/api/workspace/notes", json={
            "root": str(workspace), "content": "## Build\n- run pytest\n",
        })
        assert saved.status_code == 200
        read = await client.get("/api/workspace/notes", params={"root": str(workspace)})
        assert read.json()["content"] == "## Build\n- run pytest\n"

    async def test_usage_endpoint_grouping_validation(self, client: AsyncClient) -> None:
        empty = await client.get("/api/usage", params={"group_by": "model"})
        assert empty.status_code == 200
        assert empty.json()["rows"] == []
        invalid = await client.get("/api/usage", params={"group_by": "week"})
        assert invalid.status_code == 422

    async def test_safety_settings_api_validates_reviewer(self, client: AsyncClient) -> None:
        stored = await client.put("/api/safety", json={"reviewer": "rules"})
        assert stored.status_code == 200
        assert stored.json()["settings"]["reviewer"] == "rules"
        invalid = await client.put("/api/safety", json={"reviewer": "unsafe"})
        assert invalid.status_code == 400

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
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        import aiosqlite

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
        server.app.state.services.model_mgr = SimpleNamespace(current_model="test-model")
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
        server.app.state.services.model_mgr = SimpleNamespace(current_model="test-model")
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

    async def test_active_skill_run_context_uses_registry_activation_content(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from types import SimpleNamespace

        from atlas import server

        class SkillManager:
            def get_skill(self, name: str):
                if name == "coding-discipline":
                    return SimpleNamespace(name=name, version="1.0.0")
                return None

            async def activate(self, name: str, **kwargs: object) -> str:
                return "Canonical Skill instructions: 简洁优先。"

        class Registry:
            def get(self, name: str, version: str) -> dict[str, object]:
                return {"lifecycle": {"trust_state": "trusted", "state": "active"}}

        monkeypatch.setattr(server, "skill_mgr", SkillManager())
        monkeypatch.setattr(server, "skill_registry", Registry())
        monkeypatch.setattr(server, "mcp_client", None)

        result = await server._resolve_active_skill_instructions(["coding-discipline"])

        assert result == [
            {
                "name": "coding-discipline",
                "version": "1.0.0",
                "content": "Canonical Skill instructions: 简洁优先。",
            }
        ]
        with pytest.raises(ValueError, match="Skill not found"):
            await server._resolve_active_skill_instructions(["unknown-skill"])
        with pytest.raises(ValueError, match="list of Skill names"):
            await server._resolve_active_skill_instructions([{"name": "coding-discipline"}])

    async def test_runtime_shutdown_requires_managed_launch_token(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from atlas.server import app

        called: list[bool] = []
        monkeypatch.setenv("ATLAS_SHUTDOWN_TOKEN", "p17-test-token")
        monkeypatch.setattr(
            app.state,
            "desktop_shutdown_callback",
            lambda: called.append(True),
            raising=False,
        )
        denied = await client.post(
            "/api/runtime/shutdown",
            headers={"X-Atlas-Backend-Shutdown-Token": "wrong"},
        )
        assert denied.status_code == 403
        accepted = await client.post(
            "/api/runtime/shutdown",
            headers={"X-Atlas-Backend-Shutdown-Token": "p17-test-token"},
        )
        assert accepted.status_code == 202
        await asyncio.sleep(0)
        assert called == [True]


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

    async def test_configuration_persists_provider_and_hides_secret(
        self, client: AsyncClient
    ) -> None:
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

    async def test_custom_model_persists_and_duplicate_is_rejected(
        self, client: AsyncClient
    ) -> None:
        model = {
            "id": "custom-test",
            "name": "Custom Test",
            "provider": "openai",
            "litellm_model": "openai/custom-test",
        }
        response = await client.post("/api/models/custom", json=model)
        assert response.status_code == 200
        assert any(item["id"] == "custom-test" for item in response.json()["models"])
        from atlas.models import ModelManager

        assert any(item["id"] == "custom-test" for item in ModelManager().list_models())
        duplicate = await client.post("/api/models/custom", json=model)
        assert duplicate.status_code == 409

    async def test_connection_test_goes_through_model_router_and_keeps_selection(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """H4: the settings probe rides the shared model router (same seam as
        ``/api/models/test``) — no direct ``litellm.acompletion`` from a route —
        and the probe never changes the selected model."""
        from atlas.models.router import RouteSpec

        from atlas.server import model_mgr

        calls: dict = {}

        async def fake_resolve(self, model_id, purpose):
            calls["resolve"] = (model_id, purpose)
            return RouteSpec(
                provider="openai", api_mode="chat_completions", model="gpt-4o", base_url=None,
                purpose=purpose,
            )

        async def fake_complete(self, route, *, messages, **kwargs):
            calls["complete"] = {"purpose": route.purpose, "messages": messages, **kwargs}
            return object()

        monkeypatch.setattr("atlas.models.router.ModelRouter.resolve", fake_resolve)
        monkeypatch.setattr("atlas.models.router.ModelRouter.complete", fake_complete)
        selected_before = model_mgr.current_model
        response = await client.post("/api/settings/test-connection", json={"model": "gpt-4o"})
        body = response.json()
        assert body["ok"] is True, body
        assert calls["resolve"] == ("gpt-4o", "model_test")
        assert calls["complete"]["purpose"] == "model_test"
        assert calls["complete"]["max_tokens"] == 2
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
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import append_session_message
        from atlas.server import memory

        assert memory is not None
        conversation_id = await memory.create_conversation("History test")
        # SessionDB owns the transcript; the Atlas store keeps conversation metadata.
        append_session_message(DATA_ROOT / "engine", conversation_id, "user", "hello")
        append_session_message(DATA_ROOT / "engine", conversation_id, "assistant", "hi")

        resp = await client.get(f"/api/conversations/{conversation_id}/messages")

        assert resp.status_code == 200
        messages = resp.json()
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert [message["content"] for message in messages] == ["hello", "hi"]
        assert all(
            {"id", "role", "content", "created_at"} <= message.keys()
            for message in messages
        )

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

class TestMCPServerManagement:
    async def test_list_mcp_servers_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/mcp/servers")
        assert resp.status_code == 200
        data = resp.json()
        assert "servers" in data
        assert data["servers"] == []

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
        server.app.state.services.mcp_client = mcp

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

    async def test_read_only_dependency_check_reports_runtime_and_skill_blockers(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from atlas import server

        class Registry:
            def list(self, *, status=None):
                return [{
                    "name": "sample", "version": "1.0.0", "status": "active",
                    "requirements": [
                        {"kind": "python_packages", "name": "present", "requested": ">=2"},
                        {"kind": "python_packages", "name": "absent", "requested": None},
                        {"kind": "python_packages", "name": "old", "requested": ">=3"},
                        {"kind": "unknown", "name": "opaque", "requested": None},
                    ],
                }]

        class Runtime:
            def get_runtime_status(self):
                return {"servers": [{
                    "name": "filesystem", "configured": True, "enabled": True,
                    "connected": False, "tool_discovery": "failed", "tool_count": 0,
                    "blocking_reason": "Node runtime unavailable",
                }]}

        registry, runtime = Registry(), Runtime()
        monkeypatch.setattr(server, "skill_registry", registry)
        monkeypatch.setattr(server, "mcp_client", runtime)
        services = server.app.state.services
        original_registry, original_mcp = services.skill_registry, services.mcp_client
        services.skill_registry, services.mcp_client = registry, runtime
        monkeypatch.setattr(
            "atlas.skills.dependencies._installed_package_version",
            lambda name: {"present": "2.5.0", "old": "2.5.0"}.get(name),
        )
        monkeypatch.setattr(server, "get_node_runtime_status", lambda: {
            "available": False, "source": "missing", "version": None,
            "bundled": {"available": False, "blocking_reason": "bundled Node unavailable"},
            "blocking_reason": "bundled Node executable is missing",
        })

        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/runtime/dependency-check")

        assert response.status_code == 200
        report = response.json()
        assert report["read_only"] is True
        assert report["node"]["available"] is False
        assert report["mcp_servers"][0]["tool_discovery"] == "failed"
        states = {item["name"]: item["state"] for item in report["skills"][0]["dependencies"]}
        assert states == {
            "present": "satisfied", "absent": "missing", "old": "incompatible",
            "opaque": "unknown",
        }
        assert {item["state"] for item in report["skills"][0]["blocking"]} == {
            "missing", "incompatible", "unknown",
        }
        services.skill_registry, services.mcp_client = original_registry, original_mcp


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
        memory_mock = SimpleNamespace(
            save_conversation_metadata=AsyncMock(
                side_effect=OSError("database unavailable")
            ),
        )
        monkeypatch.setattr(server, "memory", memory_mock)
        server.app.state.services.memory = memory_mock
        monkeypatch.setattr(server, "orchestrator", SimpleNamespace())
        server.app.state.services.orchestrator = SimpleNamespace()
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
        memory_mock = SimpleNamespace(
            save_conversation_metadata=AsyncMock(),
        )
        monkeypatch.setattr(server, "memory", memory_mock)
        server.app.state.services.memory = memory_mock
        monkeypatch.setattr(server, "orchestrator", SimpleNamespace(run=events))
        server.app.state.services.orchestrator = SimpleNamespace(run=events)
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

    async def test_success_without_tool_failures_completes(
        self, monkeypatch
    ) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from atlas import server

        async def events(**kwargs):
            yield {"type": "done"}

        memory_mock = SimpleNamespace(
            save_conversation_metadata=AsyncMock(),
        )
        run = server.RunState("clean-run", "conv-clean", "test-model")
        monkeypatch.setattr(server, "memory", memory_mock)
        server.app.state.services.memory = memory_mock
        monkeypatch.setattr(server, "orchestrator", SimpleNamespace(run=events))
        server.app.state.services.orchestrator = SimpleNamespace(run=events)

        await server._execute_run("clean-connection", run, "hello", None)


    async def test_model_and_runtime_failures_emit_failure_events(
        self, monkeypatch
    ) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from atlas import server

        class Socket:
            def __init__(self) -> None:
                self.events: list[dict] = []

            async def send_json(self, event: dict) -> None:
                self.events.append(event)

        memory_mock = SimpleNamespace(
            save_conversation_metadata=AsyncMock(),
        )
        monkeypatch.setattr(server, "memory", memory_mock)
        server.app.state.services.memory = memory_mock

        for category in ("model", "runtime"):
            socket = Socket()
            conn_id = f"{category}-failure-test"
            run = server.RunState(f"{category}-failure-run", "conv-3", "test-model")

            if category == "model":
                async def events(**kwargs):
                    yield {"type": "error", "category": "model", "detail": "provider unavailable"}
            else:
                async def events(**kwargs):
                    raise RuntimeError("runtime crashed")
                    yield  # Make this an async generator.

            monkeypatch.setattr(server, "orchestrator", SimpleNamespace(run=events))

            server.app.state.services.orchestrator = SimpleNamespace(run=events)
            monkeypatch.setitem(server.runtime_mgr.connections, conn_id, socket)
            try:
                await server._execute_run(conn_id, run, "perform work", None)
            finally:
                server.runtime_mgr.connections.pop(conn_id, None)
            assert run.status == "failed"
            failed = next(event for event in socket.events if event["event"] == "run.failed")
            assert failed["data"]["category"] == category

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
            server.app.state.services.orchestrator = SimpleNamespace(run=fake_run)
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
        server.app.state.services.model_mgr = SimpleNamespace(current_model="test-model")
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


class TestBackendParityWave1:

    async def test_ask_user_event_waits_for_a_response(self, monkeypatch) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        class Socket:
            def __init__(self) -> None:
                self.events = []
            async def send_json(self, event): self.events.append(event)

        async def ask_then_finish(**kwargs):
            answer = await kwargs["input_callback"]("ask-call", "Choose a path", ["A", "B"])
            assert answer == "A"
            yield {"type": "done"}

        socket = Socket()
        run = server.RunState("ask-user-run", "ask-user-conv", "model")
        memory_mock = SimpleNamespace(
            save_conversation_metadata=AsyncMock(),
        )
        monkeypatch.setattr(server, "memory", memory_mock)
        server.app.state.services.memory = memory_mock
        monkeypatch.setattr(server, "orchestrator", SimpleNamespace(run=ask_then_finish))
        server.app.state.services.orchestrator = SimpleNamespace(run=ask_then_finish)
        monkeypatch.setitem(server.runtime_mgr.connections, "ask-user-conn", socket)
        monkeypatch.setitem(server.runtime_mgr.runs, run.run_id, run)
        task = asyncio.create_task(server._execute_run(
            "ask-user-conn", run, "question", None,
        ))
        try:
            for _ in range(50):
                required = next((item for item in socket.events
                                 if item["event"] == "input.required"), None)
                if required:
                    break
                await asyncio.sleep(0.02)
            assert required is not None
            assert required["data"]["options"] == ["A", "B"]
            run.input_futures[required["data"]["event_id"]].set_result("A")
            await task
            assert run.status == "completed"
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            server.runtime_mgr.connections.pop("ask-user-conn", None)
            server.runtime_mgr.runs.pop(run.run_id, None)

    async def test_conversation_pin_archive_and_optional_title(self, client: AsyncClient) -> None:
        created = await client.post("/api/conversations", json={"title": "Kept title"})
        conversation_id = created.json()["id"]
        updated = await client.put(f"/api/conversations/{conversation_id}", json={
            "pinned": True, "archived": True,
        })
        assert updated.status_code == 200
        row = next(item for item in (await client.get("/api/conversations")).json()
                   if item["id"] == conversation_id)
        assert (row["title"], row["pinned"], row["archived"]) == ("Kept title", True, True)
        assert (await client.put("/api/conversations/missing", json={"pinned": True})).status_code == 404

    async def test_checkpoint_diff_and_invalid_run_filter(
        self, client: AsyncClient, tmp_path: Path, monkeypatch,
    ) -> None:
        workspace = tmp_path / "diff-workspace"
        workspace.mkdir()
        file = workspace / "note.txt"
        file.write_text("before\n", encoding="utf-8")
        store = server.orchestrator.checkpoints
        # Keep test snapshots out of the user's real %LOCALAPPDATA%\Atlas\checkpoints.
        monkeypatch.setattr(store, "storage_dir", (tmp_path / "checkpoints").resolve())
        store.create_checkpoint(
            workspace, ["note.txt"], run_id="diff-run", conversation_id="diff-conv",
        )
        file.write_text("after\n", encoding="utf-8")
        listed = await client.get("/api/checkpoints", params={"run_id": "diff-run"})
        assert listed.status_code == 200
        assert listed.json()[0]["run_id"] == "diff-run"
        changes = (await client.get("/api/runs/diff-run/changes")).json()
        assert changes["files"][0]["status"] == "modified"
        assert "+after" in changes["files"][0]["diff"]
        assert (await client.get("/api/checkpoints", params={"workspace": "<invalid>"})).status_code == 200

    async def test_process_endpoints_read_output_kill_and_404(self, client: AsyncClient, tmp_path: Path) -> None:
        import sys
        runtime = server.local_execution
        started = await runtime.call_tool("local_exec", {
            "executable": sys.executable,
            "args": ["-c", "import time; print('process-output', flush=True); time.sleep(30)"],
            "cwd": str(tmp_path), "detached": True,
        }, run_id="process-test")
        process_id = started["data"]["execution_id"]
        assert any(item["id"] == process_id for item in (await client.get("/api/processes")).json())
        await asyncio.sleep(0.2)
        output = await client.get(f"/api/processes/{process_id}/output")
        assert "process-output" in output.json()["output"]
        assert (await client.post(f"/api/processes/{process_id}/kill")).status_code == 200
        assert (await client.get("/api/processes/unknown/output")).status_code == 404

    async def test_terminal_returns_explicit_missing_dependency_error(self, tmp_path: Path, monkeypatch) -> None:
        import builtins

        class Socket:
            def __init__(self) -> None:
                self.events = []
                self.closed = None
            async def accept(self): pass
            async def send_json(self, value): self.events.append(value)
            async def close(self, code): self.closed = code

        socket = Socket()
        original_import = builtins.__import__
        def no_winpty(name, *args, **kwargs):
            if name == "winpty":
                raise ImportError("missing test dependency")
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", no_winpty)
        await server.ws_terminal(socket, cwd=str(tmp_path))
        assert socket.events == [{"type": "error", "error": "pywinpty is not installed"}]
        assert socket.closed == 1011

    async def test_workspace_tree_file_and_path_escape(self, client: AsyncClient, tmp_path: Path) -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        (root / "hello.txt").write_text("hello", encoding="utf-8")
        (root / ".git").mkdir()
        tree = await client.get("/api/workspace/tree", params={"root": str(root)})
        assert [entry["name"] for entry in tree.json()["entries"]] == ["hello.txt"]
        file = await client.get("/api/workspace/file", params={"root": str(root), "path": "hello.txt"})
        assert file.json()["content"] == "hello"
        escaped = await client.get("/api/workspace/file", params={
            "root": str(root), "path": "../outside.txt",
        })
        assert escaped.status_code == 400

    async def test_usage_sum_manual_compact_and_missing_conversation(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        total = server._sum_usage([
            {"request_id": "main-1", "purpose": "conversation", "request_count": 1,
             "input_tokens": 2, "output_tokens": 3, "context_tokens": 5,
             "cached_input_tokens": 1, "cache_write_tokens": 2,
             "context_limit": None, "model": "m"},
            {"request_id": "main-2", "purpose": "conversation", "request_count": 1,
             "input_tokens": 4, "output_tokens": 1, "context_tokens": 5,
             "cached_input_tokens": 2, "cache_write_tokens": 0,
             "context_limit": None, "model": "m"},
            {"request_id": "child-1", "purpose": "subagent", "request_count": 1,
             "input_tokens": 3, "output_tokens": 2, "context_tokens": 7,
             "cached_input_tokens": 0, "cache_write_tokens": 0,
             "context_limit": None, "model": "child-model"},
        ])
        assert total["input_tokens"] == 9 and total["output_tokens"] == 6
        assert total["request_count"] == 3
        assert total["purpose_totals"]["conversation"]["request_count"] == 2
        assert total["purpose_totals"]["subagent"]["request_count"] == 1
        assert total["cached_input_tokens"] == 3 and total["cache_write_tokens"] == 2
        assert total["cache_hit_rate"] == 0.3333
        assert total["context_tokens"] == 5
        created = await client.post("/api/conversations", json={})
        conv_id = created.json()["id"]
        await server.memory.save_message(conv_id, "user", "A compactable conversation")

        async def fake_compact_session(self, **_kwargs):
            return {
                "before_tokens": 6, "after_tokens": 1,
                "summary": "A compactable conversation", "compressed": True,
            }

        from atlas.engine.hermes_runtime import HermesRuntime

        monkeypatch.setattr(HermesRuntime, "compact_session", fake_compact_session)
        compacted = await client.post(f"/api/conversations/{conv_id}/compact")
        assert compacted.status_code == 200 and compacted.json()["before_tokens"] > 0
        assert (await client.post("/api/conversations/missing/compact")).status_code == 404

    async def test_workspace_rules_list_present_and_missing_roots(self, client: AsyncClient, tmp_path: Path) -> None:
        root = tmp_path / "rules-root"
        root.mkdir()
        (root / "AGENTS.md").write_text("Keep changes small", encoding="utf-8")
        result = (await client.get("/api/workspace/rules", params={"root": str(root)})).json()
        assert any(item["content"] == "Keep changes small" for item in result["files"])
        assert (await client.get("/api/workspace/rules", params={"root": str(root / "missing")})).status_code == 200

    async def test_file_attachment_inline_and_invalid_base64(self, tmp_path: Path) -> None:
        content, paths = server._validated_file_attachments([{
            "name": "notes.md", "mime": "text/markdown",
            "data_base64": "SGVsbG8=",
        }], "attach-run", "question")
        assert "Hello" in content and paths == []
        with pytest.raises(ValueError, match="invalid base64"):
            server._validated_file_attachments([{
                "name": "bad.txt", "mime": "text/plain", "data_base64": "%%%",
            }], "attach-run", "question")

    async def test_plan_tool_allowlist_and_validation(self) -> None:
        tools = [
            {"type": "function", "function": {"name": "local_file", "parameters": {
                "properties": {"action": {"enum": ["read", "write", "delete"]}},
            }}},
            {"type": "function", "function": {"name": "local_shell", "parameters": {}}},
            {"type": "function", "function": {"name": "web_fetch", "parameters": {}}},
        ]
        allowed = server._plan_mode_tools(tools)
        assert [item["function"]["name"] for item in allowed] == ["local_file", "web_fetch"]
        assert allowed[0]["function"]["parameters"]["properties"]["action"]["enum"] == [
            "read", "list", "glob", "search", "stat",
        ]
        assert len(tools) == 3

    async def test_fork_truncate_and_missing_message(self, client: AsyncClient) -> None:
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import append_session_message

        conv_id = (await client.post("/api/conversations", json={"title": "Branch"})).json()["id"]
        # SessionDB owns the transcript; fork/truncate address it by message uid
        # and cut on user-turn boundaries (a fork through a turn keeps the
        # whole turn, including its assistant reply).
        first = append_session_message(DATA_ROOT / "engine", conv_id, "user", "first")
        append_session_message(DATA_ROOT / "engine", conv_id, "assistant", "second")
        third = append_session_message(DATA_ROOT / "engine", conv_id, "user", "third")
        fork = await client.post(f"/api/conversations/{conv_id}/fork", json={
            "through_message_id": first,
        })
        assert fork.status_code == 201
        # SessionDB-owned branches link back to their parent instead of copying
        # legacy body rows, so the response carries the linkage, not files_shared.
        assert fork.json()["parent_conversation_id"] == conv_id
        forked_messages = await client.get(f"/api/conversations/{fork.json()['id']}/messages")
        assert [item["content"] for item in forked_messages.json()] == ["first", "second"]
        truncated = await client.post(f"/api/conversations/{conv_id}/truncate", json={
            "from_message_id": third,
        })
        assert truncated.status_code == 200
        assert [
            item["content"]
            for item in (await client.get(f"/api/conversations/{conv_id}/messages")).json()
        ] == ["first", "second"]
        assert (await client.post(f"/api/conversations/{conv_id}/fork", json={
            "through_message_id": "absent",
        })).status_code == 404

    async def test_chinese_trigram_and_short_like_search(self, client: AsyncClient) -> None:
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import append_session_message

        conv_id = (await client.post("/api/conversations", json={"title": "中文会话"})).json()["id"]
        append_session_message(DATA_ROOT / "engine", conv_id, "user", "请记住工作区规则注入")
        long_query = await client.get("/api/search", params={"q": "工作区规则"})
        short_query = await client.get("/api/search", params={"q": "规则"})
        assert long_query.status_code == short_query.status_code == 200
        assert long_query.json()[0]["title"] == "中文会话"
        assert short_query.json()

    async def test_run_workspace_saved_and_invalid_mode_rejected(
        self, client: AsyncClient, tmp_path: Path, monkeypatch,
    ) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        workspace = tmp_path / "run-workspace"
        workspace.mkdir()
        (workspace / "AGENTS.md").write_text("Use tests", encoding="utf-8")
        server._set_workspace_trusted(str(workspace), True)
        conv_id = await server.memory.create_conversation("Workspace session")
        monkeypatch.setattr(server, "model_mgr", SimpleNamespace(current_model="test-model"))
        server.app.state.services.model_mgr = SimpleNamespace(current_model="test-model")
        async def do_nothing(*args, **kwargs): return None
        monkeypatch.setattr(server, "_execute_run", do_nothing)
        run_id = "workspace-run-test"
        await server._handle_run_start("workspace-test-conn", {
            "run_id": run_id, "conversation_id": conv_id, "content": "hello",
            "workspace": str(workspace), "mode": "act",
        })
        assert (await server.memory.get_conversation(conv_id))["workspace"] == str(workspace)
        await asyncio.sleep(0)
        assert (await server.memory.get_conversation(conv_id))["workspace"] == str(workspace)
        send = AsyncMock()
        monkeypatch.setattr(server.runtime_mgr, "send", send)
        await server._handle_run_start("invalid-mode-conn", {
            "run_id": "invalid-mode-test", "conversation_id": conv_id,
            "content": "hello", "mode": "unknown",
        })
        assert any(call.args[1]["event"] == "run.failed" for call in send.await_args_list)
        await server._handle_run_start("invalid-permission-conn", {
            "run_id": "invalid-permission-test", "conversation_id": conv_id,
            "content": "hello", "permission_mode": "unsafe",
            "allowed_paths": ["relative/path"],
        })
        assert any(
            call.args[1]["event"] == "run.failed"
            and call.args[1]["data"]["category"] == "validation"
            for call in send.await_args_list
        )

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
