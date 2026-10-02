from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "1.0"
PARTICIPANTS = ("atlas", "claude", "codex", "opencode", "pi", "hermes", "zcode", "fake")
JUNK_NAMES = {"__pycache__", ".DS_Store", "Thumbs.db", "node_modules", ".pytest_cache", ".mypy_cache"}
JUNK_SUFFIXES = {".pyc", ".pyo", ".tmp", ".swp", ".bak"}
SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)[\"']?[^\s,;\"']+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
)


@dataclass
class WorkspaceInspection:
    changed_files: list[str]
    forbidden_changes: list[str]
    test_files_deleted: list[str]
    junk_files: list[str]
    symlink_files: list[str]
    before: dict[str, str]
    after: dict[str, str]


class ScenarioController:
    """Small adapter hook for scheduling steps and recording observed events."""

    def __init__(self, scenario: dict[str, Any] | None, workspace: Path | None = None):
        self.steps = list((scenario or {}).get("steps", []))
        self.events: list[dict[str, Any]] = []
        self.workspace = workspace
        self._baseline = _snapshot(workspace) if workspace else {}
        self._issued: set[int] = set()
        self._delivered: set[int] = set()
        self.started = time.monotonic()

    def due_steps(self, event: str | None = None, elapsed_seconds: float | None = None) -> list[dict[str, Any]]:
        elapsed = time.monotonic() - self.started if elapsed_seconds is None else elapsed_seconds
        for index, step in enumerate(self.steps):
            if index in self._delivered:
                continue
            if index in self._issued:
                return []
            trigger = step.get("trigger") or {}
            due_now = (not trigger or
                       (trigger.get("event") is not None and event == trigger.get("event")) or
                       (trigger.get("after_seconds") is not None and elapsed >= float(trigger["after_seconds"])))
            if due_now:
                self._issued.add(index)
                return [step]
            return []
        return []

    def emit(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            raise TypeError("scenario events must be dictionaries")
        self.events.append(dict(event))

    def record_delivery(self, step: dict[str, Any], evidence: dict[str, Any]) -> None:
        """Record native delivery evidence supplied by an adapter after confirmation."""
        try:
            index = next(i for i, candidate in enumerate(self.steps) if candidate is step)
        except StopIteration:
            index = next((i for i, candidate in enumerate(self.steps) if candidate == step), -1)
        if index < 0:
            raise ValueError("delivered scenario step is not part of this scenario")
        self._delivered.add(index)
        self.emit({"kind": "scenario_step_delivered", "step_index": index,
                   "action": step.get("action"), "evidence": evidence})

    def snapshot_before_approval(self) -> list[str]:
        """Capture workspace changes at the moment before a native approval action."""
        current = _snapshot(self.workspace) if self.workspace else {}
        changed = sorted(path for path in set(self._baseline) | set(current)
                         if self._baseline.get(path) != current.get(path))
        self.emit({"kind": "workspace_snapshot", "point": "before_approve", "changed_files": changed})
        return changed


def _safe_rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        rel = _safe_rel(root, path)
        if rel == ".git" or rel.startswith(".git/"):
            continue
        try:
            if path.is_symlink():
                result[rel] = "symlink:" + os.readlink(path)
            elif path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                result[rel] = f"file:{path.stat().st_mode & 0o777}:{digest}"
        except (OSError, ValueError):
            result[rel] = "unreadable"
    return result


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) or (pattern.endswith("/**") and path.startswith(pattern[:-3] + "/")) for pattern in patterns)


def _is_test_path(path: str) -> bool:
    name = Path(path).name.lower()
    parts = {part.lower() for part in Path(path).parts}
    return "tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py")


def _is_junk(path: str) -> bool:
    p = Path(path)
    return any(part in JUNK_NAMES for part in p.parts) or p.suffix.lower() in JUNK_SUFFIXES


def inspect_workspace(root: Path, protected_paths: list[str] | None = None,
                      allowed_changes: list[str] | None = None,
                      before: dict[str, str] | None = None) -> WorkspaceInspection:
    protected = protected_paths if protected_paths is not None else ["tests/**"]
    allowed = allowed_changes or []
    start = before if before is not None else _snapshot(root)
    end = _snapshot(root)
    changed = sorted(path for path in set(start) | set(end) if start.get(path) != end.get(path))
    forbidden = sorted(path for path in changed if not _matches(path, allowed))
    deleted_tests = sorted(path for path in start.keys() - end.keys() if _is_test_path(path))
    for path in changed:
        if _matches(path, protected) and path in start and start.get(path) != end.get(path):
            if path not in forbidden:
                forbidden.append(path)
    junk = sorted(path for path in end if _is_junk(path))
    symlinks = sorted(path for path, value in end.items() if value.startswith("symlink:"))
    forbidden.extend(path for path in symlinks if path in changed)
    return WorkspaceInspection(changed, sorted(set(forbidden)), deleted_tests, junk, symlinks, start, end)


def fixture_fingerprint(task_dir: Path) -> str:
    entries = {name: digest for name, digest in _snapshot(task_dir).items() if not _is_junk(name)}
    return fingerprint_for(entries)


def implementation_fingerprint() -> str:
    entries = {}
    for folder in (ROOT / "harness", ROOT / "participants", ROOT / "fixtures", ROOT / "fault_proxy"):
        for name, digest in _snapshot(folder).items():
            if name.endswith(".py") and not _is_junk(name) and "tests/" not in name:
                entries[folder.name + "/" + name] = digest
    entries["run.py"] = hashlib.sha256((ROOT / "run.py").read_bytes()).hexdigest()
    return fingerprint_for(entries)


def prepare_scenario(scenario: dict[str, Any] | None, config: dict[str, Any]) -> dict[str, Any] | None:
    """Expand explicitly configured context steps into deterministic local text."""
    if scenario is None:
        return None
    prepared = json.loads(json.dumps(scenario))
    window = config.get("context_window_tokens")
    if window is None:
        window = config.get("tracks", {}).get(config.get("_selected_track", "same-model"), {}).get("context_window_tokens")
    for step in prepared.get("steps", []):
        if step.get("action") != "context" or not ("target_tokens" in step or "target_fraction" in step):
            continue
        target = step.get("target_tokens")
        if target is None and window is not None:
            target = int(int(window) * float(step["target_fraction"]))
        if target is None:
            raise ValueError("context_window_tokens is required for context pressure scenario")
        target = max(1, min(int(target), 2_000_000))
        prefix = str(step.get("text", ""))
        filler_line = str(step.get("filler", "T1 context carry-forward marker.")) + "\n"
        needed_chars = max(0, target * 4 - len(prefix))
        filler = (filler_line * ((needed_chars // len(filler_line)) + 1))[:needed_chars]
        step["text"] = prefix + filler
        step["generated_context_target_tokens"] = target
    return prepared


def fingerprint_for(data: Any) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def is_resume_match(result: dict[str, Any], fingerprint: str) -> bool:
    return result.get("fingerprint") == fingerprint and result.get("status") in {"completed", "unsupported"}


def build_result(**values: Any) -> dict[str, Any]:
    result = {
        "schema_version": SCHEMA_VERSION,
        "participant": None, "track": None, "model": None, "task_id": None, "attempt": 1,
        "status": "completed", "success": None, "check_exit_code": None, "participant_exit_code": None, "duration_ms": None, "total_duration_ms": None,
        "tool_calls": None, "turns": None, "input_tokens": None, "output_tokens": None,
        "cached_tokens": None, "cost_usd": None, "changed_files": [], "forbidden_changes": [],
        "test_files_deleted": [], "junk_files": [], "runner_error": None, "participant_error": None,
        "raw_log_paths": {}, "usage_source": "unknown", "scenario_events": [], "fingerprint": None,
        "unsupported": [], "git_diff_path": None,
        "approval_changed_files": [],
    }
    result.update(values)
    validate_result(result)
    return result


def validate_result(result: Any) -> None:
    required = {
        "schema_version": str, "participant": str, "track": str, "model": (str, type(None)),
        "task_id": str, "attempt": int, "status": str, "success": (bool, type(None)),
        "check_exit_code": (int, type(None)), "participant_exit_code": (int, type(None)), "duration_ms": (int, float, type(None)), "total_duration_ms": (int, float, type(None)),
        "tool_calls": (int, type(None)), "turns": (int, type(None)),
        "input_tokens": (int, type(None)), "output_tokens": (int, type(None)),
        "cached_tokens": (int, type(None)), "cost_usd": (int, float, type(None)),
        "changed_files": list, "forbidden_changes": list, "test_files_deleted": list,
        "junk_files": list, "runner_error": (str, type(None)), "participant_error": (str, type(None)),
        "raw_log_paths": dict, "usage_source": str, "scenario_events": list,
        "fingerprint": (str, type(None)), "unsupported": list, "git_diff_path": (str, type(None)),
        "approval_changed_files": list,
    }
    if not isinstance(result, dict):
        raise ValueError("result must be an object")
    extra = set(result) - set(required)
    if extra:
        raise ValueError("unknown result field(s): " + ", ".join(sorted(extra)))
    for key, expected in required.items():
        if key not in result or not isinstance(result[key], expected):
            raise ValueError(f"result field {key!r} is missing or has the wrong type")
        if key in {"check_exit_code", "participant_exit_code"} and isinstance(result[key], bool):
            raise ValueError(f"result field {key!r} cannot be boolean")
        if key in {"attempt", "tool_calls", "turns", "input_tokens", "output_tokens", "cached_tokens", "duration_ms", "total_duration_ms", "cost_usd"}:
            value = result[key]
            if isinstance(value, bool):
                raise ValueError(f"result field {key!r} cannot be boolean")
            if value is not None and value < (1 if key == "attempt" else 0):
                raise ValueError(f"result field {key!r} cannot be negative or zero")
            if value is not None and not math.isfinite(value):
                raise ValueError(f"result field {key!r} must be finite")
    if result["status"] not in {"completed", "unsupported", "unavailable", "runner_error", "real_execution_denied", "dry_run"}:
        raise ValueError(f"invalid result status: {result['status']}")
    for key in ("changed_files", "forbidden_changes", "test_files_deleted", "junk_files", "approval_changed_files"):
        if not all(isinstance(v, str) for v in result[key]):
            raise ValueError(f"result field {key!r} must contain strings")
    if not all(isinstance(value, str) for value in result["unsupported"]):
        raise ValueError("unsupported must contain strings")
    if not all(isinstance(event, dict) for event in result["scenario_events"]):
        raise ValueError("scenario_events must contain objects")
    if not all(isinstance(value, str) for value in result["raw_log_paths"].values()):
        raise ValueError("raw_log_paths must contain strings")


def _load_manifest(task_dir: Path) -> dict[str, Any]:
    with (task_dir / "manifest.toml").open("rb") as f:
        manifest = tomllib.load(f)
    for key in ("id", "title", "kind", "allowed_changes", "timeout_seconds", "multi_round", "capabilities"):
        if key not in manifest:
            raise ValueError(f"{task_dir.name}: manifest missing {key}")
    return manifest


def _redact(text: str, config: dict[str, Any] | None = None) -> str:
    value = text
    for name, secret in os.environ.items():
        if any(word in name.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")) and len(secret) >= 8:
            value = value.replace(secret, "[REDACTED]")
    for key, secret in (config or {}).items():
        if any(word in str(key).lower() for word in ("key", "secret", "token", "password")) and isinstance(secret, str) and secret:
            value = value.replace(secret, "[REDACTED]")
    for pattern in SECRET_PATTERNS:
        value = pattern.sub(lambda m: (m.group(1) + m.group(2) + "[REDACTED]") if m.lastindex and m.lastindex >= 2 else "[REDACTED]", value)
    return value


def _copy_fixture(task_dir: Path, workspace: Path) -> None:
    fixture = task_dir / "fixture"
    if not fixture.is_dir():
        raise ValueError(f"fixture directory is missing: {fixture}")
    shutil.copytree(fixture, workspace, dirs_exist_ok=True, symlinks=True)
    setup = task_dir / "setup.py"
    if setup.is_file():
        completed = subprocess.run([sys.executable, str(setup), str(workspace)], cwd=task_dir, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=600)
        if completed.returncode:
            raise RuntimeError(f"setup.py exited {completed.returncode}: {completed.stderr[-2000:]}")


def _cleanup_fixture(task_dir: Path, workspace: Path) -> None:
    cleanup = task_dir / "cleanup.py"
    if cleanup.is_file():
        proc = subprocess.run([sys.executable, str(cleanup), str(workspace)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if proc.returncode:
            raise RuntimeError("fixture cleanup failed: " + proc.stderr[-1000:])


@contextmanager
def _temporary_workspace(task_dir: Path):
    with tempfile.TemporaryDirectory(prefix="t1-中文-") as temp:
        workspace = Path(temp) / "工作副本"
        workspace.mkdir()
        try:
            yield workspace
        finally:
            _cleanup_fixture(task_dir, workspace)


def _git_baseline(workspace: Path) -> str:
    env = _git_env()
    commands = [
        ["git", "init", "-q", "--template="], ["git", "config", "user.email", "t1-runner@localhost"],
        ["git", "config", "user.name", "T1 Runner"], ["git", "add", "-A"],
        ["git", "commit", "-qm", "T1 fixture baseline"],
    ]
    for command in commands:
        subprocess.run(command, cwd=workspace, check=True, capture_output=True, env=env, timeout=120)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=workspace, check=True, capture_output=True, text=True, env=env, timeout=10).stdout.strip()


def _git_env():
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
    return env


def _make_diff(workspace: Path, baseline: str, inspection: WorkspaceInspection, path: Path, config=None) -> None:
    tracked = subprocess.run(["git", "diff", baseline, "--"], cwd=workspace, capture_output=True, env=_git_env(), timeout=60, check=True).stdout
    chunks = [tracked]
    for name in inspection.changed_files:
        if name not in inspection.after or name in inspection.before:
            continue
        candidate = workspace / Path(name)
        if candidate.is_symlink():
            payload = f"symlink -> {os.readlink(candidate)}\n".encode()
        elif candidate.is_file():
            payload = candidate.read_bytes()
            if b"\0" in payload:
                payload = ("binary file; bytes=" + str(len(payload)) + "; sha256=" + hashlib.sha256(payload).hexdigest()).encode()
            else:
                try:
                    payload.decode("utf-8")
                except UnicodeDecodeError:
                    payload = ("binary file; bytes=" + str(len(payload)) + "; sha256=" + hashlib.sha256(payload).hexdigest()).encode()
        else:
            continue
        chunks.append(f"\n--- untracked: {name} ---\n".encode() + payload + b"\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_redact(b"".join(chunks).decode("utf-8", "replace"), config), encoding="utf-8")


def _run_check(task_dir: Path, workspace: Path, timeout: float, fault_evidence: Path | None = None) -> tuple[int | None, str]:
    py = task_dir / "check.py"
    ps = task_dir / "check.ps1"
    if py.is_file():
        command = [sys.executable, str(py), str(workspace)]
    elif ps.is_file():
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps), str(workspace)]
    else:
        raise ValueError("task requires check.py or check.ps1")
    try:
        check_env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
        check_env.pop("T1_FAULT_EVIDENCE_PATH", None)
        if fault_evidence:
            check_env["T1_FAULT_EVIDENCE_PATH"] = str(fault_evidence)
        proc = subprocess.run(command, cwd=workspace, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=check_env)
        return proc.returncode, _redact(proc.stdout + proc.stderr)
    except subprocess.TimeoutExpired as exc:
        def decoded(value):
            return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")
        return None, _redact(decoded(exc.stdout) + decoded(exc.stderr) + "check timeout")


def _adapter_worker(participant: str, config: dict[str, Any], task_id: str, workspace: str,
                    task_dir: str, prompt: str, model: str | None, timeout_seconds: float,
                    scenario: dict[str, Any] | None, result_file: str) -> None:
    result: dict[str, Any]
    controller = ScenarioController(scenario)
    stack = ExitStack()
    try:
        if os.name != "nt":
            os.setsid()
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT.parents[1]))
        from participants import get_adapter
        adapter_config = dict(config.get("participants", {}).get(participant, config))
        proxy = None
        if task_id == "20" and participant != "fake":
            from fault_proxy import FaultProxy
            proxy_config = adapter_config.get("fault_proxy", {})
            proxy = stack.enter_context(FaultProxy(upstream_url=proxy_config.get("upstream_url"),
                                                   timeout=min(timeout_seconds, 15)))
            adapter_config["fault_proxy_url"] = proxy.url
        adapter = get_adapter(participant, adapter_config)
        method = getattr(adapter, "run_scenario", None)
        from participants.base import RunContext
        pressure_config = dict(config)
        if "context_window_tokens" in adapter_config:
            pressure_config["context_window_tokens"] = adapter_config["context_window_tokens"]
        elif participant == "fake" and "context_window_tokens" not in pressure_config:
            pressure_config["context_window_tokens"] = 1024
        prepared_scenario = prepare_scenario(scenario, pressure_config)
        context = RunContext(task_id=task_id, workspace=Path(workspace), task_dir=Path(task_dir),
                             prompt=prompt, model=model, timeout_seconds=timeout_seconds,
                             config=adapter_config, scenario=prepared_scenario)
        controller = ScenarioController(prepared_scenario, Path(workspace))
        outcome = method(context, controller) if method and prepared_scenario else adapter.run_once(context)
        if proxy is not None:
            outcome.events.append({"type": "provider_fault_trace", "source": "configured-upstream-proxy",
                                   "requests": list(proxy.requests),
                                   "recovered": any(_provider_request_completed(r) for r in proxy.requests)})
        result = {
            "exit_code": getattr(outcome, "exit_code", None),
            "stdout": getattr(outcome, "stdout", ""), "stderr": getattr(outcome, "stderr", ""),
            "events": getattr(outcome, "events", []) or [], "duration_ms": getattr(outcome, "duration_ms", 0),
            "error": getattr(outcome, "error", None), "unsupported": getattr(outcome, "unsupported", []) or [],
            "usage": {**(adapter.parse_usage(outcome) or {}), "source": "fake" if participant == "fake" else "native_log"},
            "scenario_events": controller.events,
        }
    except Exception as exc:
        result = {"worker_error": f"{type(exc).__name__}: {exc}", "scenario_events": controller.events}
    finally:
        try:
            if "adapter" in locals():
                adapter.cleanup()
        except Exception:
            pass
        stack.close()
        Path(result_file).write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")


def _call_adapter(participant: str, config: dict[str, Any], task_id: str, workspace: Path,
                  task_dir: Path, prompt: str, model: str | None, timeout: float,
                  scenario: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    import multiprocessing
    ctx = multiprocessing.get_context("spawn")
    fd, temp_name = tempfile.mkstemp(prefix="t1-adapter-", suffix=".json")
    os.close(fd)
    temp = Path(temp_name)
    proc = ctx.Process(target=_adapter_worker, args=(participant, config, task_id, str(workspace), str(task_dir), prompt,
                                                     model, timeout, scenario, str(temp)))
    proc.start()
    proc.join(timeout)
    timed_out = proc.is_alive()
    if timed_out:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if proc.is_alive():
            proc.terminate()
        proc.join(2)
        if proc.is_alive() and hasattr(proc, "kill"):
            proc.kill()
            proc.join()
    try:
        data = json.loads(temp.read_text(encoding="utf-8")) if temp.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    finally:
        temp.unlink(missing_ok=True)
    if timed_out:
        return {"error": f"participant timeout after {timeout:g}s", "scenario_events": []}, True
    if proc.exitcode not in (0, None) and not data:
        return {"worker_error": f"adapter worker exited {proc.exitcode}", "scenario_events": []}, False
    return data, False


def _load_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _provider_request_completed(request: Any) -> bool:
    return (isinstance(request, dict) and request.get("fault") is None
            and request.get("status") == 200 and request.get("completed") is True
            and not request.get("upstream_error")
            and (not request.get("stream") or request.get("stream_done") is True))


def fault_trace_valid(trace: Any) -> bool:
    if not isinstance(trace, dict) or trace.get("recovered") is not True:
        return False
    requests = trace.get("requests")
    return (isinstance(requests, list) and len(requests) >= 4
            and all(isinstance(r, dict) for r in requests)
            and [r.get("fault") for r in requests[:3]] == ["429", "500", "disconnect"]
            and any(_provider_request_completed(r) for r in requests[3:]))


def _task_ids(task_arg: str | None) -> list[str]:
    available = sorted(p.name for p in (ROOT / "tasks").iterdir() if p.is_dir() and p.name.isdigit())
    if not task_arg:
        return available
    selected: set[str] = set()
    for token in task_arg.split(","):
        token = token.strip()
        if "-" in token:
            left, right = token.split("-", 1)
            width = max(len(left), len(right), 2)
            selected.update(f"{n:0{width}d}" for n in range(int(left), int(right) + 1))
        else:
            selected.add(token.zfill(2) if token.isdigit() else token)
    unknown = selected - set(available)
    if unknown:
        raise ValueError("unknown task id(s): " + ", ".join(sorted(unknown)))
    return sorted(selected)


def _load_scenario(task_dir: Path) -> dict[str, Any] | None:
    path = task_dir / "scenario.json"
    if not path.is_file():
        return None
    scenario = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(scenario, dict) or not isinstance(scenario.get("steps", []), list):
        raise ValueError(f"invalid scenario: {path}")
    return scenario


def summarize(output_dir: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*.result.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            validate_result(data)
            records.append(data)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    def group(key: str) -> dict[str, Any]:
        out: dict[str, list[dict[str, Any]]] = {}
        for row in records:
            out.setdefault(str(row[key]), []).append(row)
        return {name: _aggregate(rows) for name, rows in sorted(out.items())}
    per_task_participant = {}
    for task_id in sorted({row["task_id"] for row in records}):
        selected = [row for row in records if row["task_id"] == task_id]
        per_task_participant[task_id] = {name: _aggregate([row for row in selected if row["participant"] == name]) for name in sorted({row["participant"] for row in selected})}
    status_counts = {status: sum(row["status"] == status for row in records) for status in sorted({row["status"] for row in records})}
    return {"runs": len(records), "per_task": group("task_id"), "per_participant": group("participant"), "per_track": group("track"), "per_task_participant": per_task_participant, "status_counts": status_counts,
            "success_rate": _ratio(records), "average_duration_ms": _mean_known(records, "duration_ms"),
            "known_cost_usd": _sum_known(records, "cost_usd"),
            "unknown_cost_runs": sum(row["cost_usd"] is None for row in records),
            "forbidden_change_rate": (sum(bool(row["forbidden_changes"]) for row in records) / len(records)) if records else None}


def _ratio(rows: list[dict[str, Any]]) -> float | None:
    known = [row["success"] for row in rows if row["success"] is not None]
    return sum(known) / len(known) if known else None


def _mean_known(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if isinstance(row.get(key), (int, float)) and (key != "duration_ms" or row.get("status") == "completed")]
    return sum(values) / len(values) if values else None


def _sum_known(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
    return sum(values) if values else None


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"runs": len(rows), "success_rate": _ratio(rows), "average_duration_ms": _mean_known(rows, "duration_ms"),
            "evaluated_runs": sum(r["success"] is not None for r in rows),
            "status_counts": {status: sum(row["status"] == status for row in rows) for status in sorted({row["status"] for row in rows})},
            "best_success": max((r["success"] for r in rows if r["success"] is not None), default=None),
            "best_duration_ms": min((r["duration_ms"] for r in rows if r.get("status") == "completed" and isinstance(r.get("duration_ms"), (int, float))), default=None),
            "input_tokens": _sum_known(rows, "input_tokens"), "output_tokens": _sum_known(rows, "output_tokens"),
            "cached_tokens": _sum_known(rows, "cached_tokens"),
            "cost_usd": _sum_known(rows, "cost_usd"), "unknown_cost_runs": sum(r["cost_usd"] is None for r in rows),
            "forbidden_change_rate": (sum(bool(r["forbidden_changes"]) for r in rows) / len(rows)) if rows else None}


def execute(args: Any) -> int:
    output = Path(args.output).resolve()
    if args.summary:
        summary = json.dumps(summarize(output), indent=2, ensure_ascii=False)
        output.mkdir(parents=True, exist_ok=True)
        (output / "summary.json").write_text(summary, encoding="utf-8")
        print(summary)
        return 0
    tasks = _task_ids(args.task)
    config = _load_config(Path(args.config) if args.config else None)
    config["_selected_track"] = args.track
    overrides = config.get("participant_commands", {})
    if args.participant in overrides:
        config.setdefault("participants", {}).setdefault(args.participant, {})["command"] = overrides[args.participant]
    cli_cfg = config.get("participants", {}).get(args.participant, {})
    if not isinstance(cli_cfg, dict):
        cli_cfg = {}
    config_for_fingerprint = json.loads(json.dumps(config, default=str))
    implementation = implementation_fingerprint()
    model = args.model or config.get("tracks", {}).get(args.track, {}).get("models", {}).get(args.participant)
    if not args.dry_run and args.participant != "fake" and not args.allow_real:
        print("real participants are disabled; pass --allow-real only for an explicitly authorized real run", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)
    attempts = {task_id: 0 for task_id in tasks}
    budget_records = [r for p in output.rglob("*.result.json") for r in [_read_json(p)] if r and r.get("status") != "dry_run" and (r.get("status") in {"completed", "runner_error"} or r.get("participant_exit_code") is not None or r.get("cost_usd") is not None)]
    known_costs = [r["cost_usd"] for r in budget_records if r.get("cost_usd") is not None]
    unknown_prior = any(r.get("cost_usd") is None for r in budget_records)
    spent = sum(float(c) for c in known_costs)
    if not args.dry_run and args.budget_usd is not None and unknown_prior:
        print("budget cannot be enforced: prior result has unknown cost", file=sys.stderr)
        return 3
    for task_id in tasks:
        task_dir = ROOT / "tasks" / task_id
        manifest = _load_manifest(task_dir)
        if getattr(args, "timeout_seconds", None) is not None:
            manifest["timeout_seconds"] = float(args.timeout_seconds)
        scenario = _load_scenario(task_dir)
        fingerprint = fingerprint_for({"participant": args.participant, "track": args.track, "model": model,
                                      "task": fixture_fingerprint(task_dir), "config": fingerprint_for(config_for_fingerprint), "timeout_seconds": manifest["timeout_seconds"], "implementation": implementation})
        task_output = output / args.participant / args.track / f"task-{task_id}"
        task_output.mkdir(parents=True, exist_ok=True)
        prior = [_read_json(p) for p in sorted(task_output.rglob("*.result.json"))]
        matching_prior = [row for row in prior if row and is_resume_match(row, fingerprint)]
        completed_count = len(matching_prior) if args.resume else 0
        if completed_count >= args.repeat:
            continue
        if not args.dry_run and args.budget_usd is not None and spent >= args.budget_usd:
            print("budget exhausted; stopping before next attempt", file=sys.stderr)
            return 0
        for repeat in range(completed_count, args.repeat):
            attempt = 1 + max([row.get("attempt", 0) for row in prior if row] + [attempts[task_id]])
            attempts[task_id] = attempt
            logs = task_output / f"attempt-{attempt:03d}"
            logs.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            print(f"{args.participant} task {task_id} attempt {attempt}: prepare", file=sys.stderr, flush=True)
            base = dict(participant=args.participant, track=args.track, model=model, task_id=task_id, attempt=attempt,
                        fingerprint=fingerprint)
            if args.dry_run:
                try:
                    from participants import get_adapter
                    adapter = get_adapter(args.participant, cli_cfg)
                    from participants.base import RunContext
                    context_stub = RunContext(task_id=task_id, workspace=Path("<dry-run>"), task_dir=task_dir,
                                              prompt=str((task_dir / "task.md").read_text(encoding="utf-8")), model=model,
                                              timeout_seconds=float(manifest["timeout_seconds"]), config=cli_cfg,
                                              scenario=scenario)
                    command = adapter.build_command(context_stub)
                    command_text = _redact(subprocess.list2cmdline(command), cli_cfg)
                    (logs / "command.txt").write_text(command_text + "\n", encoding="utf-8")
                    adapter.cleanup()
                    result = build_result(**base, status="dry_run", success=None, runner_error=None,
                                          duration_ms=(time.monotonic() - started) * 1000,
                                          raw_log_paths={"command": str(logs / "command.txt")})
                except Exception as exc:
                    result = build_result(**base, status="unavailable", success=None,
                                          runner_error=_redact(f"{type(exc).__name__}: {exc}", cli_cfg),
                                          duration_ms=(time.monotonic() - started) * 1000)
            else:
                try:
                    with _temporary_workspace(task_dir) as workspace:
                        _copy_fixture(task_dir, workspace)
                        print(f"{args.participant} task {task_id}: git baseline", file=sys.stderr, flush=True)
                        baseline = _git_baseline(workspace)
                        before = _snapshot(workspace)
                        print(f"{args.participant} task {task_id}: participant", file=sys.stderr, flush=True)
                        from participants import get_adapter
                        adapter = get_adapter(args.participant, cli_cfg)
                        availability = adapter.availability()
                        if not availability.get("available"):
                            result = build_result(**base, status="unavailable", success=None,
                                                  runner_error=_redact(str(availability.get("reason", "unavailable")), cli_cfg),
                                                  duration_ms=(time.monotonic() - started) * 1000)
                        else:
                            required = list(manifest.get("capabilities", []))
                            if scenario:
                                aliases = {"prompt": "multi_round", "approve": "approval"}
                                required += [aliases.get(step.get("action", ""), step.get("action", ""))
                                             for step in scenario.get("steps", [])]
                            unsupported = sorted({cap for cap in required if cap and not adapter.supports(cap)})
                            if unsupported:
                                result = build_result(**base, status="unsupported", success=None, unsupported=unsupported,
                                                      duration_ms=(time.monotonic() - started) * 1000)
                            else:
                                prompt = (task_dir / "task.md").read_text(encoding="utf-8")
                                participant_started = time.monotonic()
                                data, timed_out = _call_adapter(args.participant, config, task_id, workspace, task_dir,
                                                                prompt, model, float(manifest["timeout_seconds"]), scenario)
                                participant_duration_ms = (time.monotonic() - participant_started) * 1000
                                print(f"{args.participant} task {task_id}: check", file=sys.stderr, flush=True)
                                stdout = _redact(str(data.get("stdout", "")), cli_cfg)
                                stderr = _redact(str(data.get("stderr", "")), cli_cfg)
                                (logs / "stdout.txt").write_text(stdout, encoding="utf-8")
                                (logs / "stderr.txt").write_text(stderr, encoding="utf-8")
                                events = data.get("events", []) or []
                                scenario_events = data.get("scenario_events", []) or []
                                approval_snapshots = [event for event in scenario_events
                                                      if event.get("kind") == "workspace_snapshot" and event.get("point") == "before_approve"]
                                approval_changed = sorted({name for event in approval_snapshots
                                                           for name in event.get("changed_files", [])})
                                if scenario and any(step.get("action") == "approve" for step in scenario.get("steps", [])) and not approval_snapshots:
                                    participant_error = "missing trusted workspace snapshot immediately before approval"
                                else:
                                    participant_error = None
                                fault_evidence = None
                                if task_id == "20":
                                    traces = [e for e in events if e.get("type") == "provider_fault_trace"]
                                    fault_evidence = logs / "fault_proxy.json"
                                    fault_evidence.write_text(_redact(json.dumps(traces, indent=2), cli_cfg), encoding="utf-8")
                                    if len(traces) != 1 or not fault_trace_valid(traces[0]):
                                        participant_error = "missing observed provider fault sequence and recovery"
                                serialized_events = json.dumps({"events": events, "scenario_events": scenario_events}, indent=2, ensure_ascii=False)
                                (logs / "events.json").write_text(_redact(serialized_events, cli_cfg), encoding="utf-8")
                                inspection = inspect_workspace(workspace, manifest.get("protected_paths", ["tests/**"]),
                                                               manifest["allowed_changes"], before)
                                diff_path = logs / "diff.patch"
                                _make_diff(workspace, baseline, inspection, diff_path, cli_cfg)
                                check_code, check_output = _run_check(task_dir, workspace, float(manifest["timeout_seconds"]), fault_evidence)
                                (logs / "check.log").write_text(_redact(check_output, cli_cfg), encoding="utf-8")
                                usage = data.get("usage", {}) or {}
                                participant_error = data.get("error") or data.get("worker_error") or participant_error
                                out_unsupported = data.get("unsupported", []) or []
                                status = "unsupported" if out_unsupported else ("runner_error" if data.get("worker_error") else "completed")
                                result = build_result(**base, status=status,
                                    success=(check_code == 0 and data.get("exit_code") == 0 and not out_unsupported and not inspection.forbidden_changes
                                             and not approval_changed and not participant_error) if status == "completed" else None,
                                    check_exit_code=check_code, participant_exit_code=data.get("exit_code"), duration_ms=participant_duration_ms, total_duration_ms=(time.monotonic() - started) * 1000,
                                    tool_calls=usage.get("tool_calls"), turns=usage.get("turns"),
                                    input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                                    cached_tokens=usage.get("cached_tokens"), cost_usd=usage.get("cost_usd"),
                                    usage_source=usage.get("source", "unknown"), changed_files=inspection.changed_files,
                                    forbidden_changes=inspection.forbidden_changes, test_files_deleted=inspection.test_files_deleted,
                                    junk_files=inspection.junk_files, runner_error=_redact(data.get("worker_error", "") or "", cli_cfg) or None,
                                    participant_error=_redact(str(data.get("error") or participant_error), cli_cfg)
                                                      if (data.get("error") or participant_error) else None,
                                    raw_log_paths={"stdout": str(logs / "stdout.txt"), "stderr": str(logs / "stderr.txt"),
                                                   "events": str(logs / "events.json"), "check": str(logs / "check.log"),
                                                   **({"fault_proxy": str(fault_evidence)} if fault_evidence else {})},
                                    scenario_events=json.loads(_redact(json.dumps(scenario_events), cli_cfg)), unsupported=out_unsupported, git_diff_path=str(diff_path),
                                    approval_changed_files=approval_changed)
                                if result["cost_usd"] is not None:
                                    spent += float(result["cost_usd"])
                                elif args.budget_usd is not None:
                                    result["runner_error"] = "cost unknown; budget enforcement stops after this attempt"
                        if 'result' not in locals():
                            raise RuntimeError("runner did not produce a result")
                except Exception as exc:
                    result = build_result(**base, status="runner_error", success=None,
                                          runner_error=_redact(f"{type(exc).__name__}: {exc}", cli_cfg),
                                          duration_ms=(time.monotonic() - started) * 1000)
            result_path = logs / f"task-{task_id}.result.json"
            result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            possibly_spent = result["status"] in {"completed", "runner_error"} or result["participant_exit_code"] is not None
            if not args.dry_run and args.budget_usd is not None and (spent >= args.budget_usd or (possibly_spent and result["cost_usd"] is None)):
                print("budget exhausted or unknown; stopping after current attempt", file=sys.stderr)
                return 0
    summary = json.dumps(summarize(output), indent=2, ensure_ascii=False)
    (output / "summary.json").write_text(summary, encoding="utf-8")
    print(summary)
    return 0


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
