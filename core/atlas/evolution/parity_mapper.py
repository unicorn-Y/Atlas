"""E3 CORE-PARITY 更新建议（KEEP / UPGRADE / REPLACE，只产文本提案）。

输入是 E2 的分类结果（或原始条目，内部先分类），输出：

- 行结构：``capability | source | repo/file | why stronger | Atlas 实现 | suggestion``
- :func:`render_parity_patch` 生成 CORE-PARITY 补丁**提案文本**，永远只返回字符串，
  绝不写入 ``docs/plan/``（docs/plan 对本模块只读）。

建议规则（确定性）：

- ``ALREADY_HAVE``            → KEEP（现状已覆盖）
- ``BETTER_THAN_ATLAS``       → UPGRADE（对照上游强化现有实现）
- ``NEW``                     → REPLACE（引入上游实现填补空缺）
- ``REGRESSION_REMOVED``      → KEEP 且 ``advisory=False``（上游删功能，不建议跟随）
- ``IRRELEVANT``              → 不产出行
"""

from __future__ import annotations

from datetime import date
from typing import Any

from atlas.evolution.capability_diff import (
    CAPABILITY_MAP,
    classify_entry,
)

#: 分类 → 建议动作。
SUGGESTION_BY_CLASS = {
    "ALREADY_HAVE": "KEEP",
    "BETTER_THAN_ATLAS": "UPGRADE",
    "NEW": "REPLACE",
    "REGRESSION_REMOVED": "KEEP",
}

_WHY_BY_CLASS = {
    "BETTER_THAN_ATLAS": "上游在该能力上持续强化，Atlas 现有实现偏弱，可对照吸收",
    "NEW": "Atlas 尚无该能力，上游有可直接参考/移植的实现",
    "ALREADY_HAVE": "上游更新属于该能力的常规迭代，Atlas 现状已覆盖",
    "REGRESSION_REMOVED": "上游移除/废弃了该能力相关内容；仅作情报记录",
}


def _get_capability(capability_id: str) -> dict[str, Any]:
    for capability in CAPABILITY_MAP:
        if capability["id"] == capability_id:
            return capability
    return {}


def build_parity_rows(
    diffs: list[dict[str, Any]] | None = None,
    entries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """从分类结果（或原始条目）生成 CORE-PARITY 建议行。

    行字段：``capability_id / capability / source / repo / repo_file / entry_id /
    why_stronger / atlas_implementation / suggestion / advisory / ref / url``
    """
    if diffs is None:
        diffs = [classify_entry(entry) for entry in (entries or [])]
    rows: list[dict[str, Any]] = []
    for diff in diffs:
        suggestion = SUGGESTION_BY_CLASS.get(diff["cls"])
        if suggestion is None:  # IRRELEVANT
            continue
        capability_id = (diff.get("capabilities") or [{}])[0].get("id", "")
        capability = _get_capability(capability_id)
        matched_files = diff.get("matched_files") or []
        rows.append({
            "capability_id": capability_id,
            "capability": capability.get("name") or capability_id,
            "source": diff.get("source"),
            "repo": diff.get("repo"),
            "repo_file": matched_files[0] if matched_files else "",
            "entry_id": diff.get("entry_id"),
            "ref": diff.get("entry_id"),
            "url": None,  # 由调用方按需补（条目里才有 url；这里保持行结构纯净）
            "why_stronger": diff.get("reason") or _WHY_BY_CLASS.get(diff["cls"], ""),
            "atlas_implementation": capability.get("impl", ""),
            "suggestion": suggestion,
            "advisory": bool(diff.get("advisory", True)),
        })
    return rows


def render_parity_patch(
    rows: list[dict[str, Any]], generated_on: date | None = None,
) -> str:
    """把建议行渲染成 CORE-PARITY 补丁**提案文本**（不落盘到 docs/plan）。"""
    today = (generated_on or date.today()).isoformat()
    actionable = [row for row in rows if row["suggestion"] != "KEEP" or not row["advisory"]]
    lines: list[str] = [
        f"# CORE-PARITY 补丁提案（自动生成于 {today}；未写入 docs/plan，仅供人工审阅）",
        "",
        "以下变更需要人工确认后手动修改 docs/plan/CORE-PARITY.md；本文件只是提案。",
        "",
        "*** Begin Patch",
        "*** Update File: docs/plan/CORE-PARITY.md",
    ]
    if not actionable:
        lines += ["@@（无 UPGRADE/REPLACE 建议，本轮无需改表）"]
    for row in actionable:
        cap = row.get("capability_id") or "?"
        name = row.get("capability") or ""
        repo = row.get("repo") or row.get("source") or "上游"
        repo_file = row.get("repo_file") or ""
        where = f" `{repo_file}`" if repo_file else ""
        suggestion = row["suggestion"]
        advisory = "" if row.get("advisory", True) else "（advisory=false，不建议跟随）"
        lines += [
            f"@@ {cap} {name}",
            f"- Atlas 现状：{row.get('atlas_implementation') or '（见 CORE-PARITY.md）'}",
            f"+ 建议（{suggestion}）{advisory}：参考 {repo}{where} @ {row.get('ref') or '最新'}",
            f"  理由：{row.get('why_stronger', '')}",
        ]
    lines += ["*** End Patch", ""]
    return "\n".join(lines)
