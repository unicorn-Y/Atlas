# W2 结果

日期：2026-11-14  
分支：`zcode/dsh-w2`  
批次 rows：E3、E4

## 状态

- **E3 — PARTIAL**：`ToolScheduler` 现在提供 typed `pre_execute`、`post_execute`、`result_stage` 回调及 `continue` / `deny` / `replace` 决策；dispatch 仍是执行阶段。kernel loop 的既有 PreToolUse、PostToolUse 与新接口未完成统一调用接线，因此不能报 CLOSED。
- **E4 — PARTIAL**：`ToolRegistry.register()` 可接受输出 JSON Schema、render 类型和 presentation metadata；所有登记工具会得到兼容默认输出契约，handler 的成功返回按该 schema 校验，registry 暴露契约查询。逐工具专属 schema 以及 UI/render 消费仍未接线，因此不能报 CLOSED。

## 修改文件

- `core/atlas/engine/kernel/tools.py` — 增加 typed tool decision 和 scheduler stage 回调。
- `core/atlas/engine/tools/registry.py` — 增加工具输出契约、注册时 schema 检查、dispatch 成功输出校验及契约查询。
- `core/tests/test_dsh_w2_tool_contract.py` — 覆盖阶段顺序、pre-execute deny、输出 schema 成功/失败、旧工具默认契约。
- `docs/parity/DSH-GAP-LEDGER.md` — 更新 E3/E4 状态及未完成边界。

## 自动化验证

命令（在 `core/`）：

```text
rtk pytest -q -p no:cacheprovider tests/test_dsh_w2_tool_contract.py tests/test_kernel_tool_timeout.py tests/test_tool_scheduler_concurrency.py
```

输出：

```text
Pytest: 28 passed
```

## 真实模型验证（8822）

启动命令：

```text
rtk python -m uvicorn atlas.server:app --port 8822
```

服务启动输出包含：

```text
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8822 (Press CTRL+C to quit)
```

真实 WebSocket 命令：

```text
rtk python scripts/dsh_live_ws_check.py 8822 "Reply with exactly the word: OK"
```

结果（退出码 1，**未通过**）：

```text
[event] run.started
[event] run.context.sources
[event] run.status
[event] run.phase
[terminal] run.failed data={"category": "runtime", "detail": "TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType' (run log: D:\\Atlas\\.worktrees\\dsh-w2\\data\\logs\\runs\\2026-11-13\\fc380bdb-b08e-4092-8f7b-ddfa7f7532b5.jsonl)"}
[reply] ''
[result] terminal=run.failed chars=0
```

服务 traceback 指向 `core/atlas/engine/kernel/loop.py:1540`：`int(requested_output_limit)` 收到 `None`。真实模型调用未到达工具流水线，E3/E4 的真实模型路径未验证。该行在本批文件所有权之外，没有在此批修改。

## 结论

测试验证了本批新增接口与 registry schema 校验；真实模型端到端路径因上述运行时配置/处理错误失败。E3、E4 均保留 PARTIAL，不能据此宣称端到端完成。
