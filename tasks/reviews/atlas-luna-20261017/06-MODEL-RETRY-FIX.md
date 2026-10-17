# W1 模型故障策略修复

## 基线与调用链

- 基于 `ui-redesign` / `0b1ba4114e25643369c95bfac85d37563788444f` 的独立 worktree `D:\atlas-luna-w1-20261017`。
- `D:\Atlas` 工作区原有未提交改动。只读比较确认其中 `model_call.py`、`loop.py`、`run_phases.py`、`hermes_runtime.py` 的 diff 属于 expert prompt、web research、content-filter 指令，不是本次策略依赖；未复制或覆盖。
- 主会话链：`agent/run_phases.py::_phase_init` 解析所选模型 → `kernel/loop.py` 调用 `kernel/model_call.py::complete_stream` → `ModelRouter.stream`。
- 辅助调用链：`engine/hermes_runtime.py` → `ModelRouter.complete_for` → `ModelRouter.complete`。

## 修改

- `model_call.py` 将每次调用的重试硬限制为最多 2 次（同模型总 HTTP 请求最多 3 次）；默认短退避 0.5 秒、1.5 秒。环境变量和旧 watchdog 参数不能扩大上限。
- 显式 HTTP 状态只允许 408、429、500、502、503、504、529 进入重试判断；其他状态（包含 409、425、501、505）即使正文包含 timeout/connection 也不重试。没有 HTTP 状态的连接失败或超时可有限重试。内容过滤、额度、模型不存在、上下文和参数错误立即结束。`Retry-After` 超过 15 秒终止，并把恢复秒数传给错误卡。
- 当前流尝试一旦已产生文本、reasoning、refusal 或 tool-call delta，失败后不重发，保留已发布/持久化部分结果。等待期间取消事件可立即取消重试。
- 单轮只解析并请求明确选定的 model id；忽略旧 `fallback_models` 兼容参数。`run_phases.py` 不再读取主会话 fallback。`ModelRouter.complete_for` 不追加配置候选或硬编码 DeepSeek 候选。
- 错误事件包含中文分类、model id、provider、HTTP status、脱敏上游说明、request id、请求数、手动重试标志；长 `Retry-After` 会停止重试并显示预计恢复时间。HTTPX streaming status 错误在响应关闭前仅读取最多 16 KiB body，以保留 provider 原因。路由失败以 0 次请求、预算拒绝以 0 次 HTTP 请求上报。
- `run.failed(category=model)` 到达前端时暂停队列；dispatch 在暂停后不会移除队首，排队消息保留到用户手动恢复。
- 现有 HTTP 传输没有发现嵌套自动重试：`models/router.py::_client` 构造普通 `httpx.Client`，`_stream_completion` 每次 `client.stream` 单发；辅助请求 `_post_completion` 每次 `client.post` 单发。当前凭据池仅在 `ModelRouter.resolve` 通过 `pool.select(model=...)` 选择一次凭据，没有请求内轮换重发。Hermes `AIAgent` 不在当前对话链中；`HermesRuntime._agent_factory` 已明确移除该入口。

## 错误卡示例

> 模型服务暂时错误。已保留本轮已完成内容。
> model-a · provider-a · HTTP 503
> 上游说明：upstream unavailable
> 请求 ID：provider-req-16
> 请求次数：3 · 可手动重试：是

长 `Retry-After` 时卡片显示预计恢复秒数。上游异常说明同时读取 HTTP response body，并复用 `redact_sensitive_text(..., force=True)` 做秘密脱敏。

## 验证

Python 使用指定的 `D:\Atlas\core\.venv\Scripts\python.exe`，`PYTHONPATH=D:\atlas-luna-w1-20261017\core`。测试数据与 pytest 临时目录位于本 worktree 的 `.tmp`；没有启动 Atlas、连接模型服务或消耗真实 token。

命令：

```powershell
$env:PYTHONPATH='D:\atlas-luna-w1-20261017\core'
$env:ATLAS_DATA_DIR='D:\atlas-luna-w1-20261017\.tmp\model-retry-data'
rtk D:\Atlas\core\.venv\Scripts\python.exe -m pytest D:\atlas-luna-w1-20261017\core\tests\test_kernel_tool_error_regressions.py -vv -p no:cacheprovider --basetemp D:\atlas-luna-w1-20261017\.tmp\pytest-model-retry-final5
```

stdout 结论：

```text
======================= 38 passed, 5 warnings in 3.01s ========================
```

5 条 warning 是已有 Pydantic/FastAPI deprecated API 提示。

新增/调整的针对性覆盖包括：瞬断后同模型重试成功；503 最多 3 次并保留完整字段；400/401/402/403/404/409/413/422/425/501/505 不重试（400/409/422/425/501/505 的错误文本含 connection/timeout）；malformed tool-call index 不重发；503/529 长 Retry-After 不等待重试；HTTPX 未读stream body最多读16KiB、保留provider原因并经共用redactor脱敏；响应 JSON 原因被保留且 API key 被脱敏；路由身份验证失败返回 model/provider/status/attempts=0；未知或空模型在发送请求前返回完整模型路由错误；429 Retry-After 2 秒重试、16 秒停止并保留 provider request id；流式文本或 tool delta 后不重发；取消中断重试等待；主会话与辅助调用均不尝试 fallback model。

前端：

```text
vitest useAtlasStore.test.ts -t 'pauses queued follow-ups after a model failure'
1 passed, 24 skipped

vitest timeline.test.ts
17 passed

tsc -p frontend/tsconfig.renderer.json --noEmit
exit 0, no diagnostics
```

当前分支的队列定向用例命令为 `rtk node_modules\\.bin\\vitest run frontend/src/renderer/store/useAtlasStore.test.ts -t 'pauses queued follow-ups after a model failure'`，结果 `1 passed, 24 skipped`；timeline 文件 `17 passed`，renderer `tsc` 无诊断。

为核对基线失败，在干净 worktree `D:\\atlas-luna-w1-cleanbase-20261017`（HEAD `0b1ba4114e25643369c95bfac85d37563788444f`）使用 `rtk node_modules\\.bin\\vitest run frontend/src/renderer/store/useAtlasStore.test.ts --reporter=verbose` 执行完整 store 文件。结果 `3 failed | 21 passed`，失败项均存在于基线：`conversation creation > loads history and selects each opened conversation`（history mock 未初始化，断言处 `useAtlasStore.test.ts:99`）、`settings configuration > loads and saves subagent enablement and default model together`（`SettingsPage` 中 React 未定义）、`message pagination and bounded cache > defaults to the latest page and prepends an earlier one on loadEarlier`（profiles mock 为 undefined，`useAtlasStore.ts:362`）。干净基线工作树仅用于只读复核，随后删除。未运行全套后端或前端测试。

## 未验证边界

- 使用本地模拟异常，不连接真实 provider；没有测 provider 特有的所有错误体格式或真实限流恢复时间。
- 前端通过 Zustand/event 单测和 renderer TypeScript 检查，没有启动 Electron 做手工 UI 检查。
- 本提交尚待 GPT-6 独立审查；当前状态 `AWAITING_GPT6_REVIEW`。
