"""Filesystem lifecycle for rebuildable, provenance-linked learned skills."""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from atlas.evolution.skill_candidate import SkillCandidate, score_candidate
from atlas.skills import SKILLS_DIR

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_CANDIDATE_DIR = "技能候选"


def candidate_root(memory_root: Path) -> Path:
    return Path(memory_root) / _CANDIDATE_DIR


def _parse_skill(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if not match:
        raise ValueError("SKILL.md 缺少 frontmatter")
    data = yaml.safe_load(match.group(1))
    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter 无效")
    return data, text[match.end():]


def _write_skill(path: Path, metadata: dict[str, Any], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
                   + "\n---\n\n" + body.lstrip(), encoding="utf-8")
    tmp.replace(path)


def _with_metadata(markdown: str, additions: dict[str, Any]) -> str:
    match = _FRONTMATTER.match(markdown)
    if not match:
        raise ValueError("候选缺少 frontmatter")
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict):
        raise ValueError("候选 frontmatter 无效")
    metadata.update(additions)
    return ("---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
            + "\n---\n\n" + markdown[match.end():].lstrip())


def stage_candidate(memory_root: Path, candidate: SkillCandidate, *,
                    validation: dict[str, Any] | None = None,
                    status: str = "staging") -> Path:
    """Persist a rebuildable candidate under the Markdown memory root."""
    if status not in {"candidate", "staging", "rejected", "promoted", "archived"}:
        raise ValueError("invalid skill candidate status")
    if not candidate.source_refs or len(candidate.evidence_ids) < 2:
        raise ValueError("candidate requires source refs and two experience IDs")
    markdown = candidate.as_markdown()
    metadata = {"candidate_status": status, "validation": validation or {}}
    output = _with_metadata(markdown, metadata)
    path = candidate_root(memory_root) / candidate.name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    ignore = path.parent / ".gitignore"
    if not ignore.exists():
        ignore.write_text(".skillopt-state/\n", encoding="utf-8")
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(output, encoding="utf-8")
    tmp.replace(path)
    return path


def record_candidate_rejection(memory_root: Path, experiences: list[Any], reason: str) -> Path:
    """Retain a validation rejection without creating an executable skill."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    refs = [ref for item in experiences for ref in item.source_refs]
    ids = [item.experience_id for item in experiences]
    path = candidate_root(memory_root) / "rejected" / stamp / "SKILL.md"
    metadata = {"name": "rejected-candidate", "description": "Rejected learned-skill candidate",
                "version": "0.0.0", "candidate_status": "rejected",
                "metadata": {"source_experience_ids": ids, "source_refs": refs},
                "rejection_reason": reason[:1000]}
    _write_skill(path, metadata, "此候选未通过格式或来源校验，因此没有可执行步骤。\n")
    return path


def archive_candidate(candidate_path: Path, *, reason: str) -> Path:
    """Record a rejected or superseded candidate in-place; source remains auditable."""
    metadata, body = _parse_skill(candidate_path)
    metadata["candidate_status"] = "archived"
    metadata["archive_reason"] = str(reason)[:500]
    _write_skill(candidate_path, metadata, body)
    return candidate_path


def record_validation(candidate_path: Path, *, validation: dict[str, Any],
                      benchmark: dict[str, Any], candidate: SkillCandidate | None = None) -> Path:
    """Persist heldout evidence beside the candidate as rebuildable Markdown metadata."""
    metadata, body = _parse_skill(candidate_path)
    if candidate is not None:
        source, _ = _parse_skill_text(candidate.as_markdown())
        for key in ("name", "description", "version", "triggers", "metadata"):
            metadata.setdefault(key, source[key])
        metadata["metadata"] = source["metadata"]
    metadata["validation"] = dict(validation)
    metadata["benchmark"] = dict(benchmark)
    metadata["candidate_status"] = "staging"
    _write_skill(candidate_path, metadata, body)
    return candidate_path


def _parse_skill_text(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER.match(text)
    if not match:
        raise ValueError("SKILL.md 缺少 frontmatter")
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict):
        raise ValueError("SKILL.md frontmatter 无效")
    return metadata, text[match.end():]


def _memory_library():
    from atlas.memory.library import get_library

    library = get_library()
    if library is None:
        raise RuntimeError("memory library is disabled; skill promotion requires its change log")
    library.store.ensure()
    return library


def _append_daily_change(library: Any, message: str, *, metadata: dict[str, Any]) -> str | None:
    from atlas.memory.library.store import Entry

    now = datetime.now(UTC)
    rel = f"日记/{now.date().isoformat()}.md"
    page = library.store.read(rel)
    page.current.append(Entry(text=message, id=f"skill-{now.strftime('%H%M%S%f')}",
                              src="整理", source_level="model_inference", recorded_at=now.isoformat(),
                              extra_metadata=metadata))
    library.store.write(page)
    return library.store.commit("技能版本变动：" + message[:80])


def _version_parts(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", version)
    return tuple(map(int, match.groups())) if match else (0, 1, 0)


def _next_version(current: str | None) -> str:
    major, minor, patch = _version_parts(current or "0.0.0")
    return f"{major}.{minor}.{patch + 1}"


def _stored_gate_passed(decision: Any, heldout: Any) -> bool:
    """Recheck every persisted promotion condition before using stored evidence."""
    if not isinstance(decision, dict) or not isinstance(heldout, dict):
        return False
    heldout_ids = {str(item) for item in heldout.get("heldout_ids", [])}
    success_ids = {str(item) for item in heldout.get("success_ids", [])}
    counterexample_ids = {str(item) for item in heldout.get("counterexample_ids", [])}
    try:
        strict_gain = float(decision["candidate_score"]) > float(decision["baseline_score"])
        enough_tasks = int(decision["task_count"]) >= 2
        zero_blockers = (int(decision["safety_blockers"]) == 0
                         and int(decision["correctness_blockers"]) == 0)
    except (KeyError, TypeError, ValueError):
        return False
    return bool(
        decision.get("passed") is True
        and decision.get("gate_mode") == "on"
        and decision.get("blocker_evidence_available") is True
        and decision.get("holdout_leaked") is False
        and strict_gain and enough_tasks and zero_blockers
        and not decision.get("other_blockers")
        and heldout.get("passed") is True
        and success_ids and counterexample_ids
        and success_ids <= heldout_ids and counterexample_ids <= heldout_ids
    )


def promote_candidate(candidate_path: Path, *, report: Any | None = None,
                      gate_mode: str = "on",
                      safety_blockers: int | None = None, correctness_blockers: int | None = None,
                      skill_root: Path | None = None,
                      user_reviewed: bool | None = None,
                      **_kwargs: Any) -> dict[str, Any]:
    """Automatically promote a candidate only after its strict real heldout gate passes."""
    metadata, body = _parse_skill(candidate_path)
    if report is None:
        decision = metadata.get("validation") or {}
        benchmark = metadata.get("benchmark") or {}
        heldout = benchmark.get("heldout") if isinstance(benchmark, dict) else None
        if not _stored_gate_passed(decision, heldout):
            return {"promoted": False, "path": str(candidate_path),
                    "reason": "stored_promotion_evidence_incomplete_or_not_passed"}
    else:
        decision = score_candidate(report, gate_mode=gate_mode, safety_blockers=safety_blockers,
                                   correctness_blockers=correctness_blockers)
        benchmark = metadata.get("benchmark") or {}
        heldout = benchmark.get("heldout") if isinstance(benchmark, dict) else None
        if not _stored_gate_passed(decision, heldout):
            decision = {**decision, "passed": False,
                        "reason": "promotion_evidence_incomplete_or_not_passed"}
    metadata["validation"] = {**(metadata.get("validation") or {}), **decision}
    metadata["candidate_status"] = "staging" if not decision["passed"] else "promoted"
    if not decision["passed"]:
        _write_skill(candidate_path, metadata, body)
        return {"promoted": False, "path": str(candidate_path), "gate": decision}

    name = str(metadata.get("name") or "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("candidate has invalid skill name")
    sources = metadata.get("metadata") or {}
    source_refs = sources.get("source_refs") or []
    source_ids = sources.get("source_experience_ids") or []
    if len(source_ids) < 2 or not source_refs:
        raise ValueError("promotable skill must retain two experience IDs and source refs")

    library = _memory_library()
    live_dir = (skill_root or SKILLS_DIR) / "learned" / name
    live_path = live_dir / "SKILL.md"
    prior_version = None
    prior_backup = None
    if live_path.exists():
        prior_meta, _ = _parse_skill(live_path)
        prior_version = str(prior_meta.get("version") or "0.0.0")
        # Snapshot belongs to the memory-root derived manifest so M7 can discover it.
        prior_backup = candidate_root(library.store.root) / "versions" / name / prior_version / "SKILL.md"
        prior_backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live_path, prior_backup)

    version = _next_version(prior_version or str(metadata.get("version") or "0.1.0"))
    metadata["version"] = version
    metadata["candidate_status"] = "promoted"
    metadata["promotion"] = {"promoted_at": datetime.now(UTC).isoformat(),
                              "previous_version": prior_version}
    stage_candidate_path = candidate_root(library.store.root) / name / "SKILL.md"
    if candidate_path.resolve() != stage_candidate_path.resolve():
        stage_candidate_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate_path, stage_candidate_path)
        candidate_path = stage_candidate_path
    _write_skill(candidate_path, metadata, body)
    tmp = live_path.with_suffix(".md.tmp")
    live_dir.mkdir(parents=True, exist_ok=True)
    tmp.write_text("---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
                   + "\n---\n\n" + body.lstrip(), encoding="utf-8")
    tmp.replace(live_path)
    message = f"技能 {name} 升级到 {version}；回滚版本 {prior_version or '无'}"
    commit = _append_daily_change(library, message, metadata={
        "skill_name": name, "skill_version": version, "previous_version": prior_version,
        "source_experience_ids": source_ids, "source_refs": source_refs,
        "validation": decision,
    })
    return {"promoted": True, "path": str(live_path), "version": version,
            "previous_version": prior_version, "backup": str(prior_backup) if prior_backup else None,
            "memory_commit": commit, "gate": decision}


def rollback_promotion(name: str, *, previous_version: str | None,
                       skill_root: Path | None = None) -> dict[str, Any]:
    """Restore an archived skill version, or remove the learned skill if it was new."""
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("invalid skill name")
    library = _memory_library()
    live_path = (skill_root or SKILLS_DIR) / "learned" / name / "SKILL.md"
    if previous_version:
        backup = candidate_root(library.store.root) / "versions" / name / previous_version / "SKILL.md"
        if not backup.is_file():
            raise FileNotFoundError("previous learned-skill version is unavailable")
        live_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, live_path.with_suffix(".md.tmp"))
        live_path.with_suffix(".md.tmp").replace(live_path)
    else:
        live_path.unlink(missing_ok=True)
    commit = _append_daily_change(library, f"技能 {name} 已回滚到 {previous_version or '初始状态'}",
                                  metadata={"skill_name": name, "rollback_to": previous_version})
    return {"rolled_back": True, "path": str(live_path), "version": previous_version,
            "memory_commit": commit}


def derived_manifest_for_sources(memory_root: Path, source_refs: list[dict[str, Any]]) -> dict[str, Any]:
    """Return memory-root derivative paths and external live skills linked to these refs.

    M7's propagate_forget accepts only paths under its memory root. Callers must
    pass ``memory_paths`` as its derived_manifest and separately use
    ``external_live_paths`` through an authorized learned-skill cleanup callback.
    """
    targets = {(str(ref.get("conversation_id")), str(ref.get("message_uid")))
               for ref in source_refs if ref.get("conversation_id") and ref.get("message_uid")}
    memory_paths: list[str] = []
    external_live_paths: list[str] = []
    external_live_needs_rebuild: list[str] = []
    root = candidate_root(memory_root)
    if not root.is_dir():
        return {"memory_paths": [], "external_live_paths": [], "external_live_needs_rebuild": []}
    for path in root.rglob("SKILL.md"):
        try:
            metadata, _ = _parse_skill(path)
        except (OSError, ValueError, yaml.YAMLError):
            continue
        details = metadata.get("metadata") or {}
        refs = details.get("source_refs") or []
        ref_keys = {(str(item.get("conversation_id")), str(item.get("message_uid")))
                    for item in refs if isinstance(item, dict)
                    and item.get("conversation_id") and item.get("message_uid")}
        matched = ref_keys & targets
        found = bool(matched)
        if not found:
            continue
        try:
            memory_paths.append(path.relative_to(memory_root).as_posix())
        except ValueError:
            continue
        relative_parts = path.relative_to(root).parts
        if "versions" not in relative_parts and "archived" not in relative_parts and "rejected" not in relative_parts:
            live = Path(SKILLS_DIR) / "learned" / str(metadata.get("name") or path.parent.name) / "SKILL.md"
            if live.is_file():
                if ref_keys and ref_keys <= targets:
                    external_live_paths.append(str(live))
                else:
                    external_live_needs_rebuild.append(str(live))
        state_dir = path.parent / ".skillopt-state"
        if state_dir.exists():
            try:
                memory_paths.append(state_dir.relative_to(memory_root).as_posix())
            except ValueError:
                pass
    return {"memory_paths": sorted(set(memory_paths)),
            "external_live_paths": sorted(set(external_live_paths)),
            "external_live_needs_rebuild": sorted(set(external_live_needs_rebuild))}


__all__ = ["archive_candidate", "candidate_root", "derived_manifest_for_sources",
           "promote_candidate", "record_candidate_rejection", "record_validation",
           "rollback_promotion", "stage_candidate"]
