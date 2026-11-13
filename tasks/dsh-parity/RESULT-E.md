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
