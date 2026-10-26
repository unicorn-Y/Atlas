"""U22 real-scenario acceptance checks. Run from the repository root with core's uv env."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))
os.environ.setdefault("ATLAS_ROOT", r"C:\engine-reg\_atlasroot")

_DIAGNOSTIC_SECRET = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret|token)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_KEY_SHAPES = re.compile(
    r"\b(?:dsk-|sk-|xox[baprs]-|gh[pousr]_|github_pat_|AIza|AKIA|ASIA)[A-Za-z0-9_-]{12,}\b"
)


def _redact_diagnostic(value: str) -> str:
    value = _DIAGNOSTIC_SECRET.sub(r"\1\2[REDACTED]", value)
    value = _BEARER.sub("Bearer [REDACTED]", value)
    value = _KEY_SHAPES.sub("[REDACTED_KEY]", value)
    return value[-2400:]


def _last_run_error_event(since: float) -> str:
    """Return only the last error-shaped event, never raw event JSON or run prompts."""
    try:
        from atlas.logs import LOG_DIR

        paths = [path for path in (LOG_DIR / "runs").rglob("*.jsonl")
                 if path.is_file() and path.stat().st_mtime >= since - 2]
    except OSError:
        return "unavailable"
    except Exception:
        return "unavailable"
    paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths[:20]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines[-300:]):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            event = str(record.get("event") or "")
            if not ("error" in event.lower() or "fail" in event.lower() or "timeout" in event.lower()):
                continue
            summary = {key: record[key] for key in (
                "timestamp", "event", "run_id", "tool", "tool_name", "error_type", "status",
                "status_code", "category", "error"
            ) if key in record}
            return _redact_diagnostic(json.dumps(summary, ensure_ascii=False, default=str))
    return "none"


def _action_continuation_count(since: float) -> int:
    try:
        from atlas.logs import LOG_DIR

        paths = [path for path in (LOG_DIR / "runs").rglob("*.jsonl")
                 if path.is_file() and path.stat().st_mtime >= since - 2]
    except Exception:
        return 0
    count = 0
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("event") == "unfulfilled_action_continuation":
                count += 1
    return count


def check_office_generation(workspace: Path) -> None:
    from atlas.office import create_document, create_presentation, create_spreadsheet, read_office

    document_path = "templates/report.docx"
    spreadsheet_path = "templates/tasks.xlsx"
    presentation_path = "templates/update.pptx"
    create_document(str(workspace), {
        "path": document_path, "title": "U22 project report",
        "blocks": [{"type": "heading", "text": "Executive summary", "level": 1},
                   {"type": "paragraph", "text": "Decision, findings, and next actions."},
                   {"type": "table", "rows": [["Action", "Owner"], ["Review", "Team"]]}],
    })
    create_spreadsheet(str(workspace), {
        "path": spreadsheet_path,
        "sheets": [{"name": "Tasks", "rows": [["Task", "Owner"], ["Review", "Team"]], "header": True}],
    })
    create_presentation(str(workspace), {
        "path": presentation_path,
        "slides": [{"title": "Project update", "bullets": ["Progress", "Risks", "Next steps"]}],
    })
    assert read_office(str(workspace / document_path))["paragraphs"][0] == "Executive summary"
    assert read_office(str(workspace / spreadsheet_path))["sheets"][0]["rows"][1][0] == "Review"
    assert read_office(str(workspace / presentation_path))["slides"][0]["title"] == "Project update"
    print("PASS Office tool generation: DOCX, XLSX, PPTX created and read back")


def check_live_model_template(workspace: Path) -> None:
    """Exercise the real configured model and the same create_document tool used by the UI."""
    from real_model_check import (
        AttemptResult, latest_run_log_path, retry_real_model_check,
    )

    instruction = (
        "Use create_document to create u22-live-template.docx in the current workspace. "
        "Make a concise project decision brief with a title, executive summary, assumptions, "
        "risks, and three owner/action rows. Use concrete sample wording and no placeholders. "
        "After creating the file, reply with a short confirmation."
    )
    command = [
        sys.executable, "-m", "atlas.cli", "exec", "--model", "deepseek-v4.1-flash",
        "--workspace", str(workspace), "--approve-writes",
    ]
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(
        part for part in (str(CORE), os.environ.get("PYTHONPATH", "")) if part
    )}
    target = workspace / "u22-live-template.docx"
    continuation_samples: list[int] = []

    def run_attempt(prompt: str, attempt_number: int) -> AttemptResult:
        del attempt_number
        target.unlink(missing_ok=True)
        started_at = time.time()
        try:
            result = subprocess.run(
                [*command, prompt], cwd=ROOT, env=environment, capture_output=True,
                encoding="utf-8", errors="replace", timeout=300, check=False,
            )
            return_code = result.returncode
            stderr_text = result.stderr or ""
            answer = result.stdout or ""
        except subprocess.TimeoutExpired as exc:
            return_code = "timeout"
            raw_stderr = exc.stderr or ""
            stderr_text = raw_stderr.decode("utf-8", errors="replace") if isinstance(raw_stderr, bytes) else str(raw_stderr)
            raw_stdout = exc.stdout or ""
            answer = raw_stdout.decode("utf-8", errors="replace") if isinstance(raw_stdout, bytes) else str(raw_stdout)
        except OSError as exc:
            return_code = "spawn-error"
            stderr_text = str(exc)
            answer = ""
        continuation_samples.append(_action_continuation_count(started_at))
        if return_code == 0 and target.is_file() and target.stat().st_size > 0:
            return AttemptResult(True, answer=answer, value=target)
        stderr = stderr_text.lower()
        last_error_event = _last_run_error_event(started_at)
        category = next((label for needle, label in (("503", "upstream 503"), ("429", "rate limited"), ("timeout", "timeout"),
                                                     ("timed out", "timeout"), ("401", "auth"), ("create_document", "tool error"))
                         if needle in (stderr + " " + last_error_event.lower())),
                        "model did not create the file" if return_code == 0 else "run failed")
        return AttemptResult(False, answer=answer, detail=(
            f"exit_code={return_code}; failure_category={category}; "
            f"run_log_path={latest_run_log_path(started_at)}; "
            f"stderr_tail={_redact_diagnostic(stderr_text)}; "
            f"last_run_error_event={last_error_event}"
        ), exit_code=return_code, stderr_tail=_redact_diagnostic(stderr_text),
            run_log_path=latest_run_log_path(started_at),
            last_run_error_event=last_error_event)

    retry_real_model_check("U22 Office DOCX tool creation", instruction, run_attempt)
    print(
        "U22 model action-intent continuation events across acceptance attempts: "
        f"{sum(continuation_samples)} (samples={len(continuation_samples)})",
        flush=True,
    )


def check_ide_fallback(workspace: Path) -> None:
    from atlas.ide_context import discover_ide_context, format_ide_context

    source = workspace / "src" / "main.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('fixture')\n", encoding="utf-8")
    context = asyncio.run(discover_ide_context(
        cwd=workspace,
        environment={
            "ZED_TERM": "true", "ZED_WORKTREE_ROOT": str(workspace),
            "ZED_RELATIVE_FILE": "src/main.py", "ATLAS_IDE_SELECTION": "def fixture(): return 22",
        },
        use_extension=False,
    ))
    assert context and context["editor"] == "Zed"
    assert Path(context["file"]) == source.resolve()
    assert context["selection"]["text"] == "def fixture(): return 22"
    assert "Workspace:" in format_ide_context(context)
    print("PASS IDE terminal fallback: Zed workspace, active file, and selected text discovered without extension")


async def check_mcp_stdio(workspace: Path) -> None:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(
        part for part in (str(CORE), os.environ.get("PYTHONPATH", "")) if part
    )}
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "atlas.cli", "mcp", "serve"],
        cwd=ROOT,
        env=environment,
        encoding_error_handler="replace",
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as client:
            await client.initialize()
            tools = await client.list_tools()
            tool = next((item for item in tools.tools if item.name == "local_shell"), None)
            assert tool and "command" in tool.input_schema.get("properties", {})
            assert "arguments" not in tool.input_schema.get("properties", {})
            resources = await client.list_resources()
            assert any(str(item.uri) == "atlas://capabilities" for item in resources.resources)
            catalog = await client.read_resource("atlas://capabilities")
            assert "local_shell" in str(catalog.contents)
            result = await client.call_tool("local_shell", {
                "command": "python --version", "cwd": str(workspace), "timeout": 20,
            })
            assert not result.is_error and "Python " in str(result.content)
    print("PASS MCP server: stdio client listed schema/resources and invoked a real Atlas tool")


def check_ui_wiring() -> None:
    frontend = ROOT / "frontend" / "src" / "renderer"
    shortcuts = (frontend / "services" / "shortcuts.ts").read_text(encoding="utf-8")
    changes = (frontend / "shell" / "panels" / "ChangesPanel.tsx").read_text(encoding="utf-8")
    inspector = (frontend / "shell" / "Inspector.tsx").read_text(encoding="utf-8")
    create = (frontend / "pages" / "CreatePage.tsx").read_text(encoding="utf-8")
    app = (frontend / "App.tsx").read_text(encoding="utf-8")
    assert "Ctrl+Alt+D" in shortcuts and "diffNextHunk" in shortcuts and "diffPreviousHunk" in shortcuts
    assert "折叠差异块" in changes and "atlas:diff-action" in changes and "onReviewHunk" in changes
    assert "任务面板标签概览" in inspector and "aria-valuemin" in inspector and "atlas.preference.inspector-width" in inspector
    assert all(kind in create for kind in ("docx", "xlsx", "pptx")) and "模板结构" in create
    assert "diff-open" in app and "onFullScreenDiffChange" in app
    print("PASS renderer wiring: Office templates, full-screen diff shortcuts, Inspector overview and saved divider")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="atlas-u22-") as temporary:
        workspace = Path(temporary).resolve()
        check_office_generation(workspace)
        if not os.environ.get("U22_SKIP_LIVE_MODEL"):
            check_live_model_template(workspace)
        else:
            print("SKIP Office live-model scene: U22_SKIP_LIVE_MODEL is set")
        check_ide_fallback(workspace)
        asyncio.run(check_mcp_stdio(workspace))
        check_ui_wiring()
    print("U22 CHECK PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
