你是施工者。任务：Atlas 功能对标任务卡 B-TC-04（Changes：Diff、评注与审批），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-b-tc-04 -b card-b-tc-04 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28794`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-b-tc-04。在 docs/parity/cards/B-TC-04.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **B025 Approval 权限范围、一次/始终允许、拒绝理由**〔部分｜P0｜M〕缺：已有后端决策，权限范围、拒绝理由和审批键盘交互仍需完整呈现。  抄：ZCode `packages/ui/src/PermissionDialog.tsx`、`WorkflowPermissionBlock.tsx`；Codex [approvals](https://learn.chatgpt.com/docs/permissions)；Claude [permission modes](https://code.claude.com/docs/en/permission-modes)  Atlas 位置：待定
- **B055 Diff 的逐文件查看与行级 review**〔部分｜P0｜M〕缺：hunk 接受/拒绝已接入，更完整的逐文件编辑/IDE 选择与评注能力未完成。  抄：ZCode `packages/ui/src/components/ui/diff-viewer.tsx`；Codex [code review](https://learn.chatgpt.com/docs/code-review)；Claude [desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：shell/panels/ChangesPanel.tsx
- **B076 OpenCode V2 Review 会话概览和文件预览（V5 B115；V2）**〔部分｜P0｜M〕缺：已有 review 面板，缺 OpenCode V2 独立 Review 会话概览布局。  抄：固定 SHA：`packages/session-ui/src/v2/components/session-review-v2.tsx`、`session-review-file-preview-v2.tsx`；文件模型 `packages/app/src/workspaces/files/model.tsx`  Atlas 位置：待定
- **B093 Codex 合并审查提示与快捷导航（V5 B180；VI R12）**〔部分｜P1｜M〕缺：缺对合并审查的逐条导航/提示闭环；需核验评论框焦点和中文输入法。  抄：Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)；VI R12 [issue #48836](https://github.com/openai/codex/issues/48836) 是特定版本焦点/IME bug，不是功能缺失证据  Atlas 位置：待定
- **B102 Claude Desktop 多行 Diff 评论一次提交（V5 B159；VI R12 对照）**〔没做｜P0｜S〕缺：缺 Diff 多行评论的集中提交与焦点/输入法交互。  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B103 Claude Desktop Code Review 逐条 Fix/Dismiss/Apply fixes（V5 B160）**〔部分｜P1｜M〕缺：已有 hunk 接受/拒绝，缺 Review finding 的 Fix/Dismiss/Apply fixes 全语义。  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：shell/panels/ChangesPanel.tsx
- **B123 Codex Desktop Auto Review 审查结果/权限 UI**〔部分｜P1｜M〕缺：/auto-review 仅映射 /review，缺专属自动审查策略、授权和结果 UI。  抄：https://learn.chatgpt.com/docs/sandboxing/auto-review  Atlas 位置：待定

## 总账里这张卡的说明
### B-TC-04｜Changes：Diff、评注与审批（7 条）

- **包含编号：** B025, B055, B076, B093, B102, B103, B123
- **Atlas 拟修改文件/目录：** `shell/panels/ChangesPanel.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/PermissionDialog.tsx`、`WorkflowPermissionBlock.tsx`；Codex [approvals](https://learn.chatgpt.com/docs/permissions)；Claude [permission modes](https://code.claude.com/docs/en/permission-modes)
  - ZCode `packages/ui/src/components/ui/diff-viewer.tsx`；Codex [code review](https://learn.chatgpt.com/docs/code-review)；Claude [desktop](https://code.claude.com/docs/en/desktop)
  - 固定 SHA：`packages/session-ui/src/v2/components/session-review-v2.tsx`、`session-review-file-preview-v2.tsx`；文件模型 `packages/app/src/workspaces/files/model.tsx`
  - Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)；VI R12 [issue #48836](https://github.com/openai/codex/issues/48836) 是特定版本焦点/IME bug，不是功能缺失证据
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - https://learn.chatgpt.com/docs/sandboxing/auto-review
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
