"""Atlas 自动追新（X5 自我进化）——上游跟踪后端。

模块分层（全部确定性工具，绝不做模糊的“自我修改”）：

- :mod:`atlas.evolution.watcher`         E1 上游/更新监视（本地 git 优先，REST 兜底，离线优雅降级）
- :mod:`atlas.evolution.capability_diff` E2 能力差异分类（NEW/BETTER/ALREADY/REGRESSION/IRRELEVANT）
- :mod:`atlas.evolution.parity_mapper`   E3 CORE-PARITY 更新建议（文本提案，从不写 docs/plan）
- :mod:`atlas.evolution.taskbook_draft`  E4 任务书草稿生成（tasks/taskbooks/*.draft.md，仅草稿）
- :mod:`atlas.evolution.branch_flow`     E5 批准 + 隔离分支/worktree（永不自动合并到 main）
- :mod:`atlas.evolution.skill_curator`   E6 技能自学/整理桥（概念移植自 hermes curator）

数据全部落在 ``get_config().db_path.parent / "evolution"`` 之下：
``sources.json``（来源+缓存）、``drafts.json``、``branches.json``、
``candidates/*.json``、``worktrees/``。
"""

from __future__ import annotations

from atlas.evolution.watcher import (
    EvolutionStore,
    UpstreamUnavailable,
    evolution_root,
    list_sources,
    run_check,
)

__all__ = [
    "EvolutionStore",
    "UpstreamUnavailable",
    "evolution_root",
    "list_sources",
    "run_check",
]
