# R3 研究报告：OpenClaw 的 node / paired machine / computer placement 语义

- 来源（冻结，只读）：`D:\Atlas-persistent-sources\openclaw`（HEAD `3e5560873a4`）
- 对照本体：`D:\Atlas`（HEAD `a034bff`，X2 Windows Computer/Browser 执行层已有）
- 日期：2026-10-03
- 回答六个问题：设备模型 / placement 决策 / computer tool 路由 / takeover-handoff / 离线重连 / Atlas 落点建议

---

## 1. 设备 / node 数据模型

### 1.1 持久层：PairedDevice（SQLite 设备配对库）

文件：`src/infra/device-pairing.types.ts`（`PairedDevice`，L131-154）。关键身份字段：

| 字段 | 含义 |
|---|---|
| `deviceId` | 稳定设备 id（= nodeId，协议里 `connect.device.id ?? connect.client.id`，见 `src/gateway/node-registry.ts` `registerSession` L486） |
| `publicKey` | 设备密钥对公钥；连接时验签（`captureAuthenticatedNodePairingState`，`src/infra/device-pairing-node-state.ts` L66-92 要求 publicKey+token+role 三者全对） |
| `tokens: Record<role, DeviceAuthToken>` | 每角色 bearer token；`DeviceAuthToken{token, role, scopes, createdAtMs, rotatedAtMs?, revokedAtMs?, lastUsedAtMs?}`（L45-57） |
| `roles` / `approvedScopes` | 角色（`operator` / `node` …）与授权 scope 基线 |
| `approvedVia: PairedDeviceApprovalKind` | 授权方式：`owner | silent | trusted-cidr | trusted-proxy | ssh-verified | bootstrap`（L69-75；只有 `silent`（同机）可被自动 prune，跨机永不自动删） |
| `nodeSurface: PairedDeviceNodeSurface` | node 角色的持久授权面：`displayName/caps/commands/permissions/bins/sessionHost/lastConnectedAtMs/lastDisconnectedAtMs/lastHostStats`（L84-101）。**注释明确：这里的 displayName 是审批时的操作员命名，重连元数据刷新不得覆盖它** |
| `pendingNodeSurface` | 待审批的 surface 扩容请求，带 `revision` 防"重连 vs 审批"竞态（L110-128） |
| `lastSeenAtMs` / `lastSeenReason` | presence 持久化（由 `updatePairedDevicePresence` 带期望 pairingGeneration 写入，`src/infra/device-pairing.ts` L188-198） |
| `createdAtMs` / `approvedAtMs` | 生命周期时间戳 |

配对状态解析：`NodePairingState = { identity: {nodeId, key}, generation: {nodeId,key} | null }`（`src/infra/device-pairing-core.types.ts` L13-16）。**pairingGeneration 是撤销/重配对的核心机制**：角色或 surface 变化 → 生成新 generation → 所有持有旧 generation 的连接被判 stale 并 invalidate（`NodeRegistry.invalidateSessionForPairingChange`，`node-registry.ts` L702-724；`settleNodeRegistryPairingGenerationChange`）。

存储操作全部经 `withDevicePairingLock` + worker mutation（`device-pairing.ts`）：`requestDevicePairing / rejectDevicePairing / removePairedDevice / removePairedDeviceRole / updatePairedDeviceMetadata / updatePairedDevicePresence`。

### 1.2 内存层：NodeSession（连接中的会话）

文件：`src/gateway/node-session.types.ts`。`NodeRegistry`（`node-registry.ts`）持有 `nodesById`/`nodesByConn` 两张 Map。关键字段：

- 身份：`nodeId, connId, pairingIdentity, pairingGeneration, clientId, clientMode, displayName, platform, version, coreVersion, uiVersion, deviceFamily, modelIdentifier, remoteIp`
- 能力面：`declaredCaps/commands`（节点自报的持久声明）、`sessionCapsCeiling/sessionCommandsCeiling`（本连接上限）、生效 `caps/commands/permissions`（= approved ∩ declared，`refreshSessionPolicy` L376-435 每次配置/pairing 变化重算）、`declaredComputerUse/computerUse`（ComputerUseCapabilityDescriptor，含 provider.generation 与 action 列表）
- presence：`connectedAtMs, lastActiveAtMs, presenceUpdatedAtMs, presenceActivitySource('app'|'system'), hostStats(60s 快照), desktopAvailability('locked'|'unlocked'|'unknown')`
- 连接替换语义：同一 nodeId 新连接注册时先 set 再 unregister 旧连接（L562-566），旧连接的 pending invoke 被判 `DISCONNECTED`，但不会误发 offline 事件。

### 1.3 配对流程（两段式）

文档 `docs/nodes/pairing-and-status.md` + `src/gateway/node-connect-reconcile.ts` `reconcileNodePairingOnConnect`：

1. **设备配对（transport 认证）**：node 用签名设备身份连接 → gateway 建 `DevicePairingPendingRequest`（含 publicKey/displayName/platform/roles/scopes/remoteIp，TTL 5 分钟、重试刷新同 requestId，auth 变更则 supersede 旧请求）→ 操作员 `devices approve <requestId>`（或 silent/trusted-cidr/ssh-verified/bootstrap 自动）→ 写入 PairedDevice + 签发 node token。
2. **命令面审批（能力授权）**：设备批准后连接会再触发一个 node-surface pending 请求（`nodes pending / nodes approve`）。审批 scope 分级：无命令请求只要 `operator.pairing`；含 `system.run` 等要 `operator.admin`。后续任何扩容（新命令/新 cap/新权限）都要重新审批；缩容/权限丢失只收窄不触发审批。
3. **撤销**：`devices remove`（`removePairedDevice`）或 `nodes remove`（只摘 `node` 角色，混合角色设备保留行）→ 先 invalidate 客户端连接（credential fence）→ 再做环境/placement 清算（见 §5）。
4. **Setup code 快速配对**：`device.pair.setup_code`（schema `packages/gateway-protocol/src/schema/devices.ts` L178-216）mint 短期 bootstrap token，`bootstrapProfile: "limited" | "node" | "voice-node"` 控制交接面；`setupId` 是与 bearer 无关的关联 id，`device.pair.setup_status` 能回答"这个码到底成没成"（含 `deliveryUncertain` 态）。

### 1.4 presence / last_seen / online 判定

- **online = 连接当前且 pairing 现行**。`listCurrentConnected/getCurrentConnected` 每次都过 `resolvePairingLease`（`node-registry.ts` L348-374）：比对内存 lease 的 identity/generation 与持久 pairing 发布（`isPairingStateCurrent`），stale 则 invalidate。`client.invalidated === true` 的会话从所有列表消失。
- **活动 presence（谁在用电脑）**：`node-registry.presence.ts`。macOS app 上报 `{idleSeconds, source: 'app'|'system', saturated}` → `updateNodePresenceActivity`（L58-94）换算 `lastActiveAtMs = observedAtMs - idleSeconds*1000`；`source` 切换时直接替换而非取 max（防止旧源样本漂移）。`selectActiveNode/selectActiveNodesByProfile`（L15-56）选出"最近有输入"的机器 → `publishActiveNodeContext`（`node-registry.ts` L861-886）把它发布为 agent prompt 的 active-node hint（按认证用户 profile 分组，绝不跨人兜底）。权限变化（accessibility 撤销）会 `clearNodePresenceActivity`。
- **心跳 beacon**：`node.presence.alive`（payload schema `packages/gateway-protocol/src/schema/nodes.ts` L37-46，reason 枚举 `packages/gateway-protocol/src/node-presence.ts`：`background/silent_push/bg_app_refresh/significant_location/manual/connect`）记录"移动端醒过"，不算 connected、不算用户活动。
- **last_seen 持久化**：`updatePairedDevicePresence`（带 expectedPairingGeneration 乐观校验）；`hostStats` 每 60s 上报并在 PairedDevice 留 last-known 快照（离线仍显示，带 `updatedAtMs`）。
- **桌面可用性**：`updateDesktopAvailability`（node-registry.ts L796-815）记录 native 会话 `locked/unlocked/unknown`；`checkConnectivity`（L889-989）用 websocket ping/pong 主动探测（2s 超时），并 fence "探测期间连接被替换"。

---

## 2. Session placement 决策：session 放在哪台机器跑

### 2.1 三种执行形态

（文档 `docs/gateway/cloud-workers/placement-and-machine-selection.md`、`docs/nodes/session-hosting.md`）

1. **Gateway 本机**（`local`）——默认。
2. **paired device worker**（`deviceId` / `autoDevice`）——session 被 dispatch 到一台已配对、已开 `nodeHost.workerRuns.enabled` 的 node，gateway 把 sealed worker bundle + workspace 传过去，node 上跑 worker 子进程执行 turn。
3. **cloud profile**（`profileId`，Crabbox 等 provider）+ **paired-device remote-exec**（如 Codex exec-server 直接在 node 上跑，不占 worker slot）。

### 2.2 placement 状态机（权威）

`packages/gateway-protocol/src/schema/session-placement-state.ts` + `src/gateway/worker-environments/placement-state.ts`：

```
local → requested → provisioning → syncing → starting → active → draining → reconciling → local | reclaimed | failed
                     └──────────── 全程可 → failed ←────────────┘
reclaimed → requested ; failed → local | requested
```

每个 placement 记录（`schema/session-placement.ts`）：`generation`（单调递增）、`activeOwnerEpoch`（环境租约纪元）、`environmentId`、`workerBundleHash`、`remoteWorkspaceDir` + `workspaceBaseManifestRef`、`runner: {kind:'device', status:'available'|'offline', deviceId}`、`diskSpace`、`workerRuntimeInstall{phase:transferring|installing}`、`workspaceResultConflict`、失败态带 `recoveryError/recoveryAction('restart'|'stop-first')/retryOnSend`。

### 2.3 设备候选选择（Auto 放置算法）

`src/gateway/worker-environments/device-placement-selector.ts` `selectDevicePlacementCandidates`：

1. 过滤 `environment.type === 'node'`，按 id 排序；有 `update-required` issue 的设备不能当候选（但保留错误信息优先展示）。
2. 只要 `sessionHost === true` 的环境（= 节点显式开启并声明 hosting）；没有 → "no paired session-host nodes"。
3. 只要 `status === 'available'`（连接现行）；全断连 → 报 disconnected。
4. 对每台跑 `resolveDevicePlacementEligibility`（`device-placement-eligibility.ts`）：
   - `resolveDeviceWorkerAvailability`（device-provider.ts）+ worker-turn 时 `resolveNodeWorkerExecutionIssue(node.workerHost)`（captured exec-policy 支持）；
   - **lease 现行性**：nodeId/connId/pairingGeneration 与请求时一致；
   - **requiredNodeCommands**：`resolveRequiredNodeCommandAuthority` 给出四态 `invocable | pending-approval | undeclared | unauthorized`（schema environments.ts L102-107），非 invocable 即不可选；
   - **slot**：`availableWorkerSlots(node.workerHost.capacity)`；`consumesWorkerSlot` 的 runtime 要求 >0。
5. **Auto 排序**（L98-114）：`consumesWorkerSlot` 时按 `admittedSessions/totalSlots` 升序（负载比最低优先）→ `availableSlots` 降序 → deviceId 字典序；不占 slot 的 runtime 直接取最小 deviceId。pending dispatch 数（`getPendingDispatchCount`，来自 `device-placement-demand.ts` 投影已准入但未物理启动的工作）会从 availableSlots 里扣。
6. 失败信息分层：update-required > 具体 eligibility issue > at-capacity > 不支持 runtime。选中后 workspace 准备开始前三台以内可顺位重试；准备一旦 admitted，后到的满载不取消它（`docs/nodes/session-hosting.md` "Auto" 节）。

worker slot 语义：默认每 CPU 核 1 slot（`nodeHost.workerRuns.capacity` 可配）；idle worker（≤2 个、保留 2 分钟）可被 reclaim；新 turn 最多等 10s durable slot。**placement 本身不占 slot，turn 启动才占**。

### 2.4 `session-placement-computer.ts` 本体机制

文件 `src/agents/session-placement-computer.ts`（仅 51 行，真正的"决策"是**绑定而非选择**）：

- 一个 `AsyncLocalStorage<PlacementComputerContext>`（`Symbol.for("openclaw.sessionPlacementComputer")`），context = `{runId, agentId, isActive(), sandboxToolPolicy?, bind(run)}`。
- 唯一写入点：`src/gateway/worker-environments/workspace-result-finalize.ts` L483-495 —— 远程 worker turn 执行前 `withSessionPlacementComputer({...}, runLocal)`，其中 `bind = (run) => computer.bind(run)`，`computer` 来自 `params.environments.prepareComputer(turnClaim)`（= `computer-transport.ts` `createWorkerComputerTransportOwner`，见 §3.2）。
- 唯一读取点：`resolveSessionPlacementComputer(run)`（agent-tools.ts L473 与 embedded-agent-runner/run/attempt-tool-prepare.ts L222）：
  - 无 store → `undefined` = 普通 node 路由（computer tool 自由选机）；
  - 有 store 且 `run.runId === context.runId && isActive()` → `bind(run)` 返回**绑定到本 session 桌面的 transport**；
  - 有 store 但 run 不匹配/已失效 → `null` = **显式扣留**（不回退到别的机器）。
- `resolveSessionPlacementSandboxToolPolicy`（L31-43）同步把 placed session 的 sandbox 工具策略（containedToolNames 含 `computer`）注入。
- 绑定期间的每一步都做权威断言（workspace-result-finalize.ts L447-479 `assertNodeExecutionCurrent`）：placement `state==='active' && executionMode==='remote-exec'`、generation/ownerEpoch/environmentId/nodeDeviceId/attachedSessionIds===1 全对才放行。

**结论**：OpenClaw 的 placement 决策 = 派发时一次性选设备（显式或 Auto 排序），此后 placement 记录持有 `environmentId + ownerEpoch + generation`，session 的 computer 工具被 AsyncLocalStorage 绑死到该环境的桌面；不存在"每次调用重新就近选机"。

---

## 3. computer tool 与 gateway 的关系

### 3.1 命令契约

- 节点命令就两条：`computer.act`（输入+观察动作）与 `screen.snapshot`（截图，返回 `displayFrameId`）。协议 schema：`packages/gateway-protocol/src/schema/computer.ts`（`ComputerInvokeParamsSchema{command, params, generation, timeoutMs?, idempotencyKey}`）。
- capability descriptor（`src/plugins/computer-use-contract.ts`）声明 provider `generation` 与 v2 action 集（pointer/keyboard/scroll/window/element/browser/recording…）。工具只暴露 provider 能忠实执行的 action；`COMPUTER_CONTRACT_MISMATCH` / `COMPUTER_STALE_FRAME` / `COMPUTER_STALE_OBSERVATION` 是三类核心错误码。
- 坐标安全：坐标动作必须 echo 截图 `frameId`；`displayFrameId`（provider 签发的显示身份）随动作携带，显示器重连/几何变化 fail closed；屏幕像素不变时返回 "screen unchanged since previous frame" 省上下文。

### 3.2 工具调用怎么路由到具体机器

入口 `src/agents/tools/computer-tool.ts` `createComputerTool`（每实例串行化 opQueue 保证输入按模型顺序落地）。`ComputerToolSession.resolveTarget`（computer-tool-node.ts L287-473）解析 target，`src/agents/tools/computer-tool-bindings.ts` `resolveComputerBinding`（L56-248）按四条路由产生 `ComputerBinding{host, gatewayOpts, capabilities, invoke}`：

1. **`environmentId`（attached/cloud session 桌面）**：要求 admitted run + `workerEnvironmentService.findSessionAttachment(caller)`，每次 invoke 前后 `touchSessionAttachment` + `assertSessionAttachment` + run authority 校验；`prepareAttachedComputer(...).bind(run)` 得到 transport；`__close_execution` 映射为 `prepared.close('execution-complete')`。
2. **session transport（placed session，§2.4 注入）**：`transport.resolveNode()` 直接给出唯一 node；拒绝一切 host/gateway override（"Computer control is bound to this session's desktop"）。
3. **`target:'gateway'`（gateway 自己的桌面）**：`loadGatewayComputerStatus` / `computer.status` RPC → `computer.invoke` RPC；要求调用者是"该 gateway 托管的 agent run"（`assertHostedCaller`），远端 URL/token override 的连接不能蹭 gateway 桌面。
4. **paired node（默认回退）**：`listNodes` + `isEligibleComputerNode`（必须同时 advertise `computer.act`+`screen.snapshot`）→ `resolveEligibleNodeFromList`：明确指定则精确匹配；多个候选报错列出 id；零候选报错并给 enablement 提示。invoke 走 `invokeAgentNodeCommand` = `node.invoke` RPC（带 idempotencyKey）。

绑定后 target 记忆：`executionTargets: Map<computerHostKey, binding>`；`heldButtonTarget` 阻止按住左键时切换机器/屏幕；`take_control` 仅限 attached/session 桌面。执行结束 `dispose(reason)` 对每个 binding 发 `__close_execution`（幂等键 `computer.close:{executionId}:{hostKey}`），session-transport/attached/gateway 的清理失败会向上抛（node 路由尽力而为）。

### 3.3 Gateway 侧的"自己的电脑"

- `src/gateway/server-methods/computer.ts`：`computer.status` / `computer.invoke` RPC。调用者身份三分：admitted agent run（`agentRuntimeIdentity` → owner = `computerRunOwner(authority)`）、普通 operator 连接（owner=connId）、synthetic discovery。`assertCurrent` 组合 connectionSignal + sessionMutationCommitGuard + run 审批权威校验。
- `src/gateway/desktop/computer-owner.ts`：`computerRunOwner` 把 owner 编码为 `[agent, instanceId, runId, lifecycleGeneration, claimId]` —— **一个物理执行属于一个确定的 admitted-run claim**。
- `src/gateway/desktop/computer-service.ts` `createGatewayComputerService`：单 runtime（`HostRuntime{provider, desktopTarget:'native'|'managed', process, desktop?, execution?}`）；`prepare()` 惰性启动；`invoke()` 做 generation fence（`COMPUTER_STALE_OBSERVATION`）、**单执行独占**（`COMPUTER_HOST_BUSY: another execution owns the Gateway computer`）、幂等键 replay 检测（同键不同输入报错；已 settled 的键要求先观察再新动作）；idle timer（无执行 60s / 有执行 5min）后台 retire；`revokeRunAuthority` 在 run 结束时回收。managed 模式先从 `HostDesktopService.acquireComputer` 拿桌面 lease/环境。
- `src/gateway/desktop/computer-process.ts` `startComputerHostProcess`：spawn 私有 helper 子进程（stdin/stdout NDJSON，协议 `computer-protocol.ts`：`start/invoke/cancel/stop` → `ready/result/error`），60s 启动超时、30s 优雅停机、32MB 消息上限；owner 进程退出即 fail 全部 pending。
- `src/gateway/desktop/session-registry.ts`：人类观察者/控制器的桌面会话注册表（见 §4）。

### 3.4 放到 paired node 桌面（session 环境）

`src/gateway/worker-environments/computer-transport.ts` `createEnvironmentComputerTransportOwner`：对 `environment.nodeDeviceId`：
- 一次性 probe：一次性 worker（非 sharedHost）走私有 worker-supervisor 协议 `NODE_WORKER_DESKTOP_COMPUTER_COMMAND {operation:'capabilities'}` 拿 descriptor；sharedHost（配对宿主自己的桌面）要求公开面上两条命令齐全。
- `bind(run)` 生成每次 run 的 transport：execution 首次使用时 gateway **自己 mint 物理 executionId**（"Remote execution IDs are correlation only. The Gateway alone mints the native owner"），之后每个动作都带它；`applyPluginNodeInvokePolicy`（高危动作分类/审批）→ `send()`（私有通道或 `nodeRegistry.invoke`，带 expectedConnId/pairingGeneration）。
- 每次 dispatch 前重验：环境 lease/epoch、node connId/pairingGeneration、plugin policy 现行、run authority。

---

## 4. takeover / handoff 语义（人接管 ⇄ agent 控制）

涉及文件：`src/gateway/desktop/session-registry.ts`（控制权仲裁）、`src/gateway/worker-environments/computer-transport.ts` L336-614（agent 侧状态机）、`docs/nodes/computer-use.md`（产品语义）。

### 4.1 控制权注册表（每个桌面 source 一个 controller 槽位）

`createDesktopSessionRegistry`（session-registry.ts）：
- `attachObserver({control, operatorName, ownerEpoch})`：`control=true` 且已有 controller → 逐出旧控制器，对其 websocket 发 close(4000, `control-taken:<operatorName>`)；`onControlChanged` 通知监听者。
- `takeControl(sourceKey, ownerEpoch)`（L339-359）：**agent 侧接管入口**。逐出当前 controller 并 close(4000, `control-taken:Agent`)；ownerEpoch 不匹配抛 `DesktopSessionStaleOwnerError`。UI 侧收到后以 view-only 重连。
- 人类拿回控制：再 `attachObserver(control=true)` → 逐出的是"当前 controller"（不管它是人还是已被 agent take_control 后的 view-only 观察者）。
- 观察者上限 8、linger 60s、`retainActivity`（computer 执行与 browser observer 分离保活）。

### 4.2 agent 侧输入状态机（computer-transport.ts bind()）

```
state: AGENT_ACTIVE
  ├─ 人类 attachObserver(control) → onControlChanged(controlled=true)
  │    → inputNeedsObservation=true, controlGeneration++
  │    → abort 所有 in-flight inputControllers（"Computer input paused while the operator has control"）
  │    → 之后每个 isInput 动作在 assertInvocationCurrent 被
  │      hasController() 拒绝："Computer input paused … use take_control when asked to resume"
  │    → 观察（screenshot 等非 input）仍允许 ← agent 还能看屏幕
  ├─ agent 调 take_control（action:'__take_control'）
  │    → 先 setTarget+清 observationState（人类输入作废旧坐标帧）
  │    → takeoverKey=[environmentId, ownerEpoch, idempotencyKey] 记入 completedTakeovers（WeakMap 按 run）
  │    → registry.takeControl() 逐出人类控制器（close 4000 control-taken:Agent）
  │    → 若此刻又有 controller（人抢回）→ "The operator took control again; observe before requesting another takeover"
  │    → 成功后仍 inputNeedsObservation=true：必须先新截图才能输入（COMPUTER_STALE_OBSERVATION）
  ├─ 新 screenshot 在 controlGeneration 未变且无 controller 时 → inputNeedsObservation=false → 回 AGENT_ACTIVE
  └─ binding.close / run 结束 → close('turn-complete') 发 __close_execution，物理执行退役
```

产品语义（docs/nodes/computer-use.md L17）：人接管**暂停 agent 输入并取消 pending 输入**（不取消观察）；"普通输入绝不自动接管"；被打断的动作**不重放**；takeover 使旧坐标/窗口/浏览器观察全部失效。`take_control` 是显式 handoff，复用 admitted run 已有的 computer-control authority，无需 viewer 签发 handoff token。

### 4.3 活动指示（activity indication）

- **机器活跃度**：§1.4 的 presence activity（15s 合并上报、3min keepalive、30 天 idle 上限）→ `nodes status` 标 `active`，agent prompt 拿 stable active-node hint；连接告警路由到最近活跃 Mac。
- **桌面状态**：`desktopAvailability locked/unlocked/unknown`；macOS 锁屏会退役计算机执行并释放 keep-awake（执行期间临时 keep-awake ≤1h）。
- **资源心跳**：`hostStats` 60s（CPU/load/mem/disk），存 `PairedDevice.nodeSurface.lastHostStats`，离线仍显示 last-known。
- **操作回放**：每个 computer 动作后自动跟随截图/`get_window_state` 观察（AFTER_ACTION_SCREENSHOT_DELAY_MS=500ms），结果附 `frameId/observationId` —— 这是 transcript 层的"刚才发生了什么"证据；截图 model-only，不进聊天频道。

---

## 5. 离线 / 重连

### 5.1 掉线瞬间（gateway 侧）

- `NodeRegistry.unregister(connId)`：删映射、`forgetNodeRunnerInventory`、清 desktopAvailability/plugin tools/remote skills、`invokeStreams.handleDisconnect(connId)` —— **该连接上的 pending invoke 全部以 `DISCONNECTED`（或 `MCP_SERVER_UNAVAILABLE`）立即 resolve**，不悬空等待；授权过的 system.run 事件窗口一并删除。
- 正在跑的 remote-exec/worker turn：transport 的每次 dispatch 都要过 `isCurrent`（connId/pairingGeneration/lease/ownerEpoch）。断连后下一个断言失败 → turn 失败。**但 placement 不回退**：`workspace-result-finalize.ts` L535-563 特判 `WorkerTunnelOwnerDisconnectedError` —— "Offline nodes keep their exact lease; the next turn reconciles its dirty workspace"（`cancelWorkspaceResultAndReleaseTurn(reason:'node-disconnect')`）。

### 5.2 掉线期间（placement 与数据）

- `docs/nodes/session-hosting.md` L248-284 权威描述：**offline 是 process-current 投影不是终态** —— placement 保持 `active`，`sessions.list/describe` 投影 `runner:{kind:'device', status:'offline'}`；Control UI 显示 **Device offline** 并默认等待（不放弃 placement/workspace/authority），设备回来后下一 turn 重试。
- **Continue on Gateway…** 是显式破坏性选项：fence 掉 device owner，从最后同步的 gateway workspace 继续，不同步的设备文件与 in-flight 工作会丢。
- 配对记录保留最后接受的 v6 hosting consent（离线行可见但 disabled）；**pairing 后 node 掉线 14 天**视为环境消亡，placement 正常清算；pairing 本身仍在，重连可再 provision。
- Gateway 重启：active device placement 显示 offline 直到 runner 重连（inventory current 后投影回 available 并发 session refresh）。
- 容器隔离模式：崩溃后 node-host 启动时按 durable engine/container 身份对账清理孤儿容器。

### 5.3 重连与排队任务

- **重连 reconcile**：`reconcileNodePairingOnConnect`（§1.3 第 2 步）——已批准面 ∩ 新声明 = 生效面；扩容才生成 pending 审批。重连不影响 pairing authority，只影响能力可见性。
- **排队工作队列**：`src/gateway/node-pending-work.ts` —— 每 node×pairingGeneration 一条内存队列（`status.request/location.request`，优先级 high/normal/default，TTL 默认 24h，同 type 去重）；node 重连后 `node.pending.drain`（≤10 条）拉取，`revision` 支持轮询感知变化；协议 `node.pending.enqueue` 带 `wake:true` 触发推送唤醒。
- **唤醒**：`src/gateway/node-wake-state.ts` —— APNs wake/nudge 按 node+generation 维护去重/节流状态（in-flight wake 合并、lastWakeAtMs 节流、nudge 节流），配 `node.invoke` 的 `invokeNodeWithReadinessRetry`（就绪重试）。
- **worker 生命周期**：turn 完成后 idle worker 保留 ≤2min/≤2 个可被复用；断连/停机/placement teardown 走正常进程树清理；`node-worker-status-wait-v1` 让 turn 终态由 node 主动唤醒等待方（旧版本退化为轮询）。**没有跨重连的"任务断点续跑"**：正在执行的 turn 随断连失败，排队的是 turn 级重试与 pending-work 提示，不是进程级迁移。

---

## 6. Atlas 落点建议

### 6.1 目标重述与映射判断

Atlas 目标："专用 Windows 笔记本就是 Atlas 自己的电脑"（真机、非 Linux 虚拟桌面），已有 X2 Windows Computer/Browser（`core/atlas/tools/x2/computer.py`：Hermes computer_use 桥 + 前台升级确认 + `computer.step` 回放；`core/atlas/tools/x2/browser.py`：browser_* + `browser_handoff` + HandoffBroker/pending.py；`core/atlas/capabilities/computer/{cua_backend,uia_backend}.py`）。

OpenClaw 值得抄的骨架与 Atlas 的差异：
- OpenClaw 的 `gateway computer` ≈ Atlas 的"Atlas-owned laptop"（同一台机器既是 gateway 又是受控桌面），对应其 `createGatewayComputerService` 的单执行独占 + generation fence + idle retire 模型，**直接可移植**。
- OpenClaw 的 `paired node` ≈ Atlas 的"主机/手机 ingress only"（只收消息、展示卡片，不当执行机）。**不要把 OpenClaw 的 worker-slot/session-hosting 整套搬来**；只需要 device registry + pairing + presence 的*投影*部分。
- `session-placement-computer.ts` 的 AsyncLocalStorage 绑定模式 ≈ Atlas 已有的 `X2Context`（contextvars）——**方向一致，把"绑定桌面"的权威断言加进去即可**，无需新机制。

### 6.2 Atlas device registry 建议字段与文件位置

新文件 `core/atlas/devices/registry.py`（数据 JSON 落 `data/devices/devices.json`，与现有 data/ 目录习惯一致；并发写用文件锁）。建议字段（对照 OpenClaw `PairedDevice`/`NodeSession` 精简）：

```jsonc
{
  "deviceId": "laptop-01",                 // 稳定 id；本机固定 "self"
  "kind": "atlas-laptop | ingress",        // laptop=可执行机；ingress=主机/手机只进不出
  "displayName": "Atlas 专用笔记本",
  "identity": { "publicKey": "...", "tokenHash": "..." },   // ingress 配对验签
  "roles": ["operator"],                   // laptop: ["computer"]（内置，不配对）
  "generation": 3,                         // pairing 撤销/扩权时 +1，旧连接作废
  "approvedSurface": { "tools": ["computer","browser"], "foreground": true },
  "presence": {
    "state": "online | offline",           // online = 心跳窗口内
    "lastSeenAtMs": 0, "lastSeenReason": "connect|heartbeat|manual",
    "activity": { "lastActiveAtMs": 0, "source": "app|system" },
    "desktop": "unlocked | locked | unknown"
  },
  "capabilities": {                        // laptop 自报（X2 探测）
    "computer": { "provider": "x2-hermes", "generation": "g1", "actions": [...] },
    "browser": { "mode": "standalone|copied|cdp|extension" }
  },
  "execution": { "maxConcurrentRuns": 1, "activeRunId": null },  // 单执行独占
  "createdAtMs": 0, "approvedAtMs": 0, "approvedVia": "owner|local"
}
```

判定规则照抄 OpenClaw：`online` = 存活连接/心跳新鲜（ingress 心跳 + 重连退避）；`available`（可执行）= `kind==atlas-laptop && online && desktop==unlocked && execution.activeRunId==null`；pairing generation 不匹配的连接一律 stale 丢弃。本机（laptop）无需配对，注册表里作为内置行，`approvedVia:"local"`。

### 6.3 placement 语义映射

- **不需要 OpenClaw 的 10 态 placement 状态机**（那是为云端 worker provision 设计的）。Atlas 只需 3 态：
  `local`（session 跑在服务进程，桌面工具经 X2 打到本机）→（暂不支持迁移）→ 无。ingress 设备永远不成为 placement 目标。
- 保留 OpenClaw 的两个关键不变量：
  1. **派发时绑定，执行期锁死**：run 启动时把 `deviceId="self"`（唯一可执行设备）写进 run 上下文；`computer`/`browser` 工具 handler 每次调用断言 `registry.available(deviceId) && run 仍 active`，否则报 `STALE_EXECUTION` 而不是静默换机（对齐 `resolveSessionPlacementComputer` 的三值语义：undefined=自由路由 / transport=绑定 / null=扣留）。
  2. **单执行独占 + 幂等**：`execution.activeRunId` 占用语义对齐 `COMPUTER_HOST_BUSY`；动作幂等键 `sha256(runId+toolCallId+action)`，已 settled 的键要求"先观察再新动作"。
- 桌面锁定（locked）时不启动新的前台/后台输入执行；正在跑的执行在锁屏时退役（对齐 macOS keep-awake/locked 语义），解锁后需新执行。

### 6.4 takeover UX 需要的后端 API 清单

现有基础：`X2Context.emit_event`（runtime events 流）、`pending.py` HandoffBroker、`POST /api/computer/foreground`、`POST /api/browser/handoff`。建议新增/扩展（前缀 `/api/desktop`）：

| API | 语义（对应 OpenClaw 实现） |
|---|---|
| `GET /api/desktop/state` | `{deviceId, desktopAvailability, controller: 'agent'|'human'|null, activeRunId, lastStepEvent}`（= registry + session-registry 投影） |
| `POST /api/desktop/take_control` | 人接管：置 controller=human，abort 该 run 所有 in-flight input（computer-transport L581-594 语义），广播 `desktop.control_changed{controller:'human'}`；已被 abort 的工具调用收到"operator has control"错误 |
| `POST /api/desktop/release_control` | 人放手：controller=null；agent 侧置 `needs_observation=true`，下一个动作先强制截图 |
| `POST /api/desktop/agent_take_control` | 对应 agent `take_control` action（也可由模型工具触发）：逐出 human controller，同上 needs_observation |
| `WS /api/desktop/stream` | 截图/回放流（观察在 takeover 期间不中断，对齐"agent 仍能看"） |
| `GET /api/devices` / `POST /api/devices/:id/rename` / `DELETE /api/devices/:id` | registry CRUD + 撤销（撤销=generation+1 + 踢连接） |
| `GET /api/devices/:id/presence` | lastSeen/activity/desktop 投影（"活动指示"数据源） |
| `POST /api/computer/foreground`（已有，保留） | 前台升级确认（≈ OpenClaw 的 escalate 审批位） |

事件流新增（对齐 `X2Context` 事件命名风格）：`desktop.control_changed`、`desktop.execution_retired{reason}`、`device.presence_changed`。

### 6.5 handoff 状态机（建议）

```
桌面控制权（每台 laptop 一个槽位）:
  FREE ──human open panel(control)──► HUMAN
  AGENT ──human take_control────────► HUMAN   (abort in-flight input; needs_observation=true)
  HUMAN ──agent take_control────────► AGENT   (human 收 control-taken; needs_observation=true)
  HUMAN ──release───────────────────► FREE
  AGENT ──release/run end───────────► FREE   (execution retired, reason 记录)
  任何态 ──desktop locked───────────► RETIRED (执行退役; 解锁后从 FREE 重开)

人类 handoff 卡片（browser_handoff / foreground，沿用 pending.py）:
  PENDING ──open_panel──► (浏览器面板 + 桌面控制权转 HUMAN)
  PENDING ──done────────► 解除阻塞，回 AGENT（needs_observation=true）
  PENDING ──give_up / timeout / run cancel──► 工具调用以 give_up 解缠（现状已实现）
```

关键不变量（全部来自 OpenClaw 实测语义）：(1) 普通输入永不自动接管；(2) 被打断的动作不重放；(3) 控制权任何变更后第一次坐标类动作前必须新截图；(4) 观察永远不被 takeover 阻断；(5) 撤销/换代后旧连接与旧执行全部 stale，不回退到别的机器。

### 6.6 不建议照搬的部分

- worker-slot / idle-retention / sealed bundle 传输 / workspace manifest reconcile：为远程算力设计，Atlas 单机直跑用不上。
- 14 天 dormancy、APNs wake、pending-work 队列：ingress 手机若在线即收消息、离线走既有推送渠道即可；等 Atlas 出现第二台可执行机再引入 `device-placement-selector` 的 Auto 排序（负载比 → 空闲 slot → id）。
- OpenClaw 的四路由 computer binding（gateway/attached/placed/paired）：Atlas 收敛为两路由（本机 X2、未来第二台 laptop），接口层保留 `resolve_binding(deviceId?)` 形状即可平滑扩展。
