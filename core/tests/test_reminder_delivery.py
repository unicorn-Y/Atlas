"""Chat reminders reach the user when they fire (no agent run on the reminder text)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from atlas.api.automation_router import _project
from atlas.automation import reminders
from atlas.automation.engine import REMINDER_NAME_PREFIX, AutomationEngine
from atlas.automation.store import AutomationStore, normalize_record
from atlas.notifications import apprise as apprise_mod


def _engine(tmp_path, record: dict[str, Any]):
    calls: dict[str, list[Any]] = {"dispatch": [], "deliver": []}

    async def dispatch(payload: dict[str, Any]) -> str:
        calls["dispatch"].append(payload)
        return "agent reply"

    async def deliver(record: dict[str, Any], outcome: dict[str, Any]) -> bool:
        calls["deliver"].append(outcome["result"])
        return True

    store = AutomationStore(tmp_path / "automations.toml")
    store.put(normalize_record(record))
    return AutomationEngine(store, dispatch_turn=dispatch, deliver=deliver), calls


def _record(automation_id: str, name: str, delivery_mode: str = "none") -> dict[str, Any]:
    return {
        "id": automation_id,
        "name": name,
        "enabled": True,
        "trigger": {"kind": "date", "at": "2026-10-11T09:00:00+08:00"},
        "payload": {"kind": "agent_turn", "message": "交周报", "wake_mode": "now"},
        "delivery": {"mode": delivery_mode},
    }


def test_prefix_matches_reminders_module() -> None:
    assert REMINDER_NAME_PREFIX == reminders.REMINDER_PREFIX


@pytest.mark.asyncio
async def test_reminder_notifies_owner_without_running_agent(tmp_path) -> None:
    engine, calls = _engine(tmp_path, _record("rem-1", REMINDER_NAME_PREFIX + "交周报"))
    run = await engine.execute_payload("rem-1", "schedule")
    assert run["status"] == "ok"
    assert run["delivery"] == "delivered"  # stored with mode "none", still delivered
    assert calls["dispatch"] == []
    assert calls["deliver"] == [REMINDER_NAME_PREFIX + "交周报"]


@pytest.mark.asyncio
async def test_plain_agent_turn_keeps_its_delivery_mode(tmp_path) -> None:
    engine, calls = _engine(tmp_path, _record("job-1", "nightly digest"))
    run = await engine.execute_payload("job-1", "schedule")
    assert run["delivery"] == "not-requested"
    assert len(calls["dispatch"]) == 1
    assert calls["deliver"] == []


def test_cancelled_automation_has_no_next_run() -> None:
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    record = {"id": "rem-2", "enabled": False, "trigger": {"kind": "date", "at": future}}
    assert _project(record)["next_run_at"] == ""
    assert _project({**record, "enabled": True})["next_run_at"] != ""


def test_windows_toast_is_default_target(monkeypatch) -> None:
    cfg = SimpleNamespace(raw={}, toast_enabled=True)
    monkeypatch.delenv("ATLAS_NOTIFY_URLS", raising=False)
    monkeypatch.setattr(apprise_mod, "get_config", lambda: cfg)
    monkeypatch.setattr(apprise_mod, "_file_urls", lambda: [])
    monkeypatch.setattr(apprise_mod.os, "name", "nt")
    assert apprise_mod.configured_urls() == ["windows://"]
    cfg.toast_enabled = False
    assert apprise_mod.configured_urls() == []
