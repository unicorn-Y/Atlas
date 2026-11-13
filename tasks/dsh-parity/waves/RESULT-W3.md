# W3 批次结果

## Rows

- **E8 — PARTIAL**：静态检查确认 kernel 每次模型调用前走 context prepare，overflow 重试只在 provider history surface 改变后继续；8823 的真实模型检查在 dispatch 前失败，未取得模型回合证据。失败发生于 `loop.py` 将 `requested_output_limit=None` 转成 `int`。`loop.py` 不属于 W3 所有权，本批未修改。
- **S9 — PARTIAL**：tool-result 剪枝默认阈值、头部和尾部分别为 8192/4096/1024 字符；剪枝前保存完整结果，返回带 `output_ref`、`microcompacted` 和 `masked_content` 标记的替换节点。测试覆盖阈值边界、头尾、原始文件和重复处理稳定性。真实 session 持久化与进程重启后的 resume 重放未验证，不能关闭。
- **S25 — PARTIAL**：逐 surface node 计价、route-aware 图像计价及 `measure()` 集成已有实现，定向测试通过；生产模型请求调用点和生产图像定价回调仍缺失，超出本批目录所有权。

## 修改文件

- `core/atlas/engine/kernel/context.py` — 将 microcompact 默认阈值/保留片段设为 8192/4096/1024 字符，并在剪枝替换节点写入遮蔽标记。
- `core/tests/test_context_tool_result_pruning.py` — 新增阈值边界、头尾保留、全文存储和重复处理测试。
- `docs/parity/DSH-GAP-LEDGER.md` — 更新 E8、S9、S25 状态和证据。
- `tasks/dsh-parity/waves/RESULT-W3.md` — 本批结果。

## 测试输出

命令（`core/`）：

```text
rtk pytest -q -p no:cacheprovider tests/test_context_tool_result_pruning.py tests/test_token_meter.py tests/test_kernel_compaction_surface.py
Pytest: 21 passed
```

第一次运行时新增测试夹具只有一组工具结果，按既有策略会被 `keep_recent_tool_results=1` 保留；随后改用两组结果验证旧结果剪枝，第二次运行通过。

## 真实模型检查（端口 8823）

命令：

```text
python scripts/dsh_live_ws_check.py 8823 "Reply with exactly the word: OK"
```

真实输出摘录：

```text
[event] run.started
[event] run.phase
[terminal] run.failed data={"category": "runtime", "detail": "TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType' ..."}
[reply] ''
[result] terminal=run.failed chars=0
LIVE_CHECK_EXIT=1
```

后端在 `127.0.0.1:8823` 正常启动并接受 WebSocket；run log 为 `data/logs/runs/2026-11-13/de07a5a5-8bc8-4f49-9859-f18574fccaa1.jsonl`。日志表明运行选择了 `anthropic/claude-sonnet-4-20250514`，kernel 在模型请求发送前于 `loop.py:1540` 对空的 `requested_output_limit` 执行 `int()` 并失败；因此没有取得任何真实模型回复。服务进程已停止。
