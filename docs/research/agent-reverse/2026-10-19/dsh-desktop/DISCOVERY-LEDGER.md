# DISCOVERY LEDGER（源码实证能力编号）

S：固定 commit 源码；D：固定文档；I：推断；U：本轮未确认。**S 不是 R：没有现场运行测试**。路径 A 默认相对于 dsh-desktop-next，B 默认相对于自身仓库，O 官方相对于 deepseek-harness。

## A — anywhere-labs，Next 2.0.19-next

| ID | 归属及能力 | 代码路径/关键符号 | 证据 |
|---|---|---|---|
| DSH_DESKTOP-001 | 社区 Electron/Node 子 Host 进程，而非新 Agent loop | A package.json main；src/host-process.ts:228-319 spawn/IPC | S |
| DSH_DESKTOP-002 | 调用官方 runProfile 装配 DSH Web/Cordis | A src/host/index.ts:28-80；src/profiles.ts:290-357 | S |
| DSH_DESKTOP-003 | 以 loopback 随机端口替换官方 WebServer | A host.cordis.patch.yml；src/webserver.ts | S |
| DSH_DESKTOP-004 | 结构化 child IPC ready、fatal、permission、platform-login、notification、injections、update-tasks | A src/host-process.ts:251-319；src/host/index.ts:96-125 | S |
| DSH_DESKTOP-005 | 后端启动串行化/取消、清理失败 AggregateError、保留根因 | A src/backend-controller.ts:33-172 | S |
| DSH_DESKTOP-006 | Profile 创建/切换、Cordis patch 注入和可选 bundles | A src/profiles.ts:18-49,76-215,290-357 | S |
| DSH_DESKTOP-007 | browser-access 拒绝 HTTP + WS upgrade，并撤销既有 browser socket | A src/webserver.ts:setBrowserAccess/registerUpgrade | S |
| DSH_DESKTOP-008 | 官方客户端 Slots 注入桌面设置、权限、市场按钮、原生文件夹、onboarding | A src/client/index.ts:31-100 | S |
| DSH_DESKTOP-009 | 安全模式独立临时 home、Profile checkpoint/recover | A src/desktop-runtime.ts:85-145；src/recovery.ts:10-180 | S，限配置快照 |
| DSH_DESKTOP-010 | 托盘动态 Profile/终端/诊断/恢复/更新/浏览器等命令 | A src/desktop-menu.ts:6-35；src/desktop-contract.ts:94-115 | S |
| DSH_DESKTOP-011 | 本地 community market 有独立 Host route 与 React 设置 UI | A dsh-community-market/src/host/routes.ts；src/client/MarketSettingsTab.tsx | S 文件存在，默认启用 U |
| DSH_DESKTOP-012 | AA bridge remote control、Market、官方 Market 均为可选 bundle | A src/profiles.ts:20-27,45-49；A Next package.json vendored AA | S 装配，外部服务运行 U |
| DSH_DESKTOP-013 | runtime payload inventory/checksum、更新安装与 LAN/HTTPS 组件 | A src/runtime-tree.ts；src/update-installer.ts；src/lan-https-* | S 结构，R 未测 |
| DSH_DESKTOP-014 | jobCompleted/jobFailed 字段保留作兼容但默认永远 false | A src/desktop-contract.ts:30-42 | S；不是正常任务通知 |
| DSH_DESKTOP-015 | 电脑使用/Office/Skill badge 原生资源路径接入 | A src/host/index.ts:36-44；src/host/cua-driver.ts；cordis.patch.yml | S；native CUA driver 默认 disabled |

## B — dongdong-agent，0.1.15

| ID | 归属及能力 | 代码路径/关键符号 | 证据 |
|---|---|---|---|
| DSH_DESKTOP-016 | Tauri + React 管理壳，官方 WebUI 外嵌 | B package.json；src/App.tsx:17-20；src-tauri/src/lib.rs:295-318 | S |
| DSH_DESKTOP-017 | 引擎就绪后 navigate 主 WebView，取代原 React JS，非独立 Agent UI | B src/App.tsx:~270-320；src-tauri/src/lib.rs:158-209 | S |
| DSH_DESKTOP-018 | 探测常见端口并复用；按 engine-instance.json + PID 判 owned | B src/lib/dshEngine.ts:51-53,479-635 | S；401 误判风险 |
| DSH_DESKTOP-019 | Cookie + Rust POST /api/session/list 业务 readiness，而非只看 TCP/HTTP | B src/lib/dshEngine.ts:~650-770；Rust lib.rs:229-292 | S，30秒超时放行 |
| DSH_DESKTOP-020 | 从 ~/.dsh/.credentials.yaml 读取官方签名 secret，构造 HMAC cookie | B src/lib/engineAuth.ts:24-120；Rust lib.rs:170-209 | S |
| DSH_DESKTOP-021 | 多候选 node/npx/dsh spawn、stderr 尾、进程退出、残留写锁清理 | B src/lib/dshEngine.ts:154-361,~800-1000 | S |
| DSH_DESKTOP-022 | 系统托盘管理页重返、重启、测试版升级、留后端退出/全退出 | B src-tauri/src/lib.rs:~320-465 | S |
| DSH_DESKTOP-023 | 版本并存/更新/rollback/已验证列表 | B src/lib/updater.ts；src/components/TitleBar.tsx；StatusBar.tsx | S |
| DSH_DESKTOP-024 | --patch 目录选择和官方 web-search 计费覆盖 | B src/lib/enginePatch.ts:33-70,108-186 | S |
| DSH_DESKTOP-025 | key manager/安装器/沉浸/快捷键 | B src/components/KeyManagerDialog.tsx；EngineLauncher.tsx；src/App.tsx | S 壳端；导航后不可见 |
| DSH_DESKTOP-026 | restartEngine/quit_all 按端口 PID 可强杀外部复用实例 | B src/lib/dshEngine.ts:restartEngine；Rust lib.rs:37-70,128-145 | S，关键风险 |
| DSH_DESKTOP-027 | codebuddy-mcp、dsh-balance、dsh-tauri-dir-picker 为附属 tools | B tools/；src/lib/enginePatch.ts:isTauriDirPickerMounted | S 存在，实际挂载 U |
| DSH_DESKTOP-028 | 官方宣称跨平台，但多处 Windows hardcoded 路径、cmd/taskkill | B src/lib/dshEngine.ts、src/lib/engineAuth.ts、Rust lib.rs | I/U，不代表全平台可用 |

## O — 官方 DSH 内置 UI，**不可归入 A/B 自研**

| ID | 能力 | 固定源码 | 证据 |
|---|---|---|---|
| DSH_DESKTOP-029 | 子代理递归展开、运行指示、Token 使用和时长投影 | O packages/client/ui-subagent/src/client/SubagentHeaderLineage.tsx:190-350 | S |
| DSH_DESKTOP-030 | 子代理主会话/右侧栏导航，精确 parent/child/mode address、SessionReference | O ui-subagent/src/client/index.ts:43-99；sidebar-chat/index.tsx:18-201 | S |
| DSH_DESKTOP-031 | one-shot 只读，continuable 根据 parentAvailable 切 composer、可独立 Stop | O ui-subagent/src/client/index.ts:33-52；README.md | S+D；Host RPC 实测 U |
| DSH_DESKTOP-032 | 工具/请求/消息轨迹映射、检索、时间轴与历史分页 | O packages/client/ui-trajectory/src/client/TrajectoryView.tsx；trajectory-event-projection.ts | S |
| DSH_DESKTOP-033 | 官方 packages/subagent,experimental/agent-team,mcp,skill,jobs,session 等存在 | O 对应 package 树 | S 文件存在，不等于默认装载 |

## A 内嵌官方 runtime：已验证资产新增发现

| ID | 归属及能力 | 实物包路径 / 符号 | 证据 |
|---|---|---|---|
| DSH_DESKTOP-034 | Next 2.0.19-next 实际随包携带官方 `@deepseek-ai/*@0.2.1-rc.2` runtime，而非只引用空 deepseek-harness gitlink | ZIP `vendor/dsh-runtime/0.2.1-rc.2/manifest.json` 343/343 tarball SHA 匹配；`A-runtime-symbol-index.md` | S（包内元数据+tarball digest） |
| DSH_DESKTOP-035 | Agent Inbox 为两路 event-sourced 队列：`next-turn` 和 `next-step`；claim 消费并记录生命周期事件 | `@deepseek-ai/dsh-agent-loop@0.2.1-rc.2` tar `lib/index.js:70-204,806-813`；事件 `agent/inbox/spliced` | S（真实 A 源包内嵌 tarball） |
| DSH_DESKTOP-036 | UI projection/RPC/controller 具备队列回显、request-ID 去重、edit/remove/steer 变更；冷 Agent 会 resolve/restore 后再改 durable inbox | `@deepseek-ai/dsh-client-ui-chat` `lib/client.js:2757-2847`；`dsh-api-session-controller` `lib/index.js:925-950,1004-1054,2689`，wire `typert.remote-client.js:1912-1938` | S；具体按钮到 RPC 的映射 U |
| DSH_DESKTOP-037 | 随 A 包的 Agents Anywhere 存在多版并行 tarballs；`provenance.json` 指向的 `.c39b82d4fffb1...tgz` SHA 与 provenance 声明 `f1b117...` 一致，但同目录还有其他同版不同 commit 构件，不能只按 package semver 认定运行时选中了哪份 | A `vendor/agents-anywhere/provenance.json` + `*.tgz`；详见 `A-vendor-package-index.tsv` | S 文件/哈希；Profiles 默认关 AA bridge；运行加载 U |

## 未证 / 不可冒充完整

A 的 experimental Agent team、AA 远控和默认插件实际激活、桌面关闭/重启后的当前 Agent turn 恢复；B 自研 Agent UI、每子 Agent精确计费、所有三平台体验；官方 external 子代理 leaf 可点击进入聊天；UI inbox action 的具体控件到 RPC 映射、Windows 真实运行、WS trace：本轮统统 **U**。A/B 指定归档身份校验已完成，不再列为 U。
