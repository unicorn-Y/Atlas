# Atlas 执行指南（任何 Agent 通用）

## 一、项目和环境

- 仓库：`github.com/unicorn-Y/Atlas`，分支 `main`。
- 结构：
  - `core/`：Python 后端（FastAPI + uvicorn，端口 8765；litellm 调模型；LangGraph；DBOS；APScheduler）。
  - `frontend/`：Electron + React + Vite（Tailwind v4 + Radix）。
  - `backend-adapter/`：前端调用后端的 TypeScript 客户端。
- 用户的两台机器（细节见 `tasks/HANDOFF.md`）：
  - 笔记本：`C:\Users\youdu\Desktop\Atlas`，venv 在 `core/.venv`（Python 3.12；C1 起升到 3.14，因为 Hermes 内核需要）。
  - 主机：`ssh zhuji`，`D:\Atlas`，用户在这里用 Codex 桌面端；C1 起另有 Hermes fork 克隆在 `D:\hermes-agent`。
- 用户用的模型：设置里配的 OpenAI 兼容网关（`api.monkeyapi.net`），默认 Claude 系列模型。

### 常用命令（在仓库根目录）

```bash
# 装依赖
core/.venv/Scripts/python.exe -m pip install -q -e core
npm ci   # 开发版在跑时不要执行

# 后端
core/.venv/Scripts/python.exe -m uvicorn atlas.server:app --host 127.0.0.1 --port 8765 --app-dir core

# 前端（开发）
cd frontend && npx vite --host 127.0.0.1
cd frontend && npx tsc -p tsconfig.electron.json && VITE_DEV_SERVER_URL=http://127.0.0.1:5173 ATLAS_PYTHON=../core/.venv/Scripts/python.exe ../node_modules/electron/dist/electron.exe . --remote-debugging-port=9335

# 后端默认快测（unit lane，dev 快查；验收计时用 core/scripts/run_h1r_r6_gates.ps1，见第八节）
cd core && .venv/Scripts/python.exe -m pytest -q -n auto --dist loadscope

# 前端检查
cd frontend && npx tsc -p tsconfig.renderer.json --noEmit && npx tsc -p tsconfig.electron.json --noEmit && npx vitest run && npx vite build
```

- `tests/test_computer_use.py::test_real_desktop_observe_input_clipboard_and_window_management` 会操作真实桌面，只在交互式 Windows 桌面通过 `-m desktop` 单独运行。
- 重启后端前先按端口找到进程（`Get-NetTCPConnection -LocalPort 8765`），确认是 uvicorn 再停。

## 二、代码地图（改之前先读对应文件）

| 要改什么 | 看哪里 |
| --- | --- |
| **新内核（C1 起）** | `core/atlas/engine/`（适配层、Atlas 工具注册、权限插件）+ fork `D:\hermes-agent`（`run_agent.py`、`agent/`、`tools/`），见第三点六节 |
| 旧 Agent 主循环（C2 删除） | `core/atlas/agent/__init__.py`：`acompletion(**kwargs, stream=True)` 在第 940 行附近；系统消息在第 1952 行起拼装；工具执行和审批在第 1050–1240 行 |
| 权限判断 | 同上：`permission_mode`（`full_access` / `ask_writes` / `read_only`）、`is_write` 集合、`APPROVAL_REQUIRED_TOOLS` |
| 工具输出截断 | 同上第 1590 行附近 `externalize_tool_output` |
| 子任务 / Worker | `_run_atlas_subtask`、`run(worker=True)`（`agent/__init__.py`）；`agent/orchestrator.py` |
| 工具 | `core/atlas/tools/`：`local_execution.py`（文件、命令、git、进程）、`computer_use.py`、`web_extract.py`、`mcp_client.py`、`custom_tools.py` |
| 浏览器 | `core/atlas/capabilities/browser/browser_use.py`；chrome-devtools / playwright MCP |
| 调度和事件触发 | `core/atlas/scheduler/__init__.py`（`TriggerType.EVENT`、`dispatch_event`、文件监控 `_start_file_watchers`） |
| Hooks | `core/atlas/runtime/hooks.py` |
| HTTP / WS 接口 | `core/atlas/server.py`（6800+ 行）；WS 在 `/ws/chat` |
| 本机接口安全 | `core/atlas/origin_guard.py` |
| 记忆（冻结） | `core/atlas/memory/` |
| 凭据 | `keyring`（参考 `core/atlas/telegram.py` 的写法） |
| 前端事件解析 | `frontend/src/renderer/services/runtimeEvents.ts`（已知事件列表 `known`） |
| 时间线（把事件变成人能读的步骤） | `frontend/src/renderer/components/timeline.ts` |
| 对话里的卡片（审批、提问、信任、Worker 组…） | `frontend/src/renderer/components/ConversationActivity.tsx` |
| 状态管理 | `frontend/src/renderer/store/useAtlasStore.ts` |
| 设置弹窗（左侧分类） | `frontend/src/renderer/App.tsx` 第 850 行附近 `sheet === '…'` |
| 设置面板样例 | `frontend/src/renderer/pages/TelegramPanel.tsx`（Tailwind 写法，推荐照抄风格） |
| 后端客户端 | `backend-adapter/src/client.ts`（HTTP 方法；WS 发消息用 `sendOnRun`）、`types.ts` |
| 事件类型 | `frontend/src/types/runtime.ts`（`AgentEventType`） |

新增一个运行事件的完整链路：后端发事件 → `runtimeEvents.ts` 的 `known` 加上 → `types/runtime.ts` 加类型 → `timeline.ts` 处理 → `ConversationActivity.tsx` 渲染卡片 → 需要用户回应的，`client.ts` 加 `sendOnRun` 方法、store 加动作、`applyRuntimeEvent` 里把状态设成 `waiting`。

## 三、规则

1. **中文**：界面文字、错误提示、给用户的回复都用中文；写给用户的文字要让不懂技术的人也看得懂。
2. **接口名、事件名、字段名严格按任务书**；确需偏离，写进结果文件。
3. **安全**：
   - 所有 HTTP / WS 都过 OriginGuard，只能新增受信方式，不能放宽。
   - 返回用户文件或第三方 HTML 的接口必须带沙箱 CSP（参考已有的 `/api/workspace/raw`）。
   - Electron 只给主页面注入 token，子框架（iframe、webview）拿不到。
   - 路径参数一律规范化后检查是否在允许目录内；不要把用户输入直接拼进路径或命令。
   - 访问网络的新功能要防内网访问（参考 `web_extract.py` 的 `_validate_url`）。
   - 密钥、令牌存系统凭据库（keyring），接口永远不返回密钥原文。
4. **测试**：不写用户真实数据目录；不在仓库里建临时目录；不依赖真实网络（用 mock）。
5. **不逐波用真实模型实测**（用户 2026-10-01 决定，太费配额）：施工和验收都用假模型服务（Hermes 的 `tests/fakes/fake_llm_provider.py` 或同类），把模型回复写成脚本，断言真实行为。mock 测不到的问题（比如第五波 Worker 收不到任务）要靠「端到端走真实代码路径 + 假模型」来防：从 WebSocket 发 `run.start`，一路走到工具执行和事件输出，只把模型换成假的。真实模型实测集中在 C6 之后的「实测」阶段。
6. **提交**：每节一个提交，提交信息写清「为什么」；推送前 `git pull --rebase`。不要提交 `frontend/scripts/.cdp.mjs`。
7. **结果文件**：`tasks/results/<任务书名>.result.md`：每节做了什么、偏差、已知限制、手动验证方法、全量测试的汇总行原文。

## 三点五、怎么搬代码（每一节都按这个做）

1. **拿到来源**：浅克隆到系统临时目录（不要放进 Atlas 仓库），记下提交号。
   ```bash
   git clone --depth 1 https://github.com/NousResearch/hermes-agent.git "$TEMP/hermes-src"
   git -C "$TEMP/hermes-src" log -1 --format=%H
   ```
2. **先读完再搬**：读任务书点名的文件，以及它 import 的同目录兄弟文件；读来源项目对应的 `AGENTS.md`（Hermes 每个目录都有）和测试。
3. **只搬需要的部分**：Hermes 是「门面 + 兄弟文件」结构，耦合重。拿函数、数据结构、规则表，接到 Atlas 已有的位置上；不要把整个包连带依赖拖进来。
   **但规则表、模式库、检测器这类「数据密集」的文件必须整份拷贝**，只改环境相关的几行，**不得自己重写一个缩水版**。W06 的教训：任务书要求搬 Hermes 1540 行的危险命令识别，首版交付的是 36 行自写正则，漏掉了 `rm -rf ~`、`git push --force`、`curl | sh` 等大半规则。验收时对比来源文件和搬入文件的规则数量。
4. **替换环境依赖**：
   - Hermes 的配置（`~/.hermes/config.yaml`、`get_hermes_home()`、`hermes_cli.config_defaults`）→ Atlas 的 `atlas.config`（`get_config()`）和数据目录。
   - Hermes 的会话键（`session_key`）→ Atlas 的 `run_id` / `conversation_id`。
   - Hermes 的事件和请求（`tui_gateway` 的 `approval`、`clarify` 等）→ Atlas 的运行事件（`approval.required`、`input.required`…）。
   - Hermes 的提示词里提到 Hermes 的地方改成 Atlas。
5. **文件头**写明来源：
   ```python
   # Ported from NousResearch/hermes-agent@12e4d3e:tools/approval_smart.py (MIT, (c) Nous Research).
   # Changes: wired to Atlas run context; Chinese user-facing messages.
   ```
   MIT / Apache 要求保留原版权声明：在 `THIRD_PARTY_NOTICES.md`（仓库根目录，没有就建）里附上来源项目的 LICENSE 全文，每个项目一次。
6. **测试一起搬**：来源项目对应的测试改成 Atlas 的接口一起搬过来；来源没有测试的部分自己补。
7. **登记**：在 `docs/plan/VENDORED.md` 加一行。
8. **用户看得到的文字改成中文**。

## 三点六、Hermes 内核 fork 的工作流（C1 起）

- 内核在 `unicorn-Y/hermes-agent` 的 `atlas` 分支上；主机克隆在 `D:\hermes-agent`，远端 `origin` 是 fork，`upstream` 是 `NousResearch/hermes-agent`。
- **Atlas 专属的东西放在 Atlas 仓库**：适配层、Atlas 工具、权限插件都在 `core/atlas/engine/`，用 Hermes 的注册表和钩子接进去。**只有非改内核不可的才改 fork**，比如给 `terminal` 加 PowerShell、修换行。fork 改得越少，合并上游越容易。
- 开发：`core/.venv` 里 `pip install -e D:\hermes-agent`。发布：`core/pyproject.toml` 固定到 fork 上的某个提交号。改了 fork 之后，先推 fork，再把 Atlas 里的提交号改成新的，两边各一个提交。
- **合并上游**（看到 Hermes 出了新东西时）：
  ```bash
  cd D:\hermes-agent && git fetch upstream && git checkout atlas && git merge upstream/main
  ```
  解决冲突，跑 Hermes 的相关测试和 Atlas 全量测试，推 fork，更新 Atlas 里的提交号。
- **从其他家抄**（OpenCode、Pi、Codex 等）：照第三点五节，翻译成 Python。属于内核的放进 fork，属于 Atlas 的放进 `core/atlas/engine/`。文件头写来源，并登记到 VENDORED.md。

Atlas C1 当前命令（PowerShell）：

```powershell
# 首次克隆；已有仓库时只 fetch，不覆盖工作树
git clone https://github.com/unicorn-Y/hermes-agent.git D:\hermes-agent
git -C D:\hermes-agent remote add upstream https://github.com/NousResearch/hermes-agent.git
git -C D:\hermes-agent fetch upstream main
git -C D:\hermes-agent switch -C atlas upstream/main

# 仅在确认 fork 工作树干净后更新；先 rebase，再提交推送
git -C D:\hermes-agent fetch origin
git -C D:\hermes-agent pull --rebase origin atlas
git -C D:\hermes-agent add <改动路径>
git -C D:\hermes-agent commit -m "fix: <说明原因>"
git -C D:\hermes-agent push origin atlas

# Atlas 中更新固定提交号（每次 fork 推送后单独提交）
# core/pyproject.toml: hermes-agent @ git+https://github.com/unicorn-Y/hermes-agent.git@<commit>

# 同步 Hermes 上游
git -C D:\hermes-agent fetch upstream
git -C D:\hermes-agent switch atlas
git -C D:\hermes-agent merge upstream/main
```

依赖固定到 `atlas` 分支的提交号；开发验证可在 `core/.venv` 安装本机 `D:\hermes-agent` editable 版本。不要将 Atlas 专属适配放入 fork。

## 四、交付前自检

- [ ] 后端全量测试跑完并通过（汇总行写进结果文件）
- [ ] 前端四项检查通过（tsc ×2、vitest、vite build）
- [ ] 新接口都有 OriginGuard 测试（无 token 的外部 Origin 被拒）
- [ ] 任务书的假模型端到端测试都在，并且通过
- [ ] `docs/plan/CORE-PARITY.md` 本波的行更新了状态和提交号；界面功能有变化的同步改 `docs/PARITY.md`
- [ ] 结果文件写好

## 五、验收清单（每一波交付后，由 Sol 执行）

验收方不只是读代码：**自己跑全量测试，自己用假模型把任务书的端到端测试跑一遍**，对照 CORE-PARITY 里本波的每一行逐项检查。**不用真实模型。** 发现的问题直接修，修完补测试，记进验收记录。

端到端隔离做法：独立 `ATLAS_DATA_DIR`（复制 `config/atlas.toml`，删掉所有 `[tools.servers.*]`）、`ATLAS_SCHEDULER_ENABLED=false`、独立端口（如 8775）、临时工作目录和假文件、假模型服务；用一个小脚本通过 WebSocket `/ws/chat` 发 `run.start`（字段见 `backend-adapter/src/types.ts` 的 `RunStartRequest`），记录事件序列。**不要碰用户 8765 上的开发后端，也不要动用户的真实文件。**

1. 拉代码（Atlas 和 hermes fork 都拉），装新依赖，**自己跑一遍全量测试**，不要相信交付方的结果。先对比搬入代码和来源的规模，看有没有自写的缩水版。
2. 对照 CORE-PARITY 本波的每一行：「最强做法」写到的细节，代码里有没有、测试有没有覆盖。
3. 看已有功能有没有倒退（CORE-PARITY 第 11 节）。
4. 看权限有没有被绕过：新工具有没有进写操作集合；`ask_writes`、`read_only` 下是否正确拦截；子 Agent 的权限是否不超过父级。
5. 前端：四项检查自己跑；用无头 Edge 截图检查本波改过的界面。
6. 修掉的问题写进 `tasks/reviews/<任务书名>.review.md`，每条写清「问题、影响、修法」，再写验收结论和全量测试汇总行。
7. 提交推送 → 同步主机。

## 六、界面实测方法

- 无头浏览器：用 playwright-core 驱动 Edge（`C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`）打开 `http://127.0.0.1:5173`。需要选工作目录时，无头 Edge 里没有 `atlasDesktop`，会弹 `window.prompt`，用 `page.on('dialog', d => d.accept(路径))`。
- 需要 Electron 专有能力（webview、菜单、token 注入）时，通过 CDP 连 9335。
- 临时脚本放 `frontend/scripts/.wNN.mjs`，用完删掉。

## 七、踩过的坑

1. 长测试需要等待进程真正退出并保存日志、JUnit 和墙钟耗时；终端提前返回 session id 不代表命令完成。独立审查仍需亲自重跑验收门槛。
2. 测试之间会互相污染：单跑能过、全量挂，多半是模块级全局对象被上一个测试关掉或替换了。
3. Git Bash 的 heredoc 会吃掉反斜杠和中文：复杂改动用编辑工具或先写成 Python 脚本。
4. 开发版运行时不要 `npm ci`（会删掉正在用的依赖）。
5. 主机上 `package-lock.json` 常显示改动（只是换行符），拉代码前 `git checkout -- package-lock.json`。
6. Electron 以 `/api/health.status == "ok"` 作为就绪条件；`starting` 表示仍有组件未就绪，后端存活时继续轮询。
   - `components` 按组件报告 `starting`、`ready` 或 `failed`；`component_errors` 提供失败诊断。
   - 等待期间显示进度；失败时显示诊断和重试入口，不因组件仍为 `starting` 提前终止存活的后端进程。
   - 没有启用 MCP server 时，MCP 组件可直接就绪；共享 proxy 在首次 MCP 使用（含动态新增）时才构造客户端。
   - 冷启动耗时只按冷启动探针和 `test_startup_time.py` 的实测结果记录。

## 八、后端测试分层（H10.1 分层；H1R2 Lane I 归层收紧）

在 `D:\Atlas\core` 的 PowerShell 中运行。一次性安装开发测试依赖：

```powershell
uv sync --extra dev
```

### 分组与选择机制

pytest 默认选择 `unit`（`core/pyproject.toml` 的 `addopts = "-m unit"`）。分层判定在 `tests/conftest.py`：

- 未显式标注的测试按 unit 收集：只许 fake、进程内协作件和真实文件系统临时目录。
- 跨真实边界的整模块 / 整类（起真 uvicorn 子进程、真 git、真 LSP 子进程、真 Playwright 浏览器、真打包脚本等）在 `_INTEGRATION_MODULES` / `_INTEGRATION_CLASSES` 里显式列为 integration。
- 单个用例跨真实边界时，在该用例上写 `@pytest.mark.integration`（惯例见 `tests/test_cli_headless.py`；不要整模块挪，除非模块里所有用例都跨边界）。
- 真实桌面用例归 `desktop`（失败只自动重试一次）；真实模型调用归 `live`，必须显式 `@pytest.mark.live`，且只有 `ATLAS_LIVE=1` 时才会执行。

归层判据（诚实归层）：测试真正起了「真服务 / 真子进程 / 真浏览器 / 真 git」就归 integration；**慢不是归层理由**——只是慢但没有真实外部资源的用例留在 unit，用 `-Parallel` 压墙钟。

### 标准分组命令（gates 脚本，推荐）

```powershell
# 仓库根目录。默认全串行——这是验收证据模式。
core/scripts/run_h1r_r6_gates.ps1 -Gates unit
core/scripts/run_h1r_r6_gates.ps1 -Gates unit-integration

# 可选并行：-Parallel N 给 unit / unit-integration 两个 gate 加 -n N --dist loadscope；
# 输出写 unit-parN.log / unit-parN.xml（unit-integration 同理加 -parN 后缀），
# 与串行证据文件互不覆盖；并行模式下单测超时放宽为 600s（串行保持 300s）。
# 脚本开头会探测 pytest-xdist：venv 里没有时打印警告并自动退回串行，不会崩。
# desktop / frontend 两个 gate 永远串行。
core/scripts/run_h1r_r6_gates.ps1 -Gates unit,unit-integration -Parallel 8

# 其他参数：-OutputDirectory <dir> 改输出目录（默认 artifacts\h1r-r6）；
# -BasetempRoot <dir> 改 pytest basetemp；-ContinueOnFailure 失败不中断后续 gate。
```

每次运行会把各 gate 的 markers、墙钟、退出码和 junit 计数合并写进 `artifacts/h1r-r6/summary.json`（按 gate 名去重更新；并行模式因 gate 名带 `-parN` 后缀而与串行条目共存）。

### 每层的预算

| 层 | 选择表达式 | 墙钟预算 |
| --- | --- | --- |
| unit | `-m unit` | ≤ 180s |
| unit + integration | `-m "unit or integration"` | ≤ 600s |
| desktop | `-m desktop`（只在交互式 Windows 会话） | 不设预算，失败重试 1 次 |
| live | `-m live` + `ATLAS_LIVE=1` | 手动，无预算 |

超时或失败时保留相同选择的完整日志，先检查 `--durations=30` 和失败根因，再优化 setup、共享状态或串行瓶颈；不能通过删测试或加 skip 缩短数字。

### 计时纪律

验收计时由 controller 在无其他负载的空闲机器上**串行实测**（`-Parallel` 的并行结果只作吞吐参考，不是验收证据；并行输出文件名带 `-parN`，不会污染串行证据）。

TODO(controller): 串行实测后在此填入——unit=___s、unit+integration=___s（改动前诊断：unit 层 365.4s，见 artifacts/h1r-r6-diagnostic/summary.json）。

### 手动等价命令（不经过 gates 脚本时）

选择表达式必须与上表一致；串行是默认，加 `-n N --dist loadscope` 才并行。

```powershell
$run = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = "..\artifacts\test-runs\$run"
New-Item -ItemType Directory -Force $out | Out-Null
$timer = [Diagnostics.Stopwatch]::StartNew()
python -m pytest -q -m unit --timeout=300 --durations=30 `
  --junitxml="$out\unit.xml" --basetemp="$env:TEMP\atlas-gate-$run\unit" 2>&1 | Tee-Object "$out\unit.log"
$exitCode = $LASTEXITCODE
$timer.Stop()
"exit=$exitCode wall_seconds=$([math]::Round($timer.Elapsed.TotalSeconds, 1))"
```

`unit + integration` 的目标墙钟时间不超过 600 秒：

```powershell
python -m pytest -q -m "unit or integration" --timeout=300 --durations=30 `
  --junitxml="$out\unit-integration.xml" --basetemp="$env:TEMP\atlas-gate-$run\unit-integration" `
  2>&1 | Tee-Object "$out\unit-integration.log"
```

桌面 lane 只在用户可见的交互式 Windows 会话运行。目标桌面用例失败时只自动重试一次；其他测试不重试。

```powershell
python -m pytest -q -n 1 -m desktop --timeout=300 --durations=30 `
  --junitxml="$out\desktop.xml" 2>&1 | Tee-Object "$out\desktop.log"
```

真实模型 lane 必须显式启用。API 密钥只从本机环境/凭据读取，日志不得包含密钥或原始 provider 请求。

```powershell
$env:ATLAS_LIVE = '1'
python -m pytest -q -n 1 -m live --durations=25 `
  --junitxml="$out\live.xml" 2>&1 | Tee-Object "$out\live.log"
$exitCode = $LASTEXITCODE
Remove-Item Env:ATLAS_LIVE
"exit=$exitCode"
```
