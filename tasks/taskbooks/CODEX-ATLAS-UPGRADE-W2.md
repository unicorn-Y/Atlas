# CODEX 任务书 · Atlas W2 收尾（P4 接通 + P3 诚实化）

## 0. 一句话

上一轮（W1）四阶段里 P1/P2 已验收通过，**P4 是半成品、P3 是空壳**。本轮只修这两处，不做新功能、不扩范围。

完整背景与验收口径见 `D:/Atlas/docs/plan/UPGRADE-W2/PLAN.md`，**开工前先读它**。

## 1. 环境

- 解释器：`D:\Atlas\core\.venv\Scripts\python.exe`
- `PYTHONPATH=D:\Atlas\core`
- cwd：`D:\Atlas`
- 分支 `ui-redesign`，工作区有 W1 遗留的未提交改动（`mcp_client.py`、`memory/library/*`、`kernel/context.py`、`tool_catalog.py` 等）——**这些是 W1 的合法产出，不许回滚、不许重写**

## 2. 硬约束（W1 踩过的坑，违反即失败）

1. **禁止一切 git 写操作**：`add` / `commit` / `push` / `reset` / `stash` / `checkout` / `branch` / `worktree`。只读的 `status` / `log` / `diff` / `show` 可以。
2. **禁止调用 `store.commit()`**。W1 的 `aml_adapter.add()` 第 56 行调它，导致仓库里冒出两个空提交。本轮凡是写记忆的地方，走不提交的路径；需要提交时用显式 `commit=False`。
3. **允许改的文件**（写全了，不许再拿"被边界卡住"当借口）：
   - `core/atlas/kernel/loop.py`
   - `core/atlas/kernel/context.py`
   - `core/atlas/agent/tool_catalog.py`
   - `core/atlas/memory/aml_adapter.py`
   - `core/tests/test_context_compact_in_place.py`
   - `core/tests/test_aml_adapter.py`（新建）
   - `docs/plan/UPGRADE-W1/P3-aml-baseline.md`、`docs/plan/UPGRADE-W1/P4-compact-in-place.md`、`docs/plan/UPGRADE-W1/SUMMARY.md`（更新）
   
   以上之外一律不许碰。特别是 `frontend/`、`config/atlas.toml`、其它 `memory/library/*`、`agent/enrichment.py`。
4. **不许删改已有测试来凑绿**。
5. **`--basetemp` 指到系统临时区**（`$TMPDIR` 或 `C:/Users/25011/AppData/Local/Temp/...`），**不许落在仓库里**。收工前删掉自己建的临时目录。
6. **报告如实**：没做就写"未做 + 原因"，不许用"部分完成"含糊。

## 3. 任务 A：P4 真正接通（主线，你自己做）

### 现状

- `core/atlas/kernel/context.py:145` 的 `compact_in_place(history, *, summarize, budget_tokens, keep_recent_turns=2)` 实现完整：保留最近轮次 verbatim、保护 tool_call/tool_result 配对、budget 校验。**这部分是对的，不要重写。**
- `core/atlas/agent/tool_catalog.py:361` 已有 `compact_context` 的 schema，描述正确区分了与 `new_context_window` 的差异。
- **缺的是 dispatch**：`core/atlas/kernel/loop.py` 第 2800 行只有 `if name in {"new_context", "new_context_window"}` 的分支，没有 `compact_context`。模型调用这个工具时落不到任何实现。

### 要做

**(1) 在 `loop.py` 加 callback**（位置：紧邻 953–980 行的 `new_context_window_callback` 定义处，同一个闭包作用域内）

模式完全同构 —— 那里已经有 `messages`、`summarize`、`context_manager`、`model_window`、`estimate_tokens` 可用：

```python
async def compact_in_place_callback() -> dict[str, Any]:
    budget = context_manager.budget(model_window)
    before = estimate_tokens(messages)
    compacted = await context_manager.compact_in_place(
        messages, summarize=summarize, budget_tokens=budget, keep_recent_turns=2)
    messages[:] = compacted
    return {"method": "in_place", "before_tokens": before,
            "after_tokens": estimate_tokens(messages), "budget_tokens": budget}

proxy_runtime.compact_in_place_callback = compact_in_place_callback
```

**核实**：`context_manager` 是否已有 `compact_in_place` 方法。如果 `compact_in_place` 是 `ContextManager` 上的方法就直接调；如果是模块级函数就按实际签名调。**按真实代码来，不要照抄我这段伪代码。**

**(2) 在 `loop.py:2800` 附近加 dispatch 分支**

```python
if name == "compact_context":
    callback = getattr(runtime, "compact_in_place_callback", None)
    if not callable(callback):
        return {"content": "In-place compaction is unavailable for this runtime.",
                "is_error": True}
    result = await callback()
    await event_queue.put({"type": "context.compacted.in_place", "data": result})
    return {"content": "Compacted older history in place; the task continues in the same window.",
            "data": result, "outcome": "completed"}
```

返回值形状必须和 `new_context_window` 分支一致（照它的实际返回结构写，别照抄我的）。

**(3) 补测试** `core/tests/test_context_compact_in_place.py`（已存在，追加）

必须新增一条**端到端**用例，不是只测 `compact_in_place` 本身：
- 构造 40 轮带 tool_call/tool_result 的历史
- 通过 dispatch 路径调用 `compact_context`（能起 runtime 就起，起不来就 mock 出 `proxy_runtime` 并断言 callback 被调用且 `messages` 被替换）
- 断言：token 下降 ≥50%、`messages` 对象被就地替换（不是返回新列表）、最近 2 轮 verbatim 还在、`goal`/`open_items` 在摘要里

### 验收（必须贴真实输出）

```
cd /d/Atlas && PYTHONPATH=D:/Atlas/core core/.venv/Scripts/python.exe -m pytest core/tests/test_context_compact_in_place.py -q --basetemp=<系统临时区>
grep -n "compact_context" core/atlas/kernel/loop.py
```

两条都要有输出，`grep` 至少 2 处命中（callback 定义 + dispatch 分支）。

---

## 4. 任务 B：P3 诚实化（开一个 worker 子代理做，与你并行）

### 现状

`core/atlas/memory/aml_adapter.py` 72 行，`PROFILE_DIMENSIONS` 是个 7 元素常量元组，**没有任何计算逻辑**。它跑不出任何分数，却在报告里挂着"7 维剖面"。

### 要做（二选一，按真实可行性判断）

**路线 1 —— 能拿到数据集就真跑：**
- 找 `LoCoMo-Refined`（GitHub / HuggingFace）。拿到就写 `run_locomo(dataset_path) -> dict`，真跑 7 维、出真分数
- 报告里贴命令 + 真实输出 + 数据集来源 URL

**路线 2 —— 拿不到就诚实降级：**
- **删掉 `PROFILE_DIMENSIONS` 假常量**
- 改成 `run_locomo(dataset_path)` 入口，数据集不存在时抛 `FileNotFoundError("LoCoMo-Refined dataset not found at <path>; source: <url>")`，**不许静默返回空 dict、不许返回全 0**
- `aml-baseline.md` 明确写"未跑分，缺数据集"

### 红线

**不许编造任何分数。** 没有真跑就写"未跑"。

### 附带必做

- `aml_adapter.add()` 里的 `store.commit(...)` 必须去掉或改成 `commit=False`（W1 的空提交就是它干的）
- 新建 `core/tests/test_aml_adapter.py`：测 `add`/`search` 接口契约 + 数据集缺失时的报错行为

### 验收

```
cd /d/Atlas && PYTHONPATH=D:/Atlas/core core/.venv/Scripts/python.exe -m pytest core/tests/test_aml_adapter.py -q --basetemp=<系统临时区>
grep -c "PROFILE_DIMENSIONS" core/atlas/memory/aml_adapter.py   # 必须是 0
grep -n "store.commit\|\.commit(" core/atlas/memory/aml_adapter.py   # 必须为空
```

---

## 5. 收尾（你自己做）

1. 更新 `docs/plan/UPGRADE-W1/P4-compact-in-place.md`：写清 dispatch 接入位置（文件+行号）、callback 形状、测试证据
2. 更新 `docs/plan/UPGRADE-W1/P3-aml-baseline.md`：写清走了哪条路线、数据集来源、真分数或"未跑"
3. 更新 `docs/plan/UPGRADE-W1/SUMMARY.md`：W2 收尾后的四项最终状态
4. **清理临时目录**，确认 `git status --short` 没有新增未跟踪目录
5. 最后跑一次：

```
git log --oneline -3          # 必须还是 c72b4c4f / 32c22061 / b3e5f9d6
git status --short | head -30
```

**`git log` 有变化 = 你违规提交了，立即报告，不要自己 reset。**

## 6. 现在开始

先回一句「已读，开始」，并说明：
- 你核实到的 `compact_in_place` 真实签名
- `context_manager` 上有没有这个方法
- 任务 B 你选路线 1 还是路线 2，理由

然后开工。不要等我确认。
