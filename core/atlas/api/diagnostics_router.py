"""Local diagnostics."""

from __future__ import annotations

import json
import importlib.util
import os
import sqlite3
import sys
import shutil
from datetime import datetime, timezone
from typing import Annotated, Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib  # type: ignore[no-redef]

from fastapi import APIRouter, Depends

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.config import CONFIG_PATH, DATA_ROOT, USER_SETTINGS_PATH

router = APIRouter()


def _model_mgr(services: AppServices) -> Any:
    return services.model_mgr


def _file_state(path: Any, parser: Any) -> str:
    """Inspect a local config file without returning its path or contents."""
    try:
        if not path.is_file():
            return "missing"
        if path.stat().st_size > 1024 * 1024:
            return "too_large"
        content = path.read_text(encoding="utf-8")
        parser(content)
        return "valid"
    except FileNotFoundError:
        return "missing"
    except (OSError, UnicodeError, ValueError, TypeError):
        return "unreadable"


def _toml_parser(text: str) -> Any:
    return tomllib.loads(text)


def _json_object_parser(text: str) -> Any:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("settings must be an object")
    return value


def _public_state(value: Any) -> str:
    state = str(value or "unknown").lower()
    return state if state in {"ready", "starting", "failed"} else "unknown"


def _config_check_state(state: str) -> tuple[str, str]:
    if state == "valid":
        return "ok", "配置文件可读取且格式有效。"
    if state == "missing":
        return "ok", "未创建配置文件；Atlas 使用默认配置。"
    return "warning", "配置文件不可读取或格式无效；详细内容未包含在报告中。"


@router.get("/api/diagnostics")
async def get_diagnostics(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Return a copyable local report; this endpoint performs no network I/O."""
    startup = getattr(services, "startup", None)
    try:
        component_snapshot = startup.snapshot() if startup is not None else {}
    except Exception:  # noqa: BLE001 — diagnostics must not expose internals
        component_snapshot = {}
    components = {
        str(name): _public_state(state)
        for name, state in sorted(component_snapshot.items())
    }
    backend_state = (
        "failed" if "failed" in components.values()
        else "starting" if "starting" in components.values()
        else "ready"
    )
    checks: list[dict[str, str]] = [{
        "id": "backend",
        "label": "Atlas 后端",
        "status": "error" if backend_state == "failed" else "warning" if backend_state == "starting" else "ok",
        "detail": {"ready": "服务已就绪。", "starting": "部分组件仍在启动。", "failed": "有组件启动失败；报告不包含原始错误或路径。"}[backend_state],
    }]
    checks.append({
        "id": "python_runtime", "label": "Python 运行环境",
        "status": "ok" if sys.version_info >= (3, 11) else "warning",
        "detail": f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}。" +
                  ("运行版本满足当前要求。" if sys.version_info >= (3, 11) else "建议使用 Python 3.11 或更新版本。"),
    })
    missing_modules = [name for name in ("fastapi", "uvicorn", "litellm") if importlib.util.find_spec(name) is None]
    checks.append({
        "id": "python_dependencies", "label": "Python 依赖",
        "status": "warning" if missing_modules else "ok",
        "detail": f"缺少依赖：{', '.join(missing_modules)}。建议在 Atlas 的 core 环境重新安装依赖。" if missing_modules else "核心运行依赖均可导入。",
    })
    try:
        free_bytes = shutil.disk_usage(DATA_ROOT).free
        checks.append({
            "id": "disk_space", "label": "数据盘空间",
            "status": "warning" if free_bytes < 2 * 1024 ** 3 else "ok",
            "detail": f"可用空间约 {free_bytes // 1024 ** 3} GB。" + ("建议清理磁盘后重试。" if free_bytes < 2 * 1024 ** 3 else "空间充足。"),
        })
    except OSError:
        checks.append({"id": "disk_space", "label": "数据盘空间", "status": "unknown", "detail": "无法读取数据盘空间；检查目录访问权限。"})
    proxy_configured = any(os.environ.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"))
    checks.append({
        "id": "network_proxy", "label": "网络代理配置",
        "status": "ok" if proxy_configured else "unknown",
        "detail": "检测到代理环境变量（值已隐藏）。" if proxy_configured else "未检测到代理；需要代理时请在系统网络或启动环境中配置。此检查不会连接外网。",
    })
    from atlas.engine_core.state.hermes_state_wal import is_sqlite_wal_reset_vulnerable

    sqlite_unsafe = is_sqlite_wal_reset_vulnerable(sqlite3.sqlite_version_info)
    checks.append({
        "id": "sqlite_runtime", "label": "SQLite 运行时",
        "status": "warning" if sqlite_unsafe else "ok",
        "detail": f"SQLite {sqlite3.sqlite_version}；" +
                  ("此版本受 WAL-reset 问题影响，请使用新版桌面包。" if sqlite_unsafe else "已包含 WAL-reset 修复。"),
    })

    config_state = _file_state(CONFIG_PATH, _toml_parser)
    config_status, config_detail = _config_check_state(config_state)
    checks.append({"id": "atlas_config", "label": "Atlas 配置", "status": config_status, "detail": config_detail})

    user_settings_state = _file_state(USER_SETTINGS_PATH, _json_object_parser)
    if user_settings_state == "valid":
        settings_status, settings_detail = "ok", "用户设置文件可读取且格式有效。"
    elif user_settings_state == "missing":
        settings_status, settings_detail = "ok", "未创建用户设置文件；Atlas 使用默认值。"
    else:
        settings_status, settings_detail = "warning", "用户设置文件不可读取或格式无效；敏感内容未读取到报告中。"
    checks.append({"id": "user_settings", "label": "用户设置", "status": settings_status, "detail": settings_detail})

    model_mgr = _model_mgr(services)
    if model_mgr is None:
        checks.append({"id": "model_config", "label": "模型配置", "status": "unknown", "detail": "模型服务当前不可用。"})
    else:
        try:
            model_count = len(model_mgr.list_models())
        except Exception:  # noqa: BLE001
            model_count = 0
        has_key = bool(getattr(model_mgr, "api_key_configured", False))
        from atlas.models import ModelManager

        credential_error = (model_mgr.missing_model_credentials(model_mgr.current_model)
                            if isinstance(model_mgr, ModelManager) else None)
        checks.append({
            "id": "model_config",
            "label": "模型配置",
            "status": "warning" if not model_count or credential_error else "ok",
            "detail": credential_error or f"已登记 {model_count} 个模型；网关密钥{'已配置' if has_key else '未配置（本地模型或其他登录方式可能无需网关密钥）'}。不会显示模型地址或密钥。此检查不验证远端连接。",
        })

    for name, state in components.items():
        checks.append({
            "id": f"component:{name}",
            "label": f"启动组件：{name}",
            "status": "error" if state == "failed" else "warning" if state != "ready" else "ok",
            "detail": {"ready": "就绪。", "starting": "正在启动。", "failed": "启动失败；原始错误已省略。", "unknown": "状态未知。"}[state],
        })

    failed = sum(check["status"] == "error" for check in checks)
    warnings = sum(check["status"] in {"warning", "unknown"} for check in checks)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "status": "error" if failed else "warning" if warnings else "ok",
            "check_count": len(checks),
            "warning_count": warnings,
            "error_count": failed,
        },
        "checks": checks,
        "privacy": {
            "local_only": True,
            "network_requests": 0,
            "uploaded": False,
            "secrets_included": False,
            "paths_included": False,
        },
    }
