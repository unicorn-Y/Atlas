"""Discover and merge project instruction files for the active workspace.

The directory walk and AGENTS fallback behavior follow Codex's project-doc
loader (``core/src/agents_md.rs``). Atlas-specific instruction filenames are
included alongside ``AGENTS.md`` so existing workspace conventions continue
to work.
"""

from __future__ import annotations

import hashlib
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


def project_instruction_root(workspace: str | Path) -> Path:
    """Resolve the same repository boundary used by initial instruction loading."""
    cwd = Path(workspace).resolve()
    return _nearest_project_root(cwd)


def _source_key(path: str | Path) -> str:
    try:
        return str(Path(path).expanduser().resolve(strict=False)).casefold()
    except (OSError, RuntimeError, ValueError):
        return str(path).replace("\\", "/").casefold()


def snapshot_project_instructions(rules: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for rule in rules:
        path = str(rule.get("path") or "").strip()
        if not path:
            continue
        content = str(rule.get("content") or "")
        snapshot[_source_key(path)] = {
            **rule,
            "path": path,
            "content": content,
            "revision": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
        }
    return snapshot


def refresh_project_instructions(
    workspace: str | Path,
    touched_paths: Iterable[str | Path],
    *,
    project_root: str | Path,
    previous: dict[str, dict[str, Any]],
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Reconcile trusted instruction sources after a successful local file tool.

    Existing sources are compared only when they govern a touched directory.
    Missing files are reported as removed only for ``FileNotFoundError``;
    permission/read errors leave the last known source intact.
    """
    if str(workspace).strip().casefold().startswith("ssh://"):
        return [], previous
    root = Path(project_root).resolve()
    next_snapshot = dict(previous)
    updates: dict[tuple[str, str], dict[str, Any]] = {}
    seen_scopes: set[Path] = set()

    for raw in touched_paths:
        try:
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = Path(workspace) / candidate
            resolved = candidate.resolve(strict=False)
            if not _inside(resolved, root):
                continue
            scope = resolved if resolved.is_dir() else resolved.parent
        except (OSError, RuntimeError, ValueError):
            continue
        if scope in seen_scopes:
            continue
        seen_scopes.add(scope)

        current_rules = load_project_instructions(
            scope, trusted=True, project_root=root, max_bytes=max_bytes,
        )
        current = snapshot_project_instructions(current_rules)
        previous_scope = {
            key: item for key, item in next_snapshot.items()
            if _inside(scope, Path(str(item.get("path") or "")).parent.resolve(strict=False))
        }

        for key, item in current.items():
            old = next_snapshot.get(key)
            if old is None or old.get("revision") != item.get("revision"):
                state = "added" if old is None else "changed"
                change_id = hashlib.sha256(
                    f"{key}\0{state}\0{item.get('revision', '')}".encode("utf-8"),
                ).hexdigest()[:16]
                update = {**item, "state": state, "change_id": change_id}
                updates[(key, state)] = update
            next_snapshot[key] = item

        for key, old in previous_scope.items():
            if key in current:
                continue
            old_path = Path(str(old.get("path") or ""))
            try:
                old_path.stat()
            except FileNotFoundError:
                state = "removed"
            except OSError:
                # An inaccessible source is not proof of deletion.
                continue
            else:
                try:
                    resolved_old = old_path.resolve(strict=True)
                except (OSError, RuntimeError, ValueError):
                    continue
                if not _inside(resolved_old, root):
                    state = "deactivated"
                elif old_path.name == "AGENTS.md" and (old_path.parent / "AGENTS.override.md").is_file():
                    state = "overridden"
                else:
                    # The file still exists but was not loaded (for example a
                    # read/size-budget failure); preserve its last known state.
                    continue
            updates[(key, state)] = {
                "path": str(old.get("path") or old_path),
                "state": state,
                "revision": old.get("revision", ""),
                "change_id": hashlib.sha256(
                    f"{key}\0{state}\0{old.get('revision', '')}".encode("utf-8"),
                ).hexdigest()[:16],
            }
            next_snapshot.pop(key, None)

    return list(updates.values()), next_snapshot


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

