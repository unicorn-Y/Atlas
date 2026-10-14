"""三方合并：把上游新版本的改动合进 Atlas 改过的副本。

- :func:`merge_text` 单个文件（借鉴代码）：基准 = 移植时的上游版本，我方 = Atlas 现在的文件，
  对方 = 上游最新版本；用 ``git merge-file``，有冲突就不写入并返回冲突。
"""

from __future__ import annotations

import difflib
import tempfile
from pathlib import Path

from atlas.upstream import sources


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
