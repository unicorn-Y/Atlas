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
