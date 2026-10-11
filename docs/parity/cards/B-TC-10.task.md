你是施工者。任务：Atlas 功能对标任务卡 B-TC-10（对话轨迹、后台任务与调试），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-b-tc-10 -b card-b-tc-10 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28790`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-b-tc-10。在 docs/parity/cards/B-TC-10.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **B073 模型调用轨迹按调用来源/类型展开（V5 B103；VIII-M）**〔没做｜P1｜M〕缺：缺少逐次调用持久化与来源/类型展开  抄：固定 SHA：packages/ui/src/ModelTrajectoryExpansionMenu.tsx、packages/ui/src/i18n/locales/zh-CN.ts（VIII-M，调用来源和筛选文案）  Atlas 位置：待定
- **B075 OpenCode V2 后台会话状态及重新连接入口（VIII-B2；IX R101）**〔没做｜P0｜M〕缺：缺 OpenCode V2 等效的会话级后台挂起、状态与重连接口。  抄：固定 SHA：packages/app/src/session/commands/use-session-commands.tsx、packages/app/src/session/screen.tsx；IX R101 是特定版本传输故障报告，不是能力证据  Atlas 位置：待定
- **B116 会话/模型网络日志和逐轮 Token 调试（V5 B147；VIII-M）**〔没做｜P1｜M〕缺：缺会话逐轮模型 HTTP/I/O、网络日志和 token 的真实采集数据。  抄：ZCode 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L4763-L4798`（诊断 UI 文案，需配组件）；Codex TUI 固定源 `codex-rs/tui/src/slash_command.rs`（`6c0c6759d061`）  Atlas 位置：待定
- **B124 Thinking 内容与工作状态（V5 B102；VI R03；IX R102）**〔部分｜P1｜M〕缺：运行状态已显示，缺模型实际 Thinking 内容的分类和可展开转录。  抄：OpenCode 固定 SHA：packages/session-ui/src/message/current-message.tsx、message-content.tsx；Codex TUI 固定源 codex-rs/tui/src/keymap.rs（6c0c6759d061）；Claude Desktop view modes 文档  Atlas 位置：待定
- **B126 Claude Desktop 会话快捷键帮助层（V5 B152）**〔部分｜P1｜M〕缺：快捷键帮助仅覆盖 Composer，缺完整会话/全局键位的帮助弹层。  抄：https://code.claude.com/docs/en/desktop#keyboard-shortcuts  Atlas 位置：待定
- **B127 OpenCode V2 背景 Bash 输出侧栏（V5 B123）**〔没做｜P0｜M〕缺：缺后台 Bash 输出专用侧栏及进程状态/停止管理。  抄：固定 SHA：packages/app/src/session/screen.tsx、screen-layout.ts、runtime/extension/panels.tsx  Atlas 位置：待定
- **B133 Claude 后台任务查看与停止**〔没做｜P1｜M〕缺：缺与当前会话关联的后台任务状态/停止专用面板  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B134 Codex 模型轨迹内搜索**〔没做｜P1｜M〕缺：缺按调用/轮次检索模型轨迹的能力；独立于普通对话搜索  抄：ZCode `packages/ui/src/i18n/locales/zh-CN.ts`（V5 B133，文案线索，具体 TSX 待核）  Atlas 位置：待定

## 总账里这张卡的说明
### B-TC-10｜对话轨迹、后台任务与调试（8 条）

- **包含编号：** B073, B075, B116, B124, B126, B127, B133, B134
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - 固定 SHA：packages/ui/src/ModelTrajectoryExpansionMenu.tsx、packages/ui/src/i18n/locales/zh-CN.ts（VIII-M，调用来源和筛选文案）
  - 固定 SHA：packages/app/src/session/commands/use-session-commands.tsx、packages/app/src/session/screen.tsx；IX R101 是特定版本传输故障报告，不是能力证据
  - ZCode 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L4763-L4798`（诊断 UI 文案，需配组件）；Codex TUI 固定源 `codex-rs/tui/src/slash_command.rs`（`6c0c6759d061`）
  - OpenCode 固定 SHA：packages/session-ui/src/message/current-message.tsx、message-content.tsx；Codex TUI 固定源 codex-rs/tui/src/keymap.rs（6c0c6759d061）；Claude Desktop view modes 文档
  - https://code.claude.com/docs/en/desktop#keyboard-shortcuts
  - 固定 SHA：packages/app/src/session/screen.tsx、screen-layout.ts、runtime/extension/panels.tsx
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - ZCode `packages/ui/src/i18n/locales/zh-CN.ts`（V5 B133，文案线索，具体 TSX 待核）
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
