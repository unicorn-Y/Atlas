# 去重问题总账

状态：AWAITING_GPT6_REVIEW。基线 ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f；当前源码根 D:\Atlas。代码确认不等于真实进程复现。W1是唯一已授权施工范围，其余均仅记录。

## 统计与去重规则

共 21 个不同问题（P1 10、P2 11）；没有本轮确认的P0。W3的队列/错误卡分别对应W1修复的两个前端环节，保留独立症状、不重复计算为其他模块发现。W1重试与fallback合并为一个策略问题。W2-003仅为候选分支集成风险；W5-008为已披露功能缺口；W5-009待验证，不列为已复现故障。优先级表示处理建议，不代表已获施工授权。

| ID | 来源 | 优先级 | 领域 | 处置 |
|---|---|---|---|---|
| ATL-001 | W1-001 | P1 | 模型故障重试/锁定所选模型 | W1修复，待独立验收 |
| ATL-002 | W2-001 | P1 | run cancellation / long-running tools | 仅审查，待授权 |
| ATL-003 | W2-002 | P2 | truthful completion / post-edit verification | 仅审查，待授权 |
| ATL-004 | W2-003 | P2 | 独有分支集成风险 / 工具流去重 | 仅审查，待授权 |
| ATL-005 | W3-001 | P1 | 会话队列 / 运行状态 | W1修复，待独立验收 |
| ATL-006 | W3-002 | P1 | 模型故障 / 错误详情 UI | W1修复，待独立验收 |
| ATL-007 | W4-001 | P2 | SSH workspace / LSP | 仅审查，待授权 |
| ATL-008 | W5-001 | P1 | Dream / checkpoint / recovery | 仅审查，待授权 |
| ATL-009 | W5-002 | P1 | Dream / manual edit / concurrent writes | 仅审查，待授权 |
| ATL-010 | W5-003 | P1 | queue / failed recovery | 仅审查，待授权 |
| ATL-011 | W5-004 | P2 | queue / process restart | 仅审查，待授权 |
| ATL-012 | W5-005 | P2 | index / search pagination and filters | 仅审查，待授权 |
| ATL-013 | W5-006 | P2 | timeline / cursor pagination | 仅审查，待授权 |
| ATL-014 | W5-007 | P1 | provenance / source authenticity | 仅审查，待授权 |
| ATL-015 | W5-008 | P2 | forget / source propagation | 仅审查，待授权 |
| ATL-016 | W5-009 | P2 | forget / Git history rewrite / concurrent recovery | 仅审查，待授权 |
| ATL-017 | W6-001 | P1 | 启动/调试面 | 仅审查，待授权 |
| ATL-018 | W6-002 | P1 | 更新/回滚 | 仅审查，待授权 |
| ATL-019 | W6-003 | P2 | 依赖pin/Python启动 | 仅审查，待授权 |
| ATL-020 | W6-004 | P2 | 源码/构建产物一致性 | 仅审查，待授权 |
| ATL-021 | ROOT-001 | P2 | 语音/资源生命周期 | 仅审查，待授权 |

## 逐项证据与最小处理建议

### ATL-001 — 模型故障重试/锁定所选模型（P1 / W1-001）

- **症状**：基线允许超出两次的重试、fallback candidates及辅助调用默认/备用模型循环，不能保证故障后仍使用用户选择的模型。
- **真实运行影响边界**：当前源码主调用及辅助调用可达；真实会话未注入故障。
- **证据/函数**：ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f core/atlas/kernel/model_call.py:559-575,613 complete_stream（候选/重试循环）；core/atlas/agent/run_phases.py:315-317 模型配置；core/atlas/models/router.py:374-379 complete_for（硬编码备用模型）；准确修复差异及测试见06。
- **结论类别**：代码确认；W1隔离修复验证
- **最小处理**：所选模型固定；初次+最多两次短暂故障重试；permanent/partial delta立即终止；不重放工具或整个run。
- **复用方向**：复用现有ModelCallError/调用和事件链；无新框架。
- **复杂度 / 执行者**：M / W1
- **施工状态**：已在独立W1分支修复，测试与SHA见06；未部署到D:\\Atlas。

### ATL-002 — run cancellation / long-running tools（P1 / W2-001）

- **症状**：A stop request sets the run cancel event, but AtlasKernel waits for an in-flight tool batch using only the tool task and event queue. If a tool is still awaiting work and emits no event, the API cannot observe cancellation until that tool returns; long or stuck calls may keep the run alive after the user requests stop.
- **真实运行影响边界**：主执行者确认 Atlas 进程源码根为 D:\Atlas；实际加载字节未知。若加载 ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f，代码路径受影响。主目录 dirty/untracked 的 deep_research overlay 同样缺少 run cancel_event 传递。
- **证据/函数**：[{"branch":"ui-redesign","full_sha":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/kernel/loop.py","lines":"1496-1505","function":"AtlasKernel.run"},{"branch":"ui-redesign","full_sha":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/kernel/loop.py","lines":"2394-2423","function":"AtlasKernel._dispatch"},{"branch":"ui-redesign","full_sha":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/api/run_drive.py","lines":"166,2268-2278,2707-2710","function":"stop command / check_pause_cancel / _execute_run event consumer"},{"branch":"ui-redesign host overlay (untracked file, not in commit)","full_sha":"0b1ba4114e25643369c95bfac85d37563788444f plus uncommitted overlay","path":"core/atlas/research/tool.py","lines":"57-80","function":"run_deep_research_tool"},{"branch":"codex/desktop-repair-20261013","full_sha":"b177a6a94a7f1a9adb2891955a37cd4d4490054d","path":"core/atlas/kernel/loop.py","lines":"1435-1443","function":"AtlasKernel.run tool batch wait"}]
- **结论类别**：代码确认；隔离运行复现未执行；进程源码根已确认 D:\Atlas，加载字节待核实；desktop-repair 分支亦未修复
- **最小处理**：Race the kernel tool batch against the run cancel event. Signal cancellable child operations and stop launching new calls; await and record settled results, preserve partial output, then finish as cancelled/interrupted. Never restart a cancelled side-effecting call.
- **复用方向**：Reuse the existing model-stream cancel_waiter in kernel/loop.py and workflow cancellation watcher in kernel/workflow_tool.py.
- **复杂度 / 执行者**：M / W2
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-003 — truthful completion / post-edit verification（P2 / W2-002）

- **症状**：The current kernel path can finish after the model emits a final answer following code-changing tools without a mechanical prompt to run a relevant check. Verification is left to model behavior, so unverified edits can end in a normal completed turn.
- **真实运行影响边界**：主执行者确认 Atlas 进程源码根为 D:\Atlas；实际加载字节未知。若加载 ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f，kernel 结束路径受影响；desktop-repair 默认 AtlasKernel 路径仍未接入 nudge。
- **证据/函数**：[{"branch":"ui-redesign","full_sha":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/engine/hermes_runtime.py","lines":"864-867,967,985","function":"HermesRuntime.run_turn"},{"branch":"ui-redesign","full_sha":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/kernel/loop.py","lines":"1593-1604","function":"AtlasKernel.run"},{"branch":"ui-redesign","full_sha":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/agent/run_phases.py","lines":"929-949","function":"_phase_finalize"},{"branch":"codex/desktop-repair-20261013","full_sha":"b177a6a94a7f1a9adb2891955a37cd4d4490054d","path":"core/atlas/agent/run_phases.py","lines":"1467-1474","function":"_pump_events / verification nudge"}]
- **结论类别**：代码确认；本机复现未执行；desktop-repair 的默认 AtlasKernel 路径仍有缺口
- **最小处理**：Wire the existing changed-path and successful-check evidence into kernel finalization and emit the existing bounded verification nudge when code changes remain unverified. Keep run completion as a turn-terminal status unless goal success is separately defined.
- **复用方向**：Reuse agent/verification_stop.py, changed-path tracking in agent/tool_node.py, and the existing soft nudge in agent/run_phases.py.
- **复杂度 / 执行者**：S-M / W2
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-004 — 独有分支集成风险 / 工具流去重（P2 / W2-003）

- **症状**：codex/desktop-repair-20261013 移除了 kernel 对已从事件队列转发的 tool_result call id 的去重记录；tool_node 仍将 tool_result 写入事件队列，而 batch 聚合结束时 kernel 又为 settled result 发出 tool_result，可能向 UI 或流消费者重复报告同一工具调用结果。该分支也移除了 tool_preparing 增量进度事件，长参数流期间不再显示准备进度。
- **真实运行影响边界**：仅该分支候选集成风险，非 ui-redesign 基线缺陷；尚未合入当前运行源码。
- **证据/函数**：[{"branch":"codex/desktop-repair-20261013","full_sha":"b177a6a94a7f1a9adb2891955a37cd4d4490054d","path":"core/atlas/kernel/loop.py","lines":"1410-1452","function":"AtlasKernel.run / consume_tool_results 与 tool event queue"},{"branch":"codex/desktop-repair-20261013","full_sha":"b177a6a94a7f1a9adb2891955a37cd4d4490054d","path":"core/atlas/agent/tool_node.py","lines":"203-208,315-319,1409-1419","function":"execute_tools_node tool_result event emission"},{"branch":"ui-redesign","full_sha":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/kernel/loop.py","lines":"519-524,1115-1120,1483-1516","function":"AtlasKernel.run existing forwarded result de-dup and streaming progress"}]
- **结论类别**：分支差异确认；重复 UI 事件影响由调用链推断，未做 UI/流消费者复现；集成前需保留基线去重/进度语义或证明替代实现等价
- **最小处理**：合并候选改动时恢复基线的 forwarded_results/tool result 去重及 tool_preparing 进度语义；若分支有新事件路由方案，需确保每个 call_id 只产生一个最终结果事件，并补定向的本地隔离验证。
- **复用方向**：复用 ui-redesign 基线的 forwarded_results、tool_started_at 及参数增量节流实现。
- **复杂度 / 执行者**：S / W2
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-005 — 会话队列 / 运行状态（P1 / W3-001）

- **症状**：run.failed 与 run.completed、run.cancelled 共用终态处理并调用 dispatchQueue；失败没有设置 queuePaused。存在排队消息时，失败终止可能直接取出并执行下一条消息，无法按用户要求在模型故障后暂停队列。
- **真实运行影响边界**：父进程与监听端口核实实际源码根为 D:\Atlas、HEAD为ui-redesign 0b1ba4114e25643369c95bfac85d37563788444f；useAtlasStore.ts在该dirty工作区未修改。进程内加载文件精确字节仍待核实。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"frontend/src/renderer/store/useAtlasStore.ts","line":670,"function":"applyRuntimeEvent/store runtime event terminal handler"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"frontend/src/renderer/store/useAtlasStore.ts","line":1161,"function":"dispatchQueue"}]
- **结论类别**：代码确认
- **最小处理**：在 run.failed 分支调用 dispatchQueue 前设置 conversation queuePaused=true，并保留队列项；仅由用户显式 resumeQueue 或重试动作恢复。
- **复用方向**：复用现有 queuePaused、resumeQueue 和 ConversationQueuePanel 行为，不新增队列抽象。
- **复杂度 / 执行者**：S / W1
- **施工状态**：已在独立W1分支修复，测试与SHA见06；未部署到D:\\Atlas。

### ATL-006 — 模型故障 / 错误详情 UI（P1 / W3-002）

- **症状**：run.failed 到时间线卡片的投影仅取 data.detail 或 data.code；错误卡只显示该字符串，没有显示可用的 provider/model/status/request_id/attempts/retryability 结构化信息。独立的手动重试按钮已存在。
- **真实运行影响边界**：父进程与监听端口核实实际源码根为 D:\Atlas、HEAD为ui-redesign 0b1ba4114e25643369c95bfac85d37563788444f；timeline.ts有dirty编辑但仅新增deep_research工具标签（该差异行116），不影响run.failed投影。进程启动前后磁盘编辑时间与进程内加载字节仍待核实；若事件未提供结构化字段，亦涉及W1事件契约。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"frontend/src/renderer/components/timeline.ts","line":713,"function":"buildTimeline run.failed case"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"frontend/src/renderer/components/ConversationActivity.tsx","line":93,"function":"ConversationActivity failed item renderer"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"frontend/src/renderer/App.tsx","line":1253,"function":"retryNote manual retry affordance"}]
- **结论类别**：代码确认
- **最小处理**：让 run.failed event-to-timeline mapping保留已脱敏的结构化错误字段，并在错误卡展示分类、model/provider、HTTP状态、原始说明、request ID、尝试次数及手动重试状态；与W1事件字段契约对齐。
- **复用方向**：复用现有 run.failed event、错误卡和 store.retryRun；不增加新错误框架。
- **复杂度 / 执行者**：S / W1
- **施工状态**：已在独立W1分支修复，测试与SHA见06；未部署到D:\\Atlas。

### ATL-007 — SSH workspace / LSP（P2 / W4-001）

- **症状**：SSH workspace 的 native file write 路径明确跳过 Atlas 的 LSP pre/post edit reporting；远端编辑因此没有本地 workspace 相同的 Atlas post-edit diagnostics。
- **真实运行影响边界**：仅影响选中的 workspace 为 ssh:// 且通过 engine tool registry native file write 执行的运行；本轮未建立 SSH 会话或实测。
- **证据/函数**：{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/engine/tool_registry.py","line":470,"function":"register_tools"}
- **结论类别**：代码确认（静态；运行未验证）
- **最小处理**：若产品要求 SSH 编辑也有诊断，在 SSH 主机运行或复用 language server 并桥接 LSP transport；否则在 SSH 工具结果/界面明确标注远端编辑不产生 Atlas LSP diagnostics。当前只记录缺口，不改实现。
- **复用方向**：先复用 Atlas 现有 LSP seam：core/atlas/engine/lsp_bridge.py 与 core/atlas/engine/tool_registry.py:129-230；协议参考 Microsoft LSP 仓库 protocol.md（GitHub 读取已核路径存在）：https://github.com/microsoft/language-server-protocol/blob/main/protocol.md。
- **复杂度 / 执行者**：L / W4
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-008 — Dream / checkpoint / recovery（P1 / W5-001）

- **症状**：run_dream 扫描 checkpoint 之后的经历，并在全部生成完成后把全局 checkpoint 推到运行时 now。若在扫描完成、checkpoint 写入前到达的经历具有早于 now 的 entry.at（例如重启后处理迟到队列），下次 _episode_groups 会因 entry.at <= checkpoint 永久跳过它；全局时间水位也无法表达逐 source 的处理状态。
- **真实运行影响边界**：ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f 源码符合该条件；是否发生于当前实际运行进程未核实。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/dream.py","line":28,"function":"_episode_groups"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/dream.py","line":154,"function":"run_dream"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/tests/test_memory_library_w2.py","line":274,"function":"test_dream_checkpoint_advances_only_after_all_projects_succeed (does not cover late/concurrent sources)"}]
- **结论类别**：代码确认
- **最小处理**：以 entry/source ID + extractor version 保存已成功处理游标；只有该 source 的结果持久化后才推进它的状态。至少复核扫描期间新增的 source，避免以运行时间覆盖尚未看见的条目。
- **复用方向**：V4.1 M01 的 ReMe Extract/Integrate/Finish 思路；继续用 Atlas 现有 SQLite/Git，不引入 ReMe service。
- **复杂度 / 执行者**：M / W5
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-009 — Dream / manual edit / concurrent writes（P1 / W5-002）

- **症状**：_write_project 在模型调用前读取 existing 页面并等待 LLM；run_dream 最后只用 store.lock 包住写入，却按旧 existing 保护用户编辑行并整页覆盖。若用户在 LLM 等待期间编辑/新增该项目条目，旧快照不含新行，最终写入会删除该编辑。
- **真实运行影响边界**：ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f 源码存在该竞态；并发发生频率未测。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/dream.py","line":65,"function":"_write_project"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/dream.py","line":105,"function":"_write_project (await model completion)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/dream.py","line":167,"function":"run_dream (lock then stale-snapshot overwrite)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/__init__.py","line":431,"function":"edit_entry"}]
- **结论类别**：代码确认
- **最小处理**：生成后在 lock 内重新读取最新页面并合并；如果需要 LLM 重整完整页面，则对输入页面 hash 做 CAS，检测冲突时保留用户最新版本并重试生成。
- **复用方向**：复用 MemoryStore.write 的原子 rename 与既有 SRC_EDITED 来源标识；不加通用并发框架。
- **复杂度 / 执行者**：M / W5
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-010 — queue / failed recovery（P1 / W5-003）

- **症状**：queue.pending 只返回 attempts < 3 的行；fail 将 attempts 加一，第三次后行永久不再进入消费列表。接口只有 failed_count，没有 reset/retry 操作，故经历结构化提炼可永久停留在失败行，只有已有日记阶段可读。
- **真实运行影响边界**：ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f 源码确认；真实失败行数量未读（未访问数据）。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/queue.py","line":60,"function":"TurnQueue.pending"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/queue.py","line":73,"function":"TurnQueue.failed_count"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/queue.py","line":77,"function":"TurnQueue.fail"}]
- **结论类别**：代码确认
- **最小处理**：保留失败详情并暴露显式恢复一次的用户入口；对可重试错误施加退避与有界次数，终态错误允许手动重置 attempts。
- **复用方向**：沿用现有 SQLite pending 表及 pending_failed 计数，不引入新 broker。
- **复杂度 / 执行者**：S / W5
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-011 — queue / process restart（P2 / W5-004）

- **症状**：队列行能跨 Library 对象/重启持久化，但消费 drain 仅由 observe_turn 写入新行后 create_task；应用 startup 钩子启动的是 Dream scheduler，没有扫描既有 queue。因此没有下一次会话轮次时，重启前的 pending 工作不会主动继续。
- **真实运行影响边界**：ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f 源码确认；空闲启动期间实际延迟未观测。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/__init__.py","line":298,"function":"MemoryLibrary.observe_turn (insert and schedule drain)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/__init__.py","line":309,"function":"MemoryLibrary._drain"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/api/memory_library_router.py","line":333,"function":"start_dream_scheduler (startup hook)"}]
- **结论类别**：代码确认
- **最小处理**：在已存在的应用启动/lifespan 中用当前 model_mgr 对 pending 行启动一次有界 drain；无模型则保留并记录 deferred 状态。
- **复用方向**：复用当前 queue.pending/_drain 与已有 lifecycle；不另建常驻队列服务。
- **复杂度 / 执行者**：S / W5
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-012 — index / search pagination and filters（P2 / W5-005）

- **症状**：/api/memlib/search 先请求 relevance 排序前 1000 条，再由 API 对 src/from/to/project 过滤。符合过滤器的结果若落在索引候选窗口 1000 以外，items 与 total 都看不到；offset 只作用于已过滤的该窗口。
- **真实运行影响边界**：ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f 源码确认；数据量及真实漏结果未测。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/api/memory_library_router.py","line":112,"function":"search (fixed 1000 candidate limit)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/api/memory_library_router.py","line":114,"function":"search (post-query filters)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/api/memory_library_router.py","line":128,"function":"search (offset/limit page)"}]
- **结论类别**：代码确认
- **最小处理**：把 source/date/project predicates 下推到 Index 查询；若做不到，迭代取候选直到收齐一页并且 total 完整。
- **复用方向**：复用 MemoryIndex 的 keyword/vector/hybrid 排名及 API 参数，不替换检索算法。
- **复杂度 / 执行者**：M / W5
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-013 — timeline / cursor pagination（P2 / W5-006）

- **症状**：timeline 按 at 倒序排序，下一页只返回 page[-1].at；下一次请求排除所有 entry.at >= before。若多条经历共享该秒级 timestamp（常见于连续写入），游标处其余相同时间经历全部被跳过。
- **真实运行影响边界**：ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f 源码确认；同 timestamp 实例未测试。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/api/memory_library_router.py","line":148,"function":"timeline"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/api/memory_library_router.py","line":157,"function":"timeline (before comparison)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/api/memory_library_router.py","line":162,"function":"timeline (sort)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/api/memory_library_router.py","line":186,"function":"timeline (timestamp-only next cursor)"}]
- **结论类别**：代码确认
- **最小处理**：用稳定复合游标 `(at,id)`，排序也按 `(at,id)`；before 谓词严格按同一排序键推进。
- **复用方向**：沿用现有 endpoint 与稳定 Entry.id，不需迁移存储格式。
- **复杂度 / 执行者**：S / W5
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-014 — provenance / source authenticity（P1 / W5-007）

- **症状**：open_ref 接受 `session@timestamp`，在该 SessionDB 中选时间差最近的 user 消息；无有效时间时取最后一条 user。它不能保证入口 ref 指向经历实际来源 message，无法按 exact UID 区分同时间消息。mem-integrate 的 SourceRef 实现不在本基线。
- **真实运行影响边界**：ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f 源码确认；错误打开的真实引用未抽查（不读真实会话）。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/sources.py","line":25,"function":"open_ref"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/sources.py","line":61,"function":"open_ref (nearest timestamp selection)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/sources.py","line":153,"function":"search_raw (timestamp ref construction)"},{"branch":"mem-integrate","fullSHA":"4046764fbabda187a4b329c830a4b9cab9631951","path":"core/atlas/memory/library/source_ref.py","line":1,"function":"SourceRef (file absent from current baseline)"}]
- **结论类别**：代码确认
- **最小处理**：沿用 SessionDB 的 message_uid；新引用 exact 打开且缺失时报 missing，不回退猜测；旧 timestamp 引用标 approximate。
- **复用方向**：直接复用 `mem-m2` SourceRef contract 与 SessionDB UID；不生成第二种 transcript ID。
- **复杂度 / 执行者**：M / W5
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-015 — forget / source propagation（P2 / W5-008）

- **症状**：forget_entry 删除派生 Markdown、日记匹配文本和记忆 Git 可达历史，但明确把 Atlas 原始会话库列为 not_covered；同一来源仍可由显式 kind=raw 的 /api/memlib/search 查询，之后也可重新进入整理流程。当前 UI/API 有披露边界，因此属于忘记语义尚未覆盖 canonical source 的功能缺口。
- **真实运行影响边界**：ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f 源码确认；没有读取或查询真实 source 内容。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/__init__.py","line":467,"function":"forget_entry"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/__init__.py","line":483,"function":"forget_entry (history rewrite only for memory store)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/sources.py","line":153,"function":"search_raw"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/api/memory_library_router.py","line":108,"function":"search (raw kind opt-in)"}]
- **结论类别**：功能缺口
- **最小处理**：先保持 UI 明确说明原会话未删除；如产品将 forget 定义为源级删除，则以 exact SourceRef 对 canonical SessionDB 传播删除/失效，并令 raw search/后续提炼尊重 tombstone。
- **复用方向**：复用 existing tombstone hashes + M2 SourceRef；仅实现 source invalidation，不复制 transcript。
- **复杂度 / 执行者**：M / W5
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-016 — forget / Git history rewrite / concurrent recovery（P2 / W5-009）

- **症状**：forget 的 Git rewrite 先备份、导出、重写、检查 commit 数/残留 needle/工作树，再替换 .git，并对已捕获异常尝试还原；但互斥仅为一个 MemoryStore 实例的 threading.RLock。两个实例或另一进程若共享同一 memory root，writer 可在校验和 .git swap 之间修改工作树或 refs，现有快照校验并不形成跨进程事务。恢复失败时异常被吞并且保留备份供人工处理，真实并发/失败注入未验证。
- **真实运行影响边界**：当前默认单实例路径有锁；只有同 root 多实例/多进程 writer 才受影响，部署形态未验证。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/store.py","line":228,"function":"MemoryStore.__init__ (instance-local RLock)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/forget.py","line":97,"function":"purge_history (rewrite transaction begins)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/forget.py","line":119,"function":"purge_history (verify before swap)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/forget.py","line":128,"function":"purge_history (.git swap)"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/atlas/memory/library/forget.py","line":142,"function":"purge_history (rollback)"}]
- **结论类别**：待验证
- **最小处理**：只有在确认存在多 writer 时，用 memory-root 级 OS file lock 包住 forget 与修改事务；做两条最小故障注入，分别覆盖 swap 前失败和 swap 后 restore 失败，并保留人工恢复路径。
- **复用方向**：沿用已有 backup、commit count、needle/tree 校验与 rollback；不重写忘记算法。
- **复杂度 / 执行者**：M / W5
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-017 — 启动/调试面（P1 / W6-001）

- **症状**：源码启动默认启用CDP 9335并允许任意Origin，拥有本机端口访问的进程可连接并控制/检查桌面页面会话。代码确认，实际Electron PID持有9335；未验证跨主机可达性。
- **真实运行影响边界**：源码路径可达；本轮未触发该场景，不等于已观察实际故障。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"scripts/atlas-update.mjs","line":188,"function":"launch"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"scripts/atlas-update.mjs","line":192,"function":"launch"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"scripts/atlas-update.mjs","line":195,"function":"launch"}]
- **结论类别**：代码确认
- **最小处理**：默认关闭CDP，仅通过明确的opt-in启用；调试启用时限制回环绑定及可信来源。
- **复用方向**：无需引入外部实现；Electron/Chromium现有调试参数即可。
- **复杂度 / 执行者**：S / W6
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-018 — 更新/回滚（P1 / W6-002）

- **症状**：源代码fast-forward与依赖安装后原地构建；失败只记录错误，但relaunch/launch-only仍会重启，未恢复旧源码、依赖或dist，可能启动半更新版本。源码确认，未故障注入。
- **真实运行影响边界**：源码路径可达；本轮未触发该场景，不等于已观察实际故障。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"scripts/atlas-update.mjs","line":74,"function":"pull"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"scripts/atlas-update.mjs","line":136,"function":"rebuild"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"scripts/atlas-update.mjs","line":258,"function":"failure/relaunch"}]
- **结论类别**：代码确认
- **最小处理**：新版本在隔离目录完成安装/构建和入口校验后再切换；失败时保留旧版本并停止自动重启失败版本。
- **复用方向**：可复用现有build-stamp与updater状态文件，增加暂存/切换步骤。
- **复杂度 / 执行者**：M / W6
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-019 — 依赖pin/Python启动（P2 / W6-003）

- **症状**：新建core虚拟环境仅pip install -e core，主要依赖为>=范围；首次build stamp缺失时updater的requirements.lock变更条件不触发，首次安装未应用完整锁文件。
- **真实运行影响边界**：源码路径可达；本轮未触发该场景，不等于已观察实际故障。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"start-atlas.bat","line":19,"function":"venv bootstrap"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"start-atlas.bat","line":23,"function":"venv bootstrap"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"scripts/atlas-update.mjs","line":150,"function":"rebuild"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"core/pyproject.toml","line":10,"function":"project dependencies"}]
- **结论类别**：代码确认
- **最小处理**：首次创建或重建venv时安装requirements.lock，并纳入完成状态记录。
- **复用方向**：复用现有core/requirements.lock，无需新锁定工具。
- **复杂度 / 执行者**：S / W6
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-020 — 源码/构建产物一致性（P2 / W6-004）

- **症状**：launch-only只比较build stamp和HEAD；重建健康判定只查renderer index与preload，没有校验Electron主进程bundle。stamp相同且主bundle缺失时会跳过重建并尝试启动。
- **真实运行影响边界**：源码路径可达；本轮未触发该场景，不等于已观察实际故障。
- **证据/函数**：[{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"scripts/atlas-update.mjs","line":209,"function":"launch-only fast path"},{"branch":"ui-redesign","fullSHA":"0b1ba4114e25643369c95bfac85d37563788444f","path":"scripts/atlas-update.mjs","line":169,"function":"rebuild artifact probe"}]
- **结论类别**：代码确认
- **最小处理**：stamp快路径和rebuild探测都检查dist-electron/main/electron.js及所有启动必需bundle。
- **复用方向**：沿用现有文件存在性探测逻辑。
- **复杂度 / 执行者**：S / W6
- **施工状态**：未施工；不得将本建议视为批准。

### ATL-021 — 语音/资源生命周期（P2 / ROOT-001）

- **症状**：语音界面先关闭、getUserMedia后返回时，返回的麦克风流及AudioContext绕过effect清理
- **真实运行影响边界**：当前分支代码受影响；本机触发未复现
- **证据/函数**：ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f frontend/src/renderer/components/VoiceOverlay.tsx:153-159,179-188 VoiceOverlay useEffect
- **结论类别**：代码确认
- **最小处理**：effect卸载标记；晚返回流立即stop tracks，挂载时才创建AudioContext
- **复用方向**：现有React effect cleanup与MediaStreamTrack.stop
- **复杂度 / 执行者**：S / 主执行者
- **施工状态**：未施工；不得将本建议视为批准。

## 已撤回与未重复记账

Android/tap/swipe/type并非缺失：kernel tools和loop已桥接mobile_simulator；未做真实设备验收。F2-D只有文档新增，WIP C3的TeamBoard等不归到F2-D。配置编辑接口返回编辑内容本身不直接认定泄露，OriginGuard与实际访问条件需结合判断。SSH缺口仅指远程编辑诊断，不等于SSH工具整体不可用。没有将历史报告中的故障直接当作当前复现。

模块完整调用链、搜索边界及独有分支说明见[W2](modules/W2-KERNEL.md)、[W3](modules/W3-FRONTEND.md)、[W4](modules/W4-TOOLS.md)、[W5](modules/W5-MEMORY.md)、[W6](modules/W6-STARTUP.md)、[补充](modules/ROOT-ADDITIONAL.md)。

