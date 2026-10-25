"""Atlas REST surface for the managed local model runtime (``/api/local/models/*``).

The 12 endpoint groups of integration-map §5 / r6 §7, each a thin pass-through to the
singleton :class:`~atlas.engine.local_runtime_adapter.LocalRuntimeAdapter` (which in
turn delegates to the pinned Hermes fork's ``hermes_cli.local_runtime`` — no runtime
logic lives here). Long tasks (runtime install, model downloads) follow the hermes
job concept: the POST returns ``{job_id}`` and clients poll ``/jobs/{job_id}``;
``/download/pause`` + ``/download/resume`` ride the same resumable transfer.

Integration note for the owner of ``atlas/server.py``::

    from atlas.api.local_models_router import router as local_models_router
    app.include_router(local_models_router)

OriginGuard: the whole ``atlas.server`` app sits behind the ``OriginGuard`` ASGI
middleware; the ``_require_trusted_origin`` dependency re-applies the same rule so the
router stays safe when mounted standalone (tests, tooling).
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.engine.local_runtime_adapter import (
    LocalRuntimeAdapter,
    LocalRuntimeError,
)
from atlas.origin_guard import TOKEN_HEADER, is_trusted
from atlas.config import load_user_settings, save_user_settings

router = APIRouter(tags=["local-models"])

_adapter = LocalRuntimeAdapter()

# Ollama access is fixed to the local IPv4 loopback daemon. Callers cannot
# provide a host, proxy, or redirect target.
_OLLAMA_BASE = "http://127.0.0.1:11434"
_OLLAMA_OPENAI_BASE = f"{_OLLAMA_BASE}/v1"
_OLLAMA_PULL_JOBS: dict[str, dict[str, Any]] = {}
_OLLAMA_PULL_TASKS: set[asyncio.Task[None]] = set()
_LLAMA_PROCESS: subprocess.Popen | None = None
_LLAMA_LOCK = threading.Lock()


def get_adapter() -> LocalRuntimeAdapter:
    """The router's singleton adapter (tests replace it via :func:`set_adapter`)."""
    return _adapter


def set_adapter(adapter: LocalRuntimeAdapter) -> None:
    """Swap the singleton (tests inject a stub; production wiring never calls this)."""
    global _adapter
    _adapter = adapter


def _require_trusted_origin(request: Request) -> None:
    """Mirror of the app-level OriginGuard rule for standalone mounts."""
    trusted = is_trusted(
        request.headers.get("origin"),
        request.headers.get(TOKEN_HEADER),
        fetch_site=request.headers.get("sec-fetch-site"),
    )
    if not trusted:
        raise HTTPException(status_code=403, detail="Requests from this origin are not allowed")


class RuntimeInstallBody(BaseModel):
    backend: str | None = None   # None/auto → detect from this machine


class DownloadBody(BaseModel):
    model_id: str
    files: dict[str, Any] | None = None   # {"repo": str, "paths": [str]} for browsed HF GGUFs


class JobIdBody(BaseModel):
    job_id: str


class ServerActionBody(BaseModel):
    action: str                 # "stop" | "start"


class SideloadBody(BaseModel):
    path: str                   # absolute path to a .gguf on this machine


class ActivateBody(BaseModel):
    model_id: str               # exact variant id (a staged .gguf stem)


class EjectBody(BaseModel):
    model_id: str


class OllamaPullBody(BaseModel):
    name: str


class OllamaActivateBody(BaseModel):
    name: str


class LlamaConfigBody(BaseModel):
    binary_path: str | None = None
    model_path: str | None = None
    port: int | None = None


def _llama_config() -> dict[str, Any]:
    raw = load_user_settings().get("llama_cpp") or {}
    return raw if isinstance(raw, dict) else {}


def _llama_status() -> dict[str, Any]:
    cfg = _llama_config()
    process_running = _LLAMA_PROCESS is not None and _LLAMA_PROCESS.poll() is None
    port = int(cfg.get("port") or 8080)
    healthy = False
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.5,
                             trust_env=False, follow_redirects=False)
        healthy = response.status_code == 200
    except httpx.HTTPError:
        pass
    return {"binary_path": str(cfg.get("binary_path") or ""),
            "model_path": str(cfg.get("model_path") or ""), "port": port,
            "running": process_running or healthy, "managed": process_running,
            "healthy": healthy, "base_url": f"http://127.0.0.1:{port}/v1"}


@router.get("/api/local/models/llama/status", dependencies=[Depends(_require_trusted_origin)])
def llama_status() -> dict[str, Any]:
    return _llama_status()


@router.put("/api/local/models/llama/config", dependencies=[Depends(_require_trusted_origin)])
def llama_configure(body: LlamaConfigBody) -> dict[str, Any]:
    settings = load_user_settings()
    cfg = _llama_config()
    if body.binary_path is not None:
        binary = Path(body.binary_path).expanduser()
        if not binary.is_file():
            raise HTTPException(status_code=422, detail="llama-server 可执行文件不存在。")
        cfg["binary_path"] = str(binary.resolve())
    if body.model_path is not None:
        model = Path(body.model_path).expanduser()
        if not model.is_file() or model.suffix.lower() != ".gguf":
            raise HTTPException(status_code=422, detail="模型路径必须指向已存在的 GGUF 文件。")
        cfg["model_path"] = str(model.resolve())
    if body.port is not None:
        if not 1 <= body.port <= 65535:
            raise HTTPException(status_code=422, detail="端口必须在 1 到 65535 之间。")
        cfg["port"] = body.port
    settings["llama_cpp"] = cfg
    save_user_settings(settings)
    return _llama_status()


@router.post("/api/local/models/llama/start", dependencies=[Depends(_require_trusted_origin)])
def llama_start() -> dict[str, Any]:
    global _LLAMA_PROCESS
    cfg = _llama_config()
    binary, model = Path(str(cfg.get("binary_path") or "")), Path(str(cfg.get("model_path") or ""))
    if not binary.is_file() or not model.is_file():
        raise HTTPException(status_code=422, detail="请先配置存在的 llama-server 程序和 GGUF 模型文件。")
    with _LLAMA_LOCK:
        if _LLAMA_PROCESS is not None and _LLAMA_PROCESS.poll() is None:
            return _llama_status()
        port = int(cfg.get("port") or 8080)
        command = [str(binary), "--model", str(model), "--host", "127.0.0.1", "--port", str(port), "--ctx-size", "8192"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            _LLAMA_PROCESS = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                              close_fds=True, creationflags=flags)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"启动 llama-server 失败：{exc}") from exc
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = _llama_status()
        if status["healthy"]:
            return status
        if _LLAMA_PROCESS is None or _LLAMA_PROCESS.poll() is not None:
            break
        time.sleep(0.2)
    if _LLAMA_PROCESS is not None and _LLAMA_PROCESS.poll() is not None:
        exit_code = _LLAMA_PROCESS.returncode
        _LLAMA_PROCESS = None
        raise HTTPException(status_code=502,
                            detail=f"llama-server 启动后立即退出（exit code {exit_code}）。请检查本机二进制和模型文件。")
    return _llama_status()


@router.post("/api/local/models/llama/stop", dependencies=[Depends(_require_trusted_origin)])
def llama_stop() -> dict[str, Any]:
    global _LLAMA_PROCESS
    with _LLAMA_LOCK:
        process = _LLAMA_PROCESS
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=4)
        _LLAMA_PROCESS = None
    return _llama_status()


@router.post("/api/local/models/llama/activate", dependencies=[Depends(_require_trusted_origin)])
def llama_activate(services: AppServices = Depends(get_app_services)) -> dict[str, Any]:
    status = _llama_status()
    if not status["healthy"]:
        raise HTTPException(status_code=409, detail="请先启动并等待 llama.cpp 服务健康。")
    cfg = _llama_config()
    name = Path(str(cfg.get("model_path") or "model.gguf")).stem
    model_id = f"llama-cpp:{name}"
    manager = _safe_model_manager(services)
    existing = next((item for item in manager.list_models() if str(item.get("id")) == model_id), None)
    if existing is not None:
        if str(existing.get("base_url") or "").rstrip("/") != status["base_url"].rstrip("/"):
            manager.update_model(model_id, {"base_url": status["base_url"]})
        return {"id": model_id, "added": False, "name": name}
    manager.add_model({"id": model_id, "name": name, "provider": "llama-cpp",
                       "litellm_model": f"llama-cpp/{name}", "base_url": status["base_url"],
                       "local_only": True, "category": "local"})
    return {"id": model_id, "added": True, "name": name}


def _guard(fn, *args, **kwargs):
    """Run an adapter call, mapping LocalRuntimeError.status_code onto the HTTP error."""
    try:
        return fn(*args, **kwargs)
    except LocalRuntimeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _validate_ollama_name(value: str) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 256 or any(ord(char) < 32 for char in name):
        raise HTTPException(status_code=422, detail="Ollama 模型名不能为空且不得超过 256 个字符。")
    return name


async def _ollama_tags() -> list[dict[str, Any]]:
    """Read installed tags from the fixed local Ollama API, without proxy/redirects."""
    try:
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(8.0, connect=3.0),
        ) as client:
            response = await client.get(f"{_OLLAMA_BASE}/api/tags")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="无法连接本机 Ollama（127.0.0.1:11434）。") from exc
    if response.is_redirect:
        raise HTTPException(status_code=502, detail="本机 Ollama 返回重定向，已拒绝连接其他地址。")
    if response.status_code >= 400:
        raise HTTPException(status_code=503, detail=f"本机 Ollama 返回 HTTP {response.status_code}。")
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="本机 Ollama 返回了无效 JSON。") from exc
    rows = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="本机 Ollama 响应缺少 models 列表。")
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get("name") or row.get("model"), str)]


def _safe_model_manager(services: AppServices) -> Any:
    manager = services.model_mgr
    if manager is None:
        from atlas import server as atlas_server

        manager = atlas_server.model_mgr
    if manager is None:
        raise HTTPException(status_code=503, detail="Atlas 模型路由当前不可用。")
    return manager


async def _run_ollama_pull(job_id: str, name: str) -> None:
    job = _OLLAMA_PULL_JOBS[job_id]
    job.update(status="connecting", detail="正在连接本机 Ollama…")
    seen = False
    try:
        timeout = httpx.Timeout(180.0, connect=5.0, write=15.0, pool=5.0)
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=timeout,
        ) as client:
            async with client.stream(
                "POST",
                f"{_OLLAMA_BASE}/api/pull",
                json={"name": name, "stream": True},
            ) as response:
                if response.is_redirect:
                    raise RuntimeError("本机 Ollama 返回重定向，已拒绝连接其他地址。")
                if response.status_code >= 400:
                    await response.aread()
                    raise RuntimeError(f"本机 Ollama 返回 HTTP {response.status_code}。")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    seen = True
                    try:
                        event = json.loads(line)
                    except ValueError as exc:
                        raise RuntimeError("本机 Ollama 返回了无效下载进度。") from exc
                    if not isinstance(event, dict):
                        continue
                    if event.get("error"):
                        raise RuntimeError(str(event["error"])[:500])
                    total = event.get("total")
                    completed = event.get("completed")
                    percent = None
                    if isinstance(total, (int, float)) and total > 0 and isinstance(completed, (int, float)):
                        percent = min(100, max(0, int(completed * 100 / total)))
                    job.update(
                        status="downloading",
                        detail=str(event.get("status") or "正在下载")[:160],
                        percent=percent,
                        completed=completed if isinstance(completed, (int, float)) else None,
                        total=total if isinstance(total, (int, float)) else None,
                    )
        if not seen:
            raise RuntimeError("本机 Ollama 未返回下载结果。")
        job.update(status="completed", detail="模型已下载。", percent=100)
    except Exception as exc:  # noqa: BLE001 — report local daemon errors to the initiating UI
        job.update(status="failed", detail=str(exc)[:500])


# ── read models ──────────────────────────────────────────────
@router.get("/api/local/models/status", dependencies=[Depends(_require_trusted_origin)])
def local_models_status(adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.status)


@router.get("/api/local/models/hardware", dependencies=[Depends(_require_trusted_origin)])
def local_models_hardware(adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.hardware)


@router.get("/api/local/models/backends", dependencies=[Depends(_require_trusted_origin)])
def local_models_backends(adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.backends)


@router.get("/api/local/models/catalog", dependencies=[Depends(_require_trusted_origin)])
def local_models_catalog(adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.catalog)


@router.get("/api/local/models/search", dependencies=[Depends(_require_trusted_origin)])
def local_models_search(q: str, limit: int = 20,
                        adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.search_hf, q, limit)


@router.get("/api/local/models/search/files", dependencies=[Depends(_require_trusted_origin)])
def local_models_search_files(repo: str, adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.search_repo_files, repo)


# ── long jobs ────────────────────────────────────────────────
@router.post("/api/local/models/runtime/install", dependencies=[Depends(_require_trusted_origin)])
def local_models_runtime_install(body: RuntimeInstallBody,
                                 adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.install_runtime, body.backend)


@router.post("/api/local/models/download", dependencies=[Depends(_require_trusted_origin)])
def local_models_download(body: DownloadBody, adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.download, body.model_id, body.files)


@router.post("/api/local/models/download/pause", dependencies=[Depends(_require_trusted_origin)])
def local_models_download_pause(body: JobIdBody, adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.pause_download, body.job_id)


@router.post("/api/local/models/download/resume", dependencies=[Depends(_require_trusted_origin)])
def local_models_download_resume(body: JobIdBody, adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.resume_download, body.job_id)


@router.get("/api/local/models/jobs", dependencies=[Depends(_require_trusted_origin)])
def local_models_jobs(adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.jobs_list)


@router.get("/api/local/models/jobs/{job_id}", dependencies=[Depends(_require_trusted_origin)])
def local_models_job(job_id: str, adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.job, job_id)


@router.delete("/api/local/models/models/{model_id}", dependencies=[Depends(_require_trusted_origin)])
def local_models_delete(model_id: str, adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.delete_model, model_id)


@router.post("/api/local/models/sideload", dependencies=[Depends(_require_trusted_origin)])
def local_models_sideload(body: SideloadBody, adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.sideload, body.path)


# ── server lifecycle / activation ────────────────────────────
@router.post("/api/local/models/server", dependencies=[Depends(_require_trusted_origin)])
def local_models_server(body: ServerActionBody, adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    action = (body.action or "").strip().lower()
    if action == "start":
        return _guard(adapter.start_server)
    if action == "stop":
        return _guard(adapter.stop_server)
    raise HTTPException(status_code=400, detail="action must be 'stop' or 'start'")


@router.post("/api/local/models/activate", dependencies=[Depends(_require_trusted_origin)])
def local_models_activate(body: ActivateBody, adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    """The activation gate: runs synchronously (load + touch + tool-call probe) and
    returns the full ActivationReport. Promoting to the Atlas default model is the
    caller's decision, allowed only when ``ok`` is true."""
    return _guard(adapter.activate, body.model_id).to_dict()


@router.post("/api/local/models/eject", dependencies=[Depends(_require_trusted_origin)])
def local_models_eject(body: EjectBody, adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.eject, body.model_id)


@router.get("/api/local/models/diagnostics", dependencies=[Depends(_require_trusted_origin)])
def local_models_diagnostics(job_id: str | None = None,
                             adapter: LocalRuntimeAdapter = Depends(get_adapter)):
    return _guard(adapter.diagnostics, job_id)


# ── Ollama-local model discovery / pull / route registration ────────────────
@router.get("/api/local/models/ollama/tags", dependencies=[Depends(_require_trusted_origin)])
async def ollama_local_tags() -> dict[str, Any]:
    """List models already installed in the default local Ollama instance."""
    rows = await _ollama_tags()
    return {
        "models": [
            {
                "name": row.get("name") or row.get("model"),
                "size": row.get("size"),
                "modified_at": row.get("modified_at"),
                "details": row.get("details") if isinstance(row.get("details"), dict) else {},
            }
            for row in rows
        ],
        "base_url": _OLLAMA_BASE,
    }


@router.post("/api/local/models/ollama/pull", dependencies=[Depends(_require_trusted_origin)])
async def ollama_local_pull(body: OllamaPullBody) -> dict[str, str]:
    """Start an explicit Ollama pull requested by the user; progress is polled by job id."""
    name = _validate_ollama_name(body.name)
    if any(
        job.get("name") == name and job.get("status") in {"pending", "connecting", "downloading"}
        for job in _OLLAMA_PULL_JOBS.values()
    ):
        raise HTTPException(status_code=409, detail="该 Ollama 模型正在下载。")

    while len(_OLLAMA_PULL_JOBS) >= 64:
        stale_id = next((
            key for key, job in _OLLAMA_PULL_JOBS.items()
            if job.get("status") in {"completed", "failed"}
        ), None)
        if stale_id is None:
            raise HTTPException(status_code=429, detail="本机 Ollama 下载任务过多，请稍后再试。")
        _OLLAMA_PULL_JOBS.pop(stale_id, None)

    job_id = uuid.uuid4().hex
    _OLLAMA_PULL_JOBS[job_id] = {
        "job_id": job_id,
        "name": name,
        "status": "pending",
        "detail": "等待连接 Ollama…",
        "percent": None,
        "completed": None,
        "total": None,
    }
    task = asyncio.create_task(_run_ollama_pull(job_id, name))
    _OLLAMA_PULL_TASKS.add(task)
    task.add_done_callback(_OLLAMA_PULL_TASKS.discard)
    return {"job_id": job_id, "name": name}


@router.get("/api/local/models/ollama/jobs/{job_id}", dependencies=[Depends(_require_trusted_origin)])
async def ollama_local_pull_job(job_id: str) -> dict[str, Any]:
    job = _OLLAMA_PULL_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ollama 下载任务不存在或已过期。")
    return dict(job)


@router.post("/api/local/models/ollama/activate", dependencies=[Depends(_require_trusted_origin)])
async def ollama_local_activate(
    body: OllamaActivateBody,
    services: AppServices = Depends(get_app_services),
) -> dict[str, Any]:
    """Register an installed Ollama tag in the route resolver's local-only path."""
    name = _validate_ollama_name(body.name)
    rows = await _ollama_tags()
    installed = {str(row.get("name") or row.get("model") or "") for row in rows}
    if name not in installed:
        raise HTTPException(status_code=404, detail="该模型尚未安装在本机 Ollama。")

    model_id = f"ollama-local:{name}"
    manager = _safe_model_manager(services)
    existing = next(
        (item for item in manager.list_models() if str(item.get("id")) == model_id),
        None,
    )
    if existing is not None:
        if (str(existing.get("provider")) != "ollama"
                or str(existing.get("litellm_model")) != f"ollama/{name}"
                or str(existing.get("base_url")) != _OLLAMA_OPENAI_BASE
                or existing.get("local_only") is not True):
            raise HTTPException(status_code=409, detail="Atlas 中已有同名但路由不同的模型条目。")
        return {"id": model_id, "name": name, "added": False, "provider": "ollama"}

    try:
        manager.add_model({
            "id": model_id,
            "name": name,
            "provider": "ollama",
            "litellm_model": f"ollama/{name}",
            "base_url": _OLLAMA_OPENAI_BASE,
            "local_only": True,
            "category": "local",
        })
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": model_id, "name": name, "added": True, "provider": "ollama"}
