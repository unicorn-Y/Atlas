# Batch C — Policy

## 结果

关闭：E12（审批 asked/decided append-only 事件）、E13（权限/sandbox/approval 预设及 resume）、E15（PTY owner fencing 与 waitReason）。

部分完成：E14（Docker per-call read-only/workspace-write；danger-full-access 在该路径 fail-closed，但没有通用 host OS sandbox）、E18（单次审批和 Docker 路径已接入；缺少所有 host 工具共用的 per-call isolation executor）。

关闭：E16（统一后台作业 registry，追加收尾见下）。X9 的自动化入口已解析并传递 preset 能力；完整 preset runtime enforcement 记录在 Batch A/D。

## 改动文件

- `core/atlas/approval_policy.py`
- `core/atlas/engine/tool_permissions.py`
- `core/atlas/sandbox.py`
- `core/atlas/tools/local_execution.py`
- `core/atlas/api/run_drive.py`
- `core/atlas/api/runtime.py`
- `core/atlas/api/runtime_ws_router.py`
- `core/tests/test_permission_policy_batch_c.py`
- 更新 `core/tests/test_local_execution.py`

## 测试

```text
rtk python -m pytest -q -p no:cacheprovider tests/test_permission_policy_batch_c.py tests/test_kernel_sandbox_escalation.py tests/test_event_contract.py tests/test_permission_grants.py tests/test_approval_outcome.py tests/test_local_execution.py tests/test_agent_preset_capabilities.py tests/test_agent_preset_enforcement.py tests/test_agent_policy_context_wiring.py tests/test_automation_capability_binding.py -k "not shells_executable_cwd_environment_and_nonzero_exit"

108 passed, 1 skipped, 1 deselected, 5 warnings in 13.95s
```

独立 live-route fake-socket 测试：

```text
rtk python -m pytest -q -p no:cacheprovider tests/test_permission_policy_batch_c.py -k "run_inject_routes or websocket_inject_branch"

2 passed, 21 deselected, 5 warnings in 2.66s
```

改动 Python 文件 `py_compile` 成功；`_handle_run_start` 的 AST 解析成功。真实 isolated backend 注入尝试因测试 provider 错误地请求 OpenAI 而先收到 401，无法证明注入语义；误导性测试已移除，改由上述确定性 route test 覆盖。

## 真实模型回合

命令：`rtk python scripts/dsh_live_ws_check.py 8811 "Reply with exactly the word: OK"`

```text
[reply] 'OK'
[result] terminal=run.completed chars=2
```

终止事件的 runner 输出为 `run.completed`，模型为 `deepseek-v4.1-flash`，input 9794/output 2，cached input 9600。

## 未完成项与原因

E14/E18 的缺口是通用 host per-call sandbox enforcement。真实模型回合不覆盖隔离执行与审批拒绝等独立分支。

## 后续收尾：E16

`ExecManager` 统一注册 detached shell 和后台 subagent，提供 owner-fenced `job_list/job_output/job_kill`、256KiB 运行环形缓冲、settled 后 16KiB 保留、每 owner 最多 10 个，并将 `job_*` 工具接入模型调用。subagent 通过 refresh/kill 回调接入同一注册表。新增文件：`core/tests/test_kernel_exec_jobs.py`；更新 `core/atlas/engine/kernel/exec.py`、`core/atlas/tools/local_execution.py`、`core/atlas/agent/tool_node.py`。

```text
rtk python -m pytest -q -p no:cacheprovider tests/test_kernel_exec_jobs.py

9 passed, 5 warnings in 2.38s
```

```text
rtk python -m pytest -q -p no:cacheprovider tests/test_kernel_exec_jobs.py tests/test_local_execution.py -k "not shells_executable_cwd_environment_and_nonzero_exit"

27 passed, 1 deselected, 5 warnings in 11.36s
```

被排除的断言是既有 nonzero-exit 行为不匹配，与本次 registry 无关。
