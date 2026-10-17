# W5 原生记忆 / 数据一致性只读审查

## 范围与基线

- 独立 worktree：`D:\atlas-luna-w5-20261017`，detached，基于 `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f`。宿主 `D:\Atlas` 有未提交/未跟踪改动，本审查未在宿主写文件。
- 未读取或访问 `D:\Atlas\data`、会话库或真实记忆内容。只读源代码、测试夹具和文档。验证用 `PYTHONPATH=D:\atlas-luna-w5-20261017\core`、隔离 `.tmp`、项目现有 Python venv。
- `core/atlas/api/application.py:30,54,111,143` 同时挂载 `/api/knowledge` 与 `/api/memlib/*`。W5 主入口链：`application` → `memory_library_router` → `MemoryLibrary.recall / observe_turn` → SQLite `TurnQueue` 与 Markdown/Git `MemoryStore` → 可重建 `MemoryIndex`。队列写日记并异步提炼见 `core/atlas/memory/library/__init__.py:298-330`；Dream scheduler 由 API startup 单独启动，`core/atlas/api/memory_library_router.py:333-349`。
- 本地运行进程是否实际绑定该 HEAD 未由 W5 验证；以下 runtime_affected 均限定为本基线代码行为。

## 核心结论

当前实现有可用的 Markdown+Git 记忆库、经历/日记、队列、索引、手动编辑/忘记、原始会话查询与时间线入口；其存在不等于 V4.1 已实施。最值得先处理的数据一致性问题是 Dream 使用全局时间 checkpoint 并基于模型调用前的旧页面快照覆盖写；队列超过三次失败后不可见于消费列表且没有恢复入口；记忆来源仍用 `session@timestamp` 找最近用户消息，不使用 M2 的精确 `message_uid`。

## 问题摘要

| ID | 优先级 | 问题 | 分类 |
|---|---|---|---|
| W5-001 | P1 | Dream 扫描与全局时间 checkpoint 之间的迟到 / 并发经历可永久漏整理 | 代码确认 |
| W5-002 | P1 | Dream 模型执行期间产生的手动编辑可能被旧快照覆盖 | 代码确认 |
| W5-003 | P1 | 达三次失败的队列行被永久排除且没有恢复动作 | 代码确认 |
| W5-004 | P2 | 重启只持久化队列，启动时不主动 drain | 代码确认 |
| W5-005 | P2 | 搜索在 source/date/project 过滤之前仅取 1000 个候选 | 代码确认 |
| W5-006 | P2 | timeline 时间戳游标会跳过同 timestamp 的边界经历 | 代码确认 |
| W5-007 | P1 | 记忆出处精度为近似时间匹配，未接入精确 message UID | 代码确认 |
| W5-008 | P2 | 忘记只清理派生记忆；canonical 会话仍保留原文且可被显式 raw 搜索 | 功能缺口（边界已披露） |
| W5-009 | P2 | Git 历史重写恢复有备份与校验，但没有跨实例/进程写入互斥 | 待验证 |

每项完整统一字段见同目录 `W5-issues.json`。

## 当前代码上的最小迁移方案

1. **先封住漏写与覆盖**：Dream 按稳定 source/event ID 记录每个输入经历的处理状态；先提取、校验并保存增量结果，再推进该 source 的 checkpoint。写项目前重新读取页面并合并，或对生成时版本做 CAS 冲突检测，保留并发的用户编辑。沿用现有 SQLite/Git 与 ReMe Extract→Integrate→Finish 的小流程，不迁入 ReMe 的服务层。
2. **队列可恢复**：保留现有 `.queue.sqlite` 与日记阶段语义；启动后按当前 model_mgr 发起一次有界 drain；达到上限的行显示具体错误并提供显式 retry/reset，不自动无限重试。为每轮引入稳定 turn/event ID，日记阶段重试保持幂等。
3. **固定来源身份**：把 W2 的 `session@timestamp` ref 迁至 `SourceRef(conversation_id,message_uid)`，用 SessionDB 既有 UID 精确打开；旧 ref 保持 `approximate` 并显示精度，禁止猜测为 exact。使用 V4.1/M2 已有接口契约，不另造 UID 或 transcript store。
4. **正确分页**：把 src/date/project 限制推入候选查询，或使用可持续扫描的 keyset cursor；timeline cursor 使用 `(at,id)` 稳定复合键。过滤后的 `total` 必须覆盖全候选而非 1000 项窗口。
5. **忘记语义显式闭环**：维持 Git rewrite 的备份、commit 数、残留文本和工作树校验；为同 root 多实例/进程增加最小互斥并做故障注入恢复检查。界面继续披露原始聊天及外部备份未清除；若产品承诺彻底忘记，则按精确 source refs 对 canonical SessionDB 传播删除/排除，且让 raw search 尊重墓碑。

不实施上述迁移，也不修改任何旧代码或真实数据。

## W0/W1/W2 与 mem-m1..9 独有实现核对

- `origin/memory-w0@3a5e41c5c47767361d979deb2f00b09cbf1866ff` 是本基线祖先。当前 W0 三次失败队列行保留、forget Git 校验等仍在；当前本地队列 restart 持久化用例通过，但并不验证自动 drain 或终态失败恢复。
- `origin/memory-w1@9ace88c5731ed8be6dd7406d758161236938e2de`、`origin/memory-w2-api@aa14c3173392d0fc60ec3e401e4495a2d3357cb7`、`origin/memory-w2-ui@11153a028feace09e952e23544e0adf1d155887c` 均非基线祖先。当前树确有经历提炼、项目页、Dream、检索、来源打开与 UI/路由的一部分同功能；只能按当前实现计，不把这些分支的真实模型/20k 等历史报告当成本分支证据。
- `origin/mem-integrate@4046764fbabda187a4b329c830a4b9cab9631951` 及 M1–M9 各分支均非基线祖先。与其比较，当前基线的 `library/{association.py,claim_resolution.py,consolidation.py,lifecycle.py,recall.py,source_ref.py}` 缺失；`__init__.py,dream.py,extract.py,forget.py,index.py,queue.py,sources.py,store.py` 为明显不同实现（diff stat：16 files，530 insertions / 2584 deletions）。因此“W2/M1–M9 已集成”不成立。
- M1 的 per-source lifecycle/checkpoint、M2 的 exact SourceRef、M4 的 Dream consolidation validation、M5 的 layered recall、M7 的 claim/forget rules、M8 的 one-hop association 在 mem-integrate 有独有代码；当前基线只保留了早期近似能力。M3 的 source metadata/episode、M6 的 embedding、M9 的策略方向需逐项比较，不能仅因相同 `memory.library` 路径认作吸收。
- `origin/research/atlas-memory-2026-10-16-handoff@bc42b5091563d3f8ee5d25ffc3266ea1c72f6af8` 的 V4.1 明确“研究/移植裁决，不是已施工证明”；它建议以 ReMe 增量 Dream 替换全局时间扫描、以 MemOS 的 staged retrieval/AMA 轨迹工具做轻量移植、Graphiti 双时间规则用于事实时间、Hindsight RRF 作为可验证检索算法。当前 W5 先修唯一来源身份与增量恢复，再选择这些内核，不引入第二记忆服务。

## 当前 HEAD 验证及历史报告重定性

以下三个现有聚焦用例在当前 `0b1ba4114e25643369c95bfac85d37563788444f` 上分别执行，隔离 basetemp，均通过：

- `test_m03_pending_turn_survives_library_restart`：1 passed；证明 pending 行可跨 MemoryLibrary 对象重读，不证明应用启动主动 drain。
- `test_dream_checkpoint_advances_only_after_all_projects_succeed`：1 passed；证明异常时保持 checkpoint，未覆盖扫描并发/迟到 event。
- `test_dream_writes_project_sections_and_advances_checkpoint_after_success`：1 passed；证明成功路径会写页面并前进 checkpoint，未覆盖生成期间的用户编辑。

把此前 W0/W1/W2 报告限定为各自记录的 branch、commit 与隔离条件；未在当前 HEAD 重跑的历史案例均为“未在本基线验证”。本次三个用例均未读取真实记忆/会话数据。一次三用例合并执行先因 basetemp 父目录不存在而 setup 失败；修正目录后组合进程挂起在输出 `...`，已停止该命令专属 pytest 进程并改为逐个执行。未跑全套。

## W5 覆盖边界

覆盖了原生 memory library/旧 knowledge router 接线、队列、经历/日记、Dream、index/search/timeline、手动编辑、forget/Git revision、source refs、W0/W1/W2 和 M1–M9 独有实现、V4.1 研究差异。仅按 LEDGER 对照得到 C053（外部会话历史导入，部分）；LEDGER 没有独立记忆/Dream/forget 能力项。未审个人待办/日历、D115/D116 callable scheduler，未复现跨进程 writer 与 Git 失败恢复故障，未检查真实运行进程或真实数据，未实施任何迁移。

### 本地未推送分支补充（W0 指定）

- `codex/desktop-repair-20261013@b177a6a94a7f1a9adb2891955a37cd4d4490054d` 的唯一 memory 变更是 `core/atlas/memory/desktop_views.py::facts` 过滤 `legacy:agent_reflections:*` 反思投影及一条回归测试；规则有效，但该旧分支投影不是当前 Markdown library 的实际写入链，不能直接作为本审查问题的修复。
- 其 ancestor `67f5d317ff3459ae7d598e67d020afb9ef079951` 为另一套 unified-facade/MemOS authority 接线；相对当前 HEAD，桌面修复分支整体删除 W2 `memory/library` 与对应路由并替换记忆子系统（详见 W0 branch classification），应作为整套架构候选评估，不能 cherry-pick 到当前 W2 路径。
- `p11b-worker-leftover@9379d6b499a8d1dd316ff7f8af274cf5285a8654` 在 W0 `work/w0-local-refs.json` 中 `unique_paths=[]`；提交内容为 P11B observability 描述但提交树无文件差异，对 W5 数据一致性没有独有实现。

