你是施工者。任务：Atlas 功能对标任务卡 B-TC-07（Browser：预览验证与站点权限），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-b-tc-07 -b card-b-tc-07 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28797`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-b-tc-07。在 docs/parity/cards/B-TC-07.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **B060 浏览器控制、导航、响应式 viewport 与权限**〔部分｜P1｜M〕缺：浏览器预览和批注已接入，网站权限控制及自动预览验证未实现。  抄：ZCode `packages/ui/src/browser-use/{UnifiedBrowserView.tsx,BrowserViewportToolbar.tsx,EmbeddedBrowserPermissionPrompts.tsx}`；Codex [browser](https://learn.chatgpt.com/docs/app)；Claude [desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：shell/panels/BrowserPanel.tsx
- **B098 Claude Desktop Browser 开发服务器列表与批量停止（V5 B155）**〔没做｜P1｜M〕缺：缺 Browser 内开发服务的列表与批量停止及其进程状态联动。  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B099 Claude Desktop Browser 自动预览验证（V5 B156）**〔没做｜P1｜M〕缺：当前浏览器只供手工预览，缺操作后自动验证服务。  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B100 Claude Desktop Browser Cookie 持久化/清除站点数据（V5 B157）**〔没做｜P1｜M〕缺：缺站点 Cookie/存储的持久化与清除状态展示。  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B101 Claude Desktop Browser 外站逐域允许一次/总是允许/拒绝（V5 B158）**〔没做｜P1｜M〕缺：缺浏览器外站逐域一次/始终允许/拒绝的真实审批 UI。  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B111 浏览器网站权限卡片（V5 B127）**〔没做｜P1｜M〕缺：缺 Atlas 自有网站权限卡；Chromium 原生弹窗不等于 Atlas 授权面板。  抄：ZCode 固定 SHA：`packages/ui/src/browser-use/EmbeddedBrowserPermissionPrompts.tsx`；Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B112 浏览器设备权限结果卡（摄像头/麦克风/屏幕/定位等；VIII-M）**〔待核实｜P1｜L〕缺：缺设备权限结果卡及各设备来源真实授权状态的逐设备核验。  抄：ZCode 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L965-L1000`（可见设备权限类别，组件/API 需逐项核验）；Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定

## 总账里这张卡的说明
### B-TC-07｜Browser：预览验证与站点权限（7 条）

- **包含编号：** B060, B098, B099, B100, B101, B111, B112
- **Atlas 拟修改文件/目录：** `shell/panels/BrowserPanel.tsx`
- **要读的上游文件/文档：**
  - ZCode `packages/ui/src/browser-use/{UnifiedBrowserView.tsx,BrowserViewportToolbar.tsx,EmbeddedBrowserPermissionPrompts.tsx}`；Codex [browser](https://learn.chatgpt.com/docs/app)；Claude [desktop](https://code.claude.com/docs/en/desktop)
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - ZCode 固定 SHA：`packages/ui/src/browser-use/EmbeddedBrowserPermissionPrompts.tsx`；Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - ZCode 固定 SHA：`packages/ui/src/i18n/locales/zh-CN.ts#L965-L1000`（可见设备权限类别，组件/API 需逐项核验）；Claude [Desktop](https://code.claude.com/docs/en/desktop)
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
