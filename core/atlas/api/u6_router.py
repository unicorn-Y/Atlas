"""U6 session suggestions and project environment hints."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.config import load_user_settings

router = APIRouter()
_last_retention_sweep = 0.0


def _data_paths() -> dict[str, list[Path]]:
    from atlas.config import DATA_ROOT, get_config
    data = DATA_ROOT / "data"
    db = get_config().db_path
    return {
        "sessions": [db, Path(str(db) + "-wal"), Path(str(db) + "-shm")],
        "logs": [DATA_ROOT / "logs", data / "logs"],
        "artifacts": [DATA_ROOT / "artifacts", data / "artifacts"],
        "cache": [DATA_ROOT / "cache", data / "cache"],
        "snapshots": [db.parent / "checkpoints", data / "checkpoints"],
        "models": [DATA_ROOT / "models", data / "models"],
    }


def _size(path: Path) -> int:
    if path.is_file():
        try: return path.stat().st_size
        except OSError: return 0
    total = 0
    if path.is_dir():
        for root, _, files in os.walk(path):
            for name in files:
                try: total += (Path(root) / name).stat().st_size
                except OSError: pass
    return total


@router.get("/api/u6/storage")
async def storage_usage() -> dict[str, Any]:
    labels = {"sessions": "会话数据库（清理只删除已归档会话）", "logs": "运行日志", "artifacts": "任务产物", "cache": "缓存", "snapshots": "工作区快照", "models": "模型下载"}
    return {"categories": [{"id": key, "label": label, "bytes": sum(_size(p) for p in _data_paths()[key]), "can_clear": True} for key, label in labels.items()]}


@router.delete("/api/u6/storage/{category}")
async def clear_storage(category: str, request: dict[str, Any], services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    paths = _data_paths()
    if category not in paths: raise HTTPException(status_code=404, detail="未知存储类别")
    if request.get("confirm") is not True: raise HTTPException(status_code=400, detail="需要确认清理")
    released = sum(_size(path) for path in paths[category])
    if category == "sessions":
        if services.memory is None: raise HTTPException(status_code=503, detail="会话数据库尚未就绪")
        # 只清理已归档的会话：一键删光全部会话不可撤销，代价远超省下的空间。
        for conversation in await services.memory.list_conversations(limit=None):
            if conversation.get("archived") and not conversation.get("pinned"):
                await services.memory.delete_conversation(conversation["id"])
        try:
            await services.memory._db.execute("VACUUM")
        except Exception: pass
        return {"category": category, "released_bytes": max(0, released - sum(_size(path) for path in paths[category]))}
    for path in paths[category]:
        if path.is_dir(): shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            try: path.unlink()
            except OSError: pass
    return {"category": category, "released_bytes": released}


@router.get("/api/u6/retention")
async def get_retention() -> dict[str, Any]:
    settings = load_user_settings()
    return {"days": settings.get("conversation_retention_days", 0), "action": settings.get("conversation_retention_action", "archive"), "exclude_pinned": settings.get("conversation_retention_exclude_pinned", True), "exclude_projects": settings.get("conversation_retention_exclude_projects", True)}


@router.put("/api/u6/retention")
async def put_retention(request: dict[str, Any]) -> dict[str, Any]:
    global _last_retention_sweep
    days = request.get("days", 0); action = request.get("action", "archive")
    if not isinstance(days, int) or days < 0 or days > 36500 or action not in ("archive", "delete"):
        raise HTTPException(status_code=422, detail="保留期限或操作无效")
    settings = load_user_settings(); settings.update({"conversation_retention_days": days, "conversation_retention_action": action, "conversation_retention_exclude_pinned": bool(request.get("exclude_pinned", True)), "conversation_retention_exclude_projects": bool(request.get("exclude_projects", True))})
    from atlas.config import USER_SETTINGS_PATH
    USER_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True); USER_SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _last_retention_sweep = 0.0
    return await get_retention()


@router.get("/api/u6/keybindings")
async def get_keybindings() -> dict[str, Any]:
    from atlas.config import DATA_ROOT
    path = DATA_ROOT / "data" / "keybindings.json"
    if not path.exists(): return {"bindings": {}, "updated_at": -1}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, list) or not all(isinstance(x, str) for x in v) for k, v in value.items()): raise ValueError("期望 action id → 字符串数组")
        return {"bindings": value, "updated_at": path.stat().st_mtime_ns}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"keybindings.json 格式错误：{exc}") from exc


@router.put("/api/u6/keybindings")
async def put_keybindings(request: dict[str, Any]) -> dict[str, Any]:
    value = request.get("bindings")
    if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, list) or not all(isinstance(x, str) for x in v) for k, v in value.items()): raise HTTPException(status_code=422, detail="期望 action id → 字符串数组")
    from atlas.config import DATA_ROOT
    path = DATA_ROOT / "data" / "keybindings.json"; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"bindings": value, "updated_at": path.stat().st_mtime_ns}


@router.get("/api/u6/whatsnew")
async def whatsnew() -> dict[str, Any]:
    from atlas.config import PROJECT_ROOT
    changelog = PROJECT_ROOT / "CHANGELOG.md"
    if changelog.is_file(): return {"source": "CHANGELOG.md", "highlights": changelog.read_text(encoding="utf-8", errors="replace")[:12000].splitlines()[:100]}
    import asyncio
    try:
        head = await asyncio.to_thread(subprocess.run, ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
        result = await asyncio.to_thread(subprocess.run, ["git", "-C", str(PROJECT_ROOT), "log", "-80", "--no-merges", "--date=short", "--pretty=format:%cs%x09%s"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
    except (OSError, subprocess.SubprocessError):
        return {"source": "git", "highlights": []}
    commits = [line.split("\t", 1) for line in (result.stdout or "").splitlines()]
    commits = [parts for parts in commits if len(parts) == 2 and parts[1].strip()]
    raw = [{"date": parts[0], "title": parts[1]} for parts in commits[:40]]
    version = (head.stdout or "").strip()
    from atlas.config import DATA_ROOT
    cache_path = DATA_ROOT / "data" / "whatsnew-cache.json"
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("version") == version and cached.get("highlights"):
            return {"source": "git+model", "version": version, "highlights": cached["highlights"]}
    except (OSError, ValueError):
        pass
    # 提交标题是给开发者看的（"U6-8 增补项目与前端连线检查"），交给模型改写成用户能看懂的更新亮点，按版本缓存。
    highlights = await _rewrite_highlights([f"{date} {title}" for date, title in commits])
    if not highlights:
        return {"source": "git", "version": version, "highlights": raw}
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"version": version, "highlights": highlights}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return {"source": "git+model", "version": version, "highlights": highlights}


async def _rewrite_highlights(commit_lines: list[str]) -> list[dict[str, str]]:
    if not commit_lines:
        return []
    try:
        import atlas.server
        router_client = getattr(atlas.server.orchestrator, "_model_router", None)
        model_mgr = getattr(atlas.server, "model_mgr", None)
        settings = load_user_settings()
        models = [str(settings.get("compression_model") or ""), str(getattr(model_mgr, "current_model", "") or ""),
                  *[str(item) for item in (settings.get("fallback_chain") or [])]]
        models = [item for index, item in enumerate(models) if item and item not in models[:index]]
    except Exception:
        return []
    if router_client is None:
        return []
    prompt = (
        "下面是 Atlas（桌面 AI 助手）最近的开发提交记录。请整理成给普通用户看的“有什么新功能”：\n"
        "- 最多 12 条，每条一句话说清用户能用它做什么，例如“主模型挂了会自动换备用模型接着干，并在对话里提示”；\n"
        "- 合并同一功能的多次提交，忽略纯内部的测试、检查、重构、验收提交；修复只保留用户能感知到的；\n"
        "- 只返回 JSON 数组，每项 {\"date\": \"YYYY-MM-DD\", \"title\": \"一句话\"}，按日期从新到旧。\n\n"
        + "\n".join(commit_lines[:80])
    )
    for model in models:
        try:
            result = await router_client.complete_for(model, "whatsnew", [{"role": "user", "content": prompt}],
                                                      max_tokens=1200, temperature=0.2)
        except Exception:
            continue
        text = str(getattr(result, "text", "")).strip()
        start, end = text.find("["), text.rfind("]")
        try:
            items = json.loads(text[start:end + 1]) if start >= 0 and end > start else []
        except ValueError:
            return []
        return [{"date": str(item.get("date") or ""), "title": str(item.get("title") or "").strip()}
                for item in items if isinstance(item, dict) and str(item.get("title") or "").strip()][:12]
    return []


@router.get("/api/u6/retention/run")
async def run_retention(services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    """Apply configured retention at most once a day as conversation lists refresh."""
    global _last_retention_sweep
    if time.time() - _last_retention_sweep < 86400: return {"affected": 0}
    settings = load_user_settings(); days = settings.get("conversation_retention_days", 0)
    if not isinstance(days, int) or days <= 0: return {"affected": 0}
    memory = services.memory
    if memory is None: return {"affected": 0}
    cutoff = time.time() - days * 86400; affected = 0
    for item in await memory.list_conversations(limit=None):
        if item.get("pinned") and settings.get("conversation_retention_exclude_pinned", True): continue
        try: updated = datetime.strptime(item.get("updated_at", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError): continue
        if updated >= cutoff: continue
        if item.get("archived") and settings.get("conversation_retention_action", "archive") == "archive": continue
        if settings.get("conversation_retention_exclude_projects", True) and services.projects:
            try:
                if await services.projects.find_by_conversation(item["id"]): continue
            except Exception: pass
        if settings.get("conversation_retention_action", "archive") == "delete": await memory.delete_conversation(item["id"])
        else: await memory.update_conversation(item["id"], archived=True)
        affected += 1
    _last_retention_sweep = time.time()
    return {"affected": affected}


@router.get("/api/u6/environment")
async def workspace_environment(workspace: str = Query("", max_length=4096)) -> dict[str, Any]:
    path = Path(workspace).expanduser()
    if not workspace or workspace.startswith("ssh://") or not path.is_dir():
        return {"is_git": False, "changed": 0, "languages": []}
    try:
        result = await __import__("asyncio").to_thread(
            subprocess.run, ["git", "-C", str(path), "status", "--porcelain=v1", "-z"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=4,
        )
        is_git = result.returncode == 0
        changed = len([item for item in result.stdout.split("\0") if item]) if is_git else 0
    except (OSError, subprocess.SubprocessError):
        is_git, changed = False, 0
    suffixes = {".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript", ".rs": "Rust", ".go": "Go", ".java": "Java", ".cs": "C#", ".swift": "Swift"}
    languages: set[str] = set()
    ignored = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "__pycache__"}
    scanned = 0
    for current, dirs, files in os.walk(path):
        dirs[:] = [name for name in dirs if name not in ignored]
        for name in files:
            language = suffixes.get(Path(name).suffix.lower())
            if language: languages.add(language)
            scanned += 1
            if scanned >= 1500: break
        if scanned >= 1500: break
    return {"is_git": is_git, "changed": changed, "languages": sorted(languages)[:5]}


@router.post("/api/u6/suggestions")
async def generate_suggestions(
    services: Annotated[AppServices, Depends(get_app_services)], request: dict[str, Any],
) -> dict[str, Any]:
    """Create two or three short follow-ups from one completed conversation turn."""
    orchestrator = services.orchestrator
    if orchestrator is None:
        import atlas.server
        orchestrator = atlas.server.orchestrator
    router_client = getattr(orchestrator, "_model_router", None)
    model_mgr = services.model_mgr
    settings = load_user_settings()
    # 依次尝试：压缩/辅助模型 → 本轮实际完成回复的模型 → 当前主模型 → 备用链；主模型挂了建议也能出。
    candidates = [str(settings.get("compression_model") or ""), str(request.get("model") or ""),
                  str(model_mgr.current_model) if model_mgr is not None else "",
                  *[str(item) for item in (settings.get("fallback_chain") or [])]]
    models = [item for index, item in enumerate(candidates) if item and item not in candidates[:index]]
    if router_client is None or not models:
        return {"suggestions": []}
    goal = str(request.get("goal") or "")[:1200]
    response = str(request.get("response") or "")[:6000]
    if not response.strip():
        return {"suggestions": []}
    prompt = (
        "根据本轮用户目标和 Atlas 回复，给出 2 到 3 条用户接下来很可能真的想让 Atlas 做的具体请求。\n"
        "要求：每条是能直接发给 Atlas 执行的完整中文请求（例如“把这个函数补上单元测试并运行”），"
        "要结合回复里的具体对象（文件、命令、结论）；禁止“继续”“确认”“收到”“好的”“谢谢”这类没有具体内容的话；"
        "如果这一轮只是寒暄、简单问答或已经彻底完成、没有有价值的后续，就返回空数组 []。\n"
        "只返回 JSON 数组，不要解释。\n"
        f"目标：{goal}\n回复：{response}"
    )
    for model in models:
        try:
            result = await router_client.complete_for(model, "suggestions", [{"role": "user", "content": prompt}],
                                                      max_tokens=260, temperature=0.35)
        except Exception:  # 建议是可选的：这个模型不可用就试下一个，全失败就不显示。
            continue
        raw = str(getattr(result, "text", "")).strip()
        start, end = raw.find("["), raw.rfind("]")
        try:
            suggestions = json.loads(raw[start:end + 1]) if start >= 0 and end > start else []
        except ValueError:
            return {"suggestions": []}
        if not isinstance(suggestions, list):
            return {"suggestions": []}
        cleaned = [item.strip()[:180] for item in suggestions
                   if isinstance(item, str) and len(item.strip()) >= 6
                   and item.strip().rstrip("。.!！") not in _GENERIC_SUGGESTIONS]
        return {"suggestions": cleaned[:3] if len(cleaned) >= 2 else []}
    return {"suggestions": []}


_GENERIC_SUGGESTIONS = {"继续", "请继续", "继续吧", "确认", "收到", "好的", "好", "谢谢", "明白", "没问题", "OK", "ok"}
