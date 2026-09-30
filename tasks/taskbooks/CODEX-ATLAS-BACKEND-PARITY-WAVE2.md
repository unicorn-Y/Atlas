# CODEX-ATLAS-BACKEND-PARITY-WAVE2

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-BACKEND-PARITY-WAVE1（已接受，见 tasks/reviews/CODEX-ATLAS-BACKEND-PARITY-WAVE1.review.md）
CODE_BASE_HEAD: 351d50d
SOURCE: docs/PARITY.md

## Mission

第一波的接口都已经接进前端并合入 main。第二波补「多任务并行、可复用、可配置」这一块。

规则和第一波相同：

- **只做后端**，不改 `frontend/`、`backend-adapter/`。
- 接口名、事件名、字段名必须与本文件一致；确需偏离写进结果文件。
- FULL_ACCESS 仍是默认，不加逐工具审批。记忆系统冻结。
- 所有 HTTP / WebSocket 路由都经过 `core/atlas/origin_guard.py`，**不要绕过、不要放宽**。新的 WebSocket 路由不需要额外处理，中间件已经覆盖。
- 运行时协议从 `1.3` 升到 `1.4`；前端按「主版本相同、次版本 ≥ 1.2」判断，升级不会破坏现有客户端。
- 测试不得写入用户真实数据：checkpoint、附件、worktree、recipes、profiles 的存储目录在测试里必须指向 `tmp_path`（第一波有测试把快照写进了真实目录，已修）。

## 1. Git worktree 隔离 — F014、F015、F190

让一个会话在独立的 worktree 里改代码，多个会话并行互不干扰。

- `run.start` 新增可选 `worktree: {"base_branch": "<可选，默认当前分支>", "name": "<可选>"}`。
  - 该会话第一次带 `worktree` 启动时：在 `<workspace>/../.atlas-worktrees/<repo名>/<会话短 id>` 执行 `git worktree add -b atlas/<会话短 id> <path> <base_branch>`；之后该会话的 run 都以这个 worktree 为工作目录。
  - 会话记录 `worktree_path`、`worktree_branch`、`base_branch`，在 `GET /api/conversations` 返回。
  - workspace 不是 git 仓库时返回 `run.failed`，`category: "validation"`，`detail` 写明原因。
- `GET /api/conversations/{id}/worktree` → `{path, branch, base_branch, ahead, behind, dirty, changed_files}`。
- `POST /api/conversations/{id}/worktree/merge`，body `{"strategy": "merge" | "squash", "message": "<可选>"}`：合并回 `base_branch` 所在的主工作区。有冲突时不留半合并状态，返回 409 和冲突文件列表。
- `DELETE /api/conversations/{id}/worktree`：`git worktree remove` 并删分支（`?keep_branch=true` 保留分支）。有未提交改动时返回 409，除非 `?force=true`。
- `GET /api/git/branches?root=` → `{current, branches: [..]}`，给前端选起始分支用。

## 2. 子 Agent 与后台任务进度 — F045、F187、F189

现在 `delegate_task` 对前端是黑盒。

- 委派开始时发 `subtask.started`：`{subtask_id, goal, backend, parent_run_id}`。
- 有输出时发 `subtask.progress`：`{subtask_id, text}`（节流，≥ 500ms 一次）。
- 结束时发 `subtask.completed`：`{subtask_id, status: "completed"|"failed"|"cancelled", summary, duration_ms}`。
- `POST /api/runs/{run_id}/subtasks/{subtask_id}/cancel`。
- 这些事件走父 run 的事件流，序号连续（不要像第一波的 `run.steer.rejected` 那样用新 RunState，前端会丢弃序号不连续的事件）。

## 3. Recipes — F064、F184、F063

把一次好用的任务存成可以带参数复跑的配方。

- 存储：`<data>/recipes/<id>.toml`。
- 字段：`{id, name, description, prompt, params: [{name, label, default}], active_skills, mode: "act"|"plan", workspace: <可选>, profile_id: <可选>, created_at, updated_at}`。`prompt` 里用 `{{参数名}}` 占位。
- `GET /api/recipes`、`POST /api/recipes`、`PUT /api/recipes/{id}`、`DELETE /api/recipes/{id}`。
- `POST /api/recipes/{id}/render`，body `{"params": {...}}` → `{prompt, active_skills, mode, workspace, profile_id}`；缺参数返回 422 并列出缺哪些。前端拿渲染结果走普通的 `run.start`。
- `POST /api/recipes/from-run`，body `{"run_id", "name"}`：用这个 run 的用户输入、技能、mode、workspace 生成一个配方草稿并保存，返回配方。

## 4. Agent 角色配置（Profile / Mode）— F020、F065、F180、F188

- 存储：`<data>/profiles/<id>.toml`。
- 字段：`{id, name, description, model: <可选>, reasoning_effort: <可选>, instructions: "<追加到系统提示>", active_skills: [..], tools: {"allow": [..] | null, "deny": [..]}, mode: "act"|"plan"}`。`tools.allow` 为 null 表示不限制；工具名用模型看到的名字。
- 内置三个，不可删、可改：`default`（现在的行为）、`architect`（只读工具 + plan）、`reviewer`（只读工具，指令偏代码审查）。
- `GET/POST /api/profiles`、`PUT/DELETE /api/profiles/{id}`。
- `run.start` 新增可选 `profile_id`；run 里的 `model`、`active_skills`、`mode` 显式传入时优先于 profile。
- 工具过滤要在分发层也生效（参照第一波 plan 模式的做法），不能只是不告诉模型。

## 5. 推理档位 — F165

- `run.start` 新增可选 `reasoning_effort: "minimal"|"low"|"medium"|"high"`，传给 litellm（`reasoning_effort` 参数）；模型不支持时忽略，并在第一次 `run.usage` 里带 `reasoning_effort_applied: false`。
- `GET /api/models` 每个模型增加 `supports_reasoning_effort: bool`（按 litellm 的能力判断，拿不到就 false）。

## 6. @ 文件搜索与 # 会话引用 — F047、F048

- `GET /api/workspace/search?root=&q=&limit=50` → `{files: [{path, name, type}]}`：按文件名模糊匹配（子序列匹配即可，按匹配度排序），尊重 `.gitignore`，跳过第一波 tree 接口跳过的目录。
- `run.start` 新增可选 `context_files: ["<相对 workspace 的路径>", ..]`：内容注入用户消息（单文件 64 KB、总计 256 KB 截断，注明截断）。
- `run.start` 新增可选 `context_conversations: ["<会话 id>", ..]`：每个会话取最后 20 条消息生成摘要注入（复用 ContextMaintenance 的摘要能力），最多 3 个。

## 7. 侧边问答（side chat）— F087

在不打扰主任务的情况下问一个问题。

- `run.start` 新增可选 `ephemeral: true`：以 `conversation_id` 的历史作为上下文运行，但这次的用户消息和回复**不写入**该会话；工具只允许只读。事件照常推送。
- 主任务正在运行时也允许同一会话再开一个 ephemeral run。

## 8. 会话分叉关系 — F089、F090、F096

- fork 时记录 `parent_conversation_id`、`fork_message_id`，`GET /api/conversations` 返回。
- `POST /api/conversations/{id}/fork` 新增可选 `summarize: true`：新会话开头插入一条系统消息，是对被分叉前内容的摘要（F096）。
- `POST /api/conversations/{id}/duplicate`：复制全部消息，等价于 fork 到最后一条。

## 9. 目标编辑 — F083

- `PUT /api/goals/{id}`，可改 `name`、`goal`、`description`、`trigger_type`、`trigger_args`、`tags`；改 `goal` 时记录 `goal.replaced` 事件并把 `goal_status` 重置为 `pending`。
- `POST /api/goals/{id}/pause`、`/resume`：暂停时不再触发，状态 `paused`。

## 10. 文件原样读取 — F143、F144

- `GET /api/workspace/raw?root=&path=`：按扩展名返回正确的 `Content-Type` 流式输出，上限 50 MB。给前端预览 PDF、图片、HTML 用。与 tree/file 接口相同的路径逃逸检查。

## 11. 大结果外置 — F169

- 核实工具输出是否会原样塞进上下文。单次工具结果超过 16 KB 时：完整内容写到 `<data>/tool-results/<run_id>/<call_id>.txt`，给模型的只保留头尾各 4 KB 和文件路径，并告诉模型可以用文件工具读取。`tool.completed` 事件的 `data` 增加 `full_output_path`。

## 12. 杂项

- 把 `core/.pytest-*` 临时目录的来源找出来（第一波在主机上留了十几个），测试改用 pytest 的 `tmp_path`/`--basetemp` 到系统临时目录，不再在仓库里建目录。
- `test_provider_reference_hash_matches_node_generated_mixed_path_fixture` 的 `zh-CN` locale 问题（第一波结果文件里记的那个）。

## 不在本波范围

- 两套调度（Hub 任务 / scheduler + Goals）的合并：等用户决定。
- SSH、容器、云端执行、远程/手机控制。
- 浏览器预览、任务看板：前端自己做，不需要后端。

## Required tests

- 每一节至少一个 pytest，覆盖正常路径和一个错误路径。
- worktree 测试在 `tmp_path` 里 `git init` 一个仓库来测。
- 现有 `core/tests` 全部通过（`test_computer_use.py` 会操控真实鼠标，可以单独跑或在结果里说明）。
- `/api/runtime/protocol` 返回 `1.4`。

## Result

写 `tasks/results/CODEX-ATLAS-BACKEND-PARITY-WAVE2.result.md`：每一节是否完成、实际的接口和字段（与本文件不同处标出）、测试命令和结果、未完成项及原因。交付时把 `tasks/CURRENT.md` 更新为本任务（写上交付状态和 result 路径），PREVIOUS 为 WAVE1（ACCEPTED）。
