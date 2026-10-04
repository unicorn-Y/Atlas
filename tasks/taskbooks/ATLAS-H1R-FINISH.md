# ATLAS-H1R-FINISH：接手 H1，把剩下的做完

> 母任务书：`tasks/taskbooks/ATLAS-H1-CORE-HARDENING.md`（以下简称 H1）。验收标准仍是 H1 第 13 节 A1–A16，**一条不降**。
> 进度账本：`tasks/results/ATLAS-H1-CORE-HARDENING.progress.md`（必读，里面有每条已做事项的证据）。
> 2026-10-05 早上 ZCode 做到一半，换 Codex 接手。本书只列**剩下的**；已完成并有证据的不要重做。

---

## 0. 执行规则

沿用 H1 第 0 节：子代理开到 runtime 允许的最大并发；热文件单 owner；不加新功能；行为不变；每项修复带测试。

补充：
1. **测试串行跑 gate**：账本记录过「多个 lane 并发跑 pytest 时偶发卡住 15 分钟以上」。子代理只跑自己的 focused tests；全量/分层 gate 由 controller 在没有其他 pytest 进程时跑，并加 `--timeout`（单测 300 秒）。
2. 失败就是失败：偶发失败要单独重跑并在账本写明，不能写成全绿。
3. 每个 milestone 提交后 push 到 `h1-core-hardening` 分支（见 R0），**最终验收前不推 main**。

---

## R0 接手现场（第一步，必须先做）

施工位置：主机 `D:\Atlas-h1-core-hardening`（`main` 分支，比 origin 多 5 个提交：`0a89089 … fd1c752`）。

1. 确认 ZCode 已停止：没有其他 pytest/codex/zcode 进程在这个工作树里写文件（看进程和文件最后修改时间）。如果还在写，停下来报告用户，不要两边同时改。
2. 工作区有 ZCode 未提交的改动（23 个已改文件，以及新文件 `api/startup_components.py`、`api/deferred_startup.py`、`api/dbos_startup.py`、`tests/test_health_components.py`、`tests/live/`、`tests/test_live_full_run*.py` 等）。内容是 H8 启动拆分做到一半，加上 H10.2 剩余场景的脚手架。
   - 先跑这些文件对应的 focused tests 并记录结果，然后**原样**提交：`wip(h1r): takeover checkpoint from ZCode`。
   - `artifacts/` 下的运行产物不提交（大文件），只在账本里记下路径。
3. `git fetch`；把 origin/main 新增的提交（只有本任务书这一个文档提交）rebase 或 merge 进来。
4. 推到远端分支：`git push origin HEAD:h1-core-hardening`。之后所有 milestone 都推到这个分支。
5. 在账本末尾加「## Codex takeover (H1R), 2026-10-05」一节，记录接手时的 HEAD、未提交改动的处理方式、focused tests 结果。

---

## R1 H8 启动 ≤ 5 秒（A12）

规格已写好：`tasks/results/ATLAS-H1-H8-lifespan-spec.md`（S1–S6、O1–O4）。照着做完，不要重新设计。

- 现状：Electron 侧已完成（不再固定 15 秒杀进程，5 个测试）；O1/O2 的 import 延迟已落地；S1–S5 正在实现（就是 R0 提交的那批未完成文件）。冷启动中位数 6.9 秒。
- 要做：
  - 补完 S1 组件注册表、S2 lifespan 拆成关键路径 + 后台启动（顺序依赖：automation 要等 dbos ready；关闭时等后台任务，最多 10 秒）、S3 运行开始前等 MCP 最多 10 秒（不 503，降级运行并发 `run.recovery.notice`）、S4 `/api/health` 的 `components` 字段、S5 DBOS 只在版本变化时迁移；
  - 把 `server.py` 顶部仍然拉起 MCP 链的 import 改成延迟导入（规格里写的 `server.py:100-106`，以实际代码为准）。
- 测试：
  - `test_startup_time.py`（5 秒预算，**不许放宽**）转绿，连续 3 次；
  - `test_health_components.py`：每个组件状态都在 {starting, ready, failed} 里；全部 ready 时 `status == "ok"`，否则不是 ok；
  - 后台组件启动失败（MCP、渠道、DBOS 各注入一次）：服务器不退出、对应组件标 failed、有日志；
  - 启动过程中关闭：无异常、无残留进程；
  - 路由快照 394 项不变。
- 如果做完 S1–S5 + O1 后仍超过 5 秒，按规格 O3/O4 继续压，并在账本附 importtime 证据。

---

## R2 压缩路径的模型名残留（A7/A8 补漏）

H10.2 发现的 D1（带前缀的模型名发给中转站出错）已经修好了主对话路径。手动/自动压缩这条路径还残留着同样的问题（`engine/hermes_runtime.py` 约 560 行、605 行，另有 2 个测试把旧行为写死了）。

- 压缩、压缩模型设置（`compression_model`）、交接摘要一律改用 `RouteSpec.wire_model`；
- 修正那 2 个写死旧行为的测试；不要删测试；
- 新测试：配了前缀模型和独立压缩模型时，假服务收到的压缩请求里 `model` 字段等于 wire_model；仅原生配置下手动压缩成功；
- AST 检查：`hermes_runtime.py` 中构造请求时不再直接使用 `litellm_model` 作为发送出去的模型名。

---

## R3 H2.1 收尾：会话记录只在 SessionDB（A3）

按 `docs/plan/DATA-OWNERS.md` 的「双写退出计划」。第 2 步（写操作改直接操作 SessionDB）**已完成**，剩下第 1、3、4 步：

1. **读切换**：会话列表预览、消息分页、搜索、导出、分叉树改为从 SessionDB 读。前端协议和返回字段不变（返回结构用适配层对齐）。
2. **停写**：`agent/run_phases.py::_phase_finalize` 的 `save_message` 改为只写元数据（预览、标题），消息正文只进 SessionDB。Atlas `messages` 表保留只读一个版本；在结果文件写明删除条件。
3. **迁移**：首次启动时把 Atlas 有而 SessionDB 没有的历史会话导入；迁移前备份两个库到 `data/backup/<时间戳>/`；幂等；失败时不改任何数据，并通过 health 的 components（`session_migration: failed`）加界面提示告知用户。
4. **`atlas doctor sessions`**：H9 已有 `atlas doctor`，补上 sessions 子检查（孤儿、条数不一致、工具配对断裂）。

测试（H1 §4 原样要求）：
- 用脱敏的真实形状 fixture 库（含分叉、回退、工具调用、图片、中文）做迁移：条数、顺序、工具配对一致；重复迁移不重复导入；中途抛异常时两个库都未被改动（比对文件哈希）；
- 分叉、回退、删除、导出、导入，每步之后 `atlas doctor sessions` 报告零不一致；
- 前端消息列表、分叉树、搜索相关测试全绿；路由快照不变；
- **用主机真实数据库的副本**（`D:\Atlas\data` 下，复制到临时目录，不动原件）跑一次迁移 + doctor，把条数统计写进账本（不提交数据本身）。

---

## R4 H6 错误处理清零（A10）

- 现状：渠道/网关范围已清零。按账本记录，剩余 agent 约 31 处、server 约 25 处、api 约 30 处、engine 约 25 处，`test_lint_gate` 现在是红的。
- 要做：H1 §8 指定的范围（`engine/`、`agent/`、`models/`、`server.py`、`api/`、`gateway_service.py`、`heartbeat/`、`automation/`、`channels/`）中 BLE001/S110/S112 清零；全仓不超过基线。处理方式只能三选一：缩小异常类型、`logger.exception` 后继续、转成用户可见提示。**不许用 `# noqa` 绕过**（gate 用 `--ignore-noqa` 检查）。
- 错误注入测试（H1 §8 要求，逐条确认存在，没有就补）：通知库读失败、标题回调失败、MCP server 启动失败、压缩模型失败、渠道发送失败。每一项都要断言：有日志、界面收到可见提示、运行不中断。
- `test_lint_gate.py` 转绿。

---

## R5 Hermes fork 收口（A2）

- 现在 Atlas 依赖钉在 fork 的 `codex/h1-core-hooks` 分支（`7508919`），而 fork 平常用的 `atlas` 分支还停在 `ef4571d`。
- 要做：把 `codex/h1-core-hooks` 合并进 fork 的 `atlas` 分支并 push；确认 fork 根目录 `ATLAS_PATCHES.md` 登记了全部补丁、每项都有测试；Atlas `core/pyproject.toml` 重新钉到 `atlas` 分支上的合并提交；更新 `docs/plan/VENDORED.md`。
- 测试：fork 测试（补丁相关）+ Atlas `test_hermes_contract.py` 在新的钉住版本下通过。账本里记录过的「固定日期测试在旧 fork 上也失败」照旧注明，不加绕过。

---

## R6 H10.1 分层耗时达标（A14）

- 账本写着「Full lane timing remains pending」。在没有其他进程抢资源时，由 controller 实测：
  - `unit` ≤ 3 分钟；`unit + integration` ≤ 10 分钟；
  - 后端全量（所有非 live 层）通过；前端全量通过（当前 160+）；
- 不达标就找出最慢的测试（`--durations=30`），优化或正确归层（真慢的移到 integration，**不许删测试或加 skip 来凑时间**）。
- 把最终的分组命令和实测耗时写进 `docs/plan/EXECUTION-GUIDE.md`。

---

## R7 H10.2 真实模型冒烟补全（A15）

- 现状（`artifacts/h10-live-smoke/full-run/`，deepseek-v4.1-flash）：ZCode 已经跑过一轮，01–09、11 共 10 个 `CHECK-OK`；**10（运行中插话）、12（Webhook 审批）没有检查结果**；08 的「先出计划」那一步超时（exit 124，600 秒）。
- 整轮实际用量很小：上报合计约 40 万输入 token、7 千输出 token，单个场景 1 万–4.6 万输入。

### R7.0 先修用量统计（假模型测试即可，不花钱）

上面的数字很可能**少算了**。多步任务（如 01 修测试，至少要读文件、跑测试、改文件、回答好几次请求）上报的输入只比一次系统提示（约 1 万）多一点，看起来只记了最后一次请求；子 Agent 的用量也未必算进去。另外全部场景 `cached_input_tokens` 都是 0。
- `atlas run` 汇总和 `run_usage` 改为本次运行**所有模型请求累加**（含子 Agent、压缩、标题等旁路请求，分项列出）；
- 查明缓存为 0 的原因：是中转站不返回缓存字段，还是请求前缀不稳定。如果是前缀不稳定，就修掉；如果是中转站的问题，在结果文件写明；
- 假模型测试：脚本化 4 次请求 + 1 个子 Agent，断言汇总等于各次之和；假服务返回缓存字段时汇总能正确带出。

### R7.1 补跑

- 等 R1–R4 合并后再跑（启动和会话存储都改了，之前的结果不算数），用主机 Atlas 设置里现有的 deepseek 模型，通过 `atlas run` 把 12 个场景**整轮跑 1 遍**；失败的只重跑那 1 个确认。
- 先查清 10、12 为什么没出结果，以及 08 计划步骤为什么会超时，修掉再跑。
- **额度上限按 token 算，不按钱算**：整个 R7 累计（含重跑）不超过 **300 万输入 token**，单个场景不超过 **50 万**，超过就停并报告。按上一轮的用量，这个上限是实际需要的好几倍，正常跑完远远用不到。key 只从用户现有配置读，不进仓库、日志和账本。
- **不跑原生 Claude 的对比**（要花 Claude 的钱；留到 T1，由用户决定）。
- **通过标准：至少 10/12，且 10、12 必须有明确结果。** 每个失败都要写根因；能修的本波修掉，补假模型回归测试，再重跑该场景；修不了的写进 `tasks/feedback/INBOX.md`。
- 汇总表（场景、是否通过、请求次数、累计 token、耗时、失败根因）写进结果文件；原始日志放 `artifacts/`，不提交。

---

## R8 H11 收尾

1. 用同一脚本出「之后」的数字，写 `tasks/results/ATLAS-H1-after.json`，在结果文件里和 `ATLAS-H1-baseline.json` 做前后对比表（冷启动、Agent 构建次数、MCP 注册次数、循环唤醒、内存、吞错数、server 行数、测试耗时）。
2. 更新 `docs/plan/VENDORED.md`、`docs/plan/DATA-OWNERS.md`（状态改为 ✅）、`docs/plan/EXECUTION-GUIDE.md`、`README.md`（项目结构里的「LangGraph orchestrator」等过时描述）。
3. 写 `tasks/results/ATLAS-H1-CORE-HARDENING.result.md`：A1–A16 逐条给证据（测试名、命令、数字）。未达标的如实写，不得标成通过。
4. **最终 gate**（controller 串行跑）：后端分层全量、前端全量、`test_route_snapshot`、`test_lint_gate`、`test_startup_time` ×3、`test_concurrency_isolation` ×20。
5. 全部通过后：`h1-core-hardening` 合并进 `main`，`tasks/CURRENT.md` 改为 `CURRENT: ATLAS-H1-CORE-HARDENING / STATUS: AWAITING_REVIEW`，push main，核对本地和远端 head 一致，停。
6. 独立验收按 H1 第 15 节的提示词，另开一个 Sol 对话来做。

---

## 顺序与并行

```
R0 接手（controller 亲自做，单线程）
 └→ 并行：
      L1  R1 启动 ≤5s       owner: server.py + api/startup* + dbos_backend
      L2  R2 压缩模型名      owner: engine/hermes_runtime.py
      L3  R3 SessionDB 收尾  owner: api/conversations*、agent/run_phases.py、engine/session_sync.py、cli doctor
      L4  R4 lint 清零       按目录分给多个子代理；server.py 和 hermes_runtime.py 的部分交给 L1、L2 的 owner 顺手做
      L5  R5 fork 收口       owner: Hermes fork + pyproject
 └→ R6 分层耗时（等 L1–L5 合并）
 └→ R7 用量统计修正 + 真实模型 12 场景补跑
 └→ R8 收尾
```

不得启动：T1、X6、R1、MemoryOS、UI 改版、安全审查、新一轮上游调研。
