# 实现机制与端到端调用链（固定源码 687f282e / 0.2.1-rc.2）

版本语义必须分清：后续各章节原仓库 `packages/.../src` 锚点属于固定源码 `687f282e` / `0.2.1-rc.2` 的 **S 级静态证据**；另在本轮从 CLI manifest 实际安装并读了同版本 `0.2.0-rc.2` npm runtime packages（证据文件 `extracted/published-runtime-packages.json`），这部分是发布编译 JS 静态证据。仅 CLI `--version`、`--help` 动态运行成功；没有启动 profile、Agent、服务器或模型。不得把 source 的机制自动等同到旧发布包。

## 0. 实际 CLI/Web 发行物的边界（新增 S）

三包已从 Atlas 固定 release 下载、按全 SHA 校验并解包；逐包元数据见 `extracted/manifest-verified.json`。此处把实物入口与较新的源码追踪分开：

- 发布 `@deepseek-ai/dsh@0.2.0-rc.2` 的 `extracted/cli/bin.js` 真实包含 `parseDshArgs → resolveBoot → runCli`。launcher 解析 `--profile`、profile template、patch 与配置 dump；第一个未识别 token 开始交给 profile app；`plugin` 调用 `runPlugin`。启动 profile 时加载外部 `@deepseek-ai/dsh-app-boot`、Home paths，再动态 import `profile-boot.js`；发生 `StartupError` 时生成 `$DSH_HOME/logs/startup-*.log`，并警告原始诊断可能含配置或凭据值。它是 launcher 机制证据，不是 Agent loop 证据。
- 发布 CLI manifest 有 82 个 direct dependencies；该 tar 仅带自身 `lib/*` 与 declarations。现已以这份 tar 为 root 执行 `npm install --ignore-scripts`，package-lock registry integrity 固定的旧版 `dsh-agent-loop`, `dsh-session`, `dsh-session-persistence-jsonl`, `dsh-api-session-controller`, `dsh-subagent`, `dsh-web-app`, `dsh-client-ui-*` 包均为 `0.2.0-rc.2`。旧版发布 Agent 路径直接核对已装编译 JS：`dsh-agent-loop/lib/index.js:936-1118` 为 turn/step、tool recovery 与 stream commit；`dsh-session/lib/index.js:801-850,1441-1479,1832-1849` 有 tool-call conservative recovery、append/flush；`dsh-session-persistence-jsonl/lib/index.js:116-171,624-660,2372-2410` 有 append/flush、writer lease 与 JSONL handle；`dsh-api-session-controller/lib/index.js:2578-2600,3091-3184` 注册 prompt/page/follow/projections/control RPC；`dsh-subagent/lib/index.js:961-1100,1754-1917` 覆盖 child create/resume 与冷恢复。这填补了此前“旧引擎包未取得”的证据空缺，但仍是静态编译包审读，尚非动态 profile/Agent 行为验收。
- 同版 Web 宿主 `dsh-web-app/lib/index.js` 明确是 Cordis glue plugin，解析 bundled frontend dist、挂载 frontend-static owner、注册 host prompt/runtime URL/browser handoff；同版 `dsh-client-ui-subagent`, `...-jobs`, `...-trajectory` 的 npm 包及完整性的 registry records 均出现在安装依赖图/lock 中。它证明这些 UI 包依赖随安装图可用，**不单独证明特定默认 profile 的确 mount 或某页面实际显示**。旧 CLI 实际依赖集合均为 `0.2.0-rc.2`；源码 ZIP 是 `0.2.1-rc.2` 且所列 73 个同名包仍不同版本，不能替代逐行 diff。旧 standalone Web `0.0.1-rc.5` 仍与此宿主中 frontend `0.2.0-rc.2` 属不同包版本，尚无 build identity 证明等价。
- 发布 Web `0.0.1-rc.5` 的实物入口 `extracted/web/index.html` 是 Vite static SPA：mount `#root`，载入 `index-DYtepzMn.js`、`vendor-Cjbwl5VI.js` 与两份 CSS。dist 有 86 个 asset、25 个 JS、零 `.map`；分析索引 `web-assets-map.json` / `web-chunk-symbols.jsonl` 已覆盖包内静态资源。REA 解析 Web app 目录 25 个 JS、3,448,159 text bytes，但主 entry 在 semantic 阶段耗尽分析 heap，图为 partial。未启动本包，没有运行时路由/API/RPC 观察。
- Web 包 manifest 是 `0.0.1-rc.5`、BSD-3-Clause；source `apps/web` 是 `0.2.1-rc.2`、MIT。旧 Web bundle 无 sourcemap，故新源码子代理组件等不能一一归给旧 Web build。关键词命中不等于功能：entry 只出现通用 `session` 和 `prompt` 文字；vendor/editor 中的 `interrupt` / `job` 命中是 parser 结构上下文，不支持 DSH Agent 功能结论。没有目标字符串也不能证明功能缺失。

## 1. 顶层构件和依赖边界

```text
apps/cli/src/bin.ts -> parseDshArgs -> boot profile (Cordis 插件树)
                                            |
        +-----------------------------------+-------------------------+
        |                                     |                       |
 @deepseek-ai/dsh-agent-loop           @deepseek-ai/dsh-subagent     API Gateway / Typert
 ReactLoopAgent -> LLM, tools,         SubagentManager / providers   Remote mux
 session events / projections          child session + lifecycle      /api/remote.mux
        |                                     |                       |
        +-----> session persistence JSONL <--+---- session controller + client
                    |                                                |
          durable seq / format migration                      Web Chat / Trajectory
          write lock / repair                            Subagent tree / right sidebar
```

插件不是简单的可选 UI 包：`@deepseek-ai/cordis` 的 Context 服务注入、scoped effect 注册及撤销贯穿 `agent-loop`、`tools`、`subagents`、`mcp-client`、`session-controller`。CLI launcher 本身只持 profile/patch/config/plugin 管理，具体用户命令属于启动的树：`apps/cli/src/args.ts:1-14,143-210`；`apps/cli/src/bin.ts:26-79`。这为同一个引擎在不同前端复用提供实现基础，但具体打包组合仍属 U。

## 2. 单 Agent 的 Turn / Step / attempt 有序事件链 — DSH_CORE-001..006

调用链：
1. `ReactLoopAgent.followup` → `send('next-turn', wakeup=true)`，中途人为改方向走 `steer('next-step')`；`ReactLoopInbox.splice` 以 `agent/inbox/spliced` 的事件投影维护两级输入。定位：`packages/core/agent-loop/src/agent.ts:154-173`；`inbox.ts:20-55`。
2. `wakeDriver()` 领取 Agent 运行状态和 AbortController，`kick()` 串行 `while(await turn())`。定位：`agent.ts:214-265`。
3. `turn()` `session.append('turn/start')` → `preStep` 合并 next-turn/next-step → `step/start` → `step()` → `step/end` → `turn/end`。错误情况 `ToolCallRecovery` 先为已发出而未结束的工具补失效结果，保证 replay 时不留下孤儿工具调用；终局的 `blocked/max-tokens/error/aborted/completed` 分别记录。定位：`agent.ts:298-395`。
4. 每次请求 `prepareRequest` 用 `agent/request` waterfall 让插件决定 provider/model/effort，再 `llm.prepareCall`；`buildRequest()` 写 `request/header`（`initial|resume|change|series`）、必要 `request/context`，工具 schema 新增/移除写 `developer/message`。定位：`agent.ts:563-684`。
5. `AssistantStreamAttempt.start/push/settle`：在临时流里按 attemptId + revision + index 发 `start/chunk/end`；只有 `session.append('assistant/message'|'assistant/attempt')` 成功时 `end` 才带 committed seq，提交失败用 abandoned。定位：`assistant-stream.ts:18-107`；`agent.ts:443-555`。
6. `finish.kind === error|aborted` 的 attempt 先写 `assistant/attempt`，`agent/request-error` 插件 waterfall 可以决定 retry；非 retry 抛 `LlmError`。这和整个 Agent run 被错误终结是两级不同边界。定位：`agent.ts:504-526`。

**关键时序：**每次 LLM stream 是一次 attempt；同个 step 中可以因请求错误再次 attempt；step 中模型产生 tool-calls 时再调度各工具；工具结果写入 `next-step` 供下一请求，不假设所有工具调用都能安全并行。不能用 assistant token delta 代替完整 durable event log。

## 3. Tool scheduler：并行执行、串行承认 — DSH_CORE-005

`executeToolCalls` 对同一模型 response 产生的工具数组 `planned` 保留 **模型原始顺序**；首次分类 `ctx.tools.executionMode(...).kind` 是 `parallel` 或互斥。 `runGroup` 在 `maxParallelToolCalls` 容量内滚动启动 `prepare → dispatch`，遇后续工具动态变成 exclusive 则停止填槽，等当前 pool 清空后形成新 barrier。结果先进入对应 index 的 `slots`，但 `commitReady` 只从最早未提交 slot 执行 `finalize/finish → appendToolResult → additionalContexts`，后来的工具先完成不能抢先改变模型所见结果顺序。定位：`packages/core/agent-loop/src/tool-calls.ts:60-100,122-160,163-246`。

取消：停止补充，等待已启动 dispatch settle，剩余未派发的工具写 `tool/call` + 合成的 `tool/result`（`TOOL_ABORTED_BEFORE_DISPATCH`），避免事件缺口。异常：drain 之后上抛，让 Agent step 做保守修复。见 `tool-calls.ts:232-286`、`agent.ts:333-358`。

## 4. 子代理运行与持久地址：控制平面 vs Residency — DSH_CORE-007..012

```text
父 Agent 生成 subagent tool_call
  -> tool-subagent.apply() 的动态 tool 定义
  -> ctx.subagents.startActivation({provider,label,request,delivery:'parent'})
  -> SubagentManager.startLocal / startExternal
  -> reserve root ActivationPool、snapshot depth/route/policy、materialize
  -> child Session durable descriptor / parent session lineage
  -> parent 收到 child id，child 自行执行
  -> subagent/start (runId + childId + provider) -> child agent status/inbox
  -> child durable Session 真实 turn/end -> captureLocalResult / epochStopReason
  -> subagent/end（stopReason / final output） + result delivery/disposal
```

关键入口：`packages/subagent/tool-subagent/src/index.ts:193-220,319-379`；`packages/subagent/subagent/src/manager.ts:129-179,373-465,483-515,739-763,930-964`；`lifecycle.ts:63-114,118-170`。

- `resident: Map<SessionId, Activation>` **只存在进程内**；`childId`、父子关系和 descriptor 保存在独立 Session。child 创建前若失败回滚资源，不“报一个不存在的 id”。`ChildLock.run` 以 child id 线性化投递与清理，避免同一孩子同时恢复两份。地址、具体 parent 归属用 durable header/目录而非 UI 当前树推断。
- `sendMessage(sender,targetId,...)` 只允许确切存活的直接父/子成员；可以发给 direct parent，也可以向 continuable child 送 steer。未 resident 的 direct child 可通过持久化 cold-resume。人类入口 `queuePrompt` 送 next turn，`steerPrompt` 送 next step；二者都在 `deliver` 闭锁后 `followup/steer`。定位：`manager.ts:533-628,707-730`。
- 独立 `send_message` 与 `interrupt_agent` 是薄工具适配器：仅返回 messageId / accepted，interrupt 是请求，不保证子进程立即停止，也**不默认终止其后代**。定位：`tool-subagent-control/src/index.ts:27-111`。
- 子代理 parent route 继承来自当前 `session.requestHeader()`，不是总沿创建时配置；在改 model 而未明确 effort 时清掉父的 reasoning effort；保留 depth 跨 resume。定位：`child-agent.ts:49-118,135-160`。
- local continuable 与 external one-shot 不能混为一谈；后者没有 parent enforce 的同样能力，也不接受后续消息。定位：`subagent/src/out-of-process.ts:1-53`。
- 更高层 `packages/experimental/agent-team/src/index.ts` 的 `TeamService`（experimental）在上述子代理基本原语上增加 roster、Lead Session journal、task DAG、有 revision 的 CAS 任务转移、peer 消息和 change wait。见 `task-board.ts:28-255`、`journal.ts:55-70`。**尚未证明发布 profile 默认启用实验 Team。**

## 5. Browser 操作到 Host API：子 Session 的真实可观察性 — DSH_CORE-012..015,022

```text
SubagentHeaderLineage catalog (parent subagentCatalog projection)
  -> openChild({parentSessionId,childSessionId,mode})
  -> ClientSessions.resolveTarget + 子 Session history page/follow
  -> Contextual Chat / Trajectory (durable event + transient chunks)
  -> 用户继续输入:
       普通 Session -> remote.session.prompt
       child mode=continuable -> remote.subagents.prompt
  -> Subagent service 校验 parent/child/mode 与权限
  -> SubagentManager.queuePrompt/steerPrompt -> child inbox -> ReactLoopAgent
  -> session event/projection -> control stream -> UI running/read-only/retry
```

UI 点击：`packages/client/ui-subagent/src/client/index.ts:52-101`，可导航主对话或 `ctx.sidebarRight.openResource(subagentChatAddress(...))` 打开并列嵌入会话；地址编码和恢复见 `sidebar-chat/index.tsx:18-21,47-82,129-201`。客户端投递具体路由：`packages/api/session-controller/src/client/sessions/session.ts:240-357`；服务端 `packages/subagent/subagent/src/index.ts:436-527`。

Host Session RPC：`packages/api/session-controller/src/index.ts:118-176,524-603` 的 `page/follow/projections/control`；`history.ts:120-220` 的 cold page 后继续 live follow；`control.ts:17-79` 投影基线与增量。浏览器临时流 `assistant/live-chunk`、正式 `SessionEvent` 在 `client/contract/events.ts:6-35,97-120` 由版本化 event-window 聚合。可观测层 `client/ui-trajectory/src/client/TrajectoryView.tsx`、`TrajectoryTable.tsx` 展示 request diff、retry、token、tool call 等，既可读已持久化事件，也可读当前临时流。界面视觉动态未做实测。

## 6. Remote 协议和断线行为 — DSH_CORE-015

`packages/api/gateway/src/stream-protocol.ts:6-19` 明确一条 WebSocket `/api/remote.mux` 多路逻辑 Typert Remote stream；每条逻辑流 `streamId`、open/item/end/错误与 cancellation；`stream-server.ts:44-127` 管连接、ping/pong heartbeat 与终止；`client/stream-client.ts:52-105,241-380` 管物理 carrier / 等待 reconnect / multiplex。

**重要区别：**当前 socket 断开时 `lost()` 会 `failAll` 现有流，随后 Client Connection 可发起新连接；这不等于“原 stream iterator 自动从断点继续”。后续由 Domain 的 Session `follow` 基线/cursor 机制重新定位事件；需要实际浏览器断线 E2E 确认不遗漏/重复。

## 7. Session 事件持久化：不可把 UI 状态当真源 — DSH_CORE-016

`packages/session/session-persistence-jsonl/src/storage.ts` ：`JsonlSessionHandle.append` 在排队前验证并固定 batch；已运行 Session live events 走 write-behind buffer（最大有意批延时 **200ms**，`storage.ts:35-36,270-289`），`flush/close` drain，失败的 buffer 保留后续重试；append 前校验 seq 连续性，并修复 torn physical tail。`session-persistence-jsonl/src/lease.ts:1-28` 说明跨进程 **POSIX flock / Windows named kernel semaphore** 的排它写持有期，进程死亡由 OS 释放，不用“TTL 超时抢锁”；`format.ts:1-43,308-323` 序列化事件、支持 none/zstd、版本格式链。这里的持久化有明确时序，200ms write-behind 在硬掉电时是否全部安全必须以 flush 边界区分。

## 8. Token / Context / Compaction — DSH_CORE-017..018

`packages/llm/token-meter/src/turn-usage.ts:12-35,81-139,170-275` 从已提交的 assistant/message、assistant/attempt 与 retry lifecycle 计算 token usage，仅当完整一致的提供商事实成立时返回 exact；可辨识 cache-read、cache-write、reasoning tokens、total 与路由。分辨模型输出用量和客户端估计 `estimate.ts`、`route-pricing.ts:32-74`，不能把上下文占用估算当账单。

`packages/compaction/compaction-basic/src/index.ts:148-233,267-310` 由 pre-step / context overflow request error 触发压缩和重试；`summarizer.ts:110-179` 通过前缀重放摘要请求提高缓存复用。`compaction-tool-result-pruner/src/index.ts:128-170` 的工具结果无模型裁剪会写 shadow-price 事件及替代 tool/result，历史计算可说明“哪里被缩过”。遇 compaction 失败时可由 plugin policy 延续或报错，不等于忽略故障。

## 9. 其他主动发现的独立服务

- `packages/api/job-controller/src/index.ts:1-8,75-115`：后台 job 运行列表、非消费式按 offset follow 输出、human kill（与模型消费 cursor 分离）；`jobs/jobs-local/src/pump.ts` 截断/spill 行为。**Job 与子代理是不同对象，不要用 jobs 的状态冒充 child tree。**
- `packages/mcp/mcp-client/src/index.ts:1-14,154-192` + `tools.ts:81-158`：MCP stdio/HTTP，server-qualified tool 名，list change 重新同步，effect dispose 取消与卸载，而不是一开始发现一次后永久保留陈旧列表。
- `packages/schedule/schedule/src/index.ts:90-118`：持久提醒；`goal/goal-round-driver/src/index.ts:173-255`：自动轮次与子代理等待；`ptc-runtime/ptc-runtime-node/src/index.ts:36-105,186-240`：可隔离子进程执行代码或 owner-scope retained REPL。均需验证发布 profile 装配。

## 10. Profile 装配、模块解析和进程边界（主动新增）

Profile 并非一份全局配置文件，而是有序模块/patch 装配：`apps/cli/src/profile-boot.ts:202-245,306-337` 先读 `dsh.profile.bundles` 所指 bundle patch，再加 profile user patch、home-wide `$DSH_HOME/cordis.patch.yml`、按 argv 顺序的 `--patch` overlays，最后合成 telemetry switch；生成的 `ProfileRuntimeResolution` 在 plugins import 前一次计算。`packages/boot/app-boot/src/profile.ts:179-237,740-840` 定义 `acp/web/headless/sdk/sdk-minimal` shipped templates 与 optional bundles；default template 未显式初始化则首次 `loadProfile` 会建立目录和 bundle list。

Module resolver 为 bundle/plugin 维护 installation 与 profile 两个 anchor；安装包依赖先从安装位置解析，profile 自己的 npm 包从 profile node_modules 进入 resolver table，再由 Node ESM/CJS loader 拦截层按归属解析。源码把无法读/不兼容 bundle 记入 `skippedBundles` 并启动时逐个报告；profile manifest 与用户 patch 解析错误继续 fail startup。证据：`packages/boot/app-boot/src/profile.ts:89-120,492-565,740-840`、`profile-resolution/resolver.ts:86-120`。

另一个发现是 Host 在 mount 任何插件之前取 immutable launch-environment snapshot，通过它安装 HTTP proxy；这解决 Node `fetch` 不自动遵循 `.env` 代理的差异。`SIGTERM` 和 `SIGINT` 在整个 startup window 注册，对 boot fiber + proxy 共用一个 coalesced disposer，分别记退出码 0/130；重复信号会升级退出，最长给清理 5 秒。见 `apps/cli/src/profile-boot.ts:271-341`、`process-shutdown.ts:1-72`。这些是新源码的源码级控制机制，尚未在包上触发信号、切换代理或制造损坏 profile；旧 npm runtime 等价性仍 U。

## 未闭合链路

## G2 continuation: UI to addressed child (S, newer source)

ConversationService submit calls the selected Session wrapper. Session.prompt chooses session.prompt for a root address or subagents.prompt for a continuable addressed child; Session.updateQueue invokes the queue RPC. The host SessionController exposes the prompt/updateQueue remotes and SessionCommands applies queue/Agent ownership rules. Child stop uses subagents.interruptByParent. Child navigation resolves a real child Session then uses page/follow/control. See SURFACE-MAP.tsv for source anchors and END-TO-END-TRACES.md for state effects and limits. These are newer-source static traces; the shipped Web npm is an older non-mapped bundle and has not yet been interactively run.

Session-controller test source explicitly rejects generic cancel/updateQueue/model selection/create against runtime-owned child Sessions with session/agent-busy, while addressed child control uses parent-addressed subagent RPC. This is a separate discovery, DSH_CORE-036; dynamic execution is pending.

CLI 0.2.0 与源码根 0.2.1 的实际 diff、Web UI 0.0.1-rc.5 构建中是否有上述 UI、production profile 默认插件矩阵、各源码 plugin 的运行状态、进程重启时挂起 model/tool/subagent 真实恢复、浏览器协议抓包：**U，补采见 EXTRACTION-REQUEST.md**。
