# Atlas 记忆源码调研｜R 总裁决（返工版）

日期：2026-10-16。已按 Claude 验收意见修订。此文档是后续施工裁决，不表示已施工。

## 最终架构

**唯一权威真源是 Atlas 透明 Markdown 记忆库及其 Git 历史。** 条目中的来源等级、记录时间、有效时间、取代/撤回关系和原文引用写入 Markdown frontmatter 或行内元数据。原文仍保存在 Atlas SessionDB；`SourceEvent` 只保存 SessionDB conversation/message/tool 指针，不复制原文。SQLite、FTS、向量、链接图、队列、使用统计和缓存都是可从 Markdown 与 SessionDB 重建的派生数据，不设独立事实库或证据账本。

流程：会话与工具事件留在 SessionDB → M2 形成精确指针 → M3 以 Codex Phase 1 流程提炼详细经历与回顾，并用 Mem0 ADD 从中抽取原子事实候选 → M7 按拍板规则判定当前事实状态 → M4 将有来源的变更安全写入 Markdown/Git → M5/M9 从文件重建派生检索结构 → M6 将上下文交给外部 Agent，返回结果再回到 SessionDB/来源指针并交 M3 → M8 从可追溯经历中形成独立 Skill 候选。

## 模块选择

| 模块 | 结论 | 源码参考与边界 |
|---|---|---|
| M1 生命周期 | Hermes hooks 为事件模型；结合 Claude/OpenClaw hook 事件与 Codex 工作队列的失败重试 | hook 触发持久任务，不要求 hook 本身完成提炼 |
| M2 原文指针 | Atlas `core/atlas/engine/session_sync.py` 的 `message_uid` 为原文身份；参考 Codex rollout/citations 与 AMA `traj_get/traj_find` | SourceEvent 是指针，不复制原文。Codex统一使用官方 Rust v0.162.1 快照 `openai/codex@092d3acd6bec3e3a14bdc7e7a2810ab628ab759d` |
| M3 提炼 | **Codex Phase 1 为主**：翻译并改写 `stage_one_system.md` 的提示词与 `phase1.rs` 流程。每个会话产出详细经历 + 会话回顾 + 原文指针。Mem0 ADDITIVE 只从经历补抽原子事实；Nemori 带原消息 episode、Mastra previous extraction/重试作补充 | 不移植 Rust。保留决定和理由、文件、命令、错误原文、数字、未完成事项和用户纠正；补入生活/个人事实、偏好、计划。不是只有原子事实的存储 |
| M4 整合 | Codex Phase 2 控制流 + OpenClaw host-side plan/lineage/exact-match 文件校验 | 模型只提案，host 重读当前文件后应用；每个来源版本提交成功再记处理状态。Basic Memory core 是 AGPL，只作行为参考，不复制 |
| 透明库 | Atlas Markdown + Git 唯一真源；借 Codex baseline diff 与 OpenClaw current-file/hash guard | 用户直接编辑受保护；其他状态均派生。Git 记忆库的本地提交是内容提交边界 |
| M5 读取 | Mem0 hybrid/rerank fallback、Claude-Mem 按需下钻、Codex citations/use stats、mnemostack 有界重试 | 结果可引用到 SessionDB 原文；派生索引失败可重建 |
| M6 委派 | Hermes `on_delegation` + Atlas ContextBroker | 外部 Agent 在用户委派任务中拥有完整执行权；派发前送相关记忆，执行中可再取，结果收回后交 M3 提炼。 |
| M7 变化事实 | Graphiti 双时间与 invalidation 规则，不引入其图服务 | 字段写 Markdown；冲突固定按本文件“用户拍板规则” |
| M8 技能 | MemOS eligibility/verifier/lifecycle + Atlas SkillOpt staging | 技能与长期记忆分开；保留来源与验证记录，默认不自动 adopt |
| M9 联想 | Markdown `[[links]]` 一跳；A-MEM 作 link suggestion 参考，HippoRAG 2 PPR 作可选扩展 | PPR 默认关闭；先用一跳，真实使用证明有收益再启用 |

## 已拍板规则（施工任务书默认，不再作为待确认项）

1. Basic Memory 是 AGPL，只当行为参考，不复制代码。
2. 用户纠正永远最高；其他冲突按来源等级：用户说的 > 工具观察 > 模型推断。相同等级取新值；旧值保留并标 `superseded`。
3. 遗忘沿派生链删文件、索引、摘要和技能候选内容；只留 W0 已有的内容哈希墓碑，阻止重新导入。
4. M9 PPR 可选且默认关；默认沿 `[[链接]]` 多看一跳。
5. 外部 Agent 在用户委派任务中拥有完整执行权；结果回 Atlas 走 M3 是数据流。
6. Markdown+Git 记忆库是唯一权威；SessionDB 是既有会话原文源。`SourceEvent` 只是指针。SQLite/FTS/vector/图/队列/统计都可重建。

## 与 GPT V4.2 A0–A7、Claude M1–M8 映射

| 施工合同 | GPT V4.2 | Claude |
|---|---|---|
| A0 W2 上线与运行基线 | A0 | 前置 |
| M2 原文指针与来源事件 | A1/A2 | M2/M3 |
| M1 生命周期 | A2/A4 | M1/M6 |
| M3 会话提炼 | A1/A2 | M3 |
| M4 透明库与整合 | A2 | M4 |
| M5 召回/引用 | A3 | M5 |
| M6 委派 | A4 | M6 |
| M7 时间事实/纠正/遗忘 | A5 | M7 |
| M8 Skill 晋升 | A6 | M8 |
| M9 联想（补充） | A3 关联检索 | M4/M5 链接 |
| 多模态字段预留 | A7 | M1/M2 |

## 施工顺序与并行

**A0 → M2 → M1/M3/M7 并行 → M4；M5/M9 在 M2 后并行；M6 依赖 M1/M2/M5；M8 依赖 M3/M4/M7。** A0 把 W2 合入当前 `ui-redesign` 并完成运行验收；所有 M 任务以该合并后的 `ui-redesign` 为基线。每份任务书载明 ownership，禁止多个任务同时改同一文件。

## 边界

视觉、语音、手机等只研究并预留 event metadata，本轮不接入采集器或多模态处理。没有开始 A0 或 M1–M9 施工。

SURVEY REWORK DONE
