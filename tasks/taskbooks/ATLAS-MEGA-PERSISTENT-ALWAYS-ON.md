# ATLAS-MEGA-PERSISTENT-ALWAYS-ON：Persistent Atlas / Always-On 最强整合波

> 用户决定继续“抄最强的”，但必须先确认 2026-10 当前最新再施工。
>
> 这是一个连续大任务。目标不是再造一个新 Agent，而是把当前 Atlas 从“强桌面 Agent”升级成：
>
> **常驻、长期 Agent、多 Agent、手机/IM 随时派活、主动 Heartbeat、可靠 Cron/自动化、笔记本就是 Atlas 自己的电脑、托管本地模型、技能持续学习。**
>
> 中间不按 X1/X7 分波停下来等人工验收。

---

## 0. 执行硬规则：子代理开到当前环境最大

ZCodex 是 controller，不是主要 coder。

必须：
1. 研究、源码对比、port、编码、focused tests、review 尽量交子代理。
2. **使用当前 runtime 实际允许的最大子代理并发。**
3. 不写死 worker 数量。
4. 独立文件/模块继续 spawn，直到 runtime 拒绝更多并发。
5. 遇到 concurrency/quota rejection：缩当前 batch，已有 worker 回收槽位后继续派；**不能因此退回单线程。**
6. 热文件只给一个 integration owner：
   - `core/atlas/server.py`
   - `core/atlas/engine/hermes_runtime.py`
   - `frontend/src/renderer/App.tsx`
   - `frontend/src/renderer/store/useAtlasStore.ts`
   - Hermes fork 高冲突核心
7. worker 自己跑 focused tests；controller 只做跨模块/最终验证。
8. 每个内部 milestone commit + push 后立即继续，不停下来等用户。

建议首批并行 lane：
- L1 OpenClaw persistent-agent/gateway
- L2 OpenClaw heartbeat/cron
- L3 OpenClaw node/computer placement
- L4 Hermes Bot Mode/Bot Screen
- L5 Hermes messaging adapters
- L6 Hermes local runtime
- L7 DBOS durable automation
- L8 Skill Workshop/curator
- L9 frontend UX/source-map/integration audit

---

# 1. Phase P0 — 开工重新冻结最新来源

**不允许直接用任务书写死的旧 HEAD 开工。**

重新 fetch：

- `openclaw/openclaw:main`
- `NousResearch/hermes-agent:main`
- `dbos-inc/dbos-transact-py:main`
- Atlas `main`
- Atlas Hermes fork `unicorn-Y/hermes-agent:atlas`

写：
`docs/research/2026-10-03-persistent-atlas/source-freeze.md`

记录：
- HEAD/tag/date
- 相比本任务书研究时的新变化
- 本波涉及文件是否改名
- 哪个来源当前仍是该能力最强

本任务书生成时观察到：
- OpenClaw `899a0ca6814f02da84938c3d2b6af5e3b6dedf04`
- Hermes `c8301ea6c9b797184df16a9c5dd462400b264ff4`
- DBOS Python `03fb5c92cde8e107ff333cd2b419f65e02719e99`

如果开工时它们已变化，**以开工冻结值为准**。

同时先 tail-sync Hermes fork 到开工冻结的 upstream HEAD；保留 Atlas patches。只跑 touched/fork focused tests，不重新跑整个 Mega。

---

# 2. Phase P1 — 先定唯一架构，禁止重复系统

在编码前写：

`docs/research/2026-10-03-persistent-atlas/integration-map.md`

每层只允许一个 owner：

| 层 | 唯一 owner |
|---|---|
| Agent loop / model calls / context | Atlas + Hermes fork（现有） |
| SessionDB / conversation | 现有 Atlas/Hermes |
| Persistent Agent registry | Atlas Profile/Agent 层升级 |
| Gateway ingress/routing | Atlas 新 Gateway，按 OpenClaw 状态机 |
| Channel adapters | Atlas plugin contract；Hermes Python adapters 优先 |
| Heartbeat | Atlas 新 persistent-agent service，OpenClaw 语义 |
| Automation state | Atlas Automation |
| Durable execution | 现有 DBOS backend |
| Cron Agent API | Atlas endpoint/tool，Hermes/OpenClaw UX/contract |
| Computer/Browser | 现有 X2 |
| Device/node ownership | Atlas device layer，OpenClaw placement 语义 |
| Skills | 现有 Atlas SkillRegistry |
| Local model runtime | Hermes managed local_runtime 通过 Atlas adapter |
| UI | Atlas Electron |

禁止：
- 嵌一个完整 OpenClaw agent runtime 当第二核心；
- 再造第二 Scheduler；
- 再造第二 SessionDB；
- 再造第二 Skill registry；
- 再造第二 Computer/Browser runtime；
- 把 Bot 各自复制一份模型/skill/session 系统。

---

# 3. Phase P2 — Persistent Agent / Bot Mode

## 目标

把现有 Atlas `ProfilesPanel` / AgentProfile 升级成真正长期 Agent：

每个 persistent agent 至少拥有：
- stable agent_id
- name/avatar/description/instructions
- model/provider/reasoning
- enabled skills
- tool allow/deny
- permission mode
- workspace
- own long-lived conversation/session lineage
- heartbeat config
- channel bindings
- automation ownership
- browser profile identity
- device/computer ownership preference
- status/presence
- last activity / last error

不要复制 MemoryOS；Memory 继续冻结。需要“Bot memory”时先复用当前 Agent/Profile + Hermes session/memory能力。

## 来源

OpenClaw 架构语义：
- `docs/gateway/config-agents/**`
- `src/agents/**`
- `src/gateway/**`

Hermes 产品/UI：
- `apps/desktop/src/plugins/hermes-bots/**`
- `group-chat*.tsx`
- create/edit/roster/identity/canonical-chat/cron UI

## Atlas UX

新增“Agents / 我的 Atlas”面板：
- Agent 列表
- 创建/编辑/启停
- 点 Agent 进入它的长期聊天
- 状态：空闲/工作中/等待用户/离线
- 当前模型/设备/渠道
- heartbeat
- routines
- 浏览器/电脑
- skills

把现有普通 Profile 迁移为：
- default/architect/reviewer 保留；
- profile 可选择“临时角色”或“长期 Agent”；
- 不破坏现有 composer role 选择。

## 多 Agent 协作

吸收 Hermes Bot group chat：
- 建群
- 加 Agent
- @ 指定
- Round/轮询
- handoff
- shared group timeline

但 Agent 内部仍通过 Atlas/Hermes 原有 child/delegation/runtime 工作，不重新造模型循环。

---

# 4. Phase P3 — Gateway + Channels

## 目标

Atlas 在笔记本上常驻后，用户可以从桌面、网页、Telegram/Slack/飞书/钉钉/企业微信/Email/Webhook 发任务。

## Gateway 架构

按 OpenClaw 吸收：
- long-lived gateway process
- connection registry
- per-channel account binding
- channel → agent routing
- reconnect/backoff
- liveness/heartbeat
- dedupe/idempotency
- owner DM / group/mention gating
- delivery queue
- attachment normalization
- status/presence
- restart recovery
- device identity/pairing

重点源码族：
- `src/gateway/**`
- `packages/gateway-protocol/**`
- channel/plugin framework

跨语言：不要硬抄 TS 到 Python 形成缩水实现。先抽协议/state machine；能独立成 Node sidecar 且不重复 Agent core 的部分，可以作为 Atlas bundled Node gateway component。若 sidecar 会带入第二 Agent runtime，则拒绝，改 Python thin implementation + tests 对齐语义。

## Channel adapter：优先直接搬 Hermes Python

直接从最新 fork 接：
- Telegram：`plugins/platforms/telegram/**`
- Slack：`plugins/platforms/slack/**`
- Feishu：`plugins/platforms/feishu/**`
- DingTalk：`plugins/platforms/dingtalk/**`
- WeCom：`plugins/platforms/wecom/**`

再做：
- Email
- generic Webhook

所有 adapter 进入同一 Atlas channel plugin contract。

不要一开始手写 29 个渠道。
**先把框架做到可直接挂 adapter**；本波真实接通上面 7 类即可。其他 OpenClaw/Hermes 渠道以后就是插件安装，不需改 Gateway core。

## 消息行为

- incoming message → route persistent agent/session
- 支持文本/图片/文件
- 回复回原渠道
- clarify/approval 能回渠道
- 长任务进度只发重要节点，不刷屏
- background completion 能回原渠道
- channel session 与桌面打开的是同一个 conversation，不复制

---

# 5. Phase P4 — Heartbeat / Proactivity

## 目标

Agent 没人叫时也能按规则主动检查世界，但“不变化就不烧模型、不通知”。

## 直接吸收 OpenClaw heartbeat 状态机

来源：
- `src/infra/heartbeat-runner*.ts`
- `src/infra/heartbeat-*.ts`
- `src/cron/heartbeat-*.ts`
- `src/gateway/server-chat-heartbeat.ts`

实现：
- per-agent heartbeat
- interval
- active hours
- quiet hours
- cooldown
- busy guard
- one heartbeat per agent lane
- event-driven wake
- process completion wake
- schedule wake
- restart continuation
- stable isolated heartbeat session
- delivery target
- dedupe
- no-change → no notification
- no-change → 尽量 no-model（源能先 cheaply diff 的先 diff）

Heartbeat 本身不直接拥有工具；它唤醒现有 Atlas Agent runtime。

UI：
- Agent 设置页显示 heartbeat 开关/间隔/活跃时间/最后检查/最后动作
- timeline 显示 heartbeat 触发原因
- 用户可看“为什么主动找我”

---

# 6. Phase P5 — Durable Automation / Cron

## 目标

把 Atlas 现有 Automation/Goal/Scheduler 收成一套真正可靠的后台任务系统。

## 三层组合

### DBOS = durable execution

继续使用现有 Atlas DBOS backend：
- durable workflow
- queue
- crash/restart resume
- durable sleep
- retries
- concurrency

不再建第二 durable DB。

### OpenClaw = scheduling/recovery semantics

吸收：
- `src/cron/**`
- `src/agents/tools/cron-tool*.ts`
- `packages/gateway-protocol/src/schema/cron*.ts`
- `docs/automation/cron-jobs/**`

重点：
- one-shot / recurring
- startup recovery
- missed-run policy
- no duplicate fire
- owner
- delivery outcome
- run history
- cancel active run
- blocked/failed outcome
- event/condition watcher
- webhook trigger

### Hermes = Agent-facing product surface

直接参考/复用：
- `cron/**`
- `hermes_cli/cron.py`
- `apps/desktop/src/app/cron/**`
- `apps/desktop/src/plugins/hermes-bots/cron*.tsx`

能力：
- model-created cron
- no-agent/script job
- attach skills
- per-job model/reasoning
- deliver channel
- edit/pause/resume/run-now/delete
- natural-language scheduling

## 单一状态

Atlas Automation 是产品状态。
DBOS workflow id 只是 durable execution handle。
Hermes/OpenClaw 结构映射到 Atlas state，不保留三套 job database。

---

# 7. Phase P6 — Atlas 自己的电脑 / Paired Node

## 用户目标

专用 Windows 笔记本就是 Atlas 自己的电脑，不是 Linux 虚拟桌面。

## 来源组合

OpenClaw：
- node/pairing/placement/device identity/presence
- `src/agents/session-placement-computer.ts`
- `src/agents/tools/computer-tool-*.ts`
- `src/gateway/desktop/computer-owner.ts`
- `packages/gateway-protocol/src/schema/computer.ts`

Hermes：
- Bot Screen 的 takeover UX
- `apps/desktop/src/plugins/hermes-bots/screen-*.tsx`

Atlas：
- X2 Windows Computer/Browser 是实际执行层

## 实现

Device registry：
- device_id
- display_name
- capabilities
- OS
- online/presence
- last_seen
- Atlas-owned vs user-owned
- computer/browser capability
- default agent bindings

Laptop：
- 标记为 Atlas-owned device
- startup/service
- health
- reconnect
- sleep/wake state
- network reconnect
- background Computer Use
- persistent browser profile

主机/手机：
- 只作为 ingress/control surface，不把本地桌面错误暴露给 Agent

## Takeover

Bot Screen UX 改造成 Windows：
- 用户看到 Atlas 当前电脑画面/状态
- Agent 正在操作时有 activity
- 登录/2FA/CAPTCHA → handoff
- 用户操作后“还给 Atlas”
- handoff 原地续跑

不搬 Xfce/noVNC backend。

---

# 8. Phase P7 — Managed Local Models

## 目标

Atlas 除了接 Ollama/LM Studio，还能自己管理 llama.cpp / GGUF。

## 主体直接复用 Hermes

来源：
- `hermes_cli/local_runtime/**`
- `hermes_cli/web_routers/local_models.py`

不要复制代码到 `core/atlas`。
通过 pinned Hermes fork adapter 暴露 API。

UI 至少：
- 硬件检测
- 安装/更新 runtime
- backend（CUDA/Vulkan/HIP/CPU）
- 搜 HF/GGUF
- 下载/暂停/继续
- 导入本地 GGUF
- 模型 fit / VRAM/RAM estimate
- context recommendation
- 启动/停止
- idle unload
- 当前 server
- 错误诊断

## OpenClaw 补强

吸收：
- Windows managed llama.cpp 缺 Microsoft runtime 时的本地补齐/诊断思路
- local provider activation probe

**激活本地模型前必须跑：**
1. health/completion
2. 一次真实工具调用（用隔离 fake/local harmless tool）

只有两者都通过才标“可作为默认 Agent 模型”。

LM Studio/Ollama：
- 继续作为 external runtime
- UI 可探测
- 不由 Atlas 管它们进程（除非已有现成功能）

---

# 9. Phase P8 — Skill Workshop / Curator 继续升级

现有 X4/X5 不推倒。

继续吸收 OpenClaw 当前 Skill Workshop：
- per-agent learned-skill collection
- proposal
- pending
- diff
- approve/reject
- rollback metadata
- source provenance
- watcher
- autonomous suggestion

结合 Hermes curator：
- dedupe
- merge
- stale/outdated
- background maintenance

所有结果仍落同一个 Atlas SkillRegistry。

来源类型新增清楚：
- marketplace
- plugin
- project
- user
- local_recorded
- local_evolved
- agent_learned

Agent 可有“默认启用/建议技能”，但技能实体不复制 N 份。

---

# 10. Phase P9 — UI 一次收口

不要做七八个新侧栏入口。

建议信息架构：

### 左栏
- 聊天
- Agents
- 自动化
- 技能
- 设备
- 自动追新

### Agent 详情
Tabs：
- 聊天
- 身份/模型
- Skills
- Channels
- Heartbeat
- Automations
- Computer/Browser
- Activity

### 设置
- Gateway
- Channels/accounts
- Devices
- Local models

复用现有浅色主题和组件，不重做 Atlas 首页。

---

# 11. Phase P10 — 集成去重

专门开 integration workers 检查：

- 一个 Agent core
- 一个 SessionDB
- 一个 SkillRegistry
- 一个 Automation state
- 一个 DBOS durable layer
- 一个 Computer runtime
- 一个 Browser runtime
- 一个 Gateway route owner
- 一个 device registry

必须删除/禁用重复旧路径，而不是“新旧都留着”。

检查：
- restart
- cold boot
- gateway reconnect
- heartbeat + cron 同时触发
- Agent busy 时 heartbeat
- channel message + desktop 同时操作
- handoff
- device offline/reconnect
- local model crash/restart
- DBOS recovery

---

# 12. Phase P11 — 验收：少而真

速度优先，不做巨型测试矩阵。

## Worker
每 lane focused tests。

## Controller 最终一次

Backend：
- full pytest 最多一次

Frontend：
- renderer tsc
- electron tsc
- Vitest
- Vite build

Fake E2E 至少：

1. 创建 persistent Agent → 重启 → identity/session 还在
2. Telegram/Feishu fake inbound → Agent → reply 原渠道
3. 同一聊天在 channel + desktop 看同一 session
4. heartbeat 无变化 → 不通知
5. heartbeat 有事件 → Agent 醒来 → 通知
6. cron one-shot
7. cron recurring no duplicate
8. restart 后 overdue/recovery
9. no-agent script cron
10. channel-created cron 回原渠道
11. 两个 persistent Agent group handoff
12. device offline → online → queued work继续
13. Computer handoff → user done → 原任务继续
14. managed local runtime fake supervisor
15. local model activation tool-call probe
16. learned skill proposal → approve → Agent 使用

真实 Telegram/Feishu/本地 GPU/Windows desktop smoke 如果需要用户 token/登录：
标 `REQUIRES_USER_DAILY_SMOKE`，不阻塞代码交付。

不用真实付费模型。

---

# 13. 结果与退出条件

结果：
`tasks/results/ATLAS-MEGA-PERSISTENT-ALWAYS-ON.result.md`

必须写：

- source freeze
- 每块最终赢家与为什么
- 直接 port 的 repo/file
- thin adapter 的 repo/file
- 删除的重复 Atlas 旧实现
- Persistent Agent schema
- Gateway/channel architecture
- Heartbeat
- Automation/DBOS
- Device/node
- Local runtime
- Skills Workshop
- tests
- remaining real-user smoke

只有满足下面才能宣称完成：

> **Atlas 已成为常驻个人 Agent：能长期存在、从外部渠道接任务、主动 Heartbeat、可靠定时/条件任务、在自己的 Windows 笔记本上工作、多人/多 Agent 协作、管理本地模型并持续学习技能。**

完成后：
- 更新 `docs/plan/CORE-PARITY.md`
- 更新 `docs/plan/ROADMAP-TO-PRODUCT.md`
- `tasks/CURRENT.md → AWAITING_REVIEW`
- push Atlas main
- 若 Hermes fork 有 tail-sync/patch 也 push
- 核对 local == remote
- 停止

## 不在本波

- X6 实时语音
- 视频生成
- MemoryOS 扩展
- full T1
- R1 release installer 重做

不要自行启动这些。
