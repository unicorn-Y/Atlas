# WAVE 3 — X1 结果（E2 / E4 / E19 / E25）

日期：2026-11-14
分支：`wave3`
基线：`2bc3a626`

## 逐条结论

| Row | 状态 | 依据 / 未完成项 |
|---|---|---|
| E2 | CLOSED | `TurnLifecycle` 现在保留每个 step 的 typed end reason；定向单测通过。真实模型普通回合日志观察到 `step_start → step_end(response) → turn_end(completed)`，工具回合观察到 `step_end(tool_calls)`。 |
| E4 | PARTIAL | 注册工具与 host 工具均有输出合同，handler/post-hook 校验已覆盖；真实回合收到 `concludeTurn` 的输出合同。仍有 12 个存量 registry 工具使用宽泛默认 schema，MCP/host schema 也不是逐工具语义 schema，故不关闭。 |
| E19 | CLOSED | 真实模型按指令调用 `concludeTurn`，得到 `tool.completed`、一次请求后 `run.completed` 和 `CONCLUDED_OK`。现有 lifecycle 单测覆盖 `TurnConclusion` 的 typed response。 |
| E25 | PARTIAL | 真实 run 的收尾会调用 `AtlasKernel.runMaintenance()`，且 idle/active 互斥单测通过；生产 `AgentRunContext` 未设置 `maintenance_callback`，当前会回退为 no-op，缺少真实维护操作。 |

## 测试命令输出

RED（在增加 `step_reasons` 实现前运行）：

```text
python -m pytest -q -p no:cacheprovider tests/test_kernel_lifecycle_reasons.py
....FFFFFF....                                                           [100%]
6 failed, 8 passed, 5 warnings in 9.73s
```

6 个失败均为预期的 `AttributeError: 'TurnLifecycle' object has no attribute 'step_reasons'`，证明新增断言能捕获缺少的 step reason 记录。

GREEN（变更后，生命周期与工具合同定向回归）：

```text
python -m pytest -q -p no:cacheprovider tests/test_kernel_lifecycle_reasons.py tests/test_dsh_w2_tool_contract.py
.....................                                                    [100%]
21 passed, 5 warnings in 2.54s
```

警告是现存 FastAPI `on_event` 与 Pydantic class-based config 弃用提示；本批没有新增测试警告类型。

## 真实模型命令与输出

后端按计划启动：

```powershell
$env:http_proxy='http://127.0.0.1:7897'; $env:https_proxy='http://127.0.0.1:7897'; python -m uvicorn atlas.server:app --port 8871
```

真实普通回合：

```text
python scripts/dsh_live_ws_check.py 8871 "Reply with exactly the word: OK"
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 9947, "uncached_input_tokens": 9947, "output_tokens": 14, "cached_input_tokens": 0, "cache_write_tokens": null, "request_count": 1, "context_tokens": 9947, "context_limit": 1048576, "model": "deepseek-v4.1-flash", "wir
[reply] 'OK'
[result] terminal=run.completed chars=2
```

真实 `concludeTurn` 回合：

```text
python scripts/dsh_live_ws_check.py 8871 "Use the concludeTurn tool now with response exactly: CONCLUDED_OK. Do not answer in plain text."
[event] tool.preparing name=concludeTurn
[event] tool.started name=concludeTurn
[event] tool.completed name=concludeTurn output_contract=text/concludeTurn output
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 9813, "uncached_input_tokens": 8277, "output_tokens": 58, "cached_input_tokens": 1536, "cache_write_tokens": null, "request_count": 1, "context_tokens": 9813, "context_limit": 1048576, "model": "deepseek-v4.1-flash", "
[reply] 'CONCLUDED_OK'
[result] terminal=run.completed chars=12
```

该回合 run journal：`data/logs/runs/2026-11-14/3a83264e-eb98-42d7-9247-416dee3cb0de.jsonl`。实际记录的顺序为 `step_start(step=1)`、`step_end(reason=tool_calls)`、`tool_result(name=concludeTurn,state=completed)`、`turn_end(reason=completed)`、`run_end(status=completed)`。普通回合 journal `data/logs/runs/2026-11-14/95c3b0c1-a26c-4724-aa6f-11d938b1ec53.jsonl` 记录 `step_end(reason=response)` 与 `turn_end(reason=completed)`。

## HARD 项（本轮直接定性，未派工）

- E1: `HARD` — 事件日志不是模型历史真源；压缩与 rewind 不发事件，目标需要重构。
- S1: `HARD` — 缺 append-only canonical log，现有压缩/rewind 会改写消息记录。
- S2: `HARD` — surface replacement 依赖缺失的 append-only log 与原事件保留语义。
- X1: `HARD` — 需要替换 52 字段 `AppServices` 与 79 个 router 的组合根。
- X5: `HARD` — 缺少包管理器依赖解析、lockfile 回滚和取消语义。
- X6: `HARD` — 缺少包版本兼容与 profile 级风险豁免语义。
- X7: `HARD` — 缺少 build script 执行模型和逐包持久审批台账。
- E14: `HARD` — Windows per-call OS sandbox 需要 Job Object/AppContainer 执行器；Docker Engine 当前不可用。
- S30: `HARD` — Atlas 长期记忆已强于 DSH，不为对齐而退化。
- E18(host): `HARD` — host per-call OS executor 缺失，需要 Job Object/AppContainer；E18 其余审批行为仍按 PARTIAL 记录。

## 本批改动

- `core/atlas/engine/kernel/state.py`：将每次已结束 step 的 `StepEndReason` 保存在生命周期状态中。
- `core/tests/test_kernel_lifecycle_reasons.py`：覆盖每种 step end reason 的存储行为。
- `docs/parity/DSH-GAP-LEDGER.md`：更新 X1 四条结论，并将指定 HARD 项写入账本。

真实模型回合在退出时另外触发了一条既存 rewind checkpoint 错误日志：`browser_password_import.py` 当时缺失导致 `FileNotFoundError`。该跟踪文件已恢复到基线；它没有进入本批提交。该日志不影响这两次模型回合的 `run.completed`，但属于环境/工作区异常，需后续定位其发生来源。
