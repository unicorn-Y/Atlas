# Atlas 原生记忆系统 · 续研增量与原生架构修订（2026-10-16）

> **新增研究文件，独立于原 V3 ZIP 快照。**
> 基线：`unicorn-Y/Atlas` 研究分支 `research/atlas-memory-2026-10-16-handoff` 交接提交 `c7610a7c7d6e05190240b9820f1dedf3d9434d12`。
> 本文件没有修改任何生产代码，也没有在用户 Windows 机器运行测试。**研究事实、静态风险、工程建议严格分开。**

## 0. 决策继承（已经由用户确定；不要再次询问）

1. **Atlas 唯一长期记忆主体**。Codex、Claude 等外部 Agent 是可替换、具有充分开发/执行权限的工具。这里的「统一写入语义」不是限制执行器文件权限。
2. Atlas 首次委派提供精简任务记忆，执行器随时向 Atlas 请求更多历史和原始证据；结果与真实工具轨迹回到 Atlas 后形成经历、事实与技能。
3. 最终覆盖聊天、任务、PC、浏览器、Android、视觉、语音；**视觉、语音和手机感知仅规划，不在本轮实施**。
4. 原有 W0/W1/W2/SkillOpt 必须先判定复用价值，禁止重复造已存在模块；优先移植成熟可证实的源码机制。
5. 弃用旧研究中的 DelegationGrant、租约授权、RBAC/审批闸口、第二个独立长期记忆服务等与最终决议冲突的设计。

## 1. 本轮 GitHub 核对范围

- 原归档入口 README、`source/README_先看这里.md`、`03_主权与委派`、`02_本轮深挖`、`00_新增研究` 已读取；旧 A/B/C 原始任务书、候选源码索引、论文/体验报告、Opus 旧差异和机器清单已核对分级与版本。旧版差异不凌驾于最新主权决议。
- 仓库远端 `main@aa6196f550098cc46081dc6db2c376cb87ddffa5`、`memory-v1@9ace88c5731ed8be6dd7406d758161236938e2de`、`memory-w2-api@aa14c3173392d0fc60ec3e401e4495a2d3357cb7`、`memory-w2-ui@11153a028feace09e952e23544e0adf1d155887c`（本轮查询时）。
- GitHub Compare 返回相对 main 各记忆分支领先、不是 main 的合并证据；`D:\Atlas` 实际运行版本 **未验证**。
- 新增深读 W2-A 的 `run_phases.py`、`library/{__init__,queue,dream,index,hybrid,embed,sources}.py`。外部新增深读 AMA-Agent `construct.py/retrieve.py/tool.py`、LongMemEval-V2 `trajectory_store.py`、`agentrunbook_online_learning.py`。

## 2. 新发现的源码级问题（与原 W2 缺陷审计去重）

| 编号 | 观察 / 位置 | 已验证程度 | 影响 | 最小建议 |
|---|---|---|---|---|
| N01 | W2 `queue.py::pending()` 读取 `attempts<3` 的全部条目，没有原子 claim；`MemoryLibrary._turn_lock` 仅进程内 `asyncio.Lock` | **代码静态确认，双进程实测待做** | 若多进程/库实例同时 drain，同一轮可能被消费两次 | 在原 `.queue.sqlite` 上加入领取标记、领取到期与 `UPDATE ... RETURNING` 原子 claim；不需要 Redis/RabbitMQ |
| N02 | `queue.py` 达三次失败不再出现在 `pending()`，只留 `failed_count()` | **代码静态确认** | 暂时性 LLM/网络错误可能导致长期未提炼而无自动恢复 | 区分 transient 退避重试、人工可见的真正永久失败；提供一次恢复入口，别无限重试 |
| N03 | `index.py::_schedule_embeddings()` 要求 `asyncio.get_running_loop()`；正常主会话 `_merge_library_recall()` 使用 `asyncio.to_thread(library.recall,...)`，后台 `_apply` 同样在 `to_thread` 中调用 `index.sync()` | **代码调用链确认，真实 W2 环境待复现** | 自动 embedding 构建可能未被调度（并非宣称“所有入口永不调度”，其他事件循环入口可能触发） | 将 `embed_missing` 放入已存在的明确 runtime 后台任务入口，而不是指望同步索引调用所在的线程碰巧有事件循环 |
| N04 | `dream.py::run_dream()` 先写 Markdown / Git commit 后独立写 `.dream-state.json`；页面写入也不是原子替换 | **代码静态确认；崩溃注入未验证** | 中途失败时索引、页面、checkpoint 可不同步；重试可能重算新 ID | 将已处理 source IDs 与生成版本持久化为单个可恢复作业状态，写派生视图用临时文件 + rename，作业幂等 |
| N05 | `run_phases.py::_note_tool_step()` 最多 30 步、每步 `note` 最多 200 字符；`open_ref()` 仍靠 session+timestamp 最近消息定位 | **代码静态确认** | “工具执行摘要”不等于可复查完整轨迹。长任务早期步骤及详细参数/结果可能不可由摘要恢复 | 原始会话/工具事件按精确 `message_id/tool_call_id/event_id` 指针引用；摘要仅做可丢弃索引 |
| N06 | W2 `index.py::tokenize()` **已经使用中日韩双字 gram**，且 FTS5 配置 `trigram` | **代码静态确认** | 不能误报“中文完全没有词法支持”，也不能为了中文盲目重写 tokenizer | 只做“2 字词、代码符号、路径、错误码”代表性比较，决定是否换词法召回策略 |
| N07 | W2 `embed.py` 首次初始化失败后置 `_attempted=True`，进程内后续不自动重新加载 | **代码静态确认** | 模型临时未安装/下载失败后，恢复文件不代表该进程马上恢复向量 | 给用户可见的 `unavailable` 状态及显式重新初始化入口；非优先 P0 |

N01/N03/N04 属静态调用链揭示的**待复现故障机制**，不能冒充用户本机真实事故。原研究已有 Dream 未成熟 group 跳过、project trigger 误合并、source timestamp 误定位、完成状态不等于真实验收等问题，此处不重复立项。

Atlas 代码依据：
- https://github.com/unicorn-Y/Atlas/blob/memory-w2-api/core/atlas/memory/library/queue.py
- https://github.com/unicorn-Y/Atlas/blob/memory-w2-api/core/atlas/memory/library/index.py
- https://github.com/unicorn-Y/Atlas/blob/memory-w2-api/core/atlas/memory/library/dream.py
- https://github.com/unicorn-Y/Atlas/blob/memory-w2-api/core/atlas/memory/library/__init__.py
- https://github.com/unicorn-Y/Atlas/blob/memory-w2-api/core/atlas/agent/run_phases.py

## 3. 进一步深入、可吸收而此前未源码裁决的成熟机制

### R01｜AMA-Agent：证据充分性驱动的轨迹检索（**提升优先级 P1**）

- 仓库 https://github.com/AMA-Bench/AMA-Bench ，所查顶层 `LICENSE` 为 MIT。
- **已读源码**：`src/method/ama_agent_core/retrieve.py::memory_retrieve` 先取相似片段，再通过 `SUFFICIENT / NEED_GRAPH / NEED_CODE` 分支判断是否扩展证据；`tool.py::traj_get` 能按轨迹 turn 索引、区间、字段提取，`traj_find` 能按 keyword/regex/action/entity 搜索；`construct.py` 可选构建因果图。
- **借用边界**：建议吸收 `traj_get`、`traj_find` 的轻量结构化“原始证据下钻”及“是否足够回答”的策略，不直接搬 `NEED_CODE` 中让 LLM 生成并运行 Python 搜索脚本的整套实验框架。ContextBroker 可以先廉价查 episode，再按不足证据请求相关工具邻域、commit、错误日志。
- **重要区别**：因果边由模型猜测得到时仍是候选边；不能把相邻两步自动写成验证过的 `CAUSED_BY`。
- **效果证据**：论文给出 AMA-Agent 的基准成绩，**Atlas 中文/Windows/开发任务未复现**。https://proceedings.mlr.press/v306/zhao26bs.html
- 源：https://github.com/AMA-Bench/AMA-Bench/blob/main/src/method/ama_agent_core/retrieve.py 、https://github.com/AMA-Bench/AMA-Bench/blob/main/src/method/ama_agent_core/tool.py 。

### R02｜LongMemEval-V2：逻辑轨迹指纹 + 自适应检索策略（**P1/P2**）

- 仓库 https://github.com/xiaowu0162/LongMemEval-V2 ，所查顶层 `LICENSE` 为 Apache-2.0。
- **已读源码**：`memory_modules/trajectory_store.py::logical_trajectory_fingerprint_from_simplified` 规范化目标、结果、动作及状态，再以 SHA256 识别同一逻辑轨迹（刻意不直接将截图路径等易漂移字段作为内容主键）。这是跨机器/迁移/重复导入去重的一种可行机制。
- **已读源码**：`memory_modules/agentrunbook_online_learning.py` 将检索历史、适用条件和策略经验整理到 `LEARNED_RETRIEVAL_STRATEGY.md`；相当于学习“应该去哪儿找证据”，而非新建独立 Agent 长期人格。
- **Atlas 复用方向**：采用稳定 `source_event_id` + 逻辑内容 fingerprint + 事件来源引用来做幂等。对难查的老故障，可以在 Atlas 自己的 `RecallRouter` 维护少量经回放证明有用的“先查哪些路径/仓库/日志”的检索策略。与已有 SkillOpt 分清：检索策略不等同可执行操作 Skill。
- **限制**：基准代码可能假设 web 轨迹、截图和 Linux 辅助工具，Atlas 不应原样安装整套基准宿主，也不代表已在 Windows 跑通。
- 源：https://github.com/xiaowu0162/LongMemEval-V2/blob/main/memory_modules/trajectory_store.py 、https://github.com/xiaowu0162/LongMemEval-V2/blob/main/memory_modules/agentrunbook_online_learning.py 。

### R03｜LangGraph：当前任务 checkpoint 与长期记忆 store 分离（**只借状态模型**）

- 官方文档明确区分 thread-scoped checkpointer 与跨 thread long-term store：https://langchain-ai.github.io/langgraph/concepts/durable_execution/ 。
- Atlas 已有任务/会话 runtime，不应该再引入 LangGraph 作为并列 runtime。**借概念但不照搬第二套运行时**：活跃 task checkpoint 保存“做到哪一步、下一步什么”；Atlas 长期记忆保存从任务证据得出的持久经验。这两者使用引用关联，任务恢复不应靠向量搜索碰运气。
- **状态：官方机制已核对，Atlas 适配尚未实施**。

### R04｜SQLite FTS5：现有索引不宜因新架构被反复重造

- 官方文档明确 FTS5 `trigram` 与 external-content 的约束、触发器一致性：https://www.sqlite.org/fts5.html 。
- W2 的文本索引本身已支持 trigram 和自定义 bigram。候选替换要证明真实检索收益；结构化 evidence/claim 数据若迁 SQLite，也只需保留一套可重建 FTS 派生索引，防止重复事实真源。
- **状态：SQLite 官方机制 + Atlas W2 代码已核对；迁移方案未实测。**

## 4. 修订后的原生架构：明确三条不能混淆的时间线与五类数据

**唯一拥有者 Atlas** 并不意味着所有数据必须放在同一张表、同一个 prompt；长期记忆逻辑真源唯一，而事务、媒体、视图可分层：

1. **不可混淆的原始证据（SourceEvent）**：`event_id`、`session_id`、`task_id`、`run_id`、`tool_call_id`、`source_actor`、`workspace/project_id`、`occurred_at`、`received_at`、`payload_ref`、`content_hash`。优先引用 Hermes/Atlas 已存原文而不是再复制一套大日志。纠错/删除指令对派生视图产生失效传播。
2. **TaskState / ExecutionState（活跃操作进度）**：目标、计划、当前环境、已完成步骤、待确认项、恢复点、外部执行器状态。**不等于用户的长期事实**；可恢复运行与长期记忆独立但相互引用。
3. **Episode + Claim + Entity/Link（可重建的认知结构）**：Episode 是有目标的行动轨迹及结果；Claim 是带 `source_event_ids`、有效期、观察期和冲突状态的派生判断；Entity 用项目/仓库/设备/人物稳定 ID 而不是 trigger 名字串；Link 区分 `NEXT`、`SUPPORTS`、`CONTRADICTS`、`DEPENDS_ON` 与**待证实的因果猜测**。
4. **WorkingContext / ContextBundle（可丢弃装配物）**：Atlas 根据 worker 的任务和当前阶段生成；外部 Codex/Claude 按需 `request_more(task_id, query, seen_ids)`，可展开精确事件原文。装配物不是新的独立事实来源，避免摘要自我强化。
5. **Policy / Skill / Prospective Commitment（行动资产）**：检索策略和操作 Skill 分开，前者优化证据寻找，后者经 Atlas 现有 SkillOpt 评测、记录适用条件与反例；定时/条件承诺连接调度系统，不能仅当向量记忆。

**工程首选（暂定、可推翻）**：单机先保留 Atlas 原始 engine 作为聊天/工具证据源，给它稳定 event pointer；派生 claim/episode/FTS/轻边放 SQLite，按需加 embedding；Git/Markdown 用作人类可读编辑层而非“所有派生事实每夜整体重写”的唯一真源。实际规模/跨设备并发证明不足时再考虑 PostgreSQL。其他外部项目只移植少量机制，不部署多套同时长期运行的记忆服务。

## 5. 修改研究优先级，而不是增加十个新项目

### P0｜先核对和修正 W2 正确性

- 把 W2-A/B 的真实调用路径、未合并组件和 API 字段核准；确认实际主机使用哪一版（**未验证**）。
- 对原报告的 Dream checkpoint / trigger 跨项目误合并 / source timestamp 错位 / Skill 自报验收继续做小范围反例。
- 新增 N01/N02/N03/N04 四个最多十几步的定向复现。只有复现才上升到“真实缺陷”；静态风险本身不能夸张为已发生事故。

### P1｜先修证据与任务持续性，再增强“主动想起”

- 初始 ContextBundle + 运行中 request_more 挂现有 worker/tool 通道，不加第二套授权基础设施。
- event pointer 精确到 message/tool/event，原文可按区间展开；增加 `get_episode_trace`、`get_event_range` 等小函数可复用 AMA-Agent `traj_get` 结构。
- ContextBroker 的检索执行优先 lexical/metadata，再 dense/关系，仅在证据不足时扩大；从 tool_error、subtask_start、before_skill 等触发，减少盲目搜索。
- 消费成功的 source 及派生版本采用明确 job-level checkpoint/幂等，保证中断后可继续。任务恢复进度和长期记忆巩固进度分开。

### P2｜经验到策略，再到 Skill

- 重用 Atlas `skill_sleep.py` 与现有 Skill 目录。引入使用证据/负例/适用版本，不创建第二套晋升系统。
- 在离线回放中先试小型 learned retrieval strategy；策略变差能回到旧版，再根据 LongMemEval-V2/AMA-Bench 的研究接口扩展。
- 未来视觉、语音、Android 的 schema/time/media refs 继续保留，但**暂停任何采集、模型部署或自动监控施工**。

## 6. 最小验证清单（本轮均 NOT EXECUTED）

| 测试 | 预期 |
|---|---|
| 两个独立 MemoryLibrary 实例/进程消费同一队列行 | 恰好写入一个 episode；不要只依赖单进程 `asyncio.Lock` |
| 模型临时错误三次后恢复 | 失败可见，可主动重试成功，不能永久漏记 |
| 主聊天首次 recall、回合结束，且只使用现有自动链路 | embedding 任务真正启动；状态从 building 到 ready/unavailable 有证据 |
| Dream 写第二个项目时故障并重启 | 不丢任何原始 episode、可重试、无重复派生事实 |
| 30 步以上的真实工具任务中查询第 1 步原文 | 能通过 event pointer 开到准确 tool call/result，不依赖 200 字符摘要 |
| 两个 Codex/Claude 执行器接续同一任务，执行中索取旧错误背景 | Atlas 回答之前未提供的精确相关证据、避免重复包；执行器仍保有充分文件/命令权限 |
| 已撤销 claim 的索引与旧摘要 | 不作为当前事实被重新返回 |
| 中文双字词 + 文件路径 + 错误码 vs 语义问法 | W2 既有 bigram/trigram 与候选融合真实比较，不虚报新增词法功能 |

## 7. 证据边界与后续研究要点

- **已验证 = GitHub 源码可读、明确调用路径和实现机制存在**；不等于 Windows 测试通过、更不等于生产生效。
- **待验证** = 并发/崩溃/线程运行时条件下静态风险能否复现；中文写入/检索实际命中；模型 API 费用和端到端时延；引入 AMA sufficiency 是否真正提高后续任务成功率。
- **未实施** = 以上架构迁移、ContextBroker 接线、事件 ID 迁移、队列升级、技能闭环增强、视觉/语音/手机采集。
- **暂不做**：部署图数据库/并行 memory server/新权限网关、整套 AMA Agent 的 Python 代码执行搜索、重做已有 FTS UI、上大规模无关单测。
- **没有要求用户新增选项**；当前默认按上述小切片推进。真正锁数据库/是否长期全量媒体留存等不可逆取舍时再询问。

研究新材料留在本文件，原 V3 ZIP 的既有 SHA256 和归档状态不改；未来若重新发布 V4 再统一封包。