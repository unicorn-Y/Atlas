# TASKBOOK-M9：由 Markdown `[[links]]` 提供可解释的一跳联想

状态：待后续施工。本文件是工作合同，不表示图联想已经实现。

## 目标、范围与数据权威

在 M5 已召回的 Markdown 页面/条目上，默认沿用户可读、可直接编辑的 `[[Page]]` 链接多看一跳，返回关联理由和原始来源指针。Markdown+git 记忆库是唯一权威；链接索引、关联缓存、访问计数和图投影全部由 Markdown 重建，不另存关系真源。PPR 是可选排序器、默认关闭；只有一跳联想经真实使用日志证明有收益后，才考虑单独启用 PPR。禁止模型关联直接改事实、有效时间、来源等级或自动写入人工链接。

SourceEvent 仍仅是 SessionDB transcript 指针；M9 不复制原文。外部 Agent 的运行结果先经 Atlas/M3 变成有来源的 Markdown 经历，再参加普通关联查询。

全局固定默认值：Basic Memory AGPL 只作行为参考，不复制代码；用户纠正永远最高，其次为 user（用户陈述/编辑）> tool（工具观察）> model（模型推断），同级新主张胜出、旧主张以 `superseded` 留在 Markdown 历史；遗忘沿派生链删除正文、摘要、索引和技能候选，只留 W0 已有内容哈希墓碑；关联默认只沿 Markdown `[[links]]` 多看一跳，PPR 默认关闭，只有真实使用证明一跳扩展有收益后才考虑启用。

## 固定上游依据与使用边界

- `agiresearch/A-mem@ceffb860f0712bbae97b184d440df62bc910ca8d:agentic_memory/memory_system.py:add_note/find_related_memories/process_memory/update_neighbor`（233、288–310、590、679–720）：只借“找到邻居后产生关联建议”的思路。上游 `update_neighbor` 用结果序号作本地 insertion index，可能更新错对象；修改等 consolidation 才同步 Chroma。Atlas 不复制此更新逻辑，不把模型建议写入 Markdown。
- `OSU-NLP-Group/HippoRAG@d5c8329422e0a0b834a15874545cb6a74b4f9b26:src/hipporag/HippoRAG.py:graph_search_with_fact_entities/run_ppr`（2008、2177）：仅在明确启用后借用 seed 加权 PPR。`run_ppr` 调用 graph library 的 `personalized_pagerank`，仓库没有自定义同名方法；实现运行在无向图投影。若有事实但没有正权重 seed，上游可能抛错，因此 Atlas 必须先处理 empty seed 并回退。HippoRAG 依赖 OpenIE/LLM/embedding/图服务，不搬整套服务。
- `basicmachines-co/basic-memory@a72751c5d626380dedeed30f55f7a80ba3dc710d:markdown/plugins.py:parse_relation_type/relation_rule`、`markdown/entity_parser.py:parse`、`services/context_service.py:find_related/build_context`：只参考 Markdown 明示关系与有限深度展开；其根许可 AGPL-3.0-or-later，**只作行为参考，不复制代码**。Atlas 使用自身现有 Markdown 页面结构。
- `getzep/graphiti@d50741d1bf463cbe3859eb73914cbff1b66839e6:graphiti_core/search/search.py:search/edge_search/node_search` 与 `search_utils.py:node_distance_reranker` 只作未来 query 设计对照；不引入 Graphiti 图存储或 hybrid graph stack。

## Atlas 路径审计与所有权

已实读 `D:\atlas-mem-w2-api`，HEAD `aa14c3173392d0fc60ec3e401e4495a2d3357cb7`。实际 library 仅有 `__init__.py, cleanup.py, dream.py, embed.py, extract.py, forget.py, hybrid.py, index.py, queue.py, sources.py, store.py`；不存在 `models.py`。`core/atlas/memory/library/index.py` 确实有 `MemoryIndex.sync/rebuild/search/facts`；`core/atlas/memory/library/__init__.py` 确实有 `MemoryLibrary._relevant_block/search`，目前从普通/episode/diary lane 组合召回。M9 施工基线为 A0 合并后的 `ui-redesign`，开始时核实此调用链仍存在。

| 文件所有权 | 目标函数 / 职责 |
|---|---|
| `core/atlas/memory/library/association.py`（**新建，M9 独占唯一代码文件**） | 新建 `parse_wikilinks(text)`, `build_link_index(store)`, `expand_one_hop(seeds, link_index, limit)`, `rank_associations(seeds, candidates)`；所有输入来自当前 Markdown parse；解析不可达目标时保留原文但忽略该跳。PPR 路径如日后启用则在此新建 `rank_ppr(...)` API，配置默认 false，独立于一跳扩展。输出供 M5 调用。 |
| `core/atlas/memory/library/index.py`（M5 独占，M9 不修改） | 已存在 `MemoryIndex.search/sync/rebuild/facts`。M5 在主召回路径调用 association API 并负责结果装配、过滤与索引重建。 |
| `core/atlas/memory/library/store.py`（只读调用，Entry/Page 元数据归 M7/M4） | 复用 `MemoryStore.pages/read` 与 `Page.parse`；若当前 schema 未暴露 wiki links，解析器读取 Markdown 文本本身，不改 store/Page。 |
| `core/atlas/memory/library/__init__.py`（M5/M3 owns，M9 不修改） | 现存 `MemoryLibrary._relevant_block/search` 为运行期路径，M5 负责从其主召回入口调用 M9 API；M9 只交付独立函数，不接线。 |

不得新建数据库作为图真源或额外 `models.py`。`.index.sqlite` 可删除并由 M5 从 Markdown 重建。关联原因需要引用页面/条目 ID 与来源 `source_ref`，不能存放复制的 SessionDB 正文。M9 的所有源代码改动仅限新建 `association.py`；它提供可调用 API，但不编辑任何现存 Atlas 文件。

## 逐步施工清单

1. 在 A0 合并后的工作树核实 `MemoryIndex.search` 和 `MemoryLibrary._relevant_block` 现状、M5 的候选结构及一跳链接页面格式；锁定与 M5 无重叠的输出扩展点。
2. 定义最小解析规则：识别 Markdown 中 `[[Page]]` 与 `[[Page#section|alias]]`；路径按现有页面 canonical name/alias 解析。大小写/空白规范化应确定但不得擅自改写原文件。坏链保持原文字面值并记 orphan，不自动创建目标页面。
3. 在 `association.py` 从 `MemoryStore.pages/read` 构建可重建的 source→target 邻接表。只接受页面中真实存在的显式链接；拒绝已删除/忘记目标、历史中已失效的实体映射和无来源的模型联想。索引持久化仅作为缓存。
4. 定义 `expand_one_hop` API：输入 M5 提供的 top seeds 及 Markdown 邻接投影，返回直接链接目标、`via_page/link_text/source_ref` 和可解释原因。M5 的主召回路径负责排除 seed 本身、重复项、已删除/撤回条目和预算外候选，并用现有 `MemoryIndex.search` 补目标页有效条目；不由 M9 改写 M5 排序。
5. PPR 实现放在独立函数/配置后面，默认 `association_ppr_enabled=false`。若真实使用数据确认一跳的遗漏有具体实例，再另行按用户既定默认值启用评估；当前施工只预留稳定接口，可不实现 PPR 算法。若启用，需空 seed/无边/异常/超预算回退 M5 原结果，图由 Markdown 即时或重建得到。
6. 删除、改名、编辑 `[[link]]` 后，增量同步或全量 rebuild 必须让关系结果反映 Markdown 最新内容。forget 与 M7 联动清除目标及沿其派生出的关联缓存；不得留下可恢复正文的 orphan 内容。
7. 将 API 与真实 Atlas 查询联调由 M5 完成：至少一种有用一跳链接、一个孤立页面、一个断链和一个删除/改名目标。根据用户是否实际打开/继续询问目标页记录结果（该记录仍为派生使用反馈）；不能用单纯命中数宣称 PPR 提升。M9 不编辑 M5 接线文件。

## 旧代码与数据迁移

保留 `MemoryIndex.search` 的 keyword/vector/hybrid 基础召回和 `MemoryLibrary` 现有 episode/diary lane；只增加可解释的一跳候选。已有 Markdown `[[...]]` 可无损索引；未确认语义的普通 URL/文字不自动转 link。清除任何旧的图表/外部图存储（若存在）并从 Markdown 重建；旧自动关联若无法映射为用户明示链接则不提升为事实关系，作为可删除派生物清理。链接索引、PPR 权重和点击/使用统计均不是权威且遗忘后可清除重算。

## 最少真实使用验收（真实对话与日志）

- 在真实 Atlas 记忆页中人工编辑一个 `[[Page]]`，重建索引后用相关查询检索：日志显示 seed、目标页、link_text、source_ref；目标内容从真实页面读出并出现在上下文中。再改掉链接并重建，旧路径立即消失，原文件编辑保持原样。
- 查一个孤立主题与一个断链页面：前者稳定只返回 M5 原始结果；后者显示可诊断 orphan 但不生成虚假目标。对已忘记页面执行查询，关联及索引日志都不再出现目标内容。
- PPR 默认配置为 off；默认运行路径日志可见未调用 PPR，结果只沿显式链接一跳。若另有批准的收益验证后启用，记录对照查询、打开/追问等实际使用信号、seed 权重和算法版本；empty-seed 必须回退且不能抛错。
- 删除 `.index.sqlite` 后从 Markdown 重建，查询关联结果一致；这证明数据库只是可再生投影，不是真源。

## 依赖、并行与边界

依赖 A0 完成并以 M2 后开始；与 M5 并行且无共享文件：M9 只拥有新建的 `association.py`，M5 独占 `index.py` 与 `MemoryLibrary.recall/search` 主召回路径，并在自己的路径里调用 M9 API。M9 不改事实、不改来源/时间/纠正规则；M7 拥有失效和忘记传播语义。可与 M4 并行，双方不得写同一 Markdown mutator；M1/M3/M7 不依赖 M9。PPR 默认关闭，未来是否启用以真实一跳使用证据为依据，不在本任务书中扩展成图数据库项目。
