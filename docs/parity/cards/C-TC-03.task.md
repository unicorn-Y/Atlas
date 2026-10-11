你是施工者。任务：Atlas 功能对标任务卡 C-TC-03（Profile、历史导入与工作流），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-c-tc-03 -b card-c-tc-03 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28793`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-c-tc-03。在 docs/parity/cards/C-TC-03.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **C012 账号/Profile、登录/退出和本地配置档隔离**〔部分｜P1｜M〕缺：只展示本地 Profile，缺真实云账号登录/退出与配置档隔离服务。  抄：Codex [auth](https://learn.chatgpt.com/docs/auth); Claude [authentication](https://code.claude.com/docs/en/authentication); ZCode `CodingPlanStatusActions.tsx`  Atlas 位置：待定
- **C036 扫描其他 Agent 配置/会话、选择范围后导入**〔部分｜P1｜M〕缺：可移植配置包已做，外部 Agent 会话/配置按范围选择导入尚不完整。  抄：ZCode `settings/{MigrationSection,ExternalAgentImportDialog}.tsx`; Codex [import](https://learn.chatgpt.com/docs/import); Claude [MCP](https://code.claude.com/docs/en/mcp)  Atlas 位置：待定
- **C053 Claude Code / Codex 会话历史选择性导入**〔部分｜P1｜M〕缺：导入仅处理可见文本，工具/推理/子代理历史尚不能无损选择导入。  抄：Claude [env vars](https://code.claude.com/docs/en/env-vars); Codex [`rollout` recorder](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/recorder.rs), V5 §C 配置传输与附录 VI–IX；Atlas `core/atlas/runtime/external_import.py`, `core/atlas/api/external_history_router.py`  Atlas 位置：待定
- **C054 崩溃上报与遥测隐私开关**〔部分｜P1｜M〕缺：已有 Memos 遥测 opt-out，缺应用级崩溃上报和其它渠道统一隐私控制。  抄：V5 §C 诊断/Computer Use 行、VIII-A；Atlas `frontend/src/main/electron.ts`, `diagnostics_router.py`  Atlas 位置：待定
- **C066 可保存、复用并共享工作流**〔部分｜P1｜L〕缺：Recipe 只回填 prompt，缺可执行、可复用并分享的工作流定义。  抄：Goose [recipes](https://goose-docs.ai/docs/guides/recipes/); V5 §C 保存工作流行、Codex App 自动化行  Atlas 位置：待定
- **C071 SSH host / remote workspace 配置**〔部分｜P1｜L〕缺：已有 SSH workspace，缺独立 SSH host registry/远程工作区统一设置。  抄：V5 §C SSH 行；各家官方 Desktop/Remote Control docs  Atlas 位置：待定
- **C072 配套 CLI 安装**〔部分｜P1｜S〕缺：CLI 随 Python 包可用，缺桌面侧安装与 PATH/命令路径管理。  抄：V5 §C Install CLI 行；Atlas `core/atlas/cli.py`  Atlas 位置：待定

## 总账里这张卡的说明
### C-TC-03｜Profile、历史导入与工作流（7 条）

- **包含编号：** C012, C036, C053, C054, C066, C071, C072
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - Codex [auth](https://learn.chatgpt.com/docs/auth); Claude [authentication](https://code.claude.com/docs/en/authentication); ZCode `CodingPlanStatusActions.tsx`
  - ZCode `settings/{MigrationSection,ExternalAgentImportDialog}.tsx`; Codex [import](https://learn.chatgpt.com/docs/import); Claude [MCP](https://code.claude.com/docs/en/mcp)
  - Claude [env vars](https://code.claude.com/docs/en/env-vars); Codex [`rollout` recorder](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/recorder.rs), V5 §C 配置传输与附录 VI–IX；Atlas `core/atlas/runtime/external_import.py`, `core/atlas/api/external_history_router.py`
  - V5 §C 诊断/Computer Use 行、VIII-A；Atlas `frontend/src/main/electron.ts`, `diagnostics_router.py`
  - Goose [recipes](https://goose-docs.ai/docs/guides/recipes/); V5 §C 保存工作流行、Codex App 自动化行
  - V5 §C SSH 行；各家官方 Desktop/Remote Control docs
  - V5 §C Install CLI 行；Atlas `core/atlas/cli.py`
- **派工顺序：** Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
