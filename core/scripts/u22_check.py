"""U22 real-scenario acceptance checks. Run from the repository root with core's uv env."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))
os.environ.setdefault("ATLAS_ROOT", r"C:\engine-reg\_atlasroot")


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
    command = [
        sys.executable, "-m", "atlas.cli", "exec", "--model", "deepseek-v4.1-flash",
        "--workspace", str(workspace), "--approve-writes",
        "Use create_document to create u22-live-template.docx in the current workspace. "
        "Make a concise project decision brief with a title, executive summary, assumptions, "
        "risks, and three owner/action rows. Use concrete sample wording and no placeholders.",
    ]
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(
        part for part in (str(CORE), os.environ.get("PYTHONPATH", "")) if part
    )}
    result = subprocess.run(
        command, cwd=ROOT, env=environment, capture_output=True,
        encoding="utf-8", errors="replace", timeout=240, check=False,
    )
    target = workspace / "u22-live-template.docx"
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        # Provider error text can contain request details; do not print subprocess output.
        raise RuntimeError(f"real deepseek-v4.1-flash Office scenario failed (exit {result.returncode})")
    print("PASS Office live-model scene: deepseek-v4.1-flash created a DOCX through create_document")


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
