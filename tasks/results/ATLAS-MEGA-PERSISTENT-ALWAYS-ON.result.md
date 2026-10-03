# ATLAS-MEGA-PERSISTENT-ALWAYS-ON — 结果

> 状态：AWAITING_REVIEW（2026-10-04）
> 基线：`a034bff` → 收尾提交见 git log；Hermes fork `unicorn-Y/hermes-agent@atlas` = `ef4571dec5`（= origin/atlas，已推送）

## 1. Source freeze（开工冻结，详见 source-freeze.md）

| 来源 | 冻结 HEAD | 本波用法 |
|---|---|---|
| OpenClaw `main` | `3e5560873a4`（任务书旧值 `899a0ca681` 已前进，以冻结值为准） | 只读参考（语义/状态机移植源） |
| NousResearch/hermes-agent `main` | `c8301ea6c9` | fork tail-sync 目标 |
| dbos-transact-py `main` | `03fb5c92` | 现有 DBOS backend 继续用，未升级 |
| Atlas `main` | `a034bff` | 本波施工基线 |
| unicorn-Y/hermes-agent `atlas`（fork） | `7912500ffd` → tail-sync `ef4571dec5`（合并 upstream 9 个 local-runtime 修复） | 进程内 import 的 pinned 依赖（`core/pyproject.toml:47` git pin 已 bump） |

## 2. 每块最终赢家与为什么

| 层 | 赢家 | 为什么 |
|---|---|---|
| Agent loop / 模型调用 | Atlas + Hermes fork（现状） | 唯一 Agent core；OpenClaw 仅语义移植，未嵌入（审计 #1 CLEAN） |
| Persistent Agent | Atlas `persistent_agents/`（新） | OpenClaw config-agents 语义 + Hermes hermes-bots 产品面；落 TOML 单存储（与 role profiles 同目录不同 record kind） |
| 群聊 | Atlas `groups/`（新，FakeDispatcher 状态机先证） | Hermes group-chat 面太重（TS desktop），状态机/轮转/handoff 语义移植 + REST 产品面 |
| Gateway + 渠道 | Atlas `channels/` + `gateway_service.py`（Python 重实现） | OpenClaw gateway 是 TS 且会带入第二 Agent runtime（任务书明令拒绝 sidecar 形态）；协议/状态机照 OC，adapter 直搬 Hermes Python |
| Heartbeat | Atlas `heartbeat/`（OC guard 链移植） | guard 链/wake bus/outcome 契约是纯语义，移植后与 Atlas host 缝（agent registry/orchestrator/delivery）对接 |
| Durable/Cron | 现有 DBOS backend + Atlas `automation/` | 不建第二 durable DB；OC cron 语义（幂等 sync/no-duplicate/missed policy）+ Hermes cron 产品面（model-created/脚本任务/渠道投递） |
| Device/接管 | Atlas `devices/` | OC placement 语义 + Hermes takeover UX 状态机化；X2 仍是唯一执行层 |
| 本地模型 | Hermes fork `local_runtime` 进程内 import（thin adapter） | 任务书选项 A；不复制代码，API 面漂移由 fork pin 控制 |
| Skills | 现有 SkillRegistry + W7 proposal/collections | 一个 registry；collections 是投影；agent_learned 批准后经 W8 桥接进 run |
| UI | Atlas Electron（W8 一次收口） | Agents 页 + 8 tabs、群聊、设备/接管卡、渠道/本地模型设置、自动化页重做；不新增侧栏入口群 |

## 3. 直接 port / thin adapter 明细

**直接 port（Python→Python）：**
- 渠道 adapter：`slack/feishu/dingtalk/wecom` 移植自 Hermes `plugins/platforms/**` @ `c8301ea6c9`（telegram/email/webhook 为 Atlas 原生同 contract 实现）
- OpenClaw 语义移植（TS→Python 状态机，非缩水仿写）：heartbeat guard 链/retain/dedup（`src/infra/heartbeat-*`）、cron 幂等/no-duplicate（`src/cron/**`）、gateway routing/gating 状态机（`src/gateway/**`）、computer placement/pairing 语义（`src/agents/session-placement-computer.ts` 等）
- 群聊轮转/handoff/@ 解析：Hermes group-chat 语义（round-robin + mention 插队 + round caps + epoch stop）

**Thin adapter（不复制逻辑）：**
- `core/atlas/engine/local_runtime_adapter.py` → `hermes_cli.local_runtime`（fork 进程内 import；安装/下载/导入/启停/诊断/预算全是直调，仅 job 簿记 ~150 行是 UI 胶水）
- `core/atlas/engine/session_sync.py` / `hermes_policy.py` → 既有 fork 桥（未动）

**Atlas 重复旧实现处置（P10）：**
- 旧 APScheduler：不再默认启动（`scheduler.enabled` 默认 False），`/api/automations/import-legacy` 导入后暂停旧任务（`pause_legacy=True`）——双触发路径关闭；旧代码保留为迁移源
- 旧 telegram 直轮询：与网关渠道互斥从"仅启动时"补到"运行时"（渠道启用 telegram 即停旧 poller）
- 其余 9 项审计 CLEAN（无第二 SessionDB/SkillRegistry/DBOS/Computer/Browser/device/agent registry/模型 supervisor；`channel_sessions` 只是键映射）

## 4. 关键设计落点

- **Persistent Agent schema**：stable `id`、name/description/instructions、model/provider/reasoning、enabled skills（+collections 投影合并进 `effective_skills`）、tool allow/deny、permission_mode、workspace、session lineage（`agent:<id>:{heartbeat,channel:<ch>:<peer>,group:<gid>}`）、heartbeat config、channel bindings、automation ownership（heartbeat-<id>）、status/presence（idle/working/waiting_user/offline + last_error）、browser/computer 偏好。重启持久：TOML + `channel_sessions` sqlite 双证（P11 场景 1 新测试）。
- **Gateway 架构**：`ChannelManager`（凭据/门控/ingress/外发队列：退避+死信+租约回收）→ `GatewayBridge`（session_key 幂等映射、一次入站=一次 run=一条回执、失败/停止单条答、状态投影）→ `_handle_run_start`。群消息：`run.start{group_id}` → `_start_group_turn_run` → `GroupOrchestrator.run_turn`（真 dispatcher 复用 `_collect_orchestrator_text` 引擎缝）。
- **Heartbeat**：`HeartbeatService.tick` guard 链（disabled→quiet-hours→preflight(empty-scratch/no-pending-event)→busy→cooldown(not-due/min-spacing/flood)）；事件唤醒经 wake bus（250ms 合并、retryable busy 保留重试）；无变化=NO_REPLY=零投递；W1↔W4 reconcile 生成/回收 `heartbeat-<agent_id>` 自动化。
- **Automation/DBOS**：产品状态只在 `automation/store`；DBOS workflow id 是执行句柄；interval 自续 loop、cron 走 `create_schedule`、幂等 sync（重 sync 不重建、改签名 delete+create）、`run_now` no-duplicate、脚本 payload 真子进程、delivery ∈ delivered/not-delivered/not-requested。
- **Device/node**：`devices.json` 单注册表、presence 投影（ingress 超时窗口，laptop 常在线）、TakeoverStateMachine + handoff 卡（blocked→resolved→原 run 继续）；设备离线不阻塞本地 durable 工作（场景 12 组合测试）。
- **Local runtime**：HERMES_HOME 进程级 pin；激活闸门 = health + 真实 tool-call probe（`ATLAS_PROBE_TOOL` nonce 回环，`tool_choice:"required"`），probe 失败保留诊断且不得设为默认模型。
- **Skills Workshop**：proposal（pending/diff/approve/reject/rollback，revisionHash 防并发旧写）→ registry active → agent collections 行（learned 默认启用）→ W8 桥接把显式 per-agent 行合并进 run 的 `effective_skills`（decision=global 行不注入不清除——注册表已把全目录标 active，全局注入会炸 8 技能激活上限，W8 权衡记录在案）。

## 5. 测试

**Controller 最终一次（收尾验证）：**
- Backend 全量：**2008 passed, 1 failed, 7 skipped**（30:45）。唯一失败 `test_computer_use.py::test_real_desktop_observe_input_clipboard_and_window_management` = 真桌面窗口创建在 30 分钟满载下超时（已知桌面焦点偶发），单跑复验 **通过**（4.5s）。跳过 7 项为平台/可选依赖。
- Frontend：renderer tsc ✔、electron tsc ✔、Vitest **155/155** ✔、vite build ✔（chunk 体积警告为既有）。
- 注：`test_release_acceptance.py`（安装器真机 smoke）按验收映射标 REQUIRES_USER_DAILY_SMOKE，未纳入全量跑。

**本波新增 focused tests（各 lane 自跑全绿）：**
- W1 persistent agents 36；W2 渠道 156；W3 heartbeat 118；W4 automation/DBOS 43；W5 devices 36；W6 local models 55；W7 skill workshop 20；W8 groups+gateway 接线（wiring 11 + groups 状态机/router）。
- P11 收尾补测（本文件 §6）：场景 1 重启（2）、3 桌面同源（1）、10 渠道回投（1）、11 双 Agent handoff 活体（1）、12 设备离线组合（1）、16 learned skill 进 run（1）；P10 去重 8。

## 6. P11 验收映射终态（16 场景）

- 原 COVERED 9 项不变；PARTIAL/MISSING 7 项全部闭合：
  - #1 重启持久：新 store/service 实例同 root 重开 + SessionMapper 重开同 db（新测试）+ `/api/agents/{id}/sessions` 已接线（真 channel_sessions 查询）
  - #3 桌面同源：channel 会话出现在 `/api/conversations` 与 `/messages`（新测试）
  - #10 渠道回投：`delivery={mode:channel,channel:fake,target}` 的 automation 结果经真 `channel_manager.send` 落 FakeAdapter；owner 模式不落（新测试）
  - #11 群 handoff：3 真 persistent agent、@mention handoff 插队、timeline 次序、bob 零发言、成员 group session 归属（新测试，活体 app）
  - #12 设备离线：离线窗口内本地 automation 照常执行 + presence 恢复（组合测试，自设备语义=场景 8 的 DBOS 恢复，见映射 §2.5 选项 1）
  - #16 learned skill 进 run：proposal→approve→run.start→fake LLM 请求含技能正文（新测试）
- REQUIRES_USER_DAILY_SMOKE（不阻塞交付）：真实渠道凭据收发、Windows 真桌面注入、本地 GPU 真跑 llama-server、安装器 smoke。

## 7. 遗留与已知权衡

1. **群聊流式**：群 turn 经 orchestrator 汇总文本回 report/timeline，不做逐成员 WS 流式（W8 范围=一次入站→编排→timeline；产品化流式留待后续波）。
2. **engine 文本失败应答**：模型供应商彻底失败时 hermes 以"暂时不可用…/retry"文本结束 turn（run 记 completed 携错误文本，渠道收到该原文，单条不刷屏）；是否升格为 run.failed 分类是产品决策，未在本波改（P11 场景测试按实际契约断言 `HTTP 500` 可见）。
3. **hub.py**：opt-in 后台面仍持旧 scheduler/telegram 直路（lease 协调），随旧路径退役一并清理（审计记 cosmetic）。
4. **群消息不落渠道→群路由**：渠道入站→群路由未接（`run.start{group_id}` 的 ws/REST 面已通），属于下一波产品化项。
5. dev 环境注意：pytest basetemp 现必须用仓库外目录或非忽略路径（`.tmp/` 已进 .gitignore，否则 workspace_search 的 git-listed 捷径会改变行为；相关测试已改 tempfile 免疫）。

## 8. 退出条件核对

- [x] 16 场景 fake E2E 全部有确定性测试证据（§6）
- [x] full pytest 一次 + 前端四件套（§5）
- [x] `docs/plan/CORE-PARITY.md` 已加 §11.6
- [x] `docs/plan/ROADMAP-TO-PRODUCT.md` 已加交付记录
- [x] `tasks/CURRENT.md` → AWAITING_REVIEW
- [x] Atlas main push；fork `atlas` 无新 patch（tail-sync 已在 W6 推送，== origin/atlas）
- [x] 未启动 X6 / full T1 / R1

**结论**：任务书完成判据成立——Atlas 已具备常驻个人 Agent 形态：persistent agent 长期身份与群协作、七渠道网关接活、无变化不烧模型的 heartbeat、DBOS 可靠定时/条件任务、自有设备注册与接管、托管本地模型（激活闸门）、技能持续学习闭环；全部以 fake 确定性测试背书，真实凭据/真桌面/GPU 项明确标 REQUIRES_USER_DAILY_SMOKE。
