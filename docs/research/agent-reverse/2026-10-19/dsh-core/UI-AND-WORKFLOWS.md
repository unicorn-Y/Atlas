# 官方 Web UI：操作 → 数据 → 执行链（源码静态审查）

后续 UI 操作的组件/源代码路线固定在官方源码 root `0.2.1-rc.2`，不是 standalone npm Web UI `0.0.1-rc.5`。另已安装实际 CLI `0.2.0-rc.2` runtime dependency 图，并静态确认若干旧版 UI/runtime 包含在 graph 中；这不代表组件对应旧 standalone Web build 或已由 default profile mount。社区 DSH Desktop 完全排除。S 代表读过的具体静态文件；运行效果/发布版实际 mount 仍 U。

## 发行 Web 实物检查（新增，静态 S；没有运行）

Release 中的 `@deepseek-ai/dsh-web-frontend@0.0.1-rc.5` 是 Vite 静态产物。实际 index 载入 `assets/index-DYtepzMn.js`，preload `vendor-Cjbwl5VI.js`，再引用两份 CSS；package 内没有 `.map`，也没有 npm 中同版本的 TS 源码。资产逐项 SHA/大小位于 `extracted/web-assets-map.json`，指定产品词搜索含 offset 与各自最多 150-byte 邻域的记录位于 `extracted/web-chunk-symbols.jsonl`。

在此旧发布包的 main entry 中可见 `session` 和 `prompt` 词项；按该证据检索不到 `remote.mux`、`subagent`、`interrupt`、`assistant`、`job`、`usage`、`team`、`trajectory`。其它通用 editor / parser vendor chunk 会命中 `interrupt`、`job`、`session` 等普通字符串。**这些都是静态文本发现，既不能将较新的 0.2.1-rc.2 UI 行为归给 0.0.1-rc.5，也不能仅凭词项缺失声称旧版功能不存在。** REA 对 bundle 的应用图为 partial（main entry semantic 阶段超过工具堆限制），且没有受控运行环境与 Host 接口，所以本篇随后各操作流程仍是固定新源码的 S 级路由追踪，不是旧 npm 的 R 证据。

## A. 子代理树：查看/进入/侧栏打开

- 入口：`packages/client/ui-subagent/src/client/index.ts:52-101` 在 Conversation session header 注册 slot，`SubagentCatalogAction` 读取 `subagentCatalog` projection，`SubagentHeaderLineage.tsx:18-45,196-395,456-492` 使用 parent、childId、mode 与 timing/status，递归展开；loading/error 的 refresh path 明确。`SubagentHeaderLineage.tsx:660-735` 有键盘导航、活动数量与 running dot。
- **打开子代理主会话**：`openChild({parentSessionId,childSessionId,mode})` 交 `ClientSessions` 选定 child Session，继承 Chat/Trajectory 视图，而不是仅把子代理最后一条结果显示在父消息下。
- **在右侧打开**：`openChildAside` → `ctx.sidebarRight.openResource(subagentChatAddress(address))`。资源名 `dsh-resource://subagentchat/session/<child>?parent=...&mode=...`，`packages/client/ui-subagent/src/client/sidebar-chat/index.tsx:18-21,47-82,155-201` 注册可恢复 tab 和 `conversation.content` embedded surface。
- **状态**：child summary 的 `subagentTiming` 是会话 `turn/start/end` 事件派生的计时投影，`packages/subagent/subagent/src/projection.ts:60-114`，不是 UI 自计量进度百分比；child runtime activity 由 parent catalog + session status merge。
- **限制**：`one-shot/unknown` 与 parent 不可用会触发 read-only composer，`ui-subagent/src/client/index.ts:37-44,96-101`；不能认为所有展示的 child 都可继续对话。

## B. 子代理对话：输入、干预、停止

```text
用户在 child 对话发送
 -> ClientSession.beginSubmission / session.ts:240-304
 -> if normal: remote.session.prompt
 -> if child: remote.subagents.prompt({parentSessionId,childSessionId,mode})
 -> Subagent service validates address/ownership and delivery availability
 -> SubagentManager.queuePrompt or steerPrompt
 -> child ReactLoopInbox.next-turn / next-step
 -> durable child Session event + live frame
 -> client history + trajectory/rendering
```

- 客户端分流见 `packages/api/session-controller/src/client/sessions/session.ts:265-304`；停止分流 `session.ts:342-357` → `subagents.interruptByParent`；Host 路由 `packages/subagent/subagent/src/index.ts:436-527`、`control.ts:16-28,56-104`。
- 真正的执行决定在 `manager.ts:585-628`，模型定义中的 `send_message` 与浏览器 human prompt 属于不同调用者与归因源，不能直接把浏览器任意 child 消息混进父 Agent inbox。
- `interruptByParent` ≠ 终止全任务树；模式决定是否允许后续恢复。必须保留人类主动停止/恢复的 UI 语义，不凭 status dot 宣称一定 cancel 成功。

## C. 主对话、历史页、时间线和工具/模型详情

- Host `SessionController`：`list/search/create/prompt/updateQueue/cancel/fork/page/follow/projections/control` 见 `packages/api/session-controller/src/index.ts:275-603`。客户端带 Session 地址从 cold `page` 打开，`follow` 接续事件；`history.ts:120-220` 提供观察窗口及新事件。
- `packages/api/session-controller/src/client/contract/events.ts:6-35,97-120` 用 `AssistantLiveChunkEvent` 只负责未持久化流的临时显示，durable commit 到来时以正式事件替代临时片段。禁止把流式 token 增量当持久化完整回复。
- `TrajectoryView.tsx:132-380` 加载事件及当前 partial；`TrajectoryTable.tsx:2080-2257,3170-3194` 提供 Turn/Step、工具参数/结果、LLM request、重试次数与退避延迟、prompt diff、渲染与源数据、滚动/虚拟化；这是一次请求的可观察性不是 Agent “思考链”全文承诺。

## D. 后台 Jobs：观测不改变模型读游标

`packages/api/job-controller/src/index.ts:75-115` 注册 Remote `job.list`, `job.follow`, `job.kill`。`follow` 从绝对 byte offset 读取保留输出，公开 Human 读取不能前移模型自己的 `jobs` cursor/notice；服务器 `jobs-local/src/pump.ts` 内部环形缓存与 spill 区分丢失字节。工具运行和后台 job 不应被强行归入 subagent timeline。

## E. Agent Teams（实验，默认启用 U）

`packages/experimental/client-ui-agent-team/src/client/index.ts:1-16` 注册 Conversation header team action；Host `packages/experimental/agent-team/src/index.ts:129-211` 支持 teammate spawn、peer message、创建/领取/完成/重开有依赖任务、wait change、interrupt。DAG 不是抽象任务清单，`task-board.ts:28-255` 存 revision 和 ownership；`journal.ts:55-70` 把变更写入 lead Session 再 flush。**还需要判断具体 profile 中是否加载该实验包。**

## F. 动态前端其他已定位入口
- `packages/client/ui-schedule/src/client/index.ts:1-20,77-113`：会话 header 的 reminders、右栏任务详情、持久 page/tab binding；`schedule` Host 提供 delivery history。
- `packages/client/ui-settings-subagent/src/client/index.ts:52-92`：子 Agent 插件及模型选择配置在 Settings/Plugins slot，不是静态 HTML 表单。
- `packages/client/ui-trajectory/src/client/TrajectoryTable.tsx`：compact inspection、timeline、token 用量视图。
- `packages/boot/plugin-manager/src/operations.ts`：插件管理作为 Host pnpm profile 变更，UI 可调用服务，但成功安装、reload/HMR 后注册才算功能完成。

## 发行验证缺口

## Continuation: address-aware conversation controls

Newer-source composer and queue flow is mapped in SURFACE-MAP.tsv: QueueDock calls the conversation queue API; the Session client sends session.updateQueue; addressed child messages select subagents.prompt, and stop selects subagents.interruptByParent. A child opened from SubagentHeaderLineage is a Session resource with page/follow/control state, not a synthetic nested message. The matching SessionController test source also exercises a generic-control rejection fence for child Sessions. This closes the static interaction-to-Host chain for the snapshot, but not a live UI click/run or a feature claim about the older Web npm.
固定源码包含 `apps/web` 和 `apps/desktop` 入口，但任务给的 CLI npm 与 Web npm **是不同且更早版本**。Web 旧版 dist、chunk 词项及 package metadata 已机械提取，25 个 JS 有 sourceMappingURL marker 但 `.map` 未随包发布。当前还不能说旧版 Web UI 的子 Agent tree/inline intervention 或实验 Team 都在正式发包中实际可见；继续闭环需获取旧版对应 TS 源或同版本构建产物与 Host runtime，再实际启动验证，见 `extracted/version-diff.md`。
