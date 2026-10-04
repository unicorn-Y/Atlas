"""W10 wiring acceptance — persistent agents over the REAL FastAPI app.

In-process variant of tests/test_c1_websocket_acceptance.py: the same
isolated-backend idea (scripted provider, everything else real) but the app runs
via TestClient so the lifespan wiring (agent router mount, channel gateway,
heartbeat service, automation engine, telegram gating) is exercised as shipped.

Covers (controller spec §7 + W8/W7 integration):
- ws run.start with ``agent_id`` runs the full chain and projects the agent's
  runtime status (working while the run lives → idle once it settles);
- run.start without ``agent_id`` keeps the legacy behaviour;
- unknown agent → run.failed validation; W8 group_id → real room drive
  (validated group/membership, orchestrated rounds, shared timeline);
- W7→W10 bridge: a learned+approved skill reaches the agent run's system prompt;
- /api/agents CRUD + session lineage over the real mounted router.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.fakes.fake_llm_provider import FakeLLMServer, Text

pytest.importorskip("dbos")


@pytest.fixture()
def fake_llm():
    with FakeLLMServer() as fake:
        yield fake


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_llm: FakeLLMServer):
    """Full app with lifespan, isolated config, fake model gateway."""
    from atlas import config
    from atlas.telegram import TelegramService

    (tmp_path / "workspace").mkdir()
    data_root = tmp_path / "atlas-data"
    config_path = tmp_path / "config" / "atlas.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "[models]\ndefault=\"fake-model\"\n"
        f"[models.gateway]\nbase_url=\"{fake_llm.base_url}\"\napi_key=\"sk-fake-w10\"\n"
        "[[models.custom]]\nid=\"fake-model\"\nname=\"Fake fixture\"\nprovider=\"openai\"\n"
        "litellm_model=\"openai/fake-model\"\nmax_output_tokens=512\n"
        "[agent]\nverify_before_stop=false\n"
        "[tools]\nauto_start=[]\n[tools.servers]\n"
        "[scheduler]\nenabled=false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "DATA_ROOT", data_root)
    monkeypatch.setattr(config, "USER_SETTINGS_PATH", data_root / "data" / "user-settings.json")
    monkeypatch.setattr(config, "_config", None)
    for key in ("OPENAI_API_BASE", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    # The legacy telegram poll must not run in tests (gating itself is asserted
    # in test_gateway_singletons_and_legacy_telegram_gating); stop() is safe.
    monkeypatch.setattr(TelegramService, "start", lambda _self: None)

    from atlas.server import app

    with TestClient(app) as tc:
        # H8 S2: component starts (DBOS/MCP/automation/...) run as the deferred
        # task after the lifespan yields; wait so tests see the started graph.
        startup = app.state.services.startup
        if startup is not None:
            assert startup.wait_all_ready_sync(timeout=120.0), (
                f"deferred startup did not become ready: {startup.snapshot()}"
            )
        yield tc


def _create_agent(client: TestClient, tmp_path: Path, agent_id: str = "agent-w10") -> dict:
    response = client.post("/api/agents", json={
        "id": agent_id,
        "name": "Wiring Agent",
        "model": "fake-model",
        "instructions": "始终用中文回复。",
        "mode": "act",
        "agent": {"workspace": str(tmp_path / "workspace"), "enabled": True},
    })
    assert response.status_code == 201, response.text
    return response.json()


def _wait_status(client: TestClient, agent_id: str, status: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        last = client.get(f"/api/agents/{agent_id}/status").json()["status"]
        if last == status:
            return
        time.sleep(0.05)
    raise AssertionError(f"agent status never reached {status!r} (last: {last!r})")


def test_new_w10_routers_are_mounted(client: TestClient) -> None:
    # New FastAPI wraps included routers lazily (_IncludedRouter), so probe the
    # live endpoints instead of scanning app.routes.
    for path in ("/api/channels", "/api/automations", "/api/devices",
                 "/api/local/models/status", "/api/agents", "/api/groups"):
        assert client.get(path).status_code == 200, path


def test_group_singletons_are_bound_with_real_dispatcher(client: TestClient) -> None:
    """Lifespan binds GroupService + GroupOrchestrator with the real dispatcher."""
    from atlas.api.group_router import get_group_orchestrator, get_group_service
    from atlas.groups import unbound_dispatcher

    import atlas.server as server

    service = get_group_service()
    orchestrator = get_group_orchestrator()
    assert service is not None and orchestrator is not None
    assert orchestrator._service is service
    assert orchestrator._dispatcher is not unbound_dispatcher
    assert server.gateway_bridge is not None  # dispatcher's session-map dependency


def test_run_start_with_agent_id_full_chain_and_status_projection(
    client: TestClient, tmp_path: Path, fake_llm: FakeLLMServer,
) -> None:
    """Full chain, with the model call parked so the working projection is deterministic."""
    record = _create_agent(client, tmp_path)
    agent_id = record["id"]

    release = threading.Event()

    def responder(_record):
        release.wait(timeout=30)
        return Text("渠道 wired 回复")

    fake_llm._responder = responder

    conversation = client.post("/api/conversations", json={"title": "w10-agent-run"}).json()["id"]
    run_id = uuid.uuid4().hex
    with client.websocket_connect("/ws/chat") as ws:
        # NOTE: no workspace / no model — both must come from the agent record.
        ws.send_text(json.dumps({
            "type": "run.start", "run_id": run_id, "content": "report status",
            "conversation_id": conversation, "agent_id": agent_id,
        }))
        fake_llm.wait_for_requests(1, timeout=30)  # run reached the model turn
        assert client.get(f"/api/agents/{agent_id}/status").json()["status"] == "working"
        release.set()
        completed = False
        for _ in range(200):
            event = json.loads(ws.receive_text())
            if event.get("run_id") != run_id:
                continue
            if event["event"] == "run.completed":
                completed = True
                break
            if event["event"] == "run.failed":
                pytest.fail(f"run failed: {event['data']}")
    assert completed
    _wait_status(client, agent_id, "idle")
    status = client.get(f"/api/agents/{agent_id}/status").json()
    assert status["error"] == ""
    # The profile resolved: the run went out on the agent's model (fake-model;
    # litellm records the fully-qualified "openai/fake-model" string).
    assert any(str(request.get("model", "")).endswith("fake-model")
               for request in fake_llm.main_requests())


def test_run_start_without_agent_id_unchanged(client: TestClient, tmp_path: Path) -> None:
    _create_agent(client, tmp_path, "agent-legacy")
    conversation = client.post("/api/conversations", json={"title": "w10-plain-run"}).json()["id"]
    run_id = uuid.uuid4().hex
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_text(json.dumps({
            "type": "run.start", "run_id": run_id, "content": "plain run",
            "conversation_id": conversation,
            "workspace": str(tmp_path / "workspace"), "model": "fake-model",
        }))
        final = None
        for _ in range(200):
            event = json.loads(ws.receive_text())
            if event.get("run_id") == run_id and event.get("event") in {
                "run.completed", "run.failed", "run.cancelled",
            }:
                final = event
                break
    assert final is not None and final["event"] == "run.completed", final
    # The untouched agent never gets a status projection from legacy runs.
    assert client.get("/api/agents/agent-legacy/status").json()["status"] == "offline"


def _run_until_failed(client: TestClient, tmp_path: Path, extra: dict) -> dict:
    conversation = client.post("/api/conversations", json={"title": "w10-gate"}).json()["id"]
    run_id = uuid.uuid4().hex
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_text(json.dumps({
            "type": "run.start", "run_id": run_id, "content": "hi",
            "conversation_id": conversation,
            "workspace": str(tmp_path / "workspace"), **extra,
        }))
        for _ in range(50):
            event = json.loads(ws.receive_text())
            if event.get("run_id") == run_id and event.get("event") == "run.failed":
                return event["data"]
    raise AssertionError("expected run.failed")


def test_run_start_unknown_agent_fails_validation(client: TestClient, tmp_path: Path) -> None:
    failed = _run_until_failed(client, tmp_path, {"agent_id": "ghost-agent"})
    assert failed["category"] == "validation"
    assert "persistent agent not found" in failed["detail"]


def test_run_start_group_id_drives_room_and_records_timeline(
    client: TestClient, tmp_path: Path, fake_llm: FakeLLMServer,
) -> None:
    """W8 acceptance: one inbound group message → rounds → shared timeline.

    Two persistent agents form the room; run.start with group_id (from the user)
    must drive the members through the REAL dispatcher (fake LLM sees the group
    prompts) and append both the user message and the member reply to the room
    log. round_caps max_rounds=1 keeps the drive to a single round.
    """
    _create_agent(client, tmp_path, "alice")
    _create_agent(client, tmp_path, "bob")
    created = client.post("/api/groups", json={
        "id": "team", "name": "Team",
        "member_agent_ids": ["alice", "bob"],
        "round_caps": {"max_rounds": 1},
    })
    assert created.status_code == 201, created.text

    def group_responder(record: dict) -> Text:
        messages = json.dumps((record.get("body") or {}).get("messages") or [])
        # "You are @alice" — the addressee line, not the participant roster.
        return Text("hi from alice") if "You are @alice" in messages else Text("(pass)")

    fake_llm._responder = group_responder

    run_id = uuid.uuid4().hex
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_text(json.dumps({
            "type": "run.start", "run_id": run_id, "content": "hello group",
            "group_id": "team",
        }))
        fake_llm.wait_for_requests(1, timeout=30)
        final = None
        for _ in range(200):
            event = json.loads(ws.receive_text())
            if event.get("run_id") != run_id:
                continue
            if event["event"] == "run.completed":
                final = event
                break
            if event["event"] == "run.failed":
                pytest.fail(f"run failed: {event['data']}")
    assert final is not None
    report = final["data"]["group_turn"]
    assert report["status"] in {"capped", "settled"}
    timeline = client.get("/api/groups/team/timeline").json()
    entries = timeline["entries"]
    assert [entry["kind"] for entry in entries] == ["user", "member"], entries
    assert report["messages"] >= 1 and "alice" in report["speakers"], report

    assert entries[0]["actor"] == "user" and entries[0]["text"] == "hello group"
    assert entries[1]["actor"] == "alice" and entries[1]["text"] == "hi from alice"

    # The member turns went through the real dispatcher: the fake LLM saw the
    # orchestrator's group-round prompt for alice.
    group_requests = [
        request for request in fake_llm.main_requests()
        if "[Group chat:" in json.dumps(request.get("messages") or [])
    ]
    assert group_requests
    assert any("@alice" in json.dumps(request["messages"]) for request in group_requests)

    # The member's group session key landed in the agent's session lineage.
    sessions = client.get("/api/agents/alice/sessions").json()["sessions"]
    assert any(item["session_key"] == "agent:alice:group:team" for item in sessions)
    assert any(
        (item.get("conversation") or {}).get("title") == "群聊会话 team"
        for item in sessions
    )


def test_run_start_group_id_validates_group_and_membership(
    client: TestClient, tmp_path: Path,
) -> None:
    _create_agent(client, tmp_path, "agent-insider")
    _create_agent(client, tmp_path, "agent-outsider")
    created = client.post("/api/groups", json={
        "id": "room-2", "name": "Room", "member_agent_ids": ["agent-insider"],
    })
    assert created.status_code == 201, created.text

    missing = _run_until_failed(client, tmp_path, {"group_id": "ghost-room"})
    assert missing["category"] == "validation"
    assert "group not found" in missing["detail"]

    outsider = _run_until_failed(
        client, tmp_path, {"group_id": "room-2", "agent_id": "agent-outsider"})
    assert outsider["category"] == "validation"
    assert "not a member" in outsider["detail"]


def test_agents_crud_over_real_app(client: TestClient, tmp_path: Path) -> None:
    record = _create_agent(client, tmp_path, "agent-crud")
    assert record["kind"] == "persistent"

    listing = client.get("/api/agents").json()
    assert any(item["id"] == "agent-crud" for item in listing["agents"])

    fetched = client.get("/api/agents/agent-crud").json()
    assert fetched["name"] == "Wiring Agent"
    assert fetched["model"] == "fake-model"

    patched = client.patch("/api/agents/agent-crud", json={"name": "Renamed"})
    assert patched.status_code == 200
    assert client.get("/api/agents/agent-crud").json()["name"] == "Renamed"

    heartbeat = client.put(
        "/api/agents/agent-crud/heartbeat",
        json={"enabled": True, "interval_minutes": 17, "delivery": "owner"},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["heartbeat"]["enabled"] is True
    assert heartbeat.json()["heartbeat"]["interval_minutes"] == 17

    channels = client.post(
        "/api/agents/agent-crud/channels",
        json={"channel": "telegram", "target": "1001", "account": ""},
    )
    assert channels.status_code == 201
    assert client.get("/api/agents/agent-crud/channels").json()["channels"] == [
        {"channel": "telegram", "target": "1001", "account": ""},
    ]

    assert client.delete("/api/agents/agent-crud").status_code == 200
    assert client.get("/api/agents/agent-crud").status_code == 404


def test_gateway_singletons_and_legacy_telegram_gating(client: TestClient) -> None:
    """Lifespan must wire the W10 singletons; legacy telegram poll stays off by default."""
    import atlas.server as server
    from atlas.api.agent_router import get_agent_service
    from atlas.api.channel_router import get_channel_manager
    from atlas.automation import get_automation_engine

    assert server.channel_manager is get_channel_manager()
    assert server.gateway_bridge is not None
    assert server.heartbeat_service is not None
    assert get_agent_service() is not None
    engine = get_automation_engine()
    assert engine is not None and engine.started

    # The gateway's telegram channel is not enabled in the isolated data dir,
    # so on a real deployment the LEGACY service would own the poll (and vice
    # versa) — the two stacks must never double-poll. Here both starts are
    # inert; assert the gating math the lifespan applies.
    assert not (server.channel_manager.configs.get("telegram") or {}).get("enabled")


# ---------------------------------------------------------------------------
# W7 skill-workshop bridge (scenario 16) + agent session lineage
# ---------------------------------------------------------------------------

LEARNED_SKILL_BODY = "SCENARIO16-MARKER learned handoff instructions 9f3a"


def _skill_md(name: str, version: str = "1.0.0") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"version: {version}\n"
        "description: Learned by an agent run\n"
        "---\n"
        f"# {name}\n\n{LEARNED_SKILL_BODY}\n"
    )


def test_learned_skill_reaches_agent_run_system_prompt(
    client: TestClient, tmp_path: Path, fake_llm: FakeLLMServer,
) -> None:
    """Scenario 16: proposal → approve → the learned skill joins the agent's run."""
    _create_agent(client, tmp_path, "agent-learn")

    proposal = client.post("/api/skill-proposals", json={
        "skill_name": "learned-handoff",
        "files": {"SKILL.md": _skill_md("learned-handoff")},
        "origin": {"agent_id": "agent-learn"},
        "goal": "agent kept repeating a fix-up flow",
        "evidence": "3 successful runs",
    })
    assert proposal.status_code == 201, proposal.text
    proposal_id = proposal.json()["proposal_id"]

    approved = client.post(
        f"/api/skill-proposals/{proposal_id}/approve", json={"reviewer_note": "safe"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "applied"

    # The learned relation is default-enabled for the origin agent (W7 store).
    skills = client.get("/api/agents/agent-learn/skills").json()["skills"]
    row = next(item for item in skills if item["skill_name"] == "learned-handoff")
    assert row["relation"] == "learned" and row["effective"] is True

    conversation = client.post("/api/conversations", json={"title": "w10-learned"}).json()["id"]
    run_id = uuid.uuid4().hex
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_text(json.dumps({
            "type": "run.start", "run_id": run_id, "content": "continue the flow",
            "conversation_id": conversation, "agent_id": "agent-learn",
        }))
        fake_llm.wait_for_requests(1, timeout=30)
        final = None
        for _ in range(200):
            event = json.loads(ws.receive_text())
            if event.get("run_id") != run_id:
                continue
            if event["event"] == "run.completed":
                final = event
                break
            if event["event"] == "run.failed":
                pytest.fail(f"run failed: {event['data']}")
    assert final is not None
    # The skill body rode the run's system prompt to the model.
    assert any(
        LEARNED_SKILL_BODY in json.dumps(request.get("messages") or [])
        for request in fake_llm.main_requests()
    )


def test_agent_sessions_lists_gateway_lineage_with_conversation_metadata(
    client: TestClient, tmp_path: Path,
) -> None:
    """``/api/agents/{id}/sessions`` reads the gateway session map + conversations."""
    import atlas.server as server

    _create_agent(client, tmp_path, "agent-sess")
    assert client.get("/api/agents/agent-sess/sessions").json()["sessions"] == []

    conversation = client.post(
        "/api/conversations", json={"title": "lineage conversation"}).json()
    key = "agent:agent-sess:telegram:direct:1001"
    server.gateway_bridge.sessions.put(key, conversation["id"])

    listing = client.get("/api/agents/agent-sess/sessions").json()
    assert [item["session_key"] for item in listing["sessions"]] == [key]
    row = listing["sessions"][0]
    assert row["conversation_id"] == conversation["id"]
    assert row["conversation"]["id"] == conversation["id"]
    assert row["conversation"]["title"] == "lineage conversation"

    # Another agent's lineage never leaks across the prefix filter.
    server.gateway_bridge.sessions.put("agent:someone-else:main", conversation["id"])
    assert [
        item["session_key"]
        for item in client.get("/api/agents/agent-sess/sessions").json()["sessions"]
    ] == [key]

    # Unknown agents still 404 before any lineage is read.
    assert client.get("/api/agents/ghost-agent/sessions").status_code == 404
