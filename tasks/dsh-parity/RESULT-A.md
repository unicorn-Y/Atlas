# Batch A — Engine

## 结果

关闭：E5、E6、E8、E10、E20、S6、X17。

部分完成：E2（typed terminal reason 已落 journal/result，但还没有完整的 turn/step 生命周期）、E3（hook/finalizer 已接入，typed waterfall/result observer 仍不完整）、E17（现有 delegate 能力尚缺完整 fork 前缀与 persona）、E18（kernel 审批边界 fail-closed，但 host per-call OS sandbox 执行器缺失）、X9（preset 能力在 RunContext 应用；ACP 入口还未接入）。

未关闭：E4（强制 output schema/render/presentationMeta）、E11（`engine/goals.py` 的 revision CAS 与默认上限）、E19（concludeTurn）、E25（idle-only maintenance slot）。

## 改动文件

- `core/atlas/agent/__init__.py`
- `core/atlas/agent/run_phases.py`
- `core/atlas/agent/todo_state.py`
- `core/atlas/engine/kernel/context.py`
- `core/atlas/engine/kernel/inbox.py`（新增）
- `core/atlas/engine/kernel/loop.py`
- `core/atlas/engine/kernel/request_envelope.py`（新增）
- `core/atlas/engine/kernel/state.py`
- `core/atlas/engine/kernel/stuck.py`
- 对应新增测试：`test_agent_inbox_wiring.py`、`test_agent_policy_context_wiring.py`、`test_agent_preset_capabilities.py`、`test_agent_preset_enforcement.py`、`test_agent_skill_model_invocation.py`、`test_kernel_checkpoint_barriers.py`、`test_kernel_compaction_surface.py`、`test_kernel_durable_inbox.py`、`test_kernel_lifecycle_reasons.py`、`test_kernel_request_envelope.py`、`test_kernel_sandbox_escalation.py`、`test_repeat_tool_reminder.py`、`test_run_checkpoints_fail_closed.py`、`test_todo_state_durable_events.py`。

## 测试

合并后的 Batch A 定向回归：

```text
rtk python -m pytest -q -p no:cacheprovider tests/test_agent_inbox_wiring.py tests/test_agent_policy_context_wiring.py tests/test_agent_preset_enforcement.py tests/test_agent_skill_model_invocation.py tests/test_kernel_durable_inbox.py tests/test_todo_state_durable_events.py tests/test_kernel_checkpoint_barriers.py tests/test_run_checkpoints_fail_closed.py tests/test_kernel_lifecycle_reasons.py tests/test_kernel_request_envelope.py tests/test_repeat_tool_reminder.py tests/test_kernel_compaction_surface.py tests/test_fork_open_turn_guard.py tests/test_agent_run_phases.py

46 passed, 11 warnings in 8.07s
```

Preset enforcement integration：

```text
rtk python -m pytest -q -p no:cacheprovider tests/test_agent_preset_enforcement.py tests/test_agent_policy_context_wiring.py tests/test_agent_preset_capabilities.py tests/test_automation_capability_binding.py tests/test_permission_policy_batch_c.py tests/test_plan_mode_live_guidance.py

42 passed, 5 warnings in 4.19s
```

## 真实模型回合

命令：`rtk python scripts/dsh_live_ws_check.py 8811 "Reply with exactly the word: OK"`

实际输出末尾：

```text
[reply] 'OK'
[result] terminal=run.completed chars=2
```

终止事件的 runner 输出为 `run.completed`，模型为 `deepseek-v4.1-flash`，input 9794/output 2。

## 未完成项与原因

E4、E11、E19、E25 未实现完整能力；E2、E3、E17 仍只有部分 parity。E18 的 per-call host sandbox 执行器不存在，因此不宣称该路径已可执行。X9 对 ACP 入口尚未接线。曾运行 `test_kernel_tool_error_regressions.py`，其中 `test_tool_call_arguments_repair_only_closed_objects` 失败；失败点在未修改的 `model_call.py`，同组其余 21 项通过。未运行整套 core 测试。
