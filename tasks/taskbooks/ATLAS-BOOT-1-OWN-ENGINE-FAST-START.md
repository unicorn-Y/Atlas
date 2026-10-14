# BOOT-1：摘掉 Hermes 依赖 + 秒级启动 + 常驻后端

> 交给：主机 Codex（强度「高」，子代理最多 4 个，按文件分工）
> 基线：`origin/memory-v1` = `7826e91`
> 工作树：`D:\atlas-boot`，分支 `boot-1`（`git -C D:\Atlas worktree add D:\atlas-boot -b boot-1 origin/memory-v1`）
> 结果：`tasks/reviews/BOOT-1.result.md`（前后实测数字、搬进来的文件清单、删掉的东西），Claude 审查后合并
> 写于 2026-10-15，Claude（笔记本）

按 A → B → C 顺序做，每个阶段单独提交。一次做完，不要中途停下来等确认。测试不搞膨胀：只修因为改了 import 路径而坏掉的测试，不另写新测试套件，靠最后的实测和日志验收。

---

## 0. 现状（Claude 已在主机实测，2026-10-15 01:45）

| 阶段 | 耗时 | 在干嘛 |
|---|---|---|
| 启动器 `scripts/atlas-update.mjs --launch-only` | 约 3 秒 | git rev-parse、`core/scripts/setup_hermes.py`（约 2 秒）、`python -m atlas.upstream post-merge`（约 1.5 秒），全部做完才拉起 Electron |
| `import atlas.server` | 2.2 秒（热缓存） | `atlas.api.application` 1.25 秒、fastapi 0.38 秒、`atlas.agent.capabilities` 0.29 秒 |
| `python -m atlas.desktop_entry` → 第一次 health 有响应 | 4.3 秒 | |
| → health 全部就绪 | 8.5 秒 | 最后等的是 `mcp`、`engine_registrations`（多出约 4 秒） |
| 合计：双击 → 能发消息 | 约 12 秒（热缓存） | 冷开机更慢；ZCode 约 5 秒 |

另外两个问题：
- `frontend/src/main/electron.ts` 中，`ensureBackendRunning` 一旦失败就 `dialog.showErrorBox` + `app.quit()`。任何一次启动失败都会直接把整个程序关掉。
- 10-14 17:10 有过这样一次：旧后端还在关闭（DBOS 在 join worker 线程，用了 20 秒以上），28 秒内又被启动了两次。新后端只打出 `config.loaded`，之后再没有任何输出，最后没有一个 Atlas 进程活着。也就是说，旧后端还没退干净时新的就起来了，这种情况没有处理。

## 1. 目标（验收数字）

| 指标 | 目标 |
|---|---|
| 双击 → 窗口出现 | ≤ 1 秒 |
| 双击 → 能发出第一条消息（热缓存，后端不常驻） | ≤ 3 秒 |
| 冷开机后第一次打开 | ≤ 5 秒（不比 ZCode 慢） |
| 常驻后端已在运行时打开窗口 → 能发消息 | ≤ 1 秒 |
| 任何启动失败 | 不退出程序，界面内提示 + 自动重试 + 「重试」按钮 + 「查看日志」 |
| 运行时依赖 | 不再需要 `hermes-agent` 仓库，也不再需要 `pip install -e` 它 |

---

## 阶段 A：摘掉 Hermes 依赖（把用到的代码搬进 Atlas）

### A1. 现在依赖了什么（Claude 已列出，Codex 要以运行时普查结果为准）

`core/atlas` 中有 19 个文件直接 import Hermes。按模块分：

- **工具**：`tools.registry`、`toolsets`、`model_tools._run_async`、`tools.mcp_tool_discovery/common/lifecycle`、`tools.terminal_tool`、`tools.terminal_scope`、`tools.file_tools`、`tools.vision_tools`、`tools.interrupt`、`tools.browser_tool*`、`tools.browser_supervisor`、`tools.computer_use.*`
  - 引用方：`engine/tool_registry.py`、`engine/hermes_runtime.py`、`engine/steer_dispatch.py`、`tools/browser_use_compat.py`、`tools/x2/browser.py`、`tools/x2/computer.py`、`review/engine.py`
- **会话存储**：`hermes_state.SessionDB`、`hermes_state_wal`
  - 引用方：`engine/session_sync.py`、`engine/hermes_runtime.py`、`channels/delivery.py`、`channels/ingress.py`
- **辅助模型 / 模型元数据**：`agent.auxiliary_client`（7448 行，只用到 `call_llm` 等少数几个入口）、`agent.turn_usage`、`agent.model_metadata`、`agent.ssl_verify`、`agent.process_bootstrap`、`agent.anthropic_adapter`、`agent.azure_identity_adapter`
  - 引用方：`kernel/model_call.py`、`models/router.py`、`models/network_transport.py`、`models/tokens.py`
- **其余 agent 部件**：`agent.title_generator`、`agent.plan_prompt`、`agent.prompt_builder`、`agent.runtime_cwd`、`agent.agent_hooks`、`agent.context_breakdown`、`agent.conversation_compression*`、`agent.context_compressor`、`agent.agent_runtime_helpers`、`agent.inline_tool_executors`、`agent.lsp`、`agent.vault_store`
- **hermes_cli**：`plugins`、`plugins_manifest`、`goals`、`goal_command`、`local_runtime.recovery`、`browser_runtime`、`sqlite_runtime`、`config`
- **gateway**：`gateway.warning_notifications.DiagnosticText`
- **整个 Hermes 循环**：`run_agent.AIAgent`
  - 在 `engine/hermes_runtime.py::_agent_factory` 中，供 `engine.kernel = "hermes"` 的回落路径使用，**另外压缩（compression）还在用它**（约第 857 行）。

Hermes 整体约 53 万行（tools 10.7 万、agent 11.7 万、hermes_cli 23.6 万、plugins 6.8 万），Atlas 只用其中一小部分。**不要整包拷贝。**

### A2. 做法：拿来主义，按实际用到的范围搬

1. **运行时普查**（先做）：在当前 `memory-v1` 上起后端，跑一轮真实对话，覆盖终端、读写文件、浏览器、MCP 工具、看图、computer-use doctor、标题生成、一次压缩、goal 命令。然后从 `sys.modules` 导出所有来自 `D:\hermes-agent` 的模块，再和静态 import 闭包取并集，得到「必须搬」清单，写进结果文件。
2. **搬进 `core/atlas/engine_core/`**（名字可以改，但要统一）：
   - 保留原来的子目录结构（`tools/`、`agent/`、`state/` 等），import 全部改成 `atlas.engine_core.*`。
   - 每个文件头部加一行来源：`# ported from hermes-agent@c9e076b <原路径> (MIT)`。
   - 根目录放一份 `PORTED.md`：原路径 → 新路径 → 来源提交。
3. **砍掉用不上的**：
   - 56 个 Hermes 插件（image_gen、video_gen、各家 web provider 等）只保留 Atlas 配置里实际启用、实际用到的；其余不搬，也不注册。
   - Nous、OpenRouter 认证探测，「run: hermes setup / hermes auth」这类提示，全部去掉，换成 Atlas 自己的模型配置（`atlas.models`）。
   - `auxiliary_client` 只保留被调用到的入口和它的依赖，不整份拷贝 7448 行。
4. **去掉 `engine.kernel = "hermes"` 回落和 `run_agent.AIAgent`**：
   - 压缩改走 Atlas 内核的 `kernel/model_call.py`。
   - ⚠ `D:\atlas-ctx-opt`（分支 `ctx-opt`，任务 CTX-1）正在改 `kernel/context.py` 和压缩逻辑。**本任务不要碰 `kernel/context.py`。** 压缩入口只做最小改动：把原来 AIAgent 做的那一次摘要调用换成 `model_call`，提示词照搬原样。合并时如有冲突，以 CTX-1 为准。
5. **数据兼容（必须）**：现有的 `engine/state.db`、`engine/config.yaml`，以及 `HERMES_HOME` 所指的目录，要能原样读写。表结构和路径都不变，旧会话必须全部能打开。环境变量 `HERMES_*` 可以保留兼容读取，新代码统一用 `ATLAS_*`。
6. **删除**：
   - `core/scripts/setup_hermes.py`
   - `core/pyproject.toml` 中的 `[tool.atlas.hermes]`
   - `atlas doctor` 中的 hermes 检查
   - 启动器里的 setup_hermes 调用
   - `start-atlas.bat` 中对 setup_hermes 的调用
   - `engine/hermes_runtime.py` 可以改名为 `engine/runtime.py`（可选，改了就要把引用一起改完）

   完成标准：在 `core/atlas` 下 grep `^\s*(from|import) (hermes_cli|hermes_state|run_agent|model_tools|toolsets|gateway|agent|tools)\b`，结果为 0。
7. **追新机制改造**（`core/atlas/upstream`）：Hermes 上游不再合进 fork，改成「对 PORTED.md 里列出的文件，比较上游从来源提交到最新提交的 diff，生成报告，在设置页显示有哪些可抄的改动」，人工决定要不要搬。原来的自动合并流程对 Hermes 停用。
8. **验收 A**：
   - 卸载 hermes-agent：`pip uninstall hermes-agent`，并把 `D:\hermes-agent` 改名，确保代码不可能再引用到它。
   - 在这个状态下，起后端，跑一遍 A2 第 1 步的那一轮真实对话，全部正常；旧会话能打开；`backend.log` 里没有 Hermes 的认证或插件注册日志。

---

## 阶段 B：秒级启动

### B1. 启动器不挡路（`scripts/atlas-update.mjs`）
- `--launch-only`：直接拉起 Electron，不跑 git、setup_hermes（A 阶段已删）、post-merge。
- `post-merge` 只在真的拉到新提交之后才跑（`update:apply` 流程里），而且是在后台跑。
- 「有没有更新」的检查放到 Electron 起来之后，在后台进行（已有的 UpdateBanner 照用）。

### B2. 后端「能聊就算就绪」（参考 Claude Code：界面先出来，MCP 在后台连，连好一个亮一个）
- 把 health 分成两层：
  - **`ready`**：只要求 HTTP 已经开始监听 + 模型配置已加载 + 内核和内置工具已注册。
  - **`components`**：其余组件各自报告进度。
- 不阻塞 `ready` 的组件：MCP、插件、技能扫描、telegram、channels、automation、scheduler、DBOS、记忆（memory library / reflector）、upstream、LSP、浏览器监管。它们全部在后台启动；用户点到对应功能但它还没好时，提示「正在加载」。
  - 用到某个 MCP 工具时，如果它还没连上：等它连上（设上限），超时就返回明确的错误。
- 大库延迟导入：用 `python -X importtime -c "import atlas.server"` 找出 >50ms 的导入链，改成用到时才导入。重点是 `atlas.api.application`（1.25 秒）、`atlas.agent.capabilities`。router 能延迟注册的就延迟注册。
- 目标：`desktop_entry` 启动 → `ready` ≤ 1.5 秒（热缓存）。

### B3. Electron 端（`frontend/src/main/backendProcess.ts`、`electron.ts`）
- **失败不退出**：删掉 `showErrorBox` + `app.quit()`，改成广播一个失败状态给渲染进程。界面上显示原因、日志尾部、「重试」和「打开日志目录」按钮，并自动重试（1s / 3s / 10s 退避，最多 3 次，之后只留手动重试）。
- **旧后端没退干净**：启动前如果 8765 端口被占，或者 pid 文件里记录的进程还活着：
  - 如果是自己的后端、而且令牌对得上，就直接连上去。
  - 如果是正在关闭的旧后端，等它退出（最多 30 秒，界面显示「正在关闭上一次的后台」），超时就 `taskkill /T /F`。
  - 如果是别的程序占着端口，提示用户是哪个进程。
  - 后端启动时把 pid 写进 `data/runtime/backend.pid`。
- **关闭要快**：后端 shutdown 中 DBOS join 线程那一步花了 20 秒以上。改成设超时，到时间直接强制退出，不在退出时做清理以外的工作。
- **渲染进程**：`app-*.js` 有 2.9MB。各页面（设置、工作台、技能库、记忆库、图表、katex、mermaid/cytoscape/elk）改成按需 `import()`，首屏只加载聊天页。窗口用 `show: false` + `ready-to-show`，先显示骨架屏。

### B4. 验收 B
- 写 `scripts/diag/boot_timing.mjs`（或 .py），自动测 5 次并取中位数，报告以下时间点：双击 → 窗口出现、→ 后端 `ready`、→ 第一条消息开始流式输出。
- 冷缓存测法：重启电脑后的第一次打开，测 1 次。
- 结果写进结果文件，并和 ZCode 对比：用同一台机器，用录屏或秒表都行，写清楚测法。
- 故障演练，三项都要能自行恢复，不弹窗退出：
  1. 连点两下桌面图标；
  2. 运行中手动杀掉后端进程；
  3. 让 8765 被一个无关进程占用。

---

## 阶段 C：常驻后端（托盘）

参考：主机上已经常驻运行的 `openclaw gateway --port 18789`、Hermes gateway；Electron 的 `Tray`、`app.setLoginItemSettings`。

- 后端由一个常驻的托盘进程托管：开机自启（设置页可以关），关掉窗口不退出后端；只有托盘菜单「退出 Atlas」才真正停掉后端。
- 令牌：后端第一次启动时生成，存到 `data/runtime/api-token`（只有当前用户能读）。新打开的窗口读这个文件，直接连已经在运行的后端。现有的「外部后端必须接受本窗口令牌」校验改成用这份共享令牌。
- 更新：`update:apply` 时先让后端优雅退出，再更新，再重新拉起后端和窗口。不能出现旧后端继续跑旧代码的情况（10-06 吃过这个亏）。
- 托盘菜单：打开 Atlas、后台状态（各组件）、重启后台、查看日志、退出。
- 验收 C：
  - 常驻状态下，双击 → 能发消息 ≤ 1 秒；
  - 关掉窗口再打开，会话和正在进行的 run 都还在；
  - 点「立即更新」后，新代码生效（看版本号）；
  - 关闭开机自启后，重启电脑，Atlas 不会自己起来。

---

## 交付清单（写进 `tasks/reviews/BOOT-1.result.md`）
1. 前后对比表：使用 §1 的全部指标，热缓存 5 次中位数 + 冷缓存 1 次，并附 ZCode 的对比数据。
2. 运行时普查清单，以及搬进来的文件清单（`PORTED.md` 的摘要），说明哪些没搬、为什么。
3. 删掉了什么（插件、认证、setup_hermes、回落路径）。
4. 那一轮真实对话的结果：各工具是否正常、旧会话能否打开。
5. 和 CTX-1 可能冲突的文件列表。
6. 已知遗留问题。

完成后提交、推送 `boot-1`，通知 Claude 审查合并。
