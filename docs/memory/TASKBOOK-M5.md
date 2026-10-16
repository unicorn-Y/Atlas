# TASKBOOK-M5：可解释分层召回、精确原文引用与使用反馈

状态：待后续施工；本文是可执行施工合同，不表示功能已经实现。基线是完成 A0 后的 `ui-redesign`。所有检索结构服务于 Markdown+Git 权威记忆与 SessionDB 原文，不建立独立来源账本。

## 目标与数据不变量

为当前 Atlas 对话、任务和外部 Agent 上下文提供稳定召回：先返回简短总览/相关 Claim，用户或 Agent 需要时沿 `source_ref` 打开经历及 SessionDB 原文。结果给出 Claim ID、为何命中、时间状态、来源等级和来源指针。搜索排序、相似度缓存、SQLite、FTS、向量、链接图和统计日志均是派生物，可从 Markdown 与 SessionDB 重建。

唯一权威：记忆正文及 Claim 元数据写在 Markdown（Git 跟踪）。字段包括 `source_level`、`recorded_at`、`valid_from/to`、`supersedes/retracts`、`source_ref`；`SourceEvent` 仅是 SessionDB 会话/消息定位符，不保存另一份消息正文。打开原文由 SessionDB 读取。任何结果中的摘要必须带回 Markdown Claim ID 或 SessionDB 指针，不能变成不可追溯的事实。

本系统已拍板的共同规则也适用于召回排序与用户操作：用户纠正最高；来源等级依次为 user > tool > model；同等级时新记录胜出，旧 Claim 留存并标记 `superseded`。遗忘时删除 Markdown 内容及其派生摘要、索引、向量和技能候选，只保留 W0 已有的内容哈希墓碑。Basic Memory 为 AGPL，仅供 Markdown/文件协调行为参考，不复制其代码。关联默认只沿显式 `[[链接]]` 多看一跳；PPR 默认关闭，只有真实使用证明确有收益后才启用。

## 上游来源与具体可借机制

- `mem0ai/mem0@0724291bd864cf807e88ee8981c8226644e8fb42:mem0/memory/main.py:Memory.search/_search_vector_store/_add_to_vector_store`。参考向量 overfetch、候选合并、按相似度与元数据返回、重复候选过滤的流水线。边界：该快照 `top_k=10` 候选范围内的 hash 去重不是全库幂等保证；解析失败时仍可能保存消息缓冲。不得把“无重复”“所有写入已成功”当成 Mem0 保证，也不移植其持久层。
- `mnemostack/mnemostack@1d8dc160c06276b49c598e29cef3efbaf17d2559:src/mnemostack/recall/flow.py:recall_flow`、`retry.py:retry_weak_recall`。借用统一 recall pipeline（过滤、重排、数量/预算控制）与受限改写；retry 在上游默认关闭且最多两次额外变体，Atlas 初始默认也关闭。
- `openai/codex@092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`（官方 Codex Rust v0.162.1 拆解快照）：`codex-rs/memories/read/src/citations.rs` 的精确引用定位/展示；`codex-rs/core/src/usage.rs` 中使用计数分类只借字段设计。只借接口与行为，不移植 Rust。
- Claude-Mem 三级按需检索：短索引→搜索结果→按引用展开原文，作为交互层次参考；不要复制其独立数据库为真源的实现。
- `supermemory` MCP `search-memory.ts:register` 是远端客户端 façade，不是本地检索算法。OpenViking 根项目 AGPL，只作分层展开行为参考，不复制代码。

## Atlas 基线核对与文件所有权

已在 `origin/memory-w2-api` 核对下列真实函数；施工必须在 A0 合并后的实际基线再次核对 commit 和签名。Library 真实文件清单是 `__init__.py`、`cleanup.py`、`dream.py`、`embed.py`、`extract.py`、`forget.py`、`hybrid.py`、`index.py`、`queue.py`、`sources.py`、`store.py`。

| 文件 | 当前函数与职责 | 所有权 |
|---|---|---|
| `core/atlas/memory/library/index.py` | `MemoryIndex.sync/rebuild/_reindex/_keyword_search/_vector_search/search/facts/entities`；SQLite/FTS 和可选 embedding 当前实现 | **M5 独占整个文件**，包括所有 `MemoryIndex` 方法；M9 不编辑此文件 |
| `core/atlas/memory/library/hybrid.py` | `temporal_decay/merge_scores/_similarity/mmr_select` | M5 所有；负责融合与多样性 |
| `core/atlas/memory/library/sources.py` | `open_ref/_parse_at/search_raw`；目前通过 ref 读取经历/日记，原文搜索走 SessionDB | M5 所有，可增补引用解析；SessionDB 读消息应调用 M2 接口 |
| `core/atlas/memory/library/__init__.py` | `MemoryLibrary.recall/_resident_block/_recent_episodes/_relevant_block/search` | M5 独占 `MemoryLibrary.search` 与 recall 整合点（`recall/_relevant_block`）；M3/M4/M6 如需同文件改动，施工前约定函数级分块，M5 保持检索接线所有权 |
| `core/atlas/engine/session_sync.py` | `read_session_messages/read_session_all_messages/session_message_evidence/search_session_messages` 等 SessionDB 接口 | M2 所有；M5 调用不改 schema/读写实现 |
| `core/atlas/memory/library/store.py` | `Entry.meta/line/parse` Markdown Claim 字段 | M2/M3/M4 所有；M5 只消费稳定字段 |

不存在 `core/atlas/memory/library/session_sync.py` 或 `models.py`。不得以 SQLite index schema 当成真实数据模型。

## 施工步骤

1. **锁定已有调用面。** 在 A0 基线记录 `git rev-parse HEAD`，梳理 `MemoryLibrary.search/recall`、Agent prompt 注入点及 UI/API 返回结构。保持现有 API 字段兼容，扩展结果字段时使用可选键，明确默认返回层级和上限。
2. **明确内部结果结构。** 对每个 hit 统一标准化 `{claim_id, text, source_level, recorded_at, valid_from, valid_to, source_ref, score, rank_reasons, layer}`。此结构只在进程内传递或从 Markdown 派生；不要建另一张权威 Claim/source 表。当前 project/task 信息只用于相关性加权。
3. **分开候选生成和排序。** 将 `MemoryIndex.search` 拆为候选召回和排序：关键词/中文 token、FTS、向量（配置可用时）、实体命中、时间条件各自产候选及原始分。`hybrid.merge_scores` 合并归一化分数，按相关性、当前有效时间和重要度排序。M9 独占新建的 `core/atlas/memory/library/association.py`，仅实现显式一跳 `[[链接]]` 关联与可选 PPR API；M5 在本任务所有的 `index.py` 和 `MemoryLibrary.search/recall` 接线点调用该 API。默认只沿显式链接看一跳，PPR 默认关闭；只有实际使用证明关联带来收益后才能开启 PPR。
4. **实现渐进展开。** 第一层输出有限短摘要及 Claim ID；第二层输出匹配 Claim 正文、命中原因和时间/来源元数据；第三层 `open_ref` 依据 `source_ref` 调 M2 读取精确 SessionDB 消息窗口或经历文本。重复长文不得复制进每个召回结果。失效指针须明确标为不可打开，并保留 Markdown Claim，不得静默伪造引用。
5. **加入受控低命中补救。** 初始不做 query rewrite；可在配置启用后最多再产生两条候选 query。改写只能维持原意、实体和时间，不得扩大事实内容。每次改写记录原 query、改写文本和候选数，合并后仍使用同一排序管线。若重排模型或向量服务失败，回落到可用关键词/时间/实体排序并记录原因；不可因降级而不返回已有有效结果。
6. **记录用户可解释的使用事件。** 分开记录曝光、用户展开引用、Agent/模型明确引用、显式有用/无用反馈和任务最终结果；给事件稳定 ID，重放同一事件不重复累计。该日志只服务评估，可删除/重建，不承载 Claim 正文、来源真值或访问规则。未使用只降低后续排序权重的候选信号，不删除记忆。
7. **重建索引，不迁移索引事实。** 更新 tokenizer、schema 或排序字段时，从 Markdown 所有页面读取当前/历史条目重新构建 SQLite/FTS；从条目文本重算向量。SessionDB 原文索引按 M2 数据读取接口重建。无需迁移搜索缓存；无法从旧条目还原来源的数据明确标为 `legacy_unattributed`，仍可读但显示较低可信度。
8. **验证语义边界并接入 UI。** UI/API 保留现有检索入口；增加分层打开交互所需引用键。实现后检查详细原文由引用打开而非默认全量注入。记录索引版本和重建耗时作为运维信息；这些值不是记忆事实。

## 旧逻辑：删除与保留

- 替换：`index.py` 中把单一相似分或数据库排序直接暴露为最终答案的路径；不一致的独立关键词/向量召回格式；将 ref 当成可直接读取的正文副本；因“未引用”而删除 Claim 的设计。
- 保留：现有 SQLite/FTS/embedding 工具作为可丢弃投影；`tokenize` 的 CJK 二元词支持；来源分类作为展示/排序元数据；`open_ref` 当前 Markdown/日记定位兼容；通过 M2 的 SessionDB 原文读取；embedding 缺失时关键词回退。
- 新建（如确有拆分需要）：`core/atlas/memory/library/recall.py`（`RecallRouter.search/expand/record_usage`，派生召回逻辑）；`core/atlas/memory/library/citations.py`（`resolve_source_ref/format_citation`，来源指针显示）。先看当前模块规模，能在 M5 所有文件内完成则不新建。`core/atlas/memory/library/association.py` 由 M9 新建和独占，提供一跳/PPR API；M5 只在自有 `index.py` 与 `__init__.py` 检索接口中接线，不改 M9 文件。不得新建 source ledger。

## 旧数据迁移

1. 备份现有 Markdown/Git 和 SessionDB；保持条目 ID、正文、来源标签、时间和旧 ref 原样可读。
2. 扫描旧 `ref` 与日记 ref：可对应 SessionDB 消息的，映射为 M2 `source_ref` 结构；可对应经历 Markdown 的继续指向文件/entry；不确定的标 `legacy_unattributed`，不拼造消息 ID。
3. 将已有 `MemoryIndex` SQLite/FTS 删除后从 Markdown 重建；向量按当前 embedding 模型再算，缓存 build version；失败可继续用关键词搜索。
4. 旧访问/使用统计只在事件字段可区分时导入评估日志，不能升级成 Claim 来源；来源等级未知的统计数据丢弃也不影响记忆。
5. 对照迁移前后固定的一组真实查询，人工确认核心结果与可展开引用；检查历史条目仍可读、失效 ref 显示原因。

## 最少真实使用验收

在 A0 合并后的真实 Atlas 会话中，分别使用一个中文关键词查询、一个跨语义表达查询、一个具体人名/项目名、一个带时间边界查询、一个存在历史/当前相反 Claim 的查询。逐条查看日志中的 query、候选来源、融合得分/排序原因、有效时间判断和返回层级；至少打开三条引用，核对显示的经历/SessionDB 原文确实包含支持片段。实际关闭 embedding 后确认关键词结果仍可用；在隔离库删除 SQLite/FTS/向量目录后重启并观察从 Markdown/SessionDB 重建；配置启用时观察一次低命中最多两轮改写。检查曝光、引用打开、采用、反馈各产生可区分事件，重放日志不会重复计数。不得用测试桩或伪造日志代替真实会话。

## 依赖、并行与交付

依赖 A0 基线和 M2 的 `source_ref` / SessionDB 读取接口。M5 与 M9 在 M2 后可并行开发各自模块：M5 独占 `index.py`、`hybrid.py`、`sources.py` 和 `MemoryLibrary.search/recall` 检索整合点；M9 只新建并独占 `association.py`，实现一跳/PPR API，**不得直接编辑 `index.py`**。最终 API 接口由 M5 在自己的文件所有权内接线；默认启用一跳关联，PPR 默认关闭。M4 与 M5 可并行：M4 独占 `dream.py`/写入协议；`__init__.py` 由 M5 与 M3/M4/M6 先约定函数级分块。M6 依赖 M1/M2/M5 的召回接口。交付说明基线 SHA、改动文件/所有者、Markdown/SessionDB 来源映射、派生索引重建过程、真实查询和日志摘要、降级路径及未验证边界。
