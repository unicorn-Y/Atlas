"""V4A patch-header helper used by Atlas' LSP pre-write bridge.

Source: NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd (MIT).
This file carries only the header extraction seam used by Atlas.
"""
from __future__ import annotations

import re

_V4A_SINGLE_HEADER_RE = re.compile(r'^(\*\*\*\s*(Update|Add|Delete)\s+File:\s*)(.+)$', re.MULTILINE)
_V4A_MOVE_HEADER_RE = re.compile(r'^(\*\*\*\s*Move\s+File:\s*)(.+?)\s*->\s*(.+)$', re.MULTILINE)


def _collect_v4a_header_paths(patch: str) -> tuple[list[str], list[str], list[str]] | str:
    """Return paths named in V4A headers, rejecting parent traversal."""
    headers = [(m.group(3), m.group(2) in ("Update", "Add"))
               for m in _V4A_SINGLE_HEADER_RE.finditer(patch)]
    headers += [(path, False) for m in _V4A_MOVE_HEADER_RE.finditer(patch)
                for path in (m.group(2), m.group(3))]
    paths: list[str] = []
    content_paths: list[str] = []
    entry_paths: list[str] = []
    for raw, writes_text in headers:
        path = raw.strip()
        if ".." in path.replace("\\", "/").split("/"):
            return f"V4A patch header contains '..' traversal: {path!r}."
        paths.append(path)
        (content_paths if writes_text else entry_paths).append(path)
    return paths, content_paths, entry_paths



