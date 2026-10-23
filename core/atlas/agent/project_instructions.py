"""Discover and merge project instruction files for the active workspace.

The directory walk and AGENTS fallback behavior follow Codex's project-doc
loader (``core/src/agents_md.rs``). Atlas-specific instruction filenames are
included alongside ``AGENTS.md`` so existing workspace conventions continue
to work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


DEFAULT_MAX_BYTES = 32_768
_ATLAS_RULE_FILES = (
    Path("CLAUDE.md"),
    Path(".claude") / "CLAUDE.md",
    Path("CLAUDE.local.md"),
    Path(".claude") / "AGENTS.md",
    Path(".atlas") / "NOTES.md",
    Path(".atlas") / "rules.md",
)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _nearest_project_root(cwd: Path) -> Path:
    """Return the closest git worktree/repository root, or cwd if none exists."""
    for directory in (cwd, *cwd.parents):
        try:
            if (directory / ".git").exists():
                return directory
        except OSError:
            continue
    return cwd


def _directories(root: Path, cwd: Path) -> Iterable[Path]:
    """Yield each ancestor exactly once, from root through cwd."""
    chain: list[Path] = []
    current = cwd
    while True:
        chain.append(current)
        if current == root:
            break
        parent = current.parent
        if parent == current or not _inside(parent, root):
            return
        current = parent
    yield from reversed(chain)


def load_project_instructions(
    workspace: str | Path,
    *,
    trusted: bool = True,
    project_root: str | Path | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> list[dict[str, Any]]:
    """Load project instructions from the repository root down to ``workspace``.

    The nearest ``.git`` ancestor defines the default project boundary. At each
    level, Atlas-supported instruction files are merged, while
    ``AGENTS.override.md`` replaces ``AGENTS.md`` at that level. More local
    directories are appended later, so their instructions have the final word.
    Real paths are checked against the project root and duplicate targets are
    read only once. Unreadable or concurrently removed files are skipped.

    Return dictionaries compatible with ``request.workspace_rules``. ``bytes``
    is the number of source bytes included, and ``truncated`` reports whether
    the file exceeded its share of the total content budget.
    """
    if not trusted or max_bytes <= 0:
        return []
    try:
        cwd = Path(workspace).resolve()
        root = Path(project_root).resolve() if project_root is not None else _nearest_project_root(cwd)
    except (OSError, RuntimeError, ValueError):
        return []
    if not _inside(cwd, root):
        return []

    sections: list[dict[str, Any]] = []
    seen: set[Path] = set()
    remaining = max_bytes

    for directory in _directories(root, cwd):
        if remaining <= 0:
            break
        agent_override = directory / "AGENTS.override.md"
        try:
            agent_file = agent_override if agent_override.is_file() else directory / "AGENTS.md"
        except OSError:
            agent_file = directory / "AGENTS.md"
        candidates = [directory / relative for relative in _ATLAS_RULE_FILES]
        candidates.append(agent_file)

        for candidate in candidates:
            if remaining <= 0:
                break
            try:
                if not candidate.is_file():
                    continue
                resolved = candidate.resolve(strict=True)
                if not _inside(resolved, root) or resolved in seen:
                    continue
                with candidate.open("rb") as stream:
                    raw = stream.read(remaining + 1)
            except (OSError, RuntimeError, ValueError):
                continue

            truncated = len(raw) > remaining
            if truncated:
                raw = raw[:remaining]
            content = raw.decode("utf-8-sig", errors="replace").strip()
            if not content:
                continue
            sections.append({
                "path": str(candidate),
                "content": content,
                "bytes": len(raw),
                "truncated": truncated,
            })
            remaining -= len(raw)
            seen.add(resolved)

    return sections

