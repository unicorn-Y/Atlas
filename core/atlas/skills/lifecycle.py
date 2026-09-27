"""Auditable lifecycle transitions for externally installed skills."""

from __future__ import annotations

import hashlib
import inspect
import os
import shutil
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import Any

from atlas.skills.acquisition import (
    Acquisition,
    _validate_files,
    payload_sha256,
    prepare_acquisition,
)
from atlas.skills.dependencies import dependency_preflight
from atlas.skills.registry import SkillRegistry

_LOCKS: dict[tuple[str, str], threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
TRUST_STATES = {"unreviewed", "trusted", "revoked", "blocked"}
PIN_POLICIES = {"unpinned", "exact", "hash"}


def _lock(registry: SkillRegistry, name: str) -> threading.RLock:
    key = (str(registry.path.resolve()), name)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _lifecycle(skill: dict[str, Any]) -> dict[str, Any]:
    current = skill.get("lifecycle")
    return current if isinstance(current, dict) else {
        "state": "active" if skill.get("status") == "active" else "disabled",
        "trust_state": "unreviewed", "pin_policy": "unpinned", "pinned_version": None,
        "pinned_hash": None, "content_hash": (skill.get("provenance") or {}).get(
            "computed_sha256"
        ),
    }


def _managed_path(skills_dir: Path, skill: dict[str, Any]) -> Path:
    provenance = skill.get("provenance") or {}
    recorded = provenance.get("installed_path")
    target = Path(recorded) if isinstance(recorded, str) and recorded else (
        skills_dir / "community" / skill["name"]
    )
    root = skills_dir.resolve()
    resolved = target.resolve(strict=False)
    if not resolved.is_relative_to(root) or target.is_symlink():
        raise ValueError("installed skill path is outside the managed skills directory")
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError("installed skill payload is missing")
    return target


def dependency_states(registry: SkillRegistry, requirements: Any) -> list[dict[str, Any]]:
    return dependency_preflight(
        requirements, registry=registry,
    )


def _payload(path: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for item in path.rglob("*"):
        if item.is_symlink() or not item.is_file():
            if item.is_symlink():
                raise ValueError("installed skill contains a symlink")
            continue
        relative = item.relative_to(path).as_posix()
        files[relative] = item.read_text(encoding="utf-8")
    _validate_files(files)
    return files


def inspect_skill(
    registry: SkillRegistry, skills_dir: Path, name: str, version: str,
) -> dict[str, Any]:
    skill = registry.get(name, version)
    if skill is None:
        raise KeyError("skill not found")
    meta = _lifecycle(skill)
    provenance = skill.get("provenance") or {}
    try:
        actual_files = _payload(_managed_path(skills_dir, skill))
        actual_hash = payload_sha256(actual_files)
        drifted = bool(meta.get("content_hash") and actual_hash != meta["content_hash"])
    except (OSError, UnicodeError, ValueError) as exc:
        actual_hash = None
        actual_files = {}
        drifted = True
        drift_error = str(exc)
    else:
        drift_error = None
    dependency_state = dependency_states(registry, skill.get("requirements", []))
    return {
        **skill, "lifecycle": {**meta, "drifted": drifted, "actual_hash": actual_hash,
                               "drift_error": drift_error},
        "provenance": provenance, "dependency_state": dependency_state,
        "file_hashes": {
            path: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for path, content in actual_files.items()
        },
        "history": registry.lifecycle_history(name),
    }


def _event(
    *, name: str, action: str, version: str, actor: str, reason: str, result: str,
    previous_hash: str | None = None, resulting_version: str | None = None,
    resulting_hash: str | None = None, source: str | None = None, provider: str | None = None,
    trust_before: str | None = None, trust_after: str | None = None,
    pin_before: str | None = None, pin_after: str | None = None,
    approval_event_id: str | None = None, error_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()), "name": name, "timestamp": _now(), "action": action,
        "skill_version": version, "previous_version": version, "previous_hash": previous_hash,
        "resulting_version": resulting_version, "resulting_hash": resulting_hash,
        "source": source, "provider": provider, "trust_before": trust_before,
        "trust_after": trust_after, "pin_before": pin_before, "pin_after": pin_after,
        "approval_event_id": approval_event_id, "actor": actor, "reason": reason,
        "result": result, "error_code": error_code, "details": details or {},
    }


def _audit_failures(action: str):
    def decorate(function):
        signature = inspect.signature(function)

        def record_failure(bound, error: Exception) -> None:
            registry = bound.arguments.get("registry")
            acquisition = bound.arguments.get("acquisition")
            name = bound.arguments.get("name")
            if not isinstance(name, str) and isinstance(acquisition, Acquisition):
                name = acquisition.record.get("name")
            version = bound.arguments.get("current_version", bound.arguments.get("version"))
            if not isinstance(name, str) or not isinstance(version, str):
                return
            try:
                skill = registry.get(name, version)
                meta = _lifecycle(skill) if skill else {
                    "trust_state": "unreviewed", "pin_policy": "unpinned",
                    "content_hash": None,
                }
                event = _event(
                    name=name, action=action, version=version, actor="user",
                    reason=str(bound.arguments.get("reason", "lifecycle attempt")),
                    result="blocked" if isinstance(error, PermissionError) else "failure",
                    previous_hash=meta.get("content_hash"),
                    source=(skill.get("provenance") or {}).get("source_url") if skill else None,
                    provider=(skill.get("provenance") or {}).get("provider") if skill else None,
                    trust_before=meta.get("trust_state"), trust_after=meta.get("trust_state"),
                    pin_before=meta.get("pin_policy"), pin_after=meta.get("pin_policy"),
                    approval_event_id=bound.arguments.get("approval_event_id"),
                    error_code=type(error).__name__,
                )
                registry.record_lifecycle_event(event)
            except Exception:
                return

        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def async_wrapper(*args, **kwargs):
                bound = signature.bind_partial(*args, **kwargs)
                try:
                    return await function(*args, **kwargs)
                except Exception as error:
                    record_failure(bound, error)
                    raise

            return async_wrapper

        @wraps(function)
        def sync_wrapper(*args, **kwargs):
            bound = signature.bind_partial(*args, **kwargs)
            try:
                return function(*args, **kwargs)
            except Exception as error:
                record_failure(bound, error)
                raise

        return sync_wrapper

    return decorate


@_audit_failures("trust")
def transition_trust(
    registry: SkillRegistry, name: str, version: str, state: str, *, reason: str,
    approval_event_id: str, content_hash: str | None = None,
) -> dict[str, Any]:
    if state not in TRUST_STATES or not reason.strip():
        raise ValueError("valid trust state and reason are required")
    with _lock(registry, name):
        skill = registry.get(name, version)
        if skill is None:
            raise KeyError("skill not found")
        meta = _lifecycle(skill)
        before_hash = content_hash or meta.get("content_hash")
        before = meta["trust_state"]
        if before in {"revoked", "blocked"} and state != before:
            raise PermissionError("revoked or blocked trust cannot be restored by lifecycle action")
        meta["trust_state"] = state
        if content_hash:
            meta["content_hash"] = content_hash
        if state == "blocked":
            meta["state"] = "quarantined"
        skill["lifecycle"] = meta
        provenance = skill.get("provenance") or {}
        event = _event(name=name, action="trust", version=version, actor="user", reason=reason,
                       result="success", previous_hash=before_hash,
                       resulting_version=version, resulting_hash=meta.get("content_hash"),
                       source=provenance.get("source_url"), provider=provenance.get("provider"),
                       trust_before=before, trust_after=state, approval_event_id=approval_event_id)
        registry.record_lifecycle_event(event, metadata=skill, version=version)
        return registry.get(name, version) or skill


@_audit_failures("pin")
def transition_pin(
    registry: SkillRegistry, skills_dir: Path, name: str, version: str, policy: str, *,
    reason: str, approval_event_id: str,
) -> dict[str, Any]:
    if policy not in PIN_POLICIES or not reason.strip():
        raise ValueError("valid pin policy and reason are required")
    with _lock(registry, name):
        inspected = inspect_skill(registry, skills_dir, name, version)
        meta = _lifecycle(inspected)
        if meta["drifted"]:
            raise PermissionError("filesystem drift blocks pin changes")
        before_hash = meta.get("content_hash")
        resulting_hash = inspected["lifecycle"]["actual_hash"]
        meta["content_hash"] = resulting_hash
        before = meta["pin_policy"]
        meta["pin_policy"] = policy
        meta["pinned_version"] = version if policy == "exact" else None
        meta["pinned_hash"] = inspected["lifecycle"]["actual_hash"] if policy == "hash" else None
        skill = registry.get(name, version)
        assert skill is not None
        skill["lifecycle"] = meta
        provenance = skill.get("provenance") or {}
        event = _event(name=name, action="unpin" if policy == "unpinned" else "pin",
                       version=version, actor="user", reason=reason, result="success",
                       previous_hash=before_hash, pin_before=before, pin_after=policy,
                       resulting_version=version, resulting_hash=resulting_hash,
                       source=provenance.get("source_url"), provider=provenance.get("provider"),
                       approval_event_id=approval_event_id)
        registry.record_lifecycle_event(event, metadata=skill, version=version)
        return skill


def _snapshot(path: Path, root: Path, name: str, event_id: str) -> tuple[Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.resolve().is_relative_to(root.parent.resolve()):
        raise ValueError("rollback storage escapes its trusted parent")
    snapshot = root / name / event_id
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if snapshot.exists():
        raise FileExistsError("rollback snapshot already exists")
    try:
        shutil.copytree(path, snapshot, symlinks=True)
        digest = payload_sha256(_payload(snapshot))
        return snapshot, digest
    except Exception:
        shutil.rmtree(snapshot, ignore_errors=True)
        raise


def _replace(target: Path, files: dict[str, str], *, previous_root: Path) -> Path:
    stage_parent = target.parent
    stage = Path(tempfile.mkdtemp(prefix=".atlas-skill-stage-", dir=stage_parent))
    for relative, content in files.items():
        destination = stage.joinpath(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    previous_root.mkdir(parents=True, exist_ok=True)
    previous = previous_root / f".atlas-skill-previous-{uuid.uuid4().hex}"
    os.replace(target, previous)
    try:
        for attempt in range(3):
            try:
                os.replace(stage, target)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.025 * (attempt + 1))
    except Exception:
        os.replace(previous, target)
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return previous


@_audit_failures("update")
async def update_skill(
    acquisition: Acquisition, *, registry: SkillRegistry, skills_dir: Path,
    current_version: str, approval_event_id: str, reason: str,
) -> dict[str, Any]:
    verified = prepare_acquisition(acquisition.record, acquisition.files)
    if (verified.computed_hash != acquisition.computed_hash
            or verified.security != acquisition.security):
        raise PermissionError("update payload changed since security review")
    acquisition = verified
    name = acquisition.record["name"]
    with _lock(registry, name):
        current = registry.get(name, current_version)
        if current is None:
            raise KeyError("installed skill not found")
        inspected = inspect_skill(registry, skills_dir, name, current_version)
        meta = _lifecycle(current)
        if inspected["lifecycle"]["drifted"]:
            raise PermissionError("filesystem drift blocks update")
        if meta["trust_state"] in {"revoked", "blocked"}:
            raise PermissionError("revoked or blocked skill cannot be updated")
        target_record = registry.get(name, acquisition.record["version"])
        if target_record is not None and acquisition.record["version"] != current_version:
            raise ValueError("target skill name and version already exist in Registry")
        if meta["pin_policy"] != "unpinned":
            raise PermissionError("pinned skill must be explicitly unpinned before update")
        new_dependencies = dependency_states(
            registry, acquisition.validation.get("dependencies", []),
        )
        blockers = [item["name"] for item in new_dependencies
                    if item["state"] != "satisfied"]
        if blockers:
            raise PermissionError("update dependencies are not satisfied: " + ", ".join(blockers))
        old_source = (current.get("provenance") or {}).get("external_id")
        if old_source != acquisition.record.get("external_id"):
            raise PermissionError("source identity changed; update requires a separate review")
        old_provider = (current.get("provenance") or {}).get("provider")
        if old_provider != acquisition.record.get("provider"):
            raise PermissionError("provider changed; update requires a separate review")
        if acquisition.security.get("result") == "BLOCK":
            raise PermissionError("blocked update cannot be installed")
        old_version_tuple = tuple(int(part) for part in current_version.split(".")[:3])
        new_version_tuple = tuple(
            int(part) for part in acquisition.record["version"].split(".")[:3]
        )
        if (acquisition.computed_hash == meta.get("content_hash")
                and new_version_tuple >= old_version_tuple):
            registry.record_lifecycle_event(_event(
                name=name, action="update", version=current_version, actor="user",
                reason=reason, result="no_op", previous_hash=meta.get("content_hash"),
                resulting_version=acquisition.record["version"],
                resulting_hash=acquisition.computed_hash,
                source=acquisition.record.get("source_url"),
                provider=acquisition.record.get("provider"),
                trust_before=meta["trust_state"], trust_after=meta["trust_state"],
                pin_before=meta["pin_policy"], pin_after=meta["pin_policy"],
                approval_event_id=approval_event_id,
            ))
            return {"status": "unchanged", "name": name, "version": current_version,
                    "hash": acquisition.computed_hash}
        operation_action = "downgrade" if new_version_tuple < old_version_tuple else "update"
        old_path = _managed_path(skills_dir, current)
        snapshot_root = skills_dir.parent / ".atlas-skill-rollback"
        event_id = str(uuid.uuid4())
        snapshot, snapshot_hash = _snapshot(old_path, snapshot_root, name, event_id)
        target = old_path
        try:
            previous_dir = _replace(
                target, acquisition.files, previous_root=skills_dir.parent,
            )
        except Exception:
            shutil.rmtree(snapshot, ignore_errors=True)
            raise
        new_meta = {**meta, "state": "active", "content_hash": acquisition.computed_hash}
        try:
            new_registry = {
                **current, "version": acquisition.record["version"],
                "description": acquisition.record["description"],
                "requirements": acquisition.validation.get("dependencies", []),
                "provenance": {**(acquisition.record), "computed_sha256": acquisition.computed_hash,
                               "installed_path": str(target), "rollback_event_id": event_id},
                "lifecycle": new_meta,
            }
            old_record = {**current, "lifecycle": {**meta, "state": "rollback-available"}}
            new_registry["source"] = (
                f"{acquisition.record['provider']}:{acquisition.record['external_id']}"
            )
            event = _event(
                name=name, action=operation_action, version=current_version, actor="user",
                reason=reason, result="success", previous_hash=meta.get("content_hash"),
                resulting_version=acquisition.record["version"],
                resulting_hash=acquisition.computed_hash,
                source=acquisition.record.get("source_url"),
                provider=acquisition.record.get("provider"), trust_before=meta["trust_state"],
                trust_after=meta["trust_state"], pin_before=meta["pin_policy"],
                pin_after=meta["pin_policy"], approval_event_id=approval_event_id,
                details={"snapshot": str(snapshot), "snapshot_hash": snapshot_hash,
                         "snapshot_version": current_version,
                         "snapshot_metadata": current,
                         "snapshot_registry_source": current.get("source")},
            )
            from atlas.skills import SkillManager

            SkillManager(skills_dir=skills_dir).scan_skills_sync()
            registry.commit_lifecycle_update(
                previous=old_record, resulting=new_registry, event=event,
                old_version=current_version,
            )
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            os.replace(previous_dir, target)
            shutil.rmtree(snapshot, ignore_errors=True)
            raise
        shutil.rmtree(previous_dir, ignore_errors=True)
        return {"status": "updated", "name": name, "version": acquisition.record["version"],
                "hash": acquisition.computed_hash, "rollback_snapshot_hash": snapshot_hash}


@_audit_failures("remove")
def remove_skill(
    registry: SkillRegistry, skills_dir: Path, name: str, version: str, *,
    approval_event_id: str, reason: str,
) -> dict[str, Any]:
    with _lock(registry, name):
        inspected = inspect_skill(registry, skills_dir, name, version)
        meta = _lifecycle(inspected)
        if inspected["lifecycle"]["drifted"]:
            raise PermissionError("filesystem drift blocks remove")
        dependents = [item["name"] for item in registry.list(status="active")
                      if item["name"] != name and any(
                          requirement == name or requirement == f"skill:{name}"
                          or (isinstance(requirement, str) and requirement.startswith(
                              f"skill:{name}@"
                          ))
                          for requirement in (item.get("requirements") or [])
                      )]
        if dependents:
            raise PermissionError("active skills declare this dependency: " + ", ".join(dependents))
        target = _managed_path(skills_dir, inspected)
        event_id = str(uuid.uuid4())
        snapshot, snapshot_hash = _snapshot(
            target, skills_dir.parent / ".atlas-skill-rollback", name, event_id,
        )
        tombstone = skills_dir.parent / f".atlas-skill-removed-{event_id}"
        try:
            os.replace(target, tombstone)
        except Exception:
            shutil.rmtree(snapshot, ignore_errors=True)
            raise
        skill = registry.get(name, version)
        assert skill is not None
        meta["state"] = "removed"
        skill["lifecycle"] = meta
        try:
            from atlas.skills import SkillManager

            SkillManager(skills_dir=skills_dir).scan_skills_sync()
            registry.record_lifecycle_event(_event(
                name=name, action="remove", version=version, actor="user", reason=reason,
                result="success", previous_hash=meta.get("content_hash"),
                resulting_version=version, resulting_hash=None,
                source=(skill.get("provenance") or {}).get("source_url"),
                provider=(skill.get("provenance") or {}).get("provider"),
                trust_before=meta["trust_state"], trust_after=meta["trust_state"],
                pin_before=meta["pin_policy"], pin_after=meta["pin_policy"],
                approval_event_id=approval_event_id,
                details={"snapshot": str(snapshot), "snapshot_hash": snapshot_hash,
                         "snapshot_version": version,
                         "snapshot_metadata": skill,
                         "snapshot_registry_source": skill.get("source")},
            ), metadata=skill, version=version, status="disabled")
        except Exception:
            os.replace(tombstone, target)
            shutil.rmtree(snapshot, ignore_errors=True)
            raise
        shutil.rmtree(tombstone, ignore_errors=True)
        return {"status": "removed", "name": name, "version": version,
                "hash": meta.get("content_hash"), "rollback_snapshot_hash": snapshot_hash,
                "dependents": dependents}


@_audit_failures("rollback")
def rollback_skill(
    registry: SkillRegistry, skills_dir: Path, name: str, version: str, *,
    event_id: str, approval_event_id: str, reason: str,
    expected_current_hash: str | None = None,
) -> dict[str, Any]:
    with _lock(registry, name):
        history = registry.lifecycle_history(name, limit=1000)
        source_event = next((item for item in history if item["event_id"] == event_id), None)
        if not source_event or source_event["action"] not in {
            "update", "downgrade", "remove", "rollback",
        }:
            raise ValueError("rollback record is missing or invalid")
        details = source_event["details"]
        snapshot = Path(details.get("snapshot", ""))
        expected_hash = details.get("snapshot_hash")
        expected_root = (skills_dir.parent / ".atlas-skill-rollback" / name).resolve()
        try:
            snapshot_resolved = snapshot.resolve(strict=True)
            in_rollback_root = snapshot_resolved.is_relative_to(expected_root)
        except OSError:
            in_rollback_root = False
        if (not snapshot.is_dir() or snapshot.is_symlink() or not in_rollback_root
                or not isinstance(expected_hash, str)):
            raise ValueError("rollback snapshot is missing or corrupt")
        files = _payload(snapshot)
        actual_hash = payload_sha256(files)
        if actual_hash != expected_hash:
            raise ValueError("rollback snapshot hash mismatch")
        current = registry.get(name, version)
        if current is None:
            current = registry.get(name, details.get("snapshot_version", ""))
        if current is None:
            raise KeyError("skill provenance for rollback target is missing")
        meta = _lifecycle(current)
        current_path = skills_dir / "community" / name
        current_hash = None
        if current_path.exists():
            current_state = inspect_skill(registry, skills_dir, name, version)
            if current_state["lifecycle"]["drifted"]:
                raise PermissionError("filesystem drift blocks rollback")
            current_hash = current_state["lifecycle"].get("actual_hash")
        else:
            current_hash = meta.get("content_hash")
        if expected_current_hash is not None and current_hash != expected_current_hash:
            raise PermissionError("current skill hash changed after rollback approval")
        if meta["trust_state"] in {"revoked", "blocked"}:
            raise PermissionError("revoked or blocked skill cannot be restored")
        restored_version = details.get("snapshot_version") or version
        if (meta["pin_policy"] == "exact" and meta.get("pinned_version") != restored_version):
            raise PermissionError("rollback target conflicts with exact version pin")
        if meta["pin_policy"] == "hash" and meta.get("pinned_hash") != actual_hash:
            raise PermissionError("rollback target conflicts with content hash pin")
        target = skills_dir / "community" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        current_snapshot = None
        current_snapshot_hash = None
        if target.exists():
            inspected = inspect_skill(registry, skills_dir, name, version)
            if inspected["lifecycle"]["drifted"]:
                raise PermissionError("filesystem drift blocks rollback")
            current_snapshot, current_snapshot_hash = _snapshot(
                target, skills_dir.parent / ".atlas-skill-rollback", name, str(uuid.uuid4()),
            )
            try:
                previous = _replace(target, files, previous_root=skills_dir.parent)
            except Exception:
                shutil.rmtree(current_snapshot, ignore_errors=True)
                raise
        else:
            stage = Path(tempfile.mkdtemp(prefix=".atlas-skill-stage-", dir=target.parent))
            shutil.rmtree(stage)
            for relative, content in files.items():
                destination = stage.joinpath(*PurePosixPath(relative).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
            os.replace(stage, target)
            previous = None
        restored = details.get("snapshot_metadata")
        if not isinstance(restored, dict):
            restored = registry.get(name, restored_version) or current
        else:
            restored = {**restored, "name": name, "version": restored_version}
        restored["lifecycle"] = {
            **_lifecycle(restored), "state": "active", "content_hash": actual_hash,
        }
        provenance = current.get("provenance") or {}
        try:
            event = _event(
                name=name, action="rollback", version=version, actor="user", reason=reason,
                result="success", previous_hash=meta.get("content_hash"),
                resulting_version=restored_version, resulting_hash=actual_hash,
                source=provenance.get("source_url"), provider=provenance.get("provider"),
                approval_event_id=approval_event_id,
                details={
                    "restored_from_event": event_id,
                    "snapshot": str(current_snapshot) if current_snapshot else None,
                    "snapshot_hash": current_snapshot_hash,
                    "snapshot_version": version if current_snapshot else None,
                    "snapshot_metadata": current if current_snapshot else None,
                    "snapshot_registry_source": current.get("source") if current_snapshot else None,
                },
            )
            registry.commit_lifecycle_rollback(
                current_version=version,
                current={**current, "lifecycle": {**meta, "state": "superseded"}},
                restored_version=restored["version"], restored=restored, event=event,
                restored_source=details.get("snapshot_registry_source"),
            )
        except Exception:
            if previous and target.exists():
                shutil.rmtree(target, ignore_errors=True)
                os.replace(previous, target)
            elif previous is None:
                shutil.rmtree(target, ignore_errors=True)
            if current_snapshot:
                shutil.rmtree(current_snapshot, ignore_errors=True)
            raise
        if previous:
            shutil.rmtree(previous, ignore_errors=True)
        return {"status": "rolled_back", "name": name, "version": restored_version,
                "hash": actual_hash, "source_event_id": event_id}
