# Batch B — Session/state

## 结果

关闭：S3、S6、S11、S13、S32。

未关闭：S4（reader-side repair closer 仍需 kernel/reader 的更完整接线）、S9（工具结果遮蔽替换与 resume 重放）、S19（durable image attachment）、S21（session-scoped filesystem observation）、S22（真实 OTel span 调用点）、S25（per-node token pricing）。这些实现分布在本批文件边界之外或仍需 runtime 接线。

## 改动文件

- `core/atlas/engine/session_sync.py`
- `core/atlas/engine/state/atlas_state_common.py`
- `core/atlas/engine/state/atlas_state_portability.py`
- `core/atlas/engine/state/atlas_state_search.py`
- `core/atlas/session_projections.py`
- `core/atlas/run_checkpoints.py`
- 新增/更新测试：`test_fork_open_turn_guard.py`、`test_session_projections.py`、`test_session_query_corpus.py`、`test_run_checkpoints_fail_closed.py`。

## 测试

```text
rtk python -m pytest -q -p no:cacheprovider tests/test_session_projections.py tests/test_app_services_accessors.py tests/test_session_query_corpus.py tests/test_fork_open_turn_guard.py tests/test_state_schema_refusal.py tests/test_event_contract.py tests/test_run_checkpoints_fail_closed.py

56 passed, 5 warnings in 4.83s
```

`git diff --check` 对本批文件无 whitespace 错误。

## 真实模型回合

命令：`rtk python scripts/dsh_live_ws_check.py 8811 "Reply with exactly the word: OK"`

```text
[reply] 'OK'
[result] terminal=run.completed chars=2
```

终止事件的 runner 输出为 `run.completed`，模型为 `deepseek-v4.1-flash`，input 9794/output 2，cached input 9600。

## 未完成项与原因

S4/S9/S19/S21/S22/S25 没有在本批所有权内全部完成；S4 与 S9 还需要 kernel/read-repair 行为，不把已有消息表改写当成修复。真实回合只验证服务启动、WS 消息流与真实模型回复，不替代各 persistence feature 的独立运行验证。
