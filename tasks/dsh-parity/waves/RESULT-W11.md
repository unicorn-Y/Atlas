# W11 结果：MCP 与外部入口

## Rows

### X23 — MCP resources + 作用域隔离：CLOSED（既有实现，本批复核）

- `MCPClient.for_scope()` 返回 `ScopedMCPClient`；scope 过滤工具发现、工具调用、resource/template 列表和资源读取。
- kernel loop 读取当前 `AgentRunContext.mcp_server_allow`，将 MCP client 缩为该 allow-list 后用于发现和派发。
- 本批复核通过 `test_mcp_client_scope.py` 的作用域测试。`test_mcp_runtime_live.py` 中的 2 条 packaged/live MCP E2E 因默认 `-m unit` 未执行（deselected），不能算通过。真实模型回合也未能完成，见下方 live 验证；因此本批不声称重新取得了真实模型验收证据。Ledger 保留 worktree 原有 CLOSED 标记。

### X9 — 外部入口 preset：PARTIAL

- webhook automation record 会校验并保存 `agent_preset_id` 与 `permission_preset`，执行时把两者传给 `dispatch_turn`；`test_automation_capability_binding.py` 复核通过。
- ACP `session/new` 只保存 workspace/conversation，`session/prompt` 调用默认 `orchestrator.run()`；当前 handler 未把 agent preset 或 permission preset 从 ACP 请求带入 run。
- ACP handler 位于 `core/atlas/tools/app_server.py`，不属于 W11 计划分配的 `core/atlas/tools/mcp_client.py` 和 `core/atlas/automation/` 文件范围。本批没有越界修改；要完成 X9，需要将该 handler 加入明确的文件所有权后再实现 session preset 绑定及端到端覆盖。

## 文件

- `docs/parity/DSH-GAP-LEDGER.md`：将 X9 更新为 PARTIAL 并记录 ACP 的具体缺口；X23 保留 worktree 已有 CLOSED 状态。
- `tasks/dsh-parity/waves/RESULT-W11.md`：本结果记录。
- 未修改 MCP client、automation、ACP handler 或测试源码；本批复核到 X23 的 scope unit tests 通过，packaged/live MCP E2E 未运行，X9 的未完成部分落在分配目录之外。

## 测试与输出

命令（工作目录 `core/`）：

```text
python -m pytest -q -p no:cacheprovider tests/test_mcp_client_scope.py tests/test_mcp_runtime_live.py tests/test_automation_capability_binding.py
```

真实输出：

```text
.......                                                                  [100%]
7 passed, 2 deselected, 5 warnings in 5.66s
```

两条 deselected 测试遵循项目默认 `-m unit` 选择器；本次没有把它们算作通过。5 条 warning 是 FastAPI `on_event` 与 Pydantic class-based config 弃用提示。

## 真实模型进程验证

在 `core/` 启动 `python -m uvicorn atlas.server:app --host 127.0.0.1 --port 8831`，进程启动完成，输出 `Uvicorn running on http://127.0.0.1:8831`。随后运行：

```text
python scripts/dsh_live_ws_check.py 8831 "Reply with exactly the word: OK"
```

真实输出：

```text
[event] rules.loaded
[event] run.context.sources
[event] run.started
[event] mcp.startup.progress
[event] mcp.startup.progress
[event] mcp.startup.progress
[event] mcp.startup.progress
[event] mcp.startup.progress
[event] mcp.startup.progress
[event] run.status
[event] run.phase
[event] run.context.sources
[event] run.status
[terminal] run.failed data={"category": "runtime", "detail": "TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType' (run log: D:\\Atlas\\.worktrees\\dsh-w11\\data\\logs\\runs\\2026-11-13\\6e9972bf-cf24-47a5-b84e-e8784f88136f.jsonl)"}
[reply] ''
[result] terminal=run.failed chars=0
```

该 worktree 首次启动时自动从 example 创建 `config/atlas.toml`，运行日志显示实际选中的模型为 `claude-sonnet-4`，而 WAVE-PLAN 指定的真实验证模型为 `deepseek-v4.1-flash`。运行期已连接并初始化配置中的 MCP server，但模型调用前因 `int(None)` 失败；故真实模型验证 **未通过 / 未完成**，不能作为 X23 或 X9 的真实模型验收证据。
