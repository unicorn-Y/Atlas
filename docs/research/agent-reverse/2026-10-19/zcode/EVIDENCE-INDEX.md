# 证据索引与可复核定位

## 版本控制与级别

研究派工源：research/agent-reverse-dispatch-20261019/tasks/research/agent-reverse/2026-10-19/{PROTOCOL.md,sessions/zcode.md}。Atlas main HEAD：aa6196f550098cc46081dc6db2c376cb87ddffa5；ZCode 上游固定 commit：aac4755666d09fdcd70272fcf063c077a639015f（root package.json=3.15.1）。

- S：**实际读取** ZCode 3.15.1 真实源码正文与 Atlas main 正文，具有定位。DISCOVERY-LEDGER 的 ZCODE-001..025 为 S。
- D：zcode.z.ai/en/changelog 发布说明。ZCODE-026 为 D。
- U：3.15.3 CJS / app.asar 内容无法直接在本会话取出。ZCODE-027 为 U。
- R：没有 Windows 进程、操作、动态日志、抓包；**0 条 R**。函数源码存在不等于动态行为已通过。

固定源码快速访问前缀：
- https://github.com/zai-org/ZCode/tree/aac4755666d09fdcd70272fcf063c077a639015f
- https://github.com/unicorn-Y/Atlas/tree/aa6196f550098cc46081dc6db2c376cb87ddffa5

## 原始材料身份（来自已提交的机械采集索引，本会话未亲自重新计算哈希）

| 项目 | 版本/路径 | 大小 | SHA256 |
|---|---|---:|---|
| Windows Installer | 3.15.3 / ZCode-3.15.3-win-x64.exe | 181367144 | bc8100ba4377256fbe1531d549b4775f18e3ba21768b6294ca50751cd461faca |
| 内嵌 Agent Runtime | 3.15.3 安装包 / resources/glm/zcode.cjs | 15127039 | 31965ce1d5d4a808ef156784f67996de42ccab335591d2386a61ea8f6f506a54 |
| 源码快照 | ZCode 3.15.1 / aac4755 ZIP | 100436252 | 45034cfbc064716a34a06a117af6aed359012927834a3e40c24cf89682ef8ab1 |

- [安装器 Release](https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/zcode-desktop-v3.15.3-bc8100ba43.exe)
- [真实内嵌 CJS Release](https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/zcode-agent-runtime-embedded-v3.15.3-31965ce1d5.cjs)
- [固定源码快照 Release](https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/zcode-source-main-aac4755-45034cfbc0.zip)
- [机械索引](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-dispatch-20261019/docs/research/agent-clients/2026-10-19/indexes/opencode-zcode-index.md)
- [manifest](https://github.com/unicorn-Y/Atlas/blob/research/agent-reverse-dispatch-20261019/docs/research/agent-clients/2026-10-19/manifest.json)

采集记录：官方 Windows 内层 NSIS app-64.7z -> application/resources/app.asar，内含 resources/glm/zcode.cjs；整个 application tree 有 882 package.json / 693 命名包，source map 0。该数字仅为采集索引的证据，**并非本次解包统计**。内部 CLI 版本尚不确定。排除同名第三方 npm zcode-cli@0.0.1，独立官方 CLI Release 未找到。

## 真实源码证据目录（全部为 3.15.1）

以下 URI 前缀统一： https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/

| Ledger | 路径与已读取的关键位置 | 机制 |
|---|---|---|
| 001 | packages/desktop/src/main/desktopHostProcess.ts#L157-L300 | Electron Host fork 与回调 |
| 002 | apps/zcode-cli/packages/core/src/runtime/methods/turn-loop.ts#L44-L230 | 模型回合及命令/压缩/MCP |
| 003 | apps/zcode-cli/packages/core/src/runtime/methods/turn-tools.ts#L30-L168 | 事件、排程、工具执行 |
| 004 | apps/zcode-cli/packages/core/src/subagent/runner.ts#L110-L405 | 子 Agent 启停、后台化与 watchdog |
| 005 | apps/zcode-cli/packages/core/src/runtime/methods/subagent.ts#L65-L230 | child model/MCP/skills/context |
| 006 | apps/zcode-cli/packages/core/src/runtime/methods/subagent-messages.ts#L25-L107 | 分支代际与父队列交付 |
| 007 | apps/zcode-cli/packages/core/src/runtime-task/registry.ts#L105-L245 | InMemory registry + waiter |
| 008 | apps/zcode-cli/packages/core/src/runtime/command-queue.ts#L114-L240 | 优先级命令和 batch |
| 009 | apps/zcode-cli/packages/dynamic-workflow-runtime/src/harness.ts#L225-L420 | 子进程执行 / NDJSON |
| 010-011 | apps/zcode-cli/packages/dynamic-workflow/src/engine/scheduler.ts#L125-L289 | ask hash、journal、import cache |
| 012 | apps/zcode-cli/packages/dynamic-workflow/src/engine/concurrency.ts#L120-L275 | 429/epoch/streak cap |
| 013 | apps/zcode-cli/packages/dynamic-workflow-runtime/src/harness.ts#L350-L420 | stopped/errored/abort |
| 014 | apps/zcode-cli/packages/dynamic-workflow/src/engine/engine-resume.ts#L17-L44 | replay settle ordering |
| 015 | apps/zcode-cli/packages/adapters/src/storage/session-store/repositories/dwf-journal.ts#L1-L84 | SQLite dwf_* adapter |
| 016 | apps/zcode-cli/packages/adapters/src/storage/session-store/repositories/usage.ts#L17-L248 | 30d usage/request/turn |
| 017 | apps/zcode-cli/packages/core/src/runtime/methods/compact-active.ts#L73-L122 | 压缩与 telemetry |
| 018 | apps/zcode-cli/packages/core/src/runtime/methods/session-fork.ts#L219-L235 | ForkIdentityMap |
| 019 | apps/zcode-cli/packages/adapters/src/mcp/index.ts#L165-L168 | tools list changed 等通知 |
| 020 | apps/zcode-cli/packages/adapters/src/plugins/index.ts#L39-L107; adapters/src/skills/index.ts#L29-L60 | 扩展/插件/跨 manifest |
| 021 | packages/ui/src/plugin-ui/adapters/messagePortTransport.ts#L5-L40; packages/ui/src/plugin-ui/app/pluginUiHostBridge.ts#L38-L122 | MCP Apps AppBridge |
| 022 | packages/desktop/src/main/pluginSandbox/host.ts#L49-L205 | WebView/partition/permission |
| 023 | packages/ui/src/app-shell/WorkflowRunSidePane.tsx#L85-L220; packages/ui/src/app-shell/workflow-artifacts/presets/ArtifactChartView.tsx#L320-L372 | UI 权威投影和 charts |
| 024 | packages/desktop/src/main/desktopCronScheduler.ts#L60-L210 | 分进程 cron/offpeak dispatch |
| 025 | packages/services/src/session/zcodeTaskService.ts#L199-L650; packages/services/src/bots/feishuChannelRuntime.ts#L39-L129 | Service RPC/群消息 |

补充实际阅读：apps/zcode-cli/packages/adapters/src/model/runner-stream.ts、adapters/src/storage/session-store/sqlite-session-store.ts、packages/services/src/gen-ui/adapters/stateStorage.ts、packages/desktop/src/main/pluginSandbox/permissionGate.ts。通过上游 git tree 发现大量其他潜在能力，但仅路径不计 S。

## Atlas main 实物对照文件

所有 URI 前缀： https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/

- core/atlas/agents/backends/zcode.py#L22-L105（适配器每 turn 新 process，resume 抛错）
- core/atlas/agent/run_phases.py#L146-L209（真实 Agent loop）
- core/atlas/agent/tool_node.py#L58-L166（真 tool execution）
- core/atlas/agent/subagent_worktree.py#L237-L342（真 git worktree）
- core/atlas/engine/hermes_runtime.py#L70-L100；core/atlas/engine/session_sync.py#L1-L12（模型及 SessionDB）
- core/atlas/runtime/hub.py#L119-L161；core/atlas/scheduler/__init__.py#L310（后台与 Cron）
- core/atlas/persistent_agents/store.py#L21-L144（profile）
- core/atlas/plugins/runtime.py#L1-L135（插件）
- core/atlas/tools/mcp_client.py#L1-L183（MCP）
- core/atlas/api/group_router.py#L1-L72；core/atlas/api/conversations_router.py#L65（群聊/会话）
- frontend/src/renderer/store/useAtlasStore.ts#L17-L21；frontend/src/renderer/components/MessageThread.tsx#L47-L95；frontend/src/renderer/pages/agents/AgentsPage.tsx#L21-L57

## 未解决的实物和覆盖问题

1. **3.15.3 CJS 未直接读取**：连接器不接收该 Release 大型二进制的完整内容。无法提供该版本函数名/AST/偏移/符号映射，也无法断言 3.15.1 到 3.15.3 哪些模块重构。
2. **3.15.3 前端/主进程同版源码未知**：未拿到 app.asar 解出主/renderer bundle 索引与 IPC 消息定义。
3. **没有 Windows 动态测试**：并发真实额度、网络错误、会话恢复、启动/托盘、模型计费、权限弹窗不可据静态代码证真。
4. **远端商用服务与账户协议**：客户端不能推出服务端实现或绕过登录；未做内网/凭据/账户数据采集。
5. **部分外围代码仍未展开到调用者和被调用者**：内置浏览器、UI 全菜单、隐性实验开关、语音/远程平台、native helper，需要机械枚举补全。

发布说明（仅 D）：https://zcode.z.ai/en/changelog ; 安装说明：https://zcode.z.ai/en/docs/install 。ZCode root LICENSE 是 Apache-2.0，具体复用还需核对 NOTICE、具体子包 third-party headers；许可证不是 3.15.3 闭源二进制可自由复制的证明。
