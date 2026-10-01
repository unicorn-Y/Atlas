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

**从 C2 起（用户 2026-10-01 决定）：**
- **Sol 主控**（主机 Codex，模型 GPT-6.1 Sol）：读任务书、拆块，用 Codex 的子代理（`spawn_agent`，指定 GPT-6 Luna、推理档位 high）逐块施工；每块审 diff、跑测试、纠偏或返工；最后跑全量、写结果文件。
- **独立验收**（另开一个 Sol 新对话）：没参与施工的 Sol 按 EXECUTION-GUIDE 第五节验收、找问题、写验收记录；**修复交给它开的 GPT-6 Luna（high）子代理**（用户 2026-10-02 要求，省配额）。**用户要求保留这一步。**
- **Claude（你）**：写任务书 → 填「Sol 主控」提示词 → 用户点发送 → Sol 完成后读结果文件 → 填「独立验收」提示词 → 用户点发送 → 读验收记录 → 写下一波任务书或补做任务书。不巡检、不写代码、不跑测试。
- C6 验收通过后进入「实测」阶段（Claude 参与，真实模型横向对比），再收尾，最后 Claude 按 `docs/plan/FINAL-REVIEW.md` 做最终审查，向用户汇报。
- 每次给用户的汇报要短：做到哪了、下一步是什么、需要用户点什么。

**并行规则（用户 2026-10-02）**：主控和验收都可以同时开多个 GPT-6 Luna（high）子代理并行干活，但必须按文件或模块分好：每个子代理只改分给它的文件，开工前写明负责哪些、不许碰哪些；会改到同一文件的活交给同一个子代理，或者排在后面串行做。子代理共用一个工作区，只 git add 自己的文件，提交前 git pull --rebase，不许 reset、stash 或改别人的改动；全量测试和端到端等所有子代理都提交完再统一跑。这条要写进每波的 Sol 主控和独立验收提示词。

**C1（旧流程，正在进行）**：Luna 单独施工；Claude 用会话内定时任务每 20 分钟巡检（`scratchpad/inspect.sh`：两个仓库的提交、结果文件、Luna 最近的话），用户授权 Claude 在 C1 巡检中自己发送纠偏指令。C1 交付后删掉巡检，开新 Sol 对话做独立验收（用下面的「独立验收」提示词）。

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

### Sol 主控提示词（C2 起每波通用，替换任务书名；新开对话，模型选 GPT-6.1 Sol）

```
你是 Atlas 这一波的主控。工作目录 D:\Atlas，先 git pull 到最新 main；Hermes 内核 fork 在 D:\hermes-agent（atlas 分支），也拉到最新。
完整阅读 LUNA_WORKER.md、docs/plan/00-MASTER-PLAN.md、docs/plan/CORE-PARITY.md、docs/plan/EXECUTION-GUIDE.md（尤其第三点五、三点六、第五节），再完整阅读任务书 tasks/taskbooks/<任务书名>.md，它取代 tasks/CURRENT.md 里记录的任务。
你自己不直接写大段代码，而是这样带队：
1. 把任务书拆成若干块（通常一节一块），写出每块的完成标准（对应 CORE-PARITY 的哪些行、要过哪些测试）。
2. 用 spawn_agent 开子代理施工，模型指定 GPT-6 Luna、reasoning_effort 指定 high；给子代理的消息里写清：读哪些文件、这一块的范围和完成标准、本项目的硬规矩（见下）、做完一块提交一次并汇报改了什么和测试结果。可以同时开多个子代理并行，但要按文件或模块分好：每个子代理只改分给它的文件，开工前写明负责哪些、不许碰哪些；会改同一批文件的块交给同一个子代理或按顺序做；子代理只 git add 自己的文件，提交前 git pull --rebase，不许 reset、stash 或改别人的改动。
3. 每块完成后你亲自审：看 diff、跑相关测试、对照来源代码检查有没有自写缩水版、有没有砍功能、已有事件和接口是否保持兼容。不合格就让同一个子代理返工（send_input）或纠偏，合格再进行下一块。
4. 全部完成后，你用后台进程跑完 Atlas 全量测试和前端四项检查，汇总行写进结果文件 tasks/results/<任务书名>.result.md（每块做了什么、偏差、已知限制、没覆盖的项）；更新 tasks/CURRENT.md 和 docs/plan/CORE-PARITY.md；push 前 git pull --rebase；核验 remote HEAD；然后停止。
硬规矩：搬代码先读源码再搬，Atlas 专属的放 Atlas 仓库，非改内核不可的才改 fork（只进 atlas 分支）；规则表整份拷贝不得缩水；不得放宽 core/atlas/origin_guard.py；测试不写真实数据目录、不在仓库建临时目录、不依赖真实网络；不用真实模型，用假模型服务跑端到端；接口名、事件名、字段名与任务书一致，已有的保持兼容；不要碰用户 8765 上的开发后端和用户的真实文件。安全审查由用户亲自负责，不做任何安全审查相关功能（Hermes 的审批和危险检测保持关闭，core/atlas/safety/ 保持默认关闭）；本地语音暂缓。
```

### 独立验收提示词（每波通用，替换任务书名；新开对话，模型选 GPT-6.1 Sol）

```
你是 Atlas 的独立验收者，没有参与本波施工。工作目录 D:\Atlas，先 git pull 到最新 main；Hermes 内核 fork 在 D:\hermes-agent（atlas 分支），也拉到最新。
完整阅读 docs/plan/00-MASTER-PLAN.md、docs/plan/CORE-PARITY.md、docs/plan/EXECUTION-GUIDE.md（尤其第三点六节和第五节验收清单）、任务书 tasks/taskbooks/ATLAS-C1-HERMES-CORE.md 和结果文件 tasks/results/ATLAS-C1-HERMES-CORE.result.md。
按验收清单逐项做：对比搬入代码与来源规模；自己用后台进程跑完全量测试；读改动的代码找 bug；用假模型服务在隔离环境（独立 ATLAS_DATA_DIR、去掉 MCP、独立端口、假目录）跑任务书要求的端到端测试；对照 CORE-PARITY 里本波的每一行逐项检查；检查已有功能有没有倒退；前端用无头 Edge 截图检查。不要用真实模型。
不要碰用户 8765 上的开发后端和用户的真实文件。安全审查由用户亲自负责，不做也不评。
你只负责找问题、审查和验收；修复交给子代理（用户要求，省配额）：用 spawn_agent 开子代理，model 指定 GPT-6 Luna、reasoning_effort 指定 high，每个子代理给一组相关问题，写清问题、位置、复现、修复标准、要补的测试和本项目硬规矩；子代理每个修复一个提交并写清为什么；你审 diff、跑相关测试，不合格让它返工；可以同时开多个子代理并行，但要按文件或模块分好，每个只改分给它的文件，只 git add 自己的文件，提交前 git pull --rebase，不许 reset、stash 或改别人的改动；全量和端到端等全部提交完再统一跑。
验收记录写到 tasks/reviews/ATLAS-C1-HERMES-CORE.review.md：结论、每个问题（问题/影响/修法）、CORE-PARITY 逐行核对结果、全量测试汇总行。更新 CORE-PARITY 状态。push 前 git pull --rebase，然后停止。
```

### 给 Luna 的提示词模板（只用于 C1 这种单独施工；C2 起改用上面的「Sol 主控」）

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
