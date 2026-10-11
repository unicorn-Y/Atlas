你是施工者。任务：Atlas 功能对标任务卡 B-TC-01（会话子功能：反馈、分支与工作流），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-b-tc-01 -b card-b-tc-01 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28791`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-b-tc-01。在 docs/parity/cards/B-TC-01.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **B008 回复/产品反馈动作**〔没做｜P1｜M〕缺：缺实际反馈接收 API，不能将反馈按钮接到虚构服务。  抄：ZCode `packages/ui/src/v4/ConversationHookDetailsAction.tsx`；Codex TUI fixed source `codex-rs/tui/src/slash_command.rs`（`6c0c6759d061`）；Codex [Desktop slash commands](https://learn.chatgpt.com/docs/reference/slash-commands)  Atlas 位置：待定
- **B047 Codex desktop shortcut：command center/settings/new/fork/chat/search**〔部分｜P1｜M〕缺：对话搜索快捷键已实现，其余全局命令与快捷键需 A/C 区接线核对。  抄：[reference commands](https://learn.chatgpt.com/docs/reference/commands)  Atlas 位置：待定
- **B122 动态并行工作流执行图（V5 B143）**〔部分｜P1｜L〕缺：有真实 run 事件时间线，缺并行工作流拓扑图与动态更新。  抄：ZCode 固定 SHA：`packages/ui/src/app-shell/WorkflowRunDirectorySidePane.tsx`；Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B130 同一 session 内树状分支与摘要切换**〔没做｜P1｜M〕缺：缺节点式会话持久化、分支摘要和返回旧节点继续编辑；Atlas fork 使用新会话 ID  抄：Pi `packages/coding-agent/docs/sessions.md`  Atlas 位置：待定
- **B131 Claude 临时 Side Chat 共享上下文 Fork**〔部分｜P1｜M〕缺：已有 SideChat，缺主会话上下文共享及临时分支生命周期  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B132 Claude 后续 Prompt 推荐**〔没做｜P1｜M〕缺：缺会话结束后的下一步 Prompt 建议交互  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定

## 总账里这张卡的说明
### B-TC-01｜会话子功能：反馈、分支与工作流（6 条）

- **包含编号：** B008, B047, B122, B130, B131, B132
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/v4/ConversationHookDetailsAction.tsx`；Codex TUI fixed source `codex-rs/tui/src/slash_command.rs`（`6c0c6759d061`）；Codex [Desktop slash commands](https://learn.chatgpt.com/docs/reference/slash-commands)
  - [reference commands](https://learn.chatgpt.com/docs/reference/commands)
  - ZCode 固定 SHA：`packages/ui/src/app-shell/WorkflowRunDirectorySidePane.tsx`；Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - Pi `packages/coding-agent/docs/sessions.md`
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
