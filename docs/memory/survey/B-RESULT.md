# B 线结果：读取召回、变化事实与联想

调研日期：2026-10-16。范围：M5、M7、M9。仅调研，未改 Atlas 源码、未运行测试。项目 SHA 均指本轮核对的 pinned commit 或 shallow clone HEAD；提交日期用于判断新增候选在近一年是否活跃，不采用项目自报跑分。许可证同时扫描根目录及源码相关子目录；表中只列对本次所查路径有意义的许可证，不能据此覆盖仓库其他目录。

## M5 读取与召回

### 对比表

| 项目 | Commit | 关键文件:函数:行 | 做法 / 强项 | 弱项 / 证据边界 | 许可 | 移植成本 | 证据 |
|---|---|---|---|---|---|---|---|
| Codex memories | `092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`（官方拆解 tag `rust-v0.162.1`, 2026-10-09） | `codex-rs/ext/memories/templates/memories/read_path.md:21-46,75-113`; `codex-rs/memories/read/src/citations.rs:6-70`; `memories/read/src/usage.rs:30-64`; `core/src/memory_usage.rs:9-30`; `state/src/runtime/memories.rs:58-88,400-430,453-486` | 从 registry 定向读少量 rollout/skill；引用含文件行号、rollout ID；解析引用并去重，持久化 usage_count/last_usage，据近期使用做选择和淘汰。长处是读取有出处且反馈能进入后续选择。 | citations 由模型生成，解析会丢坏行但不验证 path/行号；不提供检索引擎，写入纠错属于其他流程。 | Apache-2.0；相关 memories/read/state 路径无独立许可。 | 低中；移植读取契约、引用和使用反馈，接 Atlas 搜索层/存储。 | 源码；用本机官方拆解 pinned tag。 |
| Hindsight（既有核验） | `9a499b1759084a86598eff8af30ed59f7354e76c`（2026-10-15） | `hindsight-api-slim/hindsight_api/engine/search/fusion.py:29 reciprocal_rank_fusion`（任务书已核验） | 多路候选 rank 融合；只复用已核的 fusion 结论。 | 本轮没有重查融合实现和完整读写/失败/反馈链，不能视为完整复审。 | MIT；所查 search 路径无子许可，其他 integrations 需逐目录看。 | Python；引擎依赖较多，本轮不作整库移植评估。 | 既有源码核验，本轮只核 SHA/许可。 |
| MemOS（既有核验） | `a7367d07e55db61099f7b4e2c1108bc5831a24f3`（2026-09-22） | `apps/memos-local-plugin/core/retrieval/retrieve.ts:97-124 turnStartRetrieve,238+ runAll`（任务书既有核验） | 复用已核验 retrieval 结论，不重做整条链。 | TS 插件路径不是独立 Python 检索器；本轮未重查完整写入、失败或反馈链。 | Apache-2.0；所查 retrieval 目录无独立许可。 | 中；需要将接口/策略适配到 Atlas Python。 | 既有源码核验，本轮只核 SHA/许可。 |
| Claude-Mem | `b8fc2ef9bab0dd1438d6cc8699c6884445ad409b`（2026-10-15） | `src/shared/progressive-search.ts:214-367 ProgressiveSearch.run`; `src/services/worker/search/SearchOrchestrator.ts:94-143,145+`; `src/services/worker/http/routes/SearchRoutes.ts:237-245` | 三层渐进式读取：紧凑 ID/title 索引、时间邻居、批量详情；guided/auto，可做一次 query refinement；continuation 有 HMAC scope、TTL、大小限制；语义搜索失败可退回 SQLite FTS。 | 检索主要更新短期状态/telemetry，不见有用性反馈排名；检索不直接写长期记忆。 | Apache-2.0；`src/` 无独立许可；dsh、ragtime 等其他子树有各自许可。 | 中高；协议可借，TS、SQLite、Chroma/embedding 整体适配较重。 | 源码。 |
| Basic Memory | `a72751c5d626380dedeed30f55f7a80ba3dc710d`（2026-10-15） | `src/basic_memory/schemas/search.py:26-31`; `services/search_service.py:433-493`; `repository/search_reader.py:1068-1108,1383-1467,1589-1640`; `repository/search_trace.py:232+` | Markdown 真源 + SQLite FTS/vector 同步索引；hybrid 多路候选融合；严格 AND 无结果可退到 relaxed OR；trace 能看候选及过滤阶段，返回 permalink。 | 搜索不写记忆，未见采用/有用反馈；AGPL 对直接移植有影响。 | 根 AGPL-3.0-or-later，`src/basic_memory/` 无单独许可；Pi/Hermes/OpenClaw 集成目录有各自许可。 | 低中；Python + SQLite/FTS/vector，需自行承接透明编辑和索引同步。 | 源码。 |
| OpenClaw memory-core | `59cb44796b0f1f0daa0e37af8b1495abb45d9bc1`（tag `v2026.10.3`, 2026-10-03） | `extensions/memory-core/src/memory/manager-search-orchestration.ts:453-602`; `memory/hybrid.ts:56-249 mergeHybridResults`; `temporal-decay.ts:15-25,110-153`; `mmr.ts:28-91`; `memory-search-tool-query.ts:122-165` | 合并 keyword/vector 候选，按 ID、加权分、项目/重要性排序；提供指数时间衰减和 token Jaccard MMR 多样化；查询保留 partial/fallback。 | temporal decay 与 MMR 默认关闭，相关旧配置已 retired；不能把它们说成当前启用默认值。 | MIT；`memory-core` 无独立许可。 | 中；算法可以翻译到 Python，整体 TS/SQLite/vector/FTS 不宜直接搬。 | 源码。 |
| Mem0 | `0724291bd864cf807e88ee8981c8226644e8fb42`（2026-10-14） | `mem0/memory/main.py:1393-1536 Memory.search`; `:1642-1745 _search_vector_store`; `:1007-1076`; `configs/prompts.py:480-533 ADDITIVE_EXTRACTION_PROMPT` | 语义 overfetch + BM25 + lemma/entity boost + 过期过滤；可 rerank，失败退回原排序；ADD prompt 把 existing memories 用于去重/链接而不重新抽取；批次失败可逐项降级。 | OSS search 未见 memory 级 use-feedback；云 API feedback 与 OSS 搜索分离。配置/集成须逐路径核许可。 | Apache-2.0；本次所查 memory/config 与相关 skill 为 Apache-2.0。 | 低中（算法）；整套依赖 LLM、embedding、reranker 和多种向量后端，成本高。 | 源码。 |
| Supermemory | `ccf048586919b7a555c117c439ec327386237b35`（2026-10-15） | `apps/mcp/src/server/tools/search-memory.ts:13-68`; `get-profile.ts:13-67`; `forget-memory.ts:41-118` | MCP 只调用远端 `client.search` 并回文本/ID/相似度；profile 暴露静态/动态信息；forget 要 exact text 或显式 ID。 | 公开仓库是 SaaS client/API façade，不含后端搜索算法；未见使用反馈或直接编辑。 | 根 MIT；`packages/tools/LICENSE` Apache-2.0；`skills/supermemory/LICENSE` Apache-2.0。 | API/删除确认 UX 可参考；算法不可核、不可源码移植。 | 源码，但仅客户端。 |
| Cognee | `f154b32a9e544dac73e7ddf2010327cf9988edcd`（2026-10-13） | `cognee/api/v1/add/add.py:40`; `cognify.py:112`; `tasks/storage/add_data_points.py:70,126`; `modules/retrieval/hybrid_retriever.py:131,137,168-187,280-316`; `temporal_hybrid_retriever.py:60,98,122` | 并行取 chunk/entity/fact 候选并保 provenance；有时间锚点扩展上下文，temporal conflict resolver 标记旧边 superseded。 | 图/向量/关系服务带来较高整合成本；用户可见可改、召回 retry、use-feedback 未从所查源码确认。异常处理只是 warning 的路径不保证原子纠错。 | Apache-2.0；扫描到根许可，`licenses/README.md` 指向第三方许可目录。 | 高；适合借 hybrid/time/provenance 契约，不整库接入。 | 源码。 |
| Zep | `3997767fccf83bbea7b54ad5f73554f2e5bcd54e`（2026-10-14） | `ingestion/src/zep_ingest/pipeline.py:70,103`; `verify.py:33 search_when_ready`; `integrations/adk/python/src/zep_adk/memory_service.py:67,145`; `mcp/zep-mcp-server/internal/handlers/search.go:15` | 此 public checkout 可证实的是 SDK/ingestion 与 MCP/API adapter：索引未就绪会等/重试，按页提交，API 传 scope/reranker/MMR/filter。 | 仓库没有托管服务核心，不能据此断言其服务端搜索或时间冲突算法；adapter 的边界要与服务器实现分开。 | Apache-2.0；`ingestion/` 与 `mcp/zep-mcp-server/` 也为 Apache-2.0。 | 高/不可准确估算；可用 Python API adapter，服务内部不可搬。 | 源码，范围限 SDK/adapter。 |
| OpenViking | `119eba57db8a2fe7d5c8b7bb400d2e2b032a6825`（2026-10-16） | `openviking/service/search_service.py:114 SearchService.search`; `server/routers/search.py:478,549`; `retrieve/hierarchical_retriever.py:92,258-370`; `context_assembler/gather.py:170,205`; `tiers.py:193,205,219`; `memory_lifecycle.py:18 hotness_score` | 层级读取、候选去重、分层替代和 hotness 信号；适合观察资源预算与按需下钻。 | D 盘目标 clone 因空间不足失败，改在 C 盘独立浅克隆；本轮未完整跟读 gather→budget→render 与生命周期重试/用户编辑/采用反馈。只按“看思路”证据使用。 | 根 AGPL-3.0；`bot/license/LICENSE` MIT、`crates/LICENSE` 与 `examples/LICENSE` Apache-2.0，须按实际拷贝路径裁定。 | 中高；层级调度思路可借，完整 Rust/Python/service 引入高成本且许可需审。 | 部分源码。 |
| mnemostack（新增） | `1d8dc160c06276b49c598e29cef3efbaf17d2559`（2026-09-28） | `src/mnemostack/recall/flow.py:22`; `recall/retry.py:101,421,464+`; `feedback.py:121 apply_feedback`; `access.py:177-200` | 一个 recall pipeline 处理 rerank/token budget；弱召回时 bounded reformulation 最多一轮且不放宽 tenant/filter/validity；按统一 key 去重；clicked/reward 有 Q-learning/IoR 反馈，access 统计失败 fail-open。 | 依赖 Qdrant/可选 reranker；没有透明编辑 UI。 | Apache-2.0；`src/` 无独立许可。 | 中；Python 召回流程可抽取，需适配存储。 | 源码；HEAD 日期为近一年。 |
| Engram（新增） | `c8708c5aa78ed42a97759296be37eab74667780a`（2026-10-14） | `engram/retrieval.py:12 recall`; `engram/core.py:296`; `engram/store.py:311 log_access,1112 search_episodes_hybrid` | SQLite + sqlite-vec + FTS5；BM25/cosine hybrid，可 graph spreading；支持 agent/as_of 约束并记访问。 | 无召回 retry 或明确采纳反馈；access/importance 不是“有用”证据。CLI 可 inspect/forget，未见直观编辑 UI。 | Apache-2.0；`engram/` 无独立许可。 | 低中；Python 本地库，须适配 Atlas schema/sqlite-vec。 | 源码；HEAD 日期为近一年。 |

### 第 3 节字段补充核对

| 项目 | 存储 / 写入 | 失败、去重纠错 | 用户可读改 / 是否用上反馈 |
|---|---|---|---|
| Codex | 文件记忆 + SQLite 使用统计；本次检查的写入仅为引用后的 `usage_count/last_usage`。 | citation/rollout ID 去重；坏引用行丢弃；读取 retry 与内容纠错未核。 | 文件可读改；按引用/读取统计排序，不代表回答质量反馈。 |
| Hindsight / MemOS | 未核查；本轮只引用已有 fusion / retrieve 结论。 | 未核查。 | 未核查。 |
| Claude-Mem | SQLite observation/summary + Chroma 向量索引；渐进搜索写 continuation/临时 telemetry，不是长期记忆写入。 | 搜索可从语义 lane 降到 SQLite FTS；未核自动重试；ID/kind/project 有校验。 | 有 viewer/API 查询，长期编辑入口未核；无被采用反馈排序。 |
| Basic Memory | Markdown 是可编辑真源，SQLite FTS/vector 索引同步；写入/索引触发未在 search 路径检查。 | strict AND 无命中可 relaxed fallback；其他 retry 未核；用户改 Markdown 可纠错。 | Markdown 可看改、有 permalink；trace 记录候选过滤，不是采用反馈。 |
| OpenClaw | 本轮只查召回插件，写入链未核。 | partial/fallback；混合结果按 ID 合并；内容纠错与 retry 未核。 | 查看/编辑入口和使用反馈未核。 |
| Mem0 | 可插拔向量库存 payload，SQLite 存历史；ADD 路径分阶段读新消息、抽取新增记忆。 | 语义近重复 + hash；显式 update/delete 留 history，批次失败逐项降级，rerank 失败回原序。 | 有 get/list/update/delete API，无透明 Markdown 真源；OSS 未见 memory-level use feedback。 |
| Supermemory | 公开仓库不含后端存储；MCP add 委托远端服务。 | client 有请求重试配置，但服务端幂等/纠错未核；后端去重未知。 | 可看搜索结果，forget 需 exact text/ID；无公开 use-feedback 证据。 |
| Cognee | add 保存输入，cognify 建图；图/向量/关系型后端存数据与 provenance。 | 节点/边 ID 去重；同内容重加 no-op，内容改动显式 update；pipeline 有恢复处理，resolver 异常 warning。 | 有 provenance API/可视化；memify 可异步将 session used IDs/rating 写到反馈权重。 |
| Zep | 当前 clone 无 hosted backend；SDK/adapter 提交 ingestion。 | SDK 预检、批次继续、索引延迟轮询；服务端纠错/幂等未知。 | 服务端查看修改和使用反馈未知。 |
| OpenViking | URI/文件资源；可见 memory compile/update/upsert/delete，完整落盘语义未核完。 | gather lane fail-open；同 URI 保留高分候选；其他写 retry 未核。 | Agent 有 read/search/list；完整用户编辑器未证明；有 hotness 统计但未发现召回递增与排名使用证据。 |
| mnemostack | 插件化 store（本次所查以 Qdrant 为主）；写入链未核。 | 最多一轮有约束 query reformulation；按 memory key 去重；访问统计失败 fail-open。 | 透明编辑 UI 未见；clicked/reward 有 Q-learning/IoR 反馈。 |
| Engram | SQLite + sqlite-vec + FTS5；observe 写入，召回时记 access。 | 本轮未见自动 retry/内容去重纠错。 | CLI inspect/forget；有访问统计，无明确采用反馈。 |
| MemForge | PostgreSQL/pgvector/FTS；`add` 写入。 | retry、内容纠错未核；RRF candidate merge。 | dashboard/API 管理，具体编辑 UX 未核；有 feedback API，排序效果未核。 |

### 裁决

**最强：Codex 的按需读取 + 引用使用反馈。** 强在从短 registry 钻到具体原文的分步读取、引用去重，以及把引用使用统计写回下一轮选择/淘汰；它不替代 Atlas 的实际检索引擎。**第二：mnemostack 的受约束弱召回重试与显式反馈**，强在重写查询时不扩张 scope/tenant/时间过滤，并把点击/reward 纳入排序。Atlas 的检索层适合保留 W2 的多路候选，吸收两者的读取契约、失败 retry、引用和使用反馈；OpenClaw 的 decay/MMR 作为可选实验机制，不作为默认要求。

### 移植清单

- `codex@092d3acd:read_path.md + citations.rs + usage.rs + runtime/memories.rs → core/atlas/memory/library/__init__.py:MemoryLibrary.recall/_relevant_block/search`：保留短总览→定向检索→原文下钻、引用格式/校验、ref usage 统计；改为 Atlas 的 Markdown entry IDs 和 SQLite 索引；丢掉 Codex rollout/Rust runtime 专属路径。Atlas 当前无引用使用计数。
- `mnemostack@1d8dc160:recall/retry.py + feedback.py → core/atlas/memory/library/index.py:MemoryIndex.search`：保留最多一次受约束 reformulation、候选 key 去重、clicked/reward/ignore 信号；改为本地 FTS/vector 适配，不引入 Qdrant（除非未来单独拍板）。
- `OpenClaw@59cb4479:hybrid.ts + temporal-decay.ts + mmr.ts → origin/memory-w2-api:core/atlas/memory/library/hybrid.py:temporal_decay/merge_scores/mmr_select; origin/memory-w2-api:core/atlas/memory/library/index.py:MemoryIndex.search`：保留可选排序组件；改默认关闭并明确权重/窗口，丢掉 TS runtime。该 W2 代码不在当前 `memory-survey` 基线上。
- `Claude-Mem@b8fc2ef9:progressive-search.ts → MemoryLibrary._relevant_block/search`：可保留逐层返回、cursor/byte budget 概念；不移植 Chroma/TS 状态机整套。
- `BasicMemory@a72751c5:search_reader.py + search_service.py → MemoryIndex.search + MemoryStore.read`：保留 FTS/向量候选互补、relaxed query fallback、trace；先裁定 AGPL-3.0 是否可接受，或只实现兼容机制而不复用代码。
- `Cognee@f154b32a:hybrid_retriever.py → MemoryIndex.search`：可保留多 lane provenance 和时间窗；拒绝其服务端适配器与完整 graph stack。

### 对 Claude 骨架假设的意见

**支持但要补强。** 常驻短总览、模型按需检索、引用和 Markdown 可见可改，方向成立；“4–6 步”应由 token/任务预算控制，而不是固定深度。补上引用解析验证、召回未命中时受约束重试、使用/忽略反馈和过滤不变约束。不能将 OpenClaw 的 temporal decay/MMR 当作默认已启用机制。

### 还没查清

Hindsight 和 MemOS 仅引用既有已核结论；Zep public clone 不含服务端算法；Supermemory 后端不开源；Cognee 的重试、用户编辑和 use-feedback 未确认；OpenViking 本轮未走完全部层级装配；搜索结果是否被模型采纳仍没有跨候选统一证据。MemForge 的 feedback API 是否真正改变 recall ranking 未继续追调用链。

## M7 会变的事实

### 对比表

| 项目 | Commit | 关键文件:函数:行 | 做法 / 强项 | 弱项 / 证据边界 | 许可 | 移植成本 | 证据 |
|---|---|---|---|---|---|---|---|
| Graphiti | `d50741d1bf463cbe3859eb73914cbff1b66839e6`（2026-10-15） | `graphiti_core/utils/maintenance/edge_operations.py:786-832 _extract_edge_timestamps,834-861 resolve_extracted_edge,864-1010 _dedupe_extracted_edge`; `temporal_edge_utils.py:39-96`; `graphiti_core/edges.py:271+ EntityEdge` | 图边存 valid_at/invalid_at（现实事实有效时间）与 created_at/expired_at（系统记录时间）；抽取后 canonicalize/dedupe，再令冲突旧边失效而留历史。未来事实边界钳制到 reference time；模糊截止词不误当失效时间。 | 需要图数据库、async LLM/embedder driver；完整图栈很重，异常并非全被吞掉。 | Apache-2.0，根许可适用所查路径。 | 高；移植时间字段、冲突规则，不能直接移 Neo4j/FalkorDB 等。 | 源码。 |
| Zep | `3997767fccf83bbea7b54ad5f73554f2e5bcd54e`（2026-10-14） | 当前 public `getzep/zep` checkout 只有 SDK/integrations/MCP，未发现服务端 temporal graph core；`ingestion/src/zep_ingest/pipeline.py:70,103`; `verify.py:33 search_when_ready` | 可见 ingestion replay 与索引等待 retry；真实服务事实冲突和失效规则无法在此仓库验证。 | 不以 Graphiti 替代 Zep 自身证据；服务端持久化/更正/删除未核。 | 根 Apache-2.0；`ingestion/`、`mcp/zep-mcp-server/` Apache-2.0。 | 高/无法精确估算；仅可证实 API 接入。 | 源码（只限 adapter）。 |
| Mem0 | `0724291bd864cf807e88ee8981c8226644e8fb42`（2026-10-14） | `mem0/memory/main.py:1829-1902 Memory.update/delete,2052-2142 _update_memory/_delete_memory`; `configs/prompts.py:176-290 DEFAULT_UPDATE_MEMORY_PROMPT`; `mem0/memory/storage.py:150-192 SQLiteManager.add_history` | LLM 产出 ADD/UPDATE/DELETE/NONE，更新保留 memory ID、改 updated_at 并留 old/new 操作历史；DELETE 从 vector store 移除并记录 deleted history、清 entity links。 | 这是修改审计，不是双时间事实：更新覆盖当前向量事实，删除实体记录；异常可能上抛。 | Apache-2.0；所查 memory/config 为 Apache，其他 integration 有独立许可。 | 中；可借本地历史事件模型，忽略向量/entity store。 | 源码。 |
| Memobase | `358c16bbc6d687937d79bc2f984a11c3be8da901`（2026-01-11） | `prompts/extract_profile.py:45-105 FACT_RETRIEVAL_PROMPT`; `controllers/profile.py:150-184 update_user_profiles,226-315 add_update_delete_user_profiles` | 提示显式区分 mention time 与 event occurrence time，要求时间敏感信息推具体日期；后端批次事务覆写 profile 内容，失败 rollback/reject。 | prompt 的双时间要求没有在所查 profile row 持久化为双时间版本；profile 路径会覆盖/物理删除，历史透明度弱。 | Apache-2.0，根许可适用所查路径。 | 中；抽取规则可译，Postgres/Redis 服务不宜整库搬。 | 源码。 |
| Supermemory | `ccf048586919b7a555c117c439ec327386237b35`（2026-10-15） | `packages/validation/schemas.ts:242-263 MemoryEntrySchema`; `packages/memory-graph/src/canvas/version-chain.ts:17-104`; `packages/tools/src/tools-shared.ts:134-167 forgetMemory` | schema 有 version/isLatest/parent/root/sourceCount/forgotten；canvas 重建版本链、处理缺序号，forget 有语义 preview 与 ID 删除。 | 所见版本链是客户端投影/推断，服务端如何生成与持久化版本未核；不能认定为权威版控规则。 | 根 MIT；`skills/supermemory` 与若干 SDK 子目录 Apache-2.0。 | 中高；可借 parent/root/version schema，不能搬服务。 | 源码（客户端和 schema）。 |
| Letta server | `5bcdd177d70fa2b31a754cfcd801e77b2e1ab16a`（2026-09-10） | 该 checkout 仅 root 文件/README，未含 server 的 memory block CRUD；另查 `letta-ai/letta-code@1297870b0aa6662d6c70729d273f5073c1bcbdea`：`src/agent/memory-git.ts:1234 commitMemoryWrite,1837 syncPendingMemoryCommitsAfterTurn,1905 invalidPendingMemory` | Letta Code 将编辑的本地 MemFS 文件按 pathspec commit，校验 pending writes，post-turn 同步；Git history 便于用户审计/改写。 | Letta Code 不等于 Letta server 的 block API；该仓未能在 D 盘 clone，按固定 GitHub SHA 源码验证。 | 两仓 Apache-2.0。 | 对 Atlas 既有 Markdown+git 为低；server block CRUD 未评估。 | 源码；Letta Code 为 GitHub 固定 commit。 |
| Codex | `a45b8ccb016fb74f63a6bc29e701568e387cbe38`（2026-10-16） | `codex-rs/state/src/runtime/memories.rs:301-348 delete_thread_memory,400-429 prune_stage1_outputs_for_retention,444-493 get_phase2_input_selection`; `codex-rs/config/src/types.rs:60 DEFAULT_MEMORIES_MAX_UNUSED_DAYS`; `memory_versions.rs:39-51` | 删除 thread 会清 V1 和已建 V2；若 stage1 记录进入 phase2，事务入队 global consolidation 后续传播。prune 只删未选入 phase2 的阶段产物，按使用/来源时间与 cutoff 处理。 | 不是用户事实有效期；派生记忆只能靠后续整合传播删除。源码默认 max_unused_days=30 天，不应当作事实失效时间或直接复制为 Atlas retention policy。 | Apache-2.0；相关记忆目录根许可；仓库 vendor 有其他许可。 | 中；SQL 语义易借，需接 Atlas source→derived provenance 与 tombstone。 | 源码。 |
| LangMem（新增） | `48e3c11f5bb527282c7d5339c6a87a0b35abccfc`（2026-10-02） | `src/langmem/knowledge/extraction.py:941-975 _apply_manager_output,1102-1135 ainvoke,1666-1686 create_memory_store_manager`; `knowledge/tools.py:25-40,271-303` | manager 以 namespace/key 稳定 ID 写回同一 store key，删除时 `adelete`；有相关记忆语义更新。 | 注释称 versioned history，但源码只覆盖同 key，没有归档旧值/历史时间；不能按版本化机制引用。 | MIT，根许可适用所查路径。 | 低中；Python glue 可借写入语义，需自行增加历史。 | 源码。 |
| Cognee（新增） | `f154b32a9e544dac73e7ddf2010327cf9988edcd`（2026-10-13） | `tasks/graph/resolve_temporal_contradictions.py:60-106 resolve_temporal_contradictions`; `tasks/storage/close_node.py`; `api/v1/add/add.py:40` | functional/single-valued 关系冲突时给旧边写 superseded/superseded_by/reason，留 provenance 不物理删；close_node 为旧版本写 valid_to。 | adapter/backend 事务细节未全查，异常/并发保障不明；依赖图存储。 | Apache-2.0，所查源码根许可。 | 高；借 supersedes/provenance/valid_to 语义。 | 源码。 |
| Hindsight（新增） | `9a499b1759084a86598eff8af30ed59f7354e76c`（2026-10-15） | `hindsight-api-slim/hindsight_api/engine/retain/orchestrator.py:980-1267 _streaming_store_owned_retain` | 文档 chunk 有变化/删除时先找 delta、清派生 observations，再 scoped replace/tombstone，针对过时观察仍被召回做清理。 | PG retain 底层事务/tombstone 本轮未追到；依赖 Postgres/pgvector/图/LLM。 | MIT；所查 engine 路径无独立许可，其他 integrations 有子许可。 | 高；只借 source→derived invalidation 清单。 | 源码。 |

### 第 3 节字段补充核对

| 项目 | 存储 / 写入 | 失败、去重纠错 | 用户可读改 / 使用反馈 |
|---|---|---|---|
| Graphiti | graph edge 存事实与两套时间；`add_episode` 触发抽取并写图。 | 时间解析异常可 warn/保留已有边界；抽取后 canonicalize/dedupe 和 invalidate 旧边；完整事务 retry 未核。 | UI 人工浏览/修改、事实采用反馈未核。 |
| Zep | 当前公开仓仅 SDK/adapter，无 hosted store 证据。 | SDK 有预检/分批和索引等待；服务端纠错/retry 未核。 | 服务端用户编辑和使用反馈未核。 |
| Mem0 | vector store 保存当前文本，SQLite history 保存旧/新操作记录。 | UPDATE 同 ID 覆盖并更新时间；DELETE 删向量、保操作历史、清 entity links；错误可能上抛，不是双时间。 | 有 API update/delete；无透明 Markdown 真源；更新/删除是操作审计，不是召回采用反馈。 |
| Memobase | Postgres profile row 保存汇总字符串/attrs。 | add/update/delete 批次事务，失败 rollback；对同 profile 覆写/删除，没有版本历史证据。 | API 能更新/删；直接编辑透明度和采用反馈未核。 |
| Supermemory | 公开 schema/UI 读取版本链投影；权威存储在远端 API。 | version-chain UI 可按 parent/root 排链并推算版本；forget API 报告失败；真实服务端版本写入/纠错未核。 | 可追版本链和执行 forget；不是 Markdown 原文编辑；采用反馈未核。 |
| Letta / Letta Code | server checkout 不含核心；Letta Code MemFS 本地 git 文件按 pathspec commit。 | pending write 会校验；dirty/conflict/invalid 被分类，不 silent；重试由 post-turn sync 流程提示，非已证明自动成功。 | 本地 git 文件可看/改历史；使用反馈未核。 |
| Codex | runtime SQLite 记录 thread/stage1/stage2 memory 与使用统计。 | 删除 thread 后事务清相关 V1/V2；入选过的产物排队 consolidation；默认 30 天 prune 未入选 stage1。 | 文件/数据库可核查；usage_count/last_usage 是被引用信号，不是回答正确性。 |
| LangMem | BaseStore 按 namespace/key 存当前值。 | 同 key 覆盖、delete 移除；注释提 versioned history，但实现未保存历史；失败重试未核。 | store API 可读取/写入；直接用户编辑体验与采用反馈未核。 |
| Cognee | dataset + graph/向量后端保存输入、实体、事实和 provenance。 | 同内容 add no-op，不同内容需 update；冲突边标 superseded；resolver 异常 warning；完整并发/事务恢复未全核。 | provenance API/可视化；图值可查但不是透明 Markdown 真源；M9 专用采用反馈未核。 |
| Hindsight | Postgres/pgvector 与派生 observations。 | orchestrator 发现变更/删除 chunk 后清派生观察并替换；底层原子性、失败重试未核。 | 本轮未核用户直接编辑和召回采用反馈。 |

### 裁决

**最强：Graphiti 的双时间边 + 旧边失效而保留历史。** 强在同时表示“事实何时对现实有效”和“系统何时记录/失效”，并为未来/模糊时间做归一化；这比简单覆盖或只记 `until` 更能解释矛盾。**第二：Hindsight 的源文档变化向派生观察传播**，强在把删除/替换当成需要清理下游派生事实的事件。实际施工建议组合两者的细节，不复制图服务：Atlas 每条当前 claim 保持可编辑文件，历史 claim 记 `superseded_by`、`valid_from/to`、`recorded_at/retracted_at` 和来源 ID；删除时沿 source/provenance 撤销衍生项和索引。

### 移植清单

- `Graphiti@d50741d1:edge_operations.py:_extract_edge_timestamps/_dedupe_extracted_edge/resolve_extracted_edge + temporal_edge_utils.py → core/atlas/memory/library/store.py:Entry, Page; extract.py:known_facts/apply/expire`：保留事实有效时间与系统记录时间分离、冲突保留旧值并建立 supersedes；改为 Markdown metadata/SQLite 可查询字段；丢弃 graph driver、LLM 时间抽取服务；替换仅靠 `at/until` 表达的时态字段，而不是全量换库。
- `Mem0@0724291b:Memory.update/delete + add_history → extract.py:apply/apply_episode + MemoryStore.write`：保留可审计 old/new/delete 事件；改成不硬删当前证据，构建历史版本和用户纠正优先级；不复制 vector DB。
- `Codex@a45b8ccb:delete_thread_memory/prune_stage1_outputs_for_retention → memory/library/forget.py:purge_history + __init__.py:forget_entry/_purge`：保留删除触发派生层清理/重整合及未用产物淘汰；按 Atlas provenance 做具体传播，不能照抄 Codex 的 retention 天数。
- `Hindsight@9a499b17:_streaming_store_owned_retain → extract.py:apply/expire + forget.py:purge_history + index.py:sync`：保留 source delta 清理观察、派生条目标记失效、重建索引；以源 ID/派生 ID 查询影响面，增加可审计变更日志。
- `Cognee@f154b32a:resolve_temporal_contradictions/close_node → extract.py:apply`：可借 superseded reason 和 provenance；拒绝引入图服务。
- `Letta Code@1297870b:memory-git.ts:commitMemoryWrite/syncPendingMemoryCommitsAfterTurn → MemoryStore.write/commit`：Atlas 已 Markdown+git，可保留 git 审计和人工编辑保护；不能将本地 MemFS 等同于 server memory block 版控。

### 对 Claude 骨架假设的意见

**修改。** 保留来源等级与人工纠正优先，但“在已有 fact 加 `until` 就够”不足以处理事实改变。补 `valid_from/valid_to` 与 `recorded_at/retracted_at`（或同义的双时间）、`supersedes/superseded_by` 及源/派生引用；删除/纠正必须传到手册、索引和引用它的派生内容。保留 Markdown+git 为可见层，不要求 Graphiti 图数据库。

### 还没查清

Zep public repo 无服务端核心；Letta server repo 无 memory block 实现；Supermemory 版本链持久化由 API 服务生成的方式未核；Hindsight PG 原子事务与 tombstone 底层尚未追；Graphiti 的全部异常/LLM失败事务和 UI 人工编辑体验没有逐路径审完。Codex 默认 30 天是未使用 stage1 产物的保留策略，不应映射为 Atlas 用户事实的失效时间。

## M9 联想

### 对比表

| 项目 | Commit | 关键文件:函数:行 | 做法 / 强项 | 弱项 / 证据边界 | 许可 | 移植成本 | 证据 |
|---|---|---|---|---|---|---|---|
| A-MEM | `ceffb860f0712bbae97b184d440df62bc910ca8d` | `agentic_memory/memory_system.py:233 add_note,288-310 find_related_memories,590 process_memory,679-720` | 向量找邻居，LLM 提议建立 `links`、增强或更新邻居；links 写进 Chroma metadata。 | `update_neighbor` 用结果序号当本地 insertion index，可能改错邻居；更新只改内存，等 consolidation 才同步 Chroma；未见带权图边。失败重试/全面纠错未核。 | MIT，根 LICENSE。 | Python 易接，但 Chroma/LLM 有依赖；只借审计提案，不原样自动更新。 | 源码。 |
| HippoRAG 2 | `d5c8329422e0a0b834a15874545cb6a74b4f9b26` | `src/hipporag/HippoRAG.py:499 index,704 retrieve,1179 add_fact_edges,1230 add_passage_edges,1278 add_synonymy_edges,2008 graph_search_with_fact_entities,2204 personalized_pagerank` | OpenIE 构建 passage/entity/fact 图；语义事实与段落作加权 PPR seeds 做多跳联想，PPR 有明确算法语义；无事实时有 DPR fallback。 | 依赖 LLM/OpenIE、embedding、图与向量组件；用户直改性差；除 chunk hash 外更多去重/纠错未核。 | MIT，根许可。 | 高；只移植 seed 加权和 PPR/小图扩展思想。 | 源码。 |
| Cognee | `f154b32a9e544dac73e7ddf2010327cf9988edcd` | `modules/retrieval/hybrid_retriever.py:57,114,137,200,246`; `hybrid/entities.py:33` | chunk/entity 向量 lanes + graph-derived fact/context；混合回填邻近 facts。 | 不是 PPR 图漫游；adapter/服务依赖较多；用户改、重试/纠错不在本次关联链核验范围。 | Apache-2.0；根许可，`licenses/README.md` 提示第三方许可。 | 高；可借双 lane 和事实邻接。 | 源码。 |
| Graphiti | `d50741d1bf463cbe3859eb73914cbff1b66839e6` | `graphiti_core/search/search.py:98 search,259 edge_search,473 node_search`; `search_utils.py:1793 node_distance_reranker` | 可指定中心节点/BFS origins，按 node/edge/community 做 hybrid search 与 graph-aware rerank。 | 搜索依赖 graph DB/async embedding/reranker；不是 PPR。 | Apache-2.0，根许可。 | 高；借 center/BFS query contract，不接图服务。 | 源码。 |
| Basic Memory | `a72751c5d626380dedeed30f55f7a80ba3dc710d` | `markdown/plugins.py:220 parse_relation_type,427+ relation_rule,445-465`; `markdown/entity_parser.py:175-194 parse`; `services/context_service.py:121 build_context,237 find_related,343+` | Markdown 原文声明 `[[...]]`/显式关系，解析为关系索引；`memory://` context 可限深度展开。关系可人工阅读/编辑且 DB 索引可重建。 | 不是 PPR 自动扩散；AGPL-3.0 核心许可需考虑。 | 根 AGPL-3.0；Hermes/Pi 集成 AGPL、OpenClaw integration MIT、fixture 有 Apache，复用 core 应按根 AGPL。 | 低中；关系格式适合抽取，注意 source-of-truth 与索引一致性。 | 源码。 |
| MemoryOS | `587ed7755c7aed179965792830ff1b5ad9a6fa92` | `memoryos-chromadb/mid_term.py:27 compute_segment_heat,97 add_session,190-275 insert_pages_into_session,279 search_sessions,329-340`; `memoryos.py:140-224` | `H=αN_visit+βL_interaction+γR_recency`，访问时更新热度；session/page 语义与关键词命中后热度影响提炼/保留。 | 热度是访问/时效/互动信号，不等于关系图或查询相关性；存储在 JSON/Chroma，不透明度较高。 | Apache-2.0，根许可。 | 中高；只借访问热度/晋升信号。 | 源码。 |
| neo4j-labs/agent-memory（新增） | `4866fdc917f61899efcfd7fdebe459cbc2a02450`（2026-10-07） | `memory/long_term.py:652 add,663 add_entity,725+ _check_for_duplicates`; `graph/queries.py:308,1234,1248,1256` | Neo4j 实体图以 `MERGE` 写入；ontology/alias/prefix/embedding 相似候选去重，有 SAME_AS/review API。 | 图 DB 依赖；失败重试、事实冲突传播、人类 UI 未核。 | Apache-2.0；TS 相关 license 亦 Apache；vendored StateBench 示例为 MIT。 | 中高；只借 schema/alias 去重。 | 源码；近一年活跃。 |
| agentralabs/agentic-memory（新增） | `9d20fc4af3dea32ea9b2f28e490459cdb63c6e28`（2026-10-02） | `engine/cognitive.rs:833 analogical`; `v3/engine.rs:245 capture_user_message`; `engine/write.rs:44 WriteEngine::ingest`; `graph/builder.rs:73 add_correction`; `format/writer.rs:33 write_to_file` | 以结构指纹找类比子图；修正会建 correction node + SUPERSEDES edge 并降低旧 node confidence；图快照为 `.amem`。 | Rust core+Python SDK，binary 不透明；capture 后 durable flush、retry、用户手改流程未核。 | 根 MIT；core/CLI/FFI/MCP/Python 子许可均 MIT，但不同版权人。 | 高；移植算法/事件语义需跨语言。 | 源码；近一年活跃。 |
| ADVASYS/ragraph（新增） | `2be43202be299856b13a967685164b11dbc28dcf`（2026-04-22） | `IngestionPipeline.ts:92 ingestFile,110 runIngest,327`; `GraphConsolidator.ts:96 mergeEntities`; `GraphStore.ts:189 upsertNode,1137 neighborhood`; `Tools.ts:1157 expandViaGraphNeighborhood` | fused seeds 后拉图邻居，以 relation weight × centrality × expansionWeight 加分，再回 vector store hydrate；合并同类实体。 | Electron/TS/SQLite；失败状态标 failed，自动重试未核；纠错/用户实际编辑节点未确认。 | MIT，根许可。 | 中高；抽图邻居分数，不搬 UI/数据层。 | 源码；近一年活跃。 |

### 第 3 节字段补充核对

| 项目 | 存储 / 写入时机 | 失败、去重纠错 | 用户可读改 / 使用反馈 |
|---|---|---|---|
| A-MEM | `add_note` 将 note/links 放 `self.memories` 与 Chroma metadata；新增前 `process_memory` 找邻居并提建议。 | 重试未核；去重纠错未核；`update_neighbor` 只改内存、待 consolidation 才写向量，且检索序号被当作本地 index 有错改风险。 | 有 read/update/delete API；透明 UI 未核；联想采纳反馈未核。 |
| HippoRAG 2 | `index(docs)` 写 passage embedding/metadata、OpenIE triples 与图边。 | 相同 chunk hash 复用 ID；metadata 冲突会 warning；更广纠错和失败重试未核。 | 用户直接编辑/有用反馈未核。 |
| Cognee | `add` 存原始数据，`cognify` 做图处理；支持 add/update。 | 相同内容重复 add no-op；同路径内容不同需 update；失败重试、图事实更正和用户直改未核。 | 有 provenance/context API；联想专用的采用反馈未核。 |
| Graphiti | `add_episode` 以 source/reference time/UUID/group 写入 episode 并抽 graph nodes/edges。 | M7 已核其边时态和 dedupe；完整事务重试未核。 | 用户直改体验和联想采纳反馈未核。 |
| Basic Memory | `write_note` 将 Markdown 按 path/owner 写入关系索引；关系从 Markdown 解析。 | checksum 冲突拒绝陈旧覆盖；关系有唯一约束；retry 未核。 | Markdown 可直接看改；M9 召回采用反馈未核。 |
| MemoryOS | `add_session` 产 session/page 向量、关键词和热度并存 JSON/Chroma；命中更新访问数/热度。 | 同主题可按语义+关键词阈值合并；存储 IOError 可记日志，自动 retry 未见；事实纠错未核。 | JSON/Chroma 内容可读但直改体验未核；热度不是明确采用反馈。 |
| Neo4j agent-memory | long-term `add/add_entity` 写图实体。 | 按类型/别名/前缀/embedding 找重复并可合并 SAME_AS；失败 retry 与冲突事实传播未核。 | 有 list/retrieve/search/delete API；UI/手改未核；联想采用反馈未核。 |
| AgenticMemory | capture API 接收消息/工具/决策事件，`WriteEngine.ingest` 写图，再由 writer 序列化 `.amem`。 | `add_correction` 建 correction node + SUPERSEDES 并降低旧 confidence；retry/内容去重未核。 | CLI/查询可读 binary 背后结构；人类直接编辑和联想采用反馈未核。 |
| RAGraph | `ingestFile`/`runIngest` 解析、抽取并写 SQLite graph/vector；reingest 先删旧 doc/vector。 | 失败标记 failed；自动重试未核；实体按类型+相似度合并，关系 unique。 | 有 graph browser 源码，真实节点/原文编辑路径未核；采用反馈未核。 |

### 裁决

**最强：HippoRAG 2 的加权 Personalized PageRank。** 强在不是看到链接就固定多看一跳，而是以语义相关事实/段落为种子，按图路径权重分配扩展分。**第二：Basic Memory 的 Markdown 关系底座。** 强在关系本身用户可读、可改且能从透明文件重新解析。选择组合：Atlas 用显式 `[[page]]`/关系字段存可编辑边，把自动推断边另行标注 provenance/置信度；召回时使用轻量加权扩散/PPR（先小深度、预算限制），不要把自动建议写回人工关系。A-MEM 的演化只作为需用户/规则审计的提案流程。

### 移植清单

- `HippoRAG2@d5c83294:graph_search_with_fact_entities/personalized_pagerank → origin/memory-w2-api:core/atlas/memory/library/index.py:MemoryIndex.search`：保留 seed 权重与多跳图扩展；改为 Atlas 页面/条目 ID 的小图，限制邻居数、深度和 token 预算；丢弃 OpenIE/LLM 全套图构建服务。
- `BasicMemory@a72751c5:entity_parser.py:parse + context_service.py:find_related → core/atlas/memory/library/store.py:Page.parse/Entry.parse + index.py:MemoryIndex.entities/search`：保留 Markdown 关系可编辑、索引可重建；改为明确区分用户手写链接与自动生成关联；不复制 AGPL core，除非许可决定允许。
- `A-MEM@ceffb860:find_related_memories/process_memory → extract.py:apply`：只借助邻居候选生成“建议链接/合并”提案；先修正稳定 ID 映射、事务写回与索引同步，再考虑采用；替换风险较高的按向量结果序号修改邻居做法。
- `MemoryOS@587ed775:compute_segment_heat/search_sessions → index.py:MemoryIndex.search`：可把访问次数、新近度作为独立晋升/排序信号，不能替代 query relevance 或来源等级。
- `Cognee@f154b32a:HybridRetriever.get_retrieved_objects → MemoryIndex.search`：借双通道 candidate/fact context；不引入 Graph DB abstraction。

### 对 Claude 骨架假设的意见

**支持并升级。** 用页面 `[[链接]]` 作用户可懂的关系表示成立；但只沿链接固定一跳不如 seed 加权图扩展。保留显式用户链接为权威边；自动推断边需独立来源、置信度和可撤销状态；以小预算 PPR/加权扩散排序邻居。不要因为联想“像海马体”就引入完整 Neo4j/Graphiti 服务。

### 还没查清

A-MEM 对邻居更新有潜在错对象缺陷；Cognee、Graphiti、MemoryOS 的用户直接修改体验和 M9 专项“是否采用联想结果”反馈未找到；Basic Memory 的 AGPL 会限制直接复用；HippoRAG 2 的生产级失败/回滚和人工编辑未核。三个新增候选有的只核到写入/关联入口，未确认全套失败重试。

## 需要用户拍板

1. **Copyleft 许可边界：** Basic Memory 与 OpenViking 核心分别为 AGPL-3.0 系列。本报告建议先抽机制、实现兼容接口，不直接复制其核心文件；若未来要直接移植，需先决定是否接受相应许可义务。
2. **关联数据底座：** 继续以 Markdown 明文关系为用户可编辑权威源，还是引入独立图存储。按用户“透明库必须保留”的已定方向，本报告先按 Markdown 关系 + 可重建索引推进。
3. **M7 时间模型：** 是否把双时间字段用于所有事实，还是先限定在易变状态/偏好。按少量复杂度换取可追溯性的原则，建议先用于有明确变化/纠正/失效的事实，不把整个系统升级成全图数据库。

## 新增候选

- **M5：** mnemostack、Engram、MemForge。搜索词：`GitHub agent memory retrieval feedback retry hybrid recall 2025 2026`; `GitHub sqlite vector memory access feedback`; `GitHub agent memory Postgres pgvector feedback RRF`。三者最新源码提交分别为 2026-09-28、2026-10-14、2026-07-29，均有源码和许可证核验。
- **M7：** LangMem、Cognee、Hindsight。搜索词：`GitHub Memobase source code memory versioning repository`; `GitHub LangMem source repository memory update temporal`; `GitHub Cognee repository memory graph temporal`。最新源码提交分别为 2026-10-02、2026-10-13、2026-10-15；其中 LangMem 的源码覆盖同 key 而非实际版本历史。
- **M9：** Neo4j `agent-memory`、Agentra `agentic-memory`、ADVASYS `ragraph`。搜索词：`site:github.com graph based memory RAG agent memory project 2025 github`; `GitHub agent memory graph associative memory project active`; `GitHub memory graph retrieval agent memory 2026 repository`。源码和日期分别核到 2026-10-07、2026-10-02、2026-04-22。

LANE B DONE

## 审查意见（R，2026-10-16）

抽查依据：B 线报告 pinned source commits；以下修正应随总裁决理解。

1. **Supermemory skill 许可证更正**：`skills/supermemory/LICENSE:1-3` 为 Apache-2.0；根 LICENSE 为 MIT。B 表 M5 将 skill 子目录列为 MIT 不实，M7 已列 Apache，现统一为 Apache-2.0。其 MCP `search-memory.ts:register` 仅调用远端 `client.search` 并映射返回字段，不能作为后端算法证据。
2. **mnemostack retry 边界**：`recall/flow.py:recall_flow` 的 filter/rerank/limit/token budget 属实；`retry.py:retry_weak_recall` 调同一 flow 做有界改写也属实，但 retry 默认关闭且最多两个额外 query；启用 reranker 时还有模型调用成本，不能表述为每次召回自动重试。
3. **Graphiti 时间规则范围**：双时间及 edge invalidation 机制可借；`normalize_future_temporal_bounds` 只对其识别的英语未来断言/期限模式生效，不证明所有语言和未来事实都能归一。Atlas 的双时间账本必须独立保留原文及解析置信度。
4. **LangMem 同键更新范围**：核验的 manager 同 key upsert 行为成立；不能泛化到所有 `BaseStore` backend 的版本/历史语义。
5. **Cognee contradiction resolver 是可选路径**：`resolve_temporal_contradictions` 在缺少 `functional_relationships` 时直接返回；`tag_superseded_edges` 使用 `supersession_reason`。独立 `close_node` helper 不是 resolver 自动完成且非幂等，不能合并描述成默认自动生命周期。
6. **A-MEM 邻居更新**：`find_related_memories` 与 `process_memory` 的邻居注入/本地更新链成立；更新只在 consolidation 后才持久化，需把模型输出视作 proposal。
7. **HippoRAG PPR 函数名与边界**：仓库函数为 `run_ppr`，其调用 `self.graph.personalized_pagerank`，而不是仓库定义的 `personalized_pagerank`；使用无向投影。没有抽到事实时可回退，已有事实但无正种子会抛错，Atlas 必须有空种子保护。

核验数：8 组源码行为；未运行项目/测试。许可证与边界更正由 R 直接补入。
