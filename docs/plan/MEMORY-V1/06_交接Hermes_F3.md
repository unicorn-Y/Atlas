# MEMORY-V1 F3：接 Codex 的 F2 继续做（交给 Hermes）

版本 1.0，2026-10-09。编写：Claude（审查方）。施工：Hermes（唯一总控）。
基线：Atlas `e0d830e4`、MemoryOS `abb2615e`（`memory-v1`），以及 §1 列出的未提交工作区。
Codex 在 F2 中途额度耗尽。它的检查点记录在 `progress/F2.md`，**开工前必须完整阅读**，另外还要读 `05_收尾包F2.md`、`00_任务书.md` 第 6 节、`04_修复包F1.md` §3（红线）。

## 0. 工作纪律（Hermes 专用，违反任意一条都要停下汇报）

1. **只改 `D:\Atlas` 和 `D:\MemoryOS` 的 `memory-v1` 分支。** 不得停止、打断或接管任何其他会话和进程（包括其他 Hermes 会话、Codex、反重力反代、网关）；不得修改 Hermes、Codex 自身的配置；不得动网络、DNS、代理或系统设置；不得删除用户桌面上或仓库外的文件。
2. **不得读取、打印或复制任何凭据文件**（`user-settings.json` 的密钥字段、反代的 `gui_config.json`、Hermes 的 `.env`、`config.yaml` 中的 api_key）。需要模型时，一律通过 Atlas 的 ModelRouter 和已登记的模型。
3. **生产数据和配置不碰**：`D:\MemoryOSData`、`D:\Atlas\data`（包括 `user-settings.json`）只能读取非敏感字段。测试一律使用隔离数据根。
4. **每完成一个任务包就提交并推送**：`git push git@github.com:unicorn-Y/<仓库>.git memory-v1`，然后执行 `git fetch git@github.com:unicorn-Y/<仓库>.git memory-v1:refs/remotes/origin/memory-v1`，再用 `git status -sb` 确认没有 ahead。上下文快满或者要停下之前，先提交推送，再在 `progress/F3.md` 中写清续作点。
5. **测试按全集报告**：Atlas 用 `-o addopts= core/tests/unified_memory`，MemoryOS 用 `tests/unified_memory`。所有失败都要列出来，不得只报通过的部分。
6. **红线**：不得在评测里预先插入记忆、改写用户原话、按题号或场景号特判、读取答案文件；不得放宽 schema 枚举；不得把单元测试通过说成效果达标；状态永远不能写成 ACCEPTED。
7. 如果使用子智能体，同一时刻最多 2 个；每个文件同一时刻只能有一个写者；子智能体的产出由你亲自验收（读 diff、复跑测试）后才能提交。

## 1. F3-0 接管未提交的工作

Atlas 工作区中 Codex 留下的未提交内容：
- 修改：`scripts/memory_v1/eval_scenarios.py`、`run_longmemeval_f1.py`、`test_eval_scenarios_runner.py`、`test_longmemeval_f1_runner.py`
- 新增：`core/tests/test_f2_observer_smoke.py`、`eval/F2-A-real-smoke-*.json`（1937/1942/1947/2004 四次，以及 partial）、`eval/F2-A-review-20261009-1947.md`、`eval/F2-C-lifecycle-rehearsal*.json`、`progress/F2-B.md`、`progress/F2-C.md`

逐个审读（重点查红线），跑相关测试，合格的提交推送。失败的运行记录也要提交，作为证据保留，不删除。

## 2. F3-A 完成观察者"零误记"验收（接 F2-A）

1. 对 `eval/F2-A-real-smoke-20261009-2004.json`（`e0d830e4` 修复之后的那一轮）做**逐条人工核对**，格式参照 `F2-A-review-20261009-1947.md`：列出每条存储的记忆，判断它是不是用户真实陈述的事实；提问、假设、条件句派生出来的内容都算误记。结论写入 `eval/F2-A-review-20261009-2004.md`。
2. 误记为 0：F2-A 判为通过（DONE_PENDING_REVIEW）。误记大于 0：只能修改**通用规则**（提示词或校验），不得按对话 id 特判，然后新跑一轮 10×3 并再做人工核对。**最多迭代 3 轮**，仍不为 0 就停下汇报，附上所有误记样本。
3. 同时确认没有出现"该记的没记"：用户明确陈述的事实漏记，也要列出来。

## 3. F3-B 修复 Codex 查出的 3 个产品缺陷（V1 用户效果 E7、E8 依赖这些）

1. **暂停采集不完整（E7）**：MemoryPage 的暂停目前只停了被动观察。按任务书 S5 第 4 条，暂停时聊天 capture 和观察者都要停止；恢复后不补采暂停期间的内容。写一个经过真实服务的测试：暂停 → 发消息 → 恢复 → 该消息不在任何记忆中，也不在 evidence 中，或者以"暂停期间不采集"的形式明确标注。
2. **自然语言提醒没有接到 Automation（E8）**：用户在聊天里说"明天上午 9 点提醒我交报告"→ 观察者产出 `facet=INTENT`（带时间条件）→ `intent_bridge.py` → 现有 AutomationEngine 中真实创建一个任务；说"取消那个提醒"→ 任务被取消；说"改到下午"→ 任务被更新。不得新建第二套调度器。写一个真实服务测试，加上一次真实模型冒烟。
3. **`occurred_at` 不进聊天链路**：评测中"隔几天"的场景需要模拟时间。实现方式：**只在** `event_class=TEST` 且使用隔离数据根时，允许请求携带测试时钟；生产路径一律使用真实时间，并写测试证明生产路径会忽略测试时钟。不得让评测运行器绕过产品链路直接写库。

每个缺陷单独提交，提交信息写清楚修的是哪个用户效果。

## 4. F3-C 评测（接 F2-B，规模不变）

- 30 条场景跑 3 次取中位数（门槛：E1–E4/E6 中位数 ≥ 90%，反例 3 次全过，E5/E7/E8 3 次全过）。F3-B 完成后再跑，否则 E7、E8 一定失败。
- LongMemEval：6 题冒烟，然后 30 题（6 类各 5 题，固定种子，题号写入报告），同一题的观察结果缓存复用。120 题不跑。
- 每份报告写清两个仓库的 hash、模型 id、运行次数、token、耗时，以及失败场景的根因分类。
- S27 缺少前置历史，按原样记为"场景设计缺陷"，不得补输入。

## 5. F3-D 启用准备（接 F2-C）

完成 `progress/S7_enable_plan.md`，并在生产数据**副本**上完整演练一次"开启 → 真实聊天 → 重启 → 关闭回滚"（`eval/F2-C-lifecycle-rehearsal.json` 已有部分结果，补完即可）。只演练，不改生产。

## 6. 收尾

写 `progress/F3.md`（每个任务包的结果、证据路径、未解决问题），更新 `CURRENT.json`，提交推送两个仓库并确认没有 ahead，然后**停下来用中文汇报**，等审查。

汇报要求：用一张表列出每个任务包的状态和证据；失败项放在最前面；不要写和任务无关的话。
