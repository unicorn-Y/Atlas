"""Remove forgotten text from every reachable Git object in a memory library."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

REDACTED = "（已按你的要求忘掉）"


def _rmtree(path: Path) -> None:
    def writable_remove(function, target, _exc_info):
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if path.exists():
        shutil.rmtree(path, onerror=writable_remove)


def _git(root: Path, *args: str, git_dir: Path | None = None) -> bytes:
    command = ["git"]
    if git_dir is not None:
        command.extend([f"--git-dir={git_dir}", f"--work-tree={root}"])
    command.extend(args)
    result = subprocess.run(command, cwd=root, capture_output=True, timeout=120, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or
                           result.stdout.decode("utf-8", errors="replace"))
    return result.stdout


def _rewrite_stream(data: bytes, needles: list[str]) -> tuple[bytes, int]:
    out = bytearray()
    changed_blocks = 0
    offset = 0
    while offset < len(data):
        end = data.find(b"\n", offset)
        if end < 0:
            out.extend(data[offset:])
            break
        line = data[offset:end + 1]
        match = re.fullmatch(rb"data (\d+)\n", line)
        offset = end + 1
        if not match:
            out.extend(line)
            continue
        size = int(match.group(1))
        block = data[offset:offset + size]
        if len(block) != size:
            raise ValueError("fast-export data 块长度不完整")
        text = block.decode("utf-8")
        updated = text
        for needle in needles:
            updated = updated.replace(needle, REDACTED)
        encoded = updated.encode("utf-8")
        if encoded != block:
            changed_blocks += 1
        out.extend(f"data {len(encoded)}\n".encode("ascii"))
        out.extend(encoded)
        offset += size
    return bytes(out), changed_blocks


def _log_has_needles(root: Path, needles: list[str]) -> bool:
    for args in (("log", "--all", "-p"), ("log", "--all", "--format=%B")):
        output = _git(root, *args)
        if any(n.encode("utf-8") in output for n in needles):
            return True
    return False


def purge_history(store: Any, needles: list[str]) -> dict[str, Any]:
    root = Path(store.root)
    clean = sorted({item.strip() for item in needles if item and len(item.strip()) >= 2},
                   key=len, reverse=True)
    if not clean or not store._git_available() or not (root / ".git").exists():
        return {"rewritten": False, "commits": 0}
    if not _log_has_needles(root, clean):
        return {"rewritten": False, "commits": 0}

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    backup = root / f".git-before-forget-{timestamp}"
    temp = root / ".git-rewrite-tmp"
    old_git = root / ".git-old"
    if temp.exists() or old_git.exists():
        raise RuntimeError("改写历史失败，已保持原样：发现未完成的历史改写目录")
    original_branch = _git(root, "symbolic-ref", "--short", "HEAD").decode("utf-8").strip()
    original_count = int(_git(root, "rev-list", "--all", "--count").strip())
    swapped = False
    restored = False
    try:
        shutil.copytree(root / ".git", backup)
        exported = _git(root, "fast-export", "--all", "--signed-tags=strip", "--reencode=yes")
        rewritten, changed_blocks = _rewrite_stream(exported, clean)
        if not changed_blocks:
            _rmtree(backup)
            return {"rewritten": False, "commits": 0}
        temp.mkdir()
        _git(root, "init", "-q", str(temp))
        _git(root, "config", "core.autocrlf", "false", git_dir=temp / ".git")
        proc = subprocess.run(["git", f"--git-dir={temp / '.git'}", "fast-import", "--force", "--quiet"],
                              cwd=root, input=rewritten, capture_output=True, timeout=120, check=False)
        if proc.returncode:
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip())
        _git(root, "symbolic-ref", "HEAD", f"refs/heads/{original_branch}", git_dir=temp / ".git")
        new_count = int(_git(root, "rev-list", "--all", "--count", git_dir=temp / ".git").strip())
        if new_count != original_count:
            raise ValueError(f"提交数不一致：{original_count} != {new_count}")
        for args in (("log", "--all", "-p"), ("log", "--all", "--format=%B")):
            output = _git(root, *args, git_dir=temp / ".git")
            if any(n.encode("utf-8") in output for n in clean):
                raise ValueError("新历史仍包含待忘记文本")
        paths = _git(root, "ls-tree", "-r", "--name-only", "-z", "HEAD",
                     git_dir=temp / ".git").split(b"\0")
        for raw_path in filter(None, paths):
            rel = raw_path.decode("utf-8", errors="surrogateescape")
            expected = _git(root, "cat-file", "blob", f"HEAD:{rel}", git_dir=temp / ".git")
            current = (root / rel).read_bytes()
            if expected != current:
                raise ValueError(f"工作区文件与新历史不一致：{rel}")

        os.replace(root / ".git", old_git)
        try:
            os.replace(temp / ".git", root / ".git")
            swapped = True
            _git(root, "reset", "--mixed", "HEAD")
        except OSError:
            os.replace(old_git, root / ".git")
            raise
        _rmtree(old_git)
        _rmtree(temp)
        _git(root, "reflog", "expire", "--expire=now", "--all")
        _git(root, "gc", "--prune=now", "-q")
        _rmtree(backup)
        return {"rewritten": True, "commits": original_count, "backup_removed": True}
    except Exception as exc:
        if swapped and backup.exists():
            failed = root / ".git-rewrite-failed"
            try:
                if (root / ".git").exists():
                    os.replace(root / ".git", failed)
                shutil.copytree(backup, root / ".git")
                _rmtree(failed)
                restored = True
            except OSError:
                pass
        if temp.exists():
            _rmtree(temp)
        if old_git.exists() and not (root / ".git").exists():
            os.replace(old_git, root / ".git")
            restored = True
        if backup.exists() and (not swapped or restored):
            _rmtree(backup)
        raise RuntimeError(f"改写历史失败，已保持原样：{exc}") from exc

