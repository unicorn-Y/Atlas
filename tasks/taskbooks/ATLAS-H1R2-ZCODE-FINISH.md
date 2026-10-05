# ATLAS-H1R2-ZCODE-FINISH：ZCode 接手，把 H1 收尾

> Codex 在 2026-10-05 约 08:46 用完额度停下。本书交给 ZCode 做 controller，**只列还没完成的部分**。
> 验收标准仍是 `tasks/taskbooks/ATLAS-H1-CORE-HARDENING.md` 第 13 节的 A1–A16，**一条不降**。
> 各项要求的细节仍以 `tasks/taskbooks/ATLAS-H1R-FINISH.md`（R0–R8）为准，本书只说明现在的位置和剩下的事。
> 必读：`tasks/results/ATLAS-H1-CORE-HARDENING.progress.md`（看末尾「Codex takeover (H1R)」之后的几节）、`tasks/results/ATLAS-H1-CORE-HARDENING.result.md`（Codex 写的阶段性结果，逐条标了 PENDING/PARTIAL）。

---

## 0. 现在的位置（2026-10-05 09:00，Claude 核对）

施工位置：主机 `D:\Atlas-h1-core-hardening`，分支 `h1-core-hardening`。

- 远端 `origin/h1-core-hardening` 停在 `6e7b446`；本地多 1 个提交 `bf42417`（测试分组），还有 **37 个文件未提交**：R7.0 用量累加的半成品（`models/router.py`、`usage.py`、`cli.py`、`api/run_drive.py`、`agent/run_phases.py`、新文件 `tests/test_run_usage_aggregation_e2e.py`、`tests/fakes/session_store.py`）、R6 修测试的半成品，以及结果文件草稿。
- 已完成并有证据的（不要重做）：
  - R2 压缩路径改用 wire model（11 个测试通过）；
  - R3 SessionDB 成为唯一来源 + 安全迁移：17 个测试通过；用主机真实库的**副本**导入 59 个会话、117 条消息，时间戳全部对上，doctor 零不一致；
  - R5 fork 收口：`atlas` 分支 = `cc817c54`，Atlas 依赖已钉到这里，契约测试通过；
  - `server.py` 761 行，路由快照 394 项一致；
  - 必须清零的目录里盲捕获已经是 0（全仓还剩 133 处）。
- 没完成的：

| 项 | 现状 |
|---|---|
| R6 单元测试层 | **57 个失败**，1989 个通过，耗时 365 秒（目标 ≤180 秒） |
| R7.0 用量统计 | 按请求记录已做；CLI/服务端汇总、「4 次主请求 + 1 个子 Agent」测试、缓存为 0 的原因，都还没完成 |
| R1 冷启动 | 最近一次干净测量中位数 **5.05 秒**，差一点没达到 5 秒；后两次测量被残留进程干扰作废 |
| A6 并发 ×20、A8 原生通道、A1/A13/A11/A16 复验 | 都还没跑最终 gate |
| R7.1 真实模型 12 场景 | 一次也没跑（H1R 期间零真实调用） |
| R8 收尾 | 未开始 |

### 两个已知的坑（Codex 踩过，必须避开）

1. **Hermes 导入串到主机的副本**：工作树会继承主机的可编辑安装，`run_agent` 会解析到 `D:\hermes-agent\run_agent.py`（旧代码），导致 `ModuleNotFoundError: agent.agent_hooks` 等 18 个假失败。Codex 用工作树本地的 `.pth` 指向隔离的 fork 副本 `D:\hermes-agent-h1r-closeout` 解决。**每次跑 gate 前都要确认** `importlib.util.find_spec("run_agent").origin` 指向 `cc817c54` 那份代码。不得修改 `D:\hermes-agent`。
2. **pytest 跑完后进程不退出**：出现过多次，总结行已经打出来了，但 Python 和 PowerShell 进程还挂着，而且会干扰后续的启动计时。规则是：一次 pytest 运行**只有进程真正退出、退出码为 0** 才算通过；每次跑完都要检查有没有遗留进程。

---

## 1. 执行规则

- ZCode 是 controller。子代理开到当前允许的最大并发；热文件单 owner（`server.py`、`engine/hermes_runtime.py`、`agent/__init__.py`、`agent/run_phases.py`、`models/router.py`、`cli.py`）。
- 子代理只跑自己的 focused tests；**全量和分层 gate、启动计时，只由 controller 在没有其他 pytest 进程时串行跑**。
- 不加新功能、行为不变、不许删测试、不许加 skip 或放宽阈值来凑通过。偶发失败要单独重跑，并在账本如实记录。
- 每个 milestone 提交后推到 `origin h1-core-hardening`；**最终验收通过前不推 main**。
- 账本（progress.md）末尾新开「## ZCode takeover (H1R2)」一节，按下面 Z0–Z7 记录。

---

## Z0 接手现场

1. 确认 Codex 已经停了：工作树里 10 分钟内没有新的文件写入，也没有 Codex 进程。
2. 清理遗留进程：列出所有命令行里带 `Atlas-h1-core-hardening` 或 `Atlas-h1r-` basetemp 的 python/pytest/powershell 进程，逐个核对命令行确认属于本任务后再结束。**不碰**这台机器上的其他进程（Atlas 正式实例、vite、ZCode 自身等）。把结束了哪些进程记进账本。
3. 先跑这 37 个改动文件对应的 focused tests 并记录结果，然后原样提交：`wip(h1r2): takeover checkpoint from Codex`。合并 `origin/main`（只有文档提交），然后推到 `h1-core-hardening`。
4. 核对 Hermes 导入来源（见坑 1），把结果写进账本。

---

## Z1 R6：单元测试层清零 + 提速（A14）

1. 用 `core/scripts/run_h1r_r6_gates.ps1 -Gates unit` 重跑，拿到当前的失败清单（上次 57 个，原始记录在 `artifacts/h1r-r6-diagnostic/`）。
2. 把失败分三类处理：
   - **真 bug**：修代码，补回归测试；
   - **测试写死了旧实现**（H5 拆分、H2 改存储、H3 复用 agent 之后路径和结构都变了）：改测试去对新的公开接口做断言，**断言的业务含义不能变弱**；
   - **测试归错层**（起真服务、真子进程、真 git）：移到 integration。
   在账本里给每个失败标注属于哪一类。
3. 提速到 `unit` ≤ 180 秒、`unit + integration` ≤ 600 秒：
   - 先用 `--durations=50` 找最慢的；
   - 可以用 pytest-xdist 并行（`-n auto` 或固定数），前提是并行下连续 3 次全绿；
   - 共享的昂贵 fixture 可以改成 session/module 作用域，但不能让测试之间互相串数据。
4. desktop 层、前端全量（当前 160+）也各跑一次。
5. 最终的分组命令和三次实测耗时写进 `docs/plan/EXECUTION-GUIDE.md`。

---

## Z2 R7.0 用量统计收尾

按 H1R 第 R7.0 节的要求，把 Codex 的半成品做完：
- `atlas run` 的最后汇总、服务端的 `run_usage`，都改成本次运行**所有模型请求的累加**，分项列出（主对话 / 子 Agent / 压缩 / 标题 / 其他旁路）；
- `test_run_usage_aggregation_e2e.py`：假模型脚本化 4 次主请求 + 1 个子 Agent，断言汇总等于各次之和、分项正确；假服务返回缓存字段时汇总能带出缓存数；
- 查清真实运行里 `cached_input_tokens` 全为 0 的原因：先用假服务确认 Atlas 两轮之间的请求前缀逐字节稳定；再看中转站响应里有没有缓存字段（只看字段名，不记录 key）。结论写进结果文件。

---

## Z3 R1：冷启动 ≤ 5 秒（A12）

- 现在 5.05 秒，只差一点。先确保测量是干净的：没有遗留 pytest 进程，主机没有其他重负载，同一个脚本（`core/scripts/startup_probe.py`）连续测 3 次，看中位数。
- 如果还超：按 `tasks/results/ATLAS-H1-H8-lifespan-spec.md` 的 O3/O4 继续压（api router 的 import、cli 里的 `rich`），用 `-X importtime` 找出最大的几项。**5 秒预算不许改。**
- `test_startup_time.py` 由 controller 单独连续跑 3 次，全部通过才算。

---

## Z4 lint 全仓基线对比（A10）

- 必须清零的目录已经是 0。剩下要做的是：`test_lint_gate.py` 要真正把全仓 133 处和 H0 基线做比较，并断言不超过基线。基线文件要提交进仓库，测试要用 `--ignore-noqa` 跑。
- 如果 H0 的基线数字比 133 还小（说明这一波新增了盲捕获），就把新增的那些清掉。

---

## Z5 其余验收项的最终 gate

controller 串行逐项跑，每项都记命令、退出码、耗时：

| 项 | 要跑的 |
|---|---|
| A1 | `test_hermes_contract.py` 的 AST 检查（无私有属性赋值、无身份字符串替换） |
| A5 | `test_runtime_resources.py` |
| A6 | `test_concurrency_isolation.py` **连续 20 次**，全部退出码 0 |
| A7 | router 以外零 `acompletion` 的 AST 检查；仅原生配置下交接/MoA/压缩/标题测试 |
| A8 | 原生 Anthropic：缓存断点、思考签名跨轮回传、tool_use 配对、网关探测与回退——四项各有测试并通过。缺哪项就补哪项（用假服务，不花钱） |
| A9 | `test_route_snapshot.py` |
| A11 | 渠道默认 `ask_writes` + 审批往返测试 |
| A13 | `test_cli_headless.py`（stream-json、退出码 0/1/2/3、resume） |
| A16 | 前端全量 + 路由快照 + 事件类型集合和基线对比 |

---

## Z6 R7.1 真实模型 12 场景

规则不变（详见 H1R 第 R7.1 节）：
- 等 Z1–Z5 都绿了再跑；用主机 Atlas 设置里现有的 deepseek 模型，通过 `atlas run` 整轮跑 1 遍，失败的重跑 1 次确认；
- **额度按 token 算**：整个 Z6 累计不超过 300 万输入 token，单场景不超过 50 万，超了就停；不跑原生 Claude 对比；
- 先查清第 10、12 个场景为什么上次没出结果，以及第 08 个场景的计划步骤为什么超时 600 秒；
- 通过标准：至少 10/12，**且 10 和 12 必须有明确结果**；每个失败都要写根因，能修的修掉、补假模型回归测试、重跑；修不了的写进 `tasks/feedback/INBOX.md`；
- 汇总表（场景、是否通过、请求次数、累计 token（用 Z2 修好的统计）、缓存数、耗时、根因）写进结果文件；key 和原始日志都不提交。

---

## Z7 R8 收尾

1. `core/scripts/baseline_metrics.py` 出 `tasks/results/ATLAS-H1-after.json`，和 `ATLAS-H1-baseline.json` 做前后对比表。
2. 更新 `docs/plan/VENDORED.md`、`docs/plan/DATA-OWNERS.md`、`docs/plan/EXECUTION-GUIDE.md`、`README.md`（项目结构里的「LangGraph orchestrator」等过时描述）。
3. 把 Codex 的阶段性结果文件改成最终版：A1–A16 每条写清状态和证据（测试名、命令、退出码、数字）。没达标的如实写，不得标成通过。
4. 全部达标后：`h1-core-hardening` 合并进 `main`，`tasks/CURRENT.md` 改为 `CURRENT: ATLAS-H1-CORE-HARDENING` / `STATUS: AWAITING_REVIEW` / `CONTROLLER: ZCode`，推 main，核对本地和远端 head 一致，停。
5. 如果有一项实在达不到（比如启动卡在 5.0x 秒），**不要硬改标准**。写清差多少、试过什么，CURRENT 改为 `BLOCKED`，推分支，不推 main，停下来等用户决定。

---

## 顺序

```
Z0 接手（controller 亲自做）
 └→ 并行：Z1 测试清零（按失败模块分给多个子代理）
          Z2 用量统计（owner: router/usage/cli/run_drive/run_phases）
          Z3 启动（owner: server.py/api startup；计时只由 controller 做）
          Z4 lint 基线
 └→ Z5 最终 gate（controller 串行）
 └→ Z6 真实模型
 └→ Z7 收尾
```

不得启动：T1、X6、R1、MemoryOS、UI 改版、安全审查、新一轮上游调研。
