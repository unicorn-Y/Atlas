# WAVE 3 — X2 结果（E21 / E22 / E23 / E24 / E26 / E27）

日期：2026-11-14
分支：`wave3`
基线：`2bc3a626`

## 逐条结论

| Row | 状态 | 依据 / 未完成项 |
|---|---|---|
| E21 | PARTIAL | `workspace_session_manage(move)` 能把会话 workspace 持久化并告知下一轮生效；运行期间 kernel workspace 固定，未实现独立 working directory 与固定 sandbox 写根。现存旧 cwd 测试还引用已移除的 Hermes `tools.*` 路径。 |
| E22 | NOT-DONE | Agent Group/Orchestrator、Kanban、peer inbox 和 REST 面存在并通过对应测试，但没有在 kernel 内作为模型工具暴露 roster、steer-only message 和带 CAS/无环约束的 task DAG。 |
| E23 | PARTIAL | 当前 `workflow` 工具是目标规划 DAG，相关 workflow unit tests 通过；模型不能提交 `agent()/parallel()/pipeline()` 编排脚本。 |
| E24 | NOT-DONE | 未找到 Ralph 串行上下文重置迭代器、256 轮上限或 16 KiB handoff 实现，本批未增加新的执行协议。 |
| E26 | PARTIAL | run 级 allow/deny glob 交集有测试；ToolRegistry 没有 registration-scoped `restrict()`，也没有对未知名/空集合在注册时 fail-fast。 |
| E27 | PARTIAL | `execute_code` 实际经当前工具管线运行，定向测试通过；它仍是可选附加工具，缺排他的 `run_code` 模式和拒绝直接工具调用的 kernel 行为。 |

本批没有条目达到 CLOSED，因此没有声称真实模型证明；按要求 E/S/X 只有同时具备单测和真实模型行为观察才会关闭。

## 定向测试：通过的现有行为

```text
python -m pytest -q -p no:cacheprovider tests/test_groups.py tests/test_groups_router.py tests/test_u32_expert_workflow.py tests/test_c1_child_policy.py::test_child_whitelist_intersection_preserves_parent_and_aliases tests/test_agent_enrichment.py::test_execute_code_dispatches_through_current_agent_tool_pipeline tests/test_agent_enrichment.py::test_codeact_subprocess_uses_atlas_bridge_for_three_operations
..................................                                       [100%]
34 passed, 5 warnings in 4.77s
```

这组结果只证明 group/API 基础、DAG workflow、run 级 allow/deny 和 execute_code 基础路径，不证明本批缺失的更强语义。

## 已存在的测试不兼容/失败输出

执行 cwd、workspace fork、child policy 与 execute_code 相关测试的批次检查：

```text
python -m pytest -q -p no:cacheprovider tests/test_engine_workspace_cwd.py tests/test_groups.py tests/test_groups_router.py tests/test_u32_expert_workflow.py tests/test_c1_child_policy.py tests/test_agent_enrichment.py
F.FFF................................FF.......F....                      [100%]
FAILED tests/test_engine_workspace_cwd.py::test_run_turn_anchors_every_cwd_surface_to_the_workspace
FAILED tests/test_engine_workspace_cwd.py::test_ssh_workspace_never_enters_local_session_records
FAILED tests/test_engine_workspace_cwd.py::test_record_session_workspace_survives_record_failure
FAILED tests/test_engine_workspace_cwd.py::test_worker_thread_pin_is_reset_after_each_turn
FAILED tests/test_c1_child_policy.py::test_inline_delegate_dispatches_through_atlas_lifecycle
FAILED tests/test_c1_child_policy.py::test_native_child_restrictions_block_direct_and_deferred_calls
FAILED tests/test_agent_enrichment.py::test_local_file_mutation_is_checkpointed_before_write_and_restorable
7 failed, 44 passed, 5 warnings in 7.54s
```

其中 cwd tests 报 `ModuleNotFoundError: No module named 'tools'` 和缺少 `AtlasRuntime._register_session_workspace`；child policy tests 的 fixture 报 `FixtureConfig` 缺少 `.raw`；enrichment 测试因 local_file 缺少此前读取步骤而保持原文件未变。

workspace fork/duplicate 的单独验证：

```text
python -m pytest -q -p no:cacheprovider tests/test_groups.py tests/test_groups_router.py tests/test_u32_expert_workflow.py tests/test_c1_child_policy.py::test_child_whitelist_intersection_preserves_parent_and_aliases tests/test_agent_enrichment.py::test_execute_code_dispatches_through_current_agent_tool_pipeline tests/test_agent_enrichment.py::test_codeact_subprocess_uses_atlas_bridge_for_three_operations tests/test_backend_parity_wave3.py::test_wave3_fork_and_duplicate_keep_original_workspace
..................................F                                      [100%]
FAILED tests/test_backend_parity_wave3.py::test_wave3_fork_and_duplicate_keep_original_workspace
ValueError: Cannot fork a session through an open turn
1 failed, 34 passed, 5 warnings in 6.00s
```

该 fixture 写入的 session transcript 被 SessionDB 判定为 open turn，故不能作为 E21 durable move 的通过证据。

## 本批变更

- `docs/parity/DSH-GAP-LEDGER.md`：将六项按现存实现与缺口写为 PARTIAL / NOT-DONE，并附 W3-X2 证据边界。
- `tasks/dsh-parity/waves/RESULT3-X2.md`：记录逐项结果和真实 pytest 输出。

本批没有改生产源码；检查到的功能边界都跨过 kernel/存储/安全语义，已有行为不能安全冒充目标能力。下一步需要先解决要闭环的具体行为，再按每条能力补测试与真实模型回合证据。
