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

## 8. Windows Desktop 实物复核（S；未启动，R=0）

本次已直接验证原始 `ChatGPT-x64.msix`，不是仅据旧采集索引：OpenAI.Codex `26.1013.4894.0`，948,993,815 bytes，SHA-256 `e2d892e6c22310e4b1a2928b0d3a29a066e0863d3a333754d6585c77cdafbe7f`。MSIX 解包得到 3,651 regular files / 2,346,419,207 bytes，REA extraction integrity 返回 containment verified、零文件不匹配（`ev_edbf1706dc64708c2195821e0cc8fb6b0bc817ab3e4da784a9ae5aca854c87c2`；包 inventory `ev_5448a1c8a343570e29c1b3d0ed47cdc15d831d912a84a029941426af9473c182`）。

ASAR 自身为 582,072,504 bytes / SHA-256 `bbec1d64e135b718a154b31655bb8ad9a39472bac1b2cabba991a9d97a339dd8`。REA 全 ASAR 深析超时；它定位到外置 `node_modules/better-sqlite3/build/Release/better_sqlite3.node` 相对 integrity manifest 不一致。MSIX 文件级抽取完整性通过与 ASAR/native unpacked addon manifest mismatch 是两项不同结果，后者没有被本研究解释为损坏或签名失败。ASAR 路径清单有 21,396 项、0 个 `.map`；其中 `webview/assets` 有 20,362 项。完整 ASAR 和全部 webview assets 未扫描，以下是 35 个 `.vite/build` 模块和 41 个命名目标 webview chunks 的有界静态分析。

### 包入口到协议客户端

* 外层 `app/ChatGPT.exe` 是包入口（4,795,184 bytes，SHA-256 `2f61eaeb01dcee7fd18d572fbb338c88b686c0d891427487fdd182afdd64b4f6`）。ASAR `package.json` 指定 Electron main `.vite/build/early-bootstrap.js`，内部 npm version `26.1013.40934`；MSIX 显示版本仍以外层 `26.1013.4894.0` 为准，二者保留为不同元数据。`app/resources/codex.exe` 341,312,816 bytes，SHA-256 `f6dbf48cb70f62649c645f26c87dc9bf84cc36986202dfad8e12fb5b8ca70312`，Authenticode 状态 Valid、OpenAI OpCo 签名者；`codex` 同名无扩展二进制 296,885,960 bytes / SHA-256 `70ea33b7094a4c20c007d09b83bb50e33debb9bbf99bf066709f9eb85bad524a`。本记录没有启动 app，签名和存在性不证明某次 UI 会话启动了哪个 executable。
* `application-network-startup-DB1VeU3v.js`（292,827 bytes / SHA-256 `c338bbdde151467554d63beea59206848ca38a68abe16b0477d983a172c67578`）字节偏移 680：`x="0.141.0"`、`codex-app-server-version-unsupported:` 与 `codex-app-server-version-restart-available:`。同模块偏移 2,900 有 `process/spawn requires experimentalApi capability` 的缺能力错误；偏移约 14,070–14,200 列出候选 runtime 名称和映射 `codex.exe`→`codex`、`codex-code-mode-host.exe`→`code-mode-host`、`codex-windows-sandbox-setup.exe`→`sandbox-setup`、`codex-command-runner.exe`→`command-runner`、`rg.exe`→`ripgrep`。偏移 49,265 证实该模块封装 Node child_process `spawn`，但不能据 resolver map 推断所有映射都会随启动执行。
* `main-C4DYk222.js`（4,049,746 bytes / SHA-256 `c8a2af504b21314fa6a64ad1b4ec83dbad80033ede902caf9978fd9c74a2c175`）偏移 3,478 标识 `codex-app-server`。偏移 49,098 起 JSON-RPC client 的 `sendNotification`、`sendRequest` 生成 `{jsonrpc:"2.0",method,params,id}` 并登记 pending request。偏移 97,588 处谓词认 `thread/start`、`thread/resume`、`thread/fork` 为 thread mutation；偏移约 740,050 的 request wrapper 对 `thread/start`, `thread/startAeon`, `thread/fork`, `turn/start`, `turn/steer`, `plugin/uninstall` 标记为 mutation。偏移 3,270,816 定义 `ws://codex-app-server/rpc` 与 16,777,216-byte 最大未分片消息限制。包还含 app-server 构建期协议版本 `0.141.0`；这是静态 bundle 观察，不是服务端版本握手成功。

### UI action、状态/通知、preload IPC

可证的调用链片段为：Electron 主进程启动 UI 的静态构建入口 → renderer 经注入 `electronBridge` 的 `sendMessageFromView` / `sendWorkerMessageFromView` 进入 IPC invoke → main bundle 协议 client 将 request 编为 JSON-RPC → app-server WebSocket `codex-app-server` transport。源码将 `thread/start` / `thread/resume` / `thread/fork` 分类并把 request promise 放在 pending map 中。该构建中的 thread coordinator 对 `turn/started`、`turn/completed` 等通知按 threadId/turnId 筛选；thread/start/resume/fork、turn/start/steer 和 queue mutations 字符串均出现。**没有将某个具体 UI button/action 的组件调用一路追到上述 RPC 的完整 renderer bundle；此处是 bridge-to-protocol 的静态链片段，用户交互入口还未闭环。**

* `preload.js` 6,909 bytes / SHA-256 `a3e622f8d80a83e58fb3cfcc640fa7e14e6461cccdae9ef7d7b0c821dde256b7`。偏移 6,599 以 `contextBridge.exposeInMainWorld` 暴露 `codexWindowType`、`electronBridge`；偏移 3,341 的 `electronBridge` 包含 `sendMessageFromView`（IPC invoke）、`sendWorkerMessageFromView`、`subscribeToWorkerMessages`、`showContextMenu`、文件路径/拖放 API 和 chunk ack。它也转发共享对象更新和 app-host 消息；`codex_desktop:mcp-app-sandbox-host-message` 经 `window.postMessage` 连到当前非 null origin。IPC channel 常量如 `codex_desktop:chunked-message-ack` 位于偏移 1,819。此处没有将 preload 接受的消息误判为完整 IPC 权限面；main handlers 必须后续对全部通道枚举。
* chunked host message 会先验 `marker === "codex-host-chunked-message-v1"`、transferId、整数 sequence、kind，并递归验证 token 类型（偏移 1,111 起）；`acknowledgeChunkedMessage` 回发 ack。表明存在带校验和确认的分片消息桥，但尚未追完组包端、背压/超时与所有调用者。
* app-server notification 名称的构建证据包括 `turn/started`、`turn/completed` 和 thread 状态通知；thread mutation 集包括 `thread/queue/add`、`turn/addUserMessage`、`turn/start`、`turn/steer`（main bundle 偏移约 125k 的 mutation registry）。`thread/turn/item/agentMessage/delta`、`item/started`、`item/completed` 等 item streaming 是否来自当前 bundle 的具体 renderer action 尚未沿所有消费端逐个闭环。不得把当前 Rust 开源 tag 的通知当成此桌面构建服务端实测。

### 打包的执行能力与隔离边界

ASAR 主进程模块含 Windows `computerUse` native pipe server 生命周期、feature enable/disable 时关闭当前 turn、路径变化后重新解析并重启 helper 的代码（main bundle 字节偏移约 170,200–173,000）；这是从包静态代码可读的专用电脑操控 host 机制。包存在 `codex-code-mode-host.exe` / 无扩展 host、`codex-command-runner.exe`、sandbox setup 与 sandbox service；这只能确证组成与主进程存在 runtime path/feature 配置，不能确认任一用户会话实际启动顺序和父子关系。文件 SHA/字节数见 `EVIDENCE-INDEX.md`。

报告行为等级：以上为 **S（静态发行包源码/资源）**；未运行应用或发起 UI 动作，所有动态验证为 **R=0**。20,362 webview assets 中仅 41 个命名目标 chunk 被提取，完整 ASAR 也未成功深析，因此“未检出”不等于功能不存在。app-server 远端/打包 Rust runtime 的服务端策略和帐号云端实现不由客户端源码证明。

## 9. 对 Atlas 当前实现的垂直对照锚点

唯一 Atlas 基线为 `origin/main@aa6196f550098cc46081dc6db2c376cb87ddffa5`。`backend-adapter/src/client.ts:524-618` 的 `startRunInternal` 保存 per-run `lastSequence` 到 localStorage，断开后发 `{type:"resume",run_id,after_sequence}`，按 run_id/sequence 去重并回放连接；`core/atlas/api/runtime_ws_router.py:18-153` 是服务端 socket 指令分发与审批/input/plan Future 回复。`frontend/src/renderer/services/runtimeEvents.ts:25-34` 对 renderer 事件使用显式 known Set 和 `normalizeRuntimeEvent`。`frontend/src/preload/index.cts:1-29` 暴露固定 `atlasDesktop` API；不能仅凭存在 preload 等同 Codex 的广义 view/worker/chunk/MCP sandbox message bridge。`core/atlas/api/runtime.py:108-153` 在进程重启时把 running/paused/waiting run 记录变为 failed，事件声明 recoverable 但 detail 明说 execution was not resumed；所以 Atlas 的事件重放是 stream continuity，不是引擎执行进程恢复。

这些是源码机制比较，不将 Codex 的 Desktop 接线未知/包静态入口说成成功运行，也不将 Atlas websocket 恢复表述为完整 durable resume。
