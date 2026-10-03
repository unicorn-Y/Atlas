"""Tests for persistent agents: store records, service semantics, REST surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from atlas.api import agent_router
from atlas.gateway_service import SessionMapper
from atlas.persistent_agents import PersistentAgentService, session_key
from atlas.persistent_agents.store import (
    BUILTIN_ROLE_IDS,
    PERSISTENT_AGENT_FIELDS,
    PersistentAgentStore,
)


@pytest.fixture()
def store(tmp_path) -> PersistentAgentStore:
    return PersistentAgentStore(tmp_path)


@pytest.fixture()
def service(store) -> PersistentAgentService:
    return PersistentAgentService(store=store)


@pytest.fixture()
def client(service):
    agent_router.set_agent_service(service)
    app = FastAPI()
    app.include_router(agent_router.router)
    with TestClient(app) as test_client:
        yield test_client
    agent_router.set_agent_service(None)


def make_agent(service: PersistentAgentService, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "值班助手",
        "description": "常驻值班代理",
        "model": "claude-sonnet-4",
        "reasoning_effort": "medium",
        "instructions": "每日巡检",
        "active_skills": ["web.search"],
        "tools": {"allow": ["local_file"], "deny": ["shell"]},
        "mode": "act",
        "agent": {"workspace": "D:/work/sre", "enabled": True},
    }
    payload.update(overrides)
    return service.create(payload)


# -- record shape and store --------------------------------------------------


def test_persistent_fields_extend_legacy_whitelist() -> None:
    assert {"id", "name", "description", "model", "reasoning_effort", "instructions",
            "active_skills", "tools", "mode", "created_at", "updated_at"} <= PERSISTENT_AGENT_FIELDS
    assert {"kind", "agent"} <= PERSISTENT_AGENT_FIELDS


def test_create_persistent_defaults(service: PersistentAgentService) -> None:
    record = make_agent(service, agent=None)
    assert record["kind"] == "persistent"
    agent = record["agent"]
    assert agent["enabled"] is True
    assert agent["workspace"] == ""
    assert agent["heartbeat"]["interval_minutes"] == 30
    assert agent["heartbeat"]["delivery"] == "owner"
    assert agent["heartbeat"]["isolated_session"] is True
    assert agent["channels"] == []
    assert agent["last_status"] == "offline"


def test_unknown_field_rejected(service: PersistentAgentService) -> None:
    with pytest.raises(ValueError, match="unsupported fields"):
        make_agent(service, person="alice")
    with pytest.raises(ValueError, match="unsupported fields"):
        make_agent(service, agent={"nope": 1})


def test_builtins_seeded_as_roles(service: PersistentAgentService) -> None:
    roles = {record["id"]: record for record in service.list_agents(include_roles=True)
             if record["id"] in BUILTIN_ROLE_IDS}
    assert set(roles) == {"default", "architect", "reviewer"}
    for role in roles.values():
        assert role["kind"] == "role"
        assert "agent" not in role


def test_builtin_role_protection(service: PersistentAgentService) -> None:
    for role_id in BUILTIN_ROLE_IDS:
        with pytest.raises(ValueError, match="built-in profiles cannot be deleted"):
            service.delete(role_id)
        with pytest.raises(ValueError, match="cannot become persistent"):
            service.update(role_id, {"kind": "persistent"})
        with pytest.raises(ValueError, match="cannot become persistent"):
            service.update(role_id, {"agent": {"enabled": True}})
        assert service.get(role_id)["kind"] == "role"


def test_upgrade_plain_profile_keeps_fields(store: PersistentAgentStore,
                                            service: PersistentAgentService) -> None:
    plain = store.put({
        "name": "普通档案", "description": "升级前", "model": "gpt-x",
        "instructions": "保持原样", "active_skills": ["a"], "tools": {"allow": ["t"], "deny": []},
        "mode": "plan", "reasoning_effort": "low",
    })
    upgraded = service.update(plain["id"], {"kind": "persistent"})
    assert upgraded["kind"] == "persistent"
    for key in ("name", "description", "model", "instructions", "reasoning_effort", "mode"):
        assert upgraded[key] == plain[key]
    assert upgraded["active_skills"] == ["a"]
    assert upgraded["tools"] == {"allow": ["t"], "deny": []}
    assert upgraded["agent"]["heartbeat"]["interval_minutes"] == 30


# -- CRUD --------------------------------------------------------------------


def test_crud_roundtrip(service: PersistentAgentService) -> None:
    record = make_agent(service)
    fetched = service.get(record["id"])
    assert fetched is not None and fetched["name"] == "值班助手"

    updated = service.update(record["id"], {"name": "改名的代理"})
    assert updated["name"] == "改名的代理"
    assert updated["created_at"] == record["created_at"]
    assert updated["updated_at"] >= record["updated_at"]

    patched = service.update(record["id"], {"agent": {"enabled": False}})
    assert patched["agent"]["enabled"] is False
    # Partial agent patches must not erase sibling tables.
    assert patched["agent"]["heartbeat"]["interval_minutes"] == 30
    assert patched["agent"]["workspace"] == "D:/work/sre"

    service.delete(record["id"])
    assert service.get(record["id"]) is None
    with pytest.raises(KeyError):
        service.delete(record["id"])


def test_list_filters_roles(service: PersistentAgentService) -> None:
    make_agent(service)
    ids = {record["id"] for record in service.list_agents()}
    assert ids and all(record["kind"] == "persistent" for record in service.list_agents())
    all_ids = {record["id"] for record in service.list_agents(include_roles=True)}
    assert {"default", "architect", "reviewer"} <= all_ids


# -- run config resolution ---------------------------------------------------


def test_resolve_agent_run_config(service: PersistentAgentService) -> None:
    record = make_agent(service)
    config = service.resolve_agent_run_config(record["id"])
    assert config["profile_id"] == record["id"]
    assert config["model"] == "claude-sonnet-4"
    assert config["reasoning_effort"] == "medium"
    assert config["instructions"] == "每日巡检"
    assert config["active_skills"] == ["web.search"]
    assert config["tools"] == {"allow": ["local_file"], "deny": ["shell"]}
    assert config["mode"] == "act"
    assert config["workspace"] == "D:/work/sre"


def test_resolve_agent_run_config_inherits_workspace(service: PersistentAgentService) -> None:
    record = make_agent(service, agent={"workspace": ""})
    assert service.resolve_agent_run_config(record["id"])["workspace"] is None


def test_resolve_agent_run_config_rejects_roles_and_missing(
    service: PersistentAgentService,
) -> None:
    with pytest.raises(KeyError):
        service.resolve_agent_run_config("default")
    with pytest.raises(KeyError):
        service.resolve_agent_run_config("ghost")


# -- session keys ------------------------------------------------------------


def test_session_key_dm_scopes() -> None:
    assert session_key("atlas") == "agent:atlas:main"
    assert session_key("atlas", peer="42") == "agent:atlas:direct:42"
    assert session_key("atlas", channel="telegram", peer="42") == "agent:atlas:telegram:direct:42"
    assert session_key("atlas", channel="telegram", account="bot1", peer="42") == \
        "agent:atlas:telegram:bot1:direct:42"


def test_session_key_group_scopes() -> None:
    assert session_key("atlas", channel="telegram", peer="room1", group=True) == \
        "agent:atlas:telegram:group:room1"
    assert session_key("atlas", peer="room1", group=True) == "agent:atlas:group:room1"


def test_session_key_validation() -> None:
    with pytest.raises(ValueError):
        session_key("atlas", account="bot1", peer="42")  # account without channel
    with pytest.raises(ValueError):
        session_key("atlas", peer="a:b")  # separator collision
    with pytest.raises(ValueError):
        session_key("")  # empty agent id
    with pytest.raises(ValueError):
        session_key("atlas", group=True)  # group without room peer


# -- heartbeat configuration -------------------------------------------------


def test_heartbeat_roundtrip(service: PersistentAgentService) -> None:
    record = make_agent(service)
    updated = service.set_heartbeat(record["id"], {
        "enabled": True, "interval_minutes": 15,
        "active_hours": "09:00-23:00", "prompt": "巡检并汇报",
        "delivery": "telegram:12345",
    })
    assert updated["agent"]["heartbeat"] == {
        "enabled": True, "interval_minutes": 15, "active_hours": "09:00-23:00",
        "prompt": "巡检并汇报", "delivery": "telegram:12345", "isolated_session": True,
    }
    assert service.get_heartbeat(record["id"])["interval_minutes"] == 15


@pytest.mark.parametrize("bad", [0, -5, "30", True, 1.5])
def test_heartbeat_interval_validation(service: PersistentAgentService, bad: Any) -> None:
    record = make_agent(service)
    with pytest.raises(ValueError, match="interval_minutes"):
        service.set_heartbeat(record["id"], {"interval_minutes": bad})


@pytest.mark.parametrize("bad", ["9:00-23:00", "25:00-23:00", "09:00-23:99", "abc", "09:00_23:00"])
def test_heartbeat_active_hours_validation(service: PersistentAgentService, bad: str) -> None:
    record = make_agent(service)
    with pytest.raises(ValueError, match="active_hours"):
        service.set_heartbeat(record["id"], {"active_hours": bad})


def test_heartbeat_active_hours_empty_means_all_day(service: PersistentAgentService) -> None:
    record = make_agent(service)
    updated = service.set_heartbeat(record["id"], {"active_hours": ""})
    assert updated["agent"]["heartbeat"]["active_hours"] == ""


@pytest.mark.parametrize("bad", ["", "owner:extra:seg", "has space:x"])
def test_heartbeat_delivery_validation(service: PersistentAgentService, bad: str) -> None:
    record = make_agent(service)
    with pytest.raises(ValueError, match="delivery"):
        service.set_heartbeat(record["id"], {"delivery": bad})


def test_heartbeat_on_role_rejected(service: PersistentAgentService) -> None:
    with pytest.raises(KeyError):
        service.get_heartbeat("default")
    with pytest.raises(KeyError):
        service.set_heartbeat("default", {"enabled": True})


# -- status projection -------------------------------------------------------


def test_status_roundtrip_and_persistence(
    service: PersistentAgentService, store: PersistentAgentStore,
) -> None:
    record = make_agent(service)
    assert service.get_status(record["id"])["status"] == "offline"

    service.set_status(record["id"], "working")
    assert service.get_status(record["id"])["status"] == "working"
    persisted = store.get(record["id"])
    assert persisted is not None and persisted["agent"]["last_status"] == "working"

    service.set_status(record["id"], "waiting_user", error="需要人工确认")
    status = service.get_status(record["id"])
    assert status["status"] == "waiting_user" and status["error"] == "需要人工确认"

    with pytest.raises(ValueError, match="status must be"):
        service.set_status(record["id"], "napping")


def test_set_enabled_projects_offline(service: PersistentAgentService) -> None:
    record = make_agent(service)
    service.set_status(record["id"], "working")
    service.set_enabled(record["id"], False)
    status = service.get_status(record["id"])
    assert status["enabled"] is False and status["status"] == "offline"


def test_status_on_role_rejected(service: PersistentAgentService) -> None:
    with pytest.raises(KeyError):
        service.get_status("default")
    with pytest.raises(KeyError):
        service.set_status("default", "idle")


# -- channel bindings --------------------------------------------------------


def test_channel_bindings_crud(service: PersistentAgentService) -> None:
    record = make_agent(service)
    bindings = service.add_channel(record["id"], "telegram", "42")
    assert bindings == [{"channel": "telegram", "target": "42", "account": ""}]
    service.add_channel(record["id"], "telegram", "42")  # duplicate is idempotent
    service.add_channel(record["id"], "telegram", "43", account="bot1")
    assert len(service.list_channels(record["id"])) == 2

    assert service.remove_channel(record["id"], "telegram", "43") == [
        {"channel": "telegram", "target": "42", "account": ""},
    ]
    with pytest.raises(KeyError):
        service.remove_channel(record["id"], "telegram", "43")

    service.add_channel(record["id"], "slack", "C1", account="a")
    service.add_channel(record["id"], "slack", "C1", account="b")
    service.remove_channel(record["id"], "slack", "C1", account="a")
    assert {"b"} == {row["account"] for row in service.list_channels(record["id"])
                     if row["channel"] == "slack"}


# -- REST surface ------------------------------------------------------------


def test_api_full_flow(client: TestClient) -> None:
    created = client.post("/api/agents", json={"name": "API 代理", "agent": {"workspace": "D:/w"}})
    assert created.status_code == 201
    agent_id = created.json()["id"]
    assert created.json()["kind"] == "persistent"

    listing = client.get("/api/agents").json()["agents"]
    assert [row["id"] for row in listing] == [agent_id]
    assert listing[0]["status"] == "offline"

    assert client.get(f"/api/agents/{agent_id}").json()["name"] == "API 代理"
    roles = client.get("/api/agents", params={"include_roles": "true"}).json()["agents"]
    assert {"default", "architect", "reviewer"} <= {row["id"] for row in roles}

    patched = client.patch(f"/api/agents/{agent_id}", json={"description": "更新过"})
    assert patched.status_code == 200 and patched.json()["description"] == "更新过"

    heartbeat = client.put(f"/api/agents/{agent_id}/heartbeat", json={"interval_minutes": 10})
    assert heartbeat.status_code == 200
    assert heartbeat.json()["heartbeat"]["interval_minutes"] == 10

    status = client.put(f"/api/agents/{agent_id}/status", json={"status": "working"})
    assert status.status_code == 200 and status.json()["status"] == "working"
    assert client.get(f"/api/agents/{agent_id}/status").json()["status"] == "working"

    channels = client.post(
        f"/api/agents/{agent_id}/channels", json={"channel": "telegram", "target": "42"},
    )
    assert channels.status_code == 201
    assert client.get(f"/api/agents/{agent_id}/channels").json()["channels"][0]["target"] == "42"
    removed = client.delete(
        f"/api/agents/{agent_id}/channels", params={"channel": "telegram", "target": "42"},
    )
    assert removed.status_code == 200 and removed.json()["channels"] == []

    sessions = client.get(f"/api/agents/{agent_id}/sessions").json()
    # Wired in W8: reads the gateway session mapper (no sessions for a fresh agent).
    assert sessions["agent_id"] == agent_id
    assert sessions["sessions"] == []

    assert client.delete(f"/api/agents/{agent_id}").json() == {"status": "deleted"}
    assert client.get(f"/api/agents/{agent_id}").status_code == 404


def test_api_builtin_protection_and_errors(client: TestClient) -> None:
    assert client.delete("/api/agents/default").status_code == 409
    assert client.patch("/api/agents/default", json={"kind": "persistent"}).status_code == 422
    assert client.get("/api/agents/ghost").status_code == 404
    assert client.patch("/api/agents/ghost", json={"name": "x"}).status_code == 404
    assert client.delete("/api/agents/ghost").status_code == 404
    assert client.get("/api/agents/ghost/sessions").status_code == 404
    assert client.get("/api/agents/default/sessions").status_code == 404
    assert client.get("/api/agents/default/heartbeat").status_code in {404, 405}
    assert client.put("/api/agents/default/status", json={"status": "idle"}).status_code == 404

    bad = client.post("/api/agents", json={
        "name": "坏配置", "agent": {"heartbeat": {"interval_minutes": 0}},
    })
    assert bad.status_code == 422
    assert "interval_minutes" in bad.json()["detail"]


# -- restart survival (P11 acceptance map §2.1, scenario 1) -------------------


def test_agent_identity_survives_service_restart(tmp_path: Path) -> None:
    root = tmp_path / "profiles-root"
    first = PersistentAgentService(store=PersistentAgentStore(root))
    record = make_agent(first)
    first.set_heartbeat(record["id"], {
        "enabled": True, "interval_minutes": 15,
        "active_hours": "09:00-23:00", "prompt": "巡检并汇报",
        "delivery": "telegram:12345",
    })
    first.add_channel(record["id"], "telegram", "42")
    first.set_status(record["id"], "working")
    first.set_status(record["id"], "idle", error="巡检完成，无异常")

    # A SECOND service over the SAME store root must see the identical agent.
    second = PersistentAgentService(store=PersistentAgentStore(root))
    revived = second.get(record["id"])
    assert revived is not None
    assert revived["id"] == record["id"]
    assert revived["name"] == "值班助手"
    assert revived["model"] == "claude-sonnet-4"
    assert revived["created_at"] == record["created_at"]
    assert second.get_heartbeat(record["id"]) == {
        "enabled": True, "interval_minutes": 15, "active_hours": "09:00-23:00",
        "prompt": "巡检并汇报", "delivery": "telegram:12345", "isolated_session": True,
    }
    assert second.list_channels(record["id"]) == [
        {"channel": "telegram", "target": "42", "account": ""},
    ]
    status = second.get_status(record["id"])
    assert status["status"] == "idle"
    assert status["error"] == "巡检完成，无异常"


def test_session_mapper_mapping_survives_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "channels.sqlite"
    mapper = SessionMapper(db_path)
    mapper.put("agent:alice:telegram:123", "conv-1")
    mapper.close()

    reopened = SessionMapper(db_path)
    try:
        assert reopened.get("agent:alice:telegram:123") == "conv-1"
        # Idempotent mapping: the first conversation id wins on conflict.
        reopened.put("agent:alice:telegram:123", "conv-2")
        assert reopened.get("agent:alice:telegram:123") == "conv-1"
    finally:
        reopened.close()
