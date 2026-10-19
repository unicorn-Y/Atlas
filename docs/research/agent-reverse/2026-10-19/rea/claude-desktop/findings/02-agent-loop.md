# 02 · Agent Loop 与工具系统

> 证据等级：**S**=源码直接可见，**R**=运行时观测，**D**=官方文档，**I**=推断，**U**=不可获得
> 主要证据文件：`index.chunk-DNyequwM.js`（1,224,866 B）、`index.chunk-Bn6onBlX.js`（2,106,696 B）

---

## 1. 最重要的一个判断：Agent Loop 不在桌面端

这是整个逆向里最关键的结构性发现，也是很多分析会搞错的地方。

桌面端**没有实现** agent loop。它做的是：

1. 把 Claude Code CLI（或内置引擎）作为**子进程**拉起；
2. 通过 **stdio 上的 stream-json 协议**双向通信；
3. 把权限决策、hook 执行、UI 渲染拉回宿主侧。

也就是说，`while (stop_reason === "tool_use") { ... }` 这个循环发生在**子进程**里，桌面端是"客户端"。

证据（S）：

```js
// index.chunk-DNyequwM.js @11314720
l.CLAUDE_CODE_ENTRYPOINT ||= "sdk-ts";
delete l.NODE_OPTIONS;
Ho(l.DEBUG_CLAUDE_AGENT_SDK) ? l.DEBUG = "1" : delete l.DEBUG;

let pe = Twe(c), me = pe ? c : a, he = pe ? [...o, ...w] : [...o, c, ...w],
    T = { command: me, args: he, cwd: i, env: l, signal: this.forwardedAbort.signal };

this.options.spawnClaudeCodeProcess
  ? (B$(`Spawning Claude Code (custom): ${me} ${he.join(" ")}`),
     this.process = this.options.spawnClaudeCodeProcess(T))
  : (B$(`Spawning Claude Code: ${me} ${he.join(" ")}`),
     this.process = this.spawnLocalProcess(T));

this.processStdin  = this.process.stdin;
this.processStdout = this.process.stdout;
```

`CLAUDE_CODE_ENTRYPOINT = "sdk-ts"` 是给**引擎侧**看的埋点标记——引擎据此知道自己是被 SDK 拉起的，而不是终端直接运行。

---

## 2. 完整命令行参数构建（S，逐条）

`index.chunk-DNyequwM.js` @1131100–1134600 是完整的 argv 构造器。**基础参数**：

```
--output-format stream-json
--verbose
--input-format  stream-json
```

这三个决定了通信协议：**双向 NDJSON over stdio**。

**条件参数**（按代码顺序）：

| 触发条件 | 追加参数 | 说明 |
|---|---|---|
| `thinking.type === "enabled"` 且无 budget | `--thinking=adaptive` | 自适应思考 |
| `thinking.type === "enabled"` 且有 budget | `--max-thinking-tokens <n>` | 显式预算 |
| `thinking.type === "disabled"` | `--thinking=disabled` | — |
| `thinking.type === "adaptive"` | `--thinking=adaptive` | — |
| `thinking.display` 且非 disabled | `--thinking-display <mode>` | 思考过程是否展示 |
| `effort` | `--effort <level>` | — |
| `maxTurns` | `--max-turns <n>` | loop 上限 |
| `maxBudgetUsd` | `--max-budget-usd <n>` | 成本上限 |
| `taskBudget` | `--task-budget <n>` | — |
| `model` | `--model <m>` | — |
| `agent` | `--agent <name>` | **子代理** |
| `betas` | `--betas a,b,c` | 灰度开关 |
| `jsonSchema` | `--json-schema <json>` | 结构化输出 |
| `debugFile` | `--debug-file <p>` | — |
| `debug` | `--debug` | — |
| `canUseTool` 回调存在 | `--permission-prompt-tool=stdio` | **权限回宿主** |
| `permissionPromptToolName` | `--permission-prompt-tool <name>` | — |
| `permissionPrompts` | `--permission-prompts <v>` | — |
| `continueConversation` | `--continue` | — |
| `resume` | `--resume <id>` | — |
| `channels[]` | `--channels <c>`（可重复） | — |
| `allowedTools[]` | `--allowedTools a,b` | — |
| `disallowedTools[]` | `--disallowedTools a,b` | — |
| `tools` 数组 | `--tools a,b` | — |
| `tools === true` | `--tools=default` | — |
| `mcpServers` 非空 | `--mcp-config <json>` | 内联 JSON |
| `settingSources[]` | `--setting-sources a,b` | — |
| `strictMcpConfig` | `--strict-mcp-config` | — |
| `permissionMode` | `--permission-mode <m>` | — |
| `bypassPermissions` | `--allow-dangerously-skip-permissions` | ⚠ 高危 |
| `fallbackModel` | `--fallback-model <m>` | 与主模型相同则**抛错** |
| `includeHookEvents` | `--include-hook-events` | — |
| `includePartialMessages` | `--include-partial-messages` | 流式增量 |
| `sessionMirror` | `--session-mirror` | — |
| `projectConfigRoot` | `--project-config-root <p>` | — |
| `additionalDirectories[]` | `--add-dir <p>`（可重复） | — |
| `pluginsViaInitialize` | `--await-initialize` | — |
| 本地 plugin 且 skipMcpDiscovery | `--plugin-dir-no-mcp <p>` | — |
| 本地 plugin | `--plugin-dir <p>` | — |
| 非 local plugin | **抛错** `Unsupported plugin type: ${type}` | — |
| `forkSession` | `--fork-session` | — |
| `resumeSessionAt` | `--resume-session-at <id>` | — |
| `resumeDropsTurn` | `--resume-drops-turn <n>` | — |
| `sessionId` | `--session-id <id>` | — |
| `persistSession === false` | `--no-session-persistence` | — |
| `managedSettings` | `--managed-settings <v>` | 企业策略 |

另外 `settings` 对象会被展开：**值为 `null` 的键输出为 `--<key>` 布尔开关**，否则 `--<key> <value>`。

**Skill 的特殊处理**（S）：

```js
if (skills !== undefined) {
  let e = skills === "all" ? ["Skill"] : skills.map(s => `Skill(${Cwe(s)})`);
  let t = new Set(allowedTools);
  allowedTools = [...allowedTools, ...e.filter(x => !t.has(x))];
}
```

即 `skills: "all"` → 在 `--allowedTools` 里塞入 `"Skill"`；具体列表 → 塞入 `Skill(<name>)`。这是 Skill 授权的真实机制。

---

## 3. 进程生命周期与失败归因（S）

`ProcessTransport` 类（`index.chunk-DNyequwM.js`）对每种子进程结局都有独立的错误分类，会进 telemetry：

| 情形 | `errorClass` | 错误文案 |
|---|---|---|
| spawn 失败（syscall 以 `spawn` 开头） | `spawn_failed` | `Failed to spawn Claude Code process: …` |
| 其他进程错误 | `process_error` | `Claude Code process error…` |
| 退出码非 0 | `process_exited_nonzero` | `Claude Code process exited with code N. stderr: …` |
| 被信号杀死 | `process_killed_by_signal` | `Claude Code process terminated by signal SIGxxx. stderr: …` |
| 用户中止 | `aborted` | `Claude Code process aborted by user` |

`formatStderrTail()` 会把 stderr 尾部拼进错误消息——这是**唯一**能把引擎侧错误带回 UI 的通道。

stdin 写入失败时：`[ProcessTransport] stdin write failed (child likely exited): ${code}`，并置 `ready = false`。

---

## 4. hook 事件全集（S，最关键的一张表）

`index.chunk-Bn6onBlX.js` @62126 有一个 `new Set("…".split("."))`，是**产品支持的 35 个 hook 事件**：

```
PreToolUse        PostToolUse       PostToolUseFailure  PostToolBatch
Notification      UserPromptSubmit  UserPromptExpansion SessionStart
SessionEnd        Stop              StopFailure         SubagentStart
SubagentStop      PreCompact        PostCompact         PreModelSwitch
PostModelSwitch   PermissionRequest PermissionDenied    Setup
TeammateIdle      TaskCreated       TaskCompleted       Elicitation
ElicitationResult ConfigChange      WorktreeCreate      WorktreeRemove
InstructionsLoaded CwdChanged       FileChanged         DirectoryAdded
MessageDisplay
```

这比公开文档里列出的 hook 多得多（`PostToolBatch`、`PreModelSwitch`、`TeammateIdle`、`Elicitation`、`FileChanged`、`DirectoryAdded` 等都不在常规文档里）。

hook 返回值的形状（S）：

```js
{ hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "allow" | "deny",
    permissionDecisionReason: <string>,
    updatedInput: <object>        // 可以改写工具入参
} }
```

**`updatedInput` 是重点**：hook 能在工具执行前改写参数。这是权限系统之外的第二条控制路径。

同一位置还有另一组状态枚举：

- `init.status.api_retry.compact_boundary.hook_started.hook_progress.hook_response.informational.local_command_output.notification.task_started.task_progress.task_updated.task_notification.background_tasks_changed.commands_changed.session_state_changed.thinking_tokens.control_request_progress.memory_recall.mirror_error.model_refusal_fallback.model_refusal_no_fallback.permission_denied.plugin_install.files_persisted.elicitation_complete.worker_shutting_down` — **28 种流内事件**
- `success / error_during_execution / error_max_turns / error_max_budget_usd / error_max_structured_output_retries` — **5 种终止原因**
- `requesting / compacting` — 忙碌子状态
- `idle / running / requires_action` — 会话状态
- `completed / failed / stopped` — 后台任务终态
- `pending / running / completed / failed / killed / paused` — 后台任务全集

---

## 5. 工具清单（S）

两处独立证据互相印证。

**广播给 UI 的工具名**（`index.chunk-lzaSYO3Q.js` @121617）：

```
AskUserQuestion Bash BashOutput Edit ExitPlanMode Glob Grep JavaScript
KillBash MultiEdit NotebookEdit Read REPL SendUserMessage Skill Task
TaskCreate TaskGet TaskList TaskStop TaskUpdate Tmux TodoWrite ToolSearch
WebFetch WebSearch Workflow Write unknown
```

**工具实现的引用位置**（`index.chunk-Bn6onBlX.js`）：Glob 7、ExitPlanMode 7、Read 5、Edit 5、Grep 5、Workflow 4、Bash 3、MultiEdit 2、Write 2、Skill 2、NotebookEdit 1、Task 1、Agent 1、AskUserQuestion 1。

两份清单的差集就是"UI 认识但桌面端不直接处理"的工具（`Tmux`、`REPL`、`SendUserMessage`、`ToolSearch`、`JavaScript`）——它们由引擎侧实现。

`Workflow` 工具值得单独提：权限逻辑里有一句 `"Review the first dynamic workflow before auto-approving."`（S），说明 **Workflow 是动态生成的**，第一次必须人工审核。

---

## 6. 权限决策：ToolPermissionBroker

`index.chunk-Bn6onBlX.js` @249439 起的 `ToolPermissionBroker` 是桌面端最复杂的单个类。

### 6.1 决策分支

```js
switch (decision) {
  case "once":      ...
  case "always":    ...
  case "scheduled": ...
  case "deny":      ...
  default: return { behavior: "deny", message: "Unknown decision" };
}
```

### 6.2 返回结构

```js
{
  behavior: "allow" | "deny",
  updatedInput: {...},
  updatedPermissions: [...],
  decisionClassification: "user_reject" | "user_temporary" | "user_permanent",
  ...(approvalSurface && { approvalSurface: "host_dialog" })
}
```

三种 `decisionClassification` 对应三档记忆：拒绝、本次允许、永久允许。

### 6.3 权限记忆的落地形式

```js
updatedPermissions: [{ type: "setMode", mode: <m>, destination: "session" }]
```

即"永久允许"被建模成**写一条 setMode，目标作用域 session**——不是单独的允许列表。

### 6.4 拒绝文案（S）

- 目录访问：`"User rejected the directory access request"`
- 工具调用：`` `User rejected ${formatToolName(toolName)} ${target}` ``

### 6.5 内部协作方法（全部 S）

`withProjectConfigFence` `zl` `Ul` `tf` `zd` `gu` `n.ks` `n.gl` `n.Tt(mode, "ToolPermissionBroker setMode")` `n.Qf` `n.$f` `t.wT` `ts.includes(toolName)` `s.viaHostCliLauncher`

其中几个语义可从上下文确定：

- `viaHostCliLauncher` — 区分"引擎是宿主 CLI 拉起的"还是"桌面端拉起的"，两种情况权限判定不同。
- `withProjectConfigFence` — 项目配置栅栏，防止项目级配置越权覆盖用户级。
- `notePlanAnswered` / `rememberSshHostToolGrant` / `onWriteScopeGranted` — 三类独立的授权记忆。
- `renewArchiveConsent` / `voidArchiveConsent` — **归档同意可以续期和作废**，说明归档是有时效的授权。
- `accumulateSessionPermissionUpdates` — 会话内权限增量累积。

### 6.6 委托判定（S）

```js
delegatedAsk(e, t, n) {
  if (!(this.turnIsDelegated(n) || !await hd(...))) return this.config.turnDelegation?.(n);
}
turnIsDelegated(e) {
  let t = this.config.getSession(e);
  return Wu() && t !== undefined && Ed(t) &&
         t._everStartedThroughHostCliLauncher !== true &&
         this.config.turnDelegation?.(e) !== undefined;
}
```

`turnDelegation` 是"这一轮由谁负责审批"的委派机制。配合 `delegatedAllow()` 会打点 `desktop_ccd_delegated_ask_allowed`。

---

## 7. 流式协议

### 7.1 消息事件（S）

`message_start` / `content_block_start` / `content_block_delta` / `content_block_stop` / `message_stop`，delta 类型含 `text_delta`、`thinking_delta`、`input_json_delta`、`signature_delta`。

标准 Anthropic Messages API 流式形状，透传不改写。

### 7.2 会话状态机（S）

```
idle → running → requires_action → running → … → idle
```

`requires_action` 是等待权限决策或用户回答的状态，对应 UI 上的权限弹窗和 AskUserQuestion。

### 7.3 控制协议

`index.chunk-BlEfqh4Z.js` @ 有一组 `set_model` / `set_permission_mode` / … 的控制消息（S），这是**mid-turn 改变模型或权限模式**的通道——不需要重启进程。

---

## 8. 上下文管理

`compact` 相关符号出现在 4 个文件（`index.chunk-DNyequwM.js` 4 次、`index.chunk-M6SkuaH9.js` 3 次、`index.chunk-Bn6onBlX.js` 5 次、`index.chunk-lzaSYO3Q.js` 4 次），事件枚举里有 `compact_boundary`、`compacting` 状态、`PreCompact`/`PostCompact` hook。

可确认的机制：

- 压缩发生在**引擎侧**，桌面端只收到 `compact_boundary` 事件和 `compacting` 状态。
- 有 `PreCompact` / `PostCompact` hook 可介入。
- `getContextUsage` / `getContextUsageSummary` 是 `LocalSessions` 的 IPC 方法（S），说明上下文用量由引擎上报、桌面端展示。

**U**：具体的压缩算法、阈值、microcompact 策略在引擎内，本样本不可获得。

---

## 9. 子代理（subagent）

证据链：

1. `--agent <name>` 参数（S，argv 构造器）
2. SDK options 里 `agent` 出现 20 次、`agents` 出现 11 次（S）
3. hook 事件里有 `SubagentStart` / `SubagentStop`（S）
4. `Task` 与 `Agent` 工具名各出现 1 次（S）
5. `createAgent` / `getAgents` 是 `LocalSessions` 的 IPC 方法（S）
6. `btwChildSessions` / `sideSessions` feature flag（S）

结论：子代理由**引擎侧**创建和调度，桌面端负责参数传递（`--agent`）、生命周期事件（`SubagentStart/Stop`）和 UI 呈现（`getAgents`）。

**U**：子代理的并发上限、模型选择、结果聚合策略——在引擎侧。

---

## 10. 执行链完整走一遍（Cowork 本地模式）

```
用户输入
  → 渲染进程 (ion-dist) 发起 IPC
  → LocalSessions 方法（339 个之一）
  → 主进程组装 SDK options
  → ProcessTransport 构建 argv（上方 30+ 条规则）
  → spawn 子进程，env 含 CLAUDE_CODE_ENTRYPOINT=sdk-ts
  → 引擎内部跑 agent loop（while stop_reason === "tool_use"）
     ├─ 需要权限 → --permission-prompt-tool=stdio → 写 stdio
     │            → 桌面端 ToolPermissionBroker 决策
     │            → 用户在弹出的 host_dialog 里选 once/always/scheduled/deny
     │            → 回写 stdio 的 hookSpecificOutput
     ├─ hook 触发 → 桌面端执行，可返回 updatedInput 改写入参
     └─ 工具执行（VM 内 / 宿主机 / MCP 宿主进程）
  → NDJSON 流回主进程（28 种事件）
  → 主进程转 IPC → 渲染进程渲染
  → 会话状态机 idle/running/requires_action 驱动 UI
  → 终止（5 种 error_* 之一或 success）
```

---

## 11. 边界

- **U**：agent loop 本体、工具实现、compaction 算法、子代理调度器——全部在引擎二进制内，本样本只有 CLI 二进制，未做单独逆向（用户明确要求：若 Claude Code CLI 是依赖则跟随，但不做独立逆向工程）。
- **I**：`Tmux` / `REPL` / `SendUserMessage` / `ToolSearch` 四个工具的语义由名称推断。
- **R 缺口**：本环境无法登录，无法在运行时观察一次真实的 tool_use 往返。
