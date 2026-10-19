# DISCOVERY LEDGER — 固定版本源码发现总账

证据定义：**S**=固定 tag 0.163.0 真实源码（不等于执行验证）；**R**=实测（受限 version/help 共 3 项）；**D**=外部声明/清单；**I**=有限推断；**U**=未确认。所有 S 均锚到 `openai/codex@83086188ae0614bd882818ff1aa23f3194962012`。文件与行号详细见 EVIDENCE-INDEX。第一手抽查覆盖的模块不是全仓库穷尽。

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
| CODEX_CLI-026 | 可供宿主消费的 App-server typed JSON-RPC 控制面 | `app-server-protocol/src/protocol/common.rs:128-139,208-287`; `app-server/src/message_processor.rs:966-1067` | S | 类型化请求反序列化、实验 API/初始化门控、turn admission 与按 serialization scope 排队/并发处理均已源码闭环；CLI help 确认 daemon/remote 入口。实际 RPC turn/终态未动态观察，服务端仍 U。 |
| CODEX_CLI-027 | **额外潜在扩展**：message-board、graph-store、hooks、voice、realtime | `codex-rs/{agent-graph-store,agent-message-board-client,voice-host,realtime-webrtc,hooks}/` | U | 固定 tag 有独立 crate；尚不能证明默认 CLI 功能已启用。留下后续逐 crate 取证线索。 |

| CODEX_CLI-028 | **持久化父子 Agent 图及生命周期边** | `agent-graph-store/src/store.rs:13-61; agent-graph-store/src/local.rs:10-112; core/src/agent/control/spawn_guard.rs:80-99` | S | AgentGraphStore + SQLite local impl; child edge status, BFS descendants; cancelled spawn closes edge。 |
| CODEX_CLI-029 | **可插拔 Agent Message Board（SQLite / in-memory / remote）** | `core/src/agent_message_board.rs:38-121` | S | Requires MultiAgentV2 and AgentMessageBoard feature flags or explicit connection; remote board supports token。 |
| CODEX_CLI-030 | **PendingSpawn 半创建取消清理守卫** | `core/src/agent/control/spawn_guard.rs:1-105` | S | Drop removes child runtime and persistence, waits for Open edge write, then writes Closed。 |
| CODEX_CLI-031 | **Daemon 快照消费及后台 cold resume** | `app-server/src/daemon_thread_recovery.rs:1-51` | S | snapshot uses dedicated OS thread; start_recovery reads+removes snapshot, spawns restore_daemon_threads without blocking readiness。 |
| CODEX_CLI-032 | **MCP 刷新并发门控与取消恢复** | `core/src/session/mcp_refresh.rs:1-57` | S | AtomicBool pending + Semaphore gate; unpublished cancelled refresh guard re-invalidates。 |
| CODEX_CLI-033 | **Retained Context checkpoint 顺序和异步 Code Mode 消息排空** | `core/src/session/retained_context.rs:145-205` | S | persistence lock aligns retained context with checkpoint suffix; TaskTracker waits for cell-generated message recording。 |
| CODEX_CLI-034 | **typed RPC 按资源域串行化与共享读并发** | `app-server/src/request_serialization.rs:24-108,160-306`; `app-server/src/turn_admission.rs:1-83` | S | Scope key 分 Global/SharedRead/Thread/Process 等；相同独占 key FIFO 串行，共享读并发；连接关闭时丢弃排队请求。turn drain 关闭新 admission 并等待已准入任务。静态机制，未实测公平性/竞态。 |
| CODEX_CLI-035 | **CLI daemon、remote app-server 与 agents 控制入口** | `cli/src/main.rs:131-190`; shipped CLI/Host help | S/R | 源码有 `--remote`、token env、`--no-daemon` 与 agents 子命令；真实 CLI help 显示本地共享 daemon 及 remote URI 形式。入口被观察，不代表认证或 remote 操作成功。 |
| CODEX_CLI-036 | **发行包多 helper 组件与固定源身份线索** | `extractions/ARCHIVE-HASHES.json`; `extractions/BINARIES.json`; `codex-resources/voice/manifest.json` | S/D | 三个归档 SHA/字节数与采集 manifest 一致；CLI 包内 Host 与单独 Host ZIP 字节相同；voice manifest 的 build_commit 与固定 tag commit 一致。它不是可重复构建证明。签名/PE/import 静态资料只描述样本。 |
| CODEX_CLI-037 | **Realtime voice 独立进程、WebRTC 协商与设备启用时序** | `realtime-webrtc/src/{client.rs,protocol.rs,session.rs}`; `voice-host/src/main.rs:43-180`; `tui/src/chatwidget/realtime.rs:301-395`; `app-server/src/request_processors/turn_processor.rs:1212-1306` | S | 同 build helper handshake 后初始化 runtime、交换 SDP、TransportReady 后才打开设备；音频帧走 WebRTC，控制走限长 framed stdin/stdout；关闭/超时会停子进程。服务端会话及动态音频未观察，不能标 R。 |

## 非穷尽说明

001—026 及 028—037 共 36 项有明确文件/方法/包级证据；027 为主动发现的待证线索。另有 3 个受限 R 操作（版本与两份 help）；没有真实 Agent turn、RPC 请求或实时语音动态记录。任何源代码路径不代表该能力在 Windows Release 的默认配置已开启。
