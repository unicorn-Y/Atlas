"""MemoryLibrary(vcs=False) 不应建 git 仓库，也不应自动提交。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from atlas.memory.library import MemoryLibrary


def _git_commits(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "log", "--oneline"],
        capture_output=True, text=True, check=False,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_vcs_false_creates_no_repo(tmp_path: Path) -> None:
    root = tmp_path / "mem"
    library = MemoryLibrary(root, vcs=False)
    library.ready()

    assert root.is_dir()
    assert not (root / ".git").exists()
    assert _git_commits(root) == []


def test_vcs_false_still_stores_memory(tmp_path: Path) -> None:
    root = tmp_path / "mem"
    library = MemoryLibrary(root, vcs=False)
    library.ready()
    library.add_entry("我.md", "主人的茶是茉莉花茶。")

    assert not (root / ".git").exists()
    hits = library.search("茉莉花茶", limit=3)
    assert any("茉莉花茶" in str(hit.get("text") or "") for hit in hits)


def test_vcs_true_keeps_version_control(tmp_path: Path) -> None:
    root = tmp_path / "mem"
    library = MemoryLibrary(root)
    library.ready()

    assert (root / ".git").exists()
    # ensure() 建立仓库时会打一条初始提交
    assert len(_git_commits(root)) >= 1
