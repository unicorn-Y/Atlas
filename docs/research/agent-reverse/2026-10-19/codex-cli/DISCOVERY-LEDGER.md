# DISCOVERY LEDGER — 固定版本源码发现总账

证据定义：**S**=固定 tag 0.163.0 真实源码（不等于执行验证）；**R**=实测（本轮 0 项）；**D**=外部声明/清单；**I**=有限推断；**U**=未确认。所有 S 均锚到 `openai/codex@83086188ae0614bd882818ff1aa23f3194962012`。文件与行号详细见 EVIDENCE-INDEX。第一手抽查覆盖的模块不是全仓库穷尽。

| ID | 主动发现/能力，不止表面名称 | 源码锚点 | 等级 | 机制结论与边界 |
|---|---|---|---|---|
| CODEX_CLI-001 | Turn 中的采样-工具结果-再次采样循环 | `core/src/session/turn.rs:152-174,1707-1835` | S | `run_turn` + `run_sampling_request`；流式异常可重试，窗口超限和额度超限走专门路径；模型并非直接执行工具。 |
| CODEX_CLI-002 | 一次响应中多工具的调度与中断 | `core/src/tools/parallel.rs:46-333`; `tools/router.rs:246-392` | S | `ToolCallRuntime` 建单次执行任务，工具注册决定是否可并行，取消和执行结果归并分离。 |
| CODEX_CLI-003 | 工具执行入口的权限/沙箱/升级重试集中收口 | `core/src/tools/orchestrator.rs:1-180` | S | `ToolOrchestrator::run` 统一审批、SandboxAttempt、反馈，避免每个工具各自私有重试。不是建议 Atlas 必须照搬限制。 |
| CODEX_CLI-004 | 工具 registry 分可信/外部与生命周期钩子 | `core/src/tools/registry.rs:55-116,305-465` | S | `CoreToolRuntime`、`register_trusted`/`register_external`、元数据、pre/post hook、缓存定义。 |
| CODEX_CLI-005 | **Code Mode 用代码单元执行一组嵌套工具** | `core/src/tools/code_mode/execute_handler.rs:39-173` | S | parse JS source → 映射工具定义 → session.execute → cell ID → initial response/yield → 记录输出和 trace。并非把工具名直接暴露给外部 JS 引擎。 |
| CODEX_CLI-006 | **Host 独立子进程 + 管道上的 HTTP/2 gRPC** | `core/src/code_mode_host.rs:1-150` | S | `ProcessOwnedGrpcCodeModeSessionProvider` 惰性共享 channel，`--listen grpc+stdio://`，keepalive，drop 时 kill/reap。 |
| CODEX_CLI-007 | **Host 会话租约、调用 ID 幂等线索、背压资源配额** | `code-mode-host/src/grpc/session.rs:39-207`; `code-mode-host/src/lib.rs:45-73` | S | sessions/cells/pending invocations、bounded seen IDs、request/cell/control permits；断开 channel 回收 session。 |
| CODEX_CLI-008 | **双向工具委派不是 Host 在 OS 上任意执行工具** | `core/src/tools/code_mode/delegate.rs:36-240`; `code-mode-host/src/grpc/mod.rs:63-145` | S | Host 发 ToolCall；Core Broker 按 cell gate 交由本回合 ToolRuntime；结果沿 callback 返回 Host。 |
| CODEX_CLI-009 | V8 JS 模块加载、异步 Promise / yield / wait / terminate | `code-mode-runtime/src/runtime/module_loader.rs:8-89`; `code-mode-runtime/src/service.rs:65-198` | S | `evaluate_main_module`, `ObserveMode::YieldAfter`, `PendingFrontier`。**V8，不等于 Node.js**。 |
| CODEX_CLI-010 | **新旧两种 Host transport 并存** | `code-mode-host/src/lib.rs:78-198`; `code-mode-host/src/grpc/mod.rs`; `src/main.rs:15-57` | S | 保留 legacy framed stdio negotiation；独立 gRPC 实现；Core 实际上走 `grpc+stdio`。不得混淆两套协议。 |
| CODEX_CLI-011 | 子 Agent 作为 Thread/Tree，资源隔离与角色配置 | `core/src/agent/control.rs:75-164`; `core/src/agent/control/spawn.rs:676-1014` | S | root session identity、`LocalAgentRuntime`、树共享限制器、`spawn_agent_internal`；子线程不只是一次性函数调用。 |
| CODEX_CLI-012 | **MAv2 子 Agent 驻留 LRU 与安全卸载/重载** | `core/src/agent/control/residency.rs:23-331` | S | `try_evict_v2_thread`、`V2Residency`、pin/reserve/touch/unload；空闲内存对象与持久线程分离。 |
| CODEX_CLI-013 | **离线消息邮箱与唤醒** | `core/src/agent/control/mailbox.rs:15-112`; `agent/control.rs:134-250` | S | 未加载目标 Agent 的非触发式消息可先 enqueue；watch/take；交付与线程回装协调。并非仅 UI 传话。 |
| CODEX_CLI-014 | 子 Agent fork 时裁剪上下文及恢复 | `core/src/agent/control/spawn.rs:81-159,1015-1460` | S | `keep_forked_rollout_item`、`prepare_forked_history`、`resume_agent_from_rollout`，按 fork mode 处理上下文，不是盲复制全部对话。 |
| CODEX_CLI-015 | 多 Agent V2 工具簇和等待条件 | `tools/handlers/multi_agents_v2/{spawn,send_message,wait,followup_task,list_agents,interrupt_agent}.rs` | S | 多个具体 Handler，wait 观察 activity；不应把“子 Agent 支持”缩成一个 spawn API。 |
| CODEX_CLI-016 | 主子 Agent 终态通知与树生命周期 | `core/src/agent/control/completion.rs:25-156`; `agent/control/runtime.rs:37-184` | S | 终态、父通知、shutdown state、teardown guard；与主线程取消分离。 |
| CODEX_CLI-017 | **完整世界状态差分注入** | `core/src/session/world_state.rs:43-414`; `core/src/context_manager/history.rs:93-129` | S | WorldState 包含项目规则、环境、插件/应用、模型设置等基准；历史快照带 context baseline/revision，非“每次把所有提示词复制进去”。 |
| CODEX_CLI-018 | 预压缩与**推测式后台压缩** | `core/src/session/turn.rs:175-232`; `session/async_compaction.rs:1-203` | S | speculative attempt、take_ready、shutdown cancel；discarded 的已完成 usage 仍被计入。激活条件依配置。 |
| CODEX_CLI-019 | **工具目录按需 BM25 检索** | `core/src/tools/handlers/tool_search.rs:38-350` | S | Code Mode/MCP tool search、handler cache、动态元数据校验，减少每轮全部工具定义提示。 |
| CODEX_CLI-020 | Thread fork / rollback / resume 与历史分支 | `core/src/thread_manager.rs:184-2771`; `session/session.rs:950-967` | S | `ForkSnapshot`、分支历史、compaction checkpoint window lineage，需后续分支逐方法核查边界。 |
| CODEX_CLI-021 | Daemon 中断 Turn 的录入点与恢复 attribution | `core/src/session/daemon_recovery.rs:1-57`; `session/turn_input.rs:230-690` | S | 只有 input 写入 rollout 后才捕获 recoverable turn；start-or-steer 有事前验证/提交语义。 |
| CODEX_CLI-022 | 用户执行中追加输入（steer） | `core/src/session/turn_input.rs:328-689`; `agent/control.rs:113-137` | S | idle start 与 active steer 路线不同，并向 Agent 上报独立 submission ID。 |
| CODEX_CLI-023 | TUI 多 Agent 可视状态/快捷切换 | `tui/src/multi_agents.rs:1-189,287-460` | S | agent picker、状态点、spawn/wait/close/resume history cells 与 shortcuts；仅源代码未跑 UI。 |
| CODEX_CLI-024 | TUI 大量实装命令入口（含 queue、rollout、agents、voice） | `tui/src/slash_command.rs:12-321`; `tui/src/session_queue_commands.rs:1-130` | S | enum/command available/visible filter；注册 ≠ 各命令在 Windows/账户可用。 |
| CODEX_CLI-025 | 结构化事件跨协议桥接/追踪 | `core/src/agent/control.rs:140-193`; `tools/parallel.rs:385-484`; `code-mode-host/src/grpc/mod.rs:45-289` | S | ItemStarted/ItemCompleted 兼容 legacy，Tool timing 分 Dispatch/Handler，Code cell OTEL。 |
| CODEX_CLI-026 | 可供宿主消费的 App-server 层，不只是 TUI 本地调用 | `codex-rs/app-server/src/{message_processor.rs,thread_state.rs,turn_admission.rs,daemon_thread_recovery.rs}` | S/U | 文件和模块存在；本轮尚未沿完整 JSON-RPC / WebSocket 请求追到终态，不当成已验证远程任务功能。 |
| CODEX_CLI-027 | **额外潜在扩展**：message-board、graph-store、hooks、voice、realtime | `codex-rs/{agent-graph-store,agent-message-board-client,voice-host,realtime-webrtc,hooks}/` | U | 固定 tag 有独立 crate；尚不能证明默认 CLI 功能已启用。留下后续逐 crate 取证线索。 |

## 非穷尽说明

前 25 项有明确文件/方法级证据；026 仅实现入口/未闭环；027 为主动发现的待证线索。用户未列出的新重点是 007、008、012、013、017、018、019、021、023。任何源代码路径不代表该能力在 Windows Release 的默认配置已开启。
