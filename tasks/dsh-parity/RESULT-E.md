# Batch E — Desktop/API

## 结果

关闭：D9（断连提示可重试；Electron restart 会先确认）。

部分完成：D3（去掉 800-event 截断，历史事件不再静默丢失；每次 timeline 仍按全量事件重建，chunk folding/incremental projection 未完成）、D30（Rollout 默认显示可读轨迹，保留原始事件切换；尚未形成完整 Chat/Trajectory 同一视图切换与筛选）。

未关闭：D1、D2、D4、D5、D6、D7、D8、D10、D13、D17。Batch D 的 D4/注册表原语虽可显示自定义节点，但中央内置 switch 迁移仍不完整。D14 已在后续收尾关闭。

## 改动文件

- `frontend/src/renderer/App.tsx`
- `frontend/src/renderer/components/ConnectionRecovery.tsx`（新增）
- `frontend/src/renderer/components/ConnectionRecovery.test.tsx`（新增）
- `frontend/src/renderer/services/runtimeEvents.ts`
- `frontend/src/renderer/services/runtimeEvents.test.ts`
- `frontend/src/renderer/shell/panels/RolloutPanel.tsx`
- `frontend/src/renderer/shell/panels/trajectory.ts`（新增）
- `frontend/src/renderer/shell/panels/trajectory.test.ts`（新增）

## 测试

```text
rtk npm test -- --run src/renderer/components/ConnectionRecovery.test.tsx src/renderer/services/runtimeEvents.test.ts src/renderer/shell/panels/trajectory.test.ts src/renderer/components/ConversationNodeRegistry.test.tsx src/renderer/components/timeline.test.ts

Test Files  5 passed (5)
Tests       32 passed (32)
```

```text
rtk npx tsc -p tsconfig.renderer.json --noEmit
TypeScript: No errors found
```

另外 `rtk python -m pytest -q -p no:cacheprovider tests/test_event_contract.py` 已包含在 Batch B/C 联合验证中并通过；本批没有修改事件名真源。

## 真实模型回合

命令：`rtk python scripts/dsh_live_ws_check.py 8811 "Reply with exactly the word: OK"`

```text
[reply] 'OK'
[result] terminal=run.completed chars=2
```

终止事件的 runner 输出为 `run.completed`，模型为 `deepseek-v4.1-flash`，input 9794/output 2，cached input 9600。

## 未完成项与原因

D3 的 per-node incremental projection 尚未实现；D30 目前是轨迹/原始 JSONL 视图，不是完整 Chat 与 Trajectory 的双态会话 renderer。其它未关闭行尚无实现或验证证据，故未标成完成。

## 后续收尾：D14

`input.required` 中标记 `intent=plan-review` 的问题现在路由到现有 Plan 卡批准/修改/丢弃控件。更新文件：`frontend/src/renderer/components/ConversationActivity.tsx`、`frontend/src/renderer/components/timeline.ts`、`frontend/src/renderer/components/timeline.test.ts`。验证：`npm test -- src/renderer/components/timeline.test.ts` → `20 passed`；渲染层 TypeScript 检查通过。

## 五批后续改动的合并回归与 live smoke

```text
rtk python -m pytest -q -p no:cacheprovider tests/test_goal_revision_cas.py tests/test_goal_command_stranded.py tests/test_goal_loop.py tests/test_goal_plan_gate.py tests/test_goal_subgoal_commands.py tests/test_goal_planning_event.py tests/test_goal_payload_plan.py tests/test_goal_scheduler.py tests/test_kernel_exec_jobs.py tests/test_run_checkpoints_fail_closed.py tests/test_log_rotation_telemetry.py tests/test_token_meter.py tests/test_context_compact_in_place.py tests/test_mcp_client_scope.py tests/test_slash_command_api.py tests/test_slash_command_registry.py tests/test_permission_policy_batch_c.py -k "not shells_executable_cwd_environment_and_nonzero_exit"

144 passed, 5 warnings in 14.59s
```

```text
rtk npm test -- --run src/renderer/services/pluginSlashCommands.test.ts src/renderer/components/timeline.test.ts

Test Files  2 passed (2)
Tests      22 passed (22)
```

```text
rtk npx tsc -p tsconfig.renderer.json --noEmit
TypeScript: No errors found
```

合并后启动 `atlas.server:app`：`/api/health` 返回 HTTP 200。`rtk python scripts/dsh_live_ws_check.py 8811 'Reply with exactly the word: OK'` 实际事件包含 `run.started`、`message.completed`、`run.completed`；模型 `deepseek-v4.1-flash`，回复 `OK`，`[result] terminal=run.completed chars=2`。验证完成后停止后端并确认 `PORT_CLOSED`。

## MASTER §6–§9 收尾（Batch E 范围）

### 因果 explain API

在 `/api/conversations/{conversation_id}/explain?message_id=N` 增加只读因果查询。它用同一 SessionDB 分别读取全量、展示态、模型态 transcript，返回 turn/step 顺序、工具调用与结果消息关联、压缩遮蔽状态、inactive 状态和匹配的 session event。rewind handler 成功后追加 `session.rewind` 事件，包含 `rewind_id`、受影响消息 IDs、边界、模式和 checkpoint ID；不改变 `messages` 表语义，也没有在 `_execute_write` 回调中嵌套写事务。

证据边界：step ID 目前按 transcript 中 assistant 消息顺序推断；旧 rewind 没有逐消息事件，无法追溯其 ID，返回 `specific_rewind: not_recorded`。新增 rewind 的事件记录在 rewind 后追加，不与消息回退处于同一个 SQLite 事务。故该项标为 PARTIAL，未宣称历史因果链全覆盖。

新增文件：`core/tests/test_conversation_explain.py`。更新文件：`core/atlas/api/conversations_router.py`。

```text
rtk python -m pytest -q -p no:cacheprovider tests/test_conversation_explain.py

4 passed, 5 warnings in 2.39s
```

最终合并验证（含三源桌面事件契约）：

```text
rtk python -m pytest -q -p no:cacheprovider tests/test_conversation_explain.py tests/test_event_contract.py

17 passed, 5 warnings in 5.17s
```

扩展 API 回归 `rtk python -m pytest -q -p no:cacheprovider tests/test_conversation_explain.py tests/test_event_contract.py tests/test_c6_server_routes.py`：`31 passed, 2 failed, 5 warnings in 10.91s`。失败为 `test_review_intercept_rewrites_run` 的 tool_allow 期望与实际扩展工具列表不一致，以及 `test_new_queue_events_reach_wire_unchanged` 中 `_noop_hook()` 不接受 `bridge_event_alias` 参数；这两个失败点与本次 explain/rewind 代码无关，未在此修改。它们不计作通过。

`rtk python -m py_compile atlas/api/conversations_router.py` 成功；`rtk git diff --check` 通过。

真实 HTTP 验证（本轮重新执行）：在独立端口 8811 启动本次代码版本的 FastAPI 后端，`/api/health` 返回 200；真实模型回合返回模型 `deepseek-v4.1-flash`，`input_tokens=10243`、`output_tokens=2`，assistant 回复 `OK`，终止事件 `run.completed`。随后 GET explain 查询同一真实回合 assistant 消息 `18410`，返回 HTTP 200：

```text
BACKEND_HEALTH_HTTP=200
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 10243, "uncached_input_tokens": 8707, "output_tokens": 2, "cached_input_tokens": 1536, "request_count": 1, "context_tokens": 10243, "context_limit": 1048576,
[reply] 'OK'
[result] terminal=run.completed chars=2
EXPLAIN_HTTP_OK status=200 message=18410 role=assistant turn=1 step=1 compaction_shadowed=False rewind_inactive=False
PORT_8811_CLOSED
```

停止模型回合后对当前代码重新启动服务复验同一条消息：`EXPLAIN_HTTP_OK status=200 message=18408 turn=1 step=1`；完成后确认 `PORT_CLOSED`。

### 其余新增要求与目录责任

- `capabilities.usage` 需要 `core/atlas/introspect/` 注册与调用计量，不在 Batch E 的 `frontend/src/` / `core/atlas/api/` 目录内；由 coordinator / introspection owner 承接，本批未跨目录改动。
- effect receipt 要从 Batch A/C 的工具/沙箱执行点采集，并由 Batch B 的事件持久层写入；不在 Batch E 目录内，由 A/C/B 承接，本批未跨目录改动。
- 八项优势的聚合回归文件 `core/tests/test_atlas_advantages.py` 不在本批所有权内。按能力由 A（写路径 LSP）、D（hooks/skills）、E（rewind、桌面多窗格、消息操作、富预览）和 memory/library owner 提供覆盖；本批没有改该聚合测试文件，也没有声称八项已锁定。
- `core/scripts/dsh_parity_bench.py` 与 `BENCH.md` 不在 Batch E 目录内，由 coordinator/core-scripts owner 承接；本批未运行跨进程 DSH 对照，不给出性能优劣结论。
- [`COVERAGE.md`](COVERAGE.md) 已汇总 ledger 的 135 行（E/S/X/D），逐行标记 CLOSED、PARTIAL、NOT-DONE 或 ATLAS-STRONGER；状态依据 ledger 和五批 RESULT，不将未验证/弱实现写成 CLOSED。
- A–D 的 RESULT 文件均存在，相关 worker worktree 当前干净；其输出已在主分支历史中，主工作树状态不包含先前描述的 44 个修改文件和 34 个新文件。没有把该历史工作误报成本轮未提交 diff。

## 全账本状态

本次提交后 `DSH-GAP-LEDGER.md` 共 135 行能力差距；24 行已标关闭（其中包括之前已关闭的 16 行与本轮追加关闭的 8 行），其余仍有 111 行 ABSENT、PRESENT-WEAKER 或尚未闭合的 parity 项。因此五批结果文件和本轮提交已经交付，但“全部差距补齐”的总目标尚未达到，不能报告为全量完成。S1/S2 仍开放；本轮没有改变 `messages` 表语义。其余未关闭项按 E/S/X/D 行号和原因保留在本账本及各批结果文件中。
