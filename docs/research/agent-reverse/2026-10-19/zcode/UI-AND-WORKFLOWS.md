# ZCode UI、交互入口与完整工作流（3.15.1 源码静态）

**状态说明：全部为静态 UI/服务/运行时连线的代码证据 S；并未在 Windows 启动 ZCode 3.15.3，所以不声称截图、操作成功或布局细节。** 可见控件是否受许可、灰度或网络模式限制，未验证。

## 1. 会话 / Agent 工作区

- 任务接口：packages/services/src/session/zcodeTaskService.ts L199-650。UI/远控可以 createTask、sendPrompt、enqueueTaskCommand、promoteTaskCommand、cancelTaskCommand、stopGeneration、resumeTask、getTaskSnapshotWithEtag、getTaskSnapshotToolCallsSlice、switchAgent、respondPermission、respondElicitation。含多窗口任务列表、分组/排序/归档接口。
- 操作序列：选择工作空间/会话 → createTask（会话层分配任务）→ sendPrompt → Host 运行 AgentRuntime → 流式事件进入父会话投影 → UI 列表、步骤、工具调用/结果更新。上一轮还在跑时可入队、升优先级、撤销排队命令；跟直接中断模型不同。
- 运行中后台子代理：Agent Tool 触发子任务 → createExploreSubagentPort → 父对话中显示运行状态 / childSession 详情；用户发 stop/background 等状态改变，核心 registry 持有 active task，结果回父 model-only command。UI 对子代理详情的源代码可从 packages/ui/src/app-shell/SubagentSessionSidePane.tsx 与 SubagentDirectorySidePane.tsx 追踪。
- 观测字段：子任务 model、allowed tools、childSessionId、耗时/工具次数/token、后台/完成/失败；来自 core/subagent/runner.ts L110-405 的 emitted events 和 files，不是从消息文本猜测。

## 2. 动态 Workflow 创建、监工与重新配置

- 源代码入口：packages/ui/src/ToolCallBlocks/renderers/create-workflow.tsx、save-workflow.tsx、resume-workflow-run.tsx、get-workflow-run.tsx、get-workflow-run-roster.tsx、get-workflow-run-situation.tsx、workflow-diagnostics.tsx、resolve-workflow-question.tsx。
- 操作序列：模型发 CreateWorkflow 或用户从 workflow 中枢运行保存的 workflow → 编译/校验 script 和 actor ask → Child Node VM 接受 script/args → Engine 发出 run/node/phase 事件、driver 创建 actor session 与模型调用 → UI 根据父会话 workflowRuns projection 展示相位、actor/roster、图、token、异步问答、产物。
- packages/ui/src/app-shell/WorkflowRunSidePane.tsx L85-220：侧栏由父 session projection 订阅真实快照，runId 对照当前 run，继任链由 supersededBy 指向 successor；图使用 toolCallId、参数化 scope 与补全版本追溯；不是全靠组件 local state 伪造“在运行”。
- Workflow 操作：UI side pane 引用 WorkflowRunSettingsPopover（可改 run 设置），isWorkflowRunCancellable/isWorkflowRunResumable 判操作资格；handleCancel 经 cancelBackgroundWork(workId=runId)；失败反馈有 reasonCode，而非假装按钮已生效。某些控件随 run status/remote mode 限制，需要 3.15.3 动态验证。
- 脚本里的 phase()、report()、ask()、artifact()、hole/fill 等进到独立事件和 journal。用户可查看完整 run 时间线、actor session、报告及产物；中断后 Resume 应交引擎 journal 做 replay/必要 ask 重新派发，而非直接在 UI 重新新建所有 actor。
- 图片/产物不是单一 Markdown：packages/ui/src/app-shell/workflow-artifacts/presets/ArtifactChartView.tsx L8-10, L320-372：小卡 compact sparkline+最新值，详情完整坐标/图例/tooltip；另有 ArtifactTable、ArtifactMetrics、ArtifactBoard 和 tile preview。

## 3. 模型、上下文与用量

- 上下文行为：普通 Turn 在首/中间模型请求前 microcompact 与 autoCompact；显示的 token 用量可来源于 provider usage 或估算，不该把推理 token 和输出 token、缓存 token 混算。
- 后端记录：adapters/storage/session-store/repositories/usage.ts 的 model_usage、turn_usage；界面目录 packages/ui/src/settings/usage-stats/ 可追累计用量；此报告没有验证计费口径与实际账单一致。
- 子代理可选独立模型配置/权限，core/runtime/methods/subagent.ts 从 session/profiles/override resolve 子模型；Workflow 模型绑定还具有脚本命名模型模型表。不要把 UI 选项出现等于网关一定支持该模型。
- session fork：session-fork.ts 重写相应消息/part ID，避免同一 child 和 parent 互相覆盖；需动态复核实际 fork/side-chat 操作。

## 4. 插件、MCP Apps 与内嵌浏览器

- MCP server 连接与 auth/elicitation → MCP tools resources → 有 UI surface 的插件使用 MessagePort JSON-RPC 和 AppBridge，更新模型上下文走 ui/update-model-context，取消/结果与 host 数据事件不同通道。UI 组件从 ui/plugin-ui/PluginUiToolCallBlock.tsx、PluginUiSidePane.tsx、pluginUiHostController.ts 等入口找。
- 插件真实网页在 desktop/main/pluginSandbox/host.ts 注册 guest、独立 partition、权限对话；浏览器 camera/mic、download/openlink 走桥接。任何插件页面不应在复用中直接获取 Atlas 机器全权限；用户对 Atlas Agent 本体授权是另一回事。
- 内嵌网页自动化：desktop/main/browserView/browserCommandExecutor.ts、browserPlaywrightExecutor.ts、browserScreenshotSurfaceCoordinator.ts、browserTabRecoveryStore.ts、browserVideoRecorder.ts 等显示 UI 与 BrowserView 操作间存在分层；具体浏览器/Computer Use 能力尚未追完所有 driver 方法，不能冒充与 Atlas 已做路线等价。
- zcode CLI 插件扫描包括 Claude/Codex/Cursor Skills 根，但“能发现 manifest”不代表所有外部插件的事件/权限语义完全兼容。

## 5. 定时、群 Bot 和无前台任务

- packages/desktop/src/main/desktopCronScheduler.ts：Cron/OffPeak scheduler 是独立进程，通过 Host 和服务 dispatcher 执行；无 Host 的 transient 不代表已派发。服务端 automationCron、automationService 负责规则及周期。
- packages/services/src/bots/feishuChannelRuntime.ts / telegramChannelRuntime.ts / weixinChannelRuntime.ts 与 providers/: 渠道的连接/消息合流到服务层，不是多模型专家讨论工作台的直接证据。对外远程网络服务的协议与凭据细节未启动验证。

## 用户真实操作与回放待核对表

| 操作 | 静态可定位链 | 此轮是否观察运行 |
|---|---|---|
| 创建会话 → 发送提示词 → 中途排队/取消 | zcodeTaskService、AgentRuntime、CommandQueue、Host | 否 |
| 在一个任务中派多个子代理 → 观察耗时/Token → 背景完成返回 | subagent/runner、RuntimeTaskRegistry、subagent-messages、side pane | 否 |
| 开 10 路 Workflow ask → 限流 → 观察并发下降与恢复 | dynamic-workflow/concurrency、scheduler、WorkflowRunSidePane | 否 |
| 失败后 app 重启 → 恢复 Workflow journal → 再消费产物 | harness、engine-resume、dwf-journal、projection | 否 |
| 安装 MCP App → 打开 UI → 订阅 resource / 请求权限 | plugins、MessagePort、AppBridge、pluginSandbox/host | 否 |
| Cron 到时无 Host → 恢复 Host 后成功派发 | desktopCronScheduler、automationService、HostProcess | 否 |

将来从 3.15.3 真包核验这些操作时，应把每一次的操作时间、模型、会话和进程 PID、对应事件类型、journal 状态、重启前后快照与版本/哈希记录到实测附卷；不能把官方 changelog 当运行截图。

### G0–G7 renderer continuation

Passive CDP on the real 3.15.3 page observed 1,491 DOM nodes and 307 loaded scripts; it supplies no screenshot or interaction evidence. Screenshot and `analyze_web_bundle` rejected this local file page with `target_not_allowed`. The launch child processes used the default ZCode user-data path, so the app was stopped without sending a prompt or clicking a task action. See [END-TO-END-TRACES.md](END-TO-END-TRACES.md).

New static renderer evidence: `pluginUi.appToolCall` is accepted by the event schema and dispatched to MCP Apps `notifyAppToolCall` (`assets/parts-1PK4PulD.js` @5,622; `assets/styles-CSpM3qgc.js` @1,044,668). This adds the renderer event consumer edge to the prior host→main registry→sandbox path, but not the producer or result loop. Full current surface rows are in [SURFACE-MAP.tsv](SURFACE-MAP.tsv); renderer actions remain unenumerated.
