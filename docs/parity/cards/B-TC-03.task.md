你是施工者。任务：Atlas 功能对标任务卡 B-TC-03（消息阅读与文件引用），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-b-tc-03 -b card-b-tc-03 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28793`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-b-tc-03。在 docs/parity/cards/B-TC-03.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **B013 Markdown 文件链接、行/列跳转和安全 URL**〔部分｜P0｜M〕缺：文件链接已可按行定位，尚未支持按列定位。  抄：ZCode `packages/ui/src/lib/markdownFileLink.ts`、`PreviewPane.tsx`；OpenCode session markdown；Codex [app](https://learn.chatgpt.com/docs/app)  Atlas 位置：components/ConversationMessage.tsx；shell/panels/FilesPanel.tsx
- **B014 文件链接右键复制路径/打开预览**〔部分｜P0｜M〕缺：文件树已有右键操作，但消息正文内文件链接缺同等级右键菜单。  抄：ZCode `packages/ui/src/lib/markdownFileLink.ts`、`PreviewPane.tsx`；OpenCode `packages/session-ui`（无消息级 context menu）；Codex [app](https://learn.chatgpt.com/docs/app)  Atlas 位置：FilesPanel.tsx
- **B046 Codex artifacts、Sources 打开/下载文件**〔部分｜P1｜M〕缺：可预览本地 artifacts，外部 Sources 下载链路尚不完整。  抄：[artifacts viewer](https://learn.chatgpt.com/docs/artifacts-viewer)，[changelog](https://learn.chatgpt.com/docs/changelog) 2026-09-11  Atlas 位置：待定
- **B069 右键菜单：消息、代码、文件链接**〔部分｜P0｜M〕缺：未实现完整消息右键菜单  抄：ZCode `packages/ui/src/v4/ConversationSelectionTooltip.tsx`、`WorkspaceFileTreeRowView.tsx`；OpenCode app/session 仅项目/会话行 context menu；Codex [app](https://learn.chatgpt.com/docs/app)  Atlas 位置：ConversationMessage.tsx；message-actions/CodeBlock.tsx；shell/panels/FilesPanel.tsx
- **B084 屏幕阅读模式/辅助阅读显示（用户追加；VI R17）**〔部分｜P1｜M〕缺：Composer 已支持读屏导航，其他对话面板的完整无障碍路径未覆盖。  抄：Claude [interactive mode](https://code.claude.com/docs/en/interactive-mode)、[releases v2.1.208](https://github.com/anthropics/claude-code/releases/tag/v2.1.208)；ZCode 固定 SHA 的 `packages/ui/src/i18n/locales/zh-CN.ts` 只证明有无障碍文案时单独标 U  Atlas 位置：components/Composer.tsx；MessageThread.tsx；ThreadPresentation.tsx
- **B085 对话区全键盘可达（用户追加；VI R17）**〔部分｜P0｜M〕缺：新控件可键盘操作，但全对话区 Tab 顺序和焦点路径尚未完整核查。  抄：ZCode 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts`（快捷键文案）及 `packages/shared/src/shortcutCommands.ts`；OpenCode 固定 SHA：`packages/app/src/runtime/i18n/en.ts`（Shortcuts 设置）和 `packages/ui/src/hooks/keyboard.ts`；Codex TUI 固定源 `codex-rs/tui/src/keymap.rs`（`6c0c6759d061`）；Claude [desktop](https://code.claude.com/docs/en/desktop)、[interactive mode](https://code.claude.com/docs/en/interactive-mode)  Atlas 位置：MessageThread.tsx；ConversationMessage.tsx；ThreadPresentation.tsx；FilesPanel.tsx
- **B092 Codex 图片灯箱缩放/下载（V5 B182）**〔部分｜P1｜S〕缺：图片灯箱缩放已有，下载动作及完整键盘关闭行为未确认。  抄：Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.429）  Atlas 位置：FilesPanel.tsx；components/message-actions/ImagePreview.tsx
- **B125 Claude Desktop transcript Normal/Thinking/Verbose（V5 B149）**〔部分｜P1｜S〕缺：已有呈现模式，未对齐 Claude Normal/Thinking/Verbose 三档语义。  抄：https://code.claude.com/docs/en/desktop#switch-view-modes；1.46388.1 之前版本另有 Summary  Atlas 位置：待定

## 总账里这张卡的说明
### B-TC-03｜消息阅读与文件引用（8 条）

- **包含编号：** B013, B014, B046, B069, B084, B085, B092, B125
- **Atlas 拟修改文件/目录：** `components/ConversationMessage.tsx`；`shell/panels/FilesPanel.tsx`；`FilesPanel.tsx`；`ConversationMessage.tsx`；`message-actions/CodeBlock.tsx`；`components/Composer.tsx`；`MessageThread.tsx`；`ThreadPresentation.tsx`；`components/message-actions/ImagePreview.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/lib/markdownFileLink.ts`、`PreviewPane.tsx`；OpenCode session markdown；Codex [app](https://learn.chatgpt.com/docs/app)
  - ZCode `packages/ui/src/lib/markdownFileLink.ts`、`PreviewPane.tsx`；OpenCode `packages/session-ui`（无消息级 context menu）；Codex [app](https://learn.chatgpt.com/docs/app)
  - [artifacts viewer](https://learn.chatgpt.com/docs/artifacts-viewer)，[changelog](https://learn.chatgpt.com/docs/changelog) 2026-09-11
  - ZCode `packages/ui/src/v4/ConversationSelectionTooltip.tsx`、`WorkspaceFileTreeRowView.tsx`；OpenCode app/session 仅项目/会话行 context menu；Codex [app](https://learn.chatgpt.com/docs/app)
  - Claude [interactive mode](https://code.claude.com/docs/en/interactive-mode)、[releases v2.1.208](https://github.com/anthropics/claude-code/releases/tag/v2.1.208)；ZCode 固定 SHA 的 `packages/ui/src/i18n/locales/zh-CN.ts` 只证明有无障碍文案时单独标 U
  - ZCode 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts`（快捷键文案）及 `packages/shared/src/shortcutCommands.ts`；OpenCode 固定 SHA：`packages/app/src/runtime/i18n/en.ts`（Shortcuts 设置）和 `packages/ui/src/hooks/keyboard.ts`；Codex TUI 固定源 `codex-rs/tui/src/keymap.rs`（`6c0c6759d061`）；Claude [desktop](https://code.claude.com/docs/en/desktop)、[interactive mode](https://code.claude.com/docs/en/interactive-mode)
  - Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.429）
  - https://code.claude.com/docs/en/desktop#switch-view-modes；1.46388.1 之前版本另有 Summary
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
