**旧研究会话累计 287 条发现/待查记录。以下逐项保留编号和证据。**

# Agent 竞品能力与内部机制统一目录

**时间：2026-10-20。阶段：已整合旧发现，未完成全量二次发现。** 记录条目≠独立功能数，静态源码≠可运行；报告中记录的未知、版本差异和研究对象也会保留。

架构：L1 界面交互；L2 桌面宿主；L3 Agent 核心；L4 多 Agent 调度；L5 工具执行；L6 会话与存储；L7 扩展生态；L8 服务与连接；L9 状态与可观测。跨层能力此版标主要层，需继续复核。

## Claude Code CLI（52 条）

源：[原始发现与证据](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-claude-code/docs/research/agent-reverse/2026-10-19/claude-code/DISCOVERY-LEDGER.md) / [当前研究完成门槛](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-claude-code/docs/research/agent-reverse/2026-10-19/claude-code/FINISH-GATES.md)

| ID | 所属层 | 是什么、用来干什么 | 证据/现状（原始记录） |
|---|---|---|---|
| CLAUDE_CODE-001 | L1 界面交互 | 交互与无头输出：支持标准输入、JSON、流式JSON，用于自动化调用 | D；Extract root command dispatch, output discriminant union, streaming message grammar |
| CLAUDE_CODE-002 | L6 会话存储 | 会话恢复与分叉：按ID、名称、转录记录继续或另开分支 | D；Derive transcript identity, parent linkage, file/branch ownership; R test fresh/resumed/fork |
| CLAUDE_CODE-003 | L2 桌面宿主 | 后台会话守护：附着、查看日志、停止、重启和清理worker | D；Reconstruct process tree, worker registry, IPC socket and restart survival |
| CLAUDE_CODE-004 | L4 多Agent调度 | 并行代理：可寻址前后台子代理与完成通知 | D；Trace agent process/thread ownership, scheduling, cancellation and parent-child IDs |
| CLAUDE_CODE-005 | L4 多Agent调度 | Agent团队通信：独立上下文、磁盘邮箱、共享任务、直接发送消息 | D；Reverse protocol envelope, mailbox atomicity/replay, distinction from ordinary subagents |
| CLAUDE_CODE-006 | L9 状态观测 | 嵌套代理消息归属：用父工具调用ID连接子代理转录 | D；Need actual stream-json sample to align structured UI/provenance, not collapse to plain text |
| CLAUDE_CODE-007 | L7 扩展生态 | 生命周期Hooks：在工具、子代理、压缩等阶段触发扩展回调 | D；Extract built-in hook registry, ordered dispatch, blocking semantics and failure path |
| CLAUDE_CODE-008 | L7 扩展生态 | Skills与命令加载：分作用域搜索、按需注入和fork上下文 | D；Reverse discovery precedence, lazy context injection, subagent handback |
| CLAUDE_CODE-009 | L7 扩展生态 | MCP与认证：注册工具、管理连接、身份验证和插件范围 | D；Extract tool schema registry, discovery, token boundary, plugin registration |
| CLAUDE_CODE-010 | L3 Agent核心 | 上下文压缩与计费：管理窗口、Token和缓存 | D；Trace context builder, summary handoff, session log and usage accounting |
| CLAUDE_CODE-011 | L5 工具执行 | 执行权限：工具允许或禁止、规划和自动模式 | D；Trace classification/rules evaluation before tool exec; current version gated flags |
| CLAUDE_CODE-012 | L1 界面交互 | 终端Agent界面：任务、计划、焦点切换和终端控制 | D；Need TTY snapshots and native TUI registration/render state |
| CLAUDE_CODE-013 | L6 会话存储 | 工作树与检查点：隔离Git修改、回退文件或任务 | D；Need actual persisted data layout, restore invariants and rollback checkpoints |
| CLAUDE_CODE-014 | L8 服务连接 | 远程执行：自建runner、远程控制和云端会话分派 | D；Explicitly client/protocol only; no inferred server implementation |
| CLAUDE_CODE-015 | L3 Agent核心 | 额外命令入口：advisor、goal、batch、autofix-pr、ultrareview等 | D；Discover commands beyond the original user list; require explicit native registration and gating evidence |
| CLAUDE_CODE-016 | L2 桌面宿主 | 原生二进制结构：记录运行时、符号及内嵌资源，属于研究目标 | U；Extract PE header, section table, imported symbols, resource enumeration; avoid assuming Bun/Node |
| CLAUDE_CODE-017 | L3 Agent核心 | 模型工具循环：请求模型、执行工具、追加结果、重试 | U；Trace native decoded function/strings -> tool scheduler -> stream parser -> session persistence |
| CLAUDE_CODE-018 | L8 服务连接 | 启动诊断：认证状态、遥测、更新和缓存 | U；Probe help/version/auth-status-only; inspect string/file references, never upload credentials |
| CLAUDE_CODE-019 | L4 多Agent调度 | 跨会话队友通信：团队外消息与唤醒协议 | D；Documented in agent team page; test output and disk ownership under R |
| CLAUDE_CODE-020 | L1 界面交互 | 命令补全与渲染降级：动态建议、辅助使用和终端适配 | D；Inspect registration tables, TUI capability-detection and terminal-specific state |
| CLAUDE_CODE-021 | L2 桌面宿主 | 守护进程生命周期：保活、重生、移除工作树和恢复原因 | D；Inspect daemon graph and recovery transaction, not just existence of commands |
| CLAUDE_CODE-022 | L8 服务连接 | 模型选择与降级：fallback模型、提示缓存和中断重试 | D/U；Docs establish flags; implementation and resilience policies unknown |
| CLAUDE_CODE-023 | L5 工具执行 | 前后台工具差异：分别过滤工具并继承权限 | D；Context-dependent tools differ from foreground; prove actual tool filter in package |
| CLAUDE_CODE-024 | L1 界面交互 | 结构化结果：按JSON Schema约束输出，提供提示建议 | D；Reverse result/validation event protocol and UI event variants |
| CLAUDE_CODE-025 | L7 扩展生态 | 隐藏入口调查：搜索命令、功能开关与注册引用，尚非确认功能 | U；Build whole-program string inventory and diff with --help/doc command tables before claiming coverage |
| CLAUDE_CODE-026 | L2 桌面宿主 | 发行安装路径：安装时复制/硬链可执行文件，失败时包装启动 | **S:** `install.cjs` and `cli-wrapper.cjs`; explains why installed and fallback process trees differ. |
| CLAUDE_CODE-027 | L2 桌面宿主 | 后台worker租约：claim、attach、detach、过期和重启状态 | **S/R:** exact native string anchors plus matching CLI commands. Concrete lease state machine still U. |
| CLAUDE_CODE-028 | L6 会话存储 | 子代理转录定位：从磁盘查找子任务记录和团队上下文 | **S:** bundle literals; file schema and lifecycle not observed. |
| CLAUDE_CODE-029 | L3 Agent核心 | SDK工作流续跑：按runID恢复并复用输入一致的已完成步骤 | **S:** `sdk-tools.d.ts:2869-2900`; SDK type contract, not asserted as CLI call path. |
| CLAUDE_CODE-030 | L4 多Agent调度 | SDK任务依赖：待办、执行中、完成、阻塞关系和负责人 | **S:** `sdk-tools.d.ts:2802-2868,4005-4038`; existence in SDK declarations, not a captured persisted task file. |
| CLAUDE_CODE-031 | L1 界面交互 | 工作树清理命令：未推送改动保护与服务注册管理 | **R:** exact `rm --help` and `daemon --help` output; no destructive operation run. |
| CLAUDE_CODE-032 | L7 扩展生态 | Windows平台限制：POSIX Hooks等不支持路径的诊断 | **S:** literal diagnostic strings in native `.bun`; runtime failure path not executed. |
| CLAUDE_CODE-033 | L8 服务连接 | 企业网关与云审查：gateway与ultrareview命令，服务器细节未知 | **R:** native help labels them enterprise auth/telemetry gateway and cloud-hosted multi-agent review; backend is U. |
| CLAUDE_CODE-034 | L2 桌面宿主 | 后台升级保护：任务活跃或有人附着时不轻易重启worker | **S (readable source in exact PE):** `evidence/12-native-supervisor-source.md`, method at file offset `0x0f3adb0d`. Actual daemon execution remains U. |
| CLAUDE_CODE-035 | L2 桌面宿主 | 后台worker回收：排除队列、计划任务、监视器等需要保留的进程 | **S:** exact PE methods at `0x0f3ae7ff` and `0x0f3c9807`; no induced low-memory run. |
| CLAUDE_CODE-036 | L6 会话存储 | 后台恢复上下文：保留resume ID、目录、启动参数及转录 | **S:** `doSpawn` visible at PE offset `0x0f3b306d`; model response and successful resume not observed. |
| CLAUDE_CODE-037 | L2 桌面宿主 | 进程接管身份校验：PID加进程起始时间防止接管错误worker | **S:** exact PE offsets `0x0f3b0d05`/`0x0f3b0dff`; cross-process takeover not exercised. |
| CLAUDE_CODE-038 | L8 服务连接 | worker通信会合：随机socket标识和重试前状态复核 | **S:** methods in exact PE at `0x0f3b0d05`, `0x0f3b306d` and adjacent source; actual authorization and retry outcomes remain U. |
| CLAUDE_CODE-039 | L9 状态观测 | 消息协议标识：用户/助手消息、parent_tool_use_id和恢复原因 | **S:** schema source at exact PE offsets `0x0e6853d0`, `0x0e68a935`, `0x0e6a0bf7`; no real event frame captured. |
| CLAUDE_CODE-040 | L4 多Agent调度 | 子任务生命周期消息：taskID、runID、父子关系和进度通知 | **S:** `task_started`, `task_updated`, `background_tasks_changed`, `task_notification` schema source near `0x0e6aa80a-0x0e6a9e7a`; order not observed. |
| CLAUDE_CODE-041 | L4 多Agent调度 | 后台工具异步回执：先返回占位结果，后通知并关联tool_use_id | **S:** `task_notification` schema description at `0x0e6a9e7a`; no background task was run. |
| CLAUDE_CODE-042 | L9 状态观测 | 工具结果元数据：区分未执行、拒绝与真实执行错误 | **S:** user/tool-result schema source at `0x0e6853d0`; no permission/tool result was generated. |
| CLAUDE_CODE-043 | L9 状态观测 | 初始化与计时事件：运行能力快照、各阶段耗时 | **S:** `system/init` and `result/success` schema source at `0x0e69c2e3` and `0x0e694228`; no live event emitted. |
| CLAUDE_CODE-044 | L4 多Agent调度 | 队友消息地址解析：重名、过期、歧义身份处理 | **S:** exact PE `deliver`/resolver and `bt` source at `0x105537f5` and `0x1054e772`; no message sent during research. |
| CLAUDE_CODE-045 | L4 多Agent调度 | SendMessage执行约束：接入执行器、权限、Hooks并校验收件内容 | **S:** tool definition at `0x105510c8`; actual permission UI/settings/hooks not exercised. |
| CLAUDE_CODE-046 | L4 多Agent调度 | 邮箱投递顺序：先落盘再唤醒在线队友 | **S:** `bt` and `xe` at `0x1054e772`/`0x1054f1f1`; inbox path/writer/read/ack are now partly source-traced in `evidence/15`; live runtime consumption remains U. |
| CLAUDE_CODE-047 | L8 服务连接 | 多通道收发：本地team、UDS、桌面或云桥选路 | **S:** dispatcher at `0x105537f5`; network/server delivery and live routing remain U. |
| CLAUDE_CODE-048 | L4 多Agent调度 | 被逐出子代理恢复：收到消息时加载旧状态续跑 | **S:** `agent-evicted` branch at `0x1055916f`; transcript retention, model turn and successful run remain U. |
| CLAUDE_CODE-049 | L6 会话存储 | 邮箱原子写入：文件锁、临时替换和状态库同步 | **S:** `Zw` at PE byte offset 248022054, exact source excerpt in `evidence/15-native-mailbox-source.md`; no live mailbox write. |
| CLAUDE_CODE-050 | L6 会话存储 | 邮箱确认与清理：读取、ack、过滤已读并处理损坏记录 | **S:** `S8e`, `RRr`, `gOe`, `WWn` at PE offsets 248020900, 248024280, 248025672, 248027467; actual consume/wakeup/parent notification remain U. |
| CLAUDE_CODE-051 | L4 多Agent调度 | 任务事件生成：task_started、updated及最终通知 | **S:** `Kn` at 246861552, `Hn` at 246859691, `_a` at 242665992; no live task executed. |
| CLAUDE_CODE-052 | L9 状态观测 | 事件队列管理：限流合并且优先保留生命周期终态 | **S:** queue source near 242662000, consumer `Gzr` at 269514323 and `ut` at 275456189; event delivery and persistence remain U. |

## Claude Desktop / Cowork（22 条）

源：[原始发现与证据](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-claude-desktop/docs/research/agent-reverse/2026-10-19/claude-desktop/DISCOVERY-LEDGER.md) / [当前研究完成门槛](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-claude-desktop/docs/research/agent-reverse/2026-10-19/claude-desktop/FINISH-GATES.md)

| ID | 所属层 | 是什么、用来干什么 | 证据/现状（原始记录） |
|---|---|---|---|
| CLAUDE_DESKTOP-001 | L1 界面交互 | 2026-09-16 起 Chat + Cowork 逐步合流，普通对话内按任务自动升级为可执行任务，无需模式跳转 | Claude 平台/云；D 确认，包 U；渲染器 mode 状态机、task escalation IPC、rollout flags |
| CLAUDE_DESKTOP-002 | L8 服务连接 | 云 Cowork 默认在服务端执行 agent loop + shell，任务及文件绑定账号跨端保存 | 云服务；D 确认，包 U；客户端 RPC、会话 ID 映射、断线恢复 |
| CLAUDE_DESKTOP-003 | L8 服务连接 | 云任务可在桌面关闭/睡眠后继续；依赖本地资源的工具仍需 Desktop 在线 | 云 + 桌面设备桥；D 确认，包 U；设备在线事件、任务与本地调用拆分 |
| CLAUDE_DESKTOP-004 | L5 工具执行 | 本地历史 Cowork：agent loop 在本机，shell 在 Hyper-V Linux VM 内；云/本地是两条不同路径 | Legacy 本地 Cowork；D 确认，包 U；cowork-svc、VM 启停/镜像/磁盘，哪种计划可触发 |
| CLAUDE_DESKTOP-005 | L8 服务连接 | 云端每会话独立 sandbox，需调用设备资源时走经中介的 Desktop 连接，逐条受本机权限约束 | 云执行 + 桥；D 确认，包 U；桌面请求协议/权限消息/工具回执 |
| CLAUDE_DESKTOP-006 | L8 服务连接 | 企业版统一体验可自动把普通聊天转换为 cloud workspace，空闲几分钟后停 VM + 加密磁盘快照，环境最长 30 天 | 企业版新架构；D 确认，包 U；恢复状态、snapshot ID、任务 UI 的具体事件 |
| CLAUDE_DESKTOP-007 | L5 工具执行 | 内置浏览器在桌面侧栏操作；不同于复用用户自己的 Chrome profile | Desktop 浏览器；D 确认，包 U；webview 实现、会话归属、截图/导航反馈 |
| CLAUDE_DESKTOP-008 | L5 工具执行 | 设备操作优先级为 connector → 内置/Chrome 浏览器 → screen interaction | Desktop/工具路由；D 确认，包 U；工具能力发现、fallback 决策链 |
| CLAUDE_DESKTOP-009 | L1 界面交互 | 定时任务 UI 支持创建、运行记录、暂停、恢复、手动触发；可指定模型/文件夹/审批方式 | Cloud/local Scheduler；D 确认，包 U；调度所有权、task/run 独立存储、失败重试 |
| CLAUDE_DESKTOP-010 | L6 会话存储 | 多端共享会话、项目上下文、连接器、技能、工件；当前多模式迁移兼容渐进发布 | Claude 账号/平台；D 确认，包 U；旧版本本地状态迁移、跨端 hydration |
| CLAUDE_DESKTOP-011 | L1 界面交互 | 新版 Docs / Slides / Design 在会话内部可编辑与共享，不只是附件下载 | Artifacts/Docs 平台；D 确认，包 U；block/component schema，编辑增量及保存版本 |
| CLAUDE_DESKTOP-012 | L5 工具执行 | 电脑操作能力需要 Desktop 连接；macOS 15+ 存在后台窗口交互模式，而不是单纯夺焦截图 | 桌面 Computer Use；D 确认，Windows 路径 U；Windows UIA/CUA 工具实现和后台能力差异 |
| CLAUDE_DESKTOP-013 | L7 扩展生态 | 官方文档明确云 sandbox 与本机 MCP / connector 的执行边界不同：本地 MCP 依赖 Desktop，云 connector 通过服务器 | 平台/扩展；D 确认，包 U；MCPB/DXT 加载器、tool bridge 路由 |
| CLAUDE_DESKTOP-014 | L2 桌面宿主 | Enterprise/consumer MSIX 内容是否等价、2.42304.0 是否已配置新 Unified UI、哪些功能按账号 rollout | Package；U 阻塞；两包 SHA、feature flags 与启动配置对照 |
| CLAUDE_DESKTOP-015 | L2 桌面宿主 | `app.asar` 真实入口、全部 IPC channels、UI routes、RPC schema、service life cycle | Package；PARTIAL S / U；入口与部分 IPC/RPC 已得；补全动态通道定义引用、所有 routes、状态和恢复 |
| CLAUDE_DESKTOP-016 | L2 桌面宿主 | `cowork-svc.exe` 真实作用、持久化文件格式与进程树 | Package；PARTIAL S / U；Go/PE 与 named-pipe VM request已见；补 service 安装/启动父进程、完整调用图和持久化动态证据 |
| CLAUDE_DESKTOP-017 | L1 界面交互 | 工具输出可点击任务卡、subtask/prefill与主会话引用 | Renderer/agent；PARTIAL S / U；artifact scheduled-task点击链已闭合；继续枚举所有卡片、subtask及后端消息 schema |
| CLAUDE_DESKTOP-018 | L2 桌面宿主 | 启动、最小化、退出、网络断开、重新登录、后台云任务消息的正确生命周期 | Desktop/platform；U 阻塞；静态调用图 + 可重复操作日志 |
| CLAUDE_DESKTOP-019 | L7 扩展生态 | 源码可见但 UI 未入口功能、动态模块、远端实验 flags | Package；PARTIAL S / U；多处 feature gate 已见，尚未穷举所有 gates/routes 和账号下发配置 |
| CLAUDE_DESKTOP-020 | L5 工具执行 | 权限策略的“继续执行/仅关键时确认”和本地设备逐 app 授权分离 | 平台 UI；D 确认，包 U；许可证/配置/审批协议及后续持久化 |
| CLAUDE_DESKTOP-021 | L6 会话存储 | 按 project 汇聚文件、上下文、指令、记忆，可跨设备访问 | Claude 账号/项目；D 确认，包 U；project metadata 与 conversation/task 关联 |
| CLAUDE_DESKTOP-022 | L4 多Agent调度 | 多子任务和并行工作流（官方可见），具体子 agent 数、隔离、任务结果合并未证实 | Cowork 任务；D 确认，仅行为；worker spawn/cancel/retry/aggregate 链路 |

## Codex CLI / Code Mode（40 条）

源：[原始发现与证据](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-codex-cli/docs/research/agent-reverse/2026-10-19/codex-cli/DISCOVERY-LEDGER.md) / [当前研究完成门槛](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-codex-cli/docs/research/agent-reverse/2026-10-19/codex-cli/FINISH-GATES.md)

| ID | 所属层 | 是什么、用来干什么 | 证据/现状（原始记录） |
|---|---|---|---|
| CODEX_CLI-001 | L3 Agent核心 | Turn 中的采样-工具结果-再次采样循环 | `core/src/session/turn.rs:152-174,1707-1835`；S；`run_turn` + `run_sampling_request`；流式异常可重试，窗口超限和额度超限走专门路径；模型并非直接执行工具。 |
| CODEX_CLI-002 | L5 工具执行 | 一次响应中多工具的调度与中断 | `core/src/tools/parallel.rs:46-333`; `tools/router.rs:246-392`；S；`ToolCallRuntime` 建单次执行任务，工具注册决定是否可并行，取消和执行结果归并分离。 |
| CODEX_CLI-003 | L5 工具执行 | 工具执行入口的权限/沙箱/升级重试集中收口 | `core/src/tools/orchestrator.rs:1-180`；S；`ToolOrchestrator::run` 统一审批、SandboxAttempt、反馈，避免每个工具各自私有重试。不是建议 Atlas 必须照搬限制。 |
| CODEX_CLI-004 | L5 工具执行 | 工具 registry 分可信/外部与生命周期钩子 | `core/src/tools/registry.rs:55-116,305-465`；S；`CoreToolRuntime`、`register_trusted`/`register_external`、元数据、pre/post hook、缓存定义。 |
| CODEX_CLI-005 | L5 工具执行 | **Code Mode 用代码单元执行一组嵌套工具** | `core/src/tools/code_mode/execute_handler.rs:39-173`；S；parse JS source → 映射工具定义 → session.execute → cell ID → initial response/yield → 记录输出和 trace。并非把工具名直接暴露给外部 JS 引擎。 |
| CODEX_CLI-006 | L2 桌面宿主 | **Host 独立子进程 + 管道上的 HTTP/2 gRPC** | `core/src/code_mode_host.rs:1-150`；S；`ProcessOwnedGrpcCodeModeSessionProvider` 惰性共享 channel，`--listen grpc+stdio://`，keepalive，drop 时 kill/reap。 |
| CODEX_CLI-007 | L5 工具执行 | **Host 会话租约、调用 ID 幂等线索、背压资源配额** | `code-mode-host/src/grpc/session.rs:39-207`; `code-mode-host/src/lib.rs:45-73`；S；sessions/cells/pending invocations、bounded seen IDs、request/cell/control permits；断开 channel 回收 session。 |
| CODEX_CLI-008 | L5 工具执行 | **双向工具委派不是 Host 在 OS 上任意执行工具** | `core/src/tools/code_mode/delegate.rs:36-240`; `code-mode-host/src/grpc/mod.rs:63-145`；S；Host 发 ToolCall；Core Broker 按 cell gate 交由本回合 ToolRuntime；结果沿 callback 返回 Host。 |
| CODEX_CLI-009 | L5 工具执行 | V8 JS 模块加载、异步 Promise / yield / wait / terminate | `code-mode-runtime/src/runtime/module_loader.rs:8-89`; `code-mode-runtime/src/service.rs:65-198`；S；`evaluate_main_module`, `ObserveMode::YieldAfter`, `PendingFrontier`。**V8，不等于 Node.js**。 |
| CODEX_CLI-010 | L2 桌面宿主 | **新旧两种 Host transport 并存** | `code-mode-host/src/lib.rs:78-198`; `code-mode-host/src/grpc/mod.rs`; `src/main.rs:15-57`；S；保留 legacy framed stdio negotiation；独立 gRPC 实现；Core 实际上走 `grpc+stdio`。不得混淆两套协议。 |
| CODEX_CLI-011 | L4 多Agent调度 | 子 Agent 作为 Thread/Tree，资源隔离与角色配置 | `core/src/agent/control.rs:75-164`; `core/src/agent/control/spawn.rs:676-1014`；S；root session identity、`LocalAgentRuntime`、树共享限制器、`spawn_agent_internal`；子线程不只是一次性函数调用。 |
| CODEX_CLI-012 | L4 多Agent调度 | **MAv2 子 Agent 驻留 LRU 与安全卸载/重载** | `core/src/agent/control/residency.rs:23-331`；S；`try_evict_v2_thread`、`V2Residency`、pin/reserve/touch/unload；空闲内存对象与持久线程分离。 |
| CODEX_CLI-013 | L4 多Agent调度 | **离线消息邮箱与唤醒** | `core/src/agent/control/mailbox.rs:15-112`; `agent/control.rs:134-250`；S；未加载目标 Agent 的非触发式消息可先 enqueue；watch/take；交付与线程回装协调。并非仅 UI 传话。 |
| CODEX_CLI-014 | L3 Agent核心 | 子 Agent fork 时裁剪上下文及恢复 | `core/src/agent/control/spawn.rs:81-159,1015-1460`；S；`keep_forked_rollout_item`、`prepare_forked_history`、`resume_agent_from_rollout`，按 fork mode 处理上下文，不是盲复制全部对话。 |
| CODEX_CLI-015 | L4 多Agent调度 | 多 Agent V2 工具簇和等待条件 | `tools/handlers/multi_agents_v2/{spawn,send_message,wait,followup_task,list_agents,interrupt_agent}.rs`；S；多个具体 Handler，wait 观察 activity；不应把“子 Agent 支持”缩成一个 spawn API。 |
| CODEX_CLI-016 | L4 多Agent调度 | 主子 Agent 终态通知与树生命周期 | `core/src/agent/control/completion.rs:25-156`; `agent/control/runtime.rs:37-184`；S；终态、父通知、shutdown state、teardown guard；与主线程取消分离。 |
| CODEX_CLI-017 | L3 Agent核心 | **完整世界状态差分注入** | `core/src/session/world_state.rs:43-414`; `core/src/context_manager/history.rs:93-129`；S；WorldState 包含项目规则、环境、插件/应用、模型设置等基准；历史快照带 context baseline/revision，非“每次把所有提示词复制进去”。 |
| CODEX_CLI-018 | L3 Agent核心 | 预压缩与**推测式后台压缩** | `core/src/session/turn.rs:175-232`; `session/async_compaction.rs:1-203`；S；speculative attempt、take_ready、shutdown cancel；discarded 的已完成 usage 仍被计入。激活条件依配置。 |
| CODEX_CLI-019 | L5 工具执行 | **工具目录按需 BM25 检索** | `core/src/tools/handlers/tool_search.rs:38-350`；S；Code Mode/MCP tool search、handler cache、动态元数据校验，减少每轮全部工具定义提示。 |
| CODEX_CLI-020 | L6 会话存储 | Thread fork / rollback / resume 与历史分支 | `core/src/thread_manager.rs:184-2771`; `session/session.rs:950-967`；S；`ForkSnapshot`、分支历史、compaction checkpoint window lineage，需后续分支逐方法核查边界。 |
| CODEX_CLI-021 | L6 会话存储 | Daemon 中断 Turn 的录入点与恢复 attribution | `core/src/session/daemon_recovery.rs:1-57`; `app-server/src/request_processors/{daemon_snapshot,daemon_continuation}.rs`; `thread_processor.rs:3870-3901,4190-4238`；S；只有非取消 regular turn、有 RecordedTurnInput、单一 local thread-configured environment 才进快照；cold resume 校验 history/environment/permission 后先 abort 旧 turn，再用新的 daemon_recovery continuation turn 重推理。不是相同 model/tool operation 原位恢复。 |
| CODEX_CLI-022 | L3 Agent核心 | 用户执行中追加输入（steer） | `core/src/session/turn_input.rs:328-689`; `agent/control.rs:113-137`；S；idle start 与 active steer 路线不同，并向 Agent 上报独立 submission ID。 |
| CODEX_CLI-023 | L1 界面交互 | TUI 多 Agent 可视状态/快捷切换 | `tui/src/multi_agents.rs:1-189,287-460`；S；agent picker、状态点、spawn/wait/close/resume history cells 与 shortcuts；仅源代码未跑 UI。 |
| CODEX_CLI-024 | L1 界面交互 | TUI 大量实装命令入口（含 queue、rollout、agents、voice） | `tui/src/slash_command.rs:12-321`; `tui/src/session_queue_commands.rs:1-130`；S；enum/command available/visible filter；注册 ≠ 各命令在 Windows/账户可用。 |
| CODEX_CLI-025 | L9 状态观测 | 结构化事件跨协议桥接/追踪 | `core/src/agent/control.rs:140-193`; `tools/parallel.rs:385-484`; `code-mode-host/src/grpc/mod.rs:45-289`；S；ItemStarted/ItemCompleted 兼容 legacy，Tool timing 分 Dispatch/Handler，Code cell OTEL。 |
| CODEX_CLI-026 | L8 服务连接 | 可供宿主消费的 App-server typed JSON-RPC 控制面 | `app-server-protocol/src/protocol/common.rs:128-139,208-287`; `app-server/src/message_processor.rs:966-1067`；S；类型化请求反序列化、实验 API/初始化门控、turn admission 与按 serialization scope 排队/并发处理均已源码闭环；CLI help 确认 daemon/remote 入口。实际 RPC turn/终态未动态观察，服务端仍 U。 |
| CODEX_CLI-027 | L7 扩展生态 | **额外潜在扩展**：message-board、graph-store、hooks、voice、realtime | `codex-rs/{agent-graph-store,agent-message-board-client,voice-host,realtime-webrtc,hooks}/`；U；固定 tag 有独立 crate；尚不能证明默认 CLI 功能已启用。留下后续逐 crate 取证线索。 |
| CODEX_CLI-028 | L6 会话存储 | **持久化父子 Agent 图及生命周期边** | `agent-graph-store/src/store.rs:13-61; agent-graph-store/src/local.rs:10-112; core/src/agent/control/spawn_guard.rs:80-99`；S；AgentGraphStore + SQLite local impl; child edge status, BFS descendants; cancelled spawn closes edge。 |
| CODEX_CLI-029 | L4 多Agent调度 | **可插拔 Agent Message Board（SQLite / in-memory / remote）** | `core/src/agent_message_board.rs:38-121`；S；Requires MultiAgentV2 and AgentMessageBoard feature flags or explicit connection; remote board supports token。 |
| CODEX_CLI-030 | L4 多Agent调度 | **PendingSpawn 半创建取消清理守卫** | `core/src/agent/control/spawn_guard.rs:1-105`；S；Drop removes child runtime and persistence, waits for Open edge write, then writes Closed。 |
| CODEX_CLI-031 | L6 会话存储 | **Daemon 快照消费及后台 cold resume** | `app-server/src/daemon_thread_recovery.rs:1-51`; `app-server/src/request_processors/daemon_continuation.rs:19-132`；S；snapshot uses dedicated OS thread; start_recovery consumes/removes snapshot, background restores eligible persistent root threads and continuation checks for still-interrupted history before injecting a new continuation turn. |
| CODEX_CLI-032 | L7 扩展生态 | **MCP 刷新并发门控与取消恢复** | `core/src/session/mcp_refresh.rs:1-57`；S；AtomicBool pending + Semaphore gate; unpublished cancelled refresh guard re-invalidates。 |
| CODEX_CLI-033 | L3 Agent核心 | **Retained Context checkpoint 顺序和异步 Code Mode 消息排空** | `core/src/session/retained_context.rs:145-205`；S；persistence lock aligns retained context with checkpoint suffix; TaskTracker waits for cell-generated message recording。 |
| CODEX_CLI-034 | L8 服务连接 | **typed RPC 按资源域串行化与共享读并发** | `app-server/src/request_serialization.rs:24-108,160-306`; `app-server/src/turn_admission.rs:1-83`；S；Scope key 分 Global/SharedRead/Thread/Process 等；相同独占 key FIFO 串行，共享读并发；连接关闭时丢弃排队请求。turn drain 关闭新 admission 并等待已准入任务。静态机制，未实测公平性/竞态。 |
| CODEX_CLI-035 | L8 服务连接 | **CLI daemon、remote app-server 与 agents 控制入口** | `cli/src/main.rs:131-190`; shipped CLI/Host help；S/R；源码有 `--remote`、token env、`--no-daemon` 与 agents 子命令；真实 CLI help 显示本地共享 daemon 及 remote URI 形式。入口被观察，不代表认证或 remote 操作成功。 |
| CODEX_CLI-036 | L2 桌面宿主 | **发行包多 helper 组件与固定源身份线索** | `extractions/ARCHIVE-HASHES.json`; `extractions/BINARIES.json`; `codex-resources/voice/manifest.json`；S/D；三个归档 SHA/字节数与采集 manifest 一致；CLI 包内 Host 与单独 Host ZIP 字节相同；voice manifest 的 build_commit 与固定 tag commit 一致。它不是可重复构建证明。签名/PE/import 静态资料只描述样本。 |
| CODEX_CLI-037 | L5 工具执行 | **Realtime voice 独立进程、WebRTC 协商与设备启用时序** | `realtime-webrtc/src/{client.rs,protocol.rs,session.rs}`; `voice-host/src/main.rs:43-180`; `tui/src/chatwidget/realtime.rs:301-395`; `app-server/src/request_processors/turn_processor.rs:1212-1306`；S；同 build helper handshake 后初始化 runtime、交换 SDP、TransportReady 后才打开设备；音频帧走 WebRTC，控制走限长 framed stdin/stdout；关闭/超时会停子进程。服务端会话及动态音频未观察，不能标 R。 |
| CODEX_CLI-038 | L8 服务连接 | **发布版 app-server JSON-RPC admission、rollout 写入与冷历史 reattach** | Real CLI 0.163.0 isolated app-server `initialize` + `thread/start` + `turn/start` + cross-process `thread/resume`; `END-TO-END-TRACES.md` R1；R (partial)；turn/start 返回 inProgress 并发 thread/turn/user-message events；新进程可加载 1 个 stored turn(status interrupted)，thread idle。没有观察 assistant/model/tool 输出或 turn/completed；这是历史 reattach，不是正在执行 operation 冷恢复。 |
| CODEX_CLI-039 | L5 工具执行 | **发布版 Code Mode Host legacy framed stdio → V8 cell → synthetic callback** | release Host SHA `07f3869f...b9988`; `END-TO-END-TRACES.md` R2；R；hello 协商 V1 后 session/open 成功；session/execute 启动 V8 cell，delegate/request 抵达测试客户端，delegate/response 合成 JSON 返回并进入 execute initialResponse。Host 链闭合；Core gRPC+stdio 和核心工具执行器仍 U。 |
| CODEX_CLI-040 | L7 扩展生态 | **独立 crate 与注入点：graph-store / message-board / hooks / dynamic registries** | `core/src/agent_message_board.rs:38-121`; `agent-graph-store/src/store.rs:13-61`; `core/src/tools/registry.rs:305-465`; `core/src/session/mcp_refresh.rs:1-57`；S；多种扩展由 trait / dependency / feature/config injection 挂接；crate 存在不代表该发布版默认启用。全量注册表未穷尽，状态部分开放。 |

## Codex Desktop（30 条）

源：[原始发现与证据](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-codex-desktop/docs/research/agent-reverse/2026-10-19/codex-desktop/DISCOVERY-LEDGER.md) / [当前研究完成门槛](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-codex-desktop/docs/research/agent-reverse/2026-10-19/codex-desktop/FINISH-GATES.md)

| ID | 所属层 | 是什么、用来干什么 | 证据/现状（原始记录） |
|---|---|---|---|
| CODEX_DESKTOP-001 | L2 桌面宿主 | Windows MSIX 包身份、app/ChatGPT.exe、codex-command-runner.exe 双入口；真实 IPC 尚不明 | S-collection：manifest.json；RECOVERY-CODEX-CLAUDE.md，MSIX 3651 条目；文件名确认；未亲自读二进制；Electron 主进程已有，平台差异未判 |
| CODEX_DESKTOP-002 | L5 工具执行 | 原生 Windows 的执行环境/可选择 WSL，工作树/后台聊天 | D：learn.chatgpt.com/docs/windows/windows-app；官方描述，不等于发行版本逐项验证；Atlas 自带 PowerShell + worktree |
| CODEX_DESKTOP-003 | L6 会话存储 | thread/start、resume、fork、read、list；线程 ID 和订阅关系分离 | S-Server：app-server-protocol/src/protocol/common.rs:552-564,772,858；app-server/src/thread_state.rs:56-79；U；Atlas fork/tree/session_sync 真实存在 |
| CODEX_DESKTOP-004 | L6 会话存储 | Daemon snapshot 保存持久根线程；服务恢复异步走 cold-resume，并删除已消费快照；与正在跑的 turn 续跑不同 | S-Server：app-server/src/daemon_thread_recovery.rs:1-54；thread_state.rs:56-77；U；Atlas 服务重启即标记 run.failed |
| CODEX_DESKTOP-005 | L6 会话存储 | 活动线程恢复：历史回包 + 后续通知订阅在监听器中按顺序完成；listener generation 与 shutdown drain | S-Server：app-server/src/thread_state.rs:57-91,106-125；U；Atlas WebSocket seq reconnect；未发现等价持久监听器迁移 |
| CODEX_DESKTOP-006 | L6 会话存储 | thread 已读收据 firstUnread/revision，revision CAS 防止多窗口无意覆盖 | S-Server+D-in-repo：common.rs:858-868；app-server/README.md read-state 段；U（实验）；Atlas 按会话缓存消息和滚动位置，未见 read CAS |
| CODEX_DESKTOP-007 | L6 会话存储 | thread/queue/add/list/update/delete/reorder/start，按线程管理任务列队 | S-Server：common.rs:630-662；thread_state.rs:78-81；标实验；U；Atlas FollowUpMode queue/steer/redirect 已实现一定逻辑，持久重排未证 |
| CODEX_DESKTOP-008 | L9 状态观测 | turn/item 分层事件：启动/完成、实时文本、plan、diff、工具 stdout/stderr、PTY 互动、失败 | S-Server：common.rs:1949-2042；U；Atlas Runtime Event 1.2 + whitelist + timeline |
| CODEX_DESKTOP-009 | L5 工具执行 | 命令审批、文件审批、额外权限、MCP elicitation 是 server→client **有响应的请求** | S-Server：common.rs:1795-1827；thread_state.rs:83-90；U；Atlas approval_futures，部分有线，事件模型不同 |
| CODEX_DESKTOP-010 | L7 扩展生态 | 工具结果可附 mcpAppUi.resourceUri 和 inline/fullscreen preference，写入历史；嵌入渲染仍取决于客户端 | S-Server+D-in-repo：app-server/README.md “MCP App UI”；U；**不宣称支持任意交互控件**；Atlas Markdown + 固定 TimelineItem 组件 |
| CODEX_DESKTOP-011 | L5 工具执行 | 动态工具调用由服务端向 UI/宿主发出，异步接回模型；失败回传失败文本；音频/远端图片输出受约束 | S-Server：app-server/src/dynamic_tools.rs:14-114；common.rs:1827+；U；Atlas MCP 工具存在，宿主动态工具响应协议未见等价 |
| CODEX_DESKTOP-012 | L7 扩展生态 | Plugins / Apps / MCP 三个独立资源、安装/管理和变更事件 | S-Server：common.rs:924-1057,1246-1284,2000+；app-server/src/message_processor.rs:28-53；U；Atlas PluginRuntime 和 Skills/MCP 存在，区别不可直接抹平 |
| CODEX_DESKTOP-013 | L5 工具执行 | 文件操作 + fs/watch 事件，MCP 事件流以及会话级文件搜索 | S-Server：common.rs:997-1037,1270-1284,1500-1520,2010+；U；Atlas File Panel / LSP / tools，具体事件契约不同 |
| CODEX_DESKTOP-014 | L5 工具执行 | command/exec 沙箱命令可 write/terminate/PTY resize；实验性的 process/spawn 非沙箱且生命周期独立 | S-Server：common.rs:1377-1435；app-server/src/command_exec.rs:53-124；U；Atlas xterm WebSocket 与进程轮询可用，不是同个 RPC |
| CODEX_DESKTOP-015 | L8 服务连接 | transport 包含 stdio、WebSocket、control socket、远程控制接口；连接有实验开关与通知订阅过滤 | S-Server：app-server/src/transport.rs:15-39,42-126；Desktop 实际选哪条未知；Atlas 本地 HTTP/WebSocket；本地 CLI IPC 未明 |
| CODEX_DESKTOP-016 | L8 服务连接 | model/list 与刷新有 provider requirements；不合规时请求显式失败，不能继续沿用不允许的旧端点 | S-Server+D-in-repo：app-server/README.md “Model catalog provider requirements”；U；Atlas model router 存在；不等价 |
| CODEX_DESKTOP-017 | L8 服务连接 | 用户触发 userVerification/cancel 不等于 prompt 已结束，也不能撤回已经完成的证明 | D-in-repo+S-contract：README User verification cancellation；common.rs:520-540；U/experimental；Atlas approval answer 有 futures，验证取消语义未查 |
| CODEX_DESKTOP-018 | L5 工具执行 | thread/realtime 提供文本/音频/语音双向事件 | S-Server：common.rs:1080-1118,2045+；实验；U（是否 desktop 载入未知）；Atlas voice overlay 不能借此判定等价 |
| CODEX_DESKTOP-019 | L1 界面交互 | 官方桌面任务调度/活动结果收件箱/并发工作树 | D：learn.chatgpt.com/docs/automations；发行版本待核；Atlas automation 与 scheduler 可见，端到端质量未知 |
| CODEX_DESKTOP-020 | L1 界面交互 | 宿主自更新、内置组件、真实消息 Card DSL、渲染容器与 action 派发 | U：必须提取 MSIX JS/HTML/asar/EXE 符号；未证，**不得声称缺失或存在**；Atlas 前端硬编码事件白名单是已证事实 |
| CODEX_DESKTOP-021 | L2 桌面宿主 | Windows Desktop 启动 runner、后台存活与用户切换的完整握手、版本兼容与错误降级 | U：MSIX + 启动进程树/脱敏日志；未证；Atlas Electron backendProcess 与 WS 存在 |
| CODEX_DESKTOP-022 | L7 扩展生态 | 外部 Agent 设置探测、配置导入及导入进度事件 | S-Server：common.rs:1440-1460,2010+；message_processor.rs:17,28+；Desktop UI 未证；Atlas external_import.py/ImportPanel 也存在 |
| CODEX_DESKTOP-023 | L7 扩展生态 | 扩展通知、订阅时实验能力闸门与各连接 opt-out 过滤 | S-Server：transport.rs:42-126；U；Atlas normalizeRuntimeEvent 丢未知 event |
| CODEX_DESKTOP-024 | L1 界面交互 | 文件改动 patchUpdated 和回合级 diffUpdated 与普通 Markdown 回答分离，可做局部操作界面 | S-Server：common.rs:1977-2008；Desktop 呈现方式 U；Atlas ChangesPanel 有逐行 diff 评论，通过文本送回引擎 |
| CODEX_DESKTOP-025 | L2 桌面宿主 | Electron preload桥：视图、worker消息、文件拖拽与分块ACK | MSIX app.asar `.vite/build/preload.js`, SHA `a3e622f8…e256b7`, offsets 1,819 / 3,341 / 6,599; exposed `electronBridge`；S; API existence confirmed; every main handler and caller not enumerated |
| CODEX_DESKTOP-026 | L2 桌面宿主 | 宿主分块帧协议：传输ID、顺序、边界和ACK校验 | same preload, byte offsets 1,111 and 1,819；S; assembled data flow, backpressure and timeout unresolved |
| CODEX_DESKTOP-027 | L8 服务连接 | 桌面JSON-RPC客户端：请求映射、通知与线程/回合的变更分类 | `.vite/build/main-C4DYk222.js`, SHA `c8a2af50…a2c175`, offsets 49,098; 97,588; ~740,050; RPC URI offset 3,270,816；S; specific renderer component → call chain not closed |
| CODEX_DESKTOP-028 | L2 桌面宿主 | 应用服务兼容性：版本匹配、重启诊断、实验API开关 | `.vite/build/application-network-startup-DB1VeU3v.js`, SHA `c338bbdd…c67578`, offsets 680 and ~2,900；S package-observed only; successful handshake unobserved |
| CODEX_DESKTOP-029 | L2 桌面宿主 | 运行时组件分层：Codex、Code Mode、沙箱、runner、搜索和Windows电脑操作管道 | startup module offset ~14,070; main bundle offsets ~170,200–173,000；S; package components/host code observed; actual process tree and feature use unobserved |
| CODEX_DESKTOP-030 | L1 界面交互 | 懒加载界面：子代理面板、会话、MCP Apps和侧栏iframe | 41 targeted chunks from 20,362 `webview/assets`; see hashes/summary in `UI-AND-WORKFLOWS.md` and `IMPLEMENTATION-TRACE.md`；S bounded sample; not full UI inventory or proof of remote service behavior |

## DSH Core（36 条）

源：[原始发现与证据](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-dsh-core/docs/research/agent-reverse/2026-10-19/dsh-core/DISCOVERY-LEDGER.md) / [当前研究完成门槛](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-dsh-core/docs/research/agent-reverse/2026-10-19/dsh-core/FINISH-GATES.md)

| ID | 所属层 | 是什么、用来干什么 | 证据/现状（原始记录） |
|---|---|---|---|
| DSH_CORE-001 | L3 Agent核心 | Agent 驱动显式 `idle/maintenance/running`，`kick/turn/step` 由会话日志构建请求 | `packages/core/agent-loop/src/agent.ts:42-50,97-150,252-265,298-400`；S；未动态跑 |
| DSH_CORE-002 | L6 会话存储 | `followup/steer/inject` 分别写 `next-turn/next-step` durable inbox；取消后 waking input 进入下个 Turn | `agent-loop/src/agent.ts:154-180`; `inbox.ts:20-55`；S；时序基于源码 |
| DSH_CORE-003 | L9 状态观测 | 每 Step 写 `step/start/end`，异常补写缺失 tool/result，Turn 末尾有终止原因 | `agent-loop/src/agent.ts:307-388`；S；崩溃中间态待运行 |
| DSH_CORE-004 | L9 状态观测 | 模型 attempt stream 暂态帧与已提交 seq 解耦，提交失败标记 `abandoned` | `agent-loop/src/assistant-stream.ts:18-107`；S；Web 对应 projection 另查 |
| DSH_CORE-005 | L5 工具执行 | 工具并行 rolling pool + exclusivity barrier + ordered finalize；取消为未派发工具合成失败结果 | `agent-loop/src/tool-calls.ts:60-100,122-246,249-286`；S；动态模式变更仍需实测 |
| DSH_CORE-006 | L8 服务连接 | 模型路由提案 waterfall → `llm.prepareCall` → durable header/context；工具 schema 变动也记 developer message | `agent-loop/src/agent.ts:563-684`；S；当前源码版本 |
| DSH_CORE-007 | L4 多Agent调度 | 子 Agent provider 可替换、`startActivation` 返回 child id，不同步等待工作完成 | `packages/subagent/tool-subagent/src/index.ts:193-220,319-379`；S；provider 类型差异 |
| DSH_CORE-008 | L4 多Agent调度 | 子代理 manager 拥有 process-local resident map、每子锁、capacity pool、初始化回滚及父子拥有关系 | `packages/subagent/subagent/src/manager.ts:129-179,373-465,735-761,930-964`; `activation.ts:15-36,164-183`；S；子树逻辑需更多演练 |
| DSH_CORE-009 | L4 多Agent调度 | 冷恢复直系 continuable child；send_message 双向相邻消息，`steerPrompt/queuePrompt` 决定 Step 或 Turn | `manager.ts:533-628,707-730`; `tool-subagent-control/src/index.ts:27-111`；S；外部子进程不可续 |
| DSH_CORE-010 | L4 多Agent调度 | start/end 生命周期边缘事件、以子 Session 真实 turn outcome 判终结而非以 disposal 成功推断 | `subagent/src/lifecycle.ts:63-114,118-170`；S；尚无 runtime log |
| DSH_CORE-011 | L4 多Agent调度 | 子代理深度预算写入 child meta；父的当前 route/reasoning 传给孩子，改 route 可清 inherited effort | `subagent/src/child-agent.ts:49-57,68-118,135-160`；S；depth 默认按插件 |
| DSH_CORE-012 | L4 多Agent调度 | Browser 可直接 `subagents.prompt`、`interruptByParent`；模式与 parentSessionId 校验 | `subagent/src/index.ts:436-527`; `control.ts:16-28,56-104`；S；一次性 provider 禁 follow-up |
| DSH_CORE-013 | L1 界面交互 | UI 可点子代理树打开子 Session 或右侧嵌套对话，明示活动状态/运行时长/只读原因 | `client/ui-subagent/src/client/index.ts:52-101`; `SubagentHeaderLineage.tsx:18-45,196-395`; `sidebar-chat/index.tsx:18-21,51-82,129-201`；S；仅源码 UI |
| DSH_CORE-014 | L6 会话存储 | 真实 `SessionController` 的 page/follow/control/projections 与 Web `MutableSessionEventSource` 增量合流 | `api/session-controller/src/index.ts:118-176,524-603`; `control.ts:17-79`; `client/contract/events.ts:6-35,97-120`；S；网络中断实测未做 |
| DSH_CORE-015 | L8 服务连接 | Typert RPC 跨一个 WebSocket 多路复用逻辑流 `/api/remote.mux`；ping/pong / connection 失败归因 | `api/gateway/src/stream-protocol.ts:6-19`; `stream-server.ts:44-127`; `client/stream-client.ts:52-105,241-380`；S；in-flight stream 失连会 fail |
| DSH_CORE-016 | L6 会话存储 | JSONL 事件日志有写入批处理、进程间单 writer 内核锁、损坏尾修复与格式版本通道 | `session/session-persistence-jsonl/src/storage.ts:35-60,85-118,186-224,270-339`; `lease.ts:1-28,39-60`; `format.ts:1-43,194-280`；S；Windows 运行未验证 |
| DSH_CORE-017 | L9 状态观测 | Turn 级 token 精确归集按 attempt 事实验证，具 cached input/write、reasoning、total；失败样本不冒充精确 | `llm/token-meter/src/turn-usage.ts:6-35,81-139,170-275`；S；不等同用户账单价格精确 |
| DSH_CORE-018 | L3 Agent核心 | 压缩模型复用上下文前缀，另有无模型工具结果裁剪与 durable shadow-price | `compaction/compaction-basic/src/summarizer.ts:110-179`; `compaction-tool-result-pruner/src/index.ts:44-68,128-170`；S；触发策略在 Basic Engine |
| DSH_CORE-019 | L7 扩展生态 | MCP stdio/HTTP bridge 以 server/raw tool 稳定命名，断线重连、list changed resync 及注册撤销 | `mcp/mcp-client/src/index.ts:1-14,154-192`; `tools.ts:1-12,81-158`；S；需动态断线 |
| DSH_CORE-020 | L4 多Agent调度 | 实验 Agent Team 是独立 Service：持久化 Lead Session DAG tasks，member roster，spawn、message、wait、interrupt | `experimental/agent-team/src/index.ts:55-109,129-211`; `task-board.ts:28-255`; `journal.ts:55-70`；S；experimental，不等于默认开启 |
| DSH_CORE-021 | L5 工具执行 | 后台 jobs 对浏览器提供按 offset follow 与 kill；浏览读取不消费模型自己的 cursor | `api/job-controller/src/index.ts:1-8,75-115`; `jobs/jobs-local/src/pump.ts:53-86`；S；与 agent task 不同概念 |
| DSH_CORE-022 | L9 状态观测 | Trajectory 具有 turn/step/tool-call ledger、请求重试详情、prompt diff、虚拟化、timeline | `client/ui-trajectory/src/client/TrajectoryView.tsx:132-380`; `TrajectoryTable.tsx:2080-2257,3170-3194`；S；UI 是否在旧 npm 构建中 U |
| DSH_CORE-023 | L7 扩展生态 | CLI 是先选择 Profile 的薄启动器，后由可组合插件树解析内部命令，`plugin` 把操作交 pnpm | `apps/cli/src/args.ts:1-14,83-99,143-210`; `bin.ts:1-79`；S；发布 CLI 版本 U |
| DSH_CORE-024 | L4 多Agent调度 | schedule 是带持久化 delivery history 的 Host service；Goal round driver 带异步轮次/等待子 Agent | `schedule/schedule/src/index.ts:1-25,90-118`; `goal/goal-round-driver/src/index.ts:1-20,77-103,173-255`；S；默认启用需证实 |
| DSH_CORE-025 | L5 工具执行 | PTC node 支持独立 worker process 或保留作用域 REPL 状态；可选 sandbox 由 runtime 约束 | `ptc-runtime/ptc-runtime-node/src/index.ts:1-11,36-105,186-240`；S；需实际运行验证 |
| DSH_CORE-026 | L7 扩展生态 | 插件以 Cordis effect-scope 注册与卸载；插件管理用 pnpm/profile overlay 与原子写入 | `boot/plugin-manager/src/operations.ts:1-16,285-450`; `mcp/mcp-client/src/index.ts:154-192`；S；单独官方 host，非社区 Desktop |
| DSH_CORE-027 | L2 桌面宿主 | 实际 CLI 发布物将 launcher flags 与 booted profile 的 app flags 分层：首个未知 token 后续 argv 原样交给 app；`plugin` 把包操作转交 pnpm，三种 config dump 互斥，Desktop profile 拒绝 CLI 管理 | `extracted/cli/bin.js` (published 0.2.0-rc.2; `parseDshArgs`, `resolveBoot`, `runCli`); source comparator `apps/cli/src/args.ts`, `bin.ts` (0.2.1-rc.2)；S；静态发行 JS，不代表实际执行成功 |
| DSH_CORE-028 | L2 桌面宿主 | CLI npm 本体只有 launcher lib；其 82 项 direct runtime dependencies 外置，完整 Agent 引擎/profile bundle 不能从 CLI tar 单包推出 | `extracted/cli/package.json`, `cli-tree.txt`; source `apps/cli/package.json` 为 0.2.1-rc.2 / 86 项 workspace dependencies；S；单独 tar 不足；按该 manifest 安装的 npm runtime 依赖另见 034。Profile 是否按默认配置启动需实际 profile boot |
| DSH_CORE-029 | L1 界面交互 | Web npm 是 Vite 静态 dist；index preload 两主 JS 和样式，无 `.map`；0.0.1-rc.5 BSD-3-Clause 与 0.2.1-rc.2 源 app MIT/license、版本均不相同 | `extracted/web/index.html`, `web/package.json`, `web-assets-map.json`, `version-diff.md`；S；build-source 一一配对未知；minified 字符搜索不是能力缺失证据 |
| DSH_CORE-030 | L1 界面交互 | 在 shipped Web 25 个 JS 文件上按指定十词逐项收集命中与 UTF-8 byte offset；入口含 `session`/`prompt` 文本，但其他 chunk 的 `interrupt`/`job` 命中来自通用解析器上下文，不能映射到 Agent 功能 | `extracted/web-chunk-symbols.jsonl`；S；静态字符串不确认路由、控制、子代理、账单、团队或运行行为；动态 U |
| DSH_CORE-031 | L7 扩展生态 | Profile 是 ordered plugin bundle patch stack：bundle order → profile patch → per-home patch → argv `--patch` order → telemetry derived patch；bundle resolve 优先 installation anchor 后 profile node_modules，用户 profile packages 再经过 Node ESM/CJS runtime resolution | `apps/cli/src/profile-boot.ts:202-245,306-337`; `packages/boot/app-boot/src/profile.ts:179-237,740-840`; `profile-resolution/resolver.ts`；S；0.2.1-rc.2 source only；旧 npm profile composition U |
| DSH_CORE-032 | L2 桌面宿主 | boot 前冻结环境快照供每个插件读取，并从该 snapshot 安装 proxy 再 mount；SIGTERM/SIGINT 在启动过程就开始 teardown，分别返回 0/130，dispose coalesce、5s 后升级强退 | `apps/cli/src/profile-boot.ts:68-79,274-319,330-386`; `apps/cli/src/process-shutdown.ts:1-72`；S；source code path；没有触发 signal / proxy 的 R 证据 |
| DSH_CORE-033 | L2 桌面宿主 | 新源码存在 CLI release 82 依赖中的 73 个同名 DSH packages，但源码版本皆为 `0.2.1-rc.2`、CLI tarball pin `0.2.0-rc.2`；Web `dsh-client-web` 同样从发布范围 `^0.0.1-rc.5` 到源码 `0.2.1-rc.2`，无一版本完全吻合 | `extracted/source-versions.json` 的 `release_dependency_pairs`；总结 `extracted/version-diff.md`；S；可确认包名关系与版本不一致，不可确认源代码逐行变化或 binary equivalence |
| DSH_CORE-034 | L2 桌面宿主 | 用已验签 CLI tarball 作为 root 执行 `npm install --ignore-scripts`，精确取得 `0.2.0-rc.2` 的 Agent loop/session/JSONL/API/subagent/Web glue 与 UI 依赖包；这些实际发布 JS 直接确认 durable step/tool recovery、session cursor/control RPC、子代理 cold resume/flush，以及 Web 前端注入型宿主。CLI `--version`/`--help` 在 Node 中真实运行成功 | `extracted/published-runtime-packages.json`（每个包的 registry integrity、入口 SHA/长度及精确 release version）；CLI 实物 `extracted/cli/bin.js`；本地安装包按上述 integrity 对照的入口文件；S (npm release package static) + R (launcher flags only)；npm 包代码静态读；没有启动 profile、Agent、HTTP/WebSocket 服务或模型，所以 runtime 行为不标 R；`0.2.1-rc.2` 源码仍是不同版本，不能替代逐行版本 diff |
| DSH_CORE-035 | L1 界面交互 | 新源码的 composer submit 到 session wrapper；对 addressed child 改走 `subagents.prompt`，并把队列更新经 `session.updateQueue` 路由至 host command。Web 子代理目录和右侧 child Session 对应服务端持久地址及 follow/control | `packages/client/ui-conversation/src/client/service.ts:250-300`; `api/session-controller/src/client/sessions/session.ts:254-357,330-338`; `api/session-controller/src/index.ts:461-505,524-603`; `client/ui-subagent/src/client/index.ts:52-101`, `SubagentHeaderLineage.tsx:196-395`；S + R-synthetic (Session, queue/input component tests)；固定源码 `687f282e`；Web npm `0.0.1-rc.5` 与新源码不等价；未观察到 live packaged UI |
| DSH_CORE-036 | L8 服务连接 | Host 的 generic session controls 会对 runtime-owned child 拒绝；普通根 Session prompt/updateQueue 与 child addressed RPC 分离，避免 UI 直接操作 child 时丢失 parent authority | `api/session-controller/src/index.ts:461-505`; `api/session-controller/src/commands.ts:319-418`; `api/session-controller/tests/session-cold.host.spec.ts`; `packages/subagent/subagent/src/control.ts:16-104`；S + R-synthetic (`session-cold.host.spec.ts` passed)；按固定快照源码的 synthetic test harness 实测；非跨进程、真人 UI 或真实 provider 运行 |

## DSH Desktop（40 条）

源：[原始发现与证据](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-dsh-desktop/docs/research/agent-reverse/2026-10-19/dsh-desktop/DISCOVERY-LEDGER.md) / [当前研究完成门槛](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-dsh-desktop/docs/research/agent-reverse/2026-10-19/dsh-desktop/FINISH-GATES.md)

| ID | 所属层 | 是什么、用来干什么 | 证据/现状（原始记录） |
|---|---|---|---|
| DSH_DESKTOP-001 | L2 桌面宿主 | 社区 Electron/Node 子 Host 进程，而非新 Agent loop | A package.json main；src/host-process.ts:228-319 spawn/IPC；S |
| DSH_DESKTOP-002 | L2 桌面宿主 | 调用官方 runProfile 装配 DSH Web/Cordis | A src/host/index.ts:28-80；src/profiles.ts:290-357；S |
| DSH_DESKTOP-003 | L8 服务连接 | 以 loopback 随机端口替换官方 WebServer | A host.cordis.patch.yml；src/webserver.ts；S |
| DSH_DESKTOP-004 | L2 桌面宿主 | 结构化 child IPC ready、fatal、permission、platform-login、notification、injections、update-tasks | A src/host-process.ts:251-319；src/host/index.ts:96-125；S |
| DSH_DESKTOP-005 | L2 桌面宿主 | 后端启动串行化/取消、清理失败 AggregateError、保留根因 | A src/backend-controller.ts:33-172；S |
| DSH_DESKTOP-006 | L7 扩展生态 | Profile 创建/切换、Cordis patch 注入和可选 bundles | A src/profiles.ts:18-49,76-215,290-357；S |
| DSH_DESKTOP-007 | L8 服务连接 | browser-access 拒绝 HTTP + WS upgrade，并撤销既有 browser socket | A src/webserver.ts:setBrowserAccess/registerUpgrade；S |
| DSH_DESKTOP-008 | L1 界面交互 | 官方客户端 Slots 注入桌面设置、权限、市场按钮、原生文件夹、onboarding | A src/client/index.ts:31-100；S |
| DSH_DESKTOP-009 | L6 会话存储 | 安全模式独立临时 home、Profile checkpoint/recover | A src/desktop-runtime.ts:85-145；src/recovery.ts:10-180；S，限配置快照 |
| DSH_DESKTOP-010 | L1 界面交互 | 托盘动态 Profile/终端/诊断/恢复/更新/浏览器等命令 | A src/desktop-menu.ts:6-35；src/desktop-contract.ts:94-115；S |
| DSH_DESKTOP-011 | L7 扩展生态 | 本地 community market 有独立 Host route 与 React 设置 UI | A dsh-community-market/src/host/routes.ts；src/client/MarketSettingsTab.tsx；S 文件存在，默认启用 U |
| DSH_DESKTOP-012 | L7 扩展生态 | AA bridge remote control、Market、官方 Market 均为可选 bundle | A src/profiles.ts:20-27,45-49；A Next package.json vendored AA；S 装配，外部服务运行 U |
| DSH_DESKTOP-013 | L2 桌面宿主 | runtime payload inventory/checksum、更新安装与 LAN/HTTPS 组件 | A src/runtime-tree.ts；src/update-installer.ts；src/lan-https-*；S 结构，R 未测 |
| DSH_DESKTOP-014 | L9 状态观测 | jobCompleted/jobFailed 字段保留作兼容但默认永远 false | A src/desktop-contract.ts:30-42；S；不是正常任务通知 |
| DSH_DESKTOP-015 | L5 工具执行 | 电脑使用/Office/Skill badge 原生资源路径接入 | A src/host/index.ts:36-44；src/host/cua-driver.ts；cordis.patch.yml；S；native CUA driver 默认 disabled |
| DSH_DESKTOP-016 | L2 桌面宿主 | Tauri + React 管理壳，官方 WebUI 外嵌 | B package.json；src/App.tsx:17-20；src-tauri/src/lib.rs:295-318；S |
| DSH_DESKTOP-017 | L1 界面交互 | 引擎就绪后 navigate 主 WebView，取代原 React JS，非独立 Agent UI | B src/App.tsx:~270-320；src-tauri/src/lib.rs:158-209；S |
| DSH_DESKTOP-018 | L2 桌面宿主 | 探测常见端口并复用；按 engine-instance.json + PID 判 owned | B src/lib/dshEngine.ts:51-53,479-635；S；401 误判风险 |
| DSH_DESKTOP-019 | L2 桌面宿主 | Cookie + Rust POST /api/session/list 业务 readiness，而非只看 TCP/HTTP | B src/lib/dshEngine.ts:~650-770；Rust lib.rs:229-292；S，30秒超时放行 |
| DSH_DESKTOP-020 | L8 服务连接 | 从 ~/.dsh/.credentials.yaml 读取官方签名 secret，构造 HMAC cookie | B src/lib/engineAuth.ts:24-120；Rust lib.rs:170-209；S |
| DSH_DESKTOP-021 | L2 桌面宿主 | 多候选 node/npx/dsh spawn、stderr 尾、进程退出、残留写锁清理 | B src/lib/dshEngine.ts:154-361,~800-1000；S |
| DSH_DESKTOP-022 | L1 界面交互 | 系统托盘管理页重返、重启、测试版升级、留后端退出/全退出 | B src-tauri/src/lib.rs:~320-465；S |
| DSH_DESKTOP-023 | L2 桌面宿主 | 版本并存/更新/rollback/已验证列表 | B src/lib/updater.ts；src/components/TitleBar.tsx；StatusBar.tsx；S |
| DSH_DESKTOP-024 | L7 扩展生态 | --patch 目录选择和官方 web-search 计费覆盖 | B src/lib/enginePatch.ts:33-70,108-186；S |
| DSH_DESKTOP-025 | L1 界面交互 | key manager/安装器/沉浸/快捷键 | B src/components/KeyManagerDialog.tsx；EngineLauncher.tsx；src/App.tsx；S 壳端；导航后不可见 |
| DSH_DESKTOP-026 | L2 桌面宿主 | restartEngine/quit_all 按端口 PID 可强杀外部复用实例 | B src/lib/dshEngine.ts:restartEngine；Rust lib.rs:37-70,128-145；S，关键风险 |
| DSH_DESKTOP-027 | L7 扩展生态 | codebuddy-mcp、dsh-balance、dsh-tauri-dir-picker 为附属 tools | B tools/；src/lib/enginePatch.ts:isTauriDirPickerMounted；S 存在，实际挂载 U |
| DSH_DESKTOP-028 | L2 桌面宿主 | 官方宣称跨平台，但多处 Windows hardcoded 路径、cmd/taskkill | B src/lib/dshEngine.ts、src/lib/engineAuth.ts、Rust lib.rs；I/U，不代表全平台可用 |
| DSH_DESKTOP-029 | L1 界面交互 | 子代理递归展开、运行指示、Token 使用和时长投影 | O packages/client/ui-subagent/src/client/SubagentHeaderLineage.tsx:190-350；S |
| DSH_DESKTOP-030 | L1 界面交互 | 子代理主会话/右侧栏导航，精确 parent/child/mode address、SessionReference | O ui-subagent/src/client/index.ts:43-99；sidebar-chat/index.tsx:18-201；S |
| DSH_DESKTOP-031 | L1 界面交互 | one-shot 只读，continuable 根据 parentAvailable 切 composer、可独立 Stop | O ui-subagent/src/client/index.ts:33-52；README.md；S+D；Host RPC 实测 U |
| DSH_DESKTOP-032 | L9 状态观测 | 工具/请求/消息轨迹映射、检索、时间轴与历史分页 | O packages/client/ui-trajectory/src/client/TrajectoryView.tsx；trajectory-event-projection.ts；S |
| DSH_DESKTOP-033 | L7 扩展生态 | 官方 packages/subagent,experimental/agent-team,mcp,skill,jobs,session 等存在 | O 对应 package 树；S 文件存在，不等于默认装载 |
| DSH_DESKTOP-034 | L2 桌面宿主 | Next 2.0.19-next 实际随包携带官方 `@deepseek-ai/*@0.2.1-rc.2` runtime，而非只引用空 deepseek-harness gitlink | ZIP `vendor/dsh-runtime/0.2.1-rc.2/manifest.json` 343/343 tarball SHA 匹配；`A-runtime-symbol-index.md`；S（包内元数据+tarball digest） |
| DSH_DESKTOP-035 | L6 会话存储 | Agent Inbox 为两路 event-sourced 队列：`next-turn` 和 `next-step`；claim 消费并记录生命周期事件 | `@deepseek-ai/dsh-agent-loop@0.2.1-rc.2` tar `lib/index.js:70-204,806-813`；事件 `agent/inbox/spliced`；S（真实 A 源包内嵌 tarball） |
| DSH_DESKTOP-036 | L1 界面交互 | UI projection/RPC/controller 具备队列回显、request-ID 去重、edit/remove/steer 变更；冷 Agent 会 resolve/restore 后再改 durable inbox | `@deepseek-ai/dsh-client-ui-chat` `lib/client.js:2757-2847`；`dsh-api-session-controller` `lib/index.js:925-950,1004-1054,2689`，wire `typert.remote-client.js:1912-1938`；S；具体按钮到 RPC 的映射 U |
| DSH_DESKTOP-037 | L2 桌面宿主 | 同版本有多个不同构建：必须核对来源哈希确定运行包 | A `vendor/agents-anywhere/provenance.json` + `*.tgz`；详见 `A-vendor-package-index.tsv`；S 文件/哈希；Profiles 默认关 AA bridge；运行加载 U |
| DSH_DESKTOP-038 | L1 界面交互 | 打包的Next Web端未找到队列编辑/删除/steer入口；同名命中是React内部 | A `package.json:209`; embedded tarball SHA `c797fa5fce3375c78b2afe7458864bb5b23814eef80013e510ad9a1f8bfbfbda`; chunk SHA/bytes in `COVERAGE.md`.；S, exact pinned build only |
| DSH_DESKTOP-039 | L2 桌面宿主 | Next可构建、Node Host可启动，但Electron GUI未能取得运行证据 | `extracted/RUNTIME-OBSERVATIONS.md`; `END-TO-END-TRACES.md`.；R host lifecycle only; no GUI/Agent |
| DSH_DESKTOP-040 | L2 桌面宿主 | 社区Tauri桌面仅是外部官方DSH Web的管理壳，Agent功能不归它实现 | `IMPLEMENTATION-TRACE.md` B cold-start/business readiness/navigation sections; B `src-tauri/src/lib.rs:158-293`.；S boundary; actual external UI/version U |

## OpenCode（19 条）

源：[原始发现与证据](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-opencode/docs/research/agent-reverse/2026-10-19/opencode/DISCOVERY-LEDGER.md) / [当前研究完成门槛](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-opencode/docs/research/agent-reverse/2026-10-19/opencode/FINISH-GATES.md)

| ID | 所属层 | 是什么、用来干什么 | 证据/现状（原始记录） |
|---|---|---|---|
| OPENCODE-001 | L2 桌面宿主 | v2 **拆分运行时包**，不是旧版原路径的小改动 | v1 `packages/opencode/src/session/prompt.ts`; v2 `packages/core/src/session/session.ts:39-48`, `packages/server/src/handlers/session.ts:35`；S；v1 原 `packages/opencode` 路径在 v2 树中不再存在；行为差异需逐项比较 |
| OPENCODE-002 | L6 会话存储 | **持久化待处理输入**，用户消息 admission 与 execution 解耦，`steer`/ `queue` 可修改或取消 | `core/src/session/session.ts:118-185`, `core/src/session/inbox.ts:240-415`, `core/src/session/sql.ts:119-149`；S；先 admission 到 SQLite，再 wake；队列不是前端数组 |
| OPENCODE-003 | L6 会话存储 | **持久化执行 claim** 与 terminal 同事件提交；shutdown 留 claim，主动取消释放 | `core/src/session/execution.ts:65-149`, `core/src/session/store.ts:62-72`；S；孤儿 turn 被重启 sweep 识别 |
| OPENCODE-004 | L6 会话存储 | **重启恢复有界重试**；恢复子 Agent、后台 shell 也分类处理 | `core/src/session/execution/restart.ts:17-57,70-219`；S；默认每 turn 10 次 resume；at-least-once 并非外部副作用 exactly-once |
| OPENCODE-005 | L4 多Agent调度 | **后台子代理并非只开线程**：Child Session、Job、关联父会话通知可恢复 | `core/src/tool/plugin/subagent.ts:110-260`, `core/src/session/subagent-job.ts:12-71`, `subagent-completion.ts:21-45`；S；background 立即返回 child ID，完成时 synthetic 入父会话 |
| OPENCODE-006 | L4 多Agent调度 | **子代理继续同一 child Session**、agent/model 切换、父子归属验证、深度限制 | `core/src/tool/plugin/subagent.ts:29-46,110-209`；S；不是每次 spawn 都必须丢上下文；默认配置深度约 1 可调 |
| OPENCODE-007 | L3 Agent核心 | **模型输出流与并行工具 fiber**，事件在开始/结束上维护顺序；工具执行前确保持久发布 Tool.Called | `core/src/session/runner/step.ts:67-192`；S；provider streaming 与本地工具相互编排，取消时等待/清理工具 fiber |
| OPENCODE-008 | L3 Agent核心 | **可解释的重试策略**：退避、上游 Retry-After、timeout 子预算、插件 hook 可调整 | `core/src/session/runner/retry.ts:31-116`；S；10 次通用重试序列、单次间隔上限逻辑，超时最多 3 次 |
| OPENCODE-009 | L3 Agent核心 | **按阶段选定上下文**：agent/permissions→tools/skills/MCP/instructions→model/history | `core/src/session/context.ts:83-185`；S；cache 友好前缀顺序，禁用工具不应仍注入其技能说明 |
| OPENCODE-010 | L3 Agent核心 | **自动/手动/overflow 压缩** 和错误状态 | `core/src/session/compaction.ts:41-63`, `runner/step.ts:135-159`；S；provider 还未输出就 overflow 可紧接压缩；细节策略见压缩源码 |
| OPENCODE-011 | L9 状态观测 | **事件投影与 token/cache/费用账目**：消息和成本合并投影 | `core/src/session/projector.ts:49-92`, `core/src/session/sql.ts:22-96`, `core/src/session/usage.ts:11-53`；S；usage 字段 input/output/reasoning/cache read/write 与 cost |
| OPENCODE-012 | L7 扩展生态 | **动态插件生命周期监督**（本地目录/npm、安装、失败/阻止、热变更、版本更新） | `core/src/config/plugin/source.ts:20-160`, `core/src/plugin/module.ts:73-150`, `supervisor.ts:150-245`；S；加载后由 registry 重新激活，配置源/文件变更触发 |
| OPENCODE-013 | L7 扩展生态 | **插件可跨能力扩展**：agent/command/tool/provider/MCP/skill/permission/event/RPC/worktree 等 Effect/Preset Promise API | `packages/plugin/src/effect/*`, `packages/plugin/src/promise/*`, `core/src/plugin/host.ts:99-130`；S 仅接口存在；特定扩展实际可用还要逐插件验证 |
| OPENCODE-014 | L2 桌面宿主 | **Desktop 管理独立 CLI server**：选择随包 CLI、service ensure、复用早期探测连接 | `desktop/src/main/service/desktop-cli.ts:20-110`, `background-service.ts:24-102`；S；Electron 主进程不是 Agent 主引擎 |
| OPENCODE-015 | L2 桌面宿主 | **Electron MessagePort / Effect RPC**，连接及渲染器销毁时解绑；HTTP server另有事件流 | `desktop/src/main/ipc-transport.ts:1-122`, `server/src/event-feed.ts:1-91`；S；不要混淆本地窗口 IPC 与 Agent API |
| OPENCODE-016 | L8 服务连接 | **按 server / location 订阅与重连同步**；独立 request queue / 状态实例 | `app/src/runtime/server/client.tsx:1-124`, `server-sync/connection.ts:1-30`；S；UI 支持 sidecar/extension 等不同 server连接；具体同步冲突策略部分未追到底 |
| OPENCODE-017 | L1 界面交互 | **服务端会话输入队列 UI**：编辑/撤回/重排带服务器回执，避免原条目先被删 | `app/src/session/composer/queue.ts:30-109`；S；优先 admit replacement，再 cancel original；并发变化能报冲突 |
| OPENCODE-018 | L5 工具执行 | **Code Mode JS 工具编排**：多工具并行 JS、进度、文件输出 | `core/src/codemode/tool.ts:1-126`; `packages/codemode/*`；S；Code Mode 是独立受控运行时，不是普通 shell 工具；权限和依赖独立 |
| OPENCODE-019 | L1 界面交互 | **时间线虚拟化与进程任务定位**，远距定位指定 tool/shell，交互展开并确保尺寸测量 | `app/src/session/timeline/virtualizer.tsx:93-426`, `message-timeline.tsx:30-70`；S；性能/交互工程实际在 UI 代码，真实帧率 U |

## ZCode（48 条）

源：[原始发现与证据](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-zcode/docs/research/agent-reverse/2026-10-19/zcode/DISCOVERY-LEDGER.md) / [当前研究完成门槛](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-20261019-zcode/docs/research/agent-reverse/2026-10-19/zcode/FINISH-GATES.md)

| ID | 所属层 | 是什么、用来干什么 | 证据/现状（原始记录） |
|---|---|---|---|
| ZCODE-001 | L2 桌面宿主 | Electron 主进程 fork 独立宿主 utilityProcess，承载 agent、浏览器命令、远程会话、数据服务等回调 | desktopHostProcess.ts L157-300；S；已追源码 |
| ZCODE-002 | L3 Agent核心 | 正常回合循环依次排空后台命令、微压缩/自动压缩、MCP 增量刷新、装工具并执行模型步骤 | core/runtime/methods/turn-loop.ts L44-230；S；已追源码 |
| ZCODE-003 | L5 工具执行 | 工具先排程、写 pending tool part、发 queued/event，再按 AbortSignal 执行并结算 | core/runtime/methods/turn-tools.ts L30-168；S；已追源码 |
| ZCODE-004 | L4 多Agent调度 | 子代理根据 profile/请求选择 foreground/background；后台受模型借用条件约束；启动前 watchdog 与元数据写入 | core/subagent/runner.ts L110-260；S；已追源码 |
| ZCODE-005 | L4 多Agent调度 | 子 agent 模型/权限/MCP/Skills/持久记忆/父子溯源分别导出、过滤或继承 | core/runtime/methods/subagent.ts L65-230；S；已追源码 |
| ZCODE-006 | L4 多Agent调度 | 子代理回复通过 priority=next 的 runtime command 注入父模型上下文；分支代际失效消息被丢弃 | core/runtime/methods/subagent-messages.ts L25-107；S；已追源码 |
| ZCODE-007 | L4 多Agent调度 | 任务 registry 区分 agent/legacy workflow/dynamic workflow，提供后台切换、等待终态、待递消息 | core/runtime-task/registry.ts L10-245；S；已追源码；注意本表是内存层 |
| ZCODE-008 | L4 多Agent调度 | runtime command queue 按 now/next/later 优先级分发，能批量消费同级 task notifications、记录 cancel-pending | core/runtime/command-queue.ts L10-240；S；已追源码；本身非持久化 |
| ZCODE-009 | L4 多Agent调度 | Workflow 文本编译/lower 后经 Node 子进程运行，通过 NDJSON request/response、event 桥接到父引擎 | dynamic-workflow-runtime/src/harness.ts L1-225; protocol.ts L45-188；S；已追源码 |
| ZCODE-010 | L6 会话存储 | ask 以 siteId+ordinal、inputHash 与 journal 作为重放门；running 重派发、已完成命中缓存，hash 变化硬失败 | dynamic-workflow/src/engine/scheduler.ts L125-205；S；已追源码 |
| ZCODE-011 | L6 会话存储 | 改版续跑 ImportedAsk 缓存受首个写工具副作用约束；无副作用 ask 有条件复用 | dynamic-workflow/src/engine/scheduler.ts L205-289；S；已追源码 |
| ZCODE-012 | L4 多Agent调度 | 并发治理：429 切 epoch 并降低上限、Retry-After 冷却、成功 streak 后渐进增大 | dynamic-workflow/src/engine/concurrency.ts L25-37, L120-275；S；已追源码 |
| ZCODE-013 | L6 会话存储 | workflow 中断与脚本错误区分：interrupted/stopped 可恢复，脚本错误不是同一状态 | dynamic-workflow-runtime/src/harness.ts L1-31, L~185; engine-state.ts L28-35；S；已追源码 |
| ZCODE-014 | L6 会话存储 | resume 从 journal 还原节点/结算顺序/报告计数，不依赖 UI 缓存 | dynamic-workflow/src/engine/engine-resume.ts L17-44; scheduler.ts L110-170；S；已追源码 |
| ZCODE-015 | L6 会话存储 | SQLite dwf_* journal 按端口与引擎分离，事务场景 driver begin immediate | adapters/storage/session-store/repositories/dwf-journal.ts L1-84；S；已追源码 |
| ZCODE-016 | L9 状态观测 | 模型使用数据分请求/turn 落库：输入输出、推理、缓存创建/命中、重试和 TTFT；留存 30 天 | adapters/storage/session-store/repositories/usage.ts L17-25, L130-166, L166-248；S；已追源码 |
| ZCODE-017 | L3 Agent核心 | Context 超限前微压缩/自动压缩，压缩 telemetry 记录 token 来源并区分手动/自动；压缩调用有尝试上限 | core/runtime/methods/turn-loop.ts L78-113; compact-active.ts L73-122；S；已追源码 |
| ZCODE-018 | L6 会话存储 | 会话 fork 需要 remap 消息、part、turn、tool call ID；不是只复制文字 | core/runtime/methods/session-fork.ts L219-235；S；已追源码 |
| ZCODE-019 | L7 扩展生态 | MCP 连接池、stdio、OAuth、elicitation、工具变更通知以及资源订阅；tools/list_changed 回合间刷新 | adapters/mcp/index.ts L105-168, L205-215, L498-502; turn-loop.ts L117-121；S；已追源码 |
| ZCODE-020 | L7 扩展生态 | 插件市场整合插件 Hook/MCP/UI surface；Skills 扫描兼容 ZCode/Claude/Codex/Cursor 多种 manifest | adapters/plugins/index.ts L39-107; adapters/skills/index.ts L29-60；S；已追源码；扩展不等于核心功能 |
| ZCODE-021 | L7 扩展生态 | 官方宿主 MCP Apps 走 renderer MessagePort JSON-RPC / AppBridge，支持调用工具、读取资源、更新模型上下文 | ui/plugin-ui/adapters/messagePortTransport.ts L5-40; ui/plugin-ui/app/pluginUiHostBridge.ts L38-122；S；已追源码 |
| ZCODE-022 | L7 扩展生态 | Electron MCP 插件 UI 有独立 guest、持久 partition、owner 关联、permission gate 与 dispose 生命周期 | desktop/main/pluginSandbox/host.ts L49-205；S；已追源码 |
| ZCODE-023 | L1 界面交互 | Workflow 的相位、参与者、artifact、provenance、设置调整/恢复动作分别投影到侧栏；图表可展示完整视图/迷你图 | ui/app-shell/WorkflowRunSidePane.tsx L5-58; workflow-artifacts/presets/ArtifactChartView.tsx L8-10, L320-372；S；已追 UI 源码；未实测 |
| ZCODE-024 | L4 多Agent调度 | Cron scheduler 是另一 Electron utilityProcess，dispatch 到合适 Host；Host 不存在按 transient 错误退避 | desktop/main/desktopCronScheduler.ts L60-210；S；已追源码 |
| ZCODE-025 | L8 服务连接 | 服务层有带 Etags 的任务快照、命令入队/升优先级/取消、会话续接、许可回应；扩展到 Feishu WebSocket 群通道 | services/session/zcodeTaskService.ts L199-650; services/bots/feishuChannelRuntime.ts L39-129；S；已追源码；可用性待实测 |
| ZCODE-026 | L9 状态观测 | 官方发布说明提到 3.15.3 的并行 Agent/快速调用请求失败修复、启动/登录问题；与 3.15.1 非同版 | 2026-10 官方 changelog（见证据索引）；D；只能确认官方说法 |
| ZCODE-027 | L2 桌面宿主 | 3.15.3 CJS 是否实际包含相同 Scheduler/Agent/Command/插件实现、增删了哪些 IPC | Release asset 与 3.15.3 app.asar；U；**BLOCKED**，见提取任务 |
| ZCODE-028 | L2 桌面宿主 | Desktop 3.15.3 ASAR package manifest 明确为 `@zcode/desktop@3.15.3`、ESM main=`out/main/index.js`；内嵌运行入口元数据为 Electron Node、`zcode.cjs`、win32-x64，来源标成 `apps/zcode-cli/packages/cli/dist/zcode.cjs` | SHA-verified EXE；`resources/app.asar.extracted/package.json`; `resources/glm/.node-bundle-meta.json`；S；已核验包身份/入口声明；实际 main/UI 模块图待补 |
| ZCODE-029 | L2 桌面宿主 | 3.15.3 `zcode.cjs` 是语法可解析的 15,127,039-byte CommonJS 脚本；Acorn 8.16.0 建出 3,458,803 AST nodes / 58,079 functions / 231,843 calls，含 `__webpack_require__` 数字模块表锚点；无 source map，函数多数缩名，不能还原源码路径 | SHA `31965ce1...506a54`; wrapper byte 2,489,228; AST 统计见 `extracted-3153/CJS-MODULE-INDEX.tsv`；S；同版包已解析；匿名/缩名模块映射仍未知 |
| ZCODE-030 | L5 工具执行 | 运行时从模型 tool-call 结果进入 `scheduleTools` 状态转换，落 `tool_queued` event，再 `executeTools`；同时有独立 `persistPendingToolPart` 持久化函数 | 同版 CJS bytes 13,192,839..13,193,404 (`gBe`) 与 13,205,979..13,210,657 (`qwt`)；S；静态调用链候选已锁定；未运行验证 event 时序 |
| ZCODE-031 | L4 多Agent调度 | `InMemoryRuntimeTaskRegistry` 保存 active branch generation、background waiters、task map、terminal waiters；`register/update` 路径会 resolve terminal/background waiter | 同版 CJS bytes 5,042,044..5,044,543（registry class init）；关键状态在 5,042,191+；S；进程内 registry 实物证据；跨重启仍要结合 SQLite journal 论证 |
| ZCODE-032 | L4 多Agent调度 | Child runner 在 `SubagentSpawned/Stopped` 事件序列中关联父/子 ID；foreground 已转后台时调用 `detachParent()` 并保留 child Promise 的异步结果处理；service `backgroundTask` 将 registry 请求设后台 | 同版 CJS bytes 12,715,173+ 与 12,716,232+ (`run`), registry method `requestBackground` 5,042,679+；S；包内代码存在；实际并发、取消、回流未运行观测 |
| ZCODE-033 | L6 会话存储 | 3.15.3 包内 DWF journal migration 使用 `dwf_run`/节点 activity 表；schema 保留 call path、attempt、input_hash、queued/running/completed/failed/skipped 等节点状态；运行时另含 `inputHash`、`actorSeq` 与 replay input hash mismatch 错误 | 同版 CJS migration bytes 1,515,023..1,543,238 (`0019_dwf_journal` 1,540,263; `dwf_run` 1,540,320; `input_hash` 1,523,765); replay helpers 12,513,514..12,524,192 (`InputHashMismatch` 12,524,144)；S；schema/部分 replay helpers 已定位；transaction driver、完整 harness 到 SQLite 调用链待续 |
| ZCODE-034 | L3 Agent核心 | CJS 中既有通用 SDK `V9s` retry-after helper，也有 model request parser `qXr` + retry diagnostic `HB` 与 retry source classifier `sHs`；读取 retry-after-ms、retry-after 秒/HTTP-date，并记录 delay、reason/header/source 等诊断字段 | `V9s` 3,898,082..3,898,491; `qXr` 4,007,148..4,007,440; `HB` 4,097,229..4,097,847; `sHs` 4,099,067..4,099,316；S；已定位 request retry telemetry；与发布说明所称并发 Agent 修复的关联仍为 U |
| ZCODE-035 | L2 桌面宿主 | 留存的 3.15.3 desktop ASAR extracted tree contains distinct main/host/preload/renderer/scheduler/plugin-sandbox bundles; package root app.asar 340,516,766 bytes SHA `3fb4104d...b4120283`; selected JS bundles separately rehashed | `extracted-3153/DESKTOP-IPC-ANCHORS.md`; exact staged file SHA/sizes recorded there；S；root ASAR REA timed out; unpacked node-pty integrity contradiction remains; individual extracted JS not yet compared to declared ASAR entry integrity |
| ZCODE-036 | L2 桌面宿主 | Main generated service facade includes agent/task/session/subagents/commands/hooks/memory/MCP/plugin UI bridge/sampling/app-tools; host creates RPC clients from a MessagePort-like transport; preload bridges plugin sandbox API to ipcRenderer.invoke | `main/chunk-JS2T33SG.js` bytes 900..4,724; `host/index.js` 1,485,135..1,485,368; `preload/index.cjs` ~731,937..732,400; bundle digests in `DESKTOP-IPC-ANCHORS.md`；S；Concrete client and transport wrappers found; process caller/transfer and UI event subscription not yet linked |
| ZCODE-037 | L3 Agent核心 | Current Atlas main has live FastAPI runtime websocket protocol; SQLite stores run lifecycle metadata while replay reads in-memory run.events; delegation runs actual model/tool/permission checks and background tasks; no DWF actor/input-hash/node journal or MCP Apps sandbox bridge found in checked paths | Atlas line references consolidated in `ATLAS-GAP.md` section “本轮复核”; base main SHA `aa6196f550098cc46081dc6db2c376cb87ddffa5`；S；Feature-by-feature static comparison only; per-gap negatives remain bounded to searched files |
| ZCODE-038 | L7 扩展生态 | 3.15.3 desktop MCP App support includes typed `mcp/ui*` resource/app-tool routes and host RPC, plus main-side provenance-bound instance registry, app-specific shell URL/partition/CSP, permissions, expiry/pin/user-gesture state; sandbox bundle contains MCP Apps initialize/resource protocol | `host/chunk-OUCOFHX4.js` 522,497/682,652–685,796; `host/index.js` 343,997/347,156; `main/index.js` 417,930–420,500; `plugin-sandbox/gen-ui.js` 595,913/603,656/612,362；S；Static app host mechanisms confirmed; renderer attach, resource/consent, model tool injection/result flow and runtime remain U |
| ZCODE-039 | L7 扩展生态 | Atlas current capability catalog explicitly lists MCP Apps as missing; checked current MCP client/capability implementation does not contain the same embedded app instance/sandbox or app-tool RPC contract | `core/atlas/evolution/capability_diff.py:232`; bounded comparison in `ATLAS-GAP.md`; base SHA `aa6196f550098cc46081dc6db2c376cb87ddffa5`；S；Missing claim scoped to exact files/catalog paths read, not assertion every Atlas module lacks any similar concept |
| ZCODE-040 | L2 桌面宿主 | Complete ASAR header inventory has 27,856 files and 22,902 JS/TS/HTML-family files (274,190,048 bytes). Acorn parsed 18,936 JS/CJS/MJS entries; 7 parser failures and 2 directory/link aliases are listed. All 2,794 `out/` code files parse. | `COVERAGE.md`; ASAR SHA `3fb4104ddcd79e9808eede75192299a22057bd9c336e15b9c2bb1825b4120283`；S；TS/HTML inventory not fully parsed; routes/actions/registrations not exhausted |
| ZCODE-041 | L2 桌面宿主 | Retained 3.15.3 app starts to local Electron page; CDP identifies ZCode 3.15.3/Electron 41.0.3. Six child processes used default ZCode user profile, so process tree was stopped. | REA `ev_49e6e6ea5689b868e98358ce0348ca05ec529fb74d25a2ad8391cf86c235c0d2`, `ev_dc5735b0dfdda2f1527d9551626b2ed373b9d12085b6a5b4ce9474316277f966`; `END-TO-END-TRACES.md`；R；No message/tool/child/restart action; unsafe/inconclusive G4 probe |
| ZCODE-042 | L7 扩展生态 | Renderer decodes `pluginUi.appToolCall` and dispatches to MCP Apps `notifyAppToolCall`. | `out/renderer/assets/parts-1PK4PulD.js` byte 5,622; `out/renderer/assets/styles-CSpM3qgc.js` bytes 1,044,668 and 1,122,039；S；Producer, app attachment, host delivery and model result return remain U |
| ZCODE-043 | L7 扩展生态 | Host `openMcpUiInstance` and typed app-tool register/claim/resolve routes are correlated with main provenance-bound registry/schema. | `out/host/index.js` byte 343,993 and ~347,156; `out/host/chunk-OUCOFHX4.js` byte 682,652 onward; `out/main/index.js` bytes 417,930–420,500; `out/main/chunk-OW6EUS2G.js` bytes 717,781–721,431；S；Host provider and renderer caller remain unlinked |
| ZCODE-044 | L7 扩展生态 | MCP Apps sandbox packages `ui/initialize`, `ui/resource`, teardown handlers and `window.postMessage` transport. | `out/plugin-sandbox/gen-ui.js` bytes 595,913, 603,656, 612,362, 619,917；S；Not equivalent to Electron IPC/MessagePort; renderer forwarder and runtime origin validation U |
| ZCODE-045 | L2 桌面宿主 | ASAR header declares two unpacked node-pty binaries whose retained files differ by bytes and SHA. | `COVERAGE.md` exact entry/file digests；S；Native terminal companion integrity unresolved; packed JS findings remain bounded to their own verified bytes |
| ZCODE-046 | L2 桌面宿主 | 3.15.1 source and 3.15.3 package share selected tool schedule, journal and MCP App names/contracts; no complete function equivalence is inferred. | `RUNTIME-DIFF-ANCHORS.md`, `END-TO-END-TRACES.md`；S/I；Only named anchors compared; unmatched/changed code remains U |
| ZCODE-047 | L2 桌面宿主 | Main forks the Host utility, transfers a MessageChannel port to Host and its peer to renderer ServicePort; window reload reattaches with AttachServicePort (`desktop-continuous`, local scope). | `out/main/index.js` UTF-8 offsets 516,642, 524,824, 588,765; `END-TO-END-TRACES.md`；S；Confirms service transport and renderer reattachment only; does not prove Agent/task cold recovery |
| ZCODE-048 | L7 扩展生态 | Same-version Host facade exposes `openMcpUiInstance`, app-tool register, claim, resolve via typed service client. | `out/host/index.js` UTF-8 offsets 343,993, 347,156, 347,644, 347,895, 1,527,677; schemas/routes in `host/chunk-OUCOFHX4.js` and `main/chunk-OW6EUS2G.js`；S；Host provider implementation, renderer mount/forwarder and model-visible result remain U |

## 不能误报为已找齐的部分

- 上述八条研究分支的 FINISH-GATES 多为 PARTIAL / WORK IN PROGRESS；很多路由、菜单、命令、Host RPC、插件注册和运行动态未查完。
- Claude Code、Claude Desktop 等部分条目来自官方文档或静态字符串，不保证当前安装包启用。
- 云端服务的私有源代码无法由桌面包凭空得到，只能按客户端协议和可观察行为验证。
- 各研究原先常以旧 main 为 Atlas 对照，需先确认实际运行版本再判缺失。
- 同类机制跨产品重复出现。本目录是源事实总账，不是已去重、已验收的 Atlas 落地清单。
