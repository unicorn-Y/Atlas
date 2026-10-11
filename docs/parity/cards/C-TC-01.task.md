你是施工者。任务：Atlas 功能对标任务卡 C-TC-01（设置来源、权限与 Worktree 策略），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-c-tc-01 -b card-c-tc-01 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28791`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-c-tc-01。在 docs/parity/cards/C-TC-01.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **C002 可搜索并直达具体设置项**〔部分｜P1｜M〕缺：只有设置组级搜索，缺每个具体表单字段的全文索引与直达。  抄：OpenCode `packages/app/src/settings/search-catalog.ts`; Codex [Settings](https://learn.chatgpt.com/docs/reference/settings)  Atlas 位置：待定
- **C003 配置作用域、优先级和管理员策略**〔部分｜P1｜M〕缺：已显示部分设置来源，缺完整来源优先级及管理员只读策略的解析。  抄：ZCode `packages/shared/src/protocol.ts` (`AppSettings`); OpenCode `packages/app/src/settings/`; Claude [settings](https://code.claude.com/docs/en/settings), [managed settings](https://code.claude.com/docs/en/managed-settings), [server managed settings](https://code.claude.com/docs/en/server-managed-settings); Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference)  Atlas 位置：待定
- **C006 配置来源检查、变化诊断和设置状态**〔部分｜P1｜M〕缺：只提供本地诊断汇总，缺所有设置有效来源与覆盖优先级解释。  抄：Claude [debug your config](https://code.claude.com/docs/en/debug-your-config); Codex [troubleshooting](https://learn.chatgpt.com/docs/reference/troubleshooting), [config reference](https://learn.chatgpt.com/docs/config-file/config-reference)  Atlas 位置：待定
- **C048 会话权限模式、Docker 沙箱和网络开关**〔部分｜P0｜L〕缺：会话权限和 Docker 网络已接，缺执行器支持的细粒度允许/拒绝规则。  抄：V5 §C 计划/审查与自动接受行；Claude [permissions](https://code.claude.com/docs/en/permissions)；Atlas `core/atlas/api/conversations_router.py`, `run_drive.py`  Atlas 位置：待定
- **C064 单独的自动接受/权限规则编辑**〔部分｜P1｜M〕缺：只有会话模式/Docker 规则，缺细粒度工具 auto-approve allow/deny 编辑器。  抄：V5 §C 计划/审查权限、自动接受行；Claude [permissions](https://code.claude.com/docs/en/permissions)  Atlas 位置：待定
- **C069 文件搜索忽略规则（`.zcodeignore`）**〔没做｜P1｜M〕缺：缺由实际文件搜索器读取的 .zcodeignore 忽略规则。  抄：V5 §C 工作区搜索规则行；ZCode `settings` 文案（U）  Atlas 位置：待定
- **C070 Worktree 策略与清理**〔部分｜P1｜S〕缺：有 Code 工作树界面，缺 Worktree strategy、保留和自动清理策略。  抄：V5 §C Worktree 行；OpenCode V2 SDK/Plugin source  Atlas 位置：待定
- **C073 自定义 LSP server 配置**〔部分｜P1｜M〕缺：缺可被运行时消费的自定义 LSP server 配置 UI/API  抄：V5 §C 扩展 LSP / Web search / Experimental 行；Atlas `LspStatusSection.tsx`, `workspace_router.py`  Atlas 位置：待定
- **C076 自动归档期限（3/7/14/30天）**〔没做｜P1｜S〕缺：缺自动归档保留策略、定时执行和设置入口  抄：V5 §C 本机运行设置行；Claude [monitoring usage](https://code.claude.com/docs/en/monitoring-usage)  Atlas 位置：待定

## 总账里这张卡的说明
### C-TC-01｜设置来源、权限与 Worktree 策略（9 条）

- **包含编号：** C002, C003, C006, C048, C064, C069, C070, C073, C076
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - OpenCode `packages/app/src/settings/search-catalog.ts`; Codex [Settings](https://learn.chatgpt.com/docs/reference/settings)
  - ZCode `packages/shared/src/protocol.ts` (`AppSettings`); OpenCode `packages/app/src/settings/`; Claude [settings](https://code.claude.com/docs/en/settings), [managed settings](https://code.claude.com/docs/en/managed-settings), [server managed settings](https://code.claude.com/docs/en/server-managed-settings); Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference)
  - Claude [debug your config](https://code.claude.com/docs/en/debug-your-config); Codex [troubleshooting](https://learn.chatgpt.com/docs/reference/troubleshooting), [config reference](https://learn.chatgpt.com/docs/config-file/config-reference)
  - V5 §C 计划/审查与自动接受行；Claude [permissions](https://code.claude.com/docs/en/permissions)；Atlas `core/atlas/api/conversations_router.py`, `run_drive.py`
  - V5 §C 计划/审查权限、自动接受行；Claude [permissions](https://code.claude.com/docs/en/permissions)
  - V5 §C 工作区搜索规则行；ZCode `settings` 文案（U）
  - V5 §C Worktree 行；OpenCode V2 SDK/Plugin source
  - V5 §C 扩展 LSP / Web search / Experimental 行；Atlas `LspStatusSection.tsx`, `workspace_router.py`
  - V5 §C 本机运行设置行；Claude [monitoring usage](https://code.claude.com/docs/en/monitoring-usage)
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
