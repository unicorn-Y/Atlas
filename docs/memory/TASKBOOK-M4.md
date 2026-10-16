# TASKBOOK-M4：可验证整合、透明 Markdown 写入与事实演进

状态：待后续施工；本文是可执行施工合同，不表示功能已经实现。所有路径均相对 Atlas 仓库根。基线必须是 A0 已完成并合入的 `ui-redesign`，不是 W2 API 临时分支，也不是本次审查分支。

## 目标与不变量

把 M3 提炼产出的经历、回顾、原文指针与原子事实，整理进用户可读、可编辑、可用 Git 查看和恢复的 Markdown 记忆库。**Markdown 文件及其 Git 历史是唯一权威真源。** Claim 的 `source_level`、`recorded_at`、`valid_from`、`valid_to`、`supersedes`、`retracts`、`source_ref` 放在条目 frontmatter 或行内元数据；`SourceEvent` 只保存指向 SessionDB 原文的标识和定位，不复制对话内容。SQLite、FTS、向量、关联图、处理队列、checkpoint 都是可从 Markdown 和 SessionDB 重建的派生物，不得成为第二套记忆真源。

执行用户已拍板的规则：用户明确纠正的内容永远优先；一般冲突按来源等级“用户陈述 > 工具观察 > 模型推断”，等级相同取较新的说法；被替代的旧条目标记 `superseded` 并留在可追溯历史中。遗忘时沿派生链删除 Markdown 记忆正文及其摘要、索引、向量和技能候选，只保留 W0 已有的内容哈希墓碑，防止同一内容重导入。

关联默认只沿 Markdown 显式 `[[链接]]` 多看一跳；PPR 默认关闭，只有真实使用证明有收益后才启用。Basic Memory 核心为 AGPL，仅作 Markdown/文件协调行为参考，不复制代码。

## 上游机制与采纳边界

- `openai/codex@092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`，官方 Codex Rust v0.162.1 拆解快照：`codex-rs/memories/write/src/phase2.rs:run`、`agent::handle`、`workspace.rs:memory_workspace_diff`、`reset_memory_workspace_baseline`、`validate_consolidation_artifacts_for_version`。只借租约持有者、增量 diff、退避重试、proposal 校验和 baseline 前后对比机制；不移植 Rust，也不把其本地 workspace/状态记录提升为 Atlas 真源。
- `openclaw/openclaw@59cb44796b0f1f0daa0e37af8b1495abb45d9bc1`（官方 v2026.10.3 拆解快照），MIT：`extensions/memory-core/src/dreaming-consolidation.ts:validateConsolidationPlan/applyMemoryConsolidationPlan`、`extensions/memory-core/src/short-term-promotion-apply.ts` 的 fingerprint/base-hash guard。借鉴计划先校验、应用前核对当前文件 hash/文本、只在未被用户编辑时自动合并的机制。
- `basic-memory` 核心许可证为 AGPL-3.0-or-later：只作人类可读 Markdown 与 DB/文件协调行为参考，不复制代码。

## Atlas 基线核对、文件所有权

按 `origin/memory-w2-api` 已核对源码结构；必须先切到 A0 合并后的 `ui-redesign` 重新核对并记录 commit、文件和函数，不能照抄不存在的路径。当前真实接口如下：

| 文件 | 已核对的现有符号 / 施工所有权 |
|---|---|
| `core/atlas/memory/library/dream.py` | `_checkpoint`、`_episode_groups`、`_write_project`、`_old_owner_lines`、`run_dream`。M4 唯一所有，可改。现状是分组经历、模型生成四段摘要、保留 `src=你说的/你改的` 行、写 `THINGS` 与 `NOW` 后提交 Git，再写 `.dream-state.json` checkpoint 并同步索引。 |
| `core/atlas/memory/library/store.py` | `Entry` / `Page` 的 `meta/line/parse/render`，`MemoryStore.read/write/pages/append_diary/find_entry/commit/show/revert`，`tombstone_hashes/add_tombstones/tombstoned`。M4 可改写入与元数据序列化；M7 与 M2/M3 共用时先冻结小接口，避免多人同改。 |
| `core/atlas/memory/library/index.py` | `MemoryIndex.sync/rebuild/_reindex`。M5 拥有。M4 只调用派生索引重建接口，不改该文件。 |
| `core/atlas/memory/library/cleanup.py`、`forget.py` | `cleanup` 负责重建索引；`forget.purge_history` 及 `store` 哈希墓碑用于遗忘。M4 不改这两文件，调用 M7/M2 确定的删除协议。 |
| `core/atlas/engine/session_sync.py` | 实际位置；`read_session_messages`、`read_session_all_messages`、`session_message_evidence`、`latest_session_message_id`。M2 所有。M4 仅消费 M2 的 SessionDB 指针接口，不把这里复制出的消息正文写入独立账本。 |

禁止引用 `core/atlas/memory/library/session_sync.py` 或 `models.py`：它们在核对的 W2 API 源码中不存在。Library 文件清单以 `__init__.py`、`cleanup.py`、`dream.py`、`embed.py`、`extract.py`、`forget.py`、`hybrid.py`、`index.py`、`queue.py`、`sources.py`、`store.py` 为准。

## 施工步骤

1. **建立可回滚基线。** 在 A0 合并后的 `ui-redesign` 记录 `git rev-parse HEAD`、记忆库根目录、当前 Git HEAD、Markdown 页面数、派生索引行数和待处理经历数；对记忆目录做 Git/文件备份。先确认 `MemoryStore.pages/read` 可以完整读取现存 Markdown。不得把数据库快照认作权威备份。
2. **冻结条目兼容形状。** 与 M2/M3/M7 对齐现有 `Entry` 行格式；在 `Entry.meta/line/parse` 或兼容解析层读写上述 Claim 字段，并保留旧条目原字段。每条 Claim 至少有稳定 ID、内容、来源等级、记录时间、有效时间边界、替代/撤回关系和 `source_ref`。老格式仍可读；不得把缺字段默认为“用户确认”。字段放在 Markdown 中，不能另建 claims.sqlite、evidence ledger 或 source ledger。
3. **重做输入选择和幂等标记。** M3 每个会话生成的经历、会话回顾和原文指针是整合输入；M4 只在经历含可沉淀的跨会话信息时生成项目摘要/当前状态，原子事实按 ID/来源引用增量处理。`.dream-state.json` 只能作为可删缓存；丢失后通过 Markdown 中已处理的 `source_ref` / 版本信息重算。禁止“checkpoint 已推进但 Markdown/Git 未成功”的窗口；同一输入重放必须通过来源指针/稳定 ID 去重，不可多造重复条目。
4. **生成 proposal，不直接接受整页覆盖。** 将 `run_dream` 拆为可审计阶段：准备候选输入；模型生成动作列表（`add/update/supersede/retract/keep`，目标 Claim ID、旧文本 hash、来源引用、拟写字段和理由）；host 代码校验格式、来源可回溯、等级和时间规则；应用器在锁内重新读当前 Markdown，验证拟修改旧行仍与 proposal 的 hash 相同。proposal 覆盖期间若用户编辑了文件，将冲突条目标记待人工/后续重试，不覆盖用户版本。模型只建议，不自行提高来源等级，不删除用户纠正，不把推断改成观察。
5. **保留历史并执行冲突规则。** 对不同等级冲突按高等级保留当前有效版本并记录被替代项；用户纠正优先于任意自动规则；同等级以 `recorded_at` 较新的值为当前版本，旧 Claim 仍在 Markdown 历史中并以 `supersedes` 关联。撤回用 `retracts` 指向被撤回 Claim，不能物理消失；只有用户明确遗忘才走 M7 的派生链清除流程。
6. **原子写 Markdown 与 Git。** 将所有目标文件写入临时文件，校验重新 parse 后的 Claim、引用和 Markdown 格式，再原子替换；提交前比较用户修改窗口中的当前 hash。Git commit 成功后才把处理水位缓存推进。Git 临时不可用时正文仍须以可恢复方式写入 Markdown，并留下未提交状态日志；重启后扫描 Markdown/Git 状态补交，不能把 SQLite 队列的完成标记当作完成事实。
7. **重建派生物。** 写入成功后调用 `MemoryIndex.rebuild/sync`；若索引重建失败，保留 Markdown/Git 成果，并在下一次启动从 Markdown 重建 SQLite/FTS/向量。队列、lease 和失败计数只支持工作恢复，全部允许丢弃重建。
8. **迁移旧内容。** 先备份，再将旧条目映射为新 frontmatter/行内格式：可从 `src` 判定的填来源等级；有 `ref` 的映射成 `source_ref`；没有证据的标 `legacy_unattributed`，不臆测；原时间映射为 `recorded_at`，若无有效期则不添加。利用现有 diary/episode 原文指针补链；无法定位 SessionDB 的项保留正文并显式标记不可回溯。迁移后重新解析所有页面、建立索引并以原 Markdown/Git diff 做人工可读审阅。失败时从备份恢复 Markdown，再重建派生物。
9. **接入遗忘和 UI 手改。** M7 的遗忘操作需删除对应 Markdown Claim、项目摘要、可导出的技能候选和派生检索数据，只写入 W0 现有哈希墓碑；不可在派生库留正文副本。普通 UI 手改直接改 Markdown，下一轮整合检测 hash 变化并尊重用户内容。

## 删除、保留与迁移范围

- 删除/替换：`_write_project` 返回文本后直接重写整页的接受方式；模型全文输出直接写入权威文件的路径；以 `.dream-state.json` 唯一判断“是否已处理”的逻辑；任何单独 SQLite 主张/来源/证据账本。
- 保留：`MemoryStore` Markdown 读写与 Git 操作；`Entry/Page` 兼容旧行的解析；现有用户编辑/来源标注保护；`MemoryIndex` 作为派生搜索层；W0 哈希墓碑；ModelRouter 调用及超时配置。
- 新建文件标注为 `新建`：`core/atlas/memory/library/consolidation.py`（proposal schema、validator、markdown patcher；建议 `validate_plan`、`apply_plan`、`source_event_exists`）。如能用小型纯函数留在 `dream.py`，优先不新建；由实现者在施工记录说明取舍。不得新建持久权威账本。

## 最少真实使用验收（使用与日志，不扩成大型测试套件）

用隔离的真实记忆库和当前配置模型完成：一次跨三个会话的摘要整合；一次同级新事实取代旧事实；一次工具观察与模型推断冲突；一次用户显式纠正；一次模型返回无效 proposal；一次 proposal 期间用户编辑目标 Markdown；一次进程在写入后、重建索引前中断并重启。逐项检查实际 Markdown、Git diff/log 和结构化运行日志，日志至少含候选来源 ref、proposal ID、old/new hash、冲突动作、文件写入/提交结果、checkpoint 状态及索引重建状态。确认原文可通过 `source_ref` 回到 SessionDB；删除临时索引目录后可重建且检索结果等价；模型失败/重启不丢输入、不覆盖手改、不重复生成 Claim。验收只报告本次真实观察到的行为，不用 mock/纯单测替代。

## 依赖、并行与交付

依赖顺序：A0 完成后，M2 为引用接口前置；M3、M7 与 M1 并行定契约；M4 在 M3 数据形状与 M7 冲突/遗忘规则冻结后施工。M5/M9 可在 M2 后与 M4 并行，但 M5 负责 `index.py`，M4 负责 `dream.py`/`store.py`；不得跨所有权改文件。M8 依赖 M3/M4/M7。交付需附基线 commit、文件改动清单、迁移前后 Markdown 样例（脱敏）、真实使用日志摘要、索引重建记录、失败与未验收项；不在本调研任务中实施。
