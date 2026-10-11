"""Redacted settings provenance, local privacy preferences and HTTP summaries.

HTTP transports call record_http_summary; only numerical metadata is retained.
Electron consumes privacy.crash_capture_enabled using uploadToServer=False.
This module never reads or publishes a crash dump, request body or HTTP header.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.config import CONFIG_PATH, USER_SETTINGS_PATH, load_user_settings, save_user_settings

router = APIRouter(tags=["settings-audit"])
_lock = threading.Lock()
_privacy_lock = asyncio.Lock()
_http: deque[dict[str, Any]] = deque(maxlen=200)


def record_http_summary(transport: str, status_code: int | None, duration_ms: float, retries: int = 0) -> None:
    """Transport integration seam. No arbitrary strings or exception text enter it."""
    if transport not in {"openai-httpx", "anthropic-httpx"}:
        return
    if not isinstance(duration_ms, (int, float)) or not math.isfinite(duration_ms) or duration_ms < 0:
        return
    if not isinstance(retries, int) or isinstance(retries, bool):
        retries = 0
    row = {
        "transport": transport,
        "status_code": status_code if isinstance(status_code, int) and 100 <= status_code <= 599 else None,
        "duration_ms": round(min(duration_ms, 86400000), 2),
        "retries": max(0, min(int(retries), 100)),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        _http.append(row)


class PrivacyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telemetry_enabled: StrictBool
    crash_capture_enabled: StrictBool


def privacy_settings() -> dict[str, Any]:
    raw = load_user_settings().get("privacy")
    raw = raw if isinstance(raw, dict) else {}
    # New capture is opt-in. Existing MemOS status remains the sender authority.
    from atlas.api.diagnostics_router import _read_memos_telemetry_enabled
    return {
        "telemetry_enabled": _read_memos_telemetry_enabled(),
        "crash_capture_enabled": raw.get("crash_capture_enabled") is True,
        "crash_upload_enabled": False,
        "telemetry_senders": ["memos-local-plugin"],
        "crash_capture_consumer": "electron-crashReporter-local-only",
    }


@router.get("/api/settings-audit/privacy")
async def get_privacy() -> dict[str, Any]:
    return privacy_settings()


@router.put("/api/settings-audit/privacy")
async def update_privacy(payload: PrivacyUpdate) -> dict[str, Any]:
    from atlas.api.diagnostics_router import set_telemetry_privacy
    async with _privacy_lock:
        # Delegate to the real sender control, including stopping live bridges.
        await set_telemetry_privacy({"enabled": payload.telemetry_enabled})
        settings = load_user_settings()
        settings["privacy"] = {
            "telemetry_enabled": payload.telemetry_enabled,
            "crash_capture_enabled": payload.crash_capture_enabled,
        }
        try:
            save_user_settings(settings)
        except OSError as exc:
            raise HTTPException(500, "遥测状态已应用，但本机隐私偏好保存失败；请刷新后重试。") from exc
        return privacy_settings()


# An explicit map to native consumers, not automatic Claude JSON import.
_MAPPINGS = {
    "model": ("partial", "Atlas 模型设置；不是 Claude 模型名称直接透传", "models/router.py"),
    "effortLevel": ("partial", "Atlas 分阶段 reasoning 配置", "models/router.py"),
    "outputStyle": ("partial", "output_style / 输出风格面板", "agent/run_phases.py"),
    "hooks": ("partial", "Claude command hooks；逐项信任审批", "runtime/hooks.py"),
    "permissions.defaultMode": ("partial", "会话 permissionMode；不是 Claude 枚举直传", "components/settings/WorkspaceSecurityPanel.tsx"),
    "sandbox.enabled": ("partial", "会话 Docker 隔离；不是 Claude 原生沙箱", "components/settings/WorkspaceSecurityPanel.tsx"),
    "modelPricing": ("partial", "Atlas 自有价格表；不是 Claude pricing JSON 导入", "usage_pricing.py"),
}


def _keys(value: Any, prefix: str = "", depth: int = 0) -> list[str]:
    if not isinstance(value, dict) or depth >= 5:
        return [prefix] if prefix else []
    result = []
    for key, item in value.items():
        # Key names are user supplied: allow only normal config identifiers.
        if not isinstance(key, str) or len(key) > 64 or not key.replace("_", "").isalnum():
            continue
        dotted = f"{prefix}.{key}" if prefix else key
        result.extend(_keys(item, dotted, depth + 1) if isinstance(item, dict) else [dotted])
    return result[:500]


@router.get("/api/settings-audit/catalog")
async def get_catalog() -> dict[str, Any]:
    manifest = json.loads(Path(__file__).with_name("claude_settings_keys.json").read_text(encoding="utf-8-sig"))
    rows = []
    for key in manifest["keys"]:
        status, equivalent, consumer = _MAPPINGS.get(key, ("unsupported", "Atlas 未实现该 Claude 设置键；不写入或透传", ""))
        rows.append({"key": key, "status": status, "equivalent": equivalent, "consumer": consumer})
    sources = []
    for label, path in (("atlas.toml", CONFIG_PATH), ("user-settings.json", USER_SETTINGS_PATH)):
        try:
            if label == "atlas.toml":
                import tomllib
                raw = tomllib.loads(path.read_text(encoding="utf-8"))
            else:
                raw = json.loads(path.read_text(encoding="utf-8"))
            sources.append({"source": label, "state": "valid" if isinstance(raw, dict) else "invalid", "keys": _keys(raw)})
        except FileNotFoundError:
            sources.append({"source": label, "state": "missing", "keys": []})
        except (OSError, ValueError):
            sources.append({"source": label, "state": "invalid_or_unreadable", "keys": []})
    environment = [{"key": key, "present": bool(os.environ.get(key)), "value_redacted": True}
                   for key in ("ATLAS_API_BASE", "ATLAS_API_KEY", "ATLAS_SCHEDULER_ENABLED")]
    return {"official_source": manifest["source"], "retrieved": manifest["retrieved"], "keys": rows,
            "sources": sources, "values_redacted": True,
            "environment_overrides": environment,
            "precedence_note": "Atlas 自有 TOML、用户偏好与会话设置分别由对应消费者处理；未实现 Claude managed/project/local 合并规则。"}


@router.get("/api/settings-audit/resources")
async def get_resources() -> dict[str, Any]:
    try:
        import psutil
        process = psutil.Process()
        with process.oneshot():
            result = {"supported": True, "backend_rss_bytes": process.memory_info().rss,
                      "backend_threads": process.num_threads(), "system_memory_percent": psutil.virtual_memory().percent,
                      "system_cpu_percent": psutil.cpu_percent(interval=None), "cpu_sample": "since_previous_read",
                      "scope": "backend process and local system"}
        return result
    except ImportError:
        # Windows desktop can provide memory metrics without an optional package.
        if os.name == "nt":
            return _windows_memory()
        return {"supported": False, "reason": "当前平台未安装 psutil。"}
    except Exception:  # psutil's AccessDenied/NoSuchProcess are not OSError
        return {"supported": False, "reason": "系统资源暂时不可读取。"}


def _windows_memory() -> dict[str, Any]:
    import ctypes
    from ctypes import wintypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD),
                    ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                    ("avail_extended", ctypes.c_ulonglong)]

    class ProcessMemory(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("page_faults", wintypes.DWORD),
                    ("peak_working_set", ctypes.c_size_t), ("working_set", ctypes.c_size_t),
                    ("peak_paged", ctypes.c_size_t), ("paged", ctypes.c_size_t),
                    ("peak_nonpaged", ctypes.c_size_t), ("nonpaged", ctypes.c_size_t),
                    ("pagefile", ctypes.c_size_t), ("peak_pagefile", ctypes.c_size_t)]

    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD]
        memory = MemoryStatus(); memory.length = ctypes.sizeof(memory)
        process = ProcessMemory(); process.cb = ctypes.sizeof(process)
        if not kernel.GlobalMemoryStatusEx(ctypes.byref(memory)) or not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(process), process.cb):
            raise OSError("memory query failed")
        return {"supported": True, "backend_rss_bytes": process.working_set,
                "system_memory_percent": memory.load, "system_cpu_percent": None,
                "backend_threads": None, "scope": "Windows native memory; CPU/thread metrics require psutil"}
    except (OSError, AttributeError):
        return {"supported": False, "reason": "Windows 本机内存查询不可用。"}


@router.get("/api/settings-audit/model-http")
async def get_model_http(services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    with _lock:
        rows = list(_http)
    ledger = services.usage_ledger
    usage = None
    if ledger is not None:
        report = await ledger.query(start=(datetime.now(timezone.utc) - timedelta(days=7)).isoformat(), group_by="day")
        totals = report.get("totals") or {}
        usage = {key: totals.get(key) for key in ("input_tokens", "output_tokens", "runs")}
    return {"http_observed": bool(rows), "samples": rows, "sample_limit": 200,
            "usage_last_7_days": usage, "headers_collected": False, "bodies_collected": False,
            "scope": "仅已接入 observer 的 HTTPX transport；无采样不表示没有请求。"}
