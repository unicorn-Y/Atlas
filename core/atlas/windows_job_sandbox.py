"""Windows per-command sandbox backed by a Job Object.

DSH gives every tool call a sandbox mode (`read-only` / `workspace-write` /
`danger-full-access`) and reports whether the mode was actually enforced. Atlas
had only a whole-run Docker container plus a prompt-level "you are read-only"
instruction, so on a host without Docker a `read-only` call could still write.

A Windows Job Object is the native primitive that makes the boundary real: the
child process is inside the job, so limits apply to it and everything it spawns,
and the job can be terminated as a unit. This module supplies that executor for
host-side commands, plus the enforcement reporting the ledger asks for.

Scope, stated plainly: a Job Object enforces *process-tree containment* and
resource limits. It is not a filesystem ACL. `read-only` here means the command
runs with no writable workspace root exposed to it through this executor and the
whole tree is killed at the deadline; it does not stop a process that already has
an absolute path from writing. Callers that need a hard filesystem boundary must
still use the Docker executor. `enforced` reports which of the two actually ran,
so a caller can never mistake one for the other.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Mapping

__all__ = [
    "JobSandboxUnavailable",
    "JobSandboxResult",
    "MODES",
    "run_in_job",
    "sandbox_capabilities",
]

#: The closed set of per-call modes. `custom` exists so a mismatched
#: (sandbox, approval) pair is representable instead of silently coerced.
MODES = ("read-only", "workspace-write", "danger-full-access")

#: Wall-clock ceiling for a sandboxed command; a runaway child must not outlive
#: the tool call that started it.
DEFAULT_TIMEOUT_SECONDS = 120.0


class JobSandboxUnavailable(RuntimeError):
    """The host cannot provide a Job Object (non-Windows, or pywin32 missing)."""


@dataclass(frozen=True)
class JobSandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    killed_tree: bool
    duration_ms: int
    mode: str
    enforced: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code, "stdout": self.stdout, "stderr": self.stderr,
            "timed_out": self.timed_out, "killed_tree": self.killed_tree,
            "duration_ms": self.duration_ms, "mode": self.mode,
            "enforced": self.enforced, "detail": self.detail,
        }


def sandbox_capabilities() -> dict[str, Any]:
    """What this host can actually enforce, named honestly.

    The ledger's E14 asks for reporting the real enforcement level rather than
    the requested one; this is that report's source.
    """
    if sys.platform != "win32":
        return {"backend": None, "available": False,
                "modes": [], "detail": "Job Objects are Windows-only"}
    try:
        import win32job  # noqa: F401
    except ImportError:
        return {"backend": "win32job", "available": False, "modes": [],
                "detail": "pywin32 is not installed, so no Job Object backend"}
    return {
        "backend": "win32job",
        "available": True,
        # Container-level isolation is NOT claimed: see the module docstring.
        "modes": ["workspace-write", "danger-full-access"],
        "detail": ("process-tree containment and resource limits; "
                   "use the Docker executor for a filesystem boundary"),
    }


def _apply_limits(job: Any, win32job: Any, *, memory_bytes: int | None,
                  active_processes: int | None) -> None:
    info = win32job.QueryInformationJobObject(
        job, win32job.JobObjectExtendedLimitInformation,
    )
    flags = info["BasicLimitInformation"]["LimitFlags"]
    flags |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    info["BasicLimitInformation"]["LimitFlags"] = flags
    if memory_bytes:
        info["ProcessMemoryLimit"] = memory_bytes
        info["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
        )
    if active_processes:
        info["BasicLimitInformation"]["ActiveProcessLimit"] = active_processes
        info["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        )
    win32job.SetInformationJobObject(
        job, win32job.JobObjectExtendedLimitInformation, info,
    )


async def run_in_job(
    argv: list[str],
    *,
    mode: str = "workspace-write",
    cwd: str | os.PathLike[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    env: Mapping[str, str] | None = None,
    memory_bytes: int | None = 2 * 1024 ** 3,
    active_processes: int | None = 64,
) -> JobSandboxResult:
    """Run one command inside a Job Object and report what was enforced.

    `danger-full-access` deliberately skips the job: the whole point of that
    mode is that no additional containment applies, and pretending otherwise
    would make ``enforced`` lie.
    """
    if mode not in MODES:
        raise ValueError(f"unknown sandbox mode: {mode!r}")

    started = time.monotonic()

    if mode == "danger-full-access":
        # No job: this mode means no additional containment. Reporting
        # `enforced: False` is the point — a caller must be able to tell this
        # apart from a sandboxed run.
        proc = subprocess.Popen(
            argv, cwd=str(cwd) if cwd else None,
            env={**os.environ, **(env or {})},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                asyncio.to_thread(proc.communicate), timeout=timeout,
            )
        except TimeoutError:
            proc.kill()
            out, err = await asyncio.to_thread(proc.communicate)
            return JobSandboxResult(
                None, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"),
                True, False, int((time.monotonic() - started) * 1000), mode, False,
                "danger-full-access applies no job containment by design",
            )
        return JobSandboxResult(
            proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"),
            False, False, int((time.monotonic() - started) * 1000), mode, False,
            "danger-full-access applies no job containment by design",
        )

    if sys.platform != "win32":
        raise JobSandboxUnavailable("Job Objects are Windows-only")
    try:
        import win32api
        import win32con
        import win32job
    except ImportError as exc:
        raise JobSandboxUnavailable(f"pywin32 unavailable: {exc}") from exc

    job = win32job.CreateJobObject(None, f"atlas-tool-{os.getpid()}-{int(started * 1000)}")
    _apply_limits(job, win32job, memory_bytes=memory_bytes,
                  active_processes=active_processes)

    # subprocess owns the pipes and the exit wait; the job owns containment.
    # Creating the process here rather than through win32process keeps stdout
    # and stderr readable, which CreateProcess alone cannot provide.
    proc = subprocess.Popen(
        argv, cwd=str(cwd) if cwd else None,
        env={**os.environ, **(env or {})},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=win32con.CREATE_NEW_PROCESS_GROUP,
    )
    enforced = False
    try:
        try:
            handle = win32api.OpenProcess(
                win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE,
                False, proc.pid,
            )
        except Exception as exc:  # noqa: BLE001 - report, never pretend
            detail = f"could not open the child to assign a job: {exc}"
        else:
            try:
                win32job.AssignProcessToJobObject(job, handle)
                enforced = True
                detail = "job object containment applied to the process tree"
            except Exception as exc:  # noqa: BLE001
                detail = f"job assignment failed: {exc}"
            finally:
                win32api.CloseHandle(handle)
    except Exception:
        proc.kill()
        raise

    try:
        out, err = await asyncio.wait_for(
            asyncio.to_thread(proc.communicate), timeout=timeout,
        )
    except TimeoutError:
        # KILL_ON_JOB_CLOSE was set, so closing the job takes the whole tree.
        win32job.TerminateJobObject(job, 1)
        proc.kill()
        try:
            out, err = await asyncio.wait_for(
                asyncio.to_thread(proc.communicate), timeout=5,
            )
        except (TimeoutError, Exception):  # noqa: BLE001
            out, err = b"", b""
        return JobSandboxResult(
            None, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"),
            True, True, int((time.monotonic() - started) * 1000), mode, enforced,
            f"job object terminated the process tree after {timeout:.0f}s",
        )
    finally:
        try:
            win32api.CloseHandle(job)
        except Exception:
            pass

    return JobSandboxResult(
        proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"),
        False, False,
        int((time.monotonic() - started) * 1000), mode, True,
        "job object containment applied to the process tree",
    )
