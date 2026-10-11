你是施工者。任务：Atlas 功能对标任务卡 D-TC-05（Browser 文件、录制及 pane 生命周期），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-d-tc-05 -b card-d-tc-05 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28791`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-d-tc-05。在 docs/parity/cards/D-TC-05.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **D032 Browser 文件交互**〔没做｜P1｜M〕缺：缺 Browser 上传/下载/拖放及受授权文件句柄 API  抄：`packages/plugin-browser/src/rpc.ts`  Atlas 位置：待定
- **D105 Browser 原生 JS dialog**〔部分｜P1｜L〕缺：原生 JS dialog 仅在活动 CDP supervisor 下可用，缺统一 pane/runtime 管理  抄：ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`tab.getJsDialog`  Atlas 位置：待定
- **D106 Browser deliverable/handoff**〔部分｜P1｜L〕缺：handoff 可用；markDeliverable/finalize 缺 pane 所有权与交付 registry  抄：ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`markDeliverable`, `markHandoff`  Atlas 位置：待定
- **D107 Browser recording**〔部分｜P1｜L〕缺：能录制步骤并保存 skill，但缺 WebM 视频产物和通用流程回放交付  抄：ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`tab.recording.{start,status,cancel}`  Atlas 位置：待定
- **D108 Browser panel visibility/headless**〔部分｜P1｜M〕缺：缺 browser pane visibility 控制及 headless launch 模式  抄：ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`browser.capabilities.get("visibility").set`, `--browser-use=headless`  Atlas 位置：待定

## 总账里这张卡的说明
### D-TC-05｜Browser 文件、录制及 pane 生命周期（5 条）

- **包含编号：** D032, D105, D106, D107, D108
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - `packages/plugin-browser/src/rpc.ts`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`tab.getJsDialog`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`markDeliverable`, `markHandoff`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`tab.recording.{start,status,cancel}`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`browser.capabilities.get("visibility").set`, `--browser-use=headless`
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
