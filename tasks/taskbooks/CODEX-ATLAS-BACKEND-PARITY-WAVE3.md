# CODEX-ATLAS-BACKEND-PARITY-WAVE3

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-BACKEND-PARITY-WAVE2（已接受，见 tasks/reviews/CODEX-ATLAS-BACKEND-PARITY-WAVE2.review.md）
SOURCE: docs/PARITY.md

## Mission

第二波已接进前端。第三波做四件大事：**统一调度**、**SSH 远程工作目录**、**可选的权限模式**、**PR / CI / Hooks**，外加第二波审阅留下的小问题。

规则不变：

- **只做后端**，不改 `frontend/`、`backend-adapter/`。
- 接口名、事件名、字段名与本文件一致；确需偏离写进结果文件。
- FULL_ACCESS 仍是默认；第 4 节的权限模式是用户主动选择的可选项。记忆系统冻结。
- 所有 HTTP / WebSocket 都经过 `core/atlas/origin_guard.py`（Hub 也已挂上），**不要绕过、不要放宽**。任何返回用户文件内容的接口都要参照 `/api/workspace/raw` 的沙箱头处理。
- 协议升到 `1.5`。
- 测试不得写入用户真实数据目录；不得在仓库里建 pytest 临时目录。

## 1. 第二波遗留

1. `POST /api/recipes/from-run`：run 在 worktree 里执行时，配方的 `workspace` 记录**原始工作目录**，不是 worktree 路径。
2. 配方默认描述改为中文（「从一次任务生成」）或留空。
3. `fork` 与 `duplicate` 复制源会话的 `workspace`（不复制 worktree 关系）。
4. `run.start.worktree.name`：用作分支名后缀 `atlas/<会话短 id>-<name>`（只允许 `[a-z0-9-]`，其余字符替换为 `-`，最长 24），不传时保持现状。

## 2. 统一调度 — F086、F194、F195、F196、F197

用户决定：**合并到 `AtlasScheduler`**，Hub 不再有自己的任务存储。

- 唯一任务存储：调度器现有的 `schedules.toml`。启动时如果存在 `data/hub-schedules.toml`，把其中任务迁移进来（id 冲突时加后缀 `-hub`），成功后改名为 `hub-schedules.toml.migrated`。迁移只做一次，要有测试。
- **同一时刻只有一个进程触发任务**：桌面后端与 Hub 通过数据目录里的锁文件协调（带进程 id 和心跳，进程死掉后锁可被接管）。Hub 运行时由 Hub 触发，桌面后端只读写存储；Hub 退出后桌面后端接管。这就是「关掉窗口后任务照常运行」的来源（F197）。
- 触发器：现有 `cron | interval | date`，再加事件触发 `trigger_type: "event"`，`trigger_args: {"event": "run.completed" | "run.failed" | "file.changed", "filter": {...}}`。`file.changed` 的 `filter` 为 `{"root": "<绝对路径>", "glob": "<可选>"}`，用 watchdog 监听，去抖 2 秒（F196）。
- API：`/api/schedules` 是唯一入口，列表同时返回普通任务和目标（带 `goal` 字段的就是目标）；增加 `POST /api/schedules/{id}/pause`、`/resume`。
- `/api/hub/tasks*` 保留一个版本作为兼容别名，转发到 `/api/schedules`，响应头加 `Deprecation: true`。`/api/hub/status|start|stop` 保留，含义改为「后台常驻进程」的状态和开关。
- 每次触发记录到任务的 `runs` 列表（最近 20 条：`{run_id, conversation_id, started_at, status}`），`GET /api/schedules/{id}` 返回。

## 3. SSH 远程工作目录 — F016、F021

对话的工作目录可以是另一台电脑上的目录。例：在笔记本上让 Atlas 直接改主机上的 `D:\Atlas`。

- 工作目录写法：`ssh://<host>/<path>`，`host` 可以是 `~/.ssh/config` 里的别名（比如 `zhuji`）。用 asyncssh（或 paramiko），读取用户的 ssh config 和密钥；**不接受、不保存密码**。
- 远端系统自动识别（Windows 用 PowerShell，Linux/macOS 用 sh），结果缓存在连接上。
- `run.start.workspace` 为 `ssh://` 时，本地文件、编辑、shell、exec、git 工具都在远端执行，返回格式与本地一致；不支持的工具（computer use、浏览器）照常在本机运行，并在工具结果里注明「在本机执行」。
- 第一波的 workspace 接口（tree / file / raw / search / rules）和 `/api/runs/{id}/changes` 都支持 `ssh://` 根目录。checkpoint 在远端工作目录下的 `.atlas-checkpoints/` 里做（远端没有 git 时退化为文件拷贝）。
- `GET /api/ssh/hosts` → `{hosts: [{alias, hostname, user}]}`（解析 `~/.ssh/config`）；`POST /api/ssh/test`，body `{"host"}` → `{ok, os, detail}`，给前端选主机、测连接用。
- 连接池：按 host 复用，空闲 5 分钟关闭；断线自动重连一次，失败时工具返回清晰错误。
- 会话记录里 workspace 原样保存 `ssh://...`；run 事件 `run.started` 的 `data` 增加 `environment: "local" | "ssh"`、`host`（F021）。
- 测试：用 asyncssh 在测试里起一个本地 SSH 服务端（或 mock 传输层），覆盖文件读写、命令执行、树、断线重连、未知 host。

## 4. 可选权限模式与工作区信任 — F154、F155、F159、F160、F161

默认行为不变（FULL_ACCESS）。用户可以按会话选更严格的模式。

- `run.start.permission_mode`：`"full_access"`（默认）| `"ask_writes"` | `"read_only"`。
  - `ask_writes`：会改动东西的工具调用（写文件、编辑、shell、exec、git 写操作、computer use 的输入类动作）先走现有的 `approval.required` 流程；读取类直接执行。
  - `read_only`：写类工具在分发层直接拒绝（参照 plan 模式的做法）。
  - 会话记住最近一次的 `permission_mode`，在 `GET /api/conversations` 返回。
- `run.start.allowed_paths`：可选的绝对路径列表；给了就只允许在这些目录（和 workspace）下读写，越界的工具调用返回错误（F160）。
- 工作区信任（F161）：工作目录里的 `AGENTS.md` 等规则文件，**第一次**加载某个目录时不直接注入，而是发 `rules.trust_required`：`{event_id, root, files: [{path, bytes}]}`，run 进入 `waiting`。客户端回 `{"type": "rules.trust", "event_id", "trust": true|false}`。信任结果按目录存到 `<data>/trusted-workspaces.json`；`GET /api/workspace/trust?root=`、`DELETE /api/workspace/trust?root=` 查看和撤销。
  - 注意：`run.steer.rejected` 那种用新 RunState 发事件的写法会导致前端丢弃事件，这里必须用当前 run 的序号。

## 5. PR 与 CI — F120、F121

依赖本机的 `gh` CLI（已登录）；没有 `gh` 或未登录时接口返回明确错误。

- `GET /api/git/pr?root=`：当前分支对应的 PR：`{number, title, url, state, draft, base, head, checks: [{name, status, conclusion, url}]}`；没有 PR 时 `{pr: null}`。
- `POST /api/git/pr`，body `{"root", "title", "body", "base": "<可选>", "draft": false}`：推送当前分支并创建 PR，返回同上结构。
- `GET /api/git/pr/checks/{check_name}/log?root=`：失败检查的日志末尾（最多 64 KB），给前端「让 Atlas 修 CI」用。
- 支持 worktree 会话（在 worktree 目录里执行）。

## 6. 用户可配置的 Hooks — F178

- 存储 `<data>/hooks.toml`：`[[hooks]] id, event, command, timeout_s (默认 30), enabled`。
- 事件：`run.started`、`tool.before`、`tool.after`、`run.completed`、`run.failed`。
- 执行：在 run 的工作目录里跑 `command`，stdin 传 JSON（事件名、run_id、conversation_id、工具名和参数/结果），stdout 前 4 KB 记入事件。`tool.before` 的命令退出码为 2 时**阻止**这次工具调用，stdout 作为拒绝原因返回给模型。
- 每次执行发 `hook.ran`：`{hook_id, event, exit_code, duration_ms, output}`。
- `GET/POST /api/hooks`、`PUT/DELETE /api/hooks/{id}`、`POST /api/hooks/{id}/test`（用示例载荷试跑）。
- Hook 超时或出错不能卡住 run，只记录。

## 不在本波范围

- Docker 沙箱、云端执行、手机远程控制。
- 前端：由另一方接线。

## Required tests

- 每一节至少一个 pytest，覆盖正常路径和一个错误路径。
- 调度锁：两个调度器实例同时启动，只有一个触发任务；持有者退出后另一个接管。
- 现有 `core/tests` 全部通过（`test_computer_use.py` 可单独说明）。
- `/api/runtime/protocol` 返回 `1.5`。

## Result

写 `tasks/results/CODEX-ATLAS-BACKEND-PARITY-WAVE3.result.md`：每一节是否完成、实际的接口和字段（与本文件不同处标出）、测试命令和结果、未完成项及原因。交付时把 `tasks/CURRENT.md` 更新为本任务，PREVIOUS 为 WAVE2（ACCEPTED）。
