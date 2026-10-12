"""Validated package sources and runtime links for Atlas extensions/skills.

Pi resource package reference: https://github.com/badlogic/pi-mono/tree/e37cdc420669e48b4df4bbce0fb2617fc3c71328/packages/coding-agent/docs
Cline Marketplace reference: https://github.com/cline/marketplace

Only safe skill sources are connected to the existing Atlas Skill Market. Plugin
code, prompts and themes remain catalog metadata and are never installed or run.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from atlas.config import load_user_settings, save_user_settings

router = APIRouter(tags=["extension-packages"])

ResourceKind = Literal["extension", "skill", "prompt", "theme"]
_PROJECT_SCOPE_LIMIT = (
    "项目级扩展覆盖暂不可启用：Atlas 只在启动时使用共享 PluginRuntime，当前请求没有可验证的项目身份或项目级加载器。"
)
_WORKSPACE_SCOPE_LIMIT = (
    "工作区级扩展覆盖暂不可启用：设置面板未向该 API 提供活动工作区，且 PluginRuntime 没有按工作区隔离的加载接口。"
)


class PackageSourcePayload(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=120)
    scope: Literal["user", "workspace", "project"] = "user"
    source_type: Literal["local", "registry"]
    source: str = Field(min_length=1, max_length=2000)
    resource_kinds: list[ResourceKind] = Field(default_factory=lambda: ["extension"], max_length=4)
    registry_metadata: dict[str, Any] = Field(default_factory=dict)
    validation_state: Literal["unvalidated", "valid", "unsupported", "invalid"] = "unvalidated"
    diagnostics: list[str] = Field(default_factory=list, max_length=30)


def _sources() -> list[dict[str, Any]]:
    value = load_user_settings().get("extension_package_sources", [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _save(sources: list[dict[str, Any]]) -> None:
    settings = load_user_settings()
    settings["extension_package_sources"] = sources
    save_user_settings(settings)


def _skill_market() -> Any:
    try:
        from atlas.api.skills_market_router import get_market

        return get_market()
    except (ImportError, AssertionError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=f"Skill Market is unavailable: {exc}") from exc


def _market_source_rows() -> list[dict[str, Any]]:
    try:
        return list(_skill_market().list_sources().get("sources", []))
    except HTTPException:
        return []


def _github_repo(source: str) -> str | None:
    parsed = urlparse(source.strip())
    if (parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        return None
    repo = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", f"{parts[0]}/{repo}"):
        return None
    return f"{parts[0]}/{repo}"


def _assess(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    diagnostics: list[str] = []
    kinds = sorted(set(row.get("resource_kinds", [])))
    if not kinds:
        return {**result, "validation_state": "invalid", "runtime_supported": False,
                "runtime_source_name": None, "diagnostics": ["At least one resource kind is required."]}
    if row.get("scope") == "project":
        diagnostics.append(_PROJECT_SCOPE_LIMIT)
        return {**result, "validation_state": "unsupported", "runtime_supported": False,
                "runtime_source_name": None, "diagnostics": diagnostics}

    if "skill" not in kinds:
        diagnostics.append(
            "Atlas can connect user-scoped skill sources to the Skill Market. "
            "Plugin code, prompt packages and themes remain catalog metadata."
        )
        return {**result, "validation_state": "unsupported", "runtime_supported": False,
                "runtime_source_name": None, "diagnostics": diagnostics}

    source_type = row.get("source_type")
    source = str(row.get("source", "")).strip()
    runtime_source_name = ""
    if source_type == "local":
        path = Path(source).expanduser()
        if not path.is_absolute():
            return {**result, "validation_state": "invalid", "runtime_supported": False,
                    "runtime_source_name": None,
                    "diagnostics": ["Local skill source must be an absolute existing directory path."]}
        try:
            if path.is_symlink():
                raise OSError("symbolic link sources are not accepted")
            resolved = path.resolve(strict=True)
        except OSError as exc:
            return {**result, "validation_state": "invalid", "runtime_supported": False,
                    "runtime_source_name": None, "diagnostics": [f"Local source is unavailable: {exc}"]}
        if not resolved.is_dir():
            return {**result, "validation_state": "invalid", "runtime_supported": False,
                    "runtime_source_name": None, "diagnostics": ["Local source must be a directory."]}
        try:
            has_skill = any(
                child.is_dir() and not child.is_symlink() and (child / "SKILL.md").is_file()
                for child in resolved.iterdir()
            )
        except OSError as exc:
            return {**result, "validation_state": "invalid", "runtime_supported": False,
                    "runtime_source_name": None, "diagnostics": [f"Local source cannot be inspected: {exc}"]}
        if not has_skill:
            return {**result, "validation_state": "invalid", "runtime_supported": False,
                    "runtime_source_name": None,
                    "diagnostics": ["No <skill-id>/SKILL.md entries were found. Atlas directory sources require that layout."]}
        result["source"] = str(resolved)
        runtime_source_name = f"atlas-package-{re.sub(r'[^a-z0-9]', '', str(row.get('id', '')).lower())[:32]}"
        diagnostics.append(
            "Directory is registered with the existing Skill Market as a read-only skill catalog; "
            "files are not copied and extension code is not executed."
        )
    elif source_type == "registry":
        repo = _github_repo(source)
        if not repo:
            return {**result, "validation_state": "unsupported", "runtime_supported": False,
                    "runtime_source_name": None,
                    "diagnostics": [
                        "Only HTTPS GitHub owner/repository URLs can connect to the existing Skill Market. "
                        "Registry reachability and package contents are not fetched during validation."
                    ]}
        result["source"] = f"https://github.com/{repo}"
        result["registry_metadata"] = {**(row.get("registry_metadata") or {}), "repository": repo}
        runtime_source_name = f"github:{repo}"
        diagnostics.append(
            "GitHub repository URL has a supported Skill Market tap shape; reachability and SKILL.md contents were not fetched."
        )
    else:
        return {**result, "validation_state": "invalid", "runtime_supported": False,
                "runtime_source_name": None, "diagnostics": ["Unsupported source type."]}

    if len(kinds) > 1:
        diagnostics.append("Only the skill resource kind is connected to a runtime; other selected kinds stay metadata-only.")
    return {**result, "validation_state": "valid", "runtime_supported": True,
            "runtime_source_name": runtime_source_name, "diagnostics": diagnostics}


def _sync_runtime_source(row: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    assessed = _assess(row)
    old_name = (previous or {}).get("runtime_source_name")
    old_managed = bool((previous or {}).get("runtime_source_managed"))
    if not assessed["runtime_supported"]:
        if old_managed and old_name:
            _skill_market().remove_source(str(old_name))
        assessed["runtime_source_managed"] = False
        assessed["runtime_enabled"] = False
        return assessed

    market = _skill_market()
    runtime_name = str(assessed["runtime_source_name"])
    market_rows = market.list_sources().get("sources", [])
    current = next((item for item in market_rows if item.get("name") == runtime_name), None)
    if current is not None:
        same = (
            (assessed["source_type"] == "local" and current.get("kind") == "directory"
             and str(Path(str(current.get("path", ""))).resolve()) == assessed["source"])
            or (assessed["source_type"] == "registry" and current.get("kind") == "github_tap"
                and current.get("repo") == assessed["registry_metadata"].get("repository"))
        )
        if not same:
            if not (old_managed and old_name == runtime_name):
                raise HTTPException(status_code=409, detail=f"Skill Market source name is already in use: {runtime_name}")
            market.remove_source(runtime_name)
            current = None

    try:
        if current is None:
            if assessed["source_type"] == "local":
                market.add_source(runtime_name, "directory", path=assessed["source"])
            else:
                repo = str(assessed["registry_metadata"]["repository"])
                market.add_source(runtime_name, "github", repo=repo)
            managed = True
        else:
            # An identical pre-existing source is used, but remains owned by its prior manager.
            managed = old_managed and old_name == runtime_name
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cannot register Skill Market source: {exc}") from exc

    if old_managed and old_name and old_name != runtime_name:
        market.remove_source(str(old_name))
    assessed["runtime_source_managed"] = managed
    effective = next((item for item in market.list_sources().get("sources", [])
                      if item.get("name") == runtime_name), {})
    assessed["runtime_enabled"] = bool(effective.get("enabled", True))
    return assessed


def _decorate(row: dict[str, Any]) -> dict[str, Any]:
    assessed = _assess(row)
    runtime_name = assessed.get("runtime_source_name")
    if runtime_name:
        market_row = next((item for item in _market_source_rows() if item.get("name") == runtime_name), None)
        assessed["runtime_enabled"] = bool(market_row.get("enabled", False)) if market_row else False
    else:
        assessed["runtime_enabled"] = False
    assessed["runtime_source_managed"] = bool(row.get("runtime_source_managed"))
    return assessed


def _assert_user_scope(payload: PackageSourcePayload) -> None:
    if payload.scope == "workspace":
        raise HTTPException(status_code=422, detail={
            "code": "workspace_scope_unavailable", "message": _WORKSPACE_SCOPE_LIMIT,
        })
    if payload.scope == "project":
        raise HTTPException(status_code=422, detail={
            "code": "project_scope_unavailable", "message": _PROJECT_SCOPE_LIMIT,
        })


@router.get("/api/extension-packages")
async def list_extension_package_sources() -> dict[str, Any]:
    sources = [_decorate(item) for item in _sources()]
    return {
        "sources": sources,
        "execution_supported": True,
        "scope_capabilities": {
            "user": {"available": True, "reason": "User skill sources use Atlas Skill Market."},
            "workspace": {"available": False, "reason": _WORKSPACE_SCOPE_LIMIT},
            "project": {"available": False, "reason": _PROJECT_SCOPE_LIMIT},
        },
        "default_sources": [],
        "reset_supported": True,
    }


@router.post("/api/extension-packages")
async def create_extension_package_source(payload: PackageSourcePayload) -> dict[str, Any]:
    _assert_user_scope(payload)
    sources = _sources()
    if any(item.get("id") == payload.id for item in sources):
        raise HTTPException(status_code=409, detail="Package source ID already exists")
    if any(str(item.get("name", "")).strip().casefold() == payload.name.strip().casefold() for item in sources):
        raise HTTPException(status_code=409, detail="A user package source with this name already exists")
    row = _sync_runtime_source(payload.model_dump(mode="json"))
    sources.append(row)
    _save(sources)
    return row


@router.put("/api/extension-packages/{source_id}")
async def update_extension_package_source(source_id: str, payload: PackageSourcePayload) -> dict[str, Any]:
    _assert_user_scope(payload)
    if payload.id != source_id:
        raise HTTPException(status_code=422, detail="Source ID must match the URL")
    sources = _sources()
    if any(item.get("id") != source_id and str(item.get("name", "")).strip().casefold() == payload.name.strip().casefold() for item in sources):
        raise HTTPException(status_code=409, detail="A user package source with this name already exists")
    for index, item in enumerate(sources):
        if item.get("id") == source_id:
            row = _sync_runtime_source(payload.model_dump(mode="json"), item)
            sources[index] = row
            _save(sources)
            return row
    raise HTTPException(status_code=404, detail="Package source not found")


@router.delete("/api/extension-packages/{source_id}")
async def delete_extension_package_source(source_id: str) -> dict[str, Any]:
    sources = _sources()
    source = next((item for item in sources if item.get("id") == source_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail="Package source not found")
    if source.get("runtime_source_managed") and source.get("runtime_source_name"):
        _skill_market().remove_source(str(source["runtime_source_name"]))
    _save([item for item in sources if item.get("id") != source_id])
    return {"id": source_id, "deleted": True}


@router.post("/api/extension-packages/reset")
async def reset_extension_package_sources(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    scope = str((payload or {}).get("scope", "user"))
    if scope == "workspace":
        raise HTTPException(status_code=422, detail={
            "code": "workspace_scope_unavailable", "message": _WORKSPACE_SCOPE_LIMIT,
        })
    if scope != "user":
        raise HTTPException(status_code=422, detail={
            "code": "project_scope_unavailable", "message": _PROJECT_SCOPE_LIMIT,
        })
    sources = _sources()
    market = _skill_market() if any(item.get("runtime_source_managed") for item in sources) else None
    removed: list[str] = []
    if market is not None:
        for item in sources:
            if item.get("runtime_source_managed") and item.get("runtime_source_name"):
                name = str(item["runtime_source_name"])
                market.remove_source(name)
                removed.append(name)
    _save([])
    return {"sources": [], "reset": True, "removed_runtime_sources": removed, "defaults": []}


@router.post("/api/extension-packages/{source_id}/validate")
async def validate_extension_package_source(source_id: str) -> dict[str, Any]:
    sources = _sources()
    for index, current in enumerate(sources):
        if current.get("id") == source_id:
            row = _assess(current)
            sources[index] = row
            _save(sources)
            return row
    raise HTTPException(status_code=404, detail="Package source not found")


@router.post("/api/extension-packages/{source_id}/enabled")
async def set_extension_package_source_enabled(source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    source = next((item for item in _sources() if item.get("id") == source_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail="Package source not found")
    if not source.get("runtime_supported") or not source.get("runtime_source_name"):
        raise HTTPException(status_code=409, detail="This package source has no safe runtime connector")
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="enabled must be a boolean")
    try:
        result = _skill_market().set_source_enabled(str(source["runtime_source_name"]), enabled)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cannot change Skill Market source state: {exc}") from exc
    source["runtime_enabled"] = enabled
    _save([source if item.get("id") == source_id else item for item in _sources()])
    return {**source, "runtime_enabled": enabled, "runtime_result": result}
