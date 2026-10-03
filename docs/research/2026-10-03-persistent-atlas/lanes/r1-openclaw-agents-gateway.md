# R1 — OpenClaw Persistent Agents 与 Gateway 架构语义

- 来源冻结：`D:\Atlas-persistent-sources\openclaw`，HEAD `3e5560873a4`（只读，未 re-fetch）。
- 落点参照：`D:\Atlas`（Python FastAPI 后端 `core/atlas/server.py` + Electron 前端）。
- 本文回答 8 个必答问题：agent 数据模型 / gateway 进程模型 / inbound 路由全路径 / gateway-protocol schema / dedupe 与 restart recovery / owner-allowlist-mention gating / 可移植性与 sidecar 可行性 / Atlas 落点建议。

---

## 1. Persistent Agent 数据模型

### 1.1 声明与存储

- **声明位置**：单文件配置 `openclaw.json`（`src/config/paths.ts` 中 `CONFIG_FILENAME = "openclaw.json"`；legacy `clawdbot.json`），默认路径 `~/.openclaw/openclaw.json`（可用 `OPENCLAW_STATE_DIR` / `OPENCLAW_CONFIG_PATH` 覆盖）。
- **Agent roster**：`agents.entries` 是 `{ [agentId]: AgentEntryConfig }` 的 record，key 即稳定 agent id（正则 `^[a-z0-9_][a-z0-9_-]{0,63}$`，见 `src/config/zod-schema.agents.ts` 的 `AgentsSchema`）。
- **Roster 规则**（`AgentsSchema.superRefine`）：
  - `entries` 至少 1 条；
  - 两个 key 归一化后同 id → 报错；
  - 多 agent 时必须 `agents.ownership: "explicit"` 或恰好一个 `default: true`（legacy，已退役语义）；
  - 全新安装由 `applyImplicitAgentRosterDefaults`（`src/config/implicit-agent-roster.ts`）补 `entries: { main: {} }`。
- **Runtime 类型**（`src/config/types.agents.ts`）：`AgentsConfig { ownership?, defaults?, entries?, list? }`，`list` 是校验期物化的内部投影，不序列化。
- **运行期 CRUD**：gateway 方法 `agents.list / agents.create / agents.update / agents.delete / agents.files.*`（`src/gateway/methods/core-descriptors.ts:155-161`；实现 `src/gateway/server-methods/agents-config-mutations.ts` 的 `updateAgentConfigEntry` / `deleteAgentConfigEntry`）。

### 1.2 Agent Entry 字段清单

基础字段（`AgentEntryBaseSchema`，`src/config/zod-schema.agent-entry-base.ts:94`）：

| 字段 | 类型/语义 |
|---|---|
| `id` | agent id（record key 重复声明） |
| `name` / `description` | 展示名与描述 |
| `workspace` | 工作区目录（默认 `~/.openclaw/workspace-<id>`，见 `resolveAgentWorkspaceDir`，`src/agents/agent-scope-config.ts:462-485`） |
| `cwd` | 回复 run 的工作目录（可与 workspace 分离） |
| `agentDir` | agent 状态目录（默认 `~/.openclaw/agents/<id>/agent`，`resolveAgentDir` / `resolveDefaultAgentDir`） |
| `model` | `string`（严格主模型无 fallback）或 `{ primary, fallbacks[] }`（`AgentModelSchema`） |
| `utilityModel` | 辅助小模型（标题生成等短任务） |
| `decisionModel` | 决策模型 |
| `models` | `Record<provider/model, { alias?, params?, agentRuntime?, pickerRuntimes?, codeMode?, streaming? }>`（`AgentModelMapSchema`） |
| `modelPolicy` | `{ allow: string[] }` 限制会话可覆盖的模型 |
| `thinkingDefault` / `reasoningDefault` / `verboseDefault` / `toolProgressDetail` / `fastModeDefault` | 各默认开关 |
| `contextInjection` / `bootstrapMaxChars` / `bootstrapTotalMaxChars` | 上下文注入控制 |
| `skills` | 技能 allowlist（显式列表替换默认，`[]` = 无技能） |
| `subagents` | `{ delegationMode, allowAgents, model, thinking, requireAgentId }` |
| `embeddedAgent` | `{ executionContract: "default" \| "strict-agentic" }` |
| `params` | agent 级流参数（temperature 等） |
| `runtime` | `{ type: "embedded" }` 或 `{ type: "acp", acp: { agent, backend, mode: "persistent"\|"oneshot", cwd } }`（`AgentRuntimeSchema`） |

扩展字段（`AgentEntrySchema = AgentEntryBaseSchema.extend({...})`，`src/config/zod-schema.agent-runtime.ts:674`）：

| 字段 | 语义 |
|---|---|
| `identity` | `{ name, theme, emoji, avatar }`（`IdentitySchema`，`zod-schema.core.ts:419`）；派生默认：`ackReaction`←emoji、`mentionPatterns`←name/emoji |
| `groupChat` | `{ mentionPatterns?, historyLimit?, unmentionedInbound? }`（`GroupChatSchema`，`zod-schema.messages.ts:23`） |
| `heartbeat` | `{ every, activeHours{start,end,timezone}, model, session, target, directPolicy, to, accountId, prompt, timeoutSeconds, lightContext, isolatedSession }`（`HeartbeatSchema`） |
| `sandbox` / `tools` / `tts` / `memory.search` / `humanDelay` / `typingMode` / `skillsLimits` / `contextLimits` | 沙箱/工具策略/TTS/记忆检索/人性化延迟/打字模式等 |

默认值继承：`agents.defaults`（`AgentDefaultsSchema`），entry 深 merge 覆盖 defaults。

### 1.3 Channel Binding（多 agent 路由声明）

`bindings` 顶层数组（`BindingsSchema`，`src/config/zod-schema.agents.ts:152`）：

```jsonc
{ type?: "route",            // 缺省 = route
  agentId, comment?,
  match: { channel,            // 必填
           accountId?,         // 省略=默认账户；"*"=全部账户
           peer?: { kind: "direct"|"group"|"channel", id },
           guildId?, teamId?, roles? },
  session?: { dmScope: "main"|"per-peer"|"per-channel-peer"|"per-account-channel-peer",
              groupScope: "main"|"per-group" } }
// 以及 type:"acp" binding：要求 match.peer.id 指向具体会话，附 acp:{mode,label,cwd,backend}
```

匹配优先级（`resolveAgentRoute`，`src/routing/resolve-route.ts`；索引 `route-binding-index.ts`）：
`binding.peer` → `binding.peer.parent`（线程父 peer）→ `binding.peer.wildcard`（kind 级通配）→ `binding.guild+roles` → `binding.guild` → `binding.team` → `binding.account`（精确）→ `binding.channel`（`"*"` 账户）→ 唯一 agent 兜底；每层内取第一条命中。多 agent 且无命中 → fail closed（`AgentSelectionRequiredError`）。

### 1.4 会话持久化（"persistent" 的实体）

- **session store**：每 agent 一个 `~/.openclaw/agents/<agentId>/sessions/sessions.json`（`resolveSessionStorePathCore`，`src/config/sessions/paths.ts:351`；`{agentId}` 模板可自定义）。
- **SessionEntry**（`src/config/sessions/types.ts:232+`，`SessionEntryCore`）：`sessionId`、`updatedAt`、`lastRoute`（最近路由：channel/to/thread）、`lastHeartbeatText/SentAt`、`lifecycleRevision`（乐观并发）、`archivedAt/pinnedAt/snoozedUntil`、`spawnedBy/spawnedBySessionId/completionOwnerSessionKey`、`pluginExtensions`、`agentStatus`、`activitySummary`、restart recovery 状态等；transcript 存 SQLite（`session-accessor.sqlite-transcript-store.ts`）。
- **状态数据库**：`openclaw-state.db`（node:sqlite + Kysely），存 ingress queue、delivery queue、pairing store、restart sentinel 等。
- **会话键格式**（`src/routing/session-key.ts` `buildAgentPeerSessionKey:206`）：
  - DM：`dmScope=main` → `agent:<id>:<mainKey>`（默认 mainKey=`main`）；`per-peer` → `agent:<id>:direct:<peerId>`；`per-channel-peer` → `agent:<id>:<channel>:direct:<peerId>`；`per-account-channel-peer` → `agent:<id>:<channel>:<accountId>:direct:<peerId>`。
  - 群：`groupScope=main` → 主会话；否则 `agent:<id>:<channel>:<groupKind>:<peerId>`。
  - identityLinks 可把多渠道身份合并到同一 peer（`resolveLinkedDirectPeerId`）。

---

## 2. Gateway 进程模型

### 2.1 单进程、单端口

`docs/gateway/index.md`：**一个常驻进程**承担路由、控制面与全部渠道连接；单端口（默认 **18789**，`--port`→env→`gateway.port`）复用 WebSocket RPC、HTTP API（`/v1/models`、`/v1/chat/completions`、`/v1/responses` 等）、插件 HTTP、Control UI 与 hooks。

- 启动链：`startGatewayServer(port=18789, opts)`（`src/gateway/server.ts:23`）→ `acquireGatewayLock`（`src/infra/gateway-lock.ts`：锁文件 + pid 存活 + 进程启动时间/cmdline 指纹做 stale 检测；`GATEWAY_LIFECYCLE_LOCK_TIMEOUT_MS=5min`）→ `startGatewayServerCore`（`server-start.ts`）→ `server-startup-*.ts` 各阶段（bootstrap/plugins/sidecars/readiness…）→ `server-shutdown.ts` / `server-close.ts` 收尾。
- 配置热重载：`gateway.reload.mode="hybrid"`（可热应用则原子换内存快照，否则进程重启；`config-reload*.ts`）。

### 2.2 连接注册表

- `GatewayClientRegistry extends Set<GatewayWsClient>`（`src/gateway/server/client-registry.ts`）：按 `connId` 索引 + 插入序；`retainRequest(client)` 在客户端 socket 死亡后仍保留请求对象供权威 fanout（`authorityClients`）；`getByConnectionIds` 按插入序做定向广播。
- 每连接归属由 `GatewayConnectionOptions`（`src/gateway/server/connection.ts:42`）注入：`bootId`、auth 解析器、方法注册表、broadcast、rate limiter 等。

### 2.3 连接状态机（服务端视角）

握手相位常量 `WS_HANDSHAKE_PHASES`（`src/gateway/server/ws-types.ts:86`）：

```
tcp_accepted → ws_upgrade_started → auth_credentials_received → auth_validated
             → session_attached → hello_payload_prepared → ready
```

- 服务端在收到 `connect` 前先推 **`connect.challenge`** 事件（`connection.ts:340` 附近）：`{ nonce: randomUUID(), ts, capabilities }`；客户端必须在 `connect.params.device` 中签名该 nonce（设备身份，见 §7 前置说明）。
- preauth 握手有超时（`handshake-timeouts.ts` `resolvePreauthHandshakeTimeoutMs`）；未完成握手的关闭按 phase 记录诊断。
- 慢消费者保护：出站 `bufferedAmount > MAX_BUFFERED_BYTES` → close(1008)（`connection.ts:300-320`）。
- WS keepalive：`startWebSocketKeepalive`（`src/gateway/websocket-keepalive.ts`）——pending ping + pong deadline（借 socket timeout 触发 `onMissedPong`），仅连接拥有方可强杀。
- **liveness（进程级）**：`createGatewayEventLoopHealthMonitor`（`src/gateway/server/event-loop-health.ts`）采样 20ms：`delayP99>1000ms` / `utilization>0.95` / `cpuCoreRatio>0.9` 判 degraded，持续 60s 判 persistent degradation；对外经 `health`/`status` 方法与 `tick` 事件暴露（`TickEventSchema { ts }`）。

### 2.4 客户端重连状态机（client 侧，Atlas 可直接抄语义）

`GatewayProtocolClient`（`packages/gateway-client/src/protocol-client.ts`，"owns the single socket/handshake/reconnect/frame state machine"）+ `RetrySupervisor`（`packages/retry/src/index.ts:78`）：

- 默认策略（`packages/gateway-client/src/client.ts:376`）：`{ initialMs: 1_000, multiplier: 2, maxMs: 30_000 }` + 抖动；`computeBackoff = min(maxMs, initialMs·factor^(n-1)) + base·jitter·rand()`。
- 成功连接后 `reset()`；协议升级/特殊恢复路径 `resetReconnectBackoff(250)` 快速重连（client.ts:934 等）。
- **不可恢复错误暂停重连**：`shouldPauseGatewayReconnect`（`reconnect-policy.ts`）——`AUTH_TOKEN_MISSING / AUTH_PASSWORD_* / AUTH_RATE_LIMITED / PAIRING_REQUIRED / PROTOCOL_MISMATCH`（可选 terminal）等直接停机并回调 `onReconnectPaused`；`connect` 失败响应可带 `reconnectDelayMs`（含 close 1013 + Retry-After 语义）。

### 2.5 渠道连接与 durable ingress（渠道侧"断线重连"）

渠道（Telegram/Discord/…插件）不直接 dispatch，而是写入**每渠道持久化 ingress 队列**（SQLite 表 `channel_ingress_events`）：

- 记录（`ingress-queue.types.ts`）：`{ id, payload, metadata, receivedAt, updatedAt, laneKey?, attempts, lastAttemptAt?, lastError? }`；认领结构 `claim { token, ownerId, claimedAt }`（乐观 claim token，完成/释放需持 token）；完成后保留 completed/failed **墓碑**用于重复检测。
- 监控泵：`createChannelIngressMonitor`（`ingress-monitor.ts`）——pump/drain/startLimit/deferred lane、retention（默认：每小时 prune、completed/failed TTL 30 天、各 2 万条上限）、与 gateway 重启 drain fence 联动（`getGatewayRestartDrainSignal`、`isGatewayRestartDraining`）。
- 重试策略（`ingress-retry-policy.ts`）：`computeBackoff({initialMs:1_000, factor:2, maxMs:180_000, jitter:0}, min(attempts,9))`；**最多 8 次尝试且事件年龄 ≥ 24h 才 dead-letter**（二者同时满足）；不可重试错误（如 restart-recovery-tombstone）直接 fail。
- run 状态：`createRunStateMachine`（`src/channels/run-state-machine.ts`）——`activeRuns/busy/lastRunActivityAt`，活动期 60s 心跳刷新渠道状态面。

---

## 3. Inbound 消息完整路由路径

从渠道收到一条消息到回复投递，关键函数/文件按序：

1. **渠道接入层**（如 `extensions/telegram/src/bot-handlers.*`）收到原消息 → `durable-receive.ts` 追加进 ingress 队列（claim）。
2. **drain**：`createChannelIngressDrain`（`src/channels/message/ingress-drain.ts`）按 laneKey 并发上限取出 → 渠道 pipeline 组装 `MsgContext` 信封（`src/auto-reply/envelope.ts`、`src/channels/inbound-event/envelope.ts`）。
3. **路由解析**：`resolveAgentRoute(cfg, { channel, accountId, peer, guildId, teamId, memberRoleIds })`（`src/routing/resolve-route.ts`）→ `ResolvedAgentRoute { agentId, channel, accountId, sessionKey, mainSessionKey, lastRoutePolicy: "main"|"session", matchedBy }`；绑定索引 `getEvaluatedBindingsForChannelAccount`（`route-binding-index.ts`），结果有 WeakMap 路由缓存（上限 4000）。
4. **会话键**：`buildAgentSessionKey` → `buildAgentPeerSessionKey`（`src/routing/session-key.ts`；§1.4 规则）。
5. **turn 组装**：`dispatchRoutedChannelTurn` / `assembleResolvedChannelTurn` / `dispatchAssembledChannelTurn`（`src/channels/turn/lifecycle.ts:108,696-709`）；DM 捷径 `dispatchInboundDirectDm`（`src/channels/direct-dm.ts:127`）。此处做 hooks（message_received / message_sending）、route dmScope 覆盖（`route-dm-scope.ts`）。
6. **会话登记**：`recordInboundSession`（`src/channels/session.ts:27` → `src/config/sessions/inbound.runtime.ts`）写 session meta（groupResolution、lastRoute；主 DM pin 跳过逻辑 `shouldSkipPinnedMainDmRouteUpdate`）。
7. **去重认领**：`claimInboundDedupe(ctx)`（`src/auto-reply/reply/inbound-dedupe.ts:80`）——duplicate/inflight/claimed（详见 §5）。
8. **调度入口**：`dispatchInboundMessageWithRoutedChannelDispatcher` → `dispatchInboundMessage`（`src/auto-reply/dispatch.ts:183`）：
   - `finalizeInboundContext` 归一化 MsgContext；
   - 前台 FIFO 租约 `reserveForegroundReplyLease`（键 = `[channel, accountId, sessionKey, chatType, target]`，保证同会话回复顺序；`/status` 类检查命令可跳过排队）；
   - 群消息先经 `dispatchGroupThread`（群激活/thread 路由），否则 `dispatchReplyFromConfig`（`src/auto-reply/reply/dispatch-from-config.ts`，阶段化：prepare-context → prepare-execution → execute → choose-route → finalize）。
9. **Agent run**：`agent-runner*`（`src/auto-reply/reply/agent-runner.ts` 及 40+ 分件）在会话 transcript 上跑内嵌 agent loop（`src/agents/embedded-agent-runner/` + `packages/agent-core`）；ACP runtime 会话走 `dispatch-acp*.ts`。并发入站按 `messages.queue`：`mode: steer|followup|collect|interrupt`、`byChannel`、`debounceMsByChannel`、`cap`、`drop: old|new|summarize`（`QueueSchema`，`zod-schema.messages.ts:33-62`）。
10. **回复投递**：`ReplyDispatcher`（`reply-dispatcher.ts`）排队 payload → `chooseDispatchRoute`（`dispatch-from-config.choose-route.ts`）决定送 originating 渠道（`shouldRouteToOriginating`）还是 `turnLedger.sendQueued`；durable 投递经 `deliverInboundReplyWithMessageSendContextCore`（`turn/durable-delivery.ts`）+ session delivery queue；出站回声抑制 `outbound-echo.ts`；渠道 send 适配器（`src/channels/message/send.ts`）最终把文本/媒体发回平台。
11. **控制面入口**（对照）：operator 经 WS `chat.send`（scope `operator.write`）→ `src/gateway/server-methods/chat-send-handler.ts` + `chat-send-admission/work-admission/agent-dispatch` → 同一 agent-runner，事件经 `agent`/`chat` 广播回客户端。

---

## 4. gateway-protocol 核心 schema

包：`packages/gateway-protocol`（**唯一运行时依赖 typebox**；`package.json`）。版本常量（`src/version.ts`）：`PROTOCOL_VERSION=4`、`MIN_CLIENT_PROTOCOL_VERSION=4`、`MIN_NODE_PROTOCOL_VERSION=3`、`MIN_PROBE_PROTOCOL_VERSION=3`。

### 4.1 帧信封（`schema/frames.ts`）

- `RequestFrameSchema`：`{ type:"req", id, method, params?, traceparent?, expectedProfileId? }`
- `ResponseFrameSchema`：`{ type:"res", id, ok, payload?, error?: ErrorShape }`；`ErrorShapeSchema { code, message, details?, retryable?, retryAfterMs? }`
- `EventFrameSchema`：`{ type:"event", event, payload?, seq?, stateVersion?, recipientProfileId? }`
- `GatewayFrameSchema = Union([req,res,event], {discriminator:"type"})`

### 4.2 连接握手

- `ConnectParamsSchema`：`{ minProtocol, maxProtocol, client { id, displayName?, version, buildId?, platform, deviceFamily?, modelIdentifier?, timeZone?, mode, instanceId? }, caps?: string[], commands?: string[], permissions?, role?, scopes?, modelCatalog?, device { id, publicKey, signature, signedAt, nonce }, auth { token?, bootstrapToken?, deviceToken?, password?, approvalRuntimeToken?, agentRuntimeIdentityToken? }, locale?, userAgent? }`
- `HelloOkSchema`：`{ type:"hello-ok", protocol, server { version, buildId?, bootId?, connId }, features { methods[], events[], capabilities? }, snapshot, controlUiUrl?, policy { maxPayload, maxBufferedBytes, tickIntervalMs, attachments { maxBytes, maxImageBytes } }, auth { method: "none"|"token"|"password"|"tailscale"|"device-token"|"bootstrap-token"|"trusted-proxy", deviceToken?, role, scopes[], sessionCap: "write"|"suggest"|"view"|"none", deviceTokens[] } }`
- `connect.challenge` 事件：`{ nonce, ts, capabilities }`；`ShutdownEventSchema { reason, restartExpectedMs? }`；`TickEventSchema { ts }`。

### 4.3 事件与方法目录（节选）

事件（`src/gateway/server-methods-list.ts`）：`connect.challenge, agent, chat, chat.metadata.changed, models.snapshot, ui.command, session.approval|message|narration|observer|operation|sharing|suggestion|reaction|typing|tool, sessions.changed, presence, tick, talk.*, shutdown, gateway.suspension, device pair changed, update.*`。

方法（`src/gateway/methods/core-descriptors.ts`，元组 `[name, area, scope, since, flags]`，scope ∈ operator.read/write/admin/approvals/…）：`health, status, logs.tail, channels.status|start|stop|logout, config.get|set|apply|patch|schema, agents.list|create|update|delete|files.*, models.list|authStatus, tools.catalog|effective|invoke, chat.history|chat.send|chat.abort(隐含)|chat.get, sessions.*(reset/patch/list/history…), exec.approval.*, question.*, device.pair.*(list/approve/start), nodes.*, talk.*, mcp.app.*, fs.listDir, worktrees.*, usage.*` 等约 200 个。

---

## 5. Dedupe / Idempotency 与 Restart Recovery

### 5.1 入站去重（进程内）

`src/auto-reply/reply/inbound-dedupe.ts` + `src/infra/dedupe.ts`：

- 缓存：TTL+LRU `createDedupeCache`（`check/peek/delete/clear/size`），入站默认 **TTL 20 分钟、容量 5000**（`DEFAULT_INBOUND_DEDUPE_TTL_MS/MAX`），经 `Symbol.for("openclaw.inboundDedupeCache")` 跨 bundle 单例。
- 键：`JSON.stringify([sessionScope, routeKey, messageId])`，其中 `sessionScope = agent:<agentId>`（同一物理消息对同一 agent 绝不跑两次，即使路由键漂移）、`routeKey = channelRouteDedupeKey({channel, to: peerId, accountId, threadId})`、`messageId = ctx.MessageSid`。
- 状态机：`claimInboundDedupe` 返回 `invalid | duplicate | inflight | claimed{commit, release}`；in-flight Map（`Symbol.for("openclaw.inboundDedupeClaims")`）让并发重复变成 `inflight`；commit 在 dispatch 最终化时写入缓存；release 支持按 ownerToken 精确删除；重启恢复时带 `reclaimPendingInput` 重新认领（旧收据过期也先回收再放行）。
- **持久重复检测**：ingress 队列的 completed/failed 墓碑（30 天 TTL / 2 万条）在进程重启后仍能拦截重复投递。

### 5.2 持久化投递队列（跨重启）

`src/infra/session-delivery-queue*.ts` + `delivery-queue-sqlite*.ts`（SQLite 表 `delivery_queue_entries`，含 staging 队列、claim/lease、tombstone 保留与失败留存策略）：

- 载荷 `QueuedSessionDeliveryPayload` 两个变体：
  - `systemEvent { sessionKey, text, deliveryContext?, idempotencyKey? }`
  - `agentTurn { sessionKey, message, messageId, expectedSessionId?, requesterBinding { agentId, sessionKey, storePath, sessionId, lifecycleRevision }, route { channel, to, accountId, replyToId, threadId, chatType }, expectedMediaUrls/Attachments, preparedMediaBlocks, suppressTextDelivery?, idempotencyKey?, owner { kind:"subagent_completion", runId, taskId, generation, deadlineAt } }`
- 信封 `QueuedSessionDelivery`：`id = sha256(idempotencyKey)`（`buildEntryId`，天然幂等）、`enqueuedAt/retryCount/availableAt(lease)/lastAttemptAt/lastError/deliveryStartedAt/acknowledgedAt/settlementOutcome("recovered"|"moved-to-failed")/retainOnFailure`。
- 错误语义：`SessionDeliverySafeRetryError`（可重试，预算已持久化则 `SessionDeliveryRetryChargedError`）vs `SessionDeliveryDeadLetteredError`。

### 5.3 Restart recovery

- **Restart Sentinel**：重启前 `writeRestartSentinel(payload)`（`src/infra/restart-sentinel.ts` → `restart-sentinel-store.ts`，SQLite + worker 写准入）持久化 `{ runningVersion, pending continuations, update run 状态 }`。
- 开机恢复：`src/gateway/server-restart-sentinel.ts`（"Gateway restart sentinel recovery resumes pending continuations and outbound delivery"）——
  1. 读 sentinel 快照（`server-restart-sentinel-snapshot.ts`）；
  2. `recoverPendingSessionDeliveries` / `drainPendingSessionDelivery`（`src/infra/session-delivery-queue-recovery.ts`）把未确认投递重放（busy 重试 6s 间隔、`RESTART_CONTINUATION_BUSY_MAX_ATTEMPTS` 上限）；
  3. 重建 restart continuation（`server-restart-sentinel-continuation-intent.ts`，按 `resolveQueuedRestartContinuationMessageId` 幂等）；
  4. 渠道投递"重启通知"（`server-restart-sentinel-notice.ts`），finalize update run；
  5. 渠道 ingress drain 与重启 fence 协同（`getGatewayRestartDrainSignal`）——drain 期间不再认领新事件，排空后恢复。
- 会话级恢复状态：`SessionEntry` 上的 `SessionRestartRecoveryState` / `RestartRecoveryRun { runId, lifecycleGeneration }` + `restart-recovery-receipt.ts` 收据，防止旧 generation 的 run 在重启后被误恢复。

---

## 6. Owner / Allowlist / Mention Gating

- **DM 策略**：`dmPolicy: "pairing" | "allowlist" | "open" | "disabled"`（`DmPolicySchema`，`zod-schema.core.ts`）。判定在 `senderGateForDirect`（`src/channels/message-access/sender-gates.ts`）：disabled→block；open 仍要求显式 `*` 或命中 allowlist；allowlist 命中→放行；pairing 时允许查 pairing store（`src/pairing/pairing-store*.ts`，未配对则发配对码 `dm_policy_pairing_required`）。每条判定输出带 redacted allowlist 诊断的 `AccessGraphGate`。
- **allowlist 来源合并**：`mergeDmAllowFromSources`（config `allowFrom` + pairing store 批准 id，`src/channels/allow-from.ts`）；组用 `resolveGroupAllowFromSources`（`groupAllowFrom` 独立、可回退 `allowFrom`）；通配 `isSenderIdAllowed`（空表=allowWhenEmpty、`*`=全放行）；`accessGroup:` 前缀引用访问组。
- **群策略**：`groupPolicy: "open" | "disabled" | "allowlist"`（`GroupPolicySchema`）。
- **Mention gating**：`resolveInboundMentionDecision`（`src/channels/mention-gating.ts`）——facts `{ canDetectMention, wasMentioned, hasAnyMention, implicitMentionKinds }` × policy `{ isGroup, requireMention, implicitMentions, allowTextCommands, hasControlCommand, commandAuthorized }` → `{ effectiveWasMentioned, shouldSkip, shouldBypassMention }`。隐式 mention 类型：`reply_to_bot`（回复 bot 消息）、`quoted_bot`（引用）、`bot_thread_participant`（bot 所在 thread）、`native`；由 `ChannelImplicitMentionsConfig { replyToBot, quotedBot, threadParticipation }`（默认全开）生成 kind allowlist。bot 自有 thread 可单独配置 `requireMentionInBotThreads`（`resolveBotThreadMentionPolicy`）。显式 pattern：agent `identity.mentionPatterns`（默认从 name/emoji 派生）与 `groupChat.mentionPatterns`。
- **群激活**：`src/auto-reply/group-activation.ts`——`mode: "mention" | "always"` + `/activation` 类命令切换。
- **命令权限**：入站 slash 命令需 `commandAuthorized`；owner 权威是**运行时能力令牌**而非可伪造数据——`bindCommandOwnerAuthority` 把 `CommandOwnerCapability{ isCurrent, operatorAuthority }` 以 Symbol 挂在上下文上（`src/auto-reply/command-owner-authority.ts`），身份/角色被撤销后 `captureCommandOwnerAssertion` 立刻抛 `CommandOwnerRevokedError`（"wire data cannot" 伪造）。
- **跨渠道身份合并**：`session.identityLinks`（`resolveLinkedDirectPeerId`）把声明身份并到同一 DM 会话。

---

## 7. 可移植性分析与 Node Sidecar 可行性

### 7.1 纯协议/状态机（可直接移植 Python）

| OpenClaw 位置 | 内容 | 移植难度 |
|---|---|---|
| `packages/gateway-protocol/src/schema/frames.ts` | req/res/event 帧信封、ConnectParams、HelloOk、ErrorShape | 低（TypeBox→pydantic，或直接消费 `protocol.schema.json` codegen） |
| `src/routing/resolve-route.ts` + `route-binding-index.ts` | binding 匹配分层与 route 解析（纯函数 + WeakMap 缓存） | 低 |
| `src/routing/session-key.ts` | 会话键字符串规则 | 低 |
| `src/infra/dedupe.ts` + `inbound-dedupe.ts` | TTL/LRU 去重 + in-flight claim 语义 | 低（asyncio 单线程下更简单） |
| `src/channels/message/ingress-queue*.ts` + `ingress-retry-policy.ts` | SQLite ingress 队列、claim token、backoff/dead-letter 公式 | 中（表结构+事务语义要抄准） |
| `src/infra/session-delivery-queue*.ts` | 持久投递队列与幂等键 | 中 |
| `packages/retry/src/index.ts` | `RetrySupervisor`/`computeBackoff`（~120 行） | 低 |
| `src/gateway/server/connection.ts` 握手相位 + `connect.challenge` nonce + `packages/gateway-client/src/device-auth.ts` 签名载荷 | 握手/设备配对协议 | 低-中 |
| `sender-gates.ts` / `mention-gating.ts` / `allow-from.ts` | 门控决策（纯函数） | 低 |

### 7.2 与 Node 深耦合（移植 = 重写）

- `src/gateway/server*.ts`（867 个文件）与 `src/gateway/server-methods/**`：根包 `openclaw` 的一部分，lazy import `server-start.ts` 后的启动图覆盖 channels/plugins/agents/llm/MCP —— **gateway 服务器与 OpenClaw 自带 agent runtime 同进程共生**（in-process run：`in-process-session-run.ts`、`gateway/agent-turn/`）。
- 基础设施：`node:sqlite`（`node-sqlite.mjs`）+ Kysely、`worker_threads`（SQLite 只读 worker、event-loop sampler）、`node:perf_hooks`（`event-loop-health.ts`）、`ws` 传输、`@lydell/node-pty`、grammy（Telegram）等。
- 根 `package.json` dependencies 证实：agent 运行时、全部 LLM provider SDK、MCP、TUI 都在同一个包里。

### 7.3 Sidecar 结论

**问：把 gateway 做成 Node sidecar，可行吗？是否违反"禁止第二 Agent core"？**

- **不可行（违反约束）**：直接把 `src/gateway` 作为 sidecar 运行 = 运行完整 OpenClaw（gateway 内嵌并调度它自己的 agent loop）。它会带来：整个 `openclaw` 根包（数百依赖：全部 provider SDK、MCP、plugin 框架、TUI），且必然自建自己的 LLM 会话——这就是第二个 Agent core。也没有"只跑 gateway 不跑 agent"的干净开关：方法层（chat.send/agent.*）默认在进程内跑 agent。
- **唯一干净的 Node 复用是客户端库**：`@openclaw/gateway-client`（依赖仅 `ws` + `ipaddr.js` + `@openclaw/gateway-protocol`）与 `@openclaw/gateway-protocol`（仅 typebox）。它们可作为 Electron 前端或 Node 工具的**纯协议客户端**，不拖 agent runtime。
- **推荐路线**：**不用 Node sidecar**。在 Atlas Python 内重实现 gateway 语义（协议帧 + 路由/会话键 + 队列/去重/恢复），把 §7.1 列出的纯状态机移植过来；OpenClaw 源码作为行为规格（协议 schema 可用其 `protocol.schema.json` 做 codegen 对照）。这样 Atlas 只有一个 Agent core（现有 `core/atlas/agent`），gateway 是它的 I/O 壳。

---

## 8. Atlas 落点建议

Atlas 现状：`core/atlas/server.py`（7925 行，FastAPI 单体）、`core/atlas/telegram.py`（262 行出站轮询）、`core/atlas/agents/`、`core/atlas/memory/`、Electron 前端。建议新建 gateway 子系统（文件路径级）：

### 8.1 建议模块划分

```
core/atlas/gateway/                     # 新增：常驻 gateway 包
  protocol/
    frames.py          ← packages/gateway-protocol/src/schema/frames.ts（req/res/event 信封、ErrorShape）
    connect.py         ← ConnectParamsSchema/HelloOkSchema + connect.challenge nonce 流程
    errors.py          ← connect-error-details.ts（错误码 + 恢复提示 canRetryWithDeviceToken/recommendedNextStep）
    version.py         ← PROTOCOL_VERSION / min-client 语义
  registry.py          ← src/gateway/server/client-registry.ts（connId 索引 + retain + 定向 fanout）
  connection.py        ← src/gateway/server/connection.ts + ws-types.ts（握手相位机）+ websocket-keepalive.ts（ping/pong 期限）
  backoff.py           ← packages/retry/src/index.ts（RetrySupervisor/computeBackoff，客户端与服务端共用）
  dedupe.py            ← src/infra/dedupe.ts + src/auto-reply/reply/inbound-dedupe.ts（键=[agentScope,routeKey,msgId]）
  health.py            ← src/gateway/server/event-loop-health.ts（语义改为 asyncio loop-lag 采样）
  restart.py           ← src/infra/restart-sentinel.ts + src/gateway/server-restart-sentinel.ts（重启前写 sentinel、开机 drain）
core/atlas/agents/
  roster.py            ← src/config/zod-schema.agent-entry-base.ts + zod-schema.agents.ts（AgentEntry pydantic + roster 校验）
  scope.py             ← src/agents/agent-scope-config.ts（workspace/agentDir/model 解析、默认继承）
  bindings.py          ← src/config/zod-schema.agents.ts(BindingsSchema) + src/routing/route-binding-index.ts（match 归一化/索引）
core/atlas/routing/
  session_keys.py      ← src/routing/session-key.ts（agent:<id>:… 键规则、dmScope/groupScope、identityLinks）
  resolve_route.py     ← src/routing/resolve-route.ts（分层匹配 + route 缓存）
core/atlas/channels/                   # 由现有 telegram.py 扩展成包
  base.py              ← src/channels/plugins 契约（access/send/pairing 适配器接口）
  ingress_queue.py     ← src/channels/message/ingress-queue*.ts + ingress-retry-policy.ts（SQLite：claim token、1s×2→3min、8 次+24h dead-letter）
  monitor.py           ← src/channels/message/ingress-monitor.ts（pump/drain/retention/restart fence）
  gating.py            ← src/channels/mention-gating.ts + message-access/sender-gates.ts + allow-from.ts（dm/group/mention 决策）
  pairing.py           ← src/pairing/pairing-store*.ts（配对码 + 批准写回 allowFrom）
  telegram.py          ← 现有 core/atlas/telegram.py 迁入，加 durable receive + 入站
core/atlas/sessions/
  store.py             ← src/config/sessions/types.ts（SessionEntry 核心：lastRoute/lifecycleRevision/restartRecovery…）+ store-writer.ts（原子写）
  delivery_queue.py    ← src/infra/session-delivery-queue.records.ts + session-delivery-queue-recovery.ts（幂等键 sha256(idempotencyKey)、lease/ack/死信）
  queue_modes.py       ← src/config/zod-schema.messages.ts QueueSchema（steer/followup/collect/interrupt + debounce/cap/drop）
```

### 8.2 移植优先级

1. **P0（语义骨架）**：`roster.py`、`bindings.py`、`session_keys.py`、`resolve_route.py`、`gating.py` —— 纯函数，先写单测对照 OpenClaw 行为。
2. **P1（可靠性）**：`ingress_queue.py`、`delivery_queue.py`、`dedupe.py`、`restart.py` —— Atlas 从"进程死了消息就丢"升级为 OpenClaw 级 durable 语义。
3. **P2（对外协议）**：`protocol/` + `connection.py` + `registry.py` —— 若 Atlas Electron/移动端要用 WS 控制面，可直接采用同构帧协议（前端可复用 `@openclaw/gateway-client`，它不携带 agent runtime，不违反单 core 约束）。
4. **P3（可选）**：`pairing.py`、`health.py`、`queue_modes.py`。

### 8.3 明确不做

- 不把 `src/gateway` / OpenClaw 进程作为 sidecar 接入 Atlas（= 第二 Agent core，违反约束；依赖面也无法收敛）。
- 不移植 ACP runtime、MCP harness、TTS/Talk、Control UI、cloud worker 等外围（与 persistent-atlas 目标无关）。
- 不照抄 `openclaw.json` 的全部字段；Atlas roster 只取 §1.2 的子集：identity / model(+fallbacks) / workspace / channel binding（match+session scope）/ heartbeat / groupChat.mentionPatterns / tools allow-deny。
