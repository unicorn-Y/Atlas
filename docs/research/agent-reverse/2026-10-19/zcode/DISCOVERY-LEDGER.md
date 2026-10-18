# ZCode 功能与机制发现总账

证据等级：**S**=固定源码可定位（此表 S 全为 **3.15.1**，非 3.15.3 实测）；**D**=官方发布说明；**I**=带依据的推断；**U**=仍不可核验；**R**=真实操作，本阶段 **0 项**。所有事实只说明调用链和静态实现存在，不等于功能在每种环境必然成功。锚点文件均基于 zai-org/ZCode@**aac4755666d09fdcd70272fcf063c077a639015f**；完整 URL 见 EVIDENCE-INDEX。

| ID | 主动发现、机制而非宣传标签 | 入口→状态/执行→归属 | 等级 | 当前状态 |
|---|---|---|---|---|
| ZCODE-001 | Electron 主进程 fork 独立宿主 utilityProcess，承载 agent、浏览器命令、远程会话、数据服务等回调 | desktopHostProcess.ts L157-300 | S | 已追源码 |
| ZCODE-002 | 正常回合循环依次排空后台命令、微压缩/自动压缩、MCP 增量刷新、装工具并执行模型步骤 | core/runtime/methods/turn-loop.ts L44-230 | S | 已追源码 |
| ZCODE-003 | 工具先排程、写 pending tool part、发 queued/event，再按 AbortSignal 执行并结算 | core/runtime/methods/turn-tools.ts L30-168 | S | 已追源码 |
| ZCODE-004 | 子代理根据 profile/请求选择 foreground/background；后台受模型借用条件约束；启动前 watchdog 与元数据写入 | core/subagent/runner.ts L110-260 | S | 已追源码 |
| ZCODE-005 | 子 agent 模型/权限/MCP/Skills/持久记忆/父子溯源分别导出、过滤或继承 | core/runtime/methods/subagent.ts L65-230 | S | 已追源码 |
| ZCODE-006 | 子代理回复通过 priority=next 的 runtime command 注入父模型上下文；分支代际失效消息被丢弃 | core/runtime/methods/subagent-messages.ts L25-107 | S | 已追源码 |
| ZCODE-007 | 任务 registry 区分 agent/legacy workflow/dynamic workflow，提供后台切换、等待终态、待递消息 | core/runtime-task/registry.ts L10-245 | S | 已追源码；注意本表是内存层 |
| ZCODE-008 | runtime command queue 按 now/next/later 优先级分发，能批量消费同级 task notifications、记录 cancel-pending | core/runtime/command-queue.ts L10-240 | S | 已追源码；本身非持久化 |
| ZCODE-009 | Workflow 文本编译/lower 后经 Node 子进程运行，通过 NDJSON request/response、event 桥接到父引擎 | dynamic-workflow-runtime/src/harness.ts L1-225; protocol.ts L45-188 | S | 已追源码 |
| ZCODE-010 | ask 以 siteId+ordinal、inputHash 与 journal 作为重放门；running 重派发、已完成命中缓存，hash 变化硬失败 | dynamic-workflow/src/engine/scheduler.ts L125-205 | S | 已追源码 |
| ZCODE-011 | 改版续跑 ImportedAsk 缓存受首个写工具副作用约束；无副作用 ask 有条件复用 | dynamic-workflow/src/engine/scheduler.ts L205-289 | S | 已追源码 |
| ZCODE-012 | 并发治理：429 切 epoch 并降低上限、Retry-After 冷却、成功 streak 后渐进增大 | dynamic-workflow/src/engine/concurrency.ts L25-37, L120-275 | S | 已追源码 |
| ZCODE-013 | workflow 中断与脚本错误区分：interrupted/stopped 可恢复，脚本错误不是同一状态 | dynamic-workflow-runtime/src/harness.ts L1-31, L~185; engine-state.ts L28-35 | S | 已追源码 |
| ZCODE-014 | resume 从 journal 还原节点/结算顺序/报告计数，不依赖 UI 缓存 | dynamic-workflow/src/engine/engine-resume.ts L17-44; scheduler.ts L110-170 | S | 已追源码 |
| ZCODE-015 | SQLite dwf_* journal 按端口与引擎分离，事务场景 driver begin immediate | adapters/storage/session-store/repositories/dwf-journal.ts L1-84 | S | 已追源码 |
| ZCODE-016 | 模型使用数据分请求/turn 落库：输入输出、推理、缓存创建/命中、重试和 TTFT；留存 30 天 | adapters/storage/session-store/repositories/usage.ts L17-25, L130-166, L166-248 | S | 已追源码 |
| ZCODE-017 | Context 超限前微压缩/自动压缩，压缩 telemetry 记录 token 来源并区分手动/自动；压缩调用有尝试上限 | core/runtime/methods/turn-loop.ts L78-113; compact-active.ts L73-122 | S | 已追源码 |
| ZCODE-018 | 会话 fork 需要 remap 消息、part、turn、tool call ID；不是只复制文字 | core/runtime/methods/session-fork.ts L219-235 | S | 已追源码 |
| ZCODE-019 | MCP 连接池、stdio、OAuth、elicitation、工具变更通知以及资源订阅；tools/list_changed 回合间刷新 | adapters/mcp/index.ts L105-168, L205-215, L498-502; turn-loop.ts L117-121 | S | 已追源码 |
| ZCODE-020 | 插件市场整合插件 Hook/MCP/UI surface；Skills 扫描兼容 ZCode/Claude/Codex/Cursor 多种 manifest | adapters/plugins/index.ts L39-107; adapters/skills/index.ts L29-60 | S | 已追源码；扩展不等于核心功能 |
| ZCODE-021 | 官方宿主 MCP Apps 走 renderer MessagePort JSON-RPC / AppBridge，支持调用工具、读取资源、更新模型上下文 | ui/plugin-ui/adapters/messagePortTransport.ts L5-40; ui/plugin-ui/app/pluginUiHostBridge.ts L38-122 | S | 已追源码 |
| ZCODE-022 | Electron MCP 插件 UI 有独立 guest、持久 partition、owner 关联、permission gate 与 dispose 生命周期 | desktop/main/pluginSandbox/host.ts L49-205 | S | 已追源码 |
| ZCODE-023 | Workflow 的相位、参与者、artifact、provenance、设置调整/恢复动作分别投影到侧栏；图表可展示完整视图/迷你图 | ui/app-shell/WorkflowRunSidePane.tsx L5-58; workflow-artifacts/presets/ArtifactChartView.tsx L8-10, L320-372 | S | 已追 UI 源码；未实测 |
| ZCODE-024 | Cron scheduler 是另一 Electron utilityProcess，dispatch 到合适 Host；Host 不存在按 transient 错误退避 | desktop/main/desktopCronScheduler.ts L60-210 | S | 已追源码 |
| ZCODE-025 | 服务层有带 Etags 的任务快照、命令入队/升优先级/取消、会话续接、许可回应；扩展到 Feishu WebSocket 群通道 | services/session/zcodeTaskService.ts L199-650; services/bots/feishuChannelRuntime.ts L39-129 | S | 已追源码；可用性待实测 |
| ZCODE-026 | 官方发布说明提到 3.15.3 的并行 Agent/快速调用请求失败修复、启动/登录问题；与 3.15.1 非同版 | 2026-10 官方 changelog（见证据索引） | D | 只能确认官方说法 |
| ZCODE-027 | 3.15.3 CJS 是否实际包含相同 Scheduler/Agent/Command/插件实现、增删了哪些 IPC | Release asset 与 3.15.3 app.asar | U | **BLOCKED**，见提取任务 |

## 初轮主动扩展出的范围（非用户事先枚举）

除了多 Agent，本轮源代码还揭示了：二进制/SEA 模式的 workflow 子进程重入、工作流模型绑定与 hole 填补、workflow 产物和图表预设、UI 插件沙箱隔离、MCP 动态 tool revision、跨插件生态的 manifest 兼容、模型请求级 usage 以及后台 Cron 与 off-peak 分通道。它们不是可单独复制的“按钮”；对应依赖、失败策略和主机数据职责见 IMPLEMENTATION-TRACE。

未覆盖完整数千文件的逐文件代码审计。尤其服务器端外部服务、商用登录许可、Native helper、可选实验开关、运行协议边界与 3.15.3 发行包均须另证。不得将“发现路径/静态有代码”转换为“已运行通过”。
