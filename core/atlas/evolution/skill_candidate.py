"""Build provenance-checked skill candidates from M3 Markdown experiences.

Candidate files are rebuildable derivatives. The only accepted input is an
episode entry already stored by the memory library; this module never reads
SessionDB or stores transcript text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import yaml

from atlas.memory.library.store import EPISODES, Entry, MemoryStore

_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FAILURE = re.compile(r"失败|未完成|无法|错误|报错|failed|failure|error|not completed", re.I)


@dataclass(frozen=True)
class Experience:
    experience_id: str
    source_refs: tuple[dict[str, Any], ...]
    source_level: str
    recorded_at: str
    task: str
    outcome: str
    verified: bool
    steps: tuple[str, ...]
    files: tuple[str, ...]
    commands: tuple[str, ...]
    open_items: tuple[str, ...]
    errors: tuple[str, ...]
    summary: str

    def as_input(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "source_ref": list(self.source_refs),
            "source_level": self.source_level,
            "recorded_at": self.recorded_at,
            "task": self.task,
            "outcome": self.outcome,
            "verified": self.verified,
            "steps": list(self.steps),
            "files": list(self.files),
            "commands": list(self.commands),
            "open_items": list(self.open_items),
            "errors": list(self.errors),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class SkillCandidate:
    name: str
    description: str
    applicability: tuple[str, ...]
    prerequisites: tuple[str, ...]
    steps: tuple[dict[str, Any], ...]
    verification: tuple[str, ...]
    counterexamples: tuple[dict[str, Any], ...]
    recovery: tuple[dict[str, Any], ...]
    evidence_ids: tuple[str, ...]
    source_refs: tuple[dict[str, Any], ...]
    version: str = "0.1.0"

    def as_markdown(self) -> str:
        frontmatter = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "triggers": [],
            "metadata": {
                "atlas_memory_skill": True,
                "source_experience_ids": list(self.evidence_ids),
                "source_refs": list(self.source_refs),
                "candidate_status": "candidate",
            },
        }
        body = ["# " + self.name.replace("-", " ").title(), "", self.description, ""]
        for title, values in (("适用条件", self.applicability), ("前置条件", self.prerequisites)):
            if values:
                body.extend([f"## {title}", *[f"- {value}" for value in values], ""])
        body.extend(["## 步骤"])
        for index, step in enumerate(self.steps, 1):
            refs = ", ".join(step["experience_ids"])
            body.append(f"{index}. {step['instruction']}（来源经历：{refs}）")
            for command in step.get("commands", []):
                body.append(f"   命令：`{command}`")
        if self.verification:
            body.extend(["", "## 验证", *[f"- {item}" for item in self.verification]])
        if self.counterexamples:
            body.extend(["", "## 反例与边界"])
            body.extend(f"- {item['case']}（来源经历：{', '.join(item['experience_ids'])}）"
                        for item in self.counterexamples)
        if self.recovery:
            body.extend(["", "## 失败恢复"])
            body.extend(f"- {item['action']}（来源经历：{', '.join(item['experience_ids'])}）"
                        for item in self.recovery)
        return ("---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).rstrip()
                + "\n---\n\n" + "\n".join(body).rstrip() + "\n")


def experience_from_entry(entry: Entry, metadata: dict[str, Any] | None = None) -> Experience | None:
    metadata = metadata or entry.meta()
    details = metadata.get("episode_details") if isinstance(metadata.get("episode_details"), dict) else {}
    refs = metadata.get("source_refs") or details.get("source_refs") or []
    if not refs and isinstance(metadata.get("source_ref"), dict):
        refs = [metadata["source_ref"]]
    refs = tuple(ref for ref in refs if isinstance(ref, dict) and
                 ref.get("conversation_id") and ref.get("message_uid"))
    if not entry.id or not refs or not entry.outcome.strip():
        return None
    summary = str(metadata.get("episode_summary") or details.get("summary") or entry.text)
    decisions = details.get("decisions") or entry.decisions
    steps = tuple(str(item.get("text") if isinstance(item, dict) else item).strip()
                  for item in [*decisions, *entry.steps] if str(item).strip())
    return Experience(
        experience_id=entry.id,
        source_refs=refs,
        source_level=str(metadata.get("source_level") or entry.source_level or "legacy_unknown"),
        recorded_at=str(metadata.get("recorded_at") or entry.recorded_at or entry.at),
        task=entry.text.split("：", 1)[0].strip(),
        outcome=entry.outcome.strip(),
        verified=bool(entry.verified),
        steps=steps,
        files=tuple(str(v) for v in details.get("files", entry.files) if str(v).strip()),
        commands=tuple(str(v) for v in details.get("commands", entry.commands) if str(v).strip()),
        open_items=tuple(str(v) for v in details.get("unfinished", entry.open_items) if str(v).strip()),
        errors=tuple(str(v) for v in details.get("errors", metadata.get("errors", [])) if str(v).strip()),
        summary=summary.strip(),
    )


def read_experiences(store: MemoryStore, *, limit: int = 120) -> list[Experience]:
    """Read recent M3 experience metadata, newest first, without opening source text."""
    experiences: list[Experience] = []
    for rel in reversed(store.pages()):
        if not rel.startswith(EPISODES + "/"):
            continue
        page = store.read(rel)
        for entry in reversed(page.current):
            item = experience_from_entry(entry)
            if item:
                experiences.append(item)
                if len(experiences) >= max(1, limit):
                    return experiences
    return experiences


def _decode_response(response: str) -> dict[str, Any]:
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("候选必须是 JSON object")
    return value


def validate_candidate(raw: dict[str, Any], experiences: list[Experience]) -> SkillCandidate:
    by_id = {item.experience_id: item for item in experiences}
    name = str(raw.get("name") or "").strip()
    description = str(raw.get("description") or "").strip()
    evidence_ids = tuple(dict.fromkeys(str(v) for v in raw.get("evidence_ids", []) if str(v) in by_id))
    if not _NAME.fullmatch(name) or not description:
        raise ValueError("技能名或描述格式无效")
    if len(evidence_ids) < 2:
        raise ValueError("候选至少需要两条不同经历证据")
    successful = [by_id[key] for key in evidence_ids
                  if by_id[key].verified and by_id[key].outcome and not _FAILURE.search(by_id[key].outcome)]
    if len(successful) < 2:
        raise ValueError("候选至少需要两条有成功证据且已验证的经历")
    if not _repeated_workflow(successful):
        raise ValueError("证据经历未显示同一操作重复发生")
    ids = set(evidence_ids)
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("候选必须包含 steps")
    clean_steps: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict) or not str(step.get("instruction") or "").strip():
            raise ValueError("步骤缺少 instruction")
        refs = tuple(dict.fromkeys(str(v) for v in step.get("experience_ids", []) if str(v) in ids))
        if not refs:
            raise ValueError("每个步骤必须引用至少一条经历")
        commands = tuple(str(v) for v in step.get("commands", []) if str(v).strip())
        supported = {command for key in refs for command in by_id[key].commands}
        if any(command not in supported for command in commands):
            raise ValueError("步骤含来源经历未记录的命令")
        clean_steps.append({"instruction": str(step["instruction"]).strip(),
                            "experience_ids": list(refs), "commands": list(commands)})
    counterexamples = _validated_examples(raw.get("counterexamples", []), ids, "case")
    recovery = _validated_examples(raw.get("recovery", []), ids, "action")
    refs = tuple(ref for key in evidence_ids for ref in by_id[key].source_refs)
    source_refs = tuple({"conversation_id": r["conversation_id"], "message_uid": r["message_uid"],
                         **{k: v for k, v in r.items() if k not in ("conversation_id", "message_uid")}}
                        for r in refs)
    return SkillCandidate(
        name=name, description=description,
        applicability=_strings(raw.get("applicability")),
        prerequisites=_strings(raw.get("prerequisites")),
        steps=tuple(clean_steps), verification=_strings(raw.get("verification")),
        counterexamples=tuple(counterexamples), recovery=tuple(recovery),
        evidence_ids=evidence_ids, source_refs=source_refs,
    )


def _repeated_workflow(experiences: list[Experience]) -> bool:
    for index, left in enumerate(experiences):
        left_task = re.sub(r"[^\w]+", "", left.task.casefold())
        left_terms = {term for term in re.findall(r"[\w]+", left.task.casefold()) if len(term) > 2}
        for right in experiences[index + 1:]:
            right_task = re.sub(r"[^\w]+", "", right.task.casefold())
            if left_task and left_task == right_task:
                return True
            if set(left.commands) & set(right.commands) or set(left.files) & set(right.files):
                return True
            right_terms = {term for term in re.findall(r"[\w]+", right.task.casefold()) if len(term) > 2}
            union = left_terms | right_terms
            if union and len(left_terms & right_terms) / len(union) >= 0.5:
                return True
    return False


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in value if str(item).strip()) if isinstance(value, list) else ()


def _validated_examples(value: Any, ids: set[str], field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    results = []
    for item in value:
        if not isinstance(item, dict) or not str(item.get(field) or "").strip():
            continue
        refs = list(dict.fromkeys(str(v) for v in item.get("experience_ids", []) if str(v) in ids))
        if refs:
            results.append({field: str(item[field]).strip(), "experience_ids": refs})
    return results


async def build_candidate(model_router: Any, model_id: str,
                          experiences: list[Experience], *,
                          existing_skills: list[dict[str, str]] | None = None) -> SkillCandidate:
    """Ask Atlas' configured model for a candidate; allow one schema-correction retry."""
    eligible = [item for item in experiences if item.outcome and item.source_refs]
    eligible = eligible[:20]
    successful = [item for item in eligible if item.verified and not _FAILURE.search(item.outcome)]
    if len({item.experience_id for item in successful}) < 2:
        raise ValueError("最近二十条经历中至少需要两条不同的已验证成功经历")
    data = [item.as_input() for item in eligible]
    existing = (existing_skills or [])[:30]
    prompt = (
        "你是 Atlas 技能提炼器。仅根据输入经历归纳一个反复出现的操作流程，返回 JSON object。"
        "字段为 name(kebab-case), description, applicability[], prerequisites[], "
        "steps:[{instruction,experience_ids[],commands[]}], verification[], "
        "counterexamples:[{case,experience_ids[]}], recovery:[{action,experience_ids[]}], "
        "evidence_ids[]。至少引用两条不同的成功经历；错误或未完成经历只能作为反例。"
        "每一步必须引用支持它的经历 ID。commands 只能逐字取自对应经历记录的 commands。"
        "反例/失败恢复只能引用失败或未完成经历。不得编造输入材料没有支持的操作指导、命令、工具参数或安全规则。"
        "生活偏好本身不是技能。若现有技能已覆盖相同流程，复用其 name 并给出改进后的完整版本，不能新建重复技能。\n"
        "现有技能索引：\n" + json.dumps(existing, ensure_ascii=False) + "\n"
        "经历：\n" + json.dumps(data, ensure_ascii=False)
    )
    last_error = ""
    for attempt in range(2):
        result = await model_router.complete_for(model_id, "memory_library", prompt,
                                                 max_tokens=3200, temperature=0.1)
        response = str(getattr(result, "text", "") or "")
        try:
            return validate_candidate(_decode_response(response), eligible)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if attempt == 0:
                prompt += ("\n上次输出未通过校验，错误：" + last_error +
                           "。只修复该错误并重发完整 JSON，不要增加无证据内容。")
    raise ValueError("候选格式/出处校验两次失败：" + last_error)


def score_candidate(report: Any, *, gate_mode: str, safety_blockers: int | None = None,
                    correctness_blockers: int | None = None) -> dict[str, Any]:
    """Fail closed unless the enabled heldout aggregate strictly beats baseline."""
    baseline = getattr(report, "baseline_score", None)
    candidate = getattr(report, "candidate_score", None)
    task_count = int(getattr(report, "n_tasks", 0) or 0)
    try:
        strict_gain = baseline is not None and candidate is not None and float(candidate) > float(baseline)
    except (TypeError, ValueError):
        strict_gain = False
    report_safety = getattr(report, "safety_blockers", 0)
    report_correctness = getattr(report, "correctness_blockers", 0)
    safety_blockers = int(report_safety or 0) if safety_blockers is None else safety_blockers
    correctness_blockers = (int(report_correctness or 0) if correctness_blockers is None
                            else correctness_blockers)
    raw_blockers = getattr(report, "blockers", None) or getattr(report, "gate_blockers", None) or []
    if isinstance(raw_blockers, dict):
        generic_blockers = [str(key) for key, value in raw_blockers.items() if value]
    elif isinstance(raw_blockers, (list, tuple, set)):
        generic_blockers = [str(item) for item in raw_blockers]
    else:
        generic_blockers = [str(raw_blockers)] if raw_blockers else []
    has_generic_blockers = bool(generic_blockers)
    enabled = str(gate_mode).lower() in {"on", "true", "1", "enabled"}
    passed = bool(enabled and getattr(report, "accepted", False) and task_count >= 2 and strict_gain
                  and safety_blockers == 0 and correctness_blockers == 0 and not has_generic_blockers)
    return {"gate_mode": "on" if enabled else "off", "passed": passed,
            "baseline_score": baseline, "candidate_score": candidate,
            "task_count": task_count, "safety_blockers": safety_blockers,
            "correctness_blockers": correctness_blockers, "other_blockers": generic_blockers,
            "reason": "strict_aggregate_improvement" if passed else "gate_not_satisfied"}


__all__ = ["Experience", "SkillCandidate", "build_candidate", "experience_from_entry",
           "read_experiences", "score_candidate", "validate_candidate"]
