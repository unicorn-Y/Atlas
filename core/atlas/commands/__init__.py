"""Atlas 内置命令包。

目前包含 ``/init``(AGENTS.md 确定性生成器,见 ``atlas.commands.init``)。
"""

from __future__ import annotations

from atlas.commands.init import (
    apply_proposal,
    build_proposal,
    compute_diff,
    register_init_routes,
    scan_workspace,
)

__all__ = [
    "apply_proposal",
    "build_proposal",
    "compute_diff",
    "register_init_routes",
    "scan_workspace",
]
