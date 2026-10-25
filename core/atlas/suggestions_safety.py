"""Safety filter for model-generated follow-up suggestions shown as one-click actions."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

GENERIC_SUGGESTIONS = {"继续", "请继续", "继续吧", "确认", "收到", "好的", "好", "谢谢", "明白", "没问题", "OK", "ok"}
_GENERIC_CASEFOLD = {value.casefold() for value in GENERIC_SUGGESTIONS}
UNSAFE_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\brm\s+-[^\s]*r[^\s]*f\b|\brm\s+-[^\s]*f[^\s]*r\b",
    r"\b(?:remove-item|rmdir|rd|del)\b.{0,120}(?:-recurse|/s\b|/q\b)",
    r"\b(?:mkfs(?:\.[\w-]+)?|diskpart|format\s+[a-z]:)\b",
    r"\bfind\b.{0,180}\s-delete\b|\bshutil\.rmtree\b",
    r"(?:永久|彻底|递归|强制).{0,20}(?:删除|清空|格式化|擦除)|(?:删除|清空|格式化|擦除).{0,20}(?:全部|所有|整个磁盘|根目录|系统文件|数据库)",
    r"\bdd\s+if=.{0,120}\bof=/dev/(?:zero|sda|nvme)",
    r"\bgit\s+(?:reset\s+--hard|clean\s+-[^\s]*f)",
    r"\b(?:drop\s+(?:database|table)|truncate\s+table)\b",
    r"\b(?:curl|wget|iwr|invoke-webrequest)\b.{0,160}(?:\||;).{0,80}(?:sh|bash|iex|invoke-expression)\b",
    r"(?:api[_ -]?keys?|passwords?|secrets?|credentials?|access tokens?|密钥|密码|凭据|访问令牌).{0,100}(?:upload|send|print|dump|export|post|上传|外发|发送|打印|导出|泄露)",
    r"(?:upload|send|print|dump|export|post|上传|外发|发送|打印|导出|泄露).{0,100}(?:api[_ -]?keys?|passwords?|secrets?|credentials?|access tokens?|密钥|密码|凭据|访问令牌)",
))


def filter_safe_suggestions(value: Any, *, limit: int = 3) -> list[str]:
    """Return unique, bounded, actionable suggestions; fail closed on unsafe content."""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not 6 <= len(text) <= 180 or any(ord(char) < 32 for char in text):
            continue
        generic_key = text.rstrip("。.!！?？").casefold()
        if generic_key in _GENERIC_CASEFOLD:
            continue
        normalized = unicodedata.normalize("NFKC", text).replace("\u200b", "").replace("\ufeff", "")
        if any(pattern.search(normalized) for pattern in UNSAFE_PATTERNS):
            continue
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result
