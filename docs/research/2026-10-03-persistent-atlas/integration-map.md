# Integration Map — ATLAS-MEGA-PERSISTENT-ALWAYS-ON（P1 定型，编码前冻结）

> 依据：本目录 9 份 lane 报告（r1–r9）+ source-freeze.md。本文件是并行施工的契约。
> 每个 lane 只允许创建/修改"所有者"列属于自己的文件；热文件只由 integration owner 动。

## 1. 层唯一 owner（终版）

| 层 | 唯一 owner | 本波动作 |
|---|---|---|
| Agent loop / model calls / context | Atlas orchestrator + Hermes fork（现有） | 不动 core；run.start 增 agent_id/group_id 入口（integration owner） |
| SessionDB / conversation | Hermes SessionDB `data/engine/state.db`（现有权威） | 禁止第二会话库；channel/desktop/heartbeat 全部复用 |
| Persistent Agent registry | **新** `core/atlas/persistent_agents/`（W1） | AgentProfile store（`data/profiles/*.toml`）扩展 persistent 字段，单存储 |
| Group chat | **新** `core/atlas/groups/`（W8，二波） | 服务端编排（port Hermes hosted_rooms 语义），复用 child delegation |
| Gateway ingress/routing | **新** `core/atlas/channels/`（W2） | Python 重实现 OpenClaw 协议/状态机；**不做 Node sidecar**（R1 结论：sidecar 会拖入完整 agent runtime） |
| Channel adapters | `core/atlas/channels/adapters/`（W2a/W2b） | 统一 ChannelAdapter ABC；Telegram 收编现有 telegram.py |
| Heartbeat | **新** `core/atlas/heartbeat/`（W3） | OpenClaw 守卫链/冷却/wake 总线/no-change 合同；tick 只由 automation engine 驱动 |
| Automation 产品状态 | **新** `core/atlas/automation/`（W4） | 单一产品状态库 `data/automations.toml`；AtlasScheduler 退役为一次性导入器后删除 |
| Durable execution | 现有 DBOS backend（dbos==3.0.0，SQLite） | create_schedule/queue/恢复/run history 全用 DBOS 原生；不建第二 durable 层 |
| Cron Agent API | `api/automation_router.py`（W4）+ agent 工具（integration） | Hermes cron 产品面 ∪ OpenClaw cron-tool actions |
| Computer/Browser | 现有 X2 | 不重造；W5 只做 device registry + takeover 状态机 |
| Device/node ownership | **新** `core/atlas/devices/`（W5） | 本机=atlas-owned laptop；主机/手机=ingress only |
| Skills | 现有 `core/atlas/skills/` SkillRegistry（W7 扩展） | 单一 registry；per-agent 用关系表，不复制技能实体 |
| Local model runtime | Hermes fork `hermes_cli/local_runtime`（pin→`ef4571dec5`）+ **薄 adapter**（W6） | 进程内 import（方案 A）；禁复制到 core/atlas |
| UI | Atlas Electron（W9，二波收口） | 复用浅色主题；Sidebar 一级入口收口 |

## 2. 新模块文件树（锁定）

```
core/atlas/persistent_agents/        # W1
  __init__.py        PersistentAgentService: CRUD/status/lineage/config 解析
  store.py           TomlRecordStore("profiles") 扩展字段读写（单一存储 data/profiles/*.toml）
core/atlas/groups/                   # W8（二波）
  __init__.py        GroupOrchestrator: room log/watermark/round-robin/@resolve/handoff
  store.py           data/groups/*.toml（群定义+成员+timeline 元数据）
core/atlas/channels/                 # W2a: contract/routing/ingress/delivery/gating/credentials/manager + telegram/webhook/email
                                     # W2b: slack/feishu/dingtalk/wecom
  __init__.py        ChannelManager（gateway 唯一 owner：连接注册表/生命周期/reconnect backoff/liveness）
  contract.py        ChannelAdapter ABC + MessageEvent/MessageType 归一化（**controller 已写定并冻结，W2a/W2b 直接 import，不得改**）
  routing.py         bindings + resolve_route（port OpenClaw peer→parentPeer→wildcard→…→唯一兜底）
  ingress.py         SQLite durable ingress 队列 + claim + 墓碑去重（port OpenClaw dedupe 语义）
  delivery.py        出站投递队列 + 重试退避 + 幂等键
  gating.py          dmPolicy/groupPolicy/mention gating
  credentials.py     KeyringCredentialStore 上移；键名 atlas.channel.<name>.<field>（保留旧 atlas.telegram.bot_token 兼容）
  adapters/telegram.py   收编 core/atlas/telegram.py（httpx 轮询，零 SDK）
  adapters/webhook.py    新写（HMAC v2 时间戳防重放）
  adapters/email.py      新写（stdlib imaplib/smtplib）
  adapters/slack.py      新写 + 整搬 hermes block_kit.py（纯 stdlib）
  adapters/feishu.py     新写（lark-oapi WS，懒加载）
  adapters/dingtalk.py   新写 + 整搬 hermes inbound.py（Stream Mode）
  adapters/wecom.py      新写 + 整搬 hermes wecom_crypto.py/send_queue.py（HTTP 回调模式）
core/atlas/heartbeat/                # W3
  __init__.py        HeartbeatService（per-agent 状态、隔离 session 键、delivery target）
  guards.py          纯函数守卫链：disabled→active/quiet hours→preflight→busy→cooldown（port OpenClaw 顺序与参数）
  wake.py            wake 总线：task/scheduled/event 三槽、250ms 合并、优先级 manual>task>interval>retry
  outcome.py         heartbeat_respond 结构化合同（outcome: no_change|progress|done|blocked|needs_attention; notify; summary; nextCheck; scratch）
core/atlas/automation/               # W4
  __init__.py        AutomationService（产品状态唯一 owner）
  store.py           data/automations.toml 读写（字段见 §4）
  engine.py          DBOS 接线：create_schedule(cron)/自续 workflow(interval)/enqueue(event|webhook)/run receipt=DBOS RUNNING workflow
  migrate.py         AtlasScheduler TOML 一次性导入器（导入后旧 scheduler 弃用）
  triggers.py        event 文件 watcher + webhook 入口 → enqueue
core/atlas/devices/                  # W5
  __init__.py        DeviceRegistry（data/devices/devices.json；本机自注册 kind=atlas-laptop）
  takeover.py        控制权状态机 FREE/HUMAN/AGENT + 卡片 handoff（不自动接管/不重放/变权先观察）
core/atlas/engine/local_runtime_adapter.py   # W6（唯一新 engine 文件）
core/atlas/skills/                   # W7
  proposals.py       SkillProposalRecord：pending/applied/rejected/stale + revisionHash + 事件账本 + rollback
  agent_collections.py  agent_skills 关系表（default_enabled/learned/suggested/adopted）+ usage 遥测
  watcher.py         技能目录 watcher（P3 期）
  evolution/curator_runner.py         后台 curator（P2 期）
core/atlas/api/                      # 各 router 由对应 lane 新建；server.py 挂载由 integration owner 做
  agent_router.py            # W1：/api/agents CRUD/status/heartbeat/channels 绑定
  group_router.py            # W8：/api/groups
  channel_router.py          # W2：/api/channels
  automation_router.py       # W4：/api/automations + runs + run-now/cancel
  device_router.py           # W5：/api/devices + takeover
  local_models_router.py     # W6：/api/local/models/*
  agent_skills_router.py     # W7：/api/agents/{id}/skills + /api/skill-proposals
```

## 3. Persistent Agent 数据模型（W1 锁定，落 `data/profiles/*.toml` 扩展字段）

现有白名单字段保留（id,name,description,model,reasoning_effort,instructions,active_skills,tools{allow,deny},mode,created_at,updated_at）+ 新增：

```
kind = "role" | "persistent"          # 缺省 role；default/architect/reviewer 恒为 role
agent = {
  enabled = true
  status = "idle|working|waiting_user|offline"     # 运行时投影，落 store 仅 last_status
  workspace = ""                       # 缺省继承主 workspace
  heartbeat = {
    enabled = false
    interval_minutes = 30
    active_hours = ""                  # "09:00-23:00"，空=全天
    prompt = ""                        # 检查指令
    delivery = "owner|none|<channel:target>"
    isolated_session = true
  }
  channels = [ { channel="telegram", target="<chat_id>", account="" } ]   # 入站绑定
  automations = []                     # 该 agent 拥有的 automation id（由 W4 回写）
  device_preference = ""               # 缺省=本机
  browser_profile = ""
  last_activity_at / last_error        # 状态投影
}
```

约束：技能实体不复制（active_skills 引用 registry）；会话 lineage=Hermes SessionDB 内该 agent 的 session 键约定 `agent:<id>:[channel:[account]:]kind:peer`（port OpenClaw 键语法，Atlas 落地为 hermes session title/metadata 约定，由 W1 定义 `session_key()` 纯函数，全波唯一实现处）。

## 4. Automation job 字段（W4 锁定，`data/automations.toml`）

```
id, name, enabled
owner_agent_id = ""                    # 空=系统
trigger = { kind = "cron|interval|date|event|webhook", cron_expr, tz, every_seconds, at, event_path, event_debounce }
payload = { kind = "agent_turn|heartbeat|script", message, agent_id, model, skills, script, timeout_seconds, wake_mode }
delivery = { mode = "none|channel", channel, target }
policy = { missed_run = "catchup|skip", max_catchup = 5, delete_after_run, consecutive_error_disable = 10 }
state（运行投影，不进产品编辑面）: next_run_at, last_run_at, last_status, consecutive_errors, paused_reason
```

DBOS 映射：cron→`create_schedule`（`sched-{id}-{iso}` 幂等 id、automatic_backfill=policy.missed_run=="catchup"）；interval→自续 workflow + `DBOS.sleep`（固定 workflow_id ReusePolicy）；date→enqueue `delay_seconds`；event/webhook→watcher enqueue + deduplication_id；run receipt=DBOS RUNNING workflow（替代 OpenClaw 自建 receipt）；run history=DBOS list_workflows(attributes.filter)。
心跳 tick：payload.kind=="heartbeat" → engine 调 `HeartbeatService.tick(agent_id, reason="schedule")`（W3↔W4 唯一接缝）。

## 5. REST/WS 契约（integration owner 按此挂载）

- `/api/agents` GET list（含 status 投影）/ POST create / `/{id}` GET PATCH DELETE；`/{id}/heartbeat` PUT；`/{id}/sessions` GET（lineage 查询，走 SessionDB）；`/{id}/skills` GET PUT（W7）
- WS `run.start` 增可选 `agent_id`、`group_id`（integration owner 在 `_handle_run_start` 最小增量；W1 提供 `resolve_agent_run_config(agent_id)`）
- `/api/groups` CRUD + `/{id}/members` + `/{id}/timeline`（W8）
- `/api/channels` GET status / PUT accounts / POST test / `/{channel}/inbound`（webhook 接收）
- `/api/automations` CRUD + `/{id}/run-now` `/{id}/cancel` `/{id}/runs` + `/api/automations/import-legacy`
- `/api/devices` GET / `/{id}` PATCH / `/{id}/takeover` POST {action: human_take|agent_take|release} / `/{id}/activity` GET
- `/api/local/models/*`：status/hardware/catalog/search/download(+pause/resume)/sideload/server{start,stop}/activate/eject（全部转调 adapter）
- `/api/skill-proposals` GET POST / `/{id}/approve` `/{id}/reject`

## 6. 并行施工规则

- Wave 1（并行）：W1 persistent agents、W2a channels 框架+3 adapter、W2b channels 4 adapter、W3 heartbeat、W4 automation、W5 devices、W6 local models、W7 skills。
- Wave 2（Wave 1 落地后）：W8 group chat、W9 UI 收口、W10 integration owner（server.py/lifespan/_handle_run_start/telegram 迁移切换）。
- 测试纪律：lane 测试自建 TestClient(app=FastAPI()+自己的 router)；DBOS 用独立 sqlite 文件 fixture；禁止 lane 间 import 对方未落地模块——跨 lane 依赖只允许 import §2–§5 冻结的契约签名。
- commit：lane 完成后报告；controller 逐 lane review+commit+push（避免 git index 竞争）。
- 热文件：`server.py`/`App.tsx`/`useAtlasStore.ts`/`hermes_runtime.py` Wave 1 期间零改动。
