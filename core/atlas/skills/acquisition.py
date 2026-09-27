"""Untrusted external skill discovery, review, and explicitly approved installation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import yaml

from atlas.skills.registry import SkillRegistry

MAX_FILES = 100
MAX_FILE_BYTES = 512_000
MAX_PAYLOAD_BYTES = 2_000_000
NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
VERSION_RE = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
_INSTALL_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_INSTALL_LOCKS_GUARD = threading.Lock()
SECRET_RE = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|password|passwd|secret|credential)"
    r"\s*[:=]\s*\S+|\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{12,}"
)
RISK_PATTERNS = {
    "execution": re.compile(
        r"(?im)\b(?:sudo|powershell|pwsh|cmd\.exe|bash|sh)\b.{0,80}(?:-c|/c|\|)"
    ),
    "install_command": re.compile(r"(?im)\b(?:pip|npm|pnpm|yarn|apt|brew)\s+install\b"),
    "network_download": re.compile(r"(?im)\b(?:curl|wget|Invoke-WebRequest)\b"),
    "atlas_state": re.compile(
        r"(?i)(?:atlas\.toml|approval|capabilit(?:y|ies)|memoryos).{0,60}(?:modify|edit|overwrite|disable|bypass)"
    ),
    "prompt_injection": re.compile(
        r"(?i)(?:ignore|override|disregard).{0,60}(?:previous|system|safety|developer)\s+(?:instructions|rules|prompt)"
    ),
}


@dataclass
class Acquisition:
    record: dict[str, Any]
    files: dict[str, str]
    validation: dict[str, Any]
    security: dict[str, Any]
    computed_hash: str


class CatalogUnavailableError(RuntimeError):
    pass


def _provider_reference_sha256(files: dict[str, str]) -> str:
    """Run the skills CLI reference hash implementation under Node Intl."""
    reference = (
        "const {createHash}=require('node:crypto');"
        "let input='';process.stdin.setEncoding('utf8');"
        "process.stdin.on('data',chunk=>input+=chunk);"
        "process.stdin.on('end',()=>{const files=JSON.parse(input);"
        "const hash=createHash('sha256');"
        "for(const file of files.sort((a,b)=>a.path.localeCompare(b.path))){"
        "hash.update(file.path);hash.update(file.contents);"
        "}process.stdout.write(hash.digest('hex'));});"
    )
    try:
        result = subprocess.run(
            ["node", "-e", reference],
            input=json.dumps(
                [{"path": path, "contents": content} for path, content in files.items()],
                ensure_ascii=False,
            ),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CatalogUnavailableError("provider reference hash verifier unavailable") from exc
    digest = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CatalogUnavailableError("provider reference hash verifier failed")
    return digest


def _provider_snapshot_files(items: list[Any]) -> dict[str, str]:
    if len(items) > MAX_FILES:
        raise ValueError("payload exceeds file count limit")
    files: dict[str, str] = {}
    for item in items:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("contents"), str)
        ):
            raise ValueError("provider snapshot contains an invalid file entry")
        if item["path"] in files:
            raise ValueError("provider snapshot contains duplicate paths")
        files[item["path"]] = item["contents"]
    return files


class SkillsShProvider:
    """skills.sh provider using its public search route and GitHub file payloads."""

    name = "skills.sh"
    base_url = "https://skills.sh"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _get(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        try:
            if self._client:
                response = await self._client.get(url, params=params, follow_redirects=False)
            else:
                async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
                    response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise CatalogUnavailableError("external-catalog-unavailable") from exc
        if response.status_code == 429:
            raise CatalogUnavailableError("external-catalog-unavailable: rate limited")
        if response.status_code >= 500:
            raise CatalogUnavailableError("external-catalog-unavailable: provider error")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise CatalogUnavailableError(
                f"external-catalog-unavailable: HTTP {response.status_code}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise CatalogUnavailableError(
                "external-catalog-unavailable: invalid provider response"
            ) from exc

    async def search(self, query: str, *, page: int = 0, limit: int = 20) -> dict[str, Any]:
        if len(query.strip()) < 2:
            return {
                "provider": self.name,
                "results": [],
                "pagination": {"page": page, "has_more": False},
                "status": "available",
            }
        offset = page * limit
        request_limit = min(offset + limit + 1, 200)
        data = await self._get(
            f"{self.base_url}/api/search",
            params={"q": query.strip(), "limit": max(request_limit, 20)},
        )
        items = data.get("skills", []) if isinstance(data, dict) else []
        results = []
        seen_ids: set[str] = set()
        has_more = len(items) > offset + limit
        for item in items[offset : offset + limit]:
            external_id = str(item.get("id", ""))
            source = str(item.get("source", ""))
            slug = str(item.get("name", ""))
            if (
                not external_id
                or not re.fullmatch(
                    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
                    external_id,
                )
                or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source)
            ):
                continue
            if external_id in seen_ids:
                continue
            seen_ids.add(external_id)
            results.append(
                {
                    "provider": self.name,
                    "external_id": external_id,
                    "name": slug,
                    "description": "",
                    "source": source,
                    "source_type": "github",
                    "version": None,
                    "source_url": f"https://github.com/{source}",
                    "install_url": f"{self.base_url}/{quote(source)}/{quote(slug)}",
                    "remote_hash": None,
                    "audit": None,
                    "provenance": {"installs": item.get("installs")},
                    "installed": False,
                    "state": "remote",
                }
            )
        return {
            "provider": self.name,
            "results": results,
            "pagination": {"page": page, "limit": limit, "has_more": has_more},
            "status": "available",
        }

    async def get_detail(self, external_id: str) -> dict[str, Any] | None:
        parts = external_id.split("/")
        if len(parts) != 3 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
            raise ValueError("invalid skills.sh external_id")
        return await self._get(
            f"{self.base_url}/api/v1/skills/" + "/".join(quote(p, safe="") for p in parts)
        )

    async def get_snapshot(self, external_id: str) -> dict[str, Any] | None:
        parts = external_id.split("/")
        if len(parts) != 3 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
            raise ValueError("invalid skills.sh external_id")
        return await self._get(
            f"{self.base_url}/api/download/" + "/".join(quote(part, safe="") for part in parts)
        )

    async def get_audit(self, external_id: str) -> dict[str, Any] | None:
        parts = external_id.split("/")
        if len(parts) != 3:
            raise ValueError("invalid skills.sh external_id")
        return await self._get(
            f"{self.base_url}/api/v1/skills/audit/" + "/".join(quote(p, safe="") for p in parts)
        )

    async def inspect(self, external_id: str) -> Acquisition:
        parts = external_id.split("/")
        try:
            snapshot = await self.get_snapshot(external_id)
        except CatalogUnavailableError:
            snapshot = None
        if isinstance(snapshot, dict) and isinstance(snapshot.get("files"), list):
            files = _provider_snapshot_files(snapshot["files"])
            source = "/".join(parts[:2])
            record = {
                "provider": self.name,
                "external_id": external_id,
                "name": parts[2],
                "description": "",
                "source": source,
                "source_type": "github",
                "version": None,
                "source_url": f"https://github.com/{source}",
                "install_url": f"{self.base_url}/{quote(source)}/{quote(parts[2])}",
                "remote_hash": snapshot.get("hash"),
                "audit": None,
                "fetched_at": datetime.now(UTC).isoformat(),
            }
            try:
                record["audit"] = await self.get_audit(external_id)
            except CatalogUnavailableError:
                pass
            acquisition = prepare_acquisition(record, files)
            if (
                acquisition.security["result"] != "BLOCK"
                or "remote_hash_mismatch" not in acquisition.security["risks"]
            ):
                return acquisition
            return await self._resolve_provider_mismatch(external_id, acquisition)
        try:
            detail = await self.get_detail(external_id)
        except CatalogUnavailableError:
            detail = None
        if not isinstance(detail, dict) or not isinstance(detail.get("files"), list):
            if len(parts) == 3:
                source = "/".join(parts[:2])
                for path in (f"skills/{parts[2]}", parts[2], ""):
                    try:
                        return await inspect_github_source(
                            f"https://github.com/{source}",
                            skill_path=path,
                        )
                    except ValueError:
                        continue
            raise CatalogUnavailableError(
                "external-catalog-unavailable: skill payload is unavailable"
            )
        source = str(detail.get("source", "/".join(parts[:2])))
        slug = str(detail.get("slug", parts[-1]))
        files = _provider_snapshot_files(detail["files"])
        audit = None
        try:
            audit = await self.get_audit(external_id)
        except CatalogUnavailableError:
            audit = None
        record = {
            "provider": self.name,
            "external_id": external_id,
            "name": slug,
            "description": "",
            "source": source,
            "source_type": "github",
            "version": None,
            "source_url": f"https://github.com/{source}",
            "install_url": f"{self.base_url}/{quote(source)}/{quote(slug)}",
            "remote_hash": detail.get("hash"),
            "audit": audit,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        acquisition = prepare_acquisition(record, files)
        if (
            acquisition.security["result"] != "BLOCK"
            or "remote_hash_mismatch" not in acquisition.security["risks"]
        ):
            return acquisition
        return await self._resolve_provider_mismatch(external_id, acquisition)

    async def _resolve_provider_mismatch(
        self, external_id: str, provider_acquisition: Acquisition
    ) -> Acquisition:
        parts = external_id.split("/")
        source = "/".join(parts[:2])
        slug = parts[2]
        provider_hash = provider_acquisition.record.get("remote_hash")
        provider_reference_hash = provider_acquisition.record.get("provider_computed_hash")
        diagnostic = {
            "provider_hash": provider_hash,
            "provider_computed_hash": provider_reference_hash,
            "provider_mismatch": True,
            "fallback_reason": "provider_hash_mismatch",
        }
        github_acquisition = None
        github_error = None
        candidates = (
            f"skills/{slug}",
            slug,
            f".agents/skills/{slug}",
            f".claude/skills/{slug}",
        )
        for candidate in candidates:
            try:
                github_acquisition = await inspect_github_source(
                    f"https://github.com/{source}", candidate, client=self._client
                )
                break
            except ValueError as exc:
                github_error = str(exc)
                continue
            except (CatalogUnavailableError, httpx.HTTPError) as exc:
                github_error = str(exc)
                break
        if github_acquisition is None and github_error and "GitHub skill path" in github_error:
            try:
                github_acquisition = await inspect_github_source(
                    f"https://github.com/{source}", expected_name=slug, client=self._client
                )
            except (CatalogUnavailableError, ValueError, httpx.HTTPError) as exc:
                github_error = str(exc)
        if github_acquisition is None:
            provider_acquisition.security = {
                "result": "BLOCK",
                "risks": ["remote_hash_mismatch", "github_source_unavailable"],
                "note": "Provider hash mismatch; GitHub source could not be verified.",
            }
            diagnostic["github_source_error"] = github_error or "GitHub skill source not found"
            diagnostic["status"] = "github_source_unavailable"
            diagnostic["message"] = (
                "Catalog snapshot and provider hash mismatch; "
                "GitHub source could not be verified."
            )
            provider_acquisition.record["integrity_diagnostic"] = diagnostic
            return provider_acquisition
        if github_acquisition.files != provider_acquisition.files:
            provider_acquisition.security = {
                "result": "BLOCK",
                "risks": ["remote_hash_mismatch", "catalog_source_mismatch"],
                "note": "The catalog snapshot does not match the current GitHub source.",
            }
            diagnostic.update({
                "status": "catalog_source_mismatch",
                "message": (
                    "Catalog snapshot differs from the current GitHub source; "
                    "installation is blocked."
                ),
                "github_source": github_acquisition.record["source_url"],
                "github_source_revision": github_acquisition.record.get("github_source_revision"),
                "github_tree_sha": github_acquisition.record.get("github_tree_sha"),
                "source_match": False,
            })
            provider_acquisition.record["integrity_diagnostic"] = diagnostic
            return provider_acquisition

        record = {
            **github_acquisition.record,
            "provider": self.name,
            "external_id": external_id,
            "remote_hash": provider_hash,
            "provider_integrity": {
                **diagnostic,
                "source_match": True,
                "github_source": github_acquisition.record["source_url"],
                "github_source_revision": github_acquisition.record.get("github_source_revision"),
                "github_tree_sha": github_acquisition.record.get("github_tree_sha"),
            },
            "integrity_diagnostic": {
                "status": "github_fallback",
                "message": (
                    "Catalog snapshot matched GitHub source; "
                    "acquisition uses verified GitHub files."
                ),
            },
        }
        safe_acquisition = prepare_acquisition(record, github_acquisition.files)
        return safe_acquisition


def _parse_manifest(content: str, expected_name: str) -> tuple[dict[str, Any], list[str]]:
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", content, re.DOTALL)
    if not match:
        raise ValueError("SKILL.md frontmatter is missing or not closed")
    raw = yaml.safe_load(match.group(1))
    if not isinstance(raw, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    name, version, description = (
        raw.get("name"),
        raw.get("version", "0.0.0"),
        raw.get("description"),
    )
    if not isinstance(name, str) or not NAME_RE.fullmatch(name) or name != expected_name:
        raise ValueError("manifest name must match the target identity")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError("manifest version must be MAJOR.MINOR.PATCH")
    raw["version"] = version
    if not isinstance(description, str) or not description.strip():
        raise ValueError("manifest description is required")
    if _contains_secret(raw):
        raise ValueError("manifest contains credential-like content")
    requirements = raw.get("requirements", raw.get("dependencies", []))
    if isinstance(requirements, dict):
        requirements = [f"{key}: {value}" for key, value in requirements.items()]
    if not isinstance(requirements, list) or any(not isinstance(x, str) for x in requirements):
        raise ValueError("declared dependencies must be a list or mapping")
    return raw, requirements


def _contains_secret(value: Any) -> bool:
    secret_parts = ("api_key", "apikey", "token", "password", "secret", "credential")
    if isinstance(value, dict):
        return any(
            any(part in str(key).casefold() for part in secret_parts) or _contains_secret(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return isinstance(value, str) and SECRET_RE.search(value) is not None


def _validate_files(files: dict[str, str]) -> None:
    if not isinstance(files, dict) or "SKILL.md" not in files:
        raise ValueError("SKILL.md is required")
    if len(files) > MAX_FILES:
        raise ValueError("payload exceeds file count limit")
    total = 0
    for name, content in files.items():
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or not path.parts
            or any(p in ("..", ".") for p in path.parts)
            or "\\" in name
            or ":" in name
        ):
            raise ValueError(f"unsafe payload path: {name}")
        if not isinstance(content, str):
            raise ValueError("payload files must be UTF-8 text")
        size = len(content.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise ValueError(f"file exceeds size limit: {name}")
        total += size
    if total > MAX_PAYLOAD_BYTES:
        raise ValueError("payload exceeds total size limit")


def _security_scan(files: dict[str, str], manifest: dict[str, Any]) -> dict[str, Any]:
    body = "\n".join(files.values())
    risks = []
    if SECRET_RE.search(body) or SECRET_RE.search(json.dumps(manifest, ensure_ascii=False)):
        risks.append("credential_or_secret_pattern")
    for kind, pattern in RISK_PATTERNS.items():
        if pattern.search(body):
            risks.append(kind)
    return {
        "result": "BLOCK"
        if "credential_or_secret_pattern" in risks
        else "WARN"
        if risks
        else "PASS",
        "risks": risks,
        "note": "Risk evidence only; this scan does not establish that the skill is safe.",
    }


def prepare_acquisition(record: dict[str, Any], files: dict[str, str]) -> Acquisition:
    _validate_files(files)
    manifest, dependencies = _parse_manifest(files["SKILL.md"], str(record.get("name", "")))
    normalized = {PurePosixPath(name).as_posix(): files[name] for name in files}
    if len(normalized) != len(files):
        raise ValueError("payload contains duplicate normalized paths")
    digest = payload_sha256(normalized)
    remote_hash = record.get("remote_hash")
    provider_reference_hash = None
    integrity = record.get("provider_integrity")
    is_verified_fallback = isinstance(integrity, dict) and integrity.get("source_match") is True
    if remote_hash:
        normalized_remote = str(remote_hash).removeprefix("sha256:").lower()
        try:
            provider_reference_hash = _provider_reference_sha256(normalized)
        except CatalogUnavailableError:
            provider_reference_hash = None
        if is_verified_fallback:
            security = _security_scan(normalized, manifest)
        elif (
            provider_reference_hash is None
            or not re.fullmatch(r"[0-9a-f]{64}", normalized_remote)
            or normalized_remote != provider_reference_hash
        ):
            security = {
                "result": "BLOCK",
                "risks": ["remote_hash_mismatch"] if provider_reference_hash is not None else [
                    "provider_reference_verifier_unavailable"
                ],
                "note": "Provider hash did not match the skills CLI reference hash."
                if provider_reference_hash is not None
                else "Provider hash could not be checked with the skills CLI reference verifier.",
            }
        else:
            security = _security_scan(normalized, manifest)
    else:
        security = _security_scan(normalized, manifest)
    return Acquisition(
        record={
            **record,
            "fetched_at": record.get("fetched_at") or datetime.now(UTC).isoformat(),
            "name": manifest["name"],
            "version": manifest["version"],
            "description": manifest["description"],
            "remote_hash": remote_hash,
            **({"provider_computed_hash": provider_reference_hash} if remote_hash else {}),
        },
        files=normalized,
        validation={"result": "PASS", "file_count": len(normalized), "dependencies": dependencies},
        security=security,
        computed_hash=digest,
    )


def payload_sha256(files: dict[str, str]) -> str:
    """Return Atlas's deterministic local digest over case-folded path order."""
    normalized_files = {PurePosixPath(name).as_posix(): content for name, content in files.items()}
    if len(normalized_files) != len(files):
        raise ValueError("payload contains duplicate normalized paths")
    digest = hashlib.sha256()
    for path in sorted(normalized_files, key=lambda value: (value.casefold(), value)):
        digest.update(path.encode("utf-8"))
        digest.update(normalized_files[path].encode("utf-8"))
    return digest.hexdigest()


async def inspect_github_source(
    source: str,
    skill_path: str = "",
    *,
    expected_name: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> Acquisition:
    parsed = urlparse(source)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("source must be an https://github.com public repository URL")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or any(part in (".", "..") for part in parts):
        raise ValueError("source must identify a public GitHub repository")
    owner, repo = parts[:2]
    if parts[2:3] == ["tree"] and len(parts) >= 5:
        branch, *embedded = parts[3:]
        skill_path = "/".join(embedded)
    else:
        branch = ""
        if len(parts) > 2:
            raise ValueError(
                "repository URL must not include arbitrary paths; provide a skill path"
            )
    path = skill_path.strip("/")
    if any(x in (".", "..") for x in PurePosixPath(path).parts) or "\\" in path:
        raise ValueError("unsafe GitHub skill path")

    async def fetch(using: httpx.AsyncClient) -> Acquisition:
        response = await using.get(f"https://api.github.com/repos/{owner}/{repo}")
        if response.status_code != 200:
            raise CatalogUnavailableError("GitHub repository unavailable, private, or rate limited")
        active_branch = branch or response.json().get("default_branch")
        commit_response = await using.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/"
            f"{quote(str(active_branch), safe='')}"
        )
        if commit_response.status_code != 200:
            raise CatalogUnavailableError("GitHub source revision is unavailable")
        commit_data = commit_response.json()
        commit_sha = commit_data.get("sha")
        if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
            raise CatalogUnavailableError("GitHub source revision is invalid")
        tree_sha = commit_data.get("commit", {}).get("tree", {}).get("sha")
        if not isinstance(tree_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", tree_sha):
            raise CatalogUnavailableError("GitHub source tree revision is invalid")
        tree_url = (
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/"
            f"{quote(tree_sha, safe='')}?recursive=1"
        )
        tree_response = await using.get(tree_url)
        if tree_response.status_code != 200:
            raise CatalogUnavailableError("GitHub repository tree is unavailable")
        tree_data = tree_response.json()
        if tree_data.get("sha") != tree_sha:
            raise CatalogUnavailableError("GitHub repository tree revision changed")
        if tree_data.get("truncated") is True:
            raise CatalogUnavailableError("GitHub repository tree is incomplete (truncated)")
        entries = tree_data.get("tree", [])
        resolved_path = path
        if not resolved_path and expected_name:
            candidates = [
                item for item in entries
                if item.get("type") == "blob"
                and isinstance(item.get("path"), str)
                and item["path"].endswith("SKILL.md")
                and item.get("mode") != "120000"
                and isinstance(item.get("size"), int)
                and 0 <= item["size"] <= MAX_FILE_BYTES
            ]
            if len(candidates) > MAX_FILES:
                raise CatalogUnavailableError(
                    "GitHub repository has too many skills to resolve safely"
                )
            matching_paths = []
            for candidate in candidates:
                response = await using.get(
                    "https://raw.githubusercontent.com/"
                    f"{owner}/{repo}/{quote(commit_sha, safe='')}/"
                    f"{quote(candidate['path'], safe='/')}"
                )
                if response.status_code != 200:
                    continue
                try:
                    frontmatter = re.match(
                        r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)",
                        response.content.decode("utf-8"),
                        re.DOTALL,
                    )
                    metadata = yaml.safe_load(frontmatter.group(1)) if frontmatter else None
                except (UnicodeDecodeError, yaml.YAMLError):
                    continue
                if isinstance(metadata, dict) and metadata.get("name") == expected_name:
                    candidate_path = candidate["path"]
                    matching_paths.append(
                        candidate_path[: -len("/SKILL.md")]
                        if "/" in candidate_path
                        else ""
                    )
            if len(matching_paths) != 1:
                raise CatalogUnavailableError(
                    "GitHub source does not resolve to one matching Skill manifest"
                )
            resolved_path = matching_paths[0]
        prefix = f"{resolved_path}/" if resolved_path else ""
        selected = [
            item
            for item in entries
            if item.get("type") == "blob"
            and isinstance(item.get("path"), str)
            and item["path"].startswith(prefix)
            and (not resolved_path or item["path"] != resolved_path)
        ]
        if not resolved_path:
            selected = [item for item in selected if item["path"] == "SKILL.md"]
        elif not any(item["path"] == f"{resolved_path}/SKILL.md" for item in selected):
            raise ValueError("GitHub skill path does not contain SKILL.md")
        if any(item.get("mode") == "120000" for item in selected):
            raise ValueError("GitHub skill payload contains a symlink")
        if len(selected) > MAX_FILES:
            raise ValueError("payload exceeds file count limit")
        if any(int(item.get("size", 0)) > MAX_FILE_BYTES for item in selected):
            raise ValueError("GitHub file exceeds size limit")

        semaphore = asyncio.Semaphore(8)

        async def fetch_file(item: dict[str, Any]) -> tuple[str, str]:
            async with semaphore:
                download = await using.get(
                    "https://raw.githubusercontent.com/"
                    f"{owner}/{repo}/{quote(commit_sha, safe='')}/"
                    f"{quote(item['path'], safe='/')}"
                )
            if download.status_code != 200:
                raise CatalogUnavailableError("GitHub skill file could not be retrieved")
            try:
                content = download.content.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("GitHub skill files must be UTF-8 text") from None
            return item["path"][len(prefix) :], content

        files = dict(await asyncio.gather(*(fetch_file(item) for item in selected)))
        _validate_files(files)
        skill_md = files["SKILL.md"]
        skill_name = ""
        for line in skill_md.splitlines()[:20]:
            if line.startswith("name:"):
                skill_name = line.split(":", 1)[1].strip().strip("\"'")
                break
        suffix = f"/{resolved_path}" if resolved_path else ""
        record = {
            "provider": "github",
            "external_id": f"{owner}/{repo}/{resolved_path or '.'}",
            "name": skill_name,
            "source": f"https://github.com/{owner}/{repo}",
            "source_type": "github",
            "source_url": f"https://github.com/{owner}/{repo}/tree/{commit_sha}{suffix}",
            "install_url": f"https://github.com/{owner}/{repo}/tree/{commit_sha}{suffix}",
            "remote_hash": None,
            "github_source_revision": commit_sha,
            "github_source_branch": str(active_branch),
            "github_tree_sha": tree_sha,
        }
        return prepare_acquisition(record, files)

    if client is not None:
        return await fetch(client)
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http_client:
        return await fetch(http_client)


async def install_acquisition(
    acquisition: Acquisition,
    *,
    skills_dir: Path,
    registry: SkillRegistry,
    approval_event: dict[str, str],
) -> dict[str, Any]:
    approval_event_id = approval_event.get("approval_event_id", "")
    approved_at = approval_event.get("approved_at", "")
    if (
        not approval_event_id
        or not approved_at
        or approval_event.get("computed_sha256") != acquisition.computed_hash
    ):
        raise PermissionError("explicit user approval is required")
    if acquisition.security["result"] == "BLOCK":
        raise PermissionError("blocked skill cannot be installed")
    name = acquisition.record["name"]
    with _INSTALL_LOCKS_GUARD:
        lock = _INSTALL_LOCKS.setdefault((str(registry.path.resolve()), name), threading.Lock())
    with lock:
        return await _install_acquisition_locked(
            acquisition,
            skills_dir=skills_dir,
            registry=registry,
            approval_event_id=approval_event_id,
            approved_at=approved_at,
        )


async def _install_acquisition_locked(
    acquisition: Acquisition,
    *,
    skills_dir: Path,
    registry: SkillRegistry,
    approval_event_id: str,
    approved_at: str,
) -> dict[str, Any]:
    name, version = acquisition.record["name"], acquisition.record["version"]
    existing = registry.get(name, version)
    if existing:
        raise FileExistsError(
            json.dumps(
                {
                    "existing": existing,
                    "incoming": {
                        "source": acquisition.record.get("source_url"),
                        "hash": acquisition.computed_hash,
                    },
                }
            )
        )
    target = skills_dir / "community" / name
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if target.exists() or target.is_symlink() or is_junction(target):
        raise FileExistsError(f"install target already exists: {target}")
    skills_dir.mkdir(parents=True, exist_ok=True)
    stage_parent = skills_dir.parent / ".atlas-skill-staging"
    if stage_parent.is_symlink() or is_junction(stage_parent):
        raise ValueError("staging directory must not be a symlink or junction")
    stage_parent.mkdir(exist_ok=True)
    if not stage_parent.resolve().is_relative_to(skills_dir.parent.resolve()):
        raise ValueError("staging directory escapes its trusted parent")
    stage = Path(tempfile.mkdtemp(prefix="skill-", dir=stage_parent))
    installed = False
    registered = False
    try:
        for relative, content in acquisition.files.items():
            destination = stage.joinpath(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.parent.resolve().is_relative_to(skills_dir.resolve()):
            raise ValueError("install target escapes the local skills directory")
        if target.parent.is_symlink() or is_junction(target.parent):
            raise ValueError("install target must not be a symlink or junction")
        stage.replace(target)
        installed = True
        metadata = {
            "name": name,
            "version": version,
            "description": acquisition.record["description"],
            "capabilities": [],
            "tools": [],
            "requirements": acquisition.validation["dependencies"],
            "examples": [],
            "aliases": acquisition.record.get("aliases", []),
            "tags": acquisition.record.get("tags", []),
            "category": "community",
            "keywords": acquisition.record.get("tags", []),
            "use_cases": [],
            "provenance": {
                "provider": acquisition.record["provider"],
                "external_id": acquisition.record["external_id"],
                "source_url": acquisition.record["source_url"],
                "fetched_at": acquisition.record.get("fetched_at"),
                "remote_hash": acquisition.record.get("remote_hash"),
                "provider_computed_hash": acquisition.record.get("provider_computed_hash")
                or acquisition.record.get("provider_integrity", {}).get(
                    "provider_computed_hash"
                ),
                "computed_sha256": acquisition.computed_hash,
                "provider_integrity": acquisition.record.get("provider_integrity"),
                "installed_at": datetime.now(UTC).isoformat(),
                "installed_path": str(target),
                "manifest": {"name": name, "version": version},
                "security_gate": acquisition.security,
                "user_approval_event_id": approval_event_id,
                "user_approval_timestamp": approved_at,
            },
        }
        registry.register(
            metadata, source=f"{acquisition.record['provider']}:{acquisition.record['external_id']}"
        )
        registered = True
        from atlas.skills import SkillManager

        manager = SkillManager(skills_dir=skills_dir)
        manager.scan_skills_sync()
        if manager.get_skill(name) is None:
            raise RuntimeError("installed skill did not pass local SkillManager discovery")
        return {
            "status": "installed",
            "name": name,
            "version": version,
            "path": str(target),
            "hash": acquisition.computed_hash,
            "security": acquisition.security,
        }
    except Exception:
        if registered:
            registry.remove(name, version)
        if installed:
            shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if stage_parent.exists() and not any(stage_parent.iterdir()):
            stage_parent.rmdir()
