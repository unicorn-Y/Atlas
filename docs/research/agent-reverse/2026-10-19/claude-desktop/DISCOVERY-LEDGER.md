# Discovery Ledger — Claude Desktop / Cowork

证据规则：**S**=本包真实源码/符号及调用链；**R**=本版本操作与日志；**D**=Anthropic 官方文档声明；**I**=有限推断；**U**=未知/待取证。已获得有限包内静态 S；R=0，服务启动关联和完整端到端链仍为 U。下表 D 的“已确认”只指官方公开产品行为，不证明 2.42304.0 MSIX 实装。

| ID | 新发现的行为 / 机制 | 归属 | 级别与状态 | 必须追的缺口 |
|---|---|---|---|---|
| CLAUDE_DESKTOP-001 | 2026-09-16 起 Chat + Cowork 逐步合流，普通对话内按任务自动升级为可执行任务，无需模式跳转 | Claude 平台/云 | D 确认，包 U | 渲染器 mode 状态机、task escalation IPC、rollout flags |
| CLAUDE_DESKTOP-002 | 云 Cowork 默认在服务端执行 agent loop + shell，任务及文件绑定账号跨端保存 | 云服务 | D 确认，包 U | 客户端 RPC、会话 ID 映射、断线恢复 |
| CLAUDE_DESKTOP-003 | 云任务可在桌面关闭/睡眠后继续；依赖本地资源的工具仍需 Desktop 在线 | 云 + 桌面设备桥 | D 确认，包 U | 设备在线事件、任务与本地调用拆分 |
| CLAUDE_DESKTOP-004 | 本地历史 Cowork：agent loop 在本机，shell 在 Hyper-V Linux VM 内；云/本地是两条不同路径 | Legacy 本地 Cowork | D 确认，包 U | cowork-svc、VM 启停/镜像/磁盘，哪种计划可触发 |
| CLAUDE_DESKTOP-005 | 云端每会话独立 sandbox，需调用设备资源时走经中介的 Desktop 连接，逐条受本机权限约束 | 云执行 + 桥 | D 确认，包 U | 桌面请求协议/权限消息/工具回执 |
| CLAUDE_DESKTOP-006 | 企业版统一体验可自动把普通聊天转换为 cloud workspace，空闲几分钟后停 VM + 加密磁盘快照，环境最长 30 天 | 企业版新架构 | D 确认，包 U | 恢复状态、snapshot ID、任务 UI 的具体事件 |
| CLAUDE_DESKTOP-007 | 内置浏览器在桌面侧栏操作；不同于复用用户自己的 Chrome profile | Desktop 浏览器 | D 确认，包 U | webview 实现、会话归属、截图/导航反馈 |
| CLAUDE_DESKTOP-008 | 设备操作优先级为 connector → 内置/Chrome 浏览器 → screen interaction | Desktop/工具路由 | D 确认，包 U | 工具能力发现、fallback 决策链 |
| CLAUDE_DESKTOP-009 | 定时任务 UI 支持创建、运行记录、暂停、恢复、手动触发；可指定模型/文件夹/审批方式 | Cloud/local Scheduler | D 确认，包 U | 调度所有权、task/run 独立存储、失败重试 |
| CLAUDE_DESKTOP-010 | 多端共享会话、项目上下文、连接器、技能、工件；当前多模式迁移兼容渐进发布 | Claude 账号/平台 | D 确认，包 U | 旧版本本地状态迁移、跨端 hydration |
| CLAUDE_DESKTOP-011 | 新版 Docs / Slides / Design 在会话内部可编辑与共享，不只是附件下载 | Artifacts/Docs 平台 | D 确认，包 U | block/component schema，编辑增量及保存版本 |
| CLAUDE_DESKTOP-012 | 电脑操作能力需要 Desktop 连接；macOS 15+ 存在后台窗口交互模式，而不是单纯夺焦截图 | 桌面 Computer Use | D 确认，Windows 路径 U | Windows UIA/CUA 工具实现和后台能力差异 |
| CLAUDE_DESKTOP-013 | 官方文档明确云 sandbox 与本机 MCP / connector 的执行边界不同：本地 MCP 依赖 Desktop，云 connector 通过服务器 | 平台/扩展 | D 确认，包 U | MCPB/DXT 加载器、tool bridge 路由 |
| CLAUDE_DESKTOP-014 | Enterprise/consumer MSIX 内容是否等价、2.42304.0 是否已配置新 Unified UI、哪些功能按账号 rollout | Package | U 阻塞 | 两包 SHA、feature flags 与启动配置对照 |
| CLAUDE_DESKTOP-015 | `app.asar` 的真实入口、全部 IPC channels、UI routes、RPC schema、service life cycle | Package | U 阻塞 | 提取 ASAR 并做定义-引用图 |
| CLAUDE_DESKTOP-016 | `cowork-svc.exe` 真实作用（桥、旧本地执行、工具代理或多合一）、持久化文件格式与进程树 | Package | U 阻塞 | exe PE 信息/字符串/导入/命令行引用、实际进程探测 |
| CLAUDE_DESKTOP-017 | 工具输出是否产生可点击任务卡、子任务/预填任务卡、任务消息与主会话相互引用 | Renderer/agent | U 阻塞 | AST 抽取组件、按钮 handler、schema 与后端来源 |
| CLAUDE_DESKTOP-018 | 启动、最小化、退出、网络断开、重新登录、后台云任务消息的正确生命周期 | Desktop/platform | U 阻塞 | 静态调用图 + 可重复操作日志 |
| CLAUDE_DESKTOP-019 | 源码可见但 UI 未入口的实验功能、动态模块、远端下发实验 flags | Package | U 阻塞 | router/action/feature-gate exhaustive inventory |
| CLAUDE_DESKTOP-020 | 权限策略的“继续执行/仅关键时确认”和本地设备逐 app 授权分离 | 平台 UI | D 确认，包 U | 许可证/配置/审批协议及后续持久化 |
| CLAUDE_DESKTOP-021 | 按 project 汇聚文件、上下文、指令、记忆，可跨设备访问 | Claude 账号/项目 | D 确认，包 U | project metadata 与 conversation/task 关联 |
| CLAUDE_DESKTOP-022 | 多子任务和并行工作流（官方可见），具体子 agent 数、隔离、任务结果合并未证实 | Cowork 任务 | D 确认，仅行为 | worker spawn/cancel/retry/aggregate 链路 |

## 主动发现方法与下一轮
- 自 UI 入口：文件树与 routes → 页面组件 → 可点击 action → IPC / HTTP / gRPC → 状态 / backend → 持久化；枚举全部未在任务书列出的模块，而非关键词取一两处。
- 自 service：PE imports、CLI flags、RPC constants / protobuf、进程树 → 逆查到 renderer 按钮与任务。
- 自版本变更：云端转移与 unified UI、Design/Slides/Docs、新浏览器、旧本地 VM 等至少分成**可离线验证 vs 依赖账号/服务端验证**。
- 当前没有足量本包文件，所以 S 和 R 不得虚增。

## 2026-10-19 实物静态发现（新增，不改写既有 ID）

- **CLAUDE_DESKTOP-023 — 固定 MSIX 与 app.asar 已核验**：S；297,191,037 bytes 与发行 manifest SHA 匹配；实际入口 `index.pre.js`，main window preload `mainView.js`。
- **CLAUDE_DESKTOP-024 — 动态生成 IPC API 面**：S/partial；437 个 JS 文件解析成功；统计见 `evidence/summary-counts.tsv`。多数通道动态构造，完整名称与 handler/caller 配对未完成。
- **CLAUDE_DESKTOP-025 — 独立 Cowork artifact bridge**：S/partial；`window.cowork` 暴露五个桥方法，main 注册存在且有 `cowork-artifact:` sender-origin 检查；后续运行时/持久化语义未闭环。
- **CLAUDE_DESKTOP-026 — cowork-svc 是 Go/Hyper-V VM 管理服务**：S (identity/help/strings/imports)；包内可见 HCS/HCN、Plan9、HvSocket、gvisor tap-vsock 相关标识。真实 call graph 与 app 安装/连接/停止关系仍 U。
- **CLAUDE_DESKTOP-027 — node-pty integrity 声明与提取字节 hash 不同**：S observation；未证明根因，不推断包损坏、篡改或打包错误。
- **CLAUDE_DESKTOP-028 — MSIX 声明企业包身份**：S；consumer 安装包未取得，版本/功能等价仍 U。

- **CLAUDE_DESKTOP-029 — Cowork artifact task run has explicit safety gates**：S；具体 artifact 可见、feature/run permission enabled、task exists/enabled、user gesture 检查后才调用 `runNow(personStarted:true)`；静态直连链已闭合。
- **CLAUDE_DESKTOP-030 — artifact MCP call carries per-tool policy and destructive approval**：S；有 visibility/args/server validation、managed policy、disabled gate、destructive prompt/remembered allow；read-only remote call 可有缓存分支。
- **CLAUDE_DESKTOP-031 — extension trust lifecycle includes signed-update check + same-fd archive validation**：S；覆盖缓存更新和重校验后解包路径，策略范围须按具体分支理解。
- **CLAUDE_DESKTOP-032 — `remote || cloudRun` omits local managed-command configuration branch**：S；只证明本地解析路径选择，不能证明远端通信内容。

- **CLAUDE_DESKTOP-033 — legacy Windows VM service IPC is named-pipe JSON RPC**：S；main bundle exposes ClaudeVM IPC, then `\\.\pipe\cowork-vm-service` methods configure/start/stop/spawn/kill/writeStdin and lifecycle events. Service install/launch parent remains U; cloud service internals remain U.

- **CLAUDE_DESKTOP-034 — packaged Windows VM pipe requires system-owned native connect**：S；若 `connectNamedPipeSystemOwned` 缺失，packaged app 直接拒绝连接；未打包开发版本才允许不验证服务身份的 `net.createConnection` fallback。注意这是源码约束，未动态验证 native 实际行为。
