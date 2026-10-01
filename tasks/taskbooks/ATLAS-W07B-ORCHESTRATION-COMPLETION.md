# ATLAS-W07B-ORCHESTRATION-COMPLETION（第七波补做 + 第六、七波前端）

> **作废（2026-10-01）**：内核换成 Hermes（见 `docs/plan/00-MASTER-PLAN.md`）。本书内容分到：并行验收修正 → C3；子任务输出合并、多模型会诊后端 → C1；看板调度器 → 冻结；编辑已有模型 → C5；前端（第三节）→ C3。第一节的审查发现仍可参考。

STATUS: READY
执行：Luna（后端 + 前端都做）。审查：Sol（按 `docs/plan/EXECUTION-GUIDE.md` 第五节）。
先读：`docs/plan/00-MASTER-PLAN.md`、`docs/plan/EXECUTION-GUIDE.md`、`tasks/taskbooks/ATLAS-W07-ORCHESTRATION.md`、`tasks/results/ATLAS-W07-ORCHESTRATION.result.md`、本文件第一节（第七波审查发现）。
来源：Hermes Agent（`NousResearch/hermes-agent`，用最新提交，记下提交号）。

## 一、第七波审查发现（Claude，2026-10-01，审查到一半转交）

- 笔记本全量：`948 passed, 1 failed, 9 skipped`。失败的 `test_server.py::TestBackendParityWave1::test_process_endpoints_read_output_kill_and_404` 单独跑通过，是对时机敏感的旧测试，与第七波无关（顺手把它改稳：轮询等待输出出现，而不是固定读一次）。
- 真机（隔离 `ATLAS_DATA_DIR`、无 MCP、DeepSeek）：
  - ✅ explore + plan 两种类型并行，类型 / 角色 / 模型字段正确，未改文件。
  - ✅ 验收会触发、只重派一次。
  - ❌ **验收误判**：整组共用一个 `verify.criteria`，验收任务 A 时把针对任务 B 的条款也算进去，**合格的 A 被判不通过并重派**（真机复现：A 列出 3 个函数完全正确，仍被重派）。
  - ❌ 汇总在验收之前生成，最终汇总反映的是验收 / 重派前的结果。
  - ❌ 各项验收串行执行，组越大越慢。
  - ⚠️ `subtask.output` 按模型输出的每个 token 发一个事件，事件数量巨大；前端现在每个片段后加换行，显示会变成一字一行。
  - ❌ 看板只有存储（`core/atlas/kanban.py` 132 行），**没有调度器**，靠模型手动逐卡派活，Codex 的看板真机场景两次失败，原因就在这。
- 搬代码完整度：Hermes 委派 / 看板 / 会诊的核心模块没有搬（Codex 结果文件已如实说明）。编排模块与 Hermes 的 Agent 主类耦合重，**逻辑移植是可以接受的**，但行为要对齐 Hermes。

## 二、后端补做

### 1. 并行验收修正（`core/atlas/agent/enrichment.py` 的 `delegate_parallel` 验收段）
- 验收提示改为：整组共用标准时，**只判断与本任务目标相关的条款**，针对其他任务的条款不影响结论；`note` 用中文写理由。
- `delegate_parallel` 每项新增可选 `verify_criteria`（只针对该项，优先于整组 `verify.criteria`），工具参数定义同步加上。
- 各项「验收 → 不通过则重派一次 → 复验」用 `asyncio.gather` 并行。
- 重派后的项加 `retried: true`；复验也要带 `on_started / on_progress / on_completed` 回调（现在复验没有事件）。
- **汇总移到验收和重派之后**，没有自定义汇总时在每项后面写「（验收：通过 / 未通过）」。
- 笔记本上有一份未测试的参考实现：`git stash list` 里的「W07 review: per-task verify fix」（只在 Claude 的笔记本上，Luna 照上面的描述自己实现即可）。
- 测试：组标准同时包含 A、B 两条时，A 合格不重派、B 不合格重派一次；`verify_criteria` 覆盖整组标准；汇总包含验收结论。

### 2. 子任务输出合并
- `subtask.output` 改为**按行或每 0.5 秒合并一次**再发（不要每个 token 一个事件）；`subtask.progress` 保持原样。

### 3. 看板调度器（从 Hermes 逻辑移植）
来源：H `cron/AGENTS.md` 的「Kanban」一节（必读）、`hermes_cli/kanban_db*.py`（尤其 `kanban_db_dispatch.py`、`kanban_db_graph.py`）、`gateway/kanban_watchers_dispatcher.py`、`tools/kanban_tools.py`、`hermes_cli/kanban_decompose.py`、`hermes_cli/kanban_swarm.py`。

要对齐的行为：
- **调度器**：后端常驻循环（默认 60 秒，可配置；启动时跑一次）：回收卡住的认领（Worker 进程不在了或超时）、把依赖全部完成的卡片从 `todo` 提升为 `ready`、原子认领、按卡片的 `assignee`（子 Agent 类型或角色）启动 Worker（走第七波的委派内核，后台模式）。
- **失败上限**：同一卡片连续失败 `kanban.failure_limit` 次（默认 2）自动 `blocked`，写明原因，防止死循环。
- **Worker 工具**（只在 Worker 执行看板卡片时提供，平时不占工具位）：`kanban_show`、`kanban_complete`、`kanban_request_review`、`kanban_request_changes`、`kanban_block`、`kanban_comment`、`kanban_create`（建子卡片）、`kanban_link`（加依赖）、`kanban_heartbeat`。
- **审查环节**：卡片 `review` 状态时调度器派 `verifier` 类型检查，通过 → `done`，不通过 → 带意见回到 `ready`（计入失败次数）。
- **拆解**：协调者工具 `kanban_decompose {board_id, goal}`：让模型把目标拆成带依赖的卡片（参考 `kanban_decompose.py` 的提示和数据结构）。
- **隔离**：看板是硬边界，Worker 只能看到和改自己所在看板。
- 状态集合：`todo / ready / running / review / blocked / done`（与现有 `kanban.py` 对齐并迁移旧数据）。
- 事件：`kanban.updated {board_id, task_id, status, assignee, note?}`，供前端实时刷新。
- 接口：在现有 `/api/kanban/...` 上补 `POST /api/kanban/boards/{id}/dispatch`（立即跑一轮）、`POST /api/kanban/tasks/{id}/unblock`、`GET /api/kanban/boards/{id}/events?after=`。
- 测试：依赖推进、原子认领（两个调度循环并发不重复认领）、失败上限、审查通过 / 打回、Worker 进程丢失后回收。

### 4. 多模型会诊对齐
来源：H `agent/moa_loop.py`、`moa_alternation.py`、`moa_trace.py`。对照现有实现补齐：参考模型失败时的降级、参考意见的长度上限、`moa.references` 事件里带每个模型的耗时和是否成功。

### 5. 编辑已有模型（第六波遗留，用户要的）
- `PUT /api/models/{id}`：可修改 `name`、`max_output_tokens`、`price`、`prompt_cache`、`fallback`；内置模型的修改存进用户设置（不改代码里的默认列表）。

## 三、前端（第六波剩余 + 第七波）

前端规则见执行指南第二节「新增一个运行事件的完整链路」。安全审查界面、本地语音**不做**（用户决定）。

1. **子任务**（`components/timeline.ts`、`ConversationActivity.tsx`）：
   - 步骤行显示类型徽标（探索 / 调研 / 规划 / 深度分析 / 验收 / 通用 / 协调者）、模型、后台标记、配方名；嵌套子任务缩进。
   - `subtask.output` 不再每段加换行（直接拼接）；`subtask.progress` 仍按行。
   - 运行中的子任务下面有「给这个子任务补充要求」输入框，发 WS `{type: "subtask.message", run_id, subtask_id, text}`；收到 `subtask.steered` 显示「你补充了：…」。
   - `subtask.background_completed` 在对话里显示一张结果卡片。
2. **Worker 组卡片**：每项显示「已验收 ✓ / 未通过 ✗ / 重派过」和验收意见（展开）。
3. **待办**：`run.todos` 在运行头部显示待办清单，按 `revision` 丢弃旧更新。
4. **看板页**：现有看板页加「任务看板」视图：列（待办 / 可执行 / 进行中 / 待验收 / 阻塞 / 完成）、卡片（负责的 Agent、依赖、产出、失败次数）、拖动改状态、「立即调度」按钮、点卡片打开对应运行；订阅 `kanban.updated` 实时刷新。可参考 H `plugins/kanban/dashboard`。
5. **会诊**：输入框「更多」菜单加「多模型会诊」开关；`moa.references` 显示「参考了 N 个模型的意见」，可展开。
6. **设置 → 子 Agent**：类型列表（来源、模型、角色、工具、警告）、快 / 强模型、并发上限、嵌套深度、会诊参考模型。
7. **项目记事本**：检查器里的「项目记事本」入口，查看和编辑 `.atlas/NOTES.md`（`/api/workspace/notes`）。
8. **编辑模型**：设置 → 模型列表每项加「编辑」，可改价格、最长输出、备用模型。
9. adapter：以上接口、事件、WS 消息的类型和方法。
10. 前端检查四项必须通过；用无头 Edge 截图检查每个新界面（方法见执行指南第六节）。

## 四、真机验收（用隔离环境，不要碰用户 8765 上的开发后端）

做法：独立 `ATLAS_DATA_DIR`（复制 `config/atlas.toml`，删掉所有 `[tools.servers.*]`）、`ATLAS_SCHEDULER_ENABLED=false`、独立端口、临时工作目录。

1. 带整组共用验收标准的并行组：A 合格、B 故意做不到 → 只有 B 重派。
2. 看板：「把 src/stats.py 改成能处理空列表，补单元测试，再更新 README」→ 拆成三张有依赖的卡片 → 调度器依次派活 → 审查 → 全部完成。
3. 后台委派 + 界面里给子任务补充要求（前端完成后在界面上操作）。
4. 会诊一轮，两个参考模型中一个故意配错，确认降级正常。

## 五、交付与审查

- Luna：每节一个提交；`VENDORED.md` 登记；结果文件 `tasks/results/ATLAS-W07B-ORCHESTRATION-COMPLETION.result.md`；全量测试用后台进程跑完并写汇总行。
- Sol：按执行指南第五节审查，记录写进 `tasks/reviews/ATLAS-W07B-ORCHESTRATION-COMPLETION.review.md`。审查重点：第二节第 1、3 项的行为（真机）、看板调度的并发认领、前端截图。
