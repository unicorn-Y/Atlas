"""Portable, single-file read-only conversation exports."""
from __future__ import annotations

from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
from typing import Any

_SECRET = re.compile(r"(?i)(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|(?:token|api[_-]?key|password|secret)\s*[:=]\s*['\"]?[^\s'\"]{8,})")
_USER_PATH = re.compile(r"(?i)(?:[A-Z]:\\Users\\[^\\\s]+|/home/[^/\s]+|/Users/[^/\s]+)")


def redact(value: str) -> str:
    return _USER_PATH.sub("~", _SECRET.sub("[REDACTED]", value))


def export_html(path: Path, *, title: str, messages: list[dict[str, Any]],
                model: str = "", usage: dict[str, Any] | None = None,
                include_tools: bool = True, include_thinking: bool = False) -> Path:
    rows = []
    for item in messages:
        role = str(item.get("role", "assistant"))
        content = str(item.get("content", ""))
        metadata = item.get("metadata", {})
        if isinstance(metadata, str):
            try: metadata = json.loads(metadata)
            except json.JSONDecodeError: metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        is_tool = role in {"tool", "function"} or bool((metadata or {}).get("tool_calls"))
        is_thought = role == "thinking" or bool((metadata or {}).get("thinking"))
        if (is_tool and not include_tools) or (is_thought and not include_thinking):
            continue
        safe = html.escape(redact(content))
        safe = re.sub(
            r"!\[([^\]]*)\]\((data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+)\)",
            lambda match: f'<img alt="{match.group(1)}" src="{match.group(2)}" style="max-width:100%">', safe,
        )
        if safe.startswith("diff --git") or "@@ -" in safe:
            safe = re.sub(r"(?m)^(\+.*)$", r'<span class="add">\1</span>', safe)
            safe = re.sub(r"(?m)^(-.*)$", r'<span class="del">\1</span>', safe)
        body = f"<details><summary>工具调用 / 输出</summary><pre>{safe}</pre></details>" if is_tool else f"<pre>{safe}</pre>"
        if is_thought:
            body = f"<details><summary>思考</summary>{body}</details>"
        rows.append(f'<article class="{html.escape(role)}"><header>{html.escape(role)} · {html.escape(str(item.get("created_at", "")))}</header>{body}</article>')
    usage_text = html.escape(json.dumps(usage or {}, ensure_ascii=False))
    doc = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{html.escape(title)}</title>
<style>body{{font:15px/1.6 system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#222}}header{{color:#666;font-size:12px}}article{{border:1px solid #ddd;border-radius:10px;padding:1rem;margin:1rem 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:.5rem 0}}.add{{color:#176b35;background:#e8f5eb}}.del{{color:#a21d24;background:#fdebed}}.user{{background:#f7f9ff}}.meta{{color:#555}}</style>
<h1>{html.escape(title)}</h1><p class="meta">导出时间：{datetime.now(timezone.utc).isoformat()} · 模型：{html.escape(model)} · 用量：{usage_text}</p>{''.join(rows)}</html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    return path
