"""W6 adapter contract tests — LocalRuntimeAdapter over the pinned hermes local_runtime.

No real llama.cpp is ever started: an in-process stub HTTP server speaks just enough
llama-server (/health /models /props /v1/chat/completions /models/load /models/unload)
to exercise the probe/activate gate and the shared-server HTTP paths (same pattern as
hermes's tests/hermes_cli/test_local_runtime.py). Long downloads are stubbed at the
``pm.downloader.Download`` seam. Hermes module imports are real; a cold subprocess
regression covers concurrent imports without starting a model server.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import atlas.engine.local_runtime_adapter as lra
from atlas.engine.local_runtime_adapter import (
    ATLAS_PROBE_NONCE,
    ATLAS_PROBE_TOOL,
    ActivationReport,
    InvalidRequestError,
    LocalRuntimeAdapter,
    NotFoundError,
    _JobRegistry,
    diagnose_windows_runtime,
)

HERMES_MODULES = (
    "binaries", "bootstrap", "supervisor", "hardware", "devices", "detect", "endpoint",
    "estimator", "gguf", "context_policy", "presets", "catalog", "hf_browse", "growth",
    "load_progress", "capabilities", "processes", "recovery",
)


# ── hermes import surface (option A: in-process, editable install) ──
@pytest.mark.parametrize("module", HERMES_MODULES)
def test_hermes_local_runtime_module_imports(module):
    assert importlib.import_module(f"hermes_cli.local_runtime.{module}") is not None


def test_hermes_local_runtime_public_surface():
    from hermes_cli import local_runtime as lr

    for name in ("ensure_local_runtime", "shutdown_local_runtime", "ensure_engine",
                 "installed_engine", "resolve_backend", "select_backend", "probe_budget",
                 "resolve_llamacpp_endpoint", "physics_check", "read_gguf_header"):
        assert hasattr(lr, name), name
    from hermes_cli.local_runtime import bootstrap, devices

    assert callable(bootstrap.staged_models) and callable(bootstrap.refresh_local_runtime)
    assert callable(devices.probe_devices)


def test_cold_parallel_runtime_endpoint_imports_are_safe(tmp_path):
    """Exercise the first Hermes imports as concurrent API worker threads in a new process."""
    script = r"""
import concurrent.futures
import importlib
import sys
import threading
import types

from atlas.engine.local_runtime_adapter import LocalRuntimeAdapter, _mod

real_import_module = importlib.import_module
def require_host_imports_first(name, package=None):
    if name.startswith("hermes_cli.local_runtime."):
        required = {
            "hermes_platform.host",
            "hermes_platform.host.facts",
            "hermes_platform.host.products",
        }
        missing = required - sys.modules.keys()
        assert not missing, f"host imports not preloaded: {missing}"
    return real_import_module(name, package)

importlib.import_module = require_host_imports_first

adapter = LocalRuntimeAdapter()
barrier = threading.Barrier(12)
operations = (
    adapter.backends,
    adapter.status,
    adapter.hardware,
    lambda: _mod("hermes_cli.local_runtime.catalog"),
    lambda: adapter.search_hf(""),
)

def call(operation):
    barrier.wait(timeout=10)
    return operation()

with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
    futures = [pool.submit(call, operations[index % len(operations)]) for index in range(12)]
    results = [future.result(timeout=20) for future in futures]

assert all(isinstance(item, (dict, types.ModuleType)) for item in results)
assert all("backends" in results[index] for index in (0, 5, 10))
assert all("models_dir" in results[index] for index in (1, 6, 11))
assert all("engine_devices" in results[index] for index in (2, 7))
assert all(getattr(results[index], "CATALOG", None) for index in (3, 8))
assert all(results[index] == {"hits": []} for index in (4, 9))
print("cold parallel local-runtime calls completed")
"""
    isolated = tmp_path / "profile"
    isolated.mkdir()
    env = os.environ.copy()
    for key, directory in {
        "HOME": isolated / "home",
        "USERPROFILE": isolated / "userprofile",
        "APPDATA": isolated / "appdata",
        "LOCALAPPDATA": isolated / "localappdata",
        "HERMES_HOME": isolated / "hermes",
        "ATLAS_DATA_DIR": isolated / "atlas",
    }.items():
        directory.mkdir(parents=True, exist_ok=True)
        env[key] = str(directory)
    for key in tuple(env):
        if key.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIALS")):
            env.pop(key)

    try:
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
            env=env, capture_output=True, text=True, timeout=30, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"cold parallel local-runtime imports did not finish: {exc}")
    detail = (result.stdout + "\n" + result.stderr)[-2000:]
    assert result.returncode == 0, detail
    assert "cold parallel local-runtime calls completed" in result.stdout, detail


def test_hermes_home_pinned_once(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    home = lra._ensure_hermes_home()
    assert os.environ["HERMES_HOME"] == str(home)
    assert (home / lra._HERMES_HOME_MARK).is_file()
    assert home.name == "local-runtime" and home.parent.name == "Atlas"
    # setdefault semantics: an existing HERMES_HOME always wins.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "operator-home"))
    assert lra._ensure_hermes_home() == tmp_path / "operator-home"


# ── stub llama-server ────────────────────────────────────────
class _StubHandler(BaseHTTPRequestHandler):
    props: dict = {}
    models: dict | None = None
    chat_answer = "Paris"
    tool_calls = True
    tool_args = json.dumps({"nonce": ATLAS_PROBE_NONCE})
    unloaded: list = []

    def _send(self, code: int, body) -> None:
        raw = (json.dumps(body) if isinstance(body, (dict, list)) else (body or "")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/health":
            self._send(200, {"status": "ok"})
        elif path == "/props":
            self._send(200, self.props)
        elif path == "/models":
            self._send(200, self.models if self.models is not None else {"data": []})
        else:
            self._send(404, {})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        if self.path == "/v1/chat/completions":
            if body.get("tools") and type(self).tool_calls:
                self._send(200, {"choices": [{"message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{"id": "call_1", "type": "function",
                                    "function": {"name": ATLAS_PROBE_TOOL,
                                                 "arguments": type(self).tool_args}}]}}]})
            else:
                self._send(200, {"choices": [{"message": {
                    "role": "assistant", "content": self.chat_answer}}]})
        elif self.path == "/models/load":
            for m in (self.models or {}).get("data", []):
                m.setdefault("status", {})["value"] = "loaded"
            self._send(200, {"success": True})
        elif self.path == "/models/unload":
            type(self).unloaded.append(body.get("model"))
            self._send(200, {"success": True})
        else:
            self._send(404, {})

    def log_message(self, *args):  # silence
        pass


@pytest.fixture
def stub_server():
    class Handler(_StubHandler):
        pass

    Handler.unloaded = []
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], Handler
    server.shutdown()


def _dead_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── probe_tool_call ──────────────────────────────────────────
def test_probe_ok_on_tool_call(stub_server):
    port, _ = stub_server
    probe = LocalRuntimeAdapter.probe_tool_call(f"http://127.0.0.1:{port}/v1", "k", "m")
    assert probe["ok"] is True
    assert probe["function_name"] == ATLAS_PROBE_TOOL
    assert probe["nonce_ok"] is True


def test_probe_fails_on_plain_text(stub_server):
    port, handler = stub_server
    handler.tool_calls = False
    probe = LocalRuntimeAdapter.probe_tool_call(f"http://127.0.0.1:{port}/v1", "k", "m")
    assert probe["ok"] is False
    assert "no tool_calls" in probe["reason"]


def test_probe_fails_on_broken_arguments(stub_server):
    port, handler = stub_server
    handler.tool_args = '{"nonce": "atlas-probe-ok"'  # unterminated JSON
    probe = LocalRuntimeAdapter.probe_tool_call(f"http://127.0.0.1:{port}/v1", "k", "m")
    assert probe["ok"] is False
    assert "not valid JSON" in probe["reason"]


def test_probe_fails_on_connection_refused():
    probe = LocalRuntimeAdapter.probe_tool_call(f"http://127.0.0.1:{_dead_port()}/v1", "k", "m",
                                                timeout_s=3)
    assert probe["ok"] is False
    assert "probe request failed" in probe["reason"]


# ── activate: the full gate ──────────────────────────────────
MODEL = "Test-3B-Q4_K_M"


@pytest.fixture
def shared_server_env(stub_server, monkeypatch):
    """Patch the hermes seams so the adapter serves from the stub (shared-server path)."""
    port, handler = stub_server
    handler.models = {"data": [{"id": MODEL, "status": {"value": "unloaded"}}]}
    import hermes_cli.local_runtime.bootstrap as bootstrap_mod
    import hermes_cli.local_runtime.endpoint as endpoint_mod

    monkeypatch.setattr(bootstrap_mod, "get_supervisor", lambda: None)
    monkeypatch.setattr(bootstrap_mod, "ensure_local_runtime", lambda config, force=False: None)
    monkeypatch.setattr(endpoint_mod, "managed_root", lambda: (f"http://127.0.0.1:{port}", "key"))
    return port, handler


def _adapter_with_staged(monkeypatch, ids: list[str]) -> LocalRuntimeAdapter:
    adapter = LocalRuntimeAdapter({"backend": "cpu", "enabled": True})
    monkeypatch.setattr(adapter, "staged_model_ids", lambda: list(ids))
    return adapter


def test_activate_full_flow(shared_server_env, monkeypatch):
    port, handler = shared_server_env
    adapter = _adapter_with_staged(monkeypatch, [MODEL])
    report = adapter.activate(MODEL)
    assert isinstance(report, ActivationReport)
    assert report.ok is True, report.diagnostics
    assert report.server_ok and report.model_ready and report.tool_call_ok
    assert report.base_url == f"http://127.0.0.1:{port}/v1"
    assert report.detail["probe"]["function_name"] == ATLAS_PROBE_TOOL
    assert report.to_dict()["ok"] is True


def test_activate_bounces_server_that_cannot_see_model(shared_server_env, monkeypatch):
    port, handler = shared_server_env
    adapter = _adapter_with_staged(monkeypatch, [MODEL])
    handler.models = {"data": []}  # router does not know the model yet

    def fake_bounce() -> bool:
        handler.models = {"data": [{"id": MODEL, "status": {"value": "unloaded"}}]}
        return True

    monkeypatch.setattr(adapter, "_bounce", fake_bounce)
    report = adapter.activate(MODEL)
    assert report.ok is True, report.diagnostics
    assert any("rescan" in step for step in report.detail.get("steps", []))


def test_activate_probe_failure_keeps_diagnosis(shared_server_env, monkeypatch):
    port, handler = shared_server_env
    handler.tool_calls = False  # health + generation fine, no tool calling
    adapter = _adapter_with_staged(monkeypatch, [MODEL])
    report = adapter.activate(MODEL)
    assert report.ok is False
    assert report.server_ok is True and report.model_ready is True
    assert report.tool_call_ok is False
    assert any("tool call" in d for d in report.diagnostics)


def test_activate_server_failure(shared_server_env, monkeypatch):
    import hermes_cli.local_runtime.endpoint as endpoint_mod

    monkeypatch.setattr(endpoint_mod, "managed_root", lambda: None)
    adapter = _adapter_with_staged(monkeypatch, [MODEL])
    report = adapter.activate(MODEL)
    assert report.ok is False and report.server_ok is False
    assert any("could not start" in d for d in report.diagnostics)


def test_activate_not_staged(monkeypatch):
    adapter = _adapter_with_staged(monkeypatch, [])
    report = adapter.activate(MODEL)
    assert report.ok is False
    assert any("not downloaded" in d for d in report.diagnostics)


# ── diagnose_windows_runtime ─────────────────────────────────
def test_diagnose_reports_missing_vc_redist(monkeypatch, tmp_path):
    (tmp_path / "llama-server.exe").write_bytes(b"MZ fake")
    monkeypatch.setattr(lra, "_launch_version_check", lambda exe, d: (False, "rc=126 module not found"))
    monkeypatch.setattr(lra, "_system_dll_names", lambda: set())
    out = diagnose_windows_runtime(tmp_path, windows=True)
    assert out["state"] == "missing-vc-redist"
    assert out["vc_redist"]["needed"] is True
    assert sorted(out["vc_redist"]["missing_dlls"]) == sorted(lra._VC_RUNTIME_DLLS)
    assert "Redistributable" in out["vc_redist"]["suggestion"]


def test_diagnose_no_redist_needed_when_dlls_present(monkeypatch, tmp_path):
    (tmp_path / "llama-server.exe").write_bytes(b"MZ fake")
    monkeypatch.setattr(lra, "_launch_version_check", lambda exe, d: (False, "rc=1 boom"))
    monkeypatch.setattr(lra, "_system_dll_names", lambda: set(lra._VC_RUNTIME_DLLS))
    out = diagnose_windows_runtime(tmp_path, windows=True)
    assert out["state"] == "launch-failed"
    assert out["vc_redist"]["needed"] is False
    assert out["vc_redist"]["suggestion"] is None


def test_diagnose_ok_launch(monkeypatch, tmp_path):
    (tmp_path / "llama-server.exe").write_bytes(b"MZ fake")
    monkeypatch.setattr(lra, "_launch_version_check", lambda exe, d: (True, "version: b6000"))
    out = diagnose_windows_runtime(tmp_path, windows=True)
    assert out == {**out, "state": "ok", "launch_ok": True}


def test_diagnose_missing_binary(tmp_path):
    out = diagnose_windows_runtime(tmp_path / "empty", windows=True)
    assert out["state"] == "launch-failed"
    assert "not found" in out["detail"]


@pytest.mark.skipif(os.name != "nt", reason="real Windows loader failure")
def test_diagnose_real_launch_failure_garbage_exe(tmp_path):
    (tmp_path / "llama-server.exe").write_bytes(b"this is not a windows executable")
    out = diagnose_windows_runtime(tmp_path, windows=True)
    assert out["launch_ok"] is False
    assert out["state"] in ("launch-failed", "missing-vc-redist")
    assert out["detail"]


# ── status / hardware / backends / catalog (real hermes layer) ──
def test_status_reports_staged_dir_under_hermes_home():
    status = LocalRuntimeAdapter().status()
    assert status["server_running"] is False  # nothing running under the test HERMES_HOME
    assert status["models"] == []
    assert status["enabled"] is False
    assert Path(status["models_dir"]).name == "models"
    assert os.environ.get("HERMES_HOME") in status["models_dir"]


def test_hardware_budget_shape():
    out = LocalRuntimeAdapter().hardware()
    assert out["uma"] in (True, False)
    assert out["ram_total_bytes"] > 0
    assert isinstance(out["engine_devices"], list)


def test_backends_surface():
    from hermes_cli.local_runtime.binaries import BACKEND_PACKAGES

    out = LocalRuntimeAdapter().backends()
    assert {row["backend"] for row in out["backends"]} == set(BACKEND_PACKAGES)
    for row in out["backends"]:
        assert isinstance(row["available"], bool)
        if not row["available"]:
            assert row["unavailable_reason"]
    assert out["recommended"] in BACKEND_PACKAGES or out["recommended_unavailable_reason"]


def test_catalog_rows_are_priced():
    rows = LocalRuntimeAdapter().catalog()["models"]
    assert rows
    for row in rows:
        assert isinstance(row["fits"], bool)
        assert row["size_bytes"] >= 0 and row["size_label"]
        assert row["fit_summary"]
    fit_rows = [r for r in rows if r["fits"]]
    if fit_rows:
        assert all("start_window" in r for r in fit_rows)


def test_search_hf_empty_query_is_local():
    assert LocalRuntimeAdapter().search_hf("  ") == {"hits": []}


# ── download / sideload / delete / jobs ──────────────────────
def test_download_catalog_model_runs_stubbed_job(monkeypatch):
    from hermes_cli.local_runtime import catalog as catalog_mod

    entry, variant = catalog_mod.CATALOG[0], catalog_mod.CATALOG[0].variants[0]
    adapter = LocalRuntimeAdapter()
    monkeypatch.setattr(adapter, "_bounce", lambda: True)

    class FakeDownload:
        def __init__(self, sources, *, pause_event=None, **kwargs):
            assert sources

        def run(self, progress=None):
            if progress is not None:
                progress(1, 1, {})

    import pm.downloader as pm_dl

    monkeypatch.setattr(pm_dl, "Download", FakeDownload)
    out = adapter.download(variant.model_id)
    assert out["job_id"], out
    for _ in range(200):
        job = adapter.job(out["job_id"])
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job.get("error")
    assert job["model_id"] == entry.id


def test_install_runtime_runs_stubbed_job(monkeypatch):
    import hermes_cli.local_runtime.binaries as binaries_mod

    engine = binaries_mod.Engine("cpu", "b6000", Path("C:/engines/x/llama-server.exe"))
    monkeypatch.setattr(binaries_mod, "ensure_engine", lambda backend, **kwargs: engine)

    def fake_resolve(requested="auto"):
        if requested == "bad":
            raise binaries_mod.BinaryResolutionError("unknown backend bad")
        return "cpu"

    monkeypatch.setattr(binaries_mod, "resolve_backend", fake_resolve)
    monkeypatch.setattr(binaries_mod, "pinned_tag", lambda backend: "b6000")
    adapter = LocalRuntimeAdapter()
    monkeypatch.setattr(adapter, "_bounce", lambda: True)
    out = adapter.install_runtime()
    assert out == {"job_id": out["job_id"], "backend": "cpu", "tag": "b6000"}
    job = adapter.job(out["job_id"])
    for _ in range(200):
        job = adapter.job(out["job_id"])
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job.get("error")
    assert "ready" in job["detail"]
    with pytest.raises(InvalidRequestError):
        adapter.install_runtime("bad")


def test_download_unknown_model_404():
    with pytest.raises(NotFoundError):
        LocalRuntimeAdapter().download("definitely-not-a-catalog-model-xyz")


def test_download_browsed_validation():
    with pytest.raises(InvalidRequestError):
        LocalRuntimeAdapter().download("x", files={"repo": "a/b", "paths": ["readme.md"]})


def test_sideload_links_gguf(monkeypatch, tmp_path):
    adapter = LocalRuntimeAdapter()
    monkeypatch.setattr(adapter, "_bounce", lambda: True)
    src = tmp_path / "My Model-Q4_K_M.gguf"
    src.write_bytes(b"GGUF....")
    out = adapter.sideload(str(src))
    assert out["ok"] is True and out["model_id"] == "My Model-Q4_K_M"
    from hermes_cli.local_runtime import bootstrap

    assert (bootstrap.models_dir() / src.name).is_file()
    # already present is idempotent
    again = adapter.sideload(str(src))
    assert again["already_present"] is True
    with pytest.raises(InvalidRequestError):
        adapter.sideload(str(tmp_path / "nope.txt"))


def test_job_registry_pause_resume_lifecycle():
    reg = _JobRegistry()
    job = reg.create("model-download", "m")
    runs = {"n": 0}
    body_started = threading.Event()

    def body():
        from pm.downloader import DownloadPaused

        body_started.set()
        runs["n"] += 1
        if runs["n"] == 1:
            pause_event = reg._running[job["job_id"]]["pause"]
            while not pause_event.is_set():
                time.sleep(0.01)
            raise DownloadPaused("paused")
        # resumed run completes the transfer

    reg.spawn(job, "t", body, resumable=True)
    assert body_started.wait(5)
    view = reg.view(job)
    assert view["can_pause"] is True
    assert reg.pause(job["job_id"]) is True
    for _ in range(200):
        if reg.view(job)["status"] == "paused":
            break
        time.sleep(0.05)
    view = reg.view(job)
    assert view["status"] == "paused" and view["can_resume"] is True
    assert reg.resume(job["job_id"]) is True
    for _ in range(200):
        if reg.view(job)["status"] == "done":
            break
        time.sleep(0.05)
    assert reg.view(job)["status"] == "done"
    assert reg.list()[0]["job_id"] == job["job_id"]


def test_eject_via_shared_endpoint(shared_server_env, monkeypatch):
    port, handler = shared_server_env
    adapter = _adapter_with_staged(monkeypatch, [MODEL])
    out = adapter.eject(MODEL)
    assert out == {"ok": True}
    assert handler.unloaded == [MODEL]


def test_diagnostics_shape(monkeypatch):
    adapter = LocalRuntimeAdapter()
    monkeypatch.setattr(adapter, "_endpoint_state", lambda: None)
    out = adapter.diagnostics()
    assert out["server"] == {"running": False}
    assert "engine" in out and "log_path" in out
