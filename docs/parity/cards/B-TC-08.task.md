你是施工者。任务：Atlas 功能对标任务卡 B-TC-08（Git：PR、分支与历史），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-b-tc-08 -b card-b-tc-08 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28798`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-b-tc-08。在 docs/parity/cards/B-TC-08.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **B062 Git Review/PR、检查状态和差异定位**〔部分｜P0｜M〕缺：不含本地评论编辑/推送选择  抄：ZCode `packages/ui/src/{GitPane.tsx,GitPaneChangeCard.tsx}`；Codex [code review](https://learn.chatgpt.com/docs/code-review)  Atlas 位置：shell/panels/PullRequestSection.tsx；shell/panels/ChangesPanel.tsx
- **B091 Codex 会话 PR 操作时间线、评论及推送选择（V5 B178）**〔部分｜P1｜M〕缺：PR checks 已可查看，缺本地评论编辑、推送选择及完整 PR 时间线。  抄：Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.409）  Atlas 位置：shell/panels/PullRequestSection.tsx
- **B113 Git 操作菜单、提交/推送动作与错误详情（V5 B130）**〔部分｜P0｜M〕缺：Git 菜单只消费已授权操作，提交/推送执行与错误状态仍需真实接线。  抄：固定 SHA：`packages/ui/src/GitActionMenu.tsx`；附录 VIII-A2 对应菜单项  Atlas 位置：待定
- **B114 Git 分支切换与新建入口（V5 B131）**〔部分｜P0｜M〕缺：已有部分分支操作，缺新建/切换后会话工作区和当前分支的完整反馈。  抄：固定 SHA：`packages/ui/src/GitActionMenu.tsx`  Atlas 位置：待定
- **B115 Git 提交历史拓扑图（V5 B132、VIII-M）**〔没做｜P1｜M〕缺：缺真实 Git 历史拓扑视图；矩阵只提供部分 i18n 线索。  抄：固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L1417-L1443`（UI 文案线索）  Atlas 位置：待定

## 总账里这张卡的说明
### B-TC-08｜Git：PR、分支与历史（5 条）

- **包含编号：** B062, B091, B113, B114, B115
- **Atlas 拟修改文件/目录：** `shell/panels/PullRequestSection.tsx`；`shell/panels/ChangesPanel.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/{GitPane.tsx,GitPaneChangeCard.tsx}`；Codex [code review](https://learn.chatgpt.com/docs/code-review)
  - Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.409）
  - 固定 SHA：`packages/ui/src/GitActionMenu.tsx`；附录 VIII-A2 对应菜单项
  - 固定 SHA：`packages/ui/src/GitActionMenu.tsx`
  - 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L1417-L1443`（UI 文案线索）
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
