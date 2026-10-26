"""Local diagnostics."""

from __future__ import annotations

import json
import importlib.util
import os
import sqlite3
import sys
import shutil
import time
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
from atlas.diagnostic_alerts import record_alert, _read as read_alerts

router = APIRouter()


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            result.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return result
    return {prefix: value}


def _safe_value(key: str, value: Any) -> Any:
    if any(word in key.lower() for word in ("key", "token", "secret", "password", "credential")):
        return "（已隐藏）"
    if isinstance(value, dict):
        return {str(name): _safe_value(f"{key}.{name}", item) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(key, item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, ensure_ascii=False)[:500]


@router.get("/api/diagnostics/config-sources")
async def get_config_sources(root: str = "") -> dict[str, Any]:
    """Show effective, non-secret values and the file that supplied each value."""
    try:
        toml_data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    except (OSError, UnicodeError, ValueError):
        toml_data = {}
    try:
        user_data = json.loads(USER_SETTINGS_PATH.read_text(encoding="utf-8")) if USER_SETTINGS_PATH.exists() else {}
        if not isinstance(user_data, dict): user_data = {}
    except (OSError, UnicodeError, ValueError):
        user_data = {}
    base = _flatten(toml_data)
    defaults: dict[str, Any] = {
        "server.host": "0.0.0.0", "server.port": 8765, "models.default": "claude-sonnet-4",
        "models.gateway.base_url": "https://api.monkeyapi.net", "memory.db_path": "./data/atlas.db",
        "memory.max_context_messages": 50, "scheduler.enabled": False, "scheduler.timezone": "Asia/Shanghai",
        "notifications.toast_enabled": True,
    }
    override = _flatten(user_data)
    project_data: dict[str, Any] = {}
    project_label = "项目 .atlas/ 配置"
    if root:
        try:
            from atlas import server as atlas_server
            workspace, _ = atlas_server._workspace_path(root)
            directory = workspace / ".atlas"
            if directory.is_dir():
                for candidate in ("config.toml", "atlas.toml", "settings.toml", "config.json", "settings.json"):
                    path = directory / candidate
                    if not path.is_file(): continue
                    if path.stat().st_size > 256 * 1024: continue
                    raw = path.read_text(encoding="utf-8")
                    parsed = json.loads(raw) if path.suffix == ".json" else tomllib.loads(raw)
                    if isinstance(parsed, dict): project_data.update(_flatten(parsed))
        except (OSError, UnicodeError, ValueError, TypeError):
            pass
    project_overrides = project_data
    keys = sorted(set(base) | set(override) | set(project_overrides) | set(defaults))
    rows = []
    for key in keys:
        sources = []
        if key in defaults: sources.append({"source": "默认值", "value": _safe_value(key, defaults[key]), "active": key not in base and key not in override and key not in project_overrides})
        if key in base: sources.append({"source": "config/atlas.toml", "value": _safe_value(key, base[key]), "active": key not in override and key not in project_overrides})
        if key in override: sources.append({"source": "data/user-settings.json", "value": _safe_value(key, override[key]), "active": key not in project_overrides})
        if key in project_overrides: sources.append({"source": project_label, "value": _safe_value(key, project_overrides[key]), "active": True})
        env_key = "ATLAS_" + key.upper().replace(".", "_").replace("-", "_")
        if env_key in os.environ:
            sources = [{"source": "环境变量 " + env_key, "value": _safe_value(key, os.environ[env_key]), "active": True}, *[{**item, "active": False} for item in sources]]
        rows.append({"key": key, "value": next((item["value"] for item in sources if item["active"]), "（默认值）"), "sources": sources})
    cli = [arg for arg in sys.argv[1:] if arg.startswith("--") and any(word in arg.lower() for word in ("model", "workspace", "config", "profile"))]
    rows.extend({"key": arg.split("=", 1)[0], "value": _safe_value(arg.split("=", 1)[0], arg.split("=", 1)[1] if "=" in arg else "已传入"),
                 "sources": [{"source": "命令行", "value": "已传入" if "=" not in arg else _safe_value(arg.split("=", 1)[0], arg.split("=", 1)[1]), "active": True}]} for arg in cli)
    return {"sources": rows, "project_sources": ["项目 .atlas/ 配置", "命令行参数"],
            "note": "仅已显式保存的值显示在树中；未覆盖的值由代码默认值补齐。命令行仅显示与模型/工作区/配置/预设有关的参数。"}


@router.get("/api/diagnostics/alerts")
async def get_diagnostic_alerts(
    services: Annotated[AppServices, Depends(get_app_services)], unread_only: bool = False,
) -> dict[str, Any]:
    # The desktop bell polls this lightweight health sweep, so background outages
    # enter the durable stream even when the diagnostics page is closed.
    startup = getattr(services, "startup", None)
    try:
        snapshot = startup.snapshot() if startup is not None else {}
        for name, state in snapshot.items():
            if str(state).lower() in {"failed", "error"}:
                record_alert("startup", f"启动组件失败：{name}", "启动检查发现该组件未能就绪。", dedupe_key=f"startup:{name}:failed")
    except Exception:
        pass
    try:
        free = shutil.disk_usage(DATA_ROOT).free
        if free < 2 * 1024 ** 3:
            record_alert("disk", "磁盘空间不足", f"数据盘可用空间约 {free // 1024 ** 3} GB。", dedupe_key="disk:low")
    except OSError:
        pass
    if services.mcp_client is not None and hasattr(services.mcp_client, "get_runtime_status"):
        try:
            for item in services.mcp_client.get_runtime_status().get("servers", []):
                if str(item.get("state", "")).lower() in {"error", "failed", "disconnected"}:
                    name = str(item.get("name", "MCP"))
                    record_alert("mcp", f"MCP 服务器异常：{name}", str(item.get("error") or item.get("detail") or item.get("state")), dedupe_key=f"mcp:{name}:{item.get('state')}")
        except Exception:
            pass
    for task in services.scheduler.list_tasks() if services.scheduler is not None and hasattr(services.scheduler, "list_tasks") else []:
        latest = task.runs[-1] if getattr(task, "runs", None) else {}
        if isinstance(latest, dict) and str(latest.get("status", "")).lower() in {"failed", "error"}:
            record_alert("scheduler", f"定时任务失败：{task.name}", str(latest.get("error") or latest.get("detail") or "任务执行失败。"),
                         dedupe_key=f"scheduler:{task.id}:{latest.get('run_id') or latest.get('finished_at')}")
    rows = read_alerts()
    if unread_only: rows = [row for row in rows if not row.get("read")]
    return {"alerts": list(reversed(rows[-300:])), "unread": sum(not row.get("read") for row in read_alerts())}


@router.post("/api/diagnostics/alerts/{alert_id}/read")
async def mark_diagnostic_alert_read(alert_id: str) -> dict[str, Any]:
    from atlas.diagnostic_alerts import _LOCK, _PATH
    with _LOCK:
        rows = read_alerts()
        found = next((row for row in rows if row.get("id") == alert_id), None)
        if found is None: return {"updated": False}
        found["read"] = True
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"updated": True}


@router.get("/api/diagnostics/tasks")
async def get_diagnostic_tasks(services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    tasks = []
    manager = services.runtime_mgr
    for run in getattr(manager, "runs", {}).values():
        if run.status in {"running", "waiting", "paused"}:
            usage = run.usage[-1] if run.usage else {}
            if not isinstance(usage, dict): usage = {}
            cpu, memory = _process_resources()
            tool_starts: dict[str, tuple[str, float]] = {}
            recent_tools: list[dict[str, Any]] = []
            for event in run.events[-100:]:
                event_data = event.get("data", {}) if isinstance(event, dict) else {}
                call_id = str(event_data.get("tool_call_id", "")) if isinstance(event_data, dict) else ""
                if not call_id: continue
                timestamp = str(event.get("timestamp", ""))
                try: moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
                except (ValueError, TypeError): continue
                if event.get("event") == "tool.started": tool_starts[call_id] = (str(event_data.get("tool_name") or event_data.get("name") or "工具"), moment)
                elif event.get("event") == "tool.completed" and call_id in tool_starts:
                    name, started = tool_starts.pop(call_id)
                    recent_tools.append({"name": name, "duration_ms": round((moment - started) * 1000)})
            for name, started in tool_starts.values(): recent_tools.append({"name": name, "duration_ms": round((time.time() - started) * 1000), "running": True})
            tasks.append({"id": run.run_id, "kind": "会话运行", "name": run.user_input[:100] or run.conversation_id,
                          "status": run.status, "model": usage.get("model", run.model), "duration_ms": usage.get("duration_ms"),
                          "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                          "cached_tokens": usage.get("cached_tokens", usage.get("cache_read")),
                          "cpu_percent": cpu, "memory_bytes": memory, "recent_tools": recent_tools[-5:], "stoppable": True})
        for sub_id, child in getattr(run, "subtasks", {}).items():
            if isinstance(child, dict) and str(child.get("status", "running")) in {"running", "waiting"}:
                tasks.append({"id": f"subagent:{run.run_id}:{sub_id}", "kind": "子 agent", "name": str(child.get("goal") or child.get("title") or child.get("task") or sub_id),
                              "status": str(child.get("status", "running")), "stoppable": True})
    local = services.local_execution
    for item in getattr(local, "_processes", {}).values() if local is not None else []:
        if item.state == "running":
            cpu, memory = _process_resources(getattr(item.process, "pid", None))
            tasks.append({"id": f"process:{item.execution_id}", "kind": "后台进程", "name": str(item.command)[:160],
                          "status": "running", "stoppable": True, "cpu_percent": cpu, "memory_bytes": memory})
    browser_module = sys.modules.get("atlas.engine_core.tools.browser_tool")
    for session_key, info in getattr(browser_module, "_active_sessions", {}).items() if browser_module else []:
        tasks.append({"id": f"browser:{session_key}", "kind": "浏览器会话", "name": str(info.get("session_name") or session_key),
                      "status": "active", "stoppable": True})
    scheduler = services.scheduler
    if scheduler is not None and hasattr(scheduler, "list_tasks"):
        for task in scheduler.list_tasks():
            latest = task.runs[-1] if getattr(task, "runs", None) else {}
            if isinstance(latest, dict) and str(latest.get("status", "")).lower() in {"failed", "error"}:
                record_alert("scheduler", f"定时任务失败：{task.name}", str(latest.get("error") or latest.get("detail") or "任务执行失败。"),
                             target="diagnostics", dedupe_key=f"scheduler:{task.id}:{latest.get('run_id') or latest.get('finished_at')}")
            tasks.append({"id": f"schedule:{task.id}", "kind": "定时任务", "name": task.name,
                          "status": getattr(task.status, "value", str(task.status)), "stoppable": str(getattr(task.status, "value", task.status)) == "active"})
    mcp = services.mcp_client
    if mcp is not None and hasattr(mcp, "get_runtime_status"):
        try:
            for item in mcp.get_runtime_status().get("servers", []):
                server_name = str(item.get("name", "MCP"))
                if str(item.get("state", "")).lower() in {"error", "failed", "disconnected"}:
                    record_alert("mcp", f"MCP 服务器异常：{server_name}", str(item.get("error") or item.get("detail") or item.get("state")),
                                 target="diagnostics", dedupe_key=f"mcp:{server_name}:{item.get('state')}")
                if item.get("state") in {"connected", "ready", "running"}:
                    tasks.append({"id": f"mcp:{server_name}", "kind": "MCP 服务器", "name": server_name, "status": item.get("state"), "stoppable": True})
        except Exception:
            pass
    return {"tasks": tasks, "event_queue_length": sum(run.steer_queue.qsize() for run in getattr(manager, "runs", {}).values()),
            "note": "CPU/内存仅对操作系统可枚举子进程提供；当前 Python 运行时未暴露该数据。"}


@router.get("/api/diagnostics/battery")
async def get_battery_status() -> dict[str, Any]:
    """Return local battery state without exposing device identifiers or paths."""
    try:
        import psutil
        battery = psutil.sensors_battery()
    except (ImportError, OSError, RuntimeError, NotImplementedError):
        battery = None
    if battery is None:
        return {"supported": False, "level": None, "charging": None, "seconds_left": None}
    if not isinstance(battery.percent, (int, float)):
        return {"supported": False, "level": None, "charging": None, "seconds_left": None}
    seconds_left = battery.secsleft
    return {
        "supported": True,
        "level": max(0, min(100, round(float(battery.percent)))),
        "charging": bool(battery.power_plugged),
        "seconds_left": int(seconds_left) if isinstance(seconds_left, (int, float)) and seconds_left >= 0 else None,
    }


_EMERGENCY_KINDS = {"会话运行", "子 agent", "后台进程", "浏览器会话"}


async def stop_all_activity(services: AppServices) -> dict[str, Any]:
    """Emergency brake for everything Atlas is actively doing outside the automation engine.

    Reuses the task manager's listing and per-item stop so both paths stay identical. Stopped
    conversation runs are cancelled (not resumable); the caller reports them so the user knows.
    """
    listing = await get_diagnostic_tasks(services)
    stopped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for task in listing.get("tasks", []):
        if task.get("kind") not in _EMERGENCY_KINDS or not task.get("stoppable", True):
            continue
        if str(task.get("status") or "").lower() in {"completed", "failed", "cancelled", "exited", "done"}:
            continue
        try:
            result = await stop_diagnostic_task(services, str(task["id"]))
        except Exception as exc:  # one stuck item must not abort the brake for the rest
            result = {"stopped": False, "reason": str(exc)}
        row = {"id": task["id"], "kind": task.get("kind"), "name": task.get("name")}
        (stopped if result.get("stopped") else failed).append({**row, **({"reason": result.get("reason")} if not result.get("stopped") else {})})
    return {"stopped": stopped, "failed": failed}


@router.post("/api/diagnostics/tasks/{run_id}/stop")
async def stop_diagnostic_task(services: Annotated[AppServices, Depends(get_app_services)], run_id: str) -> dict[str, Any]:
    if run_id.startswith("browser:"):
        module = sys.modules.get("atlas.engine_core.tools.browser_tool")
        if module is None: return {"stopped": False, "reason": "浏览器运行时已关闭。"}
        try:
            module._lifecycle._cleanup_single_browser_session(run_id[8:])
            return {"stopped": True}
        except Exception as exc:
            return {"stopped": False, "reason": str(exc)}
    if run_id.startswith("subagent:"):
        _, parent_id, child_id = run_id.split(":", 2)
        run = getattr(services.runtime_mgr, "runs", {}).get(parent_id)
        child = run.subtasks.get(child_id) if run is not None else None
        cancel = child.get("cancel_event") if isinstance(child, dict) else None
        if cancel is None: return {"stopped": False, "reason": "子 agent 已结束或不存在。"}
        cancel.set()
        return {"stopped": True}
    if run_id.startswith("process:") and services.local_execution is not None:
        process_id = run_id[8:]
        record = services.local_execution._processes.get(process_id)
        if record is None: return {"stopped": False, "reason": "后台进程不存在。"}
        await services.local_execution._cancel_process(record)
        return {"stopped": True}
    if run_id.startswith("mcp:") and services.mcp_client is not None:
        name = run_id[4:]
        try:
            await services.mcp_client.disconnect_server(name)
            return {"stopped": True}
        except Exception as exc:
            return {"stopped": False, "reason": str(exc)}
    if run_id.startswith("schedule:") and services.scheduler is not None:
        from atlas.scheduler import TaskStatus
        task = await services.scheduler.update_task(run_id[9:], status=TaskStatus.PAUSED)
        return {"stopped": task is not None, "reason": None if task is not None else "定时任务不存在。"}
    run = getattr(services.runtime_mgr, "runs", {}).get(run_id)
    if run is None or run.status not in {"running", "waiting", "paused"}:
        return {"stopped": False, "reason": "任务不存在或已结束。"}
    run.cancel_event.set()
    return {"stopped": True}


def _process_resources(pid: Any = None) -> tuple[float | None, int | None]:
    try:
        import psutil
        process = psutil.Process(int(pid)) if pid else psutil.Process()
        return float(process.cpu_percent(interval=0.0)), int(process.memory_info().rss)
    except (ImportError, OSError, ValueError, TypeError):
        return None, None


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

    for check in checks:
        if check["status"] in {"warning", "error"}:
            record_alert("startup", check["label"], check["detail"], target="diagnostics", dedupe_key=f"startup:{check['id']}:{check['status']}")

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
