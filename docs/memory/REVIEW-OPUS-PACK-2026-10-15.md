# 审查：GPT《Atlas 记忆系统 Opus5.5 全量审查交接包》（2026-10-15）

> 审查人：Claude（Opus 5.5），笔记本本地。基线：`origin/memory-v1@8036b2b`（相对包里的 `7826e91` 只多了一份 BOOT-1 文档，记忆代码没变）。
> 做法：01 的每条缺陷都回到 memory-v1 源码逐行核对；外部项目只抽查了 3 处（OpenClaw 遗忘文件、ReMe dream 管线、Letta 是否归档）。没在主机跑过任何东西。

## A. 总结

这份包比上一份 ABC 调研**有用得多**：01 列的 12 条 Atlas 缺陷**全部能在代码里找到**，行号也对，是真的读了源码。但有三个问题：
1. **严重程度标偏了**：P0-A（手改）实际后果比写的轻，但有一个它没发现的真 bug；P0-C（重启丢写入）因为原始对话还在 engine 里，算 P1。
2. **蓝图铺得太大**：W1–W6 把 ReMe、MemOS L1-L3、A-MEM、ReasoningBank、StructMem、Synapse、Mnemos、CORTEX 全排了进去，而且**没提 Atlas 已经有的 `evolution/skill_sleep.py`（SkillOpt）**，W3/W4 会和它撞车。
3. **个别事实过时或错了**：Letta 旧仓库**没有归档**（GitHub `archived=false`，9-10 还有推送）；主机旧记忆清理在 10-15 00:50 **已经做完**（8099 停掉、数据移到 `D:\_archive-old-memory-2026-10-14`），没做的只是真模型验收。

**裁决**：W0 马上做（都是小改，一次 Codex 就能做完）；W1（任务经历）+ W2（执行中想起）是下一批，真正提升"隔天记得、出错时想起"；W3 以后先冻结，等 W1/W2 用上一段时间再说。

## B. 缺陷 / 事实核对表

| 条目 | 结论 | 核对依据 / 修正 |
|---|---|---|
| P0-A 手改不同步 `value` | **确认，但后果写错了** | `edit_entry` 只改 `text/src/at`（`__init__.py:255-257`）。真正的 bug：`apply()` 判"没变"时比的是 `old.value`（`extract.py:249`）。例：原值"杭州"→你手改成"北京"→之后你又说"我住杭州"，会被当成**没变化直接跳过**，页面一直显示"北京"。另外提炼模型看到的已知值还是"杭州"（`known_facts` 用 `value or text`）。包里说的"自动提炼静默覆盖手改"反而不成立：覆盖必须有你新说的原话，按"只认亲口说的"这是对的。**修法很简单：手改时 `value` 一起改成新文本（或清空 `value`）**，不需要包里的 `manual_override + display_text` 双字段。 |
| P0-B 忘掉不彻底，可复活 | **确认，比写的还多一处** | ①旧提交里明文还在；②`show()` 把"忘掉"那次提交的删除行当成 `removed` 返回，**变动记录页会把刚忘掉的内容原样显示出来**；③`revert(sha)` 直接 `git revert`，不查墓碑，能把忘掉的内容恢复；④`redact_diary` 只替换完全相同的字符串。这是 PLAN-V1 里"忘掉=改写 git 历史"那条没做完的部分。 |
| P0-C 后台写入只在内存 | **确认，降为 P1** | `schedule_turn` 用 `asyncio.create_task`（`__init__.py:155`），连日记都在任务里写。但原始对话已经存在 engine 会话库里，崩溃只丢这一轮的提炼，可以补回来。 |
| P1-D 常驻预算被"我"挤满 | **确认** | `used` 三页共用，到 1500 字后"现状/它自己"一条都进不去（`__init__.py:96-108`）。 |
| P1-E 过期内容先被读到 | **确认，范围更大** | `expire()` 只在写入时跑；`_resident_block`、`_relevant_block`、`index.search`（也就是 `memory_search` 工具）都不看 `until`。 |
| P1-F 先取前 12 条再过滤 | **确认** | `__init__.py:129-130`。 |
| P1-G worker 不读也不写记忆 | **确认，但不全是 bug** | worker 的工具白名单里有 `memory_search`（`loop.py:530`），能主动查。不自动注入、不写入，用来做隔离是合理的。只需要补"worker 的经历归到父任务"，放进 W1。 |
| P1-H 假设句只靠提示词挡 | **确认** | `_quote_ok` 只查原话存不存在。加 `stance` 字段很便宜。 |
| P1-I 没有任务经历 | **确认** | 日记只记用户 2000 字 + 回复 300 字，工具过程全丢。这是 W1 的核心。 |
| P2-J/K/L | 确认，属于设计取舍 | 按包里写的，先加指标，暂不改。 |
| 01 §4 "主机清理待完成" | **过时** | 10-15 00:50 已清完，只差真模型验收。 |
| OpenClaw `memory-forget-*` | **确认存在** | main 和包里锁定的 `66207936` 都有 `memory-forget-kernel/content/index-task/worker/recovery` 等 20 多个文件，W0 遗忘直接参考它。 |
| ReMe `dream/{extract,integrate,finish}.py` | **确认存在** | 另外还有 `extract.yaml`、`integrate.yaml` 两份提示词。 |
| "Letta 旧仓库已归档" | **错** | `letta-ai/letta` archived=false，2026-09-10 还有推送。 |
| MemOS 子目录 MIT / 根目录 Apache | 可信，复制前看子目录 LICENSE | Atlas 以前 fork 过 `vendor/memos-local-plugin`，代码已经熟悉。 |

### 包里没发现的遗漏

1. **变动记录页暴露已忘内容**（见 B 表 P0-B ②），这是你每天会看的页面，优先级最高。
2. **revert 绕过墓碑**：撤销一条"记下"的变动没问题，但撤销"忘掉"的那次提交，会把内容直接写回来。
3. **和 skill_sleep 撞车**：W3/W4 的"经验→策略→技能"和已有的 SkillOpt 睡眠学习是同一件事，必须二选一或者合并，不能做两套。
4. **`memory_search` 返回 `until` 已过的条目**，但没标注"已过期"，模型会当成现在的事实用。

## C. 核心机制覆盖矩阵（只列影响用户体验的）

| 能力 | 现在 | 缺口 | 放在哪一波 |
|---|---|---|---|
| 隔天记得你说过的事 | ✅ 有 | 过期/预算/排序的小 bug | W0 |
| 改了马上生效 | ⚠️ value 不同步 | 一行修复 | W0 |
| 忘掉后不复活、不显示 | ❌ | 墓碑 + 历史 + UI | W0 |
| 重启不丢 | ⚠️ | 持久队列 | W0 |
| 假设/问句/网页不算事实 | ⚠️ 靠提示词 | stance 字段 | W0 |
| 记得"上次怎么做的"（任务经历） | ❌ | episode | W1 |
| 出错时想起以前的类似情况 | ❌ 只在一轮开头召回 | 工具出错时触发召回 | W2 |
| 从失败里学办法 | ⚠️ skill_sleep 已有但没运行 | 和 W3 合并 | 冻结 |
| 条件/到点提醒 | ⚠️ 自动化工具 | StandingIntent | 冻结 |
| 屏幕/手机记忆 | ❌ | 只预留 `media_ref` 字段 | 冻结 |

## D. 借鉴裁决

| 来源 | 拿什么 | 怎么拿 | 何时 |
|---|---|---|---|
| OpenClaw `memory-forget-*.ts`（MIT） | 遗忘的状态机：计划 → 删正文 → 删索引来源 → 报告 → 中断后恢复 | Python 重写进 `library/forget.py` | W0 |
| ReMe `dream/extract,integrate,finish.py`（Apache） | 只处理变化的部分 → 提炼 → 合并 → 成功才推进检查点；`auto_memory._sanitize_msg_for_save` 过滤"刚搜出的记忆"防止回流 | 重写，不装 AgentScope | 回流过滤放 W0，其余放 W1 |
| MemOS `core/retrieval/retrieve.ts`（MIT 子目录） | 按场景召回：`turn_start / tool_driven / sub_agent / decision_repair`，每个场景配额不同 | Python 重写进 `library/recall.py` | W2 |
| MemOS `l2/induce.ts`、`skill/eligibility.ts` | 多个独立 episode 才能归纳；晋升条件 | 等 W2 之后和 skill_sleep 一起评估 | 冻结 |
| A-MEM | 关联链接 | 先用 SQLite `links` 表做，不引入 chromadb | W2（可选） |
| ReasoningBank | 成功/失败提炼的提示词 | 只看提示词 | 冻结 |
| StructMem、Synapse、Mnemos、CORTEX、Soar、Titans/HOPE | — | 名字仿脑，但对 Atlas 没有已证实的收益 | 不做 |
| Graphiti、HippoRAG、向量 | — | 等 FTS + 链接明显不够用时再说 | 不做 |

## E. 修订后的架构（比包里的六层简化）

```
engine 会话库 / run log（原始证据，已存在，不复制）
   │ event_ref
data/memory/  Markdown+git（唯一可编辑真源）
   我 / 现状 / 它自己 / 人 / 事 / 日记 / 经历(W1 新增)
   .tombstones.jsonl   .queue.sqlite(W0 新增)   .index.sqlite(派生)
   │
library/  recall(场景, 预算) · search · observe_turn · observe_run(W1) · forget · edit
```

不新增 Policy/Skill/World/Intent 表。字段只加这几个：`Entry.stance`（said/hypothetical/question/quoted）、`Entry.event_ref`（W1）、`Episode` 页（W1）。

## F. 给 Codex 的任务书

### W0：记忆可靠性（一次做完）

**范围**：只动 `core/atlas/memory/library/{__init__,extract,index,store}.py`、新增 `library/forget.py`、`api/memory_library_router.py`、`components/memory/LibraryPages.tsx`。不碰 kernel、不碰别的模块。

1. **手改**：`edit_entry` 改 `text` 时把 `value` 也改成同一个值；`known_facts` 优先读 `text`。
2. **过期在读的时候过滤**：`_resident_block`、`_relevant_block`、`index.search` 默认跳过 `until <= now` 的条目；`include_history=True` 时可以返回，但标 `expired: true`。
3. **常驻预算**：我 / 现状 / 它自己 各自保底 400 字，剩下的共用；现状按 `until`、`at` 排序。
4. **先过滤再取前几条**：`index.search` 增加 `exclude_paths` 参数，在 SQL 里排除；`_relevant_block` 用它。
5. **遗忘**（照 OpenClaw `memory-forget-kernel.ts` 的步骤）：
   - a. 删当前条目，写墓碑（现在已有）；
   - b. `redact_diary` 另外按 `entry.quote` 和 `key` 的值做匹配；
   - c. **改写这个记忆库自己的 git 历史**：对含有该文本的提交跑 `git filter-repo --replace-text`（没装就用 `git filter-branch --tree-filter`），然后 `reflog expire --expire=now --all && gc --prune=now`。只动 `data/memory/.git`，不碰 Atlas 主仓；
   - d. `show()` 过滤墓碑命中的文本；`revert()` 之后对恢复出来的条目查墓碑，命中就拒绝并报错"这条已被忘掉，不能恢复"；
   - e. 返回一份范围报告：删了哪些文件、几次提交、哪些地方删不到（engine 原始会话、备份）。界面上把这份报告显示出来。
   - **验收**：忘掉之后，变动记录页、`memory_search(include_history=True)`、`git log -p` 三处都搜不到原文。
6. **持久队列**：`schedule_turn` 先往 `.queue.sqlite` 写一行 `(id, session, user_text, assistant_text, mode, status)`，再起任务；完成后删掉这一行。`ready()` 时重跑所有 pending 行（按 id 幂等，墓碑照查）。
7. **stance**：提炼的 schema 加 `stance`，只有 `said` 能写进 我/现状/人/事；其他直接丢，记 rejected。
8. **防回流**：提炼前把 assistant 回复里的 `memory_search` 结果去掉（参考 ReMe `_sanitize_msg_for_save`）。

**验收（只做这 9 条，用真实模型）**：照包里 01 §5 的 M01–M09，M01 换成"手改北京后再说杭州，要变回杭州"，M02 加上"变动记录页看不到"。

### W1：任务经历（W0 用一周后再做）

- `_phase_finalize` 在一次任务用了 ≥3 次工具时，后台写一页 `经历/YYYY-MM-DD-<slug>.md`：目标、关键步骤（工具名 + 成功/失败 + 一句结果）、最后结论、`event_ref` 指向 engine 会话。不复制工具的原始输出。
- worker 的步骤记进父任务的经历页，作者标 `worker:<id>`，不能写进"我"。
- 每晚整理照 ReMe extract→integrate→finish：只处理当天新增的经历页，合并重复的，成功才推进检查点。
- **验收**：隔天新会话问"昨天那个 X 怎么修的"，能说出步骤，并且说清楚哪一步是真验证过的。

### W2：执行中想起

- 照 MemOS `retrieve.ts`：在 `loop.py` 里工具连续报错 2 次时，用错误文本 + 工具名查"经历"，最多带 2 条，每次任务最多触发 3 次。
- **验收**：重现一个以前修过的报错，Atlas 在执行中主动引用那次经历；遇到不同原因的类似报错，不照搬。

### W3–W6：冻结

等 W1/W2 真用起来后再决定。到时第一件事是决定 skill_sleep 和 MemOS L2 合不合并。

## G. 需要主机实测、目前没有证据的

1. W0 第 5 步的 filter-repo 在主机 Windows 上能不能跑、要多久（记忆库提交很多时）。
2. 持久队列在 Atlas 被更新器重启时，能不能正常补跑。
3. stance 字段会不会让提炼模型漏掉真正的事实（跑一遍之前那 7 句冒烟）。
4. 当前召回只要 3ms，加了过滤以后还能不能保持在 20ms 以内。
5. 包里所有外部项目的效果数字都是作者自报的，没有一条在 Atlas 上验证过。
