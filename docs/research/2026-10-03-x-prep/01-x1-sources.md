# X1 连接外部世界：来源与落地核对

核对日期：2026-10-03。外部仓库快照、commit 日期、许可证和本地路径见同目录 `evidence-x1-x4.json`。Hermes 的有效基线是 Atlas `core/pyproject.toml` 固定的 `unicorn-Y/hermes-agent@e287231d7906bcce5bc373d20fb2e3e1e6427220`，对应 `D:\hermes-agent`；不沿用旧 VENDORED/adapter 注释中的历史提交。

## 能力映射

| 能力 | 最佳来源 | repo / 精确文件 | Atlas 已有 | Hermes 已有 | 直接搬什么 | 最薄接线 | 波次 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MCP stdio 与远程 Streamable HTTP | MCP Python SDK 与当前协议规范 | `modelcontextprotocol/python-sdk`: `src/mcp/client/streamable_http.py`, `src/mcp/client/auth/`；`modelcontextprotocol/ext-apps`: `specification/2026-01-26/apps.mdx` | `core/atlas/tools/mcp_client.py` 仅接受 `stdio` / 旧 SSE；已有工具命名、只读标记、连接状态、单服务器重连方法 | `tools/mcp_tool*.py`, `hermes_cli/mcp_catalog.py`, `optional-mcps/*`；支持本地 stdio 和远程 OAuth MCP | SDK transport/session 实现与协议测试；Hermes catalog entry schema/生命周期逻辑作为模式 | 在现有 `MCPClient` transport dispatcher 增加 `streamable_http`，config 按 transport 验证；沿用工具索引和运行状态 API | X1-W1 |
| OAuth / 凭据生命周期 | MCP 授权规范 + SDK OAuth client；Nango 只作 provider auth 生命周期参考 | MCP SDK `docs/client/oauth-clients.md`, `src/mcp/client/auth/`; Nango `packages/webapp/src/pages/Integrations/providerConfigKey/Settings/components/OAuthSettings.tsx`, `McpOAuthSettings.tsx` | MCP 配置没有授权状态、回调/refresh 状态机；不得把 bearer token 写日志或普通 TOML | `tools/mcp_tool_transport.py`, `tools/mcp_tool_health.py`, `hermes_cli/web_server_oauth.py`, `hermes_cli/web_routers/oauth.py`, MCP catalog oauth 示例 | OAuth PKCE / metadata discovery / refresh 的 SDK 原语，不移植 Nango 服务端 | 凭据仍走 Atlas 现有 machine-local credential/config Authority；连接状态只存 provider、scope 与 expiry 元数据；授权 UI 请求短期 action-bound 许可 | X1-W1 |
| MCP Tasks | MCP Tasks 官方扩展草案（2026-07-28） | `tasks.extensions.modelcontextprotocol.io/specification/draft/tasks`; 当前定义 `tasks/get`, `tasks/update`, `tasks/cancel`，`tools/call` 可返回 task handle | Atlas scheduler 有 durable scheduled/event task；MCP client 目前同步等待 `call_tool` | Hermes MCP tool layer 目前以请求响应调用为主；gateway/cron 的长任务不是 MCP Tasks 等价实现 | 只直接采用扩展协商、状态与轮询协议定义；不要把草案当稳定核心 | 加能力协商 + task handle 状态适配器，映射到已有 task/run state；等待扩展升为稳定版前置，不另建 task store | X1-W2（draft gate） |
| MCP Apps / interactive UI | MCP Apps 官方稳定扩展（2026-01-26）与官方 ext-apps SDK | `modelcontextprotocol/ext-apps`: `specification/2026-01-26/apps.mdx`, `examples/basic-host/`, `examples/basic-server-react/`, `src/` | 当前对话工具结果能显示结构化数据，但未发现 ext-app host / sandbox 视图 | MCP 工具调用与 desktop 卡片存在；没有证据表明其提供完整通用 MCP Apps host | host bridge 的协议校验、sandbox 样例与 resize/resource 通信模式；不直接运行不受信任 HTML | 对话内建立受隔离的 WebView 视图，origin/capability 绑定具体调用；只允许规范声明的 host bridge，禁止任意 preload/native bridge | X1-W3 |
| 连接器目录与授权入口 | Hermes curated optional MCP catalog + Nango provider manifests | Hermes `optional-mcps/*`, `hermes_cli/mcp_catalog.py`, `tools/mcp_tool_config.py`; Nango `integrations/`, `packages/shared/lib/providers/`（先复验各 provider 当前许可证/路径） | Atlas 可配任意 MCP server、技能中心可搜索技能；没有统一外部连接目录 | Hermes catalog 有 reviewed MCP entries，含 stdio/remote OAuth；插件 catalog 是另一种扩展目录 | Hermes `optional-mcps` manifest 的展示/依赖/授权声明；连接器执行仍用 MCP/API adapter | 将 catalog item 转成 Atlas MCP config draft；账号授权前显示 provider scopes / host / data classes；安装、删除和凭据改动分离 | X1-W2 |
| IM channel gateway | Hermes gateway adapter contract | `gateway/platform_registry.py`, `gateway/platforms/base.py`, `gateway/platforms/ADDING_A_PLATFORM.md`, `gateway/run_adapters.py`, `gateway/run_inbound.py`, `gateway/run_notifications.py` | Atlas 有 `TelegramService` 单渠道及 `/api/channels/telegram*`；不是统一 gateway | 一个 `gateway` subsystem 覆盖 Telegram、Discord、Slack、WhatsApp、Signal、Matrix、Mattermost、Email/SMS、钉钉、飞书/WeCom、Weixin、QQ Bot、Teams、Google Chat、Webhook 等 | 挑最需要的官方 Hermes adapters 与 BasePlatformAdapter 契约，保留传输接收/发送、媒体、typing、重试/状态 | adapter ingress 转为 Atlas 现有 run/session 提交函数；channel + account + remote conversation 仅作 session source/route metadata。不能同时启动 Hermes agent/session runtime | X1-W2 |
| Webhook / email / calendar / file / page monitors | Atlas Scheduler + Hermes gateway event/webhook/cron reference | Atlas `core/atlas/scheduler/__init__.py`; Hermes `gateway/platforms/webhook.py`, `gateway/platforms/msgraph_webhook.py`, `cron/jobs.py`, `cron/monitor.py`, `cron/delivery_queue.py` | Atlas Scheduler 支持 date/interval/cron/event，并有 `file.changed` watcher、run history；暂无外部 webhook/email/calendar/page monitor provider | Hermes webhook、MS Graph webhook 和 durable cron delivery queue 可作 adapter 范例 | 复用 Hermes verification/delivery/retry adapter 模式；现有 Scheduler 状态机和任务记录不搬成第二份 | 外部事件只生成有来源签名/去重键的 Scheduler event；通知和执行共用 task action/run；同一 event id 不可重复触发 | X1-W3 |
| 前端连接管理 | Hermes Desktop connector/MCP/channel settings patterns | Hermes `apps/desktop/src/store/connector-catalog.ts`, `apps/shared/src/catalog-browse.ts`, `apps/shared/src/catalog-install.ts`; Atlas `frontend/src/renderer/pages/SettingsPage.tsx`, `TelegramPanel.tsx`, `AutomationPage.tsx` | Telegram 和 Automation 单页存在；没有统一 connector/channel 状态页 | Desktop 分列 MCP、Channels、catalog entry、auth/status 操作 | 复用状态和认证步骤，不复制 Hermes UI/state store | Settings 下用一个 Connections 页面接现有 API：目录/已连接/需要授权/失败与健康；触发器仍编辑已有 Automation task | X1-W4 |

## 外部事实与版本边界

- MCP 2025-11-25 spec 把 Streamable HTTP 和 OAuth authorization 定为规范组成；MCP Apps 已标为 `2026-01-26` Stable；MCP Tasks 页面当前明确标注 Draft、文档版本 2026-07-28。来源：[MCP 2025-11-25 发布说明](https://blog.modelcontextprotocol.io/posts/2025-11-25-first-mcp-anniversary/)、[MCP Apps](https://apps.extensions.modelcontextprotocol.io/)、[MCP Tasks 草案](https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks)。Tasks 必须设 draft gate。
- Hermes 官方 integrations 文档当前列出 27+ 平台并统一归于 gateway subsystem；它证明平台覆盖与入口架构，不证明 Atlas 可整套复用 Hermes 的 runtime/session。[Hermes integrations](https://hermes-agent.nousresearch.com/docs/integrations/)
- Nango 适合作为 OAuth/provider lifecycle 参照，但其服务端、数据库、secret authority 和 UI 不应直接搬入 Windows Atlas。外部连接器授权若采用 hosted SaaS 会改变凭据控制边界，需单独决定；本任务书基线为 Atlas 本地凭据存储。

## 需要实施时先确认的阻塞项

1. MCP OAuth 的 Atlas 本机 redirect URI、loopback port 生命周期、token encryption backend 与已存在 credential/config Authority 的实测行为。若没有安全本机存储，OAuth provider UI 可先做只读目录，不得退化成明文 token 配置。
2. Channel adapters 的 Python 依赖/许可证和 SDK 版本逐平台复核；本波只把 Hermes 仓库明确 MIT 授权的文件纳入候选。Feishu、DingTalk、WeCom 的真实 bot/app credentials 和公网 webhook 域名需测试者提供，未提供时标为未验收。
3. MCP Tasks 仍是草案；不可作为 W1/W2 的交付 blocker，也不可声称全面兼容。
4. MCP Apps 是跨源 UI 面，必须先有 CSP/origin/host-bridge 最小威胁审查；若应用资源不能在隔离 WebView 内加载，则该项阻塞，不能退回允许任意远程页面脚本直连 Atlas API。

## 验收证据线

fake：loopback stdio 与 Streamable HTTP MCP server、假的 OAuth authorization server（PKCE/refresh/revoke/拒绝）、测试 MCP App host iframe、fake webhook 签名/重复投递、Fake Scheduler event、stub channel adapter。断言连接状态、工具列表替换/重连、approval/event idempotency、无 token/log 泄漏、重复事件只生成一个 run。

真实服务：用户配置的非生产 MCP OAuth server/官方 MCP server；只读 Gmail/Drive/Outlook/OneDrive/飞书文档查询；Channel bot 在私聊测试；真实 webhook 验签和文件/日历变化监控。每个真实 provider 写清账户、scope、读写操作和人工批准边界。缺真实账号时保留 `NOT VERIFIED`，fake 结果不得代替真实 OAuth/provider 互通声明。
