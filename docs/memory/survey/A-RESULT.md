# Atlas 记忆系统源码调研｜A 线结果

检查日期：2026-10-16（Asia/Hong_Kong）。范围：M3 提炼、M4 跨会话整合/做梦、透明记忆库。只读源码与官方拆解；没有改 Atlas 代码，没有运行项目或测试。

## 执行与证据边界

- 工作树 D:\atlas-mem-survey-a，分支 memory-survey-a，基于 origin/memory-survey 的 64a4f650a45a69061fcc3d0aa07a513366e8e426。已先 git fetch origin。
- D:\Atlas 原工作区已有未提交改动；本任务没有在其中编辑。映射分别注明当前 survey 基线、origin/memory-w2-api 或官方解包来源。
- repo HEAD 不代表完整历史，未运行任何项目。源码、官方 sourcemap、GitHub 源码页、测试/文档证据分开描述。
- 调研期间 D: 可用空间降至 0 bytes。已成功创建的浅克隆保留在 D:\_research\memory-survey\repos；停止继续 clone/写入，没有清理任何 clone。中间证据笔记位于 C:\Users\25011\Documents\Codex\A-M3.md、A-M4.md、A-TRANSPARENT.md、M4-codex-candidates.md，证据已汇总于本报告。

## 总裁决

1. M3：Mem0 ADD-only 单次提炼最强，Mastra Observer 第二。Mem0 在同 scope 最多检索10条已有记忆的基础上，只从新消息提候选、以日期解析相对时间、在召回结果与当前batch范围内去重/链接；成功记录进入ADD历史，但消息上下文缓存可能在失败时仍保存；它不负责 UPDATE/DELETE 纠错。Mastra 的结构化 extractor、previous extraction、thread metadata 与 transient retry适合可控字段提取，但仍是 thread-scoped observation，不是跨会话 canonical fact ledger。Atlas 应提炼带来源等级的事实/任务经验/工具观察/推断候选，再由 Atlas 自身证据层裁定。
2. M4：Codex 的控制闭环最强（lease、增量 Git diff、retry、产物校验、水位）；OpenClaw 的宿主校验第二，尤其适合保护用户手改：模型仅给 plan，宿主按精确旧文本与来源 lineage 校验后应用。ReMe 的逐条增量合并可作语义参考；Mastra 压缩梯度和 generation guard 可补强。
3. 透明库：选 Markdown 为唯一规范内容，SQLite/向量只作可重建投影。Basic Memory 清楚实现了文件SSOT和投影分离；Codex baseline diff 与 OpenClaw exact-match apply 更接近“用户改动不能被覆盖”。Basic 的 locked note 不保护直接改文件。Atlas 现在已有 Markdown/Git 和 SQLite索引，但无强的用户编辑协调协议。
4. Claude 骨架保留并增强：两阶段管线、透明文件库、来源等级、页面链接保留；补入 lease/idempotency/diff/retry/validation；整合模型改提案，不直接重写；来源权重按用户已拍板的用户陈述 > 工具观察 > 模型推断，但三类都可记录并保留原始证据；Markdown是真源，索引可重建。ReMe的 mtime checkpoint 不足以替代 Atlas event ID/version 账本。

## M3｜一轮或会话结束后提炼

| 项目 | commit / 许可 | 关键源码 文件:函数:行 | 机制与存储 | 重试、去重纠错、召回、可读可改、反馈 | 移植成本 / 证据 |
|---|---|---|---|---|---|
| Codex Phase 1（官方拆解） | rust-v0.162.1, 092d3acd6bec3e3a14bdc7e7a2810ab628ab759d；Apache-2.0 | memories/write/src/phase1.rs:run:56,prune:97,claim_startup_jobs:120,build_request_context:159,run_jobs:174; stage_one_system.md:45,102,226,257 | 每个rollout独立提炼出raw_memory与rollout_summary；提示要求保留证据/不确定性，并区分任务。状态入SQLite并异步排队。 | lease claim/失败退避在相邻DB job层；原文指针可回溯。人可读输出在Markdown，但不是内部SQLite真源；M3没有使用反馈。 | Rust/runtime高；流程与提示源码已读，按官方快照而非GitHub HEAD。 |
| Mem0 | 0724291bd864cf807e88ee8981c8226644e8fb42；Apache-2.0 | mem0/memory/main.py:add:760, search:925-970/1393, persist/dedup:1000-1118; configs/prompts.py:ADDITIVE_EXTRACTION_PROMPT:468-548 | add先检同scope，再只从新消息提ADD-only事实；基于观察时间解析相对日期；向量payload+SQL历史 | LLM错误上抛供caller retry；批写失败逐条fallback；hash/entity去重并链接相关记忆，不修正旧事实；vector/metadata召回，API可读改但非文本真源；feedback_str可指导提取，未见使用反馈 | 高；源码已读。 |
| Mastra Observer | a15924e709dd5d9439a6c102901c326ab0ec77fb；Apache-2.0，ee子树有例外，packages/memory无独立许可 | extractor.ts:46-63; sync.ts:113-143,228-305; async-buffer.ts:62-105,154-204; retry.ts:239-270; observational-memory.ts:3028-3074; observer-agent.ts:65-72 | 声明式结构抽取，默认传上次 extraction；active observation和抽取结果写入thread OM metadata | transient最多8次retry、指数退避+jitter；prompt要求supersede/合重但非硬冲突规则；自动注入head active observations；Studio可看时间线，已审组件未见编辑；无usage feedback | 中高；源码行+GitHub；未运行。 |
| Claude-Mem | b8fc2ef9bab0dd1438d6cc8699c6884445ad409b；Apache-2.0 | OpenAICompatibleProvider.ts:processObservationMessage:509-574; postgres/observations.ts:insert:95-120; ServerContextRows.ts:38-99,172-173; MemoryIngestRoutes.ts:52-85 | tool事件压缩后形成observations，reader区分observation/summary；generation_key防重放，导入已有文件可hash去重 | 唯一键冲突只更新时间、不改正文；完整response校验/retry未证；recent rows限额注入；viewer可读，数据库行编辑未证；无使用反馈 | 高；生产prompt/DB路径实读，但response链未全审。 |
| LightMem | 8449d574df6bae1bdf3314a1564da65e2f37e046；MIT | lightmem.py:add_memory:204,310-394; online_update:396; offline_update:399-449; retrieve:646-709 | short buffer达阈值后分段提取为MemoryEntry；online_update当前为空，offline_update才写索引 | retry/事实冲突/手改/feedback未证；offline标consolidated时间；向量召回 | 中高；只借offline bookkeeping，源码抽样。 |
| SimpleMem (SKILL实现) | 74174a1c0c95d487144a74a77addb2c23f27f783；MIT | memory_builder.py:add_dialogue:56,process_window:117,process_remaining:141,_generate_memory_entries:154-219; hybrid_retriever.py:retrieve:63; vector_store.py:add_entries:123-150 | 窗口抽atomic entries，prompt含coreference/时间锚和上窗最多3项；末窗flush。Lance+向量+FTS | 提取/JSON最多3次retry，写入无retry；无明确事实级去重/纠错；hybrid召回；编辑/反馈未证 | 中高；源码读；仓库另有cross实现，本文只指SKILL。 |
| MemoryOS | 587ed7755c7aed179965792830ff1b5ad9a6fa92 (2026-07-07)；Apache-2.0 | memoryos.py:add_memory:226-250,129-219,252-348; updater.py:100-207; retriever.py:92-130; mid_term.py:190-228,281-360; long_term.py:26-139; utils.py:48-64 | 短期满转中期主题session，热度阈值再抽长期profile/知识；FAISS和memory pages | 异常返回固定Error文本无retry，错误可能混入profile；Jaccard/embedding合主题但知识逐行append、profile整体覆盖，缺事实纠错；召回更新heat；无用户UI或显式反馈 | 中高；源码读。 |
| Memobase | 358c16bbc6d687937d79bc2f984a11c3be8da901 (2026-01-11)；Apache-2.0 | controllers/buffer.py:33-47,66-94,117-201; modal/chat/extract.py:15-69; merge.py:15-199; profile.py:75-117,120-223 | token满flush，按topic抽事实，再由LLM做UPDATE/APPEND/ABORT，profile在DB/cache | 同步入口有并发重复flush FIXME；自有retry未证；后端可读改、未见UI；update hits是计数非用户反馈；合并由LLM判断 | 中高；源码读，SDK隐式重试未证。 |
| Nemori | d2a6dff6e5481214a0be6a2d10147feccfc16244 (2026-04-16)；MIT | core/memory_system.py:76-162,197-212; generators/episode.py:30-113; semantic.py:43-151; orchestrator.py:35-45,96-183; merger.py:37-171; search/unified.py:35-114 | buffer异步切episode、保source messages、LLM合并并抽semantic；可预测-纠错对照新旧知识 | PostgreSQL/Qdrant；默认3次指数退避+jitter；merge LLM判同类并替换旧episode；hybrid vector/text+RRF；可search/delete，无edit/usage反馈；confidence未用于自动纠错 | 高；源码读；上层UI未查。 |
| Claude Code | 2.1.88 sourcemap (2.1.296另有bundle)；闭源 | memdir.ts:buildMemoryLines:199-266,buildAssistantDailyLogPrompt:327-365; sessionMemory.ts:shouldExtractMemory:134-181,extractSessionMemory:272+ | topic markdown + MEMORY.md入口；daily log append后/dream蒸馏；session summary只为压缩连续性 | prompt去重纠错，无事务retry证据；文件可见；无反馈证据 | 源码行为参考，版本差不可等同，不可移代码。 |
| A-MEM（新增） | ceffb860f0712bbae97b184d440df62bc910ca8d；MIT | memory_system.py:add_note:233,consolidate_memories:266,update:357,search_agentic:509 | note局部关联与evolution，Chroma默认ephemeral | 失败可回原note、retry/事实裁决/feedback弱；人工update入口 | 中高；只作关系增强候选。 |
| Graphiti（新增） | d50741d1bf463cbe3859eb73914cbff1b66839e6 (2026-10-15)；Apache-2.0 | graphiti.py:retrieve_episodes:1249,add_episode:1332,search:1903,add_triplet:2023; nodes.py:EpisodicNode:318,EntityNode:499 | event抽实体关系写时序图 | retry/冲突/人工编辑/反馈本轮未深读 | 很高；源码入口已读。 |
| Hindsight（新增） | 9a499b1759084a86598eff8af30ed59f7354e76c (2026-10-15)；MIT | mcp_tools.py:retain:1008/1069,recall:1259/1363,reflect:1466/1561 | retain/recall/reflect API分层 | 只读MCP wrapper，底层retry/dedup/人工编辑/feedback未知 | 高；入口读，待追。 |
| Mem0以外的候选范围 | OpenClaw、Letta由M4覆盖；Claude Code上列 | M4表有OpenClaw/Letta refs | 不把M4整合机制冒充M3抽取实现 | M3 production抽取细节未查的在“未查清”列明 | — |

M3裁决：第一 Mem0的“同scope候选 + 新消息ADD-only + 有限召回范围内hash去重 + 写入确认后推进”；它只能覆盖新增事实，不覆盖更新/删除。第二 Mastra的“structured extractor + previous extraction + thread状态 + transient retry”；但它是thread scoped observation，不是canonical cross-session memory。Claude-Mem的event→observation→summary→viewer路径有价值，但当前证据不如前两家完整。

M3移植：
- mem0 add / ADDITIVE_EXTRACTION_PROMPT → core/atlas/memory/library/__init__.py:MemoryLibrary.observe_turn/_extract_full 和 extract.py:SYSTEM_PROMPT/build_messages/parse_output/apply。保留同scope旧候选、新内容增量、日期锚、有限召回范围内hash去重、写成功才推进；改造成Atlas来源等级/原文指针；不要移植vector provider或ADD-only作为全部生命周期。取代只接受said用户原句的旧规则。
- Mastra extractor/sync/retry → 同一MemoryLibrary：保previous extraction/结构schema/transient retry；跨会话冲突交给Atlas来源账本；不搬TS runtime。
- SimpleMem process_window/process_remaining → TurnQueue与MemoryLibrary._drain：借批次边界/末尾flush，不拿prompt当持久去重。
- MemoryOS仅借热度优先级；Memobase借UPDATE/APPEND/ABORT决策类型但加并发保护；Nemori借带source的episode和retry，不搬Postgres/Qdrant。

## M4｜跨会话整合 / 做梦

| 项目 | commit / 许可 | 关键源码 文件:函数:行 | 做法、恢复/去重/人工编辑/反馈 | 移植成本 / 证据 |
|---|---|---|---|---|
| Codex Phase 2 | rust-v0.162.1, 092d3acd6bec3e3a14bdc7e7a2810ab628ab759d；Apache-2.0 | phase2.rs:run:49,claim:214,failed:249,handle:366,loop_agent:477; workspace.rs:memory_workspace_diff:29,reset_memory_workspace_baseline:46,validate_consolidation_artifacts_for_version:76; consolidation.md:111-197 | DB按限制/unused days选输入，git diff后调用agent；无变更且产物有效才推进水位。lease/heartbeat/cooldown/retry、ownership与artifact检查；prompt要求用户改动传播、按来源定点删除。markdown可人改但冲突由LLM判断；semantic dedup为prompt处理，无M4直接usage反馈 | 高；状态机可移，Rust runtime不移；源码已读。 |
| ReMe dream（已查不重做） | agentscope-ai/ReMe@514ca643a17cebf85d99da514da6b11b339197f2；Apache-2.0 | schema/dream.py:DreamUnit/DreamState/IntegrateOutcome; dream/extract.py:DreamExtractStep.execute; integrate.py:_integrate_one; finish.py:DreamFinishStep.execute | extract→逐条增量integrate→finish/state；mtime/file catalog窗口；新建/佐证/细化/更正。不整页重写 | 锁/部分成功/结构化输出；状态失败不冒充完成；人工段落保留、事实冲突交模型；反馈未知。依据已审V4.1材料，不重新clone | Python依赖较重；只借增量语义。继承源码审查。 |
| OpenClaw dreaming | official unpacked 2026.10.3, 59cb44796b0f1f0daa0e37af8b1495abb45d9bc1；MIT根，memory-core无子license | dreaming-consolidation.ts:parseConsolidationPlan:83-125,validateConsolidationPlan:205-284,applyMemoryConsolidationPlan:285-394,consolidateMemory:396-440; dreaming-phases.ts:dedupeEntries:978,selectRemCandidateTruths:1101,runDreamingSweepPhases:1379 | LLM只给added/merged/superseded plan和exact old rows；host验证action/key/lineage/旧文/损失比后幂等apply，失败append-only fallback。人工改旧行会失配而拒绝覆盖；Markdown/JSONL人可读；无使用反馈 | 低中，移协议/validator；官方解包源码已读。 |
| Mastra Reflector | a15924e709dd5d9439a6c102901c326ab0ec77fb；Apache-2.0, ee例外 | reflector-agent.ts:buildReflectorSystemPrompt:1072-1251,COMPRESSION_GUIDANCE:1261-1399; reflector-runner.ts:callReflector:3018-3172; retry.ts:withRetry:1145-1204 | Observation日志按0..4压缩梯度，保持时间/完成状态并验证压缩；active/history可见 | generation guard；语义失败递进尝试、transient transport单独退避；Studio可读编辑弱，无usage feedback | 中高；GitHub源码页，未完整本地审。 |
| Letta sleep-time | letta-code current, Apache-2.0；本地SHA不可用 | reflection.md:201-239; memory-worktree.ts:finalizeReflectionMemoryWorktreeUnlocked:2314+ | reflection子agent在隔离Git worktree读近转录与memory/skills | dirty/conflict处理为retryable，避免盲覆写；文件可读；usage feedback未证 | 中高；源码页，未clone。 |
| A-MEM | ceffb860f0712bbae97b184d440df62bc910ca8d；MIT | memory_system.py:find_related_memories:288-313,update:357-396,process_memory:590-727 | 近邻memory局部演化，更新tags/links/context | 默认Chroma ephemeral；失败回原note，缺retry/审核/feedback；不适作事实权威 | 中高；源码已读。 |
| Claude Code | 2.1.88 sourcemap，当前包2.1.296 closed source | memdir.ts:buildAssistantDailyLogPrompt:327-365; sessionMemory.ts:shouldExtractMemory:134-181 | 按主题memory文件+daily log，dream整理；session summary为压缩连续性 | prompt约束为主，没见事务retry；可读改，无反馈 | 低行为参考；闭源/版本差。 |
| MemOS local plugin lifecycle | D:\memos-src HEAD a7367d07e55db61099f7b4e2c1108bc5831a24f3；根 Apache-2.0 | core/memory/l2/l2.ts:runL2:61; core/memory/l3/l3.ts:runL3:84,recordFailure:599; core/memory/l3/abstract.ts:abstractDraft:59,buildWorldModelRow:165; core/skill/lifecycle.ts:applyFeedback:37 | L2把未匹配trace放candidate pool并按来源证据归纳成policy；L3按policy cluster抽象成world-model并带supersedes/sourceEpisodeIds。不是夜间文件dream，而是分层知识生命周期。 | L2候选promotion持久后挂trace；L3 KV retry backoff 5m/30m/2h/6h，四次失败quarantine，成功清retry；vector embedding失败单独入retry queue；合并时调整confidence。用到trace/source IDs，读写状态结构化；未见Markdown透明编辑面或usage feedback；Skill lifecycle另有feedback。 | 高：TS repository/plugin依赖；本地源码已读，非MemOS主Python服务。 |

M4 GitHub自搜新增候选：
- quinnmacro/dream-cycle@632728f66f272851e55af7424f5b37e18cac22e2，MIT；dream_engine.py:rem_dream_walk:31,llm_boost_relations:393,nrem_hebbian_consolidation:501。图漫游、证据门槛验证、Hebbian强化；无事实手册纠错；Python+Neo4j高成本。
- pylit-ai/opendream@1c3035464e54f59ecc11947f71336d0d2d7bb1c7，Apache-2.0；consolidator.py:_cluster_candidates:55,_record_from_candidate:74; semantic_dreamer.py:_run_deterministic_phase:325,_equivalent_learned_context:545,_synthesize_proposals:365。scope/type/Jaccard聚类，存provenance/supersedes/conflict/lifecycle，event去重；synthesis明确是heuristic；Python中。
- openJiuwen-ai/agent-memory@9bf45fa4154fc448cbe6a126958c50b9f26a1685，Apache-2.0；sweeper.py:Sweeper.run_sweep:73,_extract:103; store.py:MemoryUnitKnowledgeStore.promote:69。写入后推进checkpoint、失败下轮重试，跨主题归纳要求双证据；向量store不透明，中高。
- thevisionhub/agent-sleep@77678ab9de35a4b3e831f237cd90795494f4d057，MIT；consolidator.py:73-171,_prioritize:330-346; episodic.py:consolidate_episodes:126; db.py:save_semantic_memory:471,recall:575,utility_feedback:675。SQLite idempotent multi-phase及utility feedback，Alpha，低中。
- salishforge/memforge@16e2f15c5881a38911f64ca81b3dc0b25d6207ec，MIT；sleep-cycle.ts:SleepCycleEngine.run:132+; memory-manager.ts:consolidate:1367,reflect:2208,sleepCycle:2490+。评分/冲突/revision/实体去重/反思/清理全周期；TS+Postgres/Redis高。
- Zijian-Ni/agent-memory@d38704818ae7e84a4e154cd79494af0742deba18，Apache-2.0；trace_mem/store.py:write_turn:195,_score_candidate:360,_persist_item:405; sufficiency.py:RedundancyProxyGate:84-99。admission candidate和trajectory；proxy非真正counterfactual value；低中。

M4裁决/移植：Codex phase2控制闭环为第一；OpenClaw host-side exact-match/lineage validator为第二；ReMe逐来源增量语义第三。将Codex状态机/Diff协议接到 origin/memory-w2-api 的 core/atlas/memory/library/dream.py:run_dream；以source_event_id+extractor_version推进每个来源，而非全局mtime。用OpenClaw proposal/host validator替换 dream.py:_write_project 模型直接生成整页内容，校验旧行仍精确匹配后原子apply；不匹配则保护用户编辑并入retry队列。Mastra借压缩与generation guard，Letta借隔离worktree，Jiuwen借写入后推进checkpoint。ReMe完整成本/Source已在原V4.1审查；未重查。M4无独立使用反馈，除agent-sleep有utility feedback。

## 透明记忆库

| 项目 | commit / 许可 | 关键源码 | 真源、重建、人工编辑、失败纠错、召回/反馈 | 成本 / 证据 |
|---|---|---|---|---|
| Basic Memory | a72751c5d626380dedeed30f55f7a80ba3dc710d (2026-10-15)；AGPL-3.0-or-later（核对LICENSE与pyproject.toml）；各integration另有LICENSE | note_content_writes.py:write_note:399,_accept_write:639; file_service.py:write_file:197; watch_service.py:handle_changes:301; note_content_reconciler.py:reconcile:313,apply_note_content_update_plan:202; search_service.py:reindex_all:298,search:433 | Markdown是可编辑文件真源的设计目标；该commit accepted write先落DB、再异步物化Markdown，DB暂时可能领先文件，reconcile需保护DB-ahead状态；watch/reconciler重读文件修复投影。locked仅限制API写入，直接编辑/删除文件不阻止或回滚。可读改；故障恢复未实测，无usage feedback | 中高，watcher/schema复杂；源码+文档。 |
| Codex official internal | rust-v0.162.1, 092d3acd6bec3e3a14bdc7e7a2810ab628ab759d；Apache-2.0；个人级files是另一层 | state/runtime/memories.rs:MemoryStore:31,record_stage1_output_usage:58; write/storage.rs:rebuild_raw_memories_file_from_memories:13,sync_rollout_summaries_from_memories:23; workspace.rs:prepare_memory_workspace:16,memory_workspace_diff:29,reset_memory_workspace_baseline:46 | 内部SQLite存stage1/job，Markdown产物为导出/重建；不要混称为唯一真源。baseline diff能传播用户改动；任务有retry/stale claim回收。个人文件可读，内部DB不透明 | 高；Git协议可借，Rust不移；源码已读。 |
| Claude Code files | 当前2.1.296闭源；细节来自2.1.88 sourcemap | memdir.ts:buildMemoryPrompt:272,buildMemoryLines:199-266; memoryScan.ts:scanMemoryFiles:35; findRelevantMemories.ts:39,77 | topic markdown+frontmatter，MEMORY.md索引；按任务检索。prompt管写/纠错，无事务保护；可见可改，错误恢复/feedback未证 | 行为参考成本低；闭源，版本有差。 |
| MemPalace | 9b0cebf66d9796214fe03e3992d98e5f579f1400 (2026-10-15)；根LICENSE | convo_miner.py:scan_convos:561,_split_new_and_duplicate_conversations:866,_is_unchanged_since_last_mine:892,mine_convos:939; dedup.py:dedup_source_group:98,dedup_palace:169 | 主库SQLite/vector和原文drawer，不是Markdown；可备份导出、从agent transcript重新mine；hash/source追踪与近重dry-run；语义+关键词召回，人改与反向同步未证 | 中高；源码抽样。 |
| Obsidian类（Smart Connections插件） | 3bfe2b259fda93d7935ffb5d530fc8e99ba90c34 (2026-10-10)；插件根LICENSE | main.js:SmartConnectionsPlugin:29,onload:55; connections_lists.js:211; connections_list_item_state.js:18,34,176 | Obsidian核心未公开；Vault Markdown可读改。插件过滤只隐藏候选、不阻止摄取；embedding/index在Smart Environment，没审。pin/hide提供召回反馈非事实纠错 | 插件低中；完整索引未知。 |
| sqliteai/sqlite-memory（新增） | 0f0aede814cf3c39b4e6226bdff87f2c65c8255d (2026-07-21)；根LICENSE.md | memory.go:AddFile:71,AddDirectory:89,Search:107,Delete:119,Reindex:163; watch.go:Trigger:35,Run:58,Allows:146 | Markdown真源、SQLite FTS/vector投影；hash skip、重索引、可编辑源、README写文件级失败回滚/重启worker | 低中；C事务核心未完整追，未跑。 |
| dankinsoid/ai-memory（新增） | 0d63fc13c1644161facca435bc69e310fb57f345 (2026-09-30)；无根LICENSE，不可复制代码 | db.py:index_file:186,remove_file:225,reindex:245; digest.py:build_digest_prompt:317,_consolidate_facts:451; content_store.py:upsert:72,search:133,delete:219 | markdown为SSOT是TODO声明；SQLite/embedding可重扫；facts由prompt合并。错误恢复/冲突保护未深读 | 中；许可缺失，行为仅参考。 |
| Smart Connections（新增候选） | 同上 | 插件候选列表pin/hide；同为Obsidian插件而不是完整memory backend | 可将用户操作当召回信号，不能证明事实源保护或重建 | 不作为重复的独立依赖建议。 |

透明库裁决：Markdown为唯一权威；数据库/FTS/vector是可再生投影。Basic Memory提供最清楚的file SSOT/reconcile边界，但其locked并不挡文件直接改动。Codex baseline diff与OpenClaw精确旧行校验合起来更适合保护用户编辑。MemPalace适合原文档案检索而不是透明SSOT；Smart Connections只证明候选反馈UI，不证明索引权威。

透明库移植：
- Basic Memory file SSOT/reconcile → core/atlas/memory/library/store.py:MemoryStore.read/write 与 index.py:MemoryIndex.sync/rebuild：保留Markdown唯一权威及索引可重建；增加内容hash/generation校验和启动reconcile；DB失效后从md重建，不反向覆盖md。
- Codex workspace diff + OpenClaw exact-match/lineage → 替换 store.py:MemoryStore.write无条件整页写入路径，并接 extract.py:apply、dream.py:_write_project：基线生成patch，应用前current text必须匹配old text；不匹配则保护手改并转冲突/重试。
- sqlite-memory借hash/reindex/文件隔离；Claude Code主题索引、Smart Connections pin/hide只供UX；不搬MemPalace数据库作为规范源。

## Claude骨架意见、Atlas映射和拍板

| Atlas位置 | 当前行为/用途 | 建议移植/替换 |
|---|---|---|
| core/atlas/memory/library/extract.py:SYSTEM_PROMPT:33-88,build_messages:158-179,apply:294-373 | 当前只接受用户原话said且quote须出现在user_text；同时抽episode | 移除“只认用户亲口说”，改为不同source等级的候选并附证据；保留secret scrub、临时状态、forget与事实键。 |
| core/atlas/memory/library/__init__.py:MemoryLibrary._drain:282-300,_extract_full:352-366,_apply:373-389; queue.py:TurnQueue.fail:72-75 | durable pending turn；失败attempts达3后不再进入pending | 加Codex lease/backoff与写成功后推进来源状态，永久失败可见/可重试，避免静默冻结。 |
| origin/memory-w2-api@aa14c3173392d0fc60ec3e401e4495a2d3357cb7:core/atlas/memory/library/dream.py:_checkpoint,_episode_groups,_write_project,_old_owner_lines,run_dream | W2全局时间checkpoint分组，dream写项目页 | 改逐source_event_id+extractor_version处理；以OpenClaw plan/host验证代替LLM整页改写；成功持久化后再推进每来源水位。 |
| core/atlas/memory/library/store.py:MemoryStore.write:270-275,commit:365-373; index.py:MemoryIndex.sync:123-150,rebuild:150 | Markdown+Git，SQLite可重建索引 | 加baseline diff、exact match和索引generation；Markdown单一SSOT。 |
| core/atlas/evolution/skill_sleep.py:run:111-143 | SkillOpt sleep设evolve_memory=False，技能学习与长期记忆分开 | M4不塞进skill sleep；可共享源输入但状态/产物分离。 |

不重做用户已经决定的架构原则。用户已授权且报告按此继续的选择：Markdown唯一真源；来源等级为用户陈述 > 工具观察 > 模型推断；三类证据都保留，较高等级裁决不删除低等级原始证据；视听/手机只留字段，不采集。Git history是审计/恢复，不替代来源级删除账本。实施需定义人工并发编辑的3-way merge/冲突队列、索引generation、删除tombstone及派生事实撤回。

## 新增候选与搜索词

- M3：A-MEM agiresearch/A-mem，Graphiti getzep/graphiti，Hindsight vectorize-io/hindsight。搜索：agent memory extraction memory consolidation; LLM memory dedup update; long-term memory agent source code; conversation memory fact extraction; agent memory retain recall reflect.
- M4：dream-cycle quinnmacro/dream-cycle，OpenDream pylit-ai/opendream，Jiuwen openJiuwen-ai/agent-memory，agent-sleep thevisionhub/agent-sleep，memforge salishforge/memforge，agent-memory Zijian-Ni/agent-memory。搜索：agent sleep time memory consolidation github; LLM dream memory merge source; agent memory consolidation checkpoint.
- 透明库：sqlite-memory sqliteai/sqlite-memory，ai-memory dankinsoid/ai-memory，Smart Connections brianpetro/obsidian-smart-connections。搜索：markdown source of truth AI memory sqlite github; agent memory filesystem watcher index; Obsidian memory plugin source code.

## 尚未查清

- MemOS主项目的完整 lifecycle/dreaming 未核；已读本机 D:\memos-src local-plugin 的L2/L3分层管线，不能把它等同主服务或夜间dream。
- Letta letta-code和部分Mastra来自GitHub源文件页面，没有本地完整HEAD；Claude Code长期memory为2.1.88 sourcemap，当前拆解为2.1.296，不能视为同版本。
- Mem0完整UPDATE/DELETE、Claude-Mem响应校验重试、LightMem冲突逻辑、Graphiti事务、Hindsight底层写入、MemPalace源修改后delete/re-mine、Basic双写恢复未做运行验证。
- 未运行测试/项目或性能评测，不引用跑分；许可证行是根许可或注明的子树，未逐个审所有依赖许可证。
- D: 当前可用空间显示0 bytes，但本结果文件已成功写入指定工作树；提交与推送前仍需确认Git对象写入可用。

LANE A DONE

## 审查意见（R，2026-10-16）

抽查依据：A 线报告所列 pinned commits 与官方拆解源码；以下为逐函数复核及需收窄的移植边界。

1. **Basic Memory 许可证更正**：A 表将 `basic-memory@a72751c5d626380dedeed30f55f7a80ba3dc710d` 标成 Apache-2.0 不实。该提交根 `LICENSE` 与 `pyproject.toml:7` 标 AGPL-3.0-or-later；`integrations/openclaw/LICENSE` 才是 MIT，Hermes/Pi integration 仍为 AGPLv3，不能覆盖 core。不得按 Apache 代码源安排 core 复制；本裁决只将其作为行为参考，或采用另有许可的实现，许可选择留待用户确认。
2. **Mem0 幂等范围收窄**：`mem0/memory/main.py:_add_to_vector_store` 在 921-954 用同 scope 的已有记忆构造上下文，但 928-933 只取 `top_k=10`，1008-1024 的 hash 去重只覆盖召回结果和当前 batch，并非全 scope 持久唯一性。可借 ADD-only 提炼；Atlas 若需全局幂等，须以来源事件/抽取版本唯一键实现。
3. **Mem0 水位语义区分**：1052-1098 仅成功写入的记录进入 ADD mutation history；但 984-991 解析失败仍保存消息，1072-1076 全部向量插入失败时也先 `save_messages` 再抛错。应区分消息上下文缓存与已提交记忆水位，不能宣称所有失败都不消费来源。
4. **Basic Memory 的 accepted write 不是纯投影协议**：`note_content_writes.py:_accept_write:679-702` 以 DB 最新接受内容为基础；`note_content_materialization.py:materialize_write_change:699-717` 显示 accepted state 可先进入 DB、Markdown 后异步物化；`note_content_reconciliation.py:plan_existing_note_content_reconciliation:231-273` 防止旧文件观察覆盖 DB ahead 版本。Markdown 单一真源是 Atlas 已定方向，但应明确这是 Atlas 的协议决定，不可称为直接复刻该提交顺序。
5. **locked 边界补充**：API mutation runner 可拒绝 locked note，但 `docs/LOCKED_NOTES.md:24-32` 说明直接文件编辑/删除与 import 可绕开。若 Atlas 保护手改，必须在文件应用/索引重建边界做内容版本校验，不能只加 API 锁。
6. **Codex Phase 2 水位条件补全**：`phase2.rs:run:122-151` 支持“无 diff 且产物有效”捷径；有 diff 的成功路径在 `agent::handle:406-465`，还要求 agent 完成、产物有效、持有 lease 且 baseline reset 成功。验收协议要覆盖两条路径。
7. **OpenClaw 保护手改证据增强**：除 `applyMemoryConsolidationPlan` 精确旧行/lineage 校验外，`short-term-promotion-apply.ts:440-474` 会在模型运行后重读文件并比较 fingerprint/base hash。Atlas 任务应移植 host-side re-read + generation/hash guard；字符串 validator 单独不足以保护并发编辑。
8. **覆盖缺口**：任务书候选要求 M3 检查 memU；A 正文没有 memU 的函数证据或明确未查清声明。Letta/OpenClaw 的相关行转入 M4 也没有完整回答 M3 提炼机制。裁决不将这些项目作为 M3 已核实胜者，后续施工须先补证据或按本任务书规定的 Atlas 输入契约实现。

核验数：10 组函数行为；未运行候选项目/测试。上述意见由 R 直接补入，无需等待源对话修改。
