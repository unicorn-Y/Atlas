"""Automation 产品状态存储 — ``data/automations.toml``（W4，字段冻结于 integration-map §4）.

单文件 TOML，``[automations.<id>]`` 一节一条记录；沿用 ``atlas.task_artifacts``
的 TomlRecordStore 模式（人可读、手编友好、全量重写、mtime 无关）。

记录结构（§4 冻结字段；``state`` 是运行投影，不进产品编辑面）::

    id, name, enabled, owner_agent_id, created_at, updated_at
    trigger  = { kind = cron|interval|date|event|webhook,
                 cron_expr, tz, every_seconds, at, event_path, event_glob, event_debounce }
    payload  = { kind = agent_turn|heartbeat|script,
                 message, agent_id, model, skills, script, timeout_seconds, wake_mode }
    delivery = { mode = none|channel, channel, target }
    policy   = { missed_run = catchup|skip, max_catchup, delete_after_run,
                 consecutive_error_disable }
    state    = { next_run_at, last_run_at, last_status, last_error,
                 consecutive_errors, paused_reason }

校验失败抛 :class:`AutomationValidationError`（router 映射 400）。
"""

from __future__ import annotations

import json
import re
import threading
import tomllib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas.task_artifacts import _toml_value

TRIGGER_KINDS = ("cron", "interval", "date", "event", "webhook")
PAYLOAD_KINDS = ("agent_turn", "heartbeat", "script")
DELIVERY_MODES = ("none", "channel")
MISSED_RUN_POLICIES = ("catchup", "skip")
WAKE_MODES = ("", "now", "next-heartbeat")
LAST_STATUSES = ("ok", "error", "skipped")
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,100}")

DEFAULT_EVENT_DEBOUNCE = 2.0
DEFAULT_SCRIPT_TIMEOUT = 60.0
DEFAULT_CONSECUTIVE_ERROR_DISABLE = 10
DEFAULT_MAX_CATCHUP = 5


class AutomationValidationError(ValueError):
    """Raised when an automation record violates the §4 contract."""


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def new_automation_id() -> str:
    return uuid.uuid4().hex[:12]


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _number(value: Any, default: float) -> float:
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def normalize_trigger(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "kind": _text(raw.get("kind"), "interval"),
        "cron_expr": _text(raw.get("cron_expr")),
        "tz": _text(raw.get("tz")),
        "every_seconds": _number(raw.get("every_seconds"), 3600.0),
        "at": _text(raw.get("at")),
        "event_path": _text(raw.get("event_path")),
        # Pragmatic extension of §4: keeps the legacy file.changed glob filter
        # through migration; "" means "any file under event_path".
        "event_glob": _text(raw.get("event_glob")),
        "event_debounce": _number(raw.get("event_debounce"), DEFAULT_EVENT_DEBOUNCE),
    }


def normalize_payload(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    skills = raw.get("skills")
    if not isinstance(skills, list):
        skills = []
    return {
        "kind": _text(raw.get("kind"), "agent_turn"),
        "message": _text(raw.get("message")),
        "agent_id": _text(raw.get("agent_id")),
        "model": _text(raw.get("model")),
        "skills": [str(item) for item in skills],
        "script": _text(raw.get("script")),
        "timeout_seconds": _number(raw.get("timeout_seconds"), DEFAULT_SCRIPT_TIMEOUT),
        "wake_mode": _text(raw.get("wake_mode")),
        "conversation_id": _text(raw.get("conversation_id")),
    }


def normalize_delivery(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "mode": _text(raw.get("mode"), "none"),
        "channel": _text(raw.get("channel")),
        "target": _text(raw.get("target")),
    }


def normalize_policy(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "missed_run": _text(raw.get("missed_run"), "skip"),
        "max_catchup": int(_number(raw.get("max_catchup"), DEFAULT_MAX_CATCHUP)),
        "delete_after_run": _bool(raw.get("delete_after_run"), False),
        "consecutive_error_disable": int(
            _number(raw.get("consecutive_error_disable"), DEFAULT_CONSECUTIVE_ERROR_DISABLE)
        ),
    }


def normalize_state(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "next_run_at": _text(raw.get("next_run_at")),
        "last_run_at": _text(raw.get("last_run_at")),
        "last_status": _text(raw.get("last_status")),
        "last_error": _text(raw.get("last_error")),
        "consecutive_errors": int(_number(raw.get("consecutive_errors"), 0)),
        "paused_reason": _text(raw.get("paused_reason")),
    }


def normalize_source_binding(raw: dict[str, Any] | None) -> dict[str, str]:
    """Normalize the bounded provenance fields used by unified reminders."""
    raw = raw if isinstance(raw, dict) else {}
    result: dict[str, str] = {}
    for field in ("request_run_id", "source_message_ref", "intent_id"):
        value = raw.get(field)
        if isinstance(value, str) and value.strip():
            result[field] = value.strip()
    return result


def normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults for every §4 field; returns a normalized copy."""
    raw = raw if isinstance(raw, dict) else {}
    automation_id = _text(raw.get("id")) or new_automation_id()
    record = {
        "id": automation_id,
        "name": _text(raw.get("name"), automation_id),
        "enabled": _bool(raw.get("enabled"), True),
        "owner_agent_id": _text(raw.get("owner_agent_id")),
        "created_at": _text(raw.get("created_at")),
        "updated_at": _text(raw.get("updated_at")),
        "trigger": normalize_trigger(raw.get("trigger")),
        "payload": normalize_payload(raw.get("payload")),
        "delivery": normalize_delivery(raw.get("delivery")),
        "policy": normalize_policy(raw.get("policy")),
        "state": normalize_state(raw.get("state")),
    }
    if isinstance(raw.get("source_binding"), dict):
        record["source_binding"] = normalize_source_binding(raw["source_binding"])
    return record


def validate_record(record: dict[str, Any]) -> None:
    """Validate a normalized record; raises :class:`AutomationValidationError`."""
    automation_id = _text(record.get("id"))
    if not ID_PATTERN.fullmatch(automation_id):
        raise AutomationValidationError(
            "id 只能包含字母、数字、'_' 或 '-'，长度 1-100"
        )
    if not _text(record.get("name")):
        raise AutomationValidationError("name 不能为空")

    trigger = record.get("trigger") or {}
    kind = trigger.get("kind")
    if kind not in TRIGGER_KINDS:
        raise AutomationValidationError(
            f"trigger.kind 必须是 {'|'.join(TRIGGER_KINDS)} 之一，得到 {kind!r}"
        )
    if kind == "cron":
        expr = _text(trigger.get("cron_expr"))
        if not expr:
            raise AutomationValidationError("trigger.cron_expr 不能为空")
        from croniter import croniter

        # DBOS 用同样的口径校验（支持 6 字段秒级表达式）
        if not croniter.is_valid(expr, second_at_beginning=True):
            raise AutomationValidationError(f"trigger.cron_expr 非法: {expr!r}")
    elif kind == "interval":
        if _number(trigger.get("every_seconds"), 0.0) <= 0:
            raise AutomationValidationError("trigger.every_seconds 必须 > 0")
    elif kind == "date":
        at = _text(trigger.get("at"))
        if not at:
            raise AutomationValidationError("trigger.at 不能为空（ISO 8601 时间）")
        try:
            datetime.fromisoformat(at)
        except ValueError as exc:
            raise AutomationValidationError(f"trigger.at 非法 ISO 时间: {at!r}") from exc
    elif kind == "event":
        if not _text(trigger.get("event_path")):
            raise AutomationValidationError("trigger.event_path 不能为空")

    payload = record.get("payload") or {}
    payload_kind = payload.get("kind")
    if payload_kind not in PAYLOAD_KINDS:
        raise AutomationValidationError(
            f"payload.kind 必须是 {'|'.join(PAYLOAD_KINDS)} 之一，得到 {payload_kind!r}"
        )
    if payload_kind == "heartbeat" and not _text(
        payload.get("agent_id")
    ) and not _text(record.get("owner_agent_id")):
        raise AutomationValidationError("heartbeat payload 需要指定 payload.agent_id")
    if payload_kind == "script":
        if not _text(payload.get("script")):
            raise AutomationValidationError("script payload 需要提供 payload.script")
        if _number(payload.get("timeout_seconds"), DEFAULT_SCRIPT_TIMEOUT) <= 0:
            raise AutomationValidationError("payload.timeout_seconds 必须 > 0")
    if _text(payload.get("wake_mode")) not in WAKE_MODES:
        raise AutomationValidationError(
            f"payload.wake_mode 必须是 {'|'.join(WAKE_MODES).strip('|')} 之一"
        )

    delivery = record.get("delivery") or {}
    if delivery.get("mode") not in DELIVERY_MODES:
        raise AutomationValidationError(
            f"delivery.mode 必须是 {'|'.join(DELIVERY_MODES)} 之一，得到 {delivery.get('mode')!r}"
        )

    policy = record.get("policy") or {}
    if policy.get("missed_run") not in MISSED_RUN_POLICIES:
        raise AutomationValidationError(
            f"policy.missed_run 必须是 {'|'.join(MISSED_RUN_POLICIES)} 之一"
        )
    if int(_number(policy.get("consecutive_error_disable"), DEFAULT_CONSECUTIVE_ERROR_DISABLE)) < 1:
        raise AutomationValidationError("policy.consecutive_error_disable 必须 >= 1")


def _escape_read(raw: dict[str, Any]) -> dict[str, Any]:
    """Tolerate ``<section>_json`` string blobs (merged under the section table)."""
    for field in ("trigger", "payload", "delivery", "policy", "state"):
        blob = raw.pop(f"{field}_json", None)
        if not blob:
            continue
        try:
            parsed = json.loads(blob)
        except (TypeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        table = raw.get(field) if isinstance(raw.get(field), dict) else {}
        raw[field] = {**parsed, **table}
    return raw


def default_automations_path() -> Path:
    from atlas.config import get_config

    return get_config().db_path.parent / "automations.toml"


class AutomationStore:
    """Single-file TOML store; the only writer of ``data/automations.toml``."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_automations_path()
        self._lock = threading.Lock()

    # -- raw format ---------------------------------------------------------

    def _render(self, records: dict[str, dict[str, Any]]) -> str:
        lines: list[str] = [
            "# Atlas Automations（产品状态）",
            "# 运行历史在 DBOS（data/dbos.sqlite）；本文件可手编，保持字段结构。",
            "",
        ]
        for automation_id in sorted(records):
            record = records[automation_id]
            scalars = {
                key: value
                for key, value in record.items()
                if not isinstance(value, dict)
            }
            sections = {
                key: value for key, value in record.items() if isinstance(value, dict)
            }
            lines.append(f"[automations.{automation_id}]")
            for key, value in scalars.items():
                if value is None:
                    continue
                lines.append(f"{key} = {_toml_value(value)}")
            for key, section in sections.items():
                lines.append("")
                lines.append(f"[automations.{automation_id}.{key}]")
                for sub_key, sub_value in section.items():
                    if sub_value is None:
                        continue
                    lines.append(f"{sub_key} = {_toml_value(sub_value)}")
            lines.append("")
        return "\n".join(lines)

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return {}
        records: dict[str, dict[str, Any]] = {}
        for automation_id, raw in (data.get("automations") or {}).items():
            if not isinstance(raw, dict):
                continue
            raw = dict(raw)
            raw.setdefault("id", automation_id)
            records[automation_id] = _escape_read(raw)
        return records

    def _write(self, records: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".toml.tmp")
        tmp.write_text(self._render(records), encoding="utf-8")
        tmp.replace(self.path)

    # -- public API ---------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            records = self._read()
        return [normalize_record(item) for item in records.values()]

    def get(self, automation_id: str) -> dict[str, Any] | None:
        with self._lock:
            raw = self._read().get(automation_id)
        return normalize_record(raw) if raw is not None else None

    def put(self, record: dict[str, Any]) -> dict[str, Any]:
        """Create or update one automation (normalize + validate + persist)."""
        normalized = normalize_record(record)
        validate_record(normalized)
        with self._lock:
            records = self._read()
            existing = records.get(normalized["id"])
            if existing is not None:
                normalized["created_at"] = existing.get("created_at") or normalized["created_at"]
            normalized["created_at"] = normalized["created_at"] or _stamp()
            normalized["updated_at"] = _stamp()
            records[normalized["id"]] = normalized
            self._write(records)
        return normalized

    def update_state(self, automation_id: str, **fields: Any) -> dict[str, Any] | None:
        """Merge a partial ``state`` projection (last_run_at / errors / paused_reason...)."""
        with self._lock:
            records = self._read()
            raw = records.get(automation_id)
            if raw is None:
                return None
            record = normalize_record(raw)
            state = {**record["state"], **fields}
            record["state"] = normalize_state(state)
            record["updated_at"] = _stamp()
            records[automation_id] = record
            self._write(records)
            return record

    def delete(self, automation_id: str) -> bool:
        with self._lock:
            records = self._read()
            if automation_id not in records:
                return False
            del records[automation_id]
            self._write(records)
            return True
