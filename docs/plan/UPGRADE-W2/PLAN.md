# UPGRADE-W2 规划（基于 W1 实测验收）

> 2026-11-08 独立验收 W1 后的收尾规划。W1 四阶段中 P1/P2 真做完，P4 半成品，P3 空壳。

## 一、W1 实测结论

| 阶段 | W1 交付 | 我的独立验证 | 判定 |
|---|---|---|---|
| P1 MCP 无状态 | `mcp_client.py` +3.6KB，探测式握手，默认 transport 改 streamable_http | 新测试 1 passed；`test_mcp_client.py` 4 failed/18 passed，与改动前 baseline **完全一致** | ✅ 完成 |
| P2 记忆 scope | `index.py` 加 scope 列 + ALTER 迁移 + items_scope 索引；`__init__.py` 项目 scope 推导 | 6 个新 scope 测试 passed；memory 回归 5 failed/38 passed，与 HEAD worktree 对照 **失败项一字不差** | ✅ 完成 |
| P3 AML adapter | `aml_adapter.py` 72 行 | `PROFILE_DIMENSIONS` 只是常量元组，**无计算逻辑、无数据集加载、无 judge** | ❌ 空壳 |
| P4 就地 compact | `context.py:145 compact_in_place()` + `tool_catalog.py:361` schema | 方法实现完整（keep_recent_turns / tool-call 配对保护 / budget 校验），但 **`loop.py` 无 dispatch 分支** → 模型调了落空 | ⚠️ 半成品 |

## 二、W1 出的问题（W2 必须堵死）

1. **文件边界把必需文件排除了** —— P4 只许改 `context.py` + `tool_catalog.py`，而真正要接的 `kernel/loop.py` 没在允许清单里，导致"schema 有了、dispatch 没有"的空转工具。
2. **测试里的 `store.commit()` 会真提交 git** —— `aml_adapter.add()` 第 56 行调 `self._library.store.commit(...)`，过程中冒出两个空提交 `9c5255bf`/`578cb08d`，最后靠 `git reset --mixed` 收拾。
3. **验收标准写成"schema 存在"而不是"能执行"** —— P4 的验收我只写了"工具出现在 model_facing_tools 且能被调用"，它照做了字面，但调用不产生效果。
4. **临时目录残留** —— `core/.pytest_tmp_w1_mem/` 没清。

## 三、W2 范围（只做两件，不扩）

### W2-1：P4 真正接通（核心）

**目标**：模型调用 `compact_context` → 历史被就地替换成工作状态摘要 → token 下降 → 任务继续，窗口不变。

**接入点（已侦察确认）**：

`core/atlas/kernel/loop.py` 第 953–980 行已经有 `new_context_window_callback` 的完整模式，用闭包捕获 `messages` / `summarize` / `context_manager` / `model_window`。`compact_context` 完全同构：

```
async def compact_in_place_callback() -> dict[str, Any]:
    budget = context_manager.budget(model_window)
    before = estimate_tokens(messages)
    compacted = await context_manager.compact_in_place(
        messages, summarize=summarize, budget_tokens=budget, keep_recent_turns=2)
    messages[:] = compacted          # 就地替换，不动窗口
    return {"method": "in_place", "before_tokens": before,
            "after_tokens": estimate_tokens(messages), "budget_tokens": budget}
proxy_runtime.compact_in_place_callback = compact_in_place_callback
```

dispatch 侧仿照 2800 行 `new_context` 分支：

```
if name == "compact_context":
    callback = getattr(runtime, "compact_in_place_callback", None)
    if not callable(callback):
        return {"content": "In-place compaction is unavailable for this runtime.", "is_error": True}
    result = await callback()
    await event_queue.put({"type": "context.compacted.in_place", "data": result})
    return {"content": "Compacted older history in place; the task continues in the same window.",
            "data": result, "outcome": "completed"}
```

**注意**：`context_manager` 是否已有 `compact_in_place` 方法需要核实 —— `compact_in_place` 现在写在 `ContextManager` 类里（`context.py:145`），若无则补。

### W2-2：P3 收口（诚实化）

**目标**：要么真跑出分，要么明确标成"接口预留"，不许留假装有 7 维的空壳。

**做法（二选一，按可行性判断，不许两边都糊）**：
- 若能在本地找到 / 下载 LoCoMo-Refined，写 `run_locomo(path)` 真跑，出分写 `aml-baseline.md`
- 若拿不到数据集：**删掉 `PROFILE_DIMENSIONS` 假常量**，改成 `run_locomo(path)` 入口 + 数据集缺失时明确抛 `FileNotFoundError("LoCoMo-Refined dataset not found at <path>; download from <url>")`，报告里如实写"未跑分"

**红线**：不许编造任何分数。

## 四、W2 硬约束（W1 教训固化）

1. **禁止任何 git 写操作**：`add` / `commit` / `push` / `reset` / `stash` / `checkout` / `branch` / `worktree add` 全部禁止。只读的 `status` / `log` / `diff` 可以。
2. **禁止调用 `store.commit()`** —— 会真提交 git。`aml_adapter.add()` 里的那句必须换成不提交的写路径，或改成显式参数 `commit=False`。
3. **允许改的文件**（这次写全，不许再说"被边界卡住"）：
   - `core/atlas/kernel/loop.py`
   - `core/atlas/kernel/context.py`
   - `core/atlas/agent/tool_catalog.py`
   - `core/atlas/memory/aml_adapter.py`
   - `core/tests/test_context_compact_in_place.py`
   - `core/tests/test_aml_adapter.py`（新建）
   - `docs/plan/UPGRADE-W1/*.md`（更新）
   - 上述之外**一律不许碰**，包括 `frontend/`、`config/`、其它 memory 文件。
4. **验收必须是可执行证据**：跑命令、贴真实输出，不许写"schema 已存在"。
5. **收尾必须清理**：删掉自己创建的临时目录（`--basetemp` 指到系统临时区，不许落在仓库里）。
6. **报告如实**：没做的写"未做"及原因，不许用"部分完成"含糊过去。

## 五、验收标准（我会亲自复核）

**W2-1**：
- `pytest core/tests/test_context_compact_in_place.py -q` 全绿，且**新增一条**"模拟模型调用 compact_context → 断言 history 被替换 + token 下降"的用例
- `grep -c "compact_context" core/atlas/kernel/loop.py` ≥ 1
- 手工验证：`compact_in_place_callback` 可被 dispatch 取到（打印 callable 断言）

**W2-2**：
- `grep "PROFILE_DIMENSIONS" core/atlas/memory/aml_adapter.py` 返回 0（假常量已删）
- 有 `run_locomo` 入口且数据集缺失时明确报错（不许静默返回空）
- `pytest core/tests/test_aml_adapter.py -q` 全绿
- `aml-baseline.md` 里的分数要么是真跑出来的（附命令与输出），要么明确写"未跑"

**全局**：
- `git log --oneline -3` 与开工前一致（无新提交）
- `git status --short` 里没有新增的未跟踪临时目录
