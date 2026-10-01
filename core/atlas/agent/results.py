# Storage and preview behavior adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# tools/tool_result_storage.py (MIT, (c) Nous Research), retaining Atlas's run-scoped data root.
"""Bounded tool-result handling for model context."""

from __future__ import annotations

from pathlib import Path

from atlas.tools.output_limits import get_max_bytes
from atlas.tools.output_truncate import truncate_head_tail


def externalize_tool_output(
    output: str, data_root: Path, run_id: str | None, call_id: str,
) -> tuple[str, str | None]:
    if len(output.encode("utf-8")) <= 16 * 1024:
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
