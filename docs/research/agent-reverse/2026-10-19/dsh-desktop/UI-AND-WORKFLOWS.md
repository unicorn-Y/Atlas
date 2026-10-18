# 真实 UI / 操作流程（固定源码 S；不是运行截图 R）

## A：anywhere-labs Next — Electron 宿主包住官方 DSH UI

**主界面**：Next 的 src/client/index.ts:31-100 使用官方 Cordis ctx.slots.inject，注册 settings.section（Desktop Settings）、settings.action（桌面原生操作）、shell.overlay（settings requests 与安全模式），并装载 desktopDirectoryPicker、plugin-controls、onboarding。底层聊天/子代理/工具轨迹不是这个文件造出来的；来自官方 DSH Web UI 及活动 bundles。Profile + Cordis patches 决定何时加载，有 dependency 不保证启用。

**托盘与菜单**：Next src/desktop-menu.ts:6-35 可验证的 action 包含显示/刷新界面、重启桌面、打开 DSH 终端（macOS/Windows）、导出诊断、安全模式开关、Profile 动态单选项、新建/管理 Profile、设置、更新、浏览器中打开、恢复助手、退出。src/desktop-contract.ts:94-107 列出 create/switch/delete Profile、feature/preferences、rollback、修全局 patch、logs/backups、LAN 浏览器与 CA 导出等 command 类型；是否各命令在 src/main.ts 始终有无条件实现，还需全量命令映射抽取，不把 schema alone 当完成事实。

**开机/新用户**：Electron Host 启动选择 Profile→可选 Market/AA/Computer Use 通过 onboarding bridge 回写→重建 Profile bundle list 和 Cordis patch→官方 runProfile→显示官方 Web client。初始 remoteControl=false、market=false；native CUA 插件 disabled=true。A 的市场独立路径 dsh-community-market/src/client/MarketSettingsTab.tsx、src/host/routes.ts 有代码，但默认未启用，不应误称“默认运行完整插件市场”。A 有 native settings 和插件 controls 以及 LAN/HTTPS 浏览器入口；外部连接服务实际工作属于 U。

**异常与维护**：NextBackendController 使 error 状态显式展示，Recovery 对 Profile 的 package.json、cordis.patch.yml、desktop-next.features.json 建 config checkpoint，Safe Mode 创建临时 home 且最小插件集；升级前通过 Host IPC update-tasks inspect/lock/unlock 和优雅 shutdown ACK 判断。配置 checkpoint 不等于 Agent run 持久化恢复。

## B：dongdong-agent — 两阶段 UI，不是常驻两个界面

1. **React 管理壳**：src/App.tsx 渲染 TitleBar、StatusBar、EngineLauncher、KeyManagerDialog、CloseDialog；依赖安装、检查版本、升级/rollback/验证版本、状态/错误显示、密钥输入、F12、沉浸及快捷键属于此阶段。src/stores/engineStore.ts 仅有 engine health 与启动状态，不维护 Agent Session 列表。
2. **进入官方 WebUI**：已有实例复用或多候选 Node CLI spawn；waitEngineBusinessReady 尽力调用 /api/session/list；生成 HMAC Cookie；src/App.tsx invoke open_engine_in_main；Rust src-tauri/src/lib.rs window.navigate 到引擎 root，并在导航实际落地后注入 auth_js。**原 React document、TitleBar/StatusBar/KeyManager 被顶层导航替换，不能声称这些组件仍常驻。**
3. **系统托盘重进管理**：Rust lib.rs:~320-465 拥有原生 Tray：显示窗口、管理界面、重启引擎、升级测试版、退出且保留引擎、完全退出并关闭引擎。manage 返回 tauri.localhost/?manage=1；重启返回 ?restart=1&port=实际端口，由 React 管理壳重新执行 restartEngineOnPort；退出 GUI 保留共享 node dsh web，但完全退出/重启可能 taskkill 外部占用端口的进程，中断其 agent jobs。
4. **关闭事件差异**：src/App.tsx:147-160 的 React onCloseRequested 弹窗在管理壳有效，不能未经动态证据推论进入官方 WebUI 后同一 React listener 持续存在。
5. **工具插件**：tools/codebuddy-mcp、dsh-balance、dsh-tauri-dir-picker 是实际目录，挂载靠官方 Profile、Cordis patch；src/lib/enginePatch.ts 检查 dir-picker bundle 是否加入 profiles/web/package.json，未挂载会走替代覆盖层。

## 官方 DSH 子代理 UI 具体交互（不归 A 或 B 原创）

- O packages/client/ui-subagent/src/client/SubagentHeaderLineage.tsx:200-350 递归列表，只展开所需后代，Summary 投影提供 Label/Mode/running/lastTurnCompleted/tokenUsage/subagentTiming。每行状态、Token、时间，展开时可见更多子代理；已知外部子代理作为不可继续展开的叶节点。
- O packages/client/ui-subagent/src/client/index.ts:43-99：点击行 ctx.uiWorkspace.openSession(精确 parent/child/mode address)；侧栏箭头 ctx.sidebarRight.openResource(标准子代理 resource)，优先新 Pane。
- O packages/client/ui-subagent/src/client/sidebar-chat/index.tsx：resource 记录 direct parent id、child id、mode；sessions.retain(address) 持有引用；Sidebar SessionProvider 复用标准 Conversation 内容。不是另造一套假聊天。
- one-shot/unknown 历史只读，continuable 在父进程可达时允许后续 prompt；当前运行的 child 可以独立 Stop，父进程离线后 UI 限制新输入。官方文档描述队列为 FIFO；Host 每一分支实际动态结果尚无 R 验证。
- O packages/client/ui-trajectory/src/client/TrajectoryView.tsx 提供工具、请求、消息轨迹、搜索、时间维度与加载较老记录；各项目看到的“高级轨迹视图”不等于社区自己实现。

**仍未验证**：两者真实安装后的可点入体验、子代理多路并发、token/cost 到账明细、从休眠或强退恢复后的实际 UI 状态、发行包内 bundled 版本是否与源码等价。