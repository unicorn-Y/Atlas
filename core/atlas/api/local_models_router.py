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

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from atlas.engine.local_runtime_adapter import (
    LocalRuntimeAdapter,
    LocalRuntimeError,
)
from atlas.origin_guard import TOKEN_HEADER, is_trusted

router = APIRouter(tags=["local-models"])

_adapter = LocalRuntimeAdapter()


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


def _guard(fn, *args, **kwargs):
    """Run an adapter call, mapping LocalRuntimeError.status_code onto the HTTP error."""
    try:
        return fn(*args, **kwargs)
    except LocalRuntimeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
