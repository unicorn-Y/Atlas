# TASKBOOK-M3：详细会话经历、回顾与增量事实提炼

状态：待施工；本轮只修改调研文档。
基线：先完成 A0，并以 A0 合并后的 `ui-redesign` 为基线。开始施工时必须复核下列 Atlas 函数；文件/函数路径已按 `D:\atlas-mem-w2-api` `origin/memory-w2-api@aa14c3173392d0fc60ec3e401e4495a2d3357cb7` 实际打开核对。

## 裁决和数据原则

M3 采用两层输出：第一层以 Codex Phase 1 为主，对每个可处理会话生成保留细节的**会话经历记录**（发生了什么、用户目标、决策及理由、涉及文件、实际命令、原样报错、数字/结果、未完成事项、用户纠正、会话回顾和 SessionDB 原文指针）；第二层再借 Mem0 ADDITIVE 提炼，从经历与来源消息中提取独立原子事实，供后续 M4 冲突合并。不能只做 Mem0 ADD-only 原子事实，否则会丢失用户追问“怎么做、为什么、遇到什么错误、还有什么没做完”所需细节。

Codex 选择基于提示词、流程与状态语义；Codex 是 Rust 的理由不能作为拒绝移植依据。本任务只翻译和改造提示词/调度语义，不移植 Rust 代码。Nemori 保留来源消息的 episode 与 Mastra previous extraction / transient retry 是补充，不取代 Codex 主经历记录。Markdown + git 记忆库是唯一真源；事实、经历均为 Markdown 条目。Claim 元数据写在对应 Markdown frontmatter/行内 metadata。SQLite、FTS、向量和队列都是可重建派生物。SourceEvent 只指向 SessionDB 原文，不保存正文副本。
## 全局固定规则（相关模块按职责消费）

- Basic Memory 为 AGPL；只作行为参考，不复制代码。
- 冲突顺序固定：用户纠正永远最高；不同来源等级为用户陈述 > 工具观察 > 模型推断；同等级按新旧取较新，旧内容标为 `superseded` 并留在历史。
- 遗忘沿派生链清除 Markdown 内容、索引、摘要与技能候选，只保留内容哈希墓碑防止重新导入；沿用 W0 已有哈希墓碑机制。
- M9 联想默认只沿 Markdown `[[链接]]` 多看一跳，PPR 默认关闭；只有实际使用证明有收益后才考虑启用 PPR。

## 上游仓库、固定快照与移植清单

1. **Codex 主流程**：`openai/codex@092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`，官方源码 `rust-v0.162.1` 快照（`Codex-Official/VERIFY.txt` 中记录的 HEAD commit）。`codex-rs/memories/write/templates/memories/stage_one_system.md` 全文分段翻译：如何抽取个人记忆、raw memory 与 rollout summary 的区别、证据引用、不确定性、已有条目去重、何时无输出；改写 Atlas 输出 schema，使每个会话都能写详细经历，而非默认只写 facts。重点保留“尽量保留有用细节、事实不确定要标注、不要从工具/模型内容伪称用户说过”的要求，并加中文明确字段：决定及理由、文件、命令、原始错误文本、数字/结果、未完成事项、用户纠正、会话回顾、原文 UID。
   - `codex-rs/memories/write/src/phase1.rs::{run,claim_startup_jobs,build_request_context,run_jobs}`：只移植每个 rollout/session 单独处理、job lease/claim、退避重试、成功/no-output/失败分别落状态的流程思想；对照相邻 job result 的 `no_output` 语义。不得照搬 Rust 代码或 SQLite 为真源的结构。
   - Codex no-output 不能被理解为“没抽出原子事实就丢会话”。在 Atlas 中，只有闲聊/空会话等确无值得回顾的经历才 no-output；若有工作过程但没有长期事实，仍必须产出会话经历和摘要。
2. **原子事实补充层**：`mem0ai/mem0@0724291bd864cf807e88ee8981c8226644e8fb42:mem0/configs/prompts.py::ADDITIVE_EXTRACTION_PROMPT`（约 468–548 行），以及 `mem0/memory/main.py::{add,_add_to_vector_store}`。只移植 ADDITIVE prompt 中“从新输入提取新增事实、结合有限已知事实避免重复、原子化表达”的部分；不移植向量存储、Mem0 DB、历史表。Mem0 hash 只对有限 top-10 检索候选和当前 batch 去重，不能写成全局幂等保证。抽出的事实是候选，更新/冲突由 M4 与用户拍板规则处理。
3. **episode 保留原消息**：`nemori-ai/nemori@d2a6dff6e5481214a0be6a2d10147feccfc16244:core/memory_system.py:76-162,197-212`（buffer/episode pipeline），`llm/generators/episode.py:30-84` 对 source messages 与 episode 摘要的结构。参考 episode 同时保留来源消息关联和语义总结；Atlas 不复制 Nemori PostgreSQL/Qdrant，原文仍由 SessionDB 持有。
4. **前次抽取与 transient retry**：`mastra-ai/mastra@a15924e709dd5d9439a6c102901c326ab0ec77fb:packages/memory/src/observational-memory/{extractor.ts,sync.ts,async-buffer.ts,retry.ts,observational-memory.ts}`：`extractor` 中结构化 schema，`sync`/`async-buffer` 传递 previous extraction，`retry` 对临时错误退避，`observational-memory` 调用 Observer。移植“传入上次已生成的经历/事实以避免重算”和 transient retry 思路，不移植其 thread metadata/数据库。已有状态只作提示上下文，不构成第二真源。
5. **行为参考而不复制**：`basicmachines-co/basic-memory@a72751c5d626380dedeed30f55f7a80ba3dc710d` 为 AGPL；只参考 Markdown 可读编辑与 DB/文件协调行为，**不得复制代码、提示词或实现段落**。

## Atlas 路径核对与文件所有权

本节只分配 M3 独占文件，避免与并行 M1/M2 冲突。

| 文件 | 状态 / 文件所有权 | 计划函数和修改边界 |
|---|---|---|
| `core/atlas/memory/library/extract.py` | 现有；M3 独占 | `SYSTEM_PROMPT`、`SCHEMA_HINT`、`Proposal`、`Episode`、`parse_output`、`apply_episode`、`apply`：变成双层输出契约（详细经历 + 候选原子事实）；保留 secret scrub、时效和 tombstone 保护。`build_messages` 在当前 `extract.py` 是 module 函数，施工时按代码核实其签名。M7 不拥有/修改此文件。 |
| `core/atlas/memory/library/__init__.py` | 现有；M3 独占 | `MemoryLibrary._drain/observe_turn/_write_diary/_extract_full/_extract/_apply`：改为按来源会话组装详细输入、使用上次抽取提示上下文、先原子地写 Markdown 经历/候选后再更新可重建队列状态。现状通过 `schedule_turn`、queue、model manager 调用提炼。 |
| `core/atlas/memory/library/queue.py` | 现有；M3 不拥有，由 M1 独占队列生命周期 | M3 仅通过公开 `pending/remove/fail` 现有接口消费；如需标记 output/no-output，先与 M1 在接口层协商，不直接改 M1 文件。 |
| `core/atlas/memory/library/store.py` | 现有；M3 不拥有，由 M2 独占 | 使用 M2 的 Entry/metadata/source_ref 写入接口，不新开第二账本、不改 Markdown 编解码实现。 |
| `core/atlas/memory/library/sources.py` | 现有；M3 不拥有，由 M2 独占 | 通过 M2 的 `open_ref` 接口验证会话经历和事实可回到 SessionDB 原文。 |
| `core/atlas/agent/run_phases.py`, `core/atlas/kernel/loop.py` | 现有；M3 不拥有，由 M1 独占 | 输入需从 M1 提供的 UID 指针与 SessionDB 消息读接口获得。 |
| `core/atlas/memory/library/m3_prompt_zh.md` | **新建**（如果 prompt 拆分为资源文件）；M3 独占 | 只存版本化中文提示词，不存用户/会话内容。若沿用 `extract.py` 内常量则不新建此文件。 |
| `core/atlas/memory/library/claim_resolution.py` | **新建；M7 独占** | M7 提供纯冲突判定接口，输入 M3 产出的 Claim 候选与历史 Claim 元数据，返回胜出候选及旧项 `superseded/retracts` 关系；M3 不调用它，后续 M4 在其独占文件范围内接线。 |

Atlas W2 library 实际清单为 `__init__.py, cleanup.py, dream.py, embed.py, extract.py, forget.py, hybrid.py, index.py, queue.py, sources.py, store.py`；不存在本任务书旧版提到的 `models.py` 或 library 下 `session_sync.py`。SessionDB reader 是 `core/atlas/engine/session_sync.py`。

## 提示词中文迁移契约

Codex stage-one 和 Mem0 additive 提示要翻译成中文，禁止仅保留英文模板或英文注释。M3 中文主提示至少明确：

- 先写“详细经历”：目标、每个决定及原因、实际涉及路径/文件、实际执行命令、报错原文（保留语言与标点）、所有关键数字及单位、成功/失败结果、未完成事项、用户纠正和纠正前后变化；另写一段会话回顾，概括过程顺序。没有证据的字段留空/数组为空，禁止脑补。
- 事件/工具/外部 Agent 内容均通过 M2 的 `source_ref` 回到 SessionDB；不把助手或 Agent 的判断冒充用户陈述。经历中的观点保留其实际说话者和来源等级。
- 另输出可选原子事实候选：生活和个人事实必须覆盖，例如身份、居住/工作、家庭和关系、健康、习惯、喜好/厌恶、饮食/过敏、目标与计划、在做的项目、长期约束；临时事实要带有效期。只把有来源支持的内容列为候选；新信息才 ADD，重复信息不重复输出。推断可以记录为低等级候选并明确标注，不能混成用户原话。
- 用户纠正永远最高；冲突来源等级按“用户陈述 > 工具观察 > 模型推断”；同等级较新有效事实胜出，旧值标 `superseded` 留在历史。M3 只标注候选关系，最终合并依 M7/M4 的裁决流程，不能静默删除历史。
- “没有原子事实”不等于 no-output；只要会话包含值得回顾的过程/决定/文件/错误/数字/未完成工作，就输出详细经历。闲聊/确认语等才可 no-output。

输出 schema 至少包含 `episode:{title,summary,decisions:[{text,reason}],files,commands,errors,numbers,unfinished,user_corrections,source_refs,source_level}` 与 `facts:[{key,value,source_level,recorded_at,valid_from,valid_to,supersedes,retracts,source_ref}]`。经验证据映射后才提交；schema 失败不可消费队列水位。

## 触发时机（Claude 定稿补充）

- **每轮结束（轻量，保留现状）**：照旧写日记 + 抽这一轮里明确的事实候选，让下一轮马上能用到。
- **会话空闲 30 分钟或会话结束（完整）**：照 Codex phase1，对整段会话生成详细经历 + 会话回顾 + 原文指针；同一会话再次活跃后，下次空闲只对新增部分增量更新同一条经历（用 `source_ref + extractor_version` 判重），不另起一条。
- 子 Agent / 外部 Agent 的会话由 M1 的 `on_delegation` 交过来，同样走完整提炼，并在经历里写明执行者。

## 逐步施工清单

1. 在 A0 后确认当前实现：打开 `extract.py` 与 `library/__init__.py`，记录实际 `SYSTEM_PROMPT/SCHEMA_HINT/build_messages/parse_output/apply/MemoryLibrary._drain/observe_turn/_extract_full/_apply` 签名；确认 queue/store/sources 接口归 M1/M2 所有。
2. 以 Codex stage-one 为主写中文 prompt/schema，先能产出完整经历，再从同一证据抽 facts。经历按会话独立落条，记录来源 UID 和抽取器版本；内容不可因 fact 为空而丢弃。
3. 原子事实层借 Mem0 additive prompt：向 prompt 提供本轮新消息、现有候选 fact 的有限摘要、上次提炼结果及时间上下文；只做新增候选，不能依赖 top-k hash 作为跨历史全局去重或水位。
4. 对同一会话的工具/用户/助手消息按 M2 UID 排序，保留错误原文和数字；episode 中可摘要，但 `source_refs` 必须能逐条回到原始消息。外部 Agent 输出已进入 Atlas transcript 的部分与其他 tool/assistant/user 来源等同处理。
5. 参考 Nemori 的 episode+source linkage 与 Mastra previous extraction/retry：将上一版本 episode/facts 作为上下文，Transient provider/JSON 错误按有界指数退避重试；稳定的内容校验/提示问题记录为失败并让 M1 队列可恢复，不伪装成 no-output。
6. 持久化顺序：先以一笔 Markdown git 修改写 episode 与 fact candidates，再确认写入成功，最后调用队列成功标记。Markdown 写失败不得推进消费水位；进程中断可根据 `source_ref + extractor_version` 找到已完成产物并避免重复追加。
7. 冲突仅按本轮已拍板规则附元数据：用户纠正最高；不同等级取较高；同等级取较新。保留被 superseded 内容于历史；M3 不复制 M7 的时态关系引擎，也不覆盖用户手改段落。
8. 去掉目前 `extract.py` 中“事实只能源于 user_text、quote 必须逐字出现在 user_text 才能保留”的唯一准入假设；替换成 source_level + source_ref 证据核验。保留 secret scrub 与遗忘墓碑过滤；不要删忘记逻辑/临时事实过期逻辑。
9. 对已有页面做一次只读盘点后再迁移：旧 facts 只补 `source_level=user_assertion` 当旧 `src` 能证明用户陈述；`tool` 只能明确证明工具观察；无法证明统一 `legacy_unknown`。不从摘要反推精确 UID。已有 diary/episode 可依据可用 SessionDB 引用补生成回顾；没有原对话就保留原内容并标 legacy，不覆盖人工文字。
10. 删除旧的“只有 fact 候选才写 diary/episode”分支和重复抽取调用；保留 `MemoryLibrary` API、人工编辑、`store.py`/git 历史、tombstone 与既有页面。过渡期不双写第二份事实表，SQLite/FTS/向量只从 Markdown 重建。

## 最小真实使用验收

- 真实 Atlas 会话包含一次决策及理由、两个文件路径、命令、原始错误、数字、用户纠正和未完成项。落地的 Markdown 经历保留这些细节，逐条 `source_ref` 能打开 SessionDB 原文；用户只问“上一轮为什么这么改”时，召回内容足以答出理由。
- 一段会话含用户生活事实（例如居住/工作/家庭/健康/偏好之一）、工具观察和模型推断。检查 Markdown 候选有正确 source_level/ref；外部 Agent 返回的重要细节也经同一 M3 路径提炼。
- 再运行一次同一 source UID 与 extractor version：不重复追加经历/候选；模拟第一次模型超时后重试，可从日志看到 attempts 和最终 outcome；失败时队列未被误标完成。
- 仅有闲聊时可 no-output；有丰富工作经历但没有任何新原子事实时，仍有 episode、会话回顾和原文指针。
- 用户手工改一条 Markdown 事实后重建派生索引，人工文本保留。记录 prompt version、source UID、事实候选数、经历写入与队列状态；日志不再复制整段原文。

## 依赖、并行与停止边界

M3 依赖 A0 与 M2 已冻结的 SourceRef/Markdown 元数据接口；可与 M1、M7 并行。M7 同样依赖 M2 的来源/Claim 元数据契约，并消费 M3 冻结的 Claim 候选字段（`key,value,source_level,recorded_at,valid_from,valid_to,supersedes,retracts,source_ref`）；并行开工前由 M3/M7 先确认此纯数据接口，不相互改文件。M7 独占新建 `claim_resolution.py`，实现确定性冲突判定，不拥有 `extract.py`；M3 只生成带证据的候选，不接调用。之后 M4 在自己的文件所有权内，将合并流程接到 M7 接口。文件所有权：M3 独占 `extract.py`、`library/__init__.py` 和可选新建中文 prompt；M1 独占 `run_phases.py`、`kernel/loop.py`、`lifecycle.py`、生命周期队列改动；M2 独占 `engine/session_sync.py`、`sources.py`、`store.py`、`source_ref.py`；M7 独占 `claim_resolution.py`。M4 等 M3 episode/fact 输出稳定后施工；M8 依赖 M3/M4/M7。此任务不实施 M4 合并接线、不改检索排序、不建设独立账本、不移植任何上游 Rust/AGPL 代码。
