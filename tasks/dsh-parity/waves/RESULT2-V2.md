# WAVE 2 V2 结果

日期：2026-11-14  
分支：`zcode/dsh2-V2`  
Rows：E3、E4

## 状态

- **E3 — 已接线**：`ToolScheduler` 的 typed `pre_execute`、执行、`post_execute`、`result_stage` 已在 kernel loop 统一调用。既有 `PreToolUse`、`PostToolUse`、`PostToolUseFailure` hook 与结果校验在对应阶段执行；hook 输入替换、拒绝和 post-hook 输出替换通过 typed decision 流转。真实模型工具回合验证通过。
- **E4 — PARTIAL**：工具输出契约现已从 registry/tool catalog 经 kernel 与 API 事件到时间线和工具卡片，卡片支持 `text`、`markdown`、`json` render 和展示 label。登记工具输出在 dispatch 及 post-hook 后校验；host 工具也携带独立契约。目前无显式 schema 声明的旧工具仍使用通用 JSON 兼容 schema，因此逐工具语义 schema 未全部补齐。

## 主要改动

- `core/atlas/engine/kernel/loop.py`：接通 scheduler 三阶段 hooks/决策、最终输出契约复核，并确保 top-level tool completion 在 post/result 阶段后发出。
- `core/atlas/engine/tools/registry.py`：支持 post-hook 结果复校验。
- `core/atlas/agent/tool_catalog.py`、`core/atlas/api/run_drive.py`：为 registry、MCP/host 工具生成并传递输出契约。
- `frontend/src/renderer/components/timeline.ts`、`tool-cards/ToolExecutionCard.tsx`：保存历史/实时输出契约，并按 render 设置展示。
- `core/scripts/dsh_live_ws_check.py`：实时验收输出每个工具 completion 的契约标记。
- `docs/parity/DSH-GAP-LEDGER.md`：同步 E3/E4 状态与剩余缺口。

## 自动化验证

- 后端：`pytest -q -p no:cacheprovider tests/test_dsh_w2_tool_contract.py tests/test_backend_parity_wave2.py::test_large_tool_result_is_externalized_with_bounded_preview tests/test_kernel_tool_timeout.py tests/test_tool_scheduler_concurrency.py` → **31 passed**。
- 前端：`npm test -- --run src/renderer/components/timeline.test.ts` → **20 passed**。
- 前端生产构建：`npm run build` → **成功**；Vite 报告现有动态导入与大 chunk 警告。
- Python `compileall`（改动的后端文件）和 `git diff --check` → **通过**。
- 较宽后端回归批次另有 `test_fork_persists_parent_and_message_link` 失败，报错为“Cannot fork a session through an open turn”，位于 `session_sync.py`；重跑该单测持续挂起后中断。该失败不在本批工具流水线改动中，未把它记作通过。

## 真实模型验证

计划端口 **8832** 已被另一工作树的 uvicorn 进程 PID **82168** 占用（`D:\Atlas\.worktrees\dsh-w12`）。按不干扰其他工作树服务的原则，没有停止该进程；在空闲端口 **8835** 启动本工作树服务进行相同通道验证。

- 模型：`deepseek-v4.1-flash`
- base URL：`https://d1api.xin/v1`
- 后端启动 shell：`http_proxy=http://127.0.0.1:7897`、`https_proxy=http://127.0.0.1:7897`
- WebSocket 提示：读取工作区 `pyproject.toml`，使用工具后只回复 `OK`
- 实际事件：`tool_search`、`local_exec`、`local_file`、`concludeTurn` 均完成；每个 `tool.completed` 均显示 `output_contract=text/<tool> output`，没有 missing contract。
- 终态：`[terminal] run.completed`；`[reply] 'OK'`。
- 验证结束后已停止本批在 8835 启动的服务，并确认 8835 释放。8832 的 PID 82168 仍在运行。

## 交付边界

E3 已满足本轮接线和真实模型工具回合验收。E4 的渲染消费和传输接线已完成；E4 保留 PARTIAL，因为现有工具尚未逐个声明具备语义约束的输出 schema，当前由兼容 schema 承接旧工具。
