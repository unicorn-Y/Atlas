"""Paired benchmark: same tasks, same model, same gateway, both harnesses.

The gap ledger compares capabilities. This compares *behaviour*, which is the
only way "Atlas is better" becomes a claim with numbers behind it instead of a
feeling.

Both systems run against the identical OpenAI-compatible gateway
(``https://d1api.xin/v1``) with the identical model id, so a difference in the
numbers is a difference in the harness, not in the model.

Usage::

    python scripts/omni_bench.py --tasks 3
    python scripts/omni_bench.py --only atlas     # skip DSH

Every cell it cannot measure is reported as ``NOT-MEASURED`` with the reason.
It never fills a cell with a guess.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import tomllib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

ATLAS_ROOT = Path(__file__).resolve().parents[2]
DSH_ROOT = Path(os.environ.get("DSH_ROOT", r"D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness"))

#: Fixed task set. Deliberately small and deterministic — a benchmark that needs
#: a good answer to be useful cannot separate harness overhead from model luck.
#: The first five are single-turn chat; the last two force a tool round-trip so
#: the comparison also covers the loop, not just the preamble.
TASKS: tuple[str, ...] = (
    "Reply with exactly the word: OK",
    "Reply with exactly the number: 42",
    "Reply with exactly the word: ATLAS",
    "Write one short sentence describing what a file system is.",
    "Name the programming language Python in one word.",
    "Run `python -c \"import os; print(len(os.listdir('.')))\"` in the current working directory and reply with only the number it printed.",
    "Run `python -c \"print(6*7)\"` and reply with only the number it printed.",
)

PROXY = "http://127.0.0.1:7897"


@dataclass
class Sample:
    harness: str
    task: str
    ok: bool
    wall_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None
    tool_calls: int | None = None
    steps: int | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)
    final_text: str | None = None
    session_id: str | None = None
    usage_complete: bool = False

    @property
    def prompt_tokens(self) -> int | None:
        """Whole prompt the model saw: fresh input plus everything served from cache.

        The two harnesses bucket these differently, and both buckets are real:

        * Atlas reports ``input_tokens`` as the *whole* prompt and records the
          cached subset separately (``cache_hit_rate = cached / input``), so
          adding the cache field would double-count.
        * DSH's pi-ai layer reports ``inputTokens`` as the *uncached remainder*
          and puts the rest in ``cacheReadTokens`` (its own ``totalTokens`` is
          the sum of all four buckets).

        So the sum is applied only for DSH. Comparing the raw ``input`` field
        would put a cached turn's incremental tokens against an uncached turn's
        full prompt — which is exactly the mistake that made an earlier run of
        this benchmark report 225 vs 9949.
        """
        if not self.usage_complete or self.input_tokens is None:
            return None
        if self.harness == "atlas":
            return self.input_tokens
        if self.cached_input_tokens is None or self.cache_write_tokens is None:
            return None
        return self.input_tokens + self.cached_input_tokens + self.cache_write_tokens


_DSH_USAGE_FIELDS = (
    "inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens",
)


def _aggregate_dsh_step_usage(step_usage: list[dict[str, Any] | None]) -> tuple[dict[str, int | None], bool]:
    """Sum each step once; any omitted field makes that aggregate incomplete."""
    totals: dict[str, int | None] = {field: None for field in _DSH_USAGE_FIELDS}
    sums = {field: 0 for field in _DSH_USAGE_FIELDS}
    seen = {field: False for field in _DSH_USAGE_FIELDS}
    complete = bool(step_usage)
    for usage in step_usage:
        if not isinstance(usage, dict):
            complete = False
            continue
        for field in _DSH_USAGE_FIELDS:
            value = usage.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                sums[field] += value
                seen[field] = True
            else:
                complete = False
    for field in _DSH_USAGE_FIELDS:
        if seen[field]:
            totals[field] = sums[field]
        if not seen[field]:
            complete = False
    return totals, complete


def _parse_dsh_stream(stdout: str) -> dict[str, Any]:
    """Parse committed JSON events from one headless process invocation."""
    step_usage: list[dict[str, Any] | None] = []
    calls: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    session_ids: list[str] = []
    final_text: str | None = None
    terminal: str | None = None
    terminal_error: str | None = None
    steps = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "session" and event.get("sessionId"):
            session_ids.append(str(event["sessionId"]))
        elif kind == "final":
            if isinstance(event.get("text"), str):
                final_text = event["text"]
        elif kind == "status":
            phase = event.get("phase")
            if phase == "step_start":
                steps += 1
            elif phase == "step_end":
                usage = event.get("usage")
                step_usage.append(usage if isinstance(usage, dict) else None)
            elif phase == "turn_end":
                terminal = (event.get("reason") or {}).get("kind")
                if terminal == "error":
                    terminal_error = str(
                        ((event.get("reason") or {}).get("error") or {}).get("message") or "error",
                    )[:300]
        elif kind == "tool_call":
            calls.append({
                "id": event.get("callId"), "name": event.get("tool"),
                "arguments": event.get("input"),
            })
        elif kind == "tool_result":
            results.append({
                "id": event.get("callId"), "status": event.get("status"),
                "result": event.get("result"),
            })
    usage, usage_complete = _aggregate_dsh_step_usage(step_usage)
    return {
        "terminal": terminal, "terminal_error": terminal_error,
        "final_text": final_text, "session_ids": session_ids,
        "steps": steps, "tool_calls": calls, "tool_results": results,
        "usage": usage, "usage_complete": usage_complete,
    }


def _tool_result_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_tool_result_text(part) for part in value)
    if isinstance(value, dict):
        parts = [
            _tool_result_text(value[key]) for key in
            ("stdout", "output", "text", "content", "result") if key in value
        ]
        return "\n".join(part for part in parts if part)
    return ""


def _validate_task_result(
    task: str, final_text: str | None, calls: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> tuple[bool, str | None, list[str]]:
    """Check the answer and, on tool tasks, the matching successful execution."""
    final = (final_text or "").strip()
    if not final:
        return False, "no final answer event", []
    normalized = " ".join(final.split())
    if task == TASKS[0]:
        return normalized == "OK", None if normalized == "OK" else "expected exact answer OK", []
    if task == TASKS[1]:
        return normalized == "42", None if normalized == "42" else "expected exact answer 42", []
    if task == TASKS[2]:
        return normalized == "ATLAS", None if normalized == "ATLAS" else "expected exact answer ATLAS", []
    if task == TASKS[3]:
        valid = bool(re.search(r"\b(file system|filesystem)\b", normalized, re.I))
        valid = valid and bool(re.search(r"\b(store|organize|organise|manage)\b", normalized, re.I))
        return valid, None if valid else "description missed file-system purpose", []
    if task == TASKS[4]:
        return normalized.casefold() == "python", None if normalized.casefold() == "python" else "expected exact answer Python", []

    command_hint = "os.listdir" if task == TASKS[5] else "6*7"
    final_number = re.fullmatch(r"\s*(\d+)\s*", final)
    evidence_names: list[str] = []
    for call in calls:
        serialized = json.dumps(call.get("arguments"), ensure_ascii=False, sort_keys=True)
        if "python" not in serialized.casefold() or command_hint not in serialized.replace(" ", ""):
            continue
        call_id = call.get("id")
        matched = [row for row in results if row.get("id") == call_id]
        for row in matched:
            if row.get("status") != "completed":
                continue
            output = _tool_result_text(row.get("result"))
            output_lines = [line.strip() for line in output.splitlines() if line.strip()]
            if final_number and final_number.group(1) in output_lines:
                evidence_names.append(str(call.get("name") or "unnamed-tool"))
    valid = bool(final_number and evidence_names)
    reason = None if valid else "required Python tool result did not match the final number"
    return valid, reason, evidence_names


def _d1_key() -> str | None:
    """Read the gateway key from DSH's credential store, or the environment."""
    env = os.environ.get("D1API_API_KEY")
    if env:
        return env
    cred = Path.home() / ".dsh" / ".credentials.yaml"
    try:
        text = cred.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"D1API_API_KEY:\s*(\S+)", text)
    return match.group(1) if match else None


def _dsh_env() -> dict[str, str]:
    env = dict(os.environ)
    env["http_proxy"] = env["https_proxy"] = PROXY
    key = _d1_key()
    if key:
        env["D1API_API_KEY"] = key
    return env


def run_dsh(task: str, timeout: int = 180) -> Sample:
    """One DSH headless turn, parsed from its --json event stream."""
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["pnpm", "dsh", "headless", "--json", task],
            cwd=str(DSH_ROOT), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, env=_dsh_env(), shell=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Sample("dsh", task, False, int((time.monotonic() - started) * 1000),
                      error=f"{type(exc).__name__}: {exc}")
    wall = int((time.monotonic() - started) * 1000)
    parsed = _parse_dsh_stream(proc.stdout or "")
    usage = parsed["usage"]
    valid, validation_error, evidence_names = _validate_task_result(
        task, parsed["final_text"], parsed["tool_calls"], parsed["tool_results"],
    )
    terminal = parsed["terminal"]
    error = parsed["terminal_error"] or validation_error
    if proc.returncode != 0 and error is None:
        error = f"DSH exited with code {proc.returncode}"
    session_ids = parsed["session_ids"]
    session_id = session_ids[0] if len(set(session_ids)) == 1 and session_ids else None
    return Sample(
        "dsh", task, proc.returncode == 0 and terminal == "completed" and valid, wall,
        input_tokens=usage.get("inputTokens"), output_tokens=usage.get("outputTokens"),
        cached_input_tokens=usage.get("cacheReadTokens"),
        cache_write_tokens=usage.get("cacheWriteTokens"),
        tool_calls=len(parsed["tool_calls"]), steps=parsed["steps"], error=error,
        final_text=parsed["final_text"], session_id=session_id,
        usage_complete=parsed["usage_complete"],
        notes=[f"verified_tool={name}" for name in evidence_names],
    )


def _third_party_hook_overrides() -> dict[str, bool]:
    """Ids of Codex-declared lifecycle hooks that are not Atlas.

    On a machine that also runs Codex, ``~/.codex/hooks.json`` declares hooks
    Atlas faithfully mirrors. Their cost is real but it belongs to the other
    tool, so a pure architecture comparison has to run without them.

    Returns the ids to disable; empty when there is nothing to isolate.
    """
    try:
        from atlas.runtime.hooks import codex_hook_settings
    except Exception:  # noqa: BLE001 - benchmark must work without atlas importable
        return {}
    try:
        hooks = codex_hook_settings(str(ATLAS_ROOT))
    except Exception:  # noqa: BLE001
        return {}
    wanted = {"SessionStart", "UserPromptSubmit", "Stop", "PreCompact",
              "PreToolUse", "PostToolUse"}
    return {h["id"]: False for h in hooks if h.get("event") in wanted}


def _apply_hook_isolation(
    enabled: bool, data_root: Path | None = None,
    overrides: dict[str, bool] | None = None,
) -> Path | None:
    """Write hook overrides only below the benchmark's private data root."""
    if not enabled:
        return None
    if data_root is None:
        raise ValueError("hook isolation requires a dedicated ATLAS_DATA_DIR")
    overrides = overrides if overrides is not None else _third_party_hook_overrides()
    if not overrides:
        return None
    root = data_root.resolve()
    target = root / "data" / "hooks.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Written by core/scripts/omni_bench.py for one benchmark run.",
        "# This file is inside the benchmark's private ATLAS_DATA_DIR.",
        "",
    ]
    for hook_id in sorted(overrides):
        lines += ["[[hook_overrides]]", f'id = "{hook_id}"', "enabled = false", ""]
    # Exclusive creation prevents overwriting a pre-existing file even if a
    # caller accidentally reuses a data directory.
    with target.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    return target


def _atlas_usage(run_id: str, db_path: Path | None) -> dict[str, int] | None:
    """Sum the usage rows Atlas wrote for one run.

    Read from the ledger rather than scraped from the socket: ``run.completed``
    carries no token counts, so the WS stream cannot answer this. The ledger is
    the same numbers the desktop app bills from.
    """
    import sqlite3

    # Read the ledger selected by this isolated process configuration, never
    # the repository's default data/atlas.db.
    data_dir = os.environ.get("ATLAS_DATA_DIR")
    if not data_dir or db_path is None:
        return None
    try:
        root = Path(data_dir).resolve()
        db = Path(db_path).resolve()
        if not db.is_relative_to(root):
            return None
    except Exception:  # noqa: BLE001 - absence is reported as unmeasured usage
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT SUM(input_tokens), SUM(output_tokens), SUM(cached_input_tokens) "
            "FROM usage_records WHERE run_id = ?", (run_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row or row[0] is None:
        return None
    return {"input_tokens": int(row[0]), "output_tokens": int(row[1] or 0),
            "cached_input_tokens": int(row[2] or 0)}


def _atlas_base(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _atlas_ready(port: int, timeout: float = 90.0) -> bool:
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{_atlas_base(port)}/api/health", timeout=3) as resp:
                if resp.status == 200:
                    return True
        except Exception:  # noqa: BLE001 - still starting
            time.sleep(2)
    return False


class IsolatedAtlasBackend:
    """Run Atlas against a private data root and a port owned by this process."""

    def __init__(
        self, port: int, *, isolate_hooks: bool = False,
        allowed_origins: Sequence[str] = (),
    ) -> None:
        self.port = int(port)
        self._temporary = tempfile.TemporaryDirectory(prefix="atlas-dsh-bench-")
        self.data_dir = Path(self._temporary.name).resolve()
        self.process: subprocess.Popen[Any] | None = None
        self.shutdown_file = self.data_dir / "shutdown.request"
        self.hook_override: Path | None = None
        self.hook_overrides: dict[str, bool] = {}
        self.db_path = self.data_dir / "data" / "atlas.db"
        self.log_path = self.data_dir / "atlas-server.log"
        self._log_stream: Any = None
        self.graceful_exit = False
        self.forced_termination = False
        self.exit_code: int | None = None
        self.log_summary: str = ""
        self.hooks_effective = False
        self.closed = False
        self._previous_env = {
            key: os.environ.get(key)
            for key in ("ATLAS_ROOT", "ATLAS_DATA_DIR", "ATLAS_HOME")
        }
        try:
            source_config = ATLAS_ROOT / "config" / "atlas.toml"
            if source_config.is_file():
                target_config = self.data_dir / "config" / "atlas.toml"
                target_config.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_config, target_config)
                with target_config.open("rb") as stream:
                    config_data = tomllib.load(stream)
            else:
                config_data = {}
                target_config = self.data_dir / "config" / "atlas.toml"
            if allowed_origins:
                server_config = config_data.setdefault("server", {})
                current_origins = server_config.get("allowed_origins", [])
                configured = set(current_origins if isinstance(current_origins, list) else [])
                configured.update(str(origin) for origin in allowed_origins)
                server_config["allowed_origins"] = sorted(configured)
                import tomli_w

                target_config.parent.mkdir(parents=True, exist_ok=True)
                target_config.write_text(tomli_w.dumps(config_data), encoding="utf-8")
            raw_db_path = str(
                (config_data.get("memory") or {}).get("db_path") or "./data/atlas.db"
            )
            configured_db_path = Path(raw_db_path)
            self.db_path = (
                configured_db_path if configured_db_path.is_absolute()
                else self.data_dir / configured_db_path
            ).resolve()
            if not self.db_path.is_relative_to(self.data_dir):
                raise RuntimeError("Atlas benchmark database escaped its private data root")
            os.environ["ATLAS_ROOT"] = str(ATLAS_ROOT)
            os.environ["ATLAS_DATA_DIR"] = str(self.data_dir)
            os.environ["ATLAS_HOME"] = str(self.data_dir / "engine")
            self.hook_overrides = _third_party_hook_overrides() if isolate_hooks else {}
            self.hook_override = _apply_hook_isolation(
                isolate_hooks, self.data_dir, self.hook_overrides,
            )

            with socket.socket() as probe:
                probe.settimeout(0.25)
                if probe.connect_ex(("127.0.0.1", self.port)) == 0:
                    raise RuntimeError(f"Atlas benchmark port {self.port} is already occupied")

            child_env = os.environ.copy()
            child_env.update({
                "ATLAS_ROOT": str(ATLAS_ROOT),
                "ATLAS_DATA_DIR": str(self.data_dir),
                "ATLAS_HOME": str(self.data_dir / "engine"),
                "HTTP_PROXY": PROXY,
                "HTTPS_PROXY": PROXY,
                "http_proxy": PROXY,
                "https_proxy": PROXY,
                "ATLAS_SAFE_MODE": "1",
                "PYTHONPATH": os.pathsep.join(filter(None, (
                    str(ATLAS_ROOT / "core"), child_env.get("PYTHONPATH", ""),
                ))),
            })
            self._log_stream = self.log_path.open("xb")
            self.process = subprocess.Popen(
                [sys.executable, str(ATLAS_ROOT / "core" / "scripts" / "atlas_bench_server.py"),
                 "--port", str(self.port), "--shutdown-file", str(self.shutdown_file)],
                cwd=str(ATLAS_ROOT / "core"), env=child_env,
                stdin=subprocess.DEVNULL, stdout=self._log_stream,
                stderr=subprocess.STDOUT,
            )
            if not _atlas_ready(self.port):
                raise RuntimeError(
                    "isolated Atlas backend did not become ready: " + self._safe_log_tail()
                )
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"isolated Atlas child exited with code {self.process.returncode}: "
                    + self._safe_log_tail()
                )
            self._verify_hook_overrides()
        except BaseException:
            self.close()
            raise

    def _safe_log_tail(self) -> str:
        try:
            if self._log_stream is not None:
                self._log_stream.flush()
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return "private startup log unavailable"
        if not lines:
            return "private startup log was empty"
        tail = lines[-200:]
        folded = "\n".join(tail).casefold()
        startup = "complete" if "application startup complete" in folded else "not-observed"
        shutdown = "complete" if "application shutdown complete" in folded else "not-observed"
        errors = [line for line in tail if re.search(r"\b(error|critical)\b", line, re.I)]
        last_error_type = "unknown"
        for line in reversed(errors):
            match = re.search(r"\b([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))\b", line)
            if match:
                last_error_type = match.group(1).split(".")[-1]
                break
        # Never copy raw log messages into a benchmark artifact: startup logs
        # can contain request/config fragments. Keep only bounded diagnostics.
        return (f"startup={startup}; shutdown={shutdown}; errors={len(errors)}; "
                f"last_error_type={last_error_type}")

    def _verify_hook_overrides(self) -> None:
        if not self.hook_overrides:
            self.hooks_effective = True
            return
        import urllib.parse
        import urllib.request

        query = urllib.parse.urlencode({"workspace": str(ATLAS_ROOT)})
        with urllib.request.urlopen(
            f"{_atlas_base(self.port)}/api/hooks/trust?{query}", timeout=5,
        ) as response:
            rows = json.load(response).get("hooks", [])
        enabled = {str(row.get("id")): bool(row.get("enabled", True)) for row in rows}
        missing_or_enabled = [
            hook_id for hook_id in self.hook_overrides
            if hook_id not in enabled or enabled[hook_id]
        ]
        if missing_or_enabled:
            raise RuntimeError(
                "private hook overrides were not active in the running Atlas process: "
                + ", ".join(sorted(missing_or_enabled))
            )
        self.hooks_effective = True

    def close(self) -> None:
        """Request normal lifespan shutdown, then use process fallback if needed."""
        if self.closed:
            return
        graceful_request_sent = False
        try:
            if self.process is not None and self.process.poll() is None:
                try:
                    self.shutdown_file.write_text("shutdown\n", encoding="utf-8")
                    graceful_request_sent = True
                    self.process.wait(timeout=30)
                except (OSError, subprocess.TimeoutExpired):
                    self.forced_termination = True
                    try:
                        self.process.terminate()
                        self.process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=10)
        finally:
            if self.process is not None:
                self.exit_code = self.process.poll()
            self.log_summary = self._safe_log_tail()
            self.graceful_exit = bool(
                graceful_request_sent and self.exit_code == 0
                and "shutdown=complete" in self.log_summary.casefold()
            )
            if self._log_stream is not None:
                self._log_stream.close()
                self._log_stream = None
            for key, value in self._previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            self._temporary.cleanup()
            self.closed = True


class IsolatedDSHHome:
    """Keep headless sessions/profile writes under a fresh DSH_HOME."""

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="dsh-parity-home-")
        self.path = Path(self._temporary.name).resolve()
        self._previous = os.environ.get("DSH_HOME")
        os.environ["DSH_HOME"] = str(self.path)

    def close(self) -> None:
        if self._previous is None:
            os.environ.pop("DSH_HOME", None)
        else:
            os.environ["DSH_HOME"] = self._previous
        self._temporary.cleanup()


def run_atlas(task: str, port: int, db_path: Path, timeout: int = 180) -> Sample:
    """One Atlas turn over its WebSocket, measuring the same things."""
    # Imported lazily so --only dsh works without the Atlas deps installed.
    import asyncio

    import websockets

    started = time.monotonic()
    run_id = f"bench-{int(started * 1000)}"
    conv = f"bench-{int(started * 1000)}"
    usage: dict[str, Any] = {}
    tools = 0
    terminal = None
    error = None
    reply: list[str] = []
    tool_events: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []

    async def _turn() -> None:
        nonlocal usage, tools, terminal, error
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws/chat",
                                      max_size=8 * 1024 * 1024) as ws:
            await ws.send(json.dumps({
                "type": "run.start", "run_id": run_id, "conversation_id": conv,
                "content": task, "workspace": str(ATLAS_ROOT),
            }))
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    error = "timeout waiting for a terminal event"
                    return
                frame = json.loads(raw)
                event = frame.get("event") or frame.get("type")
                data = frame.get("data") or {}
                if event == "message.delta":
                    reply.append(str(data.get("content") or ""))
                elif event == "tool.started":
                    tools += 1
                    tool_events.append({
                        "id": data.get("tool_call_id"), "name": data.get("name"),
                        "arguments": data.get("arguments"),
                    })
                elif event == "tool.completed":
                    tool_results.append({
                        "id": data.get("tool_call_id"),
                        "status": "error" if data.get("is_error") else "completed",
                        "result": data.get("execution", data.get("result")),
                    })
                elif event == "run.usage" and isinstance(data.get("usage"), dict):
                    usage = data["usage"]
                elif event in {"run.completed", "run.failed", "run.cancelled"}:
                    terminal = event
                    if event == "run.failed":
                        error = str(data.get("detail") or "")[:300]
                    return

    try:
        asyncio.run(_turn())
    except Exception as exc:  # noqa: BLE001 - a broken run is a data point
        error = f"{type(exc).__name__}: {exc}"
    wall = int((time.monotonic() - started) * 1000)
    ledger = _atlas_usage(run_id, db_path)
    usage_complete = ledger is not None
    if ledger:
        usage = {"input_tokens": ledger["input_tokens"],
                 "output_tokens": ledger["output_tokens"],
                 "cached_input_tokens": ledger["cached_input_tokens"]}
    valid, validation_error, evidence_names = _validate_task_result(
        task, "".join(reply), tool_events, tool_results,
    )
    if error is None:
        error = validation_error
    return Sample(
        "atlas", task, terminal == "run.completed" and valid, wall,
        input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
        cached_input_tokens=usage.get("cached_input_tokens"),
        tool_calls=tools, steps=None, error=error,
        final_text="".join(reply), usage_complete=usage_complete,
        notes=[f"verified_tool={name}" for name in evidence_names],
    )


def dsh_boot_ms(samples: int = 3) -> int | None:
    """How long DSH takes before it can answer anything at all.

    ``pnpm dsh --help`` parses no task and calls no model, so its duration is
    pure process + profile composition cost. Subtracting it is the only way to
    compare per-turn latency: DSH pays that cost on every turn, Atlas pays it
    once at backend start.
    """
    times: list[int] = []
    for _ in range(samples):
        started = time.monotonic()
        try:
            subprocess.run(["pnpm", "dsh", "--profile", "headless", "--help"],
                           cwd=str(DSH_ROOT), capture_output=True, text=True,
                           timeout=180, env=_dsh_env(), shell=True)
        except (OSError, subprocess.TimeoutExpired):
            return None
        times.append(int((time.monotonic() - started) * 1000))
    return _median(times)


def _fmt(value: Any) -> str:
    return "NOT-MEASURED" if value is None else str(value)


def _median(values: list[int]) -> int | None:
    return int(statistics.median(values)) if values else None


def report(samples: list[Sample], out_path: Path, dsh_version: str,
           boot_ms: int | None = None) -> None:
    by_harness: dict[str, list[Sample]] = {}
    for sample in samples:
        by_harness.setdefault(sample.harness, []).append(sample)

    lines = [
        "# Atlas vs DeepSeek-Harness — paired benchmark",
        "",
        "<!-- Generated by core/scripts/omni_bench.py. Re-running replaces this file.",
        "     The reading of these numbers lives in BENCH-ANALYSIS.md, which is",
        "     written by hand and does not move when the benchmark is re-run. -->",
        "",
        f"DSH checkout: `{DSH_ROOT}`",
        f"DSH build: `{dsh_version}`",
        f"Tasks: {len(TASKS)} fixed prompts, identical model and gateway for both.",
        "Gateway: `https://d1api.xin/v1`, model `deepseek-v4.1-flash`.",
        "",
        "| Metric | Atlas | DSH | Winner |",
        "|---|---:|---:|---|",
    ]

    def values_for(attr: str) -> dict[str, int | None]:
        cells: dict[str, int | None] = {}
        for name, items in by_harness.items():
            values = [getattr(i, attr) for i in items
                      if getattr(i, attr) is not None and i.ok]
            cells[name] = _median(values)
        return cells

    def decide(a: int | None, d: int | None, lower_is_better: bool = True) -> str:
        if a is None or d is None:
            return "—"
        if a == d:
            return "tie"
        return "Atlas" if (a < d) == lower_is_better else "DSH"

    def row(label: str, attr: str, lower_is_better: bool = True) -> None:
        cells = values_for(attr)
        a, d = cells.get("atlas"), cells.get("dsh")
        lines.append(f"| {label} | {_fmt(a)} | {_fmt(d)} | "
                     f"{decide(a, d, lower_is_better)} |")

    row("Median prompt tokens / turn (cache included)", "prompt_tokens")
    row("Median output tokens / turn", "output_tokens")
    row("Median wall-clock ms / turn (as measured)", "wall_ms")
    row("Median tool calls / turn", "tool_calls")

    # Subtracting DSH's boot cost is the only like-for-like latency comparison.
    wall = values_for("wall_ms")
    if boot_ms is not None and wall.get("dsh") is not None:
        dsh_turn = max(0, int(wall["dsh"]) - boot_ms)
        atlas_turn = wall.get("atlas")
        lines.append(f"| Median wall-clock ms / turn (DSH boot excluded, "
                     f"{boot_ms} ms) | {_fmt(atlas_turn)} | {dsh_turn} | "
                     f"{decide(atlas_turn, dsh_turn)} |")
    else:
        lines.append("| Median wall-clock ms / turn (DSH boot excluded) | "
                     f"{_fmt(wall.get('atlas'))} | NOT-MEASURED | — |")

    succeeded = {name: sum(1 for i in items if i.ok) for name, items in by_harness.items()}
    lines += ["", "## Runs that completed", ""]
    for name in ("atlas", "dsh"):
        if name in by_harness:
            lines.append(f"- **{name}**: {succeeded[name]}/{len(by_harness[name])}")

    failures = [i for i in samples if not i.ok]
    if failures:
        lines += ["", "## Failures (reported, not hidden)", ""]
        for item in failures:
            lines.append(f"- `{item.harness}` · {item.task[:40]!r} — {item.error or 'not completed'}")

    lines += ["", "## Behavioral validation evidence", ""]
    for item in samples:
        lines.append(
            f"- `{item.harness}` task={item.task!r}; validated={item.ok}; "
            f"final={item.final_text!r}; tools={item.tool_calls}; "
            f"verified={','.join(item.notes) or 'none'}; "
            f"session={item.session_id or 'UNKNOWN'}; "
            f"usage={'complete' if item.usage_complete else 'partial/unknown'}; "
            f"prompt_tokens={item.prompt_tokens if item.prompt_tokens is not None else 'NOT-MEASURED'}"
        )

    lines += [
        "",
        "## How to read this",
        "",
        "- A cell is `NOT-MEASURED` when that harness reported no usage record for",
        "  the runs that completed. It is never filled with an estimate.",
        "- Token counts come from each harness's own usage record for the same",
        "  prompt and the same upstream model, so a difference is harness overhead",
        "  (system prompt, tool schemas, history assembly), not model variance.",
        "- **Output tokens are not comparable between the two.** Atlas counts the",
        "  model's reasoning tokens in `output_tokens`; DSH's `outputTokens` counts",
        "  only what was emitted as text. The row is published because dropping it",
        "  would be worse, but it must not be read as a win.",
        "- Atlas is a dedicated child process on an unused loopback port, with",
        "  a temporary data root; its whole-run boot cost is not part of each",
        "  turn. DSH starts a fresh Node process per turn. The boot-excluded row",
        "  removes DSH's measured cold-start cost; that is the per-turn latency row.",
        "- Runs completed means both terminal completion and task-specific final",
        "  answer validation; tool tasks also require a matching successful result.",
        "- DSH prompt usage sums every step_end and requires input, cache-read, and",
        "  cache-write counts. Missing usage is partial/unknown, never zero.",
        "- Atlas runs use ATLAS_SAFE_MODE=1 in a private data directory; optional",
        "  plugins/MCP integrations are outside this core-engine task sample.",
    ]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=int, default=len(TASKS))
    parser.add_argument("--only", choices=("atlas", "dsh"), default=None)
    parser.add_argument("--port", type=int, default=8910)
    parser.add_argument(
        "--isolate-hooks", action="store_true",
        help="disable third-party ~/.codex/hooks.json hooks for this run, so the "
             "latency number reflects Atlas and not whatever else is installed",
    )
    parser.add_argument("--out", default=str(ATLAS_ROOT / "tasks" / "dsh-parity" / "BENCH.md"))
    args = parser.parse_args()

    tasks = TASKS[: args.tasks]
    samples: list[Sample] = []

    backend: IsolatedAtlasBackend | None = None

    try:
        if args.only in (None, "atlas"):
            backend = IsolatedAtlasBackend(args.port, isolate_hooks=args.isolate_hooks)
            print(f"[atlas] isolated data root ready on 127.0.0.1:{args.port}")
            if not _atlas_ready(args.port):
                raise RuntimeError("the isolated Atlas backend stopped before the run")
            for task in tasks:
                sample = run_atlas(task, args.port, backend.db_path)
                samples.append(sample)
                print(f"[atlas] {sample.ok} {sample.wall_ms}ms in={sample.input_tokens} "
                      f"out={sample.output_tokens} tools={sample.tool_calls} {sample.error or ''}")

        if args.only in (None, "dsh"):
            dsh_home = IsolatedDSHHome()
            try:
                for task in tasks:
                    sample = run_dsh(task)
                    samples.append(sample)
                    print(f"[dsh]   {sample.ok} {sample.wall_ms}ms in={sample.input_tokens} "
                          f"out={sample.output_tokens} tools={sample.tool_calls} {sample.error or ''}")
            finally:
                dsh_home.close()

        try:
            version = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], cwd=str(DSH_ROOT),
                capture_output=True, text=True, timeout=15,
            ).stdout.strip() or "unknown"
        except Exception:  # noqa: BLE001
            version = "unknown"

        boot_ms = None
        if args.only in (None, "dsh"):
            dsh_home = IsolatedDSHHome()
            try:
                boot_ms = dsh_boot_ms()
            finally:
                dsh_home.close()
            print(f"[dsh]   boot baseline {boot_ms} ms (no model call)")

        report(samples, Path(args.out), version, boot_ms)
    finally:
        # Hook overrides and the usage ledger live below this instance's private
        # root. Stop its child before the root is removed.
        if backend is not None:
            backend.close()
            print(
                f"[atlas] child exit={backend.exit_code}; "
                f"forced_termination={backend.forced_termination}; "
                f"graceful_lifespan={backend.graceful_exit}; "
                f"private_log_summary={backend.log_summary!r}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
