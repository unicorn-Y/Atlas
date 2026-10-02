# ATLAS-X-PREP：X1–X7 外部阶段任务书重写与最新方案调研

> 这波和 ZCode 当前 C6 **并行**。
> 只做调研、来源核实、架构拆解和未来任务书。
> **不写 Atlas 生产代码，不启动 X1–X7，不修改 main 的 tasks/CURRENT.md。**
> 目标是等 T1/T1F 完成后，X 阶段可以直接施工，不再停下来重新调研。

## 分支与边界

分支： `sol/x-prep`

允许修改：
- `docs/research/2026-10-03-x-prep/**`
- `tasks/taskbooks/ATLAS-X1-*.md`
- `tasks/taskbooks/ATLAS-X2-*.md`
- `tasks/taskbooks/ATLAS-X3-*.md`
- `tasks/taskbooks/ATLAS-X4-*.md`
- `tasks/taskbooks/ATLAS-X5-*.md`
- `tasks/taskbooks/ATLAS-X6-*.md`
- `tasks/taskbooks/ATLAS-X7-*.md`
- 必要时更新 `tasks/taskbooks/ATLAS-X-EXTERNAL-PHASE.md`
- `tasks/results/ATLAS-X-PREP.result.md`
- `tasks/SOL-CURRENT.md`

禁止修改：
- `core/**`
- `frontend/**`
- `backend-adapter/**`
- Hermes fork
- `tasks/CURRENT.md`
- C6 生产文件
- T1 任务集和 runner
- 用户真实账号/配置/密钥

## 总原则

用户目标不是“自己拼一个类似品”，而是：

**把 2026 年当前成熟 Agent / personal-agent / computer-agent 产品已经做出来的东西直接拆解、找到原理名字和可复用实现，再给 Atlas 施工时照着搬。**

所以本波每一项都必须回答：

1. 现在谁做得最好？
2. 这个能力行业里叫什么？
3. 对方产品层是怎么表现的？
4. 底层架构/组件是什么？
5. 有没有开源实现？
6. 能不能直接接 Hermes/Atlas？
7. 具体去哪一个 repo / 哪些文件搬？
8. Atlas 已经有什么，哪些不要重复造？
9. 最薄接线点在哪？
10. 真施工时最小验收是什么？

不要只写概念。

---

# 1. 信息必须重新核实到 2026-10

现有 `ATLAS-X-EXTERNAL-PHASE.md` 里的产品名、日期、能力描述只能作为线索，**不能当事实直接抄**。

尤其核实：

- OpenAI dots / dot 类产品到底当前正式名称、入口和能力是什么
- Meta Muse
- Gemini Spark
- Grok Bot
- Microsoft Autopilot / Scout
- Manus Cue
- Perplexity Computer
- Claude Cowork / scheduled/background computer-use
- 2026 年最近新出的同类产品

若某个名字其实是媒体俗称、实验代号、社区误传或功能已改名，任务书里必须写正确名字，不要继续沿用错误名称。

优先来源：
1. 官方产品页 / 官方文档 / 官方 GitHub
2. 官方发布文章 / changelog
3. 开源仓库源码
4. 高质量工程文章
5. 社区讨论只用于补体验，不用于证明架构事实

每条重要来源写日期和链接/仓库 commit。

---

# 2. X1：连接外部世界

新任务书建议：
`tasks/taskbooks/ATLAS-X1-CONNECT-WORLD.md`

必须覆盖：

### MCP / apps
- MCP HTTP / Streamable HTTP
- OAuth
- MCP Tasks
- MCP Apps / ext-apps / interactive UI
- server discovery / health / reconnect
- connector auth lifecycle

### Connectors
优先国内 + 用户真正可能用：
- Gmail / Outlook
- Google Drive / OneDrive / Dropbox / Box / SharePoint
- 飞书 / 飞书文档
- 钉钉
- 企业微信
- 语雀
- 腾讯文档
- GitHub
- 日历

先查 Hermes 当前 connectors/plugin-catalog/optional-mcps，再查 OpenAI/Claude/OpenClaw/Composio/Nango 等成熟目录/授权实现。

### Channels
- Telegram
- Slack
- 飞书
- 钉钉
- 企业微信
- Email
- Webhook/API

目标是 Atlas **一套 channel gateway**，不能保留多套重复渠道实现。

### Triggers / monitors
- webhook
- 新邮件
- calendar
- file change
- page/price/status monitor
- condition watch
- recurring task

必须和 Atlas Scheduler + Hermes gateway/cron 合一。

任务书里明确：
- 复用 Hermes 哪些文件
- Atlas 哪些旧实现删除/变 adapter
- 前端统一管理面板
- fake + 真实服务验收边界

---

# 3. X2：电脑与浏览器

新任务书：
`ATLAS-X2-COMPUTER-BROWSER.md`

必须重新比较：

- Atlas 当前 CUA/UIA/SendInput hybrid
- Hermes computer_use
- Playwright
- chrome-devtools MCP
- Browser Use
- Stagehand
- cua
- OpenAI/Anthropic 当前 computer-use/tool 设计
- 2026 当前成熟 browser agent

重点不是“再加工具”，而是做成**一套稳定 computer/browser runtime**：

### Computer
- 后台优先
- 窗口定向
- foreground escalation
- screenshot/state
- mouse/keyboard/clipboard
- app/window recovery
- Windows 多屏/DPI
- 无障碍树 + vision fallback

### Browser
- CDP profile reuse
- DOM/a11y snapshot
- screenshot/vision
- downloads/uploads
- dialogs
- tabs/windows
- authenticated persistent browser
- browser vault
- handoff to human for login/CAPTCHA

### Learned workflows
重点深挖：
- Stagehand caching
- browser-use memory/workflow
- demonstration → reusable skill
- Grok Bot 类录屏学技能（若公开资料可证）

明确哪部分放 X2，哪部分留 X7。

---

# 4. X3：跨设备与产出物

新任务书：
`ATLAS-X3-DEVICES-DELIVERABLES.md`

覆盖：

- 笔记本 = Atlas 自己的常驻电脑
- 主机 = 用户工作/开发机
- 手机/网页作为派活入口
- 设备发现 / pairing / trust / online state
- A2A / remote agent execution
- task handoff
- shared conversation/task state
- artifact sync
- local/LAN web UI
- QR 配对
- share links
- readonly public artifact
- Atlas 操作自身 UI
- dashboard
- spreadsheet/document artifacts
- Univer 等可编辑产出物

对比 OpenClaw / Hermes A2A / Tailscale 类 pairing / current personal-agent device model，找最简单成熟路径。

---

# 5. X4：技能市场

新任务书：
`ATLAS-X4-SKILL-MARKET.md`

深挖：

- Hermes skills hub
- ClawHub
- skills.sh
- GitHub skills
- Agent Skills 标准
- Claude skills/plugins
- Gemini Skills
- OpenAI current skills/workflows if applicable
- Pi extensions

要求：

- Atlas 现有 C4 SkillManager 仍是唯一 registry
- market 只是发现/安装/update source
- skill + reference files + assets
- version/update/source provenance
- install/disable/uninstall
- dependencies
- user/project scopes
- skill composition/stacking

用户负责安装安全审查，不额外造 scanner。

---

# 6. X5：自我进化

新任务书：
`ATLAS-X5-SELF-EVOLUTION.md`

不要写“AI 自动改自己”这种空话。

拆成成熟可控流水线：

1. upstream watcher
2. source diff detector
3. capability change detector
4. Atlas parity mapper
5. taskbook draft generator
6. human approval
7. isolated implementation branch
8. regression/T1 subset
9. merge proposal

覆盖：

- Hermes upstream auto tracking
- Codex/OpenCode/Pi 等参考仓库更新
- 产品 changelog / docs tracking
- 新功能 → CORE-PARITY 建议
- 已 vendored 文件 → upstream changed warning
- 依赖版本更新建议
- skill learning/curator
- 成功经验沉淀为 skill/recipe/rule 的审批流

必须复用 Atlas 当前 git/taskbook/skill/hook/runtime，不造第二个“自我进化系统”。

---

# 7. X6：语音 + 统一入口 + 协作补全

新任务书：
`ATLAS-X6-VOICE-UNIFIED.md`

覆盖：

### 实时语音
基于用户已有方向：
- Pipecat
- streaming ASR + partial merge
- full duplex
- interruption/barge-in
- streaming TTS
- speaker/output queue
- local/cloud provider interchangeable
- web 先跑通，再接 Atlas
- 后续多设备

对比 2026 当前：
- Pipecat
- LiveKit Agents
- Vocode
- Hermes voice
- OpenAI Realtime current design
- Gemini Live current design
- 其他成熟开源 voice-agent

不要回到串行 VAD + 整句 ASR 架构。

### unified entry
聊天 / 干活 / browser / computer / voice 自动路由，仍走同一 session/runtime。

### collaboration
- remote agents
- A2A
- bot group
- shared task
- human in loop

### creation
- image
- audio
- no video

### headless/shared state
CLI、desktop、web/channel 必须共用后端/session，而不是各自一套 agent。

---

# 8. X7：常驻个人 Agent

新任务书：
`ATLAS-X7-ALWAYS-ON-PERSONAL-AGENT.md`

这是本波最重要的调研。

用户明确目标：

**笔记本就是 Atlas 自己的电脑，相当于别家云 VM；Atlas 常驻，用户从主机/手机/IM/语音给它派活。**

先把 2026-10 市场上的同类产品全部重新核实，再抽象共同架构。

至少研究：

- OpenAI 最新个人 agent / dots 类能力
- Meta Muse
- Gemini Spark 或当前正式对应产品
- Grok Bot
- Manus Cue
- Perplexity Computer
- Microsoft current proactive/agent products
- Claude background / Cowork / scheduled task capabilities
- Lindy / Relay / Gumloop / MultiOn / Convergence / OpenClaw 等真正有参考价值者
- 2026 最近新出的同类产品

不要为了凑名字全收录，只保留真正有独特机制的。

## 必须抽出的架构模块

### Always-on runtime
- Windows service / daemon
- startup
- health
- watchdog
- restart recovery
- durable task queue
- resumable runs
- crash recovery
- update handling

### Durable personal work state
- goals
- tasks
- waiting conditions
- monitors
- inbox
- scheduled work
- paused/blocked/retry
- human approvals
- activity history

### Proactivity
- event sources
- conditions
- relevance filtering
- “没有变化就不调模型”
- notification vs execute
- dedupe
- cooldown
- escalation

### Atlas own machine
- dedicated browser profile
- own email
- own messaging identities
- filesystem/workspace
- credentials
- persistent app logins
- background computer control
- remote handoff to user

### Autonomy
不要只写“三级权限”。

把成熟产品的 autonomy policy 拆成：
- auto
- ask
- forbid
- spend money
- external send/publish
- destructive
- irreversible
- account/security
- user-presence-required

和 Atlas 已有 permission modes 的关系写清，避免第二套权限体系。

### Learned workflows
- demonstration → workflow/skill
- repeated successful task → candidate skill
- decision points
- approval thresholds
- references/assets
- replay/edit/version

### Multi-agent
- persistent specialist identities
- routing
- group collaboration
- handoff
- shared task state
- role-specific memory/context
- avoid uncontrolled agent explosion

### User surfaces
- desktop
- phone/web
- IM
- email
- voice/call
- notifications

### Cloud-VM-equivalent on laptop
明确：
- 哪些云 VM 特性由本地笔记本天然替代
- 哪些仍需补（公网入口、wake、remote access、power/sleep、network reconnect）
- Windows 开机自启与无人值守
- 合盖/睡眠策略
- remote update/restart

## 最终必须形成 X7 architecture diagram（文字即可）

至少分层：

1. ingress
2. event bus
3. durable task/goal state
4. policy/autonomy
5. scheduler/monitor
6. agent runtime
7. tools/computer/browser
8. skills/workflows
9. identity/credentials
10. devices
11. notification/handoff
12. observability/recovery

然后逐层映射：
- Atlas 已有
- Hermes 已有
- 直接搬谁
- 新增最薄 glue
- X1–X6 哪一波提供前置

---

# 9. 所有任务书统一格式

每个 Xn taskbook 都必须包含：

- 用户可见目标
- 不做什么
- 当前 Atlas 已有
- Hermes 已有
- 其他成熟来源
- **精确 repo/file/source**
- 要直接搬的模块
- Atlas integration point
- 删除/替换的重复旧实现
- backend
- frontend
- data/state
- events
- Windows
- fake test
- real-world acceptance
- result 文件
- CORE-PARITY 新行
- dependencies
- blockers
- scope boundary

每个任务书要达到“下一次用户直接复制给 Sol 就能施工”的粒度。

禁止：
- “研究一下”
- “考虑使用”
- “可以参考”
- 只有产品名没有源码/架构
- 只写 UI 不写底层
- 又造第二套 runtime/session/plugin/skill/scheduler

---

# 9A. 新增：已完成 C1–C6 的 Latest-Best 回扫

用户 2026-10-03 新决定：**已经做完的主体也不能冻结在旧版本。**

除 X1–X7 外，再加一份主体刷新来源图：

`docs/research/2026-10-03-x-prep/10-core-latest-best.md`

逐项对：
- Hermes current main
- Claude Code current release/changelog
- Codex current stable + main
- OpenCode current release/main
- Pi current release/main
- ZCode 当前可验证能力

覆盖：
- agent loop/recovery/context
- file/edit/terminal/LSP
- session/fork/rewind
- permissions/plan/queue
- subagents/orchestration/worktree
- hooks/plugins/skills/MCP
- models/provider/cache/reasoning
- /init /review / long-session / coding UX

每项输出：
能力 | Atlas 当前 | 最新来源 | version/commit/date | repo/file | KEEP/UPGRADE/REPLACE | U1 施工建议

重要：
- 最新不等于盲抄。若新版本删掉某能力但 Atlas 当前实现更强（例如 Pi 新版不再内置 subagent），结论应是 KEEP Atlas，而不是跟着删。
- Claude Code 最新的 Mods、side-agent、plugin eval/configure、prompt-audit 等要核。
- Codex 最新 command center/fullscreen/history/parallel-work 变化要核。
- Hermes 最新 delegation/browser/skills/bot/gateway 要核。
- OpenCode/Pi 最新 edit/session/runtime 变化要核。

这份来源图将直接喂给 `ATLAS-U1-LATEST-BEST-REFRESH.md`，不要在 X-PREP 分支施工生产代码。

---

# 10. 调研产物

写：

`docs/research/2026-10-03-x-prep/`

至少：

- `00-summary.md`
- `01-x1-sources.md`
- `02-x2-sources.md`
- `03-x3-sources.md`
- `04-x4-sources.md`
- `05-x5-sources.md`
- `06-x6-sources.md`
- `07-x7-products.md`
- `08-x7-architecture.md`
- `09-source-map.md`

`09-source-map.md` 做成最实用的表：

能力 | 最佳来源 | repo/file | Atlas 接线点 | 波次 | 是否可直接搬

不要堆营销文案。

---

# 11. 并行方式

Sol 主控，Luna high 实际调研/写任务书。

可独立拆：
- X1
- X2
- X3
- X4
- X5
- X6
- X7 products
- X7 architecture + source map

尽量使用当前运行环境允许的最大子代理并发，不写死数量。

Sol 最后统一做：
- 去重
- 依赖顺序
- Atlas/Hermes 已有能力核对
- source path 核验
- taskbook 粒度审查

---

# 12. 验收

本波没有生产代码测试。

必须验证：

- 每个开源 repo/source path 真存在
- commit/tag/date 有记录
- 闭源产品能力必须有官方/高可信来源
- 同一个能力不要在多个 X 波重复实现
- 7 个 X taskbook 都完整
- X7 架构能明确落到 Atlas 已有组件
- 没有修改生产代码
- 没有开始施工 X1–X7

写：

`tasks/results/ATLAS-X-PREP.result.md`

最后：
- `tasks/SOL-CURRENT.md` → `AWAITING_REVIEW`
- push `sol/x-prep`
- 回报 HEAD
- 停止

**不要开始 X1，不要 merge main。**
