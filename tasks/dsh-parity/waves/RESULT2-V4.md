# WAVE 2 — V4 结果

## 状态

**CLOSED：S4、S19、S21。** 本轮按能力跨目录接线，状态记录、生产调用方和回归用例均已补齐。

## Rows

| Row | 结果 | 实现与证据 |
|---|---|---|
| S4 | CLOSED | kernel 写入 durable `turn/start` 与 `turn/end`；`read_session_events()` 检测进程已退出的 open turn，并在 SessionDB 事务中追加 `turn/end`，不改 transcript。并发 reader 在同一写事务重查未闭合 turn，避免重复 closer。测试覆盖修复幂等及 transcript 不变。 |
| S19 | CLOSED | kernel 在追加 user transcript 前将图片写入 SHA-256 内容寻址的不可变 blob，transcript 保存 ref；`read_session_model_messages()` 每次读取重算摘要，损坏或缺失时以 `invalid_history` 阻止模型继续，不能降级成空历史。测试覆盖 round trip、损坏拒绝和 kernel fail-closed。 |
| S21 | CLOSED | 完整文件读在 SessionDB `state_meta` 中按 conversation+path 保存 provider token（存在状态、stat 与内容摘要）；edit、batch edit、write 和 append 在提交前乐观重验，成功修改后刷新 token。未观察与已观察但不存在分别保留。测试覆盖跨 runtime 的持久化、会话隔离和外部修改拒绝。 |

## 改动文件

- `core/atlas/engine/session_sync.py`：附件存取/完整性校验、文件观察 token、turn event reader repair。
- `core/atlas/engine/state/atlas_state_portability.py`：事务化、幂等的 stale turn closer 写入。
- `core/atlas/engine/kernel/loop.py`：turn 生命周期写入与图片先持久化再追加用户行。
- `core/atlas/tools/local_execution.py`：跨 session 的文件观察与写前 token 比对。
- `core/tests/test_dsh2_v4_state_rows.py`：S4/S19/S21 回归用例。
- `docs/parity/DSH-GAP-LEDGER.md`、`tasks/dsh-parity/COVERAGE.md`：关闭状态与当前实现证据。

## 自动化验证

以下在 `core/` 下分别执行：

```text
python -m pytest -q -p no:cacheprovider tests/test_dsh2_v4_state_rows.py
5 passed, 5 warnings

python -m pytest -q -p no:cacheprovider tests/test_kernel_recovery.py tests/test_atlas_session_sync.py
18 passed, 12 deselected, 5 warnings

python -m pytest -q -p no:cacheprovider tests/test_local_execution.py -k "not test_shells_executable_cwd_environment_and_nonzero_exit"
18 passed, 1 deselected, 5 warnings
```

单独包含最后一条被排除用例的首次回归结果为 `1 failed, 40 passed, 2 deselected`。失败是既有 `test_shells_executable_cwd_environment_and_nonzero_exit`：非零退出的 `local_exec` 返回 `is_error=True`，与本轮状态/附件改动无关；W5 结果已记录相同基线。该失败未被计入本轮通过项。

`compileall` 与 `git diff --check` 均通过。

## 真实模型验证（8834）

最终源码启动隔离数据目录的 Atlas 后端，启动 shell 设置：

```text
http_proxy=http://127.0.0.1:7897
https_proxy=http://127.0.0.1:7897
```

验证配置路由到 `https://d1api.xin/v1`，未设置 API key 环境变量。运行 `python scripts/dsh_live_ws_check.py 8834 "Reply with exactly the word: OK"` 的关键输出：

```text
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 7459, "output_tokens": 1, ...}}
[reply] 'OK'
[result] terminal=run.completed chars=2
[session_events] {"events": ["turn/start", "turn/end"], "repair_count": 0}
```

真实回合只证明 Atlas → `d1api.xin` → `deepseek-v4.1-flash` → WebSocket 完成链路。S4 崩溃 closer、S19 图像完整性和 S21 文件冲突边界的行为证据来自上述定向回归用例。

## 边界

S21 的 token 比对可拒绝在提交前已观察到的外部文件变化。标准文件系统接口没有可移植的条件 rename/CAS，因此不声称能阻止非协作进程恰好在最后一次比对和 `os.replace` 之间写入目标。
