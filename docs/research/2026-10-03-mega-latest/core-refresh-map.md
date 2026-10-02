# Atlas 核心刷新决策表（C1–C6 vs 当前最强实现）— 2026-10-03

> U1 任务书：`tasks/taskbooks/ATLAS-U1-LATEST-BEST-REFRESH.md`。
> 结论三档：KEEP（Atlas 已相当或更强）/ UPGRADE（搬当前更强实现）/ REPLACE（删旧换新）。纯平台/企业项记入文末「仅记录」。
> 冻结锚点：Hermes upstream main `a6e75acb0d`（2026-10-02）；fork atlas 合并点 `27c63095b0`（2026-10-03 05:55 +0800）；**Atlas 已 pin `27c63095b0`**（`core/pyproject.toml:47`）——518 提交窗口内 agent/ 循环强化已经随 U0 进入 Atlas 运行时（engine 经 `run_agent.py::AIAgent` 跑真 Hermes 循环，`core/atlas/engine/hermes_runtime.py`）。Claude Code **2.1.288**（stable 2.1.285）/ Codex **rust-v0.160.0** / OpenCode **v1.18.34** / Pi **v1.0.0**。
> 注：任务书提到的并行产物 `hermes-merge-adapter-impact.md` 截至本文**尚不存在**；适配层影响只在本表备注，不重复其清单。

## 汇总

| 判定 | 数量 | 其中阻塞日常 |
| --- | --- | --- |
| KEEP | 31 | — |
| UPGRADE | 10 | 1（条件性：D1 git 安全，跑不可信仓库+子代理 worktree 时） |
| REPLACE | 1 | 0（S3 双检查点合并，清理债；**2026-10-03 已施工完成**，见 S3 行） |

UPGRADE 全部 S/M 难度、可直接搬；无 L 级。8 项建议 in-mega 施工，其余 record-only（见表）。

## A. Agent 循环 / 恢复 / 上下文（L1–L10、X1–X10）

| 能力 | Atlas 当前 | 当前最强来源 | version/commit | repo/file | 判定 | 阻塞 | 难度 | 波次 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| L1 轮数/预算 | Hermes iteration_budget，不限轮数（C1✔） | HM=CC 同构 | pin `27c63095b0` | hermes-agent `agent/iteration_budget.py` | KEEP | 否 | — | — |
| L2 出错恢复 | 限流/超时/截断/溢出/transcript 修复全链（C1✔） | HM；窗口内大幅强化：流式重复循环切断 `b6aae42c3b`、token_count 恢复 `440b97eae0`/`d037aba450`/`be20a423ba`/`815b79652d`、thinking replay 修复 `9c82eab919`/`1798b335c4`/`6403dd325c` | pin 内已含 | hermes-agent `agent/turn_recovery.py` 等 | KEEP（已随 pin 升级） | 否 | — | 备注：需跑一次适配层回归（anthropic_thinking_replay × Atlas `_atlas_before_model_request` 每请求思考切换） |
| L3 防打转 | repetition guard + 同文件计数 | HM 窗口内新增流式侧切断 | `b6aae42c3b` | hermes-agent `agent/repetition_guard.py` | KEEP | 否 | — | — |
| L4 完成自检 | 验证闸门 + stop gates | HM | pin | hermes-agent `agent/verification_stop.py` | KEEP | 否 | — | — |
| L5 并行工具 | 并行执行器 | HM 新增 `tool_call_batches.py`、`message_sanitization.py`（+99/+80） | pin 内已含 | hermes-agent `agent/tool_call_batches.py` | KEEP（pin 带来） | 否 | — | — |
| L6 插话 | redirect 立即转向、保留 partial | CX 0.159 `instant_interrupt`（opt-in） | rust-v0.160.0 | openai/codex `codex-rs/core` | KEEP（等价） | 否 | — | 记录 CX opt-in 差异 |
| L7 排队 | steer/排队桥接 | HM | pin | — | KEEP | 否 | — | — |
| L8 分阶段思考 | 规划/执行/验收三档（`models/reasoning_stages.py`） | CX 0.158 计划模式=协作模式掩码：每模式可配模型+推理档+指令 | rust-v0.158.0 | codex-rs `models-manager/src/collaboration_mode_presets.rs` | UPGRADE | 否 | S/M | **in-mega**（计划档允许指定更强模型，日常质量直接受益） |
| L9 时间预算 | run_budget 接入 | HM | pin | — | KEEP | 否 | — | — |
| L10 环境注入 | Hermes 环境提示 | HM | pin | — | KEEP | 否 | — | — |
| X1 自动压缩 | Hermes ContextCompressor（先删工具输出再总结、保护头尾） | HM；Pi v0.86 每模型压缩预算、OD v1.18.17 保留近期整轮 | Pi v1.0.0 | earendil-works/pi `docs/compaction.md` | KEEP（近期轮保护已在；Pi 每模型预算记 record-only） | 否 | S | record-only |
| X2 手动压缩 | /compress + focus topic | CX 0.155 `/recap`（等价） | rust-v0.155.0 | — | KEEP | 否 | — | — |
| X3 前缀稳定 | 三层提示词 + Atlas `agent/prompt_cache_boundary.py` | HM=Pi transcript-backed 变更同向 | pin | — | KEEP | 否 | — | — |
| X4 各家缓存 | Anthropic 标记/OpenAI 自动前缀 | Pi v0.86 **prompt cache warming**（长工具执行/空闲时保鲜，Anthropic 5m TTL 下省钱省延迟）；Atlas 无 | Pi v1.0.0 | pi `packages/agent` cache warming | UPGRADE | 否 | M | **in-mega**（engine 空闲/长工具计时器触发刷新） |
| X5 按模型提示词 | 9 模型族短指引 | OD 13 份 per-model | v1.18.34 | anomalyco/opencode `session/prompt/` | KEEP（覆盖日常模型族） | 否 | — | — |
| X6 规则文件 | AGENTS.md/CLAUDE.md/子目录 hints | CC 2.1.277 AGENTS.md fallback（Atlas 已覆盖同语义） | 2.1.288 | — | KEEP | 否 | — | — |
| X7/X8 上下文构成/窗口 | breakdown + models.dev ETag 五级缓存 | CC 2.1.287 1M 默认（models.dev 元数据自动覆盖） | 2.1.288 | — | KEEP | 否 | — | — |
| X9/X10 完整记录/干净交接 | SessionDB 同步 + context handoff（`e287231`→pin） | CC/CX/Pi 同构 | pin | — | KEEP | 否 | — | — |

## B. 文件 / 补丁 / 终端 / LSP（T1–T19）

| 能力 | Atlas 当前 | 当前最强来源 | version/commit | repo/file | 判定 | 阻塞 | 难度 | 波次 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T1–T9 读/写/编辑/搜索 | Hermes 文件工具全链（行号/分页/防覆盖/9 策略 patch/ripgrep），窗口内 `tools/` 基本静默（23 文件 +514） | HM；CX apply_patch/V4A 窗口内格式未变 | pin / rust-v0.160.0 | hermes-agent `tools/file_tools*.py` | KEEP | 否 | — | — |
| T8 编辑后诊断 | Atlas LSP 桥（写前基线、只报新增，`engine/lsp_bridge.py`） | OD v2 LSP runtime **尚不存在**（`edit.ts` 仍 TODO） | v1.18.34 | opencode `packages/core/src/tool/edit.ts` | KEEP（Atlas 领先） | 否 | — | — |
| T10–T12 终端/PTY/Windows | 后台+notify+心跳+真终端，路由 PowerShell | CX unified_exec 窗口内仅安全加固（exec-server bearer/Windows sandbox） | rust-v0.160.0 | codex-rs `core/src/unified_exec/` | KEEP | 否 | — | — |
| T13–T18 web/todo/clarify/执行/工具搜索/输出落盘 | 全部经 pin；tool_search 延迟规则在用（`review/engine.py:747` ambient 例外） | CC 2.1.287 大工具结果内存优化 ≈ Hermes tool_result_storage | 2.1.288 / pin | — | KEEP | 否 | — | — |
| T19 Atlas 自有工具 | WebSocket 验收覆盖 | — | — | — | KEEP | 否 | — | — |

## C. 会话 / 交互 / 权限（S1–S6、I1–I8）

| 能力 | Atlas 当前 | 当前最强来源 | version/commit | repo/file | 判定 | 阻塞 | 难度 | 波次 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S1 恢复会话 | SessionDB 恢复；窗口内 resume/token_count 修复已随 pin | HM | pin | hermes-agent `agent/transcript_repair.py` | KEEP | 否 | — | — |
| S2 分叉/会话树 | 分支树界面 + Hermes branch lineage（`engine/session_sync.py`）；**分支切换自动摘要已实现（2026-10-03）**：`engine/branch_summaries.py` 异步+缓存+single-flight，复用 `compression_model` 便宜模型与 `save_branch_summary`/`append_branch_summary` 落库路径，fake-model 测试断言只请求一次且读缓存不阻塞切换 | Pi branch summarization（切分支附摘要） | v1.0.0 | pi `docs/compaction.md` Branch Summarization | implemented（待 server 分支路由一行接线，注记在模块注释内） | 否 | M（已完成） | in-mega 已施工 |
| S3 撤回/检查点 | **已合并（2026-10-03）**：保留 `agent/checkpoints.py` ShadowGitCheckpointStore 为唯一实现；server.py 全部本地检查点路由（/api/checkpoints、history、rewind、_run_changes）本就调用它（C3 已单库），W06 残留的每检查点 shadow-git 子系统（每快照 4 次 git 子进程+双份存储，从未被当 git 读取）已删除；新增 `manifest_path()` 作为布局访问器。恢复兼容旧快照（git/ 优先回退 files/）。ssh.py `.atlas-checkpoints` 为远程传输适配器保留（文件在远端，本地库无法触及），语义弱（首触快照、无修剪）记录为后续项 | OD v2 content-addressed snapshot（capture/diff/restore）作合并参照 | v1.18.34 | opencode `packages/core/src/snapshot.ts` | implemented（kept ShadowGitCheckpointStore, folded W06 shadow-git machinery; 界面与 HTTP API 零改动, server.py 无需修改） | 否 | S（已完成） | in-mega 已施工 |
| S4–S6 标题/搜索/导出 | 全有（C1） | HM | pin | — | KEEP | 否 | — | — |
| I1 权限档位 | 六档 + 子代理不提权 | CC auto-mode 分类器默认全量（用户明确不做安全分类器） | 2.1.284+ | — | KEEP（分类器记 record-only） | 否 | — | record-only |
| I1b 危险命令审批 | 审批卡片常驻等待 | CC 2.1.281 危险 rm 提示 2min 超时+改写提示（无人值守不卡死） | 2.1.281 | — | UPGRADE | 否 | S | record-only |
| I2 计划模式 | 只读+批准执行 | CX mode presets（已并入 L8 行） | — | — | KEEP | 否 | — | — |
| I3/I4 目标/旁问 | 全有 | CX `/side`（main 新增，等价） | — | — | KEEP | 否 | — | — |
| I5–I8 命令/状态栏/后台面板/提醒 | 全有；后台任务面板接 HM 进程表；**I7 send-now 已实现（2026-10-03）**：`engine/steer_dispatch.py` + hermes_runtime steer 循环——send-now 消息经 `agent.steer` 入队并对工具 worker 发 `tools.interrupt.request_yield`，前台终端把活进程移交 `tools/process_registry` 后台继续（不取消），下一模型轮注入；不可后台的工具天然回退排队。fake 工具测试覆盖后台/不可后台/回退 | CC 2.1.281 **send-now 把运行中工具转后台而非取消** | 2.1.281/286 | — | I7 相关：implemented（send_now WS 字段待 server 一行接线，注记在 `steer_dispatch.queue_run_steer`） | 否 | M（已完成） | in-mega 已施工 |

## D. 子代理 / 编排（A1–A5）

| 能力 | Atlas 当前 | 当前最强来源 | version/commit | repo/file | 判定 | 阻塞 | 难度 | 波次 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A1–A5 委派/验收/定义/界面/会诊 | 全链（C1/C3✔）；上游窗口 `delegate_tool.py` 未动 | HM | pin | hermes-agent `tools/delegate_tool*.py` | KEEP | 否 | — | — |
| D1 worktree git 安全 | **已实现（implemented，2026-10-03）**：`agent/subagent_worktree.py` 已补齐 git-safety 加固——(1) 所有 git 子进程改跑内联 `noninteractive_git_env`（`GIT_TERMINAL_PROMPT=0`、`GCM_INTERACTIVE=Never`、`GIT_CONFIG_GLOBAL/SYSTEM` 置空、丢弃 `GIT_CONFIG_*` 注入、pin `core.fsmonitor=false`/`core.hooksPath`/`credential.helper` 等、`safe.directory` 回放）；(2) `worktree add`（smudge 执行点）与 finalize 的 `status` 探针（clean 执行点）改用 `noninteractive_repo_git_env`——按 `.gitattributes` 发现 repo 命名 filter 并追加空命令 + `required=false` 覆盖，发现失败即 fail-closed（创建返回 None / 树保留 unproven）。测试 `core/tests/test_subagent_worktree.py`（7 用例：恶意仓库 E2E smudge/clean/fsmonitor/hook 中和 + fail-closed + env pin 单元）+ `test_backend_parity_wave7.py` 全绿 | HM 窗口内 git-safety 系列（GHSA-7x36-8jrh-v4pw）：`bba715b42d`/`9c589b91bd`/`803cd03521`/`1ff01f4cf7` | pin 内已含（hermes 侧） | hermes-agent `tools/subagent_worktree.py:18-90`、`hermes_cli/_subprocess_compat.py` → Atlas `core/atlas/agent/subagent_worktree.py` | ✅ **UPGRADE 已完成** | 否（原条件性阻塞已消除：不可信仓库派子代理 worktree 时 filter 不再执行） | S/M | **implemented（2026-10-03，commit hash 待提交后回填）** |
| D2 子代理结果注入防护 | **已实现（implemented，2026-10-03 U1-b）**：`agent/results.py` 新增 `frame_subagent_result`/`frame_delegate_result_data`——结构化头 `<atlas-subagent-result id backend agent status>`（id 由父端生成、子代理上下文不可得）+ 正文全行缩进两格（伪造的头部/关闭标记只会以缩进内容出现，顶格关闭标记仅末尾一处），中文安全（纯 str 操作）；`agent/__init__.py` 三处模型可见文本套框：delegate_task / delegate_parallel（summary）/ subtask_status 的 content 文本，`result["data"]` 与 enrichment record 保持原始结构化字段（usage 提取与前端 schema 不变，output_schema 校验路径不经过该文本）。测试 `core/tests/test_d2_subagent_framing.py`（6 用例：结构/中文安全+伪造中和/空文本/仅动文本不动 schema/E2E 经 Hermes 循环断言 tool 消息） | CC 2.1.277：子代理输出带不可伪造头+缩进，防冒充会话指令 | 2.1.277 | — | ✅ **UPGRADE 已完成** | 否 | S | **implemented（2026-10-03）** |
| D3 子代理失败可见性 | 失败可重派、schema/status 校验（C3✔）≈ CX 0.160 环境准备失败显式化、OD task_id 可恢复 | CX/OD | 0.160 / v1.18.20 | — | KEEP | 否 | — | — |
| D4 子代理 frontmatter | 模型/上下文策略可配（`3b8627a`） | CC `omitClaudeMd`(2.1.271)/`cacheTtl`(2.1.248)/`SUBAGENT_MODEL_FORCE`(2.1.257) | 2.1.277 | — | KEEP 部分；cacheTtl/omit 记 record-only | 否 | S | record-only |

## E. 扩展（E1–E6）

| 能力 | Atlas 当前 | 当前最强来源 | version/commit | repo/file | 判定 | 阻塞 | 难度 | 波次 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E1 MCP | Hermes MCP family（经 pin）+ Atlas `tools/mcp_client.py` 自有层 | CC 2.1.285/287 `alwaysLoad:false` 整服务器延迟加载、`MAX_MCP_DESCRIPTION_LENGTH` | 2.1.287 | — | KEEP（tool_search 已做延迟）；server 级开关记 record-only | 否 | S | record-only |
| E2 技能 | SKILL.md+渐进加载+统一 SkillManager（C4✔）；**verify 技能已实现（2026-10-03 U1-b）**：`skills/dev/verify/SKILL.md`（name/description/version/category/triggers 合规，正文=焦点测试（pytest 触碰文件+紧邻测试）→ 类型检查/静态检查 → 汇报格式含强制「未验证」清单 + 提交前必跑红线），解析经 `atlas.skills._parse_skill_md` 校验 | CC 2.1.286 **verify 技能约定**（存在名为 verify 的技能则提交前必跑）；2.1.261 **/skill-doctor**（未用技能的上下文成本） | 2.1.286/261 | — | UPGRADE ×2 → ✅ verify **已完成**；skill-doctor 仍 in-mega 候选 | 否 | S / S/M | verify=**implemented（2026-10-03，tests/test_e2_verify_skill.py）**；skill-doctor=in-mega 候选 |
| E3 Hooks | 事件覆盖全（含 PreModelSwitch/PostModelSwitch，`runtime/hooks.py:27`） | CC 2.1.251 SessionStart resume 附 staleness+重缓存估算 | 2.1.251 | — | KEEP；staleness 载荷记 record-only | 否 | S | record-only |
| E4 插件 | CC 插件格式兼容（C4✔） | CC 2.1.287 Claude Mods（改 harness 行为层）、2.1.285 configure/.mcpb 配置、2.1.269 plugin eval、2.1.271/286 供应链加固 | 2.1.288 | — | KEEP；Mods/mcpb/eval 记 record-only（平台层） | 否 | L | record-only |
| E5/E6 命令/导入 | 全有（C4✔） | CC 2.1.283 /doctor prompt-audit | 2.1.283 | — | KEEP；prompt-audit 记 record-only | 否 | S/M | record-only |

## F. 模型（M1–M6）

| 能力 | Atlas 当前 | 当前最强来源 | version/commit | repo/file | 判定 | 阻塞 | 难度 | 波次 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M1 服务商/目录 | 16 家目录（2026-10-02 查证）+ models.dev ETag 元数据；GPT-6 系（astra/sol/luna/6.1-sol）已在 `models/reasoning_effort.py`；**离线回退行已实现（2026-10-03 U1-b）**：`models/catalog.py` `CLAUDE_DEFAULT_MODEL_FALLBACKS`（Sonnet 5.5 1M $2/$10+cache_read $0.20 / Opus 5.5 1M $4/$20 / Fable 5.1 1M $10/$50，行形状与 `_BUILTIN_MODEL_METADATA` 一致，未核实字段如 output 上限刻意缺席），`models/models_dev.py::_builtin_model_metadata` 内建表未命中时读取——vendored 表零改动；只补元数据不进选择器目录，在线时 models.dev 仍自动覆盖 | CC 2.1.257–284 三新默认模型：Sonnet 5.5 / Opus 5.5 / Fable 5.1（均 1M） | 2.1.284 | — | ✅ **UPGRADE 已完成** | 否 | S | **implemented（2026-10-03，tests/test_m1_offline_model_rows.py）** |
| M2 密钥池 | AtlasCredentialPool 全链（C5✔） | HM | pin | — | KEEP | 否 | — | — |
| M3/M4 fallback/推理参数 | 经 pin；effort 档位规则 per-model（`reasoning_effort.py`） | CC 2.1.251 effort 按模型记忆、2.1.267 maxEffortLevel 上限 | 2.1.267 | — | KEEP；用户 effort 按模型持久化记 record-only | 否 | S | record-only |
| M5 用量/缓存诊断 | C5 缓存未命中三层哈希归因（`0814f39`）≈ CC 2.1.251/260 /cost 缓存诊断 | CC | 2.1.260 | — | KEEP（等价） | 否 | — | — |
| M6 编辑模型 | PUT/DELETE 自定义模型（C5✔） | — | — | — | KEEP | 否 | — | — |

## G. 编程专项（P1–P4）与 UX

| 能力 | Atlas 当前 | 当前最强来源 | version/commit | repo/file | 判定 | 阻塞 | 难度 | 波次 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 /init | 确定性扫描+托管区段+diff 预览（`commands/init.py`，C6✔） | CX/OD 同类 | pin | — | KEEP | 否 | — | — |
| P2 /review | 结构化 findings+只读审查员子代理+卡片（`review/engine.py`，C6✔）；CC 2.1.288 `--max-findings` 仅参数糖 | CC/CX | 2.1.288 | — | KEEP；--max-findings 记 record-only | 否 | S | record-only |
| P3 worktree | 子代理隔离（见 D1 安全缺口） | HM+CX 默认开启（0.156） | pin | — | KEEP（默认开启记配置项） | 否 | S | record-only |
| P4 代码地图 | `coding_repo_map`/`ast_grep`；11 家仍无向量检索 | — | — | — | KEEP | 否 | — | — |
| G-UX /diff/用量/全屏 | 改动面板+用量页已有 | CC 2.1.260 /diff、CX 0.156 /usage、Pi v1.0 全屏 TUI | — | — | KEEP；前端虚拟化记 record-only | 否 | — | — |

## 仅记录（不阻塞、不进 mega）

- 平台/企业层：CC auto-mode 分类器与服务端分类、Claude Mods、plugin eval/configure/.mcpb/供应链加固、CX Guardian 全家、exec-server bearer WS+网络策略、OAuth client-secret MCP、remote compaction v2、CC/CX 语音、CX Daybreak。
- 架构信号：Pi codemode（QuickJS 沙箱跑模型写的 JS，省 ~40% 工具 token）、ContextEditEntry、tool exposure 五档；Pi v1.0.0 确认无内置子代理/无文件回滚 → Atlas 子代理与检查点体系继续 KEEP。
- 仓库更名：OpenCode → `anomalyco/opencode`、Pi → `earendil-works/pi`、goose → `aaif-goose/goose`（Linux Foundation AAIF）；Roo Code 已归档，从对标表移除（source-freeze 已录）。
- X5 watcher 初始关注：HM PR #128528（turn.alive）、#129791（delegation 子进程隔离）、#129836（插件生命周期）。
- 观察项（非表内）：`engine/hermes_runtime.py` 头注释仍指旧源 `562ad75`（pin 已是 `27c63095b0`），顺手更新；Atlas 自有 `tools/mcp_client.py` 与 Hermes MCP family 双轨并存，待 C 波确认日常路径后考虑收敛。

## 与 source-freeze 档案的差异/补充

1. 档案写「fork atlas 同步前 `e287231`、Atlas pin `e287231`」——实测 fork 已合并至 `27c63095b0` 且 `core/pyproject.toml:47` 已 pin `27c63095b0`（U0 已完成，档案快照过时但方向一致）。
2. 档案 01 把「Anthropic thinking replay/policy」列为 cherry-pick 候选——经核实**无需 cherry-pick**：Atlas 走 pin+真 AIAgent 循环，已自动包含；真正需要手工搬的是 git-safety 系列（D1，Atlas 有旧版自有拷贝）。
3. 档案 01 称上游窗口 turn-recovery 集群更新——补充量化：streaming 重复切断与 token_count/resume 修复共 8+ 提交（见 L2/L3 行），是本窗口对日常稳定性最实质的改动，已随 pin 生效。
4. `hermes-merge-adapter-impact.md` 不存在；D1/L2 的适配层回归（thinking replay × Atlas 每请求思考档切换）建议由 U0/施工波补跑。
