"""检查最新版本、保存结果、用户设置。

数据都在 ``<data>/upstream/``：

- ``status.json``  最近一次检查的完整清单
- ``settings.json`` 自动模式、检查间隔、锁定的组件、是否推送
- ``failed.json``  预演里没通过的「组件 → 版本」：自动追新不再重试这个版本，出新版本再试
- ``run.json`` / ``history.jsonl`` 见 :mod:`atlas.upstream.staging`
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from atlas.upstream import inventory
from atlas.upstream.model import CATEGORIES, HELD, OUTDATED, Component, is_actionable

log = structlog.get_logger()

DEFAULT_SETTINGS: dict[str, Any] = {
    # off：不自动做任何事；check：定时检查并提醒；auto：检查后自动在预演副本里更新并验证
    "mode": "auto",
    "interval_hours": 24,
    # 预演通过后推送到 git 远端（另一台电脑点「更新」就能拿到）
    "push": True,
    # 锁定：组件 id → 原因。锁定的项不参与一键追新与自动追新
    "holds": {},
}

_lock = threading.Lock()


def upstream_root() -> Path:
    from atlas.config import get_config

    root = get_config().db_path.parent / "upstream"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_settings(root: Path | None = None) -> dict[str, Any]:
    stored = _read((root or upstream_root()) / "settings.json", {})
    return {**DEFAULT_SETTINGS, **(stored if isinstance(stored, dict) else {})}


def save_settings(patch: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = root or upstream_root()
    with _lock:
        settings = load_settings(root)
        for key in ("mode", "interval_hours", "push", "holds"):
            if key in patch:
                settings[key] = patch[key]
        if settings["mode"] not in {"off", "check", "auto"}:
            raise ValueError("mode 只能是 off / check / auto")
        settings["interval_hours"] = max(1, int(settings["interval_hours"]))
        _write(root / "settings.json", settings)
    return settings


def load_failed(root: Path | None = None) -> dict[str, dict[str, Any]]:
    data = _read((root or upstream_root()) / "failed.json", {})
    return data if isinstance(data, dict) else {}


def record_failure(component_id: str, version: str, reason: str, root: Path | None = None) -> None:
    root = root or upstream_root()
    with _lock:
        failed = load_failed(root)
        failed[component_id] = {"version": version, "reason": reason[:2000], "at": _now()}
        _write(root / "failed.json", failed)


def clear_failure(component_id: str, root: Path | None = None) -> None:
    root = root or upstream_root()
    with _lock:
        failed = load_failed(root)
        if failed.pop(component_id, None) is not None:
            _write(root / "failed.json", failed)


def load_status(root: Path | None = None) -> dict[str, Any]:
    status = _read((root or upstream_root()) / "status.json", {})
    return status if isinstance(status, dict) else {}


def decorate(components: list[dict[str, Any]], root: Path | None = None) -> list[dict[str, Any]]:
    """叠加用户锁定与历史失败（每次读取时算，改了设置不用重新检查）。"""
    settings = load_settings(root)
    holds = settings.get("holds") or {}
    failed = load_failed(root)
    out = []
    for item in components:
        item = dict(item)
        hold = holds.get(item["id"])
        if hold is not None:
            item["held"] = True
            item["hold_reason"] = hold
            if item.get("status") == OUTDATED:
                item["status"] = HELD
        failure = failed.get(item["id"])
        if failure:
            item["last_failure"] = failure
            # 只有同一版本失败过才算「已知不行」；上游出了更新的版本就重新给机会。
            item["failed_latest"] = failure.get("version") == item.get("latest")
        item["actionable"] = is_actionable(item)
        out.append(item)
    return out


def summarize(components: list[dict[str, Any]]) -> dict[str, Any]:
    categories = []
    for category, (label, hint) in CATEGORIES.items():
        rows = [item for item in components if item.get("category") == category]
        if not rows:
            continue
        categories.append({
            "id": category, "label": label, "hint": hint, "total": len(rows),
            "outdated": sum(item.get("status") == OUTDATED for item in rows),
            "actionable": sum(bool(item.get("actionable")) for item in rows),
        })
    return {
        "total": len(components),
        "outdated": sum(item.get("status") == OUTDATED for item in components),
        "actionable": sum(bool(item.get("actionable")) for item in components),
        "errors": sum(item.get("status") == "error" for item in components),
        "categories": categories,
    }


def view(root: Path | None = None) -> dict[str, Any]:
    """给界面用的完整视图：清单 + 分类汇总 + 设置。"""
    status = load_status(root)
    components = decorate(status.get("components") or [], root)
    return {
        "checked_at": status.get("checked_at"),
        "duration_seconds": status.get("duration_seconds"),
        "errors": status.get("errors") or [],
        "components": components,
        "summary": summarize(components),
        "settings": load_settings(root),
    }


def run_check(
    ctx: inventory.Context | None = None, root: Path | None = None,
    skills: list[Component] | None = None,
) -> dict[str, Any]:
    """完整检查一遍并保存（阻塞，几十秒到几分钟；调用方放到线程里）。"""
    root = root or upstream_root()
    ctx = ctx or inventory.default_context()
    started = datetime.now(UTC)
    components = inventory.scan_all(ctx)
    if skills:
        components.extend(skills)
    status = {
        "checked_at": _now(),
        "duration_seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
        "repo": str(ctx.repo),
        "errors": ctx.errors,
        "components": [item.to_dict() for item in components],
    }
    with _lock:
        _write(root / "status.json", status)
    log.info("upstream.checked", total=len(components),
             outdated=sum(item.status == OUTDATED for item in components),
             seconds=status["duration_seconds"])
    return view(root)


def check_due(root: Path | None = None) -> bool:
    settings = load_settings(root)
    if settings["mode"] == "off":
        return False
    checked = load_status(root).get("checked_at")
    if not checked:
        return True
    try:
        last = datetime.fromisoformat(checked)
    except ValueError:
        return True
    return datetime.now(UTC) - last >= timedelta(hours=int(settings["interval_hours"]))


def auto_plan(root: Path | None = None) -> list[str]:
    """自动追新这一轮要处理的组件：可处理、没锁定、这个版本没失败过、不需要即时更新。"""
    return [
        item["id"] for item in view(root)["components"]
        if item.get("actionable") and not item.get("failed_latest")
    ]
