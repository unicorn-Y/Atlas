#!/usr/bin/env python3
"""Bounded test-command runner with separate complete logs and PID identity checks."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Sequence

import psutil


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created_at: float


def _matches(identity: ProcessIdentity, process: Any) -> bool:
    try:
        return abs(float(process.create_time()) - identity.created_at) < 0.001
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, ValueError):
        return False


def signal_if_same_process(identity: ProcessIdentity, *, force: bool = False) -> str:
    """Signal only the process instance whose PID and creation time were recorded."""
    try:
        process = psutil.Process(identity.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return "gone"
    if not _matches(identity, process):
        return "pid_reused"
    try:
        process.kill() if force else process.terminate()
    except psutil.NoSuchProcess:
        return "gone"
    except (psutil.AccessDenied, OSError):
        return "signal_failed"
    return "signalled"


def _alive(identity: ProcessIdentity) -> bool:
    try:
        process = psutil.Process(identity.pid)
        return _matches(identity, process) and process.is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False


def _snapshot_tree(root: ProcessIdentity) -> dict[tuple[int, float], ProcessIdentity]:
    result = {(root.pid, root.created_at): root}
    try:
        process = psutil.Process(root.pid)
        if not _matches(root, process):
            return result
        for child in process.children(recursive=True):
            try:
                identity = ProcessIdentity(int(child.pid), float(child.create_time()))
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, ValueError):
                continue
            result[(identity.pid, identity.created_at)] = identity
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        pass
    return result


def run_command(
    command: Sequence[str],
    *,
    cwd: str | os.PathLike[str],
    log_dir: str | os.PathLike[str],
    timeout_seconds: float,
    cleanup_seconds: float = 2.0,
    poll_interval: float = 0.025,
) -> dict[str, Any]:
    """Run a command to a hard deadline; preserve full output and report owned leftovers.

    `timeout_seconds` bounds useful execution. Cleanup has its own explicit finite allowance,
    so the total wall-clock bound is timeout_seconds + cleanup_seconds.
    """
    if not command or any(not isinstance(value, str) or not value for value in command):
        raise ValueError("command must be a non-empty sequence of non-empty strings")
    if timeout_seconds <= 0 or cleanup_seconds < 0 or poll_interval <= 0:
        raise ValueError("timeouts and poll interval must be positive")
    workdir = Path(cwd).resolve()
    logs = Path(log_dir).resolve()
    if not workdir.is_dir():
        raise ValueError("cwd must be an existing directory")
    logs.mkdir(parents=True, exist_ok=True)
    stdout_path, stderr_path = logs / "stdout.log", logs / "stderr.log"
    summary_path = logs / "result.json"
    started = time.monotonic()
    deadline = started + timeout_seconds
    cleanup_deadline = deadline + cleanup_seconds
    proc: subprocess.Popen[bytes] | None = None
    root_identity: ProcessIdentity | None = None
    owned: dict[tuple[int, float], ProcessIdentity] = {}
    timed_out = False
    returncode: int | None = None
    signal_results: list[dict[str, Any]] = []

    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        try:
            proc = subprocess.Popen(
                list(command), cwd=workdir, stdin=subprocess.DEVNULL,
                stdout=stdout_file, stderr=stderr_file, shell=False, close_fds=True,
                creationflags=creationflags, start_new_session=(os.name != "nt"),
            )
            try:
                root_process = psutil.Process(proc.pid)
                root_identity = ProcessIdentity(proc.pid, float(root_process.create_time()))
                owned[(root_identity.pid, root_identity.created_at)] = root_identity
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, ValueError):
                root_identity = None
            while root_identity is not None and time.monotonic() < deadline:
                owned.update(_snapshot_tree(root_identity))
                process_running = proc.poll() is None
                descendants_running = any(
                    identity != root_identity and _alive(identity) for identity in owned.values()
                )
                if not process_running and not descendants_running:
                    break
                time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
            if root_identity is None:
                timed_out = proc.poll() is None
            else:
                owned.update(_snapshot_tree(root_identity))
                timed_out = time.monotonic() >= deadline and (
                    proc.poll() is None
                    or any(identity != root_identity and _alive(identity) for identity in owned.values())
                )
            if timed_out:
                # Descendants first; every signal rechecks process creation time to avoid PID reuse.
                for identity in reversed(list(owned.values())):
                    if not _alive(identity):
                        continue
                    result = signal_if_same_process(identity)
                    signal_results.append({"pid": identity.pid, "result": result})
                while time.monotonic() < cleanup_deadline:
                    if proc.poll() is not None and not any(_alive(item) for item in owned.values()):
                        break
                    time.sleep(min(poll_interval, max(0.0, cleanup_deadline - time.monotonic())))
                for identity in owned.values():
                    if _alive(identity):
                        result = signal_if_same_process(identity, force=True)
                        signal_results.append({"pid": identity.pid, "result": result})
                remaining = max(0.0, cleanup_deadline - time.monotonic())
                try:
                    returncode = proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    returncode = None
            else:
                returncode = proc.wait(timeout=max(0.0, cleanup_deadline - time.monotonic()))
        except (OSError, subprocess.SubprocessError) as exc:
            error_type = type(exc).__name__
            elapsed = time.monotonic() - started
            result = {
                "status": "LAUNCH_FAILED", "returncode": None, "timed_out": False,
                "duration_seconds": elapsed, "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path), "leftover_processes": [],
                "launch_error_type": error_type,
            }
            summary_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            return result

    leftovers = [asdict(identity) for identity in owned.values() if _alive(identity)]
    if timed_out:
        status = "LEAKED" if leftovers else "TIMEOUT"
    elif leftovers:
        status = "LEAKED"
    else:
        status = "PASS" if returncode == 0 else "FAIL"
    result = {
        "status": status,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_seconds": time.monotonic() - started,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "leftover_processes": leftovers,
        "signals": signal_results,
    }
    summary_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--cleanup-timeout", type=float, default=2.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    try:
        result = run_command(
            command, cwd=args.cwd, log_dir=args.log_dir, timeout_seconds=args.timeout,
            cleanup_seconds=args.cleanup_timeout,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "INVALID", "error_type": type(exc).__name__}, sort_keys=True))
        return 2
    print(json.dumps({
        "status": result["status"], "returncode": result["returncode"],
        "timed_out": result["timed_out"], "duration_seconds": result["duration_seconds"],
        "stdout_path": result["stdout_path"], "stderr_path": result["stderr_path"],
        "leftover_count": len(result["leftover_processes"]),
    }, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
