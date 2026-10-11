"""Local diagnostics and the bundled MemOS bridge's telemetry privacy control."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib  # type: ignore[no-redef]

from fastapi import APIRouter, Depends, HTTPException

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.config import CONFIG_PATH, DATA_ROOT, USER_SETTINGS_PATH

router = APIRouter()


def _memos_config_path() -> Path:
    """Resolve the same MemOS config path that its Hermes bridge consumes."""
    configured_home = os.environ.get("MEMOS_HOME", "").strip()
    if configured_home:
        return Path(configured_home).expanduser().resolve() / "config.yaml"
    configured_file = os.environ.get("MEMOS_CONFIG_FILE", "").strip()
    if configured_file:
        return Path(configured_file).expanduser().resolve()
    return DATA_ROOT / "data" / "memos-home" / "config.yaml"


def _set_memos_telemetry_enabled(text: str, enabled: bool) -> str:
    """Change only the top-level telemetry.enabled YAML scalar, retaining comments."""
    lines = text.splitlines(keepends=True)
    sections: list[tuple[int, int, int]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^telemetry\s*:\s*(?:#.*)?(?:\r?\n)?$", line)
        if match:
            indent = 0
            end = len(lines)
            for next_index in range(index + 1, len(lines)):
                candidate = lines[next_index]
                if candidate.strip() and not candidate.lstrip().startswith("#"):
                    next_indent = len(candidate) - len(candidate.lstrip(" "))
                    if next_indent <= indent:
                        end = next_index
                        break
            sections.append((index, end, indent))

    if len(sections) > 1:
        raise ValueError("配置包含重复的 telemetry 区块，无法安全更新。")
    scalar = "true" if enabled else "false"
    if not sections:
        suffix = "" if not text or text.endswith(("\n", "\r")) else "\n"
        return f"{text}{suffix}\ntelemetry:\n  enabled: {scalar}\n"

    section_start, section_end, section_indent = sections[0]
    section_line = lines[section_start]
    if section_line.partition(":")[2].strip() and not section_line.partition(":")[2].lstrip().startswith("#"):
        raise ValueError("telemetry 区块使用内联 YAML，无法安全更新。")
    if not section_line.endswith(("\n", "\r")):
        newline = "\r\n" if "\r\n" in text else "\n"
        lines[section_start] = f"{section_line}{newline}"

    child_indent: int | None = None
    enabled_pattern = re.compile(r"^( +)enabled\s*:\s*([^#\r\n]*?)(\s*(?:#.*)?)(\r?\n)?$")
    for index in range(section_start + 1, section_end):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= section_indent:
            continue
        child_indent = indent if child_indent is None else min(child_indent, indent)

    enabled_line: int | None = None
    for index in range(section_start + 1, section_end):
        match = enabled_pattern.match(lines[index])
        if match and len(match.group(1)) == child_indent:
            enabled_line = index
            lines[index] = f"{match.group(1)}enabled: {scalar}{match.group(3)}{match.group(4) or ''}"
            break

    if enabled_line is None:
        indent = child_indent if child_indent is not None else section_indent + 2
        newline = "\r\n" if "\r\n" in text else "\n"
        lines.insert(section_start + 1, f"{' ' * indent}enabled: {scalar}{newline}")
    return "".join(lines)


def _read_memos_telemetry_enabled() -> bool:
    import yaml

    path = _memos_config_path()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=409, detail="MemOS 配置无法读取或 YAML 格式无效。") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=409, detail="MemOS 配置根节点不是对象，无法读取遥测设置。")
    telemetry = raw.get("telemetry", {})
    if not isinstance(telemetry, dict):
        raise HTTPException(status_code=409, detail="MemOS telemetry 配置格式无效。")
    value = telemetry.get("enabled", True)
    if not isinstance(value, bool):
        raise HTTPException(status_code=409, detail="MemOS telemetry.enabled 必须是布尔值。")
    return value


@router.get("/api/diagnostics/telemetry-privacy")
async def get_telemetry_privacy() -> dict[str, Any]:
    """Read the setting consumed by the bundled MemOS Local Hermes bridge."""
    return {
        "enabled": _read_memos_telemetry_enabled(),
        "scope": "memos-local-plugin",
        "applies_to": "next_bridge_start",
    }


@router.put("/api/diagnostics/telemetry-privacy")
async def set_telemetry_privacy(request: dict[str, Any]) -> dict[str, Any]:
    """Persist the sender's opt-out and restart any bridge using the old value."""
    enabled = request.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="enabled 必须是布尔值。")

    import yaml

    path = _memos_config_path()
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        original = ""
    except (OSError, UnicodeError) as exc:
        raise HTTPException(status_code=500, detail="MemOS 配置无法读取。") from exc

    try:
        parsed = yaml.safe_load(original)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=409, detail="MemOS YAML 格式无效，未修改配置。") from exc
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=409, detail="MemOS 配置根节点不是对象，未修改配置。")

    try:
        updated = _set_memos_telemetry_enabled(original, enabled)
        validated = yaml.safe_load(updated)
    except (ValueError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=409, detail=f"无法安全更新 MemOS 遥测设置：{exc}") from exc
    telemetry = validated.get("telemetry") if isinstance(validated, dict) else None
    if not isinstance(telemetry, dict) or telemetry.get("enabled") is not enabled:
        raise HTTPException(status_code=409, detail="遥测设置更新校验失败，未写入配置。")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary.write_text(updated, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="MemOS 遥测设置无法持久化。") from exc

    # The bundled adapter owns one process-scoped Node bridge. The bridge's
    # graceful shutdown flushes buffered telemetry, so opt-out must terminate
    # its Node clients before closing the registry. This also interrupts any
    # in-flight MemOS bridge operation; later providers start a fresh bridge
    # that reads the persisted setting.
    import sys

    bridge_module = sys.modules.get("shared_bridge_runtime")
    registry = getattr(bridge_module, "SHARED_BRIDGE_REGISTRY", None)
    if registry is not None:
        try:
            lock = getattr(registry, "_lock", None)
            if lock is None:
                raise RuntimeError("MemOS bridge registry lock is unavailable")
            with lock:
                runtimes = list(getattr(registry, "_runtimes", {}).values())
                clients = [getattr(runtime, "_client", None) for runtime in runtimes]
            if not enabled:
                for client in clients:
                    process = getattr(client, "_proc", None)
                    if process is not None and process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
            registry.close_all()
        except Exception as exc:  # noqa: BLE001 — report the incomplete runtime change
            raise HTTPException(
                status_code=503,
                detail="设置已持久化，但当前 MemOS bridge 未能停止；请重启 Atlas 使设置生效。",
            ) from exc

    return {"enabled": enabled, "scope": "memos-local-plugin", "applied": True}


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
        checks.append({
            "id": "model_config",
            "label": "模型配置",
            "status": "ok" if model_count else "warning",
            "detail": f"已登记 {model_count} 个模型；网关密钥{'已配置' if has_key else '未配置（本地模型可能无需密钥）'}。不会显示模型地址或密钥。",
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
