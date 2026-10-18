# Atlas main 与 Codex CLI 0.163.0 —— 机制级逐项差距

对比基准：Atlas main **aa6196f550098cc46081dc6db2c376cb87ddffa5**；Codex **83086188ae0614bd882818ff1aa23f3194962012** (rust-v0.163.0)。只审已读取的 Atlas 源码，不能把“未检索到”冒充全仓缺失。下述分类是**静态对照意见**，未做 Atlas/Codex 同环境动态基准测试。

分类定义：**已实装**=源码存在可追踪执行逻辑（不自动意味效果等价）；**部分机制**=关键调用能运行但关键状态/语义不等价；**入口/接线待核**=函数/界面存在但未走完整调用链；**明确未支持**=源码显式 NotImplemented；**未发现**=本次检查范围内找不到实现，需全仓检索或运行确认；**实现风险**=找到真实代码显示潜在差异，不能直接称缺陷。

| ID | Codex 实际机制 | Atlas main 源码核对 | 分级、影响与下一步精确锚点 |
|---|---|---|---|
| 001 | run_turn 及 sampling loop，有 stream retry、preempt、致命错误区分 | core/atlas/agent/run_phases.py:146-924 有 phased run；engine/hermes_runtime.py:828-1571 持有 Hermes 真正引擎；run_phases.py:683-697 显式避免 failed-turn 静默成功 | **已实装 / 部分机制**：不是简单无循环；将 Hermes 真实异常、重试次数、模型失败、取消与终态编码逐分支对照 |
| 002/003 | ToolCallRuntime、Orchestrator 统一调度取消、执行环境/审批/重试 | agent/tool_node.py:58-1192 真执行工具，engine/tool_registry.py:290-558 真注册与工具策略，agent/retry_utils.py:11-15 backoff | **部分机制**：同一工具 request 的排队/取消/底层执行/结果记账是否原子一致未完成；下步按 tool_call_id 追 Atlas tool.started→tool.completed→persist |
| 004/019 | 类型化工具注册、来源区分、可按需检索并动态刷新元数据 | tools/mcp_client.py:171-568 真 MCP 生命周期；engine/tool_registry.py:290-558 真工具映射；agent/injection_budget.py:30-112 做注入预算 | **部分机制 / Tool Search 未发现等价**：Atlas 有目录，尚未观察等价 BM25 按需加载及 runtime 缓存无效化；锚点 engine/tool_registry.py、tools/mcp_client.py、agent/tool_catalog.py |
| 005—010 | 独立 Code Mode Host → gRPC over pipes → V8 cell → 工具回调 Core | agent/__init__.py:672 execute_code 入口存在；tools/node_runtime.py:19-119 主要是 Node 可用性检测。没有发现匹配独立 V8/gRPC cell provider 的实现 | **实现结构未发现 / 入口待核**：不能把执行一段代码同义于长生命周期 JS cell Host。优先对照 execute_code 实体、tools/local_execution.py、tools/x2、external process；如确需该架构再移植 |
| 007/008 | Host sessions/cells/pending invocations/seen IDs，独立配额、gate 与双向委派 | Atlas 的 RuntimeManager 与 ToolNode 各管理其生命周期；runtime/external_process.py 仅处理 CLI 子进程输出 | **部分机制 / 等价协议未发现**：嵌套工具回调异步跨进程的准确一次记录与取消，无证据满足；若引入 Code Mode 再建立 session/cell/call ID |
| 011/014 | 真正的 root→child thread、fork 裁剪历史、rollout 恢复 | agent/__init__.py:512-652 的 _run_atlas_subtask 创建 child conversation，执行真实 worker turn，Stop Hook 可继续；同函数 finally **delete_session + delete_conversation** | **已能委派，但关键生命周期不等价**：默认子任务执行完会清除 child 记录，不能当可直接长期恢复的子线程；先明确目标：持久子 Agent 与临时 worker 是否分型。锚点 agent/__init__.py、runtime/backend_host.py、agent/definitions.py |
| 012 | MAv2 驻留 LRU、idle unload、需要时由 durable state reload | HermesRuntime:177,205-351 有 per-conversation cache 与闲置 sweep；但 child _run_atlas_subtask 完成后删除会话 | **部分机制**：parent session cache ≠ 子树进程驻留；需检查 child runtime 生命周期，禁止把闲置清理上升为强制任务失败 |
| 013/015/016 | 子 Agent 离线 mailbox、watch、消息投递、Activity wait、终态向父通知 | agent/__init__.py:512-654 有 worker 进度和结果合并；engine/steer_dispatch.py:41-119 有 steer queue/yield；在已读核心中未见相同 child offline mailbox+residency | **部分机制 / 未发现完整组合**：长任务挂起、未驻留 Agent 的消息与恢复可能丢失。检查 runtime/backend_host.py、persistent_agents、engine/hermes_runtime.py 后再定缺失范围 |
| 017 | 模型可见 world-state baseline/diff 与 history revision | run_phases.py:390-683 构造上下文；engine/hermes_runtime.py:1214 system_prompt_suffix；agent/injection_budget.py:30-112 有长度裁剪；models/router.py:114-340 真模型路由 | **部分机制**：不能声称 Atlas 每次全部无脑注入；但尚无与 Codex 等价跨 turn state baseline 和 revision 的跟踪证据，优先做变更差分与旧窗口失效关联 |
| 018 | 异步推测压缩，条件 feature + RemoteCompaction V2、历史代际/模型/认证代次校验 | engine/hermes_runtime.py:627-789 有真实 compact_session 与压缩模型设置；模型调用统计也在 engine/hermes_runtime.py:936-980 | **已实装压缩 / 推测机制未发现**：不同于普通 compact。尤其要区分完成的无效后台候选使用量是否计费，避免重复请求。 |
| 020/021 | thread fork + rollout checkpoint window lineage，daemon 中断后回填输入 attribution | engine/session_sync.py:517-618 capture/restore/delete/rewind/fork/list branch；agent/checkpoints.py:24-208 有 scoped file snapshot，manifest 最后写、备份/恢复 | **已实装但两类 checkpoint 不同**：Atlas 文件回滚和 conversation fork 是真实存在的；不能据此推出活跃 Turn/工具可 daemon crash 后自动恢复。需依 run/event DB 审查真实重启路径 |
| 022 | start vs steer 事前验证/提交、活动 Turn 输入注入 | engine/steer_dispatch.py:41-119 有 steer、redirect、send_now；hermes_runtime.py:1455-1525 有 watcher | **部分机制且有接线待核**：steer_dispatch.py:89-119 注释给出 server.py 的替换接线说明，不可仅依注释认定当前已接线；需读实际 server route/运行 trace |
| 023/024 | CLI/TUI 的 Agent Picker/history cells、执行中命令过滤、会话队列 | Atlas frontend/src/renderer 中存在 UI 与状态管理；api/runtime.py:17-212 有 WS RunState，engine/tool_registry.py 工具事件 | **部分机制 / TUI 非同产品**：Atlas 桌面/网页不能用终端 /commands 数量作评价；应对标状态表达语义和转态一致性，再检验 UI |
| 025 | 统一 span/tool dispatch+handler timing、Call-ID 和回溯 trace | core/atlas/api/runtime.py:17-212 RunState/RPC persistence；runtime/external_agents.py:60-98 normalize 外部事件 | **部分机制**：流式 event≠完整 span lineage。检查 WebSocket 断线重放、tool ID 对齐、session 持久化和重试合并 |
| 026 | App-server + daemon 恢复，分层协议 | runtime/backends.py:17-187 真 ACP adapter，external_process.py:24-153 子进程 adapter。external_process.py:133-134 的 resume **直接 raise NotImplementedError** | **明确未支持：generic process resume**；但不能等同整个 Atlas 不能恢复：ACPBackend.resume 有独立实现，session_sync 也有恢复。按 Backend 分别测试，修 process adapter 的最小恢复契约 |
| 027 | message-board/graph-store、voice/realtime 等可选模块 | Atlas 本身有 groups、memory、voice-demo 等模块 | **U / 不评价**：Codex 同样未证实各 crate 默认启用；不以 crate 命名把 Atlas 判落后 |

## 关键纠偏（防止“抄名词不抄机制”）

1. **已存在 ≠ 等价成熟。** Atlas 的确有会话分支、MCP、checkpoint、子任务、基本模型路由；检查其持久化和恢复语义，而不是宣布“缺全部功能”。
2. **多个“子任务”不能共用一个生命周期概念。** Codex 的 child thread、TUI background terminal、Code Mode cell、daemon recoverable turn 是四个不同实体。Atlas _run_atlas_subtask 是执行完清理会话的 worker；若要长期驻留与消息恢复必须新增相应契约，而非在已有委派方法里塞临时字段。
3. **“失败后任务全被杀”不能被默认当恢复策略。** Codex Core HostConnection drop 会回收不健康 child **host process**，不表示 parent Turn/子 Agent 任务都应该一同标 FAILED。Atlas 具体健康检查需另查故障传播边界，不根据本轮推断。
4. **用户授权策略独立于可靠性。** 参考 Codex 的结构化调度和结果归因，不表示照搬其审批或沙箱政策。Atlas 用户的权限偏好应保持为单独配置。
5. **查缺有证据等级。** “未发现”仅限本轮已检查文件；下一轮先在 Atlas 全仓索引和运行链路里证实，再据此施工，避免重复造轮子。

## 原生落地顺序（仅迁移建议，不改业务代码）

- P0：先对齐 Task/Run/Turn/Thread/ToolCall 的事件与终态不变量，并以 external_process.resume 的显式不支持为一个具体修复入口；实现工具取消与后台进程/Agent 生命周期隔离。建议源：core/atlas/runtime/backends.py、external_process.py、api/runtime.py、agent/run_phases.py。
- P1：实现 parent-child durable ID + runtime residency + mailbox + thread fork 的明确契约；不能让销毁临时 worker 误删可恢复长任务。建议源：agent/__init__.py、runtime/backend_host.py、persistent_agents、engine/session_sync.py。
- P1：Context baseline / diff / version lineage，避免重复注入或与压缩后历史脱节。建议源：engine/hermes_runtime.py、agent/run_phases.py、agent/injection_budget.py。
- P2：评估独立 Code Mode Host 是否真有产品收益。如果需要，实现 cell/session/duplex broker/异步 wait，而非只加 execute_code 接口。
- P2：Tool Search + 增量目录变更、统一 trace 展示。建议源：engine/tool_registry.py、tools/mcp_client.py、api/runtime.py。

此表对 Atlas 有利和不利的证据均保留。未跑回归，不虚报“错误已修复”。
