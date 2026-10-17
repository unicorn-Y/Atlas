# Storage and preview behavior adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# tools/tool_result_storage.py (MIT, (c) Nous Research), retaining Atlas's run-scoped data root.
"""Bounded tool-result handling for model context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atlas.tools.output_limits import get_max_bytes
from atlas.tools.output_truncate import truncate_head_tail


def externalize_tool_output(
    output: str, data_root: Path, run_id: str | None, call_id: str,
    inline_bytes: int = 16 * 1024,
) -> tuple[str, str | None]:
    if len(output.encode("utf-8")) <= inline_bytes:
        return output, None
    if not run_id:
        return truncate_head_tail(output, get_max_bytes(), label="TOOL OUTPUT"), None
    safe_run = "".join(char for char in run_id if char.isalnum() or char in "-_")[:100]
    safe_call = "".join(char for char in call_id if char.isalnum() or char in "-_")[:100]
    path = data_root / "tool-results" / safe_run / f"{safe_call or 'call'}.txt"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
    except OSError:
        return truncate_head_tail(output, get_max_bytes(), label="TOOL OUTPUT"), None
    raw = output.encode("utf-8")
    head = raw[:4096].decode("utf-8", errors="ignore")
    tail = raw[-4096:].decode("utf-8", errors="ignore")
    preview = (f"{head}\n\n[Full tool output saved to {path}; showing first and last 4 KB. "
               "Use the file tool to read the complete output if needed.]\n\n" + tail)
    return preview, str(path)


# ---------------------------------------------------------------------------
# 子代理结果 framing（D2，对齐 Claude Code 2.1.277）
# ---------------------------------------------------------------------------
# 子代理/delegate 的文本会作为工具结果拼回父会话上下文；被攻陷或被提示注入的子代理
# 不得冒充父会话或 harness 发号施令。防御与上游同构：
# 1. 头部由父端（本模块调用方）在子代理结束后生成——子代理的上下文里拿不到自己的
#    subtask_id（父端 secrets.token_hex 生成，从不回传给子代理），头部结构性不可伪造。
# 2. 正文每一行都缩进两个空格（空行保持为空），因此除首尾两行外任何行都不会顶格——
#    子代理正文中伪造的 `<atlas-subagent-result ...>` 只会以缩进内容出现，不构成结构。
# 中文安全：全部为纯 str 操作，无编码/宽度假设。

SUBAGENT_RESULT_OPEN = "<atlas-subagent-result"
SUBAGENT_RESULT_CLOSE = "</atlas-subagent-result>"
_SUBAGENT_INDENT = "  "


def frame_subagent_result(
    text: str, *, subtask_id: str = "", backend: str = "", agent: str = "", status: str = "",
) -> str:
    """Wrap child/delegate output with a structural header and an indented body."""
    attributes: list[str] = []
    for key, raw in (("id", subtask_id), ("backend", backend), ("agent", agent), ("status", status)):
        # 属性压成单行、去引号，保证头部恒为一行、形状无歧义。
        value = " ".join(str(raw or "").split()).replace('"', "'")[:120]
        if value:
            attributes.append(f'{key}="{value}"')
    header = SUBAGENT_RESULT_OPEN + (" " + " ".join(attributes) if attributes else "") + ">"
    body = str(text or "")
    if not body.strip():
        rendered = f"{_SUBAGENT_INDENT}(子任务没有返回文本)"
    else:
        rendered = "\n".join(
            _SUBAGENT_INDENT + line if line.strip() else ""
            for line in body.splitlines()
        )
    return f"{header}\n{rendered}\n{SUBAGENT_RESULT_CLOSE}"


def frame_delegate_result_data(data: dict[str, Any]) -> dict[str, Any]:
    """Shallow copy of a delegation payload whose ``result`` text is framed.

    只改模型可见文本：结构化字段（backend/subtask_id/status/evidence/…）原样透传，
    前端读到的 schema 不变；``result`` 非字符串或为空（例如后台任务仍在运行）时不改写。
    """
    if not isinstance(data, dict):
        return data
    text = data.get("result")
    if not isinstance(text, str) or not text.strip():
        return data
    return {
        **data,
        "result": frame_subagent_result(
            text,
            subtask_id=str(data.get("subtask_id") or ""),
            backend=str(data.get("backend") or ""),
            status=str(data.get("status") or ""),
        ),
    }
