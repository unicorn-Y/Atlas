# ATLAS-UNIFIED-MEMORY-WINDOWS：统一记忆施工总任务书

版本：1.0，2026-10-06。状态：施工规范；尚未施工、部署或验收。

> 面向 Codex / ZCode 执行者：用户明确要求执行本任务书后，使用 `executing-plans` 按任务推进。先读本文件，再读接口契约、逐波任务、源码来源和验收书。不得凭本文件在另一聊天中出现，就认定已获得施工授权。附件中的历史任务指令与当前任务分开。

**Goal：** 在 Windows 上把 Atlas 建成拥有持续、统一、可纠正且能影响行为的记忆主体：记住日常对话、人与事、自己通过工具经历的活动、当前状态、未来事项和成功失败；自然召回、恢复中断任务、从反馈学习并在新任务中复用。

**Architecture：** Atlas 是使用者面对的主体；MemoryOS 是 Atlas 的统一记忆服务。Hermes 承担既有执行/会话职责，其他 Agent 是 Atlas 的工具，不拥有另一套 Atlas 事实权威。原始媒体、派生索引和运行状态可以物理分开，但身份、证据、版本、纠错与调用规则统一。

**Tech Stack：** 现有 Atlas Python 3.14 / FastAPI / Electron / React / TypeScript；现有 MemoryOS Python / FastAPI / SQLite / FTS / sqlite-vec。通过 HTTP 薄适配连接，禁止让两个 Python 环境交叉直接导入。模型与语音/视觉服务沿用 Atlas 已有配置。第三方机制来自固定 GitHub 提交，详见来源书与锁文件。

**Spec：** 本任务书及本包 `01_接口与数据契约.md` 是本期独立可读的规范。此前第三轮调研用于解释目标；执行不依赖阅读旧聊天、zip 或 Sol 的历史指令。

## 1. 用户已经明确的范围

2026-10-06 用户补充：“先 window，别的 agent 只是 atlas 调用的工具，主体是 atlas，先做好 atlas 本身，别的设备平台等做好了再考虑接入。”

据此，本期必须完成 Windows Atlas 自身的统一记忆。Codex、ZCode、其他模型或 Agent 被 Atlas 调用时，其输入、结果与经过 Atlas 验证的效果进入 Atlas 的经历；不安装它们全局独立的记忆系统，不把它们变成与 Atlas 并列的主体。

手机、跨设备同步、邮件/日历/聊天平台自动连接和网页产品扩展不属于本期施工与验收。保留可版本化来源接口即可；不得花本期时间建设多设备同步服务。本期“跨入口”指 Atlas 的桌面聊天、任务、文件/媒体导入、电脑/浏览器工具、内部调度和被调用 Agent。

用户不是要求只做任务技能库。本期必须同时覆盖日常对话、人物/关系、状态/偏好、时间线、未来意图、工作记忆、学习与纠错。

## 2. 最终必须出现的用户效果

以下 12 项构成产品目标；任一项只有 mock、脚本演示或文档说明，都不能宣布完整交付。

1. 用户换聊天、关机重启、隔天或更换 Atlas 内模型后，不重新介绍自己，Atlas 能接续已记录背景。
2. 用户自然说“上次那个人”“我们前几天决定的事情”“今天怎么安排”，Atlas 能结合人物、时间与当前状态找回相关经历；候选不唯一时澄清。
3. 生活偏好、工作目标和约定在相关回答与行动中自然生效；无关问题不硬塞私事。
4. 当前状态与历史分开：“这周想安静”不会成为永久人格，“后来改时间”不会抹去最初约定。
5. Atlas 的文件、屏幕、浏览器、语音/图片及工具结果形成带原始定位的经历；看见不等于执行，Agent 宣称成功不等于验证成功。
6. 同一个人的别名、同一件事的不同线索可关联；错误关联可以拆开并修复相关理解。
7. 中断任务恢复时知道目标、约束、步骤、待解决问题和真实完成状态；不重复已经发生的外部副作用。
8. “下次打开这个项目时提醒我”“收到某结果后再继续”能在条件成立时想起；取消、延期、完成会改变后续触发。
9. 成功与失败留下可复用知识、方法、边界及反例；新问题能组合旧经验，不能只重复原任务。
10. 缺知识或方法时，Atlas 能识别缺口、针对性查证或试验，再以真实效果验证学习成果。
11. 用户纠正或删除记忆后，相关当前状态、图、摘要、计划、技能和可控缓存同步受影响；旧备份不能悄悄复活它。
12. 用户能看时间线、原始依据、当前理解、待办与学到的方法，知道为什么被记住或使用，并能修正、暂停采集和删除。

本任务书以可观察行为定义“向 AGI 靠近”。不以完成软件施工宣称意识、通用人类水平、无限泛化或保证记住未曾接入的信息。

## 3. 当前源码基线：已经核查与尚未验证

只读核查时：

| 仓库 | HEAD / 分支 | 所见事实 |
| --- | --- | --- |
| `D:/Atlas` | `32d681bdf548318a0be69fd396653645d78f8148` / main | 9 项未提交内容；`tasks/CURRENT.md` 中旧 H1 状态为 CLOSED_BY_USER。 |
| `D:/MemoryOS` | `702f702bf9c0c1fa552132930843aaca4923f139` / master | 128 项未提交内容，含历史评估与恢复材料。不得重写旧基准、私有 truth 或 HARD_ERASE 历史证据。 |
| Atlas 环境 | `core/.venv/Scripts/python.exe` | 核查时 Python 3.14.7。 |
| MemoryOS 环境 | `service/.venv/Scripts/python.exe` | 核查时 Python 3.13.15。 |
| Hermes 依赖 | Atlas `core/pyproject.toml` | 固定 fork 提交 `e0866de014e6fa99721ccaf4f848e1316a58148a`；不是历史材料中的旧 pin。 |

关键发现：`core/atlas/memory/memoryos_adapter.py` 的 `MemoryOSAdapter` 仍以 Atlas `MemoryStore` 为后端。实际入口 `server.py`、`cli.py`、`runtime/hub.py` 直接构造 `MemoryStore`；`agent/run_phases.py` 直接调用其提取、上下文和经验接口。因此只改 Adapter 文件无法完成统一接线。

Atlas 的 MemoryStore 混合了运行记录、普通记忆、候选、知识、目标经验、评估及派生报告。MemoryOS 已有 evidence、memories、episodes、experiences、protected state、删除屏障与图/向量机制。是否已接入真实运行、各机制实际质量如何，本任务书不作验收结论。

锁文件记录了规划时选定文件的工作区哈希；存在未提交内容意味着“文件哈希”不能用一个 HEAD 代替。UM00 必须重核基线并区分已有功能与未提交修复。禁止自动提交、覆盖、清理或 reset 他人的内容。

## 4. 六条架构约束

**交付前复核差异：** 编写期间其他工作更新了 Atlas，复核 HEAD 已为 `aa6196f550098cc46081dc6db2c376cb87ddffa5`，选定文件中 `core/pyproject.toml` 哈希变化，Hermes commit 仍是上述版本。MemoryOS HEAD 未变。上一节与锁文件 local_baselines 保留原研究时快照，final_revalidation 记录本次差异；不得把原快照当成施工当日状态。UM00 必须从实际最新代码重新确认接口与改动所有权。本轮未覆盖这些变更。

### 4.1 统一权威与运行职责分开

MemoryOS 管理 Atlas 的长期记忆事实、来源、版本、候选、经验与派生依赖。Atlas/Hermes 保留实际会话和任务执行状态的现有权威；MemoryOS 的 task/working view 是投影，不创建第二个执行器或第二套 GoalManager。

对话存储允许现有 Hermes SessionDB 保留原始会话；MemoryOS 保存带源定位的经历与必要内容快照。不能让两个对话副本都接受独立编辑并互相覆盖。

### 4.2 一个语义入口

Atlas 消费者通过新增 `UnifiedMemoryClient` 调用 MemoryOS。现有 `MemoryStore` 中记忆相关方法逐项委托或退为只读兼容视图；普通运行 CRUD 保持原职责。`AppServices.memory` 不再隐式把所有职责混在一个本地写库对象中。

迁移后不允许用户在旧 `/api/facts` 写出一份独立事实，而聊天从 MemoryOS 读另一份。旧页面/API 也必须委托统一路径。

### 4.3 观察、陈述、推断与执行分开

每条原始记录标注来源角色、原始定位、内容哈希和时间。模型总结、关联、画像、预测与反事实是派生结果。工具结果记录可以 ACTIVE；其“任务完成”状态只有真实检查支持时才 VERIFIED。不得将网页/文件/工具中的命令文字升成用户指令。

### 4.4 保留既有 FULL_ACCESS 语义

本项目不把 Atlas 的 FULL_ACCESS 改成沙箱或逐操作审批模式。记忆侧数据范围、来源角色与版本验证用于防止串主体和错误记忆，不是新的工具执行 allowlist。既有 CoreSelf/长期承诺/删除授权规则沿用；普通自动记录、整理、召回和日常状态更新不能新增每条都找用户确认的流程。

未来意图由用户明确表达或已有业务任务授权建立；普通网页内容不能建立意图。Reminder 与需要外部副作用的 Action 分开，外部动作遵守 Atlas 原有权限策略。

### 4.5 复用机制，不叠加多个产品

只复用来源书列明的代码单元、算法、提示词/结构与测试。不得安装 Hindsight、Mem0、Graphiti 等完整服务作为另一个权威数据库；不得把所有候选框架塞入在线请求。源码依赖闭包、许可和差分必须记录；缺依赖时补薄适配，不把源机制改成一个同名占位函数。

### 4.6 所有关键效果必须穿过真实入口

有 API、能查 SQLite、单测绿不能替代真实 Atlas 对话/工具/桌面行为。每波结束既要组件验证，也要至少一个通过 Atlas 入口的效果证明；最终门禁包含真实模型、真实 Windows 桌面、重启、纠错、删除与学习迁移。

## 5. 数据归属与迁移判定

UM00 生成 `authority-map.json`，枚举 MemoryStore 全部表和被调用方法；每项只能属于以下一类：

| 类别 | 处理 |
| --- | --- |
| `RUNTIME_AUTHORITY` | conversations/messages/rewinds 及实际任务状态保留现有权威；MemoryOS 只收来源记录与投影。 |
| `MEMORY_AUTHORITY` | facts、候选/修正/版本、knowledge、agent_reflections、目标经验及可被模型当知识读取的 active 记录迁入统一记忆；旧写路径关闭或委托。 |
| `DERIVED_VIEW` | 成熟度、健康、优化、consolidated insight、图与总结等派生视图保存来源版本，可重建；active 读取必须回查统一生命周期。 |
| `AUDIT_OPERATION` | 原运行反馈、评估和使用记录可保留作审计，但不能绕过统一服务推广知识。 |

分类按字段含义和实际调用，而非按表名猜测。列出的 37 个现有表均须分类；动态新增表也须分类，不能只迁移 facts 就宣称完成。所有旧 API 明确写出“委托/保留运行功能/只读派生/弃用并有替代入口”，不得默默返回空数组。

迁移方式：只读导出 → 规范化 legacy source refs → 幂等导入隔离 MemoryOS → 按记录数/内容哈希/生命周期/源定位核对 → 用消费契约双读对照 → 原子切换所有记忆读写入口 → 旧库只读保留。正式切换前创建一致备份；不能边切换边让旧库继续接受独立事实修改。

回滚指回到上一个完整可用版本和对应一致数据，不允许为恢复旧 UI 而把已删除记录重新导入。切换后的新写入与撤回必须先对账，再决定兼容视图或恢复版本；禁止盲目覆盖数据库。

## 6. 文件布局与责任

以下新路径是本任务书提出的目标路径；不是声称当前已存在。执行者不得随意换名；若基线已存在同职责模块，在 UM00 给出唯一映射后复用，并更新全包索引。

MemoryOS 新包 `service/unified/`：

| 文件 | 唯一职责 |
| --- | --- |
| contracts.py / repository.py | 类型、事务和记录访问；只允许 service 使用数据库。 |
| sources.py / media.py | 来源对象、编辑版本、原始片段与媒体定位。 |
| identity.py / temporal.py | 人物/实体消歧、关系和有效区间。 |
| formation.py / consolidation.py | 原始经历形成事件/事实/状态与多粒度整理。 |
| profile.py / legacy.py | 条件化当前理解与旧记忆的版本/来源迁移；服从相同权威。 |
| dependencies.py / lifecycle.py | 输入版本依赖、纠正/撤回/删除传播。 |
| working_set.py / intentions.py | 当前注意与任务投影、未来事项。 |
| query_planner.py / associations.py / graph_retriever.py / retrieval.py | 查询拆解、联想、图访问、证据选择和上下文装配。 |
| experience_distiller.py / strategy_updates.py / utility.py | 成败提炼、策略版本与条件效用。 |
| prediction.py / learning_gate.py | 有条件预测、真实反馈与学习候选门禁。 |
| self_probe.py / maintenance.py | 绑定实际检索的自测与有预算的后台整理。 |
| api.py | `/v1/unified/*` 路由，兼容现有 `/v1/*`；身份和生命周期验证。 |

Atlas 新包/文件：

| 文件 | 唯一职责 |
| --- | --- |
| core/atlas/memory/unified_client.py | HTTP 类型化调用、错误语义；不执行 SQL。 |
| core/atlas/memory/unified_facade.py | 旧记忆接口委托与新使用接口，不管理另一份事实。 |
| core/atlas/memory/capture.py / outbox.py | 源事件规范化和可靠待提交队列；队列不是可查询知识库。 |
| core/atlas/memory/context.py | 记忆块与工具上下文装配、真实 read receipt。 |
| core/atlas/memory/windows_sources.py | Atlas 入口、电脑/浏览器观察及导入；本期非全系统后台监视器。 |
| core/atlas/memory/skill_evolution.py / targeted_learning.py | 现有 skill registry 接线、隔离候选修改、针对性学习。 |
| core/atlas/memory/intent_bridge.py | 将统一意图投影到既有 Automation/调度器。 |
| core/atlas/api/unified_memory_router.py | Atlas API 代理、用户来源身份与桌面请求接线。 |
| frontend/src/renderer/components/memory/*.tsx | 时间线、证据、人物、待办、学习与纠错操作。 |

修改已确认连接文件：Atlas `server.py`、`cli.py`、`runtime/hub.py`、`api/app_services.py`、`api/memory_router.py`、`agent/run_phases.py`、`agent/enrichment.py`、`agent/tool_node.py`、`engine/hermes_runtime.py`、`tools/x2/computer.py`、`tools/x2/browser.py`、`automation/engine.py`、`automation/triggers.py`、`frontend/src/renderer/pages/MemoryPage.tsx`。MemoryOS `service/app.py`、`storage.py`、`recall.py`、`candidate_ingest.py`、`episode_ingest.py`、`compaction.py`、`erasure.py`、`erasure_barriers.py`、`graph_store.py`、`graph_query.py`、`graph_types.py` 与 schemas/migrations。

热文件单写者；并行施工仅在用户授权或执行技能规定时使用，且以所有权表隔离。不要让两个施工者同时改 `run_phases.py`、`memory/__init__.py`、`app.py`、Hermes fork 或同一 migration。控制者负责整合，不应重写其他施工者整个模块。

## 7. 波次、依赖与阶段效果

| 波次 | 依赖 | 交付后的可观察效果 |
| --- | --- | --- |
| UM00 基线与效果夹具 | 无 | 明确当前权威、保存未提交内容边界，冻结真实目标与测试来源。 |
| UM01 统一服务与迁移 | UM00 | Atlas 页面、聊天、CLI 与工具记忆使用同一事实，重启后不分叉。 |
| UM02 可靠经历采集 | UM01 | 对话/工具/调用 Agent/导入内容有稳定源定位，重复与失败可恢复。 |
| UM03 身份、时间、冲突 | UM02 | 正确人物和历史/当前状态；旧信息晚到不覆盖，条件冲突不乱裁决。 |
| UM04 日常事件与画像 | UM03 | 时间线、共同经历、偏好变化和日/周整理，原始证据可回溯。 |
| UM05 Windows 多模态 | UM02、UM03、UM04 | 图/声/电脑/浏览器观察能进入日常事件并回到原片段。 |
| UM06 工作记忆与未来意图 | UM03、UM04 | 中断接续、项目条件提醒、取消/延期及任务结果正确。 |
| UM07 自然召回与行为接线 | UM04、UM05、UM06 | 不喊“搜索记忆”也能应用相关经历；无关时克制，行动输入可追溯。 |
| UM08 纠错、删除、依赖失效 | UM07 | 错误合并可拆，旧计划重查，删除和恢复不复活。 |
| UM09 成败经验与效用 | UM07、UM08 | 真实成败提炼方法、反例与场景边界，反馈改变后续选择。 |
| UM10 技能、预测、主动学习 | UM09 | 组合/迁移、可验证学习与方法更新；预测错误可修正。 |
| UM11 后台复盘与记忆策略 | UM08、UM09、UM10 | 低打扰整理、实际召回自测和候选策略验证，保留长期重要事项。 |
| UM12 桌面体验与发布接线 | UM01–UM11 | 用户通过 Windows Atlas 浏览、解释、纠错与管理，安装版行为一致。 |
| UM13 完整效果验收 | UM12 | 按验收书重跑全部核心行为、长期轨迹与学习迁移，给出可复查证据。 |

UM01 先交可见统一效果，不以它替代最终目标。不得跳过 UM04 日常记忆、UM06 未来事项或 UM10 学习；不得到“能搜索”就停止。跨设备/外部平台以后单独立项。

## 8. 执行、验证与交接

执行者在隔离 worktree 中创建 `docs/plan/UNIFIED-MEMORY/`，把本包原文及锁文件纳入版本；任务进度写 `tasks/unified-memory/CURRENT.json`。本包没有授权发布、push main 或修改全局 Codex 配置。

每个任务按 `02_逐波施工任务.md` 执行：读来源与相关现有代码 → 写有真实判据的失败测试 → 搬来源代码及最薄适配 → 接真实调用方 → 跑组件及入口验证 → 写源差分与证据 → 提交该任务自己的文件。已有行为已满足时，重新证明并记为 REUSED_VERIFIED，不得反复重做。

状态枚举：`NOT_STARTED`、`IN_PROGRESS`、`PARTIAL`、`COMPONENT_VERIFIED`、`INTEGRATED`、`ACCEPTED`、`BLOCKED_EXTERNAL`。没有真实模型或 Windows 冒烟时，至多 INTEGRATED，不能 ACCEPTED。外部条件缺失不是把项目完工；记录缺失和恢复步骤。

最小交接内容：两个仓库 HEAD、工作区差分、当前任务、已过/未过测试、来源 parity、隔离数据目录、模型运行清单、下一项明确动作。必须含失败证据，禁止只保留最终绿结果。

隔离环境约定：Atlas `ATLAS_DATA_DIR` 指向本波唯一目录，MemoryOS `MEMORYOS_DATA_ROOT` 和 `MEMORYOS_DB_PATH` 指向该目录下的 MemoryOS 子目录。测试事件显式 `event_class=TEST`。禁止借生产默认路径跑迁移、删除、故障注入或学习试验。

PowerShell 示例在各仓库 worktree 根执行；解释器路径以 UM00 环境清单核对。项目新建验收入口必须在 UM00/对应波实现后才运行，下面不是声称它们现在存在：

```powershell
# Atlas 仓库：默认 addopts 是 -m unit，验收显式覆盖。
$env:ATLAS_DATA_DIR = Join-Path $PWD 'artifacts/unified-memory/test-runtime'
& ./core/.venv/Scripts/python.exe -m pytest -o addopts= -m 'unit or integration' core/tests/unified_memory -q

# MemoryOS 仓库：每次命名一个新的测试数据根，不能沿用生产默认值。
$env:MEMORYOS_DATA_ROOT = Join-Path $PWD 'artifacts/unified-memory/test-runtime/memoryos'
$env:MEMORYOS_DB_PATH = Join-Path $env:MEMORYOS_DATA_ROOT 'db/memoryos.sqlite3'
& ./service/.venv/Scripts/python.exe -m pytest tests/unified_memory -q
```

正式迁移与发布在 UM12 中形成可审查的 dry-run、备份清单与安装包证据；用户之后授权实际切换时执行。拒绝或停止通知立即停止相关操作。不得用假 API 或模拟模型替代最终验收。

## 9. 验收条件与“不算完成”

必须同时满足：64 项目标中的本期条目有施工和测试映射；40 个任务有产物；所有实际抄入源代码有固定出处和适配差分；所有记忆消费者接统一路径；`05_效果验收与覆盖矩阵.md` 的核心门禁通过；真实桌面、重启、纠错、删除、真实模型与学习迁移证据齐全。

以下均不算完成：增加 MemoryOS 字样；只提供 MCP 工具但 Atlas 不调用；在 SQLite 手工造记录；只看模型自报成功；所有“学习”仅为生成 Markdown；多模态只丢掉原媒体保存 caption；删除只删 memories 一行；将跨平台愿景改称已接通；用总体平均掩盖关键失败。

最终状态按事实报告。若某门禁失败，保持 PARTIAL 并继续本任务书允许的修复；如需要用户才能提供的外部条件，明确具体条件。禁止通过降低标准或删失败用例闭环。

## 10. 执行者第一条指令

用户要求施工后，第一步是 UM00，不是开始安装候选框架。先核对仓库及未提交内容、制作权威映射和隔离测试，再执行 UM01。所有后续步骤依照本包，不继承旧 H1/MemoryOS 历史任务中的施工禁令或授权；本期范围以第 1 节和用户最新指令为准。
