你是施工者。任务：Atlas 功能对标任务卡 B-TC-02（Composer：Slash、队列与快速输入），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-b-tc-02 -b card-b-tc-02 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28792`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-b-tc-02。在 docs/parity/cards/B-TC-02.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **B010 选中文本加入任务或发起 side chat**〔部分｜P0｜M〕缺：没有实现桌面级选区浮层  抄：ZCode `packages/ui/src/v4/{ConversationSelectionTooltip.tsx,SelectionActionMenu.tsx}`；Codex [side chat](https://learn.chatgpt.com/docs/app)；Claude [desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：App.tsx；components/ConversationMessage.tsx
- **B032 Slash command registry、模糊搜索、来源/说明**〔部分｜P0｜L〕缺：已接入一批 slash 命令，统一来源/说明、模糊搜索与注册契约仍需核查。  抄：ZCode packages/ui/src/lib/slashCommands.ts、hooks/useSlashCommands.ts、CLI command-center；OpenCode packages/app/src/components/dialog-select-*；Codex commands 文档；Claude commands 文档  Atlas 位置：待定
- **B038 Codex `/worktree` 当前会话工作树入口**〔部分｜P1｜M〕缺：已有进入 Worktree 面板命令，跨工作树迁移执行语义不在本入口内。  抄：[git worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)；ZCode workspace shell；Atlas Worktree 面板/API  Atlas 位置：待定
- **B048 `!` shell composer 模式/命令**〔部分｜P0｜M〕缺：缺明确的 ! shell 输入前缀模式和发送前执行确认。  抄：OpenCode session composer `!` mode；Claude [interactive mode](https://code.claude.com/docs/en/interactive-mode)  Atlas 位置：待定
- **B051 队列项编辑、拖动、立即执行、删除、恢复**〔部分｜P0｜M〕缺：已有队列 API 可支持部分编辑/删除，缺完整拖动、立即执行、恢复等操作契约。  抄：ZCode `packages/ui/src/v4/ConversationQueuePanel.tsx`；OpenCode session queue；Codex [app](https://learn.chatgpt.com/docs/app)  Atlas 位置：待定
- **B079 Codex `/ide` 当前 IDE 选区/打开文件上下文（用户追加）**〔部分｜P1｜M〕缺：/ide 仅能打开工作目录，缺当前 IDE 选区、打开文件上下文回传。  抄：固定版本源码 `https://github.com/openai/codex/blob/6c0c6759d061/codex-rs/tui/src/slash_command.rs`（VIII-E，`/ide`）；Codex [IDE integrations](https://learn.chatgpt.com/docs/ide/commands)  Atlas 位置：App.tsx
- **B088 Codex Floating Composer 浮动输入框（V5 B174）**〔没做｜P1｜S〕缺：缺真正跨窗口的浮动输入框与系统级唤起快捷键。  抄：Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（2026-09-11）  Atlas 位置：待定
- **B089 Codex 选中文字 Ask Codex 覆层（V5 B175）**〔没做｜P1｜S〕缺：缺桌面任意应用文本选区上的 Ask Codex 全局浮层。  抄：Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.410）  Atlas 位置：待定
- **B097 Claude Desktop 输入中途纠偏（V5 B153）**〔部分｜P1｜S〕缺：有运行态 queue/steer，但需要明确中途输入在各 run 状态的路由行为。  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定

## 总账里这张卡的说明
### B-TC-02｜Composer：Slash、队列与快速输入（9 条）

- **包含编号：** B010, B032, B038, B048, B051, B079, B088, B089, B097
- **Atlas 拟修改文件/目录：** `App.tsx`；`components/ConversationMessage.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/v4/{ConversationSelectionTooltip.tsx,SelectionActionMenu.tsx}`；Codex [side chat](https://learn.chatgpt.com/docs/app)；Claude [desktop](https://code.claude.com/docs/en/desktop)
  - ZCode packages/ui/src/lib/slashCommands.ts、hooks/useSlashCommands.ts、CLI command-center；OpenCode packages/app/src/components/dialog-select-*；Codex commands 文档；Claude commands 文档
  - [git worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)；ZCode workspace shell；Atlas Worktree 面板/API
  - OpenCode session composer `!` mode；Claude [interactive mode](https://code.claude.com/docs/en/interactive-mode)
  - ZCode `packages/ui/src/v4/ConversationQueuePanel.tsx`；OpenCode session queue；Codex [app](https://learn.chatgpt.com/docs/app)
  - 固定版本源码 `https://github.com/openai/codex/blob/6c0c6759d061/codex-rs/tui/src/slash_command.rs`（VIII-E，`/ide`）；Codex [IDE integrations](https://learn.chatgpt.com/docs/ide/commands)
  - Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（2026-09-11）
  - Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.410）
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
