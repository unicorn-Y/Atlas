# B-TC-02 Composer：Slash、队列与快速输入

实现提交：`d4f39670847f2d46f7c7c7022ca0ea15ce1e72fc`

## 条目结果

- **B010 选中文本加入任务或发起 side chat**：对话消息选中文字后，现有右键/更多菜单可把选区加入输入草稿；新增“用选中文本开启侧聊”，将选中文本带入当前对话的 side chat。没有实现其它应用上的全局选区浮层；那项属于 B089。
- **B032 Slash command registry、模糊搜索、来源/说明**：新增统一 SlashCommand 注册契约；校验空 ID 和重复 ID，为内建、技能、自定义命令补来源；按命令名、说明、分组、来源模糊匹配，并展示来源、分组和说明。
- **B038 Codex `/worktree` 当前会话工作树入口**：核实原有命令已打开 Inspector 的上下文页；那里可查看已创建工作树、合并或删除。Composer 也已有下次 run 的工作树和起始分支选择。本卡没有新增跨工作树迁移对话的能力；Atlas 当前没有与 Codex handoff 对应的会话迁移契约。
- **B048 `!` shell composer 模式/命令**：dock Composer 中提交 `!command` 时先显示终端执行确认，显示命令内容；取消保留草稿，确认后才走现有终端路由。Atlas 仍使用当前会话的终端面板，没有 OpenCode 的独立 session shell API。
- **B051 队列项编辑、拖动、立即执行、删除、恢复**：队列现可拖动重排、取回输入框编辑、立即优先执行、删除并撤销恢复，以及暂停后的继续发送。撤销状态只保留在当前打开的对话界面；恢复不会绕过队列直接启动。带附件或上下文引用的项不会提供纯文本 steer，避免丢失其引用内容。
- **B079 Codex `/ide` 当前 IDE 选区/打开文件上下文**：现有 `/ide` 仍仅请求系统打开当前工作目录。仓库没有 IDE 扩展的上下文回传通道，因此不能真实获取当前 IDE 选区或打开文件；未添加假上下文。
- **B088 Codex Floating Composer 浮动输入框**：新增 Electron 独立浮动输入窗口和 `Ctrl+Alt+Space` 系统快捷键。提交内容会送回 Atlas 主窗口成为草稿并聚焦输入框，仍由用户检查后发送。
- **B089 Codex 选中文字 Ask Codex 覆层**：未实现任意应用选区的全局浮层。Atlas 当前没有 Windows/macOS 系统级选区读取接口或 IDE bridge；模拟 `Ctrl+C` 会覆盖剪贴板且不能保证读到正确选区，因此没有伪造此能力。
- **B097 Claude Desktop 输入中途纠偏**：明确沿用现有路由：所有非终态 run（planning、running、paused、waiting、approval）均按 steer/redirect/queue 设置处理；附件、文件、上下文引用、指定 profile/agent 的输入进入队列。审批和等待输入卡片仍走专用回复动作；run 结束前未确认的 steer 会回到队列。

## 验收

- `npm --prefix frontend run build`：通过（Electron、preload、renderer TypeScript 和 Vite production build）。
- 在 `core` 使用 Python 3.14 启动 `uvicorn atlas.server:app --port 28792`（`ATLAS_UPSTREAM_AUTO=0`）：通过；`/api/health` 返回 `status: ok`，11 个组件均为 `ready`，随后已停止服务。
- 按 taskbook 未编写或运行测试。
- 功能代码提交号：`d4f39670847f2d46f7c7c7022ca0ea15ce1e72fc`；结果文档另随文档提交推送。
