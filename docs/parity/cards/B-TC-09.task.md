你是施工者。任务：Atlas 功能对标任务卡 B-TC-09（Inspector：面板、Dashboard 与插件 UI），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-b-tc-09 -b card-b-tc-09 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28799`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-b-tc-09。在 docs/parity/cards/B-TC-09.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **B065 Dashboard pin 工具输出/图表/报告**〔部分｜P1｜M〕缺：没有图表/报告生成器  抄：OpenClaw `docs/web/dashboards.md`、`docs/web/dashboard-architecture.md`（F1-B 原表“同上”）  Atlas 位置：shell/panels/SessionDashboardPanel.tsx
- **B066 Dashboard 受限生成内容与外部 MCP widget 权限**〔没做｜P1｜M〕缺：Dashboard 当前只支持受限文本/链接 widget，缺安全的外部 MCP widget host。  抄：OpenClaw `docs/web/dashboards.md`；ZCode `packages/ui/src/gen-ui/CONTRACT.md`；Goose [MCP UI](https://github.com/block/goose/blob/main/documentation/docs/guides/interactive-chat/mcp-ui.md)  Atlas 位置：SessionDashboardPanel.tsx；workspace_router.py
- **B071 办公/编程双 UI 模式（V5 B99）**〔没做｜P1｜M〕缺：缺真实办公/编程模式状态及两套 UI 的切换契约。  抄：固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/onboarding/OnboardingModeSelector.tsx`  Atlas 位置：待定
- **B094 侧面板多标签、拖动和最近关闭恢复（V5 B117–118）**〔部分｜P1｜M〕缺：Files 已有多 tab 与最近关闭恢复，缺跨面板拖动排序和自由布局。  抄：ZCode 固定 SHA：`packages/ui/src/app-shell/SidePaneTabOverview.tsx`、`lib/workspaceSidePane.ts`；Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.409）；Claude [desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：shell/panels/FilesPanel.tsx
- **B095 Claude Desktop 面板拖放自由布局（V5 B150）**〔没做｜P1｜L〕缺：缺多个 Inspector 面板自由拖放布局。  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B096 Claude Desktop 面板独立弹出与重新停靠（V5 B151）**〔没做｜P1｜L〕缺：缺面板独立窗口弹出与重新停靠的 Electron 生命周期。  抄：Claude [Desktop](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定
- **B119 GenUI 生成交互卡片及微调（V5 B139）**〔没做｜P1｜L〕缺：缺受控 GenUI 协议、组件宿主及模型生成代码的执行隔离。  抄：固定 SHA：`packages/ui/src/gen-ui/components/GenUiMessageResponse.tsx`、`packages/ui/src/gen-ui/CONTRACT.md`  Atlas 位置：待定
- **B120 插件自定义 UI 侧栏（V5 B140）**〔没做｜P1｜L〕缺：缺插件自定义 UI 的宿主协议、授权和受控侧栏承载。  抄：ZCode 固定 SHA：`packages/ui/src/plugin-ui/PluginUiSidePane.tsx`；Claude [MCP](https://code.claude.com/docs/en/mcp)  Atlas 位置：待定
- **B121 子代理独立侧栏与活动/历史目录（V5 B141–142）**〔部分｜P1｜L〕缺：当前只有 task 卡，缺跨会话子代理目录、活动和历史 API。  抄：ZCode 固定 SHA：`packages/ui/src/app-shell/{SubagentSessionSidePane.tsx,SubagentDirectorySidePane.tsx}`；Codex [long-running tasks](https://learn.chatgpt.com/docs/long-running-work)；Claude [sub-agents](https://code.claude.com/docs/en/sub-agents)、[agent teams](https://code.claude.com/docs/en/agent-teams)、[Desktop feature comparison](https://code.claude.com/docs/en/desktop)  Atlas 位置：待定

## 总账里这张卡的说明
### B-TC-09｜Inspector：面板、Dashboard 与插件 UI（9 条）

- **包含编号：** B065, B066, B071, B094, B095, B096, B119, B120, B121
- **Atlas 拟修改文件/目录：** `shell/panels/SessionDashboardPanel.tsx`；`SessionDashboardPanel.tsx`；`workspace_router.py`；`shell/panels/FilesPanel.tsx`
- **要读的上游文件/文档：**
  - OpenClaw `docs/web/dashboards.md`、`docs/web/dashboard-architecture.md`（F1-B 原表“同上”）
  - OpenClaw `docs/web/dashboards.md`；ZCode `packages/ui/src/gen-ui/CONTRACT.md`；Goose [MCP UI](https://github.com/block/goose/blob/main/documentation/docs/guides/interactive-chat/mcp-ui.md)
  - 固定 SHA `aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/onboarding/OnboardingModeSelector.tsx`
  - ZCode 固定 SHA：`packages/ui/src/app-shell/SidePaneTabOverview.tsx`、`lib/workspaceSidePane.ts`；Codex 官方 [changelog](https://learn.chatgpt.com/docs/changelog)（26.409）；Claude [desktop](https://code.claude.com/docs/en/desktop)
  - Claude [Desktop](https://code.claude.com/docs/en/desktop)
  - 固定 SHA：`packages/ui/src/gen-ui/components/GenUiMessageResponse.tsx`、`packages/ui/src/gen-ui/CONTRACT.md`
  - ZCode 固定 SHA：`packages/ui/src/plugin-ui/PluginUiSidePane.tsx`；Claude [MCP](https://code.claude.com/docs/en/mcp)
  - ZCode 固定 SHA：`packages/ui/src/app-shell/{SubagentSessionSidePane.tsx,SubagentDirectorySidePane.tsx}`；Codex [long-running tasks](https://learn.chatgpt.com/docs/long-running-work)；Claude [sub-agents](https://code.claude.com/docs/en/sub-agents)、[agent teams](https://code.claude.com/docs/en/agent-teams)、[Desktop feature comparison](https://code.claude.com/docs/en/desktop)
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
