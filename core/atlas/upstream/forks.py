"""三方合并：把上游新版本的改动合进 Atlas 改过的副本。

- :func:`merge_text` 单个文件（借鉴代码）：基准 = 移植时的上游版本，我方 = Atlas 现在的文件，
  对方 = 上游最新版本；用 ``git merge-file``，有冲突就不写入并返回冲突。
- :func:`merge_npm_fork` 整个 npm 包 fork（MemOS）：基准与最新版本都从 npm 下载，
  逐文件三方合并；Atlas 删掉的文件保持删除，上游删掉且 Atlas 没改过的文件跟着删。
"""

from __future__ import annotations

import difflib
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from atlas.upstream import sources

#: npm 包里这些是构建产物，fork 目录里不进 git，合并时跳过（构建步骤会重新生成）。
SKIP_PREFIXES = ("dist/", "node_modules/")


@dataclass
class MergeResult:
    changed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.conflicts


def merge_text(ours: str, base: str, theirs: str) -> tuple[str, bool]:
    """返回 (合并结果, 是否干净)。三者相同部分原样保留。

    Windows 检出的文件是 CRLF、上游是 LF：先统一成 LF 再合并，结果按我方原来的换行写回。
    """
    crlf = "\r\n" in ours
    if crlf or "\r\n" in base or "\r\n" in theirs:
        ours, base, theirs = (text.replace("\r\n", "\n") for text in (ours, base, theirs))
        merged, clean = merge_text(ours, base, theirs)
        return (merged.replace("\n", "\r\n") if crlf else merged), clean
    if ours == base:
        return theirs, True
    if theirs == base or ours == theirs:
        return ours, True
    with tempfile.TemporaryDirectory(prefix="atlas-merge-") as tmp:
        root = Path(tmp)
        paths = []
        for name, text in (("ours", ours), ("base", base), ("theirs", theirs)):
            path = root / name
            path.write_bytes(text.encode("utf-8"))
            paths.append(str(path))
        result = sources.run([*sources.GIT, "merge-file", "-p", "-L", "atlas", "-L", "base",
                              "-L", "upstream", *paths], timeout=60)
        # 0 = 干净；>0 = 冲突块数；<0 = 出错
        return result.stdout, result.returncode == 0


def unified_diff(old: str, new: str, label: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{label}", tofile=f"b/{label}",
    ))


def _npm_pack(spec: str, dest: Path) -> Path:
    result = sources.run([sources.npm_cmd(), "pack", spec, "--pack-destination", str(dest),
                          "--silent"], cwd=dest, timeout=300, check=True)
    name = result.stdout.strip().splitlines()[-1].strip()
    return dest / name


def _extract(archive: Path, dest: Path) -> Path:
    with tarfile.open(archive) as tar:
        tar.extractall(dest, filter="data")
    return dest / "package"


def _norm(data: bytes | None) -> bytes | None:
    """比较时忽略换行差异（Windows 检出是 CRLF，npm 包是 LF）；二进制原样。"""
    if data is None or b"\0" in data:
        return data
    return data.replace(b"\r\n", b"\n")


def _files(root: Path) -> dict[str, Path]:
    return {path.relative_to(root).as_posix(): path for path in root.rglob("*") if path.is_file()}


def download_package(package: str, version: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    return _extract(_npm_pack(f"{package}@{version}", dest), dest / version)


def merge_npm_fork(fork_dir: Path, package: str, base_version: str, new_version: str,
                   work: Path) -> MergeResult:
    """把 ``package`` 从 base_version 到 new_version 的改动合进 ``fork_dir``。

    有冲突时 fork_dir 里只写入了干净的文件；调用方据 ``result.clean`` 决定回退（git）。
    """
    base_root = download_package(package, base_version, work / "base")
    new_root = download_package(package, new_version, work / "new")
    base_files, new_files = _files(base_root), _files(new_root)
    result = MergeResult()
    for rel in sorted(set(base_files) | set(new_files)):
        if rel.startswith(SKIP_PREFIXES):
            continue
        ours_path = fork_dir / rel
        base_bytes = _norm(base_files[rel].read_bytes()) if rel in base_files else None
        new_bytes = _norm(new_files[rel].read_bytes()) if rel in new_files else None
        ours_bytes = _norm(ours_path.read_bytes()) if ours_path.is_file() else None
        if base_bytes == new_bytes:
            continue                          # 上游没动
        if new_bytes is None:                 # 上游删了
            if ours_bytes == base_bytes and ours_bytes is not None:
                ours_path.unlink()
                result.removed.append(rel)
            elif ours_bytes is not None:
                result.conflicts.append(f"{rel}（上游删除，但 Atlas 改过）")
            continue
        if ours_bytes is None:
            if base_bytes is None:            # 上游新增
                ours_path.parent.mkdir(parents=True, exist_ok=True)
                ours_path.write_bytes(new_bytes)
                result.added.append(rel)
            # Atlas 删掉的文件保持删除
            continue
        if ours_bytes == new_bytes:
            continue
        if base_bytes is None or ours_bytes == base_bytes:
            ours_path.write_bytes(new_bytes)
            result.changed.append(rel)
            continue
        try:
            merged, clean = merge_text(ours_bytes.decode("utf-8"), base_bytes.decode("utf-8"),
                                       new_bytes.decode("utf-8"))
        except UnicodeDecodeError:
            result.conflicts.append(f"{rel}（二进制文件两边都改了）")
            continue
        if clean:
            ours_path.write_bytes(merged.encode("utf-8"))
            result.changed.append(rel)
        else:
            result.conflicts.append(rel)
    return result
