"""Read and operate local Android emulator devices for the desktop preview panel."""
from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["mobile-preview"])


@router.get("/api/mobile/android/devices")
async def android_preview_devices() -> dict:
    from atlas.tools.mobile_simulator import call_mobile_tool

    try:
        devices = await call_mobile_tool("android_list_devices", {}, str(Path.cwd()))
        avds = await call_mobile_tool("android_list_avds", {}, str(Path.cwd()))
    except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
        return {"devices": [], "avds": [], "available": False, "reason": str(exc)}
    return {"devices": devices.get("devices", []), "avds": avds.get("avds", []),
            "available": bool(avds.get("available")), "reason": avds.get("reason")}


@router.post("/api/mobile/android/start")
async def android_preview_start(request: Request) -> dict:
    from atlas.tools.mobile_simulator import call_mobile_tool

    try:
        payload = await request.json()
        avd = str(payload.get("avd", "")).strip()
        if not avd or len(avd) > 128:
            raise HTTPException(status_code=422, detail="请选择有效的 AVD")
        return await call_mobile_tool("android_start_emulator", {"avd": avd, "timeoutMs": 180_000}, str(Path.cwd()))
    except HTTPException:
        raise
    except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/mobile/android/install")
async def android_preview_install(request: Request) -> dict:
    from atlas.tools.mobile_simulator import call_mobile_tool

    try:
        payload = await request.json()
        workspace = str(payload.get("workspace", "")).strip()
        apk = str(payload.get("apkPath", "")).strip()
        serial = str(payload.get("serial", "")).strip()
        root = Path(workspace).expanduser().resolve()
        if not root.is_dir() or not serial or not apk:
            raise HTTPException(status_code=422, detail="需要工作区、设备和 APK 相对路径")
        return await call_mobile_tool("android_install_app", {"serial": serial, "apkPath": apk}, str(root))
    except HTTPException:
        raise
    except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/mobile/android/screenshot")
async def android_preview_screenshot(serial: str = Query(..., min_length=1, max_length=128)) -> dict:
    from atlas.tools.mobile_simulator import _adb

    if not re.fullmatch(r"[A-Za-z0-9._:-]+", serial):
        raise HTTPException(status_code=422, detail="无效的 Android 设备序列号")
    try:
        image = _adb(serial, "exec-out", "screencap", "-p", binary=True, timeout=20).stdout
    except (RuntimeError, OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=f"模拟器画面读取失败：{exc}") from exc
    if not image or not image.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=502, detail="adb 未返回有效 PNG 画面")
    return {"serial": serial, "captured_at": datetime.now(timezone.utc).isoformat(),
            "data_url": "data:image/png;base64," + base64.b64encode(image).decode("ascii")}
