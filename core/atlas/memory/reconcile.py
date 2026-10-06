"""UNKNOWN 外部收据对账（UM06 / T06.2）。

任务书 T06.2：「重启查询运行权威和 focus 版本；UNKNOWN 外部结果先检查真实
文件/API/窗口，不重复调用具有副作用的工具。」

边界（如实登记）：

  * **确定性实现只有文件存在性检查**（``method="file_exists"``）：收据携带
    受影响路径（``path``/``paths``/``full_output_path``，或 ``evidence`` 子
    对象里的同名字段）时，对真实文件系统做 ``Path.exists()`` 检查 —— 存在则
    外部效果可观察（``OK``），全部不存在则无外部效果证据（``MISSING``）。
  * **真实 API / 窗口检查未接线（偏差）**：无路径定位的 UNKNOWN 收据返回
    ``UNRESOLVED`` 并保持 UNKNOWN 状态 —— 绝不把「无法检查」伪装成「已验证」
    或「已失败」；接线点留作后续波（checker 注册面见下方注释）。
  * 本模块是**纯读对账**：只报告真实世界观察，不重跑工具、不改运行状态 ——
    是否重跑由运行权威（Atlas/Hermes）决定；对账结果随焦点快照重提交
    （run 侧见 :mod:`atlas.memory.focus_flow`）。
  * 相对路径按 ``base_dir``（通常为运行 workspace）解析；路径不做存在性以外的
    推断（大小/内容校验属验证链路，不在本模块）。

后续波的 checker 扩展点：按 ``receipt["kind"]``（``file``/``api``/``window``）
分发到注册的确定性检查器；当前只有 file 一个实现，kind 缺省按可定位字段推断。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: 对账结论状态（UNKNOWN 保持 UNKNOWN —— 检查不了就不假装检查过）
STATUS_OK = "OK"
STATUS_MISSING = "MISSING"
STATUS_UNRESOLVED = "UNRESOLVED"

#: 已接线的确定性检查方法（真实 API/窗口检查留偏差）
WIRED_METHODS = ("file_exists",)

#: 收据里可携带受影响路径的字段（含 evidence 子对象的同名字段）
_PATH_KEYS = ("path", "paths", "full_output_path", "file")


def _candidate_paths(receipt: dict[str, Any]) -> list[str]:
    """收集收据上所有可检查的路径定位（去重，保持原顺序）。"""
    paths: list[str] = []
    for key in _PATH_KEYS:
        value = receipt.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(value.strip())
        elif isinstance(value, (list, tuple)):
            paths.extend(
                str(item).strip() for item in value
                if isinstance(item, str) and item.strip())
    evidence = receipt.get("evidence")
    if isinstance(evidence, dict):
        paths.extend(_candidate_paths(evidence))
    return list(dict.fromkeys(paths))


def _resolve(path: str, base_dir: Path | None) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute() and base_dir is not None:
        candidate = base_dir / candidate
    return candidate


def reconcile_unknown_receipt(
    receipt: dict[str, Any], *, base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """对一条 UNKNOWN 外部收据做真实世界对账（确定性文件存在性检查）。

    输入 ``receipt``：焦点 ``external_receipts`` / ``pending`` 里的一条
    （``status`` 为 UNKNOWN 的条目；非 UNKNOWN 条目原样通过、不重复检查）。

    返回（纯数据，无副作用）::

        {"receipt": <原条目>, "status": "OK"|"MISSING"|"UNRESOLVED",
         "checked": bool, "method": "file_exists"|None,
         "checked_paths": [{"path", "exists"}...], "note": str}

    语义：
      * 至少一个定位存在 → ``OK``（外部效果可观察，重跑前先看这里）；
      * 定位全部不存在 → ``MISSING``（无外部效果证据；是否重跑由运行权威决定）；
      * 无可检查定位 / 非 UNKNOWN → ``UNRESOLVED``/原状态（真实 API/窗口检查
        未接线，偏差已登记）。
    """
    base = Path(base_dir) if base_dir else None
    receipt = dict(receipt or {})
    current = str(receipt.get("status") or "").upper()
    if current and current != "UNKNOWN":
        return {"receipt": receipt, "status": current, "checked": False,
                "method": None, "checked_paths": [],
                "note": f"非 UNKNOWN 收据（{current}）不需要对账"}
    paths = _candidate_paths(receipt)
    if not paths:
        return {"receipt": receipt, "status": STATUS_UNRESOLVED,
                "checked": False, "method": None, "checked_paths": [],
                "note": ("收据无可确定性检查的定位（无 path 字段）；真实 API/"
                         "窗口检查未接线（T06.2 偏差），状态保持 UNKNOWN")}
    checked: list[dict[str, Any]] = []
    exists_any = False
    for raw in paths:
        target = _resolve(raw, base)
        try:
            found = target.exists()
        except OSError:
            found = False
        exists_any = exists_any or found
        checked.append({"path": str(target), "exists": found})
    if exists_any:
        return {"receipt": receipt, "status": STATUS_OK, "checked": True,
                "method": "file_exists", "checked_paths": checked,
                "note": "文件存在性检查：至少一个定位存在 → 外部效果可观察（OK）"}
    return {"receipt": receipt, "status": STATUS_MISSING, "checked": True,
            "method": "file_exists", "checked_paths": checked,
            "note": ("文件存在性检查：全部定位不存在 → 无外部效果证据"
                     "（MISSING）；是否重跑由运行权威决定，本函数只报告")}


def _reconcile_entry(entry: Any, base: Path | None,
                     ) -> tuple[Any, bool, bool]:
    """对单个条目对账 → (新条目, resolved?, unresolved?)。"""
    if not isinstance(entry, dict):
        return entry, False, False
    result = reconcile_unknown_receipt(entry, base_dir=base)
    if not result["checked"]:
        if str(entry.get("status") or "").upper() == "UNKNOWN":
            return entry, False, True
        return entry, False, False
    updated = dict(entry)
    updated["status"] = result["status"]
    updated["reconcile"] = {
        "method": result["method"], "checked_paths": result["checked_paths"],
        "note": result["note"],
    }
    return updated, result["status"] == STATUS_OK, False


def reconcile_focus_receipts(
    focus: dict[str, Any] | None, *, base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """焦点装配里的 UNKNOWN 外部收据批量对账（重跑前检查钩子）。

    输入：attend 装配（或其子集 ``{"external_receipts": [...],
    "pending": [...]}``）；``base_dir`` 为相对路径解析基准（运行 workspace）。

    返回 ``{"receipts", "pending", "resolved", "unresolved"}``：两个列表为
    对账后的**新列表**（UNKNOWN 条目获得 ``reconcile`` 结果字段并更新
    ``status``；无法确定性检查的保持 UNKNOWN），输入不被修改。
    """
    focus = focus or {}
    base = Path(base_dir) if base_dir else None
    resolved = unresolved = 0
    receipts: list[Any] = []
    for entry in focus.get("external_receipts") or []:
        updated, ok, stuck = _reconcile_entry(entry, base)
        receipts.append(updated)
        resolved += int(ok)
        unresolved += int(stuck)
    pending: list[Any] = []
    for entry in focus.get("pending") or []:
        updated, ok, stuck = _reconcile_entry(entry, base)
        pending.append(updated)
        resolved += int(ok)
        unresolved += int(stuck)
    return {"receipts": receipts, "pending": pending,
            "resolved": resolved, "unresolved": unresolved}
