# IMPLEMENTATION TRACE — 源码级调用链与状态所有权

**固定源：** `openai/codex@rust-v0.163.0` = commit `83086188ae0614bd882818ff1aa23f3194962012`；源文件定位统一为 `codex-rs/` 相对路径。等级 S：静态源码查阅；本文所有路径含源码真实文件，不指称运行实测。

## A. 入口→采样→工具→下一轮（CODEX_CLI-001/002/003/004）

1. `core/src/session/turn.rs:166` 的 `run_turn(sess, turn_context, input, mcp_startup_requirements, prewarmed_client_session, cancellation_token)` 负责整个 turn。运行前有 guardian/hook、预采样压缩、用户输入持久化（175-240），随后装配技能、插件、附加上下文。
2. `turn.rs:1666` `build_prompt` 和 `1707-1835` `run_sampling_request` 从会话历史生成模型 input，额外 attach executed tool calls，生成 Responses 元数据；调用 `try_run_sampling_request`，有 stream retry state；ContextWindowExceeded 和 UsageLimitReached 单独退出，普通流错误经 `handle_response_stream_error` 可重试，cancel/preempt 有不同结果。
3. `tools/router.rs:48-60` 的 ToolCall 标识来源，`ToolRouter::build_tool_call` (257) 和 `dispatch_tool_call_with_state` (336) 不是工具 handler 本体。`tools/registry.rs:55-116` 通过 CoreToolRuntime 约定抽象工具，`register_trusted` (417) 与 `register_external` (458) 区分注册来源，并可叠加 hooks。
4. `tools/parallel.rs:46-333` 的 `ToolCallRuntime` 执行调度；包含异步 dispatch、取消 token、AbortOnDropHandle、tool timing；`tools/orchestrator.rs:1-180` 则把执行权限/环境沙箱与 retry/反馈集中化。工具并行由 handler 能力和调度判定，**不是盲并发所有调用**。
5. 真实可靠性边界：dispatch 中止与 handler 是否自行响应取消不同；工具执行是否开始和模型是否消费结果也不同；完成/错误要流入 turn 结果与 history，不能把“API 返回 OK”当任务完整完成。

## B. Code Mode — 两个进程、两个控制方向（CODEX_CLI-005—010）

**强证据链：**

```text
Model emits code-mode execute source
 -> core/tools/code_mode/execute_handler.rs::execute
 -> parse_exec_source + prepare_code_mode_tool_definitions
 -> code_mode_service.execute(ExecuteRequest: tool_call_id, source, yield_time_ms, max_output_tokens)
 -> core/code_mode_host.rs::ProcessOwnedGrpcCodeModeSessionProvider
 -> tokio::process::Command(host, ["--listen", "grpc+stdio://"])
 -> tonic HTTP/2 gRPC framed over ChildStdout + ChildStdin
 -> code-mode-host/src/grpc/mod.rs::GrpcCodeModeHost::execute_request
 -> grpc/session.rs::GrpcSession {runtime, cells, pending_invocations, subscriptions, waits}
 -> code-mode-runtime/src/service.rs::InProcessCodeModeSession::execute
 -> code-mode-runtime/src/runtime/module_loader.rs::evaluate_main_module (V8)
 -> callback tool request -> gRPC ToolCall subscription
 -> core/tools/code_mode/delegate.rs::CodeModeDispatchBroker::start_turn_worker
 -> core ToolCallRuntime + registry + handler
 -> callback result / notification back to Host
 -> initial outcome / Yielded(cell_id), wait/terminate when applicable
 -> executed_tool_calls.start_cell + rollout_thread_trace.start_code_cell_trace
 -> model receives mapped output
```

关键精确行为：
- `core/src/code_mode_host.rs:23-92` channel **lazy/shared**，HTTP/2 ping/timeout (30s/10s)；URI `http://code-mode-host` 只是假 authority，网络不开放 HTTP server；`HostConnection::spawn` 用 pipe。`Drop` 中 start_kill 并回收子进程（约 95-154）。
- Host `code-mode-host/src/main.rs:15-58` 接受 `stdio`、`grpc+stdio://`、`grpc://IP:PORT`；本次 Core 路径指定 `grpc+stdio://`。另外 `code-mode-host/src/lib.rs:78-198` 有独立 framed protocol + handshake，不把两套对等混成一个。
- `code-mode-host/src/grpc/session.rs:39-96` 将 session、execution、seen ids、pending closures、tool subscriptions、pending invocations、waits 分开保存；`GrpcHostState::open_session` (108) 用 lease，当 event stream 关闭回收。
- `code-mode-host/src/lib.rs:45-72` 常量上限：in-flight requests=256、active cells=128、recent request IDs=4096；它们是 **Host 配额，不是 Atlas 用户子 Agent 并发上限**。
- `code-mode-host/src/grpc/mod.rs:63-144` 提供 `open_session_request`, `subscribe_request`, `complete_tool_request`, `execute_request`; 169-289 有 wait/cancel/yield/terminate。每个 cell 的嵌套回调由 Core `CodeModeDispatchBroker` gate 等待 `mark_cell_ready_for_dispatch`；已关闭/取消的 cell 不可继续随意投递工具（`core/src/tools/code_mode/delegate.rs:118-240`）。
- `core/src/tools/code_mode/execute_handler.rs:90-156` 记录 cell 和 trace，初次响应如果 Yielded 不立刻关 cell；非 Yielded 时 `finish_cell_dispatch`。这个生命周期区别对 Atlas 的工具输出、取消和 UI 特别重要。
- `code-mode-runtime/src/service.rs:65-198` 用 `ObserveMode::YieldAfter` 和 `PendingFrontier`，支持 `wait`, `terminate`、MissingCell 分类；不应把 timeout 理解成自动关闭 JS 工作。

**不可据此断言**：运行时是否在 EXE 无缝重启后恢复之前正在执行的 V8 cell（静态路径表现为新建 host 和 stale cell ID 处理）；动态恢复率须由补采测试证实。Host 不是用户浏览器 Javascript，也不等价 Node npm runtime。

## C. Multi-agent — 会话树、邮箱、驻留、恢复（011—016）

- `core/src/agent/control.rs:75-163` 定义 LocalAgentControl；root session identity 与 LocalAgentRuntime 分离，树共享执行限制器；`send_input` 通过 `start_or_steer_turn`，steer 不伪装成新 turn。
- `control/spawn.rs:676-1014` `spawn_agent_internal` 生成独立 child；`1015-1341` `prepare_forked_history` 根据父上下文、fork mode、checkpoint 清理历史；`1342+` 可从 rollout 恢复。
- `control/residency.rs:23-331` 用 `ThreadEvictionOutcome` 对运行时精确卸载；`V2Residency` 有 reserve/pin/touch/unload，避免持久 thread 因常驻对象数不足而直接丢掉。
- `control/mailbox.rs:15-112` 的 `Mailboxes` 存储待交付消息并通过 watch 唤醒；`control.rs:134-250` 在某些目标未装载且不需触发 turn 的情况下 enqueue；交付与重建 session 的原子性被显式注释。
- `control/runtime.rs:37-184` `AgentTreeShutdownState`、`AgentTreeTeardownGuard`，`completion.rs:25-156` 将 child terminal notification 回到 parent，避免把 spawn 后执行完成简单当成主线程 Turn Completed。
- MAv2 Handler 可见 `tools/handlers/multi_agents_v2/{spawn,send_message,wait,followup_task,list_agents,interrupt_agent}.rs`；与 legacy multi-agent 同时存在，启用和兼容性需读配置及跑包。

## D. 上下文生命周期（017—019）

- `core/src/context_manager/history.rs:93-129` ContextManager 使用共享快照、history version、user-input revision、world-state comparison checkpoint、reference context snapshot。它把宿主知道的状态和模型当前窗口已见状态分开。
- `core/src/session/world_state.rs:43-414` `build_world_state_for_step` 生成世界状态，相关 `context/world_state/*` 片段面向差分注入；模型/环境配置变动不是简单全文重发。
- `turn.rs:175-232` 在当前输入前处理 pre-sampling compact；`session/async_compaction.rs:1-203` 有 speculative request、checkpoint 时取 ready、退出取消，且 discarded requests 的 usage 仍需要记账。与独立用户触发 `/compact` 分离。
- `tools/handlers/tool_search.rs:38-350` `ToolSearchHandler` 通过 BM25 索引/缓存做 code mode 和 MCP 定义发现；过多工具不必须全部常驻 prompt。注意是否启用仍依功能开关/路由。

## E. 状态持久化、steer、fork、异常

- `core/src/thread_manager.rs:184-250` `NewThread`, `ForkSnapshot`, `ThreadManager`；`session/session.rs:950-967` compaction checkpoint 带 window_id/previous_window_id 等 lineage。
- `session/daemon_recovery.rs:1-57` 的 `RecordedTurnInput` 说明只有 Turn Input 已写入 rollout 才可记录 recoverable turn；caller 必须 flush rollout 再持久化快照。
- `session/turn_input.rs:90-230,328-689` `PreparedTurnInputSettings` 先 validate 后 commit，`start_or_steer` 区分 start/steer；这些构成消息恢复及执行中变更设置的一致性边界。
- `core/src/tools/parallel.rs:385-484` `ToolCallTimingGuard` 将排队/handler/合计时间分开；Code Mode cell trace 亦有 host-side duration。

## F. 潜在新发现但尚未闭环

`codex-rs/agent-graph-store`、`agent-message-board-client`、`voice-host`、`realtime-webrtc`、`hooks`、`app-server/daemon_thread_recovery.rs` 均在固定版本源码存在。并未逐个验证 feature flag、默认启用、每个 handler 最终挂载和运行入口；不能凭目录存在断言 CLI Windows 全部提供。待机械补采/第二阶段源链路取证。

## G. app-server request admission → scope queue → handler dispatch（CODEX_CLI-026/034/035）

`app-server-protocol/src/protocol/common.rs:128-139,208-287` 定义 serialization scope，并通过宏生成 typed request、wire name、scope 查找与 JSON-RPC 转换。`app-server/src/message_processor.rs:966-1067` 将 JSON-RPC 转为 typed request、检查初始化/实验能力，取得 turn admission 与 scope；thread/turn 改变与请求 scope 共同决定能否立即执行、排队或并行。

`app-server/src/request_serialization.rs:24-108` 计算 Global、GlobalSharedRead、Thread、ThreadPath、Process 等 queue key；`:160-230` 对相同独占 key FIFO 调度，共享读操作进入并发集合；`:233-306` drain queue，并在连接关闭时丢弃尚未执行的工作。`turn_admission.rs:1-83` 用 drain gate 原子拒绝新 turn、计数已准入 turn 并通知 shutdown 等待。边界：这里只核过源码和 CLI help；未动态发 RPC 测量排队公平性、并发或 close 行为。

CLI 入口方面，`cli/src/main.rs:131-190` 定义 remote/no-daemon/command wiring；真实 `CLI-HELP.txt` 显示 remote URI schemes、remote token env、默认本地 shared app-server daemon、`--no-daemon` 与 `agents` 命令。`app-server-daemon/src/client.rs:63-92` 描述本地 daemon WebSocket/Unix stream initialize 与 shutdown 通道。help 是对入口字符串的 R 观察，不代表这些 RPC 连接成功。

## H. TUI voice → helper → WebRTC → app-server session（CODEX_CLI-037）

`tui/src/chatwidget/realtime.rs:301-357` 记录 Starting/attempt ID，后台启动 realtime session，成功后以事件回交 offer；`:360-395` 停止、恢复未投递语音、关闭本地 session，并忽略晚到的旧 attempt。`realtime-webrtc/src/client.rs:130-159` 启动 transport，SDP answer 必须应用成功且 ordered event channel 打开才得 `TransportReady`，超时关 helper；`:173-228` 只从打包资源目录解析 voice host，筛选子进程环境，hello 校验 protocol/build_commit。`protocol.rs:1-10,52-120` 将音频媒体留在 WebRTC、控制/SDP 留在 bounded framed pipe；最大帧 128 KiB、SDP 最大 64 KiB。

`session.rs:140-175,274-326` 发 offer 后等 answer，成功后才开设备并下发 mute controls；音频轮询约 50ms，controls 优先于 audio。`tui/src/app_server_session/realtime.rs:19-93` 通过 typed `thread.realtime.start/stop` 连接 app-server；`app-server/src/request_processors/turn_processor.rs:1212-1306` 映射 SDP/transport 到 conversation start params 并提交后端。外部 realtime backend 的实现语义、语音/音频真实传输与账号权限仍属 U。
