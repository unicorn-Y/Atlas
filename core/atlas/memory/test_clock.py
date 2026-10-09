"""测试时钟闸门（F3-B3）。

评测里"隔几天"的场景需要虚拟时间（比如 S27 的"三天前说的"），但**生产路径
必须永远用真实时间**。所以虚拟时钟不能是一个"传了就生效"的字段 —— 它必须
被两道锁同时把关：

1. ``event_class == "TEST"``（``ATLAS_UNIFIED_EVENT_CLASS`` 或配置
   ``memory.unified.event_class``）；
2. **隔离数据根**：``ATLAS_DATA_DIR`` 已设置且不指向仓库根（生产）。

缺一即拒，并记 warning 留痕。判定失败一律按"非隔离"（保守），宁可评测少一个
虚拟时钟，也不能让生产被一个环境变量撬开。

设计上独立成模块（而不是塞在 ``capture.py`` 里）：闸门是**准入策略**，与
"怎么采集"无关；拆开后，产品侧采集代码不必知道评测的存在。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()


def isolated_test_environment() -> bool:
    """隔离数据根判定：``ATLAS_DATA_DIR`` 已设置且不指向仓库根。

    生产（未设置，或指向 ``PROJECT_ROOT``）返回 False —— 测试时钟闸门的
    第二个必要条件，防止生产进程被一个环境变量撬开虚拟时钟。
    """
    raw = os.environ.get("ATLAS_DATA_DIR", "").strip()
    if not raw:
        return False
    try:
        from atlas.config import PROJECT_ROOT

        return Path(raw).resolve() != Path(PROJECT_ROOT).resolve()
    except Exception:  # noqa: BLE001 — 判定失败一律按非隔离（保守）
        return False


def resolve_test_clock(value: Any) -> str | None:
    """测试时钟闸门（F3-B3）：**仅当** ``event_class=TEST`` **且** 隔离数据根。

    评测里"隔几天"的场景需要虚拟时间，但生产路径必须永远用真实时间。本函数
    是唯一入口：不满足两个条件之一 → 返回 None（调用方回退真实时间），并记
    warning 留痕；值不可解析也返回 None（不猜、不夹带）。

    返回 ISO 字符串（UTC 偏移保留）；调用方把它当 ``occurred_at`` 用。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    # 延迟 import：避免 capture <-> test_clock 的模块级循环。
    from atlas.memory.capture import _configured_event_class, _load_config

    if _configured_event_class(_load_config()) != "TEST":
        log.warning("memory.test_clock_rejected", reason="event_class_not_test")
        return None
    if not isolated_test_environment():
        log.warning("memory.test_clock_rejected", reason="not_isolated_root")
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            log.warning("memory.test_clock_rejected", reason="unparsable")
            return None
    # naive 保持 naive：场景种子（`2026-10-01 10:00:00`）本来就是无时区的
    # 场景内相对时间，擅自补时区会改变语义。
    return parsed.isoformat()


__all__ = ["isolated_test_environment", "resolve_test_clock"]
