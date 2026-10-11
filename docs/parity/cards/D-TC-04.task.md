你是施工者。任务：Atlas 功能对标任务卡 D-TC-04（Browser DOM、标签与 Computer Use），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-d-tc-04 -b card-d-tc-04 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28790`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-d-tc-04。在 docs/parity/cards/D-TC-04.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **D029 Computer Use**〔部分｜P0｜M〕缺：当前只有聚合动作；缺 request_access、stop control 等低层 Computer Use callable  抄：Codex [computer use docs](https://learn.chatgpt.com/docs/computer-use)；Claude [computer use](https://code.claude.com/docs/en/computer-use)；ZCode `packages/zcode-cua` / `packages/zcode-cua-plugin`  Atlas 位置：待定
- **D030 Browser 标签页/预览/导航**〔部分｜P0｜M〕缺：BrowserPanel 已有预览/停止按钮，但 browser.panel.sync 无前端消费者，browser_use 缺 tab.stop 与 pane handoff；缺 F1-unassigned Review pane/local preview 后端接线  抄：`packages/plugin-browser/src/rpc.ts`, `tools.ts`  Atlas 位置：待定
- **D031 Browser 文档/DOM 操作**〔部分｜P0｜M〕缺：缺 fill_form、selectOption 与 locator press 等 DOM 操作  抄：`packages/plugin-browser/src/rpc.ts`  Atlas 位置：待定
- **D033 Browser console/network/trace/CPU/heap/Lighthouse**〔部分｜P1｜L〕缺：只有 console；缺 network、trace、CPU/heap profiler 与 Lighthouse 内置操作  抄：`packages/plugin-browser/src/rpc.ts`  Atlas 位置：待定
- **D097 ZCode Browser Use runtime 选择**〔部分｜P1｜L〕缺：只有 X2 单一 runtime；runtime select 不可持久化且不支持 provider 切换  抄：[`browser-use-plugin/docs/overview.md`](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/browser-use-plugin/docs/overview.md)  Atlas 位置：待定
- **D098 Browser tabs 生命周期与用户 tab claim**〔部分｜P0｜L〕缺：缺 desktop user tab ownership registry、claim/finalize 生命周期  抄：ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`agent.browsers`, `browser.tabs`, `browser.user`  Atlas 位置：待定
- **D100 Browser DOM snapshot 与 locator**〔部分｜P0｜M〕缺：locator 未覆盖完整 press/select/fill_form 行为；返回的 Atlas snapshot/ref 不等同 upstream ARIA evidence  抄：ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`playwright.domSnapshot`, `getBy*/locator`  Atlas 位置：待定
- **D101 Browser frame/JS/wait**〔部分｜P1｜M〕缺：frame/evaluate/wait 依赖 Hermes/CDP supervisor；缺完整可用状态与策略受限行为一致性  抄：ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`frameLocator/evaluate/waitForURL/waitForLoadState`  Atlas 位置：待定
- **D104 Browser 截图与视口**〔部分｜P1｜M〕缺：截图返回 cache path/data URL，未形成可供界面访问的 workspace artifact  抄：ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`tab.screenshot`, `setViewportSize`, `viewportSize`  Atlas 位置：待定
- **D112 Codex App Computer Use**〔部分｜P0｜S〕缺：缺 Computer Use request/stop 低层动作与授权生命周期；后台窗口控制受 Atlas host 能力限制  抄：[Computer Use 官方插件发布说明](https://help.openai.com/en/articles/11391654)；[computer use docs](https://learn.chatgpt.com/docs/computer-use)  Atlas 位置：待定

## 总账里这张卡的说明
### D-TC-04｜Browser DOM、标签与 Computer Use（10 条）

- **包含编号：** D029, D030, D031, D033, D097, D098, D100, D101, D104, D112
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Codex [computer use docs](https://learn.chatgpt.com/docs/computer-use)；Claude [computer use](https://code.claude.com/docs/en/computer-use)；ZCode `packages/zcode-cua` / `packages/zcode-cua-plugin`
  - `packages/plugin-browser/src/rpc.ts`, `tools.ts`
  - `packages/plugin-browser/src/rpc.ts`
  - [`browser-use-plugin/docs/overview.md`](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/browser-use-plugin/docs/overview.md)
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`agent.browsers`, `browser.tabs`, `browser.user`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`playwright.domSnapshot`, `getBy*/locator`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`frameLocator/evaluate/waitForURL/waitForLoadState`
  - ZCode `apps/zcode-cli/packages/browser-use-plugin/docs/overview.md`；`tab.screenshot`, `setViewportSize`, `viewportSize`
  - [Computer Use 官方插件发布说明](https://help.openai.com/en/articles/11391654)；[computer use docs](https://learn.chatgpt.com/docs/computer-use)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
