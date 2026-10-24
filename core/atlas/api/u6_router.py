"""U6 session suggestions and project environment hints."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.config import load_user_settings

router = APIRouter()


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
    model = str(load_user_settings().get("compression_model") or "")
    if not model and model_mgr is not None:
        model = str(model_mgr.current_model)
    if router_client is None or not model:
        return {"suggestions": []}
    goal = str(request.get("goal") or "")[:1200]
    response = str(request.get("response") or "")[:6000]
    if not response.strip():
        return {"suggestions": []}
    try:
        result = await router_client.complete_for(model, "suggestions", [{
            "role": "user", "content": (
                "根据本轮用户目标和 Atlas 回复，给出 2 到 3 条具体、互不重复的下一步建议。"
                "只返回 JSON 数组，每项是简短的中文可执行请求字符串，不要解释。\n"
                f"目标：{goal}\n回复：{response}"
            ),
        }], max_tokens=220, temperature=0.35)
        raw = str(getattr(result, "text", "")).strip()
        start, end = raw.find("["), raw.rfind("]")
        suggestions = json.loads(raw[start:end + 1]) if start >= 0 and end > start else []
        if not isinstance(suggestions, list):
            return {"suggestions": []}
        cleaned = [item.strip()[:180] for item in suggestions if isinstance(item, str) and item.strip()]
        return {"suggestions": cleaned[:3] if len(cleaned) >= 2 else []}
    except Exception as exc:  # Suggestions are optional and must not fail the completed run.
        raise HTTPException(status_code=502, detail="主动建议生成失败") from exc
