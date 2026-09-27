"""Controlled local Atlas Skill package validation."""

from __future__ import annotations

import io
import json
import os
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from atlas.skills.acquisition import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_PAYLOAD_BYTES,
    Acquisition,
    _contains_secret,
    _parse_manifest,
    payload_sha256,
    prepare_acquisition,
)
from atlas.skills.dependencies import parse_dependencies

PACKAGE_MANIFEST = "atlas-skill-package.json"
MAX_PACKAGE_BYTES = MAX_PAYLOAD_BYTES + 128_000


def inspect_skill_package(data: bytes, filename: str) -> Acquisition:
    """Read and validate an untrusted local zip package without extracting it."""
    if not data or len(data) > MAX_PACKAGE_BYTES:
        raise ValueError("package is empty or exceeds the package size limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (OSError, zipfile.BadZipFile):
        raise ValueError("package must be a valid ZIP bundle") from None
    with archive:
        members = archive.infolist()
        if len(members) > MAX_FILES + 1:
            raise ValueError("package exceeds file count limit")
        files: dict[str, str] = {}
        normalized_names: set[str] = set()
        total = 0
        for item in members:
            name = (item.filename[:-1] if item.is_dir() and item.filename.endswith("/")
                    else item.filename)
            path = PurePosixPath(name)
            mode = item.external_attr >> 16
            if item.external_attr & 0x0400:
                raise ValueError(f"package reparse point is not allowed: {name}")
            if stat.S_ISLNK(mode):
                raise ValueError(f"package symlink is not allowed: {name}")
            raw_parts = name.split("/")
            if (path.is_absolute() or not path.parts
                    or any(part in {"", ".", ".."} for part in raw_parts)
                    or "\\" in name or ":" in name or name.startswith("/")):
                raise ValueError(f"unsafe package path: {name}")
            if item.is_dir():
                continue
            file_type = stat.S_IFMT(mode)
            if (name.casefold() in normalized_names or item.flag_bits & 0x1
                    or (file_type not in {0, stat.S_IFREG})):
                raise ValueError("duplicate or encrypted package entry")
            normalized_names.add(name.casefold())
            total += item.file_size
            if item.file_size > MAX_FILE_BYTES or total > MAX_PAYLOAD_BYTES + MAX_FILE_BYTES:
                raise ValueError("package payload exceeds size limits")
            try:
                files[name] = archive.read(item).decode("utf-8", errors="strict")
            except (UnicodeDecodeError, RuntimeError, OSError):
                raise ValueError(f"package file must be valid UTF-8 text: {name}") from None
    manifest_text = files.pop(PACKAGE_MANIFEST, None)
    if manifest_text is None:
        raise ValueError(f"package is missing {PACKAGE_MANIFEST}")
    try:
        package = json.loads(manifest_text)
    except json.JSONDecodeError:
        raise ValueError("package manifest must be valid JSON") from None
    if not isinstance(package, dict) or package.get("format") != "atlas-skill-package-v1":
        raise ValueError("unsupported Skill package manifest format")
    identity = package.get("identity")
    source = package.get("source")
    digest = package.get("content_sha256")
    if not isinstance(identity, dict) or not isinstance(source, dict):
        raise ValueError("package identity and source provenance are required")
    name, version = identity.get("name"), identity.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValueError("package identity requires name and version")
    if _contains_secret(package):
        raise ValueError("package manifest contains credential-like content")
    payload = {key.removeprefix("payload/"): value for key, value in files.items()
               if key.startswith("payload/")}
    if len(payload) != len(files):
        raise ValueError("package payload files must be under payload/")
    if "SKILL.md" not in payload:
        raise ValueError("package payload must include payload/SKILL.md")
    if not isinstance(digest, str) or payload_sha256(payload) != digest:
        raise ValueError("package content hash does not match its payload")
    skill_manifest, dependencies = _parse_manifest(payload["SKILL.md"], name)
    if skill_manifest["version"] != version:
        raise ValueError("package identity version does not match SKILL.md")
    declared = package.get("dependencies", [])
    if parse_dependencies(declared) != parse_dependencies(dependencies):
        raise ValueError("package dependency declaration does not match SKILL.md")
    provider = source.get("provider", "local-package")
    source_url = source.get("source_url")
    external_id = source.get("external_id")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("package source provider is required")
    if source_url is not None and not isinstance(source_url, str):
        raise ValueError("package source_url must be text")
    if external_id is not None and not isinstance(external_id, str):
        raise ValueError("package external_id must be text")
    record: dict[str, Any] = {
        "provider": provider.strip(),
        "external_id": external_id or digest,
        "name": name,
        "version": version,
        "description": skill_manifest["description"],
        "source_url": source_url or f"local-package:{os.path.basename(filename)}",
        "package_source": os.path.basename(filename),
        "original_source": source_url or "local package",
        "imported_at": datetime.now(UTC).isoformat(),
    }
    return prepare_acquisition(record, payload)
