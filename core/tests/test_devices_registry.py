"""DeviceRegistry tests — roundtrip, self-registration, generation, online window.

No real X2 probes: a fake probe and an injectable clock keep everything hermetic.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from atlas.automation.engine import AutomationEngine
from atlas.automation.store import AutomationStore, normalize_record
from atlas.devices import (
    SELF_DEVICE_ID,
    DeviceError,
    DeviceRegistry,
)


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_registry(path: Path, clock: FakeClock, probe: dict[str, Any]) -> DeviceRegistry:
    return DeviceRegistry(path, clock=clock, probe=lambda: dict(probe))


@pytest.fixture()
def probe() -> dict[str, Any]:
    return {"computer": True, "browser": True, "provider_generation": 1}


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def registry(tmp_path: Path, clock: FakeClock, probe: dict[str, Any]) -> DeviceRegistry:
    return make_registry(tmp_path / "devices.json", clock, probe)


# ---------------------------------------------------------------------------
# Self registration
# ---------------------------------------------------------------------------
def test_register_self_creates_builtin_laptop(registry: DeviceRegistry) -> None:
    device = registry.register_self()
    assert device["device_id"] == SELF_DEVICE_ID
    assert device["kind"] == "atlas-laptop"
    assert device["trusted"] is True
    assert device["online"] is True  # the laptop is always online
    assert device["presence"]["state"] == "online"
    assert device["capabilities"] == {"computer": True, "browser": True, "provider_generation": 1}
    assert device["generation"] == 1
    assert device["display_name"]  # hostname-derived, non-empty
    assert device["os"]  # platform-derived, non-empty


def test_register_self_is_idempotent(
    registry: DeviceRegistry, probe: dict[str, Any]
) -> None:
    first = registry.register_self()
    second = registry.register_self()
    assert len(registry.list_devices()) == 1
    assert second["created_at"] == first["created_at"]
    assert second["generation"] == first["generation"] == 1
    # notes survive and are never duplicated
    registry.update(SELF_DEVICE_ID, notes="运营商备注")
    again = registry.register_self()
    assert again["notes"] == "运营商备注"


def test_register_self_capability_change_bumps_generation(
    tmp_path: Path, clock: FakeClock, probe: dict[str, Any]
) -> None:
    registry = make_registry(tmp_path / "devices.json", clock, probe)
    assert registry.register_self()["generation"] == 1
    probe["browser"] = False  # X2 browser surface vanished
    assert registry.register_self()["generation"] == 2
    probe["provider_generation"] = 7  # provider upgrade alone also re-pairs
    assert registry.register_self()["generation"] == 3
    # unchanged probes never bump
    assert registry.register_self()["generation"] == 3


# ---------------------------------------------------------------------------
# Ingress CRUD + persistence roundtrip
# ---------------------------------------------------------------------------
def test_ingress_add_and_json_roundtrip(
    tmp_path: Path, clock: FakeClock, probe: dict[str, Any]
) -> None:
    path = tmp_path / "devices.json"
    registry = make_registry(path, clock, probe)
    registry.register_self()
    phone = registry.add("phone-1", "我的手机", os="iOS 18", notes="仅消息",
                         capabilities={"computer": False, "browser": True})
    assert phone["kind"] == "ingress"
    assert phone["capabilities"]["browser"] is True
    assert phone["capabilities"]["computer"] is False
    assert phone["online"] is False  # never seen
    assert phone["presence"]["state"] == "offline"

    reloaded = make_registry(path, clock, probe)  # fresh instance, same file
    stored = reloaded.get("phone-1")
    assert stored is not None
    assert stored["display_name"] == "我的手机"
    assert stored["os"] == "iOS 18"
    assert stored["notes"] == "仅消息"
    assert stored["trusted"] is False
    assert stored["created_at"] == phone["created_at"]
    ids = {device["device_id"] for device in reloaded.list_devices()}
    assert ids == {SELF_DEVICE_ID, "phone-1"}


def test_add_rejects_duplicates_self_and_bad_ids(registry: DeviceRegistry) -> None:
    registry.register_self()
    registry.add("phone-1", "手机")
    with pytest.raises(DeviceError) as dup:
        registry.add("phone-1", "手机")
    assert dup.value.status_code == 409
    with pytest.raises(DeviceError) as self_conflict:
        registry.add(SELF_DEVICE_ID, "本机")
    assert self_conflict.value.status_code == 409
    with pytest.raises(DeviceError) as bad:
        registry.add("../evil", "路径穿越")
    assert bad.value.status_code == 422
    with pytest.raises(DeviceError) as empty_name:
        registry.add("pc-2", "  ")
    assert empty_name.value.status_code == 422


def test_update_fields_and_capability_bump(registry: DeviceRegistry) -> None:
    registry.add("tablet-1", "平板")
    updated = registry.update("tablet-1", display_name="客厅平板", os="Android 15",
                              trusted=True, notes="客厅设备")
    assert updated["display_name"] == "客厅平板"
    assert updated["trusted"] is True
    assert updated["generation"] == 1
    bumped = registry.update("tablet-1", capabilities={"computer": True, "browser": True})
    assert bumped["generation"] == 2  # capability face changed → pairing revoked
    with pytest.raises(DeviceError) as unknown:
        registry.update("ghost", display_name="x")
    assert unknown.value.status_code == 404
    with pytest.raises(DeviceError) as unsupported:
        registry.update("tablet-1", device_id="new-id")
    assert unsupported.value.status_code == 422


def test_remove_ingress_only(registry: DeviceRegistry) -> None:
    registry.register_self()
    registry.add("phone-1", "手机")
    registry.remove("phone-1")
    assert registry.get("phone-1") is None
    with pytest.raises(DeviceError) as missing:
        registry.remove("phone-1")
    assert missing.value.status_code == 404
    with pytest.raises(DeviceError) as builtin:
        registry.remove(SELF_DEVICE_ID)
    assert builtin.value.status_code == 409


# ---------------------------------------------------------------------------
# Presence / online window
# ---------------------------------------------------------------------------
def test_ingress_online_timeout_window(
    registry: DeviceRegistry, clock: FakeClock
) -> None:
    registry.add("phone-1", "手机")
    assert registry.online("phone-1") is False
    registry.set_presence("phone-1", activity="打开应用")
    assert registry.online("phone-1") is True
    clock.advance(60)  # within the default 90s window
    assert registry.online("phone-1") is True
    clock.advance(31)  # 91s since the last beat
    assert registry.online("phone-1") is False
    live = registry.get("phone-1")
    assert live is not None
    assert live["online"] is False
    assert live["presence"]["state"] == "offline"
    assert live["presence"]["activity"] == "打开应用"  # last-known survives offline
    registry.set_presence("phone-1", last_seen=clock.now)
    assert registry.online("phone-1") is True


def test_laptop_is_always_online(tmp_path: Path, clock: FakeClock, probe: dict[str, Any]) -> None:
    registry = make_registry(tmp_path / "devices.json", clock, probe)
    registry.register_self()
    clock.advance(10_000)
    assert registry.online(SELF_DEVICE_ID) is True
    assert registry.get(SELF_DEVICE_ID)["online"] is True


def test_set_presence_unknown_device(registry: DeviceRegistry) -> None:
    with pytest.raises(DeviceError) as err:
        registry.set_presence("ghost", activity="x")
    assert err.value.status_code == 404


def test_explicit_bump_generation_revokes_pairing(registry: DeviceRegistry) -> None:
    registry.add("phone-1", "手机")
    assert registry.bump_generation("phone-1", reason="设备转卖") == 2
    device = registry.get("phone-1")
    assert device["generation"] == 2
    assert "设备转卖" in device["notes"]


def test_corrupt_store_starts_empty(tmp_path: Path, clock: FakeClock, probe: dict[str, Any]) -> None:
    path = tmp_path / "devices.json"
    path.write_text("{not json", encoding="utf-8")
    registry = make_registry(path, clock, probe)
    assert registry.list_devices() == []
    assert registry.register_self()["device_id"] == SELF_DEVICE_ID
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert set(on_disk["devices"]) == {SELF_DEVICE_ID}


# ---------------------------------------------------------------------------
# Scenario 12 (P11 acceptance map §2.5, option 1): offline window ≠ work stoppage
# ---------------------------------------------------------------------------
def test_device_offline_window_does_not_block_local_automation_and_presence_recovers(
    tmp_path: Path, clock: FakeClock, probe: dict[str, Any]
) -> None:
    """One combo proving both halves over real modules:

    (a) an ingress device recovers presence after the 90s offline window;
    (b) durable local work (automation engine, the self-hosted laptop half)
        keeps firing and recording while the device projects offline — the
        engine never gates on device presence.
    """
    registry = make_registry(tmp_path / "devices.json", clock, probe)
    registry.register_self()
    registry.add("phone-1", "手机")

    # -- (a) presence: online → offline window → ingress beat → online -------
    registry.set_presence("phone-1", activity="打开应用")
    assert registry.online("phone-1") is True
    clock.advance(91)  # past the default 90s online window
    assert registry.online("phone-1") is False
    live = registry.get("phone-1")
    assert live is not None
    assert live["presence"]["state"] == "offline"
    assert live["presence"]["activity"] == "打开应用"  # last-known survives offline
    assert registry.online(SELF_DEVICE_ID) is True  # the laptop itself never drops

    # -- (b) durable work continues inside the offline window ----------------
    ticks: list[tuple[str, str]] = []

    async def tick(agent_id: str, reason: str) -> dict[str, Any]:
        ticks.append((agent_id, reason))
        return {"tick": agent_id, "reason": reason}

    # Same shape server._reconcile_agent_heartbeats upserts (interval +
    # heartbeat payload, delivery none) — asserted engine-side only here.
    automation_id = "heartbeat-agent-on-call"
    store = AutomationStore(tmp_path / "automations.toml")
    store.put(normalize_record({
        "id": automation_id,
        "name": "heartbeat:值班助手",
        "enabled": True,
        "owner_agent_id": "agent-on-call",
        "trigger": {"kind": "interval", "every_seconds": 1800.0},
        "payload": {"kind": "heartbeat", "agent_id": "agent-on-call"},
        "delivery": {"mode": "none"},
    }))
    engine = AutomationEngine(store, heartbeat_tick=tick)  # local engine, no DBOS

    run = asyncio.run(engine.execute_payload(automation_id, "schedule"))
    assert run["status"] == "ok"
    assert ticks == [("agent-on-call", "schedule")]
    engine.apply_outcome(automation_id, {**run, "trigger": "schedule"})
    state = store.get(automation_id)["state"]
    assert state["last_status"] == "ok"
    assert state["last_run_at"]
    assert state["consecutive_errors"] == 0

    # The phone is still offline here — presence never gated the engine.
    assert registry.online("phone-1") is False

    # -- reconcile after recovery: beat re-attaches presence; the run recorded
    #    during the offline window is still visible and firing still works ----
    registry.set_presence("phone-1", last_seen=clock.now)
    assert registry.online("phone-1") is True

    asyncio.run(engine.reconcile_async())  # engine-side reconcile: never raises
    recovered = store.get(automation_id)
    assert recovered is not None
    assert recovered["enabled"] is True
    assert recovered["state"]["last_status"] == "ok"  # offline-window run survives
    run_after = asyncio.run(engine.execute_payload(automation_id, "schedule"))
    assert run_after["status"] == "ok"
    assert ticks == [("agent-on-call", "schedule"), ("agent-on-call", "schedule")]
