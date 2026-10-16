# TASKBOOK-M1：记忆生命周期钩子

状态：待后续授权施工。本文件为施工合同，不表示已实现。

## 来源与目标

考考 Hermes `memory_provider.py` / `memory_manager.py` 的 turn、pre-compress、session-end、delegation callbacks；对照 Claude Code `PreCompact/SessionEnd/SubagentStop` 和 OpenClaw `extensions/active-memory/index.ts:before_prompt_build/agent_end`。MemOS Hermes adapter 只作接线考考，transport reconnect 不证明记忆持久化成功。

Atlas 目标：`core/atlas/memory/library/__init__.py:MemoryLibrary._drain`、`run_phases.py` 零散 recall/write 接线及新增 `core/atlas/memory/library/lifecycle.py`。收拢重复触发路径；hook 只创建 M2 event/job，由 M3/M4 消费。

## 契约与数据迁移

每个事件携带 `event_id, conversation_id, source_pointer, event_kind, occurred_at, payload_ref, source_level`。轮前只读召回；轮后采集 user/assistant/tool events；压缩前提交摘要指针；session/subagent 结束封口来源范围并入队。重复通知由 M2 幂等键消解。无模型/bridge 时 pending 保留并可重试。旧 session 可建立兼容 wrapper；无法恢复 UID 的标 `legacy_unanchored`，不得伪造精确引用。

## 最小真实使用验收

隔离真实会话执行普通对话、工具调用、压缩/会话结束及子 Agent 返回；日志应有稳定 event ID，重复 hook 不重复入队；模型不可用后 pending 可恢复；引用可打开原文。不能只凭 hook 调用或 health 200 判通过。

## 依赖与并行

依赖 M2 event contract。可与 M3/M7 并行，限定只改 lifecycle adapter/接线文件。M6 消费本模块接口。
