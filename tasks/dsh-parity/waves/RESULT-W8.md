# W8 结果：E16 统一后台作业注册表

## 状态

**E16：CLOSED。** `ExecManager` 原有 shell/subagent 注册、owner 隔离、列表/读取/终止和 byte-capped ring 已补齐 workflow 接入，并修复 Kernel 中模型发现与调用 `job_*` 的接线。定向测试和 8828 真实模型作业回合均通过。

## 实现

- Workflow 在 runner 建立后注册为 `kind=workflow`；workflow 事件持续写入同一 `ExecManager` 输出环。`job_kill` 取消正在运行的 workflow task，成功/失败/取消会 settle 任务。
- Kernel 工具 schema 暴露 `job_list`、`job_output`、`job_kill`，并由 Kernel dispatcher 直接转发给本 run 的 `ExecManager`，避免 Agent 工具节点把它们判成未知工具。
- shell 与 subagent 原有配额和输出限制保持：运行态 256 KiB、settle 后 16 KiB、每 owner 最多 10 个。

## 修改文件

- `core/atlas/engine/kernel/workflow_tool.py`
- `core/atlas/engine/kernel/tools.py`
- `core/atlas/engine/kernel/loop.py`
- `core/tests/test_kernel_exec_jobs.py`
- `docs/parity/DSH-GAP-LEDGER.md`
- `tasks/dsh-parity/waves/RESULT-W8.md`

## 测试

命令（工作目录 `core`）：

```text
rtk proxy python -m pytest -q -p no:cacheprovider tests/test_kernel_exec_jobs.py
```

真实输出：

```text
...........                                                              [100%]
11 passed, 5 warnings in 2.24s
```

5 条 warning 是既有 FastAPI `on_event` 与 Pydantic class-based config 弃用警告。

## 8828 真实模型验证

后端以隔离临时数据目录启动，模型配置副本使用任务书指定的 `https://d1api.xin/v1`；API 凭据值未输出。

基础 websocket 回合命令：

```text
rtk proxy python scripts/dsh_live_ws_check.py 8828 "Reply with exactly the word: OK"
```

输出要点：

```text
[terminal] run.completed ... "model": "deepseek-v4.1-flash"
[reply] 'OK'
[result] terminal=run.completed chars=2
```

后台作业回合使用真实模型启动 detached Python 子进程（输出 `E16_JOB_OK`，随后退出），再调用 `job_output` 和 `job_list`。实际 websocket 事件包含：

```text
[event] tool.started name=local_process
[event] tool.started name=job_output
[event] tool.completed
[event] tool.started name=job_list
[event] tool.completed
[terminal] run.completed ... "model": "deepseek-v4.1-flash"
[reply] `E16_JOB_OK|output=present|listed=completed`
```

隔离运行日志中的工具结果确认：`job_output error=False state=completed`；`job_list error=False state=completed`。模型最终逐项核验后回复 `E16_JOB_OK|output=present|listed=completed`。

初次从 worktree 示例配置启动时回合因 `requested_output_limit=None` 失败；改用隔离临时数据目录的真实配置后，首次 endpoint 返回 401。切换到任务书指定 endpoint 后基础模型回合通过。

## 验证清理说明

8828 进程已停止。初次启动时 Atlas 从示例自动生成了被 git 忽略的 `config/atlas.toml`；后续隔离运行目录 `C:\Users\25011\AppData\Local\Temp\atlas-dsh-w8-data` 包含本轮数据和真实配置副本，`C:\Users\25011\AppData\Local\Temp\atlas-dsh-w8-8828` 保存服务器日志。清理这些路径时，执行工具的自动安全策略拒绝了 `Remove-Item` 删除操作，因此它们仍留在本机；`data/memory` 的独立 git 库保持 clean。

## 关闭依据

E16 的 shell/subagent/workflow 共用 registry、模型可发现的 `job_*` schema、Kernel 到 run registry 的调用路径、bounded output、owner 配额与终止路径均有定向测试；真实模型通过 8828 触发 detached shell，并经 `job_output` / `job_list` 读到完成结果。
