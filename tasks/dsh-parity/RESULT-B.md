# Batch B — Session/state

## 结果

关闭：S3、S6、S11、S13、S32。

未关闭：S4（reader-side repair closer 仍需 kernel/reader 的更完整接线）、S9（工具结果遮蔽替换与 resume 重放）、S19（durable image attachment）、S21（session-scoped filesystem observation）、S22（普通事件与 session-log 的独立队列）、S25（缺少真实模型路径和图像计价器接线）。

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

S4/S9/S19/S21 仍未完成；S4 与 S9 还需要 kernel/read-repair 行为，不把已有消息表改写当成修复。S22 仅在 `require_checkpoint()` 写入路径新增并验证 `atlas.run_checkpoint.write` 生产 span，不代表普通事件/session-log 双队列已完成。S25 增加 `price_surface_nodes(nodes, route, image_pricing)` 以及 `measure()` 可选接入，逐节点计价和回调校验有测试；由于模型调用没有 route-aware 计价调用点和生产图片计价适配器，保留 PRESENT-WEAKER。

## 后续收尾验证

```text
rtk python -m pytest -q -p no:cacheprovider tests/test_run_checkpoints_fail_closed.py tests/test_log_rotation_telemetry.py tests/test_token_meter.py tests/test_context_compact_in_place.py

22 passed, 5 warnings in 2.56s
```

新增/更新文件：`core/atlas/run_checkpoints.py`、`core/atlas/telemetry.py`、`core/tests/test_run_checkpoints_fail_closed.py`、`core/tests/test_log_rotation_telemetry.py`、`core/atlas/engine/agent/token_meter.py`、`core/tests/test_token_meter.py`。
