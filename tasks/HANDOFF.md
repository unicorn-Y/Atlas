# Atlas 交接（2026-10-01，下午改版）

**新会话先读这份**，再读：`docs/plan/00-MASTER-PLAN.md`（总计划：主体优先、自有内核）→ `docs/plan/CORE-PARITY.md`（主体对标表，决定每波做什么）→ `docs/plan/EXECUTION-GUIDE.md`（环境、fork 工作流、搬代码方法、验收清单）。桌面上的《Atlas会话全貌-2026-10-01.md》讲这两天发生了什么、为什么。

## 1. 用户是谁、要什么

- **始终用中文回复**（代码、命令、提交信息可以英文）。长会话会漂回英文，漂了就建议交接。
- 目标：把 Atlas（`github.com/unicorn-Y/Atlas`，Electron + React 前端，Python FastAPI 后端）做成**全能**桌面 Agent，主要自己用；**每个功能都要当下最新、最强那家的水平，而且要超过它**；**有现成开源代码就拿来改**（不要从零设计）；以后 Atlas 自己跟踪各家更新（W12）。
- 设计依据必须来自**当下最新**的资料，覆盖很多家，不能凭记忆。

## 2. 已定的决定（不要推翻）

| 决定 | 含义 |
| --- | --- |
| **自有内核**（10-01 改） | Atlas 的 Agent 内核换成 fork 来的 Hermes 内核（`unicorn-Y/hermes-agent` 的 `atlas` 分支），替掉 LangGraph 循环；界面、协议、已有功能保留。零件逐项换成各家最强的（CORE-PARITY）。官方程序（Claude Code、Codex）只当可切换选项 |
| **主体优先**（10-01） | 原 W08–W13 外部功能冻结；先做 C1–C6 |
| **每波只验收，实测放最后**（10-01） | 施工和验收都用假模型，不用真实模型；C6 之后统一真实模型横向对比 |
| 用户的目标（10-01 原话） | 「做好一个能用的，以后看哪家新的东西了，就抄过来自己用，随便扩展，慢慢做强」；「要的都是各家最强的」 |
| 规则表整份拷贝 | 规则表、模式库这类文件必须整份搬，不许自写缩水版（W06 被缩成 36 行出过事） |
| FULL_ACCESS 默认 | 不弹窗、不自动拦截 |
| **安全审查用户亲自做** | 计划里不做任何安全审查；`core/atlas/safety/` 代码保留，开关默认关 |
| **不要沙箱** | Atlas 像 CLI 一样本机直接运行 |
| **视频生成暂不做** | 图像、音频保留 |
| 本地语音 | W06 后端已有，前端放 W13 |
| 记忆系统冻结 | 只做「外部内容不进长期记忆」这类小改动 |
| 外部 Agent ACP 认证跳过 | |
| 自动跟踪更新 | 做成 Atlas 自己的功能（W12），不要另建 Claude 定时任务 |

## 3. 分工与流程（最重要）

- **Luna**（主机 Codex 桌面端，模型 GPT-6 Luna）：做每一波的后端**和前端**。
- **Sol**（同一个 Codex，模型 GPT-6.1 Sol）：验收每一波——自己跑全量、用假模型跑端到端、对照 CORE-PARITY 逐项检查、修问题、写验收记录。**不用真实模型。**
- **Claude（你）**：调度。循环：
  1. 把 Luna 提示词填进 Codex 新对话（模型选 Luna）→ **用户点发送**（权限分类器不让 Claude 点）
  2. Luna 做完 → Claude 读 `tasks/results/<任务书>.result.md`
  3. 把 Sol 提示词填进 Codex 新对话（模型选 Sol）→ 用户点发送
  4. Sol 做完 → Claude 读 `tasks/reviews/<任务书>.review.md`：通过就填下一波的 Luna 提示词；有没修完的就写补做任务书（参照 W07B）再给 Luna
- **Claude 在循环里不写代码、不跑测试**（用户明确说太费 token），只读结果、写任务书、填提示词。C6 验收通过后进入「实测」阶段（Claude 参与，真实模型横向对比），再收尾，最后 Claude 按 `docs/plan/FINAL-REVIEW.md` 做最终审查，向用户汇报。
- 每次给用户的汇报要短：做到哪了、下一步是什么、需要用户点什么。

## 4. 当前进度与下一步

- **W06 ✅**；**W07 🟡**（后端部分验收）。**W07B 作废**，内容分到 C1、C3、C5（见任务书文件头）。
- 2026-10-01 下午：Claude 读代码发现 Atlas 内核的硬伤（10 轮上限、假压缩、跨轮丢工具记录、15 行提示词、编辑改换行等，见 CORE-PARITY 第 0 节），加上外部调研（外层框架决定 13–18 分的差距、11 家主流内核都不用通用框架），和用户确认改成「自有内核 = Hermes 骨架 + 各家最强零件」。
- **下一步：C1**（`tasks/taskbooks/ATLAS-C1-HERMES-CORE.md`）→ 把「给 Luna」的提示词（任务书名换成 ATLAS-C1-HERMES-CORE）填进主机 Codex 的新对话。C1 第一节要在用户 GitHub 上 fork Hermes，如果 Luna 没有 gh 权限，需要用户手动 fork。
- 之后：C2 → C3 → C4 → C5 → C6 → 实测 → 收尾 → 最终审查。C2 起的任务书在上一波验收通过后由 Claude 按 CORE-PARITY 写。
- 参考仓库：这次会话把 Codex、Hermes、OpenClaw、OpenCode、Pi 浅克隆到了 Claude 的临时目录，会话结束就没了；要用时按 EXECUTION-GUIDE 第三点五节重新克隆。
- 用户当前用的模型：第三方中转网关上的 DeepSeek（`openai/deepseek-v4.1-flash`），缓存命中拿不到（中转不转回），用量统计正常。

## 5. 两台机器与驱动 Codex

- 笔记本（Claude 所在）：仓库 `C:\Users\youdu\Desktop\Atlas`，venv `core/.venv`（Python 3.12），GitHub 走 HTTPS + 代理 127.0.0.1:7897。端口 8765 / 5173 上可能跑着用户的开发版（旧代码），**不要动**。
- 主机：`ssh zhuji`（192.168.31.158，用户 25011），仓库 `D:\Atlas`，默认 shell cmd。同步：`ssh zhuji "cd /d D:\Atlas && git checkout -- package-lock.json & git pull -q --ff-only"`。
- Codex 桌面端开着 `--remote-debugging-port=9333`；隧道 `ssh -N -L 9333:127.0.0.1:9333 zhuji`（端口被占说明隧道还在）。
- 笔记本助手脚本 `frontend/scripts/.cdp.mjs`（未提交，别提交）：`node scripts/.cdp.mjs <脚本.js> <输出目录>`，脚本里可用 `page`（主窗口）和 `out`。
- 填提示词：`page.getByText('新聊天', { exact: true }).first().click()` → 确认底部项目是 Atlas → 输入框用 `page.locator('[data-codex-composer="true"]:visible').first()`（页面有两个，只有一个可见）→ Ctrl+A、Delete、`keyboard.insertText(提示词)` → 截图确认。**切换模型（Luna / Sol）**：输入框右下角的模型菜单（目前显示「GPT-6 Luna 高」），填之前先点开选好；不会选就让用户手动切。
- 看进度：`ssh zhuji "cd /d D:\Atlas && git log --oneline -5 && git status -sb"`，或 `git fetch` 后看 `tasks/results/`、`tasks/reviews/`。
- 计划书副本在桌面 `Atlas计划书-2026-09-30/`，改了计划书记得同步过去。
- Git Bash 的 heredoc 会吃掉反斜杠和 `\n`：复杂改动用编辑工具，或写成 Python 脚本文件再运行。

## 6. 提示词（直接复制；换掉任务书名即可）

### 给 Sol 的验收提示词（每波通用，替换任务书名）

```
你是 Atlas 的验收者。工作目录 D:\Atlas，先 git pull 到最新 main；Hermes 内核 fork 在 D:\hermes-agent（atlas 分支），也拉到最新。
完整阅读 docs/plan/00-MASTER-PLAN.md、docs/plan/CORE-PARITY.md、docs/plan/EXECUTION-GUIDE.md（尤其第三点六节和第五节验收清单）、任务书 tasks/taskbooks/ATLAS-C1-HERMES-CORE.md 和结果文件 tasks/results/ATLAS-C1-HERMES-CORE.result.md。
按验收清单逐项做：对比搬入代码与来源规模；自己用后台进程跑完全量测试；读改动的代码找 bug；用假模型服务在隔离环境（独立 ATLAS_DATA_DIR、去掉 MCP、独立端口、假目录）跑任务书要求的端到端测试；对照 CORE-PARITY 里本波的每一行逐项检查；检查已有功能有没有倒退；前端用无头 Edge 截图检查。不要用真实模型。
不要碰用户 8765 上的开发后端和用户的真实文件。安全审查由用户亲自负责，不做也不评。
发现的问题直接修复并补测试，每个修复一个提交，提交信息写清为什么。
验收记录写到 tasks/reviews/ATLAS-C1-HERMES-CORE.review.md：结论、每个问题（问题/影响/修法）、CORE-PARITY 逐行核对结果、全量测试汇总行。更新 CORE-PARITY 状态。push 前 git pull --rebase，然后停止。
```

### 给 Luna 的提示词模板（每波通用，替换任务书名）

```
你是 Atlas 施工 Worker。工作目录 D:\Atlas，先 git pull 到最新 main。
先完整阅读 LUNA_WORKER.md、docs/plan/00-MASTER-PLAN.md、docs/plan/CORE-PARITY.md、docs/plan/EXECUTION-GUIDE.md（尤其第三点五、三点六节），再完整阅读任务书 tasks/taskbooks/ATLAS-C1-HERMES-CORE.md，它取代 tasks/CURRENT.md 里记录的任务。
本波以「从开源项目搬代码改」为主：按任务书点名的来源文件先读源码再搬，不要从零重写；Atlas 专属的东西放在 Atlas 仓库，只有非改内核不可的才改 Hermes fork；每个搬入的部分写来源注释并登记到 docs/plan/VENDORED.md。
任务书里的后端和前端章节都做（前端按 EXECUTION-GUIDE 第二节的链路接入，四项前端检查必须通过）。不得放宽 core/atlas/origin_guard.py。
接口名、事件名、字段名与任务书一致，已有事件保持兼容，偏离写进结果文件。测试不写真实数据目录、不在仓库建临时目录、不依赖真实网络；不用真实模型，用假模型服务跑端到端测试。
全量测试用后台进程跑完，汇总行写进结果文件。
按任务书更新 tasks/CURRENT.md 和 docs/plan/CORE-PARITY.md；每节一个提交；push 前 git pull --rebase；写结果文件；核验 remote HEAD；然后停止。
安全审查由用户亲自负责，不做任何安全审查相关功能（Hermes 的审批和危险检测保持关闭，core/atlas/safety/ 保持默认关闭）；本地语音暂缓。
```
