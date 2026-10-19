# Atlas Gap — 与 main 实际源码逐条对照

**基准是本会话实际读取的 Atlas main@aa6196f550098cc46081dc6db2c376cb87ddffa5，不采用旧矩阵。** 
定义：等价=有同语义代码与运行证据；部分=有真实后端/前端但关键机制不同/未追完；仅 UI=表面入口没找到数据/回路；缺失=检查相关位置后没有该链路（非证明全库绝对不存在）；未知=尚未查。竞品列是 Server 源码 S 或官方 D，**Desktop 接线 U**。

| 对照 ID | Codex 可证机制（非 Desktop 可用宣称） | Atlas main 真代码证据 | 现状与不等价点 | 可移植切入点 |
|---|---|---|---|---|
| CODEX_DESKTOP-003 | thread lifecycle 与 fork/resume/list | conversations_router.py:64-160; session_sync.py:561-611；ForkTree.tsx:13-61；client.ts:188-212 | 部分：持久会话读写/分叉确有真正 API/UI；Codex Thread 协议不能直接替换 Hermes SessionDB | 只吸收协议状态分层和历史订阅边界 |
| CODEX_DESKTOP-004 | Daemon 持久 root IDs + 异步冷恢复 | runtime.py:108-151 在 restart 将 running/paused/waiting→failed；SessionDB 保历史 | **真实关键差距**：Atlas 事件恢复元数据，不会续跑先前 active run；对比 Codex cold recovery 仅能证明线程重载，尚不确定旧 turn 是否续跑 | run lifecycle 与 process ownership 分离；保持先前工作状态和恢复策略 |
| CODEX_DESKTOP-005 | 活跃线程恢复回包与订阅在 listener 中有序 | client.ts:524-618 after_sequence + localStorage cursor；runtime_ws_router.py:18-60 | 部分：连接重放存在；未见原子订阅切换和 listener generation barrier；长连接切换、并发窗口需要模拟验证 | adapter/startRunInternal + RuntimeManager/send_run |
| CODEX_DESKTOP-006 | 线程 read-state revision CAS | MessageThread.tsx:15-100 保存虚拟滚动位置；store/useAtlasStore.ts:194-225 只维护消息缓存和分页 | 目前查阅到的代码**没有** firstUnread revision/冲突处理；仍需全域再确认 | conversation metadata + store + notifications |
| CODEX_DESKTOP-007 | Thread Queue 管理增删重排启动（实验） | useAtlasStore.ts:17-20,73-80，queue/steer/redirect；steer_dispatch.py:89-119；runtime_ws_router.py:64-91 | 部分：有即时插话/队列 UI 和后端 steer；暂不能认定有持久队列 reorder 与跨重启一致性 | run queue state、session metadata |
| CODEX_DESKTOP-008/024 | turn/item/diff/patch/PTY 细分 typed events | runtimeEvents.ts:25-45 hardcoded known Set，未认识事件丢弃；timeline.ts:30-75 有固定卡；ChangesPanel.tsx:12-101 | 部分：有工具卡/diff 可交互，但强类型扩展机制是静态封闭事件集合；上游的 delta/patch diff 消费需要逐项设计 | runtime event schema + timeline registry |
| CODEX_DESKTOP-009 | 审批请求/响应及 request-resolved | runtime_ws_router.py:104-153; RunState.approval_futures；ConversationActivity.tsx TimelineRow | 部分且**真实接线**：Future 收到响应；重连/重复点击/请求已处理后的行为需验收，不把它标空按钮 | approval future lifetime + event replay |
| CODEX_DESKTOP-010 | mcpAppUi URI / inline/fullscreen 历史可重建 | ConversationMessage.tsx:2-58 Markdown+Mermaid；timeline.ts:32-75 fixed union；runtimeEvents.ts:25-46 unknown dropped | **未查到等价动态 MCP widget host**：静态消息是强项，未建立结构化 remote widget 资源/渲染/host action 双向链；前后端可能有其它模块需检索，故标待补证缺口而非全库否定 | 单独 widget descriptor + host action bus + session persistence |
| CODEX_DESKTOP-011 | server-initiated dynamic tool request → client response → model | engine/hermes_runtime.py:474-598 MCP register；plugins/runtime.py:122-313 插件操作 | 部分：Atlas 有模型调用服务端工具，但上述阅读范围没找到“服务端请求桌面 JS 执行任意动态工具后再应答”的特定协议；不得和 MCP tools 混淆 | adapter IPC / renderer host-tool gateway |
| CODEX_DESKTOP-012 | Plugins / Apps / MCP 多域对象 | plugins/runtime.py:69-313,462-677；skills_router.py，runtime plugin hooks | 部分、真实后端：本地插件发现/启停/安装/git 更新可见，不是仅 UI；Codex hosted Apps 的账户/动态面板不是相同物件 | 先明确三种对象及生命周期，免造兼容假象 |
| CODEX_DESKTOP-013 | fs/watch/status + fuzzy file search | 文件和 LSP/工具面板存在；代码归属包括 core/atlas/lsp/ 和 frontend/shell/panels/FilesPanel.tsx | 未建立行为等价。文件变动通知、客户端搜索会话触发需要继续源追 | 工具总线 + file panel |
| CODEX_DESKTOP-014 | sandboxed command/exec vs unsandboxed process/spawn 分开 | TerminalPanel.tsx:35-71 xterm WS、108-127 每 3s 进程列表/1.5s 输出；相关 local_execution.py | 部分：交互式 PowerShell 真接线；process 元数据和会话控制跟 App Server command/process RPC 不同 | TerminalPanel/Process API/session ownership |
| CODEX_DESKTOP-015/023 | 每连接实验事件门控、订阅列表、传输选择 | runtime_ws_router.py websocket；backend-adapter/client.ts:524-618；runtimeEvents.ts:25-45 | 部分：Atlas 有连接重放；硬白名单意味着协议扩展默认直接隐藏事件，动态 capability negotiation 未见 | backend-adapter handshake + event registry |
| CODEX_DESKTOP-016 | 模型 catalog 失配显式失败 | models/router.py & api/models_settings_router.py 现存模块（仅看文件与关键路由，未完整读） | 未完成对应性追踪，保留未知，不草率下结论 | model catalogue/requirements |
| CODEX_DESKTOP-019 | 定时本地任务及消息收件箱（D） | core/atlas/automation/engine.py，frontend/pages/AutomationPage.tsx 确有源码（未端到端运行） | UI/API 维度相关，未做持久性/重复计划/离线恢复等同强度验证 | scheduler 与 dashboard 任务状态 |
| CODEX_DESKTOP-020/021 | 真正 Desktop component registry / runner IPC / 更新链 | Atlas Electron frontend/src/main/electron.ts、backendProcess.ts、preload/index.cts 在 main 确有代码；Codex 二进制 U | **不作具体 gap 裁决**：竞品主程序还没拆；下阶段最优先 | MSIX 资源+Electron main traces，之后才谈移植 |

## 最重要的实践含义

1. Atlas **不缺所有基础设施**，大量 UI/API/Engine 代码已连接。问题在两个层次：终端与审查等 UI 的具体行为质量待实测，以及跨重启、跨窗口、未知协议组件可持续运行的机制/状态一致性。
2. 不能拿 CODEX_DESKTOP-004 的 daemon cold-resume 冒充 Codex 已证实“恢复崩溃中的执行现场”。Codex 可证的是线程持久身份和冷恢复流程；Atlas 可证的是将原 active run 改 failed。二者概念不同，下一步用 Windows R 级实验明确比较。
3. 固定消息类型与统一 structured event 注册机制相比的缺口是真实可见的；但**尚无 MSIX renderer 实物代码**就不能决定迁移何种 Codex UI。
4. **禁止在本轮修改业务代码**；将可验证的机制拆成候选实施任务，等二进制/运行证据回来再下施工单。

## MSIX 静态实物对照补记

本次对真实 `26.1013.4894.0` 包有限抽样后，旧表 `CODEX_DESKTOP-020/021` 中“还没拆主程序”的状态已更新为 **部分有 S 证据、runtime 为 U**：preload 暴露 `electronBridge` 固定宿主 API、view/worker message API、MCP app sandbox-host message 转发和经序号/marker 校验的 chunked host ack；主 bundle 有 app-server JSON-RPC client 和 `codex-app-server` WebSocket URI；启动 bundle 有 app-server version literal `0.141.0` 与 runtime executable path 映射；`computerUse` Windows pipe host 有 enable/disable 与重解析路径。这些是 ASAR 静态代码，不等价于 Atlas 已缺失同样能力，也没有证据证明 UI 当前实际调用某一方法或哪个 EXE 在具体 run 中启动。

Atlas 当前 preload 只可确认 `frontend/src/preload/index.cts:1-29` 暴露 `atlasDesktop` API；Atlas runtime stream 的可检出机制锚点是 `backend-adapter/src/client.ts:547-618` 的 version gate、local cursor、resume/replay，`frontend/src/renderer/services/runtimeEvents.ts:25-34` 的 typed event normalization。没有对 Atlas 每个 IPC handler、Codex 全量 webview bundles 或运行行为作等价覆盖。旧表因此不改成“Codex 已全面领先”，本更新只把曾未知的静态接线边界缩小到上述具体证据。
