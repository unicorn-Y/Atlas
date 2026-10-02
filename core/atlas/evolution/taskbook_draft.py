"""E4 任务书草稿生成（只产 ``*.draft.md`` 草稿，绝不直接改代码）。

对 E3 里 ``UPGRADE`` / ``REPLACE`` 且 ``advisory`` 的建议行，各生成一份草稿：

``<PROJECT>/tasks/taskbooks/ATLAS-AUTO-<YYYYMMDD>-<slug>.draft.md``

内容固定四段：来源（repo/引用/相关文件）、Atlas 集成点、可能改动文件、聚焦验收标准。
元数据落在 ``<data>/evolution/drafts.json``（branch_flow 批准时读它）。
草稿只是草稿：批准走 E5 的隔离分支流程，永远不自动合并 main。
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from atlas.evolution.parity_mapper import build_parity_rows

DRAFT_PREFIX = "ATLAS-AUTO"

#: 能力 → Atlas 侧可能触碰的文件（确定性映射；未列出的给通用占位）。
LIKELY_FILES: dict[str, list[str]] = {
    "L2": ["core/atlas/agent/*（恢复链）", "core/tests/test_c1_recovery.py"],
    "L4": ["core/atlas/agent/*（停止闸门）", "core/tests/test_c1_stop_gate.py"],
    "X1": ["core/atlas/agent/*（压缩）", "core/atlas/agent/enrichment.py"],
    "T1": ["core/atlas/engine/*（文件工具桥）"],
    "T5": ["core/atlas/engine/*（patch 工具桥）"],
    "T9": ["core/atlas/engine/*（搜索工具桥）"],
    "T17": ["core/atlas/engine/*（工具注册表）"],
    "A1": ["core/atlas/agent/*（子代理）", "core/tests/test_c1_lifecycle_subtask.py"],
    "E1": ["core/atlas/engine/*（MCP 桥）"],
    "E2": ["core/atlas/skills/*（由技能集成方对接）"],
    "M2": ["core/atlas/models/*（凭据池）"],
    "P2": ["core/atlas/review/*", "core/tests/test_c6_review.py"],
}


def drafts_root() -> Path:
    """草稿目录：``<PROJECT>/tasks/taskbooks``。"""
    from atlas.config import PROJECT_ROOT

    return PROJECT_ROOT / "tasks" / "taskbooks"


def evolution_meta_dir() -> Path:
    """drafts.json 所在目录（与 watcher 的 evolution_root 一致）。"""
    from atlas.evolution.watcher import evolution_root

    return evolution_root()


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug or "update"


def _index_path(root: Path | None = None) -> Path:
    return (root or evolution_meta_dir()) / "drafts.json"


def load_index(root: Path | None = None) -> dict[str, Any]:
    try:
        data = json.loads(_index_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"drafts": {}}
    return data if isinstance(data, dict) and "drafts" in data else {"drafts": {}}


def save_index(index: dict[str, Any], root: Path | None = None) -> None:
    path = _index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def draft_id_for(row: dict[str, Any], generated_on: date) -> str:
    """``ATLAS-AUTO-<YYYYMMDD>-<capability>-<source>``。"""
    slug = _slug(f"{row.get('capability_id') or 'cap'}-{row.get('source') or row.get('repo')}")
    return f"{DRAFT_PREFIX}-{generated_on.strftime('%Y%m%d')}-{slug}"


def render_draft_markdown(row: dict[str, Any], generated_on: date) -> str:
    """固定四段结构的草稿正文（中文）。"""
    capability_id = row.get("capability_id") or "?"
    files = LIKELY_FILES.get(capability_id, ["core/atlas/（按集成点定位）"])
    repo = row.get("repo") or row.get("source") or "上游仓库"
    repo_file = row.get("repo_file") or "（见上游对应改动）"
    ref = row.get("ref") or "最新"
    suggestion = row.get("suggestion") or "UPGRADE"
    slug = _slug(f"{capability_id}-{row.get('source') or repo}")
    lines = [
        f"# {DRAFT_PREFIX}-{generated_on.strftime('%Y%m%d')}-{slug}.draft",
        "",
        "状态：草稿（自动追新生成，未批准）。",
        "批准后在隔离分支 `atlas-auto/…` 上施工，合并回 main 永远需要人工操作。",
        "",
        "## 来源",
        f"- 仓库：{repo}",
        f"- 引用：{ref}",
        f"- 相关文件：`{repo_file}`",
        f"- 理由：{row.get('why_stronger', '')}",
        "",
        "## Atlas 集成点",
        f"- 能力：{capability_id} {row.get('capability', '')}",
        f"- Atlas 现状：{row.get('atlas_implementation') or '（见 docs/plan/CORE-PARITY.md）'}",
        f"- 建议：{suggestion}",
        "",
        "## 可能改动文件",
        *[f"- `{f}`" for f in files],
        "",
        "## 聚焦验收标准",
        f"- [ ] 对照上游 {repo}@{ref} 完成最小实现（不整包搬，按 SOURCE-MAP 使用规则）",
        "- [ ] 按集成点补聚焦回归测试，且既有测试全部保持绿",
        "- [ ] 不回退既有行为；改动登记到 docs/plan/VENDORED.md（如涉及拷贝代码）",
        "",
    ]
    return "\n".join(lines)


def generate_drafts(
    rows: list[dict[str, Any]] | None = None,
    entries: list[dict[str, Any]] | None = None,
    *,
    root: Path | None = None,
    meta_root: Path | None = None,
    generated_on: date | None = None,
) -> list[dict[str, Any]]:
    """为可行动建议写 ``*.draft.md`` 草稿并登记索引；返回草稿记录列表。"""
    if rows is None:
        rows = build_parity_rows(entries=entries)
    today = generated_on or date.today()
    target = root or drafts_root()
    index = load_index(meta_root)
    created: list[dict[str, Any]] = []
    for row in rows:
        if row.get("suggestion") not in ("UPGRADE", "REPLACE") or not row.get("advisory", True):
            continue
        draft_id = draft_id_for(row, today)
        record = {
            "id": draft_id,
            "capability_id": row.get("capability_id"),
            "capability": row.get("capability"),
            "source": row.get("source"),
            "repo": row.get("repo"),
            "repo_file": row.get("repo_file") or "",
            "ref": row.get("ref"),
            "suggestion": row.get("suggestion"),
            "why_stronger": row.get("why_stronger", ""),
            "atlas_implementation": row.get("atlas_implementation", ""),
            "status": "draft",
            "file": str(target / f"{draft_id}.draft.md"),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "branch": None,
        }
        previous = index["drafts"].get(draft_id) or {}
        if previous.get("status") == "approved":
            record["status"] = "approved"  # 重复生成不把已批准的草稿打回草稿态
            record["branch"] = previous.get("branch")
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{draft_id}.draft.md").write_text(
            render_draft_markdown(row, today), encoding="utf-8")
        index["drafts"][draft_id] = record
        created.append(record)
    save_index(index, meta_root)
    return created


def list_drafts(meta_root: Path | None = None) -> list[dict[str, Any]]:
    """列出草稿（按 id 倒序 = 新的在前）。"""
    index = load_index(meta_root)
    drafts = sorted(index["drafts"].values(), key=lambda d: str(d.get("id")), reverse=True)
    out: list[dict[str, Any]] = []
    for draft in drafts:
        item = dict(draft)
        item["exists"] = Path(str(draft.get("file", ""))).exists() if draft.get("file") else False
        out.append(item)
    return out


def get_draft(draft_id: str, meta_root: Path | None = None) -> dict[str, Any] | None:
    index = load_index(meta_root)
    record = index["drafts"].get(draft_id)
    return dict(record) if record else None


def set_draft_status(draft_id: str, status: str, *, branch: str | None = None,
                     meta_root: Path | None = None) -> dict[str, Any] | None:
    index = load_index(meta_root)
    record = index["drafts"].get(draft_id)
    if record is None:
        return None
    record["status"] = status
    if branch is not None:
        record["branch"] = branch
    save_index(index, meta_root)
    return dict(record)
