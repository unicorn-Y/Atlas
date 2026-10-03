"""Atlas Automations（W4）— 产品状态 + DBOS durable 触发/执行.

- :class:`AutomationStore`  ``data/automations.toml`` 产品状态（唯一 owner）
- :class:`AutomationEngine` DBOS 接线（cron schedule / interval 自续 / date delay /
  event-webhook dedup enqueue / run receipt / run history / auto-disable）
- :func:`import_legacy_schedules` 旧 AtlasScheduler ``schedules.toml`` 一次性导入
- :mod:`atlas.api.automation_router` ``/api/automations`` REST 面
"""

from __future__ import annotations

from atlas.automation.engine import (
    AutomationEngine,
    compute_next_run_at,
    schedule_name,
)
from atlas.automation.store import (
    AutomationStore,
    AutomationValidationError,
    normalize_record,
    validate_record,
)

__all__ = [
    "AutomationEngine",
    "AutomationStore",
    "AutomationValidationError",
    "compute_next_run_at",
    "schedule_name",
    "normalize_record",
    "validate_record",
]

_ENGINE: AutomationEngine | None = None


def get_automation_engine() -> AutomationEngine:
    """进程内单例（server 启动时用 :func:`set_automation_engine` 注入配置）。"""
    global _ENGINE
    if _ENGINE is None:
        from atlas.automation.store import default_automations_path

        _ENGINE = AutomationEngine(AutomationStore(default_automations_path()))
    return _ENGINE


def set_automation_engine(engine: AutomationEngine | None) -> AutomationEngine | None:
    """替换单例（server 集成 / 测试用）。返回旧值。"""
    global _ENGINE
    previous = _ENGINE
    _ENGINE = engine
    return previous
