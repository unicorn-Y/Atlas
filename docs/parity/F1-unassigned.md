# FEATURE-F1 未分配发现（D 区清单的非工具项）

> 只追加。以下是 D 区枚举开源 UI、菜单、命令、快捷键、设置与 i18n 时发现、但属于其他区域或非 model-callable runtime 的内容；由 A/B/C 区按各自文件归属判断。

## 2026-10-11：ZCode UI / 非 D callable

- **B：tool-call 专用卡片与审批交互。** `zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f`：`packages/ui/src/PermissionDialog.tsx`, `lib/permissionRequest.ts`; `packages/ui/src/ToolCallBlocks.tsx`, `ToolCallBlocks/{resolveRenderer,ToolLayout,ToolSummaryRow}.tsx`, `renderers/{read,edit,execute,search,cua,mcp}.tsx`。审批包含 tool-specific preview、Bash allow-prefix、allow/deny/persistent scope、拒绝反馈、键盘导航和数字快捷选择；卡片按文件/shell/search/CUA/MCP 显示摘要、状态、失败详情与复制错误。
- **C：MCP/ComputerUse/Browser 设置与授权入门。** `packages/ui/src/settings/{McpSettingsSection,McpServerList,McpServerForm,ComputerUseSection,BrowserSettingsSection}.tsx`；配置 MCP user/workspace scope、enablement、状态、OAuth；ComputerUse 插件及 macOS accessibility/screen recording onboarding；Browser Use plugin enablement。
- **C：快捷键编辑、工具分组设置和本地化。** `SettingsPage.tsx`, `settings/{ShortcutSettingsSection,ShortcutBindingRow}.tsx`, `packages/shared/src/shortcutCommands.ts`, `packages/ui/src/i18n/locales/{en-US,zh-CN}.ts`。命令中心 `CmdOrCtrl+K` / `CmdOrCtrl+Shift+P`，终端 `CmdOrCtrl+J`；工具摘要/审批/MCP/CUA 的中英文案分别在 locale key groups 中。
- **B/C：命令面板。** `packages/ui/src/quickpick/quickPickCommands.ts`、`command-center/CommandCenterDialog.tsx`；可打开 MCP/Skills 设置、切换终端/浏览器面板，不直接运行 model-callable 工具。
- **B/C：ZCode CUA 专属授权窗口与插件工具 UI。** `packages/desktop/src/renderer/cua-permission-panel.html`, `cuaPermissionPanel.ts`, `cuaPermissionPanelMessages.ts`; `packages/ui/src/plugin-ui/PluginUiToolCallBlock.tsx`, `UI_PLUGIN.md`, `packages/ui/src/plugin-ui/CONTRACT.md`。插件 UI 可认领 tool-call row；MCP 渲染作为 fallback，page tools 仍走宿主审批。

## 2026-10-11：OpenCode UI / 非 D callable

- **B：工具卡片与会话审批 dock。** `anomalyco/opencode@7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937`：`packages/session-ui/src/tools/tool-renderer.tsx`, `components/basic-tool.tsx`, `components/tool-error-card.tsx`; `packages/app/src/session/requests/session-permission-dock.tsx`。通用 tool card 含 specialized titles/icons/status；审批支持 allow once / allow always / deny。
- **C：MCP/扩展/项目设置。** `packages/app/src/providers/connect/mcp-dialog.tsx`, `settings/providers/extensions.tsx`, `settings/workspaces/project-extensions.tsx`。Web/desktop 有 Auto-approve 全局开关和 MCP/plugin/skill/LSP 配置；未发现 per-tool permission policy editor。
- **B/C：命令面板、slash/MCP 命令与快捷键。** `packages/app/src/shell/commands/{command,palette,dialog}.tsx`, `packages/app/src/session/commands/use-session-commands.tsx`, `packages/app/src/settings/keybinds/keybinds.tsx`; default palette `mod+k` / `mod+shift+p`, Auto-approve toggle `mod+shift+a`, MCP toggle `mod+;`, `/mcp`；TUI `packages/tui/src/component/command-palette.tsx`, `config/keybind.ts`, `component/dialog-mcp.tsx`。
- **C：工具/权限本地化。** `packages/app/src/runtime/i18n/{en,zh,zht}.ts` 与 `packages/ui/src/i18n/{en,zh}.ts`；权限和通用 tool card 的 `settings.permissions.tool.*`, `ui.tool.*`, `ui.permission.*` keys。
- **B：Browser Review pane / 本地文件预览。** Browser tab open/focus 使用 Review pane；`preview` 将 server-local file 放入 pane，截图返回 image+local path，snapshot element refs 会过期。实现与呈现源在 `packages/plugin-browser/src/{rpc,tools}.ts`；D 仅负责后端操作。

## 2026-10-11：Codex 与 Claude 官方文档中的 UI/runtime 配置边界

- **B/C：Codex desktop Browser、Chrome tab context、Computer Use、Appshots、图像附件。** [browser](https://learn.chatgpt.com/docs/browser)、[Chrome extension](https://learn.chatgpt.com/docs/chrome-extension)、[computer use](https://learn.chatgpt.com/docs/computer-use)、[Appshots](https://learn.chatgpt.com/docs/appshots)、[image inputs](https://learn.chatgpt.com/docs/image-inputs)。这些是桌面上下文采集/集成能力，不是 CLI 固定 handlers。
- **C/runtime：Codex permissions/sandbox/hooks/skills/plugin manifests/config/worktrees。** [permissions](https://learn.chatgpt.com/docs/permissions)、[sandboxing](https://learn.chatgpt.com/docs/sandboxing)、[hooks](https://learn.chatgpt.com/docs/hooks)、[plugins](https://learn.chatgpt.com/docs/plugins)、[skills](https://learn.chatgpt.com/docs/build-skills)、[worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)。它们控制 callable tools 的可用性与扩展，不等于独立用户调用 handler。
- **B/C：Claude slash commands/settings/hooks/checkpoint UI/MCP prompts.** [commands](https://code.claude.com/docs/en/commands)、[settings](https://code.claude.com/docs/en/settings)、[hooks](https://code.claude.com/docs/en/hooks)、[checkpointing](https://code.claude.com/docs/en/checkpointing)、[MCP](https://code.claude.com/docs/en/mcp)。`/rewind` 是快照 UI，MCP prompts 通过 slash command 运行；两者不是新增 model-callable handlers。
