# M1 实施记录

状态：实现待跨分支集成与最小真实使用验收。分支 `mem-m1`，工作树 `D:\atlas-mem-m1`；已 fast-forward 合入 `origin/mem-m2@5ffb1a16e7bdf73733198beefe8d2f581e04a3b0`。

## 实施范围

- `core/atlas/agent/run_phases.py`：轮次完成后从 SessionDB 取用户/assistant 稳定 UID，向 M3 提交 `turn_end` 与 30 分钟后的 `session_idle` 事件；不再把正文传入记忆队列。
- `core/atlas/kernel/loop.py`：记录本次写入 SessionDB 的 UID；在 pre-compress、工具连续失败两次、delegate/subagent 返回与 turn-end 边界接生命周期信号。工具连续失败时以原始 tool 错误调用 M5 lexical 重查；原始错误仍以 `role=tool` 写入 SessionDB，重查块作为带 `source=memory_library` 与触发原因标记的独立临时 system/context 消息注入下一轮模型输入，不混入工具输出。run log 仅记录重查事件、来源 tool_call_id 与命中 refs，不复制错误正文。
- `core/atlas/memory/library/lifecycle.py`：校验无正文事件、幂等入队、基于 Markdown source_ref UID 水位重建缺失队列，并提供同队列单 watcher，唤醒重试、idle 与过期租约。
- `core/atlas/memory/library/queue.py`：SQLite 仅持有 conversation/message UID、event、scope、尝试与 lease 状态；重复事件合并；失败使用 5 秒起、上限 1 小时的指数退避。旧行仅在 SessionDB 时间戳精确且唯一匹配时转为 UID；否则标记 `legacy_unanchored`，清除旧正文副本。

## 冻结的跨分支接口

- M1 导出 `lifecycle.enqueue(queue, event: Mapping[str, Any]) -> int`。事件必需字段为 `conversation_id`, `message_uids`, `event_kind`, `occurred_at`, `scope`；可选 `run_id`, `tool_call_id`。禁止 `content`, `text`, `user_text`, `assistant_text`, `transcript` 字段。返回幂等队列行 ID，字段错误抛 `ValueError`。
- M3 提供 `MemoryLibrary.schedule_lifecycle(event: dict[str, Any], *, model_mgr: Any = None) -> None`：调用 enqueue 并唤醒 `_drain`；成功（含 no-output）用 `remove(id)`，异常用 `fail(id,error)`。保留 `schedule_turn` 兼容入口，但不得再写入正文。
- M1 提供 `lifecycle.start_watcher(queue, callback)` 和 `lifecycle.rebuild_uncovered_uids(...)`；M3 需在 library 启动时启动 watcher，并以 M2 SessionDB UID 顺序和 Markdown `source_ref` UID 调用重建函数。
- M1 的 `run_phases._phase_context` 在每个非 worker run 启动时扫描当前 conversation 的 SessionDB UID，并通过 M3 `processed_source_uids(conversation_id)` 比较 source_ref 后重建未覆盖尾部；当前用户消息若已入库则留给该轮 `turn_end`，避免响应进行中提炼。此接线只扫描活跃 conversation，不是全库启动扫描。
- M5 提供模块级 `atlas.memory.library.recall.recheck_memory(error_text, *, limit=3, library=None) -> dict`；kernel 在连续两次工具失败时 lazy-load，使用返回的 `block`。

## 验证记录

- `python -m py_compile` 覆盖四个 M1 Python 文件：通过。
- `git diff --check`：通过。
- `core/tests/test_kernel_memory_recheck.py`：通过；验证模型输入中的 tool 消息只含原始错误、Atlas 重查块在独立标记 system 消息，且临时 SessionDB 中原文为 `role=tool` 并逐字保留。
- `core/tests/test_memory_library_w1.py -k 'not legacy_queue_schema'`：6 passed。旧 `test_w1_legacy_queue_schema_migrates_without_dropping_rows` 未运行；它要求继续保留队列正文，与 M1 的“正文只在 SessionDB”约束相冲突，需由独立验收更新判断。
- M3 的 `schedule_lifecycle` 与 `processed_source_uids`、M5 `recall.py` 在并行分支；尚未合入本分支，因此目前不能验证完整 adapter/真实模型路径。

## 最小真实使用验收

以下项目在 M3/M5/M7/M9 集成后执行；当前均未声称通过：

- [ ] 真实 Atlas 含工具调用会话：日志 UID → 队列状态 → M2/M3 条目 `source_ref` 精确打开 SessionDB 原文。
- [ ] 轮次结束后、提炼前重启：队列或 Markdown/SessionDB 重建后只产出一次；无事实结果按 no-output 移除任务。
- [ ] 重复通知幂等；模型不可用时保留并退避，模型恢复后完成。
- [ ] 压缩前已引用水位可追踪；压缩后不伪造不可读原文。
- [ ] 外部 Agent 工具结果落入 SessionDB 后由普通 M3 路径处理；连续工具失败触发 M5 lexical 重查。

边界：恢复扫描只覆盖本轮启动的 conversation；当前证据只覆盖编译、diff 检查和既有 W1 非冲突测试；队列/SessionDB/模型的端到端真实使用仍待跨分支集成验收。
