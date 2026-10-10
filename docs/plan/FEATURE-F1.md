# Atlas 功能对标 FEATURE-F1 计划书（2026-10-11，4 个 Codex 聊天并行，一次做完）

> 引擎（ENGINE-V1~V3）已做完。本批补「界面功能 + 工具」：把一流 Agent 产品的**所有**功能扒干净，Atlas 没有的全部照源码/行为做出来。
> 用户原话：「我都不知道有哪些功能和东西，不能只靠我来发现，你得自己去扒干净」。**功能清单必须由你们自己穷举，不能只做计划书里举的例子。**
> 用户要求：一次做完；**不写测试、不跑测试套件**。

## 0. 共同铁律

1. **对标对象（全部要扒）**：
   - **ZCode 桌面端**（开源，Apache-2.0，`zai-org/ZCode` 最新 HEAD）：`packages/ui`（约 1800 个源文件）、`packages/desktop`、`packages/client`、`packages/web`、`packages/share-ui`、`docs/`、`specs/`、`DESIGN.md`、`UI_PLUGIN.md`。**和 Atlas 同为 Electron + React，界面照源码移植。**
   - **OpenCode 桌面/网页端**（开源，MIT，`anomalyco/opencode` 最新 HEAD）：`packages/app`、`packages/desktop`、`packages/session-ui`、`packages/ui`、`packages/web`、`packages/tui`（看功能点）。
   - **Codex**（`openai/codex` 最新 HEAD 开源 CLI/TUI：`codex-rs/tui`、`codex-rs/core/src/tools`；桌面端闭源，看 https://developers.openai.com/codex 文档、changelog、发行说明）。
   - **Claude Code**（闭源：https://code.claude.com/docs 全部文档，含 desktop、commands、settings、hooks、checkpointing、subagents、mcp、plugins；`anthropics/claude-code` 的 CHANGELOG）。
   - 补充看：Hermes、OpenClaw、Pi、Cline、Goose 的功能列表（只在它们有而上面四家没有时纳入）。
2. **穷举方法（至少都做）**：
   - 遍历开源项目的**路由/页面、菜单与右键菜单、命令面板命令、快捷键表、设置项定义、i18n/文案文件（中英文案几乎覆盖全部用户可见功能）、工具注册表**；
   - 闭源产品逐页读官方文档和近 3 个月 changelog；
   - 每个功能记一行：功能 / 哪家有 / 源码路径或文档链接 / Atlas 现状（有、部分、无）/ 本次处理。
   - 清单写 `docs/parity/F1-<区域>.md`。不属于本区域的功能写进 `docs/parity/F1-unassigned.md`（只追加），留给下一批。
3. **实现**：清单里 Atlas「无/部分」的**全部做完**。开源的照源码移植（React 组件、交互、状态逻辑），闭源的照文档行为重做；样式用 Atlas 现有设计系统（Tailwind 变量、`ui/` 组件、三套主题）。移植文件写来源头：`// Ported from zai-org/ZCode@<sha>: <path> (Apache-2.0)`；`THIRD_PARTY_NOTICES.md` 只追加。
4. **工作树**：每个聊天各自建：`git -C D:\Atlas fetch origin` → `git -C D:\Atlas worktree add D:\atlas-f1-<区域字母> -b f1-<区域字母> origin/memory-v1`。**不要改 `D:\Atlas`**（用户在用），不碰别人的工作树。
5. **文件归属**（避免四个聊天冲突）：只改自己区域的文件；**共享文件**（`App.tsx`、`store/useAtlasStore.ts`、`core/atlas/server.py`、`core/atlas/api/application.py`、`services/` 下别人的文件、`config/atlas.example.toml`）只做**追加式小改动**（加一个 import、一个路由注册、一个 store 字段），不重排、不改别人的代码。新功能尽量放新文件。
6. **不写测试、不跑测试套件。** 只确认：后端能启动（验证用的后端设 `ATLAS_UPSTREAM_AUTO=0`）、`npm --prefix frontend run build` 通过、在界面里过一遍本区域新增功能能打开不报错。
7. 提交到自己的分支并 `git push origin f1-<区域字母>`；**不要推 memory-v1**。结果写 `tasks/results/FEATURE-F1-<区域字母>.result.md`：清单文件位置、做了哪些、有意没做的及原因、最终 SHA。

## 1. 四个区域

### A. 会话与侧栏（`f1-a`）
负责：会话/任务列表与侧栏的一切。例：**右键菜单**（重命名、置顶、归档、删除、分叉、导出、复制 ID/链接、在资源管理器打开工作区、标记未读、移动分组……）、**会话信息面板**（模型、工作区、分支、token/费用、创建时间、子 agent、改动文件……）、按工作区/项目分组、拖拽排序、搜索与筛选、批量操作、运行中状态指示、未读与通知徽标、草稿会话、最近/置顶区。以 ZCode 为主：`packages/ui/src/workspace-grouped-tasks/`、`TaskListItem*.tsx`、`TaskActionMenuContent.tsx`、`useTaskListItemContextActions.ts`、`v4/` 下 sidebar/task 相关、`app-shell/`。
文件：`frontend/src/renderer/shell/Sidebar.tsx`、新建 `frontend/src/renderer/components/sidebar/`、`core/atlas/api/conversations_router.py`、`core/atlas/api/projects_router.py`。

### B. 对话界面（`f1-b`）
负责：对话主区的一切。例：工具调用卡片（每种工具专门的展示）、文件改动 diff 视图与逐块接受/拒绝、审批交互、输入框工具栏（模型/强度/模式切换、附件、语音）、@ 文件/符号/会话引用、/ 命令、计划与待办展示、子 agent / workflow 进度、消息操作（复制、重试、编辑重发、从此分叉、回退到此）、长对话导航、引用与跳转、代码块操作、图片/文件预览、右侧面板（文件树、改动、终端、浏览器、Git 审查/PR）。以 ZCode `packages/ui/src/ToolCallBlocks/`、`chat-input-toolbar/`、`mentions/`、`workspace-file-tree/`、`gen-ui/`、`browser-use/`、git review 相关；OpenCode `session-ui`。
文件：`frontend/src/renderer/components/`（除 `sidebar/`、`settings/`）、`frontend/src/renderer/shell/Inspector.tsx`、`shell/HomeView.tsx`、`shell/panels/`、`core/atlas/api/workspace_router.py`、`runtime_ws_router.py`（只追加事件字段）。

### C. 设置与扩展（`f1-c`）
负责：设置、模型/服务商、MCP、插件、技能、钩子、快捷键、主题/外观、通知、新手引导、账号/用量、远程控制/多设备、导入导出配置、诊断。以 ZCode `packages/ui/src/settings/`、`plugin-ui/`、`onboarding/`、`feedback/`；Claude Code settings/hooks/plugins/mcp 文档；Codex 设置文档。
文件：`frontend/src/renderer/pages/`（除 Evolution 相关）、`frontend/src/renderer/components/settings/`（新建）、`core/atlas/api/models_settings_router.py`、`plugins_router.py`、`skills_router.py`、`skills_market_router.py`、`integrations_router.py`、`device_router.py`、`usage_router.py`。

### D. 工具（后端为主，`f1-d`）
负责：模型可调用的工具全集。把 Codex（`codex-rs/core/src/tools/handlers/` 全部）、Claude Code（文档里的全部内置工具：Read/Write/Edit/MultiEdit/Glob/Grep/Bash/BashOutput/KillShell/WebSearch/WebFetch/TodoWrite/NotebookEdit/Task/ExitPlanMode/AskUserQuestion/Skill/MCP 资源……以最新文档为准）、ZCode（`apps/zcode-cli/packages/core/src/tool/` 全部、`packages/zcode-cua`）、OpenCode（`packages/opencode/src/tool/` 全部）的工具逐个列出，对照 Atlas（`core/atlas/tools/`、`engine/tool_registry.py`、`kernel/tools.py`、Hermes 工具），缺的补、弱的按最强那家重做参数与行为。工具要在新内核（`kernel/tools.py`）注册；前端展示走 B 的通用卡片，D 不改前端。
文件：`core/atlas/tools/`、`core/atlas/engine/tool_registry.py`、`core/atlas/kernel/tools.py`、`core/atlas/api/tools_router.py`、`browser_router.py`、`computer_router.py`。

## 2. 合并

四个分支由 Claude 依次合并、处理共享文件冲突，在测试环境启动确认后，问用户再推 memory-v1。
