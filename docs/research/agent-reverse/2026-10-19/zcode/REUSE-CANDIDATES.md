# 机制吸收候选：能直接学到什么、落到 Atlas 哪一层

版本声明：下列均以 ZCode 3.15.1 的真实源码作为参考，**不是 3.15.3 的直接实物验收**。以源码路径确定真实工作方式，优先吸收可靠的执行语义与组件边界，避免“界面看上去有了、后端没有接线”。用户要求的充分授权/最大并发指的是 Atlas 本体已授权的执行；不应让第三方网页插件拿到未授权主机接口。

| 机制候选 | ZCode 可看的成熟实现和核心算法 | Atlas 建议接入点 | 为什么先做 / 不能照搬的地方 |
|---|---|---|---|
| 1. 父子 Agent 回执（P0） | core/subagent/runner.ts, core/runtime/methods/subagent-messages.ts, runtime/command-queue.ts, runtime-task/registry.ts：任务状态、model-only 回流、branchGeneration 防旧消息串分支、priority next；运行中可自动前台转后台 | core/atlas/agent/run_phases.py、engine/hermes_runtime.py、core/atlas/tools/agent_bridge.py、core/atlas/runtime/external_agents.py | Atlas Hermes 主链不变；需要明确发回父模型的命令和 child/parent IDs、通知 ack。不能只让 UI 显示“完成” |
| 2. 动态工作流引擎（P0） | dynamic-workflow-runtime/src/harness.ts + protocol.ts + dynamic-workflow/src/engine/scheduler.ts、engine-resume.ts、adapters/storage/session-store/repositories/dwf-journal.ts：script→子进程→NDJSON ask→driver→journal→replay，hash/ordinal/actorSeq 验证 | 独立 core/atlas/workflows/engine.py、journal.py、driver.py（待开发），复用已有 Atlas Agent API / 工具，而不是替换 Hermes | 先实现 crash-resume/stop/failed 数据契约，再考虑可视化。Python/Node 跨语言迁移要重新实现 async/SQLite 边界，不可直接把 TS CJS 强塞 Python 进程 |
| 3. 自适应并发（P0） | dynamic-workflow/src/engine/concurrency.ts 的 epoch、inFlight、waiters、lastGood、streak；429 降为 0.75x、连续 4 成功且有排队再 +1、Retry-After 冷却、5m 防盲目 seed | Atlas 未来 workflow/scheduler 子任务执行口，ModelRouter per-provider/credential 侧 | 用户允许的“尽可能多子代理”是需求；算法仅在真实服务拒绝时降低 cap，且不把 5xx/超时等价误判为额度耗尽 |
| 4. Workflow replay 的可变更缓存（P0） | dynamic-workflow/src/engine/scheduler.ts actor 索引、inputHash 与 ImportedActorState。未命中不马上关闭整个并发组缓存；第一次有副作用写入才关闭，关闭后仍允许纯 ask | workflow journal/driver，和 Atlas 任务文件变更观测对接 | 大量重复工作可真正节省 token；必须有可复核输入指纹与 side-effect provenance，不能用“提示词一样”冒充结果仍正确 |
| 5. 主机任务/服务状态分层（P1） | desktop/main/desktopHostProcess.ts、desktopCronScheduler.ts、dynamic-workflow-runtime/src/harness.ts：Host/child 生命周期与 workflow 运行结算分离；无 Host 是 transient dispatch 退避 | core/atlas/runtime/hub.py、scheduler/__init__.py、runtime/backends.py、runtime_ws_router.py | Atlas 现有 Hub/Scheduler 应直接扩展，不需重造；避免单次健康检查把所有任务取消 |
| 6. 请求、工具、Turn 级用量（P1） | adapters/storage/session-store/repositories/usage.ts：独立 model_usage/turn_usage；reasoning/cache read/cache creation/TTFT/retry；30 日 retention | core/atlas/api/usage_router.py、core/atlas/models/tokens.py、core/atlas/engine/hermes_runtime.py、frontend/src/renderer/pages/models | 保留 provider 原始 usage，并标估算与报告值来源；Usage UI 和真实计费要分开 |
| 7. MCP 动态注册与插件生态（P1） | adapters/mcp/index.ts connection pool、tools/list_changed、resource subscription、OAuth；adapters/plugins/index.ts 和 adapters/skills/index.ts 多格式 manifest 扫描与 hook/UI surface | core/atlas/tools/mcp_client.py、plugins/runtime.py、skills/discovery.py | Atlas 已有真实 MCP/Skills/Plugin 不能重写一套；按缺项补连接池、OAuth/elicitation、skills alias |
| 8. MCP App / GenUI 沙箱（P1） | desktop/main/pluginSandbox/host.ts + ui/plugin-ui/adapters/messagePortTransport.ts + app/pluginUiHostBridge.ts + services/gen-ui/adapters/stateStorage.ts：按 appIdentity 独立 partition，MessagePort JSON-RPC，AppBridge、UI state | Atlas Electron main/preload + renderer 新 MCP App host，后端 MCP resource/notifications | 与静态插件设置页完全不同；动态工具结果、资源订阅、上下文更新应端到端能跑。WebView 权限边界属于第三方插件隔离，不影响 Atlas 主 Agent 自身授权策略 |
| 9. Workflow 可视化和产物（P1） | ui/app-shell/WorkflowRunSidePane.tsx，ui/components/workflow-timeline/，ui/app-shell/workflow-artifacts/presets/{ArtifactChartView,ArtifactTable,ArtifactMetrics,ArtifactBoard}.tsx | frontend/src/renderer/components/MessageThread.tsx 事件流水、独立 Workflow Run 详情 | 只有后端 journal/projection 可读时才做 phase/actor/node 时间线；否则又是“空壳”。进度和具体模型/总 Token 来自真实 event/usage |
| 10. Session fork 的完整对象身份（P1） | core/runtime/methods/session-fork.ts ForkIdentityMap 重写各类 ID 和 goal/verification 边界 | core/atlas/engine/session_sync.py（Hermes 单一 SessionDB） | Atlas 已有持久分支，按漏项对照即可；禁止另造会话主数据库 |
| 11. BrowserView/远程任务恢复（P2） | desktop/main/browserView/*、desktopRemoteSessions.ts、services/session/zcodeTaskService.ts 的 remote/session RPC | Atlas computer/browser capability 与现有 Windows CUA/UIA/SendInput 路线 | 从浏览器实际协议/恢复状态吸收，不因为有 BrowserView 文件就判断每个浏览器操作完全支持 |
| 12. 双向 bot 与定时任务（P2） | services/bots/{telegram,feishu,weixin}ChannelRuntime.ts、session/automationService.ts、desktopCronScheduler.ts | Atlas channel_router/group_router + runtime/hub.py + scheduler | 用户的讨论工作台与 bot 多 Agent 不同；挑真实有用的通道接线，不扩张不需要的服务 |

## 迁移次序和真实完成判据

**Wave A — 先把 Agent 执行和背景恢复做对**：定义 task snapshot（run/task/parent/branch/child IDs、status、model、usage、notification status）；把 child result enqueue 到 Hermes 同一 session 下一次 model request；后台任务完成在父会话确实消费而不是仅 UI 收到。能做跨 fork stale child 回复测试。优先核对已有 Hermes / AgentBridge / Scheduler，不造平行 loop。

**Wave B — 工作流引擎和 SQLite journal**：最小路径为 3 个 actor ask 并发、有限状态 journal、宕机后重放已完成 ask 但在飞 ask 重派发；脚本 error 与宿主 interrupted 区分；调节并发在 429 减小后自动恢复；恢复顺序保证确定性。此处必须单独真实数据测试。

**Wave C — UI/插件**：用 Wave B 产生的真实 run projection 驱动时间线/图/报告；MCP App 经 MessagePort 实际发送 tools/readResource/updateModelContext 与 Host 授权，然后才宣布完成。不要创建“看起来像 ZCode”的静态页面替代后端。

## 复用边界及来源

- zai-org/ZCode root LICENSE 和 package.json 明示 **Apache License 2.0**（Copyright 2026 Z.AI Co., Ltd）；复用公共源码要遵守许可证、NOTICE、修改标识、第三方依赖许可，并纳入 Atlas THIRD_PARTY_NOTICES.md。源码是 3.15.1，不能因此认定 3.15.3 专有/未公开源码可任意逐字复制。
- 复用算法与协议思想可在 Atlas Python/Electron 中原生重写；不要未经核实导入 3.15.3 15MB 打包 CJS，也不要绕过服务端的权限或登录；这会让可持续维护性变差。
- 已读 Atlas 正式仓库无任何本研究业务代码变更。研究者不应自动把研究表当作实施验收。

## 尚不能直接复用的部分

3.15.3 Agent Runtime 与 desktop IPC 的实际符号和模块版本、部分隐藏能力与实验开关、具体 provider endpoint/账号策略、真实 Windows 工具调用路径仍是 U；由 EXTRACTION-REQUEST.md 补机械证据后再确定低成本的逐文件复制/改写清单。假装已获取同版完整源码会直接导致下一轮“抄错版本”的问题。
