# TASKBOOK-M1：会话生命周期采集与提炼触发

状态：待施工；本文件是未来实现合同，本轮只修改调研文档。
基线：先完成 TASKBOOK-A0，并以 A0 合并后的 `ui-redesign` 为唯一起点。路径审计基准为 `D:\atlas-mem-w2-api` 的 `origin/memory-w2-api@aa14c3173392d0fc60ec3e401e4495a2d3357cb7`；施工开始时先确认 A0 合并后的对应文件仍存在并复核函数签名。

## 目标与不可变约束

把对话开始、轮次结束、压缩前、会话结束及子 Agent 返回等生命周期接入统一的记忆处理流程。生命周期层只记事件种类、发生时间和指向 SessionDB 的消息 UID；不得再复制一份对话正文到新数据库或独立来源账本。记忆权威是可人工编辑的 Markdown + git 记忆库。SQLite 队列/状态、索引、摘要缓存都只是可从 Markdown 和 SessionDB 重建的派生物。外部 Agent 在用户委派任务中拥有完整执行权；其结果正常进入 Atlas 会话，再作为普通 Atlas 输入交给 M3 提炼。
## 全局固定规则（相关模块按职责消费）

- Basic Memory 为 AGPL；只作行为参考，不复制代码。
- 冲突顺序固定：用户纠正永远最高；不同来源等级为用户陈述 > 工具观察 > 模型推断；同等级按新旧取较新，旧内容标为 `superseded` 并留在历史。
- 遗忘沿派生链清除 Markdown 内容、索引、摘要与技能候选，只保留内容哈希墓碑防止重新导入；沿用 W0 已有哈希墓碑机制。
- M9 联想默认只沿 Markdown `[[链接]]` 多看一跳，PPR 默认关闭；只有实际使用证明有收益后才考虑启用 PPR。

## 上游依据及要移植的部分

1. `NousResearch/hermes-agent@607a0b0d41e07d903c0b475dd72fb6ac2b37fecc:agent/memory_provider.py::{MemoryProvider.on_turn_start,on_session_end,on_session_switch,on_pre_compress,on_delegation}` 与 `agent/memory_manager.py::{MemoryManager.sync_all,on_turn_start,on_session_end,on_session_switch,on_pre_compress,on_delegation}`：移植回调时序与生命周期边界，不搬 provider 数据库实现。
2. `openclaw/openclaw@59cb44796b0f1f0daa0e37af8b1495abb45d9bc1:extensions/active-memory/index.ts`：参考 `before_prompt_build` 与 `agent_end` 的调用位置，移植“轮前召回、轮后只排队”的职责切分，不移植其存储协议。
3. `openai/codex@092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`（官方仓库 `rust-v0.162.1` 快照）：`codex-rs/memories/write/src/phase1.rs::{run,claim_startup_jobs,run_jobs}` 只借鉴 lease、重试/退避和 no-output 的队列语义；`templates/memories/stage_one_system.md` 仅供 M3 移植提示词，本任务不改写它，也不移植 Rust 代码。

## Atlas 路径核对与逐文件所有权

以下现有路径已在 `origin/memory-w2-api@aa14c317` 打开核对；不存在 `core/atlas/memory/library/session_sync.py`。会话同步位于 `core/atlas/engine/session_sync.py`。W2 library 目录当前文件为 `__init__.py, cleanup.py, dream.py, embed.py, extract.py, forget.py, hybrid.py, index.py, queue.py, sources.py, store.py`。

| 文件 | 状态 / M1 文件所有权 | 计划修改函数或边界 |
|---|---|---|
| `core/atlas/agent/run_phases.py` | 现有；M1 独占本任务对此文件的改动 | `_schedule_library_write`（当前约 467–492 行，含 `library.schedule_turn(...)`）与 `execute_run/_phase_finalize` 的轮次结束接线；补齐最终 assistant/tool 消息的 UID 指针和结果状态，不带正文副本。施工前重定位函数行号。 |
| `core/atlas/kernel/loop.py` | 现有；M1 独占本任务对此文件的改动 | `AtlasKernel.run`开始/结束及 SessionDB 写入后的生命周期触发；只传 `conversation_id/message_uid/event_kind/time`。 |
| `core/atlas/memory/library/lifecycle.py` | **新建**；M1 独占 | 归一化生命周期信号，落入现有可重建队列；同一会话/消息/事件种类可重复触发但不重复消费；模型暂不可用则保留队列任务并按有界退避重试。不得持有原文副本。 |
| `core/atlas/memory/library/queue.py` | 现有；由 M1 独占 lifecycle queue 改动 | `TurnQueue.insert/pending/remove/fail`；保留队列作为派生执行状态，任务至少包含指针和处理状态。SQLite 丢失时依据 SessionDB 与 Markdown 可重建未完成任务。 |
| `core/atlas/engine/session_sync.py` | 现有；M1 不改，由 M2 独占 | 调用 M2 提供的 `read_session_all_messages` / 稳定 UID 接口；不可另造同路径模块。 |
| `core/atlas/memory/library/__init__.py` | 现有；M1 不改，由 M3 独占提炼入口 | lifecycle adapter 通过已有公开入口触发，不与 M3 的 `_drain/observe_turn/_extract_full` 改动冲突。 |

## 施工步骤

1. 在 A0 基线上重读上述目标文件和 `engine/session_sync.py`，记录实际调用点；确认原始 transcript 仍只在 Hermes SessionDB（`DATA_ROOT/engine/state.db`）持有。函数若已改名，更新本任务书的落点并保持职责边界。
2. 定义内部事件形状：`conversation_id, message_uid, event_kind, occurred_at, run_id?, tool_call_id?`。事件不带 `content`。SessionDB UID 无法解析时保留会话级指针并标明精度未知，不按时间猜一个消息。
3. 新建 `lifecycle.py`，将 kernel/run hook 归一成可重试队列任务；覆盖 turn-end、pre-compress、session-end、外部 Agent 返回。事件幂等只保证队列重复触发不造成重复处理，不宣称跨模型的事实全局幂等。
4. 调整 run/kernel 接线：SessionDB 写入后传稳定 UID。pre-compress 提交截至压缩水位的消息引用；压缩后不能伪造已删除正文，原文可用性由 SessionDB 能否打开决定。Agent delegation 完成消息直接进入 Atlas transcript，M3 后续抽取。
5. 为模型/队列进程重启设计短退避重试及最大退避；no-output 是有效处理结果，不是失败：只在确实无可提炼内容时完成该水位；异常、超时和无法解析保留可重试状态。队列可由 SessionDB 最近消息 UID 水位与 Markdown 中的 `source_ref` 重建。
6. 处理旧队列：读取既有 `TurnQueue` 行并转换为 UID 指针；只在行内原 session/timestamp 可唯一对应现存 message 时补 UID。无法唯一确认时留 `legacy_unanchored` 任务供 M3 以完整会话复核，不制造精确引用。Markdown 仍是最终记忆，队列不是导入源。
7. 删除/替换：移除原来在不同 turn hook 中重复 enqueue/直接抽取的重复调用，保留现有记忆页 API、人工编辑与 `MemoryLibrary.schedule_turn` 兼容入口；不删 SessionDB transcript、不把 assistant/tool 输出单独持久化为另一份来源库。
8. 用真实隔离对话走通普通轮、工具调用、压缩、会话结束、子 Agent 返回；检查审计日志中的 event_kind、conversation_id、message_uid、队列尝试次数、no-output/成功/失败状态及重启恢复结果。日志只记引用和状态，不记录重复的整段对话正文。

## 旧数据与兼容

现有 Markdown 页/经历原样保留；本任务不改其事实语义。SessionDB 是唯一会话原文，现有可检索 transcript 不复制到 memory DB。SQLite `TurnQueue` 可删除后重建；在迁移期间兼容旧的 session/timestamp 格式并仅作宽泛会话引用。过渡结束后，只保留一个到 M3 的提炼调用路径，避免旧 hook 与新 hook 双写。

## 最小真实使用验收

- 连续完成含 tool call 的真实会话，SessionDB 中消息 UID 能从生命周期日志追到处理状态，再从 M2/M3 记忆条目的 `source_ref` 打开原文。
- 故意在一轮完成后、提炼前重启 Atlas：队列可恢复或从 SessionDB/Markdown 重建，最终经历没有重复入库。
- 同一事件重复通知两次只产生一个待处理项；模拟模型不可用后队列保留，模型恢复后可完成；无可抽取事实的闲聊以 no-output 正常结束。
- 外部 Agent 返回一段有工具结果、文件名、错误信息的结果后，内容出现在 SessionDB transcript，并由普通 M3 路径处理。

## 依赖、并行与停止边界

依赖 A0 和 M2 稳定消息 UID/读取接口。M1 可与 M3、M7 并行：M1 只拥有 `run_phases.py`、`kernel/loop.py`、新 `lifecycle.py` 与 M1 对 `queue.py` 的生命周期改动；M3 拥有 `extract.py`、`library/__init__.py`；M7 依 VERDICT 文件清单分配不同文件。M4 等 M3 的事件/提炼输出稳定后再做。M6 依赖 M1/M2/M5。此任务只实现生命周期接线与可重建队列，不做检索重构、事实冲突裁决或技能训练。
