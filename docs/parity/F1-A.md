# FEATURE-F1 A 区：会话与侧栏对标

更新时间：2026-10-11（Asia/Hong_Kong）

## 范围与来源

按 docs/plan/FEATURE-F1.md 第 0 节与第 1 节 A 区执行。盘点侧栏、会话列表、筛选/分组、会话级命令和状态入口；跨渠道收件箱、常驻 Bot 名册、对话树编辑、工作树创建/合并、自动化配置、工具执行能力分别属于其他区，不在本区伪造数据或重复实现。

| 产品 | 固定来源 / 范围 |
|---|---|
| ZCode | zai-org/ZCode，HEAD aac4755666d09fdcd70272fcf063c077a639015c，Apache-2.0。检查桌面会话侧栏、分组/排序/归档、行菜单/命令中心/快捷键/设置/i18n。主组件及 locale 路径见各行。 |
| OpenCode | anomalyco/opencode，HEAD 7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937，MIT。检查 app 页面/会话与项目组件、快捷键注册和设置、命令及英文 i18n。会话 Home 不提供启用中的归档 UI（SHOW_HOME_SESSION_ARCHIVE=false）。 |
| Codex | openai/codex，HEAD 47bcb3a3f9e0904aed485389aaf410282b6b23fa（2026-10-10）。另逐页查阅 2026-10-11 可见的官方桌面、会话、快捷键和更新日志文档；近三个月变更按 2026-07-11 至 2026-10-11 筛选。 |
| Claude Code | 官方 Desktop、Manage sessions、Agent view、Commands、Cross-session messaging、Worktrees、Checkpointing 文档；CHANGELOG.md 与官方 releases 按 2026-07-11 至 2026-10-11 筛选。闭源，不存在可移植的本地源码路径。 |
| 补充独特项 | 仅核查 Hermes Bot Mode、OpenClaw main session、Pi sessions；如果与 A 区职责不同，则记录在 docs/parity/F1-unassigned.md。 |

## 逐项清单

“Atlas 基线”是本分支实施前检查结果；“本次处理”在实现与界面核查后更新。源码采用开源实现时，在代码文件头标明仓库、固定 HEAD 与许可证，并在 THIRD_PARTY_NOTICES.md 追加许可说明。

| 功能 | 哪家有 | 源码路径或文档 | Atlas 基线 | 本次处理 |
|---|---|---|---|---|
| 会话侧栏与最近会话列表 | ZCode、OpenCode、Codex、Claude Code | ZCode packages/ui 的 sidebar/task 组件；OpenCode packages/app 会话列表组件；Codex 官方 Desktop 与 sessions 文档；Claude Desktop 与 Manage sessions | 有会话列表；未核实完整历史与各产品状态 | 补齐列表覆盖范围、分组入口与会话状态 |
| 新建会话及空白草稿生命周期 | ZCode、OpenCode、Codex、Claude Code | ZCode 新会话命令与 UI 注册；OpenCode app session commands；Codex Desktop 文档；Claude Desktop 文档 | 新建立即创建持久会话，未实现首条消息前的临时草稿语义 | 保留 Atlas 现有创建语义；空草稿行为记为已知差异，检查实现边界 |
| 恢复、继续、切换已存在会话 | ZCode、OpenCode、Codex、Claude Code | Codex TUI session picker 源码及 sessions 文档；Claude Manage sessions；OpenCode session routes/commands；ZCode sidebar commands | 点击侧栏可切换；列表 API 默认只取 50 条 | 列表默认返回完整历史；保留现有点击切换 |
| 按标题/提示词/ID 搜索会话 | ZCode、OpenCode、Codex、Claude Code | ZCode TaskFind 与 Command Center；OpenCode app search/session commands；Codex session picker 搜索与官方桌面搜索；Claude Manage sessions、Agent view | 有全局搜索，但侧栏没有独立会话过滤输入 | 增加侧栏会话过滤；全文搜索沿用既有搜索 API |
| 搜索会话消息全文（跨会话） | OpenCode、Codex、Claude Code | OpenCode `packages/app/src/home/sessions/search.ts`；Codex 官方桌面搜索文档；Claude Manage sessions 与 Agent view | 后端已有 GET /api/search；侧栏过滤不直接搜正文 | 保留跨会话全文搜索；本会话查找见下方新增项 |
| 会话内文本查找 | Atlas 新增；竞品矩阵未单列，OpenCode TUI 的同名需求仍见 feature request | Atlas `core/atlas/api/conversations_router.py`；OpenCode TUI 需求记录：[issue #15602](https://github.com/anomalyco/opencode/issues/15602)（需求记录不是产品能力证据） | 详情面板无当前会话全文查找 | 新增当前会话全文查找 API 与详情面板；默认大小写不敏感，显示最近 50 条匹配及上下文片段 |
| 按状态筛选（运行、等待、完成、错误、未读） | ZCode、Codex、Claude Code | ZCode task list status 与 locale；Codex 活动/优先级视图文档；Claude Desktop、Agent view 及 v2.1.207、v2.1.257、v2.1.287 changelog | 有运行与未读提示，无统一筛选器；无持久化 completed/error 状态字段 | 补充可从现有运行/未读数据确认的筛选；不制造未存储状态 |
| 按项目、环境、工作树筛选 | ZCode、OpenCode、Codex、Claude Code | ZCode task scope/project 列表；OpenCode Projects 与 Servers 页面；Codex session picker cwd/all 和官方 Projects 文档；Claude Desktop、Manage sessions | 会话含 workspace/worktree 元数据；侧栏无项目/环境过滤器 | 加入项目/工作区分组与筛选；环境状态只显示真实字段 |
| 按今日/昨日/更早时间分组 | OpenCode、ZCode、Codex | OpenCode session list grouping；ZCode timeline grouping；Codex session picker | 按日期已有粗粒度分组 | 保留并对齐清晰的日期分段 |
| 自定义会话分组、折叠及重命名 | ZCode、OpenCode、Claude Code | ZCode custom groups UI/commands/i18n；OpenCode project/session grouping；Claude Agent view | 只有内建日期、标签色、名称、置顶、归档分组 | 增加可持久化自定义分组与折叠 |
| 拖动会话排序或移入分组 | ZCode、OpenCode、Claude Code | ZCode draggable task/group/project UI；OpenCode project reorder；Claude Agent view reorder | 未发现手动拖拽排序 | 增加组内重排及可支持的分组移动 |
| 项目会话归属与项目导航 | ZCode、OpenCode、Codex、Claude Code | ZCode project/task tree；OpenCode Projects 页面及 /api/projects 相关前端；Codex Projects 文档；Claude Desktop | 后端已有项目 CRUD/attach/detach；侧栏未列项目会话 | GET /api/projects?include_conversations=true 提供关联；侧栏接入并在拖拽/选择项目时移出其他项目关联 |
| 项目创建、重命名、导入/关闭、最近关闭 | OpenCode、Codex、Claude Code | OpenCode Projects 页面与项目命令；Codex Desktop Projects 文档；Claude Desktop | 已有 API 支持项目 CRUD/关联；侧栏 UI 未覆盖完整项目动作 | 在 A 区完成项目会话导航/归属；项目导入/仓库操作若需 Git 流程归 D |
| 置顶会话及置顶排序 | ZCode、OpenCode、Codex、Claude Code | ZCode pin/task group UI；OpenCode session actions；Codex Desktop chats 文档；Claude Agent view | 已有置顶与置顶分组 | 保留现有能力并纳入菜单/分组 |
| 归档、取消归档及归档列表 | ZCode、Codex、Claude Code | ZCode archive/list actions；Codex Desktop chats 文档；Claude Desktop / Manage sessions；OpenCode Home archive UI 当前禁用 | 有归档和可折叠归档区；无批量管理 | 保留单条归档/恢复，增加批量入口；明确 OpenCode 当前没有启用的 Home 归档 UI |
| 批量选择、归档、删除 | ZCode、Codex | ZCode bulk archive/delete 与 archive count UI；Codex Desktop 批量归档文档 | 未见批量选择操作 | 增加多选及批量归档/删除，并显示受影响数量与确认 |
| 删除确认及单条恢复/历史清理 | ZCode、OpenCode、Codex、Claude Code | ZCode archive/delete menu；OpenCode session context menu；Codex Desktop；Claude Manage sessions | 单条删除有确认；恢复只覆盖归档，不提供撤销删除 | 保留删除确认；不声称删除可恢复 |
| 右键菜单、键盘菜单键与触屏长按 | ZCode、OpenCode | ZCode task context menu；OpenCode session context menu 支持 right-click/Shift+F10/long-press | 只有更多按钮下拉菜单，未绑定行右键 | 增加同一组操作的右键/键盘入口；触屏按现有 Electron UI 能力核验 |
| 会话重命名 | ZCode、OpenCode、Codex、Claude Code | ZCode rename task；OpenCode session context menu；Codex Desktop chats；Claude Desktop 与 /rename | 已有双击和菜单重命名 | 保留并从上下文菜单及键盘入口提供 |
| 会话复制/克隆为新会话 | ZCode、OpenCode、Codex、Claude Code | OpenCode Session.fork / clone commands；Codex /fork；Claude Manage sessions /branch；ZCode fork command | 有 duplicate 与 fork；Atlas fork tree 为新会话 ID | 保留现有独立会话复制/分叉；Pi 同 session 树分支记录在 B 区 |
| 在旁边/新标签打开会话 | ZCode、OpenCode、Codex、Claude Code | ZCode split/open beside；OpenCode session tabs；Codex Desktop multitasking；Claude Desktop multi-session | 已有并排打开入口与标签 store | 接入列表菜单并复用现有 tab 行为 |
| 导出会话 | ZCode、OpenCode、Codex、Claude Code | ZCode export action；OpenCode session export JSON；Codex Desktop export/share；Claude Manage sessions export | 已支持 Markdown 和 JSON 导出 | 保留现有格式与导出路径 |
| 复制会话 ID、日志数据库路径、工作区路径 | ZCode、Codex、Claude Code | ZCode `packages/ui/src/TaskActionMenuContent.tsx`；Codex deep link/thread id docs；Claude Desktop open directory | 可从数据/API获得 ID 与 workspace；Atlas 使用共享 SessionDB，侧栏无复制入口 | 增加 ID、工作区路径和 canonical `engine/state.db` 共享日志数据库路径复制；文案说明路径为共享数据库，不伪称每会话独立文件 |
| 从会话打开项目目录 | ZCode、OpenCode、Codex、Claude Code | ZCode open folder action；OpenCode project/session actions；Codex Projects 文档；Claude Desktop | 有 Electron openPath 能力；侧栏缺少入口 | 增加可用目录的打开入口 |
| 运行、等待输入、未读提示 | ZCode、Codex、Claude Code | ZCode task status badges；Codex Activity/Priority 文档；Claude Agent view、Desktop、v2.1.207 与 v2.1.257 changelog | 已有运行/未读；没有 waiting-input 的持久来源 | 使用真实运行/未读及权限状态绘制；补齐 Atlas 已有状态，不伪造外部 worker 状态 |
| 标记未读与已读 | ZCode、Codex、Claude Code | ZCode unread action；Codex unread/activity docs；Claude Agent view | 打开时清未读、后台完成设置未读；无手动标记未读入口 | 增加手动未读/已读操作；用户标记的未读会话保存在本机侧栏状态，打开后清除 |
| 运行中/等待输入/完成通知与活动视图 | ZCode、Codex、Claude Code | ZCode row status；Codex Activity view 文档；Claude Desktop notifications、Agent view、v2.1.210/v2.1.295/v2.1.296 changelog | 可见运行状态和未读；无统一活动页/原生通知状态归一化 | 侧栏呈现已存在状态；Activity、通知投递机制不在本区重建 |
| 会话详情、状态、成本与轮次统计 | ZCode、Codex、Claude Code | ZCode `packages/ui/src/TaskListItem.tsx` 与用量事件；Codex thread metadata/session picker；Claude Manage sessions | 会话摘要含工作区、分支、权限；没有 per-session 成本/轮次面板 | 新增详情面板，显示真实用户轮次、UsageLedger 运行记录、token 和费用；未命中价格时显示“暂无价格数据”，不将未知成本写为 0 |
| 按会话成本/轮次统计展示 | Atlas 新增；ZCode 会话详情提供用量线索 | Atlas `core/atlas/api/conversations_router.py` 的 `/stats`；ZCode `packages/ui/src/TaskListItem.tsx` | 无会话级汇总 | 统计 canonical SessionDB 用户消息轮次并按 conversation 聚合 UsageLedger；展示成本、token 和运行记录 |
| 快捷键打开搜索/选择器、切换会话组 | ZCode、OpenCode、Codex、Claude Code | ZCode shortcut registry/keybindings setting；OpenCode app keybind registry/settings；Codex TUI keymap 与官方 shortcuts；Claude commands 与 v2.1.288 | 有 Ctrl+K 与全局可重绑定快捷键面板；无侧栏专属快捷键 | 复用已有键绑定系统；不覆盖其他区域快捷键归属 |
| 命令中心/命令面板中的会话命令 | ZCode、OpenCode、Codex、Claude Code | ZCode Command Center scopes/command registry；OpenCode session commands；Codex command docs/TUI actions；Claude Commands 与 v2.1.212 | 已有 Ctrl+K 命令面板及少量会话操作 | 将本区真实会话操作加入可发现菜单；执行能力沿用已有 handler |
| 可编辑快捷键与冲突处理 | ZCode、OpenCode、Codex、Claude Code | ZCode keybindings settings；OpenCode keybind settings；Codex TUI keymap；Claude v2.1.288 | Atlas ShortcutsPanel 已支持重绑定与冲突处理 | 若新增快捷键，沿用现有注册，不另建配置 |
| 设置项/i18n 对照 | ZCode、OpenCode、Codex、Claude Code | ZCode packages/ui/src/i18n/locales/en-US.ts、zh-CN.ts 与设置页面；OpenCode packages/app/src/runtime/i18n/en.ts 与 keybind 设置；Codex 官方 shortcuts/config 文档；Claude 官方文档 | Atlas 采用 renderer locale/UI 文案；新增侧栏文案需覆盖中英文 | 新增可见文案接入 Atlas 当前 locale；源码移植保留许可证头 |
| 自动归档期限选择 | ZCode | ZCode Settings 的 3/7/14/30 天自动归档选项及 i18n | 未见自动归档设置 | 自动归档策略及定时生命周期不是 A 区侧栏 UI，本次不接入；见 F1-unassigned |
| 深链打开指定会话 | Codex、Claude Code | Codex codex://threads/<id> 官方 desktop 文档；Claude claude --desktop --resume 官方 changelog v2.1.285 | 无 Atlas protocol 注册/深链处理 | 不只做复制 ID 的假链接；深链协议留待 C/D 端到端接入 |
| Home session 跨消息渠道聚合与 dock | OpenClaw 独有 | openclaw/docs/concepts/main-session.md | Atlas 没有跨渠道 DM 会话适配器 | 不是本区普通编码会话侧栏；记入 F1-unassigned |
| 常驻 Bot 名册、Bot Chat 和 Bot 群聊 | Hermes 独有 | NousResearch/hermes-agent/website/docs/user-guide/bot-mode.md | Atlas 没有 Bot profile/roster 后端 | Bot 管理和多 Bot 路由依赖 C/D；记入 F1-unassigned |
| 同一会话文件内保留/切换分支 | Pi 独有 | earendil-works/pi/packages/coding-agent/docs/sessions.md | Atlas fork 会创建另一 conversation ID，不是同一文件树分支 | 数据模型/历史导航属于 B 区，记入 F1-unassigned |
| Claude Agent View 跨项目后台 worker、Peek/Reply/Attach/Stop | Claude Code | code.claude.com/docs/en/agent-view；v2.1.207–v2.1.296 官方 changelog | Atlas 有当前会话运行状态，未见跨会话 worker registry 与投递 API | 本次仅呈现 Atlas 自身可确认的会话状态；跨会话 worker 归 C/D |
| Claude scheduled session 分组/通知 | Claude Code | code.claude.com/docs/en/desktop-scheduled-tasks | Atlas 无定时任务会话来源 | 自动化定义和调度不在 A 区；见 F1-unassigned |
| Worktree 会话创建、恢复、合并、清理 | ZCode、Codex、Claude Code | ZCode worktree task actions；Codex官方worktrees文档；Claude code.claude.com/docs/en/worktrees | 会话有 worktree 元数据，创建/回收属于项目 Git 流程 | 侧栏显示已有 worktree 字段；完整生命周期归 D |

## V5 矩阵 A 行逐项补充与校正

已将 `D:\atlas-parity\四大Agent功能矩阵V5.md` 的 A01–A45 与上表逐项核对。上表已有同义项的仍以其原行作为主记录；下列是矩阵多出的独立能力、平台限定行为或需要补充的差异。矩阵附录 VI–IX 与固定提交源码优先于主表勾选；`?`、空白和 feature request 均不作为产品已有能力证据。

| 功能 | 哪家有 | 源码路径或文档 | Atlas 现状 | 本次处理 |
|---|---|---|---|---|
| 项目/工作区多窗口 | ZCode、OpenCode、Claude Code | ZCode `packages/desktop/src/main/desktopApplicationMenu.ts`；OpenCode `packages/app/src/runtime/i18n/zh.ts`；[Claude Desktop](https://code.claude.com/docs/en/desktop) | 单窗口承载多会话；没有每项目独立窗口生命周期 | Electron 窗口策略归 C 区，本次记录到 `F1-unassigned.md` |
| 会话公开分享链接 | ZCode | ZCode `packages/ui/src/ConversationShareMenu.tsx`（固定 HEAD `aac4755666d09fdcd70272fcf063c077a639015c`） | 无托管分享服务、公开链接存储或访问控制 | 不伪造公开链接；分享服务及权限流程列入跨区依赖 |
| 共享片段范围选择 | ZCode | 同上；ZCode share UI 会筛选要发布的会话内容 | 无公开分享流程，也无可选择后发布的会话片段 UI | 依赖分享服务与消息范围 UI，列入跨区依赖 |
| 模型轨迹入口 | ZCode | ZCode `packages/ui/src/TaskActionMenuContent.tsx`；模型轨迹分类见矩阵附录 VIII-A2 | 会话详情可看状态和 UsageLedger 汇总；侧栏没有可打开的 Model/Reasoning/Tool Calls 轨迹面板 | 不把统计面板冒充模型轨迹；轨迹检视器依赖 B 区运行事件视图 |
| 最近会话/上一条/下一条导航 | ZCode、OpenCode、Codex、Claude Code | ZCode `packages/ui/src/v4/ConversationHeader.tsx`；OpenCode `packages/app/src/runtime/i18n/zh.ts`；Codex `codex-rs/tui/src/slash_command.rs`；[Claude sessions](https://code.claude.com/docs/en/sessions) | 完整历史侧栏可切换会话；没有上一条/下一条的独立控制 | 完整列表与恢复已可用；相邻会话快捷导航未新增 |
| 会话目录迁移 | OpenCode | OpenCode `packages/core/src/tool/plugin/opencode.ts`：`session_move(sessionID?, directory)` | 会话可设置工作区，但侧栏无选择器 | 增加“更改后续工作目录”菜单，调用桌面目录选择器和现有 `setWorkspace`；不声称搬迁已有 Git worktree |
| 后台会话/任务 | ZCode、OpenCode、Codex、Claude Code | ZCode task 状态与 actions；OpenCode `packages/app/src/session/commands/use-session-commands.tsx`；Codex 官方 Projects/Activity 文档；Claude Desktop sessions | Atlas 运行在切换会话后继续，侧栏可显示运行状态 | 保留运行状态标记；后台运行沿用当前 run 生命周期 |
| 异步消息待发送队列 | ZCode、OpenCode、Codex | ZCode `packages/ui/src/i18n/locales/zh-CN.ts`；OpenCode `packages/app/src/session/composer/queue-panel.tsx`；Codex `codex-rs/tui/src/session_queue_commands.rs` | store 已有队列；侧栏不显示各会话队列长度 | 增加侧栏待发送数徽标和无障碍标签，读取现有队列状态 |
| 会话工作树清理 | ZCode、Codex、Claude Code | ZCode worktree task actions；Codex 官方 worktrees 文档；[Claude worktrees](https://code.claude.com/docs/en/worktrees) | 侧栏展示已有 worktree 路径/分支；没有状态检查与回收入口 | Git 删除/清理会改变仓库状态，留给 D 区工具与 worktree 生命周期 |
| 多服务器/SSH 会话入口 | ZCode、OpenCode、Claude Code | ZCode `packages/ui/src/i18n/locales/zh-CN.ts`；OpenCode `packages/app/src/settings/servers/servers.tsx`；[Claude Desktop](https://code.claude.com/docs/en/desktop) | 已可为会话选 SSH 远程工作目录；无侧栏服务器注册表/切换入口 | 保留现有远程目录支持；服务器连接管理归 C 区 |
| 跨设备远程控制 | ZCode、Codex、Claude Code | ZCode `packages/ui/src/i18n/locales/zh-CN.ts`；[Claude Remote Control](https://code.claude.com/docs/en/remote-control)；[Codex 官方更新日志](https://learn.chatgpt.com/docs/changelog) | 有设备管理入口，但没有从手机/网页接续当前会话的 A 区路由 | 远程连接、配对与会话路由归 C 区，本次不新增假入口 |
| 侧边栏切换快捷键 | ZCode、OpenCode | ZCode `packages/ui/src/settings/ShortcutSettingsSection.tsx`；OpenCode `packages/app/src/runtime/i18n/zh.ts` | Atlas 全局快捷键注册表已有 `toggleSidebar` | 已由应用键盘分发器执行；不重复增加一套绑定 |
| Codex 按项目批量归档会话 | Codex Desktop | [Codex 官方更新日志](https://learn.chatgpt.com/docs/changelog) | 有按会话批量归档；项目分组没有整组归档动作 | 在项目分组菜单新增两步确认的“归档项目会话”，保留项目中全部非归档会话的计数 |
| Codex Command Center 固定任务 | Codex TUI 0.162 | [rust-v0.162.0 release](https://github.com/openai/codex/releases/tag/rust-v0.162.0) | 有通用置顶区，没有 Codex 专属代理命令中心 | 通用 Pin 与 Pinned 分组已覆盖会话固定；Codex 命令中心是产品专属功能，不引入仿造面板 |
| Codex 会话 PR 状态徽章 | Codex Desktop | [Codex 官方更新日志](https://learn.chatgpt.com/docs/changelog) | 会话/运行摘要没有可靠 PR 状态字段 | 不从分支名推断 PR 状态；GitHub 状态接入归 C/D 区 |
| Codex 无项目直接开聊 | Codex Desktop | [Codex 官方更新日志](https://learn.chatgpt.com/docs/changelog) | 新建会话不要求项目；是否自动带默认工作区取决于用户设置 | 已有无项目会话路径；默认工作区设置由用户可控 |
| Codex Local↔Worktree Handoff | Codex Desktop 26.303+ | [Codex 官方更新日志](https://learn.chatgpt.com/docs/changelog) | 可更改后续工作目录；运行中的会话不能原地迁移到新 worktree | 本次提供目录更新入口；工作树创建、handoff 与上下文迁移留给 D 区 |
| Codex 会话弹出浮动窗 | Codex Desktop 26.212+ | [Codex 官方更新日志](https://learn.chatgpt.com/docs/changelog) | 无独立会话窗口 | Electron 多窗口协议属于 C 区，本次不触碰窗口主进程 |
| Codex Worktree 自动清理策略 | Codex Desktop | [Codex 官方更新日志](https://learn.chatgpt.com/docs/changelog) | 无自动保留数量与清理策略 | 配置策略归 C 区，实际 worktree 清理归 D 区 |
| Claude 临时 Side Chat Fork | Claude Desktop | [Claude Desktop](https://code.claude.com/docs/en/desktop) | 有独立 SideChat 面板，但不等同于与主会话共享上下文的临时 fork | 保留现有 SideChat；临时分支生命周期与共享上下文尚未实现 |
| Claude 跨会话查阅、消息与归档 | Claude Desktop Code tab | [Claude Desktop](https://code.claude.com/docs/en/desktop) | 用户能从侧栏切换、归档会话；Agent 无跨会话消息投递与统一 worker registry | 用户侧会话管理已覆盖；Agent 跨会话发现/通信归 C/D 区 |
| Claude 手机 Dispatch 派生开发会话 | Claude Desktop / Cowork | [Claude Desktop](https://code.claude.com/docs/en/desktop) | 没有手机到桌面开发任务的专属派发/徽标流程 | 设备配对、渠道路由和任务派发归 C/D 区 |
| Claude Projects 持续项目任务 | Claude Cloud Projects | [Claude Projects](https://code.claude.com/docs/en/claude-projects) | 有本地项目/会话关联与 Atlas goals；没有 Claude Cloud 的跨会话云任务系统 | 保留本地项目分组；云任务/共享记忆依赖服务端项目层，记录到跨区清单 |
| Claude Agent View 工作调度 | Claude CLI Agent View | [Agent View](https://code.claude.com/docs/en/agent-view) | Atlas 有运行列表/看板和当前会话状态；没有 Agent View 的跨项目 worker 派发调度 | 本区显示 Atlas 已有运行/等待/未读状态；跨项目调度与 worker 控制归 C/D 区 |
| OpenCode V2 Web 配对访问 | OpenCode V2 Web | [OpenCode V2 docs](https://opencode.ai/v2/docs/) | 可运行本地 Web UI；没有一次性 pair 流程/设备授权 A 区入口 | 服务暴露、认证与配对归 C 区 |
| OpenCode SSH 后台服务连接 | OpenCode V2 Desktop | OpenCode `packages/app/src/settings/servers/servers.tsx` | Atlas 可设置 SSH workspace；没有桌面端 SSH server registry | 远程目录路径沿用现有能力；服务器管理 UI 归 C 区 |
| Codex 移动端主机重连保留 | Codex Mobile iOS 2026-10-07 | [Codex 官方更新日志](https://learn.chatgpt.com/docs/changelog) | 有设备管理页；无 Codex Mobile 同款任务创建主机重连恢复流程 | 设备配对和断线续传归 C 区 |

## 结论与边界

本清单以仓库固定 HEAD 和官方文档快照为依据。官方闭源产品没有可给出的源码路径，已提供直接文档或 release 来源；“未找到”表示本次所查公开资料未确认，不表示绝对不存在。Atlas 不存在的数据字段或后台机制不通过静态假数据补齐。实际完工项、界面核查与验证证据见 tasks/results/FEATURE-F1-A.result.md。

## OpenCode A 区源码走查索引

以下路径均对应固定 HEAD 7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937。

| 走查面 | 文件与核实到的注册/行为 |
|---|---|
| 页面与路由 | packages/app/src/shell/routes/routes.tsx：/、/server/:serverKey/session/:id、/new-session、/settings；packages/app/src/home/route.tsx；packages/app/src/new-session/route.tsx。 |
| 首页项目/服务器侧栏 | packages/app/src/home/projects/view.tsx：项目选择、项目右键/更多菜单、项目折叠与服务器分组；packages/app/src/home/projects/controller.tsx：项目菜单行为；packages/app/src/servers/registry/row-menu.tsx：服务器 Edit、Hide/Show、Remove。 |
| 会话列表、搜索、索引 | packages/app/src/home/sessions/index.ts、records.ts、controller.tsx、search.ts、view.tsx。首页仅列顶层且未归档 session，按更新时间分组 Today / Yesterday / Older；搜索标题/项目名及看似 ID 的精确项；按目录筛选，跨项目显示时标出项目名；索引每目录保留 64 条并纳入近期窗口的额外记录。 |
| 新建会话和 workspace 菜单 | packages/app/src/new-session/route.tsx、screen.tsx、view.tsx、project/selector.tsx、workspace/selector.tsx、commands.tsx：选择项目/本地仓库/已有 worktree/新建隔离 worktree，搜索 worktree/branch，循环切换位置。 |
| 会话上下文菜单 | packages/app/src/home/sessions/view.tsx 与 controller.tsx：Rename、Export、Delete、删除确认；鼠标右键、ContextMenu 键、Shift+F10、触屏长按 500ms；删除同步通知打开的会话标签。packages/app/src/session/header/session-header-actions.tsx 只查到 Review panel 开关，未找到会话生命周期右键菜单。 |
| 项目菜单 | packages/app/src/home/projects/view.tsx 与 controller.tsx：New session、Import session、Edit project、Reveal in file manager、Clear notifications、Close project；项目行也支持拖放排序并调用 projects.move(worktree, index)。本次未找到会话行“移动到另一项目”。 |
| 归档边界 | packages/app/src/home/sessions/view.tsx、controller.tsx、index.ts：SHOW_HOME_SESSION_ARCHIVE=false；V2 client 暂无可用 archive API，所以首页不显示归档动作；归档记录在 session index 中排除。 |
| 桌面菜单 | packages/app/src/shell/commands/desktop-menu.ts：File 菜单 New Session/Open Project；View 菜单 Toggle Sidebar；Go 菜单上一/下一 Session 与 Project。相关菜单引用 sidebar.toggle、session.previous/next、project.previous/next；未在 app 的 TS/TSX 源码中找到对应 command.register 定义，作为“静态菜单引用、应用内注册位置未找到”记录。 |
| 命令面板和 session 命令注册表 | packages/app/src/shell/commands/command.tsx、palette.ts：命令 catalog/keybind 匹配/命令面板，默认 mod+k 或 mod+shift+p；packages/app/src/session/commands/use-session-commands.tsx：session.new (mod+shift+s)、session.undo、session.redo、session.compact、session.background (ctrl+b)、session.fork、session.export、session.copyID、project.copyID、file.open (mod+p)、file.close、context.addSelection；home/sessions/search.ts 注册 home.sessions.search.focus (mod+f)，首页命令面板由 home/sessions/controller.tsx 和 command-palette.tsx 注册；new-session/commands.tsx 注册 project.select (mod+shift+o)、session.location.cycle (mod+alt+l)、input.focus (ctrl+l)。 |
| 设置与快捷键设置 | packages/app/src/settings/pages.ts：Projects、Workspaces、Shortcuts 设置页；settings/keybinds/keybinds.tsx、settings/model.tsx：General/Session/Navigation 分组、搜索、录入、重置、用户 keybinds 覆盖；settings/workspaces/projects.tsx、workspaces/workspaces.tsx：项目/工作区清单、筛选及 worktree 清理；settings/appearance/appearance.tsx：session tabs Horizontal/Vertical 布局。未找到专门配置首页 session filter 或 archive 展示的设置。 |
| i18n | packages/app/src/runtime/i18n/en.ts、zh.ts、zht.ts：会话新建/导入、Home 搜索、Today/Yesterday/Older、sidebar 最近会话/清除通知、重命名/导出/归档/删除、快捷键和项目/工作区设置用语；packages/app/src/runtime/i18n/language.tsx：locale 装载 app 与 UI 字典。本轮没有逐条核对其他语言文件译文。 |
| 工具/命令注册表边界 | 本轮在 app 的 session 命令注册表中枚举了与 A 区有关的 UI command IDs 与 keybind；执行工具（文件、终端、模型工具等）不属会话侧栏 A 区。桌面菜单有数个引用但未找到 app 内 register 定义的 ID 已如实列出。未审计插件动态命令全集及原生菜单 IPC，不能把未检查的执行工具全集声明为已穷尽。 |

## 固定矩阵 A 功能的附录核查索引

以下修正采用 `D:\atlas-parity\四大Agent功能矩阵V5.md` 的附录 VI–IX 与其固定提交链接。证据类别按附录 VIII-G：源码实现（S）、UI 字符串/组件（U）、官方公开能力（O）、用户报告（R）、功能请求（F）、未核实（?）；U/R/F/? 不当作已实现能力。矩阵主表空白不作为“不支持”结论。

| 走查面 | 固定源码/官方文档与本区结论 |
|---|---|
| ZCode 会话行菜单与快捷操作 | `TaskListItemContextMenu.tsx`、`TaskActionMenuContent.tsx`、`workspace-grouped-tasks/task-context-menu-content.tsx`、`WorkspaceGroupedTasksSection.tsx`（`zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015c`）：置顶、重命名、归档、未读、分组/移组、移至顶部、split、复制 workspace/task/log paths/session ID、反馈；设置侧栏视图 group/workspace/timeline 和排序。菜单也可进入 provider/model trajectory；轨迹项继续见 B 区。 |
| ZCode Command Center / Quick Actions | 附录 VI、VIII-A2 与 `packages/ui/src` 命令中心、任务动作菜单、i18n/shortcut 源：Command Center 的 All/Command/Conversation/File scopes、最近 tasks/commands/conversations/files、清历史；Quick Actions 有任务搜索、新会话、文件搜索、主题、MCP、Terminal。Atlas Ctrl+K 已有会话搜索/命令入口；文件/MCP/Terminal/主题动作分别沿用原有页面，不重复做 A 实现。 |
| OpenCode V2 model-callable session tools | `packages/core/src/tool/plugin/opencode.ts`（`anomalyco/opencode@7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937`）：`session_rename(sessionID?, title)`、`session_move(sessionID?, directory)`、`worktree_create(name)`、`worktree_list()`、`worktree_remove(directory, force?)`、`subagent(agent, description, prompt, model?, sessionID?, background?)`。这些是模型工具，不等同于 sidebar/UI commands；目录迁移 UI 已在 A 实现，worktree/agent handlers 归 D。 |
| ZCode conditional tool registry | 矩阵附录 VIII-C2/H/C3 与固定 HEAD `apps/zcode-cli/packages/core/src/tool/`：`ReadSessionContext`；`SendMessage` 与 coordinator tools；`TaskOutput`/`TaskStop`；`Agent`/`Task` 受 `includeAgent` 控制；Cron 受 automation 开关控制；workflow-run tools 与 Node REPL 受能力开关控制。Android/iOS emulator MCP tools 和 plugins 有默认关闭及 SDK/Xcode 前置条件，不能写成默认会话工具。 |
| Codex 与 Claude gated registries | Codex `codex-rs/core/src/tools` 与 V1/V2 feature flags/policy：`spawn_agent`/`send_message`/`list_agents` 等按版本、策略和启用状态变化；Claude 官方 [Subagents](https://code.claude.com/docs/en/sub-agents)、[Cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging)、[Worktrees](https://code.claude.com/docs/en/worktrees)：`ListAgents`/`SendMessage`/`EnterWorktree`/`ExitWorktree` 等受版本、模式或权限控制。它们不等同于常驻侧栏入口，Atlas 对应执行工具由 D/C 区负责。 |
| OpenCode UI command/keybind registry | OpenCode 同一固定 HEAD：`session.new`、`session.undo/redo/compact/background/fork/export/copyID`、`project.copyID`、`file.open/close`、`context.addSelection`、`review.toggle`、`fileTree.toggle`、`input.focus`、`message.previous/next`、`mcp.toggle`、`permissions.autoaccept`；`home.sessions.search.focus` 为 `mod+f`，命令面板 `mod+k`/`mod+shift+p`，project/session location/settings bindings 见上方 source index。UI command 与模型 tool 分开记录。 |
| OpenCode V2 archive 与 in-session find 校正 | V2 `SHOW_HOME_SESSION_ARCHIVE=false`，home archive API/UI 不启用；矩阵主表/空白不据此推定。OpenCode TUI 的当前会话查找另见 [issue #15602](https://github.com/anomalyco/opencode/issues/15602)，这是需求记录，不是产品支持证据。 |

## Claude Code 官方来源索引

闭源产品按 2026-10-11 可见文档快照检查；文档页未显示发布日期，不推定具体发布时间。会话/侧栏页面为 [Desktop](https://code.claude.com/docs/en/desktop)、[Manage sessions](https://code.claude.com/docs/en/sessions)、[Agent view](https://code.claude.com/docs/en/agent-view)、[Commands](https://code.claude.com/docs/en/commands)、[Cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging)、[Desktop scheduled tasks](https://code.claude.com/docs/en/desktop-scheduled-tasks)、[Worktrees](https://code.claude.com/docs/en/worktrees)、[Checkpointing](https://code.claude.com/docs/en/checkpointing)、[Subagents](https://code.claude.com/docs/en/sub-agents)。更新按官方 changelog 与逐版本 release 核查：v2.1.207–v2.1.296 中影响会话行、搜索、恢复、分叉、待处理状态、快捷键和通知的条目列于上方功能对应行；完整官方变更记录及 release 链接见 Claude Code 的 [CHANGELOG.md](https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md)。

## Codex 官方文档与源码走查索引

闭源 ChatGPT/Codex Desktop 功能采用 2026-10-11 可见官方文档快照；官方页没有统一发布日期，以 changelog 版本条目的日期核对近三个月变更。

| 走查面 | 官方文档或固定源码 |
|---|---|
| Desktop 项目与会话 | [Projects and chats](https://learn.chatgpt.com/docs/projects)、[Codex chats archive/delete](https://help.openai.com/en/articles/20001333-how-to-archive-and-delete-codex-chats-in-the-chatgpt-app)、[Reviewing Work and Codex usage](https://help.openai.com/en/articles/20001478-reviewing-work-and-codex-usage-and-using-personal-analytics-in-chatgpt-desktop) |
| 命令与 CLI 恢复/会话选择 | [Commands](https://learn.chatgpt.com/docs/reference/commands)、[Developer commands](https://learn.chatgpt.com/docs/developer-commands)、[Codex CLI reference](https://learn.chatgpt.com/docs/cli/reference)、[Troubleshooting](https://learn.chatgpt.com/docs/reference/troubleshooting) |
| 官方更新日志 | [ChatGPT & Codex changelog](https://learn.chatgpt.com/docs/changelog)、[ChatGPT Release Notes](https://help.openai.com/en/articles/6825453-chatgpt-release-notes) |
| Session picker、归档与分页实现 | openai/codex HEAD 47bcb3a3f9e0904aed485389aaf410282b6b23fa：codex-rs/tui/src/resume_picker.rs、tui/src/resume_picker/archive.rs、tui/src/resume_picker/page_loading.rs、tui/src/resume_picker_transcript_preview.rs、tui/src/app/session_picker.rs。 |
| 快捷键/命令注册 | 同一 HEAD：tui/src/keymap.rs、config/src/tui_keymap.rs、tui/src/slash_command.rs、cli/src/main.rs；thread 数据协议在 app-server-protocol/src/protocol/v2/thread.rs。TUI picker 支持 Active/Archived、cwd/all、provider 筛选、搜索、分页、排序/预览，以及归档、恢复、resume/fork/rename/delete/export 等命令；Desktop 功能按闭源文档证据单独列出。 |

### Codex 近三个月会话/侧栏相关更新

| 日期 | 官方更新摘要 | 对照项 |
|---|---|---|
| 2026-07-13 | iOS 1.2026.188：任务创建/管理、任务链接与列表行交互 | 会话入口/深链 |
| 2026-07-20 | iOS 1.2026.195：按最近活动排序、host 不可用状态、草稿恢复 | 排序/状态/草稿 |
| 2026-07-23 | Desktop 26.715：一个项目支持多个目录和主目录 | 项目分组 |
| 2026-07-30 | Desktop 26.727：Activity 侧栏和 Cmd/Ctrl+Opt+U | 活动视图/快捷键 |
| 2026-08-18 | iOS 1.2026.223：新 Thread 项目 picker 的 host 同步、任务列表丢失/恢复修复 | 项目筛选/列表可靠性 |
| 2026-08-20 | Codex/ChatGPT：只读 thread 快照、Desktop/iOS 置顶聊天同步 | 会话预览/置顶 |
| 2026-08-26 | iOS 1.2026.230：标题和会话内容搜索、长 thread 延迟加载、排序和 pin 向 Desktop 靠齐 | 搜索/排序/置顶 |
| 2026-09-01 | iOS 1.2026.237：Priority view 汇总 running/unread/awaiting response，复制 thread ID，列表可靠性修复 | 状态视图/复制 ID |
| 2026-09-11 | Desktop 26.908：quick chat 声音跟踪 thread 进度并可点入完整会话；conversation Sources 可打开文件 | 状态通知/会话详情 |
| 2026-09-23 | iOS 1.2026.258：iPad task list 与 task split view | 并排打开 |
| 2026-10-02 | iOS 1.2026.267：返回时更快刷新、保留标题、修复任务消失 | 列表状态/稳定性 |
| 2026-10-07 | iOS 1.2026.272：task deep links、连接 host 后空列表修复 | 深链/连接状态 |

版本级来源可在上方官方 changelog 和 release notes 中定位。当前 Desktop 快捷键资料、TUI keymap 是不同界面，清单不把 TUI 默认键位误报为 Desktop 默认键位；官方未指定默认值时标为“未配置/文档未指定”。
