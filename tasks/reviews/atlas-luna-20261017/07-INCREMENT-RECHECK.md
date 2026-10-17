# 增量复核 07｜运行态归因、W1 落地位、未入账缺陷（2026-10-17 第二轮）

作者：Luna 主执行者（第二轮亲自复核）。基线文件 00–06 为第一轮产物，本文件只写第一轮没有、或第一轮标为「待核实」而本轮已取到硬证据的部分。凡与 00–06 冲突处，以本文件证据为准并在文末列出更正。

## 1. 真实运行版本已归因（第一轮标「待核实」，本轮坐实）

第一轮 00-LOCAL-BASELINE.md 的进程表已过期：表中 Python 启动器 1800、后端 53140 在本轮复核时**均已退出**（`Get-CimInstance Win32_Process` 返回空）。当前实际进程链如下。

| 层级 | PID / 父 PID | 启动时间 | 关键参数 | 判定 |
|---|---|---|---|---|
| Electron 主进程 | 55644 | 2026-10-17 14:58:21 | `D:\Atlas\node_modules\electron\dist\electron.exe --remote-debugging-port=9335 --remote-allow-origins=* D:\Atlas\frontend` | 桌面壳来自该源码工作区 |
| Python 启动器 | 51284 / 55644 | 2026-10-17 16:54:17 | `D:\Atlas\core\.venv\Scripts\python.exe -m atlas.desktop_entry` | Electron 子进程 |
| Python 后端 | 50140 / 51284 | 2026-10-17 16:54:17 | 同上 | `127.0.0.1:8765` 监听归属（`Get-NetTCPConnection`） |

**决定性证据（工作进程 cwd）**：用 psutil 读取 `Process.cwd()`：

```
50140 python.exe cwd= D:\Atlas\core
51284 python.exe cwd= D:\Atlas\core
46164 python.exe cwd= D:\atlas-mem-integrate\core   ← 端口 9459，另一条独立实例
37200 python.exe cwd= D:\atlas-mem-integrate\core   ← 同上
```

即 8765 这条用户日常使用的链路，**源码根确定是 `D:\Atlas`**，不是 atlas-mem-integrate。另有一条 mem-integrate 的 9459 实例在跑（16:09 启动，未受本轮影响）。

**运行的是 HEAD 还是工作区？** 关键时间比对：

| 文件 | 磁盘 mtime | 后端进程启动 |
|---|---|---|
| `core/atlas/expert_harness.py` | 2026-10-17 12:16:39 | — |
| `core/atlas/kernel/model_call.py` | 2026-10-17 01:05:41 | — |
| `core/atlas/agent/run_phases.py` | 2026-10-17 02:53:40 | — |
| `core/atlas/kernel/loop.py` | 2026-10-17 01:05:21 | — |
| 后端 50140 | — | **2026-10-17 16:54:17** |

所有相关磁盘修改都早于后端启动 15 小时以上，且 `expert_harness.py` 是被 import 的模块（`cwd=D:\Atlas\core` 决定 `atlas` 包解析到 `D:\Atlas\core\atlas`）。结论：**当前运行的是「HEAD 0b1ba411 + 12 个未提交修改」的工作区快照，不是干净的 HEAD**。第一轮「进程加载的精确源码字节未核实」这一保留项，本轮以 cwd + mtime 顺序收口。

### 1.1 未提交修改中有一处直接改变模型故障语义

`git diff HEAD -- core/atlas/kernel/model_call.py` 只有一处，但很关键：

```python
-                        "content": ( "<content_filter_guidance>...permitted alternative...Continue unrelated authorized work.\n" )
+                        "content": filter_guidance(),   # from atlas.expert_harness
```

`core/atlas/expert_harness.py:206` → `filter_guidance()` 在 expert 模式开启时返回 `CONTINUE_FILTER_GUIDANCE`（`:112-119`），内容是「不要声明被过滤、不要道歉、不要提供替代方案，换个措辞/拆分/写到磁盘，把原任务完成」。`data/user-settings.json` 实测 `expert_mode: true`，已装 1 个 prompt（`atlas-v3`）与 24 个 skill。

因此**用户当前运行的版本**在内容过滤命中时，行为是「换措辞继续重发」，而不是任务书要求的「直接报错、不重试、不走提示词改写绕过」。

## 2. 未入账缺陷（第一轮 02-ISSUES.md 无对应编号）

### ATL-022 content_filter 被判为可重试，与任务书策略直接冲突（P1）

- **证据（基线代码本身，非本机特例）**：`ui-redesign@0b1ba411` `core/atlas/kernel/model_call.py:207` → `return "content_filter", True, status`；`classify_error` 返回可重试=True。同文件 `:858` 的 `content_filter_guidance_added` 分支会在重试前插入引导消息。
- **任务书要求**：HTTP「内容过滤」属永久性错误，直接报错不重试，且明确「不要通过提示词改写来『绕过』过滤错误」。
- **当前运行版更严重**：叠加 1.1 的 expert 注入后，它不只是重试，而是按 `CONTINUE_FILTER_GUIDANCE` **主动改写措辞重发**。
- **分类**：代码确认（基线 + 运行工作区双证据）；本机未注入过滤响应，未复现。
- **最小处理**：`classify_error` 的 content_filter 改 `retryable=False`（W1 已如此，见 `fix/...:261`），并删除 `:858` 那段重发引导分支。**注意这会与用户的 expert_harness 注入产生一次真实冲突**（见第 3 节）。
- **复杂度**：S。**执行者**：W1 扩展 / 需用户裁量（涉及 expert 模式保留与否）。

### ATL-023 运行版仍存在无界连接重试 + 默认 10 次重试（P1）

- **证据**：运行版 `core/atlas/kernel/model_call.py:564` `unbounded_connection_retries: bool = True`；`:803-812` 该分支无视 `max_retries` 直接 `will_retry`；`:608-609` 起始 5.0s 退避、`:879` 每次 ×2 上限 60s，**次数不设上限**。另 `_retry_environment`（`:71-78`）：无显式配置时 `retries = 300 if watchdog else 10`。
- **触发条件**：配置里没有 `engine.model_retries`（实测 `engine/config.yaml`、`data/user-settings.json` 均无此键），所以走 10 次默认；若错误被归为 `connection` 类别，还额外走无界分支。
- **分类**：代码确认。
- **最小处理**：W1 已把 `unbounded_connection_retries` 默认改 `False` 并 `max_retries = min(2, ...)`。但因未落地到运行版（见第 3 节），**用户今天仍在跑无界版本**。
- **复杂度**：已由 W1 覆盖。

### ATL-024 辅助模型失败会静默换到硬编码 DeepSeek（P1，运行版实际可达）

- **证据**：运行版 `core/atlas/models/router.py:378-381`
  ```python
  candidates = [model_id, *(fallbacks or [])]
  for alt in ("deepseek-v4.1-flash", "deepseek-v3"):
      if alt not in candidates:
          candidates.append(alt)
  ```
  且 `:383-389` 对每个 candidate `try/except continue`，任一失败就换下一个。与 `run_phases.py:315-317` 读取 `fallback_models` 叠加。
- **可达性（已核实的调用点，非推测）**：`complete_for` 有 6 处真实调用，覆盖 `core/atlas/agent/__init__.py:645`（MoA 并行结果汇总）、`:706`（reflection 反思）、`:909`（planning 规划）、`:927/:938/:970`，以及 `core/atlas/engine/branch_summaries.py:72`（compression 分支摘要，`max_tokens=300`）、`core/atlas/api/run_drive.py:416`、`core/atlas/engine/hermes_runtime.py:503`。也就是说规划、反思、压缩、标题这些辅助环节失败时，**用户不会得到任何提示，请求会被静默改发到 deepseek-v4.1-flash 或 deepseek-v3**。
- **本机影响边界（如实说明）**：`data/user-settings.json` 无 `fallback` 键、`config/atlas.toml` 无 `fallback` 段，故 `fallbacks` 实参为空；但**硬编码追加不受配置控制，依然生效**。当前默认模型恰好就是 `deepseek-v4.1-flash`，所以换成它时用户无感；一旦切到其他模型，这个静默换模就会显形。
- **分类**：代码确认（调用链完整）。
- **最小处理**：W1 已改为 `complete_for` 不隐式追加（`fix/...` 同函数）。同 ATL-022/023，尚未落地运行版。

### ATL-025 W1 补丁与运行版存在一处真实冲突，集成需语义决策（P1，集成风险）

实测（未污染用户目录，独立 worktree `/d/Temp/integ-probe`）：

1. 以 `0b1ba411` 建 worktree，覆盖上运行版那 3 个 dirty 文件的**当前磁盘内容**，提交为 `9481b507 runtime workspace state`（运行态快照）。
2. `git cherry-pick e2599784` → **`CONFLICT (content)` in `core/atlas/kernel/model_call.py`**，其余 11 个文件自动合并成功。
3. 冲突块唯一，正是第 1.1 节那段 `filter_guidance()` / `content_filter_guidance_added` 分支：W1 删除它，运行版保留它。
4. 按任务书语义（不重试内容过滤、不提示词绕过）取 W1 一侧删除该分支后，`cherry-pick --continue` 成功 → `4e7a87e`。
5. 集成后 `ast.parse` 通过；`test_kernel_tool_error_regressions.py` **38 passed, 5 warnings**。

**结论**：W1 可以落到用户实际运行的代码上，但**不是纯 fast-forward**，需要一次语义裁量——是否保留 expert 模式的「换措辞继续」行为。按任务书必须删；这与用户当前的 expert 使用习惯相冲突，属需要用户点头的唯一决策点。

## 3. W1 落地状态（对第一轮结论的更正）

第一轮 06 与 HANDOFF 写 W1「已修，待独立验收」。本轮核实：

- 分支 `fix/atlas-model-retry-policy-20261017` @ `e259978420f944ef57bdb15ed22a8890486c018e` 真实存在，12 文件、+587/−153，内容与自述一致。
- 在**该分支自身的代码基线上**（即 `0b1ba411`）跑 `test_kernel_tool_error_regressions.py`：**38 passed, 5 warnings**（我亲自跑的，非引用旧记录）。
- **但**该分支基于 `0b1ba411` 的干净树，而用户实际跑的是「`0b1ba411` + 12 dirty」，两者不同（第 1 节）。因此准确表述应为：**W1 在干净基线上验证通过，尚未落到用户实际运行态；落地需处理 ATL-025 的一处冲突。**

## 4. 分支覆盖补正

第一轮快照 74 个分支；本轮现场 77 个，差异为：

| 分支 | 状态 |
|---|---|
| `fix/atlas-model-retry-policy-20261017` | 本轮交付的 W1 代码分支 |
| `review/atlas-luna-global-audit-20261017` | 本轮交付的文档分支 |
| `task/hermes-atlas-implementation-20261017` | **第一轮完全未覆盖，本轮补审** |

`task/hermes-atlas-implementation-20261017` 补审结论（独立 worker 实测）：merge-base = `0b1ba411`，ahead 3 / behind 0，未被吸收。3 个 commit 全为文档（`f69f8b21`、`87aed27c` 审查交付物 + `56e2b7b3` 任务书），**Atlas 源码改动 0 行**。其任务书声称「立刻动代码、必须交真实代码」，但分支内 21 项缺陷修复与 14 个功能分支吸收**均未开始**，承诺的 `tasks/results/` 目录全量缺失。详见 `evidence/INCR-TASK-HERMES-IMPL.json`。

## 5. 本轮实测汇总（只列我亲自跑出的）

| 项 | 命令/方法 | 结果 |
|---|---|---|
| W1 分支定向测试 | `pytest core/tests/test_kernel_tool_error_regressions.py`（PYTHONPATH 指向 W1 worktree，`--basetemp` 隔离） | 38 passed, 5 warnings |
| W1→运行态集成 | cherry-pick 到运行态快照 worktree | 1 处冲突（content_filter 分支），语义消解后通过 |
| 集成后定向测试 | 同上测试文件 | 38 passed, 5 warnings |
| 集成后语法 | `ast.parse(model_call.py)` | OK |
| 运行进程 cwd | psutil | 50140/51284 = `D:\Atlas\core` |
| 分支总数 | `git ls-remote --heads` | 77（第一轮 74） |
| content_filter 分类 | 读码比对三份（HEAD/运行版/W1） | HEAD=True、运行版=True、W1=False |

## 6. 对第一轮文档的更正清单

1. `00-LOCAL-BASELINE.md` 进程表（1800/53140）已失效 → 用本文件第 1 节。
2. `00` 中「进程加载的精确源码字节未核实」→ 已收口：运行的是 `0b1ba411 + 12 dirty`（cwd + mtime 证据）。
3. `02-ISSUES.md` 缺少 ATL-022～ATL-025 四条 → 本文件补录，编号续接。
4. `06-MODEL-RETRY-FIX.md` 的「已修」应理解为「在干净基线 `0b1ba411` 上验证通过」，不等于已落到用户运行态 → 见第 3 节。
5. 分支覆盖 74 → 77，补审 `task/hermes-atlas-implementation-20261017`。

## 7. 仍未覆盖 / 不做

- 未在真实 provider 上注入故障（不烧 token），未做 Electron 手工错误卡截图验收。
- 未修改用户 `D:\Atlas` 工作区、未重启正在运行的 Atlas 进程、未触碰 `data/` 真实记忆与会话。
- 未审查 `D:\atlas-mem-integrate` 那条 9459 实例的内部状态（不在本轮范围）。
- ATL-022 的最终处置（保留 expert 改写行为 or 按任务书删除）需用户决定，本轮只给证据与冲突位置。
