# ATLAS-C4：扩展体系

> 先读 ROADMAP-TO-PRODUCT、CORE-PARITY（E 系列各行）、EXECUTION-GUIDE。前提：C3 验收通过。

## 本波目标

Atlas 的扩展机制直接兼容 Claude Code 的生态：Hooks、插件、技能、自定义命令、子 Agent 定义，网上现成的 Claude Code 插件拿来就能装。另外可以一键从 Claude Code、Codex 导入设置。
做完以后，CORE-PARITY 里 E2 到 E6 都是 ✔。

查 Claude Code 当前的官方文档：hooks、plugins、skills、slash commands、subagents 这几页。按**当月**的文档来，不要凭记忆。

## 1. Hooks 全套（E3）

- **对标**：Claude Code 的事件表：
  - `PreToolUse`、`PostToolUse`、`PostToolUseFailure`
  - `UserPromptSubmit`、`Notification`、`PermissionRequest`
  - `Stop`、`SubagentStart`、`SubagentStop`
  - `PreCompact`、`SessionStart`、`SessionEnd`
  
  以文档为准。输入输出也照它：
  - 输入：stdin 收到 JSON；
  - 输出：退出码 0 表示放行，退出码 2 表示拦截，stderr 的内容回给模型；
  - 也可以在 stdout 输出 JSON 做决定（`decision`、`reason`、改写工具输入、追加上下文等）；
  - `matcher` 按工具名匹配。
- **做法**：
  - 每个事件映射到 Hermes 的插件钩子（`hermes_cli/plugins.py` 的 `VALID_HOOKS`）。对得上的直接映射，例如 `pre_tool_call` → PreToolUse、`pre_verify` → Stop；Hermes 没有的，在 `core/atlas/engine/` 里补上触发点。
  - 配置来源有三处，都要读：`.claude/settings.json` 和 `~/.claude/settings.json` 里的 `hooks`（兼容）、Atlas 自己的 Hooks 设置、插件自带的 hooks。
  - Atlas 原有的 5 个事件（`run.started` 等）保留，作为别名映射过去。
- **前端**：设置 → Hooks 显示全部事件，可以试跑，能看到每次 Hook 运行的日志。
- **测试**：每个事件至少一个用例，覆盖拦截、改写输入、追加上下文；直接拿一份 Claude Code 格式的 settings.json 测兼容。

## 2. 插件，兼容 Claude Code 的格式（E4）

- **对标**：Claude Code 的插件（`.claude-plugin/plugin.json`，里面可以带 commands、agents、skills、hooks、MCP 服务器、mcpb 包）和插件市场（`marketplace.json`，可以从 git 地址添加）。
- **做法**：
  - Atlas 能从 git 地址或本地目录添加插件市场，列出插件，安装、启用、停用、卸载、更新。
  - 装好的插件里带的命令、子 Agent、技能、Hooks、MCP 都自动生效。
  - Hermes 自带的插件 SDK 也保留，两种插件并存。
  - 原 W11 第 4 节有设计可以参考（`tasks/taskbooks/ATLAS-W11-EFFICIENCY-SKILLS-CODING.md`）。
- **不做**：插件安装的安全扫描，那是用户自己做的事。
- **前端**：设置 → 插件，分三页：市场、已安装、更新。
- **测试**：用一个按 Claude Code 格式写的示例插件（带命令、子 Agent、技能、Hook、MCP），走一遍安装 → 生效 → 卸载。

## 3. 技能目录合一（E2）

- **现状**：Atlas 有自己的技能系统（`core/atlas/skills/`，SKILL.md 格式，带注册、目录联邦、版本和信任管理）；Hermes 也有技能工具（`tools/skills_tool.py` 等），C1 时关掉了。
- **做法**：以 Atlas 的技能系统为准，同时读取这些目录：`~/.atlas/skills`、项目里的 `.claude/skills`、`~/.claude/skills`、插件自带的技能。渐进加载：技能索引放进提示词的易变层，模型调用 `use_skill` 时才加载全文。Hermes 的技能工具不再启用；Hermes 自带的那批技能，作为一个可选的技能源导入。
- **测试**：多个来源有同名技能时，按优先级取用；索引稳定，不会破坏缓存。

## 4. 自定义命令（E5）

- **对标**：Claude Code 的 `.claude/commands/*.md`（支持 `$ARGUMENTS`、frontmatter 里的 `allowed-tools`、`model` 等）；Pi 的 prompt templates（`packages/coding-agent/docs/prompt-templates.md`）。
- **做法**：读取 `.claude/commands`、`~/.claude/commands`、`.atlas/commands`；这些命令出现在 `/` 菜单里。Atlas 原有的「配方」继续保留，配方也可以导出成命令。

## 5. 从 Claude Code 和 Codex 导入（E6）

- **来源**：Codex 的 `/import`，见 `codex-rs/external-agent-migration/src/`：`hooks_cla.rs`、`mcp.rs`、`memory.rs`、`config_values.rs` 等。
- **做法**：设置里加「从 Claude Code 导入」「从 Codex 导入」两个入口，导入这些内容：
  - MCP 服务器；
  - Hooks；
  - 规则文件和记忆文件（CLAUDE.md、AGENTS.md）；
  - 技能、子 Agent、自定义命令；
  - 模型偏好；
  - 最近的对话（只读导入，作为历史可以查看和搜索）。

  导入前列出清单让用户勾选；重复的跳过；导入后显示一份报告。
- **测试**：用假的 `~/.claude`、`~/.codex` 目录各导入一次，并且确认不会改动源目录。

## 6. 子 Agent 定义（核实）

W07 已经支持五家的定义文件（`.claude/agents` 等）。核实它在新内核和插件体系下照样能用，插件自带的子 Agent 也能被识别。

## 7. 测试和交付

- 每节各自的测试；端到端：装一个示例插件 → 它的命令、Hook、技能、MCP 在一次任务里全部生效。
- 结果文件里写：Claude Code 的事件和字段对照表；插件格式兼容了哪些、没兼容哪些、为什么。
- 更新 CORE-PARITY、PARITY（F177、F181 等）、VENDORED。

## 验收清单

1. 直接拿一份真实的 Claude Code 格式插件和 settings.json，不做任何修改就能用。
2. 事件对照表里每一项都有实现，或者写明了不做的理由。
3. 导入功能不会写源目录。
4. 已有功能不倒退。
