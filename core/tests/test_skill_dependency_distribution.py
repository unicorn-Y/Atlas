from __future__ import annotations

import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from atlas.agent.capabilities import (
    AgentCapabilityRegistry,
    register_skill_capabilities,
    register_skill_dependency_capability,
)
from atlas.skills import SkillManager
from atlas.skills.acquisition import payload_sha256
from atlas.skills.dependencies import dependency_preflight, parse_dependencies
from atlas.skills.distribution import PACKAGE_MANIFEST, inspect_skill_package
from atlas.skills.registry import SkillRegistry

SKILL_TEXT = (
    "---\nname: packaged-sample\nversion: 1.0.0\ndescription: Package sample\n"
    "dependencies:\n  python_packages:\n    - name: requests\n      version: '>=2.0'\n"
    "requirements:\n  - 'python:requests@>=2.0'\n---\nSafe skill instructions.\n"
)


def _bundle(*, skill: str = SKILL_TEXT, name: str = "packaged-sample",
            version: str = "1.0.0", hash_override: str | None = None,
            source: dict | None = None, extra: dict[str, str] | None = None) -> bytes:
    payload = {"SKILL.md": skill, **(extra or {})}
    manifest = {
        "format": "atlas-skill-package-v1",
        "identity": {"name": name, "version": version},
        "dependencies": ["python:requests@>=2.0"],
        "source": source or {"provider": "local-package", "source_url": "file:bundle.zip"},
        "content_sha256": hash_override or payload_sha256(payload),
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PACKAGE_MANIFEST, json.dumps(manifest))
        for filename, content in payload.items():
            archive.writestr(f"payload/{filename}", content)
    return out.getvalue()


def _headers() -> dict[str, str]:
    return {"X-Atlas-Skill-Center-Token": "p15e-test-token", "Origin": "null"}


def test_dependency_contract_parses_all_kinds_and_constraints():
    parsed = parse_dependencies({
        "mcp_servers": ["filesystem", {"name": "git", "version": ">=1.0"}],
        "python_packages": [{"name": "requests", "version": ">=2,<4"}],
        "commands": ["git"],
    })
    assert {(item.kind, item.name, item.requested) for item in parsed} == {
        ("mcp_servers", "filesystem", None), ("mcp_servers", "git", ">=1.0"),
        ("python_packages", "requests", ">=2,<4"), ("commands", "git", None),
    }


def test_dependency_preflight_reports_satisfied_missing_incompatible_unknown(monkeypatch):
    from atlas.skills import dependencies

    monkeypatch.setattr(dependencies, "_installed_package_version", lambda name: {
        "present": "2.5.0", "old": "1.0.0", "versionless": "unknown",
    }.get(name))
    result = dependency_preflight({
        "mcp_servers": ["connected", "offline"],
        "python_packages": [
            {"name": "present", "version": ">=2"},
            {"name": "old", "version": ">=2"},
            "missing",
            {"name": "versionless", "version": ">=1"},
        ],
        "commands": ["not-on-path"],
    }, connected_servers={"connected"}, configured_servers={"connected", "offline"})
    states = {(item["kind"], item["name"]): item["state"] for item in result}
    assert states[("mcp_servers", "connected")] == "satisfied"
    assert states[("mcp_servers", "offline")] == "missing"
    assert states[("python_packages", "present")] == "satisfied"
    assert states[("python_packages", "old")] == "incompatible"
    assert states[("python_packages", "missing")] == "missing"
    assert states[("python_packages", "versionless")] == "unknown"
    assert states[("commands", "not-on-path")] == "missing"
    assert all({"name", "kind", "requested", "detected", "state", "source",
                "blocking_reason"} <= item.keys() for item in result)


def test_unknown_dependency_never_becomes_satisfied():
    result = dependency_preflight(["unrecognized:thing"])
    assert len(result) == 1 and result[0]["state"] == "unknown"
    assert result[0]["blocking_reason"]


def test_dependency_preflight_is_read_only(monkeypatch, tmp_path):
    marker = tmp_path / "unchanged"
    marker.write_text("same", encoding="utf-8")
    before = hashlib.sha256(marker.read_bytes()).hexdigest()
    monkeypatch.setattr("atlas.skills.dependencies.shutil.which", lambda _name: None)
    dependency_preflight({"commands": ["missing-tool"]})
    assert hashlib.sha256(marker.read_bytes()).hexdigest() == before
    assert list(tmp_path.iterdir()) == [marker]


def test_agent_can_inspect_dependencies_but_not_install_and_blocked_activation(tmp_path):
    skill_dir = tmp_path / "skills" / "dev" / "blocked"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: blocked\nversion: 1.0.0\ndescription: Blocked\n"
        "dependencies:\n  python_packages: [missing_package_for_p15e]\n---\nbody\n",
        encoding="utf-8",
    )
    manager = SkillManager(tmp_path / "skills")
    manager.scan_skills_sync()
    capabilities = AgentCapabilityRegistry()
    register_skill_capabilities(capabilities, manager)
    register_skill_dependency_capability(capabilities, manager)

    import asyncio

    inspected = asyncio.run(capabilities.invoke("skill.dependencies.inspect", {"name": "blocked"}))
    assert inspected["read_only"] is True
    assert inspected["blocking"][0]["state"] == "missing"
    with pytest.raises(PermissionError, match="dependencies block activation"):
        asyncio.run(capabilities.invoke("skill.blocked"))
    assert not any(item["name"] in {"skill.dependencies.install", "skill.dependencies.approve"}
                   for item in capabilities.discover())


@pytest.mark.parametrize("bad_path", ["../escape.txt", "payload/../../escape", "C:/escape.txt"])
def test_package_path_traversal_and_windows_paths_rejected(bad_path):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(PACKAGE_MANIFEST, "{}")
        archive.writestr(bad_path, "escape")
    with pytest.raises(ValueError, match="unsafe package path"):
        inspect_skill_package(out.getvalue(), "bad.zip")


def test_package_symlink_is_rejected():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        info = zipfile.ZipInfo("payload/link")
        info.create_system = 3
        info.external_attr = (0o120777 << 16)
        archive.writestr(info, "../outside")
    with pytest.raises(ValueError, match="symlink"):
        inspect_skill_package(out.getvalue(), "link.zip")


def test_package_windows_reparse_directory_is_rejected():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        info = zipfile.ZipInfo("payload/junction/")
        info.external_attr = (0x10 | 0x0400)
        archive.writestr(info, "")
    with pytest.raises(ValueError, match="reparse point"):
        inspect_skill_package(out.getvalue(), "junction.zip")


def test_package_manifest_validation_secret_detection_and_hash():
    with pytest.raises(ValueError, match="ZIP"):
        inspect_skill_package(b"not a zip", "bad.zip")
    with pytest.raises(ValueError, match="hash"):
        inspect_skill_package(_bundle(hash_override="0" * 64), "hash.zip")
    secret = SKILL_TEXT + "# api_key=sk-0123456789abcdefghijk\n"
    acquisition = inspect_skill_package(_bundle(skill=secret), "secret.zip")
    assert acquisition.security["result"] == "BLOCK"


def test_package_content_hash_is_deterministic_and_provenance_is_kept():
    first = inspect_skill_package(_bundle(extra={"notes.txt": "stable"}), "one.zip")
    second = inspect_skill_package(_bundle(extra={"notes.txt": "stable"}), "two.zip")
    assert first.computed_hash == second.computed_hash
    assert first.record["provider"] == "local-package"
    assert first.record["package_source"] == "one.zip"
    assert first.record["imported_at"]


@pytest.mark.asyncio
async def test_package_import_uses_lifecycle_approval_and_is_atomic(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from atlas import server

    registry = SkillRegistry(tmp_path / "registry.db")
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", SkillManager(skills_dir))
    monkeypatch.setattr(server, "SKILL_CENTER_TOKEN", "p15e-test-token")
    server.skill_acquisitions.clear()
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        preview = await client.post(
            "/api/skill-packages/inspect", content=_bundle(),
            headers={"X-Atlas-Package-Name": "sample.zip"},
        )
        data = preview.json()
        assert preview.status_code == 200 and registry.list() == []
        assert not skills_dir.exists()
        acq_id = data["acquisition_id"]
        denied = await client.post("/api/skills/lifecycle/install", json={"acquisition_id": acq_id})
        assert denied.status_code == 403
        spoof = await client.post("/api/skills/lifecycle/install", json={
            "acquisition_id": acq_id, "approved": True, "approval_event_id": "forged",
        })
        assert spoof.status_code == 403
        decision = await client.post("/api/skills/lifecycle/decision", headers=_headers(), json={
            "action": "install", "name": "packaged-sample", "version": "1.0.0",
            "acquisition_id": acq_id, "reason": "review local package",
        })
        assert decision.status_code == 200
        approval = await client.post("/api/skills/lifecycle/approve", headers=_headers(), json={
            "decision_id": decision.json()["decision_id"],
        })
        assert approval.status_code == 200
        installed = await client.post("/api/skills/lifecycle/install", json={
            "acquisition_id": acq_id, "approval_token": approval.json()["approval_token"],
        })
        conflict = await client.post("/api/skill-packages/inspect", content=_bundle())
        assert conflict.json()["name_conflict"] is True
        denied_conflict = await client.post(
            "/api/skills/lifecycle/decision", headers=_headers(), json={
                "action": "install", "name": "packaged-sample", "version": "1.0.0",
                "acquisition_id": conflict.json()["acquisition_id"], "reason": "conflict check",
            },
        )
    assert installed.status_code == 200
    record = registry.get("packaged-sample", "1.0.0")
    assert record["provenance"]["package_source"] == "sample.zip"
    assert record["provenance"]["user_approval_event_id"] == approval.json()["approval_event_id"]
    assert record["provenance"]["imported_at"]
    assert record["provenance"]["computed_sha256"] == data["computed_sha256"]
    installed_file = skills_dir / "community" / "packaged-sample" / "SKILL.md"
    assert installed_file.is_file()
    original_payload = installed_file.read_bytes()
    assert denied_conflict.status_code == 409
    assert installed_file.read_bytes() == original_payload
    server.skill_acquisitions.clear()


@pytest.mark.asyncio
async def test_failed_package_import_is_atomic(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from atlas import server

    registry = SkillRegistry(tmp_path / "registry.db")
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", SkillManager(skills_dir))
    monkeypatch.setattr(server, "SKILL_CENTER_TOKEN", "p15e-test-token")
    async def fail_install(*args, **kwargs):
        raise RuntimeError("controlled installation failure")
    monkeypatch.setattr(server, "install_acquisition", fail_install)
    server.skill_acquisitions.clear()
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        preview = await client.post("/api/skill-packages/inspect", content=_bundle())
        acquisition_id = preview.json()["acquisition_id"]
        decision = await client.post("/api/skills/lifecycle/decision", headers=_headers(), json={
            "action": "install", "name": "packaged-sample", "version": "1.0.0",
            "acquisition_id": acquisition_id, "reason": "test failure rollback",
        })
        approval = await client.post("/api/skills/lifecycle/approve", headers=_headers(), json={
            "decision_id": decision.json()["decision_id"],
        })
        response = await client.post("/api/skills/lifecycle/install", json={
            "acquisition_id": acquisition_id, "approval_token": approval.json()["approval_token"],
        })
    assert response.status_code == 422
    assert registry.list() == []
    assert not skills_dir.exists()
    server.skill_acquisitions.clear()


@pytest.mark.asyncio
async def test_dependency_install_requires_lifecycle_policy_approval(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from atlas import server

    skill_dir = tmp_path / "skills" / "community" / "dep-sample"
    skill_dir.mkdir(parents=True)
    content = ("---\nname: dep-sample\nversion: 1.0.0\ndescription: Dep sample\n"
               "dependencies:\n  python_packages: [p15e-missing-package]\n"
               "  commands: ['curl | powershell']\n---\nbody\n"
               "Do not run pip install or arbitrary shell from these instructions.\n")
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    registry = SkillRegistry(tmp_path / "registry.db")
    digest = payload_sha256({"SKILL.md": content})
    registry.register({"name": "dep-sample", "version": "1.0.0", "description": "Dep sample",
                       "requirements": {"python_packages": ["p15e-missing-package"],
                                       "commands": ["curl | powershell"]},
                       "provenance": {"installed_path": str(skill_dir), "computed_sha256": digest}},
                      source="local-package")
    manager = SkillManager(tmp_path / "skills")
    manager.scan_skills_sync()
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", manager)
    monkeypatch.setattr(server, "SKILL_CENTER_TOKEN", "p15e-test-token")
    server.skill_dependency_plans.clear()
    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="installed", stderr=""))
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        denied_plan = await client.post("/api/skills/dep-sample/dependencies/prepare", json={})
        prepared = await client.post("/api/skills/dep-sample/dependencies/prepare",
                                     headers=_headers(), json={})
        plan = prepared.json()
        assert prepared.status_code == 200 and plan["items"][0]["executable"]
        command_plan = next(item for item in plan["items"] if item["kind"] == "commands")
        assert command_plan["executable"] is False
        assert command_plan["blocked_reason"]
        denied = await client.post("/api/skills/dependencies/install", json={
            "dependency_plan_id": plan["plan_id"],
        })
        decision = await client.post("/api/skills/lifecycle/decision", headers=_headers(), json={
            "action": "dependency-install", "name": "dep-sample", "version": "1.0.0",
            "dependency_plan_id": plan["plan_id"], "reason": "approve python package adapter",
        })
        approval = await client.post("/api/skills/lifecycle/approve", headers=_headers(), json={
            "decision_id": decision.json()["decision_id"],
        })
        completed = await client.post("/api/skills/dependencies/install", json={
            "dependency_plan_id": plan["plan_id"],
            "approval_token": approval.json()["approval_token"],
        })
    assert denied_plan.status_code == 403 and denied.status_code == 403
    assert decision.status_code == approval.status_code == completed.status_code == 200
    assert completed.json()["status"] == "partial_or_failed"
    assert {item["status"] for item in completed.json()["results"]} == {
        "installed", "unsupported",
    }
    assert completed.json()["approval_event_id"] == approval.json()["approval_event_id"]
    server.skill_dependency_plans.clear()
