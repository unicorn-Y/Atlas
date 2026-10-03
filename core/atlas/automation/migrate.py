"""AtlasScheduler ``schedules.toml`` 一次性导入器（W4）.

旧 ``AtlasScheduler``（APScheduler 4.x，``core/atlas/scheduler``）的 TOML 格式::

    [tasks.<id>]
    name / description / trigger_type = cron|interval|date|event
    action = "agent:<message>" | "goal" | "callback:<dotted.path>"
    status = active|paused
    created_at / updated_at / last_run_at / next_run_at / run_count
    trigger_args = {...}（或 trigger_args_json 字符串）

导入规则（r7 §7 / 本 lane 任务书）：

- cron   → APScheduler trigger_args 合成 6 字段 cron 表达式（day_of_week 的
  APScheduler 0=周一 平移到 croniter 的 0=周日）。
- interval → trigger_args 秒/分/时/天/周 求和为 every_seconds。
- date   → run_date/run_time → trigger.at。
- event  → filter.root → event_path、filter.glob → event_glob。
- action "goal" / "agent:<msg>" → payload.kind=agent_turn（goal 保留原 goal 文本）；
  "callback:<path>" 不支持 → skip。
- status=paused → enabled=false。
- 同 id 已存在于 automations.toml → skip("already-exists")。

**不删旧文件、不改旧 scheduler**；导入幂等（重复执行产生 skipped 而非重复记录）。
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from atlas.automation.store import AutomationStore, normalize_record, validate_record

log = structlog.get_logger()

APScheduler_DOW_OFFSET = 1  # APScheduler: 0=mon → croniter: 0=sun


@dataclass
class MigrationReport:
    source: str
    imported: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "imported_count": len(self.imported),
            "skipped_count": len(self.skipped),
            "imported": self.imported,
            "skipped": self.skipped,
        }


def default_legacy_path() -> Path:
    from atlas.config import get_config

    return get_config().db_path.parent / "schedules.toml"


def _load_legacy_tasks(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("automation.migrate_read_failed", path=str(path), error=str(exc))
        return {}
    tasks: dict[str, dict[str, Any]] = {}
    for task_id, raw in (data.get("tasks") or {}).items():
        if not isinstance(raw, dict):
            continue
        raw = dict(raw)
        # trigger_args 可能是子表，也可能被手写为 *_json 字符串
        if not isinstance(raw.get("trigger_args"), dict):
            blob = raw.pop("trigger_args_json", None)
            if blob:
                try:
                    raw["trigger_args"] = json.loads(blob)
                except (TypeError, ValueError):
                    raw["trigger_args"] = {}
        tasks[str(task_id)] = raw
    return tasks


def _convert_dow(value: Any) -> str:
    """APScheduler day_of_week → croniter day_of_week."""
    if value is None:
        return "*"
    text = str(value).strip()
    if text == "" or text == "*":
        return "*"
    parts: list[str] = []
    for token in text.split(","):
        token = token.strip()
        if "-" in token and not any(ch.isalpha() for ch in token):
            left, _, right = token.partition("-")
            try:
                parts.append(f"{(int(left) + APScheduler_DOW_OFFSET) % 7}-{(int(right) + APScheduler_DOW_OFFSET) % 7}")
                continue
            except ValueError:
                parts.append(token)
                continue
        try:
            parts.append(str((int(token) + APScheduler_DOW_OFFSET) % 7))
        except ValueError:
            parts.append(token)  # mon/tue/... 两个库语义一致，原样保留
    return ",".join(parts)


def _cron_expr_from_args(args: dict[str, Any]) -> str:
    second = args.get("second", 0)
    minute = args.get("minute", "*")
    hour = args.get("hour", "*")
    day = args.get("day", "*")
    month = args.get("month", "*")
    dow = _convert_dow(args.get("day_of_week", "*"))
    return f"{_f(second)} {_f(minute)} {_f(hour)} {_f(day)} {_f(month)} {_f(dow)}"


def _f(value: Any) -> str:
    return "*" if value is None else str(value)


def _every_seconds_from_args(args: dict[str, Any]) -> float:
    weeks = float(args.get("weeks", 0) or 0)
    days = float(args.get("days", 0) or 0)
    hours = float(args.get("hours", 0) or 0)
    minutes = float(args.get("minutes", 0) or 0)
    seconds = float(args.get("seconds", 0) or 0)
    return weeks * 604800 + days * 86400 + hours * 3600 + minutes * 60 + seconds


def _payload_from_action(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """action → payload；不支持返回 (None, reason)。"""
    action = str(raw.get("action", ""))
    if action == "goal":
        return {"kind": "agent_turn", "message": str(raw.get("goal", "")), "agent_id": ""}, None
    if action.startswith("agent:"):
        return {"kind": "agent_turn", "message": action[len("agent:") :], "agent_id": ""}, None
    if action.startswith("callback:"):
        return None, f"unsupported-action:{action}"
    if not action:
        return {"kind": "agent_turn", "message": "", "agent_id": ""}, None
    return None, f"unknown-action:{action}"


def _trigger_from_legacy(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    trigger_type = str(raw.get("trigger_type", "cron"))
    args = raw.get("trigger_args") if isinstance(raw.get("trigger_args"), dict) else {}
    if trigger_type == "cron":
        return {"kind": "cron", "cron_expr": _cron_expr_from_args(args)}, None
    if trigger_type == "interval":
        seconds = _every_seconds_from_args(args)
        if seconds <= 0:
            return None, "empty-interval"
        return {"kind": "interval", "every_seconds": seconds}, None
    if trigger_type == "date":
        at = str(args.get("run_date") or args.get("run_time") or "")
        if not at:
            return None, "missing-date"
        return {"kind": "date", "at": at}, None
    if trigger_type == "event":
        filters = args.get("filter") if isinstance(args.get("filter"), dict) else {}
        return {
            "kind": "event",
            "event_path": str(filters.get("root", "")),
            "event_glob": str(filters.get("glob", "")),
            "event_debounce": 2.0,
        }, None
    return None, f"unknown-trigger:{trigger_type}"


def import_legacy_schedules(
    *,
    toml_path: str | Path | None = None,
    store: AutomationStore | None = None,
) -> MigrationReport:
    """Import every convertible legacy task; returns a per-task report."""
    path = Path(toml_path) if toml_path is not None else default_legacy_path()
    target = store if store is not None else AutomationStore()
    report = MigrationReport(source=str(path))

    for task_id, raw in sorted(_load_legacy_tasks(path).items()):
        if target.get(task_id) is not None:
            report.skipped.append({"id": task_id, "reason": "already-exists"})
            continue
        try:
            trigger, reason = _trigger_from_legacy(raw)
            if trigger is None:
                report.skipped.append({"id": task_id, "reason": reason or "unknown"})
                continue
            payload, action_reason = _payload_from_action(raw)
            if payload is None:
                report.skipped.append(
                    {"id": task_id, "reason": action_reason or "unsupported-action"}
                )
                continue
            record = normalize_record(
                {
                    "id": task_id,
                    "name": str(raw.get("name") or task_id),
                    "enabled": str(raw.get("status", "active")) == "active",
                    "trigger": trigger,
                    "payload": payload,
                    "created_at": str(raw.get("created_at", "")),
                    "state": {"last_run_at": str(raw.get("last_run_at", ""))},
                }
            )
            validate_record(record)
            target.put(record)
            report.imported.append(
                {
                    "id": task_id,
                    "trigger_kind": record["trigger"]["kind"],
                    "payload_kind": record["payload"]["kind"],
                    "enabled": record["enabled"],
                }
            )
        except Exception as exc:  # noqa: BLE001 - 单条失败不阻断整批导入
            report.skipped.append({"id": task_id, "reason": f"error:{exc}"})
            log.warning("automation.migrate_task_failed", task_id=task_id, error=str(exc))

    log.info(
        "automation.migrate_done",
        source=str(path),
        imported=len(report.imported),
        skipped=len(report.skipped),
    )
    return report
