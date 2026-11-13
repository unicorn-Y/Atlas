# W5 结果

## 状态

**PARTIAL：S4、S19、S21 均未关闭。** 当前 worktree 的 W5 代码所有权是 `core/atlas/engine/state/`；三行所需的生产接入点分别位于 kernel loop、agent 图片输入和 local execution 工具。只增加 state 层孤立 API 无法形成要求的端到端行为，因此没有添加无调用方实现，也没有把这三行标成 CLOSED。

## Rows

| Row | 状态 | 未关闭原因 |
|---|---|---|
| S4 | PARTIAL | reader-side `turn/end{interrupted}` closer 未实现。当前 synthetic 内容行由 `core/atlas/engine/kernel/loop.py` 写入，超出 W5 state 目录所有权。 |
| S19 | PARTIAL | durable attachment ref 未实现。图片作为瞬时 wire payload 从 `core/atlas/agent/__init__.py` 进入，state-only 变更无法在追加用户事件前准入并持久化图片。 |
| S21 | PARTIAL | session-scoped filesystem observation 未实现。读后编辑检查与文件写入位于 `core/atlas/tools/local_execution.py`，需要该调用点参与 provider version token 检查才能消除 TOCTOU。 |

## 文件

- `docs/parity/DSH-GAP-LEDGER.md`：将 S4、S19、S21 状态更新为 PARTIAL，并记录越界的生产接入点。
- `tasks/dsh-parity/waves/RESULT-W5.md`：本结果记录。
- 未改生产源码；未新增测试，因为在 W5 state 目录内无法验证这些行的生产行为。

## 测试

命令（在 `core/` 下）：

```text
python -m pytest -q -p no:cacheprovider tests/test_atlas_session_sync.py tests/test_local_execution.py tests/test_local_edit.py tests/test_c1_lifecycle_images.py
```

实际结果：`2 failed, 22 passed, 10 deselected, 5 warnings in 14.93s`。

- `tests/test_local_execution.py::test_shells_executable_cwd_environment_and_nonzero_exit`：预期 `failed["is_error"] is False`，实际为 `True`。
- `tests/test_c1_lifecycle_images.py::test_real_atlas_request_includes_transient_image_content`：`ModuleNotFoundError: No module named 'hermes_cli.config'`。
- 没有新增 W5 行为测试；以上是现有回归测试结果，不能作为 S4/S19/S21 已验证的证据。

## 真实模型回合（8825）

使用隔离临时数据目录启动本 worktree 后端；日志确认 `default=deepseek-v4.1-flash`、`api_base=https://d1api.xin/v1`。执行 `python scripts/dsh_live_ws_check.py 8825 "Reply with exactly the word: OK"` 的实际关键输出：

```text
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 7401, "output_tokens": 2, "request_count": 1, ...}}
[reply] 'OK'
[result] terminal=run.completed chars=2
```

这是后端 WebSocket、模型路由和回复传输的真实回合证据；没有触发 reader repair、图片恢复或文件读后编辑路径，不能证明三行功能已闭环。此前一次请求误连到尚未退出的旧 8825 进程并失败（`TypeError: int(None)`）；确认并停止旧 PID 后，以上回合在新隔离进程中成功。
