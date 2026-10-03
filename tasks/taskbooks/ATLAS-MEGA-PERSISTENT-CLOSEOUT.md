# ATLAS-MEGA-PERSISTENT-CLOSEOUT：Persistent / Always-On 收口续做

> 这是 `ATLAS-MEGA-PERSISTENT-ALWAYS-ON` 的续做任务书。
> 当前远端基线：`main @ 631b5f6ad030e283bebe5fc64833ca68a55641fc`。
> 不重新研究，不重做 W1-W7；从已同步的中途断点继续，把 integration wiring 与 P11 缺口彻底收口。

---

## 0. 开工纪律

先执行：

```bash
git switch main
git pull --ff-only
git status
git log -8 --oneline
```

确认 HEAD 至少包含：

`631b5f6ad030e283bebe5fc64833ca68a55641fc`

然后读取：

- `tasks/CURRENT.md`
- `tasks/taskbooks/ATLAS-MEGA-PERSISTENT-ALWAYS-ON.md`
- `docs/research/2026-10-03-persistent-atlas/integration-map.md`
- `docs/research/2026-10-03-persistent-atlas/p11-acceptance-map.md`

禁止重新实现：

- W1 Persistent Agent
- W2 Gateway / Channels
- W3 Heartbeat
- W4 Automation / DBOS
- W5 Devices
- W6 Managed Local Models
- W7 Skill Workshop

这些都已经进 main。

---

## 1. 当前已知断点

上一批提交：

`631b5f6 feat(mega-persistent): W8 integration batch — groups chat + gateway wiring + UI closeout (frontend green 155/155, backend focused 26/38 wiring errors open) + P11 acceptance map`

现状：

- 前端本批：155/155 green
- 后端 focused：26/38
- Persistent Agent 已接入真实 server
- `run.start` 已支持 `agent_id`
- Channel / Automation / Device / Local Models / Agent Skills / Agent Router 已开始真实挂载
- Gateway / Heartbeat / Automation 已开始接真实 lifespan
- Groups backend / router 已写
- `group_id` 仍处于 `group chat wiring pending`
- P11 当前：9 COVERED / 5 PARTIAL / 2 MISSING

本任务目标：

> 修完当前 wiring 错误，把已写模块真正接通，P11 不再有真实 MISSING，写 result，CURRENT -> AWAITING_REVIEW。

---

## 2. 子代理并发

ZCodex 是 controller，不是主要 coder。

必须：

- 尽量开到当前 runtime 实际允许的最大并发
- spawn 撞并发上限就缩 batch，槽位释放后继续派
- 不允许因为一次 spawn 失败退回单线程
- worker 跑 focused tests
- controller 做热文件整合、review、最终验收

建议 lane：

- L1 Group Chat 最终接线
- L2 Persistent Agent session + desktop/channel conversation 同源
- L3 Automation / Heartbeat -> Channel 真投递
- L4 Device offline/reconnect + takeover/X2 handoff
- L5 Learned Skill -> 真 Agent runtime
- L6 P11 integration tests
- L7 Frontend regression

热文件：

- `core/atlas/server.py`

只允许一个 integration owner 最后统一改。

---

## 3. CLOSEOUT-1 — Group Chat 真正接入 Agent Runtime

已有：

- `core/atlas/groups/`
- `core/atlas/api/group_router.py`
- round robin
- @ mention
- handoff
- timeline
- persistent-agent 成员校验

必须完成：

1. 挂载 `group_router`
2. 初始化 `GroupOrchestrator`
3. 接真实 `PersistentAgentService`
4. `run.start(group_id=...)` 不再被 `group chat wiring pending` 拒绝
5. group turn 调用现有 Atlas/Hermes Agent runtime
6. 每个成员使用自己的 persistent agent 配置
7. 稳定 session lineage，例如：
   `agent:<agent_id>:group:<group_id>`
8. 支持 round robin / @agent / handoff / stop(epoch) / timeline

禁止造第二 Agent loop。

Fake E2E：

- alice -> `@bob 请继续`
- bob -> `done`

必须看到两个真实 persistent Agent 经现有 runtime 连续执行，并写同一 group timeline。

---

## 4. CLOSEOUT-2 — Persistent Agent Session 真正长期化

当前 `GET /api/agents/{id}/sessions` 仍有 integration stub。

必须补：

### Agent 重启持久化

创建 persistent Agent 后保存：

- identity
- model
- heartbeat
- channels
- workspace
- status

销毁 service/store，重新打开同一个 data root，信息仍在。

### Session lineage

Channel session mapping 必须持久。

重启 SessionMapper / Gateway 后：

相同 agent + channel + account + peer 仍映射到同一 conversation。

### Agent Sessions API

`GET /api/agents/{id}/sessions`

不能再返回占位说明，必须返回真实 session/conversation 列表。

---

## 5. CLOSEOUT-3 — Desktop 与 Channel 共用同一 Conversation

必须证明：

> Telegram / Feishu / Webhook 发来的任务，与桌面打开的是同一个 conversation，不复制聊天。

Fake E2E：

1. channel inbound
2. Gateway route persistent Agent
3. Agent 回复
4. 得到 conversation_id
5. `GET /api/conversations`
6. 桌面 API 能看到相同 conversation_id
7. `GET /api/conversations/{id}/messages`
8. 同时含 inbound user message 与 assistant response

禁止维护第二套 channel conversation 数据。

---

## 6. CLOSEOUT-4 — Automation / Heartbeat 真正回原渠道

闭合真实链：

`Automation -> _automation_deliver -> Gateway -> ChannelAdapter.send`

Fake E2E：

- trigger = interval/date
- payload = script/agent_turn
- delivery.mode = channel
- channel = fake
- target = 100

触发后 FakeAdapter 必须收到结果。

Heartbeat 同样闭合：

`event wake -> Agent -> notify=true -> delivery target -> Gateway -> channel`

而 `NO_REPLY / no_change` 继续保持零通知。

---

## 7. CLOSEOUT-5 — Device offline / reconnect 语义收口

本波目标仍是：

> Windows 专用笔记本 = Atlas 自己的电脑。

不要为 P11 额外造复杂远程 device queue。

本波语义：

- app restart
- temporary offline
- network reconnect
- sleep/wake

Atlas-owned laptop 上的 DBOS durable work 不丢，恢复后继续。

把 device presence + durable recovery 接起来验证。

若“远程 ingress device 离线任务队列”不属于本波产品语义，在 result 明确写：

`Remote ingress-device queued execution: not required for Atlas-owned laptop semantics in this wave.`

---

## 8. CLOSEOUT-6 — Takeover ↔ X2 Handoff 打通

当前已有：

### X2
- pending request
- foreground confirmation
- blocked run continuation

### Device
- takeover state machine
- handoff card

必须桥接：

`Agent Computer Use -> 登录/2FA/CAPTCHA -> HUMAN takeover -> 原 run blocked -> 用户 Done/Give Back -> pending resolve -> 重新 observe -> 原 run 继续`

不要重做 X2，只做 bridge。

Fake E2E 至少证明：

`blocked -> human_take -> done -> pending resolve -> original execution resumes`

---

## 9. CLOSEOUT-7 — Learned Skill 真正进入 Agent Run

当前已有：

`proposal -> approve -> SkillRegistry -> AgentSkillCollections`

运行时必须合并：

`effective_skills = profile.active_skills ∪ AgentSkillCollections.effective_skills(agent_id)`

禁止复制 skill entity，仍使用唯一 SkillRegistry。

Fake E2E：

1. Agent 创建 learned skill proposal
2. approve
3. relation=learned + enabled
4. 下一次该 Agent run
5. runtime 真正加载技能
6. FakeLLM / system / run context 能证明技能已进入本次 run

---

## 10. CLOSEOUT-8 — 修完当前 backend wiring errors

先跑 focused integration，不要先 full pytest。

重点：

- `test_server_agents_wiring.py`
- `test_gateway_integration.py`
- `test_groups.py`
- `test_groups_router.py`
- `test_persistent_agents.py`
- `test_heartbeat_service.py`
- `test_automation_engine.py`
- `test_devices_registry.py`
- `test_devices_router.py`
- `test_devices_takeover.py`
- `test_x2_pending.py`
- `test_skill_proposals.py`
- `test_agent_skills.py`

把当前 `26/38` 修到当前 suite 全绿；新增 closeout E2E 后以新增后的全部 green 为准。

---

## 11. P11 最终 16 项

以：

`docs/research/2026-10-03-persistent-atlas/p11-acceptance-map.md`

为准。

必须最终闭合：

1. Persistent Agent restart 后 identity/session 保留
2. Telegram/Feishu fake inbound -> Agent -> 原渠道回复
3. Channel + desktop 同一 conversation
4. Heartbeat no-change -> 不通知
5. Heartbeat event -> Agent -> 通知
6. Cron one-shot
7. Cron recurring no duplicate
8. Restart recovery
9. No-agent script cron
10. Automation -> 原渠道 delivery
11. 两个 persistent Agent group handoff
12. Atlas-owned laptop offline/restart -> durable work continuation
13. Computer handoff -> user done -> 原 task continuation
14. Managed local runtime fake supervisor
15. Local model activation tool-call probe
16. Learned skill approve -> Agent 真使用

最终映射里不应再有真正的 `MISSING`。

真实 token / 真桌面 / 真 GPU / 真安装器可以标：

`REQUIRES_USER_DAILY_SMOKE`

不得因此阻塞本轮代码完成。

---

## 12. UI

上一轮前端已 155/155 green。

只修 integration 所需内容，不重做设计。

保持：

一级入口：
- Chat
- Agents
- Automations
- Skills
- Devices
- 自动追新

Groups 不额外制造重复导航；按现有 W8/W9 收口方案放置。

Settings：
- Channels
- Gateway
- Local Models
- Devices

Agent 详情：
- Chat
- Identity
- Skills
- Channels
- Heartbeat
- Automations
- Computer
- Activity

---

## 13. 去重检查

最终确认仍只有：

- 一个 Agent runtime
- 一个 SessionDB
- 一个 SkillRegistry
- 一个 Automation product state
- 一个 DBOS durable layer
- 一个 Computer runtime
- 一个 Browser runtime
- 一个 Gateway
- 一个 Device registry

特别检查：

### Telegram
旧 Telegram service 与新 Gateway adapter 不能双 poll。

### Scheduler
旧 scheduler 只能作为 legacy importer，不再与 Automation 双运行。

---

## 14. 测试纪律

速度优先。

Worker 只跑 focused tests。

Controller 最后：

Backend：
1. integration focused suite 全绿
2. full pytest 正式最多一次

Frontend：
- renderer tsc
- electron tsc
- Vitest
- Vite build

真实 Telegram / Feishu / Slack / DingTalk / WeCom / Email、真 Windows Computer Use、真 GPU llama.cpp、安装器，缺环境时标 `REQUIRES_USER_DAILY_SMOKE`。

---

## 15. 结果与退出

完成后创建：

`tasks/results/ATLAS-MEGA-PERSISTENT-CLOSEOUT.result.md`

记录：

- 基线 `631b5f6`
- 本轮 commits
- wiring errors 修复
- Group Chat 接线
- Agent Session
- Desktop/Channel conversation 同源
- Automation/Heartbeat channel delivery
- Device recovery
- X2 takeover bridge
- Learned Skill runtime bridge
- P11 16 项最终状态
- backend tests
- frontend checks
- REQUIRES_USER_DAILY_SMOKE
- 删除/关闭的重复路径

然后：

`tasks/CURRENT.md -> STATUS: AWAITING_REVIEW`

push Atlas main，核对 local HEAD == origin/main，然后停止。

不要继续启动：

- X6 realtime voice
- T1
- R1
- MemoryOS
- 新 UI 大改
- 新一轮上游研究

---

## 16. 完成标准

只有全部成立才能结束：

- Persistent Agent 真能长期存在
- Desktop / Channel 共用 conversation
- Gateway 真能派任务
- Heartbeat 真能主动工作
- Cron/Automation 真能持久恢复
- Automation/Heartbeat 结果能回原渠道
- 多 Agent 真能 group / handoff
- Windows 笔记本能作为 Atlas-owned computer
- Human takeover 能回到原任务
- Local Models 可托管并过工具调用 probe
- Agent 学到的 Skill 下一次真能用
- P11 无 MISSING
- integration green
- frontend green
- CURRENT = AWAITING_REVIEW

**最重要：从 `631b5f6` 继续修和接线。不要重新实现已经完成的 W1-W7，也不要重新做大规模调研。**
