# W6 结果

## 行状态

- **S16 — CLOSED**：`SessionTimelineMixin` 已注册到 `SessionDB`，暴露 `get_session_timeline()` 和 `get_session_messages_around()`。新增测试经临时 SQLite 数据库验证真实写入、投影读取与分页结果。工作树端到端真实模型命令没有完成；该状态只表示 S16 的状态层注册目标及其数据库行为已验证。
- **S22 — PARTIAL**：`SessionDB.get_session_timeline()` 现在通过 `telemetry.span()` 产生 `atlas.session.turn_outline`，并记录 limit/returned/total；既有 `require_checkpoint()` 仍产生 `atlas.run_checkpoint.write`。普通事件和 session-log 的独立队列仍未实现，故不能关闭原 ledger 所描述的完整能力。

## 修改文件

- `core/atlas/engine/state/atlas_state.py` — 将 `SessionTimelineMixin` 加入 `SessionDB`。
- `core/atlas/engine/state/atlas_state_timeline.py` — 注册两个投影读取方法，并为 turn outline 加入可选 OTel span。
- `core/tests/test_state_timeline_registration.py` — 覆盖 SQLite 投影注册和 span 属性。
- `docs/parity/DSH-GAP-LEDGER.md` — 更新 S16、S22 证据与状态。

## 测试

命令（`core/`）：

```text
python -m pytest -q -p no:cacheprovider tests/test_state_timeline_registration.py tests/test_run_checkpoints_fail_closed.py
```

真实输出摘要：

```text
.....                                                                    [100%]
5 passed, 5 warnings in 4.43s
```

5 条弃用警告来自既有 FastAPI `on_event` 和 Pydantic class-based `config` 用法；测试没有失败。

## 8826 真实模型验证

命令（`core/`）：

```text
python scripts/dsh_live_ws_check.py 8826 "Reply with exactly the word: OK"
```

后端在 `127.0.0.1:8826` 启动。实际加载的 worktree 配置是自动从 example 生成的配置，启动日志显示默认模型 `claude-sonnet-4` / `https://api.monkeyapi.net`，与计划指定的 DeepSeek 路由不同。WebSocket 检查的实际输出结尾为：

```text
[event] run.started
[event] run.status
[event] run.phase
[event] run.status
[terminal] run.failed data={"category": "runtime", "detail": "TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType' ..."}
[reply] ''
[result] terminal=run.failed chars=0
```

uvicorn 错误记录定位到 `core/atlas/engine/kernel/loop.py:1540`：`int(requested_output_limit)` 收到 `None`；`total_input_tokens`/`total_output_tokens` 均为 0，未收到模型回复。本批不改 kernel 或配置目录，因此真实模型回合**未通过，未验证模型侧 span 导出**。8826 服务已停止（PID 70700）。
