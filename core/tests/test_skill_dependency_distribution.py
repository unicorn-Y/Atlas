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

from .conftest import API_TOKEN

SKILL_TEXT = (
    "---\nname: packaged-sample\nversion: 1.0.0\ndescription: Package sample\n"
    "dependencies:\n  python_packages:\n    - name: requests\n      version: '>=2.0'\n"
    "requirements:\n  - 'python:requests@>=2.0'\n---\nSafe skill instructions.\n"
)


def _bundle(*, skill: str = SKILL_TEXT, name: str = "packaged-sample",
            version: str = "1.0.0", hash_override: str | None = None,
            source: dict | None = None, extra: dict[str, str] | None = None,
            dependencies=None) -> bytes:
    if skill == SKILL_TEXT and version != "1.0.0":
        skill = skill.replace("version: 1.0.0", f"version: {version}")
    payload = {"SKILL.md": skill, **(extra or {})}
    manifest = {
        "format": "atlas-skill-package-v1",
        "identity": {"name": name, "version": version},
        "dependencies": dependencies if dependencies is not None else ["python:requests@>=2.0"],
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
    return {
        "X-Atlas-Skill-Center-Token": "p15e-test-token", "Origin": "null",
        "X-Atlas-Api-Token": API_TOKEN,
    }


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


def test_canonical_dependencies_accept_normalized_records_and_legacy_requirements():
    from atlas.skills.dependencies import normalize_dependencies

    canonical = normalize_dependencies({
        "python_packages": [{"name": "requests", "constraint": ">=2,<4"}],
        "commands": ["ffmpeg"], "mcp_servers": ["filesystem"],
    })
    assert canonical == [
        {"name": "requests", "kind": "python_packages", "requested": ">=2,<4"},
        {"name": "ffmpeg", "kind": "commands", "requested": None},
        {"name": "filesystem", "kind": "mcp_servers", "requested": None},
    ]
    assert normalize_dependencies(["python:requests@>=2,<4"]) == [canonical[0]]
    assert parse_dependencies(canonical) == parse_dependencies({
        "python_packages": [{"name": "requests", "version": ">=2,<4"}],
        "commands": ["ffmpeg"], "mcp_servers": ["filesystem"],
    })


@pytest.mark.parametrize(("kind", "value", "expected"), [
    ("python_packages", "requests", "python_packages"),
    ("commands", "ffmpeg", "commands"),
    ("mcp_servers", "filesystem", "mcp_servers"),
])
def test_documented_structured_dependency_mappings_normalize(kind, value, expected):
    from atlas.skills.acquisition import _parse_manifest

    content = ("---\nname: mapping-skill\nversion: 1.0.0\ndescription: Mapping\n"
               f"dependencies:\n  {kind}: [{value}]\n---\nbody\n")
    _manifest, dependencies = _parse_manifest(content, "mapping-skill")
    assert dependencies == [{"name": value, "kind": expected, "requested": None}]


def test_structured_named_version_constraint_is_canonicalized():
    from atlas.skills.acquisition import _parse_manifest

    content = ("---\nname: constrained\nversion: 1.0.0\ndescription: Constrained\n"
               "dependencies:\n  python_packages:\n    - name: requests\n"
               "      constraint: '>=2,<4'\n---\nbody\n")
    _manifest, dependencies = _parse_manifest(content, "constrained")
    assert dependencies == [{"name": "requests", "kind": "python_packages",
                             "requested": ">=2,<4"}]


def test_skill_dependency_sources_are_merged_and_deduplicated():
    from atlas.skills.acquisition import _parse_manifest
    from atlas.skills.dependencies import canonical_skill_dependencies

    content = ("---\nname: merged-skill\nversion: 1.0.0\ndescription: Merged\n"
               "dependencies:\n  python_packages: [requests, pydantic]\n"
               "requirements:\n  - 'python:requests'\n  - 'command:ffmpeg'\n---\nbody\n")
    _manifest, dependencies = _parse_manifest(content, "merged-skill")
    assert dependencies == [
        {"name": "requests", "kind": "python_packages", "requested": None},
        {"name": "pydantic", "kind": "python_packages", "requested": None},
        {"name": "ffmpeg", "kind": "commands", "requested": None},
    ]
    assert canonical_skill_dependencies(
        {"python_packages": [{"name": "requests", "version": ">=2,<4"}]},
        ["python:requests@>=2,<4"],
    ) == [{"name": "requests", "kind": "python_packages", "requested": ">=2,<4"}]


def test_legacy_requirements_only_manifest_still_normalizes():
    from atlas.skills.acquisition import _parse_manifest

    content = ("---\nname: legacy-only\nversion: 1.0.0\ndescription: Legacy\n"
               "requirements:\n  - 'python:requests@>=2,<4'\n---\nbody\n")
    _manifest, dependencies = _parse_manifest(content, "legacy-only")
    assert dependencies == [{"name": "requests", "kind": "python_packages",
                             "requested": ">=2,<4"}]


def test_package_manifest_must_include_every_modern_dependency():
    skill = ("---\nname: packaged-sample\nversion: 1.0.0\ndescription: Package sample\n"
             "dependencies:\n  python_packages: [requests, pydantic]\n"
             "requirements:\n  - 'python:requests'\n---\nSafe skill instructions.\n")
    with pytest.raises(ValueError, match="does not match SKILL.md"):
        inspect_skill_package(_bundle(
            skill=skill, dependencies=["python:requests"],
        ), "missing-modern-dependency.zip")

    acquisition = inspect_skill_package(_bundle(
        skill=skill, dependencies=["python:requests", "python:pydantic"],
    ), "complete-dependencies.zip")
    assert acquisition.validation["dependencies"] == [
        {"name": "requests", "kind": "python_packages", "requested": None},
        {"name": "pydantic", "kind": "python_packages", "requested": None},
    ]


def test_package_inspection_preserves_structured_dependency_semantics():
    skill = ("---\nname: packaged-sample\nversion: 1.0.0\ndescription: Package sample\n"
             "dependencies:\n  commands: [ffmpeg]\n---\nSafe skill instructions.\n")
    acquisition = inspect_skill_package(_bundle(
        skill=skill, dependencies={"commands": ["ffmpeg"]},
    ), "structured.zip")
    assert acquisition.validation["dependencies"] == [
        {"name": "ffmpeg", "kind": "commands", "requested": None},
    ]


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
    from atlas.skills import dependencies

    monkeypatch.setattr(dependencies, "_installed_package_version", lambda _name: "2.31.0")

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
        assert conflict.json()["exact_version_conflict"] is True
        assert conflict.json()["same_name_existing"] is True
        assert conflict.json()["import_state"] == "exact_version_conflict"
        denied_conflict = await client.post(
            "/api/skills/lifecycle/decision", headers=_headers(), json={
                "action": "install", "name": "packaged-sample", "version": "1.0.0",
                "acquisition_id": conflict.json()["acquisition_id"], "reason": "conflict check",
            },
        )
    assert installed.status_code == 200
    record = registry.get("packaged-sample", "1.0.0")
    assert record["requirements"] == [{
        "name": "requests", "kind": "python_packages", "requested": ">=2.0",
    }]
    assert "Safe skill instructions." in await server.skill_mgr.activate("packaged-sample")
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
async def test_modern_only_dependency_is_shared_by_registry_preflight_and_activation(
    tmp_path, monkeypatch,
):
    from httpx import ASGITransport, AsyncClient

    from atlas import server
    from atlas.skills import dependencies

    monkeypatch.setattr(dependencies, "_installed_package_version", lambda _name: "2.31.0")
    registry = SkillRegistry(tmp_path / "registry.db")
    skills_dir = tmp_path / "skills"
    manager = SkillManager(skills_dir)
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", manager)
    monkeypatch.setattr(server, "SKILL_CENTER_TOKEN", "p15e-test-token")
    server.skill_acquisitions.clear()
    skill = ("---\nname: modern-only\nversion: 1.0.0\ndescription: Modern only\n"
             "dependencies:\n  python_packages: [requests, pydantic]\n"
             "requirements:\n  - 'python:requests'\n---\nModern dependency body.\n")
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        preview_response = await client.post(
            "/api/skill-packages/inspect",
            content=_bundle(name="modern-only", skill=skill,
                            dependencies=["python:requests", "python:pydantic"]),
        )
        preview = preview_response.json()
        assert preview_response.status_code == 200
        assert [item["name"] for item in preview["validation"]["dependencies"]] == [
            "requests", "pydantic",
        ]
        decision = await client.post("/api/skills/lifecycle/decision", headers=_headers(), json={
            "action": "install", "name": "modern-only", "version": "1.0.0",
            "acquisition_id": preview["acquisition_id"], "reason": "verify canonical dependencies",
        })
        approval = await client.post("/api/skills/lifecycle/approve", headers=_headers(), json={
            "decision_id": decision.json()["decision_id"],
        })
        installed = await client.post("/api/skills/lifecycle/install", json={
            "acquisition_id": preview["acquisition_id"],
            "approval_token": approval.json()["approval_token"],
        })
    assert installed.status_code == 200
    expected = preview["validation"]["dependencies"]
    record = registry.get("modern-only", "1.0.0")
    assert record["requirements"] == expected
    registry_state = dependency_preflight(record["requirements"], registry=registry)
    manager.scan_skills_sync()
    manager_state = manager.preflight_dependencies("modern-only", registry=registry)
    assert registry_state == manager_state
    assert {item["name"] for item in registry_state} == {"requests", "pydantic"}
    assert all(item["state"] == "satisfied" for item in registry_state)
    assert "Modern dependency body." in await manager.activate("modern-only", registry=registry)
    server.skill_acquisitions.clear()


@pytest.mark.parametrize(("declaration", "expected_names"), [
    ("dependencies:\n  python_packages: [requests, pydantic]\n", {"requests", "pydantic"}),
    ("requirements:\n  - 'python:requests'\n", {"requests"}),
    (
        "dependencies:\n  python_packages: [requests, pydantic]\n"
        "requirements:\n  - 'python:requests'\n",
        {"requests", "pydantic"},
    ),
])
def test_startup_local_registration_persists_canonical_dependencies(
    tmp_path, declaration, expected_names,
):
    from atlas import server

    skill_dir = tmp_path / "skills" / "dev" / "local-contract"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: local-contract\nversion: 1.0.0\ndescription: Local test\n"
        f"{declaration}"
        "---\nLocal skill body.\n",
        encoding="utf-8",
    )
    manager = SkillManager(tmp_path / "skills")
    manager.scan_skills_sync()
    registry = SkillRegistry(tmp_path / "registry.db")

    # Exercise the exact registration function called by server lifespan.
    server._register_local_skills(manager, registry)

    skill = manager.get_skill("local-contract")
    record = registry.get("local-contract", "1.0.0")
    assert skill is not None and record is not None
    assert record["requirements"] == skill.dependency_contract
    assert {item["name"] for item in record["requirements"]} == expected_names
    assert len({
        (item["kind"], item["name"], item["requested"])
        for item in record["requirements"]
    }) == len(record["requirements"])
    registry_state = dependency_preflight(record["requirements"], registry=registry)
    manager_state = manager.preflight_dependencies("local-contract", registry=registry)
    assert registry_state == manager_state


@pytest.mark.parametrize(("installed_version", "should_activate"), [
    (None, False),
    ("2.31.0", True),
])
@pytest.mark.asyncio
async def test_startup_modern_only_dependency_controls_activation(
    tmp_path, monkeypatch, installed_version, should_activate,
):
    from atlas import server
    from atlas.skills import dependencies

    monkeypatch.setattr(dependencies, "_installed_package_version", lambda _name: installed_version)
    skill_dir = tmp_path / "skills" / "dev" / "startup-modern"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: startup-modern\nversion: 1.0.0\ndescription: Modern local\n"
        "dependencies:\n  python_packages: [p15e-startup-modern]\n"
        "---\nModern local body.\n",
        encoding="utf-8",
    )
    manager = SkillManager(tmp_path / "skills")
    manager.scan_skills_sync()
    registry = SkillRegistry(tmp_path / "registry.db")
    server._register_local_skills(manager, registry)

    record = registry.get("startup-modern", "1.0.0")
    assert record is not None
    registry_state = dependency_preflight(record["requirements"], registry=registry)
    manager_state = manager.preflight_dependencies("startup-modern", registry=registry)
    assert registry_state == manager_state
    assert len(registry_state) == 1
    assert registry_state[0]["state"] == ("satisfied" if should_activate else "missing")
    if should_activate:
        assert "Modern local body." in await manager.activate("startup-modern", registry=registry)
    else:
        with pytest.raises(PermissionError, match="dependencies block activation"):
            await manager.activate("startup-modern", registry=registry)


@pytest.mark.asyncio
async def test_failed_package_import_is_atomic(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from atlas import server
    from atlas.api import skills_router

    registry = SkillRegistry(tmp_path / "registry.db")
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", SkillManager(skills_dir))
    monkeypatch.setattr(server, "SKILL_CENTER_TOKEN", "p15e-test-token")
    async def fail_install(*args, **kwargs):
        raise RuntimeError("controlled installation failure")
    monkeypatch.setattr(skills_router, "install_acquisition", fail_install)
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
async def test_same_name_different_version_uses_approved_update_path(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from atlas import server
    from atlas.skills import dependencies

    monkeypatch.setattr(dependencies, "_installed_package_version", lambda _name: "2.31.0")
    registry = SkillRegistry(tmp_path / "registry.db")
    skills_dir = tmp_path / "skills"
    manager = SkillManager(skills_dir)
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", manager)
    monkeypatch.setattr(server, "SKILL_CENTER_TOKEN", "p15e-test-token")
    server.skill_acquisitions.clear()
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = (await client.post("/api/skill-packages/inspect", content=_bundle())).json()
        first_decision = await client.post(
            "/api/skills/lifecycle/decision", headers=_headers(), json={
                "action": "install", "name": "packaged-sample", "version": "1.0.0",
                "acquisition_id": first["acquisition_id"], "reason": "install v1",
            },
        )
        first_approval = await client.post(
            "/api/skills/lifecycle/approve", headers=_headers(), json={
                "decision_id": first_decision.json()["decision_id"],
            },
        )
        installed = await client.post("/api/skills/lifecycle/install", json={
            "acquisition_id": first["acquisition_id"],
            "approval_token": first_approval.json()["approval_token"],
        })
        assert installed.status_code == 200
        old_file = skills_dir / "community" / "packaged-sample" / "SKILL.md"
        old_content = old_file.read_bytes()

        second = (await client.post(
            "/api/skill-packages/inspect", content=_bundle(version="2.0.0"),
        )).json()
        assert second["import_state"] == "update_candidate"
        assert second["exact_version_conflict"] is False
        assert second["same_name_existing"] is True
        assert second["existing_version"] == "1.0.0"
        decision = await client.post("/api/skills/lifecycle/decision", headers=_headers(), json={
            "action": "update", "name": "packaged-sample", "version": "1.0.0",
            "acquisition_id": second["acquisition_id"], "reason": "review package update",
        })
        approval = await client.post("/api/skills/lifecycle/approve", headers=_headers(), json={
            "decision_id": decision.json()["decision_id"],
        })
        token = approval.json()["approval_token"]
        retargeted = await client.post("/api/skills/lifecycle/update", json={
            "acquisition_id": "another-acquisition", "version": "1.0.0",
            "approval_token": token,
        })
        updated = await client.post("/api/skills/lifecycle/update", json={
            "acquisition_id": second["acquisition_id"], "version": "1.0.0",
            "approval_token": token,
        })
        replay = await client.post("/api/skills/lifecycle/update", json={
            "acquisition_id": second["acquisition_id"], "version": "1.0.0",
            "approval_token": token,
        })

    assert retargeted.status_code == 410
    assert updated.status_code == 200 and updated.json()["version"] == "2.0.0"
    assert replay.status_code == 410
    assert registry.get("packaged-sample", "1.0.0")["lifecycle"]["state"] == "rollback-available"
    assert registry.get("packaged-sample", "2.0.0")["requirements"] == [{
        "name": "requests", "kind": "python_packages", "requested": ">=2.0",
    }]
    assert old_file.read_bytes() != old_content
    assert "version: 2.0.0" in old_file.read_text(encoding="utf-8")
    server.skill_acquisitions.clear()


@pytest.mark.asyncio
async def test_failed_version_update_preserves_registry_and_files(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from atlas import server
    from atlas.api import skills_router
    from atlas.skills import dependencies

    monkeypatch.setattr(dependencies, "_installed_package_version", lambda _name: "2.31.0")
    registry = SkillRegistry(tmp_path / "registry.db")
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", SkillManager(skills_dir))
    monkeypatch.setattr(server, "SKILL_CENTER_TOKEN", "p15e-test-token")
    original_update = skills_router.update_lifecycle_skill

    async def controlled_failure(*args, **kwargs):
        raise ValueError("controlled update failure")

    server.skill_acquisitions.clear()
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = (await client.post("/api/skill-packages/inspect", content=_bundle())).json()
        choice = await client.post("/api/skills/lifecycle/decision", headers=_headers(), json={
            "action": "install", "name": "packaged-sample", "version": "1.0.0",
            "acquisition_id": first["acquisition_id"], "reason": "install old version",
        })
        auth = await client.post("/api/skills/lifecycle/approve", headers=_headers(), json={
            "decision_id": choice.json()["decision_id"],
        })
        await client.post("/api/skills/lifecycle/install", json={
            "acquisition_id": first["acquisition_id"],
            "approval_token": auth.json()["approval_token"],
        })
        old_record = registry.get("packaged-sample", "1.0.0")
        old_path = skills_dir / "community" / "packaged-sample" / "SKILL.md"
        old_bytes = old_path.read_bytes()
        second = (await client.post(
            "/api/skill-packages/inspect", content=_bundle(version="2.0.0"),
        )).json()
        choice = await client.post("/api/skills/lifecycle/decision", headers=_headers(), json={
            "action": "update", "name": "packaged-sample", "version": "1.0.0",
            "acquisition_id": second["acquisition_id"], "reason": "controlled update failure",
        })
        auth = await client.post("/api/skills/lifecycle/approve", headers=_headers(), json={
            "decision_id": choice.json()["decision_id"],
        })
        monkeypatch.setattr(skills_router, "update_lifecycle_skill", controlled_failure)
        response = await client.post("/api/skills/lifecycle/update", json={
            "acquisition_id": second["acquisition_id"], "version": "1.0.0",
            "approval_token": auth.json()["approval_token"],
        })
    monkeypatch.setattr(skills_router, "update_lifecycle_skill", original_update)
    assert response.status_code == 409
    assert registry.get("packaged-sample", "1.0.0") == old_record
    assert registry.get("packaged-sample", "2.0.0") is None
    assert old_path.read_bytes() == old_bytes
    server.skill_acquisitions.clear()


@pytest.mark.asyncio
async def test_local_package_downgrade_uses_lifecycle_approval(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from atlas import server
    from atlas.skills import dependencies

    monkeypatch.setattr(dependencies, "_installed_package_version", lambda _name: "2.31.0")
    registry = SkillRegistry(tmp_path / "registry.db")
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", SkillManager(skills_dir))
    monkeypatch.setattr(server, "SKILL_CENTER_TOKEN", "p15e-test-token")
    server.skill_acquisitions.clear()
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        current = (await client.post(
            "/api/skill-packages/inspect", content=_bundle(version="2.0.0"),
        )).json()
        choice = await client.post(
            "/api/skills/lifecycle/decision", headers=_headers(), json={
                "action": "install", "name": "packaged-sample", "version": "2.0.0",
                "acquisition_id": current["acquisition_id"], "reason": "install current package",
            },
        )
        auth = await client.post(
            "/api/skills/lifecycle/approve", headers=_headers(), json={
                "decision_id": choice.json()["decision_id"],
            },
        )
        await client.post("/api/skills/lifecycle/install", json={
            "acquisition_id": current["acquisition_id"],
            "approval_token": auth.json()["approval_token"],
        })
        candidate = (await client.post(
            "/api/skill-packages/inspect", content=_bundle(version="1.5.0"),
        )).json()
        choice = await client.post(
            "/api/skills/lifecycle/decision", headers=_headers(), json={
                "action": "downgrade", "name": "packaged-sample", "version": "2.0.0",
                "acquisition_id": candidate["acquisition_id"], "reason": "review downgrade",
            },
        )
        auth = await client.post(
            "/api/skills/lifecycle/approve", headers=_headers(), json={
                "decision_id": choice.json()["decision_id"],
            },
        )
        updated = await client.post("/api/skills/lifecycle/update", json={
            "acquisition_id": candidate["acquisition_id"], "version": "2.0.0",
            "approval_token": auth.json()["approval_token"],
        })
    assert candidate["import_state"] == "update_candidate"
    assert updated.status_code == 200 and updated.json()["version"] == "1.5.0"
    assert registry.lifecycle_history("packaged-sample")[0]["action"] == "downgrade"
    server.skill_acquisitions.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "declaration", "package_dependencies", "expected_state"), [
    ("missing-import", "dependencies:\n  python_packages: [p15e-definitely-missing]",
     {"python_packages": ["p15e-definitely-missing"]}, "missing"),
    ("unknown-import", "requirements:\n  - unrecognized:dependency",
     ["unrecognized:dependency"], "unknown"),
])
async def test_imported_missing_or_unknown_dependency_blocks_activation(
    tmp_path, monkeypatch, name, declaration, package_dependencies, expected_state,
):
    from httpx import ASGITransport, AsyncClient

    from atlas import server

    skill = (f"---\nname: {name}\nversion: 1.0.0\ndescription: Test\n"
             f"{declaration}\n---\nblocked body\n")
    registry = SkillRegistry(tmp_path / "registry.db")
    skills_dir = tmp_path / "skills"
    manager = SkillManager(skills_dir)
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", manager)
    monkeypatch.setattr(server, "SKILL_CENTER_TOKEN", "p15e-test-token")
    server.skill_acquisitions.clear()
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        preview = await client.post("/api/skill-packages/inspect", content=_bundle(
            name=name, skill=skill, dependencies=package_dependencies,
        ))
        assert preview.status_code == 200
        assert preview.json()["dependency_state"][0]["state"] == expected_state
        choice = await client.post("/api/skills/lifecycle/decision", headers=_headers(), json={
            "action": "install", "name": name, "version": "1.0.0",
            "acquisition_id": preview.json()["acquisition_id"], "reason": "install for preflight",
        })
        approval = await client.post("/api/skills/lifecycle/approve", headers=_headers(), json={
            "decision_id": choice.json()["decision_id"],
        })
        installed = await client.post("/api/skills/lifecycle/install", json={
            "acquisition_id": preview.json()["acquisition_id"],
            "approval_token": approval.json()["approval_token"],
        })
    assert installed.status_code == 200
    requirements = registry.get(name, "1.0.0")["requirements"]
    assert requirements == preview.json()["validation"]["dependencies"]
    with pytest.raises(PermissionError, match="dependencies block activation"):
        await manager.activate(name, registry=registry)
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
