# TASKBOOK-M2：Markdown 来源元数据与 SessionDB 精确指针

状态：待施工；本轮只形成任务书，不修改实现。
基线：先完成 A0，所有路径从合并后 `ui-redesign` 复核。源码路径核验使用 `D:\atlas-mem-w2-api` `origin/memory-w2-api@aa14c3173392d0fc60ec3e401e4495a2d3357cb7`。M2 是后续任务的引用与元数据基础。

## 目标与数据权威

**唯一权威是 Markdown + git 记忆库。** 每条 Claim 的 `source_level`（用户陈述/工具观察/模型推断）、`recorded_at`、`valid_from`、`valid_to`、`supersedes`、`retracts`、`source_ref` 写入对应 Markdown 条目的 frontmatter 或行内元数据，支持用户直接审阅和编辑。不得新增独立“来源账本”或“证据与主张账本”。

`SourceEvent` 只是指向 Hermes SessionDB 原始消息的引用对象，核心为 `conversation_id + message_uid`，可选 `tool_call_id/span/hash`；它不带、不复制、不缓存转录正文。SessionDB (`DATA_ROOT/engine/state.db`) 是原始对话的权威。SQLite、FTS、向量、图和处理队列均是可从 Markdown 与 SessionDB 重建的派生物。外部 Agent 权限全开，其输出回到 Atlas 后按普通 transcript 处理。
## 全局固定规则（相关模块按职责消费）

- Basic Memory 为 AGPL；只作行为参考，不复制代码。
- 冲突顺序固定：用户纠正永远最高；不同来源等级为用户陈述 > 工具观察 > 模型推断；同等级按新旧取较新，旧内容标为 `superseded` 并留在历史。
- 遗忘沿派生链清除 Markdown 内容、索引、摘要与技能候选，只保留内容哈希墓碑防止重新导入；沿用 W0 已有哈希墓碑机制。
- M9 联想默认只沿 Markdown `[[链接]]` 多看一跳，PPR 默认关闭；只有实际使用证明有收益后才考虑启用 PPR。

## 上游来源与移植范围

1. `unicorn-Y/Atlas memory-w2-api@aa14c3173392d0fc60ec3e401e4495a2d3357cb7:core/atlas/engine/session_sync.py`：复用已有 `read_session_all_messages`、`read_session_messages`、`session_message_evidence` 和 `_message_for_atlas` 对稳定 `message_uid` 的映射；扩展精确 UID 读取。该文件当前在 `core/atlas/engine/`，没有 `core/atlas/memory/library/session_sync.py`。
2. Hermes SessionDB 来源在 Atlas 文件头标注的 `unicorn-Y/hermes-agent@562ad75:hermes_state.py::SessionDB`；只参考 `message_uid`、`session_id`/`conversation_id` 对应与消息读取接口。SessionDB 保持原文唯一存放处。
3. `bettyguo/agent-memory@d38704818ae7e84a4e154cd79494af0742deba18:src/trace_mem/store.py::{get_turn,verify_citation}` 与 `src/trace_mem/citation.py::{sign_citation,verify_citation_signature,verify_citation_content}`：借鉴“引用必须回到具体消息”的校验思想；不要照搬仅用 `turn_id` 的 SQL 查询。本项目发现相同 turn id 可跨 trajectory 重复，因此 Atlas 指针同时需要 `conversation_id` 与 `message_uid`。
4. `BAI-LAB/MemoryOS@587ed7755c7aed179965792830ff1b5ad9a6fa92:memoryos-pypi/memoryos.py::add_memory` 及 `updater.py`（A-RESULT 所列 `source_event_id` 链路）仅供核对来源事件概念；不移植其数据库模式。

## Atlas 路径审计与逐文件所有权

在 `D:\atlas-mem-w2-api` 已核验 library 当前文件清单：`__init__.py, cleanup.py, dream.py, embed.py, extract.py, forget.py, hybrid.py, index.py, queue.py, sources.py, store.py`。M2 不虚构 `models.py`。实际 `Entry`/`Page` 类型与 Markdown 读写在 `store.py`；原文打开入口在 `sources.py`。

| 文件 | 状态 / 文件所有权 | 本任务改动 |
|---|---|---|
| `core/atlas/engine/session_sync.py` | 现有；M2 独占 M2 改动 | `_message_for_atlas` 保留 `message_uid` 为 Atlas `id`；`read_session_all_messages`、`read_session_messages` 可通过精确消息 UID 定位；`session_message_evidence` 增加按 `(conversation_id,message_uid)` 返回存在性/role/time，不使用 timestamp 猜测消息。 |
| `core/atlas/memory/library/sources.py` | 现有；M2 独占 | `open_ref` 从旧 `conversation@timestamp` nearest-user 方式扩展到 UID 精确定位；旧引用仍可宽泛打开但标注精度 legacy。`search_raw` 保留为派生查询，不作为权威。 |
| `core/atlas/memory/library/store.py` | 现有；M2 独占 | `Entry.parse/line` 对 Markdown 行内 metadata round-trip 新 provenance keys；`MemoryStore.find_entry/read/write` 继续将 Markdown 当权威，不加第二账本。迁移时保存未知 metadata 和人工编辑。 |
| `core/atlas/memory/library/source_ref.py` | **新建**；M2 独占 | 轻量 `SourceEvent`/`SourceRef` 值对象与解析/格式化；只容纳指针与校验信息，无正文字段、无数据库写入接口。 |
| `core/atlas/memory/library/extract.py` | 现有；M2 不改，由 M3 独占 | M3 只使用本任务确定的 Markdown metadata/ref 接口。 |
| `core/atlas/memory/library/index.py`, `hybrid.py` | 现有；M2 不改 | 索引继续可删可重建，不成为来源事实。 |

## 施工步骤

1. 在 A0 合并后的工作树，重新打开 `session_sync.py`, `sources.py`, `store.py` 并确认 `message_uid`, `Entry`, `_ENTRY_RE`, `Entry.parse`, `Entry.line`, `MemoryStore.read/write` 仍在；将上述表中函数名更新为当前代码证据。
2. 定义 `SourceRef`：`conversation_id`, `message_uid`, 可选 `tool_call_id`, `span_start`, `span_end`, `content_hash`, `observed_role`, `observed_at`。身份键必须至少为 `(conversation_id,message_uid)`；相同 message_uid 在其他 conversation 不可混淆。`SourceEvent` 作为内存传递对象可包含 `event_kind`，但绝不可放 `content`。
3. 由 `session_sync.py` 提供 UID 精确查找/读取能力，必要时调用 Hermes SessionDB 查询。精确引用不得退化为“选时间最接近的 user message”。`sources.open_ref` 对新 UID 引用只读指定消息及紧邻上下文；tool result 通过 `tool_call_id`/assistant tool call 关联。`span` 若无法保真定位则显示整条消息，不伪造字符位置。
4. 将来源等级、记录时间、有效期、取代/撤回关系、来源引用编码进 `Entry` 的 Markdown metadata。字段规范统一为 `source_level`, `recorded_at`, `valid_from`, `valid_to`, `supersedes`, `retracts`, `source_ref`。元数据可以在 frontmatter 或行内 JSON；当前 W2 `Entry.line` 已有行内 metadata 机制，优先扩展它以避免另建存储文件。保留用户手工修改和未知键。
5. 给 `open_ref` 加旧格式兼容：现有 `conversation@ISO timestamp` 可继续按旧逻辑展示为 `precision=approximate`，不可自动转换成 UID。能从旧 Markdown 的 ref 和 SessionDB 原始记录唯一匹配时才迁移成 UID；无唯一匹配保持原 ref 并标 `legacy_unanchored`，人工可见。
6. 迁移既有事实：从现有 Entry 元数据搬 `src/ref/at/expires` 到规范字段；不能确认的来源等级写 `legacy_unknown`，不能补猜 `valid_from`。`supersedes/retracts` 仅在旧数据明确表达替换/撤回时生成；保留旧行历史。迁移后从 Markdown 重建 SQLite、FTS 与向量索引并逐条比对 entry ID/ref；删掉任何为该功能新增的重复 provenance SQL 表。
7. 旧 `sources.search_raw` 如从 FTS 取结果，继续只返回来源指针与匹配摘要，点开时回读 SessionDB 当前 transcript；来源删除或会话删除要如实报告不可用，不从缓存索引补正文。清除当前流程中任何把原文另写入 library SQLite/JSON 的调用。
8. 用两条不同会话中相同 `turn_id`（若数据存在）和两个不同 message UID 验证引用各自定位正确；编辑 Markdown 的等级/日期后重建索引仍读取编辑值。对比压缩前后引用行为，记录实际 SessionDB 保留边界，不承诺已删除正文仍可恢复。

## 旧代码删留与迁移边界

保留 Hermes SessionDB 全部现有读写所有权与 API；保留 W2 Markdown `Entry/Page/MemoryStore`、人工编辑、git 历史、哈希遗忘墓碑。替换 `sources.open_ref` 对新引用采用的时间近似定位。派生索引可重建，因此删掉重复的 SQL provenance/claim 表（如果 A0 或并行任务引入了此类临时实现），但禁止删 SessionDB 原文或用户 Markdown 条目。迁移脚本必须可重复运行，不修改 source content，仅规范元数据与可验证 UID。

## 最小真实使用验收

- 在实际 Atlas 生成的两条会话各提炼一个条目，source_ref 精确打开对应 SessionDB 消息；tool 类型条目也能打开对应工具调用/返回内容。
- 把 Markdown `source_level` 从 model inference 手工改为 user assertion，重建 SQLite/FTS 后 UI/API 读取仍显示手工值；删除所有派生索引后重建，结果仍能搜索和回到原文。
- 旧 timestamp ref 仍可查看并明确显示为近似；找不到 SessionDB 消息的 ref 显示来源不可用，不从独立证据库回填正文。
- 从日志可追踪 `entry_id → source_ref → conversation_id/message_uid`；日志不输出整段用户原文。无需大型测试套件。

## 依赖、并行与停止边界

第一阶段依赖 A0；第二阶段先完成 M2 并冻结 `SourceRef` 与 Markdown metadata 契约。M2 之后，M1/M3/M7 可并行；M1 不得编辑 M2 所有的 `session_sync.py`、`sources.py`、`store.py`、`source_ref.py`，M3 只消费其接口并拥有 `extract.py`、`library/__init__.py`。M5/M9 可在 M2 后并行但只改各自检索文件。M6 依赖 M1/M2/M5。M2 不建设独立账本，不改记忆提炼策略。
