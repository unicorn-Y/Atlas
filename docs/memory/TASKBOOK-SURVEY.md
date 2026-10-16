# 任务书：Atlas 记忆系统 · GitHub 记忆项目源码级横向调研（2026-10-16）

> 只做调研和裁决，**不改 Atlas 代码**。用中文写。速度优先，大量使用子智能体并行（GPT-6 Luna 高），主对话只负责分派、汇总和把关。

## 0. 背景：用户已经拍板的决定（不要再问，不要改）

1. Atlas 是**唯一**的长期记忆主体。Codex、Claude 等外部 Agent 只是工具，权限全开。派活时 Atlas 先给一份相关记忆，执行中它们可以再要，做完的结果收回 Atlas。
2. 别家的记忆系统要**翻译成 Atlas 自己的**：读源码，把好的部分移植、改造进 Atlas。不装插件，不在后台跑别人的服务，也不是看完自己从头写。
3. **不迁就 Atlas 现有架构**：W0/W1/W2、Markdown、SQLite 都可以换。
4. **取消「只认用户亲口说的」**：Atlas 自己做过的事、经验、推断都要记，但每条要标来源等级（用户说的 > 工具观察到的 > 模型推断），冲突时高的赢。
5. **透明记忆库必须保留**：用户能看到每天的变动，也能直接改。用户手改的内容不能被重建覆盖。
6. 最终覆盖聊天、任务、电脑、浏览器、手机、视觉、语音。视觉/语音/手机只研究和预留字段，不施工。
7. 目标是每个细节都比最强那家好（对标 CC、Codex、Hermes、OpenClaw、OpenCode、Pi、ZCode）。评审时**只做加法补最强机制**，不要以「太重」为理由砍能力；但也不要为显得高级而堆复杂度。

## 1. 已有材料（先读，别重做）

- **GPT 的研究**：分支 `research/atlas-memory-2026-10-16-handoff`。先读 `docs/research/atlas-memory/2026-10-16/V4_统一总纲_架构与技术裁决.md`、`V4_1_源码级原生移植裁决与替换矩阵.md`、`V4_2_原生施工任务书与接口契约.md`。B 报告和候选矩阵在 `source/` 下。**不要把仓库里的 zip 解压进 git。**
- **Claude 的评审**：本分支 `docs/memory/CLAUDE-REVIEW-V2.md`。当前的骨架假设是「Codex 两阶段管线 + Hermes 钩子 + 透明 Markdown/git 作真源 + 来源等级 + 页面 [[链接]] 联想」。**这个假设要被本次调研检验，可以推翻**，推翻时要给出源码证据。
- **已经核实过的，不用再查**：
  - ReMe dream 的 schema/extract/integrate/finish 四个文件；
  - MemOS 的 `retrieve.ts` 和 `eligibility.ts`；
  - Hindsight 的 `fusion.py`；
  - AMA 的 `retrieve.py`；
  - Codex 的 `codex-rs/memories`；
  - Hermes 的 `memory_provider.py`。
  这些只在横向比较时引用结论。
- **本机官方拆解源码**：`D:\_deliverables\官方拆解汇总\`，包括 ClaudeCode、Codex、CodexDesktop、HermesDesktop、OpenClaw、OpenCode、Pi、ZCode。这几家的记忆实现必须查。
- **Atlas 现有代码**：`D:\Atlas`，分支 ui-redesign。另外 `origin/memory-w2-api`、`origin/memory-w2-ui` 两个分支有 W2 的代码。

## 2. 分工：三条调研线 + 一个审查验收

每条线开一个 Codex 对话，各自再开子智能体，每个模块或每 2–3 个项目一个。

| 线 | 模块 | 分支 / 结果文件 |
|---|---|---|
| **A** | M3 提炼（一轮或一个会话结束后，提炼出什么、怎么提炼）、M4 整合/做梦（跨会话合并、去重、纠错、写手册和总览）、透明记忆库（Markdown 作真源、用户手改的处理） | `memory-survey-a` / `docs/memory/survey/A-RESULT.md` |
| **B** | M5 读取与召回（常驻总览、模型自己查还是系统推送、混合检索、按使用排序和淘汰、引用）、M7 会变的事实（取代、纠错、遗忘传播、双时间）、M9 联想（链接、图、类海马体） | `memory-survey-b` / `docs/memory/survey/B-RESULT.md` |
| **C** | M1 生命周期钩子（每轮前/后、压缩、会话结束、子 Agent）、M2 原文指针与轨迹回溯、M6 委派与外部 Agent 取记忆、M8 经验转技能（含与 3,298 条技能目录、SkillOpt 合流）、多模态事件字段（只研究） | `memory-survey-c` / `docs/memory/survey/C-RESULT.md` |
| **R** | 审查验收三条线 + 总裁决 + 写施工任务书 | `memory-survey` / `docs/memory/survey/VERDICT.md` 和 `docs/memory/TASKBOOK-M*.md` |

### 每个模块的必查候选（另外**自己再搜 GitHub 补至少 3 个**：近一年活跃、做同一件事、有源码）

- **M3 提炼**：Codex `phase1.rs` 与 `stage_one_system.md`（已核实，只做比较）、Claude-Mem（thedotmack/claude-mem）、Mem0 新版的单次 ADD 提炼、Mastra observational memory 的 Observer、LightMem、memU、MemoryOS（BAI-LAB；主机 `D:\MemoryOS_FULL_SETUP` 有一份）、Memobase、nemori（情景切段）、SimpleMem、Letta、OpenClaw `extensions/memory-core`、Claude Code 自动记忆（拆解源码）。
- **M4 整合**：Codex `phase2.rs` 与 `consolidation.md`、ReMe dream（已核实）、Letta sleep-time agent、Mastra Reflector、A-MEM 的记忆演化、OpenClaw 的 dreaming、Claude Code 的记忆整理、MemOS 的生命周期。
- **透明库**：Basic Memory（Markdown 真源 + SQLite 同步，**重点**）、Codex 的 memories 目录与 git 基线、Claude Code 的记忆文件、MemPalace、Obsidian 类方案。
- **M5 读取**：Codex `read_path.md`、`citations.rs` 和使用统计（已核实）、Hindsight、MemOS（已核实）、Supermemory、Basic Memory、Cognee 检索、Mem0 检索、Zep、OpenClaw 的 `hybrid`/`temporal-decay`/`mmr`、Claude-Mem 的三级按需检索、OpenViking 分层读取（AGPL，只看思路）。
- **M7 会变的事实**：Graphiti（时间规则）、Zep、Mem0 旧版的 UPDATE/DELETE、Memobase、Supermemory 的版本、Letta 的记忆块编辑、Codex 的删除传播与 `max_unused_days`。
- **M9 联想**：A-MEM、HippoRAG 2（类海马体 PPR）、Cognee、Graphiti、Basic Memory 的 wiki 链接、MemoryOS 的热度机制。
- **M1 钩子**：Hermes `memory_provider.py`/`memory_manager.py`（已核实）、MemOS 的 Hermes 适配器 `apps/memos-local-plugin/adapters/hermes`、Claude Code 的 hooks（PreCompact/SessionEnd/SubagentStop）、OpenClaw 插件钩子、Letta 的 agent loop、Mastra 的 memory processors、LangMem。
- **M2 原文指针**：AMA 的 `tool.py`（`traj_get`/`traj_find`）、Codex 的 `rollout_path` 和引用、Claude-Mem 的 observation ID、LongMemEval-V2 的 `trajectory_store.py`、Atlas 的 `session_sync.py`（`message_uid`）。
- **M6 委派**：Hermes `on_delegation`、Codex 子会话的记忆策略（不跑第一阶段）、Claude Code 子 Agent 的记忆、Letta 多 Agent 共享记忆块、MemOS `subAgentRetrieve`、CrewAI memory、OpenAI Agents SDK sessions。
- **M8 技能**：MemOS 的 `skill/` 全部（eligibility、verifier、lifecycle）、ReasoningBank、Codex 第二阶段写的 `skills/`、Agent Workflow Memory（AWM）、ExpeL、Voyager 技能库、Anthropic skills 格式、Atlas 的 `core/atlas/evolution/skill_sleep.py` 和 SkillOpt、Hermes 的技能自进化。
- **多模态（只研究）**：MIRIX、Screenpipe（注意商业许可）、memU 多模态、Second Me。

## 3. 方法（每个项目都要做到）

1. clone 到 `D:\_research\memory-survey\repos\<名字>`，记下 commit SHA 和许可证（根目录和子目录都要看）。
2. **读源码，不读宣传。** 找到做这件事的具体文件和函数，记成 `文件:函数:行号`。提示词原文要摘关键段。
3. 每个项目回答这些问题：
   - 数据怎么存；
   - 什么时候写、写什么；
   - 失败了怎么重试；
   - 怎么去重、怎么纠错；
   - 怎么召回；
   - 用户能不能看懂、能不能改；
   - 有没有「用没用上」的反馈。
4. 标明证据等级：**读了源码** / 只看了文档 / 只看了论文。作者自报的跑分不当结论。
5. 估算移植成本：语言、依赖多大、要不要起服务、和 Atlas Python 后端怎么接。

## 4. 每条线的产出（结果文件里按模块写）

每个模块一节，内容：

- **对比表**：项目 | commit | 关键文件:函数 | 做法一句话 | 强项 | 弱项 | 许可 | 移植成本 | 证据等级。
- **裁决**：最强的是谁，第二是谁，为什么。要说清它强在**哪个细节**。
- **移植清单**：`仓库@commit:文件:函数 → Atlas 的哪个文件/函数`，说明保留什么、改什么、丢什么、替换 Atlas 哪段旧代码。
- **对 Claude 骨架假设的意见**：支持、修改还是推翻，附源码证据。
- **还没查清的**。

结果文件末尾写「新增候选」：自己搜到的项目和搜索词。

**完成方式**：
1. 在 `D:\atlas-mem-survey-<a|b|c>` 建工作树（`git worktree add -b memory-survey-<a|b|c> D:\atlas-mem-survey-<a|b|c> origin/memory-survey`）；
2. 只提交 `docs/memory/survey/` 下的文件，不提交 clone 下来的仓库；
3. 推送；
4. 最后一行写「LANE <A|B|C> DONE」。

## 5. 审查验收（R 对话）

1. **等三条线完成**：每 10 分钟 `git fetch origin`，看 `origin/memory-survey-a`、`-b`、`-c` 上的结果文件是否都出现了「LANE X DONE」。等的时候可以先读第 1 节的材料。
2. **抽查**：每条线至少抽 5 处「文件:函数」，打开源码核对是否属实、理解是否正确。不实的打回：在对应线的结果文件里追加「审查意见」，再给那个对话发消息让它补。没法发消息时自己补查。
3. **总裁决** `docs/memory/survey/VERDICT.md`：
   - 每个模块最终选谁；
   - 骨架是否成立；
   - 各模块之间怎么接成**一套**系统（数据模型、生命周期、透明库怎么保证）；
   - 和 GPT V4.2 A0–A7、Claude M1–M8 的对应关系。
4. **施工任务书**：按裁决写 `docs/memory/TASKBOOK-M1.md` …，每份写清：
   - 移植哪个仓库哪个 commit 哪个文件哪个函数；
   - 改 Atlas 哪个文件；
   - 替换哪段旧代码；
   - 怎么迁移旧数据；
   - 最少的验收动作（靠真实使用和日志，不搞大测试）；
   - 哪几份可以并行（按文件不冲突来分）。
5. 合并三条线的结果到 `memory-survey`，推送。最后一行写「SURVEY VERDICT DONE」。**不要开始施工**，施工等用户点头。

## 6. 注意

- 主机 CLI 的 codex 没余额，别用。网络慢就走代理 127.0.0.1:7897。
- 不要把 clone 下来的仓库、zip、二进制提交进 git。
- 不要改 `D:\Atlas` 工作区（里面有别人没提交的改动）。
- 遇到影响架构方向的选择，写进结果文件的「需要用户拍板」一节，**不要停下来等**，先按更强的那个选项继续。
