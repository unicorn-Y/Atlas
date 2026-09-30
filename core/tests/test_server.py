"""Tests for Atlas REST API — FastAPI endpoints."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from atlas import server
from atlas.memory import MemoryStore
from atlas.server import app


@pytest.fixture(autouse=True)
def isolated_atlas_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep server tests off machine-local config and external MCP processes."""
    from atlas import config

    data_root = tmp_path / "atlas-data"
    config_path = tmp_path / "config" / "atlas.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "[scheduler]\nenabled = false\n\n[tools]\nauto_start = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "DATA_ROOT", data_root)
    monkeypatch.setattr(config, "USER_SETTINGS_PATH", data_root / "data" / "user-settings.json")
    monkeypatch.setattr(config, "_config", None)


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
        assert data["version"] == "1.6"

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

    async def test_connection_test_uses_litellm_and_does_not_change_selection(
        self, client: AsyncClient, monkeypatch
    ) -> None:
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

    async def test_memory_maturity_reports_are_readable_through_api(
        self, client: AsyncClient, tmp_path
    ) -> None:
        original_memory = server.memory
        await original_memory.close()
        isolated_memory = MemoryStore(db_path=tmp_path / "maturity-reports.db")
        await isolated_memory.init()
        server.memory = isolated_memory
        try:
            await isolated_memory.set_fact("user_preference", "concise answers")

            created = await client.post("/api/memory/maturity-reports")
            listed = await client.get("/api/memory/maturity-reports")

            assert created.status_code == 200
            assert created.json()["report"]["memory_count"] == 1
            assert created.json()["report"]["recommendations"][0]["evidence_refs"]
            assert listed.status_code == 200
            assert listed.json()[0]["report"] == created.json()["report"]
            assert await isolated_memory.get_fact("user_preference") == "concise answers"
        finally:
            await isolated_memory.close()
            server.memory = original_memory

    async def test_memory_self_steering_reports_are_readable_through_api(
        self, client: AsyncClient, tmp_path
    ) -> None:
        original_memory = server.memory
        await original_memory.close()
        isolated_memory = MemoryStore(db_path=tmp_path / "self-steering-reports.db")
        await isolated_memory.init()
        server.memory = isolated_memory
        try:
            await isolated_memory.set_fact("user_preference", "concise answers")

            created = await client.post("/api/memory/self-steering-reports")
            listed = await client.get("/api/memory/self-steering-reports")

            assert created.status_code == 200
            report = created.json()["report"]
            assert report["fact_count"] == 1
            assert report["suggestion_count"] == 1
            assert report["suggestions"][0]["evidence_refs"]
            assert report["maturity_report_id"]
            assert listed.status_code == 200
            assert listed.json()[0]["report"] == report
            assert await isolated_memory.get_fact("user_preference") == "concise answers"
        finally:
            await isolated_memory.close()
            server.memory = original_memory

    async def test_memory_optimization_candidates_require_api_approval(
        self, client: AsyncClient, tmp_path,
    ) -> None:
        original_memory = server.memory
        await original_memory.close()
        isolated_memory = MemoryStore(db_path=tmp_path / "optimization-candidates.db")
        await isolated_memory.init()
        server.memory = isolated_memory
        try:
            await isolated_memory.set_fact("user_preference", "concise answers")
            report = await client.post("/api/memory/self-steering-reports")
            assert report.status_code == 200
            report_id = report.json()["id"]

            before_approval = await client.post("/api/memory/optimization-candidates")
            assert before_approval.status_code == 200
            assert before_approval.json() == []

            approved = await client.post(
                f"/api/memory/self-steering-reports/{report_id}/approve"
            )
            assert approved.status_code == 200
            generated = await client.post("/api/memory/optimization-candidates")
            assert generated.status_code == 200
            assert generated.json()
            candidate = generated.json()[0]
            assert candidate["source_report_id"] == report_id
            assert candidate["risk"] == "low"
            assert candidate["advisory_only"] is True
            assert candidate["evidence_refs"]

            reviewed = await client.post(
                f"/api/memory/optimization-candidates/{candidate['id']}/approve"
            )
            listed = await client.get(
                "/api/memory/optimization-candidates", params={"status": "approved"}
            )
            assert reviewed.status_code == 200
            assert listed.status_code == 200
            assert listed.json()[0]["review_history"][0]["decision"] == "approved"
        finally:
            await isolated_memory.close()
            server.memory = original_memory

    async def test_memory_consolidation_proposals_require_approved_candidates(
        self, client: AsyncClient, tmp_path,
    ) -> None:
        original_memory = server.memory
        await original_memory.close()
        isolated_memory = MemoryStore(db_path=tmp_path / "consolidation-proposals.db")
        await isolated_memory.init()
        server.memory = isolated_memory
        try:
            await isolated_memory.set_fact("user_preference", "concise answers")
            original_fact = await isolated_memory.get_fact("user_preference")
            report = await client.post("/api/memory/self-steering-reports")
            assert report.status_code == 200
            report_id = report.json()["id"]

            no_approved_candidates = await client.post(
                "/api/memory/consolidation-proposals"
            )
            assert no_approved_candidates.status_code == 200
            assert no_approved_candidates.json() == []

            approved_report = await client.post(
                f"/api/memory/self-steering-reports/{report_id}/approve"
            )
            assert approved_report.status_code == 200
            candidates = await client.post("/api/memory/optimization-candidates")
            assert candidates.status_code == 200
            for candidate in candidates.json():
                reviewed = await client.post(
                    f"/api/memory/optimization-candidates/{candidate['id']}/approve"
                )
                assert reviewed.status_code == 200

            created = await client.post("/api/memory/consolidation-proposals")
            repeated = await client.post("/api/memory/consolidation-proposals")
            assert created.status_code == repeated.status_code == 200
            assert created.json()
            assert [item["id"] for item in created.json()] == [
                item["id"] for item in repeated.json()
            ]
            for proposal in created.json():
                assert proposal["advisory_only"] is True
                assert proposal["source_report_ids"] == [report_id]
                assert proposal["source_candidate_ids"]
                assert proposal["evidence_refs"]
                assert proposal["status"] == "pending"

            proposal = created.json()[0]
            rejected_proposal = {**proposal, "id": "rejected-activation-proposal"}
            await isolated_memory._db.execute(
                "INSERT INTO memory_consolidation_proposals "
                "(id, proposal_json, created_at) VALUES (?, ?, ?)",
                (
                    rejected_proposal["id"],
                    json.dumps(rejected_proposal, sort_keys=True),
                    proposal["created_at"],
                ),
            )
            await isolated_memory._db.commit()

            pending_activation = await client.post(
                f"/api/memory/consolidation-proposals/{proposal['id']}/activate"
            )
            rejected = await client.post(
                f"/api/memory/consolidation-proposals/{rejected_proposal['id']}/reject"
            )
            rejected_activation = await client.post(
                f"/api/memory/consolidation-proposals/{rejected_proposal['id']}/activate"
            )
            reviewed = await client.post(
                f"/api/memory/consolidation-proposals/{proposal['id']}/approve"
            )
            activated = await client.post(
                f"/api/memory/consolidation-proposals/{proposal['id']}/activate"
            )
            repeated_activation = await client.post(
                f"/api/memory/consolidation-proposals/{proposal['id']}/activate"
            )
            activation_list = await client.get("/api/memory/knowledge-activations")
            [candidate_id] = proposal["source_candidate_ids"]
            verification = await client.post(
                f"/api/memory/knowledge-activations/{activated.json()['id']}/verify",
                json={
                    "candidate_id": candidate_id,
                    "evidence_refs": proposal["candidate_snapshots"][0]["evidence_refs"],
                    "usage_id": "run-verification-1",
                },
            )
            unsupported_verification = await client.post(
                f"/api/memory/knowledge-activations/{activated.json()['id']}/verify",
                json={
                    "candidate_id": candidate_id,
                    "evidence_refs": ["evidence:unsupported"],
                },
            )
            verification_list = await client.get(
                "/api/memory/knowledge-verifications",
                params={"activation_id": activated.json()["id"]},
            )
            approved = await client.get(
                "/api/memory/consolidation-proposals",
                params={"status": "approved"},
            )
            duplicate_review = await client.post(
                f"/api/memory/consolidation-proposals/{proposal['id']}/reject"
            )
            assert pending_activation.status_code == 404
            assert rejected.status_code == 200
            assert rejected_activation.status_code == 404
            assert reviewed.status_code == 200
            assert activated.status_code == repeated_activation.status_code == 200
            assert activated.json() == repeated_activation.json()
            activation = activated.json()
            assert activation["advisory_only"] is True
            assert activation["activation_status"] == "active"
            assert activation["proposal"]["id"] == proposal["id"]
            assert activation["proposal"]["source_candidate_ids"] == proposal[
                "source_candidate_ids"
            ]
            assert activation["proposal"]["source_report_ids"] == [report_id]
            assert activation["proposal"]["evidence_refs"] == proposal["evidence_refs"]
            assert activation["approval_history"] == [{
                "decision": "approved", "reviewed_at": activation["proposal"]["reviewed_at"],
            }]
            assert activation["history"] == [{
                "event": "activated", "created_at": activation["created_at"],
            }]
            assert activation_list.status_code == 200
            assert activation_list.json() == [activation]
            assert verification.status_code == 200
            assert verification.json()["status"] == "verified"
            assert verification.json()["advisory_only"] is True
            assert verification.json()["checks"]["candidate_in_provenance"] is True
            assert unsupported_verification.json()["status"] == "unverified"
            assert unsupported_verification.json()["checks"]["evidence_supported"] is False
            assert verification_list.status_code == 200
            assert [item["id"] for item in verification_list.json()] == [
                unsupported_verification.json()["id"], verification.json()["id"],
            ]
            assert approved.status_code == 200
            assert approved.json()[0]["review_history"][0]["decision"] == "approved"
            assert duplicate_review.status_code == 404
            assert await isolated_memory.get_fact("user_preference") == original_fact
        finally:
            await isolated_memory.close()
            server.memory = original_memory

    async def test_goal_experience_requires_explicit_api_approval(
        self, client: AsyncClient, tmp_path,
    ) -> None:
        original_memory = server.memory
        await original_memory.close()
        isolated_memory = MemoryStore(db_path=tmp_path / "goal-outcomes.db")
        await isolated_memory.init()
        server.memory = isolated_memory
        try:
            outcome_id = await isolated_memory.record_goal_outcome(
                goal_id="weekly-review",
                goal="Review filesystem migration risks",
                status="completed",
                evaluation={"satisfied": True, "evidence": "Risks listed."},
                steps=[{
                    "id": "inspect", "title": "Inspect filesystem",
                    "status": "completed", "evidence": "Manifest reviewed.",
                }],
                source_conversation_id="scheduled-goal-weekly-review",
                source_run_id="run-1",
            )

            listed = await client.get(
                "/api/memory/goal-outcomes", params={"status": "pending"},
            )
            assert listed.status_code == 200
            assert listed.json()[0]["id"] == outcome_id
            assert await isolated_memory.retrieve_approved_goal_experiences(
                "filesystem migration",
            ) == []
            assert await isolated_memory.retrieve_approved_goal_knowledge(
                "filesystem migration",
            ) == []

            approved = await client.post(
                f"/api/memory/goal-outcomes/{outcome_id}/approve",
            )
            assert approved.status_code == 200
            [experience] = await isolated_memory.retrieve_approved_goal_experiences(
                "filesystem migration",
            )
            assert experience["id"] == outcome_id
            [knowledge] = await isolated_memory.retrieve_approved_goal_knowledge(
                "filesystem migration",
            )
            assert knowledge["source_outcome_id"] == outcome_id
            assert knowledge["approval_status"] == "approved"
        finally:
            await isolated_memory.close()
            server.memory = original_memory

    async def test_goal_knowledge_proposal_api_requires_explicit_approval(
        self, client: AsyncClient, tmp_path,
    ) -> None:
        original_memory = server.memory
        await original_memory.close()
        isolated_memory = MemoryStore(db_path=tmp_path / "goal-knowledge-proposals.db")
        await isolated_memory.init()
        server.memory = isolated_memory
        try:
            source_outcome_id = await isolated_memory.record_goal_outcome(
                goal_id="migration-review",
                goal="Review filesystem migration risks",
                status="completed",
                evaluation={"satisfied": True, "evidence": "Risks listed."},
                steps=[{"id": "inspect", "title": "Inspect", "evidence": "Reviewed."}],
                source_conversation_id="source-conversation",
                source_run_id="source-run",
            )
            assert await isolated_memory.review_goal_experience(source_outcome_id, True)
            [knowledge] = await isolated_memory.retrieve_approved_goal_knowledge(
                "filesystem migration",
            )
            await isolated_memory.record_goal_knowledge_usage(
                knowledge["id"], "execution", "execution-conversation", "execution-run",
            )
            await isolated_memory.record_goal_outcome(
                goal_id="migration-review",
                goal="Review filesystem migration risks",
                status="blocked",
                evaluation={"satisfied": False, "reason": "The manifest was unavailable."},
                steps=[],
                source_conversation_id="execution-conversation",
                source_run_id="execution-run",
            )

            listed = await client.get(
                "/api/memory/goal-knowledge/proposals", params={"status": "pending"},
            )
            assert listed.status_code == 200
            [proposal] = listed.json()
            assert proposal["status"] == "pending"
            assert proposal["execution_outcome_id"]
            governance = await client.get(
                "/api/memory/goal-knowledge/governance/evaluate",
                params={"entity_type": "proposal", "entity_id": proposal["id"]},
            )
            assert governance.status_code == 200
            [governance_decision] = governance.json()
            assert governance_decision["eligible"] is True

            approved = await client.post(
                f"/api/memory/goal-knowledge/proposals/{proposal['id']}/approve",
            )
            assert approved.status_code == 200
            assert approved.json()["status"] == "approved"

            await isolated_memory.record_goal_knowledge_usage(
                knowledge["id"], "execution", "execution-conversation-2", "execution-run-2",
            )
            await isolated_memory.record_goal_outcome(
                goal_id="migration-review",
                goal="Review filesystem migration risks",
                status="blocked",
                evaluation={"satisfied": False, "reason": "The target path was unavailable."},
                steps=[],
                source_conversation_id="execution-conversation-2",
                source_run_id="execution-run-2",
            )
            [second_proposal] = [
                item for item in await isolated_memory.list_goal_knowledge_proposals()
                if item["conversation_id"] == "execution-conversation-2"
            ]
            assert await isolated_memory.review_goal_knowledge_proposal(
                second_proposal["id"], approved=True,
            )
            evaluated = await client.post(
                "/api/memory/goal-knowledge/refinements/evaluate",
                params={"knowledge_id": knowledge["id"]},
            )
            assert evaluated.status_code == 200
            [evaluation] = evaluated.json()
            assert evaluation["eligible"] is True
            evaluation_history = await client.get(
                "/api/memory/goal-knowledge/refinement-evaluations",
                params={"knowledge_id": knowledge["id"]},
            )
            assert evaluation_history.status_code == 200
            [stored_evaluation] = evaluation_history.json()
            assert stored_evaluation["decision_reason"] == "repeated_approved_improvements"
            assert stored_evaluation["proposal_ids"] == evaluation["proposal_ids"]
            listed_refinements = await client.get(
                "/api/memory/goal-knowledge/refinements", params={"status": "pending"},
            )
            assert listed_refinements.status_code == 200
            [refinement] = listed_refinements.json()
            refined = await client.post(
                f"/api/memory/goal-knowledge/refinements/{refinement['id']}/approve",
            )
            assert refined.status_code == 200
            assert refined.json()["status"] == "approved"
            history = await client.get(
                "/api/memory/goal-knowledge/governance/history",
                params={"knowledge_id": knowledge["id"]},
            )
            assert history.status_code == 200
            assert [item["entity_type"] for item in history.json()] == [
                "proposal", "proposal", "refinement",
            ]
            feedback = await client.get(
                "/api/memory/goal-knowledge/feedback",
                params={"knowledge_id": knowledge["id"]},
            )
            assert feedback.status_code == 200
            assert len(feedback.json()) == 2
            assert all(item["signal"] == "failed" for item in feedback.json())
            evolution = await client.post(
                "/api/memory/goal-knowledge/evolution/evaluate",
                params={"knowledge_id": knowledge["id"]},
            )
            assert evolution.status_code == 200
            [evolution_decision] = evolution.json()
            assert evolution_decision["decision"] == (
                "review_recommended_after_repeated_failures"
            )
            assert len(evolution_decision["evidence"]) == 2
            evolution_history = await client.get(
                "/api/memory/goal-knowledge/evolution/evaluations",
                params={"knowledge_id": knowledge["id"]},
            )
            assert evolution_history.status_code == 200
            [stored_evolution] = evolution_history.json()
            assert stored_evolution["evidence"] == evolution_decision["evidence"]
            recommendations = await client.get(
                "/api/memory/goal-knowledge/evolution/recommendations",
                params={"knowledge_id": knowledge["id"]},
            )
            assert recommendations.status_code == 200
            [recommendation] = recommendations.json()
            assert recommendation["id"] == evolution_decision["recommendation_id"]
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

        monkeypatch.setattr(server, "skill_registry", Registry())
        monkeypatch.setattr(server, "mcp_client", Runtime())
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
            save_message=AsyncMock(side_effect=OSError("database unavailable"))
        )
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
        memory_mock = SimpleNamespace(
            save_message=AsyncMock(),
            record_agent_reflection=AsyncMock(),
            mark_agent_reflections_recovered=AsyncMock(),
        )
        monkeypatch.setattr(server, "memory", memory_mock)
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
        memory_mock.record_agent_reflection.assert_awaited_once_with(
            category="tool",
            component="fs__read",
            summary="Tool call failed: tool timed out",
            resolution_hint=(
                "Review the tool error and validate a corrected request before retrying."
            ),
            source_conversation_id="conv-2",
            source_run_id="tool-failure-run",
            model="test-model",
        )
        memory_mock.mark_agent_reflections_recovered.assert_awaited_once_with(
            "tool-failure-run"
        )

    async def test_success_without_tool_failures_does_not_write_recovery_state(
        self, monkeypatch
    ) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from atlas import server

        async def events(**kwargs):
            yield {"type": "done"}

        memory_mock = SimpleNamespace(
            save_message=AsyncMock(),
            record_agent_reflection=AsyncMock(),
            mark_agent_reflections_recovered=AsyncMock(),
        )
        run = server.RunState("clean-run", "conv-clean", "test-model")
        monkeypatch.setattr(server, "memory", memory_mock)
        monkeypatch.setattr(server, "orchestrator", SimpleNamespace(run=events))

        await server._execute_run("clean-connection", run, "hello", None)

        memory_mock.mark_agent_reflections_recovered.assert_not_awaited()

    async def test_model_and_runtime_failures_are_reflected_with_provenance(
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
            save_message=AsyncMock(),
            record_agent_reflection=AsyncMock(),
            mark_agent_reflections_recovered=AsyncMock(),
        )
        monkeypatch.setattr(server, "memory", memory_mock)

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
            monkeypatch.setitem(server.runtime_mgr.connections, conn_id, socket)
            try:
                await server._execute_run(conn_id, run, "perform work", None)
            finally:
                server.runtime_mgr.connections.pop(conn_id, None)

        calls = memory_mock.record_agent_reflection.await_args_list
        assert [(call.kwargs["category"], call.kwargs["source_run_id"])
                for call in calls] == [
            ("model", "model-failure-run"),
            ("runtime", "runtime-failure-run"),
        ]

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


class TestBackendParityWave1:
    async def test_steer_queues_for_next_model_turn_and_rejects_finished_run(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from langchain_core.messages import HumanMessage
        from atlas.agent import AgentOrchestrator, AgentRunContext

        run = server.RunState("steer-run", "conv", "model")
        assert server._queue_run_steer(run, "change direction", "event-1") is None
        model_requests = []
        class Stream:
            def __aiter__(self):
                async def chunks():
                    yield SimpleNamespace(
                        choices=[SimpleNamespace(
                            delta=SimpleNamespace(content="ok", tool_calls=[]),
                            finish_reason="stop",
                        )], usage=None,
                    )
                return chunks()
        async def completion(**kwargs):
            model_requests.append(kwargs)
            return Stream()
        from atlas import agent as agent_module
        original = agent_module.acompletion
        agent_module.acompletion = completion
        try:
            agent = object.__new__(AgentOrchestrator)
            agent._model_mgr = SimpleNamespace(current_litellm_model="test-model")
            agent._model_facing_tools = lambda: []
            agent._to_litellm_messages = lambda messages: [
                {"role": "user", "content": item.content} for item in messages
            ]
            agent.context_maintenance = SimpleNamespace(should_compact=lambda *a, **k: False)
            agent._emit_hook = AsyncMock()
            context = AgentRunContext(
                goal="original", steer_queue=run.steer_queue,
                maintenance_snapshot=None, maintenance_context={},
            )
            await agent._think_node({
                "messages": [HumanMessage(content="original")], "pending_events": [],
                "tool_rounds": 1, "runtime": context,
            })
        finally:
            agent_module.acompletion = original
        assert model_requests[0]["messages"][-1]["content"] == "change direction"
        assert (await context.event_queue.get())["type"] == "run_steered"
        run.status = "completed"
        assert server._queue_run_steer(run, "too late", "event-2") == "run_not_active"

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
            save_message=AsyncMock(), record_agent_reflection=AsyncMock(),
            mark_agent_reflections_recovered=AsyncMock(),
        )
        monkeypatch.setattr(server, "memory", memory_mock)
        monkeypatch.setattr(server, "orchestrator", SimpleNamespace(run=ask_then_finish))
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
        baseline = store.create_checkpoint(
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

    async def test_usage_sum_manual_compact_and_missing_conversation(self, client: AsyncClient) -> None:
        total = server._sum_usage([
            {"input_tokens": 2, "output_tokens": 3, "context_tokens": 5,
             "context_limit": None, "model": "m"},
            {"input_tokens": 4, "output_tokens": 1, "context_tokens": 5,
             "context_limit": None, "model": "m"},
        ])
        assert total["input_tokens"] == 6 and total["output_tokens"] == 4
        created = await client.post("/api/conversations", json={})
        conv_id = created.json()["id"]
        await server.memory.save_message(conv_id, "user", "A compactable conversation")
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
        conv_id = (await client.post("/api/conversations", json={"title": "Branch"})).json()["id"]
        first = await server.memory.save_message(conv_id, "user", "first")
        second = await server.memory.save_message(conv_id, "assistant", "second")
        fork = await client.post(f"/api/conversations/{conv_id}/fork", json={
            "through_message_id": first,
        })
        assert fork.status_code == 201 and fork.json()["files_shared"] is True
        forked_messages = await client.get(f"/api/conversations/{fork.json()['id']}/messages")
        assert [item["content"] for item in forked_messages.json()] == ["first"]
        truncated = await client.post(f"/api/conversations/{conv_id}/truncate", json={
            "from_message_id": second,
        })
        assert truncated.status_code == 200
        assert (await client.get(f"/api/conversations/{conv_id}/messages")).json()[0]["content"] == "first"
        assert (await client.post(f"/api/conversations/{conv_id}/fork", json={
            "through_message_id": "absent",
        })).status_code == 404

    async def test_chinese_trigram_and_short_like_search(self, client: AsyncClient) -> None:
        conv_id = (await client.post("/api/conversations", json={"title": "中文会话"})).json()["id"]
        await server.memory.save_message(conv_id, "user", "请记住工作区规则注入")
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


async def test_knowledge_health_approval_and_consolidated_insights_api(
    client: AsyncClient,
) -> None:
    created = await client.post("/api/memory/knowledge-health-reports")
    assert created.status_code == 200
    health_id = created.json()["id"]
    assert created.json()["status"] == "pending"

    rejected = await client.post(
        f"/api/memory/knowledge-health-reports/{health_id}/reject"
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert (await client.post(
        f"/api/memory/knowledge-health-reports/{health_id}/approve"
    )).status_code == 404

    approved_created = await client.post("/api/memory/knowledge-health-reports")
    assert approved_created.status_code == 200
    approved_id = approved_created.json()["id"]
    approved = await client.post(
        f"/api/memory/knowledge-health-reports/{approved_id}/approve"
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert (await client.post(
        f"/api/memory/knowledge-health-reports/{approved_id}/reject"
    )).status_code == 404

    listed = await client.get("/api/memory/knowledge-health-reports")
    assert listed.status_code == 200
    listed_by_id = {item["id"]: item for item in listed.json()}
    assert listed_by_id[health_id]["status"] == "rejected"
    assert listed_by_id[health_id]["review_history"][0]["decision"] == "rejected"
    assert listed_by_id[approved_id]["status"] == "approved"
    assert listed_by_id[approved_id]["review_history"][0]["decision"] == "approved"

    insights = await client.post("/api/memory/consolidated-insights")
    assert insights.status_code == 200
    assert insights.json() == []
    listed_insights = await client.get("/api/memory/consolidated-insights")
    assert listed_insights.status_code == 200
    assert listed_insights.json() == []
    applications = await client.get("/api/memory/insight-applications")
    assert applications.status_code == 200
    assert applications.json() == []
