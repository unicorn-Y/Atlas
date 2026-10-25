"""Filesystem helpers for pruning Atlas-owned terminal scratch artifacts."""

from __future__ import annotations

import os
from pathlib import Path


def subtree_touched_since(path: Path, cutoff: float) -> bool:
    """Return whether *path* or any descendant was modified after *cutoff*."""
    try:
        if path.stat().st_mtime >= cutoff:
            return True
    except OSError:
        return False
    if not path.is_dir():
        return False
    for directory, _, filenames in os.walk(path):
        for name in filenames:
            try:
                if (Path(directory) / name).stat().st_mtime >= cutoff:
                    return True
            except OSError:
                continue
    return False
