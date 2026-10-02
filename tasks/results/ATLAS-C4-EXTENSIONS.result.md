# ATLAS-C4-EXTENSIONS 结果

- 执行：主线（main）。原主控 Codex（GPT-6.1 Sol + Luna workers）中途配额耗尽；**ZCode 接手补完**。Codex 遗留的工作区 WIP（未提交）经评估后作为基线提交 `bf0184d`（hooks/plugins/skills 解析层 + commands 库层 + server 端点，约占全量 60%），其余由 ZCode 派 5 个并行 worker（A hooks 闭环 / B E2+E5 接线 / C E6 导入 / D 前端 / E 插件补强）+ 主代理集成完成。
- 日期：2026-10-02

## 一、E2–E6 完成情况

### E2 技能目录合一 ✔
- `core/atlas/skills/__init__.py`：单一 SkillManager 即唯一目录/索引层。来源装配 `default_skill_sources(workspace, atlas_home, plugin_skills, hermes_skills_dir, user_home)`，优先级 `atlas=10 → hermes=15（仅 extensions.hermes_skills 配置开启）→ claude-user ~/.claude/skills=20 → claude-project <ws>/.claude/skills=30 → plugin:<p>:<s>=60`，同名稳定取胜。
- 布局：`SkillSource.layout` 支持 `category`（内建仓库 `<类>/<名>/SKILL.md`）、`flat`（Claude 目录两层）、`single`（插件整目录）。修复了 WIP 引入的"任意深度 rglob 导致内建技能多计"回归（test_skills.py 15≠11）。
- 渐进加载保持：扫描只存 frontmatter 索引，`activate()` 时才读 SKILL.md 正文。
- 插件 skills 经 `replace_skill_sources("plugin:", …)` 整族原子换血进同一 manager，无第二套 registry。

### E3 Hooks 兼容 Claude Code ✔
- 解析：`~/.claude/settings.json`、项目 `.claude/settings.json`、`.claude/settings.local.json`（只读）+ 插件 hooks.json / manifest hooks 字段，全部进同一 `HookStore` 执行路径；matcher（精确/列表/正则）、stdin JSON、stdout JSON 决策、exit code 语义、`${CLAUDE_PROJECT_DIR}` 替换。
- 执行闭环（本波补完）：PreToolUse `updatedInput` 真正改写工具入参（与 AIMessage 中 tool_call args 同步）；`additionalContext` 追加到工具结果/本轮用户消息；UserPromptSubmit 可阻断该轮（denyReason 以助手消息返回，不触模型）或注入上下文；PermissionRequest deny 跳过审批；PreCompact 阻断手动压缩；PostToolUseFailure / SubagentStart / SubagentStop / Notification 均有触发点。
- 33 个 Claude 事件声明保留；旧 Atlas 5 事件（tool.before/after、run.*）行为原样兼容。
- 前端 HooksPanel：事件列表（来源标注 Claude 用户/项目/本地/插件）、逐条启停（override）、试跑、最近运行记录（退出码/耗时/输出摘要）。

### E4 插件兼容 Claude Code ✔
- `core/atlas/plugins/runtime.py`：兼容 `.claude-plugin/plugin.json`（及旧 plugin.json）、hooks.json、`.mcp.json`（含 `${CLAUDE_PLUGIN_ROOT}` 展开）、marketplace.json（github/url/git-subdir source）。
- 来源：本地目录 / git（https/ssh/owner-repo 简写 + ref）/ marketplace 安装；安装、启用、停用、卸载、更新、更新检查（`check_updates`：git fetch 比对 upstream，本地目录源跳过）。
- 同一 registry：Hermes 旧格式（plugin.json + hooks.json→HookBus）与 Claude 格式（→HookStore）同层，单一 state.json、单一 PluginRuntime。
- 五类贡献进 Atlas 同一发现层：skills→SkillManager 源、commands→`/api/commands`、agents→`load_types(plugin_agent_dirs=…)`、hooks→HookStore、MCP→`load_all(mcp_client=…)` 注册 `MCPServerConfig`。
- 本波修的实质缺陷：skills 组件路径去重（重名注册曾导致整个插件加载失败）、marketplace 源记录按目录名/manifest 名双键查找、坏目录名只跳过不拖垮全站、Windows 下 `.git` 只读对象导致卸载必挂（安装副本排除 `.git` + 强删兜底）、`_refresh_extension_sources` 缺定义（装/卸插件端点会 NameError）。

### E5 自定义命令 ✔
- `core/atlas/runtime/commands.py`：Markdown 命令发现/渲染。frontmatter 支持 `description`、`argument-hint`、`arguments`（命名参数）、`allowed-tools`/`disallowed-tools`、`model`、`mode`（act/plan）、`disable-model-invocation`/`user-invocable`；占位符 `$ARGUMENTS`、`$1..$n`（官方语义，`$0` 保留为 `$1` 别名）、命名参数 `$name`。
- 来源优先级（高胜同名）：atlas 用户 commands(50) → claude-user(40) → claude-project(30) → agents-project(20) → plugin(60，命名空间 `plugin:<名>:<命令>`) → recipe(5)。单文件 frontmatter 损坏只跳过该文件不拖垮列表。
- Recipe 保留并映射为 `recipe:<名>` 命令，渲染走 C3 既有 recipe 渲染器。
- 端点 `GET /api/commands`、`POST /api/commands/render`；前端 `/` 菜单合并自定义命令（按来源分组标注），选择后按 argument_hint 走参数补全，render 后进既有发送链路。

### E6 从 Claude Code / Codex 导入 ✔
- `core/atlas/runtime/external_import.py`：`scan_external(source)` 先扫描出清单（kind：mcp/hooks/rules/skills/agents/commands/model_prefs/history），`import_external(source, items)` 按勾选导入。冲突默认跳过（conflict=True），去重按内容哈希，源目录零写入（测试断言前后树哈希一致）。
- 落点全部是 Atlas 现有格式：MCP→`[tools.servers]`（写入后 tomllib 回读校验）、hooks→HookStore（仅映射 Atlas 侧有触发点的 5 事件）、规则→workspace `AGENTS.md` 段落级合并（绝不覆盖）、skills/commands/agents→Atlas 用户目录、模型偏好→user-settings `selected_model`；history 只列出不导入。
- 前端 ImportPanel：两个入口（Claude Code / Codex）→ 扫描清单勾选 → 导入 → 中文报告；放「插件与扩展」面板，未动 SettingsPage。

### 附：子 Agent 定义兼容核实 ✔
C3 child runtime 未复制。项目/用户 Claude agent 定义由既有路径识别；插件自带 agents 经 `enabled_contributions().agents` → `load_types(plugin_agent_dirs=…)` 进同一发现层（`definitions.py` 本波补了插件命名空间写回 `name` 字段）。

## 二、官方格式兼容表（施工时核对当月文档/上游实现的最终兼容字段）

| 格式 | 兼容内容 |
| --- | --- |
| Claude hooks | settings.json `hooks.<Event>[]`（matcher 多值/正则、`hooks[].type=command`、`command`+`args`、`timeout`、`if`）；stdin JSON（`hook_event_name/cwd/tool_input/session_id/…`）；stdout JSON（`continue/stopReason/hookSpecificOutput.permissionDecision(allow|deny|ask)/updatedInput/additionalContext`）；exit 2 阻断；纯 stdout → additionalContext |
| Claude plugin | `.claude-plugin/plugin.json`（name/version/description/commands/agents/skills/hooks/mcpServers 声明）；组件默认目录约定；`${CLAUDE_PLUGIN_ROOT}` |
| Claude marketplace | `marketplace.json`（name/owner/plugins[]，source ∈ github/git/url/relative） |
| Agent Skills | `SKILL.md` frontmatter（name/description）+ 渐进加载 |
| Claude commands | `.claude/commands/**/*.md`、frontmatter `description/argument-hint/arguments/allowed-tools/disallowed-tools/model/mode/disable-model-invocation/user-invocable`、`$ARGUMENTS`/`$1..$n` |
| Codex | `~/.codex/config.toml [mcp_servers]`、`AGENTS.md`、`prompts/*.md`、`sessions`/`history.jsonl`（只读）、`agents/*.toml`（Atlas 运行时已直读，导入跳过防重复） |

## 三、复用来源

- 本波为 Atlas 原生适配实现（对照 Claude Code 当月公开格式与 Codex external-agent migration 的"扫描→清单→选择→导入→报告"模式），未整文件搬任何上游仓库代码，故 `docs/plan/VENDORED.md` 本波无新增条目。
- 复用 Atlas 既有层：Hermes HookBus/插件 SDK 注册路径、C3 slash command/recipe 渲染链、`mcp_client.MCPServerConfig`、`atlas.config` 读写。

## 四、测试结果

聚焦套件（每 worker 各自验证 + 集成后复跑）：

| 套件 | 结果 |
| --- | --- |
| test_c4_hooks.py（新增 14：工具类阻断/改写/上下文、提示词类、生命周期类、权限类，真子进程 hook） | ✅ |
| test_c4_wiring.py（新增 9：source 优先级/Hermes 可选源/插件族换血/commands API/Recipe 渲染/插件 agent 发现层/import 503/404 修复） | ✅ |
| test_c4_external_import.py（新增 10：fake .claude/.codex 扫描/导入/源零写入/去重/AGENTS.md 合并/history 永不落盘） | ✅ |
| test_plugins.py（修复回归 + 新增 git 更新检查、Claude 插件五类贡献全链路） | 6 passed |
| test_c4_skills_commands.py（修复 YAML 断言 + 新增 $1 语义与坏文件容错） | 4 passed |
| test_c4_plugin_e2e.py（新增，见下） | ✅ |
| **C4 六文件合并** | **86 passed** |
| 相邻回归（agent/server/skills 系/c1 tool 系/parity wave3/5 等 13 文件） | **266 passed** |
| **后端全量 pytest（一次，整合完成后）** | 见文末汇总行 |
| 前端四项（renderer tsc / electron tsc / vitest 42 / vite build） | 全绿（最终前端代码上） |

**fake-model E2E（taskbook 最后一条硬验收）** `test_c4_plugin_e2e.py`：Claude 格式插件（command+agent+skill+hook+MCP 五类）→ `install_local` → `load_all` → hook 腿经 `HookStore(plugin_hooks=…)` 进入 `AgentOrchestrator` 真实工具执行链（`run()` 同一消费点）并阻断工具调用；skill 腿进共享 SkillManager 并 activate 出正文；command 腿经共享发现层列出 `plugin:audit:check` 并渲染；MCP 腿经 `load_all` 注册真实 `MCPServerConfig`（连接桩记录，不起真服务）。

## 五、与 ZCode C5 的 merge touchpoints

- 本波**未碰** `core/atlas/models/**`、`SettingsPage.tsx`、`UsagePanel.tsx`、backend-adapter 模型字段、provider/credential/reasoning/usage 逻辑。
- 唯一相邻点：`backend-adapter/src/{types,client}.ts` 与 `App.tsx`、`useAtlasStore.ts`（C4 面板/菜单接线）。若 C5 也改这些共享文件，合并时按 hunk 人工核对即可，无语义冲突预期。
- `external_import.py` 的 model_prefs 写 `selected_model`（现有键），C5 合并后自然读取，无需改动。

## 六、真实剩余缺口

1. permissionDecision/behavior `"ask"` 按阻断处理（提示"Hook 要求人工确认"）；接 Atlas 审批卡片留待后续。
2. PreCompact 手动压缩路径拿不到插件 hooks 来源（engine 内构造独立 HookStore）；Hermes fork 内的自动压缩无 Atlas 侧落点，未接。
3. SubagentStop 的 exit-2 "让子代理继续"语义未实现（仅触发）；SessionEnd 事件无会话级落点未接（run 结束已有 Stop/StopFailure）。
4. `render` 返回的 `model/tool_allow/tool_deny` 未接入发送链路（`run.start` 暂不支持按次限制），现只消费 `prompt/mode`。
5. mcpb 打包格式、Pi 式 TypeScript 扩展点未实现（Pi 思路仅保留设计层面）。
6. hooks 最近日志为内存环形缓冲，重启丢失（持久化属增量优化）。
7. `check_updates` 暂无独立 HTTP 端点（`POST /api/plugins/{name}/update` 已可用）。
8. 全量后端 pytest 中与 C4 无关的既有失败/跳过项不在本波范围（见汇总行）。

## 七、汇总行

- 后端全量：1 failed, 1071 passed, 9 skipped（18m33s）。唯一失败 `test_backend_parity_wave2.py::test_goal_replace_pause_resume` 为 main 存量漂移：C3R 提交 138decb 把 `ScheduledTask.goal` 改名 `legacy_goal` 后该测试未跟上，与本波改动无关（本波 diff 未触 scheduler/该测试）。
- 前端四项：renderer tsc ✅ / electron tsc ✅ / vitest 9 文件 42 用例 ✅ / vite build ✅
