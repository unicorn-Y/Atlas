# TASKBOOK-M7：变化事实、纠正、时间与遗忘传播

状态：待后续施工。本文是任务合同，不表示已有实现。

## 目标与不可变约束

在 Markdown+git 记忆库中记录可变事实的来源、记录时间、现实有效时间和修订关系。**Markdown 文件及其 git 工作树是唯一权威**；不得新增独立 Claim/Event/来源账本。Claim 元数据写在当前条目的 frontmatter 或行内元数据里。SourceEvent/SourceRef 只保存 `SessionDB` 原文的稳定指针（conversation_id、message_uid 或可解析区间、必要时内容哈希），不得复制一份原文或在独立数据库保存第二份事实。SessionDB 仍是对话原文的唯一所有者；`core/atlas/memory/library` 下数据库、FTS、向量、链接图和处理队列均为派生物，可由 Markdown+SessionDB 重建。

裁决顺序固定：用户纠正始终最高；来源等级 user（用户陈述/编辑）> tool（工具观察）> model（模型推断）；同等级 recorded_at 较新的当前有效主张胜出，旧主张标为 `superseded` 并留在 Markdown 历史。用户纠正生成一条可追溯的新主张，不能静默覆盖来源历史。时间解析保留原始表达；无法可靠解析时 valid_from/to 留空或标 unknown，不猜日期。

全局固定默认值：Basic Memory AGPL 只作行为参考，不复制代码；遗忘沿派生链删除正文及所有派生内容，只留 W0 已有内容哈希墓碑；M9 只沿 Markdown `[[links]]` 默认扩展一跳，PPR 默认关闭，真实使用证明收益后才开启。

## 固定上游依据与移植边界

- `getzep/graphiti@d50741d1bf463cbe3859eb73914cbff1b66839e6:graphiti_core/edges.py:EntityEdge`、`graphiti_core/utils/maintenance/edge_operations.py:_extract_edge_timestamps/resolve_extracted_edge/_dedupe_extracted_edge`、`temporal_edge_utils.py`：移植 valid/invalid 与 created/expired 两种时间语义、抽取后规范化/冲突失效规则；仅移植字段和规则，不接图数据库。未来边界归一化只对其支持的英文时间模式有效，不作为通用时间解析器。
- `mem0ai/mem0@0724291bd864cf807e88ee8981c8226644e8fb42:mem0/memory/main.py:Memory.update/delete/_update_memory/_delete_memory`、`configs/prompts.py:DEFAULT_UPDATE_MEMORY_PROMPT`、`memory/storage.py:SQLiteManager.add_history`：只借 ADD/UPDATE/DELETE/NONE 的修订意图与旧新值审计概念；其向量记录更新不是 Atlas 双时间真源。其 hash 去重有检索 top-k 范围限制，不得当全库唯一键。
- `topoteretes/cognee@f154b32a9e544dac73e7ddf2010327cf9988edcd:cognee/tasks/graph/resolve_temporal_contradictions.py:resolve_temporal_contradictions` 与 `cognee/modules/graph/utils/temporal_conflict_resolver.py:tag_superseded_edges`：仅借 lineage 思路；resolver 缺少 functional relationships 时会跳过，不能当无条件规则。不引入图栈。
- Basic Memory `basicmachines-co/basic-memory@a72751c5d626380dedeed30f55f7a80ba3dc710d` 为 AGPL-3.0-or-later，**仅作行为参考，不复制代码**。

## Atlas 路径审计与文件所有权

核对仓库：`D:\atlas-mem-w2-api`，HEAD `aa14c3173392d0fc60ec3e401e4495a2d3357cb7`。实际存在的 library 文件为 `__init__.py, cleanup.py, dream.py, embed.py, extract.py, forget.py, hybrid.py, index.py, queue.py, sources.py, store.py`；没有 `models.py`，不得引用或预设该模块。会话接口位于 `core/atlas/engine/session_sync.py`（已核实存在），不是 `core/atlas/memory/library/session_sync.py`。所有 M 任务的施工基线改为 A0 合并后的 `ui-redesign`；施工者先将以下函数与该基线对照，若差异只按本合同更新函数定位，不另造冲突真源。

| 文件（所有权） | 已存在函数/类及改动范围 |
|---|---|
| `core/atlas/memory/library/claim_resolution.py`（**新建，M7 独占**） | 新建纯函数 `is_current_claim(entry, now)` 与 `resolve_claim_conflict(existing, proposed)`：只依据冻结 Markdown 字段返回当前性/裁决/旧项 superseded 建议，不写文件、不访问数据库、不接 SessionDB。该 predicate 由 M4 在 Markdown 写入事务中接线，M5 在其 `index.py` 过滤当前 claim 时消费。 |
| `core/atlas/memory/library/forget.py`（M7 独占既有文件） | 保留现有 `purge_history(store, needles)`；新建 `propagate_forget(store, entry_refs, derived_manifest)`，计算要清除的派生文件/摘要/索引/技能候选并调用既有 Git 历史清除能力。只定义传播契约，不直接修改 `store.py` 或 UI。 |
| `core/atlas/memory/library/store.py`（M7 owns Entry 元数据段；M4 后续 owns 写入协议） | 已存在 `Entry` 与 `Entry.meta/line/parse`、`Page.render/parse`、`MemoryStore.tombstoned/add_tombstones`、`tombstone_hashes`。M2 完成指针接口、M3/M7 冻结字段后，M7 修改 `Entry` 元数据字段的兼容序列化；M4 随后接入 Markdown 原子写入协议。W0 哈希墓碑实现复用现有方法。 |
| `core/atlas/memory/library/extract.py`（M3 owns；M7 不拥有、不修改） | 已存在 `Proposal/apply/apply_episode/_locate/expire`。M4 在其 Markdown 提交路径调用 M7 的纯裁决函数；M7 不接线、不修改提炼逻辑。 |
| `core/atlas/memory/library/dream.py`（M4 owns；M7 不拥有） | 已存在 `_episode_groups/_write_project/run_dream`。M4 保留 supersedes/retracts 元数据并通过其写入协议应用裁决。 |
| `core/atlas/memory/library/__init__.py`（M3 owns；M7 不拥有） | 已存在 `MemoryLibrary.forget_entry/_purge`。M7 复用现有 call-site；若需新增 propagation 调用，由 M4 在之后唯一接线，M7 不修改此文件。 |
| `core/atlas/memory/library/index.py`（M5 owns；M7 不拥有） | 已存在 `MemoryIndex.sync/rebuild/search/facts`。M5 在自身 `search/facts` 实现中消费 `claim_resolution.is_current_claim`；索引由 Markdown 重建。M7 不改索引。 |
| `core/atlas/engine/session_sync.py`、`core/atlas/memory/library/sources.py`（M2 owns；M7 只消费接口） | 已存在 `session_message_evidence/read_session_messages/search_session_messages` 与 `sources.open_ref`。原文定位和打开均由 M2 提供；M7 不复制 transcript、不修改接口。 |

不新增 `models.py`、`claim_ledger.py`、`source_ledger.py`、独立 claims SQLite 表或事实账本。`claim_resolution.py` 只含无状态规则；`forget.py` 只拥有删除传播；M7 在字段接口冻结且 M2 指针工作完成后拥有 `store.py` 的 `Entry` 元数据序列化段，M4 后续负责写协议接线。当前事实索引归 M5，原文定位归 M2。M7 与 M3 可并行，只共享冻结的 Markdown 字段接口；M7 不写 `extract.py`、`index.py` 或 `__init__.py`。

## 逐步施工清单

1. 对 A0 合并后 `store.py/extract.py/forget.py/index.py/session_sync.py` 做基线核对；输出一页字段映射到代码注释/变更描述，不改旧数据。
2. 与 M3 冻结 Markdown 字段接口：`source_level`、`recorded_at`、`valid_from`、`valid_to`、`supersedes`、`retracts`、`source_ref`；M2 指针接口完成后，由 M7 在 `Entry.meta/line/parse` 实现旧字段兼容映射与新字段序列化。`source_ref` 指向 SessionDB，不内嵌消息正文。
3. 新建 `claim_resolution.py` 纯函数：先判断用户纠正，再比较来源等级，再比较 `recorded_at`；返回 winner、旧主张 superseded/retracts 建议和解释标签。函数不得写 Markdown。M4 在原子写入流程消费返回值并更新当前/历史 Markdown；M5 在自己的 index 中调用 `is_current_claim` 排除历史主张。
4. 时间抽取保存原始时间短语与解析值；仅可信 ISO 日期进入 `valid_from/to`。支持未来/过去的个人生活事实、偏好、关系、计划等普通用户事实，与项目/工作事实同样处理；不把系统推断写成用户口述。
5. 在 `forget.py` 实现 `propagate_forget`：由调用方传入被忘条目的 Markdown lineage 和派生清单，删除摘要、候选技能及缓存，要求 M5 重建索引；沿记忆库 Git 历史移除原文/衍生文本。W0 哈希墓碑由 M4 的现有写路径维护，只含内容哈希及必要时间，不含正文。不得创建不可重建的待办队列真源。
6. 对旧库做只读扫描与小批迁移：旧条目 source_level 从已有 `src` 映射；无依据的 recorded_at/valid time 填 unknown，不以文件时间冒充；可确定的 ref 转成 SessionDB 指针，不可确定则标 `legacy_unresolved`，不伪造 message ID。先 dry-run 摘要，再由同一 Markdown 写入器增量改写并保留 diff。
7. 将 `is_current_claim` 契约交给 M5；M5 在其独占的 `MemoryIndex.search/facts` 与 `MemoryLibrary.recall/search` 主召回路径集成 predicate，并由 M5 验证从 Markdown 全量 rebuild 后只返回当前有效主张。M7 不修改这些文件。
8. 在真实使用中演练纠正、时间事实和遗忘，再重启并复查 Markdown、Git 历史与索引日志；修复任何复活或错误裁决后重演。

## 旧代码与旧数据

保留 `Entry.src/at/until/ref` 的兼容读取和现有 Markdown 页面布局；M7 在 `Entry.meta/line/parse` 增量实现规范字段映射。删除任何“最新写入无条件覆盖”、“按模型置信度覆盖用户来源”及独立 SQLite Claim/SourceEvent 存储。保留 SessionDB 作为原文唯一源和 `forget.py:purge_history` 的历史擦除能力。SQLite、FTS、embedding、链接关系、处理状态均能重建；唯一持久的遗忘例外是既有 W0 内容哈希墓碑。

## 最少真实使用验收（不扩成测试项目）

- 在真实 Atlas 会话中先由用户声明一项生活偏好，再用用户明确纠正；随后加入相反的工具观察和模型推断。查看 Markdown：用户纠正为当前值，旧主张有 `supersedes`/历史标记、原始 `source_ref` 可打开 SessionDB 对话；日志显示裁决等级和记录时间。
- 记录一项有明确日期的未来计划和一项不确定时间表达。前者保存 valid_from/to，后者不被猜成确定日期；重启后召回结果一致。
- 对一条真实记忆执行忘记：日志列出被清除的 Markdown 派生摘要、索引/embedding、关联页面与技能候选；哈希墓碑存在而正文不在 Markdown、派生物或 git 历史中；全量重建索引、重启并重跑相关提炼后都不复活。
- 直接手改一条 Markdown 元数据后重建索引，编辑内容保持不变且查询反映该编辑。

## 依赖、并行与完成边界

依赖 A0 合并后的 `ui-redesign` 基线、M2 稳定原文指针和 M3 冻结的 Markdown 字段接口。M7 与 M1/M3 可并行：M7 拥有新建 `claim_resolution.py`、既有 `forget.py` 及 `store.py` 的 `Entry` 元数据序列化段；M3 仍独占 `extract.py` 与 `__init__.py`，M7 不修改它们。M4 在 M7 字段完成后顺序接写入/删除 call-site；M5 在自身 index/召回 ownership 内消费 current-claim predicate；M9 不拥有或依赖 M7 索引段。M8 依赖本任务的 lineage/forget contract。
