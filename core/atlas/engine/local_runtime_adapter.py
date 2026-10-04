"""Thin Atlas adapter over the Hermes managed local model runtime (llama.cpp/GGUF).

Design contract (docs/research/2026-10-03-persistent-atlas, r6 + integration-map §2):

- **No logic is copied from hermes.** Every engine/model/endpoint operation is a direct
  call into ``hermes_cli.local_runtime`` (pinned fork, in-process import — integration
  option A). Only the UI glue that hermes keeps in its web router (job bookkeeping,
  catalog row formatting) is re-expressed here, in the same wire schema.
- **HERMES_HOME is pinned once per process**, at import time of this module, via
  ``os.environ.setdefault`` to a machine-level directory (``%LOCALAPPDATA%\\Atlas\\
  local-runtime`` on Windows, ``~/.local/share/Atlas/local-runtime`` elsewhere) so a
  20 GB GGUF is a machine asset, not a per-profile one. ``setdefault`` semantics: an
  operator/Atlas value already present in the environment wins, and whatever value is
  in force stays constant for the whole process (the r6 trap — hermes memoizes the
  resolved root; the ``setdefault`` must run before the first ``local_runtime`` call,
  which the lazy imports below guarantee). To share the server with a desktop Hermes
  on the stable port 18434 instead, set ``HERMES_HOME`` to the same value in both.
- **Atlas owns the ``local_runtime`` config section** (enabled/backend/port/...): it is
  read from the dict injected into :class:`LocalRuntimeAdapter` and synthesized into
  ``{"local_runtime": {...}}`` for ``ensure_local_runtime``/endpoint resolution.
  hermes ``config.yaml`` is never written — Atlas settings are the single truth.
- **Activation gate** (:meth:`LocalRuntimeAdapter.activate`): server ensured (health) →
  model ensured (hermes "readiness is a touch generation" contract) → a REAL tool-call
  probe (``probe_tool_call``: ``tools=[get_atlas_probe_nonce]`` + ``tool_choice=
  "required"``, modeled on OpenClaw's activation promise). Only ``ok=True`` reports may
  be promoted to the default Agent model — the caller decides the promotion; this
  module only returns the report.
- ``diagnose_windows_runtime`` is the OpenClaw-borrowed VC-redist diagnostic: when a
  freshly installed engine fails ``llama-server --version``, it reports which of
  ``msvcp140.dll / vcruntime140.dll / vcruntime140_1.dll`` are missing and suggests the
  redistributable — diagnosis only, never installs anything.

Integration note for the owner of ``atlas/server.py``::

    from atlas.api.local_models_router import router as local_models_router
    app.include_router(local_models_router)   # mounts /api/local/models/*
"""
from __future__ import annotations

import collections
import json
import logging
import os
import re
import shutil
import threading
import time
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

_HERMES_HOME_PINNED = False
_HERMES_HOME_MARK = ".atlas-local-runtime-home"


def _ensure_hermes_home() -> Path:
    """Pin HERMES_HOME for this process, exactly once, to a machine-level directory.

    See the module docstring for why this must precede any ``local_runtime`` call.
    A marker file records that the directory is Atlas's default (an operator-set
    HERMES_HOME wins over it via ``setdefault`` and no marker is written there).
    """
    global _HERMES_HOME_PINNED
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    default_home = base / "Atlas" / "local-runtime"
    if "HERMES_HOME" not in os.environ:
        try:
            default_home.mkdir(parents=True, exist_ok=True)
            (default_home / _HERMES_HOME_MARK).touch(exist_ok=True)
        except OSError as exc:  # unwritable volume: still pin the path, failures surface later
            log.warning("atlas.local_runtime", msg="could not create default HERMES_HOME", error=str(exc))
        os.environ["HERMES_HOME"] = str(default_home)
    _HERMES_HOME_PINNED = True
    return Path(os.environ["HERMES_HOME"])


_ensure_hermes_home()


# ── errors ───────────────────────────────────────────────────
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


# ── lazy hermes handles (never import local_runtime at module import) ──
def _mod(name: str):
    import importlib

    return importlib.import_module(name)


def _bootstrap():
    return _mod("hermes_cli.local_runtime.bootstrap")


def _binaries():
    return _mod("hermes_cli.local_runtime.binaries")


def _endpoint():
    return _mod("hermes_cli.local_runtime.endpoint")


# ── activation report ────────────────────────────────────────
ATLAS_PROBE_TOOL = "get_atlas_probe_nonce"
ATLAS_PROBE_NONCE = "atlas-probe-ok"
_PROBE_PROMPT = (
    f"Call the {ATLAS_PROBE_TOOL} tool with nonce {ATLAS_PROBE_NONCE!r} and nothing else."
)


@dataclass
class ActivationReport:
    """Result of the full activation gate for one staged model."""

    model_id: str
    ok: bool = False
    base_url: str | None = None
    server_ok: bool = False
    model_ready: bool = False          # hermes touch-generation readiness proof
    tool_call_ok: bool = False         # Atlas probe: a real tool call came back
    detail: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id, "ok": self.ok, "base_url": self.base_url,
            "server_ok": self.server_ok, "model_ready": self.model_ready,
            "tool_call_ok": self.tool_call_ok, "detail": self.detail,
            "diagnostics": self.diagnostics, "duration_ms": self.duration_ms,
        }


# ── job bookkeeping (thin glue, same wire schema as hermes's pane) ──
_DOWNLOAD_PHASES = frozenset({"starting", "installing-runtime", "downloading-runtime", "downloading"})
_SPLIT_PART_RE = r"-\d{5}-of-\d{5}"
_RATE_WINDOW = 8.0
_RATE_MIN_ELAPSED = 0.5


class _JobRegistry:
    """The hermes pane's job concept: start-POST → {job_id} → poll with byte progress.

    Hermes keeps this in ``hermes_cli/web_routers/local_models.py`` (web layer, coupled
    to its config-mutation machinery); per r6 the glue is re-expressed here once, ~90
    lines, with the identical job view so the Atlas UI mirrors the hermes pane.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._running: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, kind: str, target: str, model_id: str | None = None) -> dict[str, Any]:
        job = {
            "job_id": uuid.uuid4().hex[:12], "kind": kind, "target": target,
            "model_id": model_id, "status": "running", "phase": "starting", "detail": "",
            "total_bytes": None, "done_bytes": 0, "ranges": {},
            "started_at": time.time(), "error": None,
        }
        with self._lock:
            self._jobs[job["job_id"]] = job
        return job

    def step(self, job: dict[str, Any], phase: str, detail: str) -> None:
        with self._lock:
            if job.get("phase") in _DOWNLOAD_PHASES and phase not in _DOWNLOAD_PHASES:
                pause = self._running.get(job["job_id"], {}).get("pause")
                if pause is not None and pause.is_set():
                    from pm.downloader import DownloadPaused

                    raise DownloadPaused("download paused")
            job["phase"] = phase
            job["detail"] = detail

    def finish(self, job: dict[str, Any], detail: str) -> None:
        self.step(job, "done", detail)

    def record_rate(self, job: dict[str, Any], done: int) -> None:
        running = self._running.get(job["job_id"])
        if running is None:
            return
        now = time.monotonic()
        samples: collections.deque = running.setdefault("samples", collections.deque())
        samples.append((now, done))
        while len(samples) > 1 and now - samples[0][0] > _RATE_WINDOW:
            samples.popleft()
        rate = eta = None
        if len(samples) >= 2:
            elapsed = samples[-1][0] - samples[0][0]
            first_done = samples[0][1]
            if elapsed >= _RATE_MIN_ELAPSED and done > first_done:
                rate = (done - first_done) / elapsed
                total = job.get("total_bytes")
                eta = max(0, round((total - done) / rate)) if total else None
        if rate is None:
            job.pop("bytes_per_sec", None)
            job.pop("eta_seconds", None)
        else:
            job["bytes_per_sec"] = rate
            job["eta_seconds"] = eta

    def spawn(self, job: dict[str, Any], name: str, body: Callable[[], None], *,
              fail_msg: str | None = None, resumable: bool = False,
              on_exit: Callable[[], None] | None = None) -> None:
        guard = threading.Lock()
        pause = threading.Event()

        def _run() -> None:
            from pm.downloader import DownloadPaused

            status = "done"
            try:
                body()
            except DownloadPaused:
                status = "paused"
            except Exception as exc:  # noqa: BLE001 — job body's failure is the job's error
                log.debug("atlas.local_runtime.job_failed", error=str(exc), exc_info=True)
                if fail_msg:
                    log.warning(
                        "atlas.local_runtime.job", msg=fail_msg,
                        error=str(exc), exc_info=True,
                    )
                status = "error"
                job["error"] = str(exc)
            finally:
                try:
                    if status != "paused" and on_exit is not None:
                        on_exit()
                finally:
                    with self._lock:
                        if status != "paused":
                            self._running.pop(job["job_id"], None)
                        job["status"] = status
                        guard.release()

        def start(*, initial: bool = False) -> bool:
            if not guard.acquire(blocking=False):
                return False
            with self._lock:
                if not initial and job["status"] != "paused":
                    guard.release()
                    return False
                pause.clear()
                self._running.get(job["job_id"], {}).pop("samples", None)
                job["status"] = "running"
                job["error"] = None
            thread = threading.Thread(target=_run, name=name, daemon=True)
            thread.start()
            return True

        if resumable:
            with self._lock:
                self._running[job["job_id"]] = {"resume": start, "pause": pause}
        start(initial=True)

    def view(self, job: dict[str, Any]) -> dict[str, Any]:
        out = dict(job)
        running = self._running.get(job["job_id"], {})
        pause = running.get("pause")
        out["pause_requested"] = bool(pause is not None and pause.is_set() and out["status"] == "running")
        out["can_pause"] = bool(pause is not None and out["status"] == "running"
                                and out["phase"] in _DOWNLOAD_PHASES and not out["pause_requested"])
        out["can_resume"] = out["status"] == "paused" and "resume" in running
        if out.get("total_bytes"):
            out["percent"] = min(100, round(out["done_bytes"] / out["total_bytes"] * 100))
        if out["status"] != "running":
            out.pop("bytes_per_sec", None)
            out.pop("eta_seconds", None)
        return out

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def pause(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise NotFoundError("unknown download job")
            if not self.view(job)["can_pause"]:
                return False
            self._running[job_id]["pause"].set()
            return True

    def resume(self, job_id: str) -> bool:
        if self.get(job_id) is None:
            raise NotFoundError("unknown download job")
        resume = self._running.get(job_id, {}).get("resume")
        return bool(resume and resume())

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda job: -job["started_at"])
        active = [j for j in jobs if j["status"] in ("running", "paused")]
        recent = [j for j in jobs if j["status"] in ("done", "error")][:20]
        return [self.view(j) for j in [*active, *recent]]


# ── VC redist diagnosis (OpenClaw-borrowed, diagnose-only) ───
_VC_RUNTIME_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")


def _launch_version_check(exe: Path, engine_dir: Path) -> tuple[bool, str]:
    """Run ``llama-server --version``; (ok, detail). Detail carries rc/stderr/OSError."""
    import subprocess

    try:
        result = subprocess.run([str(exe), "--version"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30,
                                cwd=str(engine_dir))
    except subprocess.TimeoutExpired:
        return False, "--version did not exit within 30s (hung loader?)"
    except OSError as exc:
        return False, f"launch failed: {exc}"
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
        return False, f"--version exited rc={result.returncode}: {' | '.join(tail)}"
    return True, (result.stdout or "").strip()[:200]


def _engine_dll_names(engine_dir: Path) -> set[str]:
    return {name for name in _VC_RUNTIME_DLLS if (engine_dir / name).is_file()}


def _system_dll_names() -> set[str]:
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    return {name for name in _VC_RUNTIME_DLLS if (system32 / name).is_file()}


def diagnose_windows_runtime(engine_dir: str | Path, *, windows: bool | None = None) -> dict[str, Any]:
    """Diagnose a llama.cpp engine dir whose binary will not start (Windows VC redist).

    When ``llama-server --version`` fails on Windows, checks which of the three Visual
    C++ runtime DLLs are absent from BOTH the engine directory (app-local placement,
    OpenClaw's fix shape) and System32, and reports the redistributable as the likely
    fix. **Diagnosis only** — this function never downloads or installs anything.
    """
    engine_dir = Path(engine_dir)
    windows = (os.name == "nt") if windows is None else bool(windows)
    exe = engine_dir / ("llama-server.exe" if windows else "llama-server")
    out: dict[str, Any] = {
        "engine_dir": str(engine_dir), "executable": str(exe),
        "launch_ok": False, "detail": "", "state": "launch-failed",
        "vc_redist": {"needed": False, "missing_dlls": [], "present_dlls": [], "suggestion": None},
    }
    if not exe.is_file():
        out["detail"] = f"{exe.name} not found in the engine directory"
        return out
    ok, detail = _launch_version_check(exe, engine_dir)
    out["launch_ok"], out["detail"] = ok, detail
    if ok:
        out["state"] = "ok"
        return out
    if not windows:
        return out
    present, missing = [], []
    engine_dlls, system_dlls = _engine_dll_names(engine_dir), _system_dll_names()
    for name in _VC_RUNTIME_DLLS:
        (present if (name in engine_dlls or name in system_dlls) else missing).append(name)
    out["vc_redist"] = {
        "needed": bool(missing), "missing_dlls": missing, "present_dlls": present,
        "suggestion": (
            "Install the Microsoft Visual C++ 2015-2022 Redistributable (x64) "
            "(vc_redist.x64.exe), or place the missing DLLs next to llama-server.exe "
            "(app-local), then retry."
        ) if missing else None,
    }
    if missing:
        out["state"] = "missing-vc-redist"
        out["detail"] = (f"launch failed and {', '.join(missing)} missing from both the engine "
                         f"dir and System32: {detail}")
    return out


# ── the adapter ──────────────────────────────────────────────
def _human_gb(n: int | float) -> str:
    return f"{n / (1 << 30):.1f} GB"


def _k_label(tokens: int) -> str:
    return f"{tokens // 1024}K"


def _hf_url(repo: str, path: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{path}"


class LocalRuntimeAdapter:
    """Atlas's single entry point to the managed local model runtime.

    All engine/model work delegates to ``hermes_cli.local_runtime``; ``config`` is the
    Atlas-owned ``local_runtime`` settings dict (never hermes config.yaml).
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config: dict[str, Any] = {
            "enabled": False,          # the durable on/off switch (start/stop endpoints flip it)
            "backend": "auto",
            "port": None,              # None → hermes stable port 18434 / ephemeral fallback
            "models_max": 4,
            "detect_ports": [],
            "active_model_id": None,   # informational: caller promotes on ActivationReport.ok
        }
        if config:
            self.config.update(config)
        self.jobs = _JobRegistry()

    # ── configuration (Atlas-owned; never touches hermes config.yaml) ──
    def configure(self, update: dict[str, Any]) -> dict[str, Any]:
        self.config.update(update)
        return dict(self.config)

    def _hermes_config(self) -> dict[str, Any]:
        section = {k: self.config.get(k) for k in
                   ("enabled", "backend", "port", "models_max", "detect_ports")}
        return {"local_runtime": section}

    # ── quiet helpers ──
    @staticmethod
    def _quiet(fn: Callable[[], Any], default: Any) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — garnish must never 500
            log.debug("atlas.local_runtime.quiet", error=str(exc), exc_info=True)
            return default

    # ── status / hardware / backends ────────────────────────
    def status(self) -> dict[str, Any]:
        binaries, bootstrap = _binaries(), _bootstrap()
        backend_cfg = self.config.get("backend", "auto")
        engine = binaries.installed_engine(backend_cfg)
        runtime_backend = engine.backend if engine is not None else None
        if engine is not None:
            tag = engine.tag
        else:
            tag = self._quiet(lambda: binaries.pinned_tag(runtime_backend or backend_cfg), None)
        endpoint = self._endpoint_state()
        loaded, placement = ({}, {}) if endpoint is None else self._quiet(
            lambda: self._loaded_models(endpoint), ({}, {}))
        mdir = bootstrap.models_dir()
        staged = self._quiet(bootstrap.staged_models, [])
        update_available = False
        if runtime_backend is not None and self.config.get("enabled"):
            import pm

            update_available = self._quiet(
                lambda: pm.installed_package(binaries.BACKEND_PACKAGES[runtime_backend]) is None, False)
        return {
            "enabled": bool(self.config.get("enabled")),
            "tag": tag,
            "configured_tag": self._quiet(lambda: binaries.pinned_tag(
                runtime_backend or backend_cfg), None),
            "update_available": update_available,
            "runtime_installed": runtime_backend is not None,
            "runtime_backend": runtime_backend,
            "server_running": endpoint is not None,
            "server_base_url": (endpoint or {}).get("base_url"),
            "active_model_id": self.config.get("active_model_id"),
            "loaded_models": loaded,
            "loading": self._quiet(lambda: _mod("hermes_cli.local_runtime.load_progress")
                                   .get_loading_progress(), {}),
            "placement": placement,
            "models": [self._staged_row(g) for g in staged],
            "models_dir": str(mdir),
        }

    def hardware(self) -> dict[str, Any]:
        hardware = _mod("hermes_cli.local_runtime.hardware")
        budget = hardware.probe_budget()
        ram_total, ram_avail = hardware._ram_bytes()
        out = {
            "uma": budget.uma,
            "vram_total_bytes": budget.total_device_bytes,
            "vram_usable_bytes": budget.usable_vram_bytes,
            "ram_total_bytes": ram_total, "ram_available_bytes": ram_avail,
            "vram_label": _human_gb(budget.total_device_bytes),
            "gpu_name": None, "gpu_util_percent": None, "vram_used_bytes": None,
            "engine_devices": [],
        }
        query = self._quiet(hardware._cached_nvidia_gpu_query, None)
        if query:
            out.update(gpu_name=query.get("gpu_name"), gpu_util_percent=query.get("gpu_util_percent"),
                       vram_used_bytes=query.get("used_bytes"))
        # AMD/Intel cards: ask the INSTALLED engine which accelerators it sees.
        engine = self._quiet(lambda: _binaries().installed_engine(self.config.get("backend", "auto")), None)
        if engine is not None:
            devices = self._quiet(lambda: _mod("hermes_cli.local_runtime.devices")
                                  .probe_devices(engine.binary.parent, engine.backend), [])
            out["engine_devices"] = devices
        return out

    def backends(self) -> dict[str, Any]:
        """Backend selector facts: pin availability, installability, installed engine."""
        binaries = _binaries()
        rows = []
        for backend in binaries.BACKEND_PACKAGES:
            reason = self._quiet(lambda b=backend: binaries.unavailable_reason(b), None)
            engine = self._quiet(lambda b=backend: binaries.installed_engine(b), None)
            pinned = self._quiet(lambda b=backend: binaries.pinned_tag(b), None)
            rows.append({
                "backend": backend, "package": binaries.BACKEND_PACKAGES[backend],
                "pinned_tag": pinned, "available": reason is None, "unavailable_reason": reason,
                "installed": engine is not None,
                "installed_tag": engine.tag if engine is not None else None,
                "installed_binary": str(engine.binary) if engine is not None else None,
            })
        recommended = reason = None
        try:
            recommended = binaries.resolve_backend(self.config.get("backend", "auto"))
        except Exception as exc:  # noqa: BLE001 — BinaryResolutionError or probe failure
            log.debug(
                "atlas.local_runtime.recommended_backend_unavailable",
                error=str(exc), exc_info=True,
            )
            reason = str(exc)
        return {"backends": rows, "recommended": recommended, "recommended_unavailable_reason": reason}

    # ── catalog / search ─────────────────────────────────────
    def catalog(self) -> dict[str, Any]:
        catalog = _mod("hermes_cli.local_runtime.catalog")
        hardware = _mod("hermes_cli.local_runtime.hardware")
        estimator = _mod("hermes_cli.local_runtime.estimator")
        bootstrap = _bootstrap()
        self._quiet(catalog.refresh_catalog_soon, None)
        budget = hardware.probe_budget(planning=True)
        staged_ids = set(self._quiet(bootstrap.staged_model_ids, []))
        rec = self._quiet(
            lambda: catalog.recommended_entry(
                budget, backend=self.config.get("backend", "auto")), None)
        recommended, recommended_reason = rec if isinstance(rec, tuple) else (None, None)
        recommended_id = recommended.id if recommended is not None else None
        rows = [self._catalog_row(entry, budget, recommended_id, recommended_reason,
                                  staged_ids, catalog, estimator, bootstrap)
                for entry in catalog.CATALOG]
        return {"models": rows}

    def search_hf(self, query: str, limit: int = 20) -> dict[str, Any]:
        hf = _mod("hermes_cli.local_runtime.hf_browse")
        if not query.strip():
            return {"hits": []}
        hits = hf.search_models(query, limit)
        return {"hits": [h.__dict__ for h in hits]}

    def search_repo_files(self, repo: str) -> dict[str, Any]:
        hf = _mod("hermes_cli.local_runtime.hf_browse")
        hardware = _mod("hermes_cli.local_runtime.hardware")
        budget = hardware.probe_budget(planning=True)
        groups = hf.priced_repo_files(repo, budget)
        return {"files": [dict(g.__dict__, paths=list(g.paths)) for g in groups]}

    # ── long jobs: runtime install / downloads ───────────────
    def install_runtime(self, backend: str | None = None) -> dict[str, Any]:
        binaries = _binaries()
        requested = backend or self.config.get("backend", "auto")
        try:
            resolved = binaries.resolve_backend(requested)
            tag = binaries.pinned_tag(resolved)
        except Exception as exc:  # noqa: BLE001
            raise InvalidRequestError(str(exc), status_code=400) from exc
        job = self.jobs.create("runtime-install", f"llama.cpp {tag} ({resolved})")
        phases = {"download": "downloading-runtime", "unpack": "unpacking-runtime",
                  "verify": "verifying-runtime"}

        def progress(stage: str, done: int, total: int, label: str) -> None:
            self.jobs.step(job, phases.get(stage, "installing-runtime"),
                           f"Preparing the pinned local engine ({label})" if label else
                           "Preparing the pinned local engine")

        def tick(done: int, total: int, ranges: dict) -> None:
            with self.jobs._lock:
                job.update(done_bytes=done, total_bytes=total or None, ranges=ranges)
                self.jobs.record_rate(job, done)

        def run() -> None:
            self.jobs.step(job, "installing-runtime", "Preparing the pinned local engine")
            binaries.ensure_engine(resolved, progress=progress,
                                   pause_event=self._pause_event(job), download_progress=tick)
            self.jobs.finish(job, f"llama.cpp {tag} ready ({resolved})")

        self.jobs.spawn(job, "atlas-lr-runtime-install", run, fail_msg="runtime install failed: %s",
                        resumable=True)
        return {"job_id": job["job_id"], "backend": resolved, "tag": tag}

    def download(self, model_id: str, files: dict[str, Any] | None = None) -> dict[str, Any]:
        """Queue a model download job.

        ``files=None`` downloads the catalog family/variant ``model_id`` (this machine's
        selected build). ``files={"repo": ..., "paths": [...]}`` downloads arbitrary HF
        GGUF paths (split parts in order) — the browsed-download shape.
        """
        bootstrap = _bootstrap()
        if files:
            repo, paths = str(files.get("repo", "")), [p for p in files.get("paths", [])
                                                       if str(p).lower().endswith(".gguf")]
            if not repo or not paths:
                raise InvalidRequestError("files spec needs 'repo' and .gguf 'paths'")
            mid = re.sub(rf"(?:{_SPLIT_PART_RE})?\.gguf$", "", paths[0].rsplit("/", 1)[-1],
                         flags=re.IGNORECASE)
            if mid in bootstrap.staged_model_ids():
                return {"job_id": None, "already_downloaded": True, "model_id": mid}
            plan = [(_hf_url(repo, p), bootstrap.models_dir() / p.rsplit("/", 1)[-1], 0)
                    for p in paths]
            label, entry_id = f"{mid} (from {repo})", mid
        else:
            entry, variant = self._download_target(model_id)
            plan = self._download_plan(entry, variant)
            label, entry_id = f"{entry.display_name} ({variant.quant})", entry.id
            if plan and all(dest.is_file() for _, dest, _ in plan):
                return {"job_id": None, "already_downloaded": True, "model_id": variant.model_id}
        job = self.jobs.create("model-download", label, model_id=entry_id)

        def tick(done: int, total: int, ranges: dict) -> None:
            with self.jobs._lock:
                job.update(done_bytes=done, total_bytes=total or None, ranges=ranges)
                self.jobs.record_rate(job, done)

        def run() -> None:
            from pm.downloader import Download, Source

            self.jobs.step(job, "downloading", f"Downloading {label}")
            dl = Download([Source(url, dest) for url, dest, _ in plan],
                          pause_event=self._pause_event(job))
            dl.run(progress=tick)
            self.jobs.finish(job, f"{label} ready")
            self._bounce()

        self.jobs.spawn(job, "atlas-lr-model-download", run, fail_msg="model download failed: %s",
                        resumable=True)
        return {"job_id": job["job_id"], "model_id": entry_id}

    def pause_download(self, job_id: str) -> dict[str, Any]:
        return {"ok": True, "paused": self.jobs.pause(job_id)}

    def resume_download(self, job_id: str) -> dict[str, Any]:
        return {"ok": True, "resumed": self.jobs.resume(job_id)}

    def jobs_list(self) -> dict[str, Any]:
        return {"jobs": self.jobs.list()}

    def job(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            raise NotFoundError("job not found")
        return self.jobs.view(job)

    def delete_model(self, model_id: str) -> dict[str, Any]:
        bootstrap = _bootstrap()
        files = self._variant_files_on_disk(model_id)
        if not files:
            raise NotFoundError("model not found")
        for path in files:
            path.unlink(missing_ok=True)
        self._quiet(lambda: _mod("hermes_cli.local_runtime.growth").clear_window_override(model_id), None)
        threading.Thread(target=self._bounce, name="atlas-lr-post-delete", daemon=True).start()
        return {"ok": True}

    def sideload(self, gguf_path: str) -> dict[str, Any]:
        """Register a GGUF already on this machine: link it into the managed models dir."""
        bootstrap = _bootstrap()
        src = Path(gguf_path)
        if not src.is_file() or src.suffix.lower() != ".gguf":
            raise InvalidRequestError("Pick a .gguf model file", status_code=422)
        dest = bootstrap.models_dir() / src.name
        if dest.exists():
            return {"ok": True, "model_id": dest.stem, "already_present": True}
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, dest)
        except OSError:
            try:
                os.symlink(src, dest)
            except OSError:
                shutil.copyfile(src, dest)
        self._bounce()
        return {"ok": True, "model_id": dest.stem}

    # ── server lifecycle ─────────────────────────────────────
    def start_server(self, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
        """Force-start the managed server under the Atlas config (updates it first)."""
        if cfg:
            self.configure(cfg)
        self.config["enabled"] = True
        endpoint = self._ensure_server()
        return {"ok": True, "base_url": endpoint["base_url"]}

    def stop_server(self) -> dict[str, Any]:
        """Stop the server and flip the durable off switch (Atlas config dict only)."""
        bootstrap = _bootstrap()
        if bootstrap.get_supervisor() is not None:
            bootstrap.shutdown_local_runtime()
        else:
            from hermes_cli.local_runtime.recovery import stop_recorded_orphan

            if not stop_recorded_orphan():
                raise ConflictError("Another process owns this server, or its ownership "
                                    "could not be verified")
        self.config["enabled"] = False
        return {"ok": True, "action": "stop"}

    def eject(self, model_id: str) -> dict[str, Any]:
        """Free a resident model's VRAM now (supervisor path or persisted-endpoint fallback)."""
        sup = _bootstrap().get_supervisor()
        if sup is not None:
            try:
                sup.unload_model(model_id)
            except Exception as exc:  # noqa: BLE001
                raise LocalRuntimeError(str(exc)) from exc
            return {"ok": True}
        endpoint = self._endpoint_state()
        if endpoint is None:
            raise ConflictError("local server is not running")
        self._managed_post(endpoint, "/models/unload", {"model": model_id}, timeout_s=120)
        return {"ok": True}

    # ── activation gate ──────────────────────────────────────
    def staged_model_ids(self) -> list[str]:
        return self._quiet(_bootstrap().staged_model_ids, [])

    def activate(self, model_id: str) -> ActivationReport:
        """Full gate: ensure server → ensure model (touch) → real tool-call probe.

        Returns the report; promoting the model to the Atlas default is the caller's
        decision and is allowed only when ``report.ok``.
        """
        started = time.monotonic()
        report = ActivationReport(model_id=model_id)
        if model_id not in self.staged_model_ids():
            report.diagnostics.append(f"{model_id} is not downloaded (not in the staged models dir)")
            report.duration_ms = int((time.monotonic() - started) * 1000)
            return report
        try:
            endpoint = self._ensure_server()
        except LocalRuntimeError as exc:
            report.diagnostics.append(f"server: {exc}")
            report.duration_ms = int((time.monotonic() - started) * 1000)
            return report
        report.server_ok = True
        report.base_url = endpoint["base_url"]
        endpoint = self._rescan_if_unknown(endpoint, model_id, report)
        if endpoint is None:
            report.duration_ms = int((time.monotonic() - started) * 1000)
            return report
        ready, why = self._model_ready(endpoint, model_id)
        report.model_ready = ready
        if not ready:
            report.diagnostics.append(f"model readiness failed: {why}")
            report.duration_ms = int((time.monotonic() - started) * 1000)
            return report
        probe = self.probe_tool_call(endpoint["base_url"], endpoint.get("api_key", ""), model_id)
        report.detail["probe"] = probe
        report.tool_call_ok = bool(probe.get("ok"))
        if not report.tool_call_ok:
            report.diagnostics.append(
                "the model does not support tool calling (health and generation are fine, but no "
                "tool_calls block came back for a tool_choice='required' request) — it cannot be "
                "an Atlas agent model")
        report.ok = report.model_ready and report.tool_call_ok
        report.duration_ms = int((time.monotonic() - started) * 1000)
        return report

    @staticmethod
    def probe_tool_call(base_url: str, api_key: str, model: str, *,
                        timeout_s: float = 60.0) -> dict[str, Any]:
        """One real tool-call probe against an OpenAI-compatible endpoint.

        Sends ``tools=[get_atlas_probe_nonce]`` + ``tool_choice="required"`` (OpenClaw's
        activation-probe shape). Success requires a ``tool_calls`` block whose function
        name matches and whose arguments parse as a JSON object. A nonce argument equal
        to the contract value is recorded, not required — the judgment is tool_calls
        presence + valid arguments.
        """
        url = base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": model,
            "messages": [{"role": "user", "content": _PROBE_PROMPT}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": ATLAS_PROBE_TOOL,
                    "description": "Return the fixed Atlas activation probe nonce.",
                    "parameters": {
                        "type": "object",
                        "properties": {"nonce": {"type": "string",
                                                 "description": f"Must be exactly {ATLAS_PROBE_NONCE!r}"}},
                        "required": ["nonce"],
                    },
                },
            }],
            "tool_choice": "required",
            "max_tokens": 256,
            "temperature": 0,
        }
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                resp = json.loads(r.read())
        except Exception as exc:  # noqa: BLE001 — transport failures are probe failures
            log.debug(
                "atlas.local_runtime.probe_request_failed",
                url=url, error=str(exc), exc_info=True,
            )
            return {"ok": False, "reason": f"probe request failed: {exc}", "url": url}
        try:
            message = resp["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return {"ok": False, "reason": "malformed chat completion response", "url": url}
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            snippet = str(message.get("content") or "")[:200]
            return {"ok": False, "reason": "no tool_calls in response (model answered in plain text)",
                    "content_snippet": snippet, "url": url}
        call = tool_calls[0].get("function") or {}
        name = call.get("name")
        raw_args = call.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except ValueError:
            return {"ok": False, "reason": f"tool call arguments are not valid JSON: {raw_args!r}",
                    "function_name": name, "url": url}
        if not isinstance(args, dict):
            return {"ok": False, "reason": f"tool call arguments are not an object: {args!r}",
                    "function_name": name, "url": url}
        if name != ATLAS_PROBE_TOOL:
            return {"ok": False, "reason": f"model called {name!r} instead of {ATLAS_PROBE_TOOL!r}",
                    "url": url}
        return {"ok": True, "function_name": name, "arguments": args,
                "nonce_ok": args.get("nonce") == ATLAS_PROBE_NONCE, "url": url}

    # ── diagnostics ──────────────────────────────────────────
    def diagnostics(self, job_id: str | None = None) -> dict[str, Any]:
        binaries, bootstrap = _binaries(), _bootstrap()
        out: dict[str, Any] = {"hermes_home": os.environ.get("HERMES_HOME", ""),
                               "hints": [], "job": None}
        endpoint = self._endpoint_state()
        out["server"] = ({"running": True, "base_url": endpoint.get("base_url")}
                         if endpoint else {"running": False})
        engine = self._quiet(lambda: binaries.installed_engine(self.config.get("backend", "auto")), None)
        if engine is not None:
            out["engine"] = {"backend": engine.backend, "tag": engine.tag,
                             "binary": str(engine.binary)}
            out["windows_runtime"] = diagnose_windows_runtime(engine.binary.parent)
            if out["windows_runtime"]["state"] == "missing-vc-redist":
                out["hints"].append("Visual C++ runtime DLLs are missing for the engine — "
                                    + (out["windows_runtime"]["vc_redist"]["suggestion"] or ""))
        else:
            reason = self._quiet(lambda: binaries.unavailable_reason(
                self.config.get("backend", "auto") or "auto"), None)
            out["engine"] = {"installed": False, "unavailable_reason": reason}
        log_path = bootstrap.models_dir().parent / "logs" / "llama-server.log"
        out["log_path"] = str(log_path)
        out["log_tail"] = self._log_tail(log_path)
        blob = "\n".join([out.get("log_tail") or "",
                          str((out.get("windows_runtime") or {}).get("detail") or ""),
                          str(out["engine"].get("unavailable_reason") or "")]).lower()
        if "vcruntime" in blob or "msvcp140" in blob or "dll" in blob:
            out["hints"].append("possible missing Visual C++ runtime (see windows_runtime)")
        if "not healthy after" in blob or "exited rc=" in blob:
            out["hints"].append("the llama-server process exited or never became healthy — read the log tail")
        if job_id:
            job = self.jobs.get(job_id)
            out["job"] = self.jobs.view(job) if job else None
            if job and job.get("error"):
                out["hints"].append(f"job error: {job['error']}")
        return out

    # ── internals: server/model plumbing ─────────────────────
    def _endpoint_state(self) -> dict[str, Any] | None:
        """Live endpoint {base_url(/v1), api_key, supervisor?} — process supervisor first,
        then the ownership-guarded state file (a server another Atlas/Hermes process runs)."""
        sup = self._quiet(_bootstrap().get_supervisor, None)
        if sup is not None:
            return {"base_url": sup.base_url, "api_key": sup.api_key, "supervisor": sup}
        managed = self._quiet(lambda: _endpoint().managed_root(), None)
        if managed:
            base, api_key = managed
            return {"base_url": f"{base}/v1", "api_key": api_key, "supervisor": None}
        return None

    def _ensure_server(self) -> dict[str, Any]:
        """Start (or adopt) the managed server; raise when neither we nor another process serve."""
        bootstrap = _bootstrap()
        sup = bootstrap.ensure_local_runtime(self._hermes_config(), force=True)
        if sup is None and self._endpoint_state() is None:
            raise LocalRuntimeError(
                "the local server could not start — install the runtime and check "
                f"{bootstrap.models_dir().parent / 'logs' / 'llama-server.log'}")
        return self._endpoint_state()  # type: ignore[return-value]

    def _rescan_if_unknown(self, endpoint: dict[str, Any], model_id: str,
                           report: ActivationReport) -> dict[str, Any] | None:
        """The router's model list is spawn-only: bounce it when it can't see the model."""
        if model_id in self._http_models(endpoint):
            return endpoint
        report.detail.setdefault("steps", []).append("bouncing server to rescan the models dir")
        if not self._bounce():
            report.diagnostics.append("server rescan failed (could not restart the local server)")
            return None
        endpoint = self._ensure_server()
        if model_id not in self._http_models(endpoint):
            report.diagnostics.append(f"{model_id} is not served even after a rescan — "
                                      "the staged GGUF may be incomplete")
            return None
        return endpoint

    def _model_ready(self, endpoint: dict[str, Any], model_id: str) -> tuple[bool, str]:
        """Hermes's readiness contract: load if needed, then prove with a touch generation."""
        sup = endpoint.get("supervisor")
        if sup is not None:
            try:
                return bool(sup.ensure_model_ready(model_id)), ""
            except KeyError:
                return False, f"model {model_id} not present in the models dir"
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "atlas.local_runtime.model_ready_failed",
                    model=model_id, error=str(exc), exc_info=True,
                )
                return False, str(exc)
        statuses = self._http_models(endpoint)
        if statuses.get(model_id) not in ("loaded", "ready"):
            try:
                self._managed_post(endpoint, "/models/load", {"model": model_id}, timeout_s=600)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "atlas.local_runtime.model_load_failed",
                    model=model_id, error=str(exc), exc_info=True,
                )
                return False, f"model load failed: {exc}"
            statuses = self._http_models(endpoint)
            if statuses.get(model_id) not in ("loaded", "ready"):
                return False, f"model did not reach a resident state (status={statuses.get(model_id)})"
        ok = self._touch_generate(endpoint, model_id)
        return ok, ("" if ok else "touch generation failed (readiness proof)")

    def _touch_generate(self, endpoint: dict[str, Any], model_id: str, timeout_s: float = 300) -> bool:
        """The hermes touch: temp-0 one-word generation, answer scanned leniently."""
        body = {"model": model_id,
                "messages": [{"role": "user", "content": "Reply with exactly one word: the capital of France."}],
                "max_tokens": 512, "temperature": 0}
        try:
            resp = self._managed_post(endpoint, "/v1/chat/completions", body, timeout_s=timeout_s)
            msg = resp["choices"][0]["message"]
            blob = (msg.get("content") or "") + " " + (msg.get("reasoning_content") or "")
            return "paris" in blob.lower()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "atlas.local_runtime.touch", model=model_id,
                error=str(exc), exc_info=True,
            )
            return False

    def _bounce(self) -> bool:
        """Restart the server so it rescans the models dir; Atlas config, never hermes config."""
        bootstrap = _bootstrap()
        try:
            if bootstrap.get_supervisor() is not None:
                bootstrap.shutdown_local_runtime()
            else:
                from hermes_cli.local_runtime.recovery import stop_recorded_orphan

                if not stop_recorded_orphan():
                    log.warning("atlas.local_runtime.bounce", msg="server owned by another process; not restarted")
                    return False
            return bootstrap.ensure_local_runtime(self._hermes_config(), force=True) is not None \
                or self._endpoint_state() is not None
        except Exception as exc:  # noqa: BLE001
            log.warning("atlas.local_runtime.bounce", error=str(exc), exc_info=True)
            return False

    # HTTP helpers against the managed router (shared-server path)
    def _managed_post(self, endpoint: dict[str, Any], route: str, payload: dict,
                      timeout_s: float = 30) -> Any:
        base = endpoint["base_url"].rsplit("/v1", 1)[0]
        req = urllib.request.Request(
            f"{base}{route}", data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {endpoint.get('api_key', '')}"})
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}

    def _http_models(self, endpoint: dict[str, Any]) -> dict[str, str]:
        sup = endpoint.get("supervisor")
        if sup is not None:
            return self._quiet(lambda: sup.models(timeout_s=10), {})
        data = self._quiet(lambda: _endpoint().managed_get_json(
            endpoint["base_url"].rsplit("/v1", 1)[0], endpoint.get("api_key", ""), "/models", 10), {})
        return {m.get("id"): (m.get("status") or {}).get("value", "unknown")
                for m in (data or {}).get("data", [])}

    def _loaded_models(self, endpoint: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
        statuses = self._http_models(endpoint)
        loaded = {mid: st for mid, st in statuses.items()
                  if st in ("loaded", "ready", "loading")}
        placement: dict[str, Any] = {}
        decisions = self._quiet(lambda: _mod("hermes_cli.local_runtime.presets")
                                .read_preset_decisions(), {})
        for mid, state in loaded.items():
            facts: dict[str, Any] = {}
            plan = (decisions or {}).get(mid)
            if plan is not None:
                window = getattr(plan, "window", None)
                if window:
                    facts.update(window=window, window_label=_k_label(int(window)))
                spilled = getattr(plan, "spilled", None)
                if spilled is not None:
                    facts["spilled"] = spilled
            if facts:
                placement[mid] = facts
        return loaded, placement

    def _pause_event(self, job: dict[str, Any]) -> threading.Event | None:
        running = self.jobs._running.get(job["job_id"])
        return running.get("pause") if running else None

    # download-plan glue (catalog acquisition, same shapes as the hermes pane)
    def _download_target(self, model_id: str) -> tuple[Any, Any]:
        """(entry, variant): a family id resolves to this machine's selected build (same
        planning budget as the catalog); an exact variant id is kept verbatim."""
        catalog = _mod("hermes_cli.local_runtime.catalog")
        hardware = _mod("hermes_cli.local_runtime.hardware")
        entry = catalog.catalog_by_id().get(model_id)
        if entry is not None:
            if self._engine_too_old(entry):
                raise ConflictError(f"{entry.display_name} needs llama.cpp {entry.min_engine} "
                                    "or newer — update the engine first")
            choice = catalog.select_variant(entry, hardware.probe_budget(planning=True))
            if choice is None:
                raise ConflictError(f"no variant of {entry.id} fits this machine")
            return entry, choice.variant
        found = catalog.find_entry_for_model(model_id)
        if found is None:
            raise NotFoundError(f"unknown model {model_id}")
        return found

    def _download_plan(self, entry: Any, variant: Any) -> list[tuple[str, Path, int]]:
        bootstrap = _bootstrap()
        plan = [(_hf_url(entry.repo, a.path), bootstrap.models_dir() / a.local_name, a.size_bytes)
                for a in variant.files]
        plan += [(_hf_url(entry.repo, a.path), bootstrap.assets_dir() / a.local_name, a.size_bytes)
                 for a in (entry.mmproj, entry.draft) if a is not None]
        return plan

    def _variant_files_on_disk(self, model_id: str) -> list[Path]:
        bootstrap, catalog = _bootstrap(), _mod("hermes_cli.local_runtime.catalog")
        pattern = re.compile(_SPLIT_PART_RE + "$")
        files = [p for p in bootstrap.models_dir().glob("*.gguf")
                 if pattern.sub("", p.stem) == model_id]
        hit = self._quiet(lambda: catalog.find_entry_for_model(model_id), None)
        if hit is not None:
            assets = (hit[0].mmproj, hit[0].draft)
            files += [bootstrap.assets_dir() / a.local_name for a in assets
                      if a is not None and (bootstrap.assets_dir() / a.local_name).exists()]
        return files

    def _engine_too_old(self, entry: Any) -> bool:
        if not getattr(entry, "min_engine", None):
            return False
        engine = self._quiet(lambda: _binaries().installed_engine(self.config.get("backend", "auto")), None)
        tag = engine.tag if engine is not None else self._quiet(
            lambda: _binaries().pinned_tag(self.config.get("backend", "auto")), None)
        if not tag:
            return False
        try:
            return int(tag.removeprefix("b")) < int(entry.min_engine.removeprefix("b"))
        except ValueError:
            return False

    # formatting glue (same rows as the hermes pane)
    def _staged_row(self, gguf: Path) -> dict[str, Any]:
        catalog = _mod("hermes_cli.local_runtime.catalog")
        model_id = re.sub(_SPLIT_PART_RE + "$", "", gguf.stem)
        hit = self._quiet(lambda: catalog.find_entry_for_model(model_id), None)
        size = hit[1].size_bytes if hit is not None else self._quiet(lambda: gguf.stat().st_size, 0)
        return {"id": model_id, "size_bytes": size, "size_label": _human_gb(size)}

    def _catalog_row(self, entry: Any, budget: Any, recommended_id: str | None,
                     recommended_reason: str | None, staged_ids: set[str],
                     catalog: Any, estimator: Any, bootstrap: Any) -> dict[str, Any]:
        choice = catalog.select_variant(entry, budget)
        dl = next((v for v in entry.variants if v.model_id in staged_ids
                   and all(dest.is_file() for _, dest, _ in self._download_plan(entry, v))), None)
        row: dict[str, Any] = {
            "id": entry.id, "display_name": entry.display_name, "description": entry.description,
            "native_context": entry.n_ctx_train, "native_context_label": _k_label(entry.n_ctx_train),
            "recommended": entry.id == recommended_id,
            "recommended_reason": recommended_reason if entry.id == recommended_id else None,
            "downloaded": dl is not None, "downloaded_model_id": dl.model_id if dl else None,
            "downloaded_quant": dl.quant if dl else None, "mtp": entry.mtp,
            "vision": entry.mmproj is not None,
            "needs_engine": self._engine_too_old(entry), "min_engine": entry.min_engine or None,
        }
        if choice is None:
            smallest = min(entry.variants, key=lambda v: v.size_bytes)
            total = entry.download_bytes(smallest)
            row.update(fits=False, size_bytes=total, size_label=_human_gb(total),
                       fit_summary="Needs more memory than this machine has",
                       fit_detail=f"even the most compact build ({smallest.quant}, "
                                  f"{_human_gb(total)}) exceeds GPU + system memory")
            return row
        variant, decision = choice.variant, entry.launch_plan(choice.variant, budget).decision
        total = entry.download_bytes(variant)
        row.update(fits=True, model_id=variant.model_id, quant=variant.quant,
                   quant_validated=variant.validated, size_bytes=total,
                   size_label=_human_gb(total), variant_count=len(entry.variants),
                   quant_reason=f"Recommended build ({variant.quant}) for this machine")
        if isinstance(decision, estimator.PhysicsRefusal):
            row["fit_summary"] = row["quant_reason"]
            return row
        row.update(start_window=decision.window, start_window_label=_k_label(decision.window),
                   spilled=decision.spilled)
        shape = (f"runs at its full {row['native_context_label']} context"
                 if decision.window >= entry.n_ctx_train else
                 f"starts at {row['start_window_label']} and grows toward "
                 f"{row['native_context_label']} as you use it")
        row["fit_summary"] = shape + (" (larger than your GPU memory — runs slower)"
                                      if decision.spilled else "")
        return row

    @staticmethod
    def _log_tail(log_path: Path, lines: int = 60) -> str | None:
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            return "\n".join(text.splitlines()[-lines:])
        except OSError:
            return None
