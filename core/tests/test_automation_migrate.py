"""旧 AtlasScheduler ``schedules.toml`` 一次性导入器覆盖（无 DBOS 依赖）。"""

from __future__ import annotations

from pathlib import Path

from atlas.automation.migrate import MigrationReport, import_legacy_schedules
from atlas.automation.store import AutomationStore

LEGACY_TOML = """
# Atlas Scheduled Tasks

[tasks.weekly-report]
name = "周报"
description = "每周一早九点"
trigger_type = "cron"
action = "agent:整理上周进展"
status = "active"
created_at = "2026-01-01T00:00:00+00:00"
last_run_at = "2026-09-28T01:00:00+00:00"

[tasks.weekly-report.trigger_args]
minute = 0
hour = 9
day_of_week = 0        # APScheduler: 0=周一 → croniter 应为 1

[tasks.cleanup]
name = "清理"
trigger_type = "interval"
action = "agent:清理临时目录"
status = "active"

[tasks.cleanup.trigger_args]
minutes = 90
seconds = 30

[tasks.one-shot]
name = "一次性"
trigger_type = "date"
action = "goal"
status = "active"
goal = "把仓库依赖升级到最新"

[tasks.one-shot.trigger_args]
run_date = "2027-01-01T08:00:00+00:00"

[tasks.watch-build]
name = "监听构建产物"
trigger_type = "event"
action = "agent:检查新构建产物"
status = "active"

[tasks.watch-build.trigger_args]
event = "file.changed"

[tasks.watch-build.trigger_args.filter]
root = "D:/obs/build"
glob = "*.log"

[tasks.paused-task]
name = "暂停中"
trigger_type = "cron"
action = "agent:不该被启用"
status = "paused"

[tasks.paused-task.trigger_args]
hour = 3

[tasks.native]
name = "回调任务"
trigger_type = "cron"
action = "callback:atlas.tools.some_callback"
status = "active"

[tasks.native.trigger_args]
hour = 4
"""


def _legacy_file(tmp_path: Path) -> Path:
    path = tmp_path / "schedules.toml"
    path.write_text(LEGACY_TOML, encoding="utf-8")
    return path


def test_import_converts_every_trigger_kind(tmp_path: Path) -> None:
    source = _legacy_file(tmp_path)
    store = AutomationStore(tmp_path / "automations.toml")
    report = import_legacy_schedules(toml_path=source, store=store)

    by_id = {item["id"]: item for item in report.imported}
    assert set(by_id) == {"weekly-report", "cleanup", "one-shot", "watch-build", "paused-task"}
    assert {item["id"] for item in report.skipped} == {"native"}
    assert report.skipped[0]["reason"].startswith("unsupported-action")

    weekly = store.get("weekly-report")
    assert weekly is not None
    assert weekly["trigger"]["kind"] == "cron"
    assert weekly["trigger"]["cron_expr"] == "0 0 9 * * 1"  # 0=周一 平移后；秒位显式 0
    assert weekly["payload"]["kind"] == "agent_turn"
    assert weekly["payload"]["message"] == "整理上周进展"
    assert weekly["enabled"] is True

    cleanup = store.get("cleanup")
    assert cleanup is not None
    assert cleanup["trigger"]["kind"] == "interval"
    assert cleanup["trigger"]["every_seconds"] == 5430.0

    one_shot = store.get("one-shot")
    assert one_shot is not None
    assert one_shot["trigger"] == {
        "kind": "date",
        "cron_expr": "",
        "tz": "",
        "every_seconds": 3600.0,
        "at": "2027-01-01T08:00:00+00:00",
        "event_path": "",
        "event_glob": "",
        "event_debounce": 2.0,
    }
    assert one_shot["payload"]["message"] == "把仓库依赖升级到最新"

    watch = store.get("watch-build")
    assert watch is not None
    assert watch["trigger"]["kind"] == "event"
    assert watch["trigger"]["event_path"] == "D:/obs/build"
    assert watch["trigger"]["event_glob"] == "*.log"

    paused = store.get("paused-task")
    assert paused is not None
    assert paused["enabled"] is False


def test_import_is_idempotent_and_keeps_source(tmp_path: Path) -> None:
    source = _legacy_file(tmp_path)
    store = AutomationStore(tmp_path / "automations.toml")

    first = import_legacy_schedules(toml_path=source, store=store)
    assert len(first.imported) == 5

    second = import_legacy_schedules(toml_path=source, store=store)
    assert second.imported == []
    # 已导入的 5 条 → already-exists；native 每次都重新判定为不支持（从未入库）
    by_reason = {item["id"]: item["reason"] for item in second.skipped}
    assert len(second.skipped) == 6
    assert {
        task_id for task_id, reason in by_reason.items() if reason == "already-exists"
    } == {"weekly-report", "cleanup", "one-shot", "watch-build", "paused-task"}
    assert by_reason["native"].startswith("unsupported-action")
    assert len(store.list()) == 5

    # 旧文件原样保留（不删、不改）
    assert source.read_text(encoding="utf-8") == LEGACY_TOML


def test_import_report_shape(tmp_path: Path) -> None:
    report = MigrationReport(source="x")
    assert report.to_dict()["imported_count"] == 0
    missing = import_legacy_schedules(
        toml_path=tmp_path / "missing.toml", store=AutomationStore(tmp_path / "a.toml")
    )
    assert missing.imported == [] and missing.skipped == []
