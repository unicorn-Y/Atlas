# Atlas main 真实源码对照与差距裁定

## 比对基线与方法

Atlas `unicorn-Y/Atlas@aa6196f550098cc46081dc6db2c376cb87ddffa5`（main）；DSH `deepseek-ai/deepseek-harness@687f282e8625c6b8d11ff58211a90524be2e4317`（源码 root 0.2.1-rc.2）。**仅根据本阶段已实际打开的 Atlas 模块判断；“未在抽查中发现”≠“全项目没有”。** Atlas 的主干已经有 Hermes Agent engine、SessionDB、WebSocket、子代理工作树、外部 Agent、后台 Hub/DBOS、checkpoint，不可写成空壳；等价机制需要验证真实运行，而非看文件名。

版本边界：DSH npm CLI 0.2.0-rc.2 与 Web 0.0.1-rc.5 均已单独下载、哈希验证和拆包。CLI manifest 的 runtime 依赖另已从 npm 安装，并静态核验精确 `0.2.0-rc.2` 编译包的 loop/session/JSONL/API/subagent/Web glue（证据 DSH_CORE-034）；这些旧版包证据与固定源码 `0.2.1-rc.2` 分开标识，不能把后者的源码细节当旧版实现。当前 UI standalone `0.0.1-rc.5` 与 runtime dependencies `0.2.0-rc.2` 的前端构建对应关系及 profile 默认挂载仍未核实；旧 Web 无 source map 且静态分析 partial。下表的结论是代码中机制存在性静态对照，不等于已在上游实际运行验证。发行包证据与限制见 `extracted/version-diff.md`。

状态：
- **有实现，机制不同**：代码确认具备用户功能，但运行/持久化/边界不等价；
- **局部实现 / 缺少证据**：有 UI/API/数据，沿路径某重要闭合点尚未核到；
- **具体行为缺口**：代码明确实现了相反/不足的行为；
- **未知**：范围内未证实，不断言全库缺失。

| 对标点 | DSH 源码锚点 | Atlas main 真实锚点与观察 | 判断/下一步 |
|---|---|---|---|
| 主执行循环 | `agent-loop/src/agent.ts:298-558` 的 Turn/Step/Attempt durable lifecycle | `core/atlas/agent/run_phases.py:1-24,146-174,698-920` 单一路径驱动；`core/atlas/engine/hermes_runtime.py:1390-1564` 在背景线程运行 Hermes loop 并异步桥接事件 | **有实现，机制不同**。Atlas 依赖 Hermes 源生 step/消息状态，需抽查是否为所有尝试持久化同等粒度、形成可重放完整链 |
| 模型请求 retry 与失败 | `agent.ts:504-526` 对 attempt 错误先 durable append，再 request-error waterfall，retry 决策 | `core/atlas/models/router.py:1-11,254-341` 复用 Hermes provider/transport retry/fallback；`hermes_runtime.py:1024-1040` 向 UI 传 recovery/retry/fallback 事件 | **有实现，机制不同**。不可说 Atlas 没重试；需验证一个失效 attempt 是否有独立且持久的回放身份，以及错误升级条件 |
| 工具并发顺序/屏障 | `tool-calls.ts:60-100,122-246` bounded rolling pool + dynamically reclassified exclusive barrier + ordered commit | `core/atlas/engine/tool_registry.py:290-493` 注册权限/工具/回调；`hermes_runtime.py:869-908` 工具起止事件由 callback 转换 | **局部实现，调度同等性未证实**。Atlas 真实 dispatch 在 Hermes 上游，需要审查对应源码而非看 Atlas wrapper 就宣布不存在；建议定义调度事件投影层 |
| 可恢复子代理 Session | `subagent/src/manager.ts:373-465,533-628` child 独立 durable session / lock / cold resume | `core/atlas/engine/tool_registry.py:43-53,586-650` 保留 `delegate_task`；`core/atlas/agent/subagent_worktree.py:237-344` 创建隔离 worktree；`core/atlas/agent/results.py:45-95` 封装 child 输出 | **部分能力存在；具体缺口待深入 Hermes 原生委派路径**。上述 Atlas 文件只证明工具注册、worktree、输出，尚未证明 child run→durable session→cold resume 的原生闭环 |
| 子 Agent 人类导航与独立会话干预 | `ui-subagent/src/client/index.ts:52-101` + `sidebar-chat/index.tsx:18-201`；`client/sessions/session.ts:265-357` | `core/atlas/api/agent_router.py:1-291` 有 agent status/persistent agent API，`core/atlas/api/runtime_ws_router.py:18-150` 有本 Run 级控制；外部 Session 见 `core/atlas/runtime/external_process.py:1-154` | **路径缺口待证实**。不能以 Atlas 已有 agent list/status API 等价“点击任意 child，进入自己的 event-log 会话并独立 steer/interrupt/cold resume”；需检查 frontend 真实组件及连接路由后定性 |
| 事件源与临时流分离 | `assistant-stream.ts:18-107` live transient + committed seq，`client/contract/events.ts:6-35` 替代临时 token | `core/atlas/api/runtime_ws_router.py:18-40` 有带序号 Run envelope；`core/atlas/api/runtime.py:18-102` 有 `RunState.events`；`core/atlas/engine/session_sync.py:1-14` Hermes SessionDB 是聊天持久真源 | **机制不同**。Atlas 存在“可见 run 事件”与“SessionDB 聊天记录”两面，需验证每个 tool/LLM attempt 是否持久原子关联、重连追平不掉关键 event |
| 重启后活跃执行处理 | DSH `subagent/src/manager.ts:533-628` 可按子 Session 冷恢复后续输入；但进程崩溃下原计算不中断 **未证实** | **明确证据** `core/atlas/api/runtime.py:108-146` ：加载时 `running/paused/waiting` 一律转 `failed`，恢复事件文本是 “execution was not resumed” | **具体行为缺口**：Atlas 会明确终止旧 Run，而不是恢复同一 Run 正在执行的步骤；但不能因 DSH 可 cold-resume 就断言它能完整无缝断点续跑。建议将“恢复 Session 可继续新回合”和“继续原执行”拆两个验收目标 |
| WebSocket 断线恢复 | DSH `api/gateway/src/client/stream-client.ts:346-380` in-flight failAll，domain re-open follow | Atlas `runtime_ws_router.py:18-60` 支持 `resume(after_sequence)`；`core/atlas/api/runtime.py:36-102` sequence/events、持久 metadata | **Atlas 已有应用层 resume**，不算缺失。需真机断线 E2E，比对恢复页是否包含所有执行事件，不能仅因为 DSH 有 mux 就认为更好 |
| Session 存储争用、截尾修复 | DSH `session-persistence-jsonl/src/storage.ts:270-339`; `lease.ts:1-28` 进程间 single writer 与 torn-tail repair | `core/atlas/engine/session_sync.py:1-14,41-145` 明确 Hermes SQLite SessionDB 唯一 owner / read、fork、rewind 操作 | **两套机制，不能按 JSONL 优劣简单移植**。先检查 Atlas SQLite writer 并发锁/事务边界；建议吸收“单写者、序号连续、失败后可验证重放”的契约，不必换存储 |
| Token 计量 | `llm/token-meter/src/turn-usage.ts:170-275` 所有 attempt 严格计费依据 | `core/atlas/models/router.py:53-73` 有 usage callback、`core/atlas/usage.py` 及 `core/atlas/usage_pricing.py` 存在（已从 main tree 核到，尚未逐函数看） | **已有组件，等价性未知**。需把 retry attempt / cache read/write / reasoning / missing buckets 与 Session/child IDs 真正关联 |
| 上下文和压缩可观测 | `compaction-basic/src/index.ts:148-233` + `compaction-tool-result-pruner/src/index.ts:128-170` 记录 shadow-price | `core/atlas/engine/hermes_runtime.py:1-9` 原生 Hermes compaction，`core/atlas/agent/run_phases.py:8-16` Atlas 前置记忆装配 | **有实现，账本同等性未知**。Atlas 不该重造压缩，需审查已具的 Hermes compaction 是否可给 UI/usage 提供可审计具体替换范围 |
| Agent Team DAG task board | `experimental/agent-team/src/task-board.ts:28-255` + `journal.ts:55-70` Lead Session durable DAG + revision | `core/atlas/agent/planning.py:10-73` 是 `PlanSubtask` 简化状态 pending/completed；`core/atlas/api/run_drive.py` 有更复杂 Goal/TODO 调度 | **部分存在、结构不同**。基础 TaskPlan 没展示完整成员/任务 revision+blockedBy DAG；但应先审查 Atlas 较新的 Goal、kanban、delegation 存储后决定是否必要 |
| 动态 MCP 工具热同步 | `mcp/mcp-client/src/index.ts:154-192`; `tools.ts:81-158` 列表更新与 live registry | `core/atlas/engine/tool_registry.py:290-493` 会注入 MCP，`core/atlas/engine/hermes_runtime.py:1-9` 引自 Hermes 的 MCP 注册 | **部分已实现/同步机制未知**。不能说 Atlas 无 MCP；测试 MCP 工具在运行中增删是否正确更新 schema 并保留 in-flight semantics |
| 背景 Tasks 与观察 | `api/job-controller/src/index.ts:75-115` Job list/follow/kill 且观察不消费模型 cursor；`schedule/schedule/src/index.ts` 持久 reminder | `core/atlas/runtime/hub.py:1-15,119-160` 后台 Hub、DBOS、真实 Agent callback；`core/atlas/api/run_drive.py` 任务调度、通知 | **Atlas 已有真实后台执行**。不能把它说成 UI 假壳；差距在 job 输出 offset/非侵入式观察与 Agent run/child 统一身份，仍需具体核验 |
| 插件生命周期 | DSH Cordis effect-scope、dynamic tool mount/dispose、pnpm profile | `core/atlas/plugins/runtime.py`、`core/atlas/engine/tool_registry.py`、`core/atlas/skills/lifecycle.py` 在 main tree 存在，尚未逐函数审完 | **未知而非缺失**。插件可安装与服务热卸载同等性需要后续专案核查 |

## 建议按**机制闭合度**而不是堆功能推进

1. 优先验收 Atlas **真实工具/LLM attempt → structured event → SessionDB durable → Web 断线追平**，保留 Hermes 主引擎，避免重写。
2. 追踪 `delegate_task` 在 Hermes 中的真实 child 创建/输出/生命周期，补统一 child session identity 与 parent lineage；然后让前端直达 child 的本体日志/干预接口，避免纯父节点摘要“假树”。
3. 针对 restart 明确产品契约：a. session 能继续下一回合；b. 运行任务继续原工作。这两件事的优先级、恢复边界不同，不用自相矛盾的“recoverable=true 但未 resume”代替执行机制。
4. Tool dispatcher 先查 Hermes 是否已有等价安全并行与 ordered commit；有则直接暴露回调，不重复造调度器。
5. 计量/错误/压缩要求跟随 **同一原始 attempt/run/child id**，真实事件不凭 UI 重构猜测。

## 未验证事项

未打开 Atlas 最新其他研究分支；本报告严格对 `main@aa6196f...`，它的 2026-10-05 提交时间 **早于**某些 Oct17–19 的其它项目工作，不得把其它分支实现当 main。未启动两个程序做性能/功能 E2E。缺口优先级基于观察机制，可继续扩展，非全库功能验收。
