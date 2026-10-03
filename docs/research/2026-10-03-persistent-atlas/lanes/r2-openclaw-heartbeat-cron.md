# R2 研究报告：OpenClaw Heartbeat 与 Cron（Automations）状态机

> 来源冻结：OpenClaw `main` @ `3e5560873a4`（`D:\Atlas-persistent-sources\openclaw`，只读）。
> Atlas 基线：`a034bff`。本文所有路径相对 OpenClaw 仓库根，除非标注 `D:\Atlas\...`。

---

## 0. 最重要的结论：Heartbeat 是 cron 的特例

OpenClaw 里 **不存在独立的 heartbeat 定时器**。heartbeat 的节拍（cadence）由 Automations（cron）调度器持有：

- `docs/gateway/heartbeat.md` 开头即声明 "**Heartbeat is an automation**"。
- Gateway 为每个启用 heartbeat 的 agent 维护**一条 system-owned cron job**（`openclaw cron list --all` 里可见 `Heartbeat (agent-id)`）。
- `src/cron/heartbeat-monitor.ts` 的 `resolveHeartbeatMonitorPlan()` 把 `agents.*.heartbeat` 配置**声明式收敛**为 cron monitor 行：
  - `declarationKey = "heartbeat:<agentId>"`（`HEARTBEAT_DECLARATION_PREFIX`，见 `src/cron/system-owned-declaration.ts`）
  - `schedule: { kind: "every", everyMs: intervalMs, anchorMs: resolveHeartbeatPhaseMs(...) }`
  - `payload: { kind: "heartbeat" }`（gateway-converged，客户端 create/patch API 明确拒绝此 kind，见 `src/cron/types.ts` 的 `isSystemOwnedCronPayloadKind` 与 `src/cron/service/ops-mutations.ts:100`）
  - `sessionTarget: "main"`、`wakeMode: "next-heartbeat"`、`enabled: 配置节拍存在`
- `anchorMs` 不是创建时间，而是**确定性相位锚**：`resolveHeartbeatPhaseMs()`（`src/infra/heartbeat-schedule.ts`）= `sha256(schedulerSeed:agentId) % intervalMs`，seed 默认是设备 identity（deviceId）。作用：重启后同一 agent 的 tick 相位不变，且多 agent 天然错峰。
- cron 命中 heartbeat payload 时（`src/cron/service/timer-execution.ts:157`），**不走 cron 自己的执行器**，而是调用 `state.deps.requestHeartbeatAndWait(heartbeatWake)`（即 session-event-wake 唤醒总线），把 heartbeat runner 当作执行传输层。注释原文："Monitors and migrated tasks share the wake bus, keeping coalescing, quiet hours, cooldown, flood, and busy guards in the heartbeat runner."
- `heartbeat.every: "0m"` 只禁用周期节拍（monitor job 保留但 disabled）；事件驱动 wake（exec 完成、手动）仍然可用。`cron.enabled=false` 时周期 heartbeat 完全不跑（没有 fallback timer）。

此外还有第二类 system-owned job：**heartbeat task**（旧 `HEARTBEAT.md` 的 `tasks:` 迁移产物），`declarationKey = "heartbeat-task:<agentId>:<sha256-24>"`（`src/cron/heartbeat-task.ts` 的 `heartbeatTaskDeclarationKey()`），payload 仍是普通 `systemEvent`、`sessionTarget: "main"`；执行时被包成 `HeartbeatScheduledTask`（`jobId/name/prompt`）塞进同一次 heartbeat turn（`timer-execution.ts` 中 `intent: "task"` 分支）。

---

## 1. Heartbeat 完整状态机

### 1.1 归属（per-agent）

- `resolveHeartbeatAgentIds()`（`src/infra/heartbeat-config.ts`）：
  1. 若任何 `agents.entries.*` 有 `heartbeat` 块 → **只有这些 agent** 跑 heartbeat；
  2. 否则 `agents.defaults.heartbeat.agentId`；
  3. 否则若有 defaults 块 → 全部 agent；
  4. 否则 ambient 归属（`tryResolveAmbientHeartbeatAgentId`：defaults.systemAgent.agentId → 唯一 agent）。多 agent roster 无主 → heartbeat 停用并告警（`isHeartbeatOwnerUnresolved`）。
- **runner 状态是 per-agent 的**：`startHeartbeatRunner()`（`src/infra/heartbeat-runner-scheduler.ts`）维护 `Map<agentId, HeartbeatAgentState>`，字段：`intervalMs`、`cooldownUntilMs`、`lastRunStartedAtMs`、`recentRunStarts[]`（洪水检测环形缓冲）、`floodLoggedSinceLastRun`。广播 wake 用 `Promise.all` 并行驱动各 agent，互不阻塞（"Sibling agents do not pause each other"）。
- `updateConfig(cfg)` 热加载：重建 per-agent 状态但**保留在跑实例的记账**（`createAgentState` 复用旧对象）。

### 1.2 节拍 / 活跃时段 / 冷却 / 洪水

| 约束 | 实现位置 | 语义 |
|---|---|---|
| interval | cron monitor `schedule.everyMs`（配置 `heartbeat.every`，默认 30m；Anthropic OAuth 时 1h） | 持久化在 cron store，重启不丢 |
| active hours（= quiet hours 反向） | `src/infra/heartbeat-active-hours.ts` `isWithinActiveHours()`；`{start:"HH:MM", end:"HH:MM"|"24:00", timezone}`；start==end 视为零宽窗口（永远跳过）；时区 `user`(agents.defaults.userTimezone→host)/`local`/IANA，解析失败**宽容放行** | 窗口外 skip，reason=`quiet-hours`；但 `wakeSource==="cron"` 或 targeted-unscheduled wake **不受** active hours 限制（heartbeat-task job 自带 active-hours 语义是靠 doctor 迁移时写进 job 的 cadence） |
| cooldown（min-spacing） | `src/infra/heartbeat-cooldown.ts` `shouldDeferWake()`：`DEFAULT_MIN_WAKE_SPACING_MS = 30_000`，`lastRunStartedAtMs + 30s` 内的其他 wake defer，reason=`min-spacing`，带 `retryAtMs` | **持久化 monitor tick 旁路**（`authoritativeScheduledTick=true` 时 `nextDueMs=now` 直接视为 due）；手动 intent 完全豁免 |
| flood guard | 同文件：60s 窗口内第 5 次 run 启动 → defer，reason=`flood`，`retryAtMs=窗口内最早 ts+60s+1`；`recordRunStart()` 维护 `threshold+1` 长度环形缓冲 | system wake-now 也受控，只有 `intent==="manual"` 豁免 |
| not-due | `intent==="scheduled"` 且 `now < nextDueMs` → defer reason=`not-due` | 事件 wake 在 agent 尚无 `lastRunStartedAtMs` 时可先于首个 tick 响应 |

### 1.3 busy guards（执行前闸门，`resolveHeartbeatWakeStage`，`src/infra/heartbeat-runner-execution.ts`）

按序检查，全部产生 `status:"skipped"` 并带 reason：

1. heartbeat 总开关 / 该 agent 未启用 / 无 interval → `disabled`；
2. active hours → `quiet-hours`；
3. **preflight**（`resolveHeartbeatPreflight`，`src/infra/heartbeat-runner-prompt.ts`）：读 monitor scratch、peek 系统 event 队列、分类 wake 来源。终态跳过（空 scratch / exec 事件已被消费）先于 busy 闸门求值（`shouldPreflightWakeBeforeBusy`）：
   - scratch 存在但**有效为空**（`isHeartbeatContentEffectivelyEmpty()`：只有空行/注释/标题/围栏/空 checklist stub）→ skip `empty-heartbeat-file`，**不烧模型**（cheap-diff 手段之一）；
   - exec-event wake 但队列里已无 exec 完成事件（被 `process poll` 消费掉）→ skip `no-pending-event`；
4. **main queue 忙**（CommandLane.Main 深度 > 0）→ `requests-in-flight`（session-scoped exec completion 豁免此条）；
5. **cron lane 忙**：活跃 cron job（排除"正在等 heartbeat 结算的自己"）或 CronNested/HookDispatch lane 非空 → `cron-in-progress`；
6. **同 agent 任一 session 有活跃 reply/embedded run** → `requests-in-flight`（`immediate`/`manual` intent 豁免这条宽检）；
7. 目标 session 的 restart-recovery / pendingFinalDelivery（30s 窗口，heartbeat-ack 文本豁免）→ `requests-in-flight`；
8. 精确目标 session 忙（replyRunRegistry / embedded run / session lane 深度 > 0）→ `requests-in-flight`。

**skip 的两种后续**（`session-event-wake.ts`）：
- `RETRY_REASONS = {active-run, requests-in-flight, cron-in-progress, preempted, channel-not-ready}` → wake 层**保留**这次 wake 并重试（1s 重试节奏），这类 skip **不消耗 cooldown**（`runOneAgent` 里 retryable 分支不调 `recordRunBookkeeping`）。
- **事件自由的纯 monitor poll**（无 queued events、无 scheduled tasks、未开始准备）被 busy 拦下时 `deferSessionEventWakePoll()` → 记为 skipped，**等下一个持久化 cadence tick**，不在 busy 工作后面挂着重试。

### 1.4 事件驱动 wake 的类别

`HeartbeatWakeIntent = "scheduled" | "task" | "event" | "immediate" | "manual"`；
`HeartbeatWakeSource = interval | manual | exec-event | notifications-event | cron | hook | background-task | background-task-blocked | acp-spawn | session-state | cli-watchdog | restart-sentinel | retry | other`（`src/infra/heartbeat-wake-contracts.ts`）。

三大类：
1. **schedule**：cron monitor tick（`source:"interval", intent:"scheduled", reason:"interval", scheduledEveryMs`）；heartbeat-task job（`intent:"task"`, `tasks:[{jobId,name,prompt}]`）。
2. **process completion**：后台 exec 完成（`exec-event`/`background-task`/`background-task-blocked`）入系统 event 队列并请求 wake；turn 内部提示词用 `[OpenClaw exec completion]`。
3. **手动 / 其他**：`openclaw system event --mode now`（`wakeNow()`，`src/cron/service/ops-run.ts:442`；mode `next-heartbeat` 则只入队等下个 tick）、hook、ACP spawn、session-state 变化、**restart-sentinel**（Gateway 重启后恢复被打断的 turn）。

**wake 总线**（`src/infra/session-event-wake.ts`）是所有类别的汇聚点：
- per-target（`agentId::sessionKey`）WakeGroup，三个槽 `SLOTS=["task","scheduled","event"]`；
- 合并窗口 `COALESCE_MS=250ms`，`merge()` 保留高优先级 intent、合并 tasks（按 jobId 去重）、`notBefore` 取 max（bypass 当 manual/immediate）；
- 优先级：manual/immediate=3 > task/event=2 > scheduled/interval=1 > retry=0；
- 并发上限 `MAX_ACTIVE_TARGETS=4`；retry 间隔 1s，idle 60s；
- abort signal 一代一换（generation），runner 停止后迟到的 loader 不得再派发。

### 1.5 restart 后如何继续

- **cadence 本身持久化**在 cron store（SQLite），重启后 cron scheduler 恢复 `nextRunAtMs`。overdue 的 heartbeat/agentTurn/main-session-systemEvent(wakeMode=now) job **不立即回放**，而是进 startup catch-up 的 deferred 队列（延迟 `DEFAULT_STARTUP_DEFERRED_MISSED_AGENT_JOB_DELAY_MS = 2min`，见 §3.5）。
- **restart-sentinel**：重启时被打断的 turn 会话里写入 continuation 事件，重启后第一次 heartbeat wake（`source:"restart-sentinel"`）把它作为"session-owned event"直接回答回**原 session**（不投递到 heartbeat target），且此类 continuation 用普通 agent timeout（48h 默认），不受 heartbeat cadence/timeout 压缩（`heartbeat-runner-run.ts` 的 `hasTaskContinuation` 分支）。
- 执行中的 heartbeat 与 gateway 生命周期绑定（`opts.abortSignal`）；wake 保留机制保证已 admit 的工作在 runner 重建后仍被重试。

### 1.6 heartbeat session 隔离

`resolveHeartbeatSessionSelection()`（`src/infra/heartbeat-runner-session.ts`）：

- `sessionTarget`（配置 `heartbeat.session`）：
  - `"main"`/缺省 → agent 主 session `agent:<id>:main`（`session.scope="global"` 时 `global`）；
  - 显式 session key（canonicalize 后必须属于本 agent 且**不能是 subagent session**——forced/subagent key 一律回落 main 并 suppressOriginatingContext）；
- `isolatedSession: true` → 每次 heartbeat 用**隔离 session**：key = `<baseKey>:heartbeat`（重复后缀 `:heartbeat` 会被折叠；entry 上存 `heartbeatIsolatedBaseSessionKey` 指回 base）。每次 run `forceNew` 建 fresh session id（复用 cron `sessionTarget:"isolated"` 的 `resolveCronSession`），旧隔离 session 归档（`archiveRemovedTranscript`）；~100K token 的历史变 ~2-5K。**投递路由仍按 base conversation**（channel/account/topic 跟随所选会话）。
- heartbeat-only 回复**不续命 session**：idle 过期看 `lastInteractionAt`（真实用户消息），heartbeat 只还原 `updatedAt`（`restoreHeartbeatUpdatedAt`，取 max，防止心跳把会话顶成"最新"）。

### 1.7 delivery target 语义

`heartbeat.target`（`docs/gateway/heartbeat.md` ParamField；解析在 `src/infra/outbound/targets.ts` `resolveHeartbeatDeliveryTargetWithSessionRoute`）：

- `owner`（默认）：`commands.ownerAllowFrom` 第一个具体条目 → channel `allowFrom`；**永不解析到群**；解析不出 → skip `reason=no-route`（模型都不跑）。首个成功投递会附一段"如何关掉"的说明。
- `last`：跟随最近一次外部会话（可含群/频道）；无外部路由也 skip。
- `<channelId>`（telegram/discord/...）+ `to`（收件人，支持 `<chatId>:topic:<threadId>`）+ `accountId`（多账号）。
- `none`：只跑内部状态、绝不外发（显式选择时视为 resolver 的 verdict，`target-none`）。
- `directPolicy: "allow"|"block"`：block 时 DM 直投被抑制（`dm-blocked`）但仍跑 turn。
- **session-owned completion 覆盖**：一次 wake 的事件**全部**是 exec 完成/restart 续跑、且落在内部会话（Control UI/WebChat/operator session）时，回复**写回该 session transcript**（`delivery={channel:"none", reason:"session-owned-completion"}`），不走 target；session 写失败则事件留队，**不**回落到频道。混合批次仍用 target。
- visibility：`channels.*.heartbeatVisibility {showOk, showAlerts, useIndicator}`（per-account > per-channel > defaults）。**三者全 false → 整个 run 在进模型前 skip（`alerts-disabled`），零模型消耗**。
- channel readiness 拦截投递 → 记录 non-delivery，1 分钟宽限后重跑 heartbeat（不占 cadence 槽）；一旦进入 durable 投递队列，传输重试归队列管。

### 1.8 "no-change → no notification" 机制与 cheap-diff

四层，从便宜到贵：

1. **结构化工具输出**（首选）：`heartbeat_respond` 工具（`src/agents/tools/heartbeat-response-tool.ts`）。one-shot（每 turn 一次，重复调用报错）。参数 schema：
   - `outcome`: `no_change | progress | done | blocked | needs_attention`（`src/auto-reply/heartbeat-tool-response.ts`）
   - `notify: boolean`（false=不外发）
   - `summary: string`（必填）
   - `notificationText?`, `reason?`, `priority?: low|normal|high`, `nextCheck?`（建议的下检间隔，写入 agent-run-registry 供 pacing 用）
   - `scratch?`：整替 monitor scratch（CAS 由 runner 在 turn 后落库，工具输出只报 `scratchPending:true`）
   - 启用条件 `shouldUseHeartbeatResponseToolPrompt`；prompt 自动追加 `HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS`。**结构化响应优先于文本 fallback**。
2. **文本约定**（legacy）：prompt 末尾约定 "If nothing needs attention, reply NO_REPLY"（`SILENT_REPLY_TOKEN`，`src/auto-reply/tokens.ts`）或 `HEARTBEAT_OK`（`HEARTBEAT_TOKEN`）。`stripHeartbeatToken()`（`src/auto-reply/heartbeat.ts`）在回复**开头或结尾**剥离 token；剩余内容 ≤300 字符（`DEFAULT_HEARTBEAT_ACK_MAX_CHARS`，固定预算）→ 整条丢弃（shouldSkip）；token 出现在**中间**不特殊处理。`isHeartbeatAcknowledgementText()` 同时识别 NO_REPLY 变体。
3. **模型前置短路**：`empty-heartbeat-file`（空 scratch）、`alerts-disabled`（三个 visibility 全关）、`no-route`（无路由的 ambient poll）都在**调用模型之前** skip。
4. **outcome 记忆而非重放**：`heartbeat-outcome-store.ts`（agent 级 SQLite）把"最后一次有意义的 outcome"（progress/done/blocked/needs_attention，summary≤4000 字符、tasks≤32 个）按 sessionKey 存一条，注入下一 turn 作有界上下文；`no_change` 与已确认的可见通知**不**存。这是"最新 outcome"，不是告警历史。

**dedupe**（对用户可见面）：Control UI/WebChat 隐藏 heartbeat prompt 与 OK-only ack（`src/gateway/server-chat-heartbeat.ts` `shouldHideHeartbeatChatOutput`/`normalizeHeartbeatChatFinalText`）；transcript marker 区分 `[OpenClaw heartbeat poll]` / `[OpenClaw exec completion]` / `[OpenClaw cron wake]`（`INTERNAL_WAKE_TRANSCRIPT_PROMPTS`）。背靠背 silent-ack 对（HEARTBEAT_OK + NO_REPLY 式）保持隐藏。

### 1.9 heartbeat turn 状态机伪代码

```
tick(cron monitor due) 或 wake(source, intent):
  runner.shouldDeferWake?            # not-due / min-spacing(30s) / flood(5/60s)
    defer → wake 层 retain + retryAtMs（monitor tick 不 defer）
  resolveHeartbeatWakeStage:
    enabled? activeHours? preflight(空scratch? exec事件还在?):
      终态 skip（不重试）
    main/cron/同agent/目标session 忙?:
      retryable skip（retain 重试）或事件自由 poll → 等下个 tick
  prepareHeartbeatRunStage:
    解析 delivery target；session-owned completion → 写回原 session
    isolatedSession → 建 fresh :heartbeat session
    拼 prompt（base prompt + exec/cron 事件专属 prompt + scratch 附注 + 任务清单）
  dispatchInboundMessage（isHeartbeat=true, InternalTurnSource=heartbeat|exec|cron）:
    模型 turn（timeout = heartbeat.timeoutSeconds ?? agents.defaults.timeoutSeconds
              ?? min(every, 600s)；task 续跑用普通 48h timeout）
    heartbeat_respond(outcome, notify, summary, scratch?)
      或 文本（NO_REPLY/HEARTBEAT_OK/告警文本）
  settle:
    notify=false / no_change / OK-only → 静默（visibility 决定是否发 OK ack）
    notify=true + notificationText → 投递 target；投递被拦 → 记录 + 1min 后重跑
    status: ran | skipped(reason, retryAtMs?) | failed(reason)
  recordRunBookkeeping: lastRunStartedAtMs=now; cooldownUntilMs=now+interval;
                        recentRunStarts.push(now)
  cron 侧: run history 记 ok/error/skipped（skipped 带 heartbeat skip reason）
```

---

## 2. Cron（Automations）store 与状态机

### 2.1 job 数据结构（`src/cron/types.ts` + `packages/gateway-protocol/src/schema/cron.ts`）

`CronJobSchema` 顶层字段：
`id`, `declarationKey?`（声明式幂等键，1-200 字符）, `displayName?`, `owner? {agentId, sessionKey, accountId}`, `scheduledToolPolicy?`（trusted | account{ownerSessionKey, ownerAccountId}）, `agentId?`, `sessionKey?`, `name`, `description?`, `enabled: bool`, `deleteAfterRun?`, `createdAtMs`, `updatedAtMs`, `configRevision?`（定义指纹，update 可带 `expectedConfigRevision` 乐观锁）, `schedule`, `pacing? {min?, max?}`（动态节拍界）, `trigger? {script, once?}`, `sessionTarget`, `wakeMode`, `payload`, `delivery?`, `failureAlert?`, `state`, 以及投影出来的 `nextRunAtMs/lastRunAtMs/lastRunStatus/lastRunError/lastDelivered/lastDeliveryStatus/lastDeliveryError/deliverySuppressionReason/lastFailureNotification*`。

**schedule**（5 种）：
- `{kind:"at", at: ISO串}` — one-shot；`computeOneShotNextRunAtMs()`：ok 后不再调度（除非 at 被改到未来）；失败/未知保留 due 以便重试/检查。
- `{kind:"every", everyMs, anchorMs?}` — interval；锚定相位；`lastRunAtMs+everyMs > now` 时优先从 lastRun 顺推。
- `{kind:"cron", expr, tz?, staggerMs?}` — croner 表达式 + IANA 时区 + per-job 确定性 jitter（`sha256(jobId)%staggerMs`，`resolveStableCronOffsetMs`）。
- `{kind:"on-exit", command, cwd?}` — 事件驱动：Gateway ProcessSupervisor 监视的进程退出时触发一次（无 nextRunAtMs）。
- `{kind:"stream", command: argv, cwd?, mode:"line"|"match", match?, batchMs?(50-5000), maxBatchBytes?(1024-65536)}` — 长驻流源，行/正则触发，静默窗合批。

**payload**（4+1 种）：`systemEvent{text, toolsAllow?}`、`agentTurn{message, model?, fallbacks?, toolsAllow?, thinking?, timeoutSeconds?, lightContext?, allowUnsafeExternalContent?}`、`command{argv, timeoutSeconds}`（仅 management 面）、`script{script(≤64K), timeoutSeconds, toolBudget?}`、`heartbeat{}`（gateway 专属）。`toolsAllowIsDefault` 标记自动盖章的默认白名单。

**delivery**（`CronDeliverySchema`）：`{mode:"none"|"announce"|"webhook", channel?("last"|具体), to?, threadId?, accountId?, bestEffort?, completionDestination?{mode:"webhook",to}, failureDestination?{channel?,to?,accountId?,mode?}}`。`bestEffort`：true 时成功执行+投递失败也允许 one-shot 完结删除。

**failureAlert**：`{after?(连续失败阈值，默认 2), channel?, to?, cooldownMs?(默认 3600000), includeSkipped?, mode, accountId?}` 或 `false`。

**sessionTarget**: `"main" | "isolated" | "current" | "session:<id>"`；**wakeMode**: `"now" | "next-heartbeat"`（main-session systemEvent 等下个 heartbeat 结算 vs 立即唤醒）。

### 2.2 可变运行状态 `CronJobState`（wire `CronJobStateSchema` + store 扩展）

wire 面：`nextRunAtMs`, `scheduleActivatedAtMs`（**fence**：schedule 编辑激活时刻，挡住"编辑发明出错过的 slot"）, `runningAtMs`, `lastRunAtMs`, `lastRunStatus`(ok|error|skipped；deprecated `lastStatus`), `lastError`, `lastDiagnostics{summary, entries[{ts,source,severity,message,toolName?,exitCode?,truncated?}]}`（source: cron-preflight|cron-setup|model-preflight|agent-run|tool|exec|delivery）, `lastDiagnosticSummary`, `lastErrorReason`(FailoverReason), `lastDurationMs`, `consecutiveErrors`, `scheduleErrorCount`, `autoDisabled{reason:"consecutive-failures"|"schedule-errors", atMs, consecutiveErrors}`, `consecutiveSkipped`, `lastDelivered`, `lastDeliveryStatus`, `lastDeliveryError`, `deliverySuppressionReason`, failure-notification 反馈（`lastFailureNotificationDelivered/Status/Error`, `lastFailureAlertAtMs`）, trigger 反馈（`lastTriggerEvalAtMs`, `triggerEvalCount`, `lastTriggerFireAtMs`, `triggerState`）, stream 反馈（`streamStatus` starting|running|restarting|stopped|disabled|error, `streamError`, `streamConsecutiveFailures`, `streamRestartExhausted`, `streamSourceIdentity`, `streamDroppedBatches/CoalescedBatches`, `streamLastStartedAtMs/LastExitAtMs`）。

store 内部扩展（`CronJobState`，`src/cron/types.ts:269`）：`startupCatchupAtMs`（startup catch-up 槽 fence）、`pacedNextRunAtMs`（paced 完成槽）、`forcePreservedNextRunAtMs`（manual run 保留的 one-shot 槽）、`queuedAtMs`（durable 预入场预约，重启未记录 run 即清除）、`runningReceiptId` + `runningScheduleChangeId`、`failureAlertIncident{signature?, scope:"run"|"trigger", repair?{atMs, alerted?}}`（一轮连败只修一次）、`lastFailureNotificationId`。

store-only 行扩展 `CronStoredJob`：`skillLibrarySelections`, `createdActor`, `toolsAllowProvenance`, `toolsAllowExecTarget(+Requirement)`, `runtimeAuthority`, `runtimeAuthorityRecoveryRequired`。

### 2.3 持久化格式与位置

- **共享 SQLite 状态库**（不再是 JSON 文件）：`src/cron/store.ts` 头注释 "backed entirely by shared SQLite state"。表：`cron_jobs`（列 `job_id, declaration_key, enabled, agent_id, payload_kind, job_json, state_json, runtime_updated_at_ms, schedule_identity, sort_order, updated_at` + grant 投影列，见 `src/cron/store/schema.ts`）、`cron_job_scratch`、`cron_run_*`（run history）。定义整体 JSON（`job_json`，含 `CronStoreFile{version:1, jobs[]}` 兼容形状）+ `state_json` 分列。
- 进程间一致性：monotonic store revision（`getCronJobsStoreRevision`，Map 上限 64）+ fingerprint 校验（`assertCronJobsStoreUnchanged` / `CronJobsStoreChangedError`）；SQLite worker 执行写事务（`save.worker.ts` / `runtime-mutation.worker.ts`），post-commit publication（`deferSqlitePostCommitPublication`）。
- 隔离租约心跳：`src/state/openclaw-state-lease-heartbeat.ts`（多进程共享 state DB 的租约续期/清理）。
- monitor scratch：`cron_job_scratch` 表，CAS（`expectedRevision` 单调），上限 256 KiB（`CronScratchSchema.content maxLength 262144`），不出现在 list/runs 输出。

### 2.4 触发循环（timer）

- `CronService`（`src/cron/service.ts`）— facade；调度细节在 `src/cron/service/`（约 60 个文件，locked(state) 串行化 mutation）。
- `armTimer()`（`timer-scheduler.ts`）：取 `summarizeCronJobSchedule().nextWakeAtMs`（只数 enabled + 有 canonical delivery + time-scheduled 的 job），timer delay 上限 `MAX_CRON_TIMER_DELAY_MS=60s`；无 due job 时 arm maintenance recheck（分钟级 watchdog，救回 schedule 计算失败的 job 直到 auto-disable）。两次 refire 最小间隔 `MIN_REFIRE_GAP_MS=2s`。
- 到点后 `collectRunnableJobs` → 容量闸（`DEFAULT_CRON_MAX_CONCURRENT_RUNS`，`src/config/cron-limits.ts`）→ `executeQueuedCronRun`。错过 timer tick 时 coalesce：cron 用**存好的 deadline + run receipts** 重查（"scheduler coalesces missed timer ticks"，不逐 slot 回放）。
- 错误退避：`DEFAULT_ERROR_BACKOFF_SCHEDULE_MS = [30s, 60s, 5m, 15m, 60m]`（`errorBackoffMs(consecutiveErrors)`）；瞬时错误默认重试 3 次（`DEFAULT_MAX_TRANSIENT_RETRIES`）。连续 **10 次执行失败** → auto-disable（`MAX_CONSECUTIVE_RUN_FAILURES=10`，`auto-disable.ts`；system-owned monitor **豁免** auto-disable，保持可见重试）；schedule 计算错误连续 **3 次**（`MAX_SCHEDULE_ERRORS=3`）→ auto-disable reason=`schedule-errors`。auto-disable 写 `state.autoDisabled` + 给 owner 发通知（"Fix the underlying cause, then run automations enable"）。
- trigger script：recurring payload 执行前 headless 评估 `{fire: bool, message?, state?}`（`CronTriggerEvaluationResult`），不 fire 记 `ok/triggerEval`；`once:true` 评估一次。
- pacing：`next_check` 工具提案（`recordCronNextCheckProposal`）→ `CronNextCheckProposal{delayMs}` → `pacedNextRunAtMs`，受 `pacing.min/max` 约束（`src/cron/pacing.ts`）。

### 2.5 missed-run policy 与 startup recovery

`runMissedJobs()`（`src/cron/service/timer-catchup.ts`）：
- 常量（`timer-execution-timeout.ts`）：`DEFAULT_MAX_MISSED_JOBS_PER_RESTART = 5`（立即跑的上限）、`DEFAULT_MISSED_JOB_STAGGER_MS = 5_000`（错峰）、`DEFAULT_STARTUP_DEFERRED_MISSED_AGENT_JOB_DELAY_MS = 2min`。
- 流程：`planCronStartup` 找出 overdue 候选 → `skipCronJobsWithoutOwners` → 按 nextRunAtMs 排序 → **agent 类工作（agentTurn / heartbeat / heartbeat-task / wakeMode=now 的 main systemEvent）全部 defer 到 startup 之后（2min 延迟）**，模型/工具执行不占 scheduler 启动 → 非代理类取前 5 个立即跑，其余 defer（5s 错峰）→ `persistQueuedCronRunReservations` 持久化预约后顺序执行。
- deferred job 记录 `scheduleIdentity`（`tryCronScheduleIdentity`）：**deferral 归属于 schedule occurrence 本身**，label/payload 内容变化、声明式收敛、再次重启都不会丢（"Startup catch-up delays survive label or payload-content reconciliation and another restart; changing the schedule starts a new scheduling decision."）。
- 状态 fence：`state.startupCatchupAtMs` 精确保护这个槽不被 future-slot repair 吞掉；`recomputeSingleJobForMaintenance` 只在 `startupCatchupAtMs === nextRunAtMs` 时保留它。
- **错过很多次的 recurring 只补一次**：执行按 job 而不是按 slot，`nextRunAtMs` 从 now 重算（"An occurrence outside active hours is skipped and tried again at its next scheduled occurrence"，heartbeat task）。

**run reconciliation**（`docs/automation/cron-jobs/how-it-works.md` + `run-recovery.ts` / `startup-run-repair.ts`）：
- 每个运行持 **run receipt**（`src/cron/store/run-receipt.types.ts`）：`{receiptId, storeKey, jobId, configRevision, agentId, requestRunId?, status: running|ok|error|skipped|interrupted|superseded, ownerPid, ownerStartTime, startedAtMs, finishedAtMs?, error?}`。
- 重启恢复按 **run identity** 匹配（receipt 的 ownerPid+ownerStartTime 验证进程身份），不是"同刻启动"巧合：活进程保 receipt；验证不了的外来进程 receipt 在 >2h（`CRON_STUCK_RUN_MS = 2h`）后变 recoverable；恢复先**撤销 receipt** 再允许新 run。
- **delivery fence**：one-shot 在交付/写消息前记录 durable delivery attempt；带此记录而被打断的 one-shot → 保持 disabled、delivery=**Unknown**，绝不重放 payload（可能已发出消息）。无证据的 legacy 中断 one-shot 同样 disabled+Unknown。
- 被打断的 run 在历史里记为 failure（`interrupted`），重复恢复不重复记历史。
- 已完成但 job 更新失败的 run：后续任何 acknowledged 的 schedule/pacing edit 触发 recovery——保留历史、settle 旧 run、**不再执行 payload**。

### 2.6 no duplicate fire

三层：
1. **queued/running markers**：`state.queuedAtMs` / `state.runningAtMs`（durable，store 行内）+ 进程内 reservation（`queuedRunReservationsByJobId`，`markerAtMs` 必须精确匹配才算 owner，`ownsCronRunMarker`）。同 job 已 queued/running 时 `hasActiveCronRun()` 为 true，admission 拒绝二次入队。
2. **run receipts**（§2.5）：跨进程的"这个 job 正在跑/已跑"事实，恢复必须先 revoke。
3. **stuck 清理**：marker 存在但 >2h 且无 matching owner → 清 marker（warn log）；清 running marker 时若 `lastRunAtMs >= nextRunAtMs`（slot 已执行过）则本 tick skip，否则允许重试。
4. 手动 `run --run-id` 复用仍活跃的 run → 报 in-flight 而非再跑。

### 2.7 cancel active run

`remove` 时如果 job 有活跃 run → 请求取消并在结果里报 `activeRunCancellationRequested:true`（cron-tool 管理面描述）。实现：`src/cron/service/active-run-cancellation.ts`（`registerActiveCronTaskRun` / `abortActiveCronTaskRuns("Gateway restarting.")` / `waitForActiveCronRuns(timeoutMs)`）+ gateway 关停路径 `cron.stopAndDrain()`（join 停止的 timer generation，见 `service.ts`）。超时打断：`timeoutSeconds` 到点 abort run 并给短 cleanup 窗；不 drain 则 force-clear 该 run 的 session ownership 再记 timeout（防止聊天队列被僵尸 session 卡住）。

### 2.8 delivery outcome 枚举与 run history

- `CronRunStatus`（执行）：`ok | error | skipped`。
- `CronDeliveryStatus`（投递）：`delivered | not-delivered | unknown | not-requested`。
- `CronCompletionStatus`（one-shot 完结判定）：`succeeded | failed | unknown`（`deleteAfterRun` 只在 `succeeded` 时删）。
- 附加：`deliverySuppressionReason`（有意静默）、`CronDeliveryTrace{intended?, resolved{...,ok,error?}, messageToolSentTo[], fallbackUsed?, delivered?}`（审计"想发到哪/实际发到哪/消息工具已自发到哪"）、`failureNotificationDelivery{delivered?, status, error?}`。
- **run history 每条记录**（`CronRunLogEntrySchema`）：`ts, jobId, action:"finished", status?, completionStatus?, error?, errorReason?, summary?, diagnostics?, delivered?, deliveryStatus?, deliveryError?, deliverySuppressionReason?, failureNotificationDelivery?, delivery(trace)?, sessionId?, sessionKey?, runId?, runAtMs?, durationMs?, nextRunAtMs?, triggerFired?, model?, provider?, usage{input/output/total/cache_read/cache_write tokens}, jobName?`。
- 持久化：`src/cron/store/run-history.kernel.ts`，SQLite 表，**保留 7 天**（`RETENTION_MS = 7*24h`；`lost` 状态记录 24h），`cleanup_after` 列 + `pruneCronRunHistoryInDatabase` 定期清。transcript 复查走 `CronHistoryParams{id, runId?, runAtMs?, cursor?, limit?}`（绑定 run，不允许任选 session）。
- run-level agent 失败即使无 reply payload 也计为 job error（推进 consecutiveErrors → 失败通知/auto-disable）。

---

## 3. cron-tool（模型可见 API 面）

工具名：**`automations`**（`AUTOMATIONS_TOOL_NAME`，label "Automations"；旧名 cron），`src/agents/tools/cron-tool.ts`。扁平参数 schema（`cron-tool-schema.ts`，add/update 共用一个 job 对象，模型可把 job 字段摊平在顶层——`recoverCronObjectFromFlatParams` 兜底恢复）。

**actions**：`status, list, get, add, update, remove, run, runs, next_check, wake`（+management-only 面 `list/get/update/run/remove`）。

- `list`：`includeDisabled?, limit(≤200), offset, query?, enabled?, scheduleKind?, lastRunStatus?, trigger?, sortBy(nextRunAtMs|updatedAtMs|name), sortDir, agentId?, compact?`（compact 返回定义-free 行 + timing），返回 `nextOffset` 翻页。
- `add`：job 全量（schedule/pacing/trigger/sessionTarget/wakeMode/payload/delivery/failureAlert/deleteAfterRun/declarationKey...）；创建默认 **enabled**（刻意的安全选择）；`declarationKey` 幂等收敛（已存在同键 → update）。creator authority：带工具白名单 capture（`toolsAllow` 上限 cap）、`cronCreateRequiresCreatorAuthority`。
- `update jobId job`：partial patch，**null 清字段**；`expectedConfigRevision` 乐观锁。
- `run jobId`：`runMode: "due"(默认)|"force"`；`waitTimeoutMs`（≤60s）内**同步等结果**——模型当次调用就拿到 finished run 或 runId，无需自建验证 job；若该 job 在本 session 跑则提示"本轮结束后才开始"。
- `runs jobId runId?`：查 run 历史（`statuses/deliveryStatuses` 过滤）。
- `next_check in:"15m"`：**仅当前正在运行的 job** 可用——自我 pace 本次运行的下一次检查（pacing 提案，受 job.pacing.min/max 钳制）。
- `wake text mode(now|next-heartbeat) [sessionKey] [agentId]`：投递 system event 到会话事件队列；`now` 立即唤醒 heartbeat。
- `remove jobId`：管理面才可；活跃 run 先请求取消。
- `get jobId`：完整 schedule/payload/delivery + deliveryPreview。

**权限分级**（`cron-tool.types.ts` / `cron-creator-authority-*`）：
- 普通会话 agent：可 list/get/status + **创建/更新带 requester authority grant**（创建时固定 owner=sessionKey、scheduledToolPolicy=account 模式、toolsAllow 被白名单 cap）。
- `management` authority（channel owner / Control UI admin turn）：可 update/remove/run 任意 job。
- **isolated run 自清理授权**（selfRemoveOnly）：只能 `status/list/get/runs/next_check/remove` **自己的 job**（schema 层直接裁掉其他 action 与字段）。
- 输出契约：`CronToolOutputSchema`（`cron-tool-output-schema.ts`），terminal 展示 `formatCronTerminalPresentation`。

---

## 4. gateway-protocol schema 形状

`packages/gateway-protocol/src/schema/`（TypeBox）：
- `cron.ts` + `cron.types.ts` + `cron-shared.ts`（`CronDateTimestampMsSchema`, `cronAgentTurnPayloadSchema`, `cronCommandPayloadSchema`, `cronScriptPayloadSchema`）：§2.1 全部 schema；RPC 方法（gateway `server-methods/cron.ts`）：`cron.status/list/get/add/update/remove/run/runs/history/scratch.get/scratch.set` + `wake`。列表有 compact 行（`CronCompactJob`）。
- `computer.ts`：极小 —— `ComputerStatusParams{}`；`ComputerInvokeParams{command: "screen.snapshot"|"computer.act", params: Record<string,unknown>, generation: string, timeoutMs?, idempotencyKey: string}`（幂等键必填、generation 防跨代重放）。`worker-computer.ts` 为 worker 侧变体。

---

## 5. Atlas 落点建议

现状（`D:\Atlas`）：
- `core/atlas/scheduler/__init__.py`：`AtlasScheduler`（APScheduler 4.x `AsyncScheduler` + TOML store `schedules.toml` + 文件锁租约（hub 优先）+ watchdog 文件事件 trigger + `runs[-20:]` 内联历史）。字段：`id/name/description/trigger_type(cron|interval|date|event)/trigger_args/action("agent:<msg>"|"goal"|callback)/status(active|paused)/tags/created_at/updated_at/last_run_at/next_run_at/run_count/runs`。
- `core/atlas/server.py`：`scheduler` 全局实例；`_scheduled_goal → durable.run_agent_task`（DBOS durable workflow，at-least-once 恢复）→ `_run_scheduled_goal`（Hermes GoalManager 生命周期）；REST：list/add/run_now/delete/pause/resume。
- `core/atlas/capabilities/durable/dbos_backend.py`：DBOS SQLite 系统库，`@dbos.workflow() run_agent_task(payload)`。

### 5.1 Heartbeat service 建议文件

```
core/atlas/heartbeat/
  __init__.py          # HeartbeatService: start/stop/wake(agent_id, request)
  config.py            # per-agent 配置解析（对齐 heartbeat-config.ts：defaults+overrides、
                       #   resolve_interval_ms、resolve_timeout_seconds、resolve_enrolled_agent_ids）
  active_hours.py      # is_within_active_hours（时区宽容语义照抄）
  cooldown.py          # should_defer_wake（intent 5 值、30s min-spacing、5/60s flood、
                       #   record_run_start 环形缓冲）——纯函数，可直接移植
  wake_bus.py          # asyncio 版 session-event-wake：per-target 槽(task/scheduled/event)、
                       #   250ms 合并窗、优先级、retain/retry(1s)/idle(60s)、MAX_ACTIVE=4
  runner.py            # run_heartbeat_once：busy guards 链 → prompt 组装 → agent turn →
                       #   heartbeat_respond 结构化结算 → 投递/静默
  outcome_store.py     # 最新 outcome 落 DB（atlas sqlite），no_change 不存
  respond_tool.py      # heartbeat_respond 工具 schema（outcome/notify/summary/.../scratch）
  monitor.py           # 声明式投影：配置 → AtlasScheduler 里的 system-owned job
                       #  （id=f"__heartbeat__:{agent_id}"，phase anchor = sha256(seed:agent)%interval）
```

建议 heartbeat 的 tick 完全复用 AtlasScheduler（cron 特例模式），`HeartbeatService` 只做 guards/settlement，与 OpenClaw 的"cron 持节拍、runner 持守卫"分工一致。agent turn 执行挂到 `_scheduled_goal` 同款 durable 路径（DBOS）或轻量 asyncio task（monitor poll 可丢、事件 wake 不可丢——retain 语义在 wake_bus 层）。

### 5.2 Cron 状态 → Atlas Automation 字段对照表

| OpenClaw 字段 | Atlas 建议（AtlasScheduler.ScheduledTask 扩展） | 备注 |
|---|---|---|
| `id` | `id`（现有 slug） | 保留 |
| `name`/`displayName` | `name` / 新增 `display_name` | |
| `declarationKey` | 新增 `declaration_key` | 声明式幂等 upsert（heartbeat monitor/迁移任务用） |
| `enabled` + `state.autoDisabled` | `status: active|paused` + 新增 `auto_disabled: {reason, at, consecutive_errors}` | auto-disable 语义整体搬运（10 连败/3 次调度错） |
| `schedule.kind:"cron" {expr,tz,staggerMs}` | `trigger_type=cron`, `trigger_args={expr,tz,stagger_ms}`（现用 APScheduler 字段名；建议改为存原始 expr+tz 由 `_make_trigger` 解析，保留 stagger） | |
| `schedule.kind:"every" {everyMs,anchorMs}` | `trigger_type=interval`, `trigger_args={seconds, anchor_ms?}` | anchor 用确定性相位（sha256）而非创建时间 |
| `schedule.kind:"at" {at}` | `trigger_type=date`, `trigger_args={run_time}` + 新增 `delete_after_run` | one-shot 语义：ok 即删；delivery unknown → disabled 保留 |
| `schedule.kind:"on-exit"/"stream"` | 暂不映射（EVENT trigger 已覆盖部分文件事件语义） | 二期 |
| `payload.kind:"agentTurn" {message, model, timeoutSeconds, toolsAllow, lightContext}` | `action="agent:<message>"` + 新增 `payload: {model?, timeout_seconds?, tools_allow?, light_context?}` | |
| `payload.kind:"systemEvent" {text}` + `wakeMode` | 新增 `payload={kind:"system_event", text}`；`wake_mode: now→立即 heartbeat wake` / `next-heartbeat→入队等下个 tick` | |
| `sessionTarget: main|isolated|current|session:` | 新增 `session_target`（映射到 Hermes 会话选择；isolated = 一次性会话） | |
| `delivery {mode, channel, to, bestEffort, failureDestination}` | 新增 `delivery`（Atlas 至少 `none|notify`；`notifications.notify` 已存在，可作 announce 后端） | |
| `failureAlert {after, cooldownMs, ...}` | 新增 `failure_alert` | |
| `pacing {min,max}` + `next_check` | 新增 `pacing`；DBOS workflow 内工具可提案 delay | |
| `state.nextRunAtMs/lastRunAtMs/lastRunStatus/consecutiveErrors/lastError/lastDurationMs` | 大多已有（`next_run_at/last_run_at/run_count`）；补 `last_run_status/last_error/consecutive_errors/last_duration_ms` | TOML 列加 4 个键 |
| `state.queuedAtMs/runningAtMs/runningReceiptId` | **建议不放 TOML**——Atlas 有 DBOS：用 DBOS workflow id 作为 durable run receipt（`queued/running` 即存在 RUNNING workflow），重启恢复由 DBOS at-least-once 承担 | 关键差异：OpenClaw 自建 receipt，Atlas 应复用 DBOS |
| `runs history`（7 天 SQLite） | `runs[-20:]` 升级为 SQLite 表 `scheduler_runs(job_id, run_id, status, error, summary, started_at, duration_ms, delivery_status, usage_json)`，保留 7d | TOML 里的 runs 移出 |
| `monitor scratch` | 新增 `heartbeat_scratch`（DB 表，CAS revision，≤256KiB） | |
| `owner {agentId, sessionKey}` | 新增 `owner_session_id`（Hermes session） | |

### 5.3 需要从 OpenClaw 原样搬运的状态机清单（按优先级）

1. **`shouldDeferWake` + `recordRunStart`**（heartbeat-cooldown.ts，102 行纯函数）：5 种 intent × not-due/min-spacing/flood 判定 + retryAtMs。零依赖直接移植。
2. **`isWithinActiveHours`**（heartbeat-active-hours.ts）：零宽窗口、跨午夜窗口、时区宽容降级。
3. **wake 总线语义**（session-event-wake.ts 精简版）：三槽合并、优先级、retryable-reason 集合 `{requests-in-flight, cron-in-progress, active-run, preempted, channel-not-ready}` vs guard-reason 集合 `{not-due, min-spacing, flood}` 的 retain 规则、"事件自由 poll 不重试等下个 tick"。
4. **busy guard 顺序**（resolveHeartbeatWakeStage 的 1-8 步，减去 OpenClaw 专属 lane）：总开关 → active hours → preflight（空 scratch / 事件已消费）→ 主队列忙 → 自动化忙 → 同 agent 活跃 turn → 目标会话忙。
5. **no-change 合同**：prompt 约定 NO_REPLY + `heartbeat_respond(outcome/notify)` 结构化工具（one-shot）+ `is_effectively_empty(scratch)` 预检 + visibility 三开关全关→不进模型。
6. **cron job state 机**：`nextRunAtMs` 重算（含 error backoff floor）、`scheduleActivatedAtMs` fence、auto-disable（10/3 阈值）、`deleteAfterRun` 仅 succeeded。
7. **startup catch-up 策略**：立即跑上限 5、错峰 5s、agent 类工作延后 2min、deferral 绑定 schedule occurrence（restart 存活）。
8. **no-duplicate**：marker（queued/running）+ 2h stuck 清理 + "slot 已执行过则 skip"；Atlas 把 receipt 一层换成 DBOS workflow 状态。
9. **one-shot delivery fence**：执行→投递前记 attempt；interrupted + attempt 存在 → disabled + Unknown，不重放。
10. **phase anchor + stagger**：`sha256(seed:agent)%interval` 与 `sha256(jobId)%staggerMs`，保证重启相位稳定、批量 job 错峰。

不建议搬运：`on-exit`/`stream` schedule、toolsAllow provenance/authority envelope（Atlas 单租户单进程可大幅简化）、multi-account delivery 路由、Store revision/fingerprint 机制（TOML mtime + DBOS 已够）。
