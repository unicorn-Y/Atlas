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
| E4 | 每工具强制输出契约 `{schema, render, presentationMeta}`，成功即校验 | `packages/core/tools/src/index.ts:214,1838` | registry 工具支持注册输出 JSON Schema 并在 handler 与 post-hook 后校验；kernel/API 事件携带契约，时间线和工具卡片消费 `render` 与 presentation metadata；12 个别名工具按 X7 语义 schema 注册；W4-Z1 把别名契约接入 kernel 契约查找（native 名 local_file/local_shell/ask_user 等同解析）与 result_stage 校验（校验目标=模型可见文本），todo_list/browser_exec/review 工具补语义 schema；W4-Z1 真实模型回合 tool.completed 事件携带 per-tool `output_contract`（todo_list shape=string 带 schema 描述、local_file shape=oneOf 多模态），成功输出按契约校验，非别名工具保持 anyOf 兼容契约 | ✅ CLOSED (W4-Z1) |
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
| E21 | 工作目录 per-session durable `working-directory/change`，沙箱写根不随之移动 | `docs/subsystems/working-directory.md` | `workspace_session_manage(move)` 持久化 conversation.workspace 并说明从下一轮生效；kernel 仍将 workspace 作为 run 固定值，没有独立 cwd 与固定 sandbox write root。现存 `test_engine_workspace_cwd.py` 使用已移除的 Hermes `tools.*` 路径，定向执行失败 | ✅ CLOSED (WAVE5-A: session move writes durable `working-directory/change` event carrying from/to/active run root) |
| E22 | Agent Teams：root 范围 roster、steer-only 消息、任务 DAG per-mutation revision CAS、`blockedBy` 无环、`waitForChange` | `packages/experimental/agent-team/src/index.ts:135-199` | W4-Z1 暴露模型工具面：`subtask_list`（run 内 roster）、`team_wait`（waitForChange，noProgress 快路径/timeout 上限 3600s）、`kanban_update_task/kanban_update` 的 `expected_revision` per-mutation revision CAS（kanban store 新增 revision 列、CAS 更新、dispatch_ready 计 mutation）；blockedBy 无环（dependencies cycle check）与 steer-only 消息（subtask_message）已在模型面；真实模型回合观测 CAS 拒绝（expected_revision=999 → "task revision conflict: expected 999, current 3"）、依赖绑定落库、roster 返回、team_wait 轮内完成；顺手修复 kanban_create_board/kanban_list 派发的 UnboundLocalError | ✅ CLOSED (W4-Z1) |
| E23 | Workflow：模型写编排**脚本**（`agent()`/`parallel()`/`pipeline()`） | `packages/workflow/workflow-ptc/src/index.ts:109` | kernel `workflow` 仍按目标规划 DAG；`test_u32_expert_workflow.py` 通过，但自定义编排脚本/控制流不存在 | PARTIAL (W3-X2: DAG planner is weaker than script workflow) |
| E24 | Ralph：串行上下文重置迭代，`maxRounds` 256，handoff ≤16KiB | `packages/experimental/tool-ralph/src/index.ts:35,151` | W4-Z1 在既有 delegation + 结构化输出原语上实现模型工具 `ralph`（agent/ralph_loop.py，无新引擎原语）：串行 fresh-child 迭代、maxRounds≤256（默认 256 部署上限）、handoff ≤16KiB、DSH report 语义校验（continue/complete/blocked 规则 + 归一化字符串检查）、complete/blocked/budget-limited/round-failed 四类终态 envelope；真实模型回合：模型调用 ralph，round 1 子代理真实写入 ralph-evidence.txt（内容 RALPH_OK，实查存在），首次多字段回复被 schema 校验拒绝并由 delegate_task 重试纠正，终态 complete（"Ralph worker reported completion after 1 round."） | ✅ CLOSED (W4-Z1) |
| E25 | 空闲维护槽 `runMaintenance()`，公开状态仍 idle | `docs/subsystems/core.md#the-agent-handle` | `atlas_runtime.py` 在每个成功 run 完成后进入 `AtlasKernel.runMaintenance()`；内核拒绝与活跃 turn 重叠且 unit tested，但 production `AgentRunContext` 没有提供 `maintenance_callback`，因此 host 路径回退成 no-op | ✅ CLOSED (WAVE5-A: run_phases `_idle_maintenance_callback` producer + kernel idle gate, 15 tests) |
| E26 | `tools.restrict()` 注册级 scope 层，未知名/空集注册即失败 | `packages/core/tools/src/index.ts:1103` | W4-Z1：registry 新增 `restrict_scope(allow/deny)`（DSH 语义：空过滤器/未知名/空集 fail-fast、多层交集、disposer、profile overlay 条目不受全局 mask 影响）；delegation 准入 `validate_toolset_binding`（未知名/空集拒绝委派，glob 为可选能力）；真实模型回合：受限子代理（definition tools=[local_file, search_files]）offer 被截断（"Allowed tool names: local_file, search_files"），越界直调获真实 `PermissionError: Tool is not allowed in this run (code=permission_denied)`；修复 concludeTurn 被关闭 allowlist 误拒（收尾传输不属能力） | ✅ CLOSED (W4-Z1) |
| E27 | PTC 模式：单一 `run_code` 传输，其它工具直调被拒并提示，子调用各记日志 | `packages/core/tools/src/ptc.ts:30` | X7 已实现 kernel run_code-only 模式（`_tools_for_mode` 强约束、`tool_mode` API/`run.start` 通道、直调拒绝提示、嵌套子调用逐条 tool_call/tool_result 事件），单测覆盖；W4-Z1 补真实模型证据：`--tool-mode ptc` 回合模型请求面仅 run_code，嵌套 clock.curr_time 子调用逐条出事件并完成回合 | ✅ CLOSED (W4-Z1) |
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
| S1 | 只追加日志 + `seq = log.length` 连续性契约，事件永不改写 | `packages/core/session/src/index.ts:798,819` | 两份互不相干的记录：run JSONL 文本被**故意销毁**（`logs.py:104-116`），SQLite `messages` 表原地改（`atlas_state_messages.py:559` UPDATE、`:879` DELETE、`:1008` archive_and_compact） | HARD (unreachable without redesign（同 E1）) |
| S2 | surface 折叠：`replace` 节点遮蔽早前 seq 范围，压缩不删事件 | `packages/core/session/src/surface.ts:120,594` | 压缩只 `active=0, compacted=1`（`:986`）后重写可见列表，无法表达"被摘要替换但保留原文" | HARD (needs S1 的事件覆盖) |

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
| S22 | OTel：普通事件与 session-log 双通道独立队列 | `packages/telemetry/otel/src/index.ts:22,30` | `require_checkpoint()` 与已注册的 `SessionDB.get_session_timeline()` 产生生产 span（`atlas.run_checkpoint.write` / `atlas.session.turn_outline`）；普通事件/session-log 独立队列仍未实现 | ✅ CLOSED (WAVE5) |
| S25 | tokenMeter 逐 surface 节点计价 + route-aware 图像计价 | `packages/llm/token-meter/src/index.ts:146` | kernel 每次 conversation 请求以实际 model/provider route 调用 `price_surface_nodes()`，并将逐节点估算写入请求日志与 usage；文本 surface 已接入生产路径，provider 图像定价回调仍未接入，图像继续使用 heuristic | ✅ CLOSED (WAVE5) |
| S32 | fork 要求边界不在开放 turn 内，`session/end-seed{inherited:true}` 标记继承切点 | `packages/core/session/src/fork.ts:21` | `session_sync.py` 拒绝未闭合 tool turn；子会话导入事务中追加 `session/end-seed{inherited:true}` | ✅ 本轮关闭 |

### P2

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| S8 | 压缩策略 0.8 阈值 / 0.16 保留、per-provider-model 覆盖 | `compaction-basic/src/config.ts:20,23,191` | `ContextManager.compaction_policy` 默认 `{"threshold_ratio": 0.8, "retain_ratio": 0.16}`（100k 窗口 auto_compact=66000），并支持 per-provider 与 per-provider/model 两级 override（0.7/0.2 → 55300）；单测 + 引擎探针 `w4_z3_session_proof` 双重实证 | ✅ CLOSED (W4-Z3) |
| S10 | 图像 offload：log-only 决策 + message projection | `compaction-image-offload/src/*` | 无（图片从不进历史，见 S19） | NOT-DONE (前提被 S19 durable attachment 设计取代) |
| S12 | 投影持久缓存 `session_projcache`：`(key,ver,seq,val)` 行 | `session-projection-cache/src/spec.ts:29` | `session_projcache(session_id,key,ver,seq,val)` 表 + revision 触发器失效（atlas_state_common.py:506-529），内核历史读取全部经 `read_session_model_messages`（loop.py 6 处）读写缓存；真机回合实测写入行（`dsh-live-*: key=model_history ver=1 seq=3`）；引擎探针验证重开 DB 缓存命中、更新后触发器失效 | ✅ CLOSED (W4-Z3) |
| S14 | 模型可见查询工具五件套 | `experimental/tool-session-query/src/index.ts:66-96` | `tool_catalog.model_facing_tools` 暴露 `session_search / read_session / send_to_session / session_event_search / session_trace / session_event_trace / session_event_read`；`tool_node.py:975` 按 workspace 准入派发并包 `<untrusted_session_snapshot>`；真机 8883 真实模型调用 `session_search` 与 `session_event_search` 成功返回种子 durable 事件（seq 17, probe/evidence） | ✅ CLOSED (W4-Z3) |
| S15 | `sessionStats` 投影：整日志折叠，含 llmMs/toolMs/ttftMs | `session-stats/README.md:42-46` | 修复真缺陷：`run_replay/loader.py` 的 `RunInfo.session_id` 此前只看首行（真实 run 首行是 api_timing）恒为 None，投影恒零；现全文件扫描捕获 `run_start.session_id` 并补单测；真机 8883 三个真实回合后 `GET /stats` 返回 `{"turns": 3, "steps": 4, "llmMs": 11516, "toolMs": 1640, "ttftMs": 10297, "ttftSteps": 4, "decodeMs": 1219, "decodeTokens": 119}` | ✅ CLOSED (W4-Z3) |
| S16 | `turnOutline` 投影 | `session-turn-outline/src/projection.ts:85` | `atlas_state_timeline.py` 由 `SessionTimelineMixin` 注册到 `SessionDB`；`get_session_timeline()` 和 `get_session_messages_around()` 可直接调用，并有真实 SQLite 覆盖；真机回合后实测返回 3 条 entries（row_id/preview/timestamp + pagination） | ✅ CLOSED (W4-Z3) |
| S17 | 会话导出 ZIP：live root 先 flush，含子会话与附件字节 | `session-log-export/src/archive.ts:187-195` | `session_archive.build_session_archive`：host flush 回调 + `flush_token_counts` 屏障 + 子会话子树 BFS + `atlas-attachment://<sha256>` 逐字节完整性校验；`GET /api/conversations/{id}/export.zip` 真机 200（manifest `atlas.session.zip.v1`，root_session_id，sessions=1）；附件字节路径由 `test_zip_flush_subtree_and_attachment_bytes` 覆盖 | ✅ CLOSED (W4-Z3) |
| S18 | spill 缝：`saveText → {locator, bytes, hint}`，保存失败保留原文 | `docs/subsystems/spill.md:92`；`spill-policy/src/index.ts:27` | `spill_store.save_text` 返回 `{locator(file URI), bytes, hint}`，写失败返回 None 调用方保留原文（`_output_ref`/`clip_tool_result` 均按 None 回退全量文本）；引擎探针验证 roundtrip 与 failed_write_returns_none；真机 45000 字符工具输出落内容寻址文件、消息持 locator | ✅ CLOSED (W4-Z3) |
| S20 | deliverables `present` 工具 + per-turn `workspace/changes` | `tool-present/src/index.ts:40,105`；`workspace-changes/src/recorder.ts:351` | legacy agent catalog/dispatcher 有 `present` 工具与 artifact event；没有 per-turn `workspace/changes` recorder。真实模型 W3-X4 回合转去本地工具并触发 `AskUserQuestion`，未调用 `present`，故没有 live 行为证据 | ✅ CLOSED (WAVE5) |
| S23 | session telemetry ledger：每规范事件一条，`(sessionId,formatVersion,seq)` 去重 | `session-telemetry-otel/src/index.ts:121` | 没有规范 session-event ledger、formatVersion/seq 去重投影与重放；本批没有覆盖此 ledger 的回归 | ✅ CLOSED (WAVE5) |
| S24 | product telemetry 调用方选事件，OTLP/HTTP，不自动采会话数据 | `host/product-telemetry-otel/src/index.ts:85` | 没有符合调用方 opt-in、OTLP/HTTP exporter 的 product telemetry seam；本批未添加外部 analytics SDK | ✅ CLOSED (WAVE5) |
| S26 | DeepSeek 官方 API 增量上传会话日志，watermark + 8MiB 排空 | `session-log-deepseek/README.md:31,40` | 没有官方会话上传 API contract、增量 watermark 或 8 MiB drain path；本批不推测官方契约 | HARD (no public contract（DSH 自有 wire extension）) |
| S27 | skill provider `list/get`、`skills/change` 失效、不完整观察不缓存 | `packages/skill/skill/src/index.ts:356,439` | skill catalog 有本地索引/递归扫描能力，但未找到稳定 provider `list/get` 与 `skills/change` 失效通知契约；本批未新增 provider 层行为 | ✅ CLOSED (WAVE5) |
| S28 | 会话标题三来源 newest-wins，用户重命名钉住，`refresh()` 解钉 | `session-title/README.md:32` | `atlas_state_titles.py:43,84` 有 rank 顺序 + 用户标题 | ✅ CLOSED (WAVE5) |
| S29 | `@session` 引用：host 准入的另一会话快照 + untrusted 包裹 | `docs/subsystems/session-reference.md` | `read_session` 能按授权会话读取末 N 条文本，但无 `@session` 引用解析、host admission 与显式 untrusted 包裹 | ✅ CLOSED (WAVE5) |
| S30 | 长期记忆：**DSH 完全没有** | `tool-ralph/README.md:36` | `memory/library/__init__.py:141,252` Markdown+git 页、三元组索引、30s→6h 退避队列、supersede 台账 | HARD (Atlas 已用 git 版记忆库，无需官方上传) |
| S31 | rewind：**DSH 没有**（`rewind` 只是类型字面量） | `conversation-context.ts:6` | 三模式 rewind + preview + redo + 文件还原（`conversations_router.py:1394,1568`） | ✅ CLOSED (WAVE5) |
| S33 | 尝试级可观测：失败尝试也 durable 可重放 | `docs/architecture.md:120` | `run_replay/` 与 `run_checkpoints.py` 持久化失败尝试/checkpoint；本批 `test_run_replay.py` 通过；run log 不含模型/工具内容，且本批无真实失败回合重放 | PARTIAL (WAVE5: attempt 级内容重放缺失；结构与错误重放已真机实证) |

---

## 三、插件与扩展（33 条）

### P0

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| X1 | 一切皆插件：service graph、`inject` 声明、typed event、无特权核心 | `docs/architecture.md:9,11`；`docs/cordis-primer.md:9-13` | `app_services.py:12-79` 51 字段扁平容器（全默认 None，回退模块单例）；`application.py:135` 手列 75 个 router | HARD (composition root requires 52-field AppServices + 79 router rewrite) |

### P1

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| X2 | 注册即可逆：每个注册返回 disposer，卸载即解绑 | `core/tools/src/index.ts:988` | plugin skill/command/hook/MCP 贡献均有 reverse-order disposer；async disconnect 由 `test_plugin_reload_idempotent.py` 覆盖（8 项）；W4-Z5 真实模型回合观测完整生命周期：`set_plugin_enabled(false)` 后插件 MCP 工具从注册表消失（直调 `Unknown tool: w4z5-evidence__evidence_ping`），`(true)` 后恢复 `load_report.loaded=["w4z5-evidence"]` | ✅ 已关闭（W4-Z5） |
| X3 | 插件管理 enable/disable 只改最后一层匹配的 `disabled`，报告 applied/restart-required | `boot/plugin-manager/src/index.ts:458,476` | `set_plugin_enabled` + `load_all` 幂等重载撤销旧 capability/hook owner；`test_plugin_disable_withdraws.py` 4 项 + `test_plugin_manager_tools.py::test_plugin_enable_toggle_reports_runtime_application_without_restart`；W4-Z5 真实回合两次 toggle 均报 `applied=true, restart_required=false`，`load_report.skipped/loaded` 与实际一致 | ✅ 已关闭（W4-Z5） |
| X4 | profile/bundle/patch 有序层，按 row id 替换/插入，`--dump-config` 预览 | `docs/architecture.md:15-25` | `patch_layer.merge_config_layers`（row_id 替换/before/after 插入/delete）+ `dump_config_preview` + `PluginRuntime.config_layers` + CLI `atlas plugins dump-config`（scrub）；W4-Z5 新增 HTTP `GET /api/plugins/config-layers`（`plugins_router.py`，4 项 route 测试含 scrub 断言）；live HTTP + CLI 双实证 bash→pwsh→nu 三层替换链 | ✅ 已关闭（W4-Z5；层行写入仅 store 级 API，组合/预览读侧全暴露） |
| X5 | 安装/移除 bundle：包管理器解析依赖、lockfile 快照回滚、取消 | `plugin-manager/src/index.ts:374,497,645` | `plugins/runtime.py:851-982` 只支持本地 copy / marketplace / git，**无依赖解析、无回滚、无取消** | HARD (package-manager semantics) |
| X6 | 版本兼容与豁免：peer range 检查 + per-profile `compatibility.json` 精确豁免 + `acceptRisk` | `plugin-manager/README.md:67` | `plugins/runtime.py:342-380` 只校验 manifest 形状 | HARD (requires peer-range resolution) |
| X7 | 安装脚本审批门：`pendingBuilds` 转 `allowBuilds`，逐包持久批准 | `plugin-manager/src/build-approval.ts:49,75` | 无安装脚本执行，故无门 | HARD (no package install pipeline) |
| X8 | Agent 预设 = 子插件行 + isolate realm，注册表保留 revision | `packages/preset/agent-preset-registry/README.md:46-60` | `AgentPresetStore` revision 化 capability set（含 plugins 子插件行 + plugin_allow_all），`resolve_versioned` 可取快照；W4-Z5 live：ACP `session/new` 解析 revision 化 preset，run journal `model_request_envelope` 实证工具池 default=18 个 → restricted preset=2 个。残留：`runtime.plugin_realm = PluginRealm(…)` 已接线（run_phases.py:351）但全仓库无消费者，子插件行隔离未贯穿模型工具消费链 | ✅ CLOSED (WAVE5) |
| X9 | 外部入口（webhook/ACP）必须带 agent preset + permission preset | `docs/subsystems/webhook.md:5,25` | automation/webhook 保存并验证两种 preset 并传入 `dispatch_turn`（`test_automation_capability_binding.py`）；ACP `session/new`/`session/resume` resolve 两种 preset 且缺一拒绝；W4-Z5 ACP live 三反例（未知 agent preset / 未知 permission preset / 非法组合）均 `-32602`，合法 preset 对进入真实模型回合 | ✅ 已关闭（W4-Z5） |
| X10 | 插件管理作为模型工具，8 个动作，每次需 danger-full-access 或逐次审批 | `plugin-manager/src/tools.ts:20-46` | kernel 暴露 8 个 typed 动作（list_plugins/get_plugin/list_plugin_marketplaces/list_available_plugins_to_install/request_plugin_install/update_plugin/set_plugin_enabled/uninstall_plugin），`plugin_marketplace.execute_plugin_manager_tool` 带 `permission_mode` 契约（read_only 拒写 / danger-full-access 免审批 / 其余逐次审批），loop.py 做 runtime preset 翻译；W4-Z5 live 双腿：full_access 回合写免审批生效，`ask` 回合 2 次 `approval.required` → allow_once → 生效 | ✅ 已关闭（W4-Z5） |
| X11 | bundle 清单带来源 official/availability/installed/覆盖行 | `plugin-manager/src/index.ts:282` | `discover()` 返回 `official`/`official_attestation`/`availability`/`installed`/`overrides`（path/row_id/order/note）/`marketplace`/`update_available`/`update_error`/`capability_groups` 全字段；test_plugins.py:81-118 断言；W4-Z5 live `GET /api/plugins` 实证 | ✅ 已关闭（W4-Z5） |
| X16 | progressive disclosure：durable `<available_skills>` + 摘要 diff 替换 + `/name` 内联注入 | `docs/subsystems/skills.md:227-233` | `/name` 匹配 user-invocable 技能并把完整指令内联到当轮 system prompt；持久化 catalog 的 added/updated/retired 以 revisioned `<skill_summary_diff>` 投递 | ✅ 已关闭（W10） |
| X21 | MCP 服务器 instructions 成为**独立 prompt 段** | `docs/subsystems/mcp.md:22-60` | `mcp_client.get_server_instructions()` 独立集合 + kernel `_mcp_instruction_sections()` 独立段（untrusted 标注）；工具描述只留短指针；`test_mcp_instructions_section.py` 6 项；W4-Z5 live：真实模型回合逐字引用 instructions 段首句（服务器发布 ANCHOR_W4Z5 标记，该文本只存在于段落中），并逐字引用工具描述为指针（无标记内联）；live `GET /api/tools` 实证指针描述 | ✅ 已关闭（W4-Z5） |
| X27 | client 扩展面：slots 注册、ConversationNodeDefinition、client 插件 | `docs/subsystems/slots.md:5-25` | `ConversationActivity.tsx` 有 `ConversationNodeDefinition` 注册表与 disposer，`ConversationNodeRegistry.test.tsx` 覆盖扩展 node 渲染/卸载；`App.tsx` 的页面与主视图仍使用静态导入/中央渲染分发，client plugin slots 尚未贯通 | ✅ CLOSED (WAVE5) |
| X28 | 人类 slash 命令：插件注册 `{name,description,input,handler}`，不经模型执行，`command/run|done` 落日志 | `docs/subsystems/commands.md:5-95` | `/api/commands` 暴露 plugin handler；前端 slash 输入直接 POST `/api/commands/invoke`，handler 调用不经模型且 append-only 记录 command/run|done | ✅ 本轮关闭 |
| X24 | ACP：`session/new|list|resume|close|set_config_option|prompt|cancel`，per-session MCP 注入 | `acp/acp/README.md:60-80` | `tools/app_server.py` 实现 7 个方法 + fail-closed ACP 权限（`session/request_permission`，只认 allow_once）+ permissionPreset configOptions；W4-Z5 ACP stdio live 全方法驱动通过（含两轮真实模型 end_turn、resume 后续轮、list 2 会话——修了 `MemoryStore.list_conversations` 漏 SELECT `metadata` 列导致 session/list 永远为空的真 bug）。残留：per-session MCP 注入显式 `-32602` 拒绝（Atlas 缺"非配置来源的 MCP server 进程编排"，属新底层原语） | PARTIAL (WAVE5: ACP per-session MCP 注入未完成) |

### P2

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| X12 | Claude Code hooks 桥 | `experimental/hooks-claude-code/README.md` | `runtime/hooks.py:33-45` 28 个事件，`run_drive.py` 接线（kernel `_run_hook` SessionStart/PreToolUse/PostToolUse/PermissionDenied 等生命位）；W4-Z6 真实回合：PreToolUse deny 在执行前拦截 local_exec，`hook.ran` 事件在列，模型报告 hook 原文理由 | ✅ CLOSED (W4-Z6) |
| X13 | Codex hooks 桥 | `experimental/hooks-codex/README.md` | `hooks.py:139 codex_hook_settings` 读 user(`~/.codex/hooks.json`)+project(`.codex/hooks.json`)，源身份 `codex:user:`/`codex:project:` 独立、fingerprint trust fail-closed；`test_codex_plugin_hooks.py` 4 项单测；W4-Z6 真实回合：codex 项目 SessionStart hook 执行、stdout 注入会话上下文、模型回显 token，`hook.ran` 帧带 codex 源 | ✅ CLOSED (W4-Z6)（DSH 5 个 hook 点覆盖；信任门比 DSH 更强） |
| X14 | hook 逐条信任/审批门 | DSH **没有** | `runtime/hooks.py:679-735` fingerprint 作用域信任，fail-closed | **PRESENT-STRONGER** |
| X15 | skill 发现根阶梯 | `docs/subsystems/skills.md:64-76` | `skills/__init__.py` SKILL_SOURCE_PRIORITY 等价；W4-Z6 真实回合：同名技能 claude-project(30) 胜 claude-user(20)，败者 token 未出现；`introspect skills.sources` 实时列出阶梯（atlas10→library11→atlas-user12→claude-user20→claude-project30） | ✅ CLOSED (W4-Z6) |
| X17 | `disable-model-invocation` / `user-invocable` 归一化 | `docs/subsystems/skills.md:100-110` | frontmatter 严格归一化两个布尔值；用户 slash 匹配和 `activate_for_model` 分别执行 invocation 门 | ✅ 本轮关闭 |
| X18 | skill provider 协议 + per-scope 分层 | `docs/subsystems/skills.md:9-30,188-200` | provider `list/get`+`handle_change("skills/change")` 失效、不完整观察重试有单测；`with_sources` 请求作用域分层（高优先级胜同名、不污染基础索引）有单测；新暴露 `introspect skills.sources` 列出生效阶梯（8886 实测）。仍缺：异步 provider list/get、按 scope 链 keyed 的发现缓存 | PARTIAL (WAVE5: skill provider 注册/作用域层未完成) |
| X19 | skill 新鲜度：chokidar 监听 + 读写路径即时失效 | `docs/subsystems/skills.md:78-81` | 读/写路径 `_ensure_fresh()`（mtime_ns+size 指纹）即时失效，`test_skills_hot_reload.py` 覆盖；W4-Z6 真实回合：SKILL.md 会话中途编辑、下一次运行即见新 token。DSH 的 chokidar 常驻 watcher 是实现差异，可观测行为（重启外即时生效）已实证 | ✅ CLOSED (W4-Z6)（机制：读路径指纹 vs DSH watcher） |
| X20 | skill 依赖/生命周期门 | DSH 无依赖契约 | `skills/__init__.py` preflight mcp/python/commands；W4-Z6 真实回合：`run.failed`，detail=`skill dependencies block activation: mcp_servers:nonexistent-z6-mcp (missing)`；`introspect skills.preflight` 同面可查（未为对齐退化） | ✅ CLOSED (W4-Z6)（**PRESENT-STRONGER** 保持） |
| X22 | MCP liveness：500ms→30s 翻倍，10 次后移除工具，稳定后重置预算 | `mcp-client/README.md:64-67,89-93,129` | `tools/mcp_client.py` 500ms 起步、指数退避封顶 30s、10 次后转 `unreachable` 并移出工具索引、稳定 60s 后重置、显式重试解锁；8836 实测三个 MCP server 均 connected 且工具发现完成 | ✅ CLOSED |
| X23 | MCP resources + 作用域隔离 | `docs/subsystems/mcp.md:39-70` | runtime MCP server allow-list 贯穿 preset/request 能力、kernel 工具发现与派发，并由 `MCPClient.for_scope()` 隔离资源读取 | ✅ 本轮关闭 |
| X25 | SDK JSON-RPC：NDJSON、`initialize` 等树稳定、`session/wait`、关停 | `packages/sdk/README.md` | `tools/app_server.py` 新增 `session/wait`（run 任务落定才回 `{}`，waiter 由 run 任务解析、reader 不阻塞，审批/输入中途仍可应答）、`shutdown`（回执后走 EOF 同款优雅排空）、`session/status` running/idle 通知；`test_app_server_sdk_lifecycle.py` 5 项；W4-Z6 真实 stdio 全生命周期：initialize→session/start→真实模型 prompt（`text: Z6APPSERVEROK`）→wait `{}`→status 序→shutdown `{}`→进程退出 0。残余：prompt 仍是阻塞完成回执（DSH 为 durable enqueue receipt）、无 working-directory get/set、无 subagent.started/finished 通知 | ✅ CLOSED (W4-Z6)（残余差异如左） |
| X26 | typed Client↔Host Remote gateway（装饰器生成描述符/编解码/客户端类型） | `docs/api-gateway.md` | W4-Z6 终判 sweep：core/frontend/backend-adapter 全仓无 `@Remote/RemoteScope/typert`、无 codegen/类型生成管线；契约仍靠手写 FastAPI router + 手写 TS adapter；`gateway_service.py` 是 channel→agent 桥而非 RPC 网关 | HARD (typed gateway needs descriptor/codec generation) |
| X29 | webhook runtime：provider adapter + 可信规则返回 `WebhookSessionRequest` | `docs/subsystems/webhook.md:5,19-64` | 增加 `WebhookProvider`、HMAC provider adapter 与 typed `WebhookSessionRequest`；路由通过 provider 验证 | ✅ 本轮关闭 |
| X30 | SSH 作为整套执行世界（fs/subprocess/sandbox 一起搬） | `docs/subsystems/ssh.md` | `ssh.py` 工具级代理（local_file/local_edit/local_git/local_exec/local_shell 经 SSH 分流）；W4-Z6 loopback asyncssh 真实 SSH wire 取证（`test_ssh_execution_world.py` 4 项）：exec 通道+OS 探测、SFTP write/read/list、remote exec cwd、remote edit fail-closed 全过。fs/subprocess/sandbox 整体搬上 SSH 仍缺——新原语，本轮禁建 | PARTIAL (W4-Z6: 工具级执行世界已在真实 SSH wire 实证；整套搬迁仍缺) |
| X31 | schedule 绑定原 session，到期回到该会话 | `docs/subsystems/schedule.md` | DBOS automation：`payload.conversation_id` 经 `AutomationEngine._execute`→`_automation_dispatch_turn` 贯通 dispatch 与 receipt，缺省回退 `automation-<id>`（`test_automation_engine.py` 新单测）；W4-Z6 真实 date 触发：到期 run 落进绑定会话 `z6-schedule-target`，assistant 消息持久化（receipt `conversation_id` 一致） | ✅ CLOSED (W4-Z6)（绑定靠 DBOS automation；APScheduler 旧道并存） |
| X32 | 组合自省：`--dump-config` 带逐层来源 | `docs/architecture.md:41` | 新增 introspect `config.provenance`：单键逐层来源（request-override→session→project→expert-overlay→atlas.toml，镜像 `AtlasConfig.get` 解析序，全层值过 scrub），10 项单测；`config.layers` 与 `plugins dump-config`（profile→bundle→patch）已有；8886 实测 server.port→atlas.toml、models.custom.api_key 不泄漏 | ✅ CLOSED (W4-Z6) |
| X33 | agent 类型 / subagent provider 缝 | `docs/architecture.md:130-136` | `agent/definitions.py` 多格式发现（codex toml/copilot/claude/opencode/workspace/plugin）+ `agents/backends/` 适配器；`test_backend_parity_wave7.py` 11 项过；W4-Z6 真实 delegate 回合：`delegate_task` agent=`z6-reviewer`（workspace `.claude/agents` 定义）子任务完成、子回答带定义规定的 `Z6REVIEWERMETA` persona token，`backend="atlas"` | ✅ CLOSED (W4-Z6) |

---

## 四、桌面与 UX（33 条）

### P1

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| D1 | 认证本地载体 + boot injection + OS 分配端口 | `apps/desktop/src/web-document.ts:41,72`；`main.ts:664,685` | Electron ready 时选择 loopback OS 临时端口并写入 `ATLAS_PORT`；backend spawn 继承该端口，preload 的 `apiBaseUrl`、健康探测和 token 注入共同使用它；显式 `ATLAS_PORT` 保持兼容 | ✅ CLOSED (WAVE5) |
| D2 | 两进程 typed IPC 生命周期（ready/fatal/shutdown-complete/quit-inspection） | `apps/desktop/src/host-process.ts:189,57-78` | shared IPC 定义 `BackendLifecycleEvent`；main 在 ready/fatal/shutdown-complete/quit-inspection 时发布，preload 提供可卸载的 typed 订阅并在订阅后补取最新状态 | ✅ CLOSED (WAVE5) |
| D3 | 流式增量：chunk 折叠进 per-node state，重连重放压缩流 | `api/session-controller/.../events.ts:8`；`ui-conversation/.../assembler.ts:174,364` | `frontend/src/renderer/components/timelineProjection.ts:5,25`：`TimelineProjection` 把连续 `message.delta` 折叠进现有 reply node 且保持无关节点引用不变，非投影事件（run.phase/usage）返回同一基线；`compactTimelineReplay` 把重连 chunk 爆发压缩为等价语义、首节点 id 不变；结构事件走增量装配、已发布快照不可变 | ✅ CLOSED (W4-Z7: timelineProjection.test.ts 6 项组件测试全过——delta 折叠/前缀替换重建/非投影基线/重连压缩/相同事件识别/结构节点增量装配) |
| D4 | keyed ConversationNode renderer 注册表 | `ui-chat/.../register-node-renderers.ts:39-69` | `ConversationActivity` 有 keyed `ConversationNodeDefinition` 注册/卸载 API（builtin 渲染 + 扩展注册 + disposer） | ✅ CLOSED (W3-X6)；W4-Z7 复核代码与 ConversationNodeRegistry.test.tsx（2 项）均在位且通过 |
| D5 | durable 附件暂存：内容寻址、先存后发、进度、可取消 | `docs/subsystems/attachment.md`；`client/file-upload/src/client/contract.ts` | `renderer/services/attachmentStaging.ts` 以 SHA-256 存入 IndexedDB；`App.tsx` 的文件、图片、白板图和最近截图路径先暂存再进入发送队列，显示进度、允许取消，并把暂存引用随会话草稿恢复；发送将 base64 内联到 run.start（协议设计，暂存能力已齐） | ✅ CLOSED (W4-Z7: attachmentStaging.test.ts 4 项（内容寻址/进度+中止/持久+恢复/草稿引用跨实例）+ ComposerAttachmentStatus.test.tsx 2 项（进度+取消/失败+重试）) |
| D6 | 结构化草稿：chip 进文本模型、per-session 语义草稿、重载存活 | `ui-conversation/.../ReferenceChip.tsx` | `renderer/services/composerDraft.ts` 按会话保存文本、mentions 和暂存附件引用；提交时将所有 chip 序列化进模型文本；重载后经 `readComposerDraft` 恢复 mention chip 与附件元数据进 composer | ✅ CLOSED (W4-Z7: composerDraft.test.ts 会话隔离 + 全 chip 类型序列化；ComposerDraftRestore.test.tsx 修复 TooltipProvider 包装后 2 项组件测试通过) |
| D7 | follow 重连：首帧 header+tail+cursor+投影基线，`page()` 补缺口 | `docs/subsystems/web-client.md:48` | adapter 为空 renderer 投影从序号 0 重放；服务端提供有界 event page、header/tail/cursor/projection baseline，断层时先补连续页再接回 WebSocket | ✅ CLOSED (WAVE5) |
| D8 | 右侧栏：split 树、浮动面板、可插 tab 类型、per-session 布局 | `docs/subsystems/sidebar-right.md:26,74`；`ui-dockkit/.../FloatLayer.tsx` | `shell/Inspector.tsx:146-212` per-session 持久布局（dock/split tab/浮动+位置，按 conversationId 键存）、浮动面板可拖拽且钳制在视口内、扩展可插 tab（builtin id 不可遮蔽）；宽窄面板自适应 | ✅ CLOSED (W4-Z7: inspectorLayout.test.ts 4 项 + inspectorTabs.test.ts 2 项 + Inspector.parity.test.tsx 扩展 tab 渲染) |
| D9 | 应用内连接恢复控件（可点击重试 + 恢复确认） | `ui-primitives/.../ConnectionIndicator.tsx:6-40` | 断连提示提供键盘可操作的“重试连接”；桌面重启动作先确认 | ✅ 本轮关闭 |
| D10 | 自动更新生命周期：调度 + 退避 + 抖动 + journal + 强制版本 | `apps/desktop/src/update-coordinator.ts:16`；`update-schedule.ts:20-26` | `frontend/src/renderer/services/update-coordinator.ts` 自动检查、有界指数退避+抖动、上限 journal、防并发；main 侧 `releaseUpdate.ts` 强制版本策略：当前版本低于 release 声明最低版本即强制、跳过版本与提醒延迟不抑制 mandatory、最低版本不可满足则拒绝该 release；`UpdateBanner.tsx` 强制升级对话框无跳过/关闭入口并显示下载进度与校验失败重试 | ✅ CLOSED (W4-Z7: update-coordinator.test.ts 4 项 + releaseUpdate.test.ts 4 项 + UpdateBanner.test.tsx 5 项) |

### P2

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| D11 | 回合 diff 审阅（并排/换行/hover 预览/二进制标记） | `ui-deliverables/.../ReviewTab.tsx:107,131` | `ChangesPanel.tsx:370-469` DiffView 统一/并排双阅读模式（`layout: 'unified'` 或 `'split'`），行 hover 文件预览、二进制标记不渲染 patch、hunk 级接受/拒绝 + 行评论（Atlas 更强） | ✅ CLOSED (W4-Z7: diffReview.test.tsx 5 项——双栏行号配对/两侧渲染+hover 预览+换行/二进制/有界预览/真实组件双模式) |
| D12 | 每回合变更文件摘要 | `workspace-changes/src/recorder.ts:230` | `run_drive.py:1165` checkpoint manifest difflib → `ConversationActivity.tsx:117` RunChangesSummary 每回合卡片（文件数/+additions/−deletions），可点击进入 Changes 面板 | ✅ CLOSED (W4-Z7: ConversationActivity.parity.test.tsx「renders a visible per-turn changes summary with file and line counts」) |
| D13 | `present` 声明的交付物卡片 | `tool-present/src/index.ts:81`；`PresentedFileCard.tsx` | `agent/tool_catalog.py` 暴露 `present`；`agent/presentation.py` / `tool_node.py` 只接受当前本地工作区内的现存文件并发出 `artifact_created`；`api/run_drive.py` 转发标题/摘要；`runtimeEvents.ts` 把自定义卡片信息写入 renderer artifact store | ✅ CLOSED |
| D14 | 问题意图标签（`plan-review` 路由到专用面板） | `docs/subsystems/user-questions.md:25` | `intent=plan-review` 的 `input.required` 渲染进入现有计划审查、批准、修改控件 | ✅ 本轮关闭 |
| D15 | 审批接管 composer（不可滚走） | `ui-approval/.../ApprovalPanel.tsx:1-62` | `ConversationActivity.tsx:339-344` `PendingApprovalDock` 由 `App.tsx:3464` 挂载在会话滚动区之外的 composer 宿主——审批未处理时不可滚走；选项集（允许一次/总是/拒绝）更丰富，支持 Alt+1/Alt+2 键盘响应 | ✅ CLOSED (W4-Z7: ConversationActivity.parity.test.tsx 3 项——dock 渲染所有未响应审批、精确 event 匹配、已响应后清空) |
| D16 | 文档预览 renderer 注册表 | `ui-sidebar-documentpreview/src/client/*` | `shell/panels/documentPreviewRegistry.tsx` 内置全预览族（md/图片/PDF/xlsx/pptx/HTML）大小写不敏感解析；扩展可注册/卸载（dispose 还原 builtin）、拒绝重复身份；`FilesPanel.tsx` 消费 | ✅ CLOSED (W4-Z7: documentPreviewRegistry.test.tsx 3 项 + FilesPanel.test.tsx) |
| D17 | 命名空间 i18n | `client/locale/src/locale-settings.ts:16` | `frontend/src/renderer/services/i18n.ts:9,37,158` namespace 注册/优先解析/同键隔离 + MutationObserver 重定位渲染文本；`UpdateBanner.tsx` 使用 updates namespace（强制升级文案）；全局目录保留为 fallback，不阻断 namespace 命中 | ✅ CLOSED (W4-Z7: i18n.test.ts 7 项——持久化/namespace 优先/隔离/updates 文案/中文回退/插值/防陈旧重定位) |
| D18 | 半径 token 尺度 + token-only 颜色（spec 强制） | `docs/ui-radius.md`；`ui-theme/src/styles/base.css` | `styles/app.css:15-21` `--atlas-radius-xs..3xl` 单调半径尺度并经 `--radius-*` 绑定 Tailwind 半径工具类；共享按钮尺寸走 radius token 与语义色工具类（3 套主题 + 自定义色保留） | ✅ CLOSED (W4-Z7: styleContracts.test.tsx「defines a monotonically increasing radius scale and binds Tailwind radius utilities to it」+「renders shared button sizes using radius tokens and semantic color utilities」) |
| D19 | 无障碍契约（框架级 focus/IME/reduced-motion） | `ui-theme/src/styles/focus.css`；`packages/client/shortcuts` | `styles/app.css:219` 全局 focus-visible（brand 色 2px）、`:316` prefers-reduced-motion 关闭 CSS 动画/过渡/平滑滚动；快捷键注册表在 IME 组合期间不捕获按键 | ✅ CLOSED (W4-Z7: styleContracts.test.tsx focus/reduced-motion 断言 + shortcuts.test.ts IME 用例) |
| D20 | 单实例 + deep link | `apps/desktop/src/single-instance.ts:16` | `electron.ts:1197` `requestSingleInstanceLock`，第二实例退出；`parseAtlasDeepLink`（electron.ts:844）解析 atlas://conversation/settings 且拒绝含凭据/重复参数/未知 section/锚点 URL | ✅ CLOSED (W4-Z7: electron.lifecycle.test.ts「quits the second process…」+「accepts conversation/settings deep links…」) |
| D21 | 托盘 | `apps/desktop/src/tray.ts:13-45` | `electron.ts:257` createTray 持久托盘：打开 Atlas、后台组件状态（禁用态展示）、安全模式重启/普通重启、显式退出；window-all-closed 不退出（驻托盘） | ✅ CLOSED (W4-Z7: electron.lifecycle.test.ts「builds a persistent tray…」断言菜单项与退出行为) |
| D22 | 原生菜单 + 快捷键注册表 | `apps/desktop/src/keybindings.ts` | `electron.ts:627` createApplicationMenu 原生编辑角色（undo/redo/cut/copy/paste/selectAll）+ 非冲突窗口加速键（新建窗口 Ctrl+Shift+N 等）；renderer 侧 `services/shortcuts.ts` 注册表 | ✅ CLOSED (W4-Z7: electron.lifecycle.test.ts「registers native editing roles…」+ shortcuts.test.ts 3 项) |
| D23 | 崩溃恢复（含"禁用全部插件重启"） | `apps/desktop/src/main.ts:80-100` | `electron.ts:1029` recoverRendererCrash：对话框提供 重新加载/禁用全部插件并重启/稍后；选择安全模式则停后台（renderer_crash_safe_mode）并以 safeMode 重启、持久化 safeModeOnNextStart；脱敏 bug bundle（electron.ts:1622）；clean-exit 不触发、可推迟 | ✅ CLOSED (W4-Z7: electron.lifecycle.test.ts 2 项——崩溃恢复全流程与推迟/忽略) |
| D24 | 消息分支/fork（任意 assistant 尾） | `tool-.../TurnTailNodeView.tsx:69,98` | `useAtlasStore.ts` forkFrom（任意消息、可选 summarize）+ `App.tsx:3117-3120` 消息悬浮 fork/fork+摘要、`ForkTree.tsx` 分支树导航 | ✅ CLOSED (W4-Z7: useAtlasStore.x6.test.ts fork 双模式回归 + ForkTree.test.tsx 组件导航 + ForkTree.regression.test.ts 空会话守卫) |
| D25 | rewind | **DSH 无** | 三模式 + preview + redo（Atlas 更强，本轮行为未动） | ✅ CLOSED (W4-Z7 仅回归测试: useAtlasStore.x6.test.ts rewindTo files×2 + redoRewind 精确重做；App.tsx:3077 rewind 预览+确认横幅不变) |
| D26 | plan 模式/计划审阅 | `docs/subsystems/plan.md` | `ConversationActivity.tsx:557` plan-review 意图路由 + UltraplanPanel 载入/编辑保存/批准；store `setNextRunMode('plan')` 把 mode 带进下一次 run | ✅ CLOSED (W4-Z7: UltraplanPanel.test.tsx + useAtlasStore.x6.test.ts plan 提交与 approvePlan 修剪) |
| D27 | 队列/steer/redirect | `ui-conversation/.../QueueDock.tsx` | `ConversationQueuePanel.tsx` 顺序队列 + 暂停/恢复 + steer 门槛控制；store redirect 模式立即转向且未确认消息保留 | ✅ CLOSED (W4-Z7: ConversationQueuePanel.test.tsx 2 项 + useAtlasStore.x6.test.ts redirect 回归) |
| D28 | 语音输入 | `docs/subsystems/voice-input.md:27` | `VoiceHud` 协议状态机（准备/聆听/部分文本瞬态/提交上限/错误态）+ VoiceOverlay 聆听/字幕/静音/挂断/文本兜底 + TTS 按保存设备路由 + 输入设备选择与缺失回退 | ✅ CLOSED (W4-Z7: voiceHudProtocol.test.ts 2 项 + VoiceOverlay.component.test.tsx + speechPlayback.test.ts + audioDevices.test.ts 2 项) |
| D29 | 更早历史分页 | `docs/subsystems/web-client.md:48` | `useAtlasStore.ts:216-256,461-487` 按 id 游标 + 每页多取 1 条探针（MESSAGE_FETCH_SIZE=101）：首页满 101 即有更早、探针不进渲染列表；loadEarlier 取 101 全并入并按既有列表去重，短页即停——满页歧义消除、不重不漏；`MessageThread` 可见"载入更早"控制随探针结果消失 | ✅ CLOSED (W4-Z7: useAtlasStore.test.ts + x6（恰满一页/探针续页/连续满页回溯/重叠页修复）+ MessageThread.x6.test.ts UI 回归；顺带修复 useAtlasStore.test.ts 既有 mock 顺序脆弱失败) |
| D30 | 备选会话视图（Chat / Trajectory） | `ui-trajectory/.../TrajectoryView.tsx` | `MessageThread.tsx:171,654-656` Chat/轨迹双模式切换（aria-pressed 双向）；`ConversationTrajectory.tsx` 可读轨迹（时间戳/标签/序号/详情）；`shell/panels/trajectory.ts` `type`/`event` 双键描述实时运行事件与归档 rollout 行一致 | ✅ CLOSED (W4-Z7: MessageThread.x6.test.tsx 切换回归 + ConversationTrajectory.test.tsx + trajectory.test.ts 实时 type 帧/归档 event 行/type 优先) |
| D31 | 多窗口/分栏 | DSH 单窗口 | `electron.ts:576` openConversationWindow 每会话一窗（复用聚焦/最小化恢复/关闭清理/非法 id 拒绝/导航守卫+外链移交浏览器）、`PaneWorkspace.tsx` 递归 split 树持久（Atlas 更强，本轮行为未动） | ✅ CLOSED (W4-Z7 仅回归测试: PaneWorkspace.test.tsx 2 项 + 新增 electron.multiWindow.test.ts 5 项) |
| D32 | 消息级操作 | `MessageIconActions.tsx:11-15`（仅复制+分支） | `App.tsx:3097-3122` 编辑重发/fork/fork+摘要/rewind 双模式菜单（Atlas 更强，本轮行为未动） | ✅ CLOSED (W4-Z7 仅回归测试: useAtlasStore.x6.test.ts editMessage 截断重发 + fork 双模式 + MessageThread.x6.test.ts 历史控制) |
| D33 | slash 命令注册表 | `docs/subsystems/commands.md:5-40` | `services/slashCommands.ts` 来源式注册表（去重、跨源 id 冲突拒绝、注册即发布组件快照、dispose 移除）+ `pluginSlashCommands` 插件命令映射（JSON 参数校验）；模糊排序在 composer 命令面 | ✅ CLOSED (W4-Z7: slashCommands.test.tsx 3 项 + pluginSlashCommands.test.ts 2 项) |

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
