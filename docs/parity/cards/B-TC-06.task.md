你是施工者。任务：Atlas 功能对标任务卡 B-TC-06（Files：文件树、预览与编辑器），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-b-tc-06 -b card-b-tc-06 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28796`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-b-tc-06。在 docs/parity/cards/B-TC-06.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **B053 工作区文件树、Git 状态、右键复制路径/加入上下文**〔部分｜P0｜M〕缺：文件树搜索/右键已有，Git 状态与加入上下文需按真实数据及 API 补齐。  抄：ZCode `packages/ui/src/WorkspaceFileTree.tsx`、`workspace-file-tree/WorkspaceFileTreeRowView.tsx`；Codex [app](https://learn.chatgpt.com/docs/app)  Atlas 位置：shell/panels/FilesPanel.tsx
- **B082 从消息文件引用/差异文件在外部编辑器或 IDE 打开（用户追加；V5 B163）**〔部分｜P1｜M〕缺：可调用系统默认程序打开文件，缺任意 IDE 选择及当前 IDE 上下文同步。  抄：ZCode 固定 SHA：`packages/ui/src/lib/markdownFileLink.ts`、`WorkspaceFileTreeRowView.tsx`；Claude [Desktop file context menu](https://code.claude.com/docs/en/desktop)；Codex [Desktop app](https://learn.chatgpt.com/docs/app)  Atlas 位置：FilesPanel.tsx；ChangesPanel.tsx；ConversationMessage.tsx
- **B090 Codex 侧栏文件标签拖放排序（V5 B177）**〔没做｜P1｜S〕缺：缺侧面板文件标签拖动重排。  抄：Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.409）  Atlas 位置：待定
- **B104 Claude Desktop 内置文件编辑器磁盘冲突提示（V5 B162）**〔没做｜P0｜M〕缺：缺内置文件编辑器真实保存与外部磁盘修改冲突检测。  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B107 文件树 Git 状态标记（V5 B120）**〔待核实｜P0｜M〕缺：缺文件树 Git 状态数据是否真实映射的核验。  抄：固定 SHA：`packages/ui/src/workspace-file-tree/gitStatus.ts`、`WorkspaceFileTree.tsx`  Atlas 位置：待定
- **B108 文件树按名称搜索和刷新（V5 B121）**〔部分｜P0｜M〕缺：文件名搜索已实现，独立刷新入口未确认。  抄：ZCode 固定 SHA：`packages/ui/src/workspace-file-tree/searchRows.ts`；OpenCode 固定 SHA：`packages/app/src/workspaces/files/model.tsx`、`packages/app/src/session/screen.tsx`  Atlas 位置：shell/panels/FilesPanel.tsx
- **B117 Markdown/SVG 源码与预览切换、换行/字体（V5 B136、VIII-M）**〔部分｜P1｜M〕缺：已有源码/预览切换，SVG 专用字体与换行控件未全部核实。  抄：固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L1493-L1530`  Atlas 位置：shell/panels/FilesPanel.tsx；message-actions/CodeBlock.tsx
- **B129 PPTX 页码、缩略图、缩放、元素选择和导出（V5 B135、VIII-M）**〔部分｜P1｜M〕缺：仅为 i18n 字段  抄：固定 SHA aac4755666d09fdcd70272fcf063c077a639015f：packages/ui/src/i18n/locales/zh-CN.ts#L1469-L1493（UI 字段线索，TSX 操作须另证）  Atlas 位置：待定

## 总账里这张卡的说明
### B-TC-06｜Files：文件树、预览与编辑器（8 条）

- **包含编号：** B053, B082, B090, B104, B107, B108, B117, B129
- **Atlas 拟修改文件/目录：** `shell/panels/FilesPanel.tsx`；`FilesPanel.tsx`；`ChangesPanel.tsx`；`ConversationMessage.tsx`；`message-actions/CodeBlock.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/WorkspaceFileTree.tsx`、`workspace-file-tree/WorkspaceFileTreeRowView.tsx`；Codex [app](https://learn.chatgpt.com/docs/app)
  - ZCode 固定 SHA：`packages/ui/src/lib/markdownFileLink.ts`、`WorkspaceFileTreeRowView.tsx`；Claude [Desktop file context menu](https://code.claude.com/docs/en/desktop)；Codex [Desktop app](https://learn.chatgpt.com/docs/app)
  - Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.409）
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - 固定 SHA：`packages/ui/src/workspace-file-tree/gitStatus.ts`、`WorkspaceFileTree.tsx`
  - ZCode 固定 SHA：`packages/ui/src/workspace-file-tree/searchRows.ts`；OpenCode 固定 SHA：`packages/app/src/workspaces/files/model.tsx`、`packages/app/src/session/screen.tsx`
  - 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L1493-L1530`
  - 固定 SHA aac4755666d09fdcd70272fcf063c077a639015f：packages/ui/src/i18n/locales/zh-CN.ts#L1469-L1493（UI 字段线索，TSX 操作须另证）
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
