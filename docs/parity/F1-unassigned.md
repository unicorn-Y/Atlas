# FEATURE-F1 补充盘点：不属于 A 区的独特行为

更新时间：2026-10-11（Asia/Hong_Kong）

本文件记录主基线之外经公开资料核实、但不属于 A 区“编码会话与侧栏”的独特功能，防止在侧栏任务中虚构不具备服务端语义的替代实现。

| 功能 | 产品与来源 | 边界判断 | 归属/后续依赖 |
|---|---|---|---|
| 跨消息渠道 DM 汇入一个长期 Home session；可将同一个 Home 对话 dock 到当前页面，并附带页面/工作 session 上下文快照 | OpenClaw：github.com/openclaw/openclaw/blob/main/docs/concepts/main-session.md | 是跨渠道通信与工作上下文注入，不是普通会话列表分组 | Channels / context capture；需要后端渠道适配、会话路由和页面上下文协议 |
| 常驻 Bot profile 名册、每个 Bot 的 canonical 长期聊天、名册分组、Bot 群聊和 Bot 间 @ 协作 | Hermes Bot Mode：github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/bot-mode.md | 静态配置的专属 Bot 工作区，不等于临时 subagent 或 fork 会话 | Agents / profiles / routing；需要 Bot 配置、运行时和消息路由 |
| 在一个 session 文件内保留多个对话分支，回到旧节点继续/编辑，并可切换分支摘要 | Pi sessions：github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sessions.md | 分支共享一个会话树，与 Atlas 当前创建独立 conversation ID 的 fork 不同 | 对话历史模型区；需要节点式持久化与分支导航，不应由 A 区菜单模拟 |
| 自动归档期限选择（3/7/14/30 天） | ZCode Settings UI 与 locale：zai-org/ZCode，HEAD aac4755666d09fdcd70272fcf063c077a639015c，Apache-2.0 | 自动生命周期和保留策略；侧栏只是展示归档结果 | Settings / lifecycle |
| Claude scheduled sessions 分组、scheduled task 执行与通知 | Claude Code：code.claude.com/docs/en/desktop-scheduled-tasks | 侧栏会显示自动化任务生成的会话，但配置与调度属于自动化 | Automation / scheduler |
| 创建、合并、回收 Git worktree，建立或清理隔离工作目录 | ZCode worktree task actions；Codex 官方 worktrees 文档；Claude Code worktrees 文档 | 侧栏能显示已有工作区信息；生命周期会更改仓库状态 | Git workspace / execution |
| Claude Agent View 的跨项目后台 worker 发现、Peek/Reply/Attach/Detach/Stop，以及跨会话消息投递 | Claude Code：code.claude.com/docs/en/agent-view、cross-session-messaging；2026-07-11 至 2026-10-09 releases | Atlas 当前侧栏能呈现自身运行/未读状态，但没有同等的跨会话 worker registry/消息投递后端 | Agent runtime / inter-session messaging |
| Codex session deep link（codex://threads/<id>）和移动端聊天打开 | Codex Desktop 官方文档及 2026 年 7–10 月更新日志 | 复制 ID 并不等于注册 protocol、路由到会话或完成移动端传递 | Deep links / desktop protocol / mobile |
| OpenCode Home 的 Projects/Servers 工作区路由 | OpenCode 官方 app 页面与项目 API | 项目会话分组可落在 A 区；服务器连接/工作区实例管理是连接器能力 | Server / workspace routing |

## V5 A 项中依赖其他区域的端到端能力（只记录责任边界）

矩阵把以下入口归在会话/侧栏，但完整行为需要跨区域服务或系统接口；A 区已在 `docs/parity/F1-A.md` 逐条记录 Atlas 当前状态，本表供对应区域接续。附录 VI–IX 与固定提交源码优先于主表的勾选。

| 功能 | 产品与来源 | 边界判断 | 归属/后续依赖 |
|---|---|---|---|
| 会话公开分享、选择片段后发布 | ZCode `packages/ui/src/ConversationShareMenu.tsx`，固定 `aac4755666d09fdcd70272fcf063c077a639015c` | Atlas 没有托管分享服务、访问控制或公开链接存储；本地导出不能当公开链接 | C 区服务身份/权限，B 区消息范围选择，后端分享存储/短链 |
| 多窗口、会话浮窗、会话 URL scheme、跨设备与移动端重连 | ZCode `packages/desktop/src/main/desktopApplicationMenu.ts`；Claude Desktop/Remote Control；Codex 2026-10 changelog | 侧栏只能发起入口；Electron window lifecycle、协议注册、设备认证和恢复状态不属于 Sidebar | C 区 Electron 主进程、设备/深链 API；A 区接入完成后的导航入口 |
| PR 状态徽章、Local↔Worktree handoff、worktree 自动清理/回收 | Codex 官方 changelog/worktrees；Claude `docs/en/worktrees` | PR 状态需要可信的 GitHub 数据；handoff/cleanup 会改变分支及工作目录，不能从 UI 文案推断 | C 区 GitHub 集成设置；D 区 worktree/PR 工具；A 区会话徽标消费字段 |
| 跨会话 Agent 检索/消息、Dispatch、跨项目 worker 调度 | Claude Desktop、[Agent View](https://code.claude.com/docs/en/agent-view)；Codex 移动端官方 changelog | 需要可发现的 session/worker registry、权限检查、消息通道和任务路由；普通会话列表不等价 | C/D 区 Agent 与渠道运行时；A 区只展示已验证状态 |
| Claude Cloud Projects 持续任务 | [Claude Projects](https://code.claude.com/docs/en/claude-projects) | 共享云目标、仓库与记忆不是 Atlas 本地项目会话关联 | C 区云项目/身份服务；A 区可接入项目任务列表 |
| OpenCode Web pair 与 SSH server registry | OpenCode V2 docs；`packages/app/src/settings/servers/servers.tsx`，固定 `7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937` | Web pair、服务认证与 SSH 实例注册不同于 Atlas 当前 SSH workspace path | C 区服务端/远程连接与授权；A 区可提供每会话导航 |

来源限制：补充核查只将查到的具体公开文档/源码当作证据；未发现公开材料不代表该产品绝不存在相关行为。跨区项目应由相应区实现完整端到端行为，不以 A 区前端静态标签代替。
