# Atlas 原生认知记忆：面向迁移的设计草案（不提前锁库）

## 0. 区分三种要解决的东西

- **原始经历（证据）**：用户消息、模型回复、工具调用、命令输出、截图/录音的引用、工作目录、版本、错误与验证。应能追踪事件和时间，也应能按用户要求删除相应副本。不能为了召回频繁复制原始大文件。
- **整理后记忆（派生认知）**：事实、偏好、人物与项目、状态、决策、理由、失败模式、方法、承诺、反例、推断；每条可以改、失效、变更来源，绝非不可错的原文。
- **执行资产**：经核实有效的 Skill / SOP / runbook、触发条件、适用环境、测试证据和反馈，不与“我听说过这么做”混淆。

## 1. 建议测试的三种底层架构（都允许推倒现有实现）

| 方案 | 实际持久化 | 好处 | 主要风险 | 推荐判断 |
|---|---|---|---|---|
| **A 文件证据 + SQLite 结构化派生** | engine 原始事件 / 少量 Markdown 用户可编辑面；SQLite 存 fact/episode/edges/FTS，向量可选 | 无服务、Windows 轻、迁移成本低；用户手工可读 | 同时维护文件和 DB 需明确谁为真、事务及删改一致 | 如 A/B 测试可达到目标，优先成本最小 |
| **B 单体 PostgreSQL + pgvector** | 大部分结构化事实、事件、引用、边、向量及全文索引统一到 Postgres；文档/媒体大文件在文件系统 | ACID、复杂关联和跨设备扩展性强，适合多 Agent | 常驻数据库服务、部署/恢复成本；不保证比 SQLite 快 | 如果 Atlas 计划多人/多设备共享且 A 在真实负载不够，作为候选 |
| **C Hindsight/Graphiti 等库内核深改** | 复用一个开源核心框架的表/检索/归纳设计，逐渐替换其宿主 API 为 Atlas runtime | 可能获得成熟的多路检索、时间链和批处理 | 抽掉原运行时后维护成本高、生命周期受上游设计影响；有“换个外壳的插件”风险 | 原生化迁移总量明显少于 A/B 时可胜出 |

不必强行“一套物理数据库”：Media blob、原始日志、结构化事实的最优存储本来可以不同。真正必须统一的是 **主体标识、写入权限、状态变更契约、检索与技能使用反馈**。

## 2. 逻辑数据模型（算法决定后再落库）

```text
MemoryEvidence
  event_id, session_id, turn_id, parent_run_id, agent_id, device_id
  event_kind, observed_at, workspace, artifact_ref, content_hash
  tool_name, tool_error, verification_ref, source_role

MemoryClaim
  memory_id, semantic_type, scope_id, subject_key, predicate, text
  asserted_by, epistemic_status [candidate, accepted, disputed, rejected, stale]
  valid_from, valid_until                 # 何时在世界里成立
  recorded_at, superseded_at             # 系统何时记录、撤销判断
  source_event_ids, supersedes_ids, reject_signature
  importance, relevance_hints, embedding_ref

MemoryEpisode
  episode_id, task_id, goal, environment, outcome
  step_event_ids, failures, verification_ref, decision_rationale
  participants, started_at, ended_at, project_id

MemoryProcedure
  skill_id, version, trigger, preconditions, procedure, success_checks
  positive_episode_ids, counterexample_episode_ids
  skill_runner_ref, last_verified_at, capability_status

MemoryUseTrace
  query_id, trigger_reason, candidate_ids, returned_ids
  used_ids, action_id, resulting_verification_ref
```

这一模型是**语义要求**而非建议立即建 30 列大表；优先存最稳定的证据/状态字段，允许附件 metadata。

## 3. 运行链路：Atlas 自己的逻辑，优先复用别人的算法

```text
接收 [chat/tool/CUA/屏幕/语音/子Agent] 事件
   ↓ 原始证据 journal / 引用，不阻塞模型
触发的事件归类/压缩 (Mastra OM, Claude-Mem)
   ↓
MemoryWriteGateway: 来源隔离、scope、双时间、冲突、纠错/遗忘 (Graphiti)
   ↓
结构化 claim / episode / 关联索引
   ↘ 异步 consolidation jobs：ReMe checkpoint & integration
   ↘ 离线策略归纳：MemOS L2 + ReasoningBank
   ↘ 验证技能候选：Atlas SkillOpt

对话开始 / 工具出错 / 新子任务 / 验证前 / 用户提及旧事
   ↓ RecallRouter：触发预算 & 检索方式 (MemOS retrieve)
   ↓ FTS / BM25 | dense | 时间/元数据 | 关系邻域 (Hindsight fusion)
   ↓ 权限 & 可信度 & 有效性过滤 → 去重融合/RRF → 需要时 rerank
   ↓ L0候选摘要 → L1相关依据 → 按需展开原始证据L2 (OpenViking 思路)
   ↓ 决策、行动、技能调用
   ↓ MemoryUseTrace 与实际验证反馈
```

## 4. 操作系统式核心不是“所有数据装进一个 prompt”

- `working context`: 当前任务状态+最近关键节点，随着执行持续更新，非永恒记忆。
- `stable profile`: 用户明确确认的身份、偏好、长程承诺，低频更新，可控制。
- `episodic memory`: 事件与任务，按来源/时间可回放，不以一条每天摘要取代轨迹。
- `semantic/relational`: 经证据支持的关联与知识；事实变化保留正确的时间视图。
- `procedural`: verified Skill/策略，不与普通 fact 同态。
- `prospective`: 持久承诺与触发条件属于任务/调度状态，不是“搜索一下记忆就能准时提醒”。

## 5. 重要的工程裁决（反对虚假的最优性）

1. **不要在没有数据前就喊换 Postgres**；单机 2~10 万条记忆与多用户高并发结论可能完全不同。比较索引构建、常见查询、并发写入、迁移、维护成本。
2. **不要盲目追全程向量化**；错误码、路径、符号名、时间跨度，词法与结构检索常常更好；中文切词要专项验证。
3. **不要把“多次重复提到”当成“已被验证”**；相同回答反复从记忆中回流会放大错误，需要记录独立证据源数量。
4. **不要所有记忆自动提升为 Skill**；实际工具结果、环境前置条件和可重复验证是晋升依据，学习失败本身也要记。
5. **不要混淆用户授权和模型推断**；多 Agent 间跨项目共享要区分“能看”与“能改”。
6. **删除与审计可能冲突**；把审计事件和个人明文分开。删除命令必须定义范围，不能宣传“任何备份、任何日志都已删除”而不检查。
7. **建立回放和影子比较**：为竞争候选运行相同真实 Atlas 事件；这样即使选错最初存储也能平滑替换算法，不再从头造轮子。

## 6. 用户体验目标

- “还记得我们上次修复 502 的事吗？” 应答出原因、有效步骤、验证和不确定项，并能跳转源任务。
- 同一个错误在执行途中出现时**主动**找旧经历；但不同工作目录/依赖版本则提醒不一定适用。
- 用户纠正“不是 A 是 B”，B 进入有效事实，A 保留可见历史或在真正遗忘时被覆盖，不再因巩固自动复活。
- Claude/Codex/Atlas 通过不同设备处理同一项目时可以继续任务，但子 Agent 的错误猜测不能自动转成用户事实。
- 用户能查询“你为何记住这条/这条来源是什么/哪些技能是你学到的”，不只能看到一堆 MD 文本。
