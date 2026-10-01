# 专题 4：记忆、个性化与自我学习（2026-09-30）

> Atlas 的记忆系统目前冻结。本专题只回答「最强的是怎么做的、Atlas 现在处在什么位置」，要不要解冻由用户决定。

## 一、当前最强做法

### 1. OpenClaw（开源里最完整，v2026.8.1 起）
- **存储透明**：长期记忆是 `MEMORY.md`，用户长期要求是 `USER.md`，另有兼容 Obsidian 的「记忆 Wiki」存整理过的笔记；向量用 LanceDB，会话记录用 SQLite。
- **混合检索**：向量 + 全文检索，没有嵌入模型时退回全文；带日期的文件按时间衰减。
- **主动回忆**：每次运行开始前，自动检索一次相关记忆（每次运行只做一次，有快速模式），只在同一个 Agent 自己的对话里找。
- **后台整理（dreaming）**：定时在后台把零散记忆整理进 `MEMORY.md`，过滤无用话题，有调用预算上限，生成整理报告。
- **来源标记**：来自网络或受限会话的内容标为「不可信」，**不会自动变成长期记忆**——防止网页里的恶意内容被记住。
- **可管理**：设置里能看状态、搜索、预览后再删除（按会话、按来源）。
- 2.0 版又加了：经验自动沉淀成「待确认的技能」。
- 缺点：启动时加载的记忆文件占每次调用 20–30% 的输入 token。

### 2. Hermes Agent（自我学习闭环最成熟）
- 解决问题后把做法写成技能（Markdown），使用中继续改进。
- **技能复盘**：每隔 N 轮（默认 10）在后台线程里跑一次复盘 Agent，只能动记忆和技能，不影响前台对话。
- **技能按描述路由，不用向量**：系统提示里放技能索引（名字 + 描述），模型选中后才读取正文。
- **自动清理**：30 天没用标记过期，90 天归档（可恢复）。
- 能搜索自己过去的对话。

### 3. Claude / ChatGPT（闭源，最省心）
- Claude：3 月起全员有持久记忆，大约每 24 小时从对话里提炼一次（职业背景、工作偏好、沟通风格），不用配置。
- ChatGPT：检索过去的对话。

### 4. OpenHuman（最激进）
- 从 118+ 服务持续吸收信息，号称「10 亿 token」的个人记忆；可编辑的记忆库；上下文压缩号称省 70–80%。

### 5. 通用记忆层（可以直接接）
- claude-mem、ClawMem（本机运行，钩子 + MCP + 混合检索，能导入 Claude Code、ChatGPT 的对话导出）、MemoryLake。

### 6. ⚠️ 自我学习的风险（2026-08 论文）
- 《Skill Misevolution》测了 25 种配置、每种 525 个任务：**21 种会自我进化的配置全部产生过不安全的技能**，其中 15 种在全新会话里造成了危害。一次「不安全但成功」的操作被写成技能后，即使触发它的输入已经不在了，也会被当成规矩反复执行。
- 建议：技能的**编写和复用都要把关**。论文提出的 SafeEvolve 把不安全技能的检索降低了 26.7 个百分点，正常任务的效果几乎不受影响。

## 二、Atlas 现状

| 能力 | Atlas | 对比 |
| --- | --- | --- |
| 事实 / 候选 / 审核 / 冲突 / 历史 | ✅ 非常完整（`memory/__init__.py` 等 5000+ 行，候选→审核→晋升，质量、健康、治理报告） | 治理机制比所有开源项目都多 |
| 存储形式 | 数据库表 | ❌ 用户看不到也改不了；OpenClaw 是可以直接编辑的 Markdown |
| 运行前主动回忆 | 🟡 有 `get_agent_context` | 第五波暴露过问题：Worker 被用户记忆带偏 |
| 后台整理 | 🟡 有 consolidation 相关接口 | 没有定时跑的「dreaming」 |
| 来源标记（网页内容不进长期记忆） | ❌ 没看到 | OpenClaw 有 |
| 自动写技能 / 改技能 | 🟡 有技能获取流程（`skillAcquisitionReview`） | Hermes 的复盘闭环更成熟 |
| 搜索过去的对话 | ✅ `session_search` | |
| 导入别家记忆 | ❌ | ClawMem 能导入 ChatGPT、Claude Code |

结论：**Atlas 的问题不是功能少，而是用户感知不到、控制不了**。

## 三、如果解冻，Atlas 该怎么做才能超过它们

1. **透明化**：记忆以 Markdown 文件为准（数据库只做索引），在界面里像笔记一样浏览、编辑、删除；每条记忆显示来源（哪次对话、哪个网页）。
2. **来源标记**：网页、邮件、外部文件里的内容标为不可信，不能自动晋升为长期记忆。成本低、价值高，**解冻前也值得先做**。
3. **后台整理**：空闲时定时整理，有预算上限，出一份「这周记住了什么」的报告，让用户确认。
4. **技能闭环 + 安全阀**：学 Hermes 的复盘，但每个新技能或技能改动都要过一遍安全检查，并由用户确认（吸取 Skill Misevolution 的教训）；长期不用的技能自动归档。
5. **导入**：导入 ChatGPT、Claude 的记忆和对话导出，新用户一装上就「认识你」。
6. **按需加载**：记忆不要每次全量塞进上下文（OpenClaw 的缺点），用索引 + 按需读取（Hermes 技能的做法）。

## 资料

- [OpenClaw v2026.8.1 记忆](https://docs.openclaw.ai/releases/2026.8.1/memory)、[OpenClaw 2.0（InfoQ）](https://www.infoq.com/news/2026/09/openclaw-2-release/)
- [OpenClaw、Hermes、Claude、Manus 记忆对比](https://medium.com/@srividyaganapathi/openclaw-vs-hermes-vs-claude-vs-manus-who-wins-on-memory-in-2026-f79de3fc7b0a)
- [Hermes Agent 是什么：记忆与技能](https://www.truefoundry.com/blog/what-is-hermes-agent)、[Hermes 文档](https://hermes-agent.nousresearch.com/docs/)
- [Skill Misevolution：自我改进 Agent 的技能风险（arXiv 2608.12851）](https://arxiv.org/abs/2608.12851)
- [claude-mem](https://github.com/thedotmack/claude-mem)、[ClawMem](https://github.com/yoloshii/ClawMem)
- [OpenHuman](https://agentic-ai.readthedocs.io/en/latest/AgentPlatforms/openhuman/)
