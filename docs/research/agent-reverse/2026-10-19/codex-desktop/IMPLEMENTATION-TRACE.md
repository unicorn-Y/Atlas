# Implementation Trace — 实现证据与完整状态链

研究线 A：**OpenAI open-source App Server (rust-v0.163.0)**；研究线 B：**Windows Desktop 26.1013.4894.0 未解包**。二者不能合并为已验证同一进程拓扑。源码指向 https://github.com/openai/codex/tree/rust-v0.163.0/codex-rs 。

## 1. 桌面包已知入口（仅采集实物索引）

MSIX app/ChatGPT.exe 是 AppxManifest 的主入口；app/resources/codex-command-runner.exe 是辅助入口。采集报告给出 Windows Desktop 包身份、签名及 3651 个 zip 项，但**没有解出 UI JS 内容，也没有启动日志**。现在不称 runner 是 app-server 子进程，不推断它通过 stdio/pipe/WebSocket 连接，甚至不能确认其自动启动时间。需 EXTRACTION-REQUEST 的进程/资源证据。

## 2. 服务器桥接，真正有代码的调用链

- app-server/src/lib.rs:1-115 引入 transport、MessageProcessor、ConnectionCleanupTasks、ThreadState、RemoteControl、CodeModeHost；这是源代码的真实模块绑定。
- app-server/src/transport.rs:15-39 分别导出 start_stdio_connection / start_websocket_acceptor / start_control_socket_acceptor / start_remote_control。connection state 带 origin、auth、是否打开实验 API、通知过滤列表和 writer 队列（42-126）。这是**可选多种传输**，不是 Windows Desktop 正使用四种。
- app-server/src/message_processor.rs:28-53 实际注入 ThreadRequestProcessor、TurnRequestProcessor、ThreadQueueRequestProcessor、AppsRequestProcessor、PluginRequestProcessor、McpRequestProcessor、FsRequestProcessor、CommandExecRequestProcessor、ProcessExecRequestProcessor 等，说明不只是无实现的协议 enum；这些 processor 内部的完整函数还待继续采集。
- 协议常量：app-server-protocol/src/protocol/common.rs:552-564 定义 thread/start/resume/fork，1057/1075 turn/start/interrupt，1949+ 定义向客户端广播的事件。每个 request 的 serialization scope 指明 thread 或 process 域；不同域并发控制不能归结为全局互斥。

## 3. 线程启动→运行→客户端展示→恢复

**普通执行的契约**：thread/start 创建线程标识 → turn/start 发起回合 → thread/turn/item 通知（文本增量、plan 增量、工具 stdout、patch 增量等）→ turn/completed。客户端需把通知按 thread/turn/item ID 索引并独立维护加载历史与实时项。传输实现确有事件，但**客户端如何缓存、虚拟滚动、合并增量及 action 卡片必须读其 JS 才能定论**。

**重新订阅活动线程的额外机制**：app-server/src/thread_state.rs:57-91 的 ThreadListenerCommand::SendThreadResumeResponse 明确把“发历史回包”与“订阅后续事件”放在同一个线程监听器顺序中；另有 ResolveServerRequest 做请求终结通知排序。thread_state.rs:106-125 有 listener_generation 和 shutdown_drain_waiter，目的是避免旧监听器 ShutdownComplete 尚未处理就被新监听器替换。此机制直接针对多窗口/重连时的丢事件或错序，不等于普通 WebSocket 重试。

**Daemon 冷恢复**：app-server/src/daemon_thread_recovery.rs:1-54 将持久根线程 ID 写成 snapshot；start_recovery 先读取/删除快照，随后 tokio::spawn 走 processor.restore_daemon_threads(candidates)。源码注释表明不阻塞 readiness；已加载运行时仍由旧客户端持有。可证明**恢复线程资源/历史加载**，但不能由此说崩溃前正在执行的工具原地继续，后者需真实测试。

**已读状态**：app-server/README.md “Thread read state” 有 firstUnread、revision；API thread/readState/update 持 revision 比较；冲突回当前状态，不要盲重试。线程历史加载不是 read ack，离屏窗口同步建议重新 thread/read。用户可见未读点与 Agent 执行状态是两个独立维度。

**队列**：协议 common.rs:630-660 给出 queue/add/list/update/delete/reorder/start，且实验门控；thread_state.rs:78-81 明确队列变更通知需按 thread listener 顺序发出。队列被放在 ThreadState 内而非一个前端按钮；持久化本体需再查 processor。不能假定 Desktop UI 有拖拽重排。

## 4. 工具、插件和交互卡

- 基础工具结果：common.rs:1970-2030 有 commandExecution/outputDelta、terminalInteraction、fileChange/patchUpdated、mcpToolCall/progress。独立于 agentMessage delta。renderer 必须区分 shell 流、patch 和普通消息，否则丢掉行为。
- 审批：common.rs:1795-1827 server-to-client request for command/file/permissions/MCP elicitation，客户端返回单独 request response；thread_state.rs:83-90 将“请求已完成”通知排序。与把 approval 画成卡但没有正确回传 future 不等价。
- 动态工具：app-server/src/dynamic_tools.rs:14-57 收到客户端执行结果后，将 success/content_items 转 CoreDynamicToolResponse，然后 conversation.submit(Op::DynamicToolResponse)。解码 59-113 会拒绝远程 image URL、非 data: audio URL，异常给失败文本。这是**宿主可执行工具请求的真实回路**，但不证明任意可点击 UI DSL。
- MCP 应用显示：app-server/README.md “MCP App UI” 说明 mcpToolCall.mcpAppUi 保存 resourceUri 和 preferredModelDisplayMode=inline/fullscreen，旧 history 有 null，工具只在 result metadata 宣告 widgets 时要重新查 catalog；资源内容/嵌入行为在 Windows Desktop 未证。
- 插件生态：common.rs:924-1057 把 PluginList/Install/Uninstall、PluginShare*、AppRead/List/Installed、FsRead/Write/Watch 分成不同域；common.rs:1246-1284 的 MCP tool/resource/event stream 仍属另一协议；common.rs:2010+ 有对应更新事件。Atlas 不应把它们仅映射到单一“skills list”。
- 命令：common.rs:1377-1435 sandboxed command/exec 与 experimental unsandboxed process/spawn 分离，均有 stdin/kill/PTY 改尺寸；command_exec.rs:53-124 包含管理器/session/控制请求。要调查桌面 Terminal 控制的是谁、数据怎么持久化，不能仅看 Windows PowerShell 窗口截图。

## 5. 实验、资源与失败路径

transport.rs:104-125 仅对启用 experimentalApi 的连接推送实验事件，且各连接可 opt-out 某些通知。出现字段不保证总有事件。app-server/README.md 还描述 shutdown 返回 -32600 reason=serverShuttingDown，model/list 对启动 provider requirements 失配拒绝而非从缓存继续；网络策略 reload 可能取消请求，guardian 有单独错误码 TooManyDenials；userVerification/cancel ack 不保证 OS 交互已经结束。这些是**可观测状态与失败编码**，比“重试一次”具体。

## 6. Atlas main 真代码的纵向链路

- renderer: ConversationMessage.tsx:2-58 用 react-markdown/GFM/高亮/Mermaid，streaming 时纯文本。timeline.ts:30-75 与 ConversationActivity.tsx 固定类型卡。runtimeEvents.ts:25-46 用 hardcoded known Set 丢弃未知 wire events，artifact.created 特殊降级映射。
- frontend/src/renderer/store/useAtlasStore.ts:17-20,70-80 支持 FollowUpMode steer/redirect/queue；frontend/src/renderer/components/MessageThread.tsx:15-100 用 Virtuoso 和 per-conversation scroll snapshot；这里已不是只有简单气泡。
- adapter: backend-adapter/src/client.ts:524-618 发 run.start，断线 resume + after_sequence，读 localStorage cursor 去重；对 approval/steer/subtask 有单独命令（620-650）。
- API: core/atlas/api/runtime_ws_router.py:18-153 接收 run.start, resume, cancel, pause, steer, subtask.message, input.response, plan approve 和 approval.response，确有 Future/handler 接线。
- Session: core/atlas/engine/session_sync.py:561-611 操作 Hermes SessionDB 的 rewind/fork；conversations_router.py:130-160 有 branches API；Frontend ForkTree.tsx:13-62 实际呈现。
- Runtime 永续性关键界线：core/atlas/api/runtime.py:108-150 将 SQLite 中处于 running、paused、waiting 的 run **直接改 failed**，虽然恢复事件含 recoverable:true，但原执行任务明确“execution was not resumed”；是事件游标重连≠进程/任务 durable resume 的可复核反例。

## 7. 尚缺必须继续的调用链

1. MSIX 的主进程→runner→app-server/CLI：实际启动参数、stdio/pipe/socket、协议版本与握手、异常重启策略。
2. MSIX UI bundle 的 Message renderer、卡片 component registry、host action dispatcher、dynamic widgets iframe/security boundary、更新和插件入口；逐条从关键 action 到 RPC 跟踪。
3. Desktop 凭据、账号、模型、会话元数据/历史及本地索引使用何种存储（只记录 schema，不上传用户数据）。
4. 真实运行的 UI 事件和后台线程在正常/关闭/断网/重启/多窗口条件下的 R 级生命周期。

以上全部作为后续取证问题，而不是已完成结论。
