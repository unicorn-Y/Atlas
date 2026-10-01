# ATLAS-W07-ORCHESTRATION（第七波：子 Agent 与编排）

STATUS: READY（W06 交付后开始）
PROTOCOL: 1.8 → 1.9
先读：`docs/plan/00-MASTER-PLAN.md`、`docs/plan/SOURCE-MAP.md` C 节、`docs/plan/EXECUTION-GUIDE.md`、H `tools/AGENTS.md` 的「Delegation」一节
主要来源：H（Hermes Agent）；子 Agent 定义格式参考 OpenHands、Codex、OpenCode、Claude Code、Copilot 的官方文档

## 本波目标

Atlas 现在的 `delegate_task` / `delegate_parallel` 能用但很基础（第五波）。把 Hermes 成熟的委派体系搬过来，再加上别家的强项：多格式的子 Agent 定义文件、内置类型、并行验收、看板、多模型会诊。

---

## 1. 委派内核（后端，从 H 搬）

**来源**：
- H `tools/delegate_tool.py`（751 行）+ 兄弟文件 `delegate_tool_config.py`、`_dispatch.py`、`_child_run.py`、`_progress.py`、`_results.py`、`_tasks.py`、`_toolsets.py`、`_registry.py`（合计约 3600 行）
- H `tools/async_delegation.py`（1211 行）：后台委派登记处
- H `tools/subagent_worktree.py`（195 行）：子 Agent 的 git worktree 隔离
- H `agent/subagent_lifecycle.py`（416 行）、`agent/delegation_context.py`、`tools/delegation_output_schema.py`、`tools/delegation_live_log.py`
- 说明：H `tools/AGENTS.md` 的 Delegation 一节（必读）

**H 已有、要原样搬到的行为**：
- 子 Agent：全新对话、自己的任务 ID、父工具集减去禁用工具、由目标和上下文生成专用系统提示；父 Agent 只看到委派调用和摘要结果，看不到子 Agent 的中间过程。
- 单个和批量（并行）两种模式；并发上限 `delegation.max_concurrent_children`（默认 3，Atlas 现在是 8，保留可配置）。
- **后台委派** `background=true`：立即返回委派 ID；完成后结果作为**新的一轮**回到对话（不在一轮中间插入）。批量后台任务默认合成一次汇报；`group` 相同的任务一起汇报。
- **两种角色**：`leaf`（不能再委派，也不能用提问、记忆、发消息、定时任务）和 `orchestrator`（可以再委派，受 `delegation.max_spawn_depth` 限制，默认 2）。
- **结构化输出** `output_schema`：不合格重试一次；仍不合格保留原文，标 `schema_valid: false`，**不丢弃结果**。
- worktree 隔离：每个子 Agent 在 `<仓库>/.worktrees/subagent-<id>`、分支 `atlas-subagent/<id>`；只有确认没有提交且干净才清理，否则保留并标记。Atlas 现在已经有 Worker 用独立 worktree，对照 H 的清理规则补强。
- 子 Agent 留下的后台进程、未读完成通知要记账并清理。

**做法**：
1. 对照 Atlas 现有实现（`agent/__init__.py` 里的 `_run_atlas_subtask`、`run(worker=True)`，`agent/orchestrator.py`），用 H 的结构重写委派：拷 H 的调度、进度、结果、工具集计算、后台登记处、worktree，接到 Atlas 的运行和事件上。
2. **保留第五波的教训**：子 Agent 用 `run(worker=True)`（不注入用户记忆、不学习），目标直接作为用户消息交给模型。
3. 事件：沿用 `subtask.started / progress / output / completed / group_completed`；`subtask.started.data` 增加 `agent`（类型）、`role`（leaf / orchestrator）、`background`、`model`、`recipe_id?`、`depth`；后台任务完成时发 `subtask.background_completed {subtask_id, summary}`，并在下一轮把结果交给主 Agent。
4. **运行中引导**：H 是否有给运行中的子 Agent 发消息的接口（`delegate_tool_progress.py`、`delegation_live_log.py`）——有就搬，没有就自己加：工具 `subtask_message {subtask_id, text}`；WS 客户端消息 `{type: "subtask.message", run_id, subtask_id, text}`；子 Agent 下一轮开始时作为用户消息插入；事件 `subtask.steered {subtask_id, text}`。
5. 工具 `subtask_status {subtask_id}`：状态、最近进度、完成后的结果。
6. 子 Agent 的工具调用照常过 W06 的智能审批。

**测试**：搬 H `tests/tools/` 下 delegate、async_delegation、subagent_worktree 的测试，改成 Atlas 接口。

## 2. 子 Agent 定义文件和内置类型（后端，按各家格式写解析器）

H 没有「从文件定义子 Agent 类型」这一层，这一节参考别家：

- **主格式**：Claude Code 风格 Markdown（YAML frontmatter + 正文作为系统提示）。字段取 OpenHands 子 Agent 定义的超集：`name`（必填，`[a-z0-9-]`）、`description`（必填）、`tools`（列表或逗号分隔；缺省为全部）、`model`（`inherit` / `fast` / `strong` / 具体模型 ID）、`role`（`leaf` / `orchestrator`，默认 `leaf`）、`permission_mode`（只能比父 run 更严）、`skills`、`mcp`（只给这个 Agent 的 MCP 服务器名）、`max_turns`、`output_schema`。未知字段忽略，写进 `warnings`。
- **读取位置**（后者同名覆盖前者）：内置 → 数据目录 `agents/` → 工作目录 `.atlas/agents/*.md`。
- **导入别家格式**：Claude Code `.claude/agents/*.md`；OpenCode `.opencode/agent/*.md`、`.opencode/agents/*.md`（`tools` 是 `{名字: bool}`，`mode: primary` 的跳过）；Codex `~/.codex/agents/*.toml`、`.codex/agents/*.toml`；Copilot `.github/agents/*.agent.md`、`~/.copilot/agents/*.agent.md`。**动手前先查各家当前官方文档确认字段**，结果文件里列出映射表。
- 工作目录里的定义属于规则文件，走第三波的信任流程。
- **内置 6 种类型**：

| 类型 | 做什么 | 工具 | 模型 | 角色 |
| --- | --- | --- | --- | --- |
| `explore` | 快速调查代码或资料，回结论和证据位置 | 只读（文件读 / 列 / 搜、git 读） | `fast` | leaf |
| `researcher` | 网上调研，回带出处的结论 | 只读 + 网页提取 + 搜索 | 父 run | leaf |
| `plan` | 给实施方案，不动手 | 只读 | 父 run | leaf |
| `oracle` | 深度分析：难 bug、架构取舍、审方案 | 只读 | `strong` | leaf |
| `verifier` | 对照成功标准验收：跑测试、看 diff，回「通过 / 不通过 + 原因」 | 只读 + 运行命令 | 父 run | leaf |
| `general` | 通用 | 全部（受父权限约束） | 父 run | leaf（`orchestrator` 需要显式指定） |

- 配置 `agents.fast_model`、`agents.strong_model`（W06 已加 `fast_model`）。
- `delegate_task` / `delegate_parallel` 加参数 `agent`（默认 `general`）；工具描述里列出可用类型（最多 20 个）；未知类型回退 `general` 并注明。
- **协调规则**写进委派工具说明和主系统提示：只有互不依赖、以阅读调查为主的任务才并行；改同一批文件、或后一步依赖前一步的，串行或自己做；一两次工具调用能完成的不要委派。
- `GET /api/agents/types?root=` → `{types: [{name, description, tools, model, role, source: "builtin"|"user"|"workspace"|"claude"|"opencode"|"codex"|"copilot", path?, trusted, warnings}]}`。

## 3. 并行验收（后端，自己写，参考 Factory Missions、Hermes 看板的验证者）

- `delegate_parallel` 加可选 `verify: {criteria}`：全部完成后派一个 `verifier` 对照标准检查每一项；不通过的带着意见**自动重派一次**（只一次）。`subtask.group_completed` 每项加 `verified`、`verifier_note`。

## 4. 配方当子 Agent（后端，参考 goose 子配方）

- `delegate_task` 可以传 `recipe: {id, params}` 代替 `goal`，按 Atlas 已有配方的提示词和参数执行；并行时每项也可以是配方。

## 5. 看板与待办（后端，从 H 搬）

**来源**：H `tools/todo_tool.py`（323 行）；H `tools/kanban_tools.py`（1222 行）、`tools/kanban_tools_schemas.py`、`hermes_cli/kanban*.py`（14 个兄弟文件，数据库和调度）、`gateway/kanban_watchers*.py`、`plugins/kanban/`。

**做法**：
1. **待办工具**：搬 `todo_tool.py`：每个 run 一份带版本号的待办清单，压缩后重新注入，不改系统提示。事件 `run.todos {revision, todos: [{id, text, status}]}`。Atlas 现有的「计划」（`run.plan.updated`）如果和它重复，以 H 的为准合并。
2. **看板（多 Agent 团队）**：Atlas 已经有看板页（显示会话和运行）。搬 H 的看板数据模型和工具：任务卡（标题、说明、负责的 Agent、依赖、状态、产出）、协调者拆任务上看板、Worker 认领执行、指派验证者。数据存 Atlas 数据库（新表，参考 H 的 `kanban.db` 结构）。接口 `GET/POST/PATCH /api/kanban/boards/...`（按 H 的操作集合定义，写进结果文件）。
3. 看板任务的执行走第 1 节的委派内核。

**测试**：搬 H 对应测试。

## 6. 多模型会诊（后端，从 H 搬）

**来源**：H `agent/moa_loop.py`（1492 行）、`moa_alternation.py`、`moa_trace.py`。H 的做法：某一轮标记为会诊后，正常循环照常调用工具和结束，但每次调用主模型之前，先让几个参考模型各自给出意见，作为上下文交给主模型。

**做法**：搬过来；配置 `moa.reference_models: [...]`、`moa.max_references`；用户在输入框里选「会诊」或输入 `/moa` 触发这一轮。事件 `moa.references {models, latency_ms}`。

## 7. 项目记事本（后端，自己写，参考 Cursor Projects 的共享上下文、OpenClaw 的 `MEMORY.md` 分层）

- 工作目录下 `.atlas/NOTES.md`。新工具 `project_note {section, text}`：往小节（构建与测试、代码约定、用户偏好、踩过的坑，或自定义）追加一条带日期的记录。主 Agent 和 `general` / `verifier` 可用。
- 运行开始时，记事本存在且目录已信任就随规则文件一起加载（第三波信任流程）；超过 8 KB 只加载每节最近 20 条。
- 系统提示补一句：发现以后每次都用得上的东西（怎么跑测试、构建命令、用户纠正过的偏好）用 `project_note` 记下；一次性信息不要记。
- `GET/PUT /api/workspace/notes?root=`。

## 8. 前端

1. **子任务**：步骤行显示类型徽标（探索 / 调研 / 规划 / 深度分析 / 验收 / 通用 / 协调者）、模型、后台标记、配方名、嵌套层级（缩进）；运行中的子任务下面有「给这个子任务补充要求」输入框（发 `subtask.message`），收到 `subtask.steered` 显示「你补充了：…」；后台任务完成时在对话里显示一张结果卡片。
2. **Worker 组**：每项显示「已验收 ✓ / 未通过 ✗」和验收意见；结构化输出不合格时显示提示。
3. **待办**：`run.todos` 在运行头部或检查器里显示待办清单（勾选状态实时更新，按 `revision` 丢弃旧更新）。H `apps/desktop` 里有对应组件可以参考。
4. **看板**：现有看板页加「任务看板」视图：列（待办 / 进行中 / 待验收 / 完成）、卡片（负责的 Agent、依赖、产出链接）、拖动改状态、点卡片看对应的运行。参考 H `plugins/kanban/dashboard` 和 `apps/desktop` 的看板界面。
5. **会诊**：输入框「更多」菜单里加「多模型会诊」开关；`moa.references` 在时间线上显示「参考了 3 个模型的意见」，可展开看各模型说了什么。
6. **设置 → 子 Agent**：类型列表（来源、模型、角色、工具、警告），快 / 强模型选择，并发上限、嵌套深度、会诊参考模型。
7. **项目记事本**：文件面板或检查器里的「项目记事本」入口，可查看和编辑。

## 9. 验收

| 项 | 最强的是 | Atlas 要做到 |
| --- | --- | --- |
| 委派 | Hermes（后台、角色、结构化输出、worktree）、Cursor（子 Agent 在虚拟机里） | H 的行为全部搬到；**额外**：界面上能给运行中的子任务发话，能看嵌套关系 |
| 子 Agent 定义 | Claude Code、OpenCode、Codex、Copilot、OpenHands 各一种格式 | 五家格式都能读 |
| 并行验收 | Factory Missions、Hermes 看板的验证者 | 自动验收 + 不通过重派一次 |
| 看板 | Hermes、Claude Code Agent Teams | 协调者拆任务、Worker 认领、验证者把关，界面可视化 |
| 会诊 | Hermes MoA、Perplexity 多模型 | 一轮内多个模型参考，界面可展开 |
| 项目记事本 | Cursor Projects | 下一次任务自动用上 |

**真机**（都要跑并记录）：
1. `explore` + `researcher` 并行调查一个小问题。
2. 带 `verify` 的并行组，故意让一项做不到，看验收和重派。
3. 后台委派一个任务，期间主 Agent 继续回答别的问题，结果作为新的一轮回来；中途用界面给子任务补充要求。
4. 读一个含 `.claude/agents/reviewer.md` 的项目，让 Atlas 用这个 reviewer 审查改动。
5. 新项目里让 Atlas「跑一下测试」，确认测试命令进了 `NOTES.md`，下一个新对话直接说「跑测试」能用上。
6. 一个三步任务用看板模式跑完。

## 10. 交付

同 W06：每节一个提交、`VENDORED.md` 登记、结果文件 `tasks/results/ATLAS-W07-ORCHESTRATION.result.md`、审查记录 `tasks/reviews/ATLAS-W07-ORCHESTRATION.review.md`。
