"""H10.2 real-model smoke of Atlas itself (taskbook §12.2, Atlas 自己，不比别家).

Three deterministic scenarios driven through the H9 headless CLI, exactly like
a user would run it (``python -m atlas.cli run -p ...``):

01  write a file with exact content            -> exit 0, file bytes correct
02  read a file and answer a question about it -> exit 0, non-empty real answer
03  write under ``ask_writes``, nobody to approve -> exit 3, auto-deny, no file

Lane policy: marked ``live`` (excluded by default; ``ATLAS_LIVE=1`` + ``-m live``
required — see core/tests/conftest.py). The run deliberately uses the
configured model and its own data root: point ``ATLAS_LIVE_SMOKE_ROOT`` at a
prepared live data root (config/atlas.toml with the real gateway + engine
home; build one with artifacts/h10-live-smoke/build_live_root.py). If no
working credential is configured the suite FAILS with the exact missing piece —
it never fakes a pass.

Every CLI subprocess launches with ``cwd=<live root>`` — deliberately NOT the
workspace — and scenario 01 names no absolute path at all: the model must
discover the workspace from the engine's anchored working directory (the
``Current working directory`` block of the system prompt) and the relative
write must land inside ``--workspace``. That is the regression proof for
H10.2-DEFECT-3 (the pre-fix engine leaked the process launch dir into the
prompt and relative writes — see
artifacts/h10-live-smoke/runs/01-probe-defect3-record.json; the pre-fix suite
had to launch inside the workspace and name it absolute as a harness
accommodation). The scratch config keeps the host-shaped prefixed
``litellm_model`` (``openai/...``) verbatim: since the H10.2-DEFECT-1 router
fix, the engine derives the bare wire id itself.
Evidence written next to the run is redacted (gateway key and any ``sk-*``
token shape) before it touches disk.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

CORE_ROOT = Path(__file__).resolve().parents[1]
CLI_TIMEOUT = 600.0
MAGIC_NUMBER = "4711"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _redact(text: str) -> str:
    """Redact the configured gateway key and generic key shapes from evidence."""
    key = ""
    data_root = os.environ.get("ATLAS_DATA_DIR", "")
    if data_root:
        try:
            import tomllib

            raw = tomllib.loads(
                (Path(data_root) / "config" / "atlas.toml").read_text(encoding="utf-8")
            )
            key = str(raw.get("models", {}).get("gateway", {}).get("api_key", "")).strip()
        except (OSError, tomllib.TOMLDecodeError):
            key = ""
    if key:
        text = text.replace(key, "<REDACTED-KEY>")
    text = re.sub(r"sk-\S{4,}", "<REDACTED-KEY>", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1<REDACTED-KEY>", text)
    return text


class LiveSession:
    """Prepared live data root + child-process env + evidence sink."""

    def __init__(self) -> None:
        self.root = Path(os.environ.get("ATLAS_LIVE_SMOKE_ROOT", "")).expanduser()
        if not self.root.is_dir():
            pytest.fail(
                "live smoke needs ATLAS_LIVE_SMOKE_ROOT pointing at a prepared live "
                "data root (config/atlas.toml with the real gateway and an engine/ "
                "home). Build one with: python artifacts/h10-live-smoke/"
                "build_live_root.py  (missing piece: ATLAS_LIVE_SMOKE_ROOT)"
            )
        os.environ["ATLAS_DATA_DIR"] = str(self.root)

        from atlas.config import get_config

        cfg = get_config()
        self.model = cfg.default_model
        self.gateway_base_url = cfg.gateway_base_url
        if not cfg.gateway_api_key:
            pytest.fail(
                f"no gateway credential configured for the live smoke (missing piece: "
                f"models.gateway.api_key in {self.root / 'config' / 'atlas.toml'} "
                f"— copy it from the host install; never commit it)"
            )
        self.evidence = Path(
            os.environ.get("ATLAS_LIVE_EVIDENCE_DIR", str(self.root / "evidence"))
        )
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.doctor: dict[str, Any] = {}
        self._workspace_root = self.root / "workspaces"
        self._workspace_root.mkdir(exist_ok=True)

    # -- child env (mirrors core/tests/test_cli_headless.py isolation) --------

    def child_env(self) -> dict[str, str]:
        engine_home = self.root / "engine"
        home = self.root / "home"
        env = dict(os.environ)
        env.update(
            HERMES_HOME=str(engine_home),
            ATLAS_SKILLS_HOME=str(self.root / "skills-home"),
            ATLAS_SCHEDULER_ENABLED="false",
            ATLAS_API_TOKEN="h10-live-smoke",
            PYTHONIOENCODING="utf-8",
        )
        for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
            env[key] = str(home)
        paths = [str(CORE_ROOT)]
        try:
            import hermes_state

            paths.append(str(Path(hermes_state.__file__).resolve().parent))
        except ImportError:
            pass
        if env.get("PYTHONPATH"):
            paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(paths)
        return env

    # -- execution + evidence --------------------------------------------------

    def run_cli(
        self, name: str, *args: str, cwd: Path, timeout: float = CLI_TIMEOUT,
    ) -> tuple[int, list[dict[str, Any]], str]:
        run_dir = self.evidence / name
        run_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        proc = subprocess.run(
            [sys.executable, "-m", "atlas.cli", *args],
            cwd=str(cwd), env=self.child_env(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        wall = round(time.monotonic() - started, 3)
        events: list[dict[str, Any]] = []
        for line in proc.stdout.splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    events.append({"type": "unparsable", "line": line})
        (run_dir / "stream.jsonl").write_text(
            _redact(proc.stdout), encoding="utf-8")
        (run_dir / "stderr.log").write_text(
            _redact(proc.stderr), encoding="utf-8")
        (run_dir / "meta.json").write_text(json.dumps({
            "name": name,
            "exit_code": proc.returncode,
            "wall_seconds": wall,
            "model": self.model,
            "gateway_base_url": self.gateway_base_url,
            "cwd": str(cwd),
            "args": [_redact(a) for a in args],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return proc.returncode, events, proc.stderr

    def workspace(self, name: str) -> Path:
        path = self._workspace_root / f"{name}-{uuid.uuid4().hex[:8]}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def summary(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        summaries = [e for e in events if e.get("type") == "summary"]
        assert summaries, f"no summary line in stream: {events[-1:]}"
        return summaries[-1]


@pytest.fixture(scope="module")
def live() -> LiveSession:
    session = LiveSession()
    # One cheap connectivity probe up front so a credential/endpoint problem
    # fails with the exact check detail instead of three confusing scenarios.
    code, events, _stderr = session.run_cli("00-doctor", "doctor", "--json",
                                            cwd=session.root)
    report = next((e for e in events if e.get("type") == "doctor"), None)
    assert report is not None, "doctor --json produced no report"
    assert code == 0, f"doctor failed: {json.dumps(report.get('checks', {}))[:800]}"
    models = report["checks"]["models"]
    assert models.get("ok") is True, (
        "model connectivity check failed (missing piece: a working gateway at "
        f"{models.get('gateway_base_url')} for key-configured default model "
        f"{session.model}); detail={models.get('error')}"
    )
    session.doctor = report
    (session.evidence / "00-doctor").mkdir(exist_ok=True)
    return session


# ---------------------------------------------------------------------------
# 01 — deterministic write task: exit 0, exact file content
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_live_01_write_file_exact_content(live: LiveSession) -> None:
    workspace = live.workspace("write")
    target = workspace / "hello.txt"
    # No absolute path in the prompt: the model must locate the workspace via
    # the engine's anchored working directory (H10.2-DEFECT-3 regression proof),
    # and the process cwd is the live root, never the workspace.
    code, events, stderr = live.run_cli(
        "01-write-file", "run",
        "-p", "在工作区创建文件 hello.txt，内容为一行："
              "ATLAS-LIVE-SMOKE-OK。除该行外不要写入任何其他内容。",
        "--workspace", str(workspace),
        "--model", live.model,
        "--output-format", "stream-json",
        "--timeout", "480",
        cwd=live.root,
    )
    summary = live.summary(events)
    assert code == 0, f"exit={code} stderr={_redact(stderr)[-1500:]}"
    assert summary["result"] == "completed"
    # Real-model evidence: actual provider usage came back.
    usage = summary.get("usage") or {}
    assert usage.get("model") == live.model
    assert usage.get("input_tokens") and usage.get("output_tokens")
    assert (summary.get("changes") or {}).get("files", 0) >= 1
    content = target.read_text(encoding="utf-8")
    assert content.strip() == "ATLAS-LIVE-SMOKE-OK", repr(content)
    # H10.2-DEFECT-3 regression: the file landed inside --workspace, and the
    # process launch dir (the live root) stayed clean.
    assert not (live.root / "hello.txt").exists()
    assert any(
        e.get("event") == "tool.completed" and e.get("data", {}).get("name") == "write_file"
        and not e.get("data", {}).get("is_error")
        for e in events if e.get("type") == "agent_event"
    ), "expected a successful write_file tool event"


# ---------------------------------------------------------------------------
# 02 — read + answer turn: exit 0, non-empty real answer with the seeded fact
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_live_02_read_and_answer(live: LiveSession) -> None:
    workspace = live.workspace("read")
    (workspace / "answer.txt").write_text(
        "项目编号：ATLAS-SMOKE\n魔数：4711\n备注：本文件只用于读取测试。\n",
        encoding="utf-8",
    )
    code, events, stderr = live.run_cli(
        "02-read-answer", "run",
        "-p", f"读取 {workspace / 'answer.txt'}，只回答文件中的魔数是多少（只输出数字）。",
        "--workspace", str(workspace),
        "--model", live.model,
        "--output-format", "stream-json",
        "--timeout", "480",
        cwd=live.root,
    )
    summary = live.summary(events)
    assert code == 0, f"exit={code} stderr={_redact(stderr)[-1500:]}"
    assert summary["result"] == "completed"
    usage = summary.get("usage") or {}
    assert usage.get("input_tokens") and usage.get("output_tokens")
    assert MAGIC_NUMBER in (summary.get("message") or ""), (
        f"answer missing magic number: {summary.get('message')!r}"
    )
    # A pure read/answer turn must not modify the workspace.
    assert (summary.get("changes") or {}).get("files", 0) == 0


# ---------------------------------------------------------------------------
# 03 — approval deny path under a real model: exit 3, nothing written
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_live_03_ask_writes_auto_deny_exit_3(live: LiveSession) -> None:
    workspace = live.workspace("approve")
    target = workspace / "forbidden.txt"
    code, events, stderr = live.run_cli(
        "03-approval-deny", "run",
        "-p", f"把字符串 denied-marker 写入文件 {target}。",
        "--workspace", str(workspace),
        "--model", live.model,
        "--permission-mode", "ask_writes",
        "--output-format", "stream-json",
        "--timeout", "480",
        cwd=live.root,
    )
    summary = live.summary(events)
    kinds = [e.get("event") for e in events if e.get("type") == "agent_event"]
    assert code == 3, f"exit={code} stderr={_redact(stderr)[-1500:]}"
    assert "approval.required" in kinds, kinds
    assert summary["approvals_denied"] >= 1
    responded = next(
        (e for e in events if e.get("type") == "agent_event"
         and e.get("event") == "approval.responded"),
        None,
    )
    assert responded is not None and responded["data"]["choice"] == "deny"
    assert not target.exists(), "denied write must not land"
