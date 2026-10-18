# DISCOVERY LEDGER — 双向能力发现总账

版本标记：Desktop MSIX 26.1013.4894.0（仅有归档采集证据）；开源 App Server rust-v0.163.0（已阅读固定源文件）。**S-Server 不是 S-Desktop**。D 官方说明；I 推断；U 客户端/运行时未验证；没有 R 级条目。

| ID | 入口／发现及生命周期 | 证据等级与精确锚点 | Desktop 是否实证 | Atlas 对照 |
|---|---|---|---|---|
| CODEX_DESKTOP-001 | Windows MSIX 包身份、app/ChatGPT.exe、codex-command-runner.exe 双入口；真实 IPC 尚不明 | S-collection：manifest.json；RECOVERY-CODEX-CLAUDE.md，MSIX 3651 条目 | 文件名确认；未亲自读二进制 | Electron 主进程已有，平台差异未判 |
| CODEX_DESKTOP-002 | 原生 Windows 的执行环境/可选择 WSL，工作树/后台聊天 | D：learn.chatgpt.com/docs/windows/windows-app | 官方描述，不等于发行版本逐项验证 | Atlas 自带 PowerShell + worktree |
| CODEX_DESKTOP-003 | thread/start、resume、fork、read、list；线程 ID 和订阅关系分离 | S-Server：app-server-protocol/src/protocol/common.rs:552-564,772,858；app-server/src/thread_state.rs:56-79 | U | Atlas fork/tree/session_sync 真实存在 |
| CODEX_DESKTOP-004 | Daemon snapshot 保存持久根线程；服务恢复异步走 cold-resume，并删除已消费快照；与正在跑的 turn 续跑不同 | S-Server：app-server/src/daemon_thread_recovery.rs:1-54；thread_state.rs:56-77 | U | Atlas 服务重启即标记 run.failed |
| CODEX_DESKTOP-005 | 活动线程恢复：历史回包 + 后续通知订阅在监听器中按顺序完成；listener generation 与 shutdown drain | S-Server：app-server/src/thread_state.rs:57-91,106-125 | U | Atlas WebSocket seq reconnect；未发现等价持久监听器迁移 |
| CODEX_DESKTOP-006 | thread 已读收据 firstUnread/revision，revision CAS 防止多窗口无意覆盖 | S-Server+D-in-repo：common.rs:858-868；app-server/README.md read-state 段 | U（实验） | Atlas 按会话缓存消息和滚动位置，未见 read CAS |
| CODEX_DESKTOP-007 | thread/queue/add/list/update/delete/reorder/start，按线程管理任务列队 | S-Server：common.rs:630-662；thread_state.rs:78-81；标实验 | U | Atlas FollowUpMode queue/steer/redirect 已实现一定逻辑，持久重排未证 |
| CODEX_DESKTOP-008 | turn/item 分层事件：启动/完成、实时文本、plan、diff、工具 stdout/stderr、PTY 互动、失败 | S-Server：common.rs:1949-2042 | U | Atlas Runtime Event 1.2 + whitelist + timeline |
| CODEX_DESKTOP-009 | 命令审批、文件审批、额外权限、MCP elicitation 是 server→client **有响应的请求** | S-Server：common.rs:1795-1827；thread_state.rs:83-90 | U | Atlas approval_futures，部分有线，事件模型不同 |
| CODEX_DESKTOP-010 | 工具结果可附 mcpAppUi.resourceUri 和 inline/fullscreen preference，写入历史；嵌入渲染仍取决于客户端 | S-Server+D-in-repo：app-server/README.md “MCP App UI” | U；**不宣称支持任意交互控件** | Atlas Markdown + 固定 TimelineItem 组件 |
| CODEX_DESKTOP-011 | 动态工具调用由服务端向 UI/宿主发出，异步接回模型；失败回传失败文本；音频/远端图片输出受约束 | S-Server：app-server/src/dynamic_tools.rs:14-114；common.rs:1827+ | U | Atlas MCP 工具存在，宿主动态工具响应协议未见等价 |
| CODEX_DESKTOP-012 | Plugins / Apps / MCP 三个独立资源、安装/管理和变更事件 | S-Server：common.rs:924-1057,1246-1284,2000+；app-server/src/message_processor.rs:28-53 | U | Atlas PluginRuntime 和 Skills/MCP 存在，区别不可直接抹平 |
| CODEX_DESKTOP-013 | 文件操作 + fs/watch 事件，MCP 事件流以及会话级文件搜索 | S-Server：common.rs:997-1037,1270-1284,1500-1520,2010+ | U | Atlas File Panel / LSP / tools，具体事件契约不同 |
| CODEX_DESKTOP-014 | command/exec 沙箱命令可 write/terminate/PTY resize；实验性的 process/spawn 非沙箱且生命周期独立 | S-Server：common.rs:1377-1435；app-server/src/command_exec.rs:53-124 | U | Atlas xterm WebSocket 与进程轮询可用，不是同个 RPC |
| CODEX_DESKTOP-015 | transport 包含 stdio、WebSocket、control socket、远程控制接口；连接有实验开关与通知订阅过滤 | S-Server：app-server/src/transport.rs:15-39,42-126 | Desktop 实际选哪条未知 | Atlas 本地 HTTP/WebSocket；本地 CLI IPC 未明 |
| CODEX_DESKTOP-016 | model/list 与刷新有 provider requirements；不合规时请求显式失败，不能继续沿用不允许的旧端点 | S-Server+D-in-repo：app-server/README.md “Model catalog provider requirements” | U | Atlas model router 存在；不等价 |
| CODEX_DESKTOP-017 | 用户触发 userVerification/cancel 不等于 prompt 已结束，也不能撤回已经完成的证明 | D-in-repo+S-contract：README User verification cancellation；common.rs:520-540 | U/experimental | Atlas approval answer 有 futures，验证取消语义未查 |
| CODEX_DESKTOP-018 | thread/realtime 提供文本/音频/语音双向事件 | S-Server：common.rs:1080-1118,2045+；实验 | U（是否 desktop 载入未知） | Atlas voice overlay 不能借此判定等价 |
| CODEX_DESKTOP-019 | 官方桌面任务调度/活动结果收件箱/并发工作树 | D：learn.chatgpt.com/docs/automations | 发行版本待核 | Atlas automation 与 scheduler 可见，端到端质量未知 |
| CODEX_DESKTOP-020 | 宿主自更新、内置组件、真实消息 Card DSL、渲染容器与 action 派发 | U：必须提取 MSIX JS/HTML/asar/EXE 符号 | 未证，**不得声称缺失或存在** | Atlas 前端硬编码事件白名单是已证事实 |
| CODEX_DESKTOP-021 | Windows Desktop 启动 runner、后台存活与用户切换的完整握手、版本兼容与错误降级 | U：MSIX + 启动进程树/脱敏日志 | 未证 | Atlas Electron backendProcess 与 WS 存在 |
| CODEX_DESKTOP-022 | 外部 Agent 设置探测、配置导入及导入进度事件 | S-Server：common.rs:1440-1460,2010+；message_processor.rs:17,28+ | Desktop UI 未证 | Atlas external_import.py/ImportPanel 也存在 |
| CODEX_DESKTOP-023 | 扩展通知、订阅时实验能力闸门与各连接 opt-out 过滤 | S-Server：transport.rs:42-126 | U | Atlas normalizeRuntimeEvent 丢未知 event |
| CODEX_DESKTOP-024 | 文件改动 patchUpdated 和回合级 diffUpdated 与普通 Markdown 回答分离，可做局部操作界面 | S-Server：common.rs:1977-2008 | Desktop 呈现方式 U | Atlas ChangesPanel 有逐行 diff 评论，通过文本送回引擎 |

## 发现方式与证据限制

从真实 Server 枚举 Request/Notification 反向找 UI 候选，从线程状态/transport/daemon recovery 找隐藏生命周期能力，再从 Atlas 的 renderer→adapter→ws router→runtime/SessionDB 正向查差距。没有扫描 MSIX 静态资源或网络，所以 CODEX_DESKTOP-020/021 是必须优先解锁的高价值未知，而不是遗漏后强称“没有”。

按证据算：**22 条机制有源代码/存档文档锚点，2 条核心 Desktop 专属行为 U**；但**Desktop 原生 UI/RPC 运行能力“已确认”数量为 0**（排除包身份 001）。不能将 22 条按“桌面端确认功能”汇总。
