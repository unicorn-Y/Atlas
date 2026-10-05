# ATLAS-H1R3-CODEX-FINISH：Codex 接回，H1 最后一段

> ZCode 在 2026-10-05 约 12:50 用完额度停下。本书交回 Codex 做 controller，**只列剩下的**。
> 验收标准仍是 `tasks/taskbooks/ATLAS-H1-CORE-HARDENING.md` 第 13 节 A1–A16，**一条不降**。
> 细节要求以 `ATLAS-H1R-FINISH.md`（R0–R8）和 `ATLAS-H1R2-ZCODE-FINISH.md`（Z0–Z7）为准；本书说明现在的位置和剩下的事。
> 必读：`tasks/results/ATLAS-H1-CORE-HARDENING.progress.md` 末尾「ZCode takeover (H1R2)」一节（Lane A–I 的证据都在那里）。

---

## 0. 现在的位置（2026-10-05 13:45，Claude 核对）

施工位置：主机 `D:\Atlas-h1-core-hardening`，分支 `h1-core-hardening`，HEAD `2604ee5`，**已和远端同步**。工作区有 4 个文件未提交（Lane J 做到一半，见 J 节）。

### 已完成并有证据（不要重做）

| 项 | 证据（详见账本） |
|---|---|
| Z0 接手 | 无遗留进程；Hermes 从隔离副本加载；checkpoint `573c8e6` |
| 记忆模块测试 | 127 个通过，无需修改（Lane A） |
| server/api 测试 | 修了一个真 bug：`/api/search` 缺少 import，从 `763d553` 起每次调用都返回 500；6 个文件 158 个通过（Lane B，`660c578`） |
| R7.0 用量统计 | 累加链路完整（含子 Agent、去重、从未发出的请求退款）；契约测试通过；focused 测试 95 个通过（Lane C，`b872092`、`e4d3fd5`） |
| **缓存为 0 的原因** | 中转站**确实返回了缓存字段**（真实日志显示第 2 次请求起命中 86%–99%），是 Atlas 的汇总把它丢了；已修 |
| 渠道两个真 bug | Webhook 密钥读不到凭据库；运行时启用渠道不启动 adapter。已修，并补了 6 个回归测试（Lane F，`113cf1e`） |
| CLI 计划模式挂死 | 场景 08 超时的根因：非交互的计划模式会一直卡住。改为按拒绝处理，退出码 3（Lane G，`e39d341`） |
| 真实场景 08/10/12 的测试脚本 | 08 改成通过 WebSocket 完整走「出计划 → 批准 → 执行」；10 的插话时机修好；12 修了取证（Lane E/H） |
| 测试分层 | 共 2278 个 = 2013 unit + 249 integration + 1 desktop + 15 live；gate 脚本支持 `-Parallel`；Controller 已定：A14 按 xdist 并行计时（Lane I，`bb3e892`） |
| lint | 全仓 133 处，三条规则都低于基线（BLE001 116 < 283、S110 14 < 27、S112 3 < 4）；必须清零的目录为 0；基线文件已提交 |
| 并发 | 20 轮并发测试跑了 3 整次都通过（Lane D） |

### 剩下的

| 项 | 状态 |
|---|---|
| J：两个 H2 引入的生产回归 | 修复写了一半，未提交 |
| F1：Hermes fork 又钉在了临时分支 | Atlas 现在钉在 `h1r2-usage@d85c8ae`，不是 `atlas` 分支 |
| Z3：冷启动 ≤ 5 秒 | 最近干净测量 5.05 秒，ZCode 没动 |
| Z5：最终 gate | 都没按最终口径跑（unit/integration 计时、A6 ×20、A8、A16 前端等） |
| Z6：真实模型 12 场景 | H1R/H1R2 期间零真实调用 |
| Z7：收尾 | 未开始 |

---

## 1. 执行规则（沿用，重点重申）

- 子代理开到最大并发；热文件单 owner。子代理只跑 focused tests；**全量/分层 gate、启动计时、真实模型只由 controller 串行跑**。
- 不加新功能、不删测试、不加 skip/xfail/noqa、不放宽阈值。
- **pytest 只有进程真正退出且退出码为 0 才算通过。** 跑 gate 时套上 ZCode 验证过的 `faulthandler.dump_traceback_later(600, exit=True)` 硬退出保护（Lane D 的做法）；pytest 输出直接写文件，不要接 `tail` 等管道（ZCode 因此丢过失败名单）。
- 每次跑测试前确认 `find_spec("run_agent").origin` 指向当前钉住的 fork 代码（F1 之后会变），**不得修改 `D:\hermes-agent`**。
- 提交推到 `origin h1-core-hardening`；最终验收通过前不推 main。账本末尾新开「## Codex return (H1R3)」一节。

---

## J. 修两个 H2 生产回归（第一件事）

Lane D 已经定位、做过最小修复验证，然后按分工还原了；Lane J 正在正式修，工作区里有 4 个未提交文件（`api/conversations_router.py`、`engine/session_sync.py`、`agent/run_phases.py`、`server.py`）：

1. **回退时文件恢复从 H2 起就失效了**：`rewind_conversation` 对 `metadata` 做 `json.loads`，但 SessionDB 读出来已经是 dict → TypeError 被吞掉 → `run_ids` 总是空 → 消息回退了，**文件没回退**。半成品已改为「是字符串才解析，是 dict 直接用」。
2. **分叉摘要跑到了对话末尾**：原来是插在开头。半成品改成在克隆前算好摘要，作为 `preamble` 放进克隆的第一条。
3. 另外两处顺手修的：`run_phases.py` 防止未 await 的协程残留；`server.py` 关闭后清掉 `manager.services`，避免关闭的服务被后来的测试拿到。

要做：
- 先 review 这 4 个文件的半成品（Claude 看过 fork 部分：`source_messages` 在使用前已经定义，逻辑是通的），确认后补测试：
  - 带文件改动的回退：回退后文件内容恢复到检查点（**这个测试以前没能抓到回归，要断言文件内容，而不只是消息**）；
  - 带摘要的分叉：摘要是新会话的第一条，后面紧跟原对话截点前的内容，顺序逐条断言；
  - 关闭后 `manager.services` 不再指向已关闭的对象。
- Lane D 记录的那 7 个文件（2 失败 / 91 通过，2 个失败正好就是这两个 bug）全部转绿。
- 提交：`fix(h1r3): restore rewind file recovery and fork summary order (H2 regressions)`。

---

## F1. Hermes fork 收口到 `atlas` 分支（A2）

和 R5 是同一个问题，又出现了一次：Lane C 把 fork 的用量改动推到了 `h1r2-usage` 分支（`d85c8ae`），Atlas 也钉到了那里；而 fork 的 `atlas` 分支还停在 `cc817c54`。

- 把 `h1r2-usage` 合并进 fork 的 `atlas` 分支并推上去；`ATLAS_PATCHES.md` 补上用量相关的补丁条目（按请求出用量、缓存分项、用途标记、子 Agent 合并），每条对应到测试。
- 隔离副本 `D:\hermes-agent-h1r-closeout` 里 ZCode 存了一个 stash（`b7151dc`，是 Codex 当时没提交的 fork 半成品）。确认它的内容已经全部进入 `d85c8ae`；如果有没进去的，列出来说明是丢弃还是补上。
- Atlas `core/pyproject.toml` 改钉到 `atlas` 分支上的合并提交，更新 `docs/plan/VENDORED.md`，工作树的 `.pth` 也指向这个提交。
- 测试：fork 的用量相关测试 + Atlas `test_hermes_contract.py` + `test_run_usage_aggregation_e2e.py` 在新的钉住版本下通过。
- **以后不许再钉临时分支**：在 `test_hermes_contract.py` 加一条检查，要求 pyproject 里钉住的提交必须是 fork `atlas` 分支的祖先。这条检查需要联网，网络不通时跳过并打印原因，不算失败。

---

## Z3. 冷启动 ≤ 5 秒（A12）

ZCode 这一轮没做。要求不变（见 H1R2 第 Z3 节）：
- 先确保测量干净：没有遗留 pytest/python 进程，主机没有其他重负载；用 `core/scripts/startup_probe.py` 连续测 3 次取中位数。
- 现在 5.05 秒，差约 0.05 秒。如果干净测量仍然超时，按 `tasks/results/ATLAS-H1-H8-lifespan-spec.md` 的 O3/O4 继续压（api router 的 import 体、cli 的 `rich`），用 `-X importtime` 找最大的几项。**5 秒预算不改。**
- `test_startup_time.py` 由 controller 单独连续跑 3 次，全部通过才算。

---

## Z5. 最终 gate（controller 串行，逐项记命令、退出码、耗时）

| 项 | 要跑的 |
|---|---|
| A14 | `run_h1r_r6_gates.ps1 -Gates unit -Parallel <n>` **连续 3 次**全绿且每次 ≤ 180 秒；`unit+integration` 并行 ≤ 600 秒；desktop 层 1 次；前端全量 1 次。耗时写进 `EXECUTION-GUIDE.md` |
| A1 | `test_hermes_contract.py` AST 检查 |
| A3 | 迁移 + `atlas doctor sessions` 测试，加上 J 的回退/分叉测试 |
| A5 | `test_runtime_resources.py` |
| A6 | `test_concurrency_isolation.py` **最终口径连续 20 次**，每次进程都正常退出 |
| A7 | router 以外零 `acompletion` 的 AST 检查；仅原生配置下交接/MoA/压缩/标题测试 |
| A8 | 原生 Anthropic 四项：缓存断点、思考签名跨轮回传、tool_use 配对、网关探测与回退。**逐项找出对应的测试名**，缺哪项就用假服务补哪项 |
| A9 | `test_route_snapshot.py` |
| A10 | `test_lint_gate.py` |
| A11 | 渠道默认 `ask_writes` + 审批往返测试 |
| A13 | `test_cli_headless.py` 全部（含 Lane G 的 3 个子进程测试） |
| A16 | 前端全量 + 路由快照 + 事件类型集合和基线对比 |

如果有任何一项失败，修掉之后**整张表重跑**，不能只重跑失败的那一项。

---

## Z6. 真实模型 12 场景（A15）

规则不变（H1R 第 R7.1 节）：
- Z5 全绿之后才跑；用主机 Atlas 设置里现有的 deepseek 模型；12 个场景整轮跑 1 遍，失败的重跑 1 次确认。
- **额度按 token 算**：整轮累计不超过 300 万输入 token，单场景不超过 50 万，超了就停。不跑原生 Claude 对比。key 和原始日志不提交。
- 08、10、12 用 Lane E/H 改好的新脚本。
- 用量用修好之后的累计统计；**顺便确认中转站缓存字段的确切名字**（Lane C 推测是 `prompt_tokens_details.cached_tokens`），写进结果文件。
- 通过标准：至少 10/12，且 10、12 必须有明确结果。每个失败写根因；能修的修掉，补假模型回归测试，重跑该场景；修不了的写进 `tasks/feedback/INBOX.md`。
- 汇总表：场景、是否通过、请求次数、累计输入/输出 token、缓存 token、耗时、根因。

---

## Z7. 收尾

1. `core/scripts/baseline_metrics.py` 生成 `tasks/results/ATLAS-H1-after.json`，在结果文件里和 `ATLAS-H1-baseline.json` 做前后对比表。
2. 更新 `docs/plan/VENDORED.md`、`docs/plan/DATA-OWNERS.md`、`docs/plan/EXECUTION-GUIDE.md`、`README.md`（去掉「LangGraph orchestrator」等过时描述）。
3. 把结果文件改成最终版：A1–A16 每条写清状态和证据（测试名、命令、退出码、数字）；列出本波真实发现并修掉的生产 bug（D1/D2/D3、`/api/search` 500、渠道 GAP-1/GAP-2、CLI 计划模式挂死、回退文件恢复失效、分叉摘要位置、用量缓存丢失）。
4. 全部达标后：`h1-core-hardening` 合并进 `main`，`tasks/CURRENT.md` 改为 `CURRENT: ATLAS-H1-CORE-HARDENING` / `STATUS: AWAITING_REVIEW` / `CONTROLLER: Codex`，推 main，核对本地和远端 head 一致，停。
5. 有一项实在达不到：**不改标准**。写清差多少、试过什么，CURRENT 改为 `BLOCKED`，推分支，不推 main，停。

---

## 顺序

```
J 两个回归（先做，单 owner：conversations_router + session_sync）
F1 fork 收口（可和 J 并行，owner：fork + pyproject）
Z3 启动（可并行做优化；计时只由 controller 在 J/F1 合并后做）
 └→ Z5 最终 gate（controller 串行，整张表）
 └→ Z6 真实模型
 └→ Z7 收尾
```

不得启动：T1、X6、R1、MemoryOS、UI 改版、安全审查、新一轮上游调研。
