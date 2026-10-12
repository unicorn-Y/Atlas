# B-TC-10：对话轨迹、后台任务与调试

## 逐项结果

- **B073 — 已完成。** 新增 SQLite 持久化模型调用轨迹，记录真实 `run.usage` 的 request ID、来源、调用类型、模型及提供方实际返回的 token 字段；新增会话范围 API 和 Inspector「轨迹」筛选、搜索与展开视图。未收到的用量仍显示未知，不补零。
- **B075 — 部分完成。** 当前进程内的运行可标记为后台、查看状态、停止，并通过现有 `/ws/chat` run 恢复协议重新连接，传输失败显示恢复提示。Atlas 进程重启后不会继续执行原 run；运行时当前会将中断运行标记失败，因此不宣称具备跨进程续跑。
- **B116 — 部分完成。** 从 Atlas 创建的 HTTPX 模型客户端采集逐请求/响应状态、时长、脱敏端点、异常类别和 HTTPX 实际交付的 payload 字节数；会话日志跨运行持久化并在轨迹面板显示。只采集元数据，不保存正文、headers、query 或密钥。字节数不含 TLS/framing，部分流会标为不完整；不经这些 HTTPX seam 的传输（例如部分 SDK/云端专用客户端）不在覆盖范围内。逐轮 token 数仍只依据 provider 的真实 usage。
- **B124 — 部分完成。** 运行中的 reasoning 状态沿用 Atlas 真实事件；新增可展开转录，仅显示 provider/运行事件或已持久化消息 metadata 中明确提供的 reasoning 文本。模型未提供实际 Thinking 内容时不合成内容。
- **B126 — 已完成。** 增加全局快捷键帮助弹层，由 Atlas 实际快捷键绑定生成，`Ctrl+/` 打开；包含已注册的会话/全局键位。Composer 输入专属按键仍由其原有帮助入口显示。行为参照 [Claude Desktop 键盘快捷键文档](https://code.claude.com/docs/en/desktop#keyboard-shortcuts)。
- **B127 — 部分完成。** 新增会话后台任务面板，可查看 Atlas detached Bash 进程状态、读取 stdout/stderr、停止进程，并查看运行与子 Agent 状态。只展示由 Atlas LocalExecutionRuntime 跟踪且与当前会话关联的进程，不扫描或伪装其他系统进程。进程记录和输出句柄在 Atlas 重启后不保留。
- **B133 — 部分完成。** 通过同一后台任务面板查看、停止当前会话的 Agent run、子 Agent 与 detached Bash。Claude Desktop 的动态 workflow/subagent 管理模型没有直接对应 Atlas 的运行时对象，因此未伪造映射；跨重启继续后台执行也未实现。
- **B134 — 已完成。** 模型轨迹 API 支持按调用/轮次字段独立搜索，并可按来源和调用类型筛选；结果只来自当前会话已持久化的真实模型 usage，不与普通消息全文搜索混用。

## 实现位置

- 后端：`core/atlas/model_trajectory.py`、`core/atlas/models/http_diagnostics.py`、`core/atlas/models/network_transport.py`、`core/atlas/api/model_trajectory_router.py`、`core/atlas/api/network_diagnostics_router.py`、`core/atlas/api/background_jobs_router.py`。
- 接线：`core/atlas/api/app_services.py`、`core/atlas/api/application.py`、`core/atlas/api/run_drive.py`、`core/atlas/server.py`。
- 前端：`frontend/src/renderer/components/ModelCallDiagnostics.tsx`、`frontend/src/renderer/components/ShortcutHelpDialog.tsx`、`frontend/src/renderer/shell/panels/ModelTrajectoryPanel.tsx`、`frontend/src/renderer/shell/panels/BackgroundJobsPanel.tsx`、`frontend/src/renderer/shell/Inspector.tsx`、`frontend/src/renderer/services/shortcuts.ts`、`frontend/src/renderer/store/useAtlasStore.ts`、`frontend/src/renderer/App.tsx`、`backend-adapter/src/client.ts`。
- 上游核对：ZCode `aac4755666d09fdcd70272fcf063c077a639015f`（Apache-2.0）；OpenCode `7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937`（MIT）；Codex TUI `6c0c6759d061`；Claude Desktop 官方快捷键文档。实现按各项目行为与接口进行 Atlas 原生接线，没有复制其源代码，因此无需新增 `THIRD_PARTY_NOTICES.md` 条目。

## 验证与交付

- `npm --prefix frontend run build`：通过。
- 后端：使用隔离的 Python 3.14 环境启动 `python -m uvicorn atlas.server:app --port 28790`，设置 `ATLAS_UPSTREAM_AUTO=0` 和工作树内独立 `ATLAS_DATA_DIR`；`GET /api/health` 返回 `status: ok`，所有组件为 `ready`。启动后已停止服务。
- 未编写或运行测试套件。
- 功能实现提交：`d10d9dcaa5580b9522989462babe0add549656f5`。
