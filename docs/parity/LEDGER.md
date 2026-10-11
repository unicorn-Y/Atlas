# Atlas 剩余工作总账｜F1 A–D + V5 去重版

> 编制依据：用户提供的 `F1-A.md`、`F1-B.md`、`F1-C.md`、`F1-D.md`、`F1-unassigned.md`、`四大Agent功能矩阵V5.md`，资料日期均为 2026-10-11。本账未读取 Atlas 实际仓库，因此状态是**附件所述状态**，不是独立代码验收。

## 一、统计与裁决口径

状态：**已做** = 材料声称本次功能闭环；**原有** = 既有且无需本轮修改；**部分** = 存在基础实现但材料明确留下缺口；**没做** = 材料描述缺少实际实现；**待核实** = 只有线索、需确认后才能施工。将摘要行、同义词、跨区转交和同一组工具的参数拆项消重；对功能边界不同者保留独立记录。

**统计单位是去重后的 Atlas 可交付能力，不是 V5 中源码 API/控件/i18n 个数。** D 区保留 F1-D 的 129 条模型可调用类别；V5 VIII-K 的 43 个 Android/iOS 工具已经计入 D 区，不另叠加。IX R101–R112 是用户报告/需求，不当作竞品已交付功能。

| 区域 | 已做 | 部分 | 没做 | 原有 | 待核实 | 合计 | 需要处理 |
|---|---:|---:|---:|---:|---:|---:|---:|
| A 会话与侧栏 | 18 | 9 | 1 | 8 | 0 | **36** | **10** |
| B 对话界面 | 35 | 46 | 34 | 21 | 3 | **139** | **83** |
| C 设置与扩展 | 30 | 35 | 33 | 3 | 0 | **101** | **68** |
| D 工具 | 67 | 44 | 16 | 2 | 0 | **129** | **60** |
| **合计** | **150** | **134** | **84** | **34** | **3** | **405** | **221** |

### 冲突与去重说明

- `F1-D.md` 明写“实施前基线 129 项，已做 67 / 部分 44 / 没做 16 / 原有 2”，原样保留；不凭 V5 的存在推测 D 工具已完工。
- A 中深链、多窗口、自动归档、Bot/Channels、Worktree、跨会话 worker 等**跨区转到 C/B/D**，不会既算 A 未做又算接收区未做。C 材料声称 `atlas://` 深链已接通，故不重复派“深链从零实现”。
- B 的重复命令/消息复制/语音/工具卡与 C 的多账号、代理、模型 effort、远端同步、深链、OS 快捷键等只记一次；界面显示与 D 的模型 callable **不视为重复功能**。
- V5 主体 A–E 与附录 IX 官方功能纳入独立缺口。仅凭 i18n/U 线索、社区 issue/R 或 feature request/F，不能升级为竞品已有功能；部分项目设“待核实”而非强行施工。
- 来源列复用上传材料中的源码路径或官方文档，若附件只写某一组件目录或泛化引用，则不补造更精确路径。修改 Atlas 文件同理。

### 派工解释

P0：每天编码、聊天、会话管理直接高频；P1：经常用；P2：低频或云端/企业/移动平台条件能力。S：小组件/单接口；M：前后端协调；L：新子系统。S → Hermes，M/L → Codex。**难度和优先级是依据功能语义的规划判断，不是材料中已有的验收事实。**

## 二、剩余条目（仅部分 / 没做 / 待核实）

### A 区 · 会话与侧栏

| 编号 | 区 | 功能（含状态） | 缺什么（一句话） | 抄谁（仓库文件或文档） | 优先级 | 难度 | 建议执行者 |
|---|---|---|---|---|---|---|---|
| A002 | A | 新建会话及空白草稿生命周期〔部分〕 | 首条消息前仍直接持久化会话，缺临时空白草稿的生命周期。 | ZCode 新会话命令与 UI 注册；OpenCode app session commands；Codex Desktop 文档；Claude Desktop 文档 | P0 | M | Codex |
| A007 | A | 按状态筛选（运行、等待、完成、错误、未读）〔部分〕 | 缺等待/完成/错误等统一筛选所需的持久化状态字段；目前只具备运行与未读状态。 | ZCode task list status 与 locale；Codex 活动/优先级视图文档；Claude Desktop、Agent view 及 v2.1.207、v2.1.257、v2.1.287 changelog | P0 | M | Codex |
| A008 | A | 按项目、环境、工作树筛选〔部分〕 | 已有项目/工作区筛选，但缺完整环境、工作树状态字段与对应筛选。 | ZCode task scope/project 列表；OpenCode Projects 与 Servers 页面；Codex session picker cwd/all 和官方 Projects 文档；Claude Desktop、Manage sessions | P0 | M | Codex |
| A011 | A | 拖动会话排序或移入分组〔部分〕 | 组内排序已增加，可跨组拖入的范围仍有限。 | ZCode draggable task/group/project UI；OpenCode project reorder；Claude Agent view reorder | P0 | M | Codex |
| A013 | A | 项目创建、重命名、导入/关闭、最近关闭〔部分〕 | 项目导航/归属已接，项目导入、关闭与最近关闭等动作未完成完整 UI/Git 工作流。 | OpenCode Projects 页面与项目命令；Codex Desktop Projects 文档；Claude Desktop | P1 | M | Codex |
| A018 | A | 右键菜单、键盘菜单键与触屏长按〔部分〕 | 右键/键盘菜单已补，触屏长按的 Electron 交互仍待核实。 | ZCode task context menu；OpenCode session context menu 支持 right-click/Shift+F10/long-press | P0 | S | Hermes |
| A025 | A | 运行、等待输入、未读提示〔部分〕 | 运行与未读可展示，缺持久化 waiting-input 状态来源。 | ZCode task status badges；Codex Activity/Priority 文档；Claude Agent view、Desktop、v2.1.207 与 v2.1.257 changelog | P0 | M | Codex |
| A027 | A | 运行中/等待输入/完成通知与活动视图〔部分〕 | 侧栏可显示现有状态，缺跨会话 Activity 归一化及原生通知投递联动。 | ZCode row status；Codex Activity view 文档；Claude Desktop notifications、Agent view、v2.1.210/v2.1.295/v2.1.296 changelog | P0 | M | Codex |
| A029 | A | 快捷键打开搜索/选择器、切换会话组〔部分〕 | 已有全局绑定系统，缺侧栏搜索/组导航独立的快捷键动作。 | ZCode shortcut registry/keybindings setting；OpenCode app keybind registry/settings；Codex TUI keymap 与官方 shortcuts；Claude commands 与 v2.1.288 | P1 | M | Codex |
| A036 | A | OpenCode 项目颜色/图标自定义〔没做〕 | 缺项目颜色、图标编辑和侧栏呈现 | OpenCode `packages/app/src/settings/search-catalog.ts`（V5 E 项；仅用于功能发现） | P1 | S | Hermes |

本区 10 项待处理；V5 原矩阵或附录独立补项可在来源索引中检索。

### B 区 · 对话界面

| 编号 | 区 | 功能（含状态） | 缺什么（一句话） | 抄谁（仓库文件或文档） | 优先级 | 难度 | 建议执行者 |
|---|---|---|---|---|---|---|---|
| B008 | B | 回复/产品反馈动作〔没做〕 | 缺实际反馈接收 API，不能将反馈按钮接到虚构服务。 | ZCode `packages/ui/src/v4/ConversationHookDetailsAction.tsx`；Codex TUI fixed source `codex-rs/tui/src/slash_command.rs`（`6c0c6759d061`）；Codex [Desktop slash commands](https://learn.chatgpt.com/docs/reference/slash-commands) | P1 | M | Codex |
| B010 | B | 选中文本加入任务或发起 side chat〔部分〕 | 没有实现桌面级选区浮层 | ZCode `packages/ui/src/v4/{ConversationSelectionTooltip.tsx,SelectionActionMenu.tsx}`；Codex [side chat](https://learn.chatgpt.com/docs/app)；Claude [desktop](https://code.claude.com/docs/en/desktop) | P0 | M | Codex |
| B013 | B | Markdown 文件链接、行/列跳转和安全 URL〔部分〕 | 文件链接已可按行定位，尚未支持按列定位。 | ZCode `packages/ui/src/lib/markdownFileLink.ts`、`PreviewPane.tsx`；OpenCode session markdown；Codex [app](https://learn.chatgpt.com/docs/app) | P0 | M | Codex |
| B014 | B | 文件链接右键复制路径/打开预览〔部分〕 | 文件树已有右键操作，但消息正文内文件链接缺同等级右键菜单。 | ZCode `packages/ui/src/lib/markdownFileLink.ts`、`PreviewPane.tsx`；OpenCode `packages/session-ui`（无消息级 context menu）；Codex [app](https://learn.chatgpt.com/docs/app) | P0 | M | Codex |
| B025 | B | Approval 权限范围、一次/始终允许、拒绝理由〔部分〕 | 已有后端决策，权限范围、拒绝理由和审批键盘交互仍需完整呈现。 | ZCode `packages/ui/src/PermissionDialog.tsx`、`WorkflowPermissionBlock.tsx`；Codex [approvals](https://learn.chatgpt.com/docs/permissions)；Claude [permission modes](https://code.claude.com/docs/en/permission-modes) | P0 | M | Codex |
| B027 | B | Composer 模型、模式、推理档位与上下文用量〔部分〕 | 模式/推理档位只能接 Atlas 真实模型 API，尚未覆盖上游所有切换项。 | ZCode `packages/ui/src/v4/composer/V4ComposerToolbar.tsx`、`ModelConfigSelect.tsx`、`ChatModeSwitchControl.tsx`、`ThoughtLevelCycleControl.tsx`；OpenCode composer; Codex [models](https://learn.chatgpt.com/docs/model-selection)；Claude [model config](https://code.claude.com/docs/en/model-config) | P0 | M | Codex |
| B028 | B | Composer 附件：选择、粘贴、拖放、进度、失败重试、移除〔部分〕 | 附件基础交互已具备，缺上传进度和失败重试的完整 API/界面状态。 | ZCode `packages/ui/src/v4/composer/{useComposerAttachments.ts,attachmentUpload.ts,conversationDropTarget.ts}`；OpenCode session composer；Codex [image inputs](https://learn.chatgpt.com/docs/app)；Claude [desktop](https://code.claude.com/docs/en/desktop) | P0 | M | Codex |
| B030 | B | `@` 文件与会话引用、文件树拖入引用〔部分〕 | @ 文件/mention 已按会话隔离，但 $skill 结构化引用未完成（另见 B031）。 | ZCode `packages/ui/src/mentions/providers/{fileMentionProvider.ts,sessionsMentionProvider.ts}`；OpenCode composer suggestions；Codex [prompting](https://learn.chatgpt.com/docs/prompting)；Claude [interactive mode](https://code.claude.com/docs/en/interactive-mode) | P0 | M | Codex |
| B031 | B | `$skill` 消息级结构化引用（区别于全局 active skill 开关）〔没做〕 | 缺消息级 $skill 结构化引用、提交协议传递及与全局 active skill 的区分。 | ZCode 固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/mentions/providers/skillsMentionProvider.ts`、`packages/ui/src/mentions/mentionMarkdown.ts`；Codex [skills](https://learn.chatgpt.com/docs/build-skills)；Claude [skills](https://code.claude.com/docs/en/skills) | P0 | L | Codex |
| B032 | B | Slash command registry、模糊搜索、来源/说明〔部分〕 | 已接入一批 slash 命令，统一来源/说明、模糊搜索与注册契约仍需核查。 | ZCode packages/ui/src/lib/slashCommands.ts、hooks/useSlashCommands.ts、CLI command-center；OpenCode packages/app/src/components/dialog-select-*；Codex commands 文档；Claude commands 文档 | P0 | L | Codex |
| B034 | B | Codex `/fast` / fast mode〔没做〕 | 无 Atlas provider 能力可执行 fast mode | [model selection](https://learn.chatgpt.com/docs/model-selection)，2026-09-22/09-29/10-08 changelog | P1 | M | Codex |
| B036 | B | Codex `/model` / `/reasoning` 模型与推理选项〔部分〕 | 已有 /model，推理档位展示依赖 Atlas 模型 API 是否暴露对应强度。 | [model selection](https://learn.chatgpt.com/docs/model-selection)；ZCode `ModelConfigSelect.tsx`、`ThoughtLevelCycleControl.tsx`；Claude [model config](https://code.claude.com/docs/en/model-config) | P1 | M | Codex |
| B038 | B | Codex `/worktree` 当前会话工作树入口〔部分〕 | 已有进入 Worktree 面板命令，跨工作树迁移执行语义不在本入口内。 | [git worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)；ZCode workspace shell；Atlas Worktree 面板/API | P1 | M | Codex |
| B042 | B | Codex `/local`、`/cloud`、`/cloud-environment` 执行位置选择〔部分〕 | 本地/worktree 模式已有，缺真实云执行环境 capability 与会话切换。 | [environments/modes](https://learn.chatgpt.com/docs/environments/modes)；[cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments) | P2 | L | Codex |
| B043 | B | Enter 发送偏好与 Queue/Steer 默认行为设置〔部分〕 | 发送/排队状态已展示，缺 Queue/Steer 默认行为的完整持久化偏好。 | Codex [reference settings](https://learn.chatgpt.com/docs/reference/settings)、[long-running work](https://learn.chatgpt.com/docs/long-running-work)；ZCode `ConversationQueuePanel.tsx`；Claude [desktop](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| B046 | B | Codex artifacts、Sources 打开/下载文件〔部分〕 | 可预览本地 artifacts，外部 Sources 下载链路尚不完整。 | [artifacts viewer](https://learn.chatgpt.com/docs/artifacts-viewer)，[changelog](https://learn.chatgpt.com/docs/changelog) 2026-09-11 | P1 | M | Codex |
| B047 | B | Codex desktop shortcut：command center/settings/new/fork/chat/search〔部分〕 | 对话搜索快捷键已实现，其余全局命令与快捷键需 A/C 区接线核对。 | [reference commands](https://learn.chatgpt.com/docs/reference/commands) | P1 | M | Codex |
| B048 | B | `!` shell composer 模式/命令〔部分〕 | 缺明确的 ! shell 输入前缀模式和发送前执行确认。 | OpenCode session composer `!` mode；Claude [interactive mode](https://code.claude.com/docs/en/interactive-mode) | P0 | M | Codex |
| B049 | B | Add menu：附件、Goal、Workflow 等快捷插入〔部分〕 | 附件与引用可快速插入，Goal/Workflow 等菜单项须逐项对齐真实可执行入口。 | ZCode `packages/ui/src/prompt-editor/ChatPromptActionMenu.tsx`；OpenCode composer attachments | P1 | S | Hermes |
| B051 | B | 队列项编辑、拖动、立即执行、删除、恢复〔部分〕 | 已有队列 API 可支持部分编辑/删除，缺完整拖动、立即执行、恢复等操作契约。 | ZCode `packages/ui/src/v4/ConversationQueuePanel.tsx`；OpenCode session queue；Codex [app](https://learn.chatgpt.com/docs/app) | P0 | M | Codex |
| B053 | B | 工作区文件树、Git 状态、右键复制路径/加入上下文〔部分〕 | 文件树搜索/右键已有，Git 状态与加入上下文需按真实数据及 API 补齐。 | ZCode `packages/ui/src/WorkspaceFileTree.tsx`、`workspace-file-tree/WorkspaceFileTreeRowView.tsx`；Codex [app](https://learn.chatgpt.com/docs/app) | P0 | M | Codex |
| B055 | B | Diff 的逐文件查看与行级 review〔部分〕 | hunk 接受/拒绝已接入，更完整的逐文件编辑/IDE 选择与评注能力未完成。 | ZCode `packages/ui/src/components/ui/diff-viewer.tsx`；Codex [code review](https://learn.chatgpt.com/docs/code-review)；Claude [desktop](https://code.claude.com/docs/en/desktop) | P0 | M | Codex |
| B060 | B | 浏览器控制、导航、响应式 viewport 与权限〔部分〕 | 浏览器预览和批注已接入，网站权限控制及自动预览验证未实现。 | ZCode `packages/ui/src/browser-use/{UnifiedBrowserView.tsx,BrowserViewportToolbar.tsx,EmbeddedBrowserPermissionPrompts.tsx}`；Codex [browser](https://learn.chatgpt.com/docs/app)；Claude [desktop](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| B062 | B | Git Review/PR、检查状态和差异定位〔部分〕 | 不含本地评论编辑/推送选择 | ZCode `packages/ui/src/{GitPane.tsx,GitPaneChangeCard.tsx}`；Codex [code review](https://learn.chatgpt.com/docs/code-review) | P0 | M | Codex |
| B065 | B | Dashboard pin 工具输出/图表/报告〔部分〕 | 没有图表/报告生成器 | OpenClaw `docs/web/dashboards.md`、`docs/web/dashboard-architecture.md`（F1-B 原表“同上”） | P1 | M | Codex |
| B066 | B | Dashboard 受限生成内容与外部 MCP widget 权限〔没做〕 | Dashboard 当前只支持受限文本/链接 widget，缺安全的外部 MCP widget host。 | OpenClaw `docs/web/dashboards.md`；ZCode `packages/ui/src/gen-ui/CONTRACT.md`；Goose [MCP UI](https://github.com/block/goose/blob/main/documentation/docs/guides/interactive-chat/mcp-ui.md) | P1 | M | Codex |
| B069 | B | 右键菜单：消息、代码、文件链接〔部分〕 | 未实现完整消息右键菜单 | ZCode `packages/ui/src/v4/ConversationSelectionTooltip.tsx`、`WorkspaceFileTreeRowView.tsx`；OpenCode app/session 仅项目/会话行 context menu；Codex [app](https://learn.chatgpt.com/docs/app) | P0 | M | Codex |
| B070 | B | 输入框插件/扩展资源上下文引用（V5 B93）〔没做〕 | 缺输入框插件/扩展资源上下文的结构化协议和可调用入口。 | 固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/mentions/components/PluginMentionOptionContent.tsx`、`packages/ui/src/mentions/mentionMarkdown.ts` | P0 | M | Codex |
| B071 | B | 办公/编程双 UI 模式（V5 B99）〔没做〕 | 缺真实办公/编程模式状态及两套 UI 的切换契约。 | 固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/onboarding/OnboardingModeSelector.tsx` | P1 | M | Codex |
| B072 | B | 按场景主动推荐任务（V5 B100）〔待核实〕 | 原材料仅有界面/文案线索，缺可执行能力的复核证据 | 固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/i18n/locales/zh-CN.ts`（仅 UI 文案证据） | P2 | M | Codex |
| B073 | B | 模型调用轨迹按调用来源/类型展开（V5 B103；VIII-M）〔没做〕 | 缺少逐次调用持久化与来源/类型展开 | 固定 SHA：packages/ui/src/ModelTrajectoryExpansionMenu.tsx、packages/ui/src/i18n/locales/zh-CN.ts（VIII-M，调用来源和筛选文案） | P1 | M | Codex |
| B075 | B | OpenCode V2 后台会话状态及重新连接入口（VIII-B2；IX R101）〔没做〕 | 缺 OpenCode V2 等效的会话级后台挂起、状态与重连接口。 | 固定 SHA：packages/app/src/session/commands/use-session-commands.tsx、packages/app/src/session/screen.tsx；IX R101 是特定版本传输故障报告，不是能力证据 | P0 | M | Codex |
| B076 | B | OpenCode V2 Review 会话概览和文件预览（V5 B115；V2）〔部分〕 | 已有 review 面板，缺 OpenCode V2 独立 Review 会话概览布局。 | 固定 SHA：`packages/session-ui/src/v2/components/session-review-v2.tsx`、`session-review-file-preview-v2.tsx`；文件模型 `packages/app/src/workspaces/files/model.tsx` | P0 | M | Codex |
| B079 | B | Codex `/ide` 当前 IDE 选区/打开文件上下文（用户追加）〔部分〕 | /ide 仅能打开工作目录，缺当前 IDE 选区、打开文件上下文回传。 | 固定版本源码 `https://github.com/openai/codex/blob/6c0c6759d061/codex-rs/tui/src/slash_command.rs`（VIII-E，`/ide`）；Codex [IDE integrations](https://learn.chatgpt.com/docs/ide/commands) | P1 | M | Codex |
| B082 | B | 从消息文件引用/差异文件在外部编辑器或 IDE 打开（用户追加；V5 B163）〔部分〕 | 可调用系统默认程序打开文件，缺任意 IDE 选择及当前 IDE 上下文同步。 | ZCode 固定 SHA：`packages/ui/src/lib/markdownFileLink.ts`、`WorkspaceFileTreeRowView.tsx`；Claude [Desktop file context menu](https://code.claude.com/docs/en/desktop)；Codex [Desktop app](https://learn.chatgpt.com/docs/app) | P1 | M | Codex |
| B084 | B | 屏幕阅读模式/辅助阅读显示（用户追加；VI R17）〔部分〕 | Composer 已支持读屏导航，其他对话面板的完整无障碍路径未覆盖。 | Claude [interactive mode](https://code.claude.com/docs/en/interactive-mode)、[releases v2.1.208](https://github.com/anthropics/claude-code/releases/tag/v2.1.208)；ZCode 固定 SHA 的 `packages/ui/src/i18n/locales/zh-CN.ts` 只证明有无障碍文案时单独标 U | P1 | M | Codex |
| B085 | B | 对话区全键盘可达（用户追加；VI R17）〔部分〕 | 新控件可键盘操作，但全对话区 Tab 顺序和焦点路径尚未完整核查。 | ZCode 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts`（快捷键文案）及 `packages/shared/src/shortcutCommands.ts`；OpenCode 固定 SHA：`packages/app/src/runtime/i18n/en.ts`（Shortcuts 设置）和 `packages/ui/src/hooks/keyboard.ts`；Codex TUI 固定源 `codex-rs/tui/src/keymap.rs`（`6c0c6759d061`）；Claude [desktop](https://code.claude.com/docs/en/desktop)、[interactive mode](https://code.claude.com/docs/en/interactive-mode) | P0 | M | Codex |
| B088 | B | Codex Floating Composer 浮动输入框（V5 B174）〔没做〕 | 缺真正跨窗口的浮动输入框与系统级唤起快捷键。 | Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（2026-09-11） | P1 | S | Hermes |
| B089 | B | Codex 选中文字 Ask Codex 覆层（V5 B175）〔没做〕 | 缺桌面任意应用文本选区上的 Ask Codex 全局浮层。 | Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.410） | P1 | S | Hermes |
| B090 | B | Codex 侧栏文件标签拖放排序（V5 B177）〔没做〕 | 缺侧面板文件标签拖动重排。 | Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.409） | P1 | S | Hermes |
| B091 | B | Codex 会话 PR 操作时间线、评论及推送选择（V5 B178）〔部分〕 | PR checks 已可查看，缺本地评论编辑、推送选择及完整 PR 时间线。 | Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.409） | P1 | M | Codex |
| B092 | B | Codex 图片灯箱缩放/下载（V5 B182）〔部分〕 | 图片灯箱缩放已有，下载动作及完整键盘关闭行为未确认。 | Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.429） | P1 | S | Hermes |
| B093 | B | Codex 合并审查提示与快捷导航（V5 B180；VI R12）〔部分〕 | 缺对合并审查的逐条导航/提示闭环；需核验评论框焦点和中文输入法。 | Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)；VI R12 [issue #48836](https://github.com/openai/codex/issues/48836) 是特定版本焦点/IME bug，不是功能缺失证据 | P1 | M | Codex |
| B094 | B | 侧面板多标签、拖动和最近关闭恢复（V5 B117–118）〔部分〕 | Files 已有多 tab 与最近关闭恢复，缺跨面板拖动排序和自由布局。 | ZCode 固定 SHA：`packages/ui/src/app-shell/SidePaneTabOverview.tsx`、`lib/workspaceSidePane.ts`；Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.409）；Claude [desktop](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| B095 | B | Claude Desktop 面板拖放自由布局（V5 B150）〔没做〕 | 缺多个 Inspector 面板自由拖放布局。 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | L | Codex |
| B096 | B | Claude Desktop 面板独立弹出与重新停靠（V5 B151）〔没做〕 | 缺面板独立窗口弹出与重新停靠的 Electron 生命周期。 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | L | Codex |
| B097 | B | Claude Desktop 输入中途纠偏（V5 B153）〔部分〕 | 有运行态 queue/steer，但需要明确中途输入在各 run 状态的路由行为。 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | S | Hermes |
| B098 | B | Claude Desktop Browser 开发服务器列表与批量停止（V5 B155）〔没做〕 | 缺 Browser 内开发服务的列表与批量停止及其进程状态联动。 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| B099 | B | Claude Desktop Browser 自动预览验证（V5 B156）〔没做〕 | 当前浏览器只供手工预览，缺操作后自动验证服务。 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| B100 | B | Claude Desktop Browser Cookie 持久化/清除站点数据（V5 B157）〔没做〕 | 缺站点 Cookie/存储的持久化与清除状态展示。 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| B101 | B | Claude Desktop Browser 外站逐域允许一次/总是允许/拒绝（V5 B158）〔没做〕 | 缺浏览器外站逐域一次/始终允许/拒绝的真实审批 UI。 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| B102 | B | Claude Desktop 多行 Diff 评论一次提交（V5 B159；VI R12 对照）〔没做〕 | 缺 Diff 多行评论的集中提交与焦点/输入法交互。 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P0 | S | Hermes |
| B103 | B | Claude Desktop Code Review 逐条 Fix/Dismiss/Apply fixes（V5 B160）〔部分〕 | 已有 hunk 接受/拒绝，缺 Review finding 的 Fix/Dismiss/Apply fixes 全语义。 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| B104 | B | Claude Desktop 内置文件编辑器磁盘冲突提示（V5 B162）〔没做〕 | 缺内置文件编辑器真实保存与外部磁盘修改冲突检测。 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P0 | M | Codex |
| B107 | B | 文件树 Git 状态标记（V5 B120）〔待核实〕 | 缺文件树 Git 状态数据是否真实映射的核验。 | 固定 SHA：`packages/ui/src/workspace-file-tree/gitStatus.ts`、`WorkspaceFileTree.tsx` | P0 | M | Codex |
| B108 | B | 文件树按名称搜索和刷新（V5 B121）〔部分〕 | 文件名搜索已实现，独立刷新入口未确认。 | ZCode 固定 SHA：`packages/ui/src/workspace-file-tree/searchRows.ts`；OpenCode 固定 SHA：`packages/app/src/workspaces/files/model.tsx`、`packages/app/src/session/screen.tsx` | P0 | M | Codex |
| B111 | B | 浏览器网站权限卡片（V5 B127）〔没做〕 | 缺 Atlas 自有网站权限卡；Chromium 原生弹窗不等于 Atlas 授权面板。 | ZCode 固定 SHA：`packages/ui/src/browser-use/EmbeddedBrowserPermissionPrompts.tsx`；Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| B112 | B | 浏览器设备权限结果卡（摄像头/麦克风/屏幕/定位等；VIII-M）〔待核实〕 | 缺设备权限结果卡及各设备来源真实授权状态的逐设备核验。 | ZCode 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L965-L1000`（可见设备权限类别，组件/API 需逐项核验）；Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | L | Codex |
| B113 | B | Git 操作菜单、提交/推送动作与错误详情（V5 B130）〔部分〕 | Git 菜单只消费已授权操作，提交/推送执行与错误状态仍需真实接线。 | 固定 SHA：`packages/ui/src/GitActionMenu.tsx`；附录 VIII-A2 对应菜单项 | P0 | M | Codex |
| B114 | B | Git 分支切换与新建入口（V5 B131）〔部分〕 | 已有部分分支操作，缺新建/切换后会话工作区和当前分支的完整反馈。 | 固定 SHA：`packages/ui/src/GitActionMenu.tsx` | P0 | M | Codex |
| B115 | B | Git 提交历史拓扑图（V5 B132、VIII-M）〔没做〕 | 缺真实 Git 历史拓扑视图；矩阵只提供部分 i18n 线索。 | 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L1417-L1443`（UI 文案线索） | P1 | M | Codex |
| B116 | B | 会话/模型网络日志和逐轮 Token 调试（V5 B147；VIII-M）〔没做〕 | 缺会话逐轮模型 HTTP/I/O、网络日志和 token 的真实采集数据。 | ZCode 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L4763-L4798`（诊断 UI 文案，需配组件）；Codex TUI 固定源 `codex-rs/tui/src/slash_command.rs`（`6c0c6759d061`） | P1 | M | Codex |
| B117 | B | Markdown/SVG 源码与预览切换、换行/字体（V5 B136、VIII-M）〔部分〕 | 已有源码/预览切换，SVG 专用字体与换行控件未全部核实。 | 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L1493-L1530` | P1 | M | Codex |
| B119 | B | GenUI 生成交互卡片及微调（V5 B139）〔没做〕 | 缺受控 GenUI 协议、组件宿主及模型生成代码的执行隔离。 | 固定 SHA：`packages/ui/src/gen-ui/components/GenUiMessageResponse.tsx`、`packages/ui/src/gen-ui/CONTRACT.md` | P1 | L | Codex |
| B120 | B | 插件自定义 UI 侧栏（V5 B140）〔没做〕 | 缺插件自定义 UI 的宿主协议、授权和受控侧栏承载。 | ZCode 固定 SHA：`packages/ui/src/plugin-ui/PluginUiSidePane.tsx`；Claude [MCP](https://code.claude.com/docs/en/mcp) | P1 | L | Codex |
| B121 | B | 子代理独立侧栏与活动/历史目录（V5 B141–142）〔部分〕 | 当前只有 task 卡，缺跨会话子代理目录、活动和历史 API。 | ZCode 固定 SHA：`packages/ui/src/app-shell/{SubagentSessionSidePane.tsx,SubagentDirectorySidePane.tsx}`；Codex [long-running tasks](https://learn.chatgpt.com/docs/long-running-work)；Claude [sub-agents](https://code.claude.com/docs/en/sub-agents)、[agent teams](https://code.claude.com/docs/en/agent-teams)、[Desktop feature comparison](https://code.claude.com/docs/en/desktop) | P1 | L | Codex |
| B122 | B | 动态并行工作流执行图（V5 B143）〔部分〕 | 有真实 run 事件时间线，缺并行工作流拓扑图与动态更新。 | ZCode 固定 SHA：`packages/ui/src/app-shell/WorkflowRunDirectorySidePane.tsx`；Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | L | Codex |
| B123 | B | Codex Desktop Auto Review 审查结果/权限 UI〔部分〕 | /auto-review 仅映射 /review，缺专属自动审查策略、授权和结果 UI。 | https://learn.chatgpt.com/docs/sandboxing/auto-review | P1 | M | Codex |
| B124 | B | Thinking 内容与工作状态（V5 B102；VI R03；IX R102）〔部分〕 | 运行状态已显示，缺模型实际 Thinking 内容的分类和可展开转录。 | OpenCode 固定 SHA：packages/session-ui/src/message/current-message.tsx、message-content.tsx；Codex TUI 固定源 codex-rs/tui/src/keymap.rs（6c0c6759d061）；Claude Desktop view modes 文档 | P1 | M | Codex |
| B125 | B | Claude Desktop transcript Normal/Thinking/Verbose（V5 B149）〔部分〕 | 已有呈现模式，未对齐 Claude Normal/Thinking/Verbose 三档语义。 | https://code.claude.com/docs/en/desktop#switch-view-modes；1.46388.1 之前版本另有 Summary | P1 | S | Hermes |
| B126 | B | Claude Desktop 会话快捷键帮助层（V5 B152）〔部分〕 | 快捷键帮助仅覆盖 Composer，缺完整会话/全局键位的帮助弹层。 | https://code.claude.com/docs/en/desktop#keyboard-shortcuts | P1 | M | Codex |
| B127 | B | OpenCode V2 背景 Bash 输出侧栏（V5 B123）〔没做〕 | 缺后台 Bash 输出专用侧栏及进程状态/停止管理。 | 固定 SHA：packages/app/src/session/screen.tsx、screen-layout.ts、runtime/extension/panels.tsx | P0 | M | Codex |
| B129 | B | PPTX 页码、缩略图、缩放、元素选择和导出（V5 B135、VIII-M）〔部分〕 | 仅为 i18n 字段 | 固定 SHA aac4755666d09fdcd70272fcf063c077a639015f：packages/ui/src/i18n/locales/zh-CN.ts#L1469-L1493（UI 字段线索，TSX 操作须另证） | P1 | M | Codex |
| B130 | B | 同一 session 内树状分支与摘要切换〔没做〕 | 缺节点式会话持久化、分支摘要和返回旧节点继续编辑；Atlas fork 使用新会话 ID | Pi `packages/coding-agent/docs/sessions.md` | P1 | M | Codex |
| B131 | B | Claude 临时 Side Chat 共享上下文 Fork〔部分〕 | 已有 SideChat，缺主会话上下文共享及临时分支生命周期 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| B132 | B | Claude 后续 Prompt 推荐〔没做〕 | 缺会话结束后的下一步 Prompt 建议交互 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| B133 | B | Claude 后台任务查看与停止〔没做〕 | 缺与当前会话关联的后台任务状态/停止专用面板 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| B134 | B | Codex 模型轨迹内搜索〔没做〕 | 缺按调用/轮次检索模型轨迹的能力；独立于普通对话搜索 | ZCode `packages/ui/src/i18n/locales/zh-CN.ts`（V5 B133，文案线索，具体 TSX 待核） | P1 | M | Codex |
| B135 | B | 系统资源监视展示〔没做〕 | 缺会话内本机 CPU/内存/进程等运行资源视图 | ZCode `packages/ui/src/i18n/locales/zh-CN.ts`（V5 E 资源监视，文案线索） | P2 | M | Codex |
| B136 | B | OpenCode 触屏适配〔没做〕 | 缺触屏设备的专门长按/拖放/命中区设计 | [O](https://github.com/anomalyco/opencode/blob/7b3d4ce3a7db/packages/app/src/settings/search-catalog.ts) | P2 | L | Codex |
| B137 | B | Codex TUI Vim 模式〔没做〕 | 缺仅用于终端输入界面的 Vim 键位模式 | Codex `codex-rs/tui/src/slash_command.rs` | P2 | M | Codex |
| B138 | B | Codex TUI 宠物〔没做〕 | 缺终端界面宠物展示；非桌面核心能力 | [C](https://github.com/openai/codex/blob/6c0c6759d061/codex-rs/tui/src/slash_command.rs) | P2 | M | Codex |
| B139 | B | Codex Security 扫描工作台〔没做〕 | 缺仓库/branch/scan 模式创建、Findings/Repositories/coverage 和报告的完整面板 | Codex [Security plugin](https://learn.chatgpt.com/docs/security/plugin) | P2 | S | Hermes |

本区 83 项待处理；V5 原矩阵或附录独立补项可在来源索引中检索。

### C 区 · 设置与扩展

| 编号 | 区 | 功能（含状态） | 缺什么（一句话） | 抄谁（仓库文件或文档） | 优先级 | 难度 | 建议执行者 |
|---|---|---|---|---|---|---|---|
| C002 | C | 可搜索并直达具体设置项〔部分〕 | 只有设置组级搜索，缺每个具体表单字段的全文索引与直达。 | OpenCode `packages/app/src/settings/search-catalog.ts`; Codex [Settings](https://learn.chatgpt.com/docs/reference/settings) | P1 | M | Codex |
| C003 | C | 配置作用域、优先级和管理员策略〔部分〕 | 已显示部分设置来源，缺完整来源优先级及管理员只读策略的解析。 | ZCode `packages/shared/src/protocol.ts` (`AppSettings`); OpenCode `packages/app/src/settings/`; Claude [settings](https://code.claude.com/docs/en/settings), [managed settings](https://code.claude.com/docs/en/managed-settings), [server managed settings](https://code.claude.com/docs/en/server-managed-settings); Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference) | P1 | M | Codex |
| C005 | C | 系统与运行环境偏好（代理、证书、shell、终端、休眠、托盘、硬件加速）〔部分〕 | 代理只覆盖支持的模型 HTTP transport，尚无托盘、休眠和完整 shell/终端环境设置。 | ZCode `packages/ui/src/settingsPageHelpers.tsx`; OpenCode `packages/app/src/settings/general/`; Claude [terminal configuration](https://code.claude.com/docs/en/terminal-config); Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference) | P2 | M | Codex |
| C006 | C | 配置来源检查、变化诊断和设置状态〔部分〕 | 只提供本地诊断汇总，缺所有设置有效来源与覆盖优先级解释。 | Claude [debug your config](https://code.claude.com/docs/en/debug-your-config); Codex [troubleshooting](https://learn.chatgpt.com/docs/reference/troubleshooting), [config reference](https://learn.chatgpt.com/docs/config-file/config-reference) | P1 | M | Codex |
| C008 | C | Provider 多账号、OAuth、环境变量/配置凭据来源及账号切换〔部分〕 | 目前仅可切换静态 Key，缺第三方 OAuth 账号会话/刷新/登出与来源统一管理。 | OpenCode `settings/providers/{providers,connect,credentials}/`; Codex [auth](https://learn.chatgpt.com/docs/auth); Claude [authentication](https://code.claude.com/docs/en/authentication) | P1 | L | Codex |
| C010 | C | 模型参数、模态能力、推理等级、effort/fast mode、provider 参数〔部分〕 | 已有 effort 与自定义模型，缺能由运行时执行的 Fast mode/元数据路由合同。 | ZCode `settings/model-provider-section/{ModelEditorAdvanced,ProviderModelMetadataDialog,ProviderModelModalityOptions,ProviderModelReasoningLevelEditor}.tsx`; OpenCode `providers/models/variant.tsx`; Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference); Claude [model configuration](https://code.claude.com/docs/en/model-config), [fast mode](https://code.claude.com/docs/en/fast-mode) | P0 | M | Codex |
| C012 | C | 账号/Profile、登录/退出和本地配置档隔离〔部分〕 | 只展示本地 Profile，缺真实云账号登录/退出与配置档隔离服务。 | Codex [auth](https://learn.chatgpt.com/docs/auth); Claude [authentication](https://code.claude.com/docs/en/authentication); ZCode `CodingPlanStatusActions.tsx` | P1 | M | Codex |
| C013 | C | 用量、Token 趋势、模型归因、热图、预算/额度状态〔部分〕 | 已有 Token/费用统计，热图、统一预算及外部计划额度 API 仍不完整。 | ZCode `settings/usage-stats/{AppUsagePanel,CodingPlanUsagePanel,UsageHeatmap}.tsx`; Codex [Settings](https://learn.chatgpt.com/docs/reference/settings), [changelog](https://learn.chatgpt.com/docs/changelog); Claude [costs](https://code.claude.com/docs/en/costs), [monitoring usage](https://code.claude.com/docs/en/monitoring-usage); OpenCode `settings/providers/` | P0 | M | Codex |
| C016 | C | MCP OAuth、headers/scopes、重新认证/重连和连接诊断〔部分〕 | 可管理 MCP 连接/重启，但 OAuth/PKCE、续签和 scopes 尚缺运行时支持。 | ZCode `McpFailurePresentation.tsx`; OpenCode `servers/connect/`; Claude [MCP](https://code.claude.com/docs/en/mcp), [managed MCP](https://code.claude.com/docs/en/managed-mcp); Codex [MCP](https://learn.chatgpt.com/docs/extend/mcp) | P0 | L | Codex |
| C017 | C | MCP 项目/用户/Agent 作用域、启停与工具允许规则〔部分〕 | 已有部分 MCP 作用域 UI，缺完整 Agent scope 与每工具允许规则链路。 | OpenCode `settings/providers/extensions.tsx`; Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference); Claude [MCP](https://code.claude.com/docs/en/mcp); ZCode `McpSettingsSection.tsx` | P1 | M | Codex |
| C019 | C | Marketplace source 管理、来源校验、插件配置和诊断〔部分〕 | 缺 Marketplace source CRUD、来源验证及可诊断的插件配置流程。 | ZCode `PluginStoreSourcesDialog.tsx`, `AddMarketplaceSourceDialog.tsx`, `PluginConfigControls.tsx`; Claude [plugin marketplaces](https://code.claude.com/docs/en/plugins/marketplaces); Codex [plugin management](https://learn.chatgpt.com/docs/enterprise/plugin-management) | P1 | M | Codex |
| C020 | C | User/Workspace/Project 扩展作用域、覆盖和恢复默认〔部分〕 | 缺 User/Workspace/Project 扩展覆盖 API 和恢复默认闭环。 | ZCode `PluginsSection.tsx`; OpenCode `settings/providers/extensions.tsx`; Codex [plugins](https://learn.chatgpt.com/docs/plugins); Claude [settings](https://code.claude.com/docs/en/settings) | P1 | M | Codex |
| C021 | C | 插件远端同步、服务器/桌面端安装情况〔没做〕 | 缺插件配置/安装状态的设备与服务器远端同步协议。 | ZCode `RemotePluginSyncDialog.tsx` | P2 | L | Codex |
| C022 | C | 扩展注册表将 GUI 设置页、菜单、palette 命令、slash 命令和快捷键统一注册〔部分〕 | 只有只读扩展目录 metadata，缺插件菜单/设置页/slash/keybind 动态贡献 runtime。 | OpenCode `runtime/extension/{settings-pages,menubar-items,commands,host-apis}.ts*`; ZCode `plugin-ui/CONTRACT.md`, `plugin-ui/app/`; Codex [plugins](https://learn.chatgpt.com/docs/plugins) | P1 | L | Codex |
| C023 | C | 插件交互 UI、小组件状态、服务调用和确认后 follow-up〔没做〕 | 缺插件交互式 UI host、小组件状态、服务调用和确认后 follow-up。 | `packages/ui/src/plugin-ui/CONTRACT.md`, `pluginUiAppTools.ts`, `pluginUiHostAppHandlers.ts`, `pluginUiPageManager.ts` | P1 | L | Codex |
| C025 | C | Skills User/Workspace/Plugin scope、frontmatter、按 Agent 权限和远端同步〔部分〕 | Skills 安全与生命周期接入市场，尚缺完整作用域、frontmatter 与远端同步。 | ZCode `SkillsSection.tsx`, `RemoteSkillSyncDialog.tsx`; OpenCode `skills.mdx`; Codex [customization](https://learn.chatgpt.com/docs/customization/overview); Claude [skills](https://code.claude.com/docs/en/skills) | P2 | L | Codex |
| C027 | C | Hook 生命周期事件、command/prompt/agent/HTTP/MCP hook 管理与测试〔部分〕 | 已有 Hook CRUD/测试，缺 HTTP/MCP hook schema 和通用导入格式。 | ZCode `settings/{HooksSection,HookForm,HooksList}.tsx`; Codex [hooks](https://learn.chatgpt.com/docs/hooks); Claude [Hooks guide](https://code.claude.com/docs/en/hooks-guide), [reference](https://code.claude.com/docs/en/hooks); OpenCode `runtime/extension/` | P1 | M | Codex |
| C028 | C | Workspace Hook trust/review、失败关闭与策略来源〔没做〕 | 缺逐 Hook 工作区信任审查及失败关闭策略来源。 | ZCode `WorkspaceHookTrustNotice.tsx`, `workspaceHookReviewCommands.ts`; Claude [Hooks](https://code.claude.com/docs/en/hooks); Codex [hooks](https://learn.chatgpt.com/docs/hooks) | P1 | M | Codex |
| C031 | C | 命令面板与统一命令注册（palette、slash、keybind 共用）〔部分〕 | 已有命令面板和自定义命令，但 palette/slash/keybind 尚未统一共享注册表。 | ZCode `packages/ui/src/command-center/CommandCenterDialog.tsx`; OpenCode `packages/app/src/shell/commands/{command,palette}.tsx`; Codex [commands](https://learn.chatgpt.com/docs/reference/commands) | P0 | L | Codex |
| C033 | C | 屏幕阅读器、全屏/终端适配、语音听写与可访问性偏好〔部分〕 | 缺面向全应用的读屏/语音/无障碍偏好与输入适配。 | Claude [accessibility](https://code.claude.com/docs/en/accessibility), [fullscreen](https://code.claude.com/docs/en/fullscreen), [voice dictation](https://code.claude.com/docs/en/voice-dictation); ZCode `settingsPageHelpers.tsx` | P1 | M | Codex |
| C036 | C | 扫描其他 Agent 配置/会话、选择范围后导入〔部分〕 | 可移植配置包已做，外部 Agent 会话/配置按范围选择导入尚不完整。 | ZCode `settings/{MigrationSection,ExternalAgentImportDialog}.tsx`; Codex [import](https://learn.chatgpt.com/docs/import); Claude [MCP](https://code.claude.com/docs/en/mcp) | P1 | M | Codex |
| C038 | C | 远程控制会话、设备配对、远端状态/同步和 QR 会话〔部分〕 | 已有设备登记/takeover，缺 QR 配对与跨设备状态同步。 | ZCode `WorkspaceWebRemoteControl{Trigger,Dialog}.tsx`; Codex [remote connections](https://learn.chatgpt.com/docs/remote-connections); Claude [Remote Control](https://code.claude.com/docs/en/remote-control), [mobile](https://code.claude.com/docs/en/mobile) | P2 | L | Codex |
| C040 | C | Agent 消息平台 gateway、平台策略、平台 toolset 和定时任务投递〔部分〕 | 已有 channels registry 和策略 API，缺部分渠道真实适配器及完整投递/配置表单。 | [Hermes messaging](https://github.com/NousResearch/hermes-agent/blob/66605471e9f0b0832abbefaf625ce08e948ca540/website/docs/user-guide/messaging/index.md), [OpenClaw channels](https://docs.openclaw.ai/channels), [Hermes cron delivery](https://github.com/NousResearch/hermes-agent/blob/66605471e9f0b0832abbefaf625ce08e948ca540/website/docs/user-guide/features/cron.md) | P1 | L | Codex |
| C044 | C | 远端反馈/诊断中心、附件截图、工单跟踪与补充材料〔部分〕 | 诊断报告可复制，缺远端反馈附件与工单跟踪服务。 | ZCode `packages/ui/src/feedback/{FeedbackCenter,FeedbackSubmitForm,TicketDetail}.tsx`; Codex [troubleshooting](https://learn.chatgpt.com/docs/reference/troubleshooting); Claude [feedback](https://code.claude.com/docs/en/commands) | P1 | S | Hermes |
| C046 | C | 多语言文案和设置/命令翻译覆盖〔部分〕 | 缺覆盖设置、命令、错误提示的完整中英文翻译体系。 | ZCode `packages/ui/src/i18n/locales/{en-US,zh-CN}.ts`; OpenCode `packages/app/src/runtime/i18n/`, `packages/ui/src/i18n/` | P1 | S | Hermes |
| C048 | C | 会话权限模式、Docker 沙箱和网络开关〔部分〕 | 会话权限和 Docker 网络已接，缺执行器支持的细粒度允许/拒绝规则。 | V5 §C 计划/审查与自动接受行；Claude [permissions](https://code.claude.com/docs/en/permissions)；Atlas `core/atlas/api/conversations_router.py`, `run_drive.py` | P0 | L | Codex |
| C053 | C | Claude Code / Codex 会话历史选择性导入〔部分〕 | 导入仅处理可见文本，工具/推理/子代理历史尚不能无损选择导入。 | Claude [env vars](https://code.claude.com/docs/en/env-vars); Codex [`rollout` recorder](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/recorder.rs), V5 §C 配置传输与附录 VI–IX；Atlas `core/atlas/runtime/external_import.py`, `core/atlas/api/external_history_router.py` | P1 | M | Codex |
| C054 | C | 崩溃上报与遥测隐私开关〔部分〕 | 已有 Memos 遥测 opt-out，缺应用级崩溃上报和其它渠道统一隐私控制。 | V5 §C 诊断/Computer Use 行、VIII-A；Atlas `frontend/src/main/electron.ts`, `diagnostics_router.py` | P1 | M | Codex |
| C055 | C | 更新通道（stable/beta/nightly）〔没做〕 | 仅支持源码仓库更新检测，缺打包版本的 feed 和 stable/beta/nightly 切换。 | V5 §C 自动更新行；Atlas `frontend/src/main/sourceUpdate.ts`, `components/UpdateBanner.tsx` | P2 | S | Hermes |
| C060 | C | 云任务与外部集成入口〔部分〕 | 本机集成入口已有，缺真实云任务环境/外部云任务服务。 | Claude [connectors](https://code.claude.com/docs/en/connectors), [scheduled tasks](https://code.claude.com/docs/en/scheduled-tasks); V5 §C Claude 专有行、IX N005–N006 | P2 | L | Codex |
| C064 | C | 单独的自动接受/权限规则编辑〔部分〕 | 只有会话模式/Docker 规则，缺细粒度工具 auto-approve allow/deny 编辑器。 | V5 §C 计划/审查权限、自动接受行；Claude [permissions](https://code.claude.com/docs/en/permissions) | P1 | M | Codex |
| C065 | C | Off-peak 低峰任务〔没做〕 | 没有离峰额度时钟或任务队列，低峰任务未实现。 | V5 §C Off-peak 行；ZCode `packages/ui/src/i18n/locales/zh-CN.ts`（U） | P2 | M | Codex |
| C066 | C | 可保存、复用并共享工作流〔部分〕 | Recipe 只回填 prompt，缺可执行、可复用并分享的工作流定义。 | Goose [recipes](https://goose-docs.ai/docs/guides/recipes/); V5 §C 保存工作流行、Codex App 自动化行 | P1 | L | Codex |
| C067 | C | 浏览器控制开关、Chrome profile/cookie/localStorage 导入、清理〔没做〕 | 有 Browser 面板，缺 Chrome profile/cookie/localStorage 导入与站点数据清理 API。 | V5 VIII-A BrowserSettingsSection（U）；ZCode settings 文案 | P1 | M | Codex |
| C068 | C | Computer Use 授权和插件开关〔部分〕 | 有本地 Computer Use/节点审批，缺统一的 Computer Use 插件启停与授权设置。 | V5 §C Computer Use 行及附录 VI/IX | P0 | M | Codex |
| C069 | C | 文件搜索忽略规则（`.zcodeignore`）〔没做〕 | 缺由实际文件搜索器读取的 .zcodeignore 忽略规则。 | V5 §C 工作区搜索规则行；ZCode `settings` 文案（U） | P1 | M | Codex |
| C070 | C | Worktree 策略与清理〔部分〕 | 有 Code 工作树界面，缺 Worktree strategy、保留和自动清理策略。 | V5 §C Worktree 行；OpenCode V2 SDK/Plugin source | P1 | S | Hermes |
| C071 | C | SSH host / remote workspace 配置〔部分〕 | 已有 SSH workspace，缺独立 SSH host registry/远程工作区统一设置。 | V5 §C SSH 行；各家官方 Desktop/Remote Control docs | P1 | L | Codex |
| C072 | C | 配套 CLI 安装〔部分〕 | CLI 随 Python 包可用，缺桌面侧安装与 PATH/命令路径管理。 | V5 §C Install CLI 行；Atlas `core/atlas/cli.py` | P1 | S | Hermes |
| C073 | C | 自定义 LSP server 配置〔部分〕 | 缺可被运行时消费的自定义 LSP server 配置 UI/API | V5 §C 扩展 LSP / Web search / Experimental 行；Atlas `LspStatusSection.tsx`, `workspace_router.py` | P1 | M | Codex |
| C074 | C | 网页搜索 Provider 选择〔部分〕 | 缺可被运行时消费的搜索 Provider 设置 | V5 §C 扩展 LSP / Web search / Experimental 行；Atlas `LspStatusSection.tsx`, `workspace_router.py` | P1 | M | Codex |
| C075 | C | 实验功能开关〔部分〕 | 缺统一实验设置与真实 Feature Flag 的执行链路 | V5 §C 扩展 LSP / Web search / Experimental 行；Atlas `LspStatusSection.tsx`, `workspace_router.py` | P2 | S | Hermes |
| C076 | C | 自动归档期限（3/7/14/30天）〔没做〕 | 缺自动归档保留策略、定时执行和设置入口 | V5 §C 本机运行设置行；Claude [monitoring usage](https://code.claude.com/docs/en/monitoring-usage) | P1 | S | Hermes |
| C077 | C | 数据库目录迁移〔没做〕 | 缺安全的数据目录运行时迁移流程及设置入口 | V5 §C 本机运行设置行；Claude [monitoring usage](https://code.claude.com/docs/en/monitoring-usage) | P2 | S | Hermes |
| C078 | C | 模型 I/O 完整保留策略〔没做〕 | 缺模型请求/响应 I/O 保留与清理的可执行配置 | V5 §C 本机运行设置行；Claude [monitoring usage](https://code.claude.com/docs/en/monitoring-usage) | P2 | M | Codex |
| C079 | C | 系统托盘驻留〔没做〕 | 缺 Electron 托盘及关闭窗口后的驻留行为 | V5 §C Windows tray / prevent sleep 行 | P1 | L | Codex |
| C080 | C | 任务期间防休眠〔没做〕 | 缺任务运行期 power-save blocker 控制 | V5 §C Windows tray / prevent sleep 行 | P1 | M | Codex |
| C081 | C | 项目/工作区独立多窗口〔没做〕 | 缺每项目独立 Electron 窗口生命周期、恢复和导航 | ZCode `packages/desktop/src/main/desktopApplicationMenu.ts`；Claude [Desktop](https://code.claude.com/docs/en/desktop) | P1 | L | Codex |
| C082 | C | 会话公开分享服务与访问控制〔没做〕 | 缺分享数据存储、授权、公开链接生成与撤销；本地导出不等于公开分享 | ZCode `packages/ui/src/ConversationShareMenu.tsx`（固定 aac4755666d09...） | P2 | M | Codex |
| C083 | C | Home session 跨消息渠道汇聚与 dock〔没做〕 | 缺跨渠道 DM 适配、长期会话路由和页面上下文快照注入 | OpenClaw `docs/concepts/main-session.md` | P1 | M | Codex |
| C084 | C | 常驻 Bot 名册及群聊协作〔没做〕 | 缺 Bot profile/长期聊天、名册分组和 Bot 间 @ 消息路由 | Hermes `website/docs/user-guide/bot-mode.md` | P1 | L | Codex |
| C085 | C | Claude 手机 Dispatch 开发任务〔没做〕 | 缺手机派单到桌面开发会话的设备配对与派发回执 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P2 | L | Codex |
| C086 | C | Claude Cloud Projects 持续任务〔没做〕 | 缺云项目服务、共享任务与持续记忆；本机项目关联不等同 | Claude [Projects](https://code.claude.com/docs/en/claude-projects) | P2 | L | Codex |
| C087 | C | OpenCode Web pair 设备授权〔没做〕 | 缺浏览器配对访问流程与服务端设备认证 | OpenCode [V2 docs](https://opencode.ai/v2/docs/) | P2 | L | Codex |
| C088 | C | 状态栏/标题栏自定义〔没做〕 | 缺可持久化的标题栏、状态栏配置界面 | [C](https://github.com/openai/codex/blob/6c0c6759d061/codex-rs/tui/src/slash_command.rs) · [H](https://code.claude.com/docs/en/statusline) | P2 | L | Codex |
| C089 | C | Claude Preview Server 多配置〔没做〕 | 缺 Preview Server 多 profile 配置、切换和状态显示 | [H](https://code.claude.com/docs/en/desktop) | P1 | M | Codex |
| C090 | C | Claude Connectors 统一管理〔没做〕 | 缺第三方云端 Connector 的独立认证、发现和管理；现有 Linear/Slack 本地集成不等价 | Claude [Connectors](https://code.claude.com/docs/en/connectors) | P2 | L | Codex |
| C091 | C | Claude Mods 自定义交互面〔没做〕 | 缺 Claude Mods 同等级的可安装交互配置与页面承载 | Claude [Desktop](https://code.claude.com/docs/en/desktop) | P2 | M | Codex |
| C092 | C | OpenCode V2 cli.json 配置兼容〔没做〕 | 缺 OpenCode V2 CLI 的 cli.json 配置格式迁移/编辑 | OpenCode [V2 migration](https://opencode.ai/v2/docs/migrate-v1) | P2 | M | Codex |
| C093 | C | OpenCode V2 CLI 本地插件加载〔没做〕 | 缺 OpenCode V2 CLI 本地插件加载协议；Atlas 扩展 metadata 不等于兼容 runtime | OpenCode https://opencode.ai/v2/docs/cli/plugins（V5 C264） | P2 | L | Codex |
| C094 | C | OpenCode V1→V2 插件迁移〔没做〕 | 缺 V1→V2 插件协议适配与迁移器 | OpenCode [V2 migration](https://opencode.ai/v2/docs/migrate-v1) | P2 | L | Codex |
| C095 | C | Codex Sites 托管网页项目〔没做〕 | 缺云端网站项目托管、部署和访问服务 | [C](https://learn.chatgpt.com/docs/changelog) | P2 | L | Codex |
| C096 | C | Codex Chronicle 屏幕上下文记忆〔没做〕 | 缺经同意的屏幕上下文采集、可暂停的记忆汇总与对应持久化 | Codex [Chronicle](https://learn.chatgpt.com/docs/customization/chronicle) | P2 | L | Codex |
| C097 | C | Codex Micro 外设映射与状态〔没做〕 | 缺专用硬件配对、6 个 Agent Keys 状态、command keys、摇杆/旋钮映射和配置 | Codex [Micro](https://learn.chatgpt.com/docs/features/codex-micro) | P2 | M | Codex |
| C098 | C | Codex Daybreak 模式〔没做〕 | 缺 Codex TUI 专属模式入口；跨端语义需独立核实 | [C](https://github.com/openai/codex/blob/6c0c6759d061/codex-rs/tui/src/slash_command.rs) | P2 | S | Hermes |
| C099 | C | Codex 调试沙箱设置〔没做〕 | 缺面向开发者的 TUI 沙箱配置入口；不等同已有权限模式 | Codex `codex-rs/tui/src/slash_command.rs` | P2 | L | Codex |
| C100 | C | 代理软件开销诊断〔没做〕 | 缺代理相关耗时、资源与配置开销诊断视图 | [Z](https://github.com/zai-org/ZCode/blob/aac4755666d0/packages/ui/src/i18n/locales/zh-CN.ts) · [C](https://github.com/openai/codex/blob/6c0c6759d061/codex-rs/tui/src/slash_command.rs) | P1 | M | Codex |
| C101 | C | 语音听写自定义词典〔没做〕 | 缺词典管理/纠错持久化；语音听写本身已有 | Codex 官方 Desktop 更新（F1-B.md 第 137 行） | P1 | M | Codex |

本区 68 项待处理；V5 原矩阵或附录独立补项可在来源索引中检索。

### D 区 · 工具

| 编号 | 区 | 功能（含状态） | 缺什么（一句话） | 抄谁（仓库文件或文档） | 优先级 | 难度 | 建议执行者 |
|---|---|---|---|---|---|---|---|
| D001 | D | 文件读取（路径、范围、编码/大文件保护）〔部分〕 | 缺按行范围/字节范围读取及大文件硬上限；当前一次读完整文件 | Claude [tools reference](https://code.claude.com/docs/en/tools-reference)；ZCode `apps/zcode-cli/packages/core/src/tool/handlers/read.ts`；OpenCode `packages/core/src/tool/plugin/read.ts`；Codex core handler index 未列独立 text Read handler | P0 | M | Codex |
| D002 | D | 文件写入〔部分〕 | 缺工作区路径限制与越界拒绝；当前 local_file 可写本机任意路径 | Claude tools reference；ZCode `handlers/write.ts`；OpenCode `plugin/write.ts`；Codex core handler index 未列独立 Write handler | P0 | M | Codex |
| D003 | D | 文件编辑、批量编辑〔部分〕 | edit 仅单文件，多文件 patch 不具事务性；缺批量校验及原子回执 | Claude tools reference + [changelog](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)；ZCode `handlers/edit.ts`；OpenCode `plugin/edit.ts`；Codex 通过 `apply_patch`/shell 组合 | P0 | M | Codex |
| D011 | D | 后台进程启动、等待、输入、输出、停止〔部分〕 | 缺 Claude TaskOutput/TaskStop 兼容 callable 名称与运行映射 | Codex `handlers/exec_command.rs`, `write_stdin.rs`；Claude TaskOutput/TaskStop（TaskOutput 有文档弃用冲突）；ZCode `handlers/{bash,task_output,task_stop}.ts`；OpenCode `plugin/shell.ts` | P0 | M | Codex |
| D013 | D | 计划模式入口/退出〔部分〕 | 有 update_plan，但缺显式 EnterPlanMode/ExitPlanMode 工具与状态转换 | Claude EnterPlanMode/ExitPlanMode；ZCode 同名工具；Codex `update_plan.rs` | P0 | M | Codex |
| D014 | D | 询问用户 / 结构化问题〔部分〕 | 仅返回字符串；缺标题、选项描述、多选结果的结构化传递 | Claude AskUserQuestion；ZCode AskUserQuestion；OpenCode `plugin/question.ts` | P0 | M | Codex |
| D016 | D | 代理创建和委派〔部分〕 | 委派参数缺调用级模型、reasoning effort 与最大深度控制 | Codex `handlers/multi_agent.rs`、TUI task tools；Claude Agent；ZCode Agent/Task；OpenCode `plugin/subagent.ts` | P0 | M | Codex |
| D017 | D | 子代理消息、恢复、等待、中断、关闭〔部分〕 | 缺模型侧等待/取消/恢复/关闭/结果升级，以及跨会话 Agent registry、消息路由与权限校验（合入 F1-unassigned） | Codex multi-agent v1/v2 handlers；Claude SendMessage/Agent teams；ZCode SendMessage/RespondToCoordinator/submit_result/escalate/ReplyToChannel/TaskStop | P0 | L | Codex |
| D018 | D | 会话上下文读取/工具历史〔部分〕 | 缺当前运行工具历史读取；new_context 依赖 Hermes handoff callback | ZCode `ReadSessionContext` handler；Codex `get_context_remaining` / `new_context` | P0 | M | Codex |
| D021 | D | Web 搜索〔部分〕 | mode 不改变检索；当前仅 DDG，缺 cached/live/provider 能力控制及不支持模式的显式结果 | Codex `web_search` handler + [web search docs](https://learn.chatgpt.com/docs/web-search)；Claude WebSearch；ZCode `handlers/web-search.ts`；OpenCode `plugin/websearch.ts` | P0 | M | Codex |
| D022 | D | Web 抓取〔部分〕 | 缺重定向跳数/响应大小限制和 TTL 缓存 | Claude WebFetch；ZCode `handlers/web-fetch.ts`；OpenCode `plugin/webfetch.ts` | P0 | S | Hermes |
| D029 | D | Computer Use〔部分〕 | 当前只有聚合动作；缺 request_access、stop control 等低层 Computer Use callable | Codex [computer use docs](https://learn.chatgpt.com/docs/computer-use)；Claude [computer use](https://code.claude.com/docs/en/computer-use)；ZCode `packages/zcode-cua` / `packages/zcode-cua-plugin` | P0 | M | Codex |
| D030 | D | Browser 标签页/预览/导航〔部分〕 | BrowserPanel 已有预览/停止按钮，但 browser.panel.sync 无前端消费者，browser_use 缺 tab.stop 与 pane handoff；缺 F1-unassigned Review pane/local preview 后端接线 | `packages/plugin-browser/src/rpc.ts`, `tools.ts` | P0 | M | Codex |
| D031 | D | Browser 文档/DOM 操作〔部分〕 | 缺 fill_form、selectOption 与 locator press 等 DOM 操作 | `packages/plugin-browser/src/rpc.ts` | P0 | M | Codex |
| D032 | D | Browser 文件交互〔没做〕 | 缺 Browser 上传/下载/拖放及受授权文件句柄 API | `packages/plugin-browser/src/rpc.ts` | P1 | M | Codex |
| D033 | D | Browser console/network/trace/CPU/heap/Lighthouse〔部分〕 | 只有 console；缺 network、trace、CPU/heap profiler 与 Lighthouse 内置操作 | `packages/plugin-browser/src/rpc.ts` | P1 | L | Codex |
| D035 | D | MCP Streamable HTTP 与认证〔部分〕 | 有 Streamable HTTP/headers，缺 OAuth 授权、PKCE、令牌持久化和刷新 | [Codex MCP docs](https://learn.chatgpt.com/docs/extend/mcp)；OpenCode `packages/core/src/tool/plugin/mcp-resource.ts`；Claude MCP docs | P0 | L | Codex |
| D038 | D | MCP 工具延迟发现/搜索〔部分〕 | tool_search 只返回名称/描述；缺按需 schema 注入，工具仍在运行启动时枚举 | Claude ToolSearch；Codex `tool_search`/plugin extension registry；ZCode `registry.ts` | P1 | M | Codex |
| D039 | D | 插件/skill 工具〔部分〕 | 缺将已安装插件的 skills/commands 暴露为统一模型侧可调用/可搜索工具 | Claude Skill/Mods；Codex plugins docs；ZCode `registry.ts`, `packages/core/src/tool/handlers/skill.ts`, `UI_PLUGIN.md`；OpenCode `plugin/skill.ts` | P0 | M | Codex |
| D040 | D | 插件安装/发现请求〔部分〕 | 可请求安装，但模型侧目录未涵盖完整已安装插件运行状态；缺统一 discover/list/catalog 返回 | Codex `list_plugins`, `request_plugin_install` tool handlers；[plugins docs](https://learn.chatgpt.com/docs/plugins) | P1 | M | Codex |
| D042 | D | 工具审批范围/理由〔部分〕 | 审批事件未统一携带显式 scope/resource 与 reason；部分 PreToolUse 分支丢失理由 | Claude permissions docs；ZCode `packages/ui/src/PermissionDialog.tsx`, `lib/permissionRequest.ts`；OpenCode `packages/app/src/session/requests/` | P0 | M | Codex |
| D043 | D | Tool registry 和兼容名称〔部分〕 | Kernel schema 与 executor dispatch 分开维护；缺单一 registry 驱动注册 | Codex `codex-rs/core/src/tools/registry.rs`; ZCode `packages/core/src/tool/registry.ts`; OpenCode `packages/core/src/plugin/internal.ts`; Claude tools reference | P1 | L | Codex |
| D044 | D | Workflow 动态编排〔部分〕 | 缺持久化、可复用的命名 workflow 定义注册表与 save/list/get 生命周期 | Claude Workflow；ZCode workflow tools；OpenCode CodeMode `packages/core/src/codemode` | P1 | L | Codex |
| D046 | D | OpenCode session rename/move 与 worktree 生命周期〔部分〕 | 缺跨 workspace 活动会话 handoff；worktree 自动清理/回收流程不足（合入 F1-unassigned） | `packages/core/src/tool/plugin/opencode.ts` | P1 | L | Codex |
| D047 | D | OpenCode model/provider 发现〔部分〕 | 仅查 Atlas 配置与静态 provider catalog；缺完整 provider/model 动态发现和过滤分页 | `packages/core/src/tool/plugin/opencode.ts` | P1 | M | Codex |
| D048 | D | 应用生成生命周期〔部分〕 | 只管理 HTML 文件，没有独立 app/window 创建、运行和关闭生命周期 | `crates/goose/src/agents/platform_extensions/apps.rs` | P1 | M | Codex |
| D049 | D | 交互式数据可视化〔部分〕 | 仅支持 bar/line/donut/radar，无其他矩阵图类和界面内交互展示器 | `crates/goose-mcp/src/autovisualiser/mod.rs` | P1 | S | Hermes |
| D052 | D | 无头/SDK/app-server 调用〔部分〕 | ACP 只支持文本 session；缺按 session 注入 MCP、loadSession 和 free-text elicitation | Codex `codex exec` / app-server 官方文档；Claude Code `claude -p` CLI 文档；[ACP v1 session setup](https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/session-setup.mdx)；Codex app-server 文档 | P1 | M | Codex |
| D053 | D | Git 平台 PR 创建与评论〔部分〕 | 已有 PR 创建/评论 callable，缺可信 PR 状态查询/徽章数据工具（合入 F1-unassigned） | GitHub CLI `gh pr create` / `gh pr comment` 官方文档；Atlas `api/workspace_router.py` 现有 PR 创建 API | P1 | M | Codex |
| D056 | D | Android 创建应用〔部分〕 | Android scaffold 缺 compileSdk、overwrite 参数及覆盖前确认/冲突策略 | ZCode `四大Agent功能矩阵V5.md` 附录 VIII-K2/K3；`android_create_app`；准确参数见矩阵 VIII-K2 | P2 | S | Hermes |
| D082 | D | iOS 创建应用〔部分〕 | iOS scaffold 缺 overwrite 参数及覆盖前确认/冲突策略 | ZCode `四大Agent功能矩阵V5.md` 附录 VIII-K2/K3；`ios_create_app`；准确参数见 VIII-K3 | P2 | S | Hermes |
| D097 | D | ZCode Browser Use runtime 选择〔部分〕 | 只有 X2 单一 runtime；runtime select 不可持久化且不支持 provider 切换 | [`browser-use-plugin/docs/overview.md`](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/browser-use-plugin/docs/overview.md) | P1 | L | Codex |
| D098 | D | Browser tabs 生命周期与用户 tab claim〔部分〕 | 缺 desktop user tab ownership registry、claim/finalize 生命周期 | ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`agent.browsers`, `browser.tabs`, `browser.user` | P0 | L | Codex |
| D100 | D | Browser DOM snapshot 与 locator〔部分〕 | locator 未覆盖完整 press/select/fill_form 行为；返回的 Atlas snapshot/ref 不等同 upstream ARIA evidence | ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`playwright.domSnapshot`, `getBy*/locator` | P0 | M | Codex |
| D101 | D | Browser frame/JS/wait〔部分〕 | frame/evaluate/wait 依赖 Hermes/CDP supervisor；缺完整可用状态与策略受限行为一致性 | ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`frameLocator/evaluate/waitForURL/waitForLoadState` | P1 | M | Codex |
| D104 | D | Browser 截图与视口〔部分〕 | 截图返回 cache path/data URL，未形成可供界面访问的 workspace artifact | ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`tab.screenshot`, `setViewportSize`, `viewportSize` | P1 | M | Codex |
| D105 | D | Browser 原生 JS dialog〔部分〕 | 原生 JS dialog 仅在活动 CDP supervisor 下可用，缺统一 pane/runtime 管理 | ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`tab.getJsDialog` | P1 | L | Codex |
| D106 | D | Browser deliverable/handoff〔部分〕 | handoff 可用；markDeliverable/finalize 缺 pane 所有权与交付 registry | ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`markDeliverable`, `markHandoff` | P1 | L | Codex |
| D107 | D | Browser recording〔部分〕 | 能录制步骤并保存 skill，但缺 WebM 视频产物和通用流程回放交付 | ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`tab.recording.{start,status,cancel}` | P1 | L | Codex |
| D108 | D | Browser panel visibility/headless〔部分〕 | 缺 browser pane visibility 控制及 headless launch 模式 | ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`browser.capabilities.get("visibility").set`, `--browser-use=headless` | P1 | M | Codex |
| D110 | D | ZCode image-search 插件〔部分〕 | 无内置 image_search callable；外部 MCP 可配置不等于提供该服务/schema，远端 schema 仍需官方接口/凭据 | `packages/image-search-plugin/.zcode-plugin/plugin.json`（远程 HTTP MCP；工具 schema 在远端不可见） | P2 | M | Codex |
| D111 | D | ZCode documents/pdf/presentations/spreadsheets 插件 skills〔部分〕 | 已有 office create/read 能力，但缺 documents/presentations/spreadsheets 对应 skill/payload 工作流 | `packages/{documents,pdf,presentations,spreadsheets}-plugin/.zcode-plugin/plugin.json` | P2 | L | Codex |
| D112 | D | Codex App Computer Use〔部分〕 | 缺 Computer Use request/stop 低层动作与授权生命周期；后台窗口控制受 Atlas host 能力限制 | [Computer Use 官方插件发布说明](https://help.openai.com/en/articles/11391654)；[computer use docs](https://learn.chatgpt.com/docs/computer-use) | P0 | S | Hermes |
| D113 | D | Codex Record & Replay〔部分〕 | 缺将一般桌面录制整理为可参数化并可调用的 skill lifecycle；现有仅 browser steps→skill | [Record & Replay](https://learn.chatgpt.com/docs/extend/record-and-replay) | P1 | L | Codex |
| D114 | D | Codex Security plugin scan〔部分〕 | 已有本地 bounded security_scan；缺 repo/branch 选择与 findings/report/repository 生命周期工具 | [Security plugin](https://learn.chatgpt.com/docs/security/plugin) | P2 | L | Codex |
| D115 | D | 本地定时任务管理〔没做〕 | 缺 CronCreate/List/Update/Delete 模型工具及 Atlas 可持久化调度 CRUD；现有前端 Automation 不提供同等 callable | ZCode `apps/zcode-cli/packages/core/src/tool/handlers/cron.ts`；Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | P1 | L | Codex |
| D116 | D | 离峰任务管理〔没做〕 | 缺 OffPeakCreate/List callable 与独立离峰队列/生命周期语义 | ZCode `apps/zcode-cli/packages/core/src/tool/handlers/off-peak.ts` | P2 | M | Codex |
| D117 | D | 远程 Routine 触发〔没做〕 | 缺 RemoteTrigger callable 与已授权 routine 触发桥接 | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | P2 | S | Hermes |
| D118 | D | 会话唤醒调度〔没做〕 | 缺 ScheduleWakeup callable；普通 clock.sleep 不提供持久化的会话唤醒 | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | P1 | M | Codex |
| D119 | D | Node REPL / JavaScript 工具〔没做〕 | 缺有状态 JavaScript REPL callable；浏览器 API 行不等于 Node REPL | ZCode `apps/zcode-cli/packages/core/src/tool/handlers/node-repl.ts` | P1 | L | Codex |
| D120 | D | 回复外部频道〔没做〕 | 缺带 channel/message target 与送达回执的 reply_to_channel callable | ZCode `apps/zcode-cli/packages/core/src/tool/handlers/reply-to-channel.ts` | P2 | S | Hermes |
| D121 | D | 托管 Artifact 发布〔没做〕 | 缺将 HTML/Markdown 交互内容发布到受管 Artifact 并返回可访问引用的 callable | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | P2 | S | Hermes |
| D122 | D | 结束会话〔没做〕 | 缺结束当前 Agent 会话的显式模型工具与用户可见结束原因 | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | P1 | M | Codex |
| D123 | D | 事件流监视〔没做〕 | 缺对后台命令输出/异步事件/WebSocket 的订阅与增量回传工具 | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | P1 | M | Codex |
| D124 | D | 推送通知〔没做〕 | 缺经用户授权的桌面/移动推送通知 callable 与送达状态 | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | P2 | M | Codex |
| D125 | D | 结构化审查发现〔没做〕 | 缺 ReportFindings 的结构化 finding/severity/location/evidence 接收与持久化 callable | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | P1 | M | Codex |
| D126 | D | 用户反馈草稿〔没做〕 | 缺可审核的 SendFeedback 草稿创建 callable 与状态回执 | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | P2 | M | Codex |
| D127 | D | 向客户端发送文件〔没做〕 | 缺受授权的本地文件传至客户端 callable 与成功/失败回执 | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | P1 | M | Codex |
| D128 | D | 分享入门指南〔没做〕 | 缺 ShareOnboardingGuide callable 及指南选择/分享结果 | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | P2 | S | Hermes |
| D129 | D | 等待 MCP 服务就绪〔没做〕 | 缺 WaitForMcpServers callable 与服务启动/超时状态查询 | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | P1 | M | Codex |

本区 60 项待处理；V5 原矩阵或附录独立补项可在来源索引中检索。

## 三、P0/P1 任务卡（每卡 5–10 条，只含同一区）

卡内编号为上文唯一 ID；任务卡以 UI/后端文件落点相近为原则分组。若来源没列 Atlas 目标文件，用**待定**表示，不能擅自认定具体仓库位置。P2 不切卡。

### A-TC-01｜会话侧栏状态、导航与项目动作（10 条）

- **包含编号：** A002, A007, A008, A025, A027, A029, A011, A018, A013, A036
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - ZCode 新会话命令与 UI 注册；OpenCode app session commands；Codex Desktop 文档；Claude Desktop 文档
  - ZCode task list status 与 locale；Codex 活动/优先级视图文档；Claude Desktop、Agent view 及 v2.1.207、v2.1.257、v2.1.287 changelog
  - ZCode task scope/project 列表；OpenCode Projects 与 Servers 页面；Codex session picker cwd/all 和官方 Projects 文档；Claude Desktop、Manage sessions
  - ZCode task status badges；Codex Activity/Priority 文档；Claude Agent view、Desktop、v2.1.207 与 v2.1.257 changelog
  - ZCode row status；Codex Activity view 文档；Claude Desktop notifications、Agent view、v2.1.210/v2.1.295/v2.1.296 changelog
  - ZCode shortcut registry/keybindings setting；OpenCode app keybind registry/settings；Codex TUI keymap 与官方 shortcuts；Claude commands 与 v2.1.288
  - ZCode draggable task/group/project UI；OpenCode project reorder；Claude Agent view reorder
  - ZCode task context menu；OpenCode session context menu 支持 right-click/Shift+F10/long-press
  - OpenCode Projects 页面与项目命令；Codex Desktop Projects 文档；Claude Desktop
  - OpenCode `packages/app/src/settings/search-catalog.ts`（V5 E 项；仅用于功能发现）
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### B-TC-01｜会话子功能：反馈、分支与工作流（6 条）

- **包含编号：** B008, B047, B122, B130, B131, B132
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/v4/ConversationHookDetailsAction.tsx`；Codex TUI fixed source `codex-rs/tui/src/slash_command.rs`（`6c0c6759d061`）；Codex [Desktop slash commands](https://learn.chatgpt.com/docs/reference/slash-commands)
  - [reference commands](https://learn.chatgpt.com/docs/reference/commands)
  - ZCode 固定 SHA：`packages/ui/src/app-shell/WorkflowRunDirectorySidePane.tsx`；Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - Pi `packages/coding-agent/docs/sessions.md`
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### B-TC-02｜Composer：Slash、队列与快速输入（9 条）

- **包含编号：** B010, B032, B038, B048, B051, B079, B088, B089, B097
- **Atlas 拟修改文件/目录：** `App.tsx`；`components/ConversationMessage.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/v4/{ConversationSelectionTooltip.tsx,SelectionActionMenu.tsx}`；Codex [side chat](https://learn.chatgpt.com/docs/app)；Claude [desktop](https://code.claude.com/docs/en/desktop)
  - ZCode packages/ui/src/lib/slashCommands.ts、hooks/useSlashCommands.ts、CLI command-center；OpenCode packages/app/src/components/dialog-select-*；Codex commands 文档；Claude commands 文档
  - [git worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)；ZCode workspace shell；Atlas Worktree 面板/API
  - OpenCode session composer `!` mode；Claude [interactive mode](https://code.claude.com/docs/en/interactive-mode)
  - ZCode `packages/ui/src/v4/ConversationQueuePanel.tsx`；OpenCode session queue；Codex [app](https://learn.chatgpt.com/docs/app)
  - 固定版本源码 `https://github.com/openai/codex/blob/6c0c6759d061/codex-rs/tui/src/slash_command.rs`（VIII-E，`/ide`）；Codex [IDE integrations](https://learn.chatgpt.com/docs/ide/commands)
  - Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（2026-09-11）
  - Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.410）
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### B-TC-03｜消息阅读与文件引用（8 条）

- **包含编号：** B013, B014, B046, B069, B084, B085, B092, B125
- **Atlas 拟修改文件/目录：** `components/ConversationMessage.tsx`；`shell/panels/FilesPanel.tsx`；`FilesPanel.tsx`；`ConversationMessage.tsx`；`message-actions/CodeBlock.tsx`；`components/Composer.tsx`；`MessageThread.tsx`；`ThreadPresentation.tsx`；`components/message-actions/ImagePreview.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/lib/markdownFileLink.ts`、`PreviewPane.tsx`；OpenCode session markdown；Codex [app](https://learn.chatgpt.com/docs/app)
  - ZCode `packages/ui/src/lib/markdownFileLink.ts`、`PreviewPane.tsx`；OpenCode `packages/session-ui`（无消息级 context menu）；Codex [app](https://learn.chatgpt.com/docs/app)
  - [artifacts viewer](https://learn.chatgpt.com/docs/artifacts-viewer)，[changelog](https://learn.chatgpt.com/docs/changelog) 2026-09-11
  - ZCode `packages/ui/src/v4/ConversationSelectionTooltip.tsx`、`WorkspaceFileTreeRowView.tsx`；OpenCode app/session 仅项目/会话行 context menu；Codex [app](https://learn.chatgpt.com/docs/app)
  - Claude [interactive mode](https://code.claude.com/docs/en/interactive-mode)、[releases v2.1.208](https://github.com/anthropics/claude-code/releases/tag/v2.1.208)；ZCode 固定 SHA 的 `packages/ui/src/i18n/locales/zh-CN.ts` 只证明有无障碍文案时单独标 U
  - ZCode 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts`（快捷键文案）及 `packages/shared/src/shortcutCommands.ts`；OpenCode 固定 SHA：`packages/app/src/runtime/i18n/en.ts`（Shortcuts 设置）和 `packages/ui/src/hooks/keyboard.ts`；Codex TUI 固定源 `codex-rs/tui/src/keymap.rs`（`6c0c6759d061`）；Claude [desktop](https://code.claude.com/docs/en/desktop)、[interactive mode](https://code.claude.com/docs/en/interactive-mode)
  - Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.429）
  - https://code.claude.com/docs/en/desktop#switch-view-modes；1.46388.1 之前版本另有 Summary
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### B-TC-04｜Changes：Diff、评注与审批（7 条）

- **包含编号：** B025, B055, B076, B093, B102, B103, B123
- **Atlas 拟修改文件/目录：** `shell/panels/ChangesPanel.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/PermissionDialog.tsx`、`WorkflowPermissionBlock.tsx`；Codex [approvals](https://learn.chatgpt.com/docs/permissions)；Claude [permission modes](https://code.claude.com/docs/en/permission-modes)
  - ZCode `packages/ui/src/components/ui/diff-viewer.tsx`；Codex [code review](https://learn.chatgpt.com/docs/code-review)；Claude [desktop](https://code.claude.com/docs/en/desktop)
  - 固定 SHA：`packages/session-ui/src/v2/components/session-review-v2.tsx`、`session-review-file-preview-v2.tsx`；文件模型 `packages/app/src/workspaces/files/model.tsx`
  - Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)；VI R12 [issue #48836](https://github.com/openai/codex/issues/48836) 是特定版本焦点/IME bug，不是功能缺失证据
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - https://learn.chatgpt.com/docs/sandboxing/auto-review
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### B-TC-05｜Composer：模型、附件与上下文（9 条）

- **包含编号：** B027, B028, B030, B031, B034, B036, B043, B049, B070
- **Atlas 拟修改文件/目录：** `Composer.tsx`；`DrawingPad.tsx`；`App.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/v4/composer/V4ComposerToolbar.tsx`、`ModelConfigSelect.tsx`、`ChatModeSwitchControl.tsx`、`ThoughtLevelCycleControl.tsx`；OpenCode composer; Codex [models](https://learn.chatgpt.com/docs/model-selection)；Claude [model config](https://code.claude.com/docs/en/model-config)
  - ZCode `packages/ui/src/v4/composer/{useComposerAttachments.ts,attachmentUpload.ts,conversationDropTarget.ts}`；OpenCode session composer；Codex [image inputs](https://learn.chatgpt.com/docs/app)；Claude [desktop](https://code.claude.com/docs/en/desktop)
  - ZCode `packages/ui/src/mentions/providers/{fileMentionProvider.ts,sessionsMentionProvider.ts}`；OpenCode composer suggestions；Codex [prompting](https://learn.chatgpt.com/docs/prompting)；Claude [interactive mode](https://code.claude.com/docs/en/interactive-mode)
  - ZCode 固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/mentions/providers/skillsMentionProvider.ts`、`packages/ui/src/mentions/mentionMarkdown.ts`；Codex [skills](https://learn.chatgpt.com/docs/build-skills)；Claude [skills](https://code.claude.com/docs/en/skills)
  - [model selection](https://learn.chatgpt.com/docs/model-selection)，2026-09-22/09-29/10-08 changelog
  - [model selection](https://learn.chatgpt.com/docs/model-selection)；ZCode `ModelConfigSelect.tsx`、`ThoughtLevelCycleControl.tsx`；Claude [model config](https://code.claude.com/docs/en/model-config)
  - Codex [reference settings](https://learn.chatgpt.com/docs/reference/settings)、[long-running work](https://learn.chatgpt.com/docs/long-running-work)；ZCode `ConversationQueuePanel.tsx`；Claude [desktop](https://code.claude.com/docs/en/desktop)
  - ZCode `packages/ui/src/prompt-editor/ChatPromptActionMenu.tsx`；OpenCode composer attachments
  - 固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/mentions/components/PluginMentionOptionContent.tsx`、`packages/ui/src/mentions/mentionMarkdown.ts`
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### B-TC-06｜Files：文件树、预览与编辑器（8 条）

- **包含编号：** B053, B082, B090, B104, B107, B108, B117, B129
- **Atlas 拟修改文件/目录：** `shell/panels/FilesPanel.tsx`；`FilesPanel.tsx`；`ChangesPanel.tsx`；`ConversationMessage.tsx`；`message-actions/CodeBlock.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/WorkspaceFileTree.tsx`、`workspace-file-tree/WorkspaceFileTreeRowView.tsx`；Codex [app](https://learn.chatgpt.com/docs/app)
  - ZCode 固定 SHA：`packages/ui/src/lib/markdownFileLink.ts`、`WorkspaceFileTreeRowView.tsx`；Claude [Desktop file context menu](https://code.claude.com/docs/en/desktop)；Codex [Desktop app](https://learn.chatgpt.com/docs/app)
  - Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.409）
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - 固定 SHA：`packages/ui/src/workspace-file-tree/gitStatus.ts`、`WorkspaceFileTree.tsx`
  - ZCode 固定 SHA：`packages/ui/src/workspace-file-tree/searchRows.ts`；OpenCode 固定 SHA：`packages/app/src/workspaces/files/model.tsx`、`packages/app/src/session/screen.tsx`
  - 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L1493-L1530`
  - 固定 SHA aac4755666d09fdcd70272fcf063c077a639015f：packages/ui/src/i18n/locales/zh-CN.ts#L1469-L1493（UI 字段线索，TSX 操作须另证）
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### B-TC-07｜Browser：预览验证与站点权限（7 条）

- **包含编号：** B060, B098, B099, B100, B101, B111, B112
- **Atlas 拟修改文件/目录：** `shell/panels/BrowserPanel.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/browser-use/{UnifiedBrowserView.tsx,BrowserViewportToolbar.tsx,EmbeddedBrowserPermissionPrompts.tsx}`；Codex [browser](https://learn.chatgpt.com/docs/app)；Claude [desktop](https://code.claude.com/docs/en/desktop)
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - ZCode 固定 SHA：`packages/ui/src/browser-use/EmbeddedBrowserPermissionPrompts.tsx`；Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - ZCode 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L965-L1000`（可见设备权限类别，组件/API 需逐项核验）；Claude [Desktop](https://code.claude.com/docs/en/desktop)
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### B-TC-08｜Git：PR、分支与历史（5 条）

- **包含编号：** B062, B091, B113, B114, B115
- **Atlas 拟修改文件/目录：** `shell/panels/PullRequestSection.tsx`；`shell/panels/ChangesPanel.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/{GitPane.tsx,GitPaneChangeCard.tsx}`；Codex [code review](https://learn.chatgpt.com/docs/code-review)
  - Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.409）
  - 固定 SHA：`packages/ui/src/GitActionMenu.tsx`；附录 VIII-A2 对应菜单项
  - 固定 SHA：`packages/ui/src/GitActionMenu.tsx`
  - 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L1417-L1443`（UI 文案线索）
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### B-TC-09｜Inspector：面板、Dashboard 与插件 UI（9 条）

- **包含编号：** B065, B066, B071, B094, B095, B096, B119, B120, B121
- **Atlas 拟修改文件/目录：** `shell/panels/SessionDashboardPanel.tsx`；`SessionDashboardPanel.tsx`；`workspace_router.py`；`shell/panels/FilesPanel.tsx`
- **要读的上游文件/文档：**
  - OpenClaw `docs/web/dashboards.md`、`docs/web/dashboard-architecture.md`（F1-B 原表“同上”）
  - OpenClaw `docs/web/dashboards.md`；ZCode `packages/ui/src/gen-ui/CONTRACT.md`；Goose [MCP UI](https://github.com/block/goose/blob/main/documentation/docs/guides/interactive-chat/mcp-ui.md)
  - 固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/onboarding/OnboardingModeSelector.tsx`
  - ZCode 固定 SHA：`packages/ui/src/app-shell/SidePaneTabOverview.tsx`、`lib/workspaceSidePane.ts`；Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.409）；Claude [desktop](https://code.claude.com/docs/en/desktop)
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - 固定 SHA：`packages/ui/src/gen-ui/components/GenUiMessageResponse.tsx`、`packages/ui/src/gen-ui/CONTRACT.md`
  - ZCode 固定 SHA：`packages/ui/src/plugin-ui/PluginUiSidePane.tsx`；Claude [MCP](https://code.claude.com/docs/en/mcp)
  - ZCode 固定 SHA：`packages/ui/src/app-shell/{SubagentSessionSidePane.tsx,SubagentDirectorySidePane.tsx}`；Codex [long-running tasks](https://learn.chatgpt.com/docs/long-running-work)；Claude [sub-agents](https://code.claude.com/docs/en/sub-agents)、[agent teams](https://code.claude.com/docs/en/agent-teams)、[Desktop feature comparison](https://code.claude.com/docs/en/desktop)
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### B-TC-10｜对话轨迹、后台任务与调试（8 条）

- **包含编号：** B073, B075, B116, B124, B126, B127, B133, B134
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - 固定 SHA：packages/ui/src/ModelTrajectoryExpansionMenu.tsx、packages/ui/src/i18n/locales/zh-CN.ts（VIII-M，调用来源和筛选文案）
  - 固定 SHA：packages/app/src/session/commands/use-session-commands.tsx、packages/app/src/session/screen.tsx；IX R101 是特定版本传输故障报告，不是能力证据
  - ZCode 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L4763-L4798`（诊断 UI 文案，需配组件）；Codex TUI 固定源 `codex-rs/tui/src/slash_command.rs`（`6c0c6759d061`）
  - OpenCode 固定 SHA：packages/session-ui/src/message/current-message.tsx、message-content.tsx；Codex TUI 固定源 codex-rs/tui/src/keymap.rs（6c0c6759d061）；Claude Desktop view modes 文档
  - https://code.claude.com/docs/en/desktop#keyboard-shortcuts
  - 固定 SHA：packages/app/src/session/screen.tsx、screen-layout.ts、runtime/extension/panels.tsx
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - ZCode `packages/ui/src/i18n/locales/zh-CN.ts`（V5 B133，文案线索，具体 TSX 待核）
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### C-TC-01｜设置来源、权限与 Worktree 策略（9 条）

- **包含编号：** C002, C003, C006, C048, C064, C069, C070, C073, C076
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - OpenCode `packages/app/src/settings/search-catalog.ts`; Codex [Settings](https://learn.chatgpt.com/docs/reference/settings)
  - ZCode `packages/shared/src/protocol.ts` (`AppSettings`); OpenCode `packages/app/src/settings/`; Claude [settings](https://code.claude.com/docs/en/settings), [managed settings](https://code.claude.com/docs/en/managed-settings), [server managed settings](https://code.claude.com/docs/en/server-managed-settings); Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference)
  - Claude [debug your config](https://code.claude.com/docs/en/debug-your-config); Codex [troubleshooting](https://learn.chatgpt.com/docs/reference/troubleshooting), [config reference](https://learn.chatgpt.com/docs/config-file/config-reference)
  - V5 §C 计划/审查与自动接受行；Claude [permissions](https://code.claude.com/docs/en/permissions)；Atlas `core/atlas/api/conversations_router.py`, `run_drive.py`
  - V5 §C 计划/审查权限、自动接受行；Claude [permissions](https://code.claude.com/docs/en/permissions)
  - V5 §C 工作区搜索规则行；ZCode `settings` 文案（U）
  - V5 §C Worktree 行；OpenCode V2 SDK/Plugin source
  - V5 §C 扩展 LSP / Web search / Experimental 行；Atlas `LspStatusSection.tsx`, `workspace_router.py`
  - V5 §C 本机运行设置行；Claude [monitoring usage](https://code.claude.com/docs/en/monitoring-usage)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### C-TC-02｜模型、Provider、用量与网络（5 条）

- **包含编号：** C010, C013, C008, C074, C100
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - ZCode `settings/model-provider-section/{ModelEditorAdvanced,ProviderModelMetadataDialog,ProviderModelModalityOptions,ProviderModelReasoningLevelEditor}.tsx`; OpenCode `providers/models/variant.tsx`; Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference); Claude [model configuration](https://code.claude.com/docs/en/model-config), [fast mode](https://code.claude.com/docs/en/fast-mode)
  - ZCode `settings/usage-stats/{AppUsagePanel,CodingPlanUsagePanel,UsageHeatmap}.tsx`; Codex [Settings](https://learn.chatgpt.com/docs/reference/settings), [changelog](https://learn.chatgpt.com/docs/changelog); Claude [costs](https://code.claude.com/docs/en/costs), [monitoring usage](https://code.claude.com/docs/en/monitoring-usage); OpenCode `settings/providers/`
  - OpenCode `settings/providers/{providers,connect,credentials}/`; Codex [auth](https://learn.chatgpt.com/docs/auth); Claude [authentication](https://code.claude.com/docs/en/authentication)
  - V5 §C 扩展 LSP / Web search / Experimental 行；Atlas `LspStatusSection.tsx`, `workspace_router.py`
  - [Z](https://github.com/zai-org/ZCode/blob/aac4755666d0/packages/ui/src/i18n/locales/zh-CN.ts) · [C](https://github.com/openai/codex/blob/6c0c6759d061/codex-rs/tui/src/slash_command.rs)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### C-TC-03｜Profile、历史导入与工作流（7 条）

- **包含编号：** C012, C036, C053, C054, C066, C071, C072
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Codex [auth](https://learn.chatgpt.com/docs/auth); Claude [authentication](https://code.claude.com/docs/en/authentication); ZCode `CodingPlanStatusActions.tsx`
  - ZCode `settings/{MigrationSection,ExternalAgentImportDialog}.tsx`; Codex [import](https://learn.chatgpt.com/docs/import); Claude [MCP](https://code.claude.com/docs/en/mcp)
  - Claude [env vars](https://code.claude.com/docs/en/env-vars); Codex [`rollout` recorder](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/recorder.rs), V5 §C 配置传输与附录 VI–IX；Atlas `core/atlas/runtime/external_import.py`, `core/atlas/api/external_history_router.py`
  - V5 §C 诊断/Computer Use 行、VIII-A；Atlas `frontend/src/main/electron.ts`, `diagnostics_router.py`
  - Goose [recipes](https://goose-docs.ai/docs/guides/recipes/); V5 §C 保存工作流行、Codex App 自动化行
  - V5 §C SSH 行；各家官方 Desktop/Remote Control docs
  - V5 §C Install CLI 行；Atlas `core/atlas/cli.py`
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### C-TC-04｜MCP、插件宿主、Hooks 与命令注册（10 条）

- **包含编号：** C016, C017, C019, C020, C022, C023, C027, C028, C031, C068
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - ZCode `McpFailurePresentation.tsx`; OpenCode `servers/connect/`; Claude [MCP](https://code.claude.com/docs/en/mcp), [managed MCP](https://code.claude.com/docs/en/managed-mcp); Codex [MCP](https://learn.chatgpt.com/docs/extend/mcp)
  - OpenCode `settings/providers/extensions.tsx`; Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference); Claude [MCP](https://code.claude.com/docs/en/mcp); ZCode `McpSettingsSection.tsx`
  - ZCode `PluginStoreSourcesDialog.tsx`, `AddMarketplaceSourceDialog.tsx`, `PluginConfigControls.tsx`; Claude [plugin marketplaces](https://code.claude.com/docs/en/plugins/marketplaces); Codex [plugin management](https://learn.chatgpt.com/docs/enterprise/plugin-management)
  - ZCode `PluginsSection.tsx`; OpenCode `settings/providers/extensions.tsx`; Codex [plugins](https://learn.chatgpt.com/docs/plugins); Claude [settings](https://code.claude.com/docs/en/settings)
  - OpenCode `runtime/extension/{settings-pages,menubar-items,commands,host-apis}.ts*`; ZCode `plugin-ui/CONTRACT.md`, `plugin-ui/app/`; Codex [plugins](https://learn.chatgpt.com/docs/plugins)
  - `packages/ui/src/plugin-ui/CONTRACT.md`, `pluginUiAppTools.ts`, `pluginUiHostAppHandlers.ts`, `pluginUiPageManager.ts`
  - ZCode `settings/{HooksSection,HookForm,HooksList}.tsx`; Codex [hooks](https://learn.chatgpt.com/docs/hooks); Claude [Hooks guide](https://code.claude.com/docs/en/hooks-guide), [reference](https://code.claude.com/docs/en/hooks); OpenCode `runtime/extension/`
  - ZCode `WorkspaceHookTrustNotice.tsx`, `workspaceHookReviewCommands.ts`; Claude [Hooks](https://code.claude.com/docs/en/hooks); Codex [hooks](https://learn.chatgpt.com/docs/hooks)
  - ZCode `packages/ui/src/command-center/CommandCenterDialog.tsx`; OpenCode `packages/app/src/shell/commands/{command,palette}.tsx`; Codex [commands](https://learn.chatgpt.com/docs/reference/commands)
  - V5 §C Computer Use 行及附录 VI/IX
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### C-TC-05｜Electron 桌面、无障碍与语音（6 条）

- **包含编号：** C033, C046, C079, C080, C081, C101
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Claude [accessibility](https://code.claude.com/docs/en/accessibility), [fullscreen](https://code.claude.com/docs/en/fullscreen), [voice dictation](https://code.claude.com/docs/en/voice-dictation); ZCode `settingsPageHelpers.tsx`
  - ZCode `packages/ui/src/i18n/locales/{en-US,zh-CN}.ts`; OpenCode `packages/app/src/runtime/i18n/`, `packages/ui/src/i18n/`
  - V5 §C Windows tray / prevent sleep 行
  - ZCode `packages/desktop/src/main/desktopApplicationMenu.ts`；Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - Codex 官方 Desktop 更新（F1-B.md 第 137 行）
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### C-TC-06｜渠道、Browser 和远程服务（6 条）

- **包含编号：** C040, C044, C067, C083, C084, C089
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - [Hermes messaging](https://github.com/NousResearch/hermes-agent/blob/66605471e9f0b0832abbefaf625ce08e948ca540/website/docs/user-guide/messaging/index.md), [OpenClaw channels](https://docs.openclaw.ai/channels), [Hermes cron delivery](https://github.com/NousResearch/hermes-agent/blob/66605471e9f0b0832abbefaf625ce08e948ca540/website/docs/user-guide/features/cron.md)
  - ZCode `packages/ui/src/feedback/{FeedbackCenter,FeedbackSubmitForm,TicketDetail}.tsx`; Codex [troubleshooting](https://learn.chatgpt.com/docs/reference/troubleshooting); Claude [feedback](https://code.claude.com/docs/en/commands)
  - V5 VIII-A BrowserSettingsSection（U）；ZCode settings 文案
  - OpenClaw `docs/concepts/main-session.md`
  - Hermes `website/docs/user-guide/bot-mode.md`
  - [H](https://code.claude.com/docs/en/desktop)
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### D-TC-01｜文件读写与本机进程接口（6 条）

- **包含编号：** D001, D002, D003, D011, D046, D127
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Claude [tools reference](https://code.claude.com/docs/en/tools-reference)；ZCode `apps/zcode-cli/packages/core/src/tool/handlers/read.ts`；OpenCode `packages/core/src/tool/plugin/read.ts`；Codex core handler index 未列独立 text Read handler
  - Claude tools reference；ZCode `handlers/write.ts`；OpenCode `plugin/write.ts`；Codex core handler index 未列独立 Write handler
  - Claude tools reference + [changelog](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)；ZCode `handlers/edit.ts`；OpenCode `plugin/edit.ts`；Codex 通过 `apply_patch`/shell 组合
  - Codex `handlers/exec_command.rs`, `write_stdin.rs`；Claude TaskOutput/TaskStop（TaskOutput 有文档弃用冲突）；ZCode `handlers/{bash,task_output,task_stop}.ts`；OpenCode `plugin/shell.ts`
  - `packages/core/src/tool/plugin/opencode.ts`
  - Claude [tools reference](https://code.claude.com/docs/en/tools-reference)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### D-TC-02｜Agent 委派、计划与任务生命周期（10 条）

- **包含编号：** D013, D014, D016, D017, D018, D042, D115, D118, D122, D125
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Claude EnterPlanMode/ExitPlanMode；ZCode 同名工具；Codex `update_plan.rs`
  - Claude AskUserQuestion；ZCode AskUserQuestion；OpenCode `plugin/question.ts`
  - Codex `handlers/multi_agent.rs`、TUI task tools；Claude Agent；ZCode Agent/Task；OpenCode `plugin/subagent.ts`
  - Codex multi-agent v1/v2 handlers；Claude SendMessage/Agent teams；ZCode SendMessage/RespondToCoordinator/submit_result/escalate/ReplyToChannel/TaskStop
  - ZCode `ReadSessionContext` handler；Codex `get_context_remaining` / `new_context`
  - Claude permissions docs；ZCode `packages/ui/src/PermissionDialog.tsx`, `lib/permissionRequest.ts`；OpenCode `packages/app/src/session/requests/`
  - ZCode `apps/zcode-cli/packages/core/src/tool/handlers/cron.ts`；Claude [tools reference](https://code.claude.com/docs/en/tools-reference)
  - Claude [tools reference](https://code.claude.com/docs/en/tools-reference)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### D-TC-03｜Web 检索、JS REPL、录制和事件流（5 条）

- **包含编号：** D021, D022, D113, D119, D123
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Codex `web_search` handler + [web search docs](https://learn.chatgpt.com/docs/web-search)；Claude WebSearch；ZCode `handlers/web-search.ts`；OpenCode `plugin/websearch.ts`
  - Claude WebFetch；ZCode `handlers/web-fetch.ts`；OpenCode `plugin/webfetch.ts`
  - [Record & Replay](https://learn.chatgpt.com/docs/extend/record-and-replay)
  - ZCode `apps/zcode-cli/packages/core/src/tool/handlers/node-repl.ts`
  - Claude [tools reference](https://code.claude.com/docs/en/tools-reference)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### D-TC-04｜Browser DOM、标签与 Computer Use（10 条）

- **包含编号：** D029, D030, D031, D033, D097, D098, D100, D101, D104, D112
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Codex [computer use docs](https://learn.chatgpt.com/docs/computer-use)；Claude [computer use](https://code.claude.com/docs/en/computer-use)；ZCode `packages/zcode-cua` / `packages/zcode-cua-plugin`
  - `packages/plugin-browser/src/rpc.ts`, `tools.ts`
  - `packages/plugin-browser/src/rpc.ts`
  - [`browser-use-plugin/docs/overview.md`](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/browser-use-plugin/docs/overview.md)
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`agent.browsers`, `browser.tabs`, `browser.user`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`playwright.domSnapshot`, `getBy*/locator`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`frameLocator/evaluate/waitForURL/waitForLoadState`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`tab.screenshot`, `setViewportSize`, `viewportSize`
  - [Computer Use 官方插件发布说明](https://help.openai.com/en/articles/11391654)；[computer use docs](https://learn.chatgpt.com/docs/computer-use)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### D-TC-05｜Browser 文件、录制及 pane 生命周期（5 条）

- **包含编号：** D032, D105, D106, D107, D108
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - `packages/plugin-browser/src/rpc.ts`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`tab.getJsDialog`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`markDeliverable`, `markHandoff`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`tab.recording.{start,status,cancel}`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`browser.capabilities.get("visibility").set`, `--browser-use=headless`
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### D-TC-06｜MCP、技能工具与 Tool Registry（6 条）

- **包含编号：** D035, D038, D039, D040, D043, D129
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - [Codex MCP docs](https://learn.chatgpt.com/docs/extend/mcp)；OpenCode `packages/core/src/tool/plugin/mcp-resource.ts`；Claude MCP docs
  - Claude ToolSearch；Codex `tool_search`/plugin extension registry；ZCode `registry.ts`
  - Claude Skill/Mods；Codex plugins docs；ZCode `registry.ts`, `packages/core/src/tool/handlers/skill.ts`, `UI_PLUGIN.md`；OpenCode `plugin/skill.ts`
  - Codex `list_plugins`, `request_plugin_install` tool handlers；[plugins docs](https://learn.chatgpt.com/docs/plugins)
  - Codex `codex-rs/core/src/tools/registry.rs`; ZCode `packages/core/src/tool/registry.ts`; OpenCode `packages/core/src/plugin/internal.ts`; Claude tools reference
  - Claude [tools reference](https://code.claude.com/docs/en/tools-reference)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

### D-TC-07｜Workflow、Provider、应用与 Git 执行（6 条）

- **包含编号：** D044, D047, D048, D049, D052, D053
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Claude Workflow；ZCode workflow tools；OpenCode CodeMode `packages/core/src/codemode`
  - `packages/core/src/tool/plugin/opencode.ts`
  - `crates/goose/src/agents/platform_extensions/apps.rs`
  - `crates/goose-mcp/src/autovisualiser/mod.rs`
  - Codex `codex exec` / app-server 官方文档；Claude Code `claude -p` CLI 文档；[ACP v1 session setup](https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/session-setup.mdx)；Codex app-server 文档
  - GitHub CLI `gh pr create` / `gh pr comment` 官方文档；Atlas `api/workspace_router.py` 现有 PR 创建 API
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。

## 四、P2 排队清单（不切卡）

**A 区：**无。

**B 区：**B042 Codex `/local`、`/cloud`、`/cloud-environment` 执行位置选择、B072 按场景主动推荐任务（V5 B100）、B135 系统资源监视展示、B136 OpenCode 触屏适配、B137 Codex TUI Vim 模式、B138 Codex TUI 宠物、B139 Codex Security 扫描工作台。

**C 区：**C005 系统与运行环境偏好（代理、证书、shell、终端、休眠、托盘、硬件加速）、C021 插件远端同步、服务器/桌面端安装情况、C025 Skills User/Workspace/Plugin scope、frontmatter、按 Agent 权限和远端同步、C038 远程控制会话、设备配对、远端状态/同步和 QR 会话、C055 更新通道（stable/beta/nightly）、C060 云任务与外部集成入口、C065 Off-peak 低峰任务、C075 实验功能开关、C077 数据库目录迁移、C078 模型 I/O 完整保留策略、C082 会话公开分享服务与访问控制、C085 Claude 手机 Dispatch 开发任务、C086 Claude Cloud Projects 持续任务、C087 OpenCode Web pair 设备授权、C088 状态栏/标题栏自定义、C090 Claude Connectors 统一管理、C091 Claude Mods 自定义交互面、C092 OpenCode V2 cli.json 配置兼容、C093 OpenCode V2 CLI 本地插件加载、C094 OpenCode V1→V2 插件迁移、C095 Codex Sites 托管网页项目、C096 Codex Chronicle 屏幕上下文记忆、C097 Codex Micro 外设映射与状态、C098 Codex Daybreak 模式、C099 Codex 调试沙箱设置。

**D 区：**D056 Android 创建应用、D082 iOS 创建应用、D110 ZCode image-search 插件、D111 ZCode documents/pdf/presentations/spreadsheets 插件 skills、D114 Codex Security plugin scan、D116 离峰任务管理、D117 远程 Routine 触发、D120 回复外部频道、D121 托管 Artifact 发布、D124 推送通知、D126 用户反馈草稿、D128 分享入门指南。

## 五、来源追踪与执行纪律

1. 每个源功能保留 `F1-A/B/C/D.md` 行号或 V5 矩阵章节/附录标记，参看伴随的 `Atlas-功能状态索引.csv`；已做/原有在 CSV 里可查询，不在正文重复列。
2. 每卡执行前阅读对应上游源码/文档及 Atlas 本地实际文件，先复核主分支是否已经合并这些 F1 分支产物；**材料列为已做不代表 main 已合并**。若实现已存在则在结果中标记“免施工”。
3. 官方闭源 GUI 只提供文档，不能下发“复制其内部源码”任务；开源源码移植按各 F1 文件所述固定 SHA/许可证保留来源与 THIRD_PARTY_NOTICES 归属。
4. 施工时只补真实运行链路；不要只加按钮、空命令、假状态。平台/套餐专属能力受条件限制，优先以 P2 作为待评估而非立即上马。
5. 每卡提交一次结果：实现文件、上游依据、所接 API/事件、仍有缺口、Git 提交、可复核路径。不要用功能请求或界面文案推断产品真实执行能力。

---
**阅读分段顺序：** 第一节统计 → 第二节 A、B、C、D 剩余 → 第三节 P0/P1 任务卡 → 第四节 P2。