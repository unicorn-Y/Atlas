# 证据索引与可复核定位

## 版本控制与级别

研究派工源：research/agent-reverse-dispatch-20261019/tasks/research/agent-reverse/2026-10-19/{PROTOCOL.md,sessions/zcode.md}。Atlas main HEAD：aa6196f550098cc46081dc6db2c376cb87ddffa5；ZCode 上游固定 commit：aac4755666d09fdcd70272fcf063c077a639015f（root package.json=3.15.1）。

- S：实际读取 3.15.1 源码/Atlas main 正文；且在本轮取得并解析已 SHA-verified 的 3.15.3 CJS 包字节及部分 desktop bundles，具有精确定位。ZCODE-001..025 为 3.15.1；ZCODE-028..037 是 3.15.3 package/desktop 或当前 main source observation。
- D：zcode.z.ai/en/changelog 发布说明。ZCODE-026 为 D。
- U：ZCODE-027 原始旧结论为 U（完成真实包分析前的状态）；本轮已有 CJS 和部分 desktop bundle 的 S 证据，但完整可信 app.asar graph、desktop runtime UI/IPC 全链与动态验收依然 U/partial。
- R：没有 Windows 进程、操作、动态日志、抓包；**0 条 R**。函数源码存在不等于动态行为已通过。

固定源码快速访问前缀：
- https://github.com/zai-org/ZCode/tree/aac4755666d09fdcd70272fcf063c077a639015f
- https://github.com/unicorn-Y/Atlas/tree/aa6196f550098cc46081dc6db2c376cb87ddffa5

## 原始材料身份（本轮从 Release 下载并重新计算）

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

本轮复核：通过 gh release download 拉取上述三个资产后，Get-Item.Length 与 SHA256 均逐个匹配 manifest。独立 PE 资源静态扫描完整遍历 61 项/28 个叶资源（REA evidence ev_0d6e943812a8cf8f6c73c8824ac8f0668d808de57b7f4cc85c852757fd82f759）；PE 解码为 x86 NSIS/安装器，未运行 EXE。既有 staging 已含内层 NSIS app-64.7z 解出目录及同 hash CJS；安装树 package manifest 写明 app @zcode/desktop@3.15.3、out/main/index.js、type=module；bundle meta 写明 electron-node、win32-x64、zcode.cjs、source apps/zcode-cli/packages/cli/dist/zcode.cjs。完整 package/PE/ASAR 元数据仍增补中。

## 本轮 3.15.3 包内实证

- CJS 输入：D:\agent-client-staging\opencode-zcode\requested-assets\zcode-agent-runtime-embedded-v3.15.3-31965ce1d5.cjs，与包内 resources/glm/zcode.cjs 同 SHA。Acorn 8.16.0 成功 parse（15,124,982 UTF-16 code units / 15,127,039 UTF-8 bytes，3,458,803 AST nodes，58,079 function nodes，43,602 variable declarations，231,843 call expressions）；未执行此文件。CJS-MODULE-INDEX.tsv 记录统计与 wrapper。
- REA evidence ev_b8b2fd3fa4a83e172dd4680e7c32e7b59a25a4c293615f1af2633d64fa08bfcb 对 resources/glm 目录：root SHA 3d777334938a6657c9e1e87601588faa80469e3e9f61dda2fb6ecef926401352；360 relevant files、294 parsed JS、186 modules、1,292,029 visited AST nodes、0 parse failures、semantic graph partial/truncated；CJS inventory node exact artifact hash 31965ce1...506a54，但 REA 的 parse_status=null，专门 CJS AST 数来自 Acorn 而非 REA。
- PE evidence ev_711f8e6d9a5a21e984b06cd0da188d083ad3c6819aa6c451cfbda0bfb7f7a854：7 segments、269 procedures、239 strings；仅 static overview，不解释 NSIS/运行逻辑。
- ASAR integrity boundary：对完整 application tree 的严格 REA 初次失败，原文报出 resources/app.asar/node_modules/node-pty/prebuilds/win32-x64/conpty_console_list.node 声明 integrity 与 companion file bytes 不符。record-and-continue 重试超出 MCP 300s 等待时间；不能称为完整、可信 ASAR 图，也不能把该 native companion 当 verified。安装包从未执行。
- app.asar 同版入口清单：resources/app.asar.extracted/package.json（来自留存 ASAR 索引文件）明示 main=out/main/index.js 和 Electron host/service/provider packages；resources/glm/.node-bundle-meta.json 明示 runtime metadata。本轮进一步从留存 `out` bundles 静态检查到 typed service facade、host MessagePort RPC client、plugin sandbox preload bridge 以及 navigation schemas，见 `extracted-3153/DESKTOP-IPC-ANCHORS.md`。这些 bundle 本身已 rehash，但未逐个同 ASAR index integrity 核验；不能宣称完整可信 IPC/renderer 图。

### 精确 UTF-8 byte-offset 锚点

以下偏移相对于 SHA 31965ce1...506a54 原始字节；CJS 为压缩/混淆 bundle，source-map 数量为 0，偏移和短符号可复核，不能自行映射为 3.15.1 源码行号。

| 证据 | byte offset / range | 实际锚点 | 结论边界 |
|---|---:|---|---|
| ZCODE-029 | 2,489,228 | __webpack_require__ wrapper；后续数字 ID module array | 识别 bundler wrapper，不代表 module names 可恢复 |
| ZCODE-033 | 1,540,263; 1,540,320; 1,523,765; region 1,515,023–1,543,238; replay region 12,513,514–12,524,192 | 0019_dwf_journal; dwf_run; input_hash; InputHashMismatch at 12,524,144; migration SQL and replay hash check | packaged journal/replay anchors; 未证明该路径启动及 DB 实际创建 |
| ZCODE-034 | V9s 3,898,082–3,898,491; qXr 4,007,148–4,007,440; HB 4,097,229–4,097,847; sHs 4,099,067–4,099,316 | SDK helper + model request retry parser and structured retry delay/source diagnostics | request retry telemetry packaged; release-note concurrency-fix linkage remains U |
| ZCODE-031 | region 5,042,044–5,044,543 | class InMemoryRuntimeTaskRegistry; activeBranchGeneration, backgroundWaiters, tasks, terminalWaiters; register/update resolves waiters | in-process task-state mechanism seen in packaged bytes |
| ZCODE-030 | region 13,192,839–13,193,404 | gBe function persistPendingToolPart; awaits persistPart for pending tool call | persistence function present in bundle |
| ZCODE-030 | region 13,205,979–13,210,657 | qwt; tool-call closure -> scheduleTools -> state transition -> tool_queued -> executeTools | static local order is visible; runtime timing/result not observed |
| ZCODE-032 | byte 12,715,173 | runner onSessionReady emits SubagentSpawned with child/parent identifiers | event emission present |
| ZCODE-032 | byte 12,716,232 | run observes backgrounded, calls detachParent(), retains async child completion callbacks | parent detachment path present; actual background survival unobserved |
| ZCODE-032 | byte 12,719,281 | task port backgroundTask requests registry background state | interface wiring visible in same local region |
| ZCODE-031 | byte 5,042,679 | requestBackground(taskId) marks task isBackgrounded and resolves waiters | state transition function present |

Exact snippets and parser/hash metadata are in extracted-3153/CJS-SLICES.md and CJS-MODULE-INDEX.tsv. Offsets were calculated against UTF-8 Buffer bytes; Acorn start/end values are UTF-16 code units and were converted before citation. The source contains non-ASCII content: whole-file UTF-16-unit count differs from UTF-8 byte size by 2,057.

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

## G0–G7 continuation evidence (2026-10-19)

* **S — static identity/inventory:** `COVERAGE.md` records installer, ASAR and CJS SHA/size; ASAR entry counts; Acorn parse results and parser failures; two aliases; and two unpacked node-pty companion mismatches. ASAR SHA-256: `3fb4104ddcd79e9808eede75192299a22057bd9c336e15b9c2bb1825b4120283`.
* **S — grouped REA:** `out/main` `ev_b48ea35577ef69b96dec6ae5d732e98e72abd9c097e22cea6e9b9c2855129e7c`; `out/host` `ev_7f0b59b9fbb70743ecaa18d8dc8c6de7e408180b77dadc7a17a0fd7bea35799f`; `out/scheduler` `ev_d89be61cdcd988ea604688441526ccf4d64a5d0b5df0580406ed7395dafcc221`; `out/plugin-sandbox` `ev_420285686f1ecb83efb2e40f3fd7e143cee3d1ca323d51aaa2c8c6d71f767c10`. Each selected directory's JS parsed; semantic relation graphs are partial/truncated.
* **S — cross-boundary anchors:** `END-TO-END-TRACES.md`, `SURFACE-MAP.tsv`, and `extracted-3153/DESKTOP-IPC-ANCHORS.md` give named bundles, byte offsets and hashes for host routes, main registry, renderer event consumer and sandbox SDK.
* **R — startup/page only:** `ev_49e6e6ea5689b868e98358ce0348ca05ec529fb74d25a2ad8391cf86c235c0d2` lists a local `ZCode` page with the 3.15.3/Electron 41.0.3 user agent; `ev_dc5735b0dfdda2f1527d9551626b2ed373b9d12085b6a5b4ce9474316277f966` passively inspected it. Process args, profile mismatch, stop action, and lack of task interaction are in `END-TO-END-TRACES.md`.
* **U:** actual app mount/consent/message bridge, app-tool producer/model result, per-entry integrity across all files, exhaustive renderer actions, safe isolated full task run, and cold execution recovery remain unknown/open.
