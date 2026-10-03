"""P10 审计去重回归 — 旧 scheduler 双触发 + telegram 双轮询.

Fix 1 (P0): ``scheduler.enabled`` 默认 False（旧 APScheduler 不再随服务自启）；
importer 支持把本次导入的任务在旧 ``schedules.toml`` 中置为 paused。
Fix 2 (P1): 运行时启用网关 telegram 适配器（PUT /api/channels/accounts）时，
停掉旧 ``TelegramService`` getUpdates 轮询，避免同一 bot token 双轮询。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.channel_router import router, set_channel_manager
from atlas.automation.migrate import import_legacy_schedules
from atlas.automation.store import AutomationStore
from atlas.channels import ChannelManager
from atlas.channels.adapters.telegram import TelegramAdapter
from atlas.channels.credentials import ChannelCredentialStore
from atlas.config import AtlasConfig


# ---------------------------------------------------------------------------
# Fix 1a — scheduler.enabled 默认关，显式/环境变量仍可开
# ---------------------------------------------------------------------------


def test_scheduler_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ATLAS_SCHEDULER_ENABLED", raising=False)
    assert AtlasConfig({}).scheduler_enabled is False
    assert AtlasConfig({"scheduler": {}}).scheduler_enabled is False


def test_scheduler_explicit_opt_in_still_works(monkeypatch):
    monkeypatch.delenv("ATLAS_SCHEDULER_ENABLED", raising=False)
    assert AtlasConfig({"scheduler": {"enabled": True}}).scheduler_enabled is True
    assert AtlasConfig({"scheduler": {"enabled": False}}).scheduler_enabled is False


def test_scheduler_env_override_still_wins(monkeypatch):
    monkeypatch.setenv("ATLAS_SCHEDULER_ENABLED", "1")
    assert AtlasConfig({}).scheduler_enabled is True
    monkeypatch.setenv("ATLAS_SCHEDULER_ENABLED", "false")
    assert AtlasConfig({"scheduler": {"enabled": True}}).scheduler_enabled is False


# ---------------------------------------------------------------------------
# Fix 1b — import 后可选暂停旧任务
# ---------------------------------------------------------------------------

LEGACY_TOML = """
# Atlas Scheduled Tasks

[tasks.daily-digest]
name = "日报"
description = "每天早上九点"
trigger_type = "cron"
action = "agent:写日报"
status = "active"
created_at = "2026-01-01T00:00:00+00:00"

[tasks.daily-digest.trigger_args]
hour = 9
minute = 0

[tasks.no-status-line]
name = "无状态行"
trigger_type = "interval"
action = "agent:巡逻"

[tasks.no-status-line.trigger_args]
minutes = 30

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


def test_import_pauses_legacy_jobs_when_requested(tmp_path: Path) -> None:
    source = _legacy_file(tmp_path)
    store = AutomationStore(tmp_path / "automations.toml")

    report = import_legacy_schedules(toml_path=source, store=store, pause_legacy=True)

    # 导入成功
    imported_ids = {item["id"] for item in report.imported}
    assert imported_ids == {"daily-digest", "no-status-line"}
    assert store.get("daily-digest") is not None
    # 报告新增字段（向后兼容的增量）：paused_count / paused
    assert report.paused == ["daily-digest", "no-status-line"]
    assert report.to_dict()["paused_count"] == 2

    # 旧文件保留（不删），且导入的任务按旧 scheduler 自身语义暂停
    text = source.read_text(encoding="utf-8")
    assert "[tasks.daily-digest]" in text
    paused_lines = [line for line in text.splitlines() if line.strip() == 'status = "paused"']
    assert len(paused_lines) == 2  # 显式 status 行翻转 + 缺省行补插
    # 其余内容不动
    assert "hour = 9" in text and "minutes = 30" in text
    # 不支持的任务未被暂停
    native_block = text.split("[tasks.native]")[1].split("[tasks.native.trigger_args]")[0]
    assert 'status = "active"' in native_block

    # 旧 scheduler 只注册 ACTIVE 任务 → 读取回来确认两条都是 paused
    from atlas.scheduler import TaskStatus, _load_tasks_from_toml

    tasks = _load_tasks_from_toml(source)
    assert tasks["daily-digest"].status is TaskStatus.PAUSED
    assert tasks["no-status-line"].status is TaskStatus.PAUSED
    assert tasks["native"].status is TaskStatus.ACTIVE

    # 幂等：再次导入全部 already-exists，不重复改文件
    before = source.read_text(encoding="utf-8")
    second = import_legacy_schedules(toml_path=source, store=store, pause_legacy=True)
    assert second.imported == [] and second.paused == []
    assert source.read_text(encoding="utf-8") == before


def test_import_default_keeps_legacy_file_untouched(tmp_path: Path) -> None:
    source = _legacy_file(tmp_path)
    store = AutomationStore(tmp_path / "automations.toml")

    report = import_legacy_schedules(toml_path=source, store=store)

    assert store.get("daily-digest") is not None
    assert report.paused == []
    # 历史契约：默认导入零改动（tests/test_automation_migrate.py 同款断言）
    assert source.read_text(encoding="utf-8") == LEGACY_TOML


# ---------------------------------------------------------------------------
# Fix 2 — 启用网关 telegram 时停掉旧 getUpdates 轮询
# ---------------------------------------------------------------------------


class _DictStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class _LegacyTelegramStub:
    """TelegramService 替身 — 异步 stop() 记录调用次数。"""

    def __init__(self, stop_raises: bool = False) -> None:
        self.stop_calls = 0
        self._stop_raises = stop_raises

    async def stop(self) -> None:
        self.stop_calls += 1
        if self._stop_raises:
            raise RuntimeError("already stopped")


@pytest.fixture()
def client(tmp_path):
    manager = ChannelManager(
        db_path=tmp_path / "channels.db",
        config_path=tmp_path / "channels.json",
        credentials=ChannelCredentialStore(base=_DictStore()),
    )
    manager.register_channel("telegram", TelegramAdapter)
    set_channel_manager(manager)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client
    set_channel_manager(None)


def _put_telegram(test_client: TestClient, enabled: bool):
    return test_client.put(
        "/api/channels/accounts",
        json={"configs": {"telegram": {"enabled": enabled, "allowed_user_ids": [42]}}},
    )


def test_enabling_gateway_telegram_stops_legacy_poller_once(client, monkeypatch):
    import atlas.server as atlas_server  # 重模块，仅本用例需要

    stub = _LegacyTelegramStub()
    monkeypatch.setattr(atlas_server, "telegram_service", stub)
    response = _put_telegram(client, enabled=True)
    assert response.status_code == 200 and response.json()["ok"] is True
    assert stub.stop_calls == 1


def test_disabling_gateway_telegram_leaves_legacy_poller(client, monkeypatch):
    import atlas.server as atlas_server

    stub = _LegacyTelegramStub()
    monkeypatch.setattr(atlas_server, "telegram_service", stub)
    response = _put_telegram(client, enabled=False)
    assert response.status_code == 200
    assert stub.stop_calls == 0


def test_repeat_calls_tolerate_absent_or_broken_legacy_service(client, monkeypatch):
    import atlas.server as atlas_server

    payload = {"configs": {"telegram": {"enabled": True}}}
    stub = _LegacyTelegramStub()
    monkeypatch.setattr(atlas_server, "telegram_service", stub)
    assert client.put("/api/channels/accounts", json=payload).status_code == 200
    assert stub.stop_calls == 1

    # 服务已不存在（未构建 / 已关闭）：不抛错
    monkeypatch.setattr(atlas_server, "telegram_service", None)
    assert client.put("/api/channels/accounts", json=payload).status_code == 200

    # stop() 自身失败（如已停止）：吞掉，渠道配置照常成功
    broken = _LegacyTelegramStub(stop_raises=True)
    monkeypatch.setattr(atlas_server, "telegram_service", broken)
    response = client.put("/api/channels/accounts", json=payload)
    assert response.status_code == 200 and response.json()["ok"] is True
    assert broken.stop_calls == 1
