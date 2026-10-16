# TASKBOOK-M8：把已验证的任务经验晋升为 Skill 候选

状态：待后续施工。本文件只定义后续实现范围，不表示现有流程已上线。

## 目标与权威边界

将多次、可复用且有成功证据的操作经历生成可读的 Skill 候选；经过真实任务验证和用户查看后才成为 live skill。记忆事实与 Skill 产物分开：经验、来源指针、成功/失败依据保存在 Markdown+git 记忆库中，该库是唯一权威；SourceEvent/SourceRef 仅指向 SessionDB 原文，不复制 transcript。候选 Skill 包、验证结果缓存、运行统计和索引均是可重建派生物，遗忘时由 M7 沿来源派生链清除。不得增加独立经验账本、SkillMemory 数据库或第二份来源真源。

来源证据至少包含可复核的经历条目及 source_ref；候选不能仅凭高模型置信度或工具调用文本生成，也不把未经验证的任意调用直接变成可执行脚本。外部 Agent 有完整执行权限；其运行结果由 Atlas 作为输入交给 M3 提炼，再由 M3 提炼为有来源的 Markdown 经历。

全局固定默认值：Basic Memory AGPL 只作行为参考，不复制代码；用户纠正永远最高，其次按 user（用户陈述/编辑）> tool（工具观察）> model（模型推断）排序，同级新主张胜出、旧主张以 `superseded` 留在 Markdown 历史；遗忘沿派生链删除条目、摘要、索引和技能候选，只留 W0 已有内容哈希墓碑；M9 默认只跟 `[[links]]` 一跳，PPR 默认关闭，真实使用证明收益后再开。

## 固定上游依据（只迁移机制与提示词）

- `microsoft/SkillOpt@343db229dbd5ddaf9df6b1d5540d8bcdb2604d5c:skillopt_sleep/cycle.py:run_sleep_cycle`（625、797–820、989–1039、1090–1093）、同文件验证/晋升门（271–286、379–434）、`staging.py:adopt`（3028）：借用 train/heldout 分离、重放比较、先 staging 后晋升。它的 strict improvement 是配置的 aggregate metric；不能推成每个 holdout 都提升的保证，gate_mode 可被配置关闭，因此 Atlas 明确保持默认 gate 开启，关闭时不得自动晋升。
- `MemOS local-plugin@a7367d07e55db61099f7b4e2c1108bc5831a24f3:core/skill/eligibility.ts:evaluateEligibility/decide`、`verifier.ts:verifyDraft`、`crystallize.ts`、`lifecycle.ts:applyFeedback/applyTrial`、提示词 `skill-crystallize.ts`：移植证据数量/成功锚点、反例、候选—试用—归档的生命周期以及格式校验失败后带错误上下文重试一次。将所有生成提示翻译为中文；尤其将 “Don't invent guidance unsupported by the inputs.” 翻为“不得编造输入材料没有支持的操作指导”，并要求每步都能指回经历/原文。注意本地拆解的 MemOS 插件根许可 Apache-2.0；实施若从拆解源搬代码，另核对对应源文件和许可。
- `NousResearch/hermes-agent@607a0b0d41e07d903c0b475dd72fb6ac2b37fecc:agent/background_review.py:_run_review_fork/spawn_background_review_thread`、`tools/skill_manager_tool.py:_create_skill/_patch_skill/skill_manage`、`agent/curator.py:apply_automatic_transitions`：借用后 turn review、先改进已有 skill 再扩充支持文件、避免每个 session 新造 skill。Hermes 仓库 MIT；仅移植必要的小段流程，不整合其 agent runtime。
- `openai/codex@092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`（v0.162.1 快照）：`codex-rs/memories/write/src/phase2.rs:run`、`templates/memories/consolidation.md` 中重复程序/省时判定、skill 格式段落；只借准入判据与渐进文件结构，不移植 Rust。Codex 许可按该快照根 Apache-2.0。
- Basic Memory `basicmachines-co/basic-memory@a72751c5d626380dedeed30f55f7a80ba3dc710d` 为 AGPL-3.0-or-later，**只作为行为参考，不复制代码**；本任务不需要依赖 Basic Memory。

## Atlas 路径审计与目标文件所有权

已打开 `D:\atlas-mem-w2-api`（HEAD `aa14c3173392d0fc60ec3e401e4495a2d3357cb7`）。真实现存目标 `core/atlas/evolution/skill_sleep.py` 有 `harvest_atlas(state_db, since_iso)`, `run(dry_run)`；`core/atlas/skills/__init__.py` 有 `SkillManager.register_skill_source/scan_skills_sync/list_skills/default_skill_sources`。memory library 实际由 `store.py,extract.py,dream.py,forget.py,index.py,queue.py,sources.py` 等承载；没有 `memory/library/models.py`。本任务施工基线是 A0 合并后的 `ui-redesign`，开工时仍须核对下列现存函数。目标文件不存在则标新建；不得按路径审计之外编造 Atlas 现成 API。

| 文件所有权 | 修改/新建的函数与产物 |
|---|---|
| `core/atlas/evolution/skill_sleep.py`（M8 独占 adapter） | 修改现有 `harvest_atlas`：从 M3 Markdown 读经历与来源指针，不再直接扫 `state.db` 原始会话；修改 `run`：调候选生成、重放评估和 staging。保留 `evolve_memory=False`；将当前 `auto_adopt=True` 改为 false，由用户查看候选后才晋升。 |
| `core/atlas/evolution/skill_candidate.py`（**新建**，M8 独占） | 新建候选结构与 `build_candidate/validate_candidate/score_candidate`；输入为 Markdown 经历与真实反馈，产物带来源 ref、适用条件、步骤、反例、验证集和版本。 |
| `core/atlas/evolution/skill_staging.py`（**新建**，M8 独占） | 新建 `stage_candidate/promote_candidate/archive_candidate`；候选存于现有 SkillOpt staging 根或对应 learned-skill staging 文件夹，标为派生物，可按来源重建；不要新建记忆事实数据库。晋升必须先过默认验证门并由用户查看确认。 |
| `core/atlas/skills/__init__.py`（M8 限于读取接线；仅当 A0 基线仍相同） | 复用现有 `SkillManager.register_skill_source/scan_skills_sync/list_skills/default_skill_sources` 挂载已晋升版本；不重写同名优先级和现有来源注册。 |
| `core/atlas/memory/library/forget.py` 与 `store.py`（M7 所有） | M8 不直接改；向 M7 提供 source_ref→candidate 文件映射/清理回调契约，使遗忘能删候选、指标缓存、摘要与对应 git 历史内容，仅留哈希墓碑。 |

M8 拥有以上 evolution adapter/new files；不得更改 `store.py/extract.py/dream.py` 的写入协议。候选和运行结果不得成为新的持久事实真源。若 SkillOpt 在 `ui-redesign` 中已存在 staging/runner，复用它并删除对应新建计划，避免复制一套候选状态机。

## 逐步施工清单

1. 以 A0 合并后的工作树审计 `skill_sleep.py`、SkillOpt 版本、真实 staging 位置、SkillManager 注册语义和现有候选存量；记录旧来源与新入口的映射。真实目标函数变化时先更新本任务书实施记录，不猜函数。
2. 定义经历到候选的最小输入 schema：`experience_id/source_ref/source_level/recorded_at/task/outcome/verified/steps/files/commands/open_items`。仅从 M3 的 Markdown 读入；SessionDB 内容通过指针按需读取，不缓存为另一份原文账本。
3. 在中文提示中要求归纳重复流程、目标、适用前置条件、逐步操作、验证办法、反例/边界、失败恢复、引用经历；明确不得补造未出现的命令/工具参数/安全规则。生活类记忆可作为任务经验的适用背景，不自动生成个人偏好型技能。
4. 准入候选：相同操作至少重复两次，并在 Markdown 经历里有可核的成功结果；错误/未完成轨迹作为反例。若技能已存在，先提出对现有版本的有来源修订，不新建重复包。格式或出处校验失败时只允许一次带错误信息的纠正生成，第二次失败保留拒绝原因并停止。
5. 从候选拆分 train/heldout 真实经历，使用现有 Atlas 模型/工具运行器做有限重放。默认 gate 开启：configured aggregate quality 必须严格高于 baseline，且不得出现安全或正确性 blocker；样本不足、结果持平、回归或 gate 未运行一律留在 staging/rejected，不晋升。将 benchmark 项、模型、工具、成功标准写入候选 Markdown frontmatter/伴随 metadata，不生成独立数据库真源。
6. 用户审阅 stage diff 后，生成独立版本并挂到现有 SkillManager 来源。运行一次真实同类任务，记录完成/失败、耗时或返工变化为 M3 可吸收的经历反馈；SkillOpt validation 通过不代表 every task 保证成功。
7. 处理遗忘：由 M7 对来源引用查询候选及已晋升 skill 派生链；清理候选、由该事实直接派生的步骤/片段、评估摘要及索引。若 live skill 混有其他独立来源，不删整包，只移除命中段落并更新来源，或将不可安全拆分的包标为需人工重建。只保留 W0 哈希墓碑防再摄取。
8. 真实使用后检视来源可追溯性、版本 diff、拒绝/晋升日志和 forget 清理日志；在重启后复查候选和 SkillManager 列表。

## 旧数据与代码处理

保留 `skill_sleep.py:run` 当前与 SkillOpt 的调度入口及 `evolve_memory=False`。替换其读取原始 state DB transcript 的 harvest；关闭当前 `auto_adopt=True`。不把旧 skill 目录扫描结果直接认作真实经历；旧 skill 缺少 source_ref 时标记 `legacy_unattributed`，允许用户继续使用，但不自动纳入新的验证或遗忘派生链。沿用 SkillManager 多来源索引和优先级；不复制数千个技能到记忆库。删除/停用旧流程中任何直接以单次工具调用写 live skill、无验证就自动晋升、或把记忆 dream 与 skill 晋升耦合的路径。修改须保留现有 SkillOpt 配置，但 Atlas 默认 gate 不能关闭。

## 最少真实使用验收（使用与日志，不建大型测试）

- 选一个真实重复 workflow，从至少两条 M3 Markdown 经历生成候选；人工点开每个步骤的来源 ref，确认中文指导没有新造输入之外的命令或结论，格式失败最多纠正一次且有日志。
- 用一条成功和一条失败/未完成经历构造 heldout，实际运行比较 baseline/candidate；日志记录数据集、模型、工具和 aggregate 指标。持平/下降/样本不足时仍为 staging/rejected；有提升也必须由用户查看后才晋升，live skill 先生成新版本并可回滚。
- 在真实任务上运行晋升版本，检查 Atlas SkillManager 能列出并调用正确版本；将实际成功/失败回写为 M3 可读取经历。
- 忘记一条被候选引用的经历，检查派生候选/摘要/评估数据清除、来源段落撤回且重启后不再出现；与该事实无关的 skill 内容保留。

## 依赖、并行与完成边界

依赖 M3 详细经历与 source_ref、M4 Markdown 写入协议、M7 时间/纠正/遗忘 lineage。按总施工序列在 M3/M4/M7 完成后开始；可与 M6 的 broker 文件在无共享 ownership 时并行。M8 独占 `core/atlas/evolution/skill_*` adapter 文件；如需更改 SkillManager 注册文件，必须先由总协调者在 A0 基线冻结冲突边界。M8 不负责记忆提炼、记忆召回或 UI 设计。
