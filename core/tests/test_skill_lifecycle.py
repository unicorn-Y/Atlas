"""Persistent and safe lifecycle transitions for community skills."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3

import pytest

import atlas.skills.lifecycle as lifecycle
from atlas import server
from atlas.agent.capabilities import (
    AgentCapabilityRegistry,
    register_skill_capabilities,
    register_skill_catalog_capabilities,
    register_skill_discovery_capability,
)
from atlas.skills import SkillManager
from atlas.skills.acquisition import payload_sha256, prepare_acquisition
from atlas.skills.lifecycle import (
    dependency_states,
    inspect_skill,
    remove_skill,
    rollback_skill,
    transition_pin,
    transition_trust,
    update_skill,
)
from atlas.skills.registry import SkillRegistry

NAME = "sample-skill"
SOURCE = "owner/repo/sample-skill"


def _files(version: str, *, note: str = "safe") -> dict[str, str]:
    return {"SKILL.md": (
        f"---\nname: {NAME}\nversion: {version}\ndescription: Sample skill\n"
        "dependencies: []\n---\n" + note + "\n"
    )}


def _acquisition(version: str, *, note: str = "safe"):
    return prepare_acquisition({
        "provider": "github", "external_id": SOURCE,
        "name": NAME, "version": version,
        "source_url": "https://github.com/owner/repo",
        "source_type": "github", "remote_hash": None,
    }, _files(version, note=note))


def _installed(tmp_path, version: str = "1.0.0", *, note: str = "safe"):
    skills_dir = tmp_path / "skills"
    target = skills_dir / "community" / NAME
    target.mkdir(parents=True)
    for relative, content in _files(version, note=note).items():
        (target / relative).write_text(content, encoding="utf-8")
    digest = payload_sha256(_files(version, note=note))
    registry = SkillRegistry(tmp_path / "registry.db")
    registry.register({
        "name": NAME, "version": version, "description": "Sample skill",
        "requirements": [], "provenance": {
            "provider": "github", "external_id": SOURCE,
            "source_url": "https://github.com/owner/repo",
            "installed_path": str(target), "computed_sha256": digest,
        },
    }, source="github:" + SOURCE)
    initial = registry.get(NAME, version)
    assert initial is not None
    initial["lifecycle"] = {"state": "active", "trust_state": "unreviewed",
                            "pin_policy": "unpinned", "content_hash": digest}
    registry.record_lifecycle_event({
        "event_id": "install-event", "name": NAME, "timestamp": registry._now(),
        "action": "install", "skill_version": version, "previous_version": None,
        "previous_hash": None, "resulting_version": version, "resulting_hash": digest,
        "source": "https://github.com/owner/repo", "provider": "github",
        "trust_before": None, "trust_after": "unreviewed", "pin_before": None,
        "pin_after": "unpinned", "approval_event_id": "install-approval",
        "actor": "user", "reason": "test install", "result": "success",
        "error_code": None, "details": {},
    }, metadata=initial, version=version)
    return registry, skills_dir, target, digest


def test_legacy_installed_registry_migrates_additively_and_keeps_history(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as db:
        db.execute("""CREATE TABLE skill_registry (
            name TEXT NOT NULL, version TEXT NOT NULL, metadata TEXT NOT NULL,
            source TEXT NOT NULL, registered_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            validation_status TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY(name,version))""")
        metadata = {
            "name": NAME, "version": "1.0.0", "description": "Legacy installed skill",
            "provenance": {"installed_path": str(tmp_path / "legacy"),
                           "computed_sha256": "a" * 64, "provider": "github"},
        }
        db.execute("INSERT INTO skill_registry VALUES (?,?,?,?,?,?,?,?)", (
            NAME, "1.0.0", json.dumps(metadata), "github:test", "2026-09-01", "2026-09-01",
            "valid", "active",
        ))
    registry = SkillRegistry(db_path)
    migrated = registry.get(NAME, "1.0.0")
    assert migrated["lifecycle"]["trust_state"] == "unreviewed"
    assert migrated["lifecycle"]["content_hash"] == "a" * 64
    assert registry.lifecycle_history(NAME)[0]["action"] == "lifecycle_initialized"


@pytest.mark.asyncio
async def test_update_snapshot_and_rollback_restore_exact_payload(tmp_path):
    registry, skills_dir, target, original_hash = _installed(tmp_path)
    result = await update_skill(
        _acquisition("1.1.0", note="new payload"), registry=registry,
        skills_dir=skills_dir, current_version="1.0.0", approval_event_id="approval-1",
        reason="reviewed update",
    )
    assert result["status"] == "updated"
    assert result["rollback_snapshot_hash"] == original_hash
    restarted = SkillRegistry(registry.path)
    assert restarted.get(NAME, "1.1.0")["lifecycle"]["content_hash"] == result["hash"]
    assert restarted.get(NAME, "1.0.0")["lifecycle"]["state"] == "rollback-available"
    assert restarted.lifecycle_history(NAME)[0]["action"] == "update"
    update_event = next(event for event in restarted.lifecycle_history(NAME)
                        if event["action"] == "update")
    restored = rollback_skill(
        registry, skills_dir, NAME, "1.1.0", event_id=update_event["event_id"],
        approval_event_id="approval-2", reason="restore prior release",
    )
    assert restored["hash"] == original_hash
    assert (target / "SKILL.md").read_text(encoding="utf-8") == _files("1.0.0")["SKILL.md"]
    assert registry.get(NAME, "1.0.0")["status"] == "active"
    assert registry.lifecycle_history(NAME)[0]["action"] == "rollback"


@pytest.mark.asyncio
async def test_corrupt_snapshot_blocks_without_changing_current_payload(tmp_path):
    registry, skills_dir, target, _ = _installed(tmp_path)
    await update_skill(
        _acquisition("1.1.0", note="new payload"), registry=registry,
        skills_dir=skills_dir, current_version="1.0.0", approval_event_id="approval-1",
        reason="reviewed update",
    )
    update_event = next(event for event in registry.lifecycle_history(NAME)
                        if event["action"] == "update")
    snapshot = update_event["details"]["snapshot"]
    (tmp_path / snapshot / "SKILL.md").write_text("corrupt snapshot", encoding="utf-8")
    (target / "SKILL.md").write_text("current version survives", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        rollback_skill(
            registry, skills_dir, NAME, "1.1.0", event_id=update_event["event_id"],
            approval_event_id="approval-2", reason="restore",
        )
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "current version survives"
    assert snapshot


@pytest.mark.asyncio
async def test_missing_snapshot_blocks_without_changing_current_payload(tmp_path):
    registry, skills_dir, target, _ = _installed(tmp_path)
    await update_skill(_acquisition("1.1.0"), registry=registry, skills_dir=skills_dir,
                       current_version="1.0.0", approval_event_id="approval-1", reason="reviewed")
    event = next(item for item in registry.lifecycle_history(NAME) if item["action"] == "update")
    shutil.rmtree(event["details"]["snapshot"])
    before = (target / "SKILL.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="missing or corrupt"):
        rollback_skill(registry, skills_dir, NAME, "1.1.0", event_id=event["event_id"],
                       approval_event_id="approval-2", reason="restore")
    assert (target / "SKILL.md").read_text(encoding="utf-8") == before


@pytest.mark.asyncio
async def test_drift_blocks_rollback_before_restore(tmp_path):
    registry, skills_dir, target, _ = _installed(tmp_path)
    await update_skill(_acquisition("1.1.0"), registry=registry, skills_dir=skills_dir,
                       current_version="1.0.0", approval_event_id="approval-1", reason="reviewed")
    event = next(item for item in registry.lifecycle_history(NAME) if item["action"] == "update")
    (target / "SKILL.md").write_text("external modification", encoding="utf-8")
    with pytest.raises(PermissionError, match="drift"):
        rollback_skill(registry, skills_dir, NAME, "1.1.0", event_id=event["event_id"],
                       approval_event_id="approval-2", reason="restore")
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "external modification"


@pytest.mark.asyncio
async def test_same_identity_is_noop_and_same_version_new_hash_is_reviewed(tmp_path):
    registry, skills_dir, target, digest = _installed(tmp_path)
    no_op = await update_skill(
        _acquisition("1.0.0"), registry=registry, skills_dir=skills_dir,
        current_version="1.0.0", approval_event_id="approval-noop", reason="reviewed",
    )
    assert no_op["status"] == "unchanged"
    assert registry.get(NAME, "1.0.0")["status"] == "active"
    changed = await update_skill(
        _acquisition("1.0.0", note="changed same-version content"), registry=registry,
        skills_dir=skills_dir, current_version="1.0.0", approval_event_id="approval-change",
        reason="reviewed content change",
    )
    assert changed["status"] == "updated"
    assert changed["hash"] != digest
    assert (target / "SKILL.md").read_text(encoding="utf-8").endswith(
        "changed same-version content\n"
    )


def test_drift_blocks_inspection_sensitive_lifecycle_actions(tmp_path):
    registry, skills_dir, target, _ = _installed(tmp_path)
    (target / "SKILL.md").write_text("changed outside Atlas", encoding="utf-8")
    inspected = inspect_skill(registry, skills_dir, NAME, "1.0.0")
    assert inspected["lifecycle"]["drifted"] is True
    assert inspected["lifecycle"]["actual_hash"] != inspected["lifecycle"]["content_hash"]


def test_dependency_state_reports_satisfied_missing_incompatible_and_unknown(tmp_path):
    registry, _, _, _ = _installed(tmp_path)
    registry.register({"name": "dependency", "version": "1.0.0",
                       "description": "Installed dependency"}, source="test")
    states = dependency_states(registry, [
        "python:json", "python:module_that_is_absent", "python:json@99.0.0",
        "skill:dependency@1.0.0", "skill:dependency@2.0.0", "network",
    ])
    assert [item["state"] for item in states] == [
        "satisfied", "missing", "unknown", "satisfied", "incompatible", "unknown",
    ]


@pytest.mark.asyncio
async def test_pin_blocks_update_and_unpin_is_explicitly_audited(tmp_path):
    registry, skills_dir, _, digest = _installed(tmp_path)
    transition_pin(registry, skills_dir, NAME, "1.0.0", "exact", reason="pin release",
                   approval_event_id="pin-approval")
    with pytest.raises(PermissionError, match="pinned"):
        await update_skill(
            _acquisition("1.1.0"), registry=registry, skills_dir=skills_dir,
            current_version="1.0.0", approval_event_id="update-approval", reason="update",
        )
    transition_pin(registry, skills_dir, NAME, "1.0.0", "unpinned", reason="allow update",
                   approval_event_id="unpin-approval")
    assert [event["action"] for event in registry.lifecycle_history(NAME)[:3]] == [
        "unpin", "update", "pin",
    ]
    assert registry.lifecycle_history(NAME)[1]["result"] == "blocked"
    assert registry.get(NAME, "1.0.0")["lifecycle"]["content_hash"] == digest


def test_trust_promotion_and_revocation_are_audited_and_revocation_sticks(tmp_path):
    registry, _, _, _ = _installed(tmp_path)
    transition_trust(registry, NAME, "1.0.0", "trusted", reason="manual review",
                     approval_event_id="trust-approval")
    transition_trust(registry, NAME, "1.0.0", "revoked", reason="withdrawn",
                     approval_event_id="revoke-approval")
    with pytest.raises(PermissionError, match="cannot be restored"):
        transition_trust(registry, NAME, "1.0.0", "trusted", reason="restore",
                         approval_event_id="bad-approval")
    history = [item for item in registry.lifecycle_history(NAME) if item["result"] == "success"]
    assert [(item["trust_before"], item["trust_after"]) for item in history] == [
        ("trusted", "revoked"), ("unreviewed", "trusted"), (None, "unreviewed"),
    ]
    assert registry.lifecycle_history(NAME)[0]["result"] == "blocked"


def test_registry_upsert_cannot_erase_lifecycle_policy_or_provenance(tmp_path):
    registry, _, _, _ = _installed(tmp_path)
    transition_trust(registry, NAME, "1.0.0", "revoked", reason="withdrawn",
                     approval_event_id="revoke")
    registry.register({"name": NAME, "version": "1.0.0", "description": "Updated text"},
                      source="api-refresh")
    record = registry.get(NAME, "1.0.0")
    assert record["lifecycle"]["trust_state"] == "revoked"
    assert record["provenance"]["external_id"] == SOURCE
    with pytest.raises(ValueError, match="audited lifecycle"):
        registry.register({"name": NAME, "version": "1.0.0", "description": "Bypass",
                           "lifecycle": {"trust_state": "trusted"}})


def test_remove_keeps_registry_provenance_and_history(tmp_path):
    registry, skills_dir, target, digest = _installed(tmp_path)
    result = remove_skill(registry, skills_dir, NAME, "1.0.0", approval_event_id="remove-1",
                          reason="user requested removal")
    assert result["hash"] == digest
    assert not target.exists()
    record = registry.get(NAME, "1.0.0")
    assert record and record["provenance"]["external_id"] == SOURCE
    assert record["lifecycle"]["state"] == "removed"
    assert registry.lifecycle_history(NAME)[0]["action"] == "remove"


def test_remove_blocks_declared_dependents_without_cascading(tmp_path):
    registry, skills_dir, target, _ = _installed(tmp_path)
    registry.register({"name": "dependent-skill", "version": "1.0.0",
                       "description": "Uses the sample skill",
                       "requirements": [f"skill:{NAME}@1.0.0"]}, source="test")
    with pytest.raises(PermissionError, match="dependency"):
        remove_skill(registry, skills_dir, NAME, "1.0.0", approval_event_id="remove-1",
                     reason="user requested removal")
    assert target.exists()
    assert registry.get(NAME, "1.0.0")["status"] == "active"


def test_remove_snapshot_can_restore_the_exact_removed_payload(tmp_path):
    registry, skills_dir, target, digest = _installed(tmp_path)
    remove_skill(registry, skills_dir, NAME, "1.0.0", approval_event_id="remove-1",
                 reason="user requested removal")
    removal = next(event for event in registry.lifecycle_history(NAME)
                   if event["action"] == "remove")
    result = rollback_skill(registry, skills_dir, NAME, "1.0.0", event_id=removal["event_id"],
                            approval_event_id="restore-1", reason="restore requested")
    assert result["hash"] == digest
    assert target.exists()
    assert registry.get(NAME, "1.0.0")["status"] == "active"


@pytest.mark.asyncio
async def test_revoked_skill_cannot_update(tmp_path):
    registry, skills_dir, _, _ = _installed(tmp_path)
    transition_trust(registry, NAME, "1.0.0", "revoked", reason="security report",
                     approval_event_id="revoke-1")
    with pytest.raises(PermissionError, match="revoked"):
        await update_skill(_acquisition("1.1.0"), registry=registry, skills_dir=skills_dir,
                           current_version="1.0.0", approval_event_id="update-1", reason="update")


@pytest.mark.asyncio
async def test_concurrent_updates_serialize_and_do_not_overwrite(tmp_path):
    registry, skills_dir, target, _ = _installed(tmp_path)
    results = await asyncio.gather(*(
        update_skill(
            _acquisition(version, note=version), registry=registry, skills_dir=skills_dir,
            current_version="1.0.0", approval_event_id=f"approval-{version}", reason="reviewed",
        ) for version in ("1.1.0", "1.2.0")
    ), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, PermissionError) for result in results) == 1
    assert registry.lifecycle_history(NAME)[0]["action"] == "update"
    assert (target / "SKILL.md").exists()


@pytest.mark.asyncio
async def test_update_registry_failure_restores_files_and_registry(tmp_path, monkeypatch):
    registry, skills_dir, target, original_hash = _installed(tmp_path)

    def fail_commit(**_kwargs):
        raise RuntimeError("registry transaction failed")

    monkeypatch.setattr(registry, "commit_lifecycle_update", fail_commit)
    with pytest.raises(RuntimeError, match="registry transaction"):
        await update_skill(_acquisition("1.1.0", note="staged"), registry=registry,
                           skills_dir=skills_dir, current_version="1.0.0",
                           approval_event_id="approval", reason="reviewed")
    restored_hash = payload_sha256({
        "SKILL.md": (target / "SKILL.md").read_text(encoding="utf-8"),
    })
    assert restored_hash == original_hash
    assert registry.get(NAME, "1.0.0")["status"] == "active"
    assert registry.get(NAME, "1.1.0") is None


@pytest.mark.asyncio
async def test_filesystem_replacement_failure_leaves_state_intact(tmp_path, monkeypatch):
    registry, skills_dir, target, original_hash = _installed(tmp_path)

    def fail_replace(*_args, **_kwargs):
        raise OSError("filesystem replacement failed")

    monkeypatch.setattr(lifecycle, "_replace", fail_replace)
    with pytest.raises(OSError, match="filesystem replacement"):
        await update_skill(_acquisition("1.1.0"), registry=registry, skills_dir=skills_dir,
                           current_version="1.0.0", approval_event_id="approval", reason="reviewed")
    restored_hash = payload_sha256({
        "SKILL.md": (target / "SKILL.md").read_text(encoding="utf-8"),
    })
    assert restored_hash == original_hash
    assert registry.get(NAME, "1.0.0")["status"] == "active"


@pytest.mark.asyncio
async def test_update_remove_race_cannot_leave_half_state(tmp_path):
    registry, skills_dir, target, _ = _installed(tmp_path)
    update = update_skill(_acquisition("1.1.0"), registry=registry, skills_dir=skills_dir,
                          current_version="1.0.0", approval_event_id="update", reason="reviewed")
    remove = asyncio.to_thread(remove_skill, registry, skills_dir, NAME, "1.0.0",
                               approval_event_id="remove", reason="user confirmed")
    outcomes = await asyncio.gather(update, remove, return_exceptions=True)
    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert any(isinstance(item, (PermissionError, FileNotFoundError)) for item in outcomes)
    assert not (target.exists() and not registry.get(NAME, "1.0.0"))


@pytest.mark.asyncio
async def test_rollback_update_race_is_serialized_and_audited(tmp_path):
    registry, skills_dir, target, _ = _installed(tmp_path)
    await update_skill(_acquisition("1.1.0", note="first update"), registry=registry,
                       skills_dir=skills_dir, current_version="1.0.0",
                       approval_event_id="first", reason="reviewed")
    original_event = next(event for event in registry.lifecycle_history(NAME)
                          if event["action"] == "update")
    update = update_skill(_acquisition("1.2.0", note="second update"), registry=registry,
                          skills_dir=skills_dir, current_version="1.1.0",
                          approval_event_id="second", reason="reviewed")
    rollback = asyncio.to_thread(
        rollback_skill, registry, skills_dir, NAME, "1.1.0",
        event_id=original_event["event_id"], approval_event_id="rollback", reason="restore",
    )
    outcomes = await asyncio.gather(update, rollback, return_exceptions=True)
    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert any(isinstance(item, PermissionError) for item in outcomes)
    assert (target / "SKILL.md").exists()
    assert registry.lifecycle_history(NAME)[0]["result"] in {"success", "blocked"}


def test_one_time_lifecycle_approval_is_bound_and_replay_safe(tmp_path):
    registry, _, _, digest = _installed(tmp_path)
    import secrets
    from datetime import UTC, datetime, timedelta

    token = secrets.token_urlsafe(20)
    now = datetime.now(UTC)
    registry.issue_lifecycle_approval({
        "approval_event_id": "approval-event",
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "action": "update", "name": NAME, "version": "1.0.0", "content_hash": digest,
        "acquisition_id": "acq-1",
        "reason": "approved", "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=1)).isoformat(),
    })
    assert registry.consume_lifecycle_approval(
        token=token, action="update", name=NAME, version="1.0.0", content_hash=digest,
        acquisition_id="acq-2",
    ) is None
    assert registry.consume_lifecycle_approval(
        token=token, action="update", name=NAME, version="1.0.0", content_hash=digest,
        acquisition_id="acq-1",
    ) == {"approval_event_id": "approval-event", "reason": "approved"}
    assert registry.consume_lifecycle_approval(
        token=token, action="update", name=NAME, version="1.0.0", content_hash=digest,
        acquisition_id="acq-1",
    ) is None


@pytest.mark.asyncio
async def test_lifecycle_http_approval_replay_and_agent_boundary(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    registry, skills_dir, _, _ = _installed(tmp_path)
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", SkillManager(skills_dir=skills_dir))
    server.skill_mgr.scan_skills_sync()
    async with AsyncClient(transport=ASGITransport(app=server.app),
                           base_url="http://test") as client:
        approval = await client.post("/api/skills/lifecycle/approve", json={
            "action": "trust", "name": NAME, "version": "1.0.0", "reason": "manual review",
        })
        assert approval.status_code == 200
        auth = approval.json()
        changed = await client.post("/api/skills/lifecycle/trust", json={
            "name": NAME, "version": "1.0.0", "trust_state": "trusted",
            "approval_token": auth["approval_token"],
        })
        assert changed.status_code == 200
        replay = await client.post("/api/skills/lifecycle/trust", json={
            "name": NAME, "version": "1.0.0", "trust_state": "trusted",
            "approval_token": auth["approval_token"],
        })
        assert replay.status_code == 403
    capabilities = AgentCapabilityRegistry()
    register_skill_discovery_capability(capabilities, registry)
    names = {item["name"] for item in capabilities.discover()}
    assert "skill.lifecycle.inspect" in names
    for forbidden in ("skill.lifecycle.approve", "skill.lifecycle.update",
                      "skill.lifecycle.remove", "skill.lifecycle.rollback"):
        assert forbidden not in names
    with pytest.raises(KeyError):
        await capabilities.invoke("skill.lifecycle.approve", {"name": NAME})


@pytest.mark.asyncio
async def test_downgrade_uses_separate_server_approval_and_lifecycle_event(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from httpx import ASGITransport, AsyncClient

    registry, skills_dir, target, _ = _installed(tmp_path)
    acquisition = _acquisition("0.9.0", note="reviewed downgrade")
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", SkillManager(skills_dir=skills_dir))
    monkeypatch.setattr(server, "skill_acquisitions", {
        "downgrade-review": {"acquisition": acquisition,
                             "expires_at": datetime.now(UTC) + timedelta(minutes=5)},
    })
    async with AsyncClient(transport=ASGITransport(app=server.app),
                           base_url="http://test") as client:
        approval = await client.post("/api/skills/lifecycle/approve", json={
            "action": "downgrade", "name": NAME, "version": "1.0.0",
            "acquisition_id": "downgrade-review", "reason": "reviewed downgrade",
        })
        assert approval.status_code == 200
        response = await client.post("/api/skills/lifecycle/update", json={
            "acquisition_id": "downgrade-review", "version": "1.0.0",
            "approval_token": approval.json()["approval_token"],
        })
    assert response.status_code == 200
    assert response.json()["version"] == "0.9.0"
    assert (target / "SKILL.md").read_text(encoding="utf-8").endswith("reviewed downgrade\n")
    assert registry.lifecycle_history(NAME)[0]["action"] == "downgrade"


@pytest.mark.asyncio
async def test_trust_does_not_grant_capabilities_and_blocked_trust_blocks_activation(tmp_path):
    registry, skills_dir, _, _ = _installed(tmp_path)
    manager = SkillManager(skills_dir=skills_dir)
    manager.scan_skills_sync()
    capabilities = AgentCapabilityRegistry()
    register_skill_capabilities(capabilities, manager, registry)
    before = capabilities.discover()
    transition_trust(registry, NAME, "1.0.0", "trusted", reason="reviewed",
                     approval_event_id="trust")
    assert capabilities.discover() == before
    transition_trust(registry, NAME, "1.0.0", "blocked", reason="security issue",
                     approval_event_id="block")
    with pytest.raises(PermissionError, match="blocks activation"):
        await capabilities.invoke(f"skill.{NAME}")


@pytest.mark.asyncio
async def test_agent_can_inspect_update_availability_without_lifecycle_authority(tmp_path):
    registry, _, _, _ = _installed(tmp_path)

    class Provider:
        async def inspect(self, _external_id):
            return _acquisition("1.1.0", note="new content")

        async def search(self, _query, page=0):
            return {"results": [], "page": page}

    capabilities = AgentCapabilityRegistry()
    register_skill_catalog_capabilities(capabilities, Provider(), registry)
    inspected = await capabilities.invoke("skill.catalog.inspect", {"external_id": SOURCE})
    assert inspected["lifecycle_update"]["available"] is True
    assert inspected["lifecycle_update"]["current_version"] == "1.0.0"
    assert registry.get(NAME, "1.0.0")["version"] == "1.0.0"
    assert "skill.lifecycle.approve" not in {
        item["name"] for item in capabilities.discover()
    }
