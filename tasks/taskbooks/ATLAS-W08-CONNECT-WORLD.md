# ATLAS-W08-CONNECT-WORLD（第八波：连接外部世界）

> **冻结（2026-10-01）**：主体优先，本书等主体实测通过后再排期；执行前按当时的内核（Hermes）重写接入部分。见 `docs/plan/00-MASTER-PLAN.md` 第五节。

STATUS: READY（W06 交付后即可开始，可与 W07 并行）
PROTOCOL: +1
先读：`docs/plan/SOURCE-MAP.md` F 节、`docs/research/2026-09-30-landscape/02-connectors-extensions-automation.md`
主要来源：H（Hermes Agent）的 MCP 客户端、连接器、聊天渠道；O（OpenClaw）的自动化设计；MCP 官方 `ext-apps`

## 本波目标

调研结论：Atlas 作为「全能」Agent 最大的缺口在连接外部世界。ChatGPT 有 1400+ 插件、Manus 能被新邮件和日历事件触发、Claude 优先走连接器。本波让 Atlas：
- 接上 2026 年新版 MCP 生态（远程服务器、OAuth 登录、对话里的交互界面）；
- 有一个能一键接入的连接器目录，**国内服务优先**（ChatGPT、Claude 都没做）；
- 能从飞书、钉钉、邮件收任务；
- 能被外部事件触发（Webhook、新邮件、关键词条件）。

---

## 1. MCP 客户端升级（后端，从 H 搬）

**来源**（H `tools/` 下，`mcp_tool.py` 是门面，15 个兄弟文件）：
- `mcp_tool.py`（696 行）：一个后台事件循环在守护线程里跑，每个服务器是一个长期任务（`MCPServerTask`），所有状态改动加锁
- `mcp_tool_transport.py`（687 行）：stdio 启动（OSV 漏洞预检、npx 缓存、子进程登记 + 死亡监控）、**Streamable HTTP** / SSE 连接（预检、身份头、客户端证书、OAuth）、协议协商、首次工具发现
- `mcp_oauth_manager.py`（428 行）：每个服务器的 OAuth 状态、跨进程令牌刷新、并发 401 去重、触发重连
- `mcp_oauth.py`、`mcp_oauth_provider.py`、`mcp_oauth_device.py`（设备码登录）
- `mcp_tool_sampling.py`（316 行）：服务器发起的请求——**sampling**（让客户端调模型）和 **elicitation**（向用户要信息）
- `mcp_tool_health.py`、`mcp_liveness.py`、`mcp_death_supervisor.py`：健康检查和自动重启
- `mcp_tool_discovery.py`、`mcp_tool_registration.py`、`mcp_tool_schema.py`、`mcp_schema_cache.py`：工具发现、注册、参数结构缓存
- `mcp_tool_scope.py`：按会话 / 子 Agent 限定可用服务器
- `tools/osv_check.py`：启动 npx 包前查已知漏洞

**做法**：
1. 用 H 的结构替换 Atlas 的 `core/atlas/tools/mcp_client.py`（542 行，只有 stdio / SSE）。保持 Atlas 现有接口（`/api/mcp/servers` 增删、重启）不变，新增字段：`transport: "stdio"|"http"|"sse"`、`url`、`headers`、`oauth: {enabled, client_id?, scopes?}`、`enabled`。
2. OAuth 令牌存系统凭据库（keyring，参考 `atlas/telegram.py`），**不落明文文件**（H 存在磁盘上，这里要改）。
3. OAuth 回调：后端新路由 `GET /api/mcp/oauth/callback`（浏览器顶层跳转，没有 Origin，OriginGuard 会放行），**必须校验 `state`**，只接受本进程发起、5 分钟内、未使用过的 `state`。授权页用系统浏览器打开（前端调用 `atlasDesktop.openExternal`）。
4. **elicitation**：服务器向用户要信息时，转成 Atlas 现有的 `input.required` 事件，加字段 `schema`（JSON Schema）和 `source: {server}`；用户回答走 `input.response`，带 `data` 对象。
5. **sampling**：服务器请求客户端调模型时，用当前 run 的模型，经过 W06 的用量记录；默认需要用户同意一次（每个服务器），设置里可改成总是允许。
6. **Tasks 扩展**（2026-07-28 规范）：服务器返回任务句柄时，轮询 `tasks/get` 直到结束，进度用 `tool.output` 推送，用户取消运行时调用 `tasks/cancel`。H 如果还没实现，按官方规范自己写。

**测试**：搬 H 的 MCP 测试（`tests/tools/` 下 mcp 相关），用本地假 MCP 服务器（stdio 和 HTTP）覆盖：连接、OAuth（假授权服务器）、令牌刷新、401 恢复、elicitation、sampling、健康重启、`state` 校验失败被拒。

## 2. MCP Apps：对话里的交互界面（前后端，依赖官方 SDK）

**来源**：`modelcontextprotocol/ext-apps`（官方规范 + SDK + 示例服务器）；`@mcp-ui/client` 的 `AppRenderer`。动手前核实两者的许可证。

**做法**：
- 后端：工具定义里带 `_meta.ui.resourceUri`（`ui://...`）的，调用完成后读取该资源；发事件 `tool.ui {tool_call_id, server, resource_uri, html_url}`；新路由 `GET /api/mcp/apps/resource?server=&uri=` 返回 HTML，带沙箱 CSP（`default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: https:; connect-src 'none'`）。
- 界面里的操作（调用同一个服务器的工具）：前端经 `POST /api/mcp/apps/call {run_id, server, tool, arguments}` 转发；只允许调用**同一个服务器**的工具；照常遵守权限模式（安全审查由用户亲自负责，本计划不做）。
- 前端：用 `AppRenderer` 在沙箱 iframe（不给 `allow-same-origin`）里渲染，支持内嵌 / 画中画 / 全屏三种显示；通过 postMessage 桥接。**iframe 拿不到 Atlas 的 API token**（Electron 只给主页面注入，保持）。
- 测试：用 ext-apps 的示例服务器跑一个带界面的工具。

## 3. 连接器目录（后端从 H 搬 + 补国内条目，前端做目录页）

**来源**：H `tools/connectors/`（`catalog.py` 382 行、`search.py`、`mcp_oauth.py` 346 行、`managed.py`、`live.py`、`operation.py`、`gateway/`）；国内服务清单 `yehuoshun/awesome-china-mcp`。

**H 的做法（要搬到的行为）**：目录里每一项解析成「插件 / MCP 服务器 / 技能」安装目标；**用户批准之前不安装任何东西**；安装走统一流程（版本锁定、黑名单、安全扫描、MCP 服务器和技能立即生效）；接入过程用「连接卡片」展示进度（`connection.request → connection.update* → connection.respond`）。

**做法**：
1. 搬 H 的目录、搜索、安装流程，接到第 1 节的 MCP 客户端和 Atlas 已有的技能系统。
2. **内置目录**（`core/atlas/connectors/catalog.json`，每项：`id, name, category, icon, description, kind: "remote-mcp"|"local-mcp"|"api-key"|"builtin", install: {...}, auth: "oauth"|"api_key"|"none", source_url, official: bool`）。先放这些（**每一项接入前都要打开仓库确认还在维护、许可证可用**）：
   - 国内：飞书（官方 `larksuite/lark-openapi-mcp`）、语雀（官方 `yuque/yuque-mcp-server`）、高德地图（官方）、百度地图（官方 `baidu-maps/mcp`）、12306（`Joooook/12306-mcp`）、小红书（`xpzouying/xiaohongshu-mcp`）、微博、B 站、微信公众号发布（`caol64/wenyan-mcp`）、Gitee（官方 `oschina/mcp-gitee`）、阿里云 / 腾讯云 / 火山引擎（官方）、微信读书、A 股数据（`FinanceMCP`、`mcp-aktools`）
   - 国际：GitHub、Gmail / Google 日历 / Drive、Microsoft 365（H `tools/microsoft_graph_*.py`）、Notion、Slack、Linear、Figma、Home Assistant（H `tools/homeassistant_tool.py`）
3. 官方 MCP Registry 搜索：`GET /api/connectors/search?q=` 同时搜内置目录和官方 Registry（预览版 API）；Registry 的结果标「社区」。
4. **主动建议**：新工具 `suggest_connector {id, reason}`，Agent 发现需要某个没接入的服务时调用；发事件 `connector.suggested {id, name, reason}`，用户在卡片上一键接入，接入后这一轮可以继续。
5. 接口：`GET /api/connectors`（目录 + 是否已接入 + 状态）、`POST /api/connectors/{id}/connect`（返回 `op_id`，进度用事件 `connector.progress {op_id, step, detail}`）、`DELETE /api/connectors/{id}`。
6. 可选的云端后备：Composio（MIT SDK，托管 OAuth，1000+ 集成），用户填自己的 API Key 才启用。

## 4. 聊天渠道：飞书、钉钉、邮件（后端，从 H 搬）

**来源**：H `gateway/`（门面 `run.py` 6154 行 + `run_*.py` 兄弟文件、`session*.py`、`delivery*.py`、`pairing.py`）、`gateway/platforms/ADDING_A_PLATFORM.md`（必读）、`plugins/platforms/`：
- `feishu/`（WebSocket 长连接 + Webhook 两种；私聊和 @ 才响应；卡片按钮事件）——**长连接不需要公网 IP**
- `dingtalk/`（Stream 模式，`dingtalk-stream>=0.20`，AI 卡片回复）——**不需要公网 IP**
- `email/`（934 行，IMAP 轮询收、SMTP 发；注意它修过的 IMAP 连接泄漏问题）
- `wecom/`（回调方式，需要公网地址，**本波不做**，等 W10 的中转）

**做法**：
1. Atlas 已有 Telegram 渠道（`core/atlas/telegram.py`）。把它和新渠道统一成「渠道」抽象：参考 H 的适配器接口（收消息、发消息、发卡片 / 按钮、发文件、身份白名单）。只搬 H 网关里**渠道适配所需的最小部分**，不要整个 `gateway/run.py`。
2. 搬飞书、钉钉、邮件三个适配器。
3. 行为和 Telegram 一致：只响应白名单里的账号；手机发来的任务默认「改前问我」，审批用卡片按钮；会话标 `source: "feishu"|"dingtalk"|"email"`。
4. 邮件渠道的邮件内容不进长期记忆。
5. 凭据存系统凭据库。
6. 接口：`GET/PUT /api/channels/{feishu|dingtalk|email}`、`POST /api/channels/{name}/test`（格式和现有 Telegram 接口一致）。

**测试**：搬 H 对应适配器的测试；mock 平台 SDK。

## 5. 触发器：Webhook、新邮件、条件触发（后端，照 O 的设计移植）

**来源**（O 是 TypeScript，照逻辑用 Python 重写）：
- 入站 Webhook：O `docs/automation/cron-jobs/webhooks.md` 及实现（`src/gateway` 里 hooks 相关）
- IMAP：O `extensions/imap/src/`（`watcher.ts`、`sender-gate.ts`、`prompt.ts`、`state.ts`、`config.ts`）
- 条件触发：O `docs/concepts/standing-intents.md` 及实现（`src/` 里 intent 相关，搜 `standing`）
- Gmail 推送：O `docs/automation/cron-jobs/gmail.md`（需要公网 HTTPS，本波不做，IMAP 已覆盖）

**做法**（全部接进现有调度器 `core/atlas/scheduler`，作为新的事件类型）：
1. **入站 Webhook**（照 O）：默认关闭；专用令牌（不是 Atlas 的 API token）；`POST /hooks/{path}`，头 `Authorization: Bearer <hook-token>`、`Idempotency-Key`；每个路径映射到一个触发任务（配方或提示模板 + 工作目录 + 权限模式）；模板可以引用请求体字段（照 O 的 `{{...}}` 语法）；可选 `waitForCompletion`；返回 `{ok, run_id}`。**OriginGuard**：`/hooks/*` 只认 hook 令牌，不认 API token，也不开放给浏览器来源（新增一种受信方式，不放宽现有规则）。
2. **新邮件触发**（照 O 的 IMAP 扩展）：监视一个邮箱文件夹；发件人白名单；**每封邮件用受限的读信任务处理**（照 O：邮件内容只当数据，不跟随邮件里的链接和指令；读信任务只有最少的工具）；去重状态持久化。
3. **条件触发**（照 O 的 standing intents）：「当 X 出现时做 Y」。新工具 `intent {action: create|list|cancel, description, triggers: [[关键词…]], scope, expires_at?, cooldown?, max_fires?}`；匹配时**不调用模型**，用 SQLite 全文索引预筛，一组关键词全部出现才命中；默认冷却 24 小时、最多触发 3 次、90 天过期（照 O 的保守默认值）；命中时把一段有长度上限的提示块交给这一轮的主回复。来源：用户消息、聊天渠道消息、新邮件。
4. **网页变化监控**（自己写）：定时用 `web_extract` 抓取（带 SSRF 防护），和上次正文比较，有实质变化就触发任务；变化内容是不可信数据。
5. 所有触发器产生的运行：标 `trigger: {type, id}`；外部内容不进长期记忆。
6. 接口：沿用 `/api/schedules`，`trigger_type` 增加 `webhook`、`email`、`intent`、`web_watch`；`GET /api/intents`、`DELETE /api/intents/{id}`。

**测试**：Webhook 令牌校验、幂等、OriginGuard（API token 在 `/hooks` 上无效）、模板渲染；IMAP 用假服务器；条件触发的匹配、冷却、次数、过期；网页监控的变化判断和 SSRF。

## 6. 前端

1. **MCP**：设置 → MCP 服务器：添加时可选 stdio / HTTP；HTTP 的「用账号登录」按钮（OAuth，系统浏览器打开）；健康状态和自动重启记录。elicitation 卡片按 `schema` 渲染表单。sampling 第一次请求时的同意卡片。
2. **MCP Apps**：`tool.ui` 在对话里渲染（`@mcp-ui/client` 的 `AppRenderer`），三种显示模式。
3. **连接器目录**（新页面，侧栏入口「连接」）：分类（国内常用、办公、开发、生活、金融、云服务）、搜索（含官方 Registry）、卡片（图标、说明、官方 / 社区标记、已接入状态）、「连接」按钮 → 连接卡片显示进度；已接入的可以断开。参考 H `apps/desktop` 的 `store/connection-request.ts` 和连接卡片组件。
4. **@ 应用**：输入框 `@` 菜单里除了文件，再列出已接入的连接器；选中后这一轮优先用它。
5. **主动建议**：`connector.suggested` 卡片：「这件事需要接入 <名称>：<原因>」+「连接」按钮。
6. **渠道**：设置 → 手机远程：在 Telegram 旁边加飞书、钉钉、邮件三个标签页，样式照 `TelegramPanel.tsx`。
7. **触发器**：自动化页加「Webhook」「新邮件」「条件触发」「网页监控」四种触发方式的创建表单；Webhook 显示完整的调用示例（curl）和令牌（只显示一次）；条件触发列表可以取消。

## 7. 验收

| 项 | 最强的是 | Atlas 要做到 |
| --- | --- | --- |
| MCP | Hermes（HTTP、OAuth、健康、采样）、ChatGPT（MCP Apps） | H 的能力全部搬到 + MCP Apps 渲染 + Tasks；令牌在系统凭据库 |
| 连接器 | ChatGPT（1400+）、OpenHuman（118 个一键授权） | 一键接入 + 主动建议 + @ 应用；**国内服务最全**（ChatGPT、Claude 都没有） |
| 渠道 | OpenClaw、Hermes（20+） | 飞书、钉钉、邮件、Telegram，审批用卡片按钮 |
| 触发器 | Manus（事件触发）、Claude Code Routines（Webhook）、OpenClaw（IMAP、条件触发）、Google（网页监控） | **四种全有**（没有一家同时具备）；外部内容一律当不可信数据 |

**真机**（都要跑并记录）：
1. 接入一个需要 OAuth 的远程 MCP 服务器（例如 GitHub 官方 MCP），用它查一个仓库的 issue。
2. 从目录一键接入高德地图，问「从公司到家怎么走」。
3. 飞书给机器人发「总结一下桌面上的 xx 文件」，在飞书里收到结果；中途需要审批时在飞书卡片上点允许。
4. 用 curl 调 Webhook 触发一个配方。
5. 设一个条件触发「当我提到发版，提醒我先备份数据库」，然后在对话里提到发版。
6. 监控一个网页，手动改动后触发任务。

## 8. 交付

同 W06（提交、`VENDORED.md`、结果文件 `tasks/results/ATLAS-W08-CONNECT-WORLD.result.md`、审查记录）。
