# UI and workflows — 已见包级入口与仍未动态验证的行为

> **2026-10-19 包内静态补充**：确认 15 个 BrowserWindow 构造、main/quick/about/buddy/find/local-consent renderer 资产及 `CoworkArtifactBridge` 五类 API。没有获得完整 route→action→IPC→state 链，也没有运行 UI；原有官方 D 级交互仍不能当成本包行为。部分映射见 `evidence/ui-route-action.tsv`。

以下未由 bundle 静态代码闭合的产品/UI行为为 **D（官方文档）**。2.42304.0 有限静态 view/bridge 已在开头列明；没有运行并录屏/抓日志，不称已动态遍历。所有分支和开关在不同套餐/rollout 中可能不同。

| 流程 | 已确认入口/用户行为（D） | 需实包补的证据（U） |
|---|---|---|
| Claude Unified 会话 | 在同一对话输入普通问题或委托任务；产品可升级至任务执行，再回到聊天 | mode selection、transition action、消息/任务卡 schema、账号实验开关 |
| 旧版 Chat/Cowork | 输入区可有 Cowork/Chat 切换；新版部分账号不再显示选择器 | 两版路由差异、何时进 cloud / local |
| Desktop 文件任务 | 连接本地文件夹，创建/修改结果并在会话中预览 | folder picker、上传映射、权限、File APIs、task result preview |
| 多步骤任务 | 查看方案、任务执行过程、对需要确认的步骤介入 | plan/tree 组件、逐条进度事件、子任务 card 与执行源头 |
| 内置浏览器 | Desktop 侧面板打开由 Claude 控制的浏览器；在交互中可看导航动作 | native browser/window/session API、网络隔离和权限 |
| 自己的 Chrome | 使用 Claude in Chrome 可在用户现有 Chrome 上操作 | 与内置浏览器工具切换条件，插件通信/权限 |
| Screen interaction | Desktop 电脑操作可鼠标键盘交互；部分平台可后台窗口操作 | Windows 具体实现、截图与 tool receipt、窗口失焦行为 |
| 云任务跨端 | 桌面启动任务后在 web/mobile 查看，关闭 laptop 仍可继续；本机工具需 Desktop 在线 | account task ID、订阅 transport、设备桥 online/offline |
| 计划任务 | 左侧 Scheduled → New task；频率、审批、模型、可选 folder；列表查看历史、手动运行/暂停/恢复/删除 | schedule/occurrence 的 store、执行归属、失败恢复 |
| 项目关联 | Project 有文件、指令、上下文和记忆；跨端恢复 | project→task→conversation 关联字段、索引 |
| Docs/Slides/Design | 在会话中创建并直接修改共享文档/幻灯片等 | interactive component registry、编辑 transaction、版本和保存 |
| 插件/本地 MCP | 安装/启用扩展，云端任务借 Desktop 使用本机资源 | MCPB/DXT 发现与 host loader、权限、停机处理 |
| 通知与后台反馈 | 结束/失败/审批待办从账户与 Desktop 显示 | 通知中心、system tray、后台弹窗、托盘退出策略 |

官方参考：
- <https://claude.com/blog/cowork-is-now-claude>（2026-09-16）
- <https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile>
- <https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork>
- <https://support.claude.com/en/articles/16607400-use-the-built-in-browser-in-claude-cowork>
- <https://support.claude.com/en/articles/14128542-let-claude-use-your-computer-in-cowork>
- <https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-claude-cowork>
- <https://support.claude.com/en/articles/14116274-organize-your-tasks-with-projects-in-claude-cowork>

## Atlas UI：当前 main 有明确代码入口（S）
- 主应用 `frontend/src/renderer/App.tsx:1017-1033` 有 `board/agents/groups/code/auto/memory/skills` 独立页面，但不是 Claude 的统一会话/任务自动转换。是否“一页套壳”应追 `startRun` 实现而非看路由名称。
- `frontend/src/renderer/components/ConversationActivity.tsx:132-188` 有步骤 timeline、失败详情自动展开、停止子任务和补充要求输入框；后端 WS `subtask.message` 存在。
- `frontend/src/renderer/services/runtimeEvents.ts:10-35` 只识别有限 known 事件；未列出的事件被忽略，容易造成“后台有机制、前端不显示”的盲区。
- `frontend/src/renderer/shell/panels/BrowserPanel.tsx`、`frontend/src/renderer/components/x2/BrowserRecorderPanel.tsx`、`ComputerReplayPanel.tsx` 为真实 UI 组件，不能凭名字认定其运行路径已与 Claude 等价。
- `frontend/src/renderer/App.tsx:85-90` 输入草稿在本机 localStorage；`frontend/src/renderer/components/Composer.tsx:52-65` 历史输入缓存亦然，与云账号级同步无直接证据。

## 复现用 UI 动态验收序列（当前未执行）
1. 新用户/旧用户/Enterprise rollout 账户分别观察新建会话的 mode picker 与任务切换。
2. 任务进行中关闭 Desktop、保持云任务，重开后查看同 task ID 的进度，再触发本地文件工具失败/恢复。
3. 启动本地 legacy Cowork（若账号允许）并核实 hypervisor/service 进程与本地 DB。
4. 内置浏览器与 Chrome 执行相同导航，比较两条工具事件流及窗口归属。
5. 启动计划任务、断网、跨设备查看 run history，抓 store/session 关联。
6. 检查交互式 Docs/Slides/Design 的组件生成、局部编辑、刷新后存储。
以上需要可授权测试账号和实际 Windows 环境；不能用包静态字符串冒充 R。

## 已闭合的静态交互链（R 未观察）

- Cowork artifact 的 scheduled-task 入口从 `window.cowork.runScheduledTask(taskId)` 进入 generated `ipcRenderer.invoke`，由 main 检查 feature rollout、run 权限、artifact visibility、task/enabled 状态和用户手势，再交给 scheduler `runNow(...,{personStarted:true})`。handler 返回 session ID/error。调用后的 Agent turn、任务落盘及恢复仍未知。
- 同一 artifact bridge 的 MCP 调用有 server/tool 校验、managed policy、disabled gate 与 destructive approval；主聊天中的工具执行链尚未从 renderer route 完整配对。
- 精确包的全局 parser 无 JS parse failure，但语义图被截断；详见 `COVERAGE.md`。这不等于全部 route/action 已枚举。
