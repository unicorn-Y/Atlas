"""Device registry — the ownership projection of "which machines exist".

W5 of ATLAS-MEGA-PERSISTENT-ALWAYS-ON.  Semantics follow the R3 lane report
(``docs/research/2026-10-03-persistent-atlas/lanes/r3-openclaw-node-computer.md``):

- The machine running the Atlas server is the single *atlas-laptop* (built-in,
  ``device_id="self"``, never paired, ``trusted=True``).  It self-registers on
  first use (idempotent) with capabilities probed read-only from the existing
  X2 surface; if a probe cannot be imported we assign conservative values.
- Hosts / phones are *ingress* devices: manually registered rows that only
  receive messages/cards and never become execution targets.
- ``online`` is a projection, never a stored truth: the laptop is always
  online (it *is* the server); ingress devices are online iff their last
  presence update is within ``online_timeout`` seconds (default 90, clock
  injectable for tests).
- Every device carries a monotonic ``generation``: bumping it invalidates
  pairing/connections minted under the previous generation (OpenClaw
  ``pairingGeneration`` revocation semantics).  Capability changes bump it
  automatically; :meth:`DeviceRegistry.bump_generation` revokes explicitly.

Storage is a single JSON document at ``data/devices/devices.json`` (atomic
tmp-file replace, guarded by an in-process lock).  Concurrent writers beyond
this process are out of scope for the wave.
"""
from __future__ import annotations

import json
import platform
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from atlas.config import DATA_ROOT

DEFAULT_DEVICES_PATH = DATA_ROOT / "data" / "devices" / "devices.json"
SELF_DEVICE_ID = "self"
DEFAULT_ONLINE_TIMEOUT = 90.0

KIND_LAPTOP = "atlas-laptop"
KIND_INGRESS = "ingress"

_ALLOWED_KINDS = (KIND_LAPTOP, KIND_INGRESS)
_UPDATABLE_FIELDS = ("display_name", "os", "notes", "trusted", "capabilities")


class DeviceError(ValueError):
    """Registry-level failure carrying the HTTP status the router should map."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def _device_id_ok(device_id: str) -> bool:
    return (
        1 <= len(device_id) <= 64
        and device_id[0].isalnum()
        and all(ch.isalnum() or ch in "._-" for ch in device_id)
    )


def _default_capabilities() -> dict[str, Any]:
    """Conservative (fail-closed) capability face used when probing is impossible."""
    return {"computer": False, "browser": False, "provider_generation": 0}


def _probe_self_capabilities() -> dict[str, Any]:
    """Read-only probe of the existing X2 surfaces — imports the probe callables
    when present, otherwise falls back to conservative defaults.

    Never spawns processes or drives hardware: cheap import + schema presence.
    """
    caps = _default_capabilities()
    try:  # X2 computer runtime exposes tool schemas without side effects
        from atlas.tools.x2.computer import get_computer_tool_schemas

        if get_computer_tool_schemas():
            caps["computer"] = True
            caps["provider_generation"] = 1
    except Exception:  # noqa: BLE001 - conservative beat an import failure
        caps["computer"] = False
    try:  # X2 browser settings resolve without opening a session
        from atlas.tools.x2.browser import get_browser_settings

        get_browser_settings()
        caps["browser"] = True
    except Exception:  # noqa: BLE001
        caps["browser"] = False
    return caps


def _normalize_capabilities(raw: Any) -> dict[str, Any]:
    caps = _default_capabilities()
    if isinstance(raw, dict):
        caps["computer"] = bool(raw.get("computer", False))
        caps["browser"] = bool(raw.get("browser", False))
        try:
            caps["provider_generation"] = int(raw.get("provider_generation", 0))
        except (TypeError, ValueError):
            caps["provider_generation"] = 0
    return caps


def _capability_face(caps: dict[str, Any]) -> tuple[bool, bool, int]:
    """The tuple whose change means "the approved surface changed" → re-pair."""
    return (
        bool(caps.get("computer")),
        bool(caps.get("browser")),
        int(caps.get("provider_generation") or 0),
    )


class DeviceRegistry:
    """Owner of ``data/devices/devices.json`` and the online projection."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        clock: Callable[[], float] | None = None,
        online_timeout: float = DEFAULT_ONLINE_TIMEOUT,
        probe: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else DEFAULT_DEVICES_PATH
        self._clock = clock or time.time
        self._online_timeout = float(online_timeout)
        self._probe = probe or _probe_self_capabilities
        self._lock = threading.RLock()
        self._devices: dict[str, dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------ io
    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError):
            return  # corrupt store: start empty rather than crash the server
        devices = data.get("devices") if isinstance(data, dict) else None
        if isinstance(devices, dict):
            self._devices = {str(k): v for k, v in devices.items() if isinstance(v, dict)}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "devices": self._devices}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    # ------------------------------------------------------------ helpers
    def _now(self) -> float:
        return float(self._clock())

    def _iso_now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self._now()))

    def _blank_device(
        self, device_id: str, display_name: str, kind: str, os_name: str, notes: str,
        capabilities: dict[str, Any], trusted: bool,
    ) -> dict[str, Any]:
        return {
            "device_id": device_id,
            "display_name": display_name,
            "kind": kind,
            "os": os_name,
            "capabilities": capabilities,
            "generation": 1,
            "trusted": bool(trusted),
            "created_at": self._iso_now(),
            "notes": notes,
            "presence": {"state": "offline", "activity": "", "last_seen": 0.0},
            "online": False,
        }

    def _online_value(self, device: dict[str, Any]) -> bool:
        if device.get("kind") == KIND_LAPTOP:
            return True  # the laptop *is* the server process
        last_seen = float((device.get("presence") or {}).get("last_seen") or 0.0)
        return (self._now() - last_seen) <= self._online_timeout and last_seen > 0.0

    def _project(self, device: dict[str, Any]) -> dict[str, Any]:
        """Return a copy with ``online`` / ``presence.state`` recomputed."""
        projected = json.loads(json.dumps(device))  # deep copy, JSON-safe by construction
        online = self._online_value(projected)
        projected["online"] = online
        projected.setdefault("presence", {})["state"] = "online" if online else "offline"
        return projected

    def _require(self, device_id: str) -> dict[str, Any]:
        device = self._devices.get(device_id)
        if device is None:
            raise DeviceError(f"没有 id 为 {device_id!r} 的设备", status_code=404)
        return device

    # ------------------------------------------------------------- public
    def register_self(self) -> dict[str, Any]:
        """Idempotent self-registration of the atlas-laptop running this process.

        Refreshes the display name / os / capability projection each call; a
        *capability change* (computer/browser face flipped) bumps ``generation``
        once, exactly like a pairing revocation.  ``created_at`` and operator
        notes survive.
        """
        with self._lock:
            caps = _normalize_capabilities(self._probe())
            hostname = socket.gethostname() or "atlas-host"
            os_name = f"{platform.system()} {platform.release()}".strip()
            existing = self._devices.get(SELF_DEVICE_ID)
            if existing is None:
                device = self._blank_device(
                    SELF_DEVICE_ID, hostname, KIND_LAPTOP, os_name,
                    "Atlas 本机（内置，自动注册）", caps, trusted=True)
                self._devices[SELF_DEVICE_ID] = device
            else:
                device = existing
                device["kind"] = KIND_LAPTOP  # never demoted by a bad store edit
                device["display_name"] = device.get("display_name") or hostname
                device["os"] = os_name
                if _capability_face(device.get("capabilities") or {}) != _capability_face(caps):
                    device["generation"] = int(device.get("generation") or 1) + 1
                device["capabilities"] = caps
                device.setdefault("presence", {"state": "online", "activity": "", "last_seen": 0.0})
            self._save()
            return self._project(device)

    def add(
        self, device_id: str, display_name: str, *,
        kind: str = KIND_INGRESS, os: str = "", notes: str = "",
        capabilities: Any = None, trusted: bool = False,
    ) -> dict[str, Any]:
        """Manually register a device (ingress hosts/phones)."""
        device_id = str(device_id or "").strip()
        if not _device_id_ok(device_id):
            raise DeviceError("device_id 必须是 1-64 位字母/数字/._- 且以字母或数字开头")
        if kind not in _ALLOWED_KINDS:
            raise DeviceError(f"kind 必须是 {' / '.join(_ALLOWED_KINDS)}")
        display_name = str(display_name or "").strip()
        if not display_name:
            raise DeviceError("display_name 不能为空")
        with self._lock:
            if device_id in self._devices:
                raise DeviceError(f"设备 {device_id!r} 已存在", status_code=409)
            if device_id == SELF_DEVICE_ID:
                raise DeviceError("self 是内置本机，无需登记", status_code=409)
            device = self._blank_device(
                device_id, display_name, kind, str(os or "").strip(), str(notes or ""),
                _normalize_capabilities(capabilities), trusted)
            self._devices[device_id] = device
            self._save()
            return self._project(device)

    def update(self, device_id: str, /, **fields: Any) -> dict[str, Any]:
        """Patch operator-owned fields.  A capability face change bumps generation."""
        with self._lock:
            device = self._require(device_id)
            unknown = set(fields) - set(_UPDATABLE_FIELDS)
            if unknown:
                raise DeviceError(f"不支持的字段：{sorted(unknown)}")
            if "display_name" in fields:
                name = str(fields["display_name"] or "").strip()
                if not name:
                    raise DeviceError("display_name 不能为空")
                device["display_name"] = name
            if "os" in fields:
                device["os"] = str(fields["os"] or "").strip()
            if "notes" in fields:
                device["notes"] = str(fields["notes"] or "")
            if "trusted" in fields:
                device["trusted"] = bool(fields["trusted"])
            if "capabilities" in fields:
                caps = _normalize_capabilities(fields["capabilities"])
                if _capability_face(device.get("capabilities") or {}) != _capability_face(caps):
                    device["generation"] = int(device.get("generation") or 1) + 1
                device["capabilities"] = caps
            self._save()
            return self._project(device)

    def remove(self, device_id: str) -> dict[str, Any]:
        """Remove an ingress row.  The built-in laptop cannot be removed."""
        with self._lock:
            device = self._require(device_id)
            if device.get("kind") == KIND_LAPTOP or device_id == SELF_DEVICE_ID:
                raise DeviceError("本机（atlas-laptop）不可移除", status_code=409)
            del self._devices[device_id]
            self._save()
            return device

    def get(self, device_id: str, *, project: bool = True) -> dict[str, Any] | None:
        with self._lock:
            device = self._devices.get(device_id)
            return self._project(device) if device and project else (dict(device) if device else None)

    def list_devices(self, *, project: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            devices = list(self._devices.values())
        if project:
            return [self._project(d) for d in devices]
        return [dict(d) for d in devices]

    def set_presence(
        self, device_id: str, *,
        activity: str | None = None, last_seen: float | None = None,
    ) -> dict[str, Any]:
        """Record a presence beat.  ``state`` stays a projection (never set here)."""
        with self._lock:
            device = self._require(device_id)
            presence = device.setdefault("presence", {})
            if activity is not None:
                presence["activity"] = str(activity)
            presence["last_seen"] = float(last_seen) if last_seen is not None else self._now()
            self._save()
            return self._project(device)

    def online(self, device_id: str) -> bool:
        with self._lock:
            device = self._require(device_id)
            return self._online_value(device)

    def bump_generation(self, device_id: str, *, reason: str = "") -> int:
        """Explicit pairing revocation: old connections/tokens are stale afterwards."""
        with self._lock:
            device = self._require(device_id)
            device["generation"] = int(device.get("generation") or 1) + 1
            if reason:
                device["notes"] = ((device.get("notes") or "") + f"\n[generation+1] {reason}").strip()
            self._save()
            return int(device["generation"])


__all__ = [
    "DEFAULT_DEVICES_PATH",
    "DEFAULT_ONLINE_TIMEOUT",
    "DeviceError",
    "DeviceRegistry",
    "KIND_INGRESS",
    "KIND_LAPTOP",
    "SELF_DEVICE_ID",
]
