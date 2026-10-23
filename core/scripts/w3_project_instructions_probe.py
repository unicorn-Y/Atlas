"""Focused probe for root-to-workspace project instruction discovery."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from atlas.agent.project_instructions import load_project_instructions


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-w3-instructions-") as temp:
        base = Path(temp)
        root = base / "repo"
        cwd = root / "packages" / "app"
        (root / ".git").mkdir(parents=True)
        cwd.mkdir(parents=True)

        _write(root / "CLAUDE.md", "root-claude")
        _write(root / "AGENTS.md", "root-agents")
        _write(cwd / "AGENTS.md", "must-be-replaced")
        _write(cwd / "AGENTS.override.md", "local-override")
        _write(cwd / ".atlas" / "rules.md", "local-atlas-rule")

        sections = load_project_instructions(cwd)
        contents = [section["content"] for section in sections]
        assert contents == ["root-claude", "root-agents", "local-atlas-rule", "local-override"], contents
        assert sum(section["content"] == "root-agents" for section in sections) == 1
        assert all(set(section) == {"path", "content", "bytes", "truncated"} for section in sections)

        # A root workspace is visited once, and an explicit boundary rejects
        # workspaces whose resolved paths are outside it.
        root_only = load_project_instructions(root)
        assert sum(section["content"] == "root-agents" for section in root_only) == 1
        assert load_project_instructions(cwd, project_root=base / "elsewhere") == []
        assert load_project_instructions(cwd, trusted=False) == []

        # The shared byte budget clips later documents and reports that fact.
        _write(root / "CLAUDE.md", "0123456789ABCDEFGHIJ")
        limited = load_project_instructions(root, max_bytes=8)
        assert sum(section["bytes"] for section in limited) <= 8
        assert limited[0]["truncated"] is True
        assert limited[0]["content"] == "01234567"

        # A transient unreadable file is skipped while later rule files load.
        _write(root / "CLAUDE.md", "unreadable")
        original_open = Path.open

        def guarded_open(path: Path, *args, **kwargs):
            if path == root / "CLAUDE.md":
                raise PermissionError("probe unreadable instruction")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            after_error = load_project_instructions(root)
        assert all(section["content"] != "unreadable" for section in after_error)
        assert any(section["content"] == "root-agents" for section in after_error)

        # A symlink that resolves outside the project root is never read.
        outside = base / "outside.md"
        _write(outside, "outside-secret-marker")
        link = root / "CLAUDE.local.md"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pass  # Symlink creation can be disabled on Windows without elevation.
        else:
            escaped = load_project_instructions(root)
            assert all("outside-secret-marker" not in section["content"] for section in escaped)

    print("W3 project instruction probe passed")


if __name__ == "__main__":
    main()
