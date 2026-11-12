"""Real-path checks for U12 CLI attachments, PPTX element references and stdin cards."""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

# python-pptx is optional (the `office` extra); without it the whole module would
# fail to import and take the CLI attachment and stdin-card checks with it.
Presentation = pytest.importorskip(
    "pptx", reason="optional Office dependency, not installed in this environment"
).Presentation

from atlas import cli
from atlas.office import render_office
from atlas.tools.local_execution import LocalExecutionRuntime


def test_cli_attach_is_encoded_into_first_run_message(tmp_path: Path, monkeypatch) -> None:
    attachment = tmp_path / "首轮附件.txt"
    attachment.write_text("U12 附件内容", encoding="utf-8")
    captured: dict[str, object] = {}

    async def fake_run_headless(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "_run_headless", fake_run_headless)
    result = CliRunner().invoke(cli.main, ["run", "-p", "读取附件", "--workspace", str(tmp_path), "--attach", str(attachment)])
    assert result.exit_code == 0, result.output
    files = captured["attachments"]
    assert isinstance(files, list) and len(files) == 1
    assert files[0]["name"] == attachment.name
    assert base64.b64decode(files[0]["data_base64"]).decode("utf-8") == "U12 附件内容"


def test_pptx_preview_exposes_stable_element_ids() -> None:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "U12 预览"
    slide.placeholders[1].text = "可引用正文元素"
    import io
    payload = io.BytesIO()
    presentation.save(payload)
    html = render_office(payload.getvalue(), ".pptx")
    assert 'data-slide="1"' in html
    assert 'data-shape-id=' in html
    assert "可引用正文元素" in html


def test_process_card_stdin_reaches_live_child_process(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = LocalExecutionRuntime()
        record = await runtime._start_from_exec({
            "executable": sys.executable,
            "args": ["-u", "-c", "import sys; print(sys.stdin.readline().strip(), flush=True)"],
            "cwd": str(tmp_path), "keep_stdin": True,
        }, "u12-check", None)
        await runtime._write_process_stdin(record, "submit_stdin", "U12-stdin-ok")
        result = await runtime._wait_result(record, timeout=10)
        output = result["content"][0]["text"]
        assert result["data"]["exit_code"] == 0
        assert "U12-stdin-ok" in output

    asyncio.run(scenario())


def test_question_and_sidechat_recovery_contracts() -> None:
    root = Path(__file__).resolve().parents[2]
    question = (root / "frontend/src/renderer/components/ConversationActivity.tsx").read_text(encoding="utf-8")
    side_chat = (root / "frontend/src/renderer/components/SideChat.tsx").read_text(encoding="utf-8")
    app = (root / "frontend/src/renderer/App.tsx").read_text(encoding="utf-8")
    tool_card = (root / "frontend/src/renderer/components/tool-cards/ToolExecutionCard.tsx").read_text(encoding="utf-8")
    compaction = (root / "core/atlas/kernel/loop.py").read_text(encoding="utf-8")
    timeline = (root / "frontend/src/renderer/components/timeline.ts").read_text(encoding="utf-8")
    shortcuts = (root / "frontend/src/renderer/pages/ShortcutsPanel.tsx").read_text(encoding="utf-8")
    assert "atlas.question-draft." in question and "localStorage.setItem(draftKey" in question
    assert "multi_select" in question and "submitAll" in question
    assert "SIDE_COMMANDS" in side_chat and "旁聊只支持" in side_chat
    assert "安排插话" in app and "停止当前运行，优先处理这条" in app
    assert "Reviewing · 正在审查" in app
    assert "/api/processes/${encodeURIComponent(processId)}/stdin" in tool_card
    assert '"duration_ms": round((time.monotonic() - compaction_started) * 1000)' in compaction
    assert "上下文整理完成" in timeline and "run.compaction.progress" in timeline
    assert "在输入框下方显示按键提示" in shortcuts
