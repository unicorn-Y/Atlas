"""W6 router contract tests — the full /api/local/models/* surface on a stub adapter.

Lane discipline: a bare FastAPI app with ONLY the local models router (no server.py),
the singleton adapter replaced by a recording stub, so every endpoint's pass-through,
error mapping and job_id shape is verified without hermes or llama.cpp.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import atlas.api.local_models_router as router_module
from atlas.engine.local_runtime_adapter import (
    ActivationReport,
    ConflictError,
    InvalidRequestError,
    LocalRuntimeError,
    NotFoundError,
)


class StubAdapter:
    """Records calls; canned payloads per endpoint group."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.config: dict[str, Any] = {}
        self.jobs: list[dict[str, Any]] = [{
            "job_id": "job1", "kind": "model-download", "target": "Test (Q4_K_M)",
            "model_id": "test", "status": "running", "phase": "downloading",
            "detail": "", "total_bytes": 1000, "done_bytes": 250, "percent": 25,
            "bytes_per_sec": 10.0, "eta_seconds": 75, "ranges": {},
            "can_pause": True, "can_resume": False, "pause_requested": False,
            "started_at": 1.0, "error": None,
        }]

    def _call(self, name: str, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        return None

    # read models
    def status(self) -> dict:
        self._call("status")
        return {"enabled": True, "runtime_backend": "cpu", "models": [], "server_running": False}

    def hardware(self) -> dict:
        self._call("hardware")
        return {"uma": False, "vram_total_bytes": 0, "ram_total_bytes": 1}

    def backends(self) -> dict:
        self._call("backends")
        return {"backends": [{"backend": "cpu", "available": True}], "recommended": "cpu"}

    def catalog(self) -> dict:
        self._call("catalog")
        return {"models": [{"id": "test", "fits": True}]}

    def search_hf(self, query: str, limit: int = 20) -> dict:
        self._call("search_hf", query, limit)
        return {"hits": [{"repo": f"org/{query}"}]}

    def search_repo_files(self, repo: str) -> dict:
        self._call("search_repo_files", repo)
        return {"files": [{"label": "Q4_K_M", "paths": ["q4.gguf"], "total_bytes": 1,
                           "fit": "fits-gpu"}]}

    # long jobs
    def install_runtime(self, backend: str | None = None) -> dict:
        self._call("install_runtime", backend)
        return {"job_id": "inst1", "backend": backend or "cpu", "tag": "b6000"}

    def download(self, model_id: str, files: dict | None = None) -> dict:
        self._call("download", model_id, files)
        if model_id == "have-it":
            return {"job_id": None, "already_downloaded": True, "model_id": "have-it"}
        if model_id == "nope":
            raise NotFoundError(f"unknown model {model_id}")
        return {"job_id": "dl1", "model_id": model_id}

    def pause_download(self, job_id: str) -> dict:
        self._call("pause_download", job_id)
        return {"ok": True, "paused": job_id == "job1"}

    def resume_download(self, job_id: str) -> dict:
        self._call("resume_download", job_id)
        return {"ok": True, "resumed": True}

    def jobs_list(self) -> dict:
        self._call("jobs_list")
        return {"jobs": self.jobs}

    def job(self, job_id: str) -> dict:
        self._call("job", job_id)
        for job in self.jobs:
            if job["job_id"] == job_id:
                return job
        raise NotFoundError("job not found")

    def delete_model(self, model_id: str) -> dict:
        self._call("delete_model", model_id)
        if model_id == "ghost":
            raise NotFoundError("model not found")
        return {"ok": True}

    def sideload(self, gguf_path: str) -> dict:
        self._call("sideload", gguf_path)
        if not gguf_path.endswith(".gguf"):
            raise InvalidRequestError("Pick a .gguf model file", status_code=422)
        return {"ok": True, "model_id": "sideloaded"}

    # server lifecycle / activation
    def start_server(self, cfg: dict | None = None) -> dict:
        self._call("start_server", cfg)
        self.config.update(cfg or {})
        return {"ok": True, "base_url": "http://127.0.0.1:18434/v1"}

    def stop_server(self) -> dict:
        self._call("stop_server")
        if self.config.get("foreign_owner"):
            raise ConflictError("Another process owns this server")
        return {"ok": True, "action": "stop"}

    def activate(self, model_id: str) -> ActivationReport:
        self._call("activate", model_id)
        return ActivationReport(
            model_id=model_id, ok=model_id == "good",
            base_url="http://127.0.0.1:18434/v1", server_ok=True, model_ready=True,
            tool_call_ok=model_id == "good",
            diagnostics=[] if model_id == "good" else ["the model does not support tool calling"],
            detail={"probe": {"ok": model_id == "good"}}, duration_ms=5)

    def eject(self, model_id: str) -> dict:
        self._call("eject", model_id)
        return {"ok": True}

    def diagnostics(self, job_id: str | None = None) -> dict:
        self._call("diagnostics", job_id)
        return {"server": {"running": False}, "hints": [], "job": None}


@pytest.fixture()
def client():
    stub = StubAdapter()
    router_module.set_adapter(stub)
    app = FastAPI()
    app.include_router(router_module.router)
    yield TestClient(app), stub
    router_module.set_adapter(router_module.LocalRuntimeAdapter())


def test_get_read_group(client):
    http, stub = client
    assert http.get("/api/local/models/status").json()["enabled"] is True
    assert http.get("/api/local/models/hardware").json()["ram_total_bytes"] == 1
    assert http.get("/api/local/models/backends").json()["recommended"] == "cpu"
    assert http.get("/api/local/models/catalog").json()["models"][0]["id"] == "test"
    assert http.get("/api/local/models/search", params={"q": "qwen"}).json() == \
        {"hits": [{"repo": "org/qwen"}]}
    files = http.get("/api/local/models/search/files", params={"repo": "org/m"}).json()
    assert files["files"][0]["fit"] == "fits-gpu"
    names = [name for name, _, _ in stub.calls]
    assert names == ["status", "hardware", "backends", "catalog",
                     "search_hf", "search_repo_files"]


def test_search_files_declared_before_any_conflict(client):
    http, _ = client
    assert http.get("/api/local/models/search/files", params={"repo": "r"}).status_code == 200


def test_job_group_shapes(client):
    http, stub = client
    out = http.post("/api/local/models/runtime/install", json={}).json()
    assert out == {"job_id": "inst1", "backend": "cpu", "tag": "b6000"}
    out = http.post("/api/local/models/runtime/install", json={"backend": "vulkan"}).json()
    assert out == {"job_id": "inst1", "backend": "vulkan", "tag": "b6000"}

    out = http.post("/api/local/models/download", json={"model_id": "test"}).json()
    assert out == {"job_id": "dl1", "model_id": "test"}
    out = http.post("/api/local/models/download",
                    json={"model_id": "have-it"}).json()
    assert out["already_downloaded"] is True and out["job_id"] is None
    assert http.post("/api/local/models/download",
                     json={"model_id": "nope"}).status_code == 404
    browsed = {"model_id": "x", "files": {"repo": "org/r", "paths": ["a.gguf"]}}
    assert http.post("/api/local/models/download", json=browsed).json()["job_id"] == "dl1"

    assert http.post("/api/local/models/download/pause",
                     json={"job_id": "job1"}).json() == {"ok": True, "paused": True}
    assert http.post("/api/local/models/download/pause",
                     json={"job_id": "other"}).json() == {"ok": True, "paused": False}
    assert http.post("/api/local/models/download/resume",
                     json={"job_id": "job1"}).json() == {"ok": True, "resumed": True}

    assert http.get("/api/local/models/jobs").json()["jobs"][0]["percent"] == 25
    assert http.get("/api/local/models/jobs/job1").json()["phase"] == "downloading"
    assert http.get("/api/local/models/jobs/ghost").status_code == 404
    assert http.delete("/api/local/models/models/test").json() == {"ok": True}
    assert http.delete("/api/local/models/models/ghost").status_code == 404


def test_sideload_server_activate_eject_diagnostics(client):
    http, stub = client
    assert http.post("/api/local/models/sideload",
                     json={"path": "C:/m/a.gguf"}).json()["ok"] is True
    assert http.post("/api/local/models/sideload",
                     json={"path": "C:/m/a.txt"}).status_code == 422

    assert http.post("/api/local/models/server",
                     json={"action": "start"}).json()["base_url"].endswith("/v1")
    assert http.post("/api/local/models/server",
                     json={"action": "stop"}).json() == {"ok": True, "action": "stop"}
    assert http.post("/api/local/models/server",
                     json={"action": "dance"}).status_code == 400

    report = http.post("/api/local/models/activate", json={"model_id": "good"}).json()
    assert report["ok"] is True and report["tool_call_ok"] is True
    bad = http.post("/api/local/models/activate", json={"model_id": "toolless"}).json()
    assert bad["ok"] is False and "tool call" in bad["diagnostics"][0]

    assert http.post("/api/local/models/eject", json={"model_id": "m"}).json() == {"ok": True}
    diag = http.get("/api/local/models/diagnostics", params={"job_id": "job1"}).json()
    assert diag["server"] == {"running": False}
    assert ("diagnostics", ("job1",), {}) in stub.calls


def test_error_mapping_uses_adapter_status(client):
    http, stub = client
    stub.config["foreign_owner"] = True
    response = http.post("/api/local/models/server", json={"action": "stop"})
    assert response.status_code == 409
    assert "owns this server" in response.json()["detail"]


def test_origin_guard_rule_applies_standalone(client):
    http, _ = client
    assert http.get("/api/local/models/status",
                    headers={"Origin": "https://evil.example"}).status_code == 403
    assert http.get("/api/local/models/status").status_code == 200


def test_router_needs_no_hermes_at_import():
    """The router module is import-safe without a running runtime (lazy hermes imports)."""
    import importlib

    module = importlib.import_module("atlas.api.local_models_router")
    assert callable(module.get_adapter)
    assert isinstance(module.get_adapter(), router_module.LocalRuntimeAdapter)


def test_local_runtime_error_carries_status():
    assert LocalRuntimeError("boom").status_code == 502
    assert InvalidRequestError("bad").status_code == 400
    assert NotFoundError("gone").status_code == 404
    assert ConflictError("busy").status_code == 409
