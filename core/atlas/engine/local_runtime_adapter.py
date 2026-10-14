"""Adapter for Atlas-managed llama.cpp models.

The Hermes local-runtime package is no longer an Atlas dependency. Until Atlas has
its own llama.cpp installer and supervisor, these endpoints report an explicit
unsupported state. Ollama routes in :mod:`atlas.api.local_models_router` remain
independent and available.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


UNSUPPORTED_REASON = (
    "Atlas no longer bundles the Hermes-managed llama.cpp runtime. "
    "Use a configured Atlas model provider or the local Ollama integration."
)


class LocalRuntimeError(RuntimeError):
    """Adapter failure with an HTTP status the router maps 1:1."""

    status_code = 502

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(LocalRuntimeError):
    status_code = 404


class InvalidRequestError(LocalRuntimeError):
    status_code = 400


class ConflictError(LocalRuntimeError):
    status_code = 409


@dataclass
class ActivationReport:
    """Result shape retained for the existing local-model API."""

    model_id: str
    ok: bool = False
    base_url: str | None = None
    server_ok: bool = False
    model_ready: bool = False
    tool_call_ok: bool = False
    detail: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id, "ok": self.ok, "base_url": self.base_url,
            "server_ok": self.server_ok, "model_ready": self.model_ready,
            "tool_call_ok": self.tool_call_ok, "detail": self.detail,
            "diagnostics": self.diagnostics, "duration_ms": self.duration_ms,
            "supported": False,
        }


class LocalRuntimeAdapter:
    """Expose an explicit unsupported response instead of importing Hermes at runtime."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = dict(config or {})

    def configure(self, update: dict[str, Any]) -> dict[str, Any]:
        self.config.update(update)
        return self.status()

    @staticmethod
    def _unsupported() -> LocalRuntimeError:
        return LocalRuntimeError(UNSUPPORTED_REASON, status_code=501)

    def status(self) -> dict[str, Any]:
        return {
            "supported": False,
            "enabled": False,
            "backend": None,
            "base_url": None,
            "models_dir": None,
            "server": {"running": False, "managed": False},
            "models": [],
            "detail": UNSUPPORTED_REASON,
        }

    def hardware(self) -> dict[str, Any]:
        return {"supported": False, "detail": UNSUPPORTED_REASON}

    def backends(self) -> dict[str, Any]:
        return {"supported": False, "backends": [], "detail": UNSUPPORTED_REASON}

    def catalog(self) -> dict[str, Any]:
        return {"supported": False, "models": [], "detail": UNSUPPORTED_REASON}

    def search_hf(self, query: str, limit: int = 20) -> dict[str, Any]:
        if not query.strip():
            return {"supported": False, "hits": [], "detail": UNSUPPORTED_REASON}
        raise self._unsupported()

    def search_repo_files(self, repo: str) -> dict[str, Any]:
        raise self._unsupported()

    def install_runtime(self, backend: str | None = None) -> dict[str, Any]:
        raise self._unsupported()

    def download(self, model_id: str, files: dict[str, Any] | None = None) -> dict[str, Any]:
        raise self._unsupported()

    def pause_download(self, job_id: str) -> dict[str, Any]:
        raise self._unsupported()

    def resume_download(self, job_id: str) -> dict[str, Any]:
        raise self._unsupported()

    def jobs_list(self) -> dict[str, Any]:
        return {"supported": False, "jobs": [], "detail": UNSUPPORTED_REASON}

    def job(self, job_id: str) -> dict[str, Any]:
        raise NotFoundError(f"Unknown local-runtime job {job_id}", status_code=404)

    def delete_model(self, model_id: str) -> dict[str, Any]:
        raise self._unsupported()

    def sideload(self, gguf_path: str) -> dict[str, Any]:
        raise self._unsupported()

    def start_server(self, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
        raise self._unsupported()

    def stop_server(self) -> dict[str, Any]:
        raise self._unsupported()

    def eject(self, model_id: str) -> dict[str, Any]:
        raise self._unsupported()

    def staged_model_ids(self) -> list[str]:
        return []

    def activate(self, model_id: str) -> ActivationReport:
        return ActivationReport(model_id=model_id, diagnostics=[UNSUPPORTED_REASON])

    def diagnostics(self, job_id: str | None = None) -> dict[str, Any]:
        return {"supported": False, "job": None, "detail": UNSUPPORTED_REASON}
