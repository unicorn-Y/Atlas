你是施工者。任务：Atlas 功能对标任务卡 C-TC-04（MCP、插件宿主、Hooks 与命令注册），一次做完。

背景：Atlas 是 Electron + React 前端、Python 后端的桌面 AI Agent。这张卡来自「剩余工作总账」（仓库 docs/parity/LEDGER.md），列的是对标 ZCode / OpenCode / Codex / Claude Code 后 Atlas 还缺或只做了一部分的功能。

规矩：
1. 建工作树，不要改 D:\Atlas（用户在用），不碰别的 D:\atlas-* 目录：
   git -C D:\Atlas fetch origin
   git -C D:\Atlas worktree add D:\atlas-card-c-tc-04 -b card-c-tc-04 origin/memory-v1
2. 每条先确认 Atlas 现在实际怎样（读代码，不要只信表格），再照上游做：ZCode（github.com/zai-org/ZCode，界面在 packages/ui、packages/desktop）和 OpenCode（github.com/anomalyco/opencode，packages/app、packages/core）开源就读源码移植，文件头写 `// Ported from owner/repo@<sha>: <path> (License)`；Codex / Claude Code 照官方文档行为做。THIRD_PARTY_NOTICES.md 只追加。
3. 缺后端接口或 Electron 主进程能力就自己补，放新文件优先；共享文件（App.tsx、store/useAtlasStore.ts、core/atlas/server.py、core/atlas/api/application.py、config/atlas.example.toml）只做追加式小改动。
4. 真做不了的条目写清原因，不许做假按钮、假数据。
5. 不写测试、不跑测试套件。只确认：后端能启动（cd core 后 `set ATLAS_UPSTREAM_AUTO=0` 再 `python -m uvicorn atlas.server:app --port 28794`，/api/health 返回 ok 后关掉）；`npm --prefix frontend run build` 通过。
6. 只读需要的文件和代码段，不要整份读大文件（省额度）。
7. 完成后 git add -A、git commit、git push origin card-c-tc-04。在 docs/parity/cards/C-TC-04.md 写结果：每条编号做了什么 / 没做的原因，以及提交号。不要推 memory-v1。

## 本卡条目

- **C016 MCP OAuth、headers/scopes、重新认证/重连和连接诊断**〔部分｜P0｜L〕缺：可管理 MCP 连接/重启，但 OAuth/PKCE、续签和 scopes 尚缺运行时支持。  抄：ZCode `McpFailurePresentation.tsx`; OpenCode `servers/connect/`; Claude [MCP](https://code.claude.com/docs/en/mcp), [managed MCP](https://code.claude.com/docs/en/managed-mcp); Codex [MCP](https://learn.chatgpt.com/docs/extend/mcp)  Atlas 位置：待定
- **C017 MCP 项目/用户/Agent 作用域、启停与工具允许规则**〔部分｜P1｜M〕缺：已有部分 MCP 作用域 UI，缺完整 Agent scope 与每工具允许规则链路。  抄：OpenCode `settings/providers/extensions.tsx`; Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference); Claude [MCP](https://code.claude.com/docs/en/mcp); ZCode `McpSettingsSection.tsx`  Atlas 位置：待定
- **C019 Marketplace source 管理、来源校验、插件配置和诊断**〔部分｜P1｜M〕缺：缺 Marketplace source CRUD、来源验证及可诊断的插件配置流程。  抄：ZCode `PluginStoreSourcesDialog.tsx`, `AddMarketplaceSourceDialog.tsx`, `PluginConfigControls.tsx`; Claude [plugin marketplaces](https://code.claude.com/docs/en/plugins/marketplaces); Codex [plugin management](https://learn.chatgpt.com/docs/enterprise/plugin-management)  Atlas 位置：待定
- **C020 User/Workspace/Project 扩展作用域、覆盖和恢复默认**〔部分｜P1｜M〕缺：缺 User/Workspace/Project 扩展覆盖 API 和恢复默认闭环。  抄：ZCode `PluginsSection.tsx`; OpenCode `settings/providers/extensions.tsx`; Codex [plugins](https://learn.chatgpt.com/docs/plugins); Claude [settings](https://code.claude.com/docs/en/settings)  Atlas 位置：待定
- **C022 扩展注册表将 GUI 设置页、菜单、palette 命令、slash 命令和快捷键统一注册**〔部分｜P1｜L〕缺：只有只读扩展目录 metadata，缺插件菜单/设置页/slash/keybind 动态贡献 runtime。  抄：OpenCode `runtime/extension/{settings-pages,menubar-items,commands,host-apis}.ts*`; ZCode `plugin-ui/CONTRACT.md`, `plugin-ui/app/`; Codex [plugins](https://learn.chatgpt.com/docs/plugins)  Atlas 位置：待定
- **C023 插件交互 UI、小组件状态、服务调用和确认后 follow-up**〔没做｜P1｜L〕缺：缺插件交互式 UI host、小组件状态、服务调用和确认后 follow-up。  抄：`packages/ui/src/plugin-ui/CONTRACT.md`, `pluginUiAppTools.ts`, `pluginUiHostAppHandlers.ts`, `pluginUiPageManager.ts`  Atlas 位置：待定
- **C027 Hook 生命周期事件、command/prompt/agent/HTTP/MCP hook 管理与测试**〔部分｜P1｜M〕缺：已有 Hook CRUD/测试，缺 HTTP/MCP hook schema 和通用导入格式。  抄：ZCode `settings/{HooksSection,HookForm,HooksList}.tsx`; Codex [hooks](https://learn.chatgpt.com/docs/hooks); Claude [Hooks guide](https://code.claude.com/docs/en/hooks-guide), [reference](https://code.claude.com/docs/en/hooks); OpenCode `runtime/extension/`  Atlas 位置：待定
- **C028 Workspace Hook trust/review、失败关闭与策略来源**〔没做｜P1｜M〕缺：缺逐 Hook 工作区信任审查及失败关闭策略来源。  抄：ZCode `WorkspaceHookTrustNotice.tsx`, `workspaceHookReviewCommands.ts`; Claude [Hooks](https://code.claude.com/docs/en/hooks); Codex [hooks](https://learn.chatgpt.com/docs/hooks)  Atlas 位置：待定
- **C031 命令面板与统一命令注册（palette、slash、keybind 共用）**〔部分｜P0｜L〕缺：已有命令面板和自定义命令，但 palette/slash/keybind 尚未统一共享注册表。  抄：ZCode `packages/ui/src/command-center/CommandCenterDialog.tsx`; OpenCode `packages/app/src/shell/commands/{command,palette}.tsx`; Codex [commands](https://learn.chatgpt.com/docs/reference/commands)  Atlas 位置：待定
- **C068 Computer Use 授权和插件开关**〔部分｜P0｜M〕缺：有本地 Computer Use/节点审批，缺统一的 Computer Use 插件启停与授权设置。  抄：V5 §C Computer Use 行及附录 VI/IX  Atlas 位置：待定

## 总账里这张卡的说明
### C-TC-04｜MCP、插件宿主、Hooks 与命令注册（10 条）

- **包含编号：** C016, C017, C019, C020, C022, C023, C027, C028, C031, C068
- **Atlas 拟修改文件/目录：** **待定**
- **要读的上游文件/文档：**
  - ZCode `McpFailurePresentation.tsx`; OpenCode `servers/connect/`; Claude [MCP](https://code.claude.com/docs/en/mcp), [managed MCP](https://code.claude.com/docs/en/managed-mcp); Codex [MCP](https://learn.chatgpt.com/docs/extend/mcp)
  - OpenCode `settings/providers/extensions.tsx`; Codex [config reference](https://learn.chatgpt.com/docs/config-file/config-reference); Claude [MCP](https://code.claude.com/docs/en/mcp); ZCode `McpSettingsSection.tsx`
  - ZCode `PluginStoreSourcesDialog.tsx`, `AddMarketplaceSourceDialog.tsx`, `PluginConfigControls.tsx`; Claude [plugin marketplaces](https://code.claude.com/docs/en/plugins/marketplaces); Codex [plugin management](https://learn.chatgpt.com/docs/enterprise/plugin-management)
  - ZCode `PluginsSection.tsx`; OpenCode `settings/providers/extensions.tsx`; Codex [plugins](https://learn.chatgpt.com/docs/plugins); Claude [settings](https://code.claude.com/docs/en/settings)
  - OpenCode `runtime/extension/{settings-pages,menubar-items,commands,host-apis}.ts*`; ZCode `plugin-ui/CONTRACT.md`, `plugin-ui/app/`; Codex [plugins](https://learn.chatgpt.com/docs/plugins)
  - `packages/ui/src/plugin-ui/CONTRACT.md`, `pluginUiAppTools.ts`, `pluginUiHostAppHandlers.ts`, `pluginUiPageManager.ts`
  - ZCode `settings/{HooksSection,HookForm,HooksList}.tsx`; Codex [hooks](https://learn.chatgpt.com/docs/hooks); Claude [Hooks guide](https://code.claude.com/docs/en/hooks-guide), [reference](https://code.claude.com/docs/en/hooks); OpenCode `runtime/extension/`
  - ZCode `WorkspaceHookTrustNotice.tsx`, `workspaceHookReviewCommands.ts`; Claude [Hooks](https://code.claude.com/docs/en/hooks); Codex [hooks](https://learn.chatgpt.com/docs/hooks)
  - ZCode `packages/ui/src/command-center/CommandCenterDialog.tsx`; OpenCode `packages/app/src/shell/commands/{command,palette}.tsx`; Codex [commands](https://learn.chatgpt.com/docs/reference/commands)
  - V5 §C Computer Use 行及附录 VI/IX
- **派工顺序：** P0 优先，完成后接 P1；Hermes 只接本卡中 S 条目，M/L 交 Codex；涉及新 API、权限/持久化时以 Codex 为主。
