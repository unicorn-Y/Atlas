"""E6 技能自学/整理桥（概念移植自 hermes ``agent/curator.py`` + ``agent/background_review.py``）。

从 Hermes 借来的**概念**（不 import 其代码）：

- 候选技能（candidate）来自三类确定性来源：重复成功运行、用户“保存为技能”、
  X2 录制包（recording bundle）；背景审查/整理永不直接动正式技能库。
- 整理员（curator）不变量：**只归档/标记，从不删除**；置顶（pinned）跳过一切自动状态迁移；
  去重合并时保留来源与历史（provenance）；按版本出处（source_version）标记过期。

候选以结构化 JSON 落盘 ``<data>/evolution/candidates/<id>.json``；``approve`` 返回
技能包 dict（交给统一 SkillManager 的接线方，本模块**不 import** ``atlas.skills``）。
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

#: 候选来源（a 重复成功运行 / b 用户保存 / c X2 录制包）。
ORIGINS = ("successful_run", "repeated_runs", "user_request", "recording_bundle")
STATUSES = ("candidate", "approved", "rejected", "stale", "merged", "rolled_back")

#: (a) 重复成功运行的默认门槛：至少 N 次成功才生成候选。
DEFAULT_MIN_RUNS = 3
#: 整理员默认“过期”天数（未被使用/更新的候选标记 stale，不删除）。
DEFAULT_STALE_AFTER_DAYS = 30


def candidates_dir() -> Path:
    from atlas.evolution.watcher import evolution_root

    return evolution_root() / "candidates"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return slug or "skill"


def _version_key(version: str) -> tuple:
    """版本比较键：数字段按整数，其他段按字符串。"""
    parts = re.split(r"[.\-+]", str(version))
    return tuple((int(p), "") if p.isdigit() else (-1, p) for p in parts)


class SkillCurator:
    """候选技能的创建 / 审批 / 整理（全部确定性，无模型调用）。"""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory else candidates_dir()

    # -- io --

    def _path(self, candidate_id: str) -> Path:
        return self.directory / f"{_slug(candidate_id)}.json"

    def list(self) -> list[dict[str, Any]]:
        if not self.directory.is_dir():
            return []
        records = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("evolution.candidates.corrupt", path=str(path))
                continue
            if isinstance(data, dict):
                records.append(data)
        records.sort(key=lambda r: str(r.get("updated_at")), reverse=True)
        return records

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        path = self._path(candidate_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _save(self, record: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(str(record["id"]))
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    # -- 创建（三类来源，同名自动合并去重） --

    def create_candidate(
        self,
        *,
        name: str,
        description: str,
        origin: str,
        references: list[str] | None = None,
        assets: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
        source_runs: list[str] | None = None,
        run_count: int | None = None,
        source_version: str | None = None,
        candidate_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """创建（或合并）候选技能。同名候选合并：引用/资产取并集，运行数累加。"""
        if origin not in ORIGINS:
            raise ValueError(f"origin 只支持 {'/'.join(ORIGINS)}")
        now = now or _now()
        candidate_id = _slug(candidate_id or name)
        existing = self.get(candidate_id)
        if existing and existing.get("status") == "merged":
            existing = self.get(existing.get("merged_into") or candidate_id)
        runs = list(dict.fromkeys(source_runs or []))
        if existing and existing.get("status") != "rejected":
            record = dict(existing)
            record["references"] = list(dict.fromkeys(
                [*record.get("references", []), *(references or [])]))
            record["assets"] = list(dict.fromkeys(
                [*record.get("assets", []), *(assets or [])]))
            merged_params = dict(record.get("parameters") or {})
            merged_params.update(parameters or {})
            record["parameters"] = merged_params
            record["source_runs"] = list(dict.fromkeys(
                [*record.get("source_runs", []), *runs]))
            record["use_count"] = (
                int(record.get("use_count") or 0) + int(run_count or len(runs) or 1))
            history = list(record.get("provenance", {}).get("history", []))
            history.append({"at": _iso(now), "action": "merged", "origin": origin,
                            "source_version": source_version})
            record.setdefault("provenance", {})
            record["provenance"]["history"] = history
            if source_version:
                record["provenance"]["source_version"] = source_version
            record["provenance"]["updated_at"] = _iso(now)
            if record.get("status") == "stale":  # 再次出现即复活（curator reactivated 概念）
                record["status"] = "candidate"
                history.append({"at": _iso(now), "action": "reactivated"})
            record["updated_at"] = _iso(now)
            record["_merged"] = True
            self._save(record)
            return record

        record = {
            "id": candidate_id,
            "name": name,
            "description": description,
            "origin": origin,
            "status": "candidate",
            "references": list(dict.fromkeys(references or [])),
            "assets": list(dict.fromkeys(assets or [])),
            "parameters": dict(parameters or {}),
            "source_runs": runs,
            "use_count": int(run_count if run_count is not None else len(runs)),
            "pinned": False,
            "last_used_at": None,
            "provenance": {
                "source_version": source_version,
                "created_at": _iso(now),
                "updated_at": _iso(now),
                "history": [{"at": _iso(now), "action": "created", "origin": origin,
                             "source_version": source_version}],
            },
            "created_at": _iso(now),
            "updated_at": _iso(now),
            "approved_at": None,
        }
        self._save(record)
        return record

    def create_candidate_from_conversation(
        self, *, conversation_id: str, run_id: str, user_text: str,
        assistant_text: str, name: str | None = None, project_id: str | None = None,
        agent_id: str | None = None, now: datetime | None = None,
    ) -> dict[str, Any]:
        """Create a reviewable skill from one successful conversation turn.

        Transcript excerpts are stored in the local candidate for review and
        rollback provenance; they are never included in application logs.
        """
        from atlas.engine_core.agent.redact import redact_sensitive_text

        goal = " ".join(redact_sensitive_text(str(user_text or ""), force=True).split())[:4000]
        outcome = "\n".join(redact_sensitive_text(
            str(assistant_text or ""), force=True).splitlines()).strip()[:6000]
        if not goal or not outcome:
            raise ValueError("当前运行缺少完整的用户目标或成功结果，无法提炼技能")
        title = " ".join(str(name or "").split()).strip() or goal[:48].rstrip(" ，。:：")
        skill_name = _slug(title)
        if skill_name == "skill":
            skill_name = f"conversation-{_slug(run_id)}"[:64].strip("-") or "conversation-skill"
        steps = [f"处理用户目标：{goal}", "复用成功运行记录中的方法与结果：", outcome]
        parameters: dict[str, Any] = {
            "steps": steps,
            "project_id": str(project_id or ""),
            "agent_id": str(agent_id or ""),
        }
        record = self.create_candidate(
            name=skill_name,
            description="从成功会话提炼的技能草案，请审核后再加入技能库。",
            origin="successful_run",
            references=[f"conversation:{conversation_id}"],
            parameters=parameters,
            source_runs=[str(run_id)],
            run_count=1,
            candidate_id=f"run-{_slug(run_id)}",
            now=now,
        )
        record["title"] = title
        self._save(record)
        return record

    def create_candidate_from_runs(
        self, *, name: str, description: str, run_results: list[dict[str, Any]],
        references: list[str] | None = None, min_runs: int = DEFAULT_MIN_RUNS,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """来源 (a)：重复成功运行。成功次数 < ``min_runs`` 时返回 None（不生成候选）。"""
        successful = [r for r in run_results if r.get("success")]
        if len(successful) < min_runs:
            return None
        return self.create_candidate(
            name=name, description=description, origin="repeated_runs",
            references=references,
            source_runs=[str(r.get("run_id")) for r in successful if r.get("run_id")],
            run_count=len(successful), now=now,
        )

    def create_candidate_from_recording(
        self, bundle: dict[str, Any], now: datetime | None = None,
    ) -> dict[str, Any]:
        """来源 (c)：X2 录制包。字段缺省安全，全部进入候选结构。"""
        return self.create_candidate(
            name=str(bundle.get("name") or "未命名录制技能"),
            description=str(bundle.get("description") or "来自 X2 录制包的候选技能"),
            origin="recording_bundle",
            references=[str(r) for r in (bundle.get("references") or [])],
            assets=[str(a) for a in (bundle.get("assets") or [])],
            parameters={"steps": list(bundle.get("steps") or []),
                        **(bundle.get("parameters") or {})},
            source_version=bundle.get("recording_version"),
            now=now,
        )

    # -- 审批 --

    def approve(self, candidate_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        """批准候选 → 返回交给统一 SkillManager 的技能包 dict（本模块不落技能库）。"""
        record = self.get(candidate_id)
        if record is None:
            raise ValueError(f"未找到候选技能：{candidate_id}")
        if record.get("status") == "rejected":
            raise ValueError("候选已被拒绝；请重新创建后再批准")
        now = now or _now()
        record["status"] = "approved"
        record["approved_at"] = _iso(now)
        record["updated_at"] = _iso(now)
        history = list(record.get("provenance", {}).get("history", []))
        history.append({"at": _iso(now), "action": "approved"})
        record.setdefault("provenance", {})["history"] = history
        self._save(record)
        return self.to_skill_bundle(record, now=now)

    def reject(
        self, candidate_id: str, *, reason: str = "", now: datetime | None = None,
    ) -> dict[str, Any]:
        """拒绝候选：只改状态并记录原因，文件保留（curator 从不删除）。"""
        record = self.get(candidate_id)
        if record is None:
            raise ValueError(f"未找到候选技能：{candidate_id}")
        now = now or _now()
        record["status"] = "rejected"
        record["updated_at"] = _iso(now)
        history = list(record.get("provenance", {}).get("history", []))
        history.append({"at": _iso(now), "action": "rejected", "reason": reason})
        record.setdefault("provenance", {})["history"] = history
        self._save(record)
        return record

    def mark_rolled_back(self, candidate_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        """Mark an approved candidate after its registered skill was rolled back."""
        record = self.get(candidate_id)
        if record is None:
            raise ValueError(f"未找到候选技能：{candidate_id}")
        if record.get("status") != "approved":
            raise ValueError("只有已批准的候选技能可以回滚")
        now = now or _now()
        record["status"] = "rolled_back"
        record["updated_at"] = _iso(now)
        history = list(record.get("provenance", {}).get("history", []))
        history.append({"at": _iso(now), "action": "rolled_back"})
        record.setdefault("provenance", {})["history"] = history
        self._save(record)
        return record

    @staticmethod
    def to_skill_bundle(
        record: dict[str, Any], *, now: datetime | None = None,
    ) -> dict[str, Any]:
        """候选 → 技能包（SKILL.md 风格 instructions + 结构化字段）。"""
        now = now or _now()
        steps = list((record.get("parameters") or {}).get("steps") or [])
        step_lines = (
            "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)) or "（按 parameters 定义）")
        ref_lines = "\n".join(f"- {r}" for r in record.get("references", [])) or "-（无）"
        instructions = "\n".join([
            f"# {record.get('title') or record['name']}",
            "",
            str(record.get("description") or ""),
            "",
            "## 步骤",
            step_lines,
            "",
            "## 参考",
            ref_lines,
        ])
        provenance = record.get("provenance") or {}
        return {
            "name": record["name"],
            "description": record.get("description") or "",
            "instructions": instructions,
            "references": list(record.get("references", [])),
            "assets": list(record.get("assets", [])),
            "parameters": dict(record.get("parameters") or {}),
            "metadata": {
                "origin": record.get("origin"),
                "source_runs": list(record.get("source_runs", [])),
                "use_count": record.get("use_count"),
                "version": provenance.get("source_version"),
                "approved_at": record.get("approved_at") or _iso(now),
                "curator": "atlas-evolution",
            },
        }

    # -- 整理（dedupe / merge / flag-stale，从不删除） --

    def maintain(
        self,
        *,
        known_versions: dict[str, str] | None = None,
        now: datetime | None = None,
        stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    ) -> dict[str, int]:
        """整理员维护：同名去重合并、按版本出处标过期、按闲置标 stale。置顶项跳过。"""
        now = now or _now()
        counts = {"checked": 0, "merged": 0, "flagged_stale": 0, "flagged_outdated": 0,
                  "reactivated": 0}
        records = sorted(
            self.list(), key=lambda r: (str(r.get("created_at")), str(r.get("id"))))
        by_name: dict[str, dict[str, Any]] = {}
        for record in records:  # 最早创建的当主记录，其余并入它（保留出处，不删除文件）
            key = str(record.get("name", "")).lower()
            primary = by_name.get(key)
            if primary is None:
                by_name[key] = record
            else:
                self._merge_pair(primary, record, now, counts)

        stale_cutoff = now - timedelta(days=stale_after_days)
        for record in self.list():
            counts["checked"] += 1
            if record.get("pinned") or record.get("status") in ("rejected", "merged"):
                continue
            history = list(record.get("provenance", {}).get("history", []))
            # 按版本出处标过期：上游/录制已出更新版本。
            version = (record.get("provenance") or {}).get("source_version")
            known = (known_versions or {}).get(str(record.get("name")))
            if version and known and _version_key(known) > _version_key(str(version)):
                record["outdated"] = True
                history.append({"at": _iso(now), "action": "flagged_outdated",
                                "known_version": known})
                counts["flagged_outdated"] += 1
            # 按闲置标 stale：候选期且太久没有活动；重新出现会复活（见 create_candidate）。
            anchor = (_parse_iso(record.get("last_used_at"))
                      or _parse_iso(record.get("updated_at"))
                      or _parse_iso(record.get("created_at")))
            if record.get("status") == "candidate" and anchor and anchor < stale_cutoff:
                record["status"] = "stale"
                history.append({"at": _iso(now), "action": "flagged_stale"})
                counts["flagged_stale"] += 1
            record.setdefault("provenance", {})["history"] = history[-50:]
            self._save(record)
        return counts

    def _merge_pair(self, primary: dict[str, Any], other: dict[str, Any],
                    now: datetime, counts: dict[str, int]) -> dict[str, Any]:
        """把 ``other`` 并进 ``primary``；``other`` 标记 merged（保留文件，不删除）。"""
        primary["references"] = list(dict.fromkeys(
            [*primary.get("references", []), *other.get("references", [])]))
        primary["assets"] = list(dict.fromkeys(
            [*primary.get("assets", []), *other.get("assets", [])]))
        params = dict(primary.get("parameters") or {})
        params.update(other.get("parameters") or {})
        primary["parameters"] = params
        primary["source_runs"] = list(dict.fromkeys(
            [*primary.get("source_runs", []), *other.get("source_runs", [])]))
        primary["use_count"] = int(primary.get("use_count") or 0) + int(other.get("use_count") or 0)
        primary["updated_at"] = _iso(now)
        history = list(primary.get("provenance", {}).get("history", []))
        history.append({"at": _iso(now), "action": "merged_duplicate",
                        "absorbed": other.get("id")})
        primary.setdefault("provenance", {})["history"] = history
        self._save(primary)

        other["status"] = "merged"
        other["merged_into"] = primary.get("id")
        other["updated_at"] = _iso(now)
        self._save(other)
        counts["merged"] += 1
        return primary

    # -- 便捷 --

    def mark_used(self, candidate_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        """技能被使用时回写（curator 依据 last_used_at 判 stale）。"""
        record = self.get(candidate_id)
        if record is None:
            return None
        now = now or _now()
        record["last_used_at"] = _iso(now)
        record["use_count"] = int(record.get("use_count") or 0) + 1
        record["updated_at"] = _iso(now)
        if record.get("status") == "stale":
            record["status"] = "approved" if record.get("approved_at") else "candidate"
        self._save(record)
        return record


def get_curator() -> SkillCurator:
    return SkillCurator()
