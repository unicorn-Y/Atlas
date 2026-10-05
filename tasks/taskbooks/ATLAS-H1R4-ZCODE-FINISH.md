# ATLAS-H1R4-ZCODE-FINISH：ZCode 接手，跑完最终 gate、真实模型、收尾

> Codex 在 2026-10-05 约 15:40 用完额度停下。本书交给 ZCode 做 controller，**只列剩下的**。
> 验收标准仍是 `tasks/taskbooks/ATLAS-H1-CORE-HARDENING.md` 第 13 节 A1–A16，**一条不降**。
> 细节以 `ATLAS-H1R3-CODEX-FINISH.md` 的 Z5/Z6/Z7 为准；本书说明现在的位置和剩下的事。
> 必读：`tasks/results/ATLAS-H1-CORE-HARDENING.progress.md` 末尾「Codex return (H1R3)」一节。

---

## 0. 现在的位置（2026-10-05 17:10，Claude 核对）

施工位置：主机 `D:\Atlas-h1-core-hardening`，分支 `h1-core-hardening`，HEAD `21cbaaf`，**工作区干净，已和远端同步**（`data/dbos-startup.json`、`engine/` 是运行产物，不提交）。

### 已完成并有证据（不要重做）

| 项 | 结果 |
|---|---|
| J 两个 H2 回归 | 回退时的文件恢复、分叉摘要的位置都修好了；补了精确断言，并用反向对照证明旧代码确实会失败；132 个测试通过（`79cb47c`） |
| F1 fork 收口 | fork `atlas` 分支 = **`ab4209b0`**（含用量修复），Atlas 钉在这里；远端分支头和钉住的提交一致；加了祖先检查测试（`38b774d` 及之后） |
| Z3 冷启动 | 干净测量中位数 **3.38 秒**（3.52 / 3.30 / 3.38），`test_startup_time.py` 连续 3 次通过。**A12 达标** |
| 用量 | 能区分「中转站没报」和「报了 0」；部分缺失、格式错误的用量会挡住后续按预算的请求；139 个测试通过 |
| Z6 准备 | 真实测试脚本每个场景前都核对 fork 版本；600 秒硬退出；离线自检通过；**还没有发出任何真实请求** |
| gate 工具 | `artifacts/h1r3/controller_pytest.py`：跑前核对 Hermes 来源和钉住的版本，带 600 秒 faulthandler 硬退出，输出直接写文件 |

### 最终 gate 的情况：连续 3 轮都卡在第一项

Z5 要求整张表一次全绿，任何一项失败都要修掉后**从头重跑**。前三轮都停在 unit 第 1 次：

| 轮 | 结果 | 失败原因（均已修） |
|---|---|---|
| 1 | 2008 过 / 2 败，199 秒（超 180 秒） | Windows 下 `bash` 解析到 WSL 启动器；SQLite 工作线程没收干净。另外把真实 HTTP 的并发场景归到 integration 层，unit 时间降下来了 |
| 2 | 2006 过 / 3 败，108 秒 | 技能 API 的 fixture 被前面的测试污染；渠道退避测试依赖真实时钟 |
| 3 | 2010 过 / 1 败，110 秒 | C6 测试往共享的 `server.app` 挂了路由却不清理，导致路由快照不一致 |

**规律**：每轮暴露的都是**测试之间的状态污染**（共享的 `server.app`、`app.state.services`、模块级全局），单独跑都能过，全量按顺序跑才失败。耗时已经稳定在 110 秒左右，达标没问题。

### 剩下的

1. Z5 第 4 轮及之后：整张表一次全绿。
2. Z6 真实模型 12 场景。
3. Z7 收尾。

---

## 1. 执行规则（沿用）

- 子代理开到最大并发；热文件单 owner。子代理只跑 focused tests；**全量 gate、真实模型只由 controller 串行跑**。
- 不加新功能、不删测试、不加 skip/xfail/noqa、不放宽阈值；**不许改 `core/tests/snapshots/routes.json` 等冻结基线来掩盖差异**（Codex 已经拒绝过一次这种做法，做得对）。
- 所有 pytest 都通过 `artifacts/h1r3/controller_pytest.py` 跑（核对来源和版本、600 秒硬退出、输出直接写文件）。**只有进程正常退出且退出码为 0 才算通过。**
- 不得修改 `D:\hermes-agent`；`.pth` 继续指向 `D:\hermes-agent-h1r-closeout`（`ab4209b0`）。
- 提交推到 `origin h1-core-hardening`；最终验收通过前不推 main。账本末尾新开「## ZCode return (H1R4)」一节。

---

## P. 先一次性清掉测试污染（新增，第一件事）

不要再「跑一轮、修一个、再从头跑」。先主动把剩下的污染一次找出来：

1. **按文件随机顺序扫一遍**：用 `pytest-randomly`（如果没装，就用 `-p no:randomly` 之外的等价办法，比如自己写一个按种子打乱文件顺序的 collection hook，只放在测试辅助代码里），对 unit 层用 3 个不同的种子各跑一次（并行，8 个 worker）。在任何顺序下失败、但单独跑能过的测试，都是污染。
2. **找共享状态的源头**，而不是给每个受害测试打补丁。重点排查：
   - 往共享 `server.app` 上挂路由、改 `app.state`、改 `app.dependency_overrides` 的 fixture；
   - 会留下 `AppServices` / `runtime_mgr.services` 的 TestClient lifespan；
   - 模块级单例（channel manager、skill registry、notification bus、DBOS 全局实例、`HERMES_HOME` 相关缓存）；
   - 用 `monkeypatch` 以外的方式改全局、而且没有在 `finally` 里还原的测试。
3. 在 `core/tests/conftest.py` 加一个 **autouse 的守卫 fixture**：每个测试结束后检查 `server.app.routes` 的数量与路径集合、`app.dependency_overrides`、`app.state.services` 的关键字段，和测试开始时比较；有变化就让**造成污染的那个测试**失败，并在报错里指出它改了什么。这样以后的污染会在源头直接暴露，而不是在别处表现成随机失败。
4. 这一步的验收：3 个种子各一次随机顺序 unit 全绿，加上守卫 fixture 之后默认顺序 unit 全绿。随机顺序**只用来找问题，不作为最终 gate 的口径**。

---

## Z5. 最终 gate（整张表，一次全绿）

口径沿用 H1R3：**unit 用 8 个 worker 跑 3 次，unit+integration 用 4 个 worker 跑 1 次**，阈值 180 秒 / 600 秒不变。

| 项 | 要跑的 |
|---|---|
| A14 | unit ×3（每次 ≤180 秒、全绿）；unit+integration ×1（≤600 秒）；desktop 层 ×1；前端全量 ×1（含 Electron 慢启动测试）。耗时写进 `EXECUTION-GUIDE.md` |
| A1 | `test_hermes_contract.py`（AST 检查 + 祖先检查；祖先检查只有网络不通时可以跳过，要记录原因） |
| A3 | 迁移 + `atlas doctor sessions` + J 的回退/分叉测试 |
| A5 | `test_runtime_resources.py` |
| A6 | `test_concurrency_isolation.py` **20 次独立进程调用**，每次都正常退出（这个测试单次约 80–95 秒，20 次约 30 分钟；放在最后，单独跑） |
| A7 | router 以外零 `acompletion` 的 AST 检查；仅原生配置下交接/MoA/压缩/标题测试 |
| A8 | 原生 Anthropic 四项：缓存断点、思考签名跨轮回传、tool_use 配对、网关探测与回退。**结果文件里要逐项写出对应的测试名**；缺哪项就用假服务补哪项 |
| A9 | `test_route_snapshot.py`（基线不改） |
| A10 | `test_lint_gate.py` |
| A11 | 渠道默认 `ask_writes` + 审批往返测试 |
| A12 | 已达标（3.38 秒）；整张表跑完后再测一次冷启动，确认没有退化 |
| A13 | `test_cli_headless.py` 全部 |
| A16 | 前端全量 + 路由快照 + 事件类型集合和基线对比 |

任何一项失败：修掉 → 整张表重跑。**做完 P 以后如果又出现新的污染**，同样要从源头修，并让守卫 fixture 能抓到同一类问题。

---

## Z6. 真实模型 12 场景（A15）

规则不变（H1R3 第 Z6 节），脚本 Codex 已经准备好并离线自检过：
- Z5 整表全绿之后才跑；用主机 Atlas 设置里现有的 deepseek 模型；12 个场景整轮跑 1 遍，失败的重跑 1 次确认。
- **额度按 token 算**：整轮累计不超过 300 万输入 token，单场景不超过 50 万（脚本里保守地设在 250 万 / 40 万就停）。实际超过合同上限时立即停，结果标 `BLOCKED`，不算通过。不跑原生 Claude 对比。key 和原始日志不提交。
- 中转站缓存字段的确切名字用这一轮的真实响应确认，写进结果文件。
- 通过标准：至少 10/12，**且 08、10、12 都必须有明确结果**。每个失败写根因；能修的修掉，补假模型回归测试，重跑该场景；修不了的写进 `tasks/feedback/INBOX.md`。
- **如果为修真实场景改了生产代码**：改动涉及的 focused tests 要通过，然后把 Z5 里的 unit ×1 和受影响的项重跑一遍（不必重跑 A6 的 20 次，除非改动涉及运行时/并发）。
- 汇总表：场景、是否通过、请求次数、累计输入/输出 token、缓存 token、耗时、根因。

---

## Z7. 收尾

1. `core/scripts/baseline_metrics.py` 生成 `tasks/results/ATLAS-H1-after.json`，在结果文件里和 `ATLAS-H1-baseline.json` 做前后对比表。
2. 更新 `docs/plan/VENDORED.md`、`docs/plan/DATA-OWNERS.md`、`docs/plan/EXECUTION-GUIDE.md`、`README.md`（去掉「LangGraph orchestrator」等过时描述）。
3. 结果文件改成最终版：A1–A16 每条写清状态和证据（测试名、命令、退出码、数字）；列出本波真实发现并修掉的生产 bug：D1/D2/D3、`/api/search` 返回 500、渠道 GAP-1/GAP-2、CLI 计划模式挂死、回退时文件不恢复、分叉摘要位置错误、用量缓存丢失、Windows hook 的 bash 解析到 WSL、SQLite 工作线程泄漏、部分用量被当成 0。
4. 全部达标后：`h1-core-hardening` 合并进 `main`，`tasks/CURRENT.md` 改为 `CURRENT: ATLAS-H1-CORE-HARDENING` / `STATUS: AWAITING_REVIEW` / `CONTROLLER: ZCode`，推 main，核对本地和远端 head 一致，停。
5. 实在达不到的：**不改标准**。写清差多少、试过什么，CURRENT 改为 `BLOCKED`，推分支，不推 main，停。

---

## 顺序

```
P 污染清扫（子代理按模块并行找源头；守卫 fixture 由一个 owner 写）
 └→ Z5 整表（controller 串行；A6 的 20 次放最后）
 └→ Z6 真实模型（controller）
 └→ Z7 收尾
```

不得启动：T1、X6、R1、MemoryOS、UI 改版、安全审查、新一轮上游调研。
