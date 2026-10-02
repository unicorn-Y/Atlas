# Source Freeze — 2026-10-03(ATLAS-MEGA-LATEST-DAILY-READY)

> 本文是 Mega 任务开工时的最新来源冻结。原则:最新情报 + 当前最强实现,不是盲目追版本号。
> 分项研究文件:01-hermes.md、02-claude-code.md、03-codex.md、04-opencode-pi.md、05-browseruse-stagehand.md、06-skills-hubs.md、07-ecosystem-others.md。
> 能力决策只允许三档:KEEP(Atlas 已相当或更强)/ UPGRADE(搬当前更强实现)/ REPLACE(删旧换新)。

## 已核实的精确版本(本机 git 直接核实)

| 来源 | 当前 HEAD / 版本 | 日期 | 备注 |
| --- | --- | --- | --- |
| NousResearch/hermes-agent main | `a6e75acb0dc68c99d33fe8ba421a186b6b781b7c` | 2026-10-02 17:44 -0400 | "Merge pull request #131697 … uninstall dry-run" |
| unicorn-Y/hermes-agent atlas(同步前) | `e287231d7906bcce5bc373d20fb2e3e1e6427220` | 2026-10-02 13:15 +0800 | Atlas context handoff |
| merge-base | `aea969677c60a1bb72fe227fdfb98f196a2092cc` | 2026-10-01 | fork 落后 518 提交、领先 8 提交 |
| unicorn-Y/Atlas main(开工时) | `baa03a5` | 2026-10-03 | docs(tasks): advance main from C6 to X2 |
| Atlas 依赖 pin(同步前) | hermes-agent @ `e287231d` | — | core/pyproject.toml:47 |

## Hermes upstream 518 提交能力分布(按提交主题粗分)

browser 13 / desktop 111 / models 73 / gateway 49 / files+terminal 49 / tests+docs 54 / cron 26 / delegation 16 / context 7 / skills 1 / mcp 0 / computer 0 / 其余 119。
合并冲突面:仅 `tools/file_operations.py`(已语义化解决:保留 Atlas 4 元组 `_probe_write_target` + 重放 upstream JSON 常量拒绝)。

## ZCode 当前可观察 UX(本机观察,2026-10-03)

- 权限五档(ask/ask-writes/auto-file/plan/full),Shift+Tab 循环;Plan mode 用 ExitPlanMode 交计划。
- 子代理:后台运行、并发上限动态、槽位释放后继续派发;Agent 完成才回传最终消息。
- 技能以 Skill 工具注入(可用技能清单由 system-reminder 提供);`/command` 触发。
- 斜杠命令、计划模式、AskUserQuestion(带 preview 的选项对比)、TodoWrite 工作表、后台任务通知。
- 每轮可注入 hook 上下文(UserPromptSubmit/SessionStart);工作流(Workflow)为显式用户选择。

## 各外部来源冻结结论

(由分项研究文件汇总;完成后填入决策表。)

| 来源 | 版本/日期 | 决策要点 |
| --- | --- | --- |
| Claude Code | npm **2.1.288**(10-02)/stable 2.1.285(09-29) | 关键变化:Claude Mods(插件改 harness 行为,2.1.287)、Auto mode 权限分类器默认全量(2.1.278+)、AGENTS.md 支持(2.1.277)、子代理输出注入防护框架(2.1.277)、Pre/PostModelSwitch hooks(2.1.251)、plugin eval/configure(2.1.269/285)、/skill-doctor(2.1.261)、MCP alwaysLoad:false 延迟加载(2.1.287)、/cost 缓存未命中原因诊断(2.1.251,Atlas C5 已有同类)、每模型 /autocompact 窗口(2.1.288)、send-now 后台化运行中工具(2.1.281)。Atlas 对照:大多数已有等价;可借鉴=Mod 式深度扩展点(记录不阻塞)、per-model autocompact 窗口(X 域 UPGRADE 候选) |
| OpenAI Codex | rust-v**0.160.0**(10-01;基线 0.154.0) | 关键变化:instant_interrupt 中断转向(0.159,Atlas 已有 redirect 等价)、Guardian 自动审批审查(0.157,用户不做安全审查→记录不搬)、/agents 指挥中心+子代理一等公民(0.157,Atlas 已有)、Plan mode 掩码协作模式(0.158)、exec-server bearer WS+网络策略(0.156)、OAuth client-secret MCP(0.160)、远程压缩 v2+/recap(0.155)、云同步 skills+预算去重(main)、/side 旁问(main,Atlas 已有 /btw 等价)。apply_patch/V4A 未变 KEEP |
| OpenCode | anomalyco/opencode **v1.18.34**(09-30;v1 Bun CLI + v2 Effect/SQLite 重写并行) | 编辑工具/LSP/plan/plugins 窗口期未动;KEEP。可借鉴:子代理失败以 task_id 可恢复(Atlas 已有重派)、压缩保留完整近期轮 |
| Pi | earendil-works/pi **v1.0.0**(10-01,首个稳定版;13 包) | **确认无内置子代理** → Atlas 保留更强子代理体系(A 系 KEEP);快照回退=仅会话树分支,Atlas 的文件级撤回更强 KEEP;可借鉴:prompt cache warming、每模型压缩预算、ContextEditEntry、结构化压缩摘要(Atlas 已有) |
| Browser Use | **0.13.10**(2026-09-04;CLI 3.0,CDP attach `BU_CDP_URL`;本地无 turnkey 录制→重放→自愈,云版才有) | X2:KEEP 现有依赖版本;录制/重放/自愈自建薄层(基于 Hermes a11y `@eN` refs),不引云 |
| Stagehand | **4.1.0**(npm 2026-09-09;CDP-native,cache/selfHeal 服务端 Browserbase-only) | 逻辑参考(observe→act 确定性重放、cache status、单步自愈),不引依赖 |
| Playwright MCP / chrome-devtools MCP | v0.0.83(09-28,新增录制生成代码)/ v1.10.1(09-23,转向性能调试) | X2:默认关闭的高级选项;Playwright MCP 录制思路供 X2 recording 参考 |
| Camoufox / Lightpanda | 0.5.6(09-06)/ **1.0.0(10-02)** | 沿用 Hermes 可选后端,不新增 |
| skills.sh | LIVE,vercel-labs/skills(33k★);API v1(`/api/v1/skills`、`/skills/search`、`/skills/{id}` 全文件快照+SHA256) | X4:走 Hermes skills_hub 的 skills-sh 源适配器 |
| ClawHub | LIVE 但域名 → **clawhub.ai**;API v1 `/skills`、`/download`;50k+;曾发生 ClawHavoc 投毒事件(341 恶意技能) | X4:接 Hermes clawhub 源;不做安全扫描(用户自负),但来源徽章标注 community |
| Hermes Skills Hub | fork 内 8 源:official / skills-sh / clawhub / github taps / well-known / lobehub / browse.sh / direct URL;lockfile 带内容哈希 | X4:主路径,单 registry=core/atlas/skills,Hermes 仅作 source/install/update 层 |
| anthropics/skills + Agent Skills 规范 | LIVE(179k★);SKILL.md:name+description 必填,allowed-tools 实验性,渐进披露 3 级 | KEEP(Atlas 已按规范);X2/X5 生成技能按同一规范输出 |
| Claude Code 插件格式 | v2.1.288;**Claude Mods**(2.1.287)、.mcpb 安装期配置(2.1.285)、非官方源禁止 allowed-tools 自预批(2.1.284) | C4 兼容层 UPGRADE 候选:Claude Mods 与 .mcpb 配置(记录,非阻塞) |
| Factory droid | v0.232.0(10-02) | 参考:Spec Mode 独立模型;不搬 |
| Cline | v4.1.22 + CLI 3.0.68 | 参考:市场 Customize;不搬 |
| Kiro | CLI 2.27.0(10-01),Workflows/Powers | 参考;不搬 |
| Roo Code | **已归档**(2026-05-15 后无动作) | 从对标表移除 |
| goose | **aaif-goose/goose**(Linux Foundation AAIF),v1.53.0(10-02);sub-recipes 文档化 | KEEP Atlas Recipe 命令映射 |
| Gemini CLI | v0.62.0(09-29);a2a-server、ACP bridge | 参考;不搬 |
| Amp | 活跃(Shared Runners、agent-to-agent 消息) | 参考;不搬 |
| OpenHands | v1.24.0(09-25);Agent Canvas、Skills/Hooks/Tools 对话框 | 参考;不搬 |
| Antigravity | 2.0 + SDK(09-08) | 参考;不搬 |

## Hermes upstream 与 Atlas 重复度核查(01-hermes.md 结论)

上游 518 提交为稳定化窗口(desktop 201 文件、hermes_cli +2.0k、agent/ +1.2k):
- **无能力域取代 Atlas 现有实现**:browser_tool*/computer_use/skills_hub/curator/delegate_tool/provider_registry 在该窗口均未被上游触碰。
- 上游新增可借鉴:agent/anthropic_thinking_replay.py+_policy.py、agent/tool_call_batches.py、agent/message_sanitization.py、turn-recovery 集群更新、git-filter 中和系列(subagent_worktree 受影响,已在合并内)。
- Honcho 记忆插件已解绑(Atlas 记忆冻结,不受影响)。
- 进行中 PR(#128528 turn.alive、#129791 delegation 子代理隔离、#129836 插件生命周期)记入 X5 watcher 初始关注列表。
