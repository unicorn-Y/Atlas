# 源码调用链：交互 → 数据 / 事件 → 执行 → 恢复

**研究对象：固定 v2.0.32 源码，非在本会话运行的安装包。** 文中短路径默认 `packages/`，数字为标签 v2.0.32 行号。

## 1. 用户提交消息 / 排队 / steering（OPENCODE-002,017）
1. Solid UI `app/src/session/composer/queue.ts:30-109` 形成 `QueuedPrompt` 与 mutation，操作调用 server API `session.inbox.cancel/list`，并通过 `data.session.prompt(admission)` 入队。
2. HTTP 合约 `protocol/src/groups/session.ts`，实现 `server/src/handlers/session.ts`；`core/src/session/session.ts:118-185` 的 `Session.prompt` 先校验 session，准备 `SessionPrompt.prepare`，再向 `SessionInbox.admit` 登记；除 `resume:false` 外执行 `execution.wake`。
3. `core/src/session/inbox.ts:240-414` 的 event projector 将条目持久化进 `sql.ts:119-149` 的 `session_inbox`（有 `delivery`, `enqueued_seq`, `payload`）。promote 时删除 pending row 并在同一事件事务中投影消息。可更改 `queue ↔ steer`；并发状态不匹配抛 `LifecycleConflict`，上层映射 `InboxConflictError`。
4. `core/src/session/runner/llm.ts:56-135` 由 `nextPromotable` 选择本轮输入；steer-scope continuation 不直接吞掉 queued next turn。代码明示“queued controls”和“queued prompts”不能混为一谈。
5. 队列编辑的前端防丢做法：`app/src/session/composer/queue.ts:88-105` 先 admit 修改后的消息，再取消旧条目；原条已被投递则保留编辑草稿，避免重复发送。

## 2. 执行所有权 / 结束 / 断点恢复（OPENCODE-003,004）
- `core/src/session/execution.ts:57-159` 的 `SessionExecution.layer` 使用 `SessionRunCoordinator.make` 管理每 session 的进程内单活执行 fiber；`started` 发布 `Execution.Started` 并在事务提交回调 `store.claim`（write-ahead）。`drain` 调 Location/Instance-bound `SessionRunner.Service`。
- `settled` 产生互斥 terminal 结果：Succeeded 和 Failed 都释放 claim；用户主动 interrupt 取消 Job 并释放；**shutdown interruption 保留 claim**，为下一服务器续跑留证。
- `core/src/session/run-coordinator.ts:60-197` 的 wake/doorbell 设计避免与停止清理竞态；`execution.ts:145-159` interrupt+resume 对 steering 优先感知，执行等待与取消回执不是同一件事。
- `core/src/session/execution/restart.ts:17-57,70-219` 扫描 `SessionStore.listSuspended`；`countResume` 在实际恢复前写入耐久次数，超过 `DEFAULT_MAX_ATTEMPTS=10` 以 Failed terminalize。插入 “Continuing after restart” synthetic 提示；对后台 shell 按已丢失执行取消并通知，对 child agent 尝试独立恢复与父会话通知。
- 注释明确 at-least-once：进程死亡可能导致外部写文件/API side effect 重做。转给 Atlas 时必须保留该语义提示；不能宣称 exactly-once。

## 3. Agent 循环、流式工具与错误（OPENCODE-007,008,010）
- `core/src/session/runner/llm.ts:45-150`（`SessionRunner.drain`）加载插件激活状态，修复陈旧 compaction / tool calls，读取待处理输入，进入 context → model step 循环。
- `core/src/session/context.ts:110-177` 两阶段 `select` + `load`：读取 session/agent；合并 Agent 和 Session permissions；并行取 tool snapshot、builtins、discovery、Skills、References、MCP、instruction entries；再以选定 model 调 `SessionHistory.entriesForRunner`。
- `core/src/session/runner/step.ts:67-192`：provider `LLMClient.stream` 逐事件写 `createLLMEventPublisher`；工具仅在事件 `tool-call` 且未 providerExecuted 时创建本地 fiber；tool task 执行前 `Tool.Called` 已写出。取消时 `interruptTools`，结束时保护最终 Tool/Step 结算不被中断。
- `core/src/session/runner/retry.ts:31-116`：重试指数增长+间隔/次数 cap；provider 的 RateLimit/Internal `retryAfterMs` 有 15 分钟最大采纳值；timeout 单独最多 3 次；插件 `session.retry` hook 可修改 retry decision/delay；发布 `RetryScheduled` 后等待。
- `core/src/session/runner/step.ts:135-181`：若上下文溢出且模型尚未产生输出，可请求 `recoverOverflow` 并 compaction，再重入；`compaction.ts:41-63` 类型区分 auto / overflow / manual、skipped/completed/failed；并不承诺任意错误都会自动补救。
- `core/src/session/runner/to-llm-message.ts:153-200` 对跨 provider/model 的 thought signatures、加密 reasoning 元数据做 replay 条件判断，不盲目复制所有 provider 内部状态。
- `core/src/session/usage.ts:11-53` 区分非缓存 input、reasoning、visible output、cache read/write，并计算美元成本；`projector.ts:58-68` 增量累加到 session 表。

## 4. 子代理两种完成路径（OPENCODE-005,006）
- tool 被注册为 `subagent`：`core/src/tool/plugin/subagent.ts:17-64` 给 model 的 schema 含 `agent/description/prompt/sessionID/background/model`。
- 实现 `:110-209` 沿 parentID 追深度并检查配置 `experimental.subagent_depth`；agent 不得为 primary；通过权限层 `permission.assert`；继续 child 前确认 `existing.parentID === context.sessionID`；model 优先 override→agent config→parent。
- `:210-259` 新建 child `sessions.create({parentID,...})`、投递 prompt、`subagents.start(recovery)`；同步执行 `jobs.block`，background 则 `subagents.background` 立刻返回 child sessionID。失败也把 sessionID 返回到错误中，支持续问。
- `core/src/session/subagent-job.ts:20-69` 管 Job 的 run/resume/wait、异步 notification；`subagent-completion.ts:21-45` 以带 `source:subagent` metadata 的 synthetic message 写入父会话，而非临时 toast。重启时恢复见第2节。
- 子代理深度值和权限是 v2 当前代码事实，不得因 Atlas 目标“最大权限”而误删 OpenCode 机制的描述。Atlas 可取通知/恢复，不必照搬其权限默认。

## 5. 插件热加载与接口（OPENCODE-012,013）
- `core/src/config/plugin/source.ts:20-160` 扫描项目/用户配置来源及本地文件，`plugins` 支持增/减、相对路径解析，文件监听事件驱动重建。
- `core/src/plugin/module.ts:73-149` 从本地入口或 npm 装载，检查默认导出 `{id,effect}` / `{id,setup}`，支持 optional TUI/RPC entrypoints，返回 revision/source。
- `core/src/plugin/supervisor.ts:150-245` pre/internal/sdk/instance/post 按顺序组装，快速激活本地可用项，再加载待安装包；`Queue.sliding(1)` 与 100ms debounce 合并连续更新；失败/blocked/pending 单独记录。
- `packages/plugin/src/effect/*` / `promise/*` 存在多域扩展接口（Agent/Tool/Session/MCP/Permission/RPC/TUI/Worktree 等）。需要检验具体扩展的实现和运行边界，不等同随意 JS 获得宿主全部权限。

## 6. Desktop 与 Server 边界（OPENCODE-014～016）
- `desktop/src/main/desktop.ts:17-50` 初始化 IPC、Windows Lifecycle 和 `BackgroundService.layer`；主进程是壳。
- `desktop/src/main/service/desktop-cli.ts:50-110` 解析随包 CLI 和版本；`background-service.ts:33-102` 借 `@opencode/client/service` 的 `Service.ensure` 启动/复用 `opencode serve --service`，接收本地 URL + basic password。固定端口冲突控制注释与实际 CLI args 对应。
- `desktop/src/main/ipc-transport.ts:1-122` Electron `MessagePortMain` 承载 Effect RPC 的 structured clone 消息；窗口 renderer 卸载时释放绑定。**这是桌面 IPC，不是服务端 Agent 消息流**。
- `server/src/event-feed.ts:1-91` Bus 事件到 SSE `data: JSON\n\n`；每 subscriber dropping capacity 4096，满了触发 `SubscriberOverflowError`，消费者需补全/重连。
- `app/src/runtime/server/client.tsx:1-125` server-scoped transport+event emitter，`createClientConnection` 有重连、按 location 分流、16ms flush；`server-sync/connection.ts:1-30` 非 connected 时 invalidate、收到 `server.connected` 后标记首次/重连并通知重取。

## 7. Code Mode 与 UI 时间线（OPENCODE-018,019）
- `core/src/codemode/tool.ts:35-126` 暴露 `execute({code})` 给模型，受控 JS 调工具命名空间、执行 progress、输出文件；模型上下文用固定 tool 描述，变化的工具列表通过 `CodeModeCatalog` 注入指令。
- `app/src/session/timeline/message-timeline.tsx:16-50` 使用 `@opencode/session-ui` projection 与 `createTimelineVirtualizer`；`virtualizer.tsx:93-426` 处理动态行高、滚动锚点、展开工具并导航到后台 shell ID；`session/requests/session-question-dock.tsx:260-283` 将多步提问回执提交到服务器 `session.form.reply/cancel`。


## 实物包确认及 Browser pane → Agent → CDP 链

精确 v2.0.32 ASAR 中 package.json 标示 @opencode/desktop 2.0.32，main 为 out/main/index.js；该入口 bundle SHA256 a43fc9bd7ce7e27cc215d1f1b630087a93b4e7b889075860ae6864c76429c9fc，819133 bytes。打包主进程 bootstrap 发现 CLI sidecar、确保本地服务并创建桌面 RPC。desktop-CiR2Cmvk.js 有 ExtensionSubscribe byte 23827；renderer main-CZyBNj5O.js 有 ExtensionSubscribe byte 1302996、browser.pane byte 1222691；host-R1JTLSvD.js 含 browser.pane byte 27546。

Browser 执行链（源码静态 S，包内路径存在 P）：内置 core plugin 注册 BrowserPlugin → plugin-browser/src/tools.ts 把 44 个操作映射成 browser.* Agent 工具并要求 browser permission → connection.ts 默认 deny 所有 agent；GUI attach 时检查 session/location 和 connectionID，session 上临时 grant browser:*，以 requestID/pending map 与桌面 pane 往返 control command/result → gui-extensions/browser main IPC demand 加载 browser pane，session-scoped model 保持 pane/session 关联 → pane 创建 Electron BrowserWindow/WebContentsView 浏览器页面并验证服务 origin/endpoint → chromium.ts 以 CDP Target.setAutoAttach 管理页面与 target → Browser tunnel RPC 在 sidecar 服务进程建立受限 TCP socket 与 desktop page/target 之间传输 CDP/network bytes。connection lease teardown 会撤销 permission 并 dispose tunnels。Runtime attach 与协议包流未观察。

桌面 GUI Extensions 的 typed IPC/store/event lifecycle 不是 Agent plugin API。后者由 packages/plugin hooks 注入 tools/agents/providers/MCP 等；前者是 Electron main/renderer 的应用 UI 功能面。不能混为同一种插件机制。

Browser 失败与副作用边界也在协议中编码：session deleted/moved 会关闭连接 (connection.ts:159-162)；命令仅可使用已 attach session 中浏览器当前公布的 tabID (:165-178)；60 秒超时与断连均把结果标为未知，要求重新检查目标而不是重放潜在副作用，取消会发 cancel control event (:231-250)。
