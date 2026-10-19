# Codex CLI / TUI：真实入口、事件与工作流

**范围**：仅 Codex 0.163.0 CLI/TUI 与对应 app-server / Core 源码，不推断 Codex Desktop。本文所有操作均为源码静态路径 S，**没有登录、Windows EXE 实机截图或交互复现（R=0）**。命令存在不等于默认可见/当前账户可用。

## 1. 从命令输入到 Core

- codex-rs/tui/src/slash_command.rs:12-321 定义 SlashCommand、description()、command()、supports_inline_args()、available_in_side_conversation()、requires_dispatch_validation()、available_when_thread_unavailable()、available_during_task() 和 is_visible()。因此命令表具有 **注册、菜单可见、会话侧路/活动任务可用** 多个不同条件，而不是所有变体始终显示。
- codex-rs/tui/src/app_command.rs:99-212 的 AppCommand 是 UI 对核心动作的表达，包含 Interrupt、CleanBackgroundTerminals、ReloadUserConfig、Compact、执行与审批动作、输入答复等。需要再追 app.rs 的具体 match 分支，才能证明每个命令最终生效。
- codex-rs/tui/src/session_queue_commands.rs:1-130 包含 run_session_queue_command / run_session_queue_action_with_app_server，排队用户消息既可走本地也可走 app server。具体多进程可靠性未实测。
- codex-rs/tui/src/daemon_recovery.rs:1-198 含兼容性恢复入口：仅托管场景、需要新确认、恢复后一次兼容检查，不能推断自动无限重启。
- codex-rs/core/src/session/turn_input.rs:90-230 的 PreparedTurnInputSettings 将校验与提交分离；328-689 的 start_or_steer 区分启动空闲 Turn 和对活动 Turn 追加输入。

## 2. 按用户操作组织的工作流（静态入口与预期状态）

| 用户行为 | UI 入口与源码 | Core 或背景机制证据 | 实时反馈与限制 |
|---|---|---|---|
| 开新会话 | SlashCommand::New，:92 的说明；session_start.rs、app.rs | thread_manager.rs::NewThread；Core SessionConfigured 初始事件 | 需动态核对空白状态、首条消息持久化及断网处理 |
| 恢复已有会话 | /resume、resume_picker.rs、session_resume.rs | thread_manager.rs、rollout、daemon_recovery.rs | 不能仅凭恢复列表确定正在进行的工具/子线程可以无损复现 |
| 会话复制/工作树隔离 | /fork、/worktree、managed_worktree_tools.rs | ThreadManager ForkSnapshot；agent/control/spawn.rs 的 fork history 是另一条子 Agent 路线 | 对话 fork、工作树 fork、子代理 fork 必须分别定义 |
| 任务中追加话语 | 输入队列、AppCommand | core/session/turn_input.rs 的 start_or_steer；input_queue | 追加到下轮/打断当前采样依模式与 preempt，不是立刻改已开始的工具调用 |
| 多 Agent 创建、观察和切换 | /agents、/multiagents；multi_agents.rs | MAv2 spawn/send_message/wait/followup/list/interrupt；LocalAgentControl | spawn、等待、关闭、恢复事件显示为历史单元；无真实终端截图 |
| 背景终端管理 | /ps、/stop；AppCommand::CleanBackgroundTerminals | 工具执行与进程生命周期另在 unified_exec、exec-server | 终端进程 ≠ 子代理；要补测任务退出/进程存活和 cancel |
| 计划与审查 | /plan、/review、/recap | core 模式/审查任务模块存在 | UI 模式切换是否保持已有 turn 需核对实际 app 分派 |
| 上下文压缩 | /compact | core/session/turn.rs 预压缩；session/async_compaction.rs 条件推测压缩 | 明确区分主动指令、自动压缩、异步推测压缩 |
| 工具发现/扩展 | /skills、/mcp、/apps、/plugins、/hooks | core tools/registry、tool_search、plugins/mcp 等 | 插件类别/认证/工具加载启用条件待专案继续追 |
| 状态和用量 | /status、/usage、/rollout、/warnings、/debug-config、/statusline | session events、turn timing、rollout trace、TUI status | token/session/workflow 指标各自归属不同 |
| 其他可发现功能 | /voice、/goal、/side、/btw、/import、/memories、/daemon | 有独立模块与代码入口 | **入口只代表候选**；后续必须逐项查匹配实现、flag 和平台 |

上述命令及描述对应 codex-rs/tui/src/slash_command.rs:12-164；隐藏或调试命令不能当公开默认功能，特别是 MemoryDrop/MemoryUpdate 的 description 明写 DO NOT USE。

## 3. 多 Agent 动态呈现不是孤立的文本行

codex-rs/tui/src/multi_agents.rs:1-189 有 AgentPickerThreadEntry、SubAgentActivityDisplay、AgentMetadata、previous_agent_shortcut/next_agent_shortcut 以及按平台处理快捷键 fallback。:189-460 由 tool_call_history_cell 和 sub_agent_activity_history_cell 把 spawn/interact/wait/close/resume 过程投影到 history cell，包含 agent 状态、结果摘要和活动展示。底层 codex-rs/core/src/agent/control.rs:140-193 发送 ItemStarted 和 ItemCompleted，且可映射 legacy events；父 Agent 终态另由 control/completion.rs 通知。**这是事件源→投影 UI 的链路，而不是 UI 手工猜进程状态**。

## 4. Code Mode 在交互中的两段执行

code mode execute 用户/模型表达是 **JS source → CodeMode Cell**，底层不是逐个直接调用固定函数；codex-rs/core/src/tools/code_mode/execute_handler.rs:39-174 会：
1. 解析 code + yield_time_ms / max_output_tokens。
2. 为 nested tool 注入本次可用 schema + 命名空间。
3. 执行后给 cell_id、telemetry、rollout thread trace。
4. initial_response 为 Yielded 时保留 cell，在后续 wait；否则结束 dispatch。
5. JS 中调用工具时，Host 回调交 Core 本轮 ToolCallRuntime，再回结果。相关 source：core/src/tools/code_mode/delegate.rs:36-240、code-mode-host/src/grpc/mod.rs:63-289、code-mode-runtime/src/service.rs:65-198。

UI 可能先接到「开始」，之后才有真正结束或 yield。用单条「工具完成」覆盖两者会造成错误。缺 Windows 真实 event trace 和终端截图，仍为 S 而非 R。

## 5. 事件、状态、取消对照表

| 核心状态/信号 | 证据 | UI 应表达的事实 |
|---|---|---|
| Turn started / sampling / retry / preempt | session/turn.rs:166-240,1707-1835 | 当前在模型采样，是否中断重试，不能伪装完成 |
| Tool dispatched / running / finished / aborted | tools/parallel.rs:46-333,385-484 | 排队、处理器耗时、失败与用户取消 |
| Cell started / yielded / completed / missing | tools/code_mode/execute_handler.rs；runtime/service.rs | Yielded 仍在后台，可 wait/terminate |
| Child spawn / wait / activity / terminal | agent/control.rs；tools/handlers/multi_agents_v2/wait.rs:39-136 | parent、child、mailbox/steer/timeout 分别显示 |
| Thread persisted / fork / resume | thread_manager.rs；session/daemon_recovery.rs | 存储落盘和实际重新调度是两个阶段 |
| Stream / JSON/protocol legacy projection | agent/control.rs；code-mode-host/src/grpc/mod.rs | UI 事件不能丢失序列/来源/call_id |

## 6. 未完成的交互证据

未观察真实 TUI 交互与屏幕截图；未确认快捷键 Windows ANSI/vt 模式；未跟踪所有 SlashCommand 的 app.rs dispatch 分支；未做从 CLI 到独立 app-server 的完整 RPC trace；未测队列消息、logout、模型切换、联网故障、恢复与动态 UI 渲染。**这些不是已实现结论**。最小补采见 EXTRACTION-REQUEST.md。Codex Desktop GUI 归其他会话。

## 7. 已观察到的真实 CLI/Host 命令行表面

发行包的 CLI `--version` 输出 `codex-cli 0.163.0`；CLI `--help` 和独立 Code Mode Host `--help` 均退出 0。完整输出分别存于 `extractions/CLI-HELP.txt`、`extractions/HOST-HELP.txt`。CLI help 暴露 `--remote` (`ws://`, `wss://`, `unix://`)、remote token 环境变量、默认共享本地 app-server daemon、`--no-daemon`、`agents` 管理入口。Host help 暴露 `--listen` 支持 stdio/grpc+stdio/grpc://IP:PORT，以及 WebSocket OTEL trace listener 和 OTLP/HTTP exporter。此处 R 仅限启动并读取 help/version；没有凭据、无 RPC/Host transport 建连，不可推断远端连接/agent/task 成功。

## 8. Realtime voice 生命周期（源码 S，未实际启动）

CLI TUI 的 `/voice` 候选实际连接独立打包 voice helper。UI Starting 状态与 attempt ID 防止过期启动结果复活；客户端验证 helper protocol/build commit，完成 SDP answer 与 ordered channel 后才开启音频设备，停止时关闭 session 并恢复未送达的语音文本。音频媒体走 WebRTC，管道仅传控制/SDP。源码位置见 IMPLEMENTATION-TRACE §H。Windows helper 仅通过 Authenticode/文件/静态依赖确认存在；未启动语音权限、设备、网络或服务端，所以动态过程均未观察。
