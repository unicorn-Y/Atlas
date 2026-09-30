# Atlas 对标工作交接（2026-09-30）

新会话先读这份，再读 `docs/PARITY.md` 和 `docs/research/2026-09-agent-harness-landscape.md`。

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

## 4. 当前进度

- 对标表 `docs/PARITY.md`：170 ✅ / 15 🟡 / 3 ❌ / 18 ➖ / 4 ⚖️。
- 后端第 1–5 波已接受（协议 1.7）；审阅记录在 `tasks/reviews/`。前端全部接好并实测。
- **第六波任务书**已推送（`tasks/taskbooks/CODEX-ATLAS-BACKEND-PARITY-WAVE6.md`）：0 遗留（Worker 用父模型、DNS 重绑定、全量测试跑完）、1 子 Agent 体系（多格式定义文件、6 种内置类型、并行验收、后台委派与引导、配方当 Worker）、2 浏览器交接与复用用户 Chrome、3 局域网网页版与手机配对、4 对话导出为网页、5 插件市场。**提示词已填进 Codex，等用户点发送。**
- 第七波候选（见调研文档第四节）：停止前校验关卡、「改前问我」的 LLM 审批员、工具延迟加载、规则优先的上下文压缩、钩子兼容 Claude Code、Agent 团队模式、远程子 Agent（A2A）、多模型会诊。

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
