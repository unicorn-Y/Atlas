# TASKBOOK-M6：委派上下文准备、运行期召回与结果回流

状态：待后续施工；本文是可执行施工合同，不表示功能已经实现。基线为完成 A0 并推送后的 `ui-redesign`。Atlas 是本项目长期记忆库；外部 Agent 在用户委派任务中拥有完整执行权，任务内容可能包含读写项目文件和使用工具。M6 只连通记忆上下文与委派生命周期，并把外部 Agent 结果交回 Atlas，由 M3 提炼为长期记忆；这是数据流程。

## 目标与数据不变量

派发前可按当前问题向 M5 请求分层记忆摘要及可展开引用；执行中可把补充搜索结果传给 Agent；完成后把子任务最终答复、工具执行摘要和来源消息指针交回父 Atlas 对话。Atlas 主循环将完整结果作为外部执行经历交给 M3。M6 不自行判断结果是否成为事实，也不跳过 M3 提炼。

唯一权威真源仍为 Markdown+Git。Claim 字段 `source_level`、`recorded_at`、`valid_from/to`、`supersedes/retracts`、`source_ref` 写在 Markdown frontmatter/行内。外部 Agent 结果的 `SourceEvent` 只记录其 SessionDB 对话及消息定位，不复制另一份正文。SQLite、全文/向量索引、结果缓存、关联图和 queue 都是可从 Markdown、SessionDB 与当前运行状态重建的派生物。外部 Agent 可能在其执行任务时直接修改工作树文件；M6 既不阻止也不把这种能力改造成记忆写接口。是否被长期记忆吸收由 M3 数据流程负责。

全局固定决策：用户纠正优先级最高；来源等级为 user > tool > model；同等级新记录胜出，旧 Claim 标为 `superseded`。遗忘时删除 Markdown 内容及其派生摘要、索引、向量和技能候选，只保留 W0 已有的内容哈希墓碑。Basic Memory 为 AGPL，仅作行为参考，不复制代码。M9 关联默认只顺显式 `[[链接]]` 一跳，PPR 默认关闭，实际使用证明有收益后再启用。外部 Agent 在用户委派任务中拥有完整执行权；M6 只传递来源指针并将结果回流 M3。

## 上游机制与边界

- `NousResearch/hermes-agent@607a0b0d41e07d903c0b475dd72fb6ac2b37fecc:agent/memory_provider.py:on_delegation` 及生命周期回调（turn start/end、session end、pre-compress、delegation）。借用在委派事件节点附带上下文并在委派结束回收结果的时机；不以其外部存储作为 Atlas 真源。
- `open-multi-agent/open-multi-agent@d4084ef803c4cfb9b241e5545b2ff236ceb2603e:packages/core/src/tool/built-in/delegate.ts:delegate`、`packages/core/src/memory/shared.ts`、`packages/core/src/memory/store.ts` 仅参考可返回子任务摘要和 `result_key` 的数据形状。上游 key 随机、默认内存态，且主调用路径不一定使用 CAS；不要把 key 当持久主键或一致性保证。Atlas 用父会话/子会话和消息 ID 作可重建定位。
- `MemOS/memos@a7367d07e55db61099f7b4e2c1108bc5831a24f3:adapters/hermes/memos_provider/__init__.py:sync_turn/on_turn_start/_turn_end/on_session_end` 展示传输关闭时的有限重连/重试模式，但 transport retry 不证明记忆提炼成功。Atlas 的记忆提交成功必须由 M3/M4 的 Markdown/Git 结果判断。
- `openai/codex@092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`（官方 Codex Rust v0.162.1 拆解快照）中的子会话边界与运行事件仅作为接口/生命周期参考，不复制 Rust 源码。

## Atlas 基线核对与文件所有权

已在 `origin/memory-w2-api` 核对下面的入口；必须在 A0 后的 `ui-redesign` 再确认行号和调用链。`core/atlas/agent/run_phases.py` 是主 Agent 上下文准备/回忆注入的候选接线点；`core/atlas/kernel/subagents.py` 是已有子 Agent 执行器；`core/atlas/agent/results.py` 负责封装回传数据。此 lane 负责接线，不拥有外部 Agent 运行时。

| 文件 | 已核对符号与职责 | 所有权 / 本任务动作 |
|---|---|---|
| `core/atlas/agent/run_phases.py` | `_merge_library_recall`、`_phase_context`、`_schedule_library_write`、`_note_tool_step`、`_phase_finalize` | M6 和 M1/M3 共用。M6 仅所有新 helper/明确预留的委派钩子；先拆分 helper 到新文件，避免改写整份 run loop。`_schedule_library_write` 现有 turn 写入与 M3 对齐。 |
| `core/atlas/kernel/subagents.py` | `SubagentManager.run`、`KernelWorkflowSubagentRunner.run`、`_complete_subtask` | M6 所有委派请求和完成结果桥接；保留原有执行、取消和结果传递语义。 |
| `core/atlas/agent/results.py` | `frame_subagent_result`、`frame_delegate_result_data`、`externalize_tool_output` | M6 所有结果整理/消息指针元数据；不得把完整 transcript 再写入独立记忆数据库。 |
| `core/atlas/memory/library/__init__.py` | `MemoryLibrary.recall/search/schedule_turn/observe_turn` | M5 拥有召回实现；M6 只调用稳定 API，并通过现有 turn pipeline 把子 Agent 结果交回 M3。 |
| `core/atlas/memory/library/queue.py` | `TurnQueue.insert/pending/remove/fail` | M3/M4 所有；M6 不修改队列持久协议，只传递父子会话来源标识。 |
| `core/atlas/engine/session_sync.py` | `read_session_messages/read_session_all_messages/session_message_evidence/latest_session_message_id` | M2 所有；M6 消费来源指针接口，不能复制 SessionDB 原文。 |

不存在 `core/atlas/memory/library/session_sync.py` 和 `models.py`。Library 文件清单为 `__init__.py`、`cleanup.py`、`dream.py`、`embed.py`、`extract.py`、`forget.py`、`hybrid.py`、`index.py`、`queue.py`、`sources.py`、`store.py`。

建议新建 `core/atlas/agent/delegation_memory.py`（**新建**；函数 `prepare_delegation_context`、`capture_delegation_result`、`source_refs_for_result`），以降低对主循环的侵入。只由 M6 所有。该模块不保存长期内容，只拼装 M5 的结果、形成 SessionDB 指针、将回流消息投递给 M3。

## 施工步骤

1. **确认真实委派入口和事件形状。** 在 A0 基线列出所有用户可触发的子 Agent/外部 Agent 入口，确认请求字段、父子 session 标识、执行中事件、取消/失败和完成回调。保持已有工具协议，不筛任务内容。
2. **派发前构造记忆上下文。** 在 `SubagentManager.run` 或其上游调用点生成 `DelegationContext`：父 session ID、子任务 ID、用户原始请求、当前工作目录/项目提示、M5 返回的短摘要、Claim ID 与 `source_ref`。传入子 Agent 时包含“按需可展开引用”的明确提示；内容选择只基于任务相关性及上下文预算，不按 Agent 身份限制。M5 暂时不可用则继续原派发流程，并在 Atlas 运行日志记明本次没有检索结果；不要编造已注入信息。
3. **提供执行中的按需记忆读取。** 将 M5 `search/expand` 以现有工具或 callback 方式暴露到子 Agent 执行上下文。调用只返回当前命中的摘要、Claim 元数据和真实引用；Agent 可以要求打开引用。记录请求与返回的 ref 作为对话运行事件即可，日志不能形成一份独立权威来源账本。
4. **接住完整委派结果。** 在 `KernelWorkflowSubagentRunner.run` 完成和 `_complete_subtask` 之后，收集子会话 ID、最后消息 ID、父任务 ID、开始/结束时间、终态、最终答复和已有工具摘要。将正文留在 SessionDB；`DelegationResult` 只持指针与轻量执行元数据。若现有结果封装为截断摘要，保留其 UI/事件兼容性，同时让原会话仍可通过 SessionDB 打开，不再把截断文本误当完整经历。
5. **把结果交回父 Atlas 与 M3。** 将 M6 result event 送到父 Atlas 当前 run/event stream，并调用既有 M3 turn observation/提炼入口；来源等级初始化为“外部工具观察”或“模型推断”须依实际证据区分，不能因为成功退出就标成用户事实。M3 负责详细经历、会话回顾、原文指针和从经历抽取的原子事实。记录提炼是否排队/完成与 Markdown/Git 写入结果；不能将“子 Agent 返回成功”写成“记忆保存成功”。
6. **重复和异常恢复。** 以稳定的父 session ID + child session ID + terminal message ID 识别同一回传事件；重复终态消息不得重复入队。Atlas 进程重启后可重新从 SessionDB 找到完成子会话并恢复未完成回流。若原文不存在或 bridge 关闭，记录缺失指针，保留任务结果本身；不得复制正文到别的持久数据库来掩盖来源缺失。
7. **多轮和嵌套委派。** 子 Agent 再委派时沿用同一接口，为每次建立 parent-child 关系并给出当前任务需要的摘要；每个结果沿自身 SessionDB 指针回到相应父节点，最终根 Atlas 运行按 M3 正常提炼。关联关系是从 SessionDB/运行事件重建的图，不是独立账本。
8. **迁移旧委派结果。** 对已有 parent/child session metadata 的历史结果构造指针 wrapper；能查到 SessionDB 的记录 parent ID、child ID、终态消息 ID。缺失会话或消息的旧摘要标 `legacy_unattributed`，保留为运行历史但不得伪造可打开原文的链接，也不自动作为 Claim。然后将新回流结果统一走 M3。
9. **日志和观测。** 每次委派记录 `context_requested`、返回 Claim IDs/ref 数量、子会话建立、终态和回流状态、M3 提炼/Markdown Git 状态。只记录正文 hash 或截断诊断时，避免日志复制原对话形成另一份真源。任务执行状态和记忆提炼状态必须分别展示。

## 旧代码删除、保留与数据迁移

- 保留：`SubagentManager` 的调度、取消、并发和生命周期；现有 delegate result framing 和事件格式；主 Agent 的现有记忆 recall；所有外部 Agent 在用户任务中的既有执行能力。
- 替换：只在主 Agent 启动时拼 prompt、没有把任务相关记忆送给子 Agent 的静态路径；只返回截断摘要但丢掉可打开原会话定位的结果路径；把“子任务完成”直接等同于“长期记忆已更新”的状态显示。
- 委派结果无论由子会话回传还是在任务执行中写入工作树，都由现有 Atlas 回合/M3 流程处理可提炼内容。
- 旧数据：不迁移 Agent 的私有记忆为 Atlas 真相。历史结果只有能关联到 SessionDB 时才作为来源指针；否则留作不可回溯的旧运行摘要。它们不会因迁移而自动创建 Claim。
- 不新建持久数据库或 SourceEvent 内容仓库。`delegation_memory.py` 是运行时 adapter；持久状态继续使用 Atlas SessionDB 与 Markdown/Git。

## 最少真实使用验收

在真实 Atlas runtime 中完成至少三次子任务：普通代码/研究类委派一次、需要引用既有 Atlas 记忆的一次、包含失败后重试或取消的一次；其中一次让子 Agent 使用 M5 引用展开，并检查其看到的 claim/source_ref 与源 Markdown/SessionDB 内容一致。观察实际运行事件：子任务上下文准备、child session ID、终态消息 ID、完整结果原文可由 SessionDB 打开、父任务收到结果、M3 收到可处理的来源指针、Markdown/Git 提炼是否完成。确认重启后可恢复一条未完成回流，重复终态不重复入队；M5 不可用时 Agent 仍能完成任务且日志准确显示无记忆结果。

## 依赖、并行与交付

执行顺序为 A0 → M2 → M1/M3/M7 并行；M4 在 M3/M7 后。M5/M9 可在 M2 后并行。M6 依赖 M1 生命周期钩子、M2 稳定 SessionDB/source_ref、M5 search/expand，故在三者可调用后接入。M8 依赖 M3/M4/M7。文件所有权：M6 所有 `delegation_memory.py`（新建）、`kernel/subagents.py` 中委派桥接点、`agent/results.py` 结果指针封装；与 M1/M3 共用 `run_phases.py` 时采用 helper 分文件或约定函数块，禁止互相覆盖对方改动。交付列明基线 SHA、入口清单、调用字段、SessionDB 指针示例、M3 回流/提交日志、三次真实运行结果和残余缺口；本轮只编写任务书，不施工。
