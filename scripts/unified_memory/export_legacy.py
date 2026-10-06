"""Atlas legacy long-term memory → read-only export (UM01 / T01.2).

把 Atlas MemoryStore（SQLite）里 authority-map.json 1.0 分类为
MEMORY_AUTHORITY 的表逐表**只读导出**为 JSONL，供 MemoryOS
``import_legacy.py`` 幂等导入隔离库：

  * 每行：{table, pk, exported_at, content, content_hash, legacy_ref,
    epistemic_kind, speaker_role, facet, lifecycle, occurred_at,
    ungrounded, legacy_ungrounded}；
  * content_hash = sha256(canonical_json(content))（与 MemoryOS
    db.canonical_json 同规则：排序 key、紧凑分隔符、ensure_ascii=False）；
  * legacy_ref = ``legacy:{table}:{pk}`` —— 导入侧幂等 ID
    ``atlas:USER_IMPORT:{legacy_ref}:1:UPSERT`` 由此派生；
  * LEGACY_UNGROUNDED 规则：无证据可考的记录统一标
    ``epistemic_kind=USER_ASSERTED``（用户曾确认写入的 facts 族）或
    ``INFERRED``（goal_knowledge/反思/知识总结类），并加
    ``ungrounded=true`` + ``legacy_ungrounded=LEGACY_UNGROUNDED``；
    **禁止伪造原聊天或 VERIFIED**；
  * 已删除/失效/冲突/历史记录（memory_fact_history、commitment history、
    superseded/rejected 候选等）全部迁入并映射到统一生命周期
    （CANDIDATE/ACTIVE/SUPERSEDED/INVALIDATED/CONFLICTED）；
  * RUNTIME_AUTHORITY（conversations/messages/rewinds）不导出 —— 不迁成
    第二套运行权威。

纯同步 stdlib 脚本；sqlite3 仅以只读 URI 打开；**不得 import atlas 包**
（避免 config 副作用）。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AUTHORITY_MAP_VERSION = "1.0"
TASK_ID = "T01.2"
LEGACY_UNGROUNDED = "LEGACY_UNGROUNDED"

#: 旧状态 → 统一生命周期（与 MemoryOS service/unified/legacy.py 保持一致）
LIFECYCLE_MAP: dict[str, str] = {
    "pending": "CANDIDATE",
    "approved": "ACTIVE",
    "rejected": "INVALIDATED",
    "superseded": "SUPERSEDED",
    "conflicted": "CONFLICTED",
    "duplicate": "SUPERSEDED",
    "active": "ACTIVE",
    "fulfilled": "ACTIVE",
    "cancelled": "INVALIDATED",
}


def map_lifecycle(old_status: str | None) -> str:
    key = str(old_status or "").strip().casefold()
    return LIFECYCLE_MAP.get(key, "ACTIVE")


def canonical_json(obj: Any) -> str:
    """与 MemoryOS db.canonical_json 同规则（对账锚点，两侧必须一致）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return "b64:" + base64.b64encode(value).decode("ascii")
    return value


# ------------------------------------------------------------------ 表规格
# 与 authority-map.json 1.0 classifications 的 MEMORY_AUTHORITY 表一一对应；
# knowledge_fts（DERIVED_VIEW）等派生/审计表不导出。

class TableSpec:
    def __init__(self, name: str, pk: str, status_field: str | None,
                 text_key: str, epistemic_kind: str, facet: str,
                 literal_status: str | None = None) -> None:
        self.name = name
        self.pk = pk
        self.status_field = status_field      # 原状态列（映射统一生命周期）
        self.literal_status = literal_status  # 整表恒定旧状态（如历史表）
        self.text_key = text_key              # 主文本列（title/summary 用）
        self.epistemic_kind = epistemic_kind  # LEGACY_UNGROUNDED 规则
        self.facet = facet

    @property
    def speaker_role(self) -> str:
        return "USER" if self.epistemic_kind == "USER_ASSERTED" else "ATLAS"


LEGACY_TABLES: tuple[TableSpec, ...] = (
    # 用户曾确认写入的事实族 → USER_ASSERTED
    TableSpec("facts", "key", "commitment_status", "value",
              "USER_ASSERTED", "FACT"),
    TableSpec("memory_candidates", "id", "status", "value",
              "USER_ASSERTED", "FACT"),
    TableSpec("memory_fact_history", "id", "event_type", "value",
              "USER_ASSERTED", "FACT"),
    TableSpec("memory_commitment_history", "id", None, "key",
              "USER_ASSERTED", "COMMITMENT", literal_status="superseded"),
    # goal_knowledge / 反思 / 知识总结类 → INFERRED
    TableSpec("knowledge", "id", None, "content", "INFERRED", "KNOWLEDGE"),
    TableSpec("agent_reflections", "id", None, "summary", "INFERRED", "EPISODE"),
    TableSpec("goal_outcomes", "id", "experience_status", "goal",
              "INFERRED", "EXPERIENCE"),
    TableSpec("goal_knowledge", "id", "source_approval_status", "goal",
              "INFERRED", "KNOWLEDGE"),
    TableSpec("goal_knowledge_proposals", "id", "status", "proposed_guidance",
              "INFERRED", "KNOWLEDGE"),
    TableSpec("goal_knowledge_refinements", "id", "status", "proposed_guidance",
              "INFERRED", "KNOWLEDGE"),
)


def _facet_for(spec: TableSpec, row: dict[str, Any]) -> str:
    if spec.name in ("facts", "memory_candidates"):
        if row.get("memory_type") == "commitment":
            return "COMMITMENT"
        if str(row.get("category") or "").casefold() == "preference":
            return "PREFERENCE"
    return spec.facet


def _raw_status(spec: TableSpec, row: dict[str, Any]) -> str | None:
    if spec.literal_status is not None:
        return spec.literal_status
    if spec.status_field is None:
        return None
    return row.get(spec.status_field)


def _pick_occurred_at(row: dict[str, Any]) -> str | None:
    for key in ("created_at", "updated_at", "recorded_at", "reviewed_at"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()  # SQLite datetime('now') = UTC naive；导入侧注明 UTC
    return None


def export_row(spec: TableSpec, row: dict[str, Any], exported_at: str) -> dict[str, Any]:
    pk = row.get(spec.pk)
    legacy_ref = f"legacy:{spec.name}:{pk}"
    raw_status = _raw_status(spec, row)
    content = {
        "record": {key: _json_safe(value) for key, value in row.items()},
        "text": str(row.get(spec.text_key) or ""),
        "legacy_table": spec.name,
        "legacy_pk": pk,
        "facet": _facet_for(spec, row),
        "legacy_status": raw_status,
    }
    content_hash = "sha256:" + hashlib.sha256(
        canonical_json(content).encode("utf-8")).hexdigest()
    return {
        "table": spec.name,
        "pk": pk,
        "exported_at": exported_at,
        "content": content,
        "content_hash": content_hash,
        "legacy_ref": legacy_ref,
        "epistemic_kind": spec.epistemic_kind,
        "speaker_role": spec.speaker_role,
        "facet": content["facet"],
        "lifecycle": map_lifecycle(raw_status),
        "occurred_at": _pick_occurred_at(row),
        "ungrounded": True,
        "legacy_ungrounded": LEGACY_UNGROUNDED,
    }


def connect_readonly(db_path: str) -> sqlite3.Connection:
    """只读打开（mode=ro）：迁移绝不写旧库。"""
    uri = f"file:{Path(db_path).as_posix()}?mode=ro&immutable=0"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def export(db_path: str, out_dir: Path, subject: str,
           only_tables: set[str] | None = None) -> dict[str, Any]:
    exported_at = datetime.now(UTC).isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = connect_readonly(db_path)
    summary_tables: dict[str, Any] = {}
    total_rows = 0
    try:
        for spec in LEGACY_TABLES:
            if only_tables is not None and spec.name not in only_tables:
                continue
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (spec.name,)).fetchone()
            if existing is None:
                summary_tables[spec.name] = {"rows": 0, "exists": False,
                                             "legacy_refs": []}
                continue
            rows = [dict(r) for r in
                    conn.execute(f"SELECT * FROM {spec.name}").fetchall()]  # noqa: S608
            legacy_refs: list[str] = []
            file_hash = hashlib.sha256()
            with (out_dir / f"{spec.name}.jsonl").open("w", encoding="utf-8",
                                                       newline="\n") as handle:
                for row in rows:
                    line = export_row(spec, row, exported_at)
                    handle.write(json.dumps(line, ensure_ascii=False) + "\n")
                    file_hash.update(canonical_json(line).encode("utf-8"))
                    file_hash.update(b"\n")
                    legacy_refs.append(line["legacy_ref"])
            summary_tables[spec.name] = {
                "rows": len(rows), "exists": True,
                "file": f"{spec.name}.jsonl",
                "content_hash": "sha256:" + file_hash.hexdigest(),
                "legacy_refs": legacy_refs,
            }
            total_rows += len(rows)
    finally:
        conn.close()
    summary = {
        "schema_version": AUTHORITY_MAP_VERSION,
        "task_id": TASK_ID,
        "authority_map_version": AUTHORITY_MAP_VERSION,
        "subject": subject,
        "db": str(db_path),
        "exported_at": exported_at,
        "read_only": True,
        "grounding_rule": LEGACY_UNGROUNDED,
        "tables": summary_tables,
        "total_rows": total_rows,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, help="Atlas MemoryStore SQLite 路径（只读打开）")
    parser.add_argument("--out", required=True, help="导出目录")
    parser.add_argument("--subject", default="legacy-atlas")
    parser.add_argument("--table", action="append", default=None,
                        help="只导出指定表（可重复；默认全部 MEMORY_AUTHORITY 表）")
    args = parser.parse_args(argv)
    only = set(args.table) if args.table else None
    summary = export(args.db, Path(args.out), args.subject, only_tables=only)
    print(json.dumps({"out": args.out, "total_rows": summary["total_rows"],
                      "tables": {name: body["rows"]
                                 for name, body in summary["tables"].items()}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
