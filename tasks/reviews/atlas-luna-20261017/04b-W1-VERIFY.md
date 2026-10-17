# 04-LOCAL-VERIFY 补充｜W1 七条策略逐条实测（2026-10-17 第二轮）

本文件只记录**我亲自跑出来的**结果。命令、假网关、断言在仓库内 `evidence/harness/`（另存工作副本 `D:/Temp/luna-audit-20261017/verify_main/`）。仓库内不新增 pytest 测试（避免与 W1 自带的 260 行用例重复）。

## 方法（含一个必须避开的坑）

同一份独立测试脚本分别针对两棵源码树执行：

| 目标 | 源码根 | 说明 |
|---|---|---|
| W1 | `D:/atlas-luna-w1-20261017/core` | 分支 `fix/atlas-model-retry-policy-20261017` @ `e2599784` |
| 运行版 | `D:/Atlas/core` | 用户实际运行的代码（`0b1ba411` + 12 处未提交修改） |

脚本自建 `FakeGateway`（`SimpleNamespace` + 计数 `stream`），**不联网、不耗真实 token**。退避用 `asyncio.sleep` + W1 的 `_wait_for_retry` 打桩归零，避免墙钟时间干扰请求计数。

> **⚠ 测量坑（第一版结论曾因此作废）**：`D:/Atlas/core/.venv/Lib/site-packages/_editable_impl_atlas_core.pth` 里写死了 `D:\Atlas\core`，它通过 editable finder 进入 `sys.meta_path`，**优先级高于 `PYTHONPATH`**。所以单纯设 `PYTHONPATH=D:/atlas-luna-w1-20261017/core` 跑出来的其实是 `D:/Atlas` 基线代码——第一版「W1 9/9」是假的（其实是基线的 6/9 被误读）。`python -P` 也无效（.pth 由 site 处理，不走 PYTHONPATH 路径）。
>
> 正确做法：跑之前先在脚本里剔除其它 Atlas 源码根再 `sys.path.insert(0, root)`，并**断言** `atlas.kernel.model_call.__file__` 落在目标根下，否则直接退出。见 `evidence/harness/run_verify.py`，它每次运行都打印实际加载路径：

```bash
python run_verify.py "D:/atlas-luna-w1-20261017/core"   # W1
python run_verify.py "D:/Atlas/core"                     # 运行版
```

实测引导行（证明加载正确）：

```
[boot] atlas root  = D:\atlas-luna-w1-20261017\core
[boot] model_call  = D:\atlas-luna-w1-20261017\core\atlas\kernel\model_call.py
```

## 逐条结果（最终实测，两棵源码树各跑一次，引导行已验加载路径）

| # | 任务书要求 | W1 | 运行版 | 实测证据 |
|---|---|---|---|---|
| 1 | 瞬断一次后同模型重试成功 | PASS | PASS | 两侧均 `requests=2, models=['model-a','model-a'], text='recovered'` |
| 2 | 503 持续失败最多 3 次并显示完整原因 | PASS | **FAIL** | W1：`requests=3, attempts=3, model=model-a, provider=provider-model-a`；运行版：**`requests=11`**，且 `ModelCallError` **无** `attempts`/`model`/`provider` 字段 |
| 3 | 401/402/404 不重试 | PASS | PASS | 三种状态两侧均 `requests=1`（永久错误本来就即时终止） |
| 4 | 失败时不请求别的模型 | PASS | PASS（但代价极大） | 两侧 `distinct_models=['model-a']`，确认**不会换模型**；差别在次数：W1 `requests=3`，运行版 **`requests=84`** |
| 5 | 429 Retry-After 与阈值比较 | PASS | **FAIL** | 2s：两侧都重试后成功（`requests=2`）。60s：W1 `requests=1` 立即失败并带 `retry_after_s=60.0`；运行版 **`requests=2` 且不抛错**——无视 60s 直接又打一次 |
| 6 | 已有部分输出时不重发 | PASS | **FAIL** | W1 `requests=1, emitted='half answer'`；运行版 `requests=2, emitted='half answerduplicate'`，用户看到答案重复 |
| 7 | 工具 delta 之后不重发 | PASS | PASS | 两侧 `requests=1` |

**W1 9/9 通过，运行版 6/9。** 运行版失败的 3 项（2、5、6）都是用户能直接感知的：等 11 次、无视长退避继续打、答案重复。

## 请求次数矩阵（实测，均为该侧自身默认配置，未传 max_retries）

| 场景 | 运行版 | W1 |
|---|---|---|
| 503 持续失败 | **11 次** | **3 次** |
| 503 + `fallback_models` 传入 3 个候选 | **84 次**（仍只打 model-a） | **3 次** |
| 429 + `Retry-After: 2` | 2 次后成功 | 2 次后成功 |
| 429 + `Retry-After: 60` | **2 次，不抛错** | **1 次，立即失败并带 `retry_after_s=60.0`** |

> 11 次 = `max_retries` 默认 10 再加首发；84 次来自连接类分支 `unbounded_connection_retries=True` 叠加配置循环，都是我实测跑出来的数字，不是推算。

## 有效性结论

- 用户本机 **没有** `engine.model_retries` 配置键，因此走 `_retry_environment` 的默认 **10**。任务书允许 3 次，实际最多 11 次（连接类错误还叠加 `unbounded_connection_retries=True` 分支）。
- 第 6 条是用户可直接感知的症状：流式输出到一半失败后，**同一段文本会重复出现**。
- 第 2/4/5 条的失败同时说明错误卡信息不完整：运行版的 `ModelCallError` 缺 `attempts`、`retry_after_s`，前端无法呈现任务书要求的「尝试次数」「预计恢复时间」。

## 仓库内 W1 自带测试（供交叉参考）

```bash
cd /d/atlas-luna-w1-20261017
PYTHONPATH="$PWD/core" /d/Atlas/core/.venv/Scripts/python.exe -m pytest \
  core/tests/test_kernel_tool_error_regressions.py -p no:cacheprovider --basetemp=/d/Temp/pt-w1-1
```
结果：**38 passed, 5 warnings**（我亲自执行，非引用旧报告）。

## 未做 / 未覆盖

- 未做真实 provider 故障注入（不烧 token）。第 7 条的 UI 呈现未截图肉眼验收，仅代码链路核对。
- 前端 `npm run typecheck` 未跑（W1 分支只改 4 个 ts/tsx 文件，测试已在 W1 自带用例覆盖）。
- 运行版 `ModelCallError` 缺 `attempts` 字段属**产品缺陷证据**；脚本已改为 `getattr` 读该字段，使条目 2 的判定回到「请求次数」这一主信号，不再因缺字段抛异常而伪装成失败。
