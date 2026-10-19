# Atlas main 实际对照：source-backed gap analysis

> **基线复核**：`origin/main` SHA `aa6196f550098cc46081dc6db2c376cb87ddffa5`。当前新增包证据只证明客户端静态组件与部分桥 API，不证明云端/服务端行为；下表原有 Atlas 行仍按 Atlas 源码证据判定。

**Atlas baseline** `aa6196f550098cc46081dc6db2c376cb87ddffa5`。**比较限制**：Claude 行为来自官方 D，不存在本安装包 S/R 对照，故每条只说明 Atlas 代码中已证实的行为与技术差异，**不能断言 Claude 私有实现细节**。严重程度基于 Atlas 目标的用户影响，而非静态功能数量。

| 对照主题 | Claude 官方 D | Atlas main 真实 S | 缺口判定 / 落点 |
|---|---|---|---|
| **交互式 run 脱离窗口继续** | 云任务关闭笔记本后继续，依赖本机工具时等待 Desktop | `frontend/src/main/electron.ts:231-242` 退出停自管后端；另有 `core/atlas/runtime/hub.py:119+` 独立任务循环 | **部分实现，不等价**：Hub 有后台任务，但普通前台 run 缺稳定移交；研究 `frontend/src/main/backendProcess.ts`、`core/atlas/runtime/hub.py` |
| **重启继续原任务** | 云 Unified VM 空闲存盘快照，跨端恢复工作 | `core/atlas/api/runtime.py:108-152` 重启将 running/paused/waiting → failed；`run_drive.py:1420-1428` 存计划显式 resume_from | **明确机制差异**：存在计划层续做，不是自动保持工具现场与 runner |
| **事件持久流/跨端订阅** | 云会话账号级状态和跨端同步 | `runtime.py:43,82-95` run.events 内存；`run_drive.py:2040-2067` 只遍历内存；`backend-adapter/src/client.ts:553-615` WS cursor localStorage | **部分实现**：同进程断线可重放，但服务跨重启 replay 不完整 |
| **Unified chat→task 自动升级** | 同会话自动执行任务，旧版模式 selector 渐进下线 | `frontend/src/renderer/App.tsx:1017-1033` 分 view；`useAtlasStore.ts:1001+` 显式 mode/actor 属性 | **未见等价自动转场**（限已读源码），可在 `App.tsx`、`run_drive.py` 查能力路由 |
| **本机/云端设备桥** | Cloud agent 经 Desktop 在线通道触达本机资源 | `core/atlas/api/runtime_ws_router.py` 直连本机 run WS；`core/atlas/runtime/hub.py` 本地 agent | **架构不同**：未在已查代码中证实 Cloud Agent→Desktop broker 机制；需跨 API/设备控制继续查 |
| **子任务动态进度/steer** | 官方支持计划/并行子任务 | `ConversationActivity.tsx:132-188` 已有 step UI/取消/steer；`runtime_ws_router.py:84-102` 转交 steering；`agent/tool_node.py:650+` 子任务事件 | **已有接线**：不能标“没有”；待实际执行行为级对照 |
| **审批与工具权限** | Desktop 与云工具有分层授权、可减少中途询问 | `runtime_ws_router.py:141-152` approval.response；`run_drive.py:1000+` permission_mode；`tool_node.py:240+` 多种策略 | **部分，非空壳**：应核对 scope、持久授权、断线等待 |
| **内置浏览器与 CU** | 有内置浏览器、必要时 screen interaction | `frontend/src/renderer/shell/panels/BrowserPanel.tsx`、`components/x2/*`；`core/atlas/tools/x2/browser.py`、`computer.py` | **现有功能通路待实测**：不能仅由组件得出效果等价或完全失效 |
| **计划任务独立 run history** | 计划可管理、审查历史并跨端使用 | `core/atlas/scheduler/__init__.py` schedule CRUD 与触发；`core/atlas/runtime/hub.py:119+` scheduler 进程；`AutomationPage.tsx` UI | **有后端**：区别是跨端 account sync/云 runtime、任务发生记录是否独立可见 |
| **会话元信息与 transcript** | 云账号级 conversation+project files | `core/atlas/engine/session_sync.py:1-10,70+` SessionDB 真正保存消息；`core/atlas/api/conversations_router.py:64-149` 列表/历史/分叉 | **本地真实落盘**，不是空壳；但账号级同步/多端一致性未见对等设计 |
| **交互式文档/幻灯片** | Claude Docs/Slides/Design 同会话中可编辑 | `runtimeEvents.ts` 将 `artifact.created` 转 `artifact.updated` 文件展示；`App.tsx` `CreatePage` 入口 | **只证明生成文件与展现**；未证实与 Claude shared live editing 相等 |
| **未知 wire 事件可见性** | 官方强调执行过程可见，可动态加新工作流 | `runtimeEvents.ts:12-38` 限定 known Set，unknown return null；`MAX_RUN_EVENTS=800` | **确定的渲染接线边界**：新事件可能后端产出但 UI 丢弃；建议在 store/event adapter 统一 schema 发现与路由 |

## 重要纠偏
1. Atlas 并不是只做了外壳：SessionDB、WebSocket reconnect、step/subtask interaction、scheduler/Hub 均可指到后端代码。
2. Atlas 确实有**明确可验证的运行时边界**：desktop 退出停自管进程、restart→failed、只重放进程内 event list。这三个是源代码直证，与用户要求的长期自主 Agent 持续性最相关。
3. `resume_from` 的 plan 继续并不保证任意工具执行精确一次或现场快照恢复；官方云沙箱快照亦不能推断实现细节。
4. 此阶段**不提出直接复制 Claude 闭源代码**。可移植的是明确结构原则：任务身份独立于窗口、统一事件日志、host/engine 生命周期分离、客户端动态事件组件映射。

## 推荐先验收而非直接开大工程
P0：复盘 interactive run 的 restart/replay 链路以及 Hub 接管边界；P1：实际包解析 Claude 设备桥和 cloud/local negotiation；P2：可选 UI 自适应 workflow、交互型 artifact、计划任务跨端。每个缺口要有本地实测、原始源位置及行为差异，不以功能菜单计数。
## 新增模块的 Atlas 对照（以已核实的 Atlas main 为准）

- **签名 MCPB 安装 / TOCTOU**：Atlas `core/atlas/evolution/capability_diff.py:169-183` 记载 MCP client 为 partial，并明确 mcpb packaging 未做；`core/atlas/tools/mcp_client.py:1-3,171-193` 是 MCP server process/client 管理。当前读取的代码没有对应 Claude DXT/MCPB 文件下载、验签、暂存与同 fd 解包链，因此此子能力为缺口；这不等于 Atlas MCP client 没有实现。
- **built-in Node self-spawn guard**：Claude 有明确错误类型限制内置 Node host 的二次 Node 派生。Atlas 在本次相关源码中采用后端进程管理 MCP servers（`core/atlas/tools/mcp_client.py`）；没有发现与 Electron embedded Node host 等价的设置或拒绝保护。只判定未找到等价机制，不推断安全影响。
- **终端 scrollback**：Atlas UI 的 `TerminalPanel.tsx:39` 设置 xterm in-memory `scrollback: 5000`，`TerminalPanel.tsx:53-66` 用 `/ws/terminal` 收发 resize/input；`core/atlas/api/tools_router.py:92-130` 管 WebSocket terminal 生命周期。查阅范围内未见等价的独立滚动日志落盘/脱敏读取 API。属于机制差异；Atlas 仍有交互终端功能。
- **文件索引 worker**：本轮查阅 Atlas `frontend/src` 与 `core/atlas` 未找到按 MessagePort worker 构建本地文件索引的同类模块；workspace 文件浏览路径需另行核对，不将搜索无命中升级为全功能缺失结论。
- **云/本地任务迁移**：Claude bundle 有 `remote || cloudRun` 命令解析分支与 `migratedToRemoteAt`/revert telemetry。Atlas `runtime_ws_router.py` 与 `run_drive.py` 显示本地 WS run/显式 `resume_from` 路径；已阅范围未发现 cloud-copy handoff 等价链。判为未证实/机制差异，不能推断 Claude 云端实现细节。


### VM/worker and local-vs-remote execution refinements

Claude's package now provides stronger evidence than a generic local service binary: the main bundle has a `ClaudeVM` IPC schema and Windows pipe client for a legacy Hyper-V VM lifecycle and process-spawn channel (see evidence module trace). Atlas's current local terminal uses a renderer WebSocket and `pywinpty`/async process on the host (`core/atlas/api/tools_router.py:92-130`); this is functional but not an equivalent VM-isolated guest shell. Atlas has no evidence here of a Windows Hyper-V guest service, gvisor network backend, VM bundle download/snapshot lifecycle or named-pipe guest process RPC. Conversely, Claude's artifact bridge is a separate user-facing tool surface; don't equate it with the legacy VM service. Cloud execution's server internals remain unknown.


Claude main also fail-closes packaged VM pipe connection when its native system-owned pipe connector is missing; the unauthenticated `net.createConnection` fallback is explicitly dev-only. Atlas source reviewed here has no analogous privileged Windows VM service-pipe connection contract because it launches workspace processes through its local backend. This is an architecture boundary, not a generic claim that Atlas IPC lacks authentication; Atlas WebSocket/API security needs its own comparison.
