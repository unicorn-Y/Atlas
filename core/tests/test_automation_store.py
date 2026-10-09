"""AutomationStore 往返与校验（无 DBOS 依赖）。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from atlas.automation.store import (
    AutomationStore,
    AutomationValidationError,
    normalize_record,
    validate_record,
)


def _store(tmp_path: Path) -> AutomationStore:
    return AutomationStore(tmp_path / "data" / "automations.toml")


def _cron_record(automation_id: str = "daily-digest", **overrides) -> dict:
    record = normalize_record(
        {
            "id": automation_id,
            "name": "每日摘要",
            "trigger": {"kind": "cron", "cron_expr": "0 9 * * *"},
            "payload": {"kind": "agent_turn", "message": "汇总今日进展"},
        }
    )
    record.update(overrides)
    return record


def test_roundtrip_put_get_list_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    saved = store.put(_cron_record())
    assert saved["created_at"] and saved["updated_at"]

    loaded = store.get("daily-digest")
    assert loaded is not None
    assert loaded["name"] == "每日摘要"
    assert loaded["trigger"]["kind"] == "cron"
    assert loaded["trigger"]["cron_expr"] == "0 9 * * *"
    assert loaded["payload"]["kind"] == "agent_turn"
    assert loaded["delivery"]["mode"] == "none"
    assert loaded["policy"]["missed_run"] == "skip"
    assert loaded["state"]["consecutive_errors"] == 0
    assert loaded["enabled"] is True

    assert [item["id"] for item in store.list()] == ["daily-digest"]

    # 更新保留 created_at、刷新 updated_at
    again = store.put({**loaded, "name": "改名", "state": {"consecutive_errors": 2}})
    assert again["created_at"] == saved["created_at"]
    assert again["updated_at"] >= saved["updated_at"]
    assert again["state"]["consecutive_errors"] == 2

    assert store.update_state("daily-digest", last_status="ok", last_run_at="2026-10-03T00:00:00+00:00")
    assert store.get("daily-digest")["state"]["last_status"] == "ok"
    assert store.delete("daily-digest") is True
    assert store.get("daily-digest") is None
    assert store.delete("daily-digest") is False


def test_source_binding_survives_automation_store_roundtrip(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path / "automations.toml")
    source_binding = {
        "request_run_id": "run-42",
        "source_message_ref": "ATLAS_USER_MESSAGE:message-42",
        "intent_id": "intent-42",
    }

    saved = store.put({**_cron_record(), "source_binding": source_binding})

    assert saved["source_binding"] == source_binding
    assert store.get(saved["id"])["source_binding"] == source_binding


def test_generated_id_and_defaults(tmp_path: Path) -> None:
    store = _store(tmp_path)
    saved = store.put({"name": "无名"})
    assert saved["id"]
    fetched = store.get(saved["id"])
    assert fetched is not None
    assert fetched["trigger"]["kind"] == "interval"  # 缺省 trigger
    assert fetched["policy"]["consecutive_error_disable"] == 10


def test_file_is_human_readable_toml(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put(_cron_record())
    text = store.path.read_text(encoding="utf-8")
    assert "[automations.daily-digest]" in text
    assert "[automations.daily-digest.trigger]" in text
    parsed = tomllib.loads(text)
    assert parsed["automations"]["daily-digest"]["payload"]["message"] == "汇总今日进展"


@pytest.mark.parametrize(
    "mutation, fragment",
    [
        ({"trigger": {"kind": "cron", "cron_expr": "not a cron"}}, "cron_expr"),
        ({"trigger": {"kind": "cron", "cron_expr": ""}}, "cron_expr"),
        ({"trigger": {"kind": "interval", "every_seconds": 0}}, "every_seconds"),
        ({"trigger": {"kind": "date", "at": "nope"}}, "at"),
        ({"trigger": {"kind": "date", "at": ""}}, "at"),
        ({"trigger": {"kind": "event", "event_path": ""}}, "event_path"),
        ({"trigger": {"kind": "turnstile"}}, "trigger.kind"),
        ({"payload": {"kind": "shell"}}, "payload.kind"),
        ({"payload": {"kind": "heartbeat", "agent_id": ""}}, "heartbeat"),
        ({"payload": {"kind": "script", "script": ""}}, "script"),
        ({"payload": {"kind": "script", "script": "echo hi", "timeout_seconds": 0}}, "timeout_seconds"),
        ({"delivery": {"mode": "fax"}}, "delivery.mode"),
        ({"policy": {"missed_run": "retry-forever"}}, "missed_run"),
    ],
)
def test_validation_rejects_bad_fields(tmp_path: Path, mutation: dict, fragment: str) -> None:
    store = _store(tmp_path)
    record = _cron_record()
    for key, value in mutation.items():
        if isinstance(value, dict) and isinstance(record.get(key), dict):
            record[key] = {**record[key], **value}
        else:
            record[key] = value
    with pytest.raises(AutomationValidationError, match=fragment):
        store.put(record)


def test_validation_bad_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(AutomationValidationError, match="id"):
        store.put(_cron_record("bad id!"))


def test_cron_six_field_seconds_expression_is_valid() -> None:
    record = _cron_record("sec", trigger={"kind": "cron", "cron_expr": "*/30 * * * * *"})
    validate_record(record)  # 6 字段秒级表达式（DBOS 同口径）不抛


def test_state_json_blob_tolerated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put(_cron_record())
    # 手工把 state 写成记录级 *_json 字符串（标量区）也能读回
    text = store.path.read_text(encoding="utf-8")
    import json as _json

    blob = _json.dumps({"last_status": "ok", "consecutive_errors": 1}).replace("\\", "\\\\").replace('"', '\\"')
    lines = []
    in_state_section = False
    for line in text.splitlines():
        if line.startswith("[automations.daily-digest.state]"):
            in_state_section = True
            continue
        if in_state_section:
            continue  # 丢弃原 state 小节，换成记录级 blob
        if line.startswith("updated_at ="):
            lines.append(line)
            lines.append(f"state_json = \"{blob}\"")
            continue
        lines.append(line)
    store.path.write_text("\n".join(lines), encoding="utf-8")
    loaded = store.get("daily-digest")
    assert loaded is not None
    assert loaded["state"]["last_status"] == "ok"
    assert loaded["state"]["consecutive_errors"] == 1
