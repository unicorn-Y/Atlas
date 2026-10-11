你是施工者。任务：Atlas 功能对标任务卡 D-TC-03（Web 检索、JS REPL、录制和事件流），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-d-tc-03 -b card-d-tc-03 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28799`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-d-tc-03。在 docs/parity/cards/D-TC-03.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **D021 Web 搜索**〔部分｜P0｜M〕缺：mode 不改变检索；当前仅 DDG，缺 cached/live/provider 能力控制及不支持模式的显式结果  抄：Codex `web_search` handler + [web search docs](https://learn.chatgpt.com/docs/web-search)；Claude WebSearch；ZCode `handlers/web-search.ts`；OpenCode `plugin/websearch.ts`  Atlas 位置：待定
- **D022 Web 抓取**〔部分｜P0｜S〕缺：缺重定向跳数/响应大小限制和 TTL 缓存  抄：Claude WebFetch；ZCode `handlers/web-fetch.ts`；OpenCode `plugin/webfetch.ts`  Atlas 位置：待定
- **D113 Codex Record & Replay**〔部分｜P1｜L〕缺：缺将一般桌面录制整理为可参数化并可调用的 skill lifecycle；现有仅 browser steps→skill  抄：[Record & Replay](https://learn.chatgpt.com/docs/extend/record-and-replay)  Atlas 位置：待定
- **D119 Node REPL / JavaScript 工具**〔没做｜P1｜L〕缺：缺有状态 JavaScript REPL callable；浏览器 API 行不等于 Node REPL  抄：ZCode `apps/zcode-cli/packages/core/src/tool/handlers/node-repl.ts`  Atlas 位置：待定
- **D123 事件流监视**〔没做｜P1｜M〕缺：缺对后台命令输出/异步事件/WebSocket 的订阅与增量回传工具  抄：Claude [tools reference](https://code.claude.com/docs/en/tools-reference)  Atlas 位置：待定

## 总账里这张卡的说明
### D-TC-03｜Web 检索、JS REPL、录制和事件流（5 条）

- **包含编号：** D021, D022, D113, D119, D123
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Codex `web_search` handler + [web search docs](https://learn.chatgpt.com/docs/web-search)；Claude WebSearch；ZCode `handlers/web-search.ts`；OpenCode `plugin/websearch.ts`
  - Claude WebFetch；ZCode `handlers/web-fetch.ts`；OpenCode `plugin/webfetch.ts`
  - [Record & Replay](https://learn.chatgpt.com/docs/extend/record-and-replay)
  - ZCode `apps/zcode-cli/packages/core/src/tool/handlers/node-repl.ts`
  - Claude [tools reference](https://code.claude.com/docs/en/tools-reference)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
