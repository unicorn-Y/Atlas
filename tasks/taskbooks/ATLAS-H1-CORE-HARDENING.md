# ATLAS-H1-CORE-HARDENING：主体加固一次到位（带测试）

> 来源：2026-10-04 Claude 对 `574db83` 的专业审查（结论见本文第 1 节）。
> 用户要求：**一次性把审查发现的问题都解决，带着测试。**
>
> 这一波**不加新功能**。只做：内核接口化、单一数据源、并发与资源、模型路由、服务端拆分、错误处理、启动速度、无头 CLI、测试体系，最后用真实模型做一轮 Atlas 自己的冒烟实测。
> 做完后才进入 T1（`tasks/taskbooks/ATLAS-T1-HEAD-TO-HEAD.md`）和日常使用。

---

## 0. 执行硬规则

ZCodex 是 controller，不是主要 coder。

1. 编码、focused tests、review 尽量交子代理；**使用当前 runtime 实际允许的最大并发**，不写死数量；被拒就缩 batch，不退回单线程。
2. 热文件只给一个 integration owner：
   - `core/atlas/server.py`（H5 之前由 H5 owner 独占）
   - `core/atlas/engine/hermes_runtime.py`
   - `core/atlas/agent/__init__.py`
   - Hermes fork `unicorn-Y/hermes-agent:atlas`
   - `frontend/src/main/backendProcess.ts`
3. 每个阶段一个或多个 milestone commit，commit 后 push，然后继续，不停下等用户（只有第 H10 节真实模型那一步可能需要用户在场，见 H10）。
4. **行为不变是默认要求**：除本书明确要求改变的地方，前端协议、API 路径、事件类型、设置项含义一律不变。协议版本号不升。
5. **禁止**：新功能、UI 改版、MemoryOS、安全审查/危险检测/注入扫描（用户自己设计）、沙箱、新一轮上游调研。
6. 每一项修复都要有对应测试；没有测试的修复不算完成。

---

## 1. 要解决的问题（审查结论，逐条对应阶段）

| # | 问题 | 证据 | 阶段 |
|---|---|---|---|
| P1 | Hermes 内核靠改私有属性接入：`agent._build_system_prompt` / `_vprint` / `_buffer_diagnostic_status` / `_dispatch_delegate_task` / `_atlas_before_model_request` / `_on_session_title` / `_atlas_context_handoff_summary`；身份靠字符串替换 `"You are Hermes Agent, built by Nous Research."` | `engine/hermes_runtime.py:664-753`，`engine/tool_registry.py:377` | H1 |
| P2 | 新旧两套并存：`AgentOrchestrator.run()` 约 40 个参数、3097 行；会话记录 Atlas SQLite 与 Hermes `state.db` 双写，靠 `session_sync` 同步 | `agent/__init__.py:2186`，`engine/session_sync.py` | H2 |
| P3 | 每轮新建 `AIAgent`、每轮重新注册 MCP；每轮改进程级 `os.environ["HERMES_HOME"]`；全局插件钩子 + 线程本地上下文；50ms 轮询 + 每 250ms 查通知库；`_LIFECYCLE_FUTURES` 只增不减 | `engine/hermes_runtime.py` | H3 |
| P4 | 默认全部走 OpenAI 兼容网关，Claude 原生缓存/思考签名、OpenAI Responses 推理续接丢失；交接摘要、MoA、规划/反思等旁路直接调 `litellm.acompletion` 用网关 key，绕开原生 provider；token 用「字符数÷4」估算 | `hermes_runtime.py:140,545,690`，`agent/__init__.py:632,702,2957,2971,3004` | H4 |
| P5 | `server.py` 8609 行、257 个路由，成为开发瓶颈 | `core/atlas/server.py` | H5 |
| P6 | 356 处 `except Exception`，大量静默吞错 | 全仓 | H6 |
| P7 | 渠道（Telegram/邮件/Slack/飞书/钉钉/企微/Webhook）进来的任务和桌面一样默认 `full_access` | `server.py:6810,7232,7400` | H7 |
| P8 | 冷启动约 20 秒，Electron 15 秒超时会杀后端 | `frontend/src/main/backendProcess.ts` | H8 |
| P9 | 没有可用的无头/脚本模式，T1 和 CI 都需要 | `core/atlas/cli.py`（242 行） | H9 |
| P10 | 2016 个测试几乎全是假模型；全量 30 分钟，Codex 终端跑不完；从未用真实模型端到端跑过 | `tasks/feedback/` 为空 | H10 |

---

## 2. 开工前（H0）

### H0.1 主机工作区

主机 `D:\Atlas` 在 2026-10-04 有约 20 个未提交改动（`skills_market_router.py`、`desktop_entry.py`、`hermes_runtime.py`、`tool_registry.py`、`models/__init__.py`、`server.py`、`mcp_client.py`、`backendProcess.ts`、`electron.ts` 等）。
- 先 `git status` / `git diff --stat`，把它们**原样**提交到分支 `wip/host-uncommitted-2026-10-04` 并 push，在结果文件里列出文件清单和一句话说明每个改了什么。
- 然后从干净的 `main` 开工。**不得丢弃或覆盖这些改动**；如果其中有和本书冲突的修复，在结果文件里标出，留给用户决定。

### H0.2 基线

写 `core/scripts/baseline_metrics.py`，输出 `tasks/results/ATLAS-H1-baseline.json`，记录（全部用假模型）：
- 后端冷启动到 `/api/health` ok 的秒数（3 次取中位）；
- 单轮简单对话（无工具）后端内部耗时，拆成：建 `AIAgent`、注册 MCP、首个模型请求发出；
- 一次等待模型 5 秒的运行期间，事件循环唤醒次数和后端进程 CPU 时间；
- 20 轮对话后进程常驻内存；
- `except Exception` 总数、静默吞错（`except Exception: pass` / 只 `continue`）数；
- `server.py` 行数和路由数；
- 后端全量测试耗时、前端测试耗时。

H11 用同一脚本出「之后」的数字。

---

## 3. H1 内核接口化：去掉所有私有属性改写

**目标：`core/atlas/` 里不再出现任何对 Hermes 对象私有属性（`_` 开头）的赋值，也不再字符串替换 Hermes 提示词。** Fork `unicorn-Y/hermes-agent:atlas` 是 Atlas 自己的，缺接口就在 fork 里加正式接口。

### 做法

1. 先查上游已有的正式机制，有就用，不重造：
   - 身份：Hermes 的身份/人格文件机制（如 engine home 下的 `SOUL.md` 或等价配置，以开工冻结版本为准）。Atlas 身份写进它，删掉字符串替换。
   - 会话标题、状态、诊断、委派：查 `AIAgent.__init__` 参数、`hermes_cli/plugins.py` 钩子、callback 参数，能用就用。
2. 上游没有的，在 fork 加**公开**参数或钩子（建议集中成一个 `AgentHooks` dataclass 作为 `AIAgent(hooks=...)` 参数），覆盖：
   - `before_model_request() -> bool`
   - `on_diagnostic(text)`（替代改写 `_vprint` / `_buffer_diagnostic_status`）
   - `delegate_dispatcher(args) -> str`
   - `on_session_title(title, source)`
   - `system_prompt_suffix(prompt) -> str`（Atlas 的会话启动上下文、模型系列提示放这里；**追加在稳定前缀之后，不能破坏提示缓存**）
   - `context_handoff_summary`（写入方式改为公开方法）
3. fork 每个补丁：
   - 在 fork 根目录 `ATLAS_PATCHES.md` 登记（文件、目的、对应测试）；
   - 在 fork 的 `tests/` 加单测；
   - 保持对上游 tail-sync 友好：改动集中、默认值等于上游原行为。
4. Atlas 端 `pyproject.toml` 重新 pin 到新 fork 提交，更新 `docs/plan/VENDORED.md`。

### 测试

- `core/tests/test_hermes_contract.py`
  - **AST 静态检查**：扫描 `core/atlas/**/*.py`，断言没有对 Hermes 对象 `_` 开头属性的赋值（白名单为空），没有 `"You are Hermes Agent"` 字面量。
  - 用真实 `AIAgent` + `tests/fakes/fake_llm_provider.py` 跑一轮带工具调用的对话，断言每个钩子都被调用一次以上，且系统提示首行是 Atlas 身份、请求里不含 "Hermes Agent"。
  - 断言系统提示的稳定前缀在两轮之间逐字节相同（缓存不被 suffix 破坏）。
- fork 内新增单测全部通过。

---

## 4. H2 单一执行路径、单一会话数据源

### H2.1 会话数据只有一份

先写 `docs/plan/DATA-OWNERS.md`：列出所有 SQLite/DBOS/文件存储，每类数据只能有一个 owner。规定：

| 数据 | 唯一 owner |
|---|---|
| 对话记录（消息、工具调用、工具结果、分叉、回退） | Hermes `SessionDB`（`engine/state.db`） |
| 对话元数据（标题、工作区、权限模式、置顶、项目、run 记录、用量） | Atlas SQLite |
| 长期记忆 | 保持现状（用户决定记忆冻结），本波只做 H2.3 的止血 |
| 定时/队列/回执 | DBOS |
| 渠道游标/去重 | 各 adapter 自己的 state db（保留，写进表里即可） |

然后：
1. Atlas 的消息读取接口（会话列表预览、消息分页、搜索、导出、分叉树）改为从 `SessionDB` 读；Atlas `messages` 表停止写入，保留只读一个版本用于回滚，结果文件写明何时可删。
2. `session_sync.py` 里「Atlas 改了 → 同步到 Hermes」的双写逻辑改为直接操作 `SessionDB`（截断、回退、分叉、删除、导入/导出）。
3. **迁移**：首次启动时把 Atlas 有、`SessionDB` 没有的历史会话导入；迁移前自动备份两个数据库到 `data/backup/<时间戳>/`；迁移幂等，可重复运行；失败不删任何数据并在界面提示。
4. 加 `atlas doctor sessions`（CLI）：对比元数据与 `SessionDB`，报告孤儿和不一致。

### H2.2 拆 `AgentOrchestrator.run()`

- 约 40 个参数改为 `RunRequest`（输入、模式、权限、工作区、模型）+ `RunCallbacks`（审批、输入、子任务、事件）两个 dataclass；调用方全部改过来。
- 删除不再被任何路径调用的旧循环残留代码。用 coverage 跑全量测试 + 搜引用，列出删除清单写进结果文件。
- 目标：`agent/__init__.py` 拆成几个模块，单文件不超过 1200 行，`run()` 函数体不超过 200 行。

### H2.3 记忆止血（不改架构）

- 测量每轮注入系统提示的记忆/反思/goal knowledge 的 token 数，加总上限（配置项，默认不超过上下文窗口 5%），超了按相关度截断。
- 列出没有任何 UI 入口、也没有被运行路径调用的记忆函数，写进结果文件，**不删**，留给用户决定。

### 测试

- 迁移：用一份脱敏的真实形状 fixture 库（含分叉、回退、工具调用、图片、中文）迁移，断言条数、顺序、工具配对一致；重复迁移不重复导入；迁移中途抛异常时两个库都未被改动。
- 分叉/回退/删除/导出/导入：每个操作后 `atlas doctor sessions` 报告零不一致。
- 前端：消息列表、分叉树、搜索相关测试全绿，协议无变化。
- 注入上限：构造超大记忆库，断言注入 token 不超过上限。

---

## 5. H3 并发与资源

1. **`HERMES_HOME` 只在进程启动时设置一次**。运行期间任何代码不得再改 `os.environ`（`hermes_runtime.py`、`session_sync.py` 等全部清掉）。
2. **策略插件、MCP 注册在启动时做一次**；MCP 配置改变时增量刷新（只重连变化的 server）。不再每轮注册。
3. **每会话 AIAgent 缓存**：移植 Hermes gateway 的每会话 agent 缓存思路（`gateway/` 下的 agent cache，以开工冻结版本的实际文件为准，写进 VENDORED.md）：同一会话连续轮次复用 agent，以保住提示缓存；模型、工具集、工作区、权限、计划模式任一变化就重建；LRU 上限可配置（默认 16），空闲超时回收并 `close()`。
4. **工具上下文**：线程本地 + 全局字典改为以 `session_id`（子 Agent 用自己的 id）为 key 的注册表，运行结束必清；Hermes 并行工具线程拿上下文只走 session_id，不走线程本地。
5. **去掉轮询**：50ms `wait_for` 循环和 250ms 查库改为事件驱动——通知写入时 `asyncio.Event` / 队列推送；取消、插话也走事件。
6. `_LIFECYCLE_FUTURES` 改为 `set`，future 完成回调里移除。

### 测试

- `test_concurrency_isolation.py`：假模型，同时跑 8 个会话（不同工作区、不同模型、不同权限模式，其中 2 个是 SSH 工作区的模拟、2 个触发审批、2 个触发子 Agent），外加 1 个常驻 Agent 心跳和 1 个群聊轮次。断言：每个会话的工具事件、cwd、审批、标题、用量都只出现在自己的流里；工具实际执行目录正确。重复跑 20 次无失败。
- `test_runtime_resources.py`：
  - 20 轮对话后 MCP 注册函数只被调用 1 次；
  - 运行期间 `os.environ` 快照不变；
  - 同会话连续 5 轮只构建 1 次 AIAgent，切换模型后重建；
  - 等待模型 5 秒期间事件循环唤醒次数比 H0 基线下降 90% 以上；
  - 跑 100 次自动压缩后 lifecycle futures 集合为空；
  - LRU 满后最旧的 agent 被 `close()`。

---

## 6. H4 模型路由统一与原生通道

1. 新建 `core/atlas/models/router.py`：`resolve(model_id, purpose) -> RouteSpec`（provider、api_mode、model、base_url、key、credential_pool）和 `complete(route, messages, **kw)`。
2. **所有模型调用都走它**：主对话、手动/自动压缩模型、交接摘要、MoA、标题、规划、反思、goal knowledge、子 Agent、心跳、群聊、Skill Workshop。全仓 `grep acompletion` / `litellm.` 结果在结果文件列出，除 router 本身外为零。
3. **原生通道默认化**：
   - Claude 系列：provider 支持 `anthropic_messages` 时默认走原生。对用户的网关（当前 `api.monkeyapi.net`），加一次性探测：是否支持 `/v1/messages`；支持就默认原生，不支持就回退 OpenAI 兼容并在设置页显示原因。探测结果缓存，设置里可手动覆盖。
   - 原生模式下必须保住：提示缓存断点（沿用已移植的 `agent/prompt_caching.py`）、思考块及签名跨轮回传、工具调用之间的思考。
   - GPT 系列：Hermes 若有 Responses API 模式（以开工版本为准），同样按探测默认启用；没有就记录在结果文件，不自己造。
4. **token 计数**：去掉「字符数÷4」。优先用 provider 返回的 usage；估算用 Hermes 的估算器或 tiktoken，中文按实际编码算。

### 测试

- `test_model_router.py`：表驱动，覆盖上面每一种调用目的 × {仅网关, 仅原生 Anthropic, 两者都有} 三种配置，断言路由正确。**仅原生配置（无网关）下，交接摘要、MoA、压缩、标题都能成功**（这是现在的 bug）。
- 扩展假模型服务，增加 Anthropic Messages 端点：
  - 请求带 `cache_control` 断点，且第 2 轮稳定前缀不变；
  - 第 1 轮返回带签名的 thinking 块，第 2 轮请求原样带回；
  - tool_use / tool_result 配对正确。
- 网关探测：假服务分别模拟支持/不支持 `/v1/messages`，断言默认值和回退提示。
- token 估算：中英文混合样本与 tiktoken 结果误差在 ±15% 内。
- AST 检查：router 以外没有 `acompletion` / `completion` 调用。

---

## 7. H5 拆分 `server.py`

**先做（H0 之后第一个开工），由一个 owner 完成，纯机械搬移，不改行为。**

1. 开工前生成路由快照 `core/tests/snapshots/routes.json`：每个路由的方法、路径、参数、请求/响应模型、WebSocket 事件类型集合。
2. 按领域拆到 `core/atlas/api/*_router.py`（已有的沿用）；共享状态放进 `AppServices` 容器，用 FastAPI 依赖注入，不再用模块级全局。
3. `server.py` 只保留 app 工厂、生命周期、路由挂载、中间件；**目标不超过 800 行**，任何单个 router 文件不超过 1500 行。

### 测试

- `test_route_snapshot.py`：拆分后快照逐项一致。
- 后端全量 + 前端全量通过。

---

## 8. H6 错误处理

1. 在 `core/pyproject.toml` 启用 ruff `BLE001`（盲捕获）、`S110`（except-pass）、`S112`（except-continue）。现有违规生成基线文件，**不允许新增**。
2. 必须清零的范围：`engine/`、`agent/`、`models/`、`server.py` 及 `api/`、`gateway_service.py`、`heartbeat/`、`automation/`、`channels/`。处理方式三选一：缩小异常类型；`logger.exception` 后继续；或转成用户可见的 `run.recovery.notice` / API 错误。
3. 其余目录静默吞错至少要有 `logger.debug(..., exc_info=True)`。

### 测试

- `test_lint_gate.py`：跑 ruff，断言上述范围零违规、全仓不超过基线。
- 错误注入：通知库读失败、标题回调失败、MCP server 启动失败、压缩模型失败、渠道发送失败，各自断言有日志且界面收到可见提示，运行不中断。

---

## 9. H7 渠道来源任务的默认权限

> 这是用户已有的权限模式的**默认值**设置，不是安全审查。用户如不要，删掉本节即可。

1. 新配置 `gateway.default_permission_mode`，默认 `ask_writes`；每个渠道绑定、每个常驻 Agent 可单独覆盖。桌面会话的默认值不变。
2. 渠道任务遇到需要审批时：审批请求发回原渠道（可回复 `允许` / `拒绝`），同时出现在桌面审批卡片里，先回复的生效；超时（默认 10 分钟）按拒绝处理，并告知渠道。
3. 心跳、自动化由用户自己创建的，沿用创建时选择的权限模式。

### 测试

- 假渠道 adapter：入站任务触发写文件 → 渠道收到审批请求 → 回复允许 → 执行完成并回执；回复拒绝 → 不执行；超时 → 拒绝并通知；桌面先批准时渠道收到「已在桌面批准」。
- 覆盖配置生效测试。

---

## 10. H8 启动速度

1. 目标：后端冷启动到 `/api/health` 返回 ok **不超过 5 秒**（主机，假模型配置）。
2. 做法：MCP server、LSP、渠道网关、DBOS 非关键初始化改为 health 之后后台启动；health 增加 `components` 字段报告每项状态（`starting / ready / failed`）。DBOS 迁移只在版本变化时跑。
3. Electron `backendProcess.ts`：不再用固定 15 秒超时杀进程；改为「进程活着且 health 有进展就继续等」，总上限 120 秒，界面显示启动进度；真失败时显示后端日志末尾 50 行。
4. 前端在 MCP 等组件未就绪时照常可用，相关入口显示「启动中」。

### 测试

- `test_startup_time.py`：冷启动 3 次中位数不超过 5 秒（标 `integration`）。
- `backendProcess` 单测：慢启动（模拟 30 秒）不被杀；进程退出时立即报错；超过上限报错。
- health `components` 字段测试。

---

## 11. H9 无头 CLI

参考 Claude Code 的 `-p` / `--output-format stream-json` 和 Codex 的 `exec --json`（以当月官方文档为准）：

```
atlas run -p "<任务>" [--workspace DIR] [--model ID] [--permission-mode MODE]
          [--output-format text|json|stream-json] [--max-turns N] [--resume ID]
```

- 进程内直接启动运行时，不需要 Electron，也不需要另起后端；也支持 `--server URL` 连已运行的后端。
- `stream-json` 每行一个事件，事件就是现有 WebSocket 事件；最后一行是汇总（结果、用量、耗时、改动文件）。
- 退出码：0 成功，1 运行失败，2 参数错误，3 需要审批但处于非交互模式（`ask_*` 模式下无人审批即按拒绝）。
- 加 `atlas doctor`（H2 的 sessions 检查 + 配置/模型连通/MCP 状态）。

### 测试

- 假模型下：`atlas run -p` 完成一个改文件任务，断言退出码、stream-json 每行可解析、汇总字段完整；`--resume` 接着上一会话；非交互需要审批时退出码 3。
- 在 Windows 上带中文路径的工作区跑通。

---

## 12. H10 测试体系 + 真实模型冒烟

### H10.1 测试分层

- pytest marker：`unit`（默认）、`integration`、`desktop`（真实桌面，单独跑，失败自动重试一次）、`live`（真实模型，必须 `ATLAS_LIVE=1` 才跑）。
- 引入 `pytest-xdist` 并行。目标：主机上 `unit` 不超过 3 分钟，`unit + integration` 不超过 10 分钟。Codex 终端会杀长命令，所以分组命令要写进 `docs/plan/EXECUTION-GUIDE.md`。
- 修掉已知的偶发失败（`test_real_desktop_observe_input_clipboard_and_window_management` 移到 `desktop` 组）。

### H10.2 真实模型冒烟（Atlas 自己，不比别家）

> 需要用户在 Atlas 设置里配好的模型（当前网关默认模型）。**API key 不进仓库、不进日志、不发给 Agent。** 预算上限由环境变量 `ATLAS_LIVE_BUDGET_USD` 设定（默认 5 美元），超了立即停并报告。如果没有可用的 key，跳过本节，在结果文件写明「待用户执行」，并给出一条命令让用户自己跑。

用 H9 的 `atlas run` 驱动，任务放 `tests/live/<编号>/`（起始文件 + `task.md` 中文原话 + `check.py`）：

| # | 场景 |
|---|---|
| 01 | 小 Python 仓库有一个失败测试，修到通过 |
| 02 | 小 TS 仓库加一个函数并补测试 |
| 03 | 改 CRLF + 中文路径 + UTF-8 BOM 文件，换行和编码保持不变 |
| 04 | 运行 PowerShell 命令、读输出、据此改文件 |
| 05 | 4 轮追加约束，最后检查第 1 轮约束仍被遵守 |
| 06 | 强制触发自动压缩后继续把任务做对 |
| 07 | 三个互不相关的子任务交给子 Agent 并行，汇总正确 |
| 08 | 计划模式出计划，再按计划执行 |
| 09 | 做到一半回退到某一步再继续 |
| 10 | 运行中第 N 秒插话改需求 |
| 11 | 通过 MCP filesystem 工具读文件回答问题 |
| 12 | Webhook 渠道入站任务（`ask_writes`）→ 审批 → 执行 → 渠道回执 |

每个跑 1 次（失败的重跑 1 次确认）。**通过标准：至少 10/12 通过**；每个失败必须给出根因，能修的本波修掉并重跑，修不了的写进 `tasks/feedback/INBOX.md`。

如果 H4 探测到网关支持原生 Claude 通道，01、05、06 三个场景用原生和兼容两种模式各跑一次，记录用量与缓存命中率对比。

---

## 13. H11 收尾与验收

1. 再跑 `baseline_metrics.py`，写 `tasks/results/ATLAS-H1-after.json`，在结果文件中做前后对比表。
2. 更新 `docs/plan/VENDORED.md`、`docs/plan/DATA-OWNERS.md`、`docs/plan/EXECUTION-GUIDE.md`、`README.md`（项目结构里的「LangGraph orchestrator」等过时描述一并改掉）。
3. 写 `tasks/results/ATLAS-H1-CORE-HARDENING.result.md`，把 `tasks/CURRENT.md` 改为 `AWAITING_REVIEW`，push，核对本地与远端 head 一致，停。

### 验收清单（独立 review 逐条核对）

| # | 标准 |
|---|---|
| A1 | `core/atlas/` 无 Hermes 私有属性赋值、无 Hermes 身份字符串替换（AST 测试绿） |
| A2 | fork 补丁全部登记在 `ATLAS_PATCHES.md` 且各有测试 |
| A3 | 对话记录只写 `SessionDB`；迁移、分叉、回退、删除后 `atlas doctor sessions` 零不一致 |
| A4 | `run()` 改为 `RunRequest`/`RunCallbacks`；`agent/__init__.py` 拆分后单文件不超过 1200 行 |
| A5 | 运行期间不改 `os.environ`；MCP 只注册一次；同会话复用 AIAgent；无 50ms 轮询；futures 不泄漏 |
| A6 | 8 会话并发隔离测试连续 20 次通过 |
| A7 | router 以外零 `acompletion`；仅原生配置下交接/MoA/压缩/标题可用 |
| A8 | 原生 Anthropic 通道：缓存断点、思考签名回传测试通过；网关探测与回退可用 |
| A9 | `server.py` 不超过 800 行，路由快照一致 |
| A10 | 指定范围 ruff 盲捕获零违规，全仓不超过基线 |
| A11 | 渠道任务默认 `ask_writes`，审批往返测试通过（若用户删除 H7 则跳过） |
| A12 | 冷启动中位数不超过 5 秒；Electron 慢启动不被杀 |
| A13 | `atlas run -p` stream-json/退出码/resume 测试通过 |
| A14 | `unit` 不超过 3 分钟，`unit+integration` 不超过 10 分钟；后端、前端全量通过 |
| A15 | 真实模型冒烟至少 10/12，失败均有根因（或注明待用户执行） |
| A16 | 前端协议、API 路径、事件类型未变（前端测试全绿 + 路由快照） |

---

## 14. 建议的施工顺序与并行 lane

```
H0（主机 WIP 保存 + 基线）
  └→ H5 server 拆分（单 owner，先做，减少后续冲突）
       └→ 并行：
            L1  H1 fork 接口 + hermes_runtime 去补丁（hermes_runtime owner）
            L2  H4 模型路由 + 原生通道 + token 计数
            L3  H6 错误处理（按目录分给多个子代理）
            L4  H8 启动速度（后端 lifespan + Electron）
            L5  H9 无头 CLI
            L6  H10.1 测试分层与提速
       └→ H3 并发与资源（依赖 L1，由 hermes_runtime owner 合并）
       └→ H2 单一数据源 + run() 拆分（依赖 H1、H3）
       └→ H7 渠道默认权限
  └→ H10.2 真实模型冒烟（依赖 H9）
  └→ H11 收尾
```

---

## 15. 独立验收（新开一个 Sol 对话）

提示词：

```
你是 Atlas 的独立验收人。读 tasks/taskbooks/ATLAS-H1-CORE-HARDENING.md 和
tasks/results/ATLAS-H1-CORE-HARDENING.result.md。逐条核对第 13 节 A1–A16：
每条都要自己跑对应测试或命令、看代码证实，不接受结果文件的自述。
重点抽查：H2 迁移是否会丢数据（用 fixture 库亲自迁移一次）、H3 并发测试
是否真的并发（不是串行跑）、H4 是否还有绕过 router 的模型调用、H5 是否改了行为。
发现问题直接修，修完补测试。写 tasks/reviews/ATLAS-H1-CORE-HARDENING.review.md，
通过则 CURRENT 改为 REVIEW_PASSED，push。
```
