# 前端多 Agent 界面证据（组件级）

**证据等级：S**（app.asar/webview/assets 中的真实 chunk 文件）。

---

## 1. 43 个与 agent/collab/subagent 相关的 UI chunk

```
Collab-a86ce4229868.js
Collab-f048009511ce.js
collab-schema-1362362c8a67.js
collaboration-schemas-9ad991c40494.js
collaborator-avatar-cfdc8d7a57ac.js
subagent-panel-e2d31e8d7515.js
subagent-row-3ffa8b6ba655.js
subagents-5b810ee166a7.js
subagents-b6d97b99ebf5.js
chatgpt-subagents-panel-74a42f22ac75.js
chatgpt-subagent-final-response-query-a09eb28a8adf.js
local-conversation-subagents-panel-tab-f7116bdb2e6f.js
open-local-conversation-subagents-panel-6bda7c73a612.js
open-local-conversation-subagents-panel-f83cd53ccff5.js
open-chatgpt-subagents-panel-0e623d628a85.js
agent-activity-item-1be092f0c744.js
page-collaborator-colors-72b01c060790.js
page-collaborator-label-bd47678174d0.js
subagent-962387dfc789.svg
```

## 2. 从文件名推断的界面结构

| 文件 | 推断的界面元素 |
|---|---|
| `subagent-panel-*` | 子代理**侧面板**主体 |
| `subagent-row-*` | 面板中每个子代理的**一行**（状态/名称/操作） |
| `subagents-*` ×2 | 子代理列表 / 数据层 |
| `chatgpt-subagents-panel-*` | ChatGPT 模式（区别于 Codex Work 模式）的子代理面板 |
| `local-conversation-subagents-panel-tab-*` | 本地会话里的**子代理 Tab** |
| `open-local-conversation-subagents-panel-*` ×2 | 打开子代理面板的入口（两个变体，可能是 feature gate 两分支） |
| `open-chatgpt-subagents-panel-*` | ChatGPT 侧的打开入口 |
| `agent-activity-item-*` | **代理活动条目**（对应 `subAgentActivity` 通知的 `started/interacted/interrupted/completed`） |
| `chatgpt-subagent-final-response-query-*` | 子代理**最终回复**的查询（拉取子代理结论） |
| `collaborator-avatar-*` | 协作者头像（多代理时区分身份） |
| `page-collaborator-colors-*` | 协作者配色（每个 agent 一种颜色） |
| `page-collaborator-label-*` | 协作者标签 |
| `Collab-*.js` ×2 | 协作模式外壳 |
| `collab-schema-*` / `collaboration-schemas-*` | 协作数据 schema（前端侧的 zod/类型校验） |
| `subagent-*.svg` | 子代理图标 |

## 3. 与后端协议的一一对应

| 前端文件 | 后端协议 |
|---|---|
| `agent-activity-item` | 通知 `subAgentActivity`（`SubAgentActivityKind`：started / interacted / interrupted / completed） |
| `subagent-row` | `CollabAgentState` / `CollabAgentStatus` |
| `subagent-panel` | `CollabAgentTool` 的 `listAgents` |
| `chatgpt-subagent-final-response-query` | 子代理完成后拉取其最终消息 |
| `Collab-*` | `CollaborationMode`（`ModeKind`：plan / default）+ `CollaborationModeMask` |
| `collaborator-*` | 协议 `SubAgentSource`（区分代理来源） |

## 4. 由此确认的界面能力（不需要登录截图）

1. **子代理有独立侧面板**，不是折叠在消息流里。
2. **每个子代理一行**，可查看状态（活动/空闲/中断/完成）。
3. **可拉取子代理的最终回复**（`final-response-query` 是独立的查询 chunk）。
4. **子代理有身份可视化**：头像 + 配色 + 标签。
5. **存在"打开子代理面板"的多个入口**，且分 ChatGPT 模式与本地会话两种。
6. **本地会话的子代理是 Tab 形式**（`...-panel-tab-*`），说明可与主对话并列查看。
7. **协作模式是独立外壳**（`Collab` chunk + `collaboration-schemas`）。

## 5. 其他界面的同类证据

| 能力 | 前端 chunk |
|---|---|
| Diff | `auto-diff`、`code-diff`、`diff-preview`、`diff-summary`、`editor-diff-page`、`file-diff` ×3、`diff-*` 多个 |
| 后台终端 | `background-terminal-149ce561556d.js` |
| 用量 / 限额 | `usage`、`rate-limit`、`rate-limit-reset-checkout`、`thread-usage-breakdown`、`workspace-credits`、`credits.svg` |
| 排队消息 | `queued-message-list-aa3e4e664a72.js` |
| 计划 | plan 相关 chunk + `turn/plan/updated` |
| 浏览器/WebMCP | `browser-page-preload.js`、`get-browser-webmcp-policy` |

## 6. 与 "UI 可视化覆盖率" 的关系

这些是**组件级证据**，不是**像素级截图**。二者区别：
- 组件级证据（本文件）能证明"有什么界面、大概长什么样、连到哪个协议"
- 像素级截图需要登录账号

因此 `COVERAGE.md` 中把"界面可视化"记为 ~15%（仅 2 张真实截图），而不是把组件清单算作可视化完成。
