# Atlas W1 补丁（模型故障重试策略）独立验证报告

验证日期：2026-10-17  
验证分支：`fix/atlas-model-retry-policy-20261017`  
验证 Commit：`e259978420f944ef57bdb15ed22a8890486c018e`  
测试脚本：`D:/Temp/luna-audit-20261017/verify_w1/test_independent_model_retry.py`  
测试框架：pytest 9.1.1, Python 3.14.7, 本地假 HTTP 网关 (`ThreadingHTTPServer` + `BaseHTTPRequestHandler`)

---

## 7 条规格真实 HTTP 调用独立验证结果

| 序号 | 规格内容 | 结果 | 关键证据与断言指标 |
| :--- | :--- | :---: | :--- |
| 1 | 网络瞬断一次（第1次 503），同模型第2次成功 → 最终成功，请求总数=2，没有换模型 | **PASS** | 假网关记录请求数: 2；两次请求 body 中的 `model` 字段均为 `primary-wire-model`；`result.attempts=2`；`result.text="Hello world"`。 |
| 2 | 持续 503 → 同一模型总共最多 3 次 HTTP 请求（首次+2次重试），然后抛错；错误对象含 category/status/attempts=3/provider/model | **PASS** | 假网关记录请求数: 3；三次请求 `model` 均为 `spec2-wire`；捕获 `ModelCallError`；`err.attempts=3`；`err.status=503`；`err.category in {'provider', 'connection', 'overloaded'}`；`err.provider="test-provider"`；`err.model="spec2-model"`。 |
| 3 | 401 / 402 / 404 → 只请求 1 次，不重试，直接抛错 | **PASS** | 401/402/404 各自发起测试，假网关各仅记录 1 次请求；直接抛出 `ModelCallError`，`err.attempts=1`，`err.status` 分别对应 401, 402, 404，没有进入任何重试等待。 |
| 4 | 指定模型 A 失败时，全程没有任何请求打到模型 B；models/router.py 的 complete_for 不再隐式追加 deepseek 备用模型 | **PASS** | 1. 传入 `fallback_models=['model-B', 'deepseek-v4.1-flash']`，模型 A 连续失败 3 次，假网关 3 次请求记录模型全为 `model-A-wire`，无任何 `model-B` 或 `deepseek` 请求。<br>2. 构造 `ModelRouter.complete_for` 调用，传入 `fallbacks=['model-B', 'model-C']`，代码仅对 `model-A` 尝试 `resolve`，解析失败直接抛出异常，未尝试任何 fallback 或追加 deepseek。 |
| 5 | 429 带 Retry-After: 2 (<15s) 会重试；带 Retry-After: 60 (>15s) 不重试立即抛错，且 retry_after_s 字段被记录 | **PASS** | 1. `Retry-After: 2`：等待并在第 2 次成功返回结果，`attempts=2`，重试延迟确认传递 2.0s。<br>2. `Retry-After: 60`：超过 15s 硬上限，假网关仅产生 1 次请求，立即抛出 `ModelCallError`，`err.attempts=1`，`err.retry_after_s=60`，`_wait_for_retry` 调用次数为 0。 |
| 6 | 流式已产出部分 text delta 后连接中断 → 不重发该请求（请求总数=1），已产生的文本保留在结果/异常里，不重复 | **PASS** | 假网关发送部分 SSE text chunk 后断开连接，假网关仅收到 1 次请求（未重发）；调用方抛出 `ModelCallError`，已通过回调收集的 text 为 `"Hello partially emitted"`，未被清空或重复发送。 |
| 7 | 若工具调用 delta 已产生后失败 → 不重发（避免工具副作用重放） | **PASS** | 假网关发送 tool_calls delta 后断开连接，假网关仅收到 1 次请求（未重发）；抛出 `ModelCallError`，`on_event` 接收到了中断前的 `tool_call_delta`。 |

---

## 2 点代码事实核查结论

### a) max_retries 是否被硬上限压到 2（首次 + 2 次重试 = 最多 3 次 HTTP 请求）
- **结论：核查通过，无绕过路径。**
- **代码事实**：
  - 在 `core/atlas/kernel/model_call.py` 的 `complete_stream` 入口：
    ```python
    max_retries = _retry_environment(max_retries, retry_watchdog, retry_watchdog_max_wait_s, overloaded_retry_base_delay_s)[0]
    max_retries = min(2, max_retries)
    ```
    此处通过 `min(2, max_retries)` 将允许的重试次数强制截断为不超过 2。
  - `candidates = [str(model_id)] if model_id else []`：外部传入的任何 `fallback_models` 均被忽略，模型候选列表只包含单一模型。
  - `unbounded_connection_retries: bool = False` 参数在 `complete_stream` 中虽作为签名保留，但没有参与任何重试上限的绕过逻辑；`hermes_runtime.py` 中调用时也显式指定了 `unbounded_connection_retries=False`。
  - 内部凭据池：Atlas 的 `ModelRouter` 直接通过 `RouteSpec` 获取单一凭据，在 `complete_stream` 循环中不存在内部轮转多个密钥发起额外重试的循环。因此对于偶发错误，同一模型最多请求 1 + 2 = 3 次。

### b) run_phases.py 与前端 dispatchQueue 队列处理
- **结论：核查通过，无自动切模型，模型失败时队列暂停并保留。**
- **代码事实**：
  - `core/atlas/agent/run_phases.py`（第 324 行）：
    ```python
    # A run remains pinned to its selected model; fallbacks require a user choice.
    runtime.fallback_models = []
    ```
    补丁将 `runtime.fallback_models` 显式重置清空，彻底移除了从配置中读取 fallback 并自动降级切模型的行为。
  - 前端 `frontend/src/renderer/store/useAtlasStore.ts`：
    当接收到 `run.failed` 且 `data.category === 'model'` 时（第 688 行）：
    ```typescript
    if (data.category === 'model') {
      set((state) => ({ queuePaused: { ...state.queuePaused, [run.conversationId]: true } }));
    }
    ```
    在 `dispatchQueue(conversationId)`（第 1168 行）中：
    ```typescript
    if (!next || get().queuePaused[conversationId] || activeRunFor(conversationId)) return;
    ```
    当 `queuePaused[conversationId]` 为 `true` 时，`dispatchQueue` 会立即退出，不会继续派发下一个排队任务；同时 `queue` 状态保持不变，原排队内容完整保留在 store 中。

---

## 总体结论
- 7 条规格全部通过独立编写的真实本地 HTTP 假网关验证，断言指标完全符合规格。
- 代码事实核查表明重试次数上限、模型隔离与会话队列暂停机制均已按规格实现，**未发现规格偏差**。
