# Atlas 交接（2026-10-01，下午改版）

**2026-10-02 最新流程**：恢复“上游规划/验收 → ZCode 搬运 → Codex 施工 → ZCode 回报 → 上游验收并直接发布下一任务”的连续闭环。用户不负责逐波派发，也不需要在阶段之间确认。当前任务永远以 `tasks/CURRENT.md` 指向的任务书为准。

**新会话先读这份**，再读：`docs/plan/ROADMAP-TO-PRODUCT.md`（成品路线、派发方法）→ `docs/plan/00-MASTER-PLAN.md`（总计划：主体优先、自有内核）→ `docs/plan/CORE-PARITY.md`（主体对标表，决定每波做什么）→ `docs/plan/EXECUTION-GUIDE.md`（环境、fork 工作流、搬代码方法、验收清单）。桌面上的《Atlas会话全貌-2026-10-01.md》讲这两天发生了什么、为什么。

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

**从现在起统一用这一套：**
- **上游规划/验收者**：根据 ROADMAP 和 CORE-PARITY 直接写当前阶段任务书并推送 Atlas 仓库；收到 ZCode 完工通知后，直接检查提交、代码、结果文件和必要测试。通过就立即写下一阶段任务并推送；不通过就直接写补做指令并推送。阶段之间不询问用户。
- **ZCode**：只做搬运和通知。读取 `tasks/CURRENT.md`，把当前任务路径交给 Codex；Codex 完成并 push 后，把结果通知上游规划/验收者。不要替 Codex 改代码，也不要自行改变任务范围。
- **Codex 施工者**：默认 **GPT-6 Luna / reasoning=high**。从仓库读取 `tasks/CURRENT.md` 和对应 taskbook，直接施工、提交、push、写 result，然后停止等待验收。
- **独立验收**：由上游规划/验收者完成，不再为每波额外开 Sol 验收会话。需要修复时直接发补做任务给 Luna high。
- 只有任务书明确写“需要真实模型/账号/物理设备”时才需要用户介入。

**速度与复杂度硬规则：**
- 禁止过度防御编程：不为理论异常堆 fallback、兼容层、重复 try/catch、抽象框架。
- 禁止过度验收：一个真实问题一个最小回归；全量测试按任务书要求通常只跑一次；不做重复测试矩阵、重复审计和为了测试而测试。
- 优先直接复用成熟上游实现；不要自写缩水版。
- 测试和验证的目的只有一个：证明这一阶段真的能用且没有明显回归。

## 4. 当前进度与下一步

- 当前正式任务看 `tasks/CURRENT.md`。截至 2026-10-02，第一轮为 `ATLAS-C1R-FINISH`：C1 Hermes 内核替换收尾。
- C1R 通过后按 ROADMAP 顺序进入 C2 → C3 → C4 → C5 → C6 → T1/T1F → X1–X6 → R1 → R2。
- 每一轮都由上游规划/验收者直接在仓库更新 CURRENT 和任务书，ZCode 只需搬当前任务，不需要用户复制提示词。
- `wip/c3-frontend-from-laptop` 只在 C3 作为参考，当前不要合并。

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
