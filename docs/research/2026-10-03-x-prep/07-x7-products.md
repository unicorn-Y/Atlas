# X7 产品核实与机制对比

核实日：2026-10-03（Asia/Hong_Kong）。这是官方资料核实，不是产品实测；闭源内部数据库、队列、调度算法及故障恢复实现均不可由 UI 或营销内容推断。开源可搬来源与 commit 见各波 sources、evidence JSON 和总 source map。下表“最佳”指对 Atlas 当前约束最有价值的机制，不是未经测试的性能排名。

## 名称、入口、能力与证据

| 正式名称 | 已核实机制 / 对 Atlas 的价值 | 官方出处与日期 | 公开边界 / 对应波 |
|---|---|---|---|
| OpenAI dots；单体叫 dot | 常驻目标执行、独立云电脑；自定义行动确认规则；有自己渠道身份 | [Release Notes](https://help.openai.com/en/articles/6825453-chatgpt-release-notes)，2026-09-29；[workspace controls](https://help.openai.com/en/articles/20001554-manage-dots-in-chatgpt-workspaces)，核实 10-03 | 渐进开放、地域/计划限制；云电脑不继承本地 VPN 和登录。local computer access 需要在线电脑与打开的 app。规则不能覆盖内置限制。X1/X2/X7；内部实现闭源 |
| Meta Muse | 专属 Secure VM、浏览器、持续目标；关 app 后继续；对外行为经独立 Sentinel；敏感动作请求人决策 | [官方发布](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/)，2026-09-08 | VM/Sentinel 内部未开源；Confidential VM 为后续计划，不能记为已交付。笔记本不自动获得云端私密计算保证。X2/X7；不照搬第二权限引擎 |
| Gemini Spark | 24/7 背景执行、Google Workspace 接入；官方把主动 agent 与日常 Gemini 对话区分 | [Gemini app update](https://blog.google/innovation-and-ai/products/gemini-app/next-evolution-gemini-app/)，2026-05-19；[India rollout](https://blog.google/intl/en-in/company-news/technology/introducing-gemini-spark-your-247-personal-ai-agent-in-country/)，2026-07-29 | 云基础设施执行，闭源；订阅/地区开放不等于所有账户可用。专属邮箱与浏览器具体规则需账号级验收，不能凭名称补写。X1/X2/X7 |
| Grok Bot | 共享持久电脑/文件/浏览器登录，Bot 身份分工；技能与例行任务分离；可示范生成技能草稿 | [Skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations)，2026-09-14；[overview](https://docs.x.ai/grok-bot)，核实 10-03 | Teach 逐步开放，示范记录最多十分钟可见交互、不含麦克风；草稿还需决策/失败/审批规则与测试。云机器不意味着每 Bot 独立 VM。X2 捕获/X4 注册/X5 审核/X6 协作/X7 运营 |
| Microsoft Autopilot（原 Microsoft Scout） | 独立 agent 身份、后台主动工作、M365 业务上下文；官方明确基于 OpenClaw 开源技术 | [Scout announcement](https://www.microsoft.com/en-us/copilot/blog/2026/06/02/introducing-microsoft-scout-your-always-on-personal-agent/)，2026-06-02，现页标明已改名 | Scout 不是另一并行产品；Work IQ/企业身份不应推断可整套开源搬入。搬 OpenClaw 可核实模块，Atlas 保留自身 authority。X1/X3/X7 |
| Cue by Manus（独立于 Manus 2.0 / Studio） | 每 agent 自己邮箱、电话、钱包和电脑；群组共享目标及交接；Manus 2.0 提供事件触发和持久 Cloud Computer | [Introducing Manus 2.0](https://manus.im/blog/introducing-manus-2-0)，2026-09-28 | Cue 邀请制 early access，iOS 页面称等待审核；电话/钱包不是 Atlas 自动购买账号的授权。该页搜索索引的相对日期有冲突，记录页面 September 28，按本轮 2026 发布上下文核对，不把索引“last year”作为年份证据。X1/X3/X6/X7 |
| Perplexity Computer | 长时间流程、背景任务/监控、并行 subagent、连接器与技能 | [Computer](https://www.perplexity.ai/products/computer)，未标发布日期，核实 10-03 | 官方能力描述，没有可搬 harness 源码或可靠的 exactly-once 保证。X1/X6/X7 |
| Perplexity Personal Computer（Mac / Windows） | 官方 Mac 页明确 Mac mini 24/7、iPhone remote、原生 app/Comet；Windows 页明确本机文件、Office、语音/连接器/Comet | [Mac](https://www.perplexity.ai/personal-computer)；[Windows](https://www.perplexity.ai/en-GB/hub/products/computer-for-windows)，两页核实 10-03 | Mac 的 24/7 与 remote 能力不能直接认定 Windows 完全同等；笔记本方案需要自己的 Windows 恢复/电源验收。X2/X3/X6/X7 |
| Claude（Cowork 已并入统一 Claude 体验，逐步开放） | 统一对话/任务入口、云端长任务、远程定时任务；桌面内置浏览器或已配置 Chrome | [Get started](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork)；[Scheduled tasks](https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-claude-cowork)，核实 10-03 | 当前帮助页与旧 Academy 教程“电脑必须醒着”存在版本差异。云 schedule 使用账户文件/连接器；需要本地文件/apps 的任务仍只能本地运行。X2/X6/X7；不能认为云调度能访问睡眠电脑 |

以上均为厂商公开说明，没有运行真实账户任务。不是所有产品公开其内部 source；这里不给闭源产品编造 repo/file。正式 taskbook 采用 Hermes/Atlas 已有和可核实开源来源实现其机制。

## 补充产品：只保留独特机制

| 产品 | 纳入理由与证据 | 处理 |
|---|---|---|
| Relay.app | [HITL steps](https://docs.relay.app/human-in-the-loop/human-in-the-loop-steps)，核实 10-03：approval / typed input / real-world task / human path choice；暂停执行、到期提醒与升级 | 将“等待人”变成持久状态，审批不能超时默认为批准；X7 contracts 参考，闭源，不宣称可直接搬 |
| Gumloop | [跨 app triggers](https://www.gumloop.com/blog/trigger-gumloop-agents-with-any-app)，2026-03-31：监控脚本轮询 MCP，条件成立才启动 agent | X1 确定性检查与 X7 relevance/filter；收费检查不等于免费，但说明可将 polling 与模型调用分开 |
| OpenClaw | Microsoft 官方明确采用的开源常驻 agent 机制；具体源码、license、commit 由 X7 evidence 核实 | 开源 daemon/heartbeat/cron/identity 模式候选，不能搬出第二套 Atlas runtime |
| Lindy 3.0 / Autopilot | [官方 3.0 发布](https://www.lindy.ai/blog/lindy-3-0)，页标 2025-07-30，核实 10-03：自然语言 Agent Builder、专属云电脑、团队共享 agent | 保留“API 之外的电脑操作”机制；不是 2026 新品，没有可搬内部 harness，不宣称本机无人值守等价 |
| MultiOn | [官方文档](https://docs.multion.ai/welcome)，未标日期，核实 10-03，仍自称 Agent V1 Beta，并把 AgentQ/2.0 描述为 upcoming | 远程浏览器 session 与本地 Chrome extension 有证据；不把旧 roadmap 当当前可用，不新增第二 browser runtime |
| Convergence / Proxy | [Salesforce 官方收购声明](https://www.salesforce.com/news/stories/salesforce-signs-definitive-agreement-to-acquire-convergence-ai/)，2025-05-15，编者注收购于 2025-06-11 完成 | 技术被纳入 Agentforce 方向；没有足够官方证据把独立 Proxy 当 2026 当前个人 agent 主来源。采用 X2 已核实开源组件 |

## 从产品共性到工程合同

1. UI 关闭与执行机关闭是两件事：Atlas renderer 关闭不能终止后端；笔记本 sleep/offline 时不承诺执行。把 pending/blocked/offline/retry/approval 暴露给主机与手机。
2. 专属电脑 = 持久文件、专属 profile、自己的服务身份与登录、可远程派活；不等于拥有云 VM 的供电、公网入口、宿主隔离或云 SLA。X7 必须补电源/网络/启动/更新/恢复。
3. 定时、事件与条件仅决定何时触发；同一 durable goal/task 与 session authority 执行。无变化的检测不启动模型，不由 cron 创建另一执行状态系统。
4. 多 Bot 是身份与路由，不能各自 fork 一套 runtime/goal DB；共享任务有单个 owner、交接确认、并发上限和失败回收。
5. 示范是证据而非自动泛化保证。X2 产出结构化 interaction/trace；X5 生成候选，用户审核；X4 唯一 SkillManager 管理版本；X7 按审批阈值复用。
6. 最佳可搬源优先顺序：Atlas 已验收 authority → 当前被 Atlas 实际加载的 Hermes fork 模块 → commit 锁定的兼容开源小模块 → 最薄 glue。产品 UI 不作为实现来源。

## 真实产品与后续 Atlas 验收的边界

本轮未登录/安装/付费，也未创建 Atlas 邮箱、电话、IM 账号或更改睡眠策略。后续 X 波使用用户授权的测试身份进行真实服务验收。产品功能存在不等于 Atlas 已有等价能力；每个 taskbook 的 fake 和真实验收均必须分别报告。未来公开页面更新不能自动改写本轮 snapshot，X 波启动时仅核对版本兼容与来源漂移，不重开整轮概念调研。
