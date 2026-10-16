"""Daily project-memory consolidation in three small, retryable phases."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from .consolidation import entry_metadata, text_hash, validate_plan
from .claim_resolution import is_current_claim, resolve_claim_conflict
from .store import NOW, SRC_DREAM, SRC_EDITED, SRC_SAID, THINGS, Entry, Page, new_id, safe_name, tombstone_hashes

log = structlog.get_logger(__name__)
_SECTIONS = ("现在状态", "定下的决定", "没做完", "来龙去脉")
_DEADLINE = re.compile(r"(?<!\d)(20\d\d-\d\d-\d\d)(?!\d)")


def _checkpoint(path: Path) -> str:
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("checkpoint") or "")
    except (OSError, ValueError, TypeError):
        return ""


def _episode_fingerprint(entry: Entry) -> str:
    metadata = entry_metadata(entry)
    payload = {
        "id": entry.id,
        "source_refs": metadata.get("source_refs") or entry.ref,
        "extractor_version": metadata.get("extractor_version", "legacy"),
        "text": entry.text,
    }
    return text_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _mark_processed(markdown: str, entries: list[Entry]) -> str:
    marker = re.compile(r"^<!-- m4-processed:(\{.*\}) -->\s*$", re.M)
    match = marker.search(markdown)
    processed: dict[str, str] = {}
    if match:
        try:
            raw = json.loads(match.group(1))
            if isinstance(raw, dict):
                processed.update({str(key): str(value) for key, value in raw.items()})
        except ValueError:
            pass
    processed.update({entry.id: _episode_fingerprint(entry) for entry in entries})
    rendered_marker = "<!-- m4-processed:" + json.dumps(processed, ensure_ascii=False,
                                                           sort_keys=True, separators=(",", ":")) + " -->"
    if match:
        markdown = markdown[:match.start()] + rendered_marker + markdown[match.end():]
    else:
        markdown = markdown.rstrip() + "\n" + rendered_marker + "\n"
    return markdown


def _episode_groups(library: Any, checkpoint: str) -> dict[str, list[Entry]]:
    groups: dict[str, list[Entry]] = {}
    seen_fingerprints: dict[str, str] = {}
    for rel in library.store.pages():
        if rel.startswith(f"{THINGS}/"):
            raw = (library.store.root / rel).read_text(encoding="utf-8")
            marker = re.search(r"<!-- m4-processed:(\{.*\}) -->", raw)
            if marker:
                try:
                    data = json.loads(marker.group(1))
                    if isinstance(data, dict):
                        seen_fingerprints.update({str(k): str(v) for k, v in data.items()})
                except ValueError:
                    pass
            page = library.store.read(rel)
            for item in [*page.current, *page.history]:
                fingerprints = entry_metadata(item).get("episode_fingerprints")
                if isinstance(fingerprints, dict):
                    seen_fingerprints.update({str(k): str(v) for k, v in fingerprints.items()})
                else:
                    seen_fingerprints.update({part: "legacy" for part in item.ref.split(",") if part})
    for rel in library.store.pages():
        if not rel.startswith("经历/"):
            continue
        for entry in library.store.read(rel).current:
            if not entry.at or seen_fingerprints.get(entry.id) == _episode_fingerprint(entry):
                continue
            candidates = [*entry.trigger]
            if not candidates:
                for file in entry.files:
                    parts = Path(file.replace("\\", "/")).parts
                    if parts:
                        candidates.append(parts[1] if len(parts) > 1 else parts[0])
            seen = set()
            for candidate in candidates:
                name = safe_name(str(candidate).strip())
                if len(name) < 2 or name.casefold() in seen:
                    continue
                seen.add(name.casefold())
                groups.setdefault(name, []).append(entry)
    output = {}
    for name, entries in groups.items():
        if len({entry.id for entry in entries}) >= 2:
            output[name] = entries
    return output


async def _write_project(
    library: Any, model_mgr: Any, name: str, entries: list[Entry]
) -> tuple[list[dict[str, Any]], str]:
    if model_mgr is None or getattr(model_mgr, "model_router", None) is None:
        raise RuntimeError("没有可用的记忆整理模型")
    model_id = library._model_id(model_mgr)
    path = f"{THINGS}/{safe_name(name)}.md"
    existing = (
        (library.store.root / path).read_text(encoding="utf-8")
        if (library.store.root / path).exists()
        else ""
    )
    records = []
    for e in entries:
        records.append(
            {
                "id": e.id,
                "at": e.at,
                "text": e.text,
                "outcome": e.outcome,
                "decisions": e.decisions,
                "files": e.files,
                "commands": e.commands,
                "facts": e.facts,
                "open_items": e.open_items,
                "steps": e.steps,
                "verified": e.verified,
            }
        )
    allowed_refs = {e.id for e in entries}
    prompt = [
        {
            "role": "system",
            "content": (
                "你负责提议项目记忆变更。只根据输入经历返回 JSON："
                '{"actions":[{"action":"add|update|supersede|retract|keep",'
                '"target_id":"已有条目 ID 或空","old_text_hash":"旧文本 SHA-256 或空",'
                '"source_refs":["输入经历 ID"],"fields":{"section":"'
                + "|".join(_SECTIONS)
                + '","text":"拟写文本"},"reason":"理由"}]}。'
                "只新增有跨会话价值的信息；不要编造、升级来源等级或删除用户编辑。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"project": name, "existing_page": existing,
                 "existing_claims": [{"id": item.id, "text": item.text,
                                     "text_hash": text_hash(item.text)}
                                    for raw_line in existing.splitlines()
                                    if (item := Entry.parse(raw_line)) is not None],
                 "new_episodes": records},
                ensure_ascii=False,
            ),
        },
    ]
    result = await asyncio.wait_for(
        model_mgr.model_router.complete_for(
            model_id, "memory_library", prompt, max_tokens=2000, temperature=0.1
        ),
        timeout=float(library._cfg("writer_timeout_seconds", 90)),
    )
    text = str(getattr(result, "text", "") or "")
    actions = validate_plan(text, allowed_refs)
    return actions, existing


def _old_owner_lines(text: str) -> dict[str, list[str]]:
    result = {section: [] for section in _SECTIONS}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^#{1,3}\s*(.+?)\s*$", line)
        if heading:
            current = heading.group(1).strip()
            if current == "现在":
                current = "现在状态"
            elif current == "历史":
                current = "来龙去脉"
        elif (
            current in result
            and line.strip().startswith(("-", "*"))
            and (SRC_SAID in line or SRC_EDITED in line)
        ):
            result[current].append(line.rstrip())
    return result


def _apply_project_plan(name: str, actions: list[dict[str, Any]], existing: str,
                        entries: list[Entry], now: datetime) -> tuple[str, dict[str, Any]]:
    sections = {section: [] for section in _SECTIONS}
    section = None
    preamble = []
    parsed: dict[str, tuple[str, Entry, str]] = {}
    for raw in existing.splitlines():
        if raw.strip().startswith("<!-- m4-processed:"):
            continue
        heading = re.match(r"^#{1,3}\s*(.+?)\s*$", raw)
        if heading:
            value = heading.group(1).strip()
            if value == name:
                continue
            section = "现在状态" if value == "现在" else "来龙去脉" if value == "历史" else value
            if section not in sections:
                preamble.append(raw.rstrip())
                section = None
            continue
        if section not in sections:
            if raw.strip():
                preamble.append(raw.rstrip())
            continue
        item = Entry.parse(raw)
        if item is not None:
            parsed[item.id] = (section, item, raw.rstrip())
            sections[section].append(raw.rstrip())
        else:
            sections[section].append(raw.rstrip())
    old_hashes: dict[str, str] = {}
    applied = []
    by_id = {entry.id: entry for entry in entries}
    for action in actions:
        kind = action["action"]
        if kind == "keep":
            continue
        fields = action["fields"]
        target_id = action["target_id"]
        target = parsed.get(target_id) if target_id else None
        if kind in {"update", "supersede", "retract"}:
            if target is None:
                continue
            old_section, old_entry, old_raw = target
            if old_entry.src in {SRC_SAID, SRC_EDITED}:
                raise ValueError("proposal cannot modify a user-owned summary entry")
            current_hash = text_hash(old_entry.text)
            if current_hash != action["old_text_hash"]:
                log.warning("memory.library.proposal_stale", target_id=target_id,
                            expected_hash=action["old_text_hash"], current_hash=current_hash)
                continue
            old_hashes[target_id] = current_hash
            if kind == "retract":
                old_entry.extra_metadata["retracted"] = True
            else:
                old_entry.extra_metadata["superseded"] = True
            new_old_line = old_entry.line()
            sections[old_section] = [new_old_line if line == old_raw else line
                                     for line in sections[old_section]]
        if kind == "retract":
            continue
        text = " ".join(fields["text"].split())[:400]
        if not text:
            raise ValueError("proposal text is empty")
        source_ids = action["source_refs"]
        source_refs = [entry for ref in source_ids if (entry := by_id.get(ref)) is not None]
        if not source_refs:
            raise ValueError("proposal source reference disappeared")
        winner = source_refs[0]
        ref_values = list(dict.fromkeys(entry.id for entry in source_refs))
        new_entry = Entry(text=text, id=new_id(), src=SRC_DREAM,
                          at=now.isoformat(timespec="seconds"), ref=",".join(ref_values),
                          source_level="model_inference", recorded_at=now.isoformat(timespec="seconds"),
                          source_ref=entry_metadata(winner).get("source_ref"))
        if target_id and kind in {"update", "supersede"}:
            new_entry.supersedes = [target_id]
        new_entry.extra_metadata["proposal_reason"] = action["reason"][:500]
        new_entry.extra_metadata["proposal_action"] = kind
        new_entry.extra_metadata["source_refs"] = [
            ref for entry in source_refs
            for ref in ((entry_metadata(entry).get("source_refs") or [])
                        if isinstance(entry_metadata(entry).get("source_refs"), list)
                        else [entry_metadata(entry).get("source_ref")])
            if ref
        ]
        new_entry.extra_metadata["episode_fingerprints"] = {
            entry.id: _episode_fingerprint(entry) for entry in source_refs
        }
        sections[fields["section"]].append(new_entry.line())
        applied.append({"action": kind, "target_id": target_id, "new_id": new_entry.id,
                        "old_hash": action["old_text_hash"], "new_hash": text_hash(text),
                        "source_refs": source_ids})
    lines = [f"# {name}"]
    if preamble:
        lines.extend(["", *preamble])
    for heading in _SECTIONS:
        lines.extend(["", f"## {heading}", *sections[heading]])
    return "\n".join(lines).rstrip() + "\n", {"applied": applied, "stale": old_hashes}


def _integrate_candidates(library: Any) -> list[dict[str, Any]]:
    outcomes = []
    for rel in library.store.pages():
        page = library.store.read(rel)
        if not page.history:
            continue
        remaining = []
        changed = False
        for candidate in page.history:
            metadata = entry_metadata(candidate)
            if candidate.src != "M3候选" or candidate.why != "待 M4 整合":
                remaining.append(candidate)
                continue
            if library.store.tombstoned(tombstone_hashes(candidate.key, candidate.value, candidate.text)):
                candidate.why = "M4 墓碑阻止重导入"
                candidate.extra_metadata["consolidated"] = True
                outcomes.append({"candidate_id": candidate.id, "action": "tombstoned",
                                 "source_ref": metadata.get("source_ref"),
                                 "new_hash": text_hash(candidate.text)})
                changed = True
                continue
            source_ref = metadata.get("source_ref") or candidate.source_ref
            if not isinstance(source_ref, dict) or not source_ref.get("conversation_id") or not source_ref.get("message_uid"):
                outcomes.append({"candidate_id": candidate.id, "action": "missing_source_ref",
                                 "new_hash": text_hash(candidate.text)})
                remaining.append(candidate)
                continue
            proposal = Entry(text=candidate.text, id=candidate.id, key=candidate.key,
                             value=candidate.value, src=candidate.src, at=candidate.at,
                             until=candidate.until, quote=candidate.quote, session=candidate.session,
                             source_level=candidate.source_level, recorded_at=candidate.recorded_at,
                             valid_from=candidate.valid_from, valid_to=candidate.valid_to,
                             supersedes=candidate.supersedes, retracts=candidate.retracts,
                             source_ref=source_ref)
            candidate.src = {"user_assertion": SRC_SAID, "tool_observation": "工具观察",
                             "model_inference": SRC_DREAM}.get(candidate.source_level or "", SRC_DREAM)
            current = next((entry for entry in page.current if entry.key == candidate.key
                            and is_current_claim(entry)), None)
            old_hash = text_hash(current.text) if current is not None else None
            if current is None:
                winner = True
                resolution = {"reason": "no_existing_claim", "superseded": []}
            elif current.src == SRC_EDITED and not (
                candidate.source_level == "user_assertion"
                and (candidate.supersedes or candidate.retracts)
            ):
                winner = False
                resolution = {"reason": "manual_markdown_edit_protected"}
            else:
                decision = resolve_claim_conflict(current, proposal)
                winner = decision.get("winner_id") == candidate.id
                resolution = decision
            if winner:
                if current is not None:
                    if current.id in candidate.retracts:
                        current.extra_metadata["retracted"] = True
                        current.extra_metadata["retracted_by"] = [candidate.id]
                        candidate.why = "M4 撤回"
                        candidate.extra_metadata["consolidated"] = True
                        remaining.append(candidate)
                    else:
                        current.extra_metadata["superseded"] = True
                        current.extra_metadata["superseded_by"] = [candidate.id]
                        candidate.supersedes = list(dict.fromkeys([*candidate.supersedes, current.id]))
                        candidate.why = "M4 整合"
                        candidate.extra_metadata["consolidated"] = True
                        page.current.append(candidate)
                    remaining.append(current)
                    page.current.remove(current)
                else:
                    candidate.why = "M4 整合"
                    candidate.extra_metadata["consolidated"] = True
                    page.current.append(candidate)
                outcomes.append({"candidate_id": candidate.id, "action": "promoted",
                                 "reason": resolution.get("reason"), "source_ref": metadata.get("source_ref"),
                                 "old_hash": old_hash, "new_hash": text_hash(candidate.text)})
                changed = True
            else:
                candidate.why = "M4 未胜出，保留历史"
                candidate.extra_metadata["consolidated"] = True
                remaining.append(candidate)
                outcomes.append({"candidate_id": candidate.id, "action": "retained_history",
                                 "reason": resolution.get("reason"), "source_ref": metadata.get("source_ref"),
                                 "old_hash": old_hash, "new_hash": text_hash(candidate.text)})
                changed = True
        page.history = remaining
        if changed:
            library.store.write(page)
    return outcomes


def _overview(library: Any, now: datetime, projects: list[str]) -> str:
    path = library.store.root / "总览.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    protected = re.search(r"<!-- user:start -->(.*?)<!-- user:end -->", old, re.S)
    sections = ["# 总览", "", "## 关于你 / 主要偏好"]
    for rel in ("我.md", "现状.md", "自己.md"):
        sections.extend(f"- {entry.text}" for entry in library.store.read(rel).current[:12])
    sections.extend(["", "## 最近项目"])
    recent_projects = []
    for rel in library.store.pages():
        if not rel.startswith(f"{THINGS}/"):
            continue
        page = library.store.read(rel)
        latest = max((entry.at for entry in page.current), default="")
        recent_projects.append((latest, page.title))
    names = list(dict.fromkeys([*projects, *[name for _, name in sorted(recent_projects, reverse=True)]]))
    sections.extend(f"- [[{name}]]" for name in names[:12])
    sections.extend(["", "## 最近重要教训"])
    lessons = []
    for rel in library.store.pages():
        if rel.startswith(f"{THINGS}/"):
            lessons.extend(entry.text for entry in library.store.read(rel).current
                           if any(word in entry.text for word in ("学到", "教训", "原因", "注意")))
    sections.extend(f"- {line}" for line in lessons[:8])
    sections.extend(["", "## 记忆页"])
    sections.extend(f"- [[{Path(rel).stem}]]" for rel in library.store.pages()[:30])
    if protected:
        sections.extend(["", "<!-- user:start -->", protected.group(1).strip(), "<!-- user:end -->"])
    text = "\n".join(sections).strip() + "\n"
    return text[:1500]


async def run_dream(library: Any, model_mgr: Any = None) -> dict[str, Any]:
    library.ready()
    state_path = library.store.root / ".dream-state.json"
    checkpoint = _checkpoint(state_path)
    now = datetime.now().astimezone()
    groups = _episode_groups(library, checkpoint)
    prepared: dict[str, tuple[list[dict[str, Any]], str, list[Entry]]] = {}
    proposal_id = new_id()
    run_log: dict[str, Any] = {"proposal_id": proposal_id, "candidate_refs": {},
                               "actions": [], "files": [], "checkpoint": "unchanged",
                               "index_rebuild": "not_started"}
    try:
        for name, entries in groups.items():
            sections, existing = await _write_project(library, model_mgr, name, entries)
            prepared[name] = (sections, existing, entries)
            run_log["candidate_refs"][name] = {
                e.id: entry_metadata(e).get("source_refs", [entry_metadata(e).get("source_ref")])
                for e in entries
            }
        written: list[str] = []
        added = changed = 0
        with library.store.lock:
            for name, (sections, existing, entries) in prepared.items():
                path = library.store.root / THINGS / f"{safe_name(name)}.md"
                current_text = path.read_text(encoding="utf-8") if path.exists() else ""
                expected_hash = text_hash(existing)
                current_hash = text_hash(current_text)
                if current_hash != expected_hash:
                    log.warning("memory.library.proposal_stale_page", proposal_id=proposal_id,
                                project=name, expected_hash=expected_hash, current_hash=current_hash)
                    run_log["actions"].append({"project": name, "action": "conflict_manual_edit",
                                               "old_hash": expected_hash, "new_hash": current_hash})
                    continue
                rendered, result = _apply_project_plan(name, sections, current_text, entries, now)
                rendered = _mark_processed(rendered, entries)
                Page.parse(f"{THINGS}/{path.name}", rendered)
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".m4-tmp")
                tmp.write_text(rendered, encoding="utf-8")
                if text_hash(path.read_text(encoding="utf-8") if path.exists() else "") != current_hash:
                    tmp.unlink(missing_ok=True)
                    run_log["actions"].append({"project": name, "action": "conflict_before_replace",
                                               "old_hash": current_hash})
                    continue
                tmp.replace(path)
                written.append(name)
                added += len(result["applied"])
                changed += bool(result["applied"])
                run_log["actions"].extend(result["applied"])
                run_log["files"].append({"path": path.name, "old_hash": current_hash,
                                         "new_hash": text_hash(rendered), "write": "ok"})
                for action in sections:
                    if action["action"] == "keep" or action["fields"]["section"] != "没做完":
                        continue
                    item = " ".join(action["fields"]["text"].split())
                    deadline = _DEADLINE.search(item)
                    if deadline:
                        page = library.store.read(NOW)
                        if not any(entry.text == item for entry in page.current):
                            source = next(entry for entry in entries if entry.id == action["source_refs"][0])
                            page.current.append(Entry(text=item, id=new_id(), key=item, value=item,
                                src=SRC_DREAM, at=now.isoformat(timespec="seconds"),
                                until=deadline.group(1), ref=source.id,
                                source_level="model_inference", recorded_at=now.isoformat(timespec="seconds"),
                                source_ref=entry_metadata(source).get("source_ref")))
                            library.store.write(page)
            facts = _integrate_candidates(library)
            run_log["facts"] = facts
            overview_path = library.store.root / "总览.md"
            old_overview = overview_path.read_text(encoding="utf-8") if overview_path.exists() else ""
            new_overview = _overview(library, now, written)
            if new_overview != old_overview:
                tmp = overview_path.with_suffix(".md.m4-tmp")
                tmp.write_text(new_overview, encoding="utf-8")
                tmp.replace(overview_path)
                run_log["files"].append({"path": "总览.md", "old_hash": text_hash(old_overview),
                                         "new_hash": text_hash(new_overview), "write": "ok"})
            if library.store._git_available():
                commit_sha = library.store.commit("整理：" + "、".join(written or ["候选事实"]))
                run_log["commit"] = commit_sha or "no_changes"
                state_path.write_text(json.dumps({"checkpoint": now.isoformat(timespec="seconds"),
                                                  "proposal_id": proposal_id}, ensure_ascii=False),
                                      encoding="utf-8")
                run_log["checkpoint"] = "advanced_after_git"
            else:
                run_log["commit"] = "git_unavailable"
                run_log["checkpoint"] = "unchanged_git_unavailable"
        try:
            library.index.rebuild()
            run_log["index_rebuild"] = "ok"
        except Exception as index_exc:  # index is derived; Markdown and Git remain authoritative.
            run_log["index_rebuild"] = "failed"
            log.warning("memory.library.dream_index_rebuild_failed", error=str(index_exc))
        log.info("memory.library.consolidation", **run_log)
        return {"ok": True, "projects": written, "added": added, "changed": changed,
                "proposal_id": proposal_id, "log": run_log, "error": None}
    except Exception as exc:  # noqa: BLE001 - any failed phase must leave the checkpoint unchanged.
        run_log["error"] = str(exc)
        log.warning("memory.library.dream_failed", error=str(exc), error_type=type(exc).__name__,
                    proposal_id=proposal_id, consolidation=run_log)
        return {"ok": False, "projects": [], "added": 0, "changed": 0,
                "proposal_id": proposal_id, "log": run_log, "error": str(exc)}


__all__ = ["run_dream"]
