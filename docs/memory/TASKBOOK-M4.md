# TASKBOOK-M4：可验证整合与透明记忆文件

状态：待后续授权施工。本文件为施工合同，不表示已实现。

## 来源与目标

参考 Codex pinned `openai/codex@092d3acd6bec3e3a14bdc7e7a2810ab628ab759d:codex-rs/memories/write/src/phase2.rs:run/agent::handle`、`workspace.rs:memory_workspace_diff/reset_memory_workspace_baseline/validate_consolidation_artifacts_for_version` 的 lease/diff/retry/校验；参考 OpenClaw MIT `extensions/memory-core/src/dreaming-consolidation.ts:validateConsolidationPlan/applyMemoryConsolidationPlan` 和 `short-term-promotion-apply.ts` current-file hash guard。Basic Memory core 为 AGPL-3.0-or-later，不安排复制。

Atlas 目标 `core/atlas/memory/library/dream.py:run_dream/_write_project/_old_owner_lines`、`store.py:MemoryStore.write/commit`。替换模型直接整页覆盖路径，改为模型 proposal + host validator + 原子 Markdown patch。索引是可重建投影。

## 契约与数据迁移

按 source event/version 选增量输入并设 lease/backoff。plan 列 action、claim IDs、old text/hash、lineage、new text。应用前重读文件，核 generation/hash、旧内容唯一匹配和来源完整性；冲突则保护用户文件并入 retry/conflict。无 diff 路径和有 diff 路径均校验产物；有 diff 还要求 agent 完成、lease 有效、baseline reset/commit 成功。仅 Markdown/Git 原子提交后推进 watermark。旧条目来源不明标 `legacy_unattributed`；迁移前备份，失败可回滚。

## 最小真实使用验收

临时库演练新增、同义合并、事实取代、用户手改冲突、模型失败和进程中断重启；检查 plan/校验/应用/watermark 日志，可从最后成功版本恢复；手改不得覆盖；失败项可重试或明确 quarantine。

## 依赖与并行

依赖 M2、M3、M7 contract。独占 `dream.py`、`store.py` 写协议；其他任务不得共改。
