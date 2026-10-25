"""REST surface tests for /api/groups (TestClient, all endpoints)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from atlas.api import group_router
from atlas.groups import GroupOrchestrator
from atlas.groups.store import DEFAULT_ROUND_CAPS, GroupService, GroupStore
from atlas.persistent_agents import PersistentAgentService
from atlas.persistent_agents.store import PersistentAgentStore


class FakeDispatcher:
    def __init__(self, default: str = "(pass)", script: dict[str, list[str]] | None = None) -> None:
        self.default = default
        self.script = dict(script or {})
        self.calls: list[dict[str, Any]] = []

    def __call__(self, agent_id: str, prompt: str, skey: str, context: dict[str, Any]):
        self.calls.append({"agent_id": agent_id, "prompt": prompt, "context": context})
        queue = self.script.get(agent_id) or []
        return queue.pop(0) if queue else self.default


@pytest.fixture()
def agent_service(tmp_path: Path) -> PersistentAgentService:
    return PersistentAgentService(store=PersistentAgentStore(tmp_path / "profiles"))


@pytest.fixture()
def service(tmp_path: Path, agent_service: PersistentAgentService) -> GroupService:
    return GroupService(GroupStore(tmp_path / "groups"), lookup=agent_service)


@pytest.fixture()
def orchestrator(service: GroupService) -> GroupOrchestrator:
    return GroupOrchestrator(service, dispatcher=FakeDispatcher(default="ok"))


@pytest.fixture()
def client(service: GroupService, orchestrator: GroupOrchestrator) -> TestClient:
    group_router.set_group_service(service)
    group_router.set_group_orchestrator(orchestrator)
    app = FastAPI()
    app.include_router(group_router.router)
    with TestClient(app) as test_client:
        yield test_client
    group_router.set_group_service(None)
    group_router.set_group_orchestrator(None)


def make_agents(agent_service: PersistentAgentService, *names: str) -> list[str]:
    return [
        agent_service.create({"name": name, "description": "peer"})["id"] for name in names
    ]


# -- CRUD ----------------------------------------------------------------------


def test_group_crud_roundtrip(client: TestClient, agent_service) -> None:
    alice, bob = make_agents(agent_service, "Alice", "Bob")
    created = client.post("/api/groups", json={
        "id": "team", "name": "Team", "member_agent_ids": [alice, bob],
        "topic_routes": [{"id": "ops", "keywords": ["deploy"], "role": "ops",
                          "agent_ids": [alice], "priority": 5}],
        "default_route": [bob], "route_fallback": "default",
    })
    assert created.status_code == 201
    record = created.json()
    assert record["enabled"] is True
    assert record["delivery"] == "origin"
    assert record["round_caps"] == DEFAULT_ROUND_CAPS
    assert record["topic_routes"][0]["id"] == "ops"
    assert record["default_route"] == [bob] and record["route_fallback"] == "default"

    listed = client.get("/api/groups").json()["groups"]
    assert [g["id"] for g in listed] == ["team"]
    assert client.get("/api/groups/team").json()["name"] == "Team"
    assert client.get("/api/groups/ghost").status_code == 404

    patched = client.patch("/api/groups/team", json={"name": "核心群", "default_route": [alice]})
    assert patched.status_code == 200
    assert patched.json()["name"] == "核心群"
    assert patched.json()["default_route"] == [alice]
    bad = client.patch("/api/groups/team", json={"bogus": 1})
    assert bad.status_code == 422

    assert client.delete("/api/groups/team").json() == {"status": "deleted"}
    assert client.get("/api/groups/team").status_code == 404
    assert client.delete("/api/groups/team").status_code == 404


def test_create_validates_members(client: TestClient, agent_service) -> None:
    alice = make_agents(agent_service, "Alice")[0]
    empty = client.post("/api/groups", json={"id": "g0", "name": "G0", "member_agent_ids": []})
    assert empty.status_code == 422
    ok = client.post("/api/groups", json={
        "id": "g1", "name": "G1", "member_agent_ids": [alice]})
    assert ok.status_code == 201
    unknown = client.post("/api/groups", json={
        "id": "g2", "name": "G2", "member_agent_ids": ["ghost"],
    })
    assert unknown.status_code == 404
    role = client.post("/api/groups", json={
        "id": "g3", "name": "G3", "member_agent_ids": ["default"],  # built-in role
    })
    assert role.status_code == 422


def test_members_endpoints(client: TestClient, agent_service) -> None:
    alice, bob = make_agents(agent_service, "Alice", "Bob")
    client.post("/api/groups", json={
        "id": "team", "name": "Team", "member_agent_ids": [alice]})
    members = client.get("/api/groups/team/members").json()
    assert members["members"] == [alice]
    assert members["agents"][0]["name"] == "Alice"
    assert members["agents"][0]["resolved"] is True

    added = client.post("/api/groups/team/members", json={"agent_id": bob})
    assert added.status_code == 201 and added.json()["members"] == [alice, bob]
    duplicate = client.post("/api/groups/team/members", json={"agent_id": bob})
    assert duplicate.status_code == 422
    unknown = client.post("/api/groups/team/members", json={"agent_id": "ghost"})
    assert unknown.status_code == 404

    removed = client.delete(
        "/api/groups/team/members", params={"agent_id": alice})
    assert removed.status_code == 200 and removed.json()["members"] == [bob]
    missing = client.delete("/api/groups/team/members", params={"agent_id": alice})
    assert missing.status_code == 404


# -- timeline / turns / stop ----------------------------------------------------


def test_turns_and_timeline_pagination(client: TestClient, agent_service) -> None:
    alice, bob, carol = make_agents(agent_service, "Alice", "Bob", "Carol")
    client.post("/api/groups", json={
        "id": "team", "name": "Team",
        "member_agent_ids": [alice, bob, carol],
        "round_caps": {"max_rounds": 2},
    })
    empty = client.get("/api/groups/team/timeline").json()
    assert empty["entries"] == []

    report = client.post("/api/groups/team/turns", json={"text": "kickoff"}).json()
    assert report["status"] == "capped" and report["capped_by"] == "max_rounds"
    assert report["rounds"] == 2 and report["messages"] == 6
    assert report["speakers"][:3] == [alice, bob, carol]

    timeline = client.get("/api/groups/team/timeline").json()
    seqs = [e["seq"] for e in timeline["entries"]]
    assert seqs == sorted(seqs) and len(seqs) == 7  # 1 user + 2 rounds x 3 member messages
    assert timeline["entries"][0]["text"] == "kickoff"

    page1 = client.get("/api/groups/team/timeline", params={"limit": 5}).json()
    assert len(page1["entries"]) == 5
    assert page1["next_before_seq"] == page1["entries"][0]["seq"]
    page2 = client.get("/api/groups/team/timeline", params={
        "limit": 5, "before_seq": page1["next_before_seq"]}).json()
    assert page2["entries"][0]["seq"] < page1["entries"][0]["seq"]
    assert not set(e["seq"] for e in page1["entries"]) & set(e["seq"] for e in page2["entries"])
    thread_page = client.get("/api/groups/team/timeline", params={"thread_id": "main"}).json()
    assert thread_page["entries"] == timeline["entries"]

    stopped = client.post("/api/groups/team/stop", json={})
    assert stopped.status_code == 200
    assert stopped.json() == {"group_id": "team", "thread_id": "main", "epoch": 1}
    event = client.get("/api/groups/team/timeline").json()["entries"][-1]
    assert event["kind"] == "event" and "epoch 1" in event["text"]


def test_turns_error_paths(client: TestClient, agent_service) -> None:
    alice = make_agents(agent_service, "Alice")[0]
    client.post("/api/groups", json={
        "id": "team", "name": "Team", "member_agent_ids": [alice]})
    assert client.post("/api/groups/ghost/turns", json={"text": "hi"}).status_code == 404
    assert client.post("/api/groups/team/turns", json={"text": "  "}).status_code == 422
    assert client.post(
        "/api/groups/team/turns", json={"text": "hi", "from_actor": "ghost"}).status_code == 422
    client.patch("/api/groups/team", json={"enabled": False})
    assert client.post("/api/groups/team/turns", json={"text": "hi"}).status_code == 422


def test_disabled_group_and_thread_param(client: TestClient, agent_service) -> None:
    alice = make_agents(agent_service, "Alice")[0]
    client.post("/api/groups", json={
        "id": "team", "name": "Team", "member_agent_ids": [alice]})
    report = client.post("/api/groups/team/turns", json={
        "text": "threaded", "thread_id": "incident-42"}).json()
    assert report["thread_id"] == "incident-42"
    stopped = client.post("/api/groups/team/stop", json={"thread_id": "incident-42"}).json()
    assert stopped["thread_id"] == "incident-42" and stopped["epoch"] == 1
    main_stop = client.post("/api/groups/team/stop", json={}).json()
    assert main_stop["thread_id"] == "main" and main_stop["epoch"] == 1  # epochs are per-thread
