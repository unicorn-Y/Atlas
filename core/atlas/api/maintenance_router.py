"""Local data migration, crash archive, request traces, audits, and reset preview."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.api.u6_router import _data_paths, _size, clear_storage
from atlas.config import DATA_ROOT
from atlas.diagnostic_store import (
    list_audit_events,
    list_model_requests,
    list_tool_calls,
    record_audit_event,
)

router = APIRouter()
_MIGRATION_ROOTS = ("data", "config", "models", "artifacts", "cache", "logs", "exports", "checkpoints")


def _file_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in _MIGRATION_ROOTS:
        base = root / name
        if base.is_file() and not base.is_symlink():
            candidates = [base]
        elif base.is_dir() and not base.is_symlink():
            candidates = []
            for current, dirs, files in os.walk(base, followlinks=False):
                dirs[:] = [item for item in dirs if not (Path(current) / item).is_symlink()]
                candidates.extend(Path(current) / item for item in files if not (Path(current) / item).is_symlink())
        else:
            continue
        for file in candidates:
            digest = hashlib.sha256()
            try:
                with file.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                rows.append({"path": file.relative_to(root).as_posix(), "bytes": file.stat().st_size, "sha256": digest.hexdigest()})
            except OSError as exc:
                raise HTTPException(status_code=409, detail=f"迁移源文件无法读取：{file.name}（{exc}）") from exc
    return rows


def _migration_target(raw_target: Any) -> Path:
    if not isinstance(raw_target, str) or not raw_target.strip() or not Path(raw_target).is_absolute():
        raise HTTPException(status_code=422, detail="目标数据目录必须是绝对路径。")
    target = Path(raw_target).expanduser().resolve()
    source = DATA_ROOT.resolve()
    if target == source or source in target.parents or target in source.parents:
        raise HTTPException(status_code=422, detail="目标目录必须与当前数据目录互不包含。")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise HTTPException(status_code=409, detail="目标目录必须为空；现有文件不会被覆盖。")
    if not target.parent.exists() or not target.parent.is_dir():
        raise HTTPException(status_code=404, detail="目标目录的父文件夹不存在。")
    return target


def _marker(root: Path) -> dict[str, Any] | None:
    marker_path = root / "data" / ".atlas-data-migration.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        return marker if isinstance(marker, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


@router.get("/api/maintenance/data-directory")
async def get_data_directory() -> dict[str, Any]:
    marker = _marker(DATA_ROOT)
    previous = Path(str(marker.get("source_root"))).resolve() if marker and marker.get("verified") and marker.get("source_root") else None
    rollback = bool(previous and previous.is_dir())
    return {"current_root": str(DATA_ROOT), "previous_root": str(previous) if rollback else None,
            "migrated_at": marker.get("created_at") if marker else None, "rollback_available": rollback}


@router.post("/api/maintenance/data-directory/preview")
async def preview_data_directory(request: dict[str, Any]) -> dict[str, Any]:
    target = _migration_target(request.get("target"))
    files = _file_manifest(DATA_ROOT)
    return {"source_root": str(DATA_ROOT), "target_root": str(target), "file_count": len(files),
            "total_bytes": sum(row["bytes"] for row in files), "files": files[:500],
            "truncated": len(files) > 500, "can_copy": True}


@router.post("/api/maintenance/data-directory/copy-verify")
async def copy_verify_data_directory(request: dict[str, Any]) -> dict[str, Any]:
    target = _migration_target(request.get("target"))
    expected = _file_manifest(DATA_ROOT)
    staging = Path(tempfile.mkdtemp(prefix=".atlas-migration-", dir=str(target.parent)))
    try:
        for name in _MIGRATION_ROOTS:
            source = DATA_ROOT / name
            destination = staging / name
            if source.is_dir() and not source.is_symlink():
                shutil.copytree(source, destination, symlinks=True)
            elif source.is_file() and not source.is_symlink():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        copied = _file_manifest(staging)
        if expected != copied:
            raise HTTPException(status_code=500, detail="复制校验失败：源与副本的文件清单或 SHA-256 不一致。")
        data_dir = staging / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        marker = {"source_root": str(DATA_ROOT), "target_root": str(target), "created_at": datetime.now(timezone.utc).isoformat(),
                  "verified": True, "file_count": len(copied), "total_bytes": sum(row["bytes"] for row in copied)}
        (data_dir / ".atlas-data-migration.json").write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if target.exists(): target.rmdir()
        staging.replace(target)
        record_audit_event("data_directory", "copy_verify", details={"source_root": str(DATA_ROOT), "target_root": str(target), "files": len(copied), "bytes": marker["total_bytes"]})
        return {"verified": True, **marker}
    except Exception:
        if staging.exists(): shutil.rmtree(staging, ignore_errors=True)
        raise


def _safe_report(value: Any, key: str = "") -> Any:
    if any(word in key.casefold() for word in ("key", "token", "secret", "password", "credential", "authorization")):
        return "（已隐藏）"
    if isinstance(value, dict): return {str(name): _safe_report(item, str(name)) for name, item in list(value.items())[:100]}
    if isinstance(value, (list, tuple)): return [_safe_report(item, key) for item in value[:100]]
    if isinstance(value, str):
        text = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer （已隐藏）", value)
        text = re.sub(r"\b(?:sk-ant-[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,})\b", "（已隐藏凭据）", text)
        return text[:4000]
    if isinstance(value, (int, float, bool)) or value is None: return value
    return str(value)[:4000]


@router.get("/api/maintenance/crash-reports")
async def list_crash_reports() -> dict[str, Any]:
    directory = DATA_ROOT / "data" / "crash-reports"
    rows = []
    if directory.exists():
        for path in sorted(directory.glob("crash-*.json"), reverse=True)[:100]:
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
                rows.append({"id": path.stem, "created_at": row.get("created_at"), "reason": row.get("reason", "")})
            except (OSError, json.JSONDecodeError): continue
    return {"reports": rows}


@router.post("/api/maintenance/crash-reports")
async def save_crash_report(request: dict[str, Any]) -> dict[str, Any]:
    directory = DATA_ROOT / "data" / "crash-reports"
    directory.mkdir(parents=True, exist_ok=True)
    report_id = uuid.uuid4().hex
    payload = {"id": report_id, "created_at": datetime.now(timezone.utc).isoformat(),
               "reason": _safe_report(str(request.get("reason") or "用户保存的本机诊断报告"))[:2000],
               "diagnostics": _safe_report(request.get("diagnostics") or {})}
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(content.encode("utf-8")) > 1024 * 1024: raise HTTPException(status_code=413, detail="报告内容超过 1 MB。")
    (directory / f"crash-{report_id}.json").write_text(content + "\n", encoding="utf-8")
    record_audit_event("crash_report", "save", details={"id": report_id})
    return {"id": report_id, "path": str(directory / f"crash-{report_id}.json"), "created_at": payload["created_at"]}


@router.get("/api/maintenance/model-traces")
async def get_model_traces(q: str = "", limit: int = 100) -> dict[str, Any]:
    return {"traces": list_model_requests(q, limit)}


@router.get("/api/maintenance/tool-traces")
async def get_tool_traces(q: str = "", limit: int = 100,
                          run_id: str = "") -> dict[str, Any]:
    """Tool-call traces, optionally narrowed to one run.

    Shares ``run_id`` with ``/model-traces``, so passing the same ``run_id`` to
    both reads one run's model requests and tool calls on a single timeline.
    """
    return {"traces": list_tool_calls(q, limit, run_id)}


@router.get("/api/maintenance/audit")
async def get_maintenance_audit(q: str = "", limit: int = 200) -> dict[str, Any]:
    return {"events": list_audit_events(q, limit)}


@router.get("/api/maintenance/reset/preview")
async def preview_resource_reset() -> dict[str, Any]:
    labels = {"sessions": "已归档会话", "logs": "运行日志", "artifacts": "任务产物", "cache": "缓存", "snapshots": "工作区快照", "models": "模型下载"}
    categories = []
    for category, paths in _data_paths().items():
        files = sum(1 for path in paths if path.is_file()) + sum(sum(len(names) for _, _, names in os.walk(path)) for path in paths if path.is_dir())
        categories.append({"id": category, "label": labels.get(category, category), "bytes": sum(_size(path) for path in paths),
                           "file_count": files, "preserved": category == "sessions", "paths": [str(path) for path in paths]})
    return {"categories": categories, "note": "应用重置仅处理所选本地资源；会话只删除已归档且未置顶记录，配置和凭据保留。"}


@router.post("/api/maintenance/reset")
async def apply_resource_reset(request: dict[str, Any], services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    categories = request.get("categories")
    if request.get("confirm") is not True or not isinstance(categories, list) or not categories:
        raise HTTPException(status_code=422, detail="请选择需要清理的资源并确认。")
    allowed = set(_data_paths())
    if any(not isinstance(item, str) or item not in allowed for item in categories):
        raise HTTPException(status_code=422, detail="重置类别无效。")
    results = []
    for category in dict.fromkeys(categories):
        result = await clear_storage(category, {"confirm": True}, services)
        results.append(result)
    record_audit_event("resource_reset", "apply", details={"categories": categories, "results": results})
    return {"results": results, "released_bytes": sum(item.get("released_bytes", 0) for item in results)}
