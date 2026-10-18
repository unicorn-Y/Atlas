# Desktop / Web / CLI / UI 工作流：静态源码所证

## 真实边界
- Windows Desktop v2 源码采用 Electron 主进程（`packages/desktop/src/main/desktop.ts`）、renderer（`packages/desktop/src/renderer/desktop-app.tsx`）和随包 CLI sidecar（`packages/desktop/src/main/service/background-service.ts`），renderer 通过 server HTTP/Event API 管 Session，窗口本地能力走独立 IPC RPC。尚未安装运行 Windows v2 EXE。
- CLI 命令源：`packages/cli/src/commands/handlers/` 实际包含 `run, serve, acp, auth, mcp, plugin, models, pair, session, service, stats, upgrade, uninstall`；列出源码文件不能证明每个命令在 Windows 发行包可用。
- Session Server 合约以 `packages/protocol/src/groups/session.ts` 定义；具体 HTTP handler 在 `packages/server/src/handlers/session.ts`，消息分页在 `handlers/message.ts:28-60`。

## 可从源码拼出的完整 UI 操作序列
1. **新消息**：Composer 构造 prompt → server session prompt → Session Inbox durable admit → 执行器 wake → Session runner → event feed → `app/src/runtime/server/client.tsx` emitter → session timeline 投影。
2. **修改队列**：`app/src/session/composer/queue.ts:60-109` 先提交 replacement、再取消原消息；`session.inbox.list` 核实待处理原始状态；服务端冲突应明确提示，避免伪装已改。
3. **边运行边追问**：代码区分 delivery=steer/queue；queued item 并不等同当前 turn 的追加 token。对应 `core/src/session/session.ts:136-185` 和 `runner/llm.ts:56-115`。
4. **子代理后台**：模型调 `subagent({background:true})` → 立即得到 child sessionID → 产生 Job → child 执行 → 父 session 收到 synthetic completion；`app/src/session/timeline/message-timeline.tsx:30-70` 有后台任务卡片与进入后台任务的交互线索。
5. **服务重连**：`server/client.tsx` 维护 connected status，服务断开时 `server-sync/connection.ts` invalidate，收到 `server.connected` 刷新；完整 backlog/replay 策略仍需 runtime 验证。
6. **表单/审批**：`app/src/session/requests/session-question-dock.tsx:260-283` 使用 `api.session.form.reply/cancel`；组件有键盘快捷处理 `:379-420`；批准与拒绝数据都通过服务器，不只是界面状态。
7. **导出/分叉/回退**：`app/src/session/commands/use-session-commands.tsx` 与 `session/commands/fork-dialog.tsx` 提供入口，后端 `core/src/session/revert.ts:21-80`、`session/projector.ts` 承接状态变更；具体菜单 keybind 在源码中动态注册，不可凭记忆给固定快捷键。
8. **多服务器/扩展**：`app/src/servers/registry/add-menu.tsx:9-56` 可扩展 server type 的菜单；`app/src/runtime/server/client.tsx` 为每个 server/目录配置连接和本地事件源；并非“整个 app 一个 WebSocket”。
9. **交互渲染**：`app/src/session/timeline/message-timeline.tsx` 调 `session-ui` 投影；`virtualizer.tsx:93-426` 处理大历史消息虚拟滚动、工具展开和跳转；性能跑分未验证。
10. **终端与后台任务**：`server/src/handlers/pty.ts` 暴露 PTY ticket+socket 分离链；`core/src/session/execution/restart.ts` 明确背景 shell 在 server restart 后不可当作继续存活，而是可告知取消。

## 没有在这批静态抽查中穷尽的 UI
完整路由/command registry 枚举、所有搜索面板、TUI 动态 JSX 组件、语音/插件自定义 UI、隐藏实验开关、移动版响应式行为、窗口崩溃后的真实重新连接，均列 U 待机械导出。要求按 `EXTRACTION-REQUEST.md` 导出可检索索引与实际运行轨迹后继续。
