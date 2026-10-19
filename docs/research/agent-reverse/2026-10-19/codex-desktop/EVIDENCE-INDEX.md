# Evidence Index — 原物、源文件、声明、审计边界

## Evidence method

- **S-collection**：采集人员已解出 MSIX 元数据、本会话实际读其索引文本；不是本会话直接复验包中的文件。
- **S-Server**：本会话从固定 git tag 实际读取的上游代码，版本 rust-v0.163.0。它证明该版本 App Server 接口/代码，**不证明 Windows 26.1013.4894.0 启用此接口**。
- **D**：公开官方说明。**R=0**，尚未运行 Windows Desktop，不能断言生产行为。
- **U**：关键的客户端二进制和动态捕捉未取得；I 必须标推断而非结果。

### 实际已读的 collection 材料

1. dispatch: tasks/research/agent-reverse/2026-10-19/sessions/codex-desktop.md；同级 PROTOCOL.md 与 START-HERE.md。
2. docs/research/agent-clients/2026-10-19/manifest.json，OpenAI Codex Desktop 记录（Windows MSIX 26.1013.4894.0，size 948993815 bytes，SHA-256 e2d892e6c22310e4b1a2928b0d3a29a066e0863d3a333754d6585c77cdafbe7f）。
3. docs/research/agent-clients/2026-10-19/PACKAGE-INDEX.md、COLLECTION-STATUS.md、DOWNLOAD-LOG.md、START-HERE.md、RECOVERY-CODEX-CLAUDE.md、indexes/claude-codex-index.txt。
4. AppxManifest archive index 主程序 app/ChatGPT.exe，辅助 app/resources/codex-command-runner.exe；初始打包 3651 项，Microsoft 商店签名“valid”由采集阶段报告，未自行验证。
5. RELEASE: https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019 。

### 上游固定版本 S-Server 文件（每条为实际读取）

基础仓库 URL：https://github.com/openai/codex/tree/rust-v0.163.0

| 文件（仓库路径相对 codex-rs/） | git blob SHA | 阅读位置 / 对应 |
|---|---|---|
| app-server-protocol/src/protocol/common.rs | b710f18f14e711a748318ee980bcdc4168a7d843 | 520-720 线程/队列；772/858 读取；924-1117 插件/Apps/FS/realtime；1246-1295 MCP/sandbox；1377-1435 command/exec/process；1795-1827 client request；1949-2070 通知 |
| app-server/README.md | 2c4d9a70e79865780120b76030234008b25c12c9 | read state、MCP App UI、shutdown admission、provider requirements、network policy、verification cancel |
| app-server/src/lib.rs | 70e8519ab84031347d837877582f57202102fdf3 | 1-115 服务模块与 imports |
| app-server/src/message_processor.rs | c9858cd9d513c69a917f6505410ee89b16bdd955 | 1-135 request processors 实际注入 |
| app-server/src/transport.rs | 51df5036ec7f7434f210ee4de9887aece6a12591 | 1-126 transport 导出，实验 gate，opt-out |
| app-server/src/daemon_thread_recovery.rs | ade73c616e64c6c6af8f017c699ebe08e827ad59 | 1-54 snapshot/start_recovery |
| app-server/src/thread_state.rs | 6dfe969ab3adfc5d703184ee2ee61a1b6335f282 | 44-125 pending resume，ordered listener commands，generation barrier |
| app-server/src/dynamic_tools.rs | 0069b6d3e4d3830fa7e4925f5a6cea9fef6155c2 | 14-113 response → Op::DynamicToolResponse，校验与 fallback |
| app-server/src/command_exec.rs | c71aff3ddf22da4958d09351b9d70f05a68d9a4b | 1-134 command lifecycle manager |
| app-server/src/plugin_config_reload.rs | 72b301cf60884fc60a2696f1659b8216a63b4c4b | 1-35 reload with config layer |
| app-server/src/lib.rs | 70e8519ab84031347d837877582f57202102fdf3 | 线程状态、code_mode、会话处理模块目录 |

上游单独源码归档：openai-codex-source-36fda4e61c.zip；版本 0.163.0；SHA-256 36fda4e61c251d805c2d68203c3a34b0f6881a88846e12776ca02fb13d6e67c7。公开 tag 直接读取，有部分代码已独立确认；没有读取 entire 9176 文件。

### Atlas main 已查实物

main HEAD aa6196f550098cc46081dc6db2c376cb87ddffa5。已读：
- frontend/src/renderer/components/ConversationMessage.tsx (1-64)
- frontend/src/renderer/components/MessageThread.tsx (1-184)
- frontend/src/renderer/components/timeline.ts (1-185+)
- frontend/src/renderer/components/ConversationActivity.tsx (1-175)
- frontend/src/renderer/components/ReviewFindingsCard.tsx (1-130)
- frontend/src/renderer/components/ForkTree.tsx (1-68)
- frontend/src/renderer/components/Composer.tsx (关键函数)
- frontend/src/renderer/services/runtimeEvents.ts (1-83)
- frontend/src/renderer/store/useAtlasStore.ts (关键状态/行为)
- frontend/src/renderer/shell/panels/TerminalPanel.tsx (1-149)
- frontend/src/renderer/shell/panels/ChangesPanel.tsx (1-232)
- frontend/src/renderer/pages/CodePage.tsx (1-120)
- backend-adapter/src/client.ts (关键 API、524-650)
- backend-adapter/src/types.ts (事件/会话/权限/插件类型)
- core/atlas/api/runtime_ws_router.py (1-157)
- core/atlas/api/runtime.py (1-212)
- core/atlas/api/conversations_router.py (关键入口/路由)
- core/atlas/engine/session_sync.py (关键持久化/分叉函数)
- core/atlas/engine/hermes_runtime.py (关键 MCP/流转/emit)
- core/atlas/engine/steer_dispatch.py (steer)
- core/atlas/plugins/runtime.py (插件加载/更新)
- core/atlas/api/skills_router.py, core/atlas/runtime/hub.py（对应模块与入口）

只扫描列表、未完全逐行精读：frontend/src/main/backendProcess.ts、frontend/src/main/electron.ts、core/atlas/automation/engine.py、core/atlas/lsp 等；**没有对 Atlas 实际启动/执行做新的 R 测试**。缺口列出仍需查的代码，不以“存在文件”推断实现。

### 官方 D 证据

- https://learn.chatgpt.com/docs/windows/windows-app —— Windows app, WSL/PowerShell、Git/worktree、插件、环境、集成能力，更新可能独立于本 MSIX。
- https://learn.chatgpt.com/docs/automations —— 工作流定时执行/结果收件箱，仍需在当前 build 验证。
- https://openai.com/index/introducing-the-codex-app/ —— 产品官方概述，不替代本版运行证据。
- https://persistent.oaistatic.com/codex-app-prod/windows-store-update.json —— 采集报告记录版本来源（本会话未二次读取 JSON）。

## 最重要的未查项 / 缺证原因

- **MSIX 全解包文件树、JS/CSS、ASAR、source maps、EXE imports 和字符串**：私有大二进制经 GitHub 连接器无法流式取得，本环境不能直接下载安装；需要本地最小机械提取。
- **EXE/main↔runner↔App Server 的真实启动协议、版本及消息帧**：仅有归档入口名；无法从 open-source CLI tag 推断 packaged Desktop 内部关系。
- **UI component registry / interactive cards / action dispatch**：没有读取客户端 renderer；任何具体组件列表当前均为 U。
- **进程断线、服务崩溃、模型切换、后台任务、多窗口、关机等 R 级轨迹**：没有 Windows 产品运行环境，也不应上传真实用户对话、凭据、token；待去敏测试。
- **发行包是否包含哪一版公开 App Server**：缺二进制版本证据；CLI 0.163.0 不等于 MSIX 内 runner 0.163.0。

继续取证输入与验收标准：见 EXTRACTION-REQUEST.md；先获得静态宿主证据，再小样本动态验证。**本文件是研究审计日志，不是功能大全。**

## 2026-10-19 本 lane 实物复核增补

原文件中“本地最小机械提取”相关缺口已部分解决。以下 hashes 均对已验证的 MSIX 提取产物/ASAR 内部文件直接计算；REA extraction evidence `ev_edbf1706dc64708c2195821e0cc8fb6b0bc817ab3e4da784a9ae5aca854c87c2` 对 3,651 files / 2,346,419,207 bytes 返回完整性通过。ASAR 文件有独立 native addon integrity mismatch（不可与 MSIX 外层解包结果混为一谈）。

| Package path | Bytes | SHA-256 | 观察 |
|---|---:|---|---|
| `ChatGPT-x64.msix` | 948,993,815 | `e2d892e6c22310e4b1a2928b0d3a29a066e0863d3a333754d6585c77cdafbe7f` | OpenAI.Codex 26.1013.4894.0，REA package inventory `ev_5448a1c8a343570e29c1b3d0ed47cdc15d831d912a84a029941426af9473c182` |
| `app/ChatGPT.exe` | 4,795,184 | `2f61eaeb01dcee7fd18d572fbb338c88b686c0d891427487fdd182afdd64b4f6` | manifest entry |
| `app/resources/app.asar` | 582,072,504 | `bbec1d64e135b718a154b31655bb8ad9a39472bac1b2cabba991a9d97a339dd8` | 21,396 archive paths; full deep inspection not completed |
| `app/resources/codex.exe` | 341,312,816 | `f6dbf48cb70f62649c645f26c87dc9bf84cc36986202dfad8e12fb5b8ca70312` | Authenticode Valid; OpenAI OpCo signer |
| `app/resources/codex` | 296,885,960 | `70ea33b7094a4c20c007d09b83bb50e33debb9bbf99bf066709f9eb85bad524a` | no extension companion binary |
| `app/resources/codex-code-mode-host.exe` | 74,921,776 | `3b6a9179a4da17fa5fc6948219cd61486dc3b534c683838076d8c61bd311c68e` | packaged helper; not launched in this research |
| `app/resources/codex-code-mode-host` | 74,277,776 | `6b4de7a1a69656779c88b6e249ab976cbbc9a43e1edf65e6ec9927feb26f996b` | no extension companion binary |
| `app/resources/codex-command-runner.exe` | 8,217,392 | `ce80b56a2f37f808815fde33cceb97ac858ceecde296425ad3860f0f37fb4877` | packaged helper; launch relation unknown |
| `app/resources/codex-windows-sandbox-service.exe` | 55,824,688 | `d1b0c213e8aaf8ec2c7a29668e7935d996951e7b60b89402739fa0e38f8bef87` | packaged Windows sandbox component |
| `app/resources/codex-windows-sandbox-setup.exe` | 17,700,144 | `c4da812016cbfb92d9a62791f78460c59e9662faadb0a2720d3aa5d0535b80bd` | packaged setup helper |
| `.vite/build/main-C4DYk222.js` | 4,049,746 | `c8a2af504b21314fa6a64ad1b4ec83dbad80033ede902caf9978fd9c74a2c175` | protocol client/main process evidence; byte offsets in IMPLEMENTATION-TRACE |
| `.vite/build/application-network-startup-DB1VeU3v.js` | 292,827 | `c338bbdde151467554d63beea59206848ca38a68abe16b0477d983a172c67578` | runtime path/version/spawn evidence |
| `.vite/build/preload.js` | 6,909 | `a3e622f8d80a83e58fb3cfcc640fa7e14e6461cccdae9ef7d7b0c821dde256b7` | contextBridge/preload IPC evidence |

REA selected-module evidence for 35 `.vite/build` JS modules: `ev_e7f5fee81b8ffba8e7fbbe53100ba3b6dec7e9ddda92dfb2f288e62adca8937b` (10,746,938 bytes parsed, 0 parse failures; semantic analysis partial/truncated). The input modules and independent hashes live under the table above for primary entry points. Webview sampling extracted 41 target chunks (947,407 bytes), not all 20,362 webview assets; examples and hashes remain in the preceding evidence table/section only where called out. This was a bounded survey, not exhaustive asset coverage.

Package protocol observation: app-server version literal `0.141.0` in `application-network-startup-DB1VeU3v.js` byte offset 680. It is the client's expected/current build literal, not evidence of a successful handshake with a remote service. Main bundle JSON-RPC and method anchors are byte offsets, not original source lines: see IMPLEMENTATION-TRACE §8. Static package behavior is S only. No Codex app start, user action, remote login or R observation occurred (R=0).

## 2026-10-19 completion-lane checkpoint: installed build identity and corpus inventory

- The installed `OpenAI.Codex_26.1013.4894.0_x64__2p2nqsd0c76g0` package is present under `D:\WindowsApps` and its `app/resources/app.asar` was opened by REA. Observed SHA-256 `bbec1d64e135b718a154b31655bb8ad9a39472bac1b2cabba991a9d97a339dd8`, matching the previously recorded ASAR digest above. This verifies the installed ASAR identity, not a second download or full MSIX signature.
- The running process inventory contains ChatGPT.exe, codex.exe, codex-code-mode-host, codex-computer-use-swift and codex-windows-sandbox-service instances. This is a point-in-time process observation only: parent/child ownership, command-line routing, IPC payloads and action correlation were not established. No CDP listening endpoint was found on the ChatGPT process.
- A bounded local ASAR-header inventory read enumerated 21,073 file entries / 593,720,176 declared bytes; 15,110 `.js` files / 414,632,995 bytes were scanned for literal anchors. Findings include thread/start and thread/resume literals in `.vite/build/main-C4DYk222.js` and `webview/assets/app-initial-5851df3f6cb1.js`; the latter contains a visible mutation classifier for `thread/start`, `thread/startAeon`, `thread/fork`, `thread/inject_items`, `thread/queue/add`, `turn/addUserMessage`, `turn/start`, and `turn/steer`. `preload.js` defines `sendMessageFromView` via `ipcRenderer.invoke` and exposes `electronBridge` through `contextBridge`. These are static string/code observations, not a proven click-to-RPC call chain.
- The ASAR inventory's 21,073 leaf entries plus directory entries must be distinguished from the prior REA path count of 21,396 paths; this local parser only counted leaves. The exhaustive JS lexical pass has no per-file semantic analysis and does not exhaustively interpret JSON, CSS, HTML or lazy UI registration.
- A whole-ASAR REA semantic-analysis request exceeded the operation window and was cancelled. A provider-owned isolated Electron scenario attempt returned `Transport closed` before evidence was returned. Neither attempt is a pass. The already-running user's app was not interacted with. A release-asset `gh release download` attempt was interrupted at 35,675,540 bytes while downloading; this checkout did not finish acquiring or re-hashing the 948,993,815-byte MSIX. Existing prior MSIX hash/decompression evidence remains historical lane evidence, not a new download in this continuation.
