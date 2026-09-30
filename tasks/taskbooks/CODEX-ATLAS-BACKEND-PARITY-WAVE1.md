# CODEX-ATLAS-BACKEND-PARITY-WAVE1

STATUS: DRAFT（用户确认后再挂到 tasks/CURRENT.md）
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-PRODUCT-GAPS-CLOSEOUT-WAVE1
SOURCE: docs/PARITY.md（F001–F210 对标表）

## Mission

前端已经按对标表补完了所有「后端已有接口」的功能（分支 `frontend-parity`）。剩下的缺口都卡在后端没有接口。

这一波**只做后端**：按下面的接口契约实现，写 pytest。前端接线由另一方完成，所以**接口名、字段名必须和本文件一致**；确实需要改的，在结果文件里写明改了什么、为什么。

不做前端改动。不改 `frontend/`、`backend-adapter/`。

保持现有决定：FULL_ACCESS 仍是默认，不加逐工具审批弹窗。下面的 Plan 模式是用户主动选的可选模式。

## 1. 运行中纠偏（steer）— F068

现状：前端把运行中发的消息排进队列，等当前 run 结束再发。这一项让用户可以**插话改方向**，不用等。

- WebSocket `/ws/chat` 新增客户端消息：
  `{"type": "run.steer", "run_id": "...", "content": "...", "event_id": "..."}`
- 后端把这条内容作为用户消息注入正在运行的 Agent 循环，在**下一次调用模型之前**生效（不打断正在执行的工具）。
- 注入后发事件 `run.steered`，`data = {"content": "...", "event_id": "..."}`。
- run 已结束时回 `run.steer.rejected`，`data = {"reason": "run_not_active"}`。
- 协议版本 `/api/runtime/protocol` 升到 `1.3`，旧客户端不受影响。

测试：steer 在运行中生效（模型下一轮能看到这条消息）；已结束的 run 被拒绝。

## 2. 会话置顶 / 归档持久化 — F026、F027

现状：前端先用 localStorage 保存（只在本机有效）。

- `conversations` 表加 `pinned INTEGER DEFAULT 0`、`archived INTEGER DEFAULT 0`（写迁移）。
- `GET /api/conversations` 每项返回 `pinned: bool`、`archived: bool`。
- `PUT /api/conversations/{id}` 接受可选字段 `pinned`、`archived`（和现有 `title` 并存，缺省不改）。

## 3. 本轮改动与 diff — F103、F110、F115

- checkpoint manifest 增加 `run_id`、`conversation_id`（Agent 在 run 中自动建的快照要填上）。
- `GET /api/checkpoints?run_id=&workspace=` 返回
  `[{"id", "workspace", "created_at", "run_id", "files": [{"path", "exists", "directory"}]}]`。
- `GET /api/runs/{run_id}/changes` 返回这次 run 改过的文件：
  `{"run_id", "files": [{"path", "workspace", "status": "added|modified|deleted", "additions": int, "deletions": int, "diff": "<unified diff>"}]}`。
  以该 run 最早的 checkpoint 为基线，对比当前磁盘内容。单文件 diff 超过 200 KB 时截断并加 `"truncated": true`。
- `run.completed` 事件的 `data` 增加 `changes: {"files": int, "additions": int, "deletions": int}`。

## 4. 进程与终端 — F042、F123–F127

- `GET /api/processes` 列出 Agent 启动的后台进程：
  `[{"id", "command", "cwd", "status": "running|exited", "exit_code", "started_at", "run_id"}]`。
- `GET /api/processes/{id}/output?after=<offset>` 返回 `{"output": "...", "next": <offset>, "status"}`。
- `POST /api/processes/{id}/kill`。
- 手动终端：WebSocket `/ws/terminal?cwd=<path>`，Windows 用 pywinpty 开 PowerShell PTY。
  - 客户端发 `{"type": "input", "data": "..."}`、`{"type": "resize", "cols", "rows"}`
  - 服务端发 `{"type": "output", "data": "..."}`、`{"type": "exit", "code"}`
  - 连接断开即结束该 PTY。
- pywinpty 装不上时 `/ws/terminal` 返回明确错误，其他接口照常工作。

## 5. 工作区文件树 — F109、F111、F112

- `GET /api/workspace/tree?root=<abs>&path=<rel>` 返回一层目录：
  `{"root", "path", "entries": [{"name", "path", "type": "file|dir", "size", "git": "M|A|D|?|null"}]}`。
  跳过 `.git`、`node_modules`、`.venv`、`__pycache__`。
- `GET /api/workspace/file?root=&path=` 返回 `{"path", "content", "truncated", "binary"}`，上限 512 KB，二进制文件不返回内容。

## 6. Token 与上下文用量 — F108、F168

- 每次模型调用后发事件 `run.usage`，
  `data = {"input_tokens", "output_tokens", "context_tokens", "context_limit", "model"}`。拿不到的字段给 `null`，不要编。
- `run.completed` 的 `data` 带本次合计 `usage`。
- `POST /api/conversations/{id}/compact`：手动压缩，复用 `ContextMaintenance.compact`，
  返回 `{"before_tokens", "after_tokens", "summary"}`。

## 7. 项目规则文件 — F173、F174、F161

- run 所在工作区（第 13 节的 `workspace`，或所属项目的 `workspace_path`）根目录下的
  `AGENTS.md`、`CLAUDE.md`、`.atlas/rules.md` 注入系统提示；另加用户级 `~/.atlas/AGENTS.md`。
- 每个文件上限 64 KB，超出截断并在提示里注明。
- 首次加载某个工作区的规则时发事件 `rules.loaded`，`data = {"files": [{"path", "bytes"}]}`。
- `GET /api/workspace/rules?root=` 返回会被加载的文件列表和内容。

## 8. 任意文件附件 — F049、F050

- `run.start` 增加可选 `files: [{"name", "mime", "data_base64"}]`，单个上限 10 MB，总共 20 MB。
- 文本类（`text/*`、json、md、csv、代码扩展名）直接内联进用户消息；
  其他类型存到 `~/.atlas/attachments/<run_id>/`，把绝对路径告诉 Agent。
- 现有图片 `attachments` 不变。

## 9. Plan 模式 — F077、F078

- `run.start` 增加可选 `mode: "plan" | "act"`，默认 `act`（即现在的行为）。
- `plan` 模式下只暴露只读工具（读文件、搜索、列目录、web 读取），不执行写文件和 shell 写操作。
- 模型产出计划后发 `run.plan.proposed`，`data = {"plan": <TaskPlan JSON>, "event_id"}`，run 进入 `waiting`。
- 客户端发 `{"type": "run.plan.approve", "run_id", "event_id", "edits": "<可选的补充说明>"}` 后切到 `act` 继续执行；
  发 `run.cancel` 则结束。

## 10. Agent 向用户提问 — F075

- 新增模型可调用的工具 `ask_user(question, options?)`。
- 调用时发 `input.required`，`data = {"event_id", "question", "options": [..] | null}`，run 进入 `waiting`。
- 客户端回 `{"type": "input.response", "event_id", "text"}`，内容作为工具结果返回给模型。

## 11. 编辑重发与分叉 — F088、F091

- `POST /api/conversations/{id}/truncate`，body `{"from_message_id"}`：删除这条及之后的消息（前端随后用新内容重新发起 run）。
- `POST /api/conversations/{id}/fork`，body `{"through_message_id"}`：复制到这条为止的消息成为新会话，返回新会话摘要。
  **只复制对话，不复制或回滚磁盘文件**，在返回里写 `"files_shared": true`。

## 12. 中文全文搜索 — F024

现状：`messages_fts` 用默认分词，中文短语基本搜不到（前端已经把查询包成短语）。

- 换成 FTS5 `trigram` 分词（SQLite ≥ 3.34），写迁移重建索引。
- 少于 3 个字的查询退回 `LIKE`。
- 返回结构不变，另加 `title`（会话标题）。

## 13. 每个会话的工作目录 — F010

- `run.start` 增加可选 `workspace: "<绝对路径>"`；没有时沿用项目的 `workspace_path`，再没有则保持现状。
- Agent 的本地文件和 shell 工具以它作为默认 cwd。
- 会话记录最近一次使用的 `workspace`，在 `GET /api/conversations` 里返回。

## 不在本波范围

- 两套调度（Hub 任务 / `scheduler` + Goals）的合并：需要用户先决定保留哪套。
- SSH、容器、云端执行、远程控制、IDE 插件。
- 记忆系统：冻结，不再新增。

## Required tests

- 每一节至少一个 pytest，覆盖正常路径和一个错误路径。
- 现有 pytest 全部通过。
- `/api/runtime/protocol` 返回 `1.3`，旧的 `1.2` 客户端消息仍然可用（回归测试）。

## Result

写 `tasks/results/CODEX-ATLAS-BACKEND-PARITY-WAVE1.result.md`：每一节是否完成、实际的接口和字段（与本文件不同处要标出）、测试命令和结果、未完成项及原因。
