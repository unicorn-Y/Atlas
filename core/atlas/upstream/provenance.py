"""借鉴代码的来源标注：从源码文件头里认出「从哪个仓库、哪个提交、哪个文件移植来的」。

推荐写法（以后新移植的文件请照这个写，追新会自动跟踪它）::

    # Ported from owner/repo@<完整提交号>: path/in/upstream.py (MIT)

已有文件的写法五花八门（``Adapted from …``、``Vendored from … commit …``、提交号和路径分在
两行……），这里宽松地解析：只看文件开头 20 行，找到含 ported/adapted/vendored/copied … from
的那一行，再在它和后面 4 行里找仓库、提交号和上游路径。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HEADER_LINES = 20
WINDOW = 5
SCAN_ROOTS = ("core/atlas", "core/scripts", "frontend/src", "backend-adapter/src", "scripts")
SUFFIXES = {".py", ".ts", ".tsx", ".mjs", ".js", ".cjs"}

#: 文件头里只写了项目名的，按名字认仓库。
ALIASES = {
    "hermes": "NousResearch/hermes-agent",
    "openclaw": "openclaw/openclaw",
    "opencode": "anomalyco/opencode",
    "mastra": "mastra-ai/mastra",
    "codex": "openai/codex",
}

_TRIGGER = re.compile(r"\b(ported|adapted|vendored|copied)\b.*?\bfrom\b", re.IGNORECASE)
_REPO = re.compile(r"\bfrom\s+`*([A-Za-z0-9][\w-]*/[\w.-]*[\w-])")
_SHA = re.compile(r"(?<![0-9a-fA-F])([0-9a-f]{7,40})(?![0-9a-fA-F])")
_PATH = re.compile(r"(?<![\w/\\.-])((?:[\w.-]+/)+[\w.-]+\.[A-Za-z]{1,5})\b")


@dataclass
class Provenance:
    file: str          # 仓库内相对路径（posix）
    repo: str          # owner/repo；认不出时为空
    sha: str           # 文件头里写的提交号（可能是短号）；没写时为空
    path: str          # 上游文件路径；没写时为空
    line: int          # 标注所在行号（1 起）
    text: str          # 标注原文（首行）


def parse_header(text: str, file: str = "") -> Provenance | None:
    lines = text.splitlines()[:HEADER_LINES]
    for index, line in enumerate(lines):
        if not _TRIGGER.search(line):
            continue
        window = "\n".join(lines[index:index + WINDOW])
        repo = ""
        match = _REPO.search(window)
        if match and not re.search(r"\.[A-Za-z]{1,5}$", match.group(1)):
            repo = match.group(1)
        if not repo:
            lowered = window.lower()
            repo = next((full for alias, full in ALIASES.items() if alias in lowered), "")
        sha_match = _SHA.search(window[match.end():] if match else window)
        if sha_match is None:
            # 没有提交号的多半是正文里顺口一提（"ported from the hermes handler"），不算移植记录。
            continue
        path = ""
        for candidate in _PATH.findall(window):
            if candidate != repo and not candidate.startswith(("http", "www.")):
                path = candidate
                break
        return Provenance(
            file=file, repo=repo, sha=sha_match.group(1),
            path=path, line=index + 1, text=line.strip(),
        )
    return None


def scan(repo_root: Path) -> list[Provenance]:
    """扫描仓库里所有带来源标注的源码文件（测试目录除外）。"""
    found: list[Provenance] = []
    for base in SCAN_ROOTS:
        root = repo_root / base
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            if path.resolve() == Path(__file__).resolve():
                continue
            parts = set(path.relative_to(repo_root).parts)
            if parts & {"node_modules", "dist", "__pycache__", "tests", "test"}:
                continue
            try:
                with path.open(encoding="utf-8", errors="replace") as handle:
                    head = "".join(handle.readline() for _ in range(HEADER_LINES))
            except OSError:
                continue
            record = parse_header(head, path.relative_to(repo_root).as_posix())
            if record is not None:
                found.append(record)
    return found


def replace_sha(text: str, record: Provenance, new_sha: str) -> str:
    """把文件头标注里的旧提交号换成新的（只动标注那几行）。"""
    lines = text.splitlines(keepends=True)
    start = record.line - 1
    for index in range(start, min(start + WINDOW, len(lines))):
        if record.sha and record.sha in lines[index]:
            lines[index] = lines[index].replace(record.sha, new_sha, 1)
            break
    return "".join(lines)
