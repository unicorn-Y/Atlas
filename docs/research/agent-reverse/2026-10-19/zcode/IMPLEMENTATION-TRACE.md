# 机制级实现追踪（ZCode 3.15.1 静态源码）

本报告分析 zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f 的实际 TypeScript 源码。安装包 3.15.3 尚未被本会话解析，以下没有任何“3.15.3 必然如此”的结论。相对目录根下 core = apps/zcode-cli/packages/core/src、adapters = apps/zcode-cli/packages/adapters/src；dynamic-workflow 各自写全包名以免混淆。

## 链 A：Desktop 进程 / RPC / 会话

1. packages/desktop/src/main/desktopHostProcess.ts L157-300：Main 用 electronUtilityProcess.fork(hostModulePath) 建宿主，传入运行环境；绑定 Agent 进程、任务数、MCP 遥测、会话建立、cron/offpeak 派发结果、浏览器执行、远程 Runtime、MCP App 沙箱登记等回调。此处宿主不是渲染器中的 JS 长任务。
2. packages/services/src/session/zcodeTaskService.ts L199-650：Service interface 包含 createTask / sendPrompt / enqueueTaskCommand / promoteTaskCommand / cancelTaskCommand / stopGeneration / resumeTask / compactSession / respondPermission / respondElicitation / getTaskSnapshotWithEtag / getTaskSnapshotToolCallsSlice 等；UI/远端经服务 API 消费。同一份服务定义是功能入口证据；实际调用是否在当前发行版畅通待动态验证。
3. packages/desktop/src/main/pluginSandbox/host.ts L49-205：Main 侧另设插件 UI 沙箱注册表、WebContents owner、会话 partition、原生权限对话；WebView 关闭与文档卸载属于生命周期一部分。
4. packages/desktop/src/main/desktopCronScheduler.ts L60-210：单独 scheduler utilityProcess。scheduler 提交 cron-dispatch-request/offpeak-dispatch-request 给 Main，Main resolveDispatchHost，再发 CronRun/OffPeakRun 给 Host；Host 返回派发结果，Main 转交 scheduler。无 Host 时给 transient，转入调度层退避，不擅自把调度失败认作任务成功。
5. packages/services/src/session/automationService.ts：cron/interval 执行配置、运行记录；bots/feishuChannelRuntime.ts L39-129：Feishu WebSocket 持有连接，接收群消息后交给 bot 通道。该通道不能和本地多子代理协作混为一谈。

**数据归属：** Main 管 Electron 进程、BrowserView/沙箱；Host 处理 Agent 任务和 service；session store/journal 是落盘权威；renderer 是投影与命令发起方。需验证 3.15.3 打包构建是否维持此拆分。

## 链 B：普通 Agent 回合 → 工具 → 后台子代理 → 反馈

- core/runtime/agent-runtime.ts L74-80 安装运行时方法与 runtimeCommandQueue。core/runtime/methods/turn-loop.ts L44-230 的 while 每次先接收上一模型步骤后到达的 runtime commands，然后微压缩、自动压缩（快速反复超限可明确失败）、初始化/变更 MCP tools、组合当前工具清单、运行模型请求。
- core/runtime/methods/turn-model-step.ts L94-199：建立模型步骤 telemetry 与 assistant persistence anchor；与 adapters/model/runner-stream.ts 的流式模型事件/错误分类结合。普通 retry、空响应重试、网络失败分类分布于 adapters/model/runner-*。
- core/runtime/methods/turn-tools.ts L30-168：模型流式 tool call -> persistPendingToolPart -> tool_queued ledger -> scheduleTools -> executeTools(signal) -> settle result；abort 对未执行调用也有明确 cancelled 投影，不可把仅有 tool_queued 解释为已执行。
- core/runtime/methods/subagent.ts L65-230：创建子 agent 时结合内置/自定义 profile、继承/覆盖模型、继承原会话中必要的 context、装配子 agent MCP、Skills、memory、工具 allowlist、权限与 caller provenance；最终通过 createExploreSubagentPort 建 child Runtime。
- core/subagent/runner.ts L110-405：launch 依据 runInBackground/profile.background 决定直接后台还是前台。前台注册 registry running，先写 metadata，再装 abort watchdog（在 session ready 之前启动）；ready 后发 SubagentSpawned；正常 await 结束则写 agent 输出与 usage 并发 SubagentStopped。执行中可人为 requestBackground 或达到 autoBackgroundMs 后 Promise.race 胜出，detachParent 后 child 继续，异步完成写结果并回调父 Agent。并不是“把前台界面隐藏就等于后台”。
- core/runtime-task/registry.ts L10-245：InMemoryRuntimeTaskRegistry 管理 taskId、pendingMessages、waitForTerminal、waitForBackgroundRequest、branchGeneration；local_agent 与 local_dynamic_workflow 的取消端口不同。**registry 本身不保证跨进程重启恢复，跨重启要靠存储层另证。**
- core/runtime/methods/subagent-messages.ts L25-107：队列上的 subagent reply 带 childSessionId、childToolCallId、parentToolCallId、responseId、branchGeneration，过期分支丢弃；persistSubagentMessageCommand 生成 model-only synthetic user message（供模型看，不直接算用户聊天）。
- core/runtime/command-queue.ts L114-240：优先级 now/next/later，task-notification 同级 batch 排空，其他命令逐条选择；有 cancel-pending set。下一次模型请求消费 queue 的行为在 turn-loop.ts L55-63。

**生命周期例外：** parent abort 在 foreground 会连带停止 child；切入 background 时 detachParent，子任务照本身生命周期继续；后台回执进入父队列而非强制触发全局中断。若父分支 fork，旧 branchGeneration 的 child reply 不交给新代。子 agent 空转判定有 activity watchdog，不用僵死 UI 推断线程状态。

## 链 C：动态 Workflow（与简单 Subagent 完全不同）

1. 脚本入口：core/runtime/methods/dynamic-workflow-run-start.ts 与 dynamic-workflow/src/compiler/compile.ts 对 authored workflow 进行解析/编译，生成 lowered 代码及 actor ask 点约束；run 配置可有 args、subagentModel/modelBindings、输入哈希、父会话/工具调用锚点、phase 和 holes。
2. 运行沙箱：apps/zcode-cli/packages/dynamic-workflow-runtime/src/harness.ts L1-31、L225-420：runWorkflowScript 建 WorkflowEngine 与 driver，写 .zcode/workflow-runs/<runId>.mjs，spawn child（Electron helper 子进程需要 ELECTRON_RUN_AS_NODE=1）。避免将整份脚本放 argv 导致 Windows 命令行限制；特殊 SEA 构建走 reexec argsPrefix。
3. 协议：dynamic-workflow-runtime/src/protocol.ts L45-188。child 调 __host.ask、create-actor 等，以逐行 NDJSON request 交给父进程；phase、report、artifact、log 是事件，不是全部同步 request；reply 走 ResponseMessage。父进程 actorMap 映射 local handle 到 engine ActorId。**工作流 JavaScript 只在子进程运行；模型请求/持久化责任在 Host driver + engine。**
4. 调度：dynamic-workflow/src/engine/scheduler.ts L125-205 使用 siteId+ordinal、actorSeq、inputHash 标识每个 ask；准入即同步记 journal 的 running 节点；执行与结算在进程外 callback 异步完成。已有 completed/failed 匹配节点不重复调用 driver；此前 running 恢复后重新派发；hash 失配则失败，避免错用旧结果。
5. 可变更恢复：scheduler.ts L205-289 中 amend-resume 的 ImportedActorState 先尝试匹配历史输入/seq；一旦第一次可能写 workspace 的工具真正出现才关缓存门；关闭后仍允许纯 ask 缓存。若仅因 fan-out 中第一个未命中就关闭，会错误地使并发兄弟 ask 的合法缓存丢失。
6. 并发资源：dynamic-workflow/src/engine/concurrency.ts L25-37、L120-275 的 ConcurrencyController 记录 epoch、inFlight、waiters、lastGood、lastBad、retryAfter 冷却。429 或 overloaded 在当前 epoch 下乘以 0.75（或退回 lastGood），4 次成功且有等待者恢复 +1，timeout/5xx 不推翻已确认上界。运行中的动态 retune/seed 另有条件。
7. 恢复：dynamic-workflow/src/engine/engine-resume.ts L17-44 从持久 journal 恢复结算顺序闸、ask 次数、artifact 版本及 run 级 report 个数/字节；不能仅“重放最后一条 assistant 消息”。adapter 的 adapters/storage/session-store/repositories/dwf-journal.ts L1-84 把 JournalStorePort 落到 node:sqlite dwf_* 表，事务由 driver 组合。
8. 结算：harness.ts L350-420 给出 engine.settled single-writer finalization。脚本错误为不可恢复的 errored；process spawn 失败/崩溃/协议错误等映射 interrupted stopped，容许 resume；AbortSignal.reason 还区分 model、user、interrupted 和 superseded（amend 后继）。动态 workflow stop/dispose 是流程语义，不是“杀进程再重来”。

**非常关键的分界：** 这套完整引擎只在 3.15.1 源码真实存在。3.15.3 CJS 是否包含同版本的工作流内核及兼容 journal schema，需 EXTRACTION-REQUEST 对照，不得直接宣称完成。

## 链 D：Context / Session / 用量

- core/runtime/methods/turn-loop.ts L78-112 在每轮请求前评估 microcompact/autoCompact；core/runtime/methods/compact-active.ts L73-122 的 AUTO_COMPACT_MAX_ATTEMPTS=3，保留工具数量上限 100，token 来源可标 provider_usage 或 estimate；状态/事件由内部 persistence helpers 管理。
- core/runtime/methods/session-fork.ts L219-235 创建 ForkIdentityMap，逐类重映射 message、part、turn、toolCall ID，还包含 goal/verification 边界。静态表明“fork 是新对象身份”，并非同一对话只展示另一个文本切片。
- adapters/storage/session-store/sqlite-session-store.ts 与 migrations：Session / Message / Todo / selection / usage 等持久化；adapters/storage/session-store/repositories/usage.ts L17-25、L20-166、L166-248：请求级 model_usage + turn_usage，存 provider/model、input/output/reasoning/cache-create/cache-read、重试次数、首 token、耗时等；有 30 天留存策略。
- subagent 定义可有长期记忆提示；但 Atlas 的唯一记忆主体设计不能直接复制 ZCode 每个子 agent 自持 memory 的语义。

## 链 E：Skills、MCP、插件及动态 UI

- adapters/mcp/index.ts L165-168、L205-215、L498-502：MCP connection pool 与跨 transport 生命周期；tools/list_changed 经 revision 到 core turn-loop 下个请求前刷新。Resource subscription、OAuth、elicitation 等是独立能力，不能只从列工具按钮推断。
- adapters/plugins/index.ts L39-107 提供插件 marketplace、hook、MCP、UI surfaces、插件来源；adapters/skills/index.ts L29-60 的 manifest 探测同时包含 .zcode-plugin、.claude-plugin、.codex-plugin、.cursor-plugin 的不同来源，属于宿主兼容逻辑。
- ui/plugin-ui/adapters/messagePortTransport.ts L5-40 将 MessagePort 转为 MCP JSON-RPC 传输；ui/plugin-ui/app/pluginUiHostBridge.ts L38-122 官方 AppBridge 暴露 tool/input/result、callTool、readResource、sampling、openLink、updateModelContext、downloadfile 等事件/RPC。
- desktop/main/pluginSandbox/host.ts L49-205 给每个 app identity 分配隔离 partition，按 owner 管理实例与权限，不是 iframe 内直接拥有 Host 的全部 Node 权限；services/gen-ui/adapters/stateStorage.ts L27-165 通过 key hash 的文件存储同步插件小状态。和 Atlas 自建 API 的插件管理不是同一层能力。
- UI 用 ui/app-shell/WorkflowRunSidePane.tsx L85-220 根据父会话的权威 projection 生成 timeline；旧的操作拒绝提示在状态变化时清理；单独展示 workflow artifact 的 metrics/table/chart/board，chart 有 compact sparkline 与详情两档。

## 后续验证用最短路径

本地机械抽取先锁定三条动态调用路径并追包内同版代码：Desktop 按 CreateWorkflow→run/start→子进程 ask→journal→事件→UI；Task(agent)→spawn→background→parent command→新 model request；MCP App resource→sandbox register→MessagePort→AppBridge→UI。对于任一环找不到，记录包内搜索证据和 U，不要用 3.15.1 的同名函数顶替。提取的 AST/片段、路径、sha 和调用者写进独立分支，不上传会话、密钥。
