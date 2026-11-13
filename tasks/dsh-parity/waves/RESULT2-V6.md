# WAVE 2 V6 结果

日期：2026-11-14  
分支：`zcode/dsh2-V6`  
Rows：X22、D13

## 行状态

- **X22 — CLOSED**：MCP reconnect budget 使用 10 次重试，起始间隔 500ms、指数退避并封顶 30s；耗尽后进入 `unreachable`。新增测试核对完整延迟序列。8836 后端的运行时健康查询还观察到 Playwright（25 tools）、Chrome DevTools（30 tools）、Serena（22 tools）均已连接且 discovery complete。真实服务器断线重连没有被人为触发，故实时证据覆盖连接与工具发现，重试语义由单测覆盖。
- **D13 — CLOSED**：新增 `present` 工具注册和执行路径；只允许呈现当前本地 workspace 中已存在的文件，并产出 artifact created 事件。后端保留 title/summary，前端规范化事件并存入 artifact store。DeepSeek 真实回合实际调用了 `present`，工具结果成功且 run 完成。

## 修改文件

- `core/atlas/agent/tool_catalog.py`、`tool_node.py`、新增 `presentation.py` — 注册并执行安全的文件呈现工具。
- `core/atlas/api/run_drive.py`、`frontend/src/renderer/services/runtimeEvents.ts` — 将 artifact 的 title/summary 从后端事件传到前端状态。
- `core/atlas/models/profiles.py` — 在 profile 匹配前剥离 provider 前缀，修复 `openai/deepseek-v4.1-flash` 错选 GPT profile、导致输出 token 上限为 None 的问题。
- `core/atlas/tools/mcp_client.py` — reconnect 首次延迟设为 500ms。
- `core/tests/test_d13_present.py`、`test_model_profiles.py`、`test_mcp_reconnect_budget.py` — 覆盖文件边界/拒绝条件、artifact 事件、DeepSeek profile 和重试延迟。
- `frontend/src/renderer/services/runtimeEvents.test.ts` — 覆盖 artifact title/summary 到 UI store 的映射。
- `docs/parity/DSH-GAP-LEDGER.md` — 更新 X22、D13 证据和状态。

## 自动化验证

`core/`：

```text
rtk proxy python -m pytest -q -p no:cacheprovider tests/test_d13_present.py tests/test_model_profiles.py tests/test_mcp_reconnect_budget.py
13 passed, 5 warnings
```

`frontend/`：

```text
rtk proxy npm test -- --run src/renderer/services/runtimeEvents.test.ts
7 passed
```

`rtk git diff --check` 通过。5 条 warning 是既有 FastAPI/Pydantic 弃用警告。

## 指定真实模型验证（端口 8836）

按计划在启动后端的 shell 设置 `http_proxy=http://127.0.0.1:7897`，使用 `deepseek-v4.1-flash`，base URL `https://d1api.xin/v1`。WebSocket smoke：

```text
python scripts/dsh_live_ws_check.py 8836 "Reply with exactly the word: OK"
[event] run.started
[event] ...
[terminal] run.completed
[reply] 'OK'
[result] terminal=run.completed chars=2
```

真实模型选 profile 时曾触发 `max_output_tokens=None`；修正 profile 前缀匹配后此回合成功。独立 D13 真实模型回合的 run log 记录了 `present` 的 tool_start、`tool_end state=completed`、`tool_result is_error=false` 和 `run_end completed`。前端事件到 store 的字段映射另由上述自动化测试覆盖。

8836 运行时健康查询报告 Playwright、Chrome DevTools、Serena 三个 MCP 服务已连接，工具发现分别为 25、30、22 个；此项没有模拟服务断线。

## 运行副作用与边界

第一次后端启动未设置隔离数据目录，在本 worktree 的 `data/` 下产生了约 2,366 个文件（其中约 2,349 个在 `data/upstream`）。启动时生成的 gitignored `config/atlas.toml` 已删除；没有清理 `data/`，因为启动前无文件基线，无法区分运行新建项和既有用户数据。`data/memory/` 不存在于该 worktree。

后续指定模型验证使用了 `%TEMP%\atlas-dsh-v6-live-8836` 隔离目录，其中只放入剔除密钥字段的 user settings 副本。后端与 smoke 客户端均已停止，8836 已确认空闲。平台策略拒绝了对该临时目录的递归清理，因此该目录仍留在临时路径中。

本轮未运行完整项目测试套件；自动化范围为上述聚焦测试，另完成了指定通道的真实模型和 MCP 运行时检查。
