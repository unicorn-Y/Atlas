# B-TC-03：消息阅读与文件引用

基线：`origin/memory-v1`（`e9be4b4b176eae332c82cd124ec669b4b7612969`）  
分支：`card-b-tc-03`

## 逐项结果

- **B013 Markdown 文件链接、行/列跳转和安全 URL — 已完成。** 消息 Markdown 文件目标现在识别 `path:line:column`、`#LlineCcolumn` 和列号查询参数，并将 1-based 列号传递到 FilesPanel 的代码视图定位。仅接受当前工作区内的本地文件链接与无凭据的 HTTP(S) 外链；危险协议、非本机 `file://` 主机、越界路径及其他无法验证的目标不渲染为可点击链接。外链通过 Electron 既有的窗口打开策略交给系统浏览器。
- **B014 文件链接右键复制路径/打开预览 — 已完成。** 消息正文的工作区文件链接右键菜单提供打开文件和复制路径；行列后缀会保留在复制结果中。打开后进入 FilesPanel 的代码视图。
- **B046 Codex artifacts、Sources 打开/下载文件 — 部分完成。** Inspector 为路径可验证位于当前 workspace/worktree 内的本地 artifact 提供下载，并保留现有预览/默认程序打开行为。外部 Sources 仍未接入：Atlas 当前消息和 artifact 数据没有外部 Source 对象、provenance、授权或受控下载 API，不能安全地构造可用下载 URL。官方 Codex/ChatGPT 文档描述了本地文件预览、Sources 打开及不可预览文件下载行为，但没有为 Atlas 提供可复用的接口合同。
- **B069 右键菜单：消息、代码、文件链接 — 已完成。** 审阅确认消息与代码块已有可访问的右键操作菜单，文件链接已有独立的复制路径/打开入口；本次将行列位置纳入文件链接菜单和复制路径。没有再新增重复菜单。
- **B084 屏幕阅读模式/辅助阅读显示 — 已完成。** Composer 原有读屏导航和建议播报保持不变。对话活动区域新增可聚焦的 region、可见焦点样式、滚动/Tab 路径屏幕阅读说明；显示设置继续提供完成回复播报偏好。
- **B085 对话区全键盘可达 — 已完成。** 对话活动区可通过 Tab 聚焦；现有按钮、折叠项和显示设置沿原生键盘交互访问。焦点位于对话活动区时，`Ctrl+O` 循环 transcript 显示预设。焦点说明使用屏幕阅读器可读文本。此次按任务卡限定只做构建验证，没有运行桌面 UI 手工验收。
- **B092 Codex 图片灯箱缩放/下载 — 部分完成。** 图片灯箱保留现有下载按钮与缩放操作；关闭行为补齐 Escape，保留焦点陷阱和关闭后焦点返回。下载使用 renderer 的 `fetch`/Blob 路径，可处理 data URL、同源 URL 和允许 CORS 的外链；拒绝 CORS 的第三方图片仍无法由 renderer 读取并下载，稳定支持任意跨域资源需要受控的 Electron 主进程下载/保存接口。
- **B125 Claude Desktop transcript Normal/Thinking/Verbose — 部分完成。** 新增 Normal、Thinking、Verbose 预设并持久化。Normal 收起 Atlas reasoning 与活动摘要；Thinking 只在当前对话存在 reasoning 时显示 reasoning 并收起活动摘要；Verbose 展开 Atlas 已记录的活动。Atlas 当前 timeline 不保证记录每一次文件读取或所有中间步骤，因此无法声称 Verbose 覆盖 Claude Desktop 的全部事件细节。

## 上游参考

- ZCode `zai-org/ZCode` 固定提交 `aac4755666d09fdcd70272fcf063c077a639015c`（Apache-2.0）：检查 Markdown 文件链接与会话选择操作。实现按行为对齐，没有复制上游代码。
- OpenCode `anomalyco/opencode` 固定提交 `7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937`（MIT）：检查会话 Markdown 的本地文件链接/外链处理。实现按行为对齐，没有复制上游代码。
- Claude Desktop：[transcript view modes](https://code.claude.com/docs/en/desktop#switch-view-modes)；Normal/Thinking/Verbose 语义及 `Ctrl+O` 循环行为。
- Codex：[Work with files / artifacts viewer](https://learn.chatgpt.com/docs/artifacts-viewer)；[官方 changelog](https://learn.chatgpt.com/docs/changelog)，2026-09-11 Sources 文件行为及 Codex app 26.429 图片灯箱下载行为。

本次没有直接移植第三方源码，因此没有添加移植头，也没有修改 `THIRD_PARTY_NOTICES.md`。

## 验证

- `npm --prefix frontend run build`：通过（Electron TypeScript、preload、renderer TypeScript 与 Vite 生产构建）。
- 后端：在工作树隔离 Python 3.14 环境、隔离 `ATLAS_DATA_DIR`/`HERMES_HOME` 且 `ATLAS_UPSTREAM_AUTO=0` 下启动 `uvicorn atlas.server:app --port 28793`；`/api/health` 返回 `status: ok`，所有组件为 `ready`，随后已关闭服务。
- 启动期间记录到一个不影响健康状态的后台 warm-up 警告：Hermes checkout 缺少 `agent.agent_hooks`；该 warm-up 被 Atlas 捕获，服务所有注册组件仍为 ready。本次没有运行会话请求来验证该可选 warm-up 路径。
- 未编写或运行测试套件。

## 提交

- 实现提交：`dd5a69e`（`feat(parity): improve conversation reading and file references`）。
- 本结果文档随后的文档提交号由 Git 记录。
