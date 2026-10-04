"""H10.2 §12.2 FULL live scenario set (atlas run side: 01-07 + 11).

Taskbook §12.2: 用 H9 的 ``atlas run`` 驱动，任务放 ``tests/live/<编号>/``
(起始文件 + ``task.md`` 中文原话 + ``check.py``)。Each scenario below copies its
``core/tests/live/<nn>/workspace`` into a fresh scratch workspace, runs the task
verbatim through the headless CLI, then runs the scenario's ``check.py`` against
the workspace. Scenarios 08/09/10/12 (plan approval / rewind / mid-run steer /
webhook channel) need one persistent backend plus a second WS/API connection —
they live in ``test_live_full_run_server.py``.

Live root: ATLAS_LIVE_SMOKE_ROOT built by
``artifacts/h10-live-smoke/full-run/build_full_run_root.py`` (host-shaped config,
prefixed ``litellm_model`` verbatim; engine ``context_length: 65536`` so scenario
06 can force a real auto-compaction; ``compression_model`` set so the compressor
summary wire-id derivation (lane Q residual) is exercised against the real relay;
stdio MCP filesystem server for scenario 11). Evidence lands redacted under
ATLAS_LIVE_EVIDENCE_DIR.

Requires ``ATLAS_LIVE=1`` + ``-m live`` (core/tests/conftest.py policy).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_live_model_smoke import LiveSession, _redact

CORE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "live"
RUN_TIMEOUT = "600"


# ---------------------------------------------------------------------------
# harness helpers
# ---------------------------------------------------------------------------


def _fixture(scenario: str) -> Path:
    path = FIXTURES / scenario
    assert path.is_dir(), f"missing scenario fixture dir {path}"
    return path


def _prompt(scenario: str, *extra: str) -> str:
    text = (_fixture(scenario) / "task.md").read_text(encoding="utf-8").strip()
    for name in extra:
        if name:
            text += "\n" + name.strip()
    return text


def _prepare_workspace(live: LiveSession, scenario: str, name: str) -> Path:
    workspace = live.workspace(name)
    source = _fixture(scenario) / "workspace"
    if source.is_dir():
        import shutil

        shutil.copytree(source, workspace, dirs_exist_ok=True)
    return workspace


def _check(live: LiveSession, scenario: str, name: str, workspace: Path,
           stdin_text: str = "") -> str:
    """Run the scenario's check.py; returns its stdout (starts with CHECK-OK on pass)."""
    proc = subprocess.run(
        [sys.executable, str(_fixture(scenario) / "check.py"), str(workspace)],
        input=stdin_text, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=300, cwd=str(_fixture(scenario)),
    )
    out = proc.stdout or ""
    run_dir = live.evidence / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "check.log").write_text(
        _redact(f"exit={proc.returncode}\n{out}\n--- stderr ---\n{proc.stderr}"),
        encoding="utf-8",
    )
    assert proc.returncode == 0 and "CHECK-OK" in out, (
        f"{scenario} check failed: {out} {proc.stderr}"
    )
    return out


def _atlas_run(live: LiveSession, name: str, prompt: str, workspace: Path,
               *extra_args: str, timeout: str = RUN_TIMEOUT) -> dict:
    code, events, stderr = live.run_cli(
        name, "run",
        "-p", prompt,
        "--workspace", str(workspace),
        "--model", live.model,
        "--output-format", "stream-json",
        "--timeout", timeout,
        *extra_args,
        cwd=live.root,
    )
    summaries = [e for e in events if e.get("type") == "summary"]
    assert summaries, f"{name}: no summary line (exit={code}) stderr={_redact(stderr)[-1200:]}"
    summary = summaries[-1]
    assert code == 0, f"{name}: exit={code} summary={summary} stderr={_redact(stderr)[-1200:]}"
    assert summary.get("result") == "completed", f"{name}: result={summary.get('result')}"
    usage = summary.get("usage") or {}
    assert usage.get("input_tokens") and usage.get("output_tokens"), (
        f"{name}: no real provider usage in summary: {usage}"
    )
    return summary


def _scan_evidence(live: LiveSession, name: str) -> str:
    blob = ""
    for filename in ("stream.jsonl", "stderr.log"):
        path = live.evidence / name / filename
        if path.exists():
            blob += path.read_text(encoding="utf-8", errors="replace")
    return blob


def _scan(blob: str, pattern: str, *, groups: bool = False) -> list[str] | bool:
    matches = re.findall(pattern, blob, flags=re.IGNORECASE)
    if groups:
        return matches
    return bool(matches)


@pytest.fixture(scope="module")
def full_live() -> LiveSession:
    """Same gate as the smoke suite: doctor must pass before any scenario runs."""
    session = LiveSession()
    code, events, _stderr = session.run_cli("00-doctor", "doctor", "--json",
                                            cwd=session.root)
    report = next((e for e in events if e.get("type") == "doctor"), None)
    assert report is not None, "doctor --json produced no report"
    assert code == 0, f"doctor failed: {report.get('checks', {})}"
    models = report["checks"]["models"]
    assert models.get("ok") is True, (
        f"model connectivity failed: {models.get('error')}"
    )
    session.doctor = report
    return session


# ---------------------------------------------------------------------------
# 01 — small Python repo has a failing test; fix the code until it passes
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_01_fix_failing_python_test(full_live: LiveSession) -> None:
    scenario = "01-fix-python-test"
    workspace = _prepare_workspace(full_live, scenario, "fix-py")
    _atlas_run(full_live, scenario, _prompt(scenario), workspace)
    _check(full_live, scenario, scenario, workspace)


# ---------------------------------------------------------------------------
# 02 — small TS repo: add a function plus tests
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_02_ts_add_function_and_tests(full_live: LiveSession) -> None:
    scenario = "02-ts-add-function"
    workspace = _prepare_workspace(full_live, scenario, "ts-fn")
    _atlas_run(full_live, scenario, _prompt(scenario), workspace)
    _check(full_live, scenario, scenario, workspace)


# ---------------------------------------------------------------------------
# 03 — CRLF + Chinese path + UTF-8 BOM file edited in place
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_03_crlf_bom_chinese_path_preserved(full_live: LiveSession) -> None:
    scenario = "03-crlf-bom-chinese-path"
    workspace = _prepare_workspace(full_live, scenario, "crlf")
    _atlas_run(full_live, scenario, _prompt(scenario), workspace)
    _check(full_live, scenario, scenario, workspace)


# ---------------------------------------------------------------------------
# 04 — run a PowerShell command, read its output, edit a file accordingly
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_04_powershell_read_then_edit(full_live: LiveSession) -> None:
    scenario = "04-powershell-read-modify"
    workspace = _prepare_workspace(full_live, scenario, "pwsh")
    _atlas_run(full_live, scenario, _prompt(scenario), workspace)
    _check(full_live, scenario, scenario, workspace)


# ---------------------------------------------------------------------------
# 05 — four rounds of appended constraints (resume); round 1 still held
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_05_four_round_constraints_survive(full_live: LiveSession) -> None:
    scenario = "05-four-round-constraints"
    fixture = _fixture(scenario)
    workspace = _prepare_workspace(full_live, scenario, "constraints")
    rounds = (fixture / "task.md").read_text(encoding="utf-8").strip()
    follow_ups = [
        part.strip()
        for part in (fixture / "constraints.md").read_text(encoding="utf-8").split("\n\n")
        if part.strip()
    ]
    first = _atlas_run(full_live, f"{scenario}-r1", rounds, workspace)
    conversation_id = str(first.get("conversation_id") or "")
    assert conversation_id, "round 1 summary lacks conversation_id"
    for index, follow_up in enumerate(follow_ups, start=2):
        _atlas_run(
            full_live, f"{scenario}-r{index}", follow_up, workspace,
            "--resume", conversation_id,
        )
    _check(full_live, scenario, scenario, workspace)


# ---------------------------------------------------------------------------
# 06 — force real auto-compaction, then still finish the task correctly
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_06_auto_compaction_then_task_still_correct(full_live: LiveSession) -> None:
    scenario = "06-auto-compaction"
    workspace = _prepare_workspace(full_live, scenario, "compact")
    # Deterministic oversized read target (the fixture dir only carries the generator).
    proc = subprocess.run(
        [sys.executable, str(_fixture(scenario) / "make_workspace.py"), str(workspace)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert proc.returncode == 0, f"big.txt generation failed: {proc.stderr}"
    (full_live.evidence / scenario).mkdir(parents=True, exist_ok=True)
    (full_live.evidence / scenario / "workspace-seed.log").write_text(
        _redact(proc.stdout), encoding="utf-8")

    summary = _atlas_run(full_live, scenario, _prompt(scenario), workspace, timeout="900")
    _check(full_live, scenario, scenario, workspace)

    # The scenario only proves what its name claims if a compaction actually
    # ran: the engine's compaction status prints (📦/🗜️ markers) surface in the
    # stream/stderr. Compressor INIT lines are not evidence and must not match.
    blob = _scan_evidence(full_live, scenario)
    assert _scan(blob, r"Preflight compression|Pre-API compression"
                       r"|summarizing earlier conversation|Session compressed"
                       r"|Context reduced to"), (
        "no auto-compaction run marker found in evidence; the scenario did not force one"
    )
    # Lane Q residual, live: the compressor's summary call must dispatch the BARE
    # wire id (host-shaped config keeps the prefixed litellm_model; the runtime
    # derives the wire id) and must not fall back to the main model.
    dispatched = _scan(
        blob, r"Compression summary call dispatched: model=(\S+)", groups=True)
    if dispatched:
        assert all("/" not in model for model in dispatched), (
            f"compression summary dispatched prefixed id(s): {dispatched}"
        )
        assert "deepseek" in dispatched[0], f"unexpected summary model: {dispatched[0]}"
    assert not _scan(
        blob, r"Summary model '.*' .* Falling back to main model"), (
        "compression fell back from the configured summary model to the main model"
    )
    usage = summary.get("usage") or {}
    assert (usage.get("input_tokens") or 0) > 8000, (
        f"input tokens too low for a real multi-read turn: {usage}"
    )


# ---------------------------------------------------------------------------
# 07 — three unrelated subtasks to parallel subagents, aggregated correctly
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_07_three_parallel_subagents(full_live: LiveSession) -> None:
    scenario = "07-three-subagents"
    workspace = _prepare_workspace(full_live, scenario, "subtasks")
    _atlas_run(full_live, scenario, _prompt(scenario), workspace, timeout="900")
    _check(full_live, scenario, scenario, workspace)


# ---------------------------------------------------------------------------
# 08 — plan mode → approve → execute: moved to test_live_full_run_server.py
# (the desktop plan-approve surface is a second WS connection on a persistent
# backend; in-process atlas run cannot reach its own ephemeral port).


# ---------------------------------------------------------------------------
# 11 — read a file through the MCP filesystem tool and answer
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_full_11_mcp_filesystem_read_answer(full_live: LiveSession) -> None:
    scenario = "11-mcp-filesystem"
    workspace = _prepare_workspace(full_live, scenario, "mcp-read")
    summary = _atlas_run(full_live, scenario, _prompt(scenario), workspace)
    answer = str(summary.get("message") or "")
    blob = _scan_evidence(full_live, scenario)
    # The answer must come from the MCP tool, not local file reads: evidence must
    # show the MCP tool call, and the vault answer must be correct.
    assert _scan(blob, r"atlas-live-fs"), (
        "no atlas-live-fs MCP tool trace in evidence"
    )
    _check(full_live, scenario, scenario, workspace, stdin_text=answer)
