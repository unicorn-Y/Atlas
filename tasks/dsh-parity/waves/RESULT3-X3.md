# WAVE 3 — X3 结果（E28–E36）

日期：2026-11-14
分支：`wave3`
基线：`2bc3a626`

## 逐条结论

| Row | 状态 | 依据 / 未完成项 |
|---|---|---|
| E28 | PARTIAL | 压缩边界和 tool-call/result 配对保护有单测；本批没有真实模型触发压缩的回合证据。 |
| E29 | PARTIAL | 逐 surface node 计价有单测且真实回合写出 per-node estimate；provider usage 未锚定回各节点。 |
| E30 | PARTIAL | 补齐并接通 `goToImplementation`，fake LSP service-level test 通过；没有真实模型实际调用证据，统一 provider registry 也未实现。 |
| E31 | PARTIAL | `session_search`、`read_session`、`send_to_session` 可用；缺 event read/trace/lineage 一体工具面。 |
| E32 | PARTIAL | conversation worktree 可从 base branch 创建；缺 pinned revision 和 run 内切入 worktree。 |
| E33 | PARTIAL（保留 Atlas 更强） | 写路径诊断已是 PRESENT-STRONGER；本批不改实现。 |
| E34 | PARTIAL | cancel/未开始调用会合成 cancelled result，unit tests 通过；无真实模型取消回合观测。 |
| E35 | PARTIAL | DB compaction lease 有实现；缺写入 transcript 的 start/end bracket，孤儿仍依赖状态推断。 |
| E36 | PARTIAL | SQLite inbox 通知可入 steer queue，unit tests 通过；未观察真实后台任务完成后续投递回合。 |

## TDD 与测试命令输出

新增 `goToImplementation` service-level test 后、实现前的 RED：

```text
python -m pytest -q -p no:cacheprovider tests/test_lsp_service.py::test_workspace_lsp_implementation_uses_implementation_request
FAILED tests/test_lsp_service.py::test_workspace_lsp_implementation_uses_implementation_request
ValueError: Unknown LSP operation: implementation
1 failed, 5 warnings in 2.97s
```

实现后 GREEN：

```text
python -m pytest -q -p no:cacheprovider tests/test_lsp_service.py::test_workspace_lsp_implementation_uses_implementation_request
.                                                                        [100%]
1 passed, 5 warnings in 2.26s
```

X3 相关完整定向回归：

```text
python -m pytest -q -p no:cacheprovider tests/test_kernel_compaction_surface.py tests/test_token_meter.py tests/test_lsp_service.py tests/test_session_query_corpus.py tests/test_subagent_worktree.py tests/test_kernel_tool_timeout.py tests/test_kernel_checkpoint_barriers.py tests/test_notifications.py tests/test_c1_process_notifications.py tests/test_context_tool_result_pruning.py
.................................................................        [100%]
65 passed, 5 warnings in 11.70s
```

警告来自已有 FastAPI `on_event` 与 Pydantic class-based config 弃用信息。

## 真实模型命令与输出

```powershell
$env:http_proxy='http://127.0.0.1:7897'; $env:https_proxy='http://127.0.0.1:7897'; python -m uvicorn atlas.server:app --port 8873
python scripts/dsh_live_ws_check.py 8873 "Reply with exactly the word: OK"
```

真实输出：

```text
[event] run.started
[event] run.usage
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 9946, "uncached_input_tokens": 8666, "output_tokens": 2, "cached_input_tokens": 1280, "cache_write_tokens": null, "request_count": 1, "context_tokens": 9946, "context_limit": 1048576, "model": "deepseek-v4.1-flash", "w
[reply] 'OK'
[result] terminal=run.completed chars=2
```

对应 run journal：`data/logs/runs/2026-11-14/0b26a5b2-f83c-4248-b38c-64acaac8f66c.jsonl`。实际 `model_request_envelope` 记录 `model=deepseek-v4.1-flash`、`surface_token_estimate=8209`、3 个节点（4866、113、3230 tokens）；随后 run 成功并记录 9946 input tokens。节点估值和 provider usage 尚未关联到各节点，所以 E29 保持 PARTIAL。

## 本批代码改动

- `core/atlas/tools/workspace_lsp.py`：支持 LSP `textDocument/implementation`，公开 `lsp_implementation` schema。
- `core/atlas/engine/kernel/tools.py`：把新工具加入 read-only 分类和查询 timeout 类别。
- `core/atlas/engine/kernel/loop.py`：把新工具接到 kernel dispatch 映射。
- `core/tests/test_lsp_service.py`：验证 LSP method、位置参数、kernel tool surface 与 read-only 分类。
- `docs/parity/DSH-GAP-LEDGER.md`：记录 E28–E36 证据与剩余差距。

## 运行期异常

真实模型 run 收尾时，Atlas rewind checkpoint 日志再次报告 tracked 文件 `core/atlas/engine/agent/browser_password_import.py` 不存在（`FileNotFoundError`/`Bad file descriptor`）。任务启动时该文件是干净的 tracked 文件；本批没有编辑它。已恢复到基线，未带入提交。模型回合本身仍以 `run.completed` 结束。来源不明，后续真实模型回合需要继续监测。
