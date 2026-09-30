# CODEX-ATLAS-BACKEND-PARITY-WAVE6

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-BACKEND-PARITY-WAVE5（已接受，见 tasks/reviews/CODEX-ATLAS-BACKEND-PARITY-WAVE5.review.md，**务必读「实测后追加修复」一节**）
SOURCE: docs/PARITY.md

## Mission

第五波已接进前端（`7f5f29a`）。第六波做五件事：**Worker 类型与可导入的子 Agent 定义**、**浏览器交接与复用你自己的浏览器**、**局域网网页版与手机配对**、**对话导出为网页**、**插件市场**，外加第五波遗留。

规则不变：

- **只做后端**，不改 `frontend/`、`backend-adapter/`。
- 接口名、事件名、字段名与本文件一致；确需偏离写进结果文件。
- 流式事件沿用现有协议（回复文字 `message.delta` / `message.completed`）。
- FULL_ACCESS 仍是默认；记忆系统冻结（Worker 不读写用户记忆，见第五波审阅）。
- 所有 HTTP / WebSocket 都经过 `core/atlas/origin_guard.py`。第 3 节需要扩展它，**只能新增一种受信方式（配对设备的会话），不能放宽现有规则**。
- 协议升到 `1.8`。
- 面向用户的错误和提示一律中文。
- 测试不得写入用户真实数据目录；不得在仓库里建 pytest 临时目录（上一波留下了 `core/.pytest-wave1-*` 一堆目录，这次先删掉并把 `core/.pytest-*` 加进 `.gitignore`）；不得依赖真实网络。
- **Mock 模型测不出的问题要真跑一次**：第五波的 Worker 在 mock 测试里全过，真机上却根本收不到任务。本波第 1、2 节完成后，用本机配置的真实模型各跑一个最小场景，把过程和结果写进结果文件（跑不了就写清楚原因）。

## 0. 第五波遗留

1. **Worker 用父 run 的模型**：`_run_atlas_subtask` 现在取 `model_mgr.current_model`（全局当前），改成父 run 实际使用的模型；Worker 里**不要调用 `model_mgr.select()`**（会改掉全局当前模型）。
2. **网页提取防 DNS 重绑定**：`_validate_url` 解析出的地址检查通过后，实际连接必须使用这些已检查过的 IP（自定义 httpx transport，或解析后按 IP 连接并保留 Host 头/SNI），不能让 httpx 重新解析。测试：第一次解析公网、第二次解析内网的 mock 下必须拒绝。
3. **全量测试必须跑完**：你的终端会中断长命令。用后台进程运行全量（例：`Start-Process` 启动 pytest，输出重定向到系统临时目录的文件，轮询到结束再读结果），把最后的汇总行原样写进结果文件。

## 1. Worker 类型与子 Agent 定义 — F192、F065

借鉴 Claude Code（`.claude/agents/*.md` 子 Agent）和 OpenCode（`mode: subagent` 的 agent 定义）的做法：Worker 分类型，每种有自己的说明、提示词、工具白名单和模型；用户可以用 Markdown 文件定义新类型。

- 定义格式：Markdown 文件，开头 YAML frontmatter，正文是该 Worker 的系统提示词。字段：`name`（必填，`[a-z0-9-]`）、`description`（必填，告诉协调者什么时候用它）、`tools`（可选，工具名列表或逗号分隔字符串；缺省为全部可用工具）、`model`（可选；缺省或 `inherit` 用父 run 的模型）、`permission_mode`（可选，只能比父 run 更严格）。未知字段忽略。
- 读取位置（后者同名覆盖前者）：内置 → 数据目录 `agents/` → 工作目录 `.atlas/agents/`。**兼容读取** 工作目录的 `.claude/agents/*.md` 和 `.opencode/agent/*.md`、`.opencode/agents/*.md`（字段按上面映射；OpenCode 的 `tools` 是 `{name: bool}` 对象，true 的算允许；工具名映射不上的忽略并在列表接口里标出来）。工作目录里的定义属于「规则文件」，要走第三波的信任流程，未信任时不加载。
- **同样兼容 Codex CLI 的角色定义**：`~/.codex/agents/*.toml`（用户级，放在数据目录旁一样读取）和工作目录的 `.codex/agents/*.toml`，每个文件一个角色。把其中的名称、说明、提示词（developer instructions）、模型、工具/沙箱相关字段映射到上面的字段；映射不上的字段忽略并写进 `warnings`。实现前先查 Codex CLI 当前文档确认字段名，结果文件里写明采用的映射。
- 内置四种：
  - `explore`：只读（文件读/列/搜、git 读、网页提取），快速调查代码或资料，返回结论和证据位置。
  - `plan`：只读，给出实施方案（改哪些文件、步骤、风险），不动手。
  - `general`：通用（当前默认 Worker 的能力）。
  - `oracle`：只读的深度分析（参考 Amp 的 Oracle）：难以定位的 bug、架构取舍、审查方案。模型用设置里的「强模型」（新增配置 `agents.strong_model`，没配就用父 run 的模型），可以用更高的推理强度。
- **协调规则**（写进委派工具的说明和主 Agent 的系统提示）：只有互不依赖、以阅读调查为主的任务才并行；会改同一批文件、或后一步依赖前一步结果的，串行做或自己做；任务很小（一两次工具调用就能完成）时不要委派。依据：并行不是免费的，每个子 Agent 都单独消耗模型调用，有依赖的任务拆开反而更差。
- `delegate_task` / `delegate_parallel` 增加参数 `agent`（类型名，默认 `general`）；工具描述里列出可用类型的 `name: description`（最多 20 个），让模型挑。并行任务每项可以各自指定 `agent`。未知类型回退到 `general` 并在结果里注明。
- Worker 的工具集 = 类型白名单 ∩ 父 run 允许的工具 − 委派工具。`permission_mode` 取两者中更严格的。
- `subtask.started` 事件的 `data` 增加 `agent`。
- `GET /api/agents/types?root=` → `{types: [{name, description, tools, model, source: "builtin"|"user"|"workspace"|"claude"|"opencode", path?, trusted, warnings: [...]}]}`，给前端展示。
- 测试：frontmatter 解析（含 OpenCode 的对象式 tools、Claude 的逗号字符串）、Codex TOML 解析、覆盖顺序、未信任的工作目录定义不加载、explore / oracle 写文件被拒、oracle 使用 strong_model、未知类型回退。

## 2. 浏览器交接与复用你自己的浏览器 — F139、F140

Agent 用浏览器时会遇到登录、验证码、支付确认这些只能人来做的事。

- 新工具 `browser_handoff`：`{reason, url?}`。调用后 run 进入等待，发事件 `browser.handoff_required {event_id, reason, url}`；用户在前端点「我弄好了，继续」（WS `{type: "browser.handoff", run_id, event_id, done: true, note?}`）后工具返回 `{done: true, note}`，Agent 继续；用户点「做不了」返回 `{done: false, note}`。超时 30 分钟算 `done: false`。
- 交接期间 Agent 的浏览器工具调用一律拒绝（中文提示「正在等用户操作浏览器」）。
- 系统提示补一句：遇到登录、验证码、二次验证、付款确认，调用 `browser_handoff`，不要尝试绕过。
- **复用用户自己的 Chrome**：设置 `browser.mode`：`"atlas"`（默认，现有方式）| `"user_chrome"`。`user_chrome` 时浏览器工具通过 CDP 连接用户已开启调试端口的 Chrome（`browser.cdp_url`，默认 `http://127.0.0.1:9222`，**只允许回环地址**）。`GET /api/browser/status` → `{mode, connected, detail, cdp_url}`；`POST /api/browser/launch-user-chrome` 用用户的 Chrome 可执行文件和**一个专用的新 profile 目录**（数据目录下 `browser-profile/`，不碰用户默认 profile）带调试端口启动，返回状态。
- 用户在自己的 Chrome 里登录过的网站 Agent 就能直接用——这正是交接的意义；在设置接口的说明里写清楚「这个浏览器里的登录状态 Atlas 都能用」。
- 测试：交接的等待/继续/做不了/超时；交接中浏览器工具被拒；`cdp_url` 非回环被拒。

## 3. 局域网网页版与手机配对 — F006、F007

不经过 Telegram，在同一个局域网里用手机浏览器打开 Atlas。

- 默认关闭。`GET/PUT /api/remote` → `{enabled, port, bind: "127.0.0.1"|"lan", url, devices: [{id, name, paired_at, last_seen}]}`。开启 `lan` 时在指定端口（默认 8766）起**第二个监听**（与桌面用的 8765 分开），只提供：静态网页（`frontend` 构建产物 `dist/`，找不到就返回一个说明页）+ 下面的 API 子集 + 运行 WebSocket。
- 配对：`POST /api/remote/pairing`（桌面端调用，需现有 token）生成 6 位数字码，5 分钟有效、只能用一次。手机页面 `POST /remote/pair {code, device_name}` → 设置 `HttpOnly; SameSite=Strict` 的会话 cookie（随机 32 字节，库里只存哈希），返回设备 id。连续 5 次错码锁定 10 分钟。`DELETE /api/remote/devices/{id}` 撤销。
- OriginGuard：在第二个监听上，**只**认配对设备 cookie（且请求的 Origin 必须是该监听自己的地址）；不认 `X-Atlas-Api-Token`，也不开放 Vite 开发来源。桌面端 8765 的规则完全不变。
- 手机端能用的 API 子集：对话列表/消息、发起和停止 run、回答审批/提问/信任、看改动列表。**不能**：改设置、看或改密钥、Hooks、脚本工具、插件、MCP、文件原文下载、终端。
- 手机发起的 run 默认 `ask_writes`（和 Telegram 一致），会话标记 `source: "remote"`。
- 测试：未配对拒绝、错码锁定、配对后可用、撤销后失效、子集外接口拒绝、token 头在第二监听上无效、Origin 不符拒绝。

## 4. 对话导出为网页 — F207

- `GET /api/conversations/{id}/export?format=html`：单文件 HTML，内联样式（浅色/深色随系统），包含用户消息、Atlas 回复（Markdown 渲染为 HTML，代码块保留语言标记）、每轮的步骤摘要（工具名 + 目标，一行一个）和产物列表；页脚写导出时间和「由 Atlas 导出」。
- **不能带脚本**：输出里不允许 `<script>`、事件属性、`javascript:` 链接；Markdown 里的原始 HTML 一律转义。响应头 `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src data:`，`Content-Disposition: attachment`。
- 可选参数 `redact=true`：把本机路径里的用户目录替换成 `~`，隐去工具参数里看起来像密钥的值（`sk-`、`ghp_`、`Bearer ` 等开头的串）。
- 测试：XSS 载荷（消息里含 `<script>`、`<img onerror>`、`javascript:`）全部被转义；redact 生效。

## 5. 插件市场 — F177、F181

现在插件只能本地安装。兼容 Claude Code 的插件市场格式（仓库里的 `.claude-plugin/marketplace.json` 列出插件，每个插件目录有 `.claude-plugin/plugin.json`，内含 skills / agents / commands / hooks / MCP 配置）。

- `GET/POST/DELETE /api/plugins/marketplaces`：添加市场（git 仓库地址或 `owner/repo` 简写，只允许 https 和 GitHub 简写），拉取到数据目录 `marketplaces/`，`POST .../{id}/refresh` 更新。
- `GET /api/plugins/marketplaces/{id}/plugins` → 插件列表（名称、说明、版本、作者、包含哪些组件）。
- `POST /api/plugins/install {marketplace_id, name}`：**先返回将要安装的内容清单**（`dry_run` 默认 true：列出每个 skill/agent/hook/MCP 服务器，尤其是 hook 命令和 MCP 启动命令的原文），前端给用户看过后再以 `dry_run: false` 安装。安装后 skills、第 1 节的 agents 可用；hooks 和 MCP 服务器**默认停用**，要用户在各自设置里单独打开。
- 已装插件纳入现有插件列表，可停用/卸载；记录来源市场和版本，`refresh` 后提示有更新。
- 测试：用本地临时 git 仓库做市场，覆盖清单（含 hook/MCP 命令原文）、安装、hook/MCP 默认停用、卸载、非 https 地址拒绝。

## 6. 验收

- 全量测试**跑完并通过**（方法见第 0 节第 3 条），汇总行写进结果文件。
- 新接口都有 OriginGuard 测试；第 3 节额外覆盖「第二监听只认配对 cookie」。
- 第 1、2 节的真实模型最小场景记录（第 Mission 最后一条）。
- 结果文件：`tasks/results/CODEX-ATLAS-BACKEND-PARITY-WAVE6.result.md`：每节做了什么、偏差、已知限制、手动验证方法。
- 提交到 `main`，每节一个提交，提交信息写清楚「为什么」。推送前先 `git pull --rebase`（我这边会同时推前端提交）。
