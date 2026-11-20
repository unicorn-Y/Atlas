# X30 SSH 子任务：可信 owner 与生命周期独立验证

2026-11-16。生产实施仍为原 Codex Desktop GPT-6 Luna 高会话；主控只读审查、隔离验证、证据记录，不接管生产实现。不累加测试数为覆盖率，不宣称 X30/DSH 全部目标完成。

## 可信运行上下文派发截点

`agent/tool_node.py` 的 SSH `local_process` 分支将可信 `ctx.run_id` 作为 callback 第三个内部参数传递；`api/run_drive.py` 的闭包接受 `owner_run_id`，调用 `ssh_workspaces.call_process(..., run_id=owner_run_id or run.run_id)`。模型工具参数中的 `_owner_run_id` 不作为登记身份。其他 SSH 工具仍沿原两参数调用。实际 child 入口/类型兼容性及 finally 自动收尾另外验证，不由该静态锚点先推完成。

主控使用既有 40 秒独立监督器、唯一 basetemp 运行以下三项：

- `test_kernel_child_ssh_process_owner_and_cancel_are_isolated`
- `test_kernel_tool_node_exec_manager_dispatches_ssh_process_without_local_fallback`
- `test_kernel_exec_manager_ssh_start_disconnect_is_unknown_without_retry`

结果：`3 passed, 5 warnings in 14.45s`，pytest exit0，未超时；观察 23 个自有 PID+creation-time，测试后泄漏 0，清理后 alive=[]。日志 `artifacts/ssh-process-check-20261116-c8a073c2/pytest-9a193ce9.log`；basetemp 后缀 `3743070b9d`。五条为既有 FastAPI/Pydantic 弃用警告。

owner 测试通过真实 kernel/tool-node dispatch、真实 AsyncSSH loopback channel 和真实 pipe 子进程，证明同一 authority 下 parent/child/sibling 登记不同 owner；child 参数伪造 parent owner 被忽略；parent 对 child cancel 被拒；显式 `remote.cancel_run(child.run_id)` 后 child cancelled、parent/sibling 仍 running，最后各自清理。后两项分别覆盖 ExecManager 无本机 fallback 的自然 completed/exit0，以及提交后断连 unknown/不重试。

测试边界：该节点手工创建三个 `AgentRunContext`、手工复制 callback，并直接调用 manager.cancel_run；尚不证明实际 delegate/spawn child 继承与正常 finish/task cancellation 自动执行生产 finally。`_wired_manager` 预接 loopback pool 并覆写 `_connect`（更新为校验 expected_authority_id），不证明实际 alias/config/host-key 认证。loopback pipe 不是真实外部主机或 OS PTY；断连节点为确定性替身。

原 Luna 报告首轮失败为 fixture `_connect(host)` 不接受新增 expected_authority_id；随后仅更新 fixture 签名并验证身份，实施侧三项 3 passed/12.12s。主控未独立执行旧 fixture 快照，不冒充亲测旧失败。

## 回调 AST 与类型锚点

主控 AST 检查快照 `run_drive.py` SHA256 `a73aa21974e3f4ebb725d12976661199bf5a008ca8d626ee0e8f0234cc7f29b4`：`ssh_tool` 定义在 3735，参数 name/arguments/owner_run_id；直接父节点为 `_execute_run:2975` 内的 `Try:3245`，不在额外条件分支内。`call_process:3741` 为 Await 内，run_id 表达式明确为 `owner_run_id or run.run_id`。随后只读定位确认 `AgentOrchestrator.run` 的 callback 类型已由 Luna 同步为 `Callable[..., Any]`。这些只证明结构/签名，不替代真实 child finally 测试。

## 实际 child 自动收尾：待验证

主控明确要求保留上述 owner 节点，并新增实际 `delegate_task → child run → run_phases finally` 的正常完成、task cancellation 两例；需证明不直接手调 manager.cancel_run 也能回收 child foreground process，父/兄弟仍运行。原 Luna 已在原会话接受并施工，尚无独立结果。窄审仅追可信身份贯穿与自动收尾，不重复终端/LSP审计。

## 既有 child 策略兼容回归

主控显式 `-o addopts=` 执行既有 `test_subagent_settings_apply_to_new_children_only` 与 `test_legacy_parallel_delegate_reaches_atlas_handler_with_parent_policy`：`2 passed, 5 warnings in 13.41s`，exit0，无超时，2 个观测自有进程、测试后泄漏0、alive=[]，日志 `pytest-df738cd1.log`。只证明这两个既有设置/父权限契约，不覆盖真实 SSH child 自动收尾或取消事件早返回；未将两次批次相加为总覆盖率。

## 真实 delegate 两项首轮独立红测

新增 `test_real_atlas_child_finish_runs_child_process_cleanup_in_run_finally` 与 `test_real_atlas_child_task_cancellation_runs_child_process_cleanup_in_run_finally` 已从实际 `agent._delegation.delegate_task(executor=atlas)` 进入 child/run/kernel，并使用本机受控 FakeLLMServer。主控独立结果 `2 failed, 5 warnings in 18.68s`，exit1，无超时，25 个观测自有进程、泄漏0、alive=[]；日志 `pytest-714f5a7f.log`。两项实际模型路由均因 SimpleNamespace 缺少 `provider_config`（`models/router.py:229`）失败，finish 返回 failed；task cancellation 未达到 second_request。尚未覆盖预期 SSH child cleanup 行为，不将失败解释为 cleanup 产品缺陷。

前后四文件 SHA256 一致：agent/__init__.py `a604b3065f9413aafc2aee5b7c52edb4cca61b1b1681c18466f464919d521f3f`；run_phases.py `fae02436150b08b099748c47f8c71846271a67c0732d310b3bda9a9fa075dd70`；tool_node.py `bf80c1eac39ed5e2637c7671d60c84544281a0f88be33c7bd447d45dcdcbe030`；test_ssh_execution_world.py `14dcf2266d2d11520420299e2739ac7a9018499341597fd3387594c9f27ee5d4`。已将准确错误交原 Luna 修测试模型接口，不允许绕过实际 router/弱化断言。

## 取消事件早返回：已复现 major，待修

独立只读 reviewer 在实际 `_run_atlas_subtask → run → execute` 与 `_turn/_pump_events` 组合中，仅替换模型引擎、持久化和远端管理器为纯内存对象，未运行网络/服务/模型/子进程。身份实际链确认：`agent/enrichment.py:804` 生成 subtask_id、`:948–953` native runner；`agent/__init__.py:781–790` 继承 callback 并 `run_id=subtask_id`；`run_phases.py:594` 写 runtime.run_id；tool-node 再由可信上下文派发。正常自然结束与直接 task.cancel 在该内存组合中均于 child runner 返回前调用自身 foreground 清理，父/兄弟记录不变。

取消事件路径另有确定性问题：`agent/__init__.py:762` async for self.run 收到 cancelled 后在 `:812–814` break，但未显式关闭异步生成器。用 Event 挡住真实 run-finally 中的 `cancel_run(child)`，观察 `child_runner_returned=True`、`returned_status=cancelled`、`cleanup_calls=[child]`，但 `foreground_cleanup_blocked=True` 且 parent/child/sibling 仍 running。放行后仅 child cancelled，最终 pending tasks0。这是“对外取消完成早于前台清理完成”，不是“永远不清理”。

快照前缀 `agent/__init__.py a7c842e5624649fd`、`run_phases.py 07ec65f28ebdde34`。已交原 Luna 在同批修复显式 async-generator 关闭/等待 finally，并补 cancel_event cleanup-gate 回归：未放行不能返回，放行后只清理 child；不得以直接 task.cancel 或显式 manager.cancel_run 代替此时序。当前 major 未关闭。

## 真实 child 三路径修复后独立通过

Luna 补上 `child_events = self.run(...)` 的显式异步生成器关闭：`_run_atlas_subtask` 在 finally 中等待 `child_events.aclose()`，并新增真实 cancel_event gate。主控在五个生产/测试源文件前后采样 SHA256，稳定一致后用既有 40 秒监督器、唯一 basetemp 运行三项：

- `test_real_atlas_child_finish_runs_child_process_cleanup_in_run_finally`
- `test_real_atlas_child_task_cancellation_runs_child_process_cleanup_in_run_finally`
- `test_real_atlas_child_cancel_event_waits_for_run_finally_process_cleanup`

结果：`3 passed, 5 warnings in 32.51s`，pytest exit0；观察 52 个自有 PID+creation-time，测试后泄漏0，清理后 `alive=[]`。日志 `artifacts/ssh-process-check-20261116-c8a073c2/pytest-8f953b33.log`；basetemp 后缀 `4e5cee0bee`。五条为既有 FastAPI/Pydantic 弃用警告。

本次真实委派通过 `delegate_task(executor=atlas)` 进入 child/run/kernel，使用受控本机 FakeLLMServer 和真实 loopback SSH process channel：正常完成、直接 task cancellation、`cancel_subtask` 触发的 cancel_event 均在 child 对外返回前完成自身 `run_phases` foreground cleanup；child record 为 cancelled、wait task 完成、lease 已释放；parent/sibling record 保持 running。cancel_event gate 在 release 前断言 runner 未完成且 child 仍 running，release 后才返回 cancelled；没有用直接 `manager.cancel_run` 冒充生命周期。

五个源文件快照前后相同：`agent/__init__.py` `870fec08b32b56bad3427f61f982ce4c58c9094b9e564d5ccfcea63257688e58`；`agent/run_phases.py` `9985e8a423688dbf0cfd57ca8ba0cd5c22442531723dee34062cdca0da06c68d`；`agent/tool_node.py` `56adf02e7fd2653c51fc0da3d606d651fa8d43a49d0a9f94018eb17e866bcd8d`；`api/run_drive.py` `da1d1b479b2dd008aa87222d8a06a067459128dbb8395412e356673a25ba2d66`；`test_ssh_execution_world.py` `7e19caec563bfe46ab2fe07a4c22b3d0b4f14833edeef842c2d300d9c337e6cc`。

验证边界：测试 manager 仍使用预接 loopback pool 并覆写 `_connect`，所以不等于外部 SSH alias/host-key/完整生产 lifespan；FakeLLMServer 是测试替身，不是真实模型。三路径 child 生命周期和 owner/cancel cleanup 已关闭原 major，sandbox 仍未实施。

## Windows loopback sandbox fail-closed 截点

主控独立在稳定源码快照上运行 `test_ssh_bwrap_rejects_windows_loopback_without_starting_user_process`：`1 passed, 5 warnings in 9.22s`，exit0；观察2个自有进程，泄漏0，`alive=[]`，日志 `artifacts/ssh-process-check-20261116-c8a073c2/pytest-1546f032.log`。`prepare_remote_sandbox` 读取目标 OS 后对 Windows loopback 明确抛出 Linux-only unavailable；无 `_processes` 用户执行记录，loopback 新命令中不含 bwrap。`ssh.py`、`run_drive.py`、该测试文件前后 SHA256 稳定。

这只证明 Windows 目标上的 unsupported/fail-closed 以及不启动用户进程；不证明 POSIX bwrap/Landlock/Seatbelt 隔离、文件写权限、网络拒绝、真实外部 SSH 或完整 lifespan。下一步可继续由原 Luna沿同一 `prepare_remote_sandbox → call_sandboxed_process → _start_process` seam 完成目标 Linux runner 的 policy/authority/canonical-cwd/side-effect 验证；不能把当前 Windows Job/Docker 或路径检查升级为 SSH OS confinement。

## SSH sandbox 接线定向测试

主控独立在稳定源码快照上运行 `tests/test_dsh_w7_sandbox.py`：`11 passed, 5 warnings in 6.54s`，exit0；观察2个自有进程，泄漏0，`alive=[]`，日志 `artifacts/ssh-process-check-20261116-c8a073c2/pytest-2146dd8d.log`，basetemp 后缀 `d1a07e0515`。六个相关源/测试文件前后哈希稳定。

定向覆盖包括：审批一次性与 justification、Docker 本地模式回归、SSH workspace 在本地 Docker/Job/命令前 fail-closed、bwrap argv 的 read-only/workspace-write/network 约束、authority pin + runner 属主/权限/namespace preflight、已有 managed SSH argv consumer、kernel dispatch 优先 SSH 而非本机 ExecManager、conversation sandbox 类型与 workspace 校验。测试替身不等于目标机 OS 隔离；本次仍无 Linux/macOS 外部 target 的真实 bwrap side-effect、网络/挂载/syscall 验证。
