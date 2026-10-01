# Atlas 对标工作交接（2026-09-30）

新会话先读这份，再读 `docs/plan/00-MASTER-PLAN.md`（总计划）、`docs/plan/SOURCE-MAP.md`（代码来源）、`docs/plan/EXECUTION-GUIDE.md`（执行和审查方法）。调研依据在 `docs/research/2026-09-30-landscape/`。

## 1. 用户与规则

- **所有回复用中文**（代码、命令、提交信息可以英文）。长会话漂回英文就建议交接。
- 目标：把 Atlas（`github.com/unicorn-Y/Atlas`，Electron + React 前端，Python FastAPI 后端）做成「全能」桌面 Agent，吸收各家主流 Agent 的能力。设计要**以最新调研为依据**（用 WebSearch 查 2026 年资料），不能凭记忆、不能只看几家。
- 分工：**Claude 做前端 + 审查后端 + 修安全问题 + 写任务书**；**后端交给主机上的 Codex 桌面端**（省配额）。
- 已定的决定：FULL_ACCESS 是默认，不做逐工具弹窗；记忆系统冻结；**外部 Agent（ACP 认证）先跳过**；调度器已合并；第三波执行环境选了 SSH。

## 2. 两台机器

- 笔记本（当前会话所在）：仓库 `C:\Users\youdu\Desktop\Atlas`，虚拟环境 `core/.venv`（Python 3.12），GitHub 走 HTTPS + 代理 127.0.0.1:7897。
- 主机：`ssh zhuji`（192.168.31.158，用户 25011），仓库 `D:\Atlas`，默认 shell 是 cmd。同步：`ssh zhuji "cd /d D:\Atlas && git checkout -- package-lock.json & git pull -q --ff-only"`；装新依赖：`core\.venv\Scripts\python.exe -m pip install -q -e core`。
- 主机仓库里有 Codex 留下的未跟踪临时目录（`core/.pytest-wave1-*`、`design/`），第六波任务书要求它清掉，别手动删。

## 3. 驱动主机上的 Codex

- Codex 桌面端带 `--remote-debugging-port=9333` 启动；隧道：`ssh -N -L 9333:127.0.0.1:9333 zhuji`（端口已被占说明隧道还在）。
- 笔记本上的助手脚本 `frontend/scripts/.cdp.mjs`（未提交，别提交）：`node scripts/.cdp.mjs <脚本.js> <输出目录>`，脚本里可用 `page`（主窗口 `app://-/index.html`，不是 avatar-overlay 那个）和 `out`。填提示词：点「新聊天」→ 确认项目是 Atlas → 在 `[data-codex-composer="true"]` 里 `insertText`。**发送按钮由用户点**（权限分类器不允许我点）。
- 看 Codex 进度：截图，或 `ssh zhuji "cd /d D:\Atlas && git log --oneline -5 && git status -sb"`。Codex 没推送前可以在主机上 `git bundle create %TEMP%\w.bundle <base>..main`，`scp` 回来 `git fetch` 审查。

## 4. 当前进度（2026-09-30 晚）

- 对标表 `docs/PARITY.md`：170 ✅ / 15 🟡 / 3 ❌ / 18 ➖ / 4 ⚖️。后端第 1–5 波已接受（协议 1.7）。
- **重新做了全景调研**（`docs/research/2026-09-30-landscape/`，40 多个产品、9 个专题）。
- **用户纠正方向**：全部功能都要最新最好的，**有现成开源代码就拿来改**（记忆 `atlas-reuse-first`）；选择「移植」路线：保留 Atlas 后端，从 Hermes Agent（Python、MIT、约 25 万星，几乎覆盖全部能力）等项目逐块搬代码。
- 新计划：`docs/plan/`（总计划、源码地图、执行指南、代码登记表）+ 七波任务书 `tasks/taskbooks/ATLAS-W06-FOUNDATION-SAFETY.md` … `ATLAS-W12-SELF-EVOLUTION.md`。
- 旧的 `CODEX-ATLAS-BACKEND-PARITY-WAVE6.md` 已作废。
- **W06 已完成（2026-10-01）**：Codex 交付后端，Claude 审阅并重做了安全部分（见 `tasks/reviews/ATLAS-W06-FOUNDATION-SAFETY.review.md`），前端接了用量页、模型切换和验证提示（`b9927af`）。
- **用户决定（2026-10-01）**：安全审查由用户亲自做，计划里不做；`core/atlas/safety/` 代码保留但默认关闭。本地语音暂缓（后端已有，前端不接）。
- 用户当前模型是第三方中转网关上的 DeepSeek（`openai/deepseek-v4.1-flash`），缓存命中拿不到；用量统计正常。
- **W07 后端已交付（Codex 自标 PARTIAL）**，Claude 审查到一半转交：发现写在 `tasks/taskbooks/ATLAS-W07B-ORCHESTRATION-COMPLETION.md` 第一节（验收误判、汇总时机、看板没有调度器、子任务输出按 token 发事件）。
- **分工与流程（2026-10-01）**：Luna 做后端 + 前端；Sol 审查并修问题；Claude 调度（Luna 做完 → 给 Sol 下审查指令 → 读审查结果 → 给 Luna 下一步），全部做完后 Claude 最终审查（`docs/plan/FINAL-REVIEW.md`）。完整路线 W07B → W14 见总计划第四节。不要沙箱，本机直接运行。
- **下一步：Luna 执行 W07B**（提示词见下方「给 Luna」），完成后 Sol 审查（「给 Sol」）。
- 真机测试方法：隔离 `ATLAS_DATA_DIR` + 去掉 MCP 服务器 + 假目录 + 独立端口（W06 审阅记录里有完整做法），不要碰用户 8765 上的开发后端。
- 用户决定：自动跟踪各家更新做成 Atlas 自己的功能（W12），不另建定时任务。

### 给 Sol 的审查提示词（每波通用，替换任务书名）

```
你是 Atlas 的审查者。工作目录 D:\Atlas，先 git pull 到最新 main。
完整阅读 docs/plan/00-MASTER-PLAN.md、docs/plan/EXECUTION-GUIDE.md（尤其第五节审查清单和真机隔离做法）、任务书 tasks/taskbooks/ATLAS-W07B-ORCHESTRATION-COMPLETION.md 和结果文件 tasks/results/ATLAS-W07B-ORCHESTRATION-COMPLETION.result.md。
按审查清单逐项审查：对比搬入代码与来源规模；自己用后台进程跑完全量测试；读改动的代码找 bug；用本机真实模型在隔离环境（独立 ATLAS_DATA_DIR、去掉 MCP、独立端口、假目录）把任务书的真机场景全部跑一遍；前端用无头 Edge 截图检查。
不要碰用户 8765 上的开发后端和用户的真实文件。安全审查由用户亲自负责，不做也不评。
发现的问题直接修复并补测试，每个修复一个提交，提交信息写清为什么。
审查记录写到 tasks/reviews/ATLAS-W07B-ORCHESTRATION-COMPLETION.review.md：结论、每个问题（问题/影响/修法）、真机记录、全量测试汇总行。更新 docs/PARITY.md。push 前 git pull --rebase，然后停止。
安全审查由用户亲自负责，不做任何安全审查相关功能（core/atlas/safety/ 保持默认关闭）；本地语音暂缓。
```

### 给 Luna 的提示词模板（每波通用，替换任务书名；W07B 起前端也由 Luna 做）

```
你是 Atlas 施工 Worker。工作目录 D:\Atlas，先 git pull 到最新 main。
先完整阅读 LUNA_WORKER.md、docs/plan/00-MASTER-PLAN.md、docs/plan/SOURCE-MAP.md、docs/plan/EXECUTION-GUIDE.md（尤其「三点五、怎么搬代码」），再完整阅读任务书 tasks/taskbooks/ATLAS-W07B-ORCHESTRATION-COMPLETION.md，它取代 tasks/CURRENT.md 里记录的任务。
本波以「从开源项目搬代码改」为主：按任务书点名的来源文件先读源码再搬，不要从零重写；每个搬入的文件写来源注释并登记到 docs/plan/VENDORED.md。
任务书里的后端和前端章节都做（前端按 EXECUTION-GUIDE 第二节的链路接入，四项前端检查必须通过）。不得放宽 core/atlas/origin_guard.py。
接口名、事件名、字段名与任务书一致，偏离写进结果文件。测试不写真实数据目录、不在仓库建临时目录、不依赖真实网络。
任务书要求的真机场景用本机真实模型跑并记录。全量测试用后台进程跑完，汇总行写进结果文件。
按任务书更新 tasks/CURRENT.md；每节一个提交；push 前 git pull --rebase；写结果文件；核验 remote HEAD；然后停止。
安全审查由用户亲自负责，不做任何安全审查相关功能（core/atlas/safety/ 保持默认关闭）；本地语音暂缓。
```

## 5. Codex 交付后怎么审查（每一波都这样做）

1. 拉代码，`pip install -e core` 装新依赖。
2. **在笔记本上跑全量**（Codex 那边长命令会被中断，它的全量从来没跑完）：
   `cd core && .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp "$TEMP/pt-x" --ignore=tests/test_computer_use.py`（放后台跑，约 3 分钟）。`test_computer_use.py` 会动真鼠标，永远跳过。
3. 重点读安全相关代码：OriginGuard、任何返回文件内容的接口（要有沙箱 CSP）、路径校验、子进程、密钥存储、网络请求（内网防护）。
4. **新 Agent 能力必须用真实模型实测一次**。第五波的 Worker 在 mock 测试里全过，真机上根本收不到任务，还被用户记忆带偏——这类问题只有真跑才能发现。
5. 修掉的问题追加进 `tasks/reviews/<波次>.review.md`，提交说明写清「为什么」。
6. 接前端 → 在开发版里实测 → 更新 `docs/PARITY.md` → 提交推送 → 同步主机。

## 6. 本地开发与实测

- 启动：先起后端 `core/.venv/Scripts/python.exe -m uvicorn atlas.server:app --host 127.0.0.1 --port 8765 --app-dir core`，再 `cd frontend && npx vite --host 127.0.0.1`，Electron：`npx tsc -p tsconfig.electron.json && VITE_DEV_SERVER_URL=http://127.0.0.1:5173 ATLAS_PYTHON=<venv python> ../node_modules/electron/dist/electron.exe . --remote-debugging-port=9335`。
- 当前会话结束时这三个可能还在跑（端口 8765 / 5173 / 9335）；重启后端前先按端口找到进程停掉（`Get-NetTCPConnection -LocalPort 8765`，确认命令行是 uvicorn 再停）。
- 前端检查：`npx tsc -p tsconfig.renderer.json --noEmit`、`npx tsc -p tsconfig.electron.json --noEmit`、`npx vitest run`、`npx vite build`。
- 界面实测：用 playwright-core 驱动**无头 Edge**（`C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`）打开 `http://127.0.0.1:5173`；需要 Electron 专有能力（webview、菜单、token 注入）时连 CDP 9335。选工作目录：无头 Edge 里没有 `atlasDesktop`，会弹 `window.prompt`，用 `page.on('dialog', d => d.accept(路径))`。临时脚本放 `frontend/scripts/.wNN.mjs`，用完删掉。
- 不要在开发版运行时 `npm ci`。
- Git Bash 的 heredoc 会吃掉反斜杠和中文：复杂改动先用 Write 写成 Python 脚本再运行，或直接用 Edit。

## 7. 安全模型（改代码时别破坏）

- 后端所有 HTTP / WS 过 `core/atlas/origin_guard.py`：带 `X-Atlas-Api-Token` 可信；没有 Origin 放行；Vite 开发来源放行；`Origin: null` 必须带 token。
- Electron 主进程只给**主页面**的请求注入 token（子框架不注入——文件预览里的 HTML 拿不到 token）；去掉了默认菜单（Ctrl+W 不再关窗口）；主窗口拒绝 `window.open` 和跳出应用。
- 浏览器面板用独立 partition `persist:atlas-browser`，没有 token。
- 返回用户文件的接口都带沙箱 CSP。
