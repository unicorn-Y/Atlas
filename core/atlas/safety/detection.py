# Rules adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# tools/approval_detection.py (MIT, (c) Nous Research); includes Atlas/Windows paths.
"""Small, conservative Windows and shell destructive-operation detector."""

from __future__ import annotations

import re

RULES = {
    "recursive_delete": "递归删除或清空文件",
    "disk_format": "格式化磁盘或文件系统",
    "registry_delete": "删除 Windows 注册表",
    "execution_policy": "更改 PowerShell 执行策略",
    "sensitive_path": "修改凭据或系统配置",
}

_DANGEROUS = (
    ("recursive_delete", re.compile(
        r"\b(?:rm\s+-[^\n]*r|remove-item\b[^\n]*-recurse|rd\s+/s|rmdir\s+/s|del\s+/s)\b",
        re.I)),
    ("disk_format", re.compile(r"\b(?:format-volume|format\s+[a-z]:|diskpart|mkfs(?:\.[\w]+)?)\b", re.I)),
    ("registry_delete", re.compile(r"\breg(?:\.exe)?\s+delete\b", re.I)),
    ("execution_policy", re.compile(r"\bset-executionpolicy\b", re.I)),
    ("sensitive_path", re.compile(
        r"(?:\.env(?:\.[\w.-]+)?|\\\.ssh\\|/\.ssh/|(?:atlas|codex)\.toml)", re.I)),
)
_SAFE_GENERATED = re.compile(r"(?:^|[\\/])(node_modules|dist|build|\.pytest[^\\/]*)$", re.I)


def detect_danger(command: str) -> list[str]:
    text = str(command or "")
    ids = [rule_id for rule_id, pattern in _DANGEROUS if pattern.search(text)]
    if "recursive_delete" in ids and re.search(r"(?:node_modules|dist|build|\.pytest[^\\/]*)", text, re.I):
        if not re.search(r"(?:\$HOME|%USERPROFILE%|\\Users\\[^\\]+\\Downloads|/home/)", text, re.I):
            ids.remove("recursive_delete")
    return ids
