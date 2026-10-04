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

防双触发（P10）：已导入的任务同时存在于新旧两个引擎时，若旧 APScheduler 仍在
运行会重复触发。``pause_legacy=True`` 时，导入成功后把 *本次导入* 的任务在旧
文件中置为 ``status = "paused"``（旧 scheduler 自身的暂停语义，见
``atlas.scheduler.TaskStatus``）——文件保留、仅翻转目标任务的状态行，其余内容
逐字不动。默认 *零改动*（历史契约：tests/test_automation_migrate.py 断言旧文件
原样保留）；调用方（/api/automations/import-legacy）应显式传 ``pause_legacy=True``。
另一道闸是 ``scheduler.enabled`` 现默认 False（``atlas.config.AtlasConfig.scheduler_enabled``），
旧 scheduler 不再随服务自启，显式 ``[scheduler] enabled=true`` 仍可启用。
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import structlog

from atlas.automation.store import AutomationStore, normalize_record, validate_record

log = structlog.get_logger()

APScheduler_DOW_OFFSET = 1  # APScheduler: 0=mon → croniter: 0=sun


@dataclass
class MigrationReport:
    source: str
    imported: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    paused: list[str] = field(default_factory=list)  # 已在旧文件中置为 paused 的任务 id

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "imported_count": len(self.imported),
            "skipped_count": len(self.skipped),
            "paused_count": len(self.paused),
            "imported": self.imported,
            "skipped": self.skipped,
            "paused": self.paused,
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


def _pause_imported_tasks(path: Path, task_ids: Iterable[str]) -> list[str]:
    """把 *task_ids* 在旧 ``schedules.toml`` 中置为 ``status = "paused"``.

    使用旧 scheduler 自身的暂停语义（``status = active|paused``，paused 任务不会被
    ``AtlasScheduler`` 注册触发）。只翻转目标任务的状态行，其余内容逐字保留
    （不删旧文件）。返回实际处于 paused 的任务 id；读写失败时记日志并返回 []，
    绝不让暂停失败影响已完成的导入。
    """
    wanted = list(dict.fromkeys(str(task_id) for task_id in task_ids))
    if not wanted:
        return []
    wanted_set = set(wanted)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("automation.migrate_pause_read_failed", path=str(path), error=str(exc))
        return []

    # [tasks.<id>] 精确段头（带子表的 [tasks.<id>.trigger_args] 捕获值含 "."，
    # 不会与裸 id 相等，因此不会误伤）。TOML 裸键不含引号包裹的 id，此处按
    # 常规 slug 处理即可。
    section_re = re.compile(r"^\[tasks\.([^\]]+)\]\s*(?:#.*)?$")
    status_re = re.compile(r"^(\s*)status\s*=.*$")

    def _eol(line: str) -> str:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n") or not line:
            return "\n"
        return line[-1]  # 孤立 \r

    lines = text.splitlines(keepends=True)
    headers = [(i, m.group(1)) for i, line in enumerate(lines) if (m := section_re.match(line.strip()))]
    result = list(lines)
    paused: list[str] = []
    for pos, (header_idx, section_id) in enumerate(headers):
        if section_id not in wanted_set:
            continue
        end_idx = headers[pos + 1][0] if pos + 1 < len(headers) else len(result)
        replaced = False
        for j in range(header_idx + 1, end_idx):
            match = status_re.match(result[j])
            if match:
                result[j] = f'{match.group(1)}status = "paused"{_eol(result[j])}'
                replaced = True
                break
        if not replaced:
            # 旧格式缺省 status 视为 active（ScheduledTask.from_dict 默认），补一行
            result.insert(header_idx + 1, f'status = "paused"{_eol(lines[header_idx])}')
        paused.append(section_id)

    new_text = "".join(result)
    if new_text == text:
        return paused  # 全部本就是 paused，无需写盘
    try:
        tmp = path.with_name(path.name + ".pause.tmp")
        tmp.write_text(new_text, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.warning("automation.migrate_pause_write_failed", path=str(path), error=str(exc))
        return []
    return paused


def import_legacy_schedules(
    *,
    toml_path: str | Path | None = None,
    store: AutomationStore | None = None,
    pause_legacy: bool = False,
) -> MigrationReport:
    """Import every convertible legacy task; returns a per-task report.

    ``pause_legacy=True`` 在导入成功后把本次导入的任务在旧文件中置为 paused
    （防双触发，见模块 docstring）；默认 False 保持旧文件零改动。
    """
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
        except Exception as exc:  # 单条失败不阻断整批导入
            report.skipped.append({"id": task_id, "reason": f"error:{exc}"})
            log.exception("automation.migrate_task_failed", task_id=task_id, error=str(exc))

    log.info(
        "automation.migrate_done",
        source=str(path),
        imported=len(report.imported),
        skipped=len(report.skipped),
    )

    if pause_legacy and report.imported:
        report.paused = _pause_imported_tasks(path, [item["id"] for item in report.imported])
        if report.paused:
            log.info("automation.migrate_legacy_paused", tasks=report.paused)

    return report
