"""W7 per-agent skill collections + agent_skills_router tests.

Covers: relation CRUD, ``effective_skills`` semantics (per-agent opt-in/opt-out
priority over the global lifecycle state), usage accumulation, and every router
endpoint through a standalone FastAPI app + TestClient (OriginGuard conventions).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.origin_guard import OriginGuard
from atlas.skills.agent_collections import (
    AGGREGATE_AGENT,
    AgentSkillCollections,
    CollectionError,
)
from atlas.skills.market import SkillMarket
from atlas.skills.proposals import SkillProposalStore
from atlas.skills.registry import SkillRegistry

TOKEN = "test-atlas-api-token"  # conftest exports ATLAS_API_TOKEN


def skill_md(name: str, version: str, description: str = "Agent skill") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"version: {version}\n"
        f"description: {description}\n"
        "---\n"
        f"# {name}\n\nBody for {name} v{version}.\n"
    )


class Env:
    def __init__(self, tmp_path) -> None:
        self.tmp = tmp_path
        self.registry = SkillRegistry(tmp_path / "atlas.db")
        self.user_skills = tmp_path / "skills"
        self.market = SkillMarket(
            self.registry, data_dir=tmp_path / "data", user_skills_dir=self.user_skills,
        )
        self.collections = AgentSkillCollections(self.registry)
        self.store = SkillProposalStore(
            self.registry, market=self.market, collections=self.collections,
        )

    def seed_skill(self, name: str, version: str = "1.0.0") -> None:
        skill_dir = self.user_skills / "community" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_md(name, version), encoding="utf-8")
        self.market.register_local(
            name, path=skill_dir, origin_kind="agent_learned",
            source="agent", reason="seed")


@pytest.fixture()
def env(tmp_path):
    return Env(tmp_path)


# ---------------------------------------------------------------------------
# agent_collections: relation CRUD
# ---------------------------------------------------------------------------

def test_relation_crud_and_validation(env) -> None:
    env.seed_skill("crud-skill")
    row = env.collections.set_agent_skill(
        "a1", "crud-skill", enabled=True, relation="default_enabled", note="factory")
    assert row["enabled"] is True and row["relation"] == "default_enabled"
    assert row["enabled_at"] and row["disabled_at"] is None

    updated = env.collections.set_agent_skill(
        "a1", "crud-skill", enabled=False, relation="suggested")
    assert updated["enabled"] is False and updated["relation"] == "suggested"
    assert updated["disabled_at"] and updated["enabled_at"]  # first enable kept

    assert env.collections.remove_agent_skill("a1", "crud-skill") is True
    assert env.collections.remove_agent_skill("a1", "crud-skill") is False
    assert env.collections.list_agent_skills("a1") == []

    with pytest.raises(CollectionError):
        env.collections.set_agent_skill(
            "a1", "crud-skill", enabled=True, relation="best_friend")
    with pytest.raises(CollectionError):
        env.collections.set_agent_skill("a1", "Not Kebab!", enabled=True)
    with pytest.raises(CollectionError):
        env.collections.set_agent_skill(" ", "crud-skill", enabled=True)


# ---------------------------------------------------------------------------
# effective_skills semantics (frozen by the lane contract)
# ---------------------------------------------------------------------------

def test_effective_skills_semantics(env) -> None:
    env.seed_skill("open-skill")       # globally active, no row -> effective (global)
    env.seed_skill("opted-out")        # globally active + agent disable -> hidden
    env.seed_skill("globally-off")     # globally disabled + agent opt-in -> effective
    env.registry.disable("globally-off", "1.0.0")

    collections = env.collections
    collections.set_agent_skill("a1", "opted-out", enabled=False, relation="adopted")
    collections.set_agent_skill("a1", "globally-off", enabled=True, relation="adopted")

    effective = {row["skill_name"]: row for row in collections.effective_skills("a1")}
    assert effective["open-skill"]["effective"] is True
    assert effective["open-skill"]["decision"] == "global"
    assert effective["open-skill"]["relation"] is None
    assert effective["opted-out"]["effective"] is False
    assert effective["opted-out"]["decision"] == "per_agent"
    assert effective["globally-off"]["effective"] is True
    assert effective["globally-off"]["decision"] == "per_agent"
    assert effective["globally-off"]["version"] == "1.0.0"

    # A different agent without rows sees only the globally active skills.
    other = {row["skill_name"]: row for row in collections.effective_skills("a2")}
    assert other["open-skill"]["effective"] and other["opted-out"]["effective"]
    assert other["globally-off"]["effective"] is False


def test_learned_relation_defaults_enabled_after_apply(env) -> None:
    env.store.create_proposal(
        "learned-one",
        files={"SKILL.md": skill_md("learned-one", "1.0.0")},
        origin={"agent_id": "agent-9"})
    env.store.approve(
        [p for p in env.store.list(status="pending")][0]["proposal_id"])
    rows = {r["skill_name"]: r for r in env.collections.list_agent_skills("agent-9")}
    assert rows["learned-one"]["relation"] == "learned"
    assert rows["learned-one"]["enabled"] is True
    effective = {r["skill_name"]: r for r in env.collections.effective_skills("agent-9")}
    assert effective["learned-one"]["effective"] is True


# ---------------------------------------------------------------------------
# usage telemetry
# ---------------------------------------------------------------------------

def test_usage_accumulates_per_agent_and_aggregate(env) -> None:
    env.seed_skill("used-skill")
    collections = env.collections
    collections.record_usage("used-skill", "a1", version="1.0.0")
    collections.record_usage("used-skill", "a1", version="1.0.0")
    collections.record_usage("used-skill", "a2", version="1.0.0")

    stats = collections.usage_stats("used-skill")
    assert stats["skill_name"] == "used-skill"
    assert stats["total_use_count"] == 3
    assert stats["distinct_agents"] == 2
    assert {row["agent_id"]: row["use_count"] for row in stats["agents"]} == {
        "a1": 2, "a2": 1,
    }
    assert stats["last_used_at"]
    # aggregate row exists too ('*'), keeping per-agent rows untouched
    with_close = collections.usage_stats("used-skill")
    assert with_close["agents"][0]["agent_id"] != AGGREGATE_AGENT


# ---------------------------------------------------------------------------
# Router: every endpoint via TestClient
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(env):
    from atlas.api import agent_skills_router as router_module

    router_module.set_collections(env.collections)
    router_module.set_proposals(env.store)
    app = FastAPI()
    app.add_middleware(OriginGuard)
    app.include_router(router_module.router)
    try:
        yield TestClient(app), env
    finally:
        router_module.set_collections(None)
        router_module.set_proposals(None)


def test_router_auth_shape(client) -> None:
    test_client, env = client
    env.seed_skill("auth-skill")
    assert test_client.get(
        "/api/agents/a1/skills", headers={"Origin": "https://evil.example"},
    ).status_code == 403
    ok = test_client.get(
        "/api/agents/a1/skills",
        headers={"Origin": "https://evil.example", "X-Atlas-Api-Token": TOKEN})
    assert ok.status_code == 200
    assert test_client.get("/api/agents/a1/skills").status_code == 200


def test_agent_skills_get_and_batch_put(client) -> None:
    test_client, env = client
    env.seed_skill("batch-skill")
    env.seed_skill("hidden-skill")
    response = test_client.put("/api/agents/a1/skills", json={"skills": [
        {"skill_name": "batch-skill", "enabled": True, "relation": "adopted"},
        {"skill_name": "hidden-skill", "enabled": False, "relation": "suggested",
         "note": "not for this agent"},
    ]})
    assert response.status_code == 200
    assert response.json()["updated"] == 2

    listing = test_client.get("/api/agents/a1/skills").json()
    by_name = {row["skill_name"]: row for row in listing["skills"]}
    assert by_name["batch-skill"]["effective"] is True
    assert by_name["hidden-skill"]["effective"] is False

    invalid = test_client.put("/api/agents/a1/skills", json={"skills": [
        {"skill_name": "batch-skill", "enabled": True, "relation": "buddy"},
    ]})
    assert invalid.status_code == 422


def test_proposal_endpoints_full_lifecycle(client) -> None:
    test_client, env = client
    created = test_client.post("/api/skill-proposals", json={
        "skill_name": "router-learned",
        "files": {"SKILL.md": skill_md("router-learned", "1.0.0")},
        "origin": {"agent_id": "agent-1", "run_id": "run-1"},
        "goal": "router lifecycle",
    })
    assert created.status_code == 201
    proposal_id = created.json()["proposal_id"]
    assert created.json()["status"] == "pending"

    listing = test_client.get(
        "/api/skill-proposals", params={"status": "pending"}).json()
    assert listing["count"] == 1
    detail = test_client.get(f"/api/skill-proposals/{proposal_id}").json()
    assert [e["event"] for e in detail["events"]] == ["created"]

    approved = test_client.post(
        f"/api/skill-proposals/{proposal_id}/approve",
        json={"reviewer_note": "ship it"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "applied"

    # learned relation surfaced on the agent's collection
    skills = test_client.get("/api/agents/agent-1/skills").json()
    row = {item["skill_name"]: item for item in skills["skills"]}["router-learned"]
    assert row["relation"] == "learned" and row["effective"] is True

    # second approve -> state-machine conflict (409)
    again = test_client.post(f"/api/skill-proposals/{proposal_id}/approve", json={})
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "proposal_conflict"

    # usage endpoint reflects telemetry written post-apply
    env.collections.record_usage("router-learned", "agent-1", version="1.0.0")
    usage = test_client.get("/api/skills/router-learned/usage").json()
    assert usage["total_use_count"] == 1
    assert usage["agents"][0]["agent_id"] == "agent-1"

    rolled = test_client.post(f"/api/skill-proposals/{proposal_id}/rollback", json={})
    assert rolled.status_code == 200
    assert rolled.json()["rolled_back_at"]
    assert test_client.get("/api/skills/router-learned/usage").json() == usage


def test_proposal_reject_and_stale_conflict_over_http(client) -> None:
    test_client, env = client
    created = test_client.post("/api/skill-proposals", json={
        "skill_name": "http-reject",
        "files": {"SKILL.md": skill_md("http-reject", "1.0.0")},
    })
    proposal_id = created.json()["proposal_id"]
    rejected = test_client.post(
        f"/api/skill-proposals/{proposal_id}/reject",
        json={"reason": "not good enough"})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert test_client.post(
        f"/api/skill-proposals/{proposal_id}/approve", json={}).status_code == 409

    # stale drift -> approve returns 409 with the stale code
    env.seed_skill("http-drift")
    drift = test_client.post("/api/skill-proposals", json={
        "skill_name": "http-drift",
        "files": {"SKILL.md": skill_md("http-drift", "2.0.0")},
    })
    drift_id = drift.json()["proposal_id"]
    env.seed_skill("http-drift", version="1.1.0")
    stale = test_client.post(f"/api/skill-proposals/{drift_id}/approve", json={})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "proposal_stale"
    detail = test_client.get(f"/api/skill-proposals/{drift_id}").json()
    assert detail["status"] == "stale"

    missing = test_client.post("/api/skill-proposals/prop-missing/approve", json={})
    assert missing.status_code == 404
    empty = test_client.post("/api/skill-proposals", json={"skill_name": "void-proposal"})
    assert empty.status_code == 422
