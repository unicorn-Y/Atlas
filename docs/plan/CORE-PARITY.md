# Atlas 主体对标表（2026-10-01）

**这张表决定 C1–C6 每一波做什么。** 范围只限「主体」：用户每天实际用的部分，包括对话干活、读改代码、跑命令、上下文、会话、交互、子 Agent、扩展、模型、编程。外部功能（渠道、连接器目录、跨设备、分享、电脑和浏览器操作扩展、自我进化）冻结，不在这张表里。

> 2026-10-02 C1 收尾复核：L2、L4、T10、T11、T19、S4、A1 的既有实现已由对应 Atlas 聚焦回归及 WebSocket 验收核实；暂停后模型调用闸门和 Kanban SQLite 锁争用另行修复。详见 `tasks/results/ATLAS-C1R-FINISH.result.md`。

对标对象：Claude Code（CC）、Codex（CX）、ZCode（ZC）、Hermes（HM）、OpenClaw（OC）、Pi、OpenCode（OD）。
- HM、OC、OD、Pi、CX 开源，下面的文件路径都对应各自仓库当前的 main。`HM@bafb42b` 是 2026-10-01 克隆时的提交号。
- CC、ZC 闭源，只能照它们的设计自己写。
- OC 的内核直接用的是 Pi 的 agent-core（见 OC 文档 agent-runtime-architecture），所以 OC 的内核能力并入 Pi 一列看。

## 0. 为什么先做主体

1. **外层框架（harness）决定实际体验。** 同一个模型换个外层框架，分数能差 13–18 分；LangChain 只改提示词、工具和前后检查，就从 52.8 提到了 66.5。这一层恰恰是 Atlas 最弱的。
2. **代码核实：Atlas 内核的硬伤**（2026-10-01，`main@77353ba`）。

| 问题 | 位置 |
| --- | --- |
| 一次任务最多 10 轮工具调用，到了就直接结束 | `core/atlas/agent/__init__.py:144` |
| 「压缩」不调用模型，只是把最近 12 条消息各截 240 字拼起来；压一次后一直沿用这份旧摘要 | `agent/__init__.py:1072-1124`、`agent/enrichment.py:76-108` |
| 下一轮对话丢掉上一轮所有的工具调用和结果，只保留问答文字 | `agent/__init__.py:2774-2778` |
| 系统提示词 15 行，没有工作目录、系统、日期、git 状态 | `agent/__init__.py:126-142` |
| 编辑会把 LF 换行改成 CRLF（已实测复现） | `tools/local_execution.py:314-325` |
| 搜索是逐文件找子串，不支持正则、不跳过 node_modules/.git、没有结果上限；读文件没有行号、不能分页 | `tools/local_execution.py:346-416` |
| 「上下文占用」的上限一直是空值 | `agent/__init__.py:1292` |
| 记忆、知识、反思等动态内容插在历史前面，导致提示词前缀每轮都变，缓存很难命中 | `agent/__init__.py:2669-2772` |
| 工具一个个串行执行；用的是 LangGraph（论文研究的 11 家主流内核里，没有一家用通用框架） | `agent/__init__.py:1436`、`_build_graph` |

3. **结论**：内核换成 Hermes 的整套 Python 内核当骨架（C1），零件再逐项换成各家最强的（C2–C6）。对标表 `docs/PARITY.md` 里 170 个 ✅ 大多是界面层的，保留下来，接到新内核上。

## 1. 怎么读这张表

- **最强做法**：写谁做得最好、好在哪个细节。
- **Atlas 现状**：✔ 已有且不差；△ 有但明显弱；✘ 没有。凡注明「代码」的都已在代码里核实；写「待核」的，由当波施工时先核实。
- **骨架带来**：C1 接上 Hermes 后自动具备的能力。
- **还要补**：Hermes 不是最强的地方，从哪家哪个文件拿。
- **波次**：在哪一波做。
- **「初判」**：表示还没把两家的源码逐行比过。当波任务书的第一步就是比，选强的那家，比的结论写进结果文件。

## 2. Agent 循环

| # | 能力 | 最强做法 | Atlas 现状 | 骨架带来 | 还要补 | 波次 |
| --- | --- | --- | --- | --- | --- | --- |
| L1 | 不限轮数，靠预算和停止条件收尾 | HM：默认不限轮数，用 `agent/iteration_budget.py` 控预算，子 Agent 共享预算；CC 同样不限 | ✔ Hermes 超过 10 轮（`4357a86`） | ✔ | — | C1 |
| L2 | 出错恢复（限流、超时、断流、空回复、输出被截断后续写、上下文超长） | HM：`agent/turn_recovery.py`、`turn_api_error.py`、`empty_response_guard.py`、`turn_truncation.py`、`turn_overflow.py`、`transcript_repair.py`（加起来几千行，各家里最全） | ✔ 限流、服务端错误、超时、空回复、截断续写、上下文超长和 transcript 修复均由 `test_c1_recovery.py` 覆盖 | ✔ | — | C1 |
| L3 | 防原地打转 | LangChain：同一文件改了 N 次就提醒换思路；HM：`agent/repetition_guard.py` | ✔ Hermes repetition guard + Atlas 同 run 同文件计数，第 6 次起提醒 | ✔ | — | C2 |
| L4 | 完成前自检 | LangChain 的完成前检查清单；HM：`agent/verification_stop.py`、`turn_stop_gates.py` | ✔ Hermes 循环在完成前执行验证闸门；未验证完成会触发修正提示，见 `test_c1_stop_gate.py` | ✔ | — | C1 |
| L5 | 并行工具调用 | CC：只读工具并行，写操作串行；HM：`agent/tool_executor.py` 加 `PARALLEL_TOOL_CALL_GUIDANCE` | ✔ Hermes 并行委派场景（`4357a86`） | ✔ | — | C1 |
| L6 | 运行中插话（不打断当前工具） | CX 0.159 `instant_interrupt`：模型输出中途也能转向；Pi 的转向队列；HM `/steer` | ✔ 默认排队下一步；立即转向用 Hermes redirect，只中断生成并保留 partial | ✔ HM steer | — | C3 |
| L7 | 消息排队 | HM `/queue`；Pi 的后续消息 | ✔ Hermes steer/排队桥接（`805110c`） | ✔ | — | C1 |
| L8 | 分阶段分配思考量 | LangChain：规划和验收深想、执行浅想（66.5 对 53.9） | ✔ 设置→模型「按阶段分配思考量」默认关；开启后首轮/计划模式=规划档、执行=执行档、stop-gate 验证轮=验收档（`_atlas_before_model_request` 每请求钩子切换，hermes transport 每请求读 `agent.reasoning_config`），关闭时行为不变（`0814f39`） | ✘ | — | C5 |
| L9 | 时间和预算提醒 | LangChain；HM `run_budget_seconds`、`deadline.py` | ✔ Atlas `agent.run_budget_seconds` / `agent.budget_warning_ratio` 接入 Hermes 原有一次性提醒链，默认关闭 | ✔ | 保留 | — |
| L10 | 每轮自动带上本机环境信息 | LangChain 的环境注入；HM `agent/env_probe.py`、`prompt_builder.py` 的环境提示 | ✔ Hermes 环境提示；SSH 信息仅注入 terminal 环境（`805110c`, `fe31ba1`） | ✔ | — | C1 |

## 3. 文件与命令工具

| # | 能力 | 最强做法 | Atlas 现状 | 骨架带来 | 还要补 | 波次 |
| --- | --- | --- | --- | --- | --- | --- |
| T1 | 读文件：行号、分页、大文件续读 | HM `read_file`：行号、分页、约 10 万字截断并给出续读位置、找不到时提示相近文件名（`tools/file_tools.py:1146`） | ✔ Hermes `read_file`（`805110c`） | ✔ | — | C1 |
| T2 | 读文档 | HM：ipynb、Office、PDF、ODF、RTF、EPUB、SQLite 都转成文本 | ✔ Hermes 文件工具集（`805110c`）；Windows 源回归有失败，见结果文件 | ✔ | — | C1 |
| T3 | 读图片 | CC 的 Read 直接读图；CX `view_image` | ✔ Hermes 图片预处理；视觉模型直读，否则调用配置的 `vision_analyze` 或给出提示；工具结果显示缩略图 | ✔ | — | C2 |
| T4 | 写文件防覆盖 | HM：没读过或磁盘上已变的文件拒绝覆盖，写完校验哈希，自动语法检查且只报新增错误（`file_tools_write_guards.py`、`file_operations_lint.py`） | ✔ Hermes 写保护经 Atlas 策略/快照桥接（`b93076b`） | ✔ | — | C1 |
| T5 | 编辑：容错匹配 | HM `patch`：逐级放宽匹配；OD `edit.ts`：唯一锚点间的变量长度替换 | ✔ Hermes 9 种策略 + OpenCode 唯一边界锚点间可变长度匹配；歧义仍拒绝，CRLF/LF/BOM 保留 | ✔ | — | C2 |
| T6 | 编辑保留换行和编码 | CC、OD：保留 CRLF/LF 和 BOM | ✔ Windows 假文件 LF/CRLF 测试通过（`4357a86`） | ✔ | — | C1 |
| T7 | 给 GPT 系模型用补丁格式 | CX `apply_patch`（`codex-rs/apply-patch`）；HM 只对 OpenAI 系模型显示 V4A 补丁模式 | ✔ Hermes patch tool 保留模型适配（`698b7bb`） | ✔ | — | C1 |
| T8 | 编辑后诊断 | OD：改完跑 LSP 诊断回传；CC 的诊断工具；HM `agent/lsp`、`file_operations_lint.py` | ◐ LSP 诊断核心已合入 main（C6A：`core/atlas/lsp/**` 移植 Hermes `agent/lsp`，版本化新鲜度、before/after 差分行位移、Windows 进程树管理、28 条 server 注册表、fake LSP 套件 73 passed；`110fdc2`）；剩瘦写路径/UI 接线（编辑后触发与诊断回传进编辑流），完整 T8 UX 未完成 | ✔ 语法检查 | LSP 诊断：对比 OD `src/lsp` 和 HM `agent/lsp`，选强的 | C6 |
| T9 | 搜索 | HM `search_files`：基于 ripgrep，正则、文件过滤、三种输出、上下文行、分页、按修改时间排序 | ✔ Hermes `search_files`（`698b7bb`） | ✔ | — | C1 |
| T10 | 跑命令：前台、后台、结束通知 | HM `terminal`：后台进程加 `notify` 结束通知、按输出匹配通知、心跳汇报、真终端模式 | ✔ 前后台、完成通知、notify/watch/heartbeat 参数映射由 `test_c1_process_notifications.py` 覆盖 | ✔ | — | C1 |
| T11 | 真终端交互（REPL、交互式命令行） | CX `unified_exec`（真终端，可写入 stdin）；HM `pty` 加 `process_manage` 的写入 | ✔ stdin/write/submit/close、Windows PTY、handoff 和子进程结束后的父级通知由 `test_c1_tool_compat.py`、`test_c1_process_notifications.py` 覆盖 | ✔ | — | C1 |
| T12 | Windows shell | CC：PowerShell 和 Bash 两个工具；Pi `powershell.ts` | ✔ Hermes terminal 在 Atlas 路由到 PowerShell；无 Git Bash 回退实测（`698b7bb`） | ✔ | — | C1 |
| T13 | 网页搜索、抓取 | HM `web_search`/`web_extract`（多后端、缓存、截断）；CC WebFetch | ✔ Atlas 网络工具由 Atlas registry 提供；未做真实网络验收（`698b7bb`） | ✔ | 保留 Atlas 的内网防护 | C1 |
| T14 | 待办清单 | CC 的任务列表；HM `todo_list`，压缩后自动重新注入 | ✔ Hermes todo 在压缩恢复场景保留（`35cd874`） | ✔ | — | C1 |
| T15 | 向用户提问 | CC AskUserQuestion（选项预览）；HM `clarify` | ✔ `clarify` 接 Atlas 输入回调（`698b7bb`） | ✔ | — | C1 |
| T16 | 跑代码片段 | HM `execute_code`（带内核、可远程） | ✔ Atlas handler 注册至 Hermes（`698b7bb`） | ✔ | — | C1 |
| T17 | 工具按需加载 | CC ToolSearch；CX `tool_search`；HM `tools/tool_search.py` | ✔ Hermes tool search/toolset（`805110c`） | ✔ | — | C1 |
| T18 | 工具输出过长时落盘 | HM `tool_result_storage.py`、`tool_output_truncate.py`；W06 已搬一部分 | ✔ 部分 | ✔ | — | C1 |
| T19 | Atlas 自有工具 | — | ✔ WebSocket 验收覆盖 Atlas 文件、终端、Git、Kanban、MCP、子任务和恢复工具路径；本地 fake MCP 验证仅调用本机服务 | — | — | C1 |

## 4. 上下文、提示词与成本

| # | 能力 | 最强做法 | Atlas 现状 | 骨架带来 | 还要补 | 波次 |
| --- | --- | --- | --- | --- | --- | --- |
| X1 | 自动压缩 | 研究结论：先按规则删旧的工具输出，不够再让模型总结。HM `context_compressor.py`（先删工具输出，再总结中段，保护头尾，可多次迭代）；Pi 的结构化摘要格式（目标/约束/进度/决定/下一步/关键上下文，`docs/compaction.md`） | ✔ Hermes ContextCompressor；摘要固定保留目标/约束、已完成、正在做/阻塞、决定、下一步、关键文件 | ✔ | — | C1，C2 |
| X2 | 手动压缩（可带说明） | CC `/compact 说明`；HM `/compress` | ✔ Hermes ContextCompressor 和 focus topic 桥接（`35cd874`） | ✔ | — | C1 |
| X3 | 前缀稳定，保住缓存 | HM：系统提示词整场会话逐字节不变，按稳定/上下文/易变三层组装（`agent/system_prompt.py`）；Manus 的经验是缓存能省 10 倍 | ✔ Hermes 三层提示词；动态 Atlas 内容在会话开始注入（`35cd874`） | ✔ | — | C1 |
| X4 | 各家模型的缓存 | HM：Anthropic 标记、OpenAI/DeepSeek 自动前缀、`prompt_cache_scope.py` | ✔ 交由 Hermes 缓存实现（`35cd874`） | ✔ | — | C1 |
| X5 | 按模型分别写的系统提示词 | OD `session/prompt/`：anthropic、gpt、gemini、kimi、codex 等 13 份；HM 按模型族加指引 | ✔ Hermes 稳定提示层按 Claude、GPT/Codex、Gemini、DeepSeek、Kimi、GLM、Qwen、MiniMax 和默认模型族提供短指引 | ✔ | — | C2 |
| X6 | 规则文件分层 | CC：用户级、项目级、子目录级的 CLAUDE.md；CX `agents_md_manager.rs`；HM `subdirectory_hints.py`（进入子目录时追加） | ✔ AGENTS.md、CLAUDE.md、`.atlas/rules.md` 接入（`805110c`） | ✔ | — | C1 |
| X7 | 看上下文构成 | CC `/context`；HM `context_breakdown.py`；CX `get_context_remaining` | ✔ 接 Hermes breakdown 并显示系统提示、工具、规则、记忆/历史、工具输出与余量；缺数据项按实际用量显示 | ✔ | — | C3 |
| X8 | 模型的上下文窗口 | HM `model_metadata.py` 加 `models_dev.py` | ✔ 实际用量及模型上下文上限接入 UI（`805110c`） | ✔ | — | C1 |
| X9 | 记录完整保存 | CC、CX、Pi：完整记录工具调用和结果，恢复时一字不差 | ✔ Hermes SessionDB 和 Atlas 消息表同步（`15b1416`） | ✔ | — | C1 |
| X10 | 中途换个干净的上下文 | CX `new_context_window` | ✔ 交接摘要与当前 todo 进入干净模型上下文；Atlas 历史保留，时间线显示切换分隔事件 | ✔ | — | C2 |

## 5. 会话与撤回

| # | 能力 | 最强做法 | Atlas 现状 | 骨架带来 | 还要补 | 波次 |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | 恢复会话 | CC：中断在工具调用中途的，告诉模型「结果未知」；HM `transcript_repair.py` | ✔ Hermes SessionDB 恢复接入 Atlas（`15b1416`）；Windows 源测试仍有失败 | ✔ | — | C1 |
| S2 | 分叉和会话树 | Pi：一个 JSONL 文件里存整棵树，`/tree` 切换，分支自动摘要（`docs/sessions.md`、`docs/compaction.md`「Branch Summarization」）；HM `/branch` | ✔ 界面有分叉树 | △ | 分支摘要照 Pi 补；底层改成存完整记录 | C3 |
| S3 | 撤回（对话加文件） | CC rewind：可以只撤对话、只撤代码或一起撤；HM `/rollback`、`/snapshot`、`checkpoint_manager.py`；OD snapshot/undo | ✔ 有界面（W06 前做的） | ✔ | 两套检查点只留一套：对比后保留强的，界面不变 | C3 |
| S4 | 自动起标题 | HM `title_generator.py` | ✔ 新会话生成标题、延迟标题升级且保留用户手动改名均由 `test_c1_lifecycle_titles.py` 覆盖 | ✔ | — | C1 |
| S5 | 搜历史会话 | HM `session_search`（FTS） | ✔ Hermes `session_search` 接入（`698b7bb`） | ✔ | — | C1 |
| S6 | 导出 | CX `/export`；HM `/export` | ✔ | ✔ | — | — |

## 6. 交互与模式

| # | 能力 | 最强做法 | Atlas 现状 | 骨架带来 | 还要补 | 波次 |
| --- | --- | --- | --- | --- | --- | --- |
| I1 | 权限档位 | ZC 五档（每步都问 / 改前问 / 自动改文件但命令要问 / 计划 / 完全放开，Shift+Tab 切换）；CC 的 auto 模式（分类器判断，不弹窗）；OC 按会话设权限、文件访问限定在工作区 | ✔ ask_each / ask_writes / auto_file / plan / full_access，另保留 read_only；按对话保存，子 Agent 不可提权 | ✔ HM 的审批档位 | —（不做安全审查分类器） | C3 |
| I2 | 计划模式 | CC：只读探索后用 ExitPlanMode 交计划；HM `plan_prompt.py`；OD `plan-enter`/`plan-exit` 工具 | ✔ 只读文件、搜索、网页与安全终端命令；计划写入拦截，批准后回到执行 | ✔ | — | C3 |
| I3 | 持续目标 | CX `/goal`；ZC `/goal`（不断迭代直到验证达成）；HM `/goal`、`/subgoal` | ✔ Automation 与对应聊天会话共用 Hermes GoalManager / SessionDB；暂停、恢复、替换、清除、评价与续跑同源，Scheduler 只负责触发；旧目标完成/暂停状态一次迁移（`d13d941`, `138decb`，C3R focused verification） | ✔ | — | C3 |
| I4 | 旁问 | CC `/btw`；CX `/side`；HM `side_question.py` | ✔ | ✔ | — | C3 |
| I5 | 斜杠命令覆盖面 | CX 约 60 条、HM 约 100 条、CC 约 50 条 | ✔ 任务书列出的 21 个日常命令有分组/模糊搜索；`/review`、`/init` 留 C6 | ✔ Hermes 命令 | — | C3 |
| I6 | 状态栏 | CC、CX：可以配置显示模型、上下文百分比、花费、分支 | ✔ 模型、推理、上下文、tokens、费用、Git、权限、后台进程可分别开关并保存在本地偏好 | — | — | C3 |
| I7 | 后台任务面板 | CC `/tasks`；CX `/ps`、`/stop` | ✔ | ✔ | 接 HM 的进程表 | C3 |
| I8 | 完成提醒 | goose：回合结束响铃；Atlas 有系统通知 | ✔ | — | — | — |

## 7. 子 Agent 与编排

| # | 能力 | 最强做法 | Atlas 现状 | 骨架带来 | 还要补 | 波次 |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | 委派单个子 Agent | CC Task 工具（独立上下文、可指定模型和工具）；HM `delegate_tool*.py`（同步和异步、运行中引导、实时日志） | ✔ Atlas 子 Agent 全链路、模型/上下文策略、只读路径限制、进度和清理由 `test_c1_lifecycle_subtask.py`、`test_c1_child_policy.py` 覆盖 | ✔ | — | C1 |
| A2 | 并行和验收 | Factory Missions；HM 并行委派；W07 的验收 | ✔ 仅 completed 且 verifier 明确通过才 accepted；失败可重派，schema/status 不完整不计通过 | ✔ | — | C3 |
| A3 | 自定义子 Agent 定义 | CC `.claude/agents`、OD agents、CX `agent-roles` | ✔ W07 | — | 保留 | — |
| A4 | 子 Agent 界面 | CC 的任务面板；CX `/agents` 指挥中心 | ✔ 既有 Worker/验收/看板/NOTES 保留；设置接现有配置 API 与 ModelManager，可启用/禁用并选择默认子 Agent 模型；仅影响后续新建 child，运行中的 child 保留原模型（`3b8627a`，C3R focused verification） | — | — | C3 |
| A5 | 多模型会诊 | HM `/moa`、`moa_loop.py` | ✔ `/moa` 通过 Atlas ModelManager 并发参考咨询，事件和 advisory prompt 已由假咨询覆盖 | ✔ | 保留 | — |

## 8. 扩展

| # | 能力 | 最强做法 | Atlas 现状 | 骨架带来 | 还要补 | 波次 |
| --- | --- | --- | --- | --- | --- | --- |
| E1 | MCP 客户端 | HM `tools/mcp_tool*.py`（15 个文件：HTTP、OAuth、断线重连、健康检查、按需发现）；CC 的 URL 模式授权 | ✔ Hermes MCP client；本地假 stdio E2E 通过，远端 HTTP/OAuth 未实测（`4d975de`） | ✔ | — | C1 |
| E2 | 技能 | CC/Agent Skills 格式（SKILL.md 加渐进加载）；HM `skills_tool.py` 等 | ✔ SKILL.md 加渐进加载；技能目录合一：内建/用户/项目 `.claude/skills`/`~/.claude/skills`/插件/Hermes（可选）统一进同一 SkillManager，同名按稳定优先级取胜（C4） | ✔ | — | C4 |
| E3 | Hooks | CC 事件最全：工具前、工具后、工具失败、提交提示词、停止、子 Agent 开始和结束、压缩前、会话开始和结束、通知、权限请求；HM 只有 `pre_tool_call`/`post_tool_call` 两个 | ✔ 直接兼容 `.claude/settings.json` hooks（user/project/local 只读 + 插件 hooks 同一执行路径）；matcher/stdin/stdout JSON/exit code 语义；可拦截、改写工具输入、追加上下文；触发点覆盖工具前/后/失败、提交提示词、停止、子 Agent 起止、压缩前/后（手动+自动压缩桥）、会话开始/结束、通知、权限请求（旧 Atlas 事件保留）；ask 决策进既有审批卡片，deny 阻断、allow 按次放行；前端可列事件、启停、试跑、看日志（C4/C4R） | ✔ | SubagentStop 阻断继续语义已接（同一 child 会话续跑）；hook 最近运行日志仍为内存环形缓冲，重启丢失 | C4 |
| E4 | 插件 | CC 的插件市场格式（`.claude-plugin`、mcpb）；HM 插件 SDK；Pi 的扩展（TypeScript，可以改工具、命令、事件、界面） | ✔ 兼容 CC 插件格式（`.claude-plugin/plugin.json`、hooks.json、`.mcp.json`、marketplace.json）；本地/git/marketplace 三种来源；安装/启停/卸载/更新/更新检查；与 HM 插件 SDK 进同一 registry；插件五类贡献（commands/agents/skills/hooks/MCP）进 Atlas 同一发现层；前端安装/市场管理面板（C4） | ✔ | mcpb 打包格式未做；Pi 式 TS 扩展点仅思路未实现 | C4 |
| E5 | 自定义命令和提示词模板 | CC `.claude/commands`；Pi prompt templates | ✔ 兼容 `.claude/commands`（含 frontmatter description/argument-hint/allowed-tools/model/mode 等）；Markdown 命令 + `$ARGUMENTS`/`$1..$n` 占位；Atlas 用户/项目/agents/插件/Recipe 五种来源按稳定优先级合并；`/` 菜单直出，`/api/commands`+render 端点；Recipe 保留并映射为命令（C4） | ✔ | render 的 model/tool_allow/tool_deny/mode 已接入下一次 run（run.start 单次覆盖，不落对话全局；C4R） | C4 |
| E6 | 从别家导入配置 | CX `/import`：从 Claude Code 导入设置、项目和最近对话 | ✔ 「从 Claude Code / Codex 导入」：先扫描出清单（MCP/hooks/规则/skills/agents/commands/模型偏好/只读历史）供勾选，冲突默认跳过，源目录零写入，重复按内容哈希去重；导入落 Atlas 现有格式；前端在「插件与扩展」面板（C4） | ✔ | 最近对话只列出不导入（按任务书只读历史） | C4 |

## 9. 模型

| # | 能力 | 最强做法 | Atlas 现状 | 骨架带来 | 还要补 | 波次 |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | 服务商覆盖 | HM 30 多家（`providers/`、`agent/provider_registry.py`），包括腾讯、Kimi 等；Pi 有统一的模型接口 | ✔ 16 家服务商目录（catalog.py，端点/文档链接 2026-10-02 查证）+ 原生 provider/api_mode 直传 hermes profile（激活各家原生思考参数）+ models.dev 元数据（ETag 五级缓存，拷贝自 `agent/models_dev.py`@`e287231`）；无 hermes_provider 的旧条目保持 OpenAI 兼容中转行为（`f595110`, `49631e5`, `0814f39`） | ✔ | — | C5 |
| M2 | 多密钥轮换和冷却 | HM `credential_pool*.py` | ✔ AtlasCredentialPool：一服务商多密钥（keyring 存储，原文不回显），429→1h（上游 reset_at 优先）、401/403→5min、唯一 key→60s、模型级冷却只 bench (key,model)；经 hermes `recover_with_credential_pool` 真实路径验证协议兼容；设置页可见槽位状态/冷却/用量（`80be8fd`） | ✔ | — | C5 |
| M3 | 出错自动切换模型 | HM `fallback_model`、`fallback_cooldown.py`（W06 已搬一部分） | ✔ Hermes fallback model 配置传递（`805110c`） | ✔ | — | C1 |
| M4 | 推理参数按服务商适配 | HM `reasoning_params.py`、`lmstudio_reasoning.py` | ✔ Atlas reasoning effort 传入 Hermes（`805110c`）；其他服务商参数未逐个验证 | ✔ | — | C1 |
| M5 | 用量和费用准确 | CC 会显示「可能的缓存未命中原因」；HM `turn_usage.py`、`usage_pricing.py` | ✔ W06；C5 补缓存未命中原因：system/tools/history 三层稳定哈希，命中率明显下降时对比定位原因（工具定义变了/系统提示词变了/历史前缀变了/未知），随 run_usage 透出并落账本新列（`0814f39`） | ✔ | — | C5 |
| M6 | 编辑已有模型 | — | ✔ PUT/DELETE /api/models/custom/{id}：名称/provider/端点/模型名/上限/能力标记/价格可改，密钥只能重填不回显；保存后下一次请求生效，运行中任务不受影响；前端编辑/删除入口（`49631e5`, `de8e4eb`, `086a887`） | — | — | C5 |

## 10. 编程专项

| # | 能力 | 最强做法 | Atlas 现状 | 骨架带来 | 还要补 | 波次 |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | 生成 AGENTS.md | CX `/init`；OD `command/template/initialize.txt` | ✘ | ✔ HM `/init` | 前端入口 | C6 |
| P2 | 审查当前改动 | CX `/review`（`command/template/review.txt` 是 OD 的同类）；HM `review_engine.py` | △ 「让审查员检查」 | ✔ | 对比 CX 和 OD 的审查提示词 | C6 |
| P3 | worktree | CX `/worktree`；HM `subagent_worktree.py` | ✔ | ✔ | — | — |
| P4 | 代码地图、语义搜索 | 11 家都没用向量检索；Atlas 有 `coding_repo_map`、`ast_grep` | ✔ | — | 保留 | — |

## 11. Atlas 已有、要保留并接到新内核上的

界面层的 170 项（`docs/PARITY.md`）都保留。下面这些和内核直接相关，C1 必须接通，否则就是功能倒退：

- 运行事件协议（`frontend/src/renderer/services/runtimeEvents.ts` 已知的全部事件）、断线续传
- 插话、排队、暂停和继续、停止
- 审批（`ask_writes`、`read_only`）、提问卡片、项目信任卡片
- 检查点、撤回和重做、改动面板的 diff
- 计划模式、Goal、旁问、配方、规格（Specs）
- 子任务、并行 Worker、看板工具、项目记事本、项目资料检索
- SSH 远程工作目录、隔离分支（worktree）、附加目录、只限工作目录
- 用户 Hooks、自定义脚本工具、MCP、技能
- 用量统计、提示缓存、输出上限、出错切换模型
- 外部 Agent 执行（Claude Code、Codex 作为可切换选项，走 `runtime/backends.py`，不经过新内核）

## 12. 不在本表（冻结，等主体实测通过后再排）

原 W08（MCP Apps、连接器目录、飞书/钉钉/邮件渠道、Webhook 等触发器）、W09（cua 后台电脑操作、浏览器全套、扩展）、W10（局域网网页版、设备互联、分享链接、Univer、仪表盘）、W12（上游自动跟踪、产品动态、技能自学）、W13（语音前端、统一入口、A2A、协作、创作、无界面运行）。任务书保留在 `tasks/taskbooks/`，文件头已标「冻结」。

**例外**：跟上 Hermes 上游更新不用等 W12。C1 采用保留原目录结构的方式搬入，以后用 `git subtree pull` 合并上游即可，做法写在 `EXECUTION-GUIDE.md` 第三点六节。
