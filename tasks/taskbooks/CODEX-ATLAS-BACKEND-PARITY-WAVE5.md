# CODEX-ATLAS-BACKEND-PARITY-WAVE5

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-BACKEND-PARITY-WAVE4（已接受，见 tasks/reviews/CODEX-ATLAS-BACKEND-PARITY-WAVE4.review.md）
SOURCE: docs/PARITY.md

## Mission

第四波已接进前端并推送。第五波做七件事：**Atlas 自己当子任务 Worker**、**一个对话多个目录**、**项目资料**、**回到某条消息之前（含文件）与重做**、**自定义脚本工具**、**网页/视频提取**、**Telegram 远程布置任务**。

用户决定：**外部 Agent 的认证问题这一波不做**，不要改 `runtime/backends.py` 的 ACP 认证逻辑。

规则不变：

- **只做后端**，不改 `frontend/`、`backend-adapter/`。
- 接口名、事件名、字段名与本文件一致；确需偏离写进结果文件。
- 流式事件沿用现有协议：回复文字用 `message.delta` / `message.completed`（不要再发 `reply.*`）。
- FULL_ACCESS 仍是默认；记忆系统冻结。
- 所有 HTTP / WebSocket 都经过 `core/atlas/origin_guard.py`，**不要绕过、不要放宽**。
- 协议升到 `1.7`。
- 面向用户的错误和提示一律中文、说人话，不出现 profile、tool 这类内部词。
- 测试不得写入用户真实数据目录；不得在仓库里建 pytest 临时目录；不得依赖真实网络、真实 Telegram、真实外部 Agent。

## 1. Atlas 自己当子任务 Worker — F192、F193

现在 `DelegationService`（`core/atlas/agent/enrichment.py`）只能把子任务交给外部 Agent；没装外部 Agent 的电脑上 `delegate_task` / `delegate_parallel` 完全用不了。

- 新增执行者 `"atlas"`，并作为 `delegate_task` / `delegate_parallel` 的**默认**：在同一个后端进程里起一个子 Agent 循环，用当前 run 的模型、工具集、`permission_mode`、`allowed_paths`、`sandbox`（子 Agent 不能比父 run 权限更大）。
- 子 Agent 的系统提示说明它是 Worker：只完成给定目标，完成后给出简短结论和证据；**不能再委派**（去掉 `delegate_task` / `delegate_parallel` 工具，防止递归）。
- 工具调用照常走 checkpoint、hooks、`ask_writes` 审批（审批卡片出现在父 run 里，`approval.required` 的 `data` 加 `subtask_id`）。
- 子 Agent 的文字进度发 `subtask.output`（并行时）或 `subtask.progress`（单个），工具调用发 `subtask.output`，`text` 写成一行人话（例：「读取 hello.txt」）。
- 每个 Worker 的轮数上限默认 12，超出算失败并给中文原因；token 用量计入父 run 的 `run.usage`。
- `delegate_parallel` 的 git worktree 隔离、patch 返回、汇总逻辑保持不变，只是默认执行者换成 `atlas`。参数里 `executor` 可选，传外部 Agent id 时走原逻辑。
- 删除第四波审阅里加的「没装外部 Agent 就整组失败」逻辑对 `atlas` 执行者的影响（`atlas` 永远可用）。
- 测试：mock 模型，覆盖单个委派、并行 3 个、一个失败其余继续、取消、禁止递归委派、`read_only` 父 run 下子 Agent 不能写、审批事件带 `subtask_id`。

## 2. 一个对话多个目录 — F011

- 会话新增 `extra_roots: string[]`（绝对路径或 `ssh://`，最多 5 个），`PUT /api/conversations/{id}` 接受，`GET /api/conversations` 返回；`run.start` 未传时用保存值。
- 运行时：系统提示列出主工作目录和附加目录，说明「文件工具可以用绝对路径访问这些目录」。`allowed_paths` 非空时，附加目录自动算在允许范围内。
- 附加目录的规则文件（AGENTS.md / CLAUDE.md / .atlas/rules.md）也走第三波的信任流程（`rules.trust_required` 一次列出所有未信任目录的文件）。
- 工作区接口（tree / file / raw / search / history / preview）已接受任意 `root`，不需改；`/api/runs/{id}/changes` 要能列出附加目录里的改动（路径用 `<目录名>/相对路径` 前缀区分，并在每项里带 `root`）。
- 测试：两个临时目录，覆盖提示词、改动列表、allowed_paths 联动、规则信任。

## 3. 项目资料 — F012

项目（`/api/projects`）现在只有目标和历史回顾。加上「资料」：项目里所有对话都能用。

- `GET /api/projects/{id}/sources` → `{instructions: string, sources: [{id, kind: "file"|"folder"|"url"|"note", title, path?, url?, text?, bytes, added_at}]}`。
- `PUT /api/projects/{id}/sources/instructions`，body `{instructions}`（最多 8000 字）：项目级指令，项目内每个 run 的系统提示都带上。
- `POST /api/projects/{id}/sources`：`{kind, title?, path?|url?|text?}`；文件/文件夹只记录路径并建立文本索引（纯文本、Markdown、代码、docx/xlsx/pptx/pdf 抽文本，单文件 2 MB、总计 50 MB 上限，二进制跳过）；`url` 抓取一次正文存下（复用第 6 节的提取）；`note` 直接存文本。`DELETE /api/projects/{id}/sources/{source_id}`；`POST .../{source_id}/refresh` 重新索引。
- 新工具 `project_sources_search`：`{query, limit?}` → 命中片段（来源标题、路径、片段、得分）；只在对话属于某个项目时提供。用现有的检索能力（有向量就用，没有就 BM25/关键词），不要引入新的大型依赖。
- 测试：索引、检索、指令注入、删除后不再命中、超限跳过。

## 4. 回到某条消息之前（对话 + 文件）与重做 — F093、F094

现在能截断对话（`/truncate`），也能按 run 恢复文件，但两者分开，恢复后也不能反悔。

- `POST /api/conversations/{id}/rewind`，body `{message_id, files: bool}`：删除该消息及之后的消息；`files=true` 时把这些消息对应的所有 run 造成的文件改动按时间倒序恢复到之前的状态（用各 run 的 checkpoint；远程目录用 SSH checkpoint）。执行前先为当前对话记录和所有涉及文件拍一份「回退前快照」。返回 `{rewind_id, removed_messages, restored_files: [...], skipped: [{path, reason}]}`。
- `POST /api/conversations/{id}/rewind/{rewind_id}/redo`：把对话记录和文件都恢复到回退前快照（即撤销这次回退）。只保留每个会话最近 5 次回退。
- 有正在运行的 run 时拒绝（409，中文说明）。
- `GET /api/conversations/{id}/rewinds` → 最近的回退记录（时间、删除的消息数、恢复的文件数、是否已重做）。
- 测试：两轮改文件后回到第一轮之前（文件和消息都回去）、重做后都回来、files=false 只动消息、有 run 在跑时拒绝。

## 5. 自定义脚本工具 — F179

让用户不写 MCP 服务器也能给 Atlas 加工具。

- 存放：数据目录下 `tools/<id>/tool.json` + 脚本文件。`tool.json`：`{id, name, description, command: [...], input_schema, timeout_s, enabled}`；`command` 是参数数组（如 `["python", "run.py"]`），在工具目录里执行；参数以 JSON 从标准输入传入，标准输出作为结果（若是 JSON 就原样返回）。
- `GET/POST /api/custom-tools`、`PUT/DELETE /api/custom-tools/{id}`、`POST /api/custom-tools/{id}/test`（body 为示例参数）。创建时可以同时提交脚本内容 `{script_name, script}`。
- 启用的工具以 `custom_<id>` 名字出现在 Agent 工具列表里；按「会动东西」处理（`ask_writes` 先问、`read_only` 拒绝）。
- `id` 只允许 `[a-z0-9-]`，脚本名不能含路径分隔符；输出截断到 64 KB；超时杀进程树。
- 测试：创建、调用、超时、非法 id、禁用后不出现在工具列表、`read_only` 拒绝。

## 6. 网页/视频正文提取 — F153

- `POST /api/web/extract`，body `{url}` → `{url, title, kind: "page"|"video", text, length, truncated}`：网页取正文（去导航/广告，优先用已有依赖；没有合适的就加 `trafilatura`），YouTube / B 站视频取字幕（有字幕才取；没有时返回中文说明，不做语音识别）。正文截断到 60 000 字。
- 同名 Agent 工具 `web_extract`，让用户说「总结这个链接」时模型能用。
- **SSRF 防护**：只允许 http/https；解析后的地址是回环、内网、链路本地、元数据地址（169.254.169.254 等）时拒绝，**除非** URL 的主机名是 `localhost` / `127.0.0.1` 且用户在请求里带 `allow_local: true`（给本地开发页面用）；跟随重定向时每一跳都检查；响应上限 10 MB；超时 20 秒。
- 测试：mock HTTP，覆盖正文提取、截断、内网地址拒绝、重定向到内网拒绝、字幕缺失的提示。

## 7. Telegram 远程布置任务 — F199、F198、F200

在手机上给 Atlas 发任务、看结果。只做出站长轮询（不开任何入站端口）。

- 设置：`GET/PUT /api/channels/telegram` → `{enabled, bot_token_set: bool, allowed_user_ids: [int], default_workspace, notify_on: ["completed","failed","approval"]}`。`PUT` 接受 `bot_token`（只写不回显，存到系统凭据库或至少与 API key 同等的方式存储，不写进普通配置文件明文）。`POST /api/channels/telegram/test` 验证 token（getMe）并返回 bot 用户名。
- 运行：启用后后台长轮询 `getUpdates`。**只处理 `allowed_user_ids` 里的用户**，其他人的消息一律忽略（回一句「未授权」即可，不泄露任何信息）。
- 命令：普通文字 → 新建对话（标题取前 30 字）在 `default_workspace` 里运行，权限模式用 `ask_writes`（远程发来的任务默认改前要确认）；`/list` 最近 5 个对话及状态；`/stop` 停止最近一个运行中的任务；`/status` 当前运行中的任务。
- 通知：任务完成/失败时回复结果摘要（最后回复的前 1500 字 + 改动文件数）；遇到审批时发消息附「允许 / 拒绝」按钮（callback 数据只含短随机 id，映射存在内存里，10 分钟过期），按钮回调同样校验用户 id。
- 桌面端要知道哪些对话来自手机：会话记录 `source: "telegram"`，`GET /api/conversations` 返回。
- Hub（后台常驻）运行时由 Hub 负责轮询，桌面后端不重复轮询（复用第三波的锁机制）。
- 测试：mock Telegram API，覆盖未授权用户被忽略、文字建任务、完成通知、审批按钮往返、token 不出现在任何 GET 响应和日志里。

## 8. 验收

- `core/.venv/Scripts/python.exe -m pytest -q --ignore=tests/test_computer_use.py --basetemp <系统临时目录> -p no:cacheprovider` **全部跑完并通过**（上一波没跑完，这次必须跑完；某个测试卡住就修测试，不要跳过整套）。
- 新接口都有 OriginGuard 测试（带 token 可访问、网页来源被拒至少各一个代表）。
- 结果文件：`tasks/results/CODEX-ATLAS-BACKEND-PARITY-WAVE5.result.md`，写清每节做了什么、偏差、已知限制、手动验证方法（尤其 Telegram 怎么在真机上试）。
- 提交到 `main`，每节一个提交，提交信息写清楚「为什么」。
