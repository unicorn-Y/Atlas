# 调研结论：GPT 三线调研筛选 + 源码核实（2026-10-14）

> 输入：网页 GPT 的《Atlas长期记忆研究-ABC全域二次查漏总包》（7 份，约 18 万字）。
> 做法：只留对第一版有用的；关键结论回 GitHub 看源码或官方文档核实。没核实的标「未核」。

## 一句话结论

**第一版直接照 OpenClaw 的记忆核心（`extensions/memory-core`，MIT）来做，用 Python 重写进 Atlas。** 它的设计和我们 10-14 定下的原则几乎逐条对上，而且是 Atlas 本来就要对标的那一家。其他项目只摘具体零件。

## 核实过的关键事实

| 结论 | 核实结果 | 出处 |
|---|---|---|
| OpenClaw 记忆分层：`USER.md` / `MEMORY.md`（精选，开场常驻）+ `memory/YYYY-MM-DD.md`（每日记录，按需检索）+ 待办意图（SQLite）+ `DREAMS.md`（整理报告，给人看） | ✅ 官方文档 | docs/concepts/memory-architecture.md |
| 来源等级写在 SQLite 里，模型通过正文改不了：`origin_class ∈ owner/agent/untrusted/system`，`session_kind ∈ interactive/cron/heartbeat/subagent`，`observed_at`，`supersedes_key`；来源不明一律当 untrusted | ✅ 源码 | packages/memory-host-sdk/src/host/memory-schema-provenance.ts |
| untrusted / system 来源的内容在晋升前就被排除，不进精选记忆；定时、心跳、子代理会话产生的内容不能晋升 | ✅ 文档 | memory-architecture.md |
| 中文检索：FTS5 可选 `trigram`；另有 CJK 二字切分（"我喜欢hello你好"只在连续汉字内切，不会切出"欢你"） | ✅ 源码 | memory-schema-fts.ts、memory-core/src/memory/tokenize.ts |
| 线索触发：条目行尾 `<!-- trigger: … -->` `<!-- importance: N -->`；得分 ≥0.65 才带入，每轮最多 3 条，只有精选层会自动带入 | ✅ 文档 | memory-architecture.md |
| 排序 = 混合相关度 × 时间衰减（每日记录 30 天半衰期，精选文件不衰减）× 重要度 | ✅ 文档 | memory-search.md |
| 改写 `MEMORY.md` 前比对内容哈希，期间被人改过就放弃改写、改为追加；每次改写保存旧版本，并在 `DREAMS.md` 里记一笔 | ✅ 文档 | memory-architecture.md |
| "忘掉"会把该会话 ID 拉黑，防止以后再被提炼回来 | ✅ 文档（自己也承认不覆盖所有副本） | memory-architecture.md |
| 待办意图（=我们的"没说完的事"）：pending/armed/fired/done/cancelled/expired；默认冷却 24 小时、最多触发 3 次、90 天过期、每轮最多带入 3 条 | ✅ 文档 | memory-architecture.md |
| EverOS：Markdown 是唯一真源，SQLite/向量索引都能从 Markdown 重建；文件监视 → 持久队列 → 只重算改动的条目；直接删索引目录不算重建 | ✅ 文档 | EverOS docs/how-memory-works.md |
| Graphiti 的事实有 `valid_at`（何时成立）/ `invalid_at`（何时不再成立）/ `expired_at`（系统何时判它失效）三个时间 | ✅ 源码 | graphiti_core/edges.py |
| Agent Memory Atlas 索引 732 个记忆系统，按"墓碑 / 可信状态 / 双时间 / 作用域 / 改动审计 / 人工审核 / 反例测试"七项打标 | ✅ 网站存在，数字是它自报 | neoneye.github.io/agent-memory-atlas |

Atlas 自己：`core/atlas/memory/__init__.py` 已经给消息表建了 trigram 全文索引。**但 trigram 搜不到两个字的词（"老王""面试"），必须补二字切分**——这正是 OpenClaw 的做法。

## 筛出来、要进第一版的教训（每条都有出处）

1. **原文永远保留，摘要和索引都是派生物、可重建**（EverOS、OpenClaw；ChatGPT 用户抱怨"摘要合并吞细节"）。
2. **来源分级由系统打，模型改不了**（OpenClaw origin_class）。网页、工具输出永远不能变成"关于你的事实"。
3. **后台整理不能卡前台**（Mastra Issue #21849：同步观察失败导致对话长时间卡住）。提炼放后台，失败就跳过。
4. **用户纠正要马上生效**（"读己之写"，Gemini 官方承认删除要几天才同步）。用户改的直接写文件、立即重建这一条索引。
5. **被否定的值要留墓碑**，否则下一次整理又从原文里提炼回来（Agent Memory Atlas 的模式；ChatGPT 用户抱怨"删了又出现"）。
6. **判冲突只在同一个人 + 同一类事实里判**，并且先软失效（Graphiti #1728：无关事实被误判失效）。
7. **相对时间要换成绝对日期再存**（"下周""昨天"过几天就指错了）。
8. **推测和你说的分两条轨**，推测被反复引用也不能自己升级成"你说的"（OP-Bench 的证据循环）。
9. **记得不等于每次都提**：敏感事默认不主动提，主动提醒有频率上限（OP-Bench、Nomi 的安静时间、OpenClaw 的冷却 + 次数上限）。
10. **记忆文件放固定数据目录**，升级、搬家不丢（MCP Memory Server 老 Issue #220）。

## 不进第一版（记下来，以后再看）

- 图数据库 / 时间知识图谱（Graphiti、cognee）：单人本机成本高，误失效风险大；先用"人 / 事"文件 + 别名表。
- 向量检索：第一版先只做全文 + 二字切分 + 别名；向量作为可选，留 OpenClaw 的 `provider: "none"` 退化路线（不让 1.5 核常驻重演）。
- 每晚整理（OpenClaw dreaming）、它的日记、技能晋升、主动开口：第二版，直接照 `dreaming-*.ts`、`short-term-promotion-*.ts`。
- 屏幕 / 多模态记忆（MIRIX）、评测基准（BEAM、MemoryArena、DolphinBench）：以后验收时再用。
- 国内产品、陪伴类的大面积用户样本：GPT 报告自己也说没找全，对第一版没有增量。

## GPT 报告本身的问题（以后下任务时注意）

- B 线 18 个项目的 13 维表大多数格子是"待验"，等于没看源码；真正有用的是第二轮补的 OpenClaw，它在第一轮完全漏了。
- 报告自己承认：没锁 commit、没跑 Windows 实测、Top20 抱怨里混着论文风险。所以本文件只采信上面核实过的部分。
