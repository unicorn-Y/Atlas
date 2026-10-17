"""Raw-layer importers: copy external session logs into ``raw/<source>`` unchanged.

Only archives; distilling raw → curated is ``distill.py`` (not built yet). Re-running is
safe: files already archived with the same size and mtime are skipped.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class ImportResult:
    source: str
    copied: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _mirror(source: str, src_root: Path, dest_root: Path, pattern: str) -> ImportResult:
    result = ImportResult(source)
    if not src_root.exists():
        result.errors.append(f"not found: {src_root}")
        return result
    for src in src_root.rglob(pattern):
        if not src.is_file():
            continue
        dest = dest_root / src.relative_to(src_root)
        try:
            st = src.stat()
            if dest.exists() and dest.stat().st_size == st.st_size and int(dest.stat().st_mtime) == int(st.st_mtime):
                result.skipped += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            result.copied += 1
        except OSError as exc:
            result.errors.append(f"{src}: {exc}")
    return result


def import_claude_code(dest: Path, path: Path | None) -> ImportResult:
    """Claude Code transcripts: ``~/.claude/projects/<project>/<session>.jsonl`` (+ memory/*.md)."""
    return _mirror("claude-code", path or Path.home() / ".claude" / "projects", dest, "*.*")


def import_codex(dest: Path, path: Path | None) -> ImportResult:
    """Codex rollouts: ``$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl``."""
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return _mirror("codex", path or home / "sessions", dest, "*.jsonl")


def import_atlas(dest: Path, path: Path | None) -> ImportResult:
    """Atlas's own sessions — needs an exporter from state.db first; pass a folder of exports for now."""
    if path is None:
        result = ImportResult("atlas")
        result.errors.append("Atlas 自身会话导出还没做，先传 path=导出目录")
        return result
    return _mirror("atlas", path, dest, "*.*")


IMPORTERS: dict[str, Callable[[Path, Path | None], ImportResult]] = {
    "claude-code": import_claude_code,
    "codex": import_codex,
    "atlas": import_atlas,
}
