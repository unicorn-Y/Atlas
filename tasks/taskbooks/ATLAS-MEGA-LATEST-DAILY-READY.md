# ATLAS-MEGA-LATEST-DAILY-READY：最新最强一次性收口到日常可用

> **这是当前唯一主线大任务。**
>
> 用户决定：不再把 U0 / U1 / X2 / X4 / X5 / K1 拆成多次人工派发。
> 本任务一次连续做完：
>
> **最新源冻结 → Hermes upstream 同步 → 已完成 C1–C6 全局 latest-best 刷新 → X2 Computer/Browser → X4 Skill Market → X5 Self-Evolution → K1 全面检查修复 → 日常可用交付**
>
> 中间不等待外部人工验收；每个阶段内部自检通过后立即继续下一阶段。
> 只有遇到真正无法在当前环境完成、且会改变产品方向的 blocker 才停。

---

# 0. 主控方式：子代理能开就开，尽量吃满并发

**这是硬要求，不是建议。**

主控负责：
- 冻结接口和文件所有权；
- 拆任务；
- 并行派发；
- 审查 worker 结果；
- 处理共享热文件和最终集成；
- 做最终验证。

实际研究、搬运、编码、测试，尽量交子代理。

## 并发规则

1. **使用当前运行环境允许的最大子代理并发。**
2. **不要写死 3 / 4 / 6 / 8 个 worker。**
3. 只要任务和文件所有权独立，就继续开子代理，直到当前环境拒绝继续 spawn。
4. 如果 spawn 因并发/配额被拒：
   - 自动缩当前 batch；
   - 等已有 worker 回收槽位后继续派下一批；
   - **不要因此停用子代理，也不要退回单线程。**
5. 同一个共享热文件只允许一个 owner：
   - `core/atlas/engine/hermes_runtime.py`
   - `core/atlas/server.py`
   - `frontend/src/renderer/App.tsx`
   - `frontend/src/renderer/store/useAtlasStore.ts`
   - fork 中高冲突核心文件
   由 integration owner 串行处理。
6. worker 自己跑 focused tests；主控不要重复 worker 已经充分跑过的测试。
7. 每个大阶段完成并验证后立刻 commit + push checkpoint，再继续下一阶段。
8. **不要阶段性停下来等用户。**

建议同时维护一个动态工作表：
- 模块
- owner
- branch/worktree
- touched files
- dependency
- status
- focused tests
- commit

---

# 1. 开工先做 Latest Source Freeze

在任何编码前，重新抓当前时间点的最新来源，并把精确版本写进：

`docs/research/2026-10-03-mega-latest/source-freeze.md`

至少包含：

- NousResearch/hermes-agent current main commit/date
- Claude Code current release/changelog/date
- OpenAI Codex current stable + main commit/tag/date
- OpenCode current release/main
- Pi current release/main
- Browser Use current release/main
- Stagehand current release/main
- skills.sh / ClawHub / Hermes Skills Hub current state
- 与 Atlas 已采用能力相关的 Factory/Cline/Kiro/Roo/goose 等当前版本
- ZCode 当前能公开验证/本机观察到的 UX 行为

**原则：最新情报 + 当前最强实现，不是盲目追版本号。**

每个能力最终只允许：
- KEEP：Atlas 已经相当或更强
- UPGRADE：搬当前更强实现
- REPLACE：删除/降级旧实现，用当前成熟实现替换

不要因为某项目新版删了能力，就机械跟删。
例如 Pi 新版不内置 subagent，不代表 Atlas 也要删 Atlas 更强的子代理体系。

如果 `sol/x-prep` 已经有更新的 source-map / X2-X7 taskbook：
- 只读取并吸收最新研究结论；
- 不整分支 merge；
- 不覆盖 main 当前生产实现；
- source path 必须自己复核存在。

---

# 2. Phase A — U0：Hermes upstream 最新同步

先完成，因为后续 X2/X4/X5 都依赖最新 Hermes。

## 目标

把：
`NousResearch/hermes-agent:main`

当前 source-freeze 记录的 HEAD，语义合并进：
`unicorn-Y/hermes-agent:atlas`

当前已知 fork 有 Atlas 自己的增强，必须保留。

## 并行拆法

主控先生成 upstream diff 分类，再最大并发分给 worker：

- agent loop / recovery / context
- files / fuzzy patch / write guards
- terminal / process / Windows
- delegation / nested orchestrator / worktree
- browser / computer
- skills hub / skill learning / curator
- gateway / cron / messaging / Bot Mode
- desktop / session / remote
- models/providers
- tests / Windows regressions

共享冲突文件由 integration owner 收口。

## 合并原则

- upstream 已经更强：用 upstream；
- Atlas 独有增强且仍有价值：重放/保留；
- 两边重复：只留一套强实现；
- 不允许简单 ours/theirs 粗暴覆盖；
- Atlas 独有逻辑尽量保持在薄 adapter/seam，减少以后同步成本。

必须特别保护：
- Atlas context handoff / fixed summary fields
- variable-size anchored fuzzy edit
- Windows/MCP orphan fixes
- Atlas read/write baseline guards
- multimodal tool-result guardrail compatibility
- Atlas-specific toolset/runtime hooks
- C1–C6 已验收语义

## 验证

只跑：
- 冲突文件直接相关 upstream tests
- Atlas fork 自己增强的 focused tests
- file/context/delegation/browser/skills/gateway/Windows smoke

不要为了“保险”做巨型矩阵。

完成：
- push `unicorn-Y/hermes-agent:atlas`
- 写 checkpoint 到最终 result
- 更新 Atlas 记录的 Hermes baseline
- **不停止，直接进入 Phase B**

---

# 3. Phase B — U1：C1–C6 全局 Latest-Best Refresh

**以前做完的不等于永远不动。**

基于 Phase A 最新 Hermes + source freeze，把 C1–C6 全部重新扫。

输出：
`docs/research/2026-10-03-mega-latest/core-refresh-map.md`

表：
能力 | Atlas 当前 | 当前最强来源 | version/commit | repo/file | KEEP/UPGRADE/REPLACE | owner | 是否阻塞日常使用

## 必扫 A：Agent loop / recovery / context

对：
- Hermes latest
- Claude Code latest
- Codex latest
- OpenCode latest
- Pi latest

看：
- loop/budget
- 429/5xx/timeout/断流/空回复/truncation/overflow
- repetition / stop gates
- prompt stability/cache
- compaction
- new-context handoff
- session resume
- token/context/cost

## 必扫 B：Files / Patch / Terminal / LSP

看：
- Hermes latest file tools
- Codex current patch/V4A
- OpenCode current edit/LSP
- Pi snapshot/revert
- Claude Code current edit/Bash behavior

重点：
- read/search/write/patch
- CRLF/BOM
- write guards
- V4A
- LSP
- terminal/PTy/background
- long output

## 必扫 C：Session / Interaction / Permissions

看最新：
- Claude Code
- Codex
- Pi
- OpenCode
- ZCode

重点：
- steer/queue/send-now
- fork/tree
- rewind/checkpoint
- plan
- permissions
- status/composer/history
- remote/background UX

## 必扫 D：Subagents / Orchestration

重点吸收：
- Hermes latest nested orchestrator
- worktree isolation
- structured child outputs
- timeout/cancel/resume
- Claude Code side-agent/subagent 新变化
- Factory verifier patterns

Atlas 继续保持：
- 最大动态并发
- verifier
- worktree 隔离
- 不共享工作区互踩

如果最新 Hermes 已有更成熟实现，删 Atlas 重复层，改 adapter。

## 必扫 E：Extensions

重新核：
- Claude Code hooks/plugins/skills/agents/MCP
- Claude Mods
- plugin configure/eval
- prompt audit
- AGENTS/CLAUDE rule behavior
- OpenCode/Pi extensions

C4 的兼容层若落后，直接升级。

## 必扫 F：Models

重新核：
- Hermes provider runtime
- Pi ModelRuntime
- Codex/Claude current reasoning/cache/provider behavior

检查：
- catalog
- aliases
- key rotation/cooldown
- staged reasoning
- cache diagnostics
- context windows
- local providers

## 必扫 G：Coding UX

对比当前：
- Codex
- Claude Code
- OpenCode
- Pi
- ZCode

重点：
- /init
- /review
- command center
- fullscreen/history
- findings
- long session
- diff/files/terminal
- palette/status/errors/settings

## 施工规则

所有标记为：
- 阻塞日常强度，或
- 明显落后，且
- 能直接搬成熟实现

的 UPGRADE/REPLACE **本阶段直接施工完成**。

纯企业治理/与个人日常无关的大边角，只记录，不阻塞。

focused 全绿后：
- backend full pytest 最多一次
- frontend 四项一次
- fake-model 主链一次

**不停止，直接进入 Phase C/D/E。**

---

# 4. Phase C — X2：最新最强 Computer + Browser

不要按旧 X2 死抄；基于 source freeze + 最新 Hermes + Browser Use/Stagehand 当前实现重新选强者。

## Computer Runtime

目标只留一套 runtime：

优先组合：
- Hermes latest computer_use/cua backend
- Atlas 已有 PID/HWND/window targeting
- UIA fallback
- SendInput fallback
- vision routing

要求：
- 后台优先
- 窗口定向
- foreground escalation
- screenshot/state
- mouse/keyboard/clipboard
- multi-monitor/DPI
- lost-focus/window-move/occlusion recovery
- accessibility + vision fallback
- Windows 真实可用

Atlas 旧工具名保留为 alias，不让模型看到重复工具。

## Browser Runtime

重新核最新：
- Hermes current browser stack
- Browser Use CLI current
- Stagehand current
- CDP
- Camofox/Lightpanda/云 backend（只保留真正有价值的）

统一能力：
- persistent authenticated profile
- DOM/a11y refs
- screenshot/vision
- upload/download
- dialogs
- tabs/windows
- browser lifecycle
- CDP attach
- real-profile copy
- extension mode
- human handoff
- vault/password never exposed to model
- browser panel sync

模型只暴露一套主 browser surface。
Playwright/chrome-devtools MCP 作为用户手动开启的高级选项，不默认重复占上下文。

## Learned Browser Workflow

直接研究并搬成熟做法：
- Stagehand caching/self-heal
- Browser Use workflow/memory
- demonstration → reusable skill

要求：
- 用户录一遍
- 生成可编辑 skill/workflow
- 重放优先不调模型
- 单步失败才模型接手
- 成功后更新该步骤

这部分生成结果必须直接接 Phase D 的统一 SkillManager，不造第二套 workflow registry。

## X2 测试

假驱动/假浏览器优先：
- 后台/前台升级
- 人工接管
- vault secret 不进日志/工具结果
- persistent profile
- download/upload/dialog/tab
- cache hit 不调模型
- self-heal
- recording → skill

真实模型/真实账号测试不在本 Mega 强制执行；需要用户凭据/验证码的记录为“待用户日常实测”。

---

# 5. Phase D — X4：最新最强 Skill Market

**X2 和 X4 大部分模块可并行开发。**
但最终 integration 需要 X2 recording → SkillManager。

主 registry 只有：
`core/atlas/skills/`

任何 marketplace/hub 只能作为 source/install/update 层。

## 必接最新 Hermes Skills Hub

按 Phase A 最新 fork 直接复用当前模块，而不是旧任务书写死旧文件。

至少覆盖：
- official
- skills.sh
- ClawHub
- GitHub/custom repo
- Claude plugin 内 skills
- 本机生成 skill

能力：
- search
- detail
- preview SKILL.md + files
- install
- update
- update-all
- uninstall
- enable/disable
- source provenance
- version
- dependencies/reference/assets
- user/project scope
- same-name conflict
- progressive loading
- lock/update state 单一来源

不要额外造安全 scanner；用户自己负责安装安全判断。

## 前端

侧栏技能：
- 市场
- 已安装
- 更新

必须能区分：
- marketplace
- plugin
- project
- user
- X2 本机录制
- X5 自动候选/本机生成

断网/代理失败给中文白话，不阻塞 UI。

---

# 6. Phase E — X5：Self-Evolution / 自动追新

**X5 的 watcher/parity/taskbook 部分可以和 X2/X4 并行开发。**
skill-curator/learned-skill 部分在 X4 registry 接好后集成。

不要做空泛的“AI 自己改自己”。

## E1 Upstream / Changelog Watcher

持续追：
- Hermes
- Codex
- Claude Code
- OpenCode
- Pi
- Browser Use
- Stagehand
- 以及 source-map 标注的重要来源

记录：
- latest version/commit/date
- changed files/releases
- capability delta

## E2 Capability Diff

将变化映射到 Atlas 能力：

输出：
- NEW
- BETTER_THAN_ATLAS
- ALREADY_HAVE
- REGRESSION/REMOVED
- IRRELEVANT

不要因为来源删功能就自动建议 Atlas 删除。

## E3 Parity Mapper

自动生成 CORE-PARITY 更新建议：
- 能力
- 来源
- repo/file
- 为什么更强
- Atlas 对应实现
- 建议 KEEP/UPGRADE/REPLACE

## E4 Taskbook Draft

有值得升级的能力时：
- 自动生成施工任务书草稿
- 精确到 source repo/file
- Atlas integration point
- likely touched files
- focused acceptance

**只生成草稿，不自动 merge main。**

## E5 Implementation Branch

用户批准后：
- 自动开 isolated branch/worktree
- 派 agent 施工
- 跑 focused regression/T1 subset
- 生成 merge proposal

不要未经批准直接改 main。

## E6 Skill Learning / Curator

研究并优先搬最新 Hermes self-learning/curator。

闭环：
- 重复成功的任务
- X2 demonstration
- 用户显式“存为技能”
- 成功 recipe/workflow

→ candidate skill
→ 自动整理 references/assets/parameters
→ 给用户预览
→ 批准
→ 进入同一个 SkillManager

后续 curator：
- 去重
- 合并
- 更新
- 过时提醒
- 来源/版本

不要建立 MemoryOS 第二套记忆系统；Memory 继续冻结。

## E7 Self-update UI

只需要一个简洁页面/区域：
- 检测到的新能力
- 建议 KEEP/UPGRADE/REPLACE
- 来源
- 任务书草稿
- 批准施工
- 分支状态
- merge proposal

---

# 7. Phase F — X2/X4/X5 Integration

这是一个明确集成阶段，不要各模块做完就算。

必须确保：

1. X2 recording 生成的 skill → X4 SkillManager
2. X5 learned skill → 同一个 X4 SkillManager
3. X5 upstream watcher 能看 Hermes/Browser Use/Stagehand/Skills Hub
4. X5 parity mapper 能识别 C1–C6/X2/X4 能力
5. Browser/Computer 不出现重复 runtime/tools
6. Skills 不出现重复 registry/lock/update state
7. Scheduler/session/runtime 继续只有现有 Atlas/Hermes 那一套
8. OriginGuard 不弱化
9. Windows 路径/进程/关闭清理正常

此阶段专门让一组 integration/review worker 并行审查：
- duplicate runtime
- duplicate registry
- hot-file conflicts
- Windows lifecycle
- resource cleanup
- UI route consistency

---

# 8. Phase G — K1：上线前全面找问题并修

完成前面所有施工后，直接执行 K1，不停下来等用户。

## G1 Hermes 最新 parity check

重新对最新 fork：
- tools/toolsets
- slash commands
- gateway methods
- desktop exposed methods
- hooks
- skills
- browser/computer
- delegation

只看：
- 主体
- X2
- X4
- X5

没接上 → 接上。
明显坏了 → 修。

## G2 Tests

一次性做：

后端：
- Atlas full pytest 一次
- Hermes 与 Atlas 直接相关 suites 一次

前端：
- renderer tsc
- electron tsc
- Vitest
- Vite build

不要循环全量。

## G3 Fake-model 日常路径

从真实 Atlas HTTP/WS surface + fake model 走至少：

1. 新会话 → 选 workspace → 改代码 → LSP → diff → review → 修
2. 压缩后继续
3. steer / queue / stop
4. plan → execute
5. 多子 Agent 并行 + verifier
6. background process notification
7. browser multi-step
8. computer-use fake driver
9. skills search/install/use/update/uninstall
10. X2 recording → skill → replay
11. X5 candidate skill → approve → install
12. model/provider switch
13. permission modes
14. restart → conversation/settings/state still present
15. 429/500/disconnect recovery

发现问题就立即派 worker 修，focused 回归后继续。

## G4 已知真实环境边界

如果某项必须：
- 用户登录
- 真验证码
- 真支付
- 真第三方账号
- 真模型付费

不要停整个 Mega。
标记为：
`REQUIRES_USER_DAILY_SMOKE`

其余全部完成。

---

# 9. 测试策略：速度优先，不搞防御性大矩阵

硬规则：

- worker 只跑自己模块 focused tests；
- integration 阶段跑跨模块 focused；
- backend full pytest **最终最多一次**；
- frontend 全套最终一次；
- 不因为一个小修复重复跑 20 分钟全套；
- 不用真实模型；
- 不动用户真实数据；
- tests 必须隔离 HOME/HERMES_HOME/ATLAS_DATA_DIR；
- 不做无关 benchmark；
- 不为了形式写几百条低价值测试。

---

# 10. 提交与连续执行

这是一个长任务，但**不能做到一半停下来“等下一波”**。

建议 checkpoint：

- M0 source freeze
- M1 Hermes upstream synced
- M2 core latest-best refresh
- M3 X2
- M4 X4
- M5 X5
- M6 integration
- M7 K1/fixes
- M8 final daily-ready

每个 checkpoint：
1. worker focused tests green
2. integration owner review
3. commit
4. pull --rebase / resolve
5. push
6. 立即进入下一阶段

只有真实 blocker 才停止。

---

# 11. 最终交付

统一结果文件：

`tasks/results/ATLAS-MEGA-LATEST-DAILY-READY.result.md`

必须包含：

## Source freeze
- 所有关键来源 version/commit/date

## Hermes sync
- old/new fork HEAD
- upstream HEAD
- conflicts
- preserved Atlas patches
- removed duplicates

## C1–C6 refresh
- KEEP / UPGRADE / REPLACE 总表
- 实际换掉的旧实现
- 仍比 Atlas 强的外部能力（如果有）

## X2
- Computer architecture
- Browser architecture
- learned workflow
- fake acceptance

## X4
- sources
- single SkillManager
- install/update/uninstall
- progressive loading

## X5
- watcher
- capability diff
- parity mapper
- taskbook generator
- approval/branch flow
- skill learning/curator

## K1
- parity check
- full test summaries
- fake daily-path matrix
- bugs found/fixed

## Remaining
只允许列：
- 必须用户账号/验证码/真实环境才能验的 smoke
- 明确后放的 X1/X3/X6/X7/T1/R1

最后明确写一句：

**“Atlas 当前主体 + Computer/Browser + Skills + Self-Evolution 已完成最新最强刷新和 K1 自动检查，可以开始日常使用。”**

如果达不到，就不要写这句话，列 blocker 并继续修。

---

# 12. 完成动作

最终：
- 更新 `docs/plan/CORE-PARITY.md`
- 更新必要 `docs/PARITY.md`
- 更新 `docs/plan/ROADMAP-TO-PRODUCT.md`
- `tasks/CURRENT.md` → `AWAITING_REVIEW`
- push Hermes fork
- push Atlas main
- 核对两个 repo local HEAD == remote HEAD
- 停止

**不要自行开始 X1 / X3 / X6 / X7 / full T1 / R1。**
