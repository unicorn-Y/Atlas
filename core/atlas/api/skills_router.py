"""Skill discovery, catalog, lifecycle and registry surface (``/api/skills, /api/skill-catalog, /api/skill-registry, /api/skill-packages``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import BaseModel
import structlog

from atlas.api.skills_market_router import get_market

import httpx  # noqa: E402
from atlas.skills import SKILLS_DIR
from atlas.skills.acquisition import (
    CatalogUnavailableError,
    install_acquisition,
    inspect_github_source,
)
from atlas.skills.registry import SkillRegistry

from atlas.skills.dependencies import dependency_preflight
from atlas.skills.discovery import SkillDiscovery
from atlas.skills.distribution import inspect_skill_package
from atlas.skills.lifecycle import (
    dependency_states,
    inspect_skill as inspect_skill_lifecycle,
    remove_skill as remove_lifecycle_skill,
    rollback_skill as rollback_lifecycle_skill,
    transition_pin,
    transition_trust,
    update_skill as update_lifecycle_skill,
)

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()
log = structlog.get_logger(__name__)


def _server() -> Any:
    """Late-bound atlas.server: its module globals stay the seam tests patch."""
    import atlas.server

    return atlas.server


def _service(name: str, services: AppServices) -> Any:
    """Resolve an optional service: per-app container first, then the server module."""
    value = getattr(services, name, None)
    if value is None:
        value = getattr(_server(), name, None)
    return value


@router.get("/api/skills")
async def list_skills(
    services: Annotated[AppServices, Depends(get_app_services)],
    category: str | None = Query(None),
) -> dict[str, Any]:
    """Return all available skills, optionally filtered by category."""
    skill_mgr = services.skill_mgr
    if skill_mgr is None:
        from atlas import server as _atlas_server

        skill_mgr = _atlas_server.skill_mgr
    assert skill_mgr is not None
    skills = skill_mgr.list_skills(category=category)
    return {
        "count": len(skills),
        "categories": skill_mgr.categories,
        "skills": [s.to_dict() for s in skills],
    }


@router.get("/api/skills/{name}/dependencies")
async def inspect_skill_dependencies(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    mcp_client = _service("mcp_client", services)
    skill_registry = _service("skill_registry", services)
    """Return a read-only dependency preflight for one indexed Skill."""
    skill_mgr = services.skill_mgr
    if skill_mgr is None:
        from atlas import server as _atlas_server

        skill_mgr = _atlas_server.skill_mgr
    assert skill_mgr is not None
    info = skill_mgr.get_skill(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    dependencies = skill_mgr.preflight_dependencies(
        name,
        connected_servers=mcp_client.get_server_names() if mcp_client else None,
        configured_servers=mcp_client.get_configured_server_names() if mcp_client else None,
        registry=skill_registry,
    )
    blockers = [item for item in dependencies if item["state"] != "satisfied"]
    return {"name": name, "dependencies": dependencies, "blocking": blockers,
            "can_activate": not blockers, "read_only": True}


@router.post("/api/skills/{name}/dependencies/prepare")
async def prepare_skill_dependencies(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str, request: Request, payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    mcp_client = _service("mcp_client", services)
    skill_mgr = _service("skill_mgr", services)
    skill_registry = _service("skill_registry", services)
    """Create a dependency plan; execution remains behind lifecycle approval."""
    _server()._require_skill_center_authority(request)
    if skill_mgr is None:
        raise HTTPException(status_code=503, detail="Skill Manager is unavailable")
    info = skill_mgr.get_skill(name)
    if info is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    record = skill_registry.get(name, info.version) if skill_registry else None
    if record is None or not (record.get("provenance") or {}).get("installed_path"):
        raise HTTPException(
            status_code=409, detail="dependency installation requires a managed Skill",
        )
    _, _, lifecycle_state = _lifecycle_context(name, info.version)
    lifecycle = lifecycle_state["lifecycle"]
    if (lifecycle["drifted"] or lifecycle.get("trust_state") in {"revoked", "blocked"}
            or lifecycle.get("state") in {"removed", "quarantined"}
            or lifecycle.get("pin_policy") != "unpinned"):
        raise HTTPException(
            status_code=409, detail="Skill lifecycle policy blocks dependency preparation",
        )
    states = skill_mgr.preflight_dependencies(
        name, connected_servers=mcp_client.get_server_names() if mcp_client else None,
        configured_servers=mcp_client.get_configured_server_names() if mcp_client else None,
        registry=skill_registry,
    )
    selected = payload.get("dependencies")
    if selected is not None and (not isinstance(selected, list)
                                 or any(not isinstance(value, str) for value in selected)):
        raise HTTPException(status_code=422, detail="dependencies must be a list of names")
    targets = [item for item in states if item["state"] != "satisfied"
               and (selected is None or item["name"] in selected)]
    if selected is not None and set(selected) != {item["name"] for item in targets}:
        raise HTTPException(
            status_code=409, detail="selected dependency is absent or already satisfied",
        )
    plan_items = []
    for item in targets:
        supported = item["kind"] == "python_packages" and bool(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", item["name"])
        )
        if item["kind"] == "python_packages" and item.get("requested"):
            try:
                SpecifierSet(item["requested"])
            except InvalidSpecifier:
                supported = False
        plan_items.append({
            **item, "adapter": "pip" if supported else None,
            "source": "https://pypi.org/simple" if supported else item["source"],
            "executable": supported,
            "blocked_reason": None if supported else (
                "no approved adapter for this dependency kind or declaration"
            ),
        })
    if not plan_items:
        raise HTTPException(status_code=409, detail="no missing dependencies were selected")
    plan_id = str(uuid.uuid4())
    plan = {
        "plan_id": plan_id, "name": name, "version": info.version,
        "items": plan_items, "created_at": datetime.now(UTC),
        "expires_at": datetime.now(UTC) + _server().SKILL_ACQUISITION_TTL,
        "approval_state": "pending",
    }
    _server().skill_dependency_plans[plan_id] = plan
    return {**plan, "approval_state": "approval_required", "read_only": True}


@router.get("/api/skills/discover")
async def discover_skills(
    services: Annotated[AppServices, Depends(get_app_services)],
    q: str = Query(""),
    name: str | None = Query(None),
    capability: str | None = Query(None),
    tool: str | None = Query(None),
    status: str = Query("active"),
    source: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Return explainable, ranked candidates from the local Skill Registry."""
    skill_registry = services.skill_registry
    if skill_registry is None:
        from atlas import server as _atlas_server

        skill_registry = _atlas_server.skill_registry
    assert skill_registry is not None
    try:
        return SkillDiscovery(skill_registry).discover(
            query=q, name=name, capability=capability, tool=tool, status=status,
            source=source, limit=limit, offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/api/skill-catalog/search")
async def search_skill_catalog(
    services: Annotated[AppServices, Depends(get_app_services)],
    q: str = Query(..., min_length=2), page: int = Query(0, ge=0),
) -> dict[str, Any]:
    skill_registry = _service("skill_registry", services)
    """Search remote candidates; failures are isolated from local discovery and chat."""
    try:
        result = await _server().skill_catalog_provider.search(q, page=page)
        registry_items = skill_registry.list() if skill_registry else []
        installed = {
            (item.get("provenance") or {}).get("external_id") for item in registry_items
        }
        for item in result["results"]:
            if item["external_id"] in installed:
                item["installed"] = True
                item["state"] = "installed"
        return result
    except CatalogUnavailableError as exc:
        return {
            "provider": "skills.sh", "results": [],
            "pagination": {"page": page, "has_more": False},
            "status": "external-catalog-unavailable", "message": str(exc),
        }


@router.post("/api/skill-catalog/inspect")
async def inspect_skill_catalog(
    services: Annotated[AppServices, Depends(get_app_services)],
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    skill_mgr = _service("skill_mgr", services)
    skill_registry = _service("skill_registry", services)
    """Fetch and review a remote candidate without registry or activation side effects."""
    try:
        if payload.get("provider") == "github":
            acquisition = await inspect_github_source(
                str(payload.get("source_url", "")), str(payload.get("skill_path", "")),
            )
        else:
            acquisition = await _server().skill_catalog_provider.inspect(str(payload.get("external_id", "")))
    except CatalogUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="GitHub source unavailable") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    acquisition_id = str(uuid.uuid4())
    created_at = datetime.now(UTC)
    expires_at = created_at + _server().SKILL_ACQUISITION_TTL
    _server().skill_acquisitions[acquisition_id] = {
        "acquisition_id": acquisition_id,
        "provider": acquisition.record["provider"],
        "external_id": acquisition.record["external_id"],
        "computed_sha256": acquisition.computed_hash,
        "name": acquisition.record["name"],
        "version": acquisition.record["version"],
        "security": acquisition.security,
        "created_at": created_at,
        "expires_at": expires_at,
        "approval_state": "pending",
        "acquisition": acquisition,
    }
    existing = None
    if skill_registry:
        candidates = [item for item in skill_registry.list()
                      if item.get("name") == acquisition.record["name"]]
        exact = skill_registry.get(acquisition.record["name"], acquisition.record["version"])
        existing = exact or next((item for item in candidates if
                                  (item.get("provenance") or {}).get("external_id") ==
                                  acquisition.record.get("external_id")), None)
        if existing and (existing.get("provenance") or {}).get("installed_path"):
            try:
                current_state = inspect_skill_lifecycle(
                    skill_registry, skill_mgr._skills_dir if skill_mgr else SKILLS_DIR,
                    existing["name"], existing["version"],
                )
                existing = {
                    **existing, "lifecycle_summary": current_state["lifecycle"],
                    "file_hashes": current_state["file_hashes"],
                }
            except (OSError, ValueError):
                pass
    prior_hashes = (existing or {}).get("file_hashes", {})
    incoming_hashes = {
        path: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for path, content in acquisition.files.items()
    }
    file_diff = {
        "added": sorted(set(incoming_hashes) - set(prior_hashes)),
        "removed": sorted(set(prior_hashes) - set(incoming_hashes)),
        "changed": sorted(path for path in set(incoming_hashes) & set(prior_hashes)
                           if incoming_hashes[path] != prior_hashes[path]),
        "unchanged": sorted(path for path in set(incoming_hashes) & set(prior_hashes)
                             if incoming_hashes[path] == prior_hashes[path]),
    }
    return {
        "acquisition_id": acquisition_id, "record": acquisition.record,
        "files": acquisition.files, "validation": acquisition.validation,
        "security": acquisition.security, "computed_sha256": acquisition.computed_hash,
        "dependency_state": dependency_states(
            skill_registry, acquisition.validation.get("dependencies", []),
        ) if skill_registry else [],
        "file_diff": file_diff,
        "already_installed": bool(skill_registry and skill_registry.get(
            acquisition.record["name"], acquisition.record["version"]
        )),
        "existing_local": existing,
        "install_target": f"skills/community/{acquisition.record['name']}",
    }


@router.post("/api/skill-packages/inspect")
async def inspect_local_skill_package(
    services: Annotated[AppServices, Depends(get_app_services)],
    request: Request,
) -> dict[str, Any]:
    mcp_client = _service("mcp_client", services)
    skill_registry = _service("skill_registry", services)
    """Review a bounded ZIP package in memory; this route never extracts or installs it."""
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > 2_128_000):
        raise HTTPException(status_code=413, detail="package exceeds the upload size limit")
    try:
        acquisition = inspect_skill_package(
            await request.body(), request.headers.get("x-atlas-package-name", "skill-package.zip"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    acquisition_id = str(uuid.uuid4())
    created_at = datetime.now(UTC)
    _server().skill_acquisitions[acquisition_id] = {
        "acquisition_id": acquisition_id, "provider": acquisition.record["provider"],
        "external_id": acquisition.record["external_id"],
        "computed_sha256": acquisition.computed_hash,
        "name": acquisition.record["name"], "version": acquisition.record["version"],
        "security": acquisition.security, "created_at": created_at,
        "expires_at": created_at + _server().SKILL_ACQUISITION_TTL,
        "approval_state": "pending", "acquisition": acquisition, "local_package": True,
    }
    exact = skill_registry.get(acquisition.record["name"], acquisition.record["version"])
    same_name = any(item["name"] == acquisition.record["name"] for item in skill_registry.list())
    existing = next((item for item in skill_registry.list(status="active")
                     if item["name"] == acquisition.record["name"]), None)
    states = dependency_preflight(
        acquisition.validation.get("dependencies", []),
        connected_servers=set(mcp_client.get_server_names()) if mcp_client else None,
        configured_servers=(set(mcp_client.get_configured_server_names()) if mcp_client else None),
        registry=skill_registry,
    )
    return {
        "acquisition_id": acquisition_id, "record": acquisition.record,
        "files": acquisition.files, "validation": acquisition.validation,
        "security": acquisition.security, "computed_sha256": acquisition.computed_hash,
        "dependency_state": states, "already_installed": exact is not None,
        "name_conflict": exact is not None,
        "exact_version_conflict": exact is not None,
        "same_name_existing": same_name,
        "import_state": ("exact_version_conflict" if exact is not None else
                         "update_candidate" if existing is not None else "new_skill"),
        "existing_version": existing["version"] if existing is not None else None,
        "install_target": f"skills/community/{acquisition.record['name']}",
        "import_requires_lifecycle_approval": True,
    }


@router.post("/api/skill-catalog/approve")
async def approve_catalog_skill(
    services: Annotated[AppServices, Depends(get_app_services)],
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    acquisition_id = payload.get("acquisition_id")
    session = _server().skill_acquisitions.get(acquisition_id) if isinstance(acquisition_id, str) else None
    if session is None:
        raise HTTPException(status_code=404, detail="Reviewed acquisition not found; inspect again")
    if datetime.now(UTC) >= session["expires_at"]:
        session["approval_state"] = "expired"
        raise HTTPException(status_code=410, detail="Reviewed acquisition expired; inspect again")
    acquisition = session["acquisition"]
    if acquisition.computed_hash != session["computed_sha256"]:
        raise HTTPException(status_code=409, detail="Reviewed payload changed; inspect again")
    if session["approval_state"] != "pending":
        raise HTTPException(status_code=409, detail="Acquisition approval is no longer pending")
    if acquisition.security["result"] == "BLOCK":
        raise HTTPException(status_code=403, detail="Blocked skill cannot be approved")
    if acquisition.security["result"] == "WARN" and payload.get("warnings_confirmed") is not True:
        raise HTTPException(
            status_code=403, detail="WARN risks require explicit second confirmation",
        )
    approved_at = datetime.now(UTC).isoformat()
    event = {
        "approval_event_id": str(uuid.uuid4()),
        "acquisition_id": acquisition_id,
        "computed_sha256": session["computed_sha256"],
        "approved_at": approved_at,
        "approval_state": "approved",
    }
    authorization = secrets.token_urlsafe(32)
    session["approval_event"] = event
    session["authorization_sha256"] = hashlib.sha256(authorization.encode("utf-8")).hexdigest()
    session["approval_state"] = "approved"
    session["approval_expires_at"] = datetime.now(UTC) + _server().SKILL_ACQUISITION_TTL
    return {**event, "install_authorization": authorization}


@router.post("/api/skill-catalog/install")
async def install_catalog_skill(
    services: Annotated[AppServices, Depends(get_app_services)],
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    skill_mgr = _service("skill_mgr", services)
    acquisition_id = payload.get("acquisition_id")
    session = _server().skill_acquisitions.get(acquisition_id) if isinstance(acquisition_id, str) else None
    if session is None:
        raise HTTPException(status_code=404, detail="Reviewed acquisition not found; inspect again")
    acquisition = session["acquisition"]
    if "approval_event_id" in payload or "approved" in payload:
        raise HTTPException(
            status_code=403, detail="Client-supplied approval claims are not accepted",
        )
    if datetime.now(UTC) >= session["expires_at"]:
        session["approval_state"] = "expired"
        raise HTTPException(status_code=410, detail="Reviewed acquisition expired; inspect again")
    if acquisition.computed_hash != session["computed_sha256"]:
        raise HTTPException(status_code=409, detail="Reviewed payload changed; inspect again")
    authorization = payload.get("install_authorization")
    approval_event = session.get("approval_event")
    if (
        session["approval_state"] != "approved"
        or not isinstance(authorization, str)
        or not isinstance(approval_event, dict)
        or datetime.now(UTC) >= session.get("approval_expires_at", datetime.min.replace(tzinfo=UTC))
        or not secrets.compare_digest(
            hashlib.sha256(authorization.encode("utf-8")).hexdigest(),
            session.get("authorization_sha256", ""),
        )
    ):
        raise HTTPException(status_code=403, detail="Valid one-time server approval is required")
    if (
        approval_event["acquisition_id"] != acquisition_id
        or approval_event["computed_sha256"] != acquisition.computed_hash
    ):
        raise HTTPException(
            status_code=403, detail="Approval does not match the reviewed acquisition",
        )
    session["approval_state"] = "consumed"
    session.pop("authorization_sha256", None)
    skill_registry = services.skill_registry
    if skill_registry is None:
        from atlas import server as _atlas_server

        skill_registry = _atlas_server.skill_registry
    assert skill_registry is not None
    try:
        result = await install_acquisition(
            acquisition, skills_dir=skill_mgr._skills_dir if skill_mgr else SKILLS_DIR,
            registry=skill_registry, approval_event=approval_event,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if skill_mgr:
        skill_mgr.scan_skills_sync()
    del _server().skill_acquisitions[acquisition_id]
    return result


def _lifecycle_context(name: str, version: str) -> tuple[SkillRegistry, Path, dict[str, Any]]:
    skill_mgr = _server().skill_mgr
    skill_registry = _server().skill_registry
    if skill_registry is None:
        raise HTTPException(status_code=503, detail="Skill Registry is unavailable")
    record = skill_registry.get(name, version)
    if record is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not (record.get("provenance") or {}).get("installed_path"):
        raise HTTPException(
            status_code=404, detail="Skill is outside the external lifecycle manager",
        )
    skills_dir = skill_mgr._skills_dir if skill_mgr else SKILLS_DIR
    try:
        state = inspect_skill_lifecycle(skill_registry, skills_dir, name, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return skill_registry, skills_dir, state


@router.get("/api/skills/lifecycle/{name}/{version}")
async def get_skill_lifecycle(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str, version: str,
) -> dict[str, Any]:
    _, _, state = _lifecycle_context(name, version)
    return state


@router.get("/api/skills/lifecycle/{name}/{version}/history")
async def get_skill_lifecycle_history(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str, version: str,
) -> dict[str, Any]:
    registry, _, state = _lifecycle_context(name, version)
    return {"name": name, "version": version, "history": registry.lifecycle_history(name),
            "lifecycle": state["lifecycle"]}


@router.post("/api/skills/lifecycle/decision")
async def create_skill_lifecycle_decision(
    services: Annotated[AppServices, Depends(get_app_services)],
    request: Request, payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    skill_mgr = _service("skill_mgr", services)
    skill_registry = _service("skill_registry", services)
    _server()._require_skill_center_authority(request)
    action, name, version = (payload.get(key) for key in ("action", "name", "version"))
    reason = payload.get("reason")
    if action not in {"install", "update", "downgrade", "dependency-install", "rollback",
                      "remove", "trust", "pin", "unpin"}:
        raise HTTPException(status_code=422, detail="unsupported lifecycle action")
    if not all(isinstance(value, str) and value.strip() for value in (name, version, reason)):
        raise HTTPException(status_code=422, detail="name, version, and reason are required")
    acquisition_id = None
    if action == "install":
        acquisition_id = payload.get("acquisition_id")
        session = (_server().skill_acquisitions.get(acquisition_id)
                   if isinstance(acquisition_id, str) else None)
        if (not session or not session.get("local_package")
                or datetime.now(UTC) >= session["expires_at"]):
            raise HTTPException(
                status_code=410, detail="reviewed local package is missing or expired",
            )
        acquisition = session["acquisition"]
        if acquisition.record["name"] != name or acquisition.record["version"] != version:
            raise HTTPException(status_code=403, detail="package review targets another Skill")
        if acquisition.security.get("result") == "BLOCK":
            raise HTTPException(status_code=403, detail="blocked package cannot be approved")
        if (acquisition.security.get("result") == "WARN"
                and payload.get("warnings_confirmed") is not True):
            raise HTTPException(
                status_code=403, detail="WARN package requires a second confirmation",
            )
        registry = skill_registry
        if registry is None:
            raise HTTPException(status_code=503, detail="Skill Registry is unavailable")
        if registry.get(name, version) is not None:
            raise HTTPException(
                status_code=409,
                detail="Skill package with this exact name and version already exists",
            )
        if session.get("computed_sha256") != acquisition.computed_hash:
            raise HTTPException(status_code=409, detail="reviewed package hash changed")
        skills_dir = skill_mgr._skills_dir if skill_mgr else SKILLS_DIR
        current_hash = ""
        content_hash = acquisition.computed_hash
    else:
        registry, skills_dir, state = _lifecycle_context(name, version)
        current_hash = (state["lifecycle"].get("actual_hash")
                        or state["lifecycle"].get("content_hash"))
        content_hash = current_hash
    rollback_event = None
    if action == "dependency-install":
        acquisition_id = payload.get("dependency_plan_id")
        plan = (_server().skill_dependency_plans.get(acquisition_id)
                if isinstance(acquisition_id, str) else None)
        if (not plan or plan["name"] != name or plan["version"] != version
                or datetime.now(UTC) >= plan["expires_at"]):
            raise HTTPException(status_code=410, detail="dependency plan is missing or expired")
        state = _lifecycle_context(name, version)[2]
        if state["lifecycle"]["drifted"]:
            raise HTTPException(
                status_code=409, detail="filesystem drift blocks dependency installation",
            )
        current_hash = (state["lifecycle"].get("actual_hash")
                        or state["lifecycle"].get("content_hash"))
        content_hash = current_hash
    elif action == "rollback":
        requested_event = payload.get("event_id")
        rollback_event = next((item for item in registry.lifecycle_history(name)
                              if item["event_id"] == requested_event), None)
        if (rollback_event is None or rollback_event["action"] != "remove"
                or state["lifecycle"].get("actual_hash") is not None):
            if state["lifecycle"]["drifted"]:
                raise HTTPException(status_code=409, detail="filesystem drift blocks rollback")
        if rollback_event is None:
            raise HTTPException(status_code=404, detail="rollback record not found")
    elif action != "install" and state["lifecycle"]["drifted"]:
        raise HTTPException(status_code=409, detail="filesystem drift blocks lifecycle actions")
    if rollback_event is not None:
        content_hash = rollback_event["details"].get("snapshot_hash")
    if action in {"update", "downgrade"}:
        acquisition_id = payload.get("acquisition_id")
        session = (
            _server().skill_acquisitions.get(acquisition_id)
            if isinstance(acquisition_id, str) else None
        )
        if not session or datetime.now(UTC) >= session["expires_at"]:
            raise HTTPException(status_code=410, detail="reviewed update is missing or expired")
        acquisition = session["acquisition"]
        if acquisition.record["name"] != name:
            raise HTTPException(status_code=403, detail="update review targets another skill")
        if acquisition.record["version"] == version:
            raise HTTPException(status_code=409, detail="exact name and version already exists")
        current_version = tuple(int(part.split("-")[0]) for part in version.split(".")[:3])
        incoming_version = tuple(
            int(part.split("-")[0]) for part in acquisition.record["version"].split(".")[:3]
        )
        expected_action = "downgrade" if incoming_version < current_version else "update"
        if action != expected_action:
            raise HTTPException(status_code=409, detail=f"review action must be {expected_action}")
        if acquisition.security.get("result") == "BLOCK":
            raise HTTPException(status_code=403, detail="blocked update cannot be approved")
        if (acquisition.security.get("result") == "WARN"
                and payload.get("warnings_confirmed") is not True):
            raise HTTPException(
                status_code=403, detail="WARN update requires a second confirmation",
            )
        content_hash = acquisition.computed_hash
        acquisition_id = session.get("acquisition_id", acquisition_id)
    if not isinstance(content_hash, str):
        raise HTTPException(status_code=409, detail="installed content hash is unavailable")
    now = datetime.now(UTC)
    decision_id = str(uuid.uuid4())
    target_trust_state = payload.get("trust_state") if action == "trust" else None
    target_pin_policy = payload.get("policy") if action in {"pin", "unpin"} else None
    if action == "trust" and target_trust_state not in {"trusted", "revoked", "blocked"}:
        raise HTTPException(status_code=422, detail="valid target trust state is required")
    if action in {"pin", "unpin"} and target_pin_policy not in {"exact", "hash", "unpinned"}:
        raise HTTPException(status_code=422, detail="valid target pin policy is required")
    try:
        registry.create_lifecycle_decision({
            "decision_id": decision_id,
            "action": action, "name": name, "version": version,
            "current_hash": current_hash or "", "content_hash": content_hash,
            "acquisition_id": acquisition_id, "target_trust_state": target_trust_state,
            "target_pin_policy": target_pin_policy,
            "rollback_event_id": rollback_event["event_id"] if rollback_event else None,
            "rollback_snapshot_hash": content_hash if rollback_event else None,
            "reason": reason.strip(),
            "created_at": now.isoformat(),
            "expires_at": (now + _server().SKILL_ACQUISITION_TTL).isoformat(),
        })
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        log.exception("skills.lifecycle_decision_persist_failed", decision_id=decision_id)
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"decision_id": decision_id, "action": action, "name": name,
            "version": version, "content_hash": content_hash,
            "expires_at": (now + _server().SKILL_ACQUISITION_TTL).isoformat()}


@router.post("/api/skills/lifecycle/approve")
async def approve_skill_lifecycle(
    services: Annotated[AppServices, Depends(get_app_services)],
    request: Request, payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    _server()._require_skill_center_authority(request)
    decision_id = payload.get("decision_id")
    if not isinstance(decision_id, str) or not decision_id:
        raise HTTPException(status_code=403, detail="server-held Skill Center decision is required")
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    approval_id = str(uuid.uuid4())
    skill_registry = services.skill_registry
    if skill_registry is None:
        from atlas import server as _atlas_server

        skill_registry = _atlas_server.skill_registry
    assert skill_registry is not None
    approval_scope = skill_registry.issue_lifecycle_approval_from_decision(
        decision_id=decision_id, approval_event_id=approval_id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        created_at=now.isoformat(), expires_at=(now + _server().SKILL_ACQUISITION_TTL).isoformat(),
    )
    if approval_scope is None:
        raise HTTPException(
            status_code=403, detail="valid unconsumed Skill Center decision is required",
        )
    return {"approval_event_id": approval_id, "approval_token": token, **approval_scope,
            "expires_at": (now + _server().SKILL_ACQUISITION_TTL).isoformat()}


def _consume_lifecycle_approval(
    registry: SkillRegistry, payload: dict[str, Any], *, action: str, name: str,
    version: str, current_hash: str, content_hash: str,
    target_trust_state: str | None = None, target_pin_policy: str | None = None,
    rollback_event_id: str | None = None, rollback_snapshot_hash: str | None = None,
) -> dict[str, str]:
    token = payload.get("approval_token")
    if not isinstance(token, str):
        raise HTTPException(status_code=403, detail="server-issued lifecycle approval is required")
    try:
        approval = registry.consume_lifecycle_approval(
            token=token, action=action, name=name, version=version, content_hash=content_hash,
            current_hash=current_hash,
            acquisition_id=(payload.get("dependency_plan_id") if action == "dependency-install"
                            else payload.get("acquisition_id")
                            if action in {"install", "update", "downgrade"} else None),
            target_trust_state=target_trust_state, target_pin_policy=target_pin_policy,
            rollback_event_id=rollback_event_id,
            rollback_snapshot_hash=rollback_snapshot_hash,
        )
    except sqlite3.Error as exc:
        log.exception("skills.lifecycle_approval_read_failed", action=action, name=name)
        raise HTTPException(status_code=503, detail="Skill approval storage is unavailable") from exc
    if approval is None:
        raise HTTPException(
            status_code=403, detail="approval is invalid, expired, mismatched, or replayed",
        )
    return approval


@router.post("/api/skills/lifecycle/update")
async def update_skill_lifecycle(
    services: Annotated[AppServices, Depends(get_app_services)],
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    skill_mgr = _service("skill_mgr", services)
    acquisition_id, version = payload.get("acquisition_id"), payload.get("version")
    session = _server().skill_acquisitions.get(acquisition_id) if isinstance(acquisition_id, str) else None
    if not session or datetime.now(UTC) >= session["expires_at"]:
        raise HTTPException(status_code=410, detail="reviewed update is missing or expired")
    acquisition = session["acquisition"]
    name = acquisition.record["name"]
    if acquisition.record["version"] == version:
        raise HTTPException(status_code=409, detail="exact name and version already exists")
    registry, skills_dir, state = _lifecycle_context(name, str(version or ""))
    if state["lifecycle"]["drifted"]:
        raise HTTPException(status_code=409, detail="filesystem drift blocks update")
    current_tuple = tuple(int(part.split("-")[0]) for part in str(version).split(".")[:3])
    incoming_tuple = tuple(
        int(part.split("-")[0]) for part in acquisition.record["version"].split(".")[:3]
    )
    action = "downgrade" if incoming_tuple < current_tuple else "update"
    approval = _consume_lifecycle_approval(
        registry, payload, action=action, name=name, version=str(version),
        current_hash=str(state["lifecycle"].get("actual_hash")
                         or state["lifecycle"].get("content_hash") or ""),
        content_hash=acquisition.computed_hash,
    )
    try:
        result = await update_lifecycle_skill(
            acquisition, registry=registry, skills_dir=skills_dir, current_version=str(version),
            approval_event_id=approval["approval_event_id"], reason=approval["reason"],
        )
    except (ValueError, PermissionError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    if skill_mgr:
        skill_mgr.scan_skills_sync()
    _server().skill_acquisitions.pop(acquisition_id, None)
    return result


@router.post("/api/skills/lifecycle/install")
async def install_local_skill_package(
    services: Annotated[AppServices, Depends(get_app_services)],
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    skill_mgr = _service("skill_mgr", services)
    skill_registry = _service("skill_registry", services)
    acquisition_id = payload.get("acquisition_id")
    session = _server().skill_acquisitions.get(acquisition_id) if isinstance(acquisition_id, str) else None
    if (not session or not session.get("local_package")
            or datetime.now(UTC) >= session["expires_at"]):
        raise HTTPException(status_code=410, detail="reviewed local package is missing or expired")
    acquisition = session["acquisition"]
    if session.get("computed_sha256") != acquisition.computed_hash:
        raise HTTPException(status_code=409, detail="reviewed package hash changed")
    if acquisition.security.get("result") == "BLOCK":
        raise HTTPException(status_code=403, detail="blocked package cannot be installed")
    if (acquisition.security.get("result") == "WARN"
            and payload.get("warnings_confirmed") is not True):
        raise HTTPException(status_code=403, detail="WARN package requires a second confirmation")
    if "approval_event_id" in payload or "approved" in payload:
        raise HTTPException(
            status_code=403, detail="client-supplied approval claims are not accepted",
        )
    registry = skill_registry
    if registry is None:
        raise HTTPException(status_code=503, detail="Skill Registry is unavailable")
    name, version = acquisition.record["name"], acquisition.record["version"]
    if registry.get(name, version) is not None:
        raise HTTPException(
            status_code=409,
            detail="Skill package with this exact name and version already exists",
        )
    approval = _consume_lifecycle_approval(
        registry, payload, action="install", name=name, version=version,
        current_hash="", content_hash=acquisition.computed_hash,
    )
    try:
        result = await install_acquisition(
            acquisition, skills_dir=skill_mgr._skills_dir if skill_mgr else SKILLS_DIR,
            registry=registry,
            approval_event={
                "approval_event_id": approval["approval_event_id"],
                "approved_at": datetime.now(UTC).isoformat(),
                "computed_sha256": acquisition.computed_hash,
            },
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (PermissionError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if skill_mgr:
        skill_mgr.scan_skills_sync()
    _server().skill_acquisitions.pop(acquisition_id, None)
    return {**result, "package_import": {"status": "installed", "lifecycle_approval": True}}


@router.post("/api/skills/dependencies/install")
async def install_prepared_dependencies(
    services: Annotated[AppServices, Depends(get_app_services)],
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    skill_registry = _service("skill_registry", services)
    plan_id = payload.get("dependency_plan_id")
    plan = _server().skill_dependency_plans.get(plan_id) if isinstance(plan_id, str) else None
    if not plan or datetime.now(UTC) >= plan["expires_at"]:
        raise HTTPException(status_code=410, detail="dependency plan is missing or expired")
    registry = skill_registry
    if registry is None:
        raise HTTPException(status_code=503, detail="Skill Registry is unavailable")
    current = _lifecycle_context(plan["name"], plan["version"])[2]
    current_lifecycle = current["lifecycle"]
    if (current_lifecycle["drifted"]
            or current_lifecycle.get("trust_state") in {"revoked", "blocked"}
            or current_lifecycle.get("state") in {"removed", "quarantined"}
            or current_lifecycle.get("pin_policy") != "unpinned"):
        raise HTTPException(
            status_code=409, detail="filesystem drift blocks dependency installation",
        )
    current_hash = str(current["lifecycle"].get("actual_hash")
                        or current["lifecycle"].get("content_hash") or "")
    approval = _consume_lifecycle_approval(
        registry, {**payload, "dependency_plan_id": plan_id},
        action="dependency-install", name=plan["name"], version=plan["version"],
        current_hash=current_hash, content_hash=current_hash,
    )
    plan["approval_state"] = "consumed"
    results: list[dict[str, Any]] = []
    for item in plan["items"]:
        if not item["executable"]:
            results.append({"name": item["name"], "kind": item["kind"],
                            "status": "unsupported", "reason": item["blocked_reason"]})
            continue
        requirement = item["name"] + (item.get("requested") or "")
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                 "--index-url", "https://pypi.org/simple", requirement],
                check=False, capture_output=True, text=True, timeout=180,
            )
            status = "installed" if completed.returncode == 0 else "failed"
            output = (completed.stderr or completed.stdout or "").splitlines()[-4:]
            results.append({"name": item["name"], "kind": item["kind"],
                            "status": status, "return_code": completed.returncode,
                            "output": output})
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append({"name": item["name"], "kind": item["kind"],
                            "status": "failed", "error": type(exc).__name__})
    return {
        "name": plan["name"], "version": plan["version"],
        "approval_event_id": approval["approval_event_id"],
        "status": "completed" if all(item["status"] == "installed" for item in results)
        else "partial_or_failed", "results": results,
    }


@router.post("/api/skills/lifecycle/remove")
async def remove_skill_lifecycle(
    services: Annotated[AppServices, Depends(get_app_services)],
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    skill_mgr = _service("skill_mgr", services)
    name, version = str(payload.get("name", "")), str(payload.get("version", ""))
    registry, skills_dir, state = _lifecycle_context(name, version)
    actual_hash = state["lifecycle"].get("actual_hash")
    approval = _consume_lifecycle_approval(
        registry, payload, action="remove", name=name, version=version,
        current_hash=str(actual_hash or state["lifecycle"].get("content_hash") or ""),
        content_hash=str(actual_hash or ""),
    )
    try:
        result = remove_lifecycle_skill(
            registry, skills_dir, name, version,
            approval_event_id=approval["approval_event_id"], reason=approval["reason"],
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if skill_mgr:
        skill_mgr.scan_skills_sync()
    return result


@router.post("/api/skills/lifecycle/rollback")
async def rollback_skill_lifecycle(
    services: Annotated[AppServices, Depends(get_app_services)],
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    skill_mgr = _service("skill_mgr", services)
    name, version, event_id = (str(payload.get(key, "")) for key in ("name", "version", "event_id"))
    registry, skills_dir, state = _lifecycle_context(name, version)
    rollback_event = next((item for item in registry.lifecycle_history(name)
                           if item["event_id"] == event_id), None)
    if rollback_event is None:
        raise HTTPException(status_code=404, detail="rollback record not found")
    rollback_hash = rollback_event["details"].get("snapshot_hash")
    approval = _consume_lifecycle_approval(
        registry, payload, action="rollback", name=name, version=version,
        current_hash=str(state["lifecycle"].get("actual_hash")
                         or state["lifecycle"].get("content_hash") or ""),
        content_hash=str(rollback_hash or ""), rollback_event_id=event_id,
        rollback_snapshot_hash=str(rollback_hash or ""),
    )
    try:
        result = rollback_lifecycle_skill(
            registry, skills_dir, name, version, event_id=event_id,
            approval_event_id=approval["approval_event_id"], reason=approval["reason"],
            expected_current_hash=str(state["lifecycle"].get("actual_hash")
                                      or state["lifecycle"].get("content_hash") or ""),
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if skill_mgr:
        skill_mgr.scan_skills_sync()
    return result


@router.post("/api/skills/lifecycle/trust")
async def trust_skill_lifecycle(
    services: Annotated[AppServices, Depends(get_app_services)],
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    name, version, target = (
        str(payload.get(key, "")) for key in ("name", "version", "trust_state")
    )
    registry, _, state = _lifecycle_context(name, version)
    action = "trust"
    approval = _consume_lifecycle_approval(
        registry, payload, action=action, name=name, version=version,
        current_hash=str(state["lifecycle"].get("actual_hash")
                         or state["lifecycle"].get("content_hash") or ""),
        content_hash=str(state["lifecycle"].get("actual_hash") or ""),
        target_trust_state=target,
    )
    try:
        return transition_trust(
            registry, name, version, target, reason=approval["reason"],
            approval_event_id=approval["approval_event_id"],
            content_hash=state["lifecycle"].get("actual_hash"),
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/api/skills/lifecycle/pin")
async def pin_skill_lifecycle(
    services: Annotated[AppServices, Depends(get_app_services)],
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    name, version, policy = (str(payload.get(key, "")) for key in ("name", "version", "policy"))
    registry, skills_dir, state = _lifecycle_context(name, version)
    action = "unpin" if policy == "unpinned" else "pin"
    approval = _consume_lifecycle_approval(
        registry, payload, action=action, name=name, version=version,
        current_hash=str(state["lifecycle"].get("actual_hash")
                         or state["lifecycle"].get("content_hash") or ""),
        content_hash=str(state["lifecycle"].get("actual_hash") or ""),
        target_pin_policy=policy,
    )
    try:
        return transition_pin(
            registry, skills_dir, name, version, policy, reason=approval["reason"],
            approval_event_id=approval["approval_event_id"],
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.get("/api/skills/discover/{name}")
async def get_discovered_skill(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str, version: str | None = Query(None),
) -> dict[str, Any]:
    """Return one registered skill with stable explainability and provenance fields."""
    skill_registry = services.skill_registry
    if skill_registry is None:
        from atlas import server as _atlas_server

        skill_registry = _atlas_server.skill_registry
    assert skill_registry is not None
    result = SkillDiscovery(skill_registry).discover(name=name, status="all", limit=100)
    matches = result["results"]
    if version is not None:
        matches = [item for item in matches if item["version"] == version]
    if not matches:
        raise HTTPException(status_code=404, detail="Skill not found")
    return matches[0]


@router.post("/api/skill-registry")
async def register_skill(
    services: Annotated[AppServices, Depends(get_app_services)],
    metadata: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Validate and persist descriptive skill metadata."""
    skill_registry = services.skill_registry
    if skill_registry is None:
        from atlas import server as _atlas_server

        skill_registry = _atlas_server.skill_registry
    assert skill_registry is not None
    try:
        return skill_registry.register(metadata, source="api")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/api/skill-registry")
async def list_registered_skills(
    services: Annotated[AppServices, Depends(get_app_services)],
    status: str | None = Query(None),
) -> dict[str, Any]:
    """List registered skill versions in deterministic identity order."""
    skill_registry = services.skill_registry
    if skill_registry is None:
        from atlas import server as _atlas_server

        skill_registry = _atlas_server.skill_registry
    assert skill_registry is not None
    if status not in (None, "active", "disabled"):
        raise HTTPException(status_code=422, detail="status must be active or disabled")
    skills = skill_registry.list(status=status)
    return {"count": len(skills), "skills": skills}


@router.get("/api/skill-registry/search")
async def search_registered_skills(
    services: Annotated[AppServices, Depends(get_app_services)],
    q: str = Query(..., min_length=1),
) -> dict[str, Any]:
    """Search active skill metadata by name, description, capability, or tool."""
    skill_registry = services.skill_registry
    if skill_registry is None:
        from atlas import server as _atlas_server

        skill_registry = _atlas_server.skill_registry
    assert skill_registry is not None
    skills = skill_registry.search(q)
    return {"count": len(skills), "skills": skills}


@router.get("/api/skill-registry/{name}/{version}/status")
async def get_registered_skill_status(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str, version: str,
) -> dict[str, Any]:
    skill_registry = services.skill_registry
    if skill_registry is None:
        from atlas import server as _atlas_server

        skill_registry = _atlas_server.skill_registry
    assert skill_registry is not None
    status = skill_registry.status(name, version)
    if status is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"name": name, "version": version, "status": status}


@router.post("/api/skill-registry/{name}/{version}/disable")
async def disable_registered_skill(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str, version: str,
) -> dict[str, Any]:
    skill_registry = services.skill_registry
    if skill_registry is None:
        from atlas import server as _atlas_server

        skill_registry = _atlas_server.skill_registry
    assert skill_registry is not None
    skill = skill_registry.disable(name, version)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.delete("/api/skill-registry/{name}/{version}", status_code=204)
async def remove_registered_skill(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str, version: str,
) -> Response:
    skill_registry = services.skill_registry
    if skill_registry is None:
        from atlas import server as _atlas_server

        skill_registry = _atlas_server.skill_registry
    assert skill_registry is not None
    record = skill_registry.get(name, version)
    if record and (record.get("provenance") or {}).get("installed_path"):
        raise HTTPException(
            status_code=409,
            detail="installed skills require the audited lifecycle removal flow",
        )
    if not skill_registry.remove(name, version):
        raise HTTPException(status_code=404, detail="Skill not found")
    return Response(status_code=204)


@router.get("/api/skill-registry/{name}/{version}")
async def get_registered_skill(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str, version: str,
) -> dict[str, Any]:
    skill_registry = services.skill_registry
    if skill_registry is None:
        from atlas import server as _atlas_server

        skill_registry = _atlas_server.skill_registry
    assert skill_registry is not None
    skill = skill_registry.get(name, version)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.get("/api/skills/{name}")
async def get_skill(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    """Return a single skill's metadata."""
    skill_mgr = services.skill_mgr
    if skill_mgr is None:
        from atlas import server as _atlas_server

        skill_mgr = _atlas_server.skill_mgr
    assert skill_mgr is not None
    skill = skill_mgr.get_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return skill.to_dict()


@router.get("/api/skills/{name}/activate")
async def activate_skill(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    mcp_client = _service("mcp_client", services)
    skill_registry = _service("skill_registry", services)
    """Activate a skill and return its full content."""
    skill_mgr = services.skill_mgr
    if skill_mgr is None:
        from atlas import server as _atlas_server

        skill_mgr = _atlas_server.skill_mgr
    assert skill_mgr is not None
    info = skill_mgr.get_skill(name)
    record = skill_registry.get(name, info.version) if skill_registry and info else None
    lifecycle = (record or {}).get("lifecycle", {})
    if lifecycle.get("trust_state") in {"revoked", "blocked"} or lifecycle.get(
        "state"
    ) in {"quarantined", "removed"}:
        raise HTTPException(status_code=403, detail="skill lifecycle policy blocks activation")
    dependencies = skill_mgr.preflight_dependencies(
        name, connected_servers=mcp_client.get_server_names() if mcp_client else None,
        configured_servers=mcp_client.get_configured_server_names() if mcp_client else None,
        registry=skill_registry,
    )
    blockers = [item for item in dependencies if item["state"] != "satisfied"]
    if blockers:
        raise HTTPException(
            status_code=409,
            detail={"message": "skill dependencies block activation", "dependencies": blockers},
        )
    body = await skill_mgr.activate(
        name, connected_servers=mcp_client.get_server_names() if mcp_client else None,
        configured_servers=mcp_client.get_configured_server_names() if mcp_client else None,
        registry=skill_registry,
    )
    if body is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return {
        "name": name,
        "content": body,
        "dependencies": dependencies,
    }


@router.get("/api/skills/search/{query}")
async def search_skills(
    services: Annotated[AppServices, Depends(get_app_services)],
    query: str,
) -> dict[str, Any]:
    """Search skills by name, description, or tags."""
    skill_mgr = services.skill_mgr
    if skill_mgr is None:
        from atlas import server as _atlas_server

        skill_mgr = _atlas_server.skill_mgr
    assert skill_mgr is not None
    results = skill_mgr.search_skills(query)
    return {
        "count": len(results),
        "skills": [s.to_dict() for s in results],
    }


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

