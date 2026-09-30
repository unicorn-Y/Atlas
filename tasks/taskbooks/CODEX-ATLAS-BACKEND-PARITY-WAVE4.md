# CODEX-ATLAS-BACKEND-PARITY-WAVE4

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-BACKEND-PARITY-WAVE3（已接受，见 tasks/reviews/CODEX-ATLAS-BACKEND-PARITY-WAVE3.review.md）
SOURCE: docs/PARITY.md

## Mission

第三波已接进前端并推送（`37eec35`）。第四波做五件事：**外部 Agent 执行**、**并行 Worker**、**Office 文档产物与版本历史**、**结构化的检查/测试结果**、**Docker 沙箱**，外加第三波审阅留下的小问题。

规则不变：

- **只做后端**，不改 `frontend/`、`backend-adapter/`。
- 接口名、事件名、字段名与本文件一致；确需偏离写进结果文件。
- FULL_ACCESS 仍是默认；记忆系统冻结。
- 所有 HTTP / WebSocket 都经过 `core/atlas/origin_guard.py`，**不要绕过、不要放宽**。任何返回用户文件内容或由用户文件生成的 HTML 的接口，都要参照 `/api/workspace/raw` 的沙箱头处理。
- 协议升到 `1.6`。
- 测试不得写入用户真实数据目录；不得在仓库里建 pytest 临时目录；不得依赖真实网络、真实 Docker、真实外部 Agent CLI（用假的可执行文件 / mock）。

## 1. 第三波遗留

1. **内置角色中文化**：内置 profiles 的 `name`、`description` 改为中文（例：「审查员」「只读顾问」）；id 不变。
2. **拒绝提示中文、说人话**：`read_only` / `ask_writes` 被拒、`allowed_paths` 越界时，工具结果的错误文案改为中文并说明原因和解决办法，不出现 profile / tool 这类内部词。例：「当前对话是只读模式，不能写文件。需要修改的话，把对话权限切到『完全访问』或『改前问我』。」
3. **`rules.trust` 更稳**：WS `{type:'rules.trust', run_id, event_id, trust}` 中 `event_id` 不匹配、但该 run 只有一个待回答的信任请求时，按 run_id 接受；都不匹配时回一个 `error` 帧而不是静默忽略。
4. **会话设置可以直接保存**：`PUT /api/conversations/{id}` 接受 `workspace`、`permission_mode`、`allowed_paths`（字符串数组）、`executor`（见第 2 节），并在 `GET /api/conversations` 里返回。现在用户选了目录但没发消息就刷新，选择会丢。`run.start` 未传这些字段时用会话里保存的值。
5. **`allowed_paths` 对 SSH 也生效**：`ssh://` 工作目录下，路径同样按 `allowed_paths` 检查（用 `SSHWorkspaceManager._remote_path` 的规范化结果比较）。
6. **可选真实 SSH 测试**：设置了环境变量 `ATLAS_SSH_TEST_HOST`（如 `zhuji`）和 `ATLAS_SSH_TEST_ROOT`（如 `D:/Atlas-ssh-test`）时，跑一组真实连接测试：测连接、写/读/删文件、在子目录里执行命令并确认当前目录、`cwd` 传 Windows 绝对路径时仍在工作目录内、越界路径被拒。没设置时 skip。（第三波的 mock 与 asyncssh 真实行为不一致，漏了 4 个问题。）

## 2. 外部 Agent 执行 — F008

`core/atlas/agents/backends/` 已有 codex / claude / hermes / pi / zcode 适配器，但界面用不到。让用户可以指定「这个对话交给 Codex / Claude Code 做」。

- `GET /api/agents/external` → `{agents: [{id, name, available, version, detail}]}`。`available` 通过查找可执行文件并执行版本命令判断（结果缓存 60 秒）；不可用时 `detail` 用中文说明怎么装。
- `run.start.executor`：`"atlas"`（默认）| 上面的 id。非 `atlas` 时，本轮由外部 Agent 在工作目录里执行：
  - 用户消息原样交给外部 Agent；同一会话的后续轮次尽量续用外部会话（适配器支持 resume 时）。
  - 输出统一成 Atlas 事件：文本 → `reply.delta` / `reply.completed`；外部 Agent 报告的命令、文件修改 → `tool.started` / `tool.completed`（`name` 用 `external:<原名>`，`arguments` 尽量保留）；结束 → `run.completed` / `run.failed`。
  - `run.started.data` 增加 `executor`。
  - 取消（`run.cancel`）要能停掉外部进程及其子进程。
  - checkpoint 与改动列表照常工作（外部 Agent 改的文件也能在「改动」里看到并撤销）：开始前拍快照，结束后比对。
  - `permission_mode` 为 `read_only` 时拒绝启动外部 Agent 并给出中文说明（外部 Agent 的权限不受 Atlas 控制）。
  - `ssh://` 工作目录暂不支持外部 Agent，返回清晰错误。
- 测试：用假的可执行文件模拟一个外部 Agent（输出固定的 JSON 流），覆盖事件转换、取消、改动列表、不可用时的错误。

## 3. 并行 Worker 与结果汇总 — F192、F193

现在 `delegate_task` 一次只派一个子任务。

- 新工具 `delegate_parallel`：参数 `{tasks: [{title, goal, context?}], max_concurrency?: 1..4}`（默认 3，最多 8 个任务）。每个子任务沿用现有 `subtask.started / subtask.output / subtask.completed` 事件，`data` 里带 `group_id`、`index`、`title`。
- 工作目录是 git 仓库且任务会改文件时，每个 Worker 在自己的 worktree 里做（复用第二波的 worktree 能力），结束后把各自的改动以 patch 形式返回，由协调者（主 Agent）决定合并；不是 git 仓库时 Worker 共用目录，并在系统提示里要求各自只动自己负责的文件。
- 全部结束后发 `subtask.group_completed`：`{group_id, results: [{index, title, status, summary, changed_files}], summary}`，`summary` 由主模型汇总（一次模型调用），工具结果返回给主 Agent 的也是这份汇总。
- 取消主 run 时取消所有 Worker。
- 测试：mock 模型，覆盖并发上限、一个失败其余继续、取消、汇总事件。

## 4. Office 文档产物与版本历史 — F146、F151

### 4.1 生成

新工具（依赖 `python-docx`、`openpyxl`、`python-pptx`，加进 `core/pyproject.toml`）：

- `create_document`：`{path, title?, blocks: [{type: "heading"|"paragraph"|"bullets"|"table"|"image", ...}]}` → `.docx`。
- `create_spreadsheet`：`{path, sheets: [{name, rows: [[...]], header?: bool, column_widths?}]}` → `.xlsx`；以 `=` 开头的单元格作为公式写入。
- `create_presentation`：`{path, slides: [{title, bullets?, notes?, image?}]}` → `.pptx`。
- 都写在工作目录内（受 `permission_mode` / `allowed_paths` 约束），走 checkpoint，完成后发 `artifact.created`（沿用现有产物事件；没有就新增 `{path, kind: "document"|"spreadsheet"|"presentation", bytes}`）。
- 同时支持读取：`read_office`：`{path}` → docx 的段落与表格文本、xlsx 各表前 200 行、pptx 每页标题与要点，给 Agent 修改已有文件用。

### 4.2 预览

`GET /api/workspace/preview?root=&path=` 把 docx / xlsx / pptx 转成**纯静态** HTML（不含脚本，图片内联为 data URL，大小上限 10 MB），响应头与 `/api/workspace/raw` 的沙箱处理一致（`Content-Security-Policy: sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'`）。xlsx 渲染为表格（每表最多 500 行），pptx 每页一个卡片。支持 `ssh://` 根目录（先拉到临时文件再转换）。

### 4.3 版本历史

- `GET /api/workspace/history?root=&path=` → `{versions: [{id, run_id, conversation_id, created_at, bytes, source: "checkpoint"|"git"}]}`：来自 checkpoint 快照；git 仓库里再加最近 20 个提交里的版本。新到旧。
- `GET /api/workspace/history/content?root=&path=&version=` → 与 `/api/workspace/file` 相同格式的内容（二进制文件返回 `binary: true`），以及 `.../raw?...` 返回原始字节（沙箱头）。
- `POST /api/workspace/history/restore`，body `{root, path, version}`：恢复前先为当前内容拍一个 checkpoint，返回 `{restored: true, checkpoint_id}`。
- 测试覆盖：三种文件生成与读取、预览 HTML 不含 `<script`、历史列表顺序、恢复前自动快照。

## 5. 结构化的检查与测试结果 — F128、F129

- 新工具 `run_checks`：`{kind: "lint"|"typecheck"|"test"|"all", paths?: [...]}`。自动识别项目：
  - Python：`pyproject.toml` / `setup.cfg` → ruff（有则用）、mypy（配置里有才跑）、pytest（`--junitxml` 到临时文件解析）。
  - Node：`package.json` 的 `lint` / `typecheck` / `test` 脚本；识别 eslint（`--format json`）、tsc（解析 `file(line,col): error TSxxxx`）、vitest / jest（`--reporter=json`）。
  - 找不到可用检查时返回中文说明，不报错。
- 结果统一为 `{kind, tool, passed, failed, skipped, duration_ms, items: [{file, line, col, severity: "error"|"warning"|"info", code, message, test?}]}`，最多 200 条；工具结果给 Agent 的文本是精简摘要。
- 每次运行发事件 `check.results`，`data` 即上面的结构（加 `run_id`）。
- Agent 自己用 `local_shell` 跑 pytest / vitest 时，如果输出能识别为测试结果汇总行（`N passed, M failed`），也补发一个只有计数、`items` 为空的 `check.results`。
- 测试：用固定的样例输出（ruff json、tsc 文本、pytest junit xml、vitest json）测解析；识别逻辑用临时项目目录测。

## 6. Docker 沙箱 — F017、F163

让用户可以选择「在容器里跑命令」，本机文件仍在工作目录里（绑定挂载），命令的副作用被关在容器里。

- `GET /api/sandbox/status` → `{docker: {available, version, detail}}`（`docker version --format json`，缓存 60 秒；不可用时 `detail` 中文说明）。
- `run.start.sandbox`：`null`（默认，本机执行）| `{type: "docker", image?: string, network?: bool}`；会话记住（同第 1 节第 4 条，`PUT` 也接受 `sandbox`）。默认镜像 `python:3.12-slim`，`network` 默认 `false`（`--network none`）。
- 启用后：`local_shell` / `local_exec` / `git` 在容器里执行（每个 run 起一个容器，`-v <workspace>:/workspace -w /workspace`，run 结束删除容器）；文件读写工具仍在本机、限定在工作目录内（等同于 `allowed_paths = [workspace]`）；computer use、浏览器、MCP 在沙箱模式下禁用，调用时返回中文说明。
- 工具结果里的路径在容器内是 `/workspace/...`，转换回本机路径再返回给 Agent 和事件。
- `run.started.data.environment` 增加 `"docker"`，并带 `image`。
- 与 `ssh://` 不能同时使用，返回清晰错误。
- 测试：mock `docker` 可执行文件（记录参数），覆盖挂载参数、`--network none`、容器清理（包括 run 失败和取消时）、禁用工具的提示、路径转换。

## 7. 验收

- `core/.venv/Scripts/python.exe -m pytest -q --ignore=tests/test_computer_use.py --basetemp <系统临时目录>` 全部通过。
- 新增接口都有 OriginGuard 下的测试（带 token 可访问、网页来源被拒至少各一个代表）。
- 结果文件：`tasks/results/CODEX-ATLAS-BACKEND-PARITY-WAVE4.result.md`，写清每节做了什么、接口/事件与本文件的偏差、已知限制、手动验证方法（尤其是外部 Agent 和 Docker 在真机上怎么试）。
- 提交到 `main`，每节一个提交，提交信息写清楚「为什么」。
