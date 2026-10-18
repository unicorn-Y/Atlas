# 底层调用链、状态/错误传播及官方能力归属

三套源基线：A 6a63b973；B 0aea85f；官方 O 687f282e；所有结论为 S（源代码）。

## A：Electron/Node Host 与 DSH Profile

**入口**：dsh-desktop-next/package.json 指向 lib/main.js，src/main.ts 为 Electron UI/托盘/主进程 IPC；src/desktop-runtime.ts:102 的 NextDesktopRuntime.start() 调用 DesktopBackendController.start()（src/backend-controller.ts:33-172）；先准备 Profile，串行 Host 创建，失败清理，不把未完全退出的旧 Host 和新 Host 无序重叠；src/host-process.ts:228-319 用 Node spawn 创建 child，stdio=['ignore','pipe','pipe','ipc']，登记 child error/close 与 IPC。

**真正运行 DSH 的线**：src/host/index.ts:28-80 从环境读取 home、projectDir、runtimeDir，加载 src/profiles.ts:290 的 loadNextProfile，合并 host.cordis.patch.yml、desktop-next.cordis.patch.json、desktop-next.runtime.patch.json，调用官方 @deepseek-ai/dsh/profile-boot 的 runProfile。官方引擎/Agent loop 在此启动，社区未重新发明执行循环。src/profiles.ts:17-49 仅在勾选时加社区 Market、dshmarket、官方 Market、Agents Anywhere bridge bundles；remoteControl=false/market=false 起始。cordis.patch.yml 插入 desktop-next-capabilities、computer-use，experimental native CUA driver disabled；host.cordis.patch.yml 禁原 Webserver、换本地随机端口子类。

**两层消息总线**：src/host-process.ts:251-319 接收 child ready(url,injections)、fatal、permission、notification、platform-login、desktop-action、injections、logging-config、browser-access、update-tasks；src/host/index.ts:96-125 处理主到 Host 的 shutdown、injections、browser-access 请求；src/ipc.ts:1-17 另外定义 Electron main↔renderer 的 state/command/browserLinks/permission/settings/shortcuts 等通道。**这些 IPC 不等于官方 DSH Chat WebSocket 事件流**。WebServer src/webserver.ts 继承 @deepseek-ai/dsh-host-webserver，HTTP 路由根据 native/browser policy 决定 403，market API 额外借官方 connection.requestRejection 授权；WS upgrade 同样判断且禁用时关闭既有 browser sockets。

**失败与关停**：BackendController 有 starting/ready/error 与 failure 原对象；start 并发共享 pending，stop 会取消 pending 并 await cleanup，失败可为 AggregateError。HostProcess 捕获 stderr 最近 64KiB，校验 IPC 事件结构，遇 close/invalid event 进入失败并拒绝所有尚未答复的请求。stop() 先 child.shutdown，等待 shutdown-complete；超时升级 SIGTERM 和 SIGKILL；更新使用 requireGraceful，收不到干净 ACK 或 exit 非0则拒绝切安装。src/desktop-runtime.ts:85-145 的 Safe Mode 使用独立临时 home/最小 Profile；src/recovery.ts 的 checkpoint 主要快照 package.json、cordis.patch.yml、desktop-next.features.json。**这只能证明桌面配置恢复，不证明 Agent turn 自动续跑**。

**UI**：src/client/index.ts:31-100 将 Desktop Settings / Settings Actions / Settings Requests / Safe Mode 注入官方 Cordis slots；插件 UI、native picker/onboarding 也是嵌入官方 client。A 的本机 terminal、LAN HTTPS、market Host routes、payload checksum/update-install 分别位于 src/desktop-terminal.ts、src/lan-https-*、dsh-community-market/src/host/routes.ts、src/runtime-tree.ts。早期 dsh-plugin-desktop 与 Next 属另一个应用变种，本研究没有混合版本路径。

## B：Tauri/Rust/React 管理壳到官方 WebUI

**冷启动**：Rust src-tauri/src/lib.rs:295-318 启动 plugin_shell/fs/dialog/http/global_shortcut/single_instance，注册 set_engine_port、open_engine_in_main、probe_engine_ready 等；React src/App.tsx 管理状态，Zustand src/stores/engineStore.ts 存 health/owned/launchRequested。src/lib/dshEngine.ts:479 起 probePort 扫 [3080,8080,8081,3000,5173,17800,18080]，200 的 body 包含 __DSH_BOOT__ 或 401 即判有服务。警惕 401 没有核实身份，可能复用并非 DSH 的端口。复用时通过 engine-instance.json/PID 识别 managed engine。若不存在，fallback 候选本机 Node+已下载 kernel bin、npx package、PATH dsh/dsh.cmd，捕获 stdout、stderr 尾和 process close/error，并清理残留 ~/.dsh/profiles 写锁。配置注入前写 directory-picker 与官方 web-search 抑制计费的 --patch，外部引擎需按实际版本确认 patch 生效。

**业务就绪**：仅 TCP/HTTP 401 不保证会话存储可读。src/lib/engineAuth.ts 读 ~/.dsh/.credentials.yaml 中 client-connection/browser-session 的 secret，以 HMAC 构造 auth cookie。src/lib/dshEngine.ts 的 probeEngineReady 调 Rust probe_engine_ready，src-tauri/src/lib.rs:229-292 用 TcpStream 发送 POST /api/session/list，携带 ClientRequest JSON envelope 和 cookie，判 response.result.ok。Rust 发而非 Tauri plugin-http：后者 Origin tauri.localhost 触发 trust 403。waitEngineBusinessReady 最多30秒，失败后仍放行（fail-open）；读不到 secret 立即放行。B 代码自述 cold-start 未读 Session index 会造成已选会话指针损坏，不能把这道门绝对化。

**顶层导航 / UI 生命周期**：src/App.tsx:140-320 先将端口注册到 Rust，然后撤销全局快捷键，invoke open_engine_in_main。Rust lib.rs:158-209 调 window.navigate(127.0.0.1:port)，等 URL 真正到 127.0.0.1 再 eval Cookie 脚本；超时返回有诊断的错误。导航是**替换原 Tauri React 文档**：TitleBar、StatusBar、KeyManager 不再渲染，用户看到官方 dsh web。Rust tray 的 menu/event handler仍在：manage=1 会返回 tauri.localhost 管理页；restart=1&port=事实端口会使管理 React 重挂并重启。退出 GUI 默认保留官方 dsh 服务；完全退出或 restartEngine 会依据端口 netstat/taskkill 杀掉**可能是外部来源**的共享引擎，真实任务会中断。

**引擎存储/更新**：src/lib/updater.ts 从 npm registry 获取版本并下载到 %APPDATA%/com.dsh.desktop/kernel/<version>，支持 pin、已验证、rollback；src/lib/enginePatch.ts 提供目录选择与 web-search patch，只有实际 Profile bundles 载入后才有效。tools/ 下的 codebuddy-mcp、dsh-balance、dsh-tauri-dir-picker 是附属扩展，并非 B 内置一套独立 Skill/MCP Agent Kernel。

## 官方 O：子代理 UI 的代码级闭环

packages/client/ui-subagent/src/client/index.ts:43-99 将 SubagentHeaderLineage 插入 conversation.session.header.lineage，SubagentCatalogAction 插入 header.actions，给子会话 composer 注册只读策略；onOpenChild 调 ctx.uiWorkspace.openSession(address)，侧栏调用 ctx.sidebarRight.openResource(subagentChatAddress(address),kind=subagentchat)。packages/client/ui-subagent/src/client/sidebar-chat/index.tsx:18-201 将父子 id + mode 编成 dsh-resource://subagentchat/session/<child>?parent=<parent>&mode=<mode>，通过 sessions.retain 获取子 SessionReference 并注入 shared Conversation slot。SubagentHeaderLineage.tsx:200-350 从 summaries.projectionValues.tokenUsage/subagentTiming 派生 token 与 time，递归延迟展开目录。官方 README 描述 continuable 经 subagents/prompt FIFO 和 interruptByParent，one-shot 是只读、external 不可导航；官方 Host control 动态验证仍缺。packages/client/ui-trajectory/src/client/TrajectoryView.tsx 读取 Session 事件投影供工具/消息时间线/搜索。

**归属判定**：即使 A/B 都显示这些 UI，也是官方模块的能力。A 的增益在运行时宿主、装配和桥；B 的增益在外部引擎启停与原生窗口。是否每个 bundle 在两个现实安装包中启用，需实际启动 Profile 验证。