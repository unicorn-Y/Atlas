# DSH → Atlas 差距账（证据级）

> 生成日期：2026-11-13
> 基准：DeepSeek-Harness `deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`
> 本地基准副本：`D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness`
> 方法：4 条并行线各自**读 DSH 实现体**（不是只读文档）→ 回 Atlas 找对应实现 → 给路径行号 → 判定等级。
> 判定词：`PRESENT-PARITY` 同等 / `PRESENT-WEAKER` 有但少关键性质 / `ABSENT` 没有 /
> `PRESENT-STRONGER` Atlas 更强（DSH 侧是缺口，**不要为了"对齐"而削弱**）。

## 结论摘要

| 维度 | 差距条数 | 其中 P0 | 其中 P1 | Atlas 更强的项 |
|---|---|---|---|---|
| 引擎与工具执行 | 36 | 3 | 12 | 2（重连取消、写路径诊断增量） |
| 会话与持久化 | 33 | 2 | 11 | 2（长期记忆、rewind） |
| 插件与扩展 | 33 | 1 | 10 | 3（hook 信任门、skill 依赖门、agent 声明） |
| 桌面与 UX | 33 | 0 | 10 | 5（rewind、多窗口/分栏、消息操作、富预览、托盘） |

**最重要的判断**：DSH 的优势不在功能数量，而在**两条地基**：
1. **会话事件日志是唯一真源**，模型历史由它派生（`deriveMessages()`）。Atlas 是"可变 SQLite 消息表 + 内容被抹掉的 run JSONL"，这是 P0。
2. **一切皆插件的组合根**（Cordis service/seam/profile/bundle/patch）。Atlas 是 51 字段扁平 `AppServices` + 手写 router 元组，这是 P0。

这两条不补，其余所有"补功能"都会退化成再加一个硬编码分支。

---

## 一、引擎与工具执行（36 条）

### P0

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| E1 | 只追加会话事件日志 = 唯一真源；`deriveMessages()` 派生模型历史 | `packages/core/session/src/index.ts:798,819`；`docs/subsystems/session.md` | `engine/session_sync.py:385-415` 直接写 role 行；run 事实走 `loop.py:603` JSONL 且**内容被抹掉**（`logs.py:104-116` 存 `{"length":N}`） | HARD (event log is not the canonical model history; compression/rewind mutate active rows without events, so the target is unreachable without redesign) |
| E2 | turn / step 两级生命周期（turn=一条用户消息，step=一次模型调用），`turn/end` 带 typed reason | `packages/core/agent-loop/src/agent.ts:298,400`；`docs/agent-lifecycle.md` | typed terminal reason 与每步结束原因写入 run journal；逐步状态、所有 typed reason 均有 unit coverage。W3-X1 的真实模型回合产出 `step_start → step_end(response) → turn_end(completed)`；带工具回合产出 `step_end(tool_calls)` 和 concludeTurn tool receipt | ✅ CLOSED (W3-X1) |
| E3 | 工具执行流水线三瀑布：pre-execute → execute → post-execute → result，带 typed decision | `packages/core/tools/src/index.ts:1375,1499,1151,1787,1838`；`docs/tool-execution-pipeline.md` | ToolScheduler 的 typed pre_execute/post_execute/result_stage 已接入 kernel loop；PreToolUse、PostToolUse、PostToolUseFailure 与最终结果校验均经过对应阶段 | ✅ W2-V2 已接线；真实模型工具回合已验证 |

### P1

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| E4 | 每工具强制输出契约 `{schema, render, presentationMeta}`，成功即校验 | `packages/core/tools/src/index.ts:214,1838` | registry 工具支持注册输出 JSON Schema 并在 handler 与 post-hook 后校验；kernel/API 事件携带契约，时间线和工具卡片消费 `render` 与 presentation metadata；12 个存量 registry 工具仍使用默认宽泛 schema，host/MCP 工具使用兼容 schema；W3-X1 真实模型观察到 concludeTurn 的 `text/concludeTurn output` 合同 | PARTIAL (W3-X1: stored tool schemas are not yet semantic per tool) |
| E5 | 两有序表 durable inbox：`next-turn` / `next-step`，`inject` 不唤醒 | `packages/core/agent-loop/src/inbox.ts:74,109` | `engine/kernel/inbox.py` 持久化两条 lane 并回放/确认；`runtime_ws_router.py` inject 分支写 inbox，不唤醒 steer 队列 | ✅ 本轮关闭 |
| E6 | 请求信封落日志 + 工具增删发 developer 消息告知模型 | `agent.ts:626-700` | `request_envelope.py` 记录请求摘要/角色/长度/工具名；`loop.py` 在工具池变化时发 developer 消息 | ✅ 本轮关闭 |
| E7 | 并发安全按**调用参数**判定，派发前**复检**，不支持者成 barrier | `packages/core/agent-loop/src/tool-calls.ts:60,122,199` | `tools.py` 调用级参数分类并在派发前复检；读写不明的调用串行化为 barrier | ✅ **本次已修**（参数感知 + 派发前复检 + barrier） |
| E8 | 上下文压缩在 **step 边界**按实测压力触发 + 溢出重试需 surface 代次前进 | `docs/subsystems/compaction.md`；`compaction-basic/src/config.ts:20,75,105` | `loop.py` 每次模型调用前检查压缩；overflow 只有 provider history 摘要前进时才重试 | ✅ 本轮关闭 |
| E9 | plan 模式：durable `plan/mode` 事件 + `plan:policy` 提示段 + 拒绝时带用户反馈 | `packages/plan/plan-mode/src/index.ts:52,217,425` | kernel 每次模型调用按 live mode 重建共享 `PlanMode` 指引，持久化 plan-mode 变化并反馈拒绝 | ✅ **本次已修**（每轮按 live mode 重建 + 共享 PlanMode 实例） |
| E10 | todo 每次写入都是 durable 事件，重启/叉分/未压缩也存活 | `packages/todo/tool-todo/src/index.ts:80,118` | `TodoStore` 将 `todo.updated` 快照写入 `session_events`，新 run 从最新快照恢复，写入失败会回滚内存状态 | ✅ 本轮关闭 |
| E11 | goal 变更 CAS `{id, revision}`，过期拒绝；轮数上限默认 256 | `packages/goal/goal/src/index.ts:244` | `engine/goals.py` 持久 goal_id/revision，SQLite 单次写回原子比较并拒绝过期 writer；goal_subgoal 要求并返回当前 CAS token；默认 max_turns=256 | ✅ 本轮关闭 |
| E12 | 审批关闭四值：`allowed-once`/`rejected`/`cancelled`/`unavailable`，全部 fail-closed，且 `ask|never` 在服务内先于任何 answerer 生效 | `packages/interaction/user-approval/src/index.ts:100,225-232` | 审批 asked/decided 通过 append-only `session_events` 持久化；ask/never 策略先于 answerer；失败关闭 | ✅ 本轮关闭 |
| E13 | 权限预设同时绑定 **沙箱模式 + 审批策略**，不匹配时派生 `custom` | `packages/interaction/permission-presets/src/index.ts:189-194` | `approval_policy.py` 预设绑定 permission/sandbox/approval 三维；RunState 和 resume 保留三维设置，不匹配时派生 `custom` | ✅ 本轮关闭 |
| E14 | OS 级沙箱按**每次调用**给 `read-only`/`workspace-write`/`danger-full-access`，并报告实际执行等级 | `packages/sandbox/sandbox-local/src/profiles.ts:16`；`docs/subsystems/sandbox.md` | Docker per-call `read-only`（临时只读 bind mount）/`workspace-write`（run 容器）有执行等级返回及定向测试；`danger-full-access` fail-closed。Docker Engine 当前不可用，未观察容器实跑；Windows host 无通用 per-call OS executor | HARD (Windows per-call OS sandbox requires a Job Object/AppContainer executor; Docker Engine is unavailable) |
| E15 | 持久 PTY：owner 鉴权、`waitReason` 四值（stdin_read/inferred_idle/timeout/session_exit）、有界回滚 | `packages/experimental/tool-terminal/src/index.ts:166-395` | `local_execution.py` 按 run owner 隔离进程读写/取消，并返回 `stdin_read` / `inferred_idle` / `timeout` / `session_exit` | ✅ 本轮关闭 |
| E16 | 统一后台作业注册表：`job_output/list/kill`，256KiB 环形缓冲，settle 后 16KiB，每 owner 最多 10 个 | `packages/jobs/jobs-local/src/index.ts:33-42,128` | `ExecManager` 统一 owner-fenced shell 与 subagent 注册/列表/输出/终止；运行缓冲 256KiB、settled 16KiB、每 owner 10 个；`job_*` 工具已暴露模型调用 | ✅ 本轮关闭 |
| E17 | 子代理统一激活：能力声明校验、`toolFilter` 真删且拒执行、fork 子（继承父已完成前缀）、persona | `packages/subagent/tool-subagent/src/index.ts:96,171` | 已验证 agent definition 的可信/能力约束与 allowlist；native 子代理 fork 父会话已完成轮次并记录 delegate lineage；agent prompt 作为受限 persona 指引注入 | ✅ 本轮关闭 |
| E18 | 工具内请求沙箱升级：`sandbox_permissions` + `justification`，按调用审批，拒绝不动既有策略 | `packages/core/tools/src/ptc.ts:387-405` | 单次 justification/approval 通过定向测试；DeepSeek V4.1 Flash 真实回合观察到 `local_exec` 的 `approval.required`，返回 `allow_once` 后 host 无 executor 路径 fail-closed，工具未执行且 run 完成；通用 host per-call executor 仍缺失 | PARTIAL; HARD(host: per-call OS executor requires Job Object/AppContainer) |

### P2

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| E19 | `concludeTurn()`：工具结果可声明"本轮结束" | `packages/core/tools/src/index.ts:435,1428,1860` | kernel 暴露 concludeTurn tool，工具回执后直接设置 final response 并结束循环；unit lifecycle coverage；W3-X1 DeepSeek 回合实际调用 `concludeTurn`，一次模型请求后 `run.completed`，回复 `CONCLUDED_OK` | ✅ CLOSED (W3-X1) |
| E20 | 重复调用提醒：按 `(name, canonical_args)` 连续相同判定，阈值 [3,5,8]，只提醒不否决 | `packages/guard/repeat-tool-reminder/src/index.ts:44,58` | `stuck.py` 按连续相同工具名和规范化参数在第 3/5/8 次发提醒，不阻止调用，不纳入结果文本 | ✅ 本轮关闭 |
| E21 | 工作目录 per-session durable `working-directory/change`，沙箱写根不随之移动 | `docs/subsystems/working-directory.md` | `workspace_session_manage(move)` 持久化 conversation.workspace 并说明从下一轮生效；kernel 仍将 workspace 作为 run 固定值，没有独立 cwd 与固定 sandbox write root。现存 `test_engine_workspace_cwd.py` 使用已移除的 Hermes `tools.*` 路径，定向执行失败 | PARTIAL (W3-X2: session move exists, independent cwd/sandbox roots do not) |
| E22 | Agent Teams：root 范围 roster、steer-only 消息、任务 DAG per-mutation revision CAS、`blockedBy` 无环、`waitForChange` | `packages/experimental/agent-team/src/index.ts:135-199` | GroupStore/GroupOrchestrator、REST API 和 Kanban 存储存在，相关 unit tests 通过；kernel 未暴露模型可调用的 team roster/message/task DAG 工具 | NOT-DONE (W3-X2: storage/API only; no in-loop tool surface) |
| E23 | Workflow：模型写编排**脚本**（`agent()`/`parallel()`/`pipeline()`） | `packages/workflow/workflow-ptc/src/index.ts:109` | kernel `workflow` 仍按目标规划 DAG；`test_u32_expert_workflow.py` 通过，但自定义编排脚本/控制流不存在 | PARTIAL (W3-X2: DAG planner is weaker than script workflow) |
| E24 | Ralph：串行上下文重置迭代，`maxRounds` 256，handoff ≤16KiB | `packages/experimental/tool-ralph/src/index.ts:35,151` | 本仓库未找到 Ralph 工具、迭代驱动器或 handoff limit 实现；本批未引入新执行协议 | NOT-DONE (W3-X2: no Ralph implementation) |
| E25 | 空闲维护槽 `runMaintenance()`，公开状态仍 idle | `docs/subsystems/core.md#the-agent-handle` | `atlas_runtime.py` 在每个成功 run 完成后进入 `AtlasKernel.runMaintenance()`；内核拒绝与活跃 turn 重叠且 unit tested，但 production `AgentRunContext` 没有提供 `maintenance_callback`，因此 host 路径回退成 no-op | PARTIAL (W3-X1: production maintenance producer still absent) |
| E26 | `tools.restrict()` 注册级 scope 层，未知名/空集注册即失败 | `packages/core/tools/src/index.ts:1103` | `tool_permissions.py` run 级 allow/deny glob 交集有 unit coverage；注册表无工具集绑定的 `restrict()` view，也没有 unknown/empty registration validation | PARTIAL (W3-X2: policy is run-scoped only) |
| E27 | PTC 模式：单一 `run_code` 传输，其它工具直调被拒并提示，子调用各记日志 | `packages/core/tools/src/ptc.ts:30` | Atlas `execute_code` 可被调用并经当前工具执行管线记录；定向 execute_code tests 通过，但仍是可选附加工具，kernel 不提供排他的 run_code-only 模式 | PARTIAL (W3-X2: optional code tool, no enforced PTC mode) |
| E28 | 压缩区域安全：位置跨度，不切开 tool-call/result 对，尾部按 token 计价 | `compaction-basic/src/region.ts:117,139` | `context.py` 以消息位置保护未配对 tool call/result，并按 token 计算尾部；`test_kernel_compaction_surface.py` 与剪枝测试通过；本批未在真实模型回合触发压缩 | PARTIAL (W3-X3: unit evidence, no live compaction observation) |
| E29 | `ctx.tokenMeter`：按 surface 节点分别计价，成功请求 usage 可锚定 | `packages/llm/token-meter/src/index.ts:101,146` | `token_meter.py` 有逐 surface node 计价，kernel 每次模型请求写入 `model_request_envelope`；真实 W3-X3 回合日志观察到 8209 surface estimate / 3 节点与 successful run 的 9946 input tokens，但没有把 provider usage 锚定回各节点 | PARTIAL (W3-X3: node estimates live; provider usage anchoring remains absent) |
| E30 | LSP 四操作闭合联合 + provider registry | `docs/subsystems/lsp.md` | 新增 `goToImplementation` operation、模型 schema、kernel read-only allowlist 与 dispatch 映射；service-level fake LSP 单测通过，真实模型尚未实际调用该操作，且统一 provider registry 未实现 | PARTIAL (W3-X3: operation wired/tested; no live call or provider registry) |
| E31 | 会话查询五工具（含 event read/trace/lineage） | `packages/experimental/tool-session-query/src/index.ts:66-109` | 现有 `session_search`、`read_session`、`send_to_session` 可用；没有 event read/trace/lineage 的统一模型工具面；corpus tests passed | PARTIAL (W3-X3: core queries exist, event/trace/lineage tools missing) |
| E32 | Git worktree：从固定 revision 创建，模型可"进入"而不必新开 run | `docs/subsystems/worktrees.md` | conversation worktree 可从 branch 创建/移除，但接口只接受 base branch 名且切换 workspace 要下一轮运行；没有 pinned revision enter-within-run 行为 | PARTIAL (W3-X3: worktree baseline exists; revision pin and in-run enter missing) |
| E33 | 兜底补齐：写路径诊断增量（Atlas 独有） | — | `engine/lsp_bridge.py:38-80` | **PRESENT-STRONGER** |
| E34 | 取消时为每个跳过调用生成合成 `tool/result`，保证可重放 | `tool-calls.ts:250` | `tools.py` 为被取消或未开始的调用合成 cancelled receipt/result；kernel timeout/cancel tests passed；本批未观察真实模型取消回合 | PARTIAL (W3-X3: unit proof, no live cancellation observation) |
| E35 | 压缩锁 bracket 落 transcript，可检测孤儿 | `docs/subsystems/compaction.md` | lease 仍只落 DB；崩溃后靠状态推断，run journal 没有 durable compaction start/end bracket；checkpoint barrier tests passed | PARTIAL (W3-X3: DB lease exists, transcript bracket missing) |
| E36 | 后台作业完成通知作为 followup 投递 | `tool-jobs/src/index.ts:30,253` | `atlas_runtime.py` SQLite inbox watcher 可将后台通知送入 steer queue，初始通知随 system context 进入模型；通知/进程测试 passed，但本批无真实后台作业完成后续投递回合 | PARTIAL (W3-X3: queue path tested, no live followup observation) |

---

## 二、会话与持久化（33 条）

### P0

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| S1 | 只追加日志 + `seq = log.length` 连续性契约，事件永不改写 | `packages/core/session/src/index.ts:798,819` | 两份互不相干的记录：run JSONL 文本被**故意销毁**（`logs.py:104-116`），SQLite `messages` 表原地改（`atlas_state_messages.py:559` UPDATE、`:879` DELETE、`:1008` archive_and_compact） | HARD (canonical event history and append-only mutation semantics are absent; compression/rewind mutate active rows without an event contract) |
| S2 | surface 折叠：`replace` 节点遮蔽早前 seq 范围，压缩不删事件 | `packages/core/session/src/surface.ts:120,594` | 压缩只 `active=0, compacted=1`（`:986`）后重写可见列表，无法表达"被摘要替换但保留原文" | HARD (surface replacement requires the missing append-only event log and retained original events) |

### P1

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| S3 | 会话格式版本 + 相邻迁移链 v0→v4；读到**更新**版本必须拒绝并指出路径 | `packages/core/session/src/types.ts:89`；`session-format/src/chain.ts:41` | `SCHEMA_VERSION = 32`；`atlas_state_schema.py` 对更高版本抛 `SchemaTooNewError` 并给出 DB 路径 | ✅ 本轮关闭 |
| S4 | 崩溃修复是 reader 侧补 closer（含 `turn/end{interrupted}`），不是重写 transcript | `packages/core/session/src/repair.ts:53` | `read_session_events()` 在读取时检查进程归属，对 stale open turn 事务性追加合成 `turn/end{interrupted}`；不修改 transcript，kernel 写入真实 `turn/start/end` | ✅ 本轮关闭 |
| S5 | handle 式持久化：read/append/flush/close，单一写者，跨进程 kernel lease | `session-persistence/src/handle.ts:59,97,109` | `engine/session_handle.py` 提供 `SessionHandle`（acquire fail-closed / read_events / append_message 带 `turn_lease_holder` 写事务 fence / append_event / flush / refresh / close）；`run_phases.execute_run` 经 `hold_turn_lease` 在整个真实回合持有跨进程租约（PID liveness 防陈旧持有者、后台续租、best-effort fail-open）；单测 10 项通过；真机 8883 回合中独立进程探针被拒（holder `pid=38808:run=…`）、回合后放行 | ✅ CLOSED (W4-Z3) |
| S6 | checkpoint 三屏障 fail-closed，写失败就阻断派发 | `session-checkpoint-policy/README.md` | `require_checkpoint()` 在阶段边界、工具派发前和工具结果持久化后失败即抛错，kernel 阻断继续执行 | ✅ 本轮关闭 |
| S7 | 压缩 bracket 进日志，`summary` 记 shadowed seqs / token / provider / model，可重建 | `packages/compaction/compaction/src/types.ts:24,34,72` | `begin_session_compaction/compact_session_messages`（session_sync.py:352-438）在 `session_events` 落 `compaction/start|summary|end` bracket；summary payload 含 `shadowed_seqs`、`shadowed_message_ids`、`snapshot{provider,model,before_tokens}`、`summary_sha256`；引擎级真库探针（w4_z3_session_proof）验证 bracket 持久 + 重开 DB 可重建 | ✅ CLOSED (W4-Z3) |
| S9 | 免模型 tool-result 剪枝：8192 阈值 / 4096 头 / 1024 尾，落**遮蔽替换节点** | `compaction-tool-result-pruner/src/config.ts:11-13` | `context.py` 阈值 8192/4096/1024（chars），剪枝 + `output_ref`/`microcompacted`/`masked_content` 持久化，kernel resume 恢复标记（单测覆盖）；真机 8883：45000 字符工具输出在首次持久化即剪为 9733 字节预览 + 内容寻址全量文件，后端重启后同会话续跑 `run.completed` 且模型历史不含全量 marker（`full_marker_in_history: false`）；内核掩码分支由引擎探针实证（9737→5335 + compact-output 引用） | ✅ CLOSED (W4-Z3) |
| S11 | 投影注册表：纯单元、`stateVersion`、有线视图 schema、`asOfSeq` 快照 | `session-projection/src/index.ts:92` | 注册 `session.summary` 默认 projection；快照含 view schema、`stateVersion`、`asOfSeq` 与数据 | ✅ 本轮关闭 |
| S13 | 会话查询语料库：可丢弃 fts5 索引 + revision/generation 增量 + `current|shadowed|log-only` 分类 | `session-query-sqlite/src/schema.ts:8,127` | 搜索结果提供稳定 `seq`、`after_seq` 游标和 `current|shadowed|log-only` 分类，覆盖 FTS/LIKE/CJK 路径 | ✅ 本轮关闭 |
| S19 | durable 附件：内容寻址不可变 ref、每次读重校验、先准入后追加用户事件 | `attachment-local/src/file-store.ts:14,76` | `session_sync.py` 将图片存为 SHA-256 内容寻址 blob；用户消息仅在 blob 原子落盘后追加；模型历史每次读取重算并核验摘要 | ✅ 本轮关闭 |
| S21 | fs 观察策略：per-session 观察态 + provider version token；未见过 vs 不存在区分 | `packages/fs/fs-observation-policy/src/index.ts:28` | 完整文件读记录到 SessionDB 的 session/path token（含 exists 与内容摘要）；edit/batch/write/append 提交前重验 token，修改后刷新观察态。此为乐观 stale-write 检测；普通文件系统没有跨任意外部写者的可移植 CAS replace 保证 | ✅ 本轮关闭 |
| S22 | OTel：普通事件与 session-log 双通道独立队列 | `packages/telemetry/otel/src/index.ts:22,30` | `require_checkpoint()` 与已注册的 `SessionDB.get_session_timeline()` 产生生产 span（`atlas.run_checkpoint.write` / `atlas.session.turn_outline`）；普通事件/session-log 独立队列仍未实现 | PRESENT-WEAKER |
| S25 | tokenMeter 逐 surface 节点计价 + route-aware 图像计价 | `packages/llm/token-meter/src/index.ts:146` | kernel 每次 conversation 请求以实际 model/provider route 调用 `price_surface_nodes()`，并将逐节点估算写入请求日志与 usage；文本 surface 已接入生产路径，provider 图像定价回调仍未接入，图像继续使用 heuristic | PARTIAL (W2; production request wiring implemented, routed image pricing remains) |
| S32 | fork 要求边界不在开放 turn 内，`session/end-seed{inherited:true}` 标记继承切点 | `packages/core/session/src/fork.ts:21` | `session_sync.py` 拒绝未闭合 tool turn；子会话导入事务中追加 `session/end-seed{inherited:true}` | ✅ 本轮关闭 |

### P2

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| S8 | 压缩策略 0.8 阈值 / 0.16 保留、per-provider-model 覆盖 | `compaction-basic/src/config.ts:20,23,191` | `ContextManager.compaction_policy` 默认 `{"threshold_ratio": 0.8, "retain_ratio": 0.16}`（100k 窗口 auto_compact=66000），并支持 per-provider 与 per-provider/model 两级 override（0.7/0.2 → 55300）；单测 + 引擎探针 `w4_z3_session_proof` 双重实证 | ✅ CLOSED (W4-Z3) |
| S10 | 图像 offload：log-only 决策 + message projection | `compaction-image-offload/src/*` | 无（图片从不进历史，见 S19） | ABSENT（被 S19 阻塞） |
| S12 | 投影持久缓存 `session_projcache`：`(key,ver,seq,val)` 行 | `session-projection-cache/src/spec.ts:29` | `session_projcache(session_id,key,ver,seq,val)` 表 + revision 触发器失效（atlas_state_common.py:506-529），内核历史读取全部经 `read_session_model_messages`（loop.py 6 处）读写缓存；真机回合实测写入行（`dsh-live-*: key=model_history ver=1 seq=3`）；引擎探针验证重开 DB 缓存命中、更新后触发器失效 | ✅ CLOSED (W4-Z3) |
| S14 | 模型可见查询工具五件套 | `experimental/tool-session-query/src/index.ts:66-96` | `tool_catalog.model_facing_tools` 暴露 `session_search / read_session / send_to_session / session_event_search / session_trace / session_event_trace / session_event_read`；`tool_node.py:975` 按 workspace 准入派发并包 `<untrusted_session_snapshot>`；真机 8883 真实模型调用 `session_search` 与 `session_event_search` 成功返回种子 durable 事件（seq 17, probe/evidence） | ✅ CLOSED (W4-Z3) |
| S15 | `sessionStats` 投影：整日志折叠，含 llmMs/toolMs/ttftMs | `session-stats/README.md:42-46` | 修复真缺陷：`run_replay/loader.py` 的 `RunInfo.session_id` 此前只看首行（真实 run 首行是 api_timing）恒为 None，投影恒零；现全文件扫描捕获 `run_start.session_id` 并补单测；真机 8883 三个真实回合后 `GET /stats` 返回 `{"turns": 3, "steps": 4, "llmMs": 11516, "toolMs": 1640, "ttftMs": 10297, "ttftSteps": 4, "decodeMs": 1219, "decodeTokens": 119}` | ✅ CLOSED (W4-Z3) |
| S16 | `turnOutline` 投影 | `session-turn-outline/src/projection.ts:85` | `atlas_state_timeline.py` 由 `SessionTimelineMixin` 注册到 `SessionDB`；`get_session_timeline()` 和 `get_session_messages_around()` 可直接调用，并有真实 SQLite 覆盖；真机回合后实测返回 3 条 entries（row_id/preview/timestamp + pagination） | ✅ CLOSED (W4-Z3) |
| S17 | 会话导出 ZIP：live root 先 flush，含子会话与附件字节 | `session-log-export/src/archive.ts:187-195` | `session_archive.build_session_archive`：host flush 回调 + `flush_token_counts` 屏障 + 子会话子树 BFS + `atlas-attachment://<sha256>` 逐字节完整性校验；`GET /api/conversations/{id}/export.zip` 真机 200（manifest `atlas.session.zip.v1`，root_session_id，sessions=1）；附件字节路径由 `test_zip_flush_subtree_and_attachment_bytes` 覆盖 | ✅ CLOSED (W4-Z3) |
| S18 | spill 缝：`saveText → {locator, bytes, hint}`，保存失败保留原文 | `docs/subsystems/spill.md:92`；`spill-policy/src/index.ts:27` | `spill_store.save_text` 返回 `{locator(file URI), bytes, hint}`，写失败返回 None 调用方保留原文（`_output_ref`/`clip_tool_result` 均按 None 回退全量文本）；引擎探针验证 roundtrip 与 failed_write_returns_none；真机 45000 字符工具输出落内容寻址文件、消息持 locator | ✅ CLOSED (W4-Z3) |
| S20 | deliverables `present` 工具 + per-turn `workspace/changes` | `tool-present/src/index.ts:40,105`；`workspace-changes/src/recorder.ts:351` | legacy agent catalog/dispatcher 有 `present` 工具与 artifact event；没有 per-turn `workspace/changes` recorder。真实模型 W3-X4 回合转去本地工具并触发 `AskUserQuestion`，未调用 `present`，故没有 live 行为证据 | PARTIAL (W3-X4: present implementation exists; changes recorder and live proof missing) |
| S23 | session telemetry ledger：每规范事件一条，`(sessionId,formatVersion,seq)` 去重 | `session-telemetry-otel/src/index.ts:121` | 没有规范 session-event ledger、formatVersion/seq 去重投影与重放；本批没有覆盖此 ledger 的回归 | ABSENT |
| S24 | product telemetry 调用方选事件，OTLP/HTTP，不自动采会话数据 | `host/product-telemetry-otel/src/index.ts:85` | 没有符合调用方 opt-in、OTLP/HTTP exporter 的 product telemetry seam；本批未添加外部 analytics SDK | ABSENT |
| S26 | DeepSeek 官方 API 增量上传会话日志，watermark + 8MiB 排空 | `session-log-deepseek/README.md:31,40` | 没有官方会话上传 API contract、增量 watermark 或 8 MiB drain path；本批不推测官方契约 | NOT-DONE (W3-X4: official upload contract unavailable in repository) |
| S27 | skill provider `list/get`、`skills/change` 失效、不完整观察不缓存 | `packages/skill/skill/src/index.ts:356,439` | skill catalog 有本地索引/递归扫描能力，但未找到稳定 provider `list/get` 与 `skills/change` 失效通知契约；本批未新增 provider 层行为 | PARTIAL (W3-X4: local index exists; provider invalidation contract missing) |
| S28 | 会话标题三来源 newest-wins，用户重命名钉住，`refresh()` 解钉 | `session-title/README.md:32` | `atlas_state_titles.py:43,84` 有 rank 顺序 + 用户标题 | PRESENT-PARITY |
| S29 | `@session` 引用：host 准入的另一会话快照 + untrusted 包裹 | `docs/subsystems/session-reference.md` | `read_session` 能按授权会话读取末 N 条文本，但无 `@session` 引用解析、host admission 与显式 untrusted 包裹 | PARTIAL (W3-X4: direct read exists; reference admission/marking missing) |
| S30 | 长期记忆：**DSH 完全没有** | `tool-ralph/README.md:36` | `memory/library/__init__.py:141,252` Markdown+git 页、三元组索引、30s→6h 退避队列、supersede 台账 | HARD (Atlas is already stronger; do not change product memory to imitate the missing DSH feature) |
| S31 | rewind：**DSH 没有**（`rewind` 只是类型字面量） | `conversation-context.ts:6` | 三模式 rewind + preview + redo + 文件还原（`conversations_router.py:1394,1568`） | **PRESENT-STRONGER** |
| S33 | 尝试级可观测：失败尝试也 durable 可重放 | `docs/architecture.md:120` | `run_replay/` 与 `run_checkpoints.py` 持久化失败尝试/checkpoint；本批 `test_run_replay.py` 通过；run log 不含模型/工具内容，且本批无真实失败回合重放 | PARTIAL (W3-X4: durable replay tests pass; live failed-attempt replay/content absent) |

---

## 三、插件与扩展（33 条）

### P0

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| X1 | 一切皆插件：service graph、`inject` 声明、typed event、无特权核心 | `docs/architecture.md:9,11`；`docs/cordis-primer.md:9-13` | `app_services.py:12-79` 51 字段扁平容器（全默认 None，回退模块单例）；`application.py:135` 手列 75 个 router | HARD (requires replacing the 52-field AppServices and 79-router composition root) |

### P1

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| X2 | 注册即可逆：每个注册返回 disposer，卸载即解绑 | `core/tools/src/index.ts:988` | plugin skill/command/hook/MCP 贡献均有 reverse-order disposer；async disconnect 由 `test_plugin_reload_idempotent.py::test_async_mcp_contribution_is_disposed_on_reload` 覆盖；本批没有真实模型触发插件 MCP 的 live 生命周期观察 | PARTIAL (W3-X5: async disposer unit proof; no live model lifecycle observation) |
| X3 | 插件管理 enable/disable 只改最后一层匹配的 `disabled`，报告 applied/restart-required | `boot/plugin-manager/src/index.ts:458,476` | `PluginRuntime.load_all/reload` 在重载前撤销旧 capability 与 hook owner；`test_plugin_reload_idempotent.py` 覆盖重复加载不重复注册；本批相关回归含一项插件 E2E 中文断言失败，且没有真实模型 enable/disable 行为观察 | PARTIAL (W3-X5: idempotent reload code/tests exist; live model behavior not verified) |
| X4 | profile/bundle/patch 有序层，按 row id 替换/插入，`--dump-config` 预览 | `docs/architecture.md:15-25` | patch 支持 row_id/order 与有序 listing；profile/bundle merge 和配置预览仍缺 | PRESENT-WEAKER |
| X5 | 安装/移除 bundle：包管理器解析依赖、lockfile 快照回滚、取消 | `plugin-manager/src/index.ts:374,497,645` | `plugins/runtime.py:851-982` 只支持本地 copy / marketplace / git，**无依赖解析、无回滚、无取消** | HARD (package-manager dependency resolution, lockfile rollback, and cancellation semantics are absent) |
| X6 | 版本兼容与豁免：peer range 检查 + per-profile `compatibility.json` 精确豁免 + `acceptRisk` | `plugin-manager/README.md:67` | `plugins/runtime.py:342-380` 只校验 manifest 形状 | HARD (requires package compatibility and persisted per-profile risk-acceptance semantics) |
| X7 | 安装脚本审批门：`pendingBuilds` 转 `allowBuilds`，逐包持久批准 | `plugin-manager/src/build-approval.ts:49,75` | 无安装脚本执行，故无门 | HARD (Atlas has no package build-script execution model or per-package approval ledger) |
| X8 | Agent 预设 = 子插件行 + isolate realm，注册表保留 revision | `packages/preset/agent-preset-registry/README.md:46-60` | `AgentPresetStore` 持久化 revision 化 capability set（tools/skills/MCP/model/mode），并在 run 时应用；尚无 isolate realm/子插件隔离 | PRESENT-WEAKER |
| X9 | 外部入口（webhook/ACP）必须带 agent preset + permission preset | `docs/subsystems/webhook.md:5,25` | automation/webhook 保存并验证两种 preset，AutomationEngine 将二者传入 `dispatch_turn`；ACP `session/new` / `session/prompt` 未接入 preset。ACP handler 在 `core/atlas/tools/app_server.py`，超出 W11 分配目录 | PARTIAL |
| X10 | 插件管理作为模型工具，8 个动作，每次需 danger-full-access 或逐次审批 | `plugin-manager/src/tools.ts:20-46` | `engine/kernel/tools.py:412-414` 只有 list/request install | PRESENT-WEAKER |
| X11 | bundle 清单带来源 official/availability/installed/覆盖行 | `plugin-manager/src/index.ts:282` | `plugins_router.py:39` → `discover()` 有基本字段，无 availability 模型 | PRESENT-WEAKER |
| X16 | progressive disclosure：durable `<available_skills>` + 摘要 diff 替换 + `/name` 内联注入 | `docs/subsystems/skills.md:227-233` | `/name` 匹配 user-invocable 技能并把完整指令内联到当轮 system prompt；持久化 catalog 的 added/updated/retired 以 revisioned `<skill_summary_diff>` 投递 | ✅ 已关闭（W10） |
| X21 | MCP 服务器 instructions 成为**独立 prompt 段** | `docs/subsystems/mcp.md:22-60` | `mcp_client.py` 保留 server instructions 独立集合，kernel prompt assembly 添加一段带 untrusted 标注的 server guidance；`test_mcp_instructions_section.py` 覆盖不内联工具描述、稳定排序和类型校验；本批未用真实模型观察该 prompt guidance 对工具行为的影响 | PARTIAL (W3-X5: separate prompt section unit-tested; live model behavior not verified) |
| X27 | client 扩展面：slots 注册、ConversationNodeDefinition、client 插件 | `docs/subsystems/slots.md:5-25` | `ConversationActivity.tsx` 有 `ConversationNodeDefinition` 注册表与 disposer，`ConversationNodeRegistry.test.tsx` 覆盖扩展 node 渲染/卸载；`App.tsx` 的页面与主视图仍使用静态导入/中央渲染分发，client plugin slots 尚未贯通 | PARTIAL (W3-X5: timeline node registry exists; application-wide slots/plugin loading absent) |
| X28 | 人类 slash 命令：插件注册 `{name,description,input,handler}`，不经模型执行，`command/run|done` 落日志 | `docs/subsystems/commands.md:5-95` | `/api/commands` 暴露 plugin handler；前端 slash 输入直接 POST `/api/commands/invoke`，handler 调用不经模型且 append-only 记录 command/run|done | ✅ 本轮关闭 |
| X24 | ACP：`session/new|list|resume|close|set_config_option|prompt|cancel`，per-session MCP 注入 | `acp/acp/README.md:60-80` | `tools/app_server.py:262-408` **自动批准所有工具**（`:114-122`）、拒绝 per-session MCP、无 resume/config-option | PRESENT-WEAKER |

### P2

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| X12 | Claude Code hooks 桥 | `experimental/hooks-claude-code/README.md` | `runtime/hooks.py:33-45` 28 个事件，`run_drive.py:3353` 接线 | PRESENT-PARITY |
| X13 | Codex hooks 桥 | `experimental/hooks-codex/README.md` | Plugin `.codex/hooks.json` 可装入 HookBus 的受支持事件；repo/user 通用来源与 trust surface 仍缺 | PRESENT-WEAKER |
| X14 | hook 逐条信任/审批门 | DSH **没有** | `runtime/hooks.py:679-735` fingerprint 作用域信任，fail-closed | **PRESENT-STRONGER** |
| X15 | skill 发现根阶梯 | `docs/subsystems/skills.md:64-76` | `skills/__init__.py:599,621-676` 优先级映射等价 | PRESENT-PARITY |
| X17 | `disable-model-invocation` / `user-invocable` 归一化 | `docs/subsystems/skills.md:100-110` | frontmatter 严格归一化两个布尔值；用户 slash 匹配和 `activate_for_model` 分别执行 invocation 门 | ✅ 本轮关闭 |
| X18 | skill provider 协议 + per-scope 分层 | `docs/subsystems/skills.md:9-30,188-200` | `SkillSource` + `with_sources` 请求作用域副本，同步 rglob | PRESENT-WEAKER |
| X19 | skill 新鲜度：chokidar 监听 + 读写路径即时失效 | `docs/subsystems/skills.md:78-81` | `skills/__init__.py:406-433` mtime+size 指纹，读时全量重扫 | PRESENT-WEAKER |
| X20 | skill 依赖/生命周期门 | DSH 无依赖契约 | `skills/__init__.py:547-590` 预检 mcp/python/commands | **PRESENT-STRONGER** |
| X22 | MCP liveness：500ms→30s 翻倍，10 次后移除工具，稳定后重置预算 | `mcp-client/README.md:64-67,89-93,129` | `tools/mcp_client.py` 500ms 起步、指数退避封顶 30s、10 次后转 `unreachable` 并移出工具索引、稳定 60s 后重置、显式重试解锁；8836 实测三个 MCP server 均 connected 且工具发现完成 | ✅ CLOSED |
| X23 | MCP resources + 作用域隔离 | `docs/subsystems/mcp.md:39-70` | runtime MCP server allow-list 贯穿 preset/request 能力、kernel 工具发现与派发，并由 `MCPClient.for_scope()` 隔离资源读取 | ✅ 本轮关闭 |
| X25 | SDK JSON-RPC：NDJSON、`initialize` 等树稳定、`session/wait`、关停 | `packages/sdk/README.md` | `tools/app_server.py:429` 协议 v1，无 settle barrier、无 wait | PRESENT-WEAKER |
| X26 | typed Client↔Host Remote gateway（装饰器生成描述符/编解码/客户端类型） | `docs/api-gateway.md` | 手写 FastAPI router + 手写 TS client，契约靠人 | ABSENT |
| X29 | webhook runtime：provider adapter + 可信规则返回 `WebhookSessionRequest` | `docs/subsystems/webhook.md:5,19-64` | 增加 `WebhookProvider`、HMAC provider adapter 与 typed `WebhookSessionRequest`；路由通过 provider 验证 | ✅ 本轮关闭 |
| X30 | SSH 作为整套执行世界（fs/subprocess/sandbox 一起搬） | `docs/subsystems/ssh.md` | `ssh.py:32-651` 工具级代理，只在 local_file/exec/git 上分流 | PRESENT-WEAKER |
| X31 | schedule 绑定原 session，到期回到该会话 | `docs/subsystems/schedule.md` | 两套并存：APScheduler（synthetic 会话）+ DBOS automation | PRESENT-WEAKER |
| X32 | 组合自省：`--dump-config` 带逐层来源 | `docs/architecture.md:41` | `introspect/registry.py:214` 运行时探针，无"这个值由哪层设置" | PRESENT-WEAKER |
| X33 | agent 类型 / subagent provider 缝 | `docs/architecture.md:130-136` | `agent/definitions.py:84-120` 多格式发现 + `agents/backends/` 适配器 | PRESENT-PARITY |

---

## 四、桌面与 UX（33 条）

### P1

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| D1 | 认证本地载体 + boot injection + OS 分配端口 | `apps/desktop/src/web-document.ts:41,72`；`main.ts:664,685` | Electron ready 时选择 loopback OS 临时端口并写入 `ATLAS_PORT`；backend spawn 继承该端口，preload 的 `apiBaseUrl`、健康探测和 token 注入共同使用它；显式 `ATLAS_PORT` 保持兼容 | PARTIAL (WAVE2-V8: 端口注入与分配已接通并有单测；完整 renderer vitest 仍有既有失败，未满足批次 CLOSED 门槛) |
| D2 | 两进程 typed IPC 生命周期（ready/fatal/shutdown-complete/quit-inspection） | `apps/desktop/src/host-process.ts:189,57-78` | shared IPC 定义 `BackendLifecycleEvent`；main 在 ready/fatal/shutdown-complete/quit-inspection 时发布，preload 提供可卸载的 typed 订阅并在订阅后补取最新状态 | PARTIAL (WAVE2-V8: lifecycle typed IPC 已接通；完整 renderer vitest 仍有既有失败，未满足批次 CLOSED 门槛) |
| D3 | 流式增量：chunk 折叠进 per-node state，重连重放压缩流 | `api/session-controller/.../events.ts:8`；`ui-conversation/.../assembler.ts:174,364` | 连续 `message.delta` 折叠进现有 reply node；`run.phase/usage/todos/context` 等不投影事件不再触发重建；其余结构事件仍经全量 `buildTimeline` 投影，重连仍逐事件回放 | PARTIAL (WAVE2-V8: 高频 delta 与非投影状态已增量处理；结构节点增量构建及压缩重放仍缺) |
| D4 | keyed ConversationNode renderer 注册表 | `ui-chat/.../register-node-renderers.ts:39-69` | `timeline.ts:73-99` 静态联合 + `ConversationActivity.tsx:42` 单 switch，无注册 API | ABSENT |
| D5 | durable 附件暂存：内容寻址、先存后发、进度、可取消 | `docs/subsystems/attachment.md`；`client/file-upload/src/client/contract.ts` | `renderer/services/attachmentStaging.ts` 以 SHA-256 存入 IndexedDB；`App.tsx` 的文件、图片、白板图和最近截图路径先暂存再进入发送队列，显示进度、允许取消，并把暂存引用随会话草稿恢复。发送仍将 base64 内联到 run.start；缺少 UI 重载和有效真实模型端到端证据 | PARTIAL |
| D6 | 结构化草稿：chip 进文本模型、per-session 语义草稿、重载存活 | `ui-conversation/.../ReferenceChip.tsx` | `renderer/services/composerDraft.ts` 按会话保存文本、mentions 和暂存附件引用；提交时将所有 chip 序列化进模型文本。单测覆盖序列化/隔离，尚未有真实 UI 重载或模型回合通过证据 | PARTIAL |
| D7 | follow 重连：首帧 header+tail+cursor+投影基线，`page()` 补缺口 | `docs/subsystems/web-client.md:48` | adapter 为空 renderer 投影从序号 0 重放；服务端提供有界 event page、header/tail/cursor/projection baseline，断层时先补连续页再接回 WebSocket | PARTIAL (WAVE2-V8: page 修复路径和服务端单测已接通；完整 renderer vitest 仍有既有失败，未满足批次 CLOSED 门槛) |
| D8 | 右侧栏：split 树、浮动面板、可插 tab 类型、per-session 布局 | `docs/subsystems/sidebar-right.md:26,74`；`ui-dockkit/.../FloatLayer.tsx` | `shell/Inspector.tsx:28,156` 单列固定 union，布局不持久 | PRESENT-WEAKER |
| D9 | 应用内连接恢复控件（可点击重试 + 恢复确认） | `ui-primitives/.../ConnectionIndicator.tsx:6-40` | 断连提示提供键盘可操作的“重试连接”；桌面重启动作先确认 | ✅ 本轮关闭 |
| D10 | 自动更新生命周期：调度 + 退避 + 抖动 + journal + 强制版本 | `apps/desktop/src/update-coordinator.ts:16`；`update-schedule.ts:20-26` | `frontend/src/renderer/services/update-coordinator.ts:23,80`、`UpdateBanner.tsx:22,39` 已接入自动检查、抖动退避和 200 条本地 journal；强制版本策略尚未接入 | PARTIAL |

### P2

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| D11 | 回合 diff 审阅（并排/换行/hover 预览/二进制标记） | `ui-deliverables/.../ReviewTab.tsx:107,131` | `ChangesPanel.tsx:199,343` hunk 级接受/拒绝 + 行评论（Atlas 更强），无并排 | PRESENT-PARITY（动作更强，阅读更弱） |
| D12 | 每回合变更文件摘要 | `workspace-changes/src/recorder.ts:230` | `run_drive.py:1165` checkpoint manifest difflib，渲染成一行脚注 | PRESENT-PARITY（数据）/WEAKER（呈现） |
| D13 | `present` 声明的交付物卡片 | `tool-present/src/index.ts:81`；`PresentedFileCard.tsx` | `agent/tool_catalog.py` 暴露 `present`；`agent/presentation.py` / `tool_node.py` 只接受当前本地工作区内的现存文件并发出 `artifact_created`；`api/run_drive.py` 转发标题/摘要；`runtimeEvents.ts` 把自定义卡片信息写入 renderer artifact store | ✅ CLOSED |
| D14 | 问题意图标签（`plan-review` 路由到专用面板） | `docs/subsystems/user-questions.md:25` | `intent=plan-review` 的 `input.required` 渲染进入现有计划审查、批准、修改控件 | ✅ 本轮关闭 |
| D15 | 审批接管 composer（不可滚走） | `ui-approval/.../ApprovalPanel.tsx:1-62` | `ConversationActivity.tsx:351-400` 内联卡片（选项更丰富），可被滚走 | PRESENT-PARITY（选项强，位置弱） |
| D16 | 文档预览 renderer 注册表 | `ui-sidebar-documentpreview/src/client/*` | `FilesPanel.tsx:635-690` 有 md/图片/PDF/xlsx/pptx/HTML | PRESENT-PARITY |
| D17 | 命名空间 i18n | `client/locale/src/locale-settings.ts:16` | `frontend/src/renderer/services/i18n.ts:11,28,143` 新增 namespace 注册/查询 API，`UpdateBanner.tsx:5,73` 使用 updates namespace；7.7k 条全局目录及 MutationObserver 替换尚未迁移 | PARTIAL |
| D18 | 半径 token 尺度 + token-only 颜色（spec 强制） | `docs/ui-radius.md`；`ui-theme/src/styles/base.css` | `shell/themes.ts:4` 3 套主题 + 自定义 7 色，组件里 `rounded-[9px]` 随意 | PRESENT-WEAKER |
| D19 | 无障碍契约（框架级 focus/IME/reduced-motion） | `ui-theme/src/styles/focus.css`；`packages/client/shortcuts` | `styles/app.css:205` 全局 focus-visible；手写 aria | PRESENT-WEAKER |
| D20 | 单实例 + deep link | `apps/desktop/src/single-instance.ts:16` | `electron.ts:1171-1185` | PRESENT-PARITY |
| D21 | 托盘 | `apps/desktop/src/tray.ts:13-45` | `electron.ts:229-280` 更丰富（后端阶段/组件状态/安全模式） | PRESENT-PARITY（Atlas 更强） |
| D22 | 原生菜单 + 快捷键注册表 | `apps/desktop/src/keybindings.ts` | `electron.ts:614`；`services/shortcuts.ts` + Keymap | PRESENT-PARITY |
| D23 | 崩溃恢复（含"禁用全部插件重启"） | `apps/desktop/src/main.ts:80-100` | `electron.ts:121` 脱敏崩溃报告 + 安全模式 | PRESENT-WEAKER |
| D24 | 消息分支/fork（任意 assistant 尾） | `tool-.../TurnTailNodeView.tsx:69,98` | `useAtlasStore.ts:189`、`App.tsx:3024` fork/fork+summary、`ForkTree.tsx` | PRESENT-PARITY（Atlas 更强） |
| D25 | rewind | **DSH 无** | 三模式 + preview + redo | **PRESENT-STRONGER** |
| D26 | plan 模式/计划审阅 | `docs/subsystems/plan.md` | `ConversationActivity.tsx:557` + UltraplanPanel | PRESENT-PARITY |
| D27 | 队列/steer/redirect | `ui-conversation/.../QueueDock.tsx` | `ConversationQueuePanel.tsx`；`useAtlasStore.ts:22,760` | PRESENT-PARITY |
| D28 | 语音输入 | `docs/subsystems/voice-input.md:27` | `VoiceHud.tsx` + `App.tsx:1450-1530` + TTS + 通话浮层 | PRESENT-PARITY（Atlas 更宽） |
| D29 | 更早历史分页 | `docs/subsystems/web-client.md:48` | `useAtlasStore.ts:452` 按 id 游标 + 满页启发式 | PRESENT-WEAKER |
| D30 | 备选会话视图（Chat / Trajectory） | `ui-trajectory/.../TrajectoryView.tsx` | Rollout 提供可读 trajectory 与原始事件切换；完整 Chat/Trajectory 双模式会话 renderer 尚未实现 | PRESENT-WEAKER |
| D31 | 多窗口/分栏 | DSH 单窗口 | `electron.ts:563,600`；`PaneWorkspace.tsx:28` 递归 split 树 | **PRESENT-STRONGER** |
| D32 | 消息级操作 | `MessageIconActions.tsx:11-15`（仅复制+分支） | `App.tsx:3007-3032` 编辑重发/fork/fork+摘要/rewind/copy | **PRESENT-STRONGER** |
| D33 | slash 命令注册表 | `docs/subsystems/commands.md:5-40` | `services/slashCommands.ts:29,52` 有去重与模糊排序；命令源仍是 `App.tsx:2240-2290` 静态数组 | PRESENT-PARITY |

---

## 五、施工优先级（按依赖排序）

**第 0 层（地基，其它一切依赖它）**
1. `S1+S2+E1`：只追加会话事件日志 + `deriveMessages()` + surface replace。
2. `X1`：把 `AppServices` 变成真正的服务/接缝组合根（先做注册表，不求重写全部）。

**第 1 层（不改地基就能独立交付，且用户可感知）**
3. `E3+E4`：工具流水线三瀑布 + 输出契约（`post-execute` 统一做截断/脱敏/落 spill）。
4. `E9` ✅ 已完成、`E7` ✅ 已完成、`X22` ✅ 已完成。
5. `S3`：读到更新版本 DB 必须拒绝（低成本、防数据损坏）。
6. `S17`：会话导出 HTTP 路由（`export_session` 已有，只缺接线）。
7. `D4`：节点渲染注册表（消除中央 switch，后续 UI 才有扩展面）。

**第 2 层（策略面，需要第 0 层才有意义）**
8. `E12+E13`：审批四值 + durable ask/decide + 权限预设绑沙箱。
9. `S6`：checkpoint fail-closed。
10. `S19+D5`：durable 附件（图片可重发）。

**明令不动（Atlas 已更强，别为"对齐"退化）**
`S30` 长期记忆、`S31` rewind、`X14` hook 信任门、`X20` skill 依赖门、
`D25` rewind、`D31` 多窗口/分栏、`D32` 消息操作、`D21` 托盘、`E33` 写路径诊断增量。

---

## 六、本次已落地的改动（可复核）

| 改动 | 文件 | 测试 |
|---|---|---|
| MCP 重连预算：10 次上限、`unreachable` 终态、稳定 60s 后重置、显式重试解锁、batch 路由纳入终态 | `core/atlas/tools/mcp_client.py`、`core/atlas/api/tools_router.py` | `core/tests/test_mcp_reconnect_budget.py`（6 项） |
| 并发安全按参数判定 + 派发前复检 + demoted 调用成 barrier | `core/atlas/engine/kernel/tools.py` | `core/tests/test_tool_scheduler_concurrency.py`（3 项） |
| plan 模式引导按 **live** mode 每轮重建；`EnterPlanMode/ExitPlanMode` 通过共享 `PlanMode` 实例切换，而非写副本 | `core/atlas/engine/kernel/loop.py`、`core/atlas/api/run_drive.py` | `core/tests/test_plan_mode_live_guidance.py`（6 项） |
| 会话 DB 版本前进拒绝（`SchemaTooNewError`），不再让旧构建写坏新库 | `core/atlas/engine/state/atlas_state_schema.py`、`core/atlas/engine/state/atlas_state_errors.py` | `core/tests/test_state_schema_refusal.py`（3 项） |
| 会话导出 HTTP 路由 `GET /api/conversations/{id}/export`，接通已存在的 `export_session` | `core/atlas/api/conversations_router.py` | `core/tests/test_conversation_export_route.py`（4 项） |
| 审批四值语义 `allowed-once`/`rejected`/`cancelled`/`unavailable` + 每值不同模型可见理由；loop 内 7 处 `== "allow"` 全部替换 | `core/atlas/approval_outcome.py`（新）、`core/atlas/engine/kernel/loop.py` | `core/tests/test_approval_outcome.py`（20 项） |
| 工具结果终化器接缝：有序组合、失败跳过、可逆注册、只允许改内容不得改结果；已接 `AppServices → RunRequest → AgentRunContext → kernel` 全链路 | `core/atlas/engine/kernel/tool_finalize.py`（新）、`core/atlas/engine/kernel/loop.py`、`core/atlas/agent/run_phases.py`、`core/atlas/api/app_services.py` | `core/tests/test_tool_result_finalize.py`（8 项）+ `core/tests/test_tool_finalize_wiring.py`（6 项） |
| 插件 `load_all` 幂等化：重载前按来源清理 capabilities/hooks，切换不再重复注册、不再让插件假性报错 | `core/atlas/plugins/runtime.py` | `core/tests/test_plugin_reload_idempotent.py`（5 项） |
| 禁用插件真正撤回：`set_enabled(False)` 同步撤销 capability 与 hook，而不是只 `_loaded.pop` | `core/atlas/plugins/runtime.py` | `core/tests/test_plugin_disable_withdraws.py`（4 项） |
| MCP instructions 改为**独立 prompt 段** + 工具描述只留短指针；顺带修掉 `str(MagicMock)` 会被当成 instructions 的脆弱点 | `core/atlas/tools/mcp_client.py`、`core/atlas/engine/kernel/loop.py` | `core/tests/test_mcp_instructions_section.py`（6 项） |

定向回归：**112 项通过**（上述 11 个新测试文件 + `test_plugins.py` + `test_kernel_tool_timeout.py` + `test_mcp_batch_reconnect.py` + `test_event_contract.py`）。

### 真实 MCP 数据佐证（`rea` 服务器）

实测本机 `rea` MCP 服务器挂 **184 个工具**、`instructions` **304 字符**。
按旧逻辑每个工具描述都抄一遍 → 约 **56 KB 重复文本/请求**；改后该文本只出现 1 次，工具描述长度 29–62 字符（`git__git_status` 29、`git__git_diff_staged` 40）。

### 实机验证记录

| 验证 | 方式 | 结果 |
|---|---|---|
| 导出端到端 | 起真实后端 `:8799`，`GET /api/conversations/mv-f97e1a6b/export` | **200 / 18391 字节**，`export_format=atlas.session.v1`，6 条真实消息 |
| 未知会话 | 同上 | **404**（路由已注册且校验生效） |
| 引擎层 6 项 | `core/scripts/dsh_parity_engine_proof.py` | plan enter/approve、guidance 文本、只读工具过滤、审批四值、scheduler barrier 全部符合预期 |
| 真实模型·纯文本一轮 | WS `run.start` → 后端 `:8801`，`deepseek-v4.1-flash` | ✅ **`run.completed`，回复 `OK`**（input 9432 / output 2），模型走 Clash `127.0.0.1:7897` |
| 真实模型·带工具一轮 | 同上，要求列出 kernel 目录 | ✅ **`run.completed`**，5 次请求、两批 `local_exec`、`tool.completed` 正常；回复准确列出 **18 个 `.py`**（含新文件 `tool_finalize.py`），input 31911 / output 412 |
| 真实模型·代理持久化 | 停掉带 `http_proxy` 的后端，改用 `:8802`（**清空所有代理环境变量**） | ✅ 仍成功：`test-connection` ok，对话回 `STABLE`，且**缓存命中**（cached 1152 / uncached 8197）——证明走的是 Atlas 已存的 `model_network` 配置，不是环境变量 |

> 模型通道修复记录：`d1api.xin` 的 `deepseek-v4.1-flash` key 此前为空（401 根因）。已通过 Atlas 自己的 `set_model_api_key` 写入 **Windows 凭据管理器**（不落明文配置）；Clash 代理 `http://127.0.0.1:7897` 通过 `PUT /api/model-network-settings` 存入凭据库，`user-settings.json` 里只有可读标签。实测经 Clash **1.6–2.6s**，直连 **24.9s**，所以代理是必需的。前提：`keyring` 需已安装（`pyproject.toml:74` 已声明，当前环境原先缺失，已补装 25.7.0）。
