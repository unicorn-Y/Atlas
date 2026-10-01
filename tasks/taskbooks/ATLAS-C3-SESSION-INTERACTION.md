# ATLAS-C3：会话与交互

> 先读 ROADMAP-TO-PRODUCT、CORE-PARITY（标 C3 的行和第 11 节）、EXECUTION-GUIDE。前提：C2 验收通过。
> 这一波量大，主控要拆成后端组和前端组，按文件分工并行做。

## 本波目标

把用户每天和 Atlas 打交道的那部分（插话、撤回、会话、权限、计划、命令、状态显示、子 Agent）做到 Claude Code、Codex、ZCode 里最好的水平。
做完以后，CORE-PARITY 里 L6、S2、S3、I1、I2、I3、I5、I6、I7、X7、A2、A4 都是 ✔。

**参考草稿**：分支 `wip/c3-frontend-from-laptop`，是旧会话按旧内核写的一版界面：
- Worker 组卡片、后台完成卡片、会诊卡片；
- 待办条、「运行方式」菜单里的会诊开关；
- 团队看板、「设置 → 子 Agent」、项目记事本。

可以参考它的界面结构，也可以挑着搬（cherry-pick），**但每个事件和字段都要对照新内核实际发出的事件重新核对**，不能直接合并。

## 1. 中途转向（L6）

- **来源**：Codex 0.159 的 `instant_interrupt`。用户的新输入在模型输出到一半时就能生效，不必等这一步结束。见 `codex-rs/features/src/lib.rs` 里的开关，以及 `codex-rs/core/tests/suite/pending_input.rs` 里的测试场景。Hermes 侧是 `agent/interrupt_control.py` 的 `steer`。
- **做法**：
  - 插话分两档：
    - 「下一步生效」：现有行为，等当前这一步结束；
    - 「立即转向」：中断当前的模型输出，已经输出的部分保留在记录里并标注「被用户打断」，然后带着新输入重新请求。
  - 正在执行的工具不打断，等它执行完再转向。
  - 前端的插话框加一个开关，选择用哪一档，默认「下一步生效」。
- **测试**：模型流式输出到一半时插话，下一次请求里包含已输出的部分和新输入；工具执行中插话，工具照常执行完。

## 2. 会话树和分支摘要（S2）

- **来源**：
  - Pi `packages/coding-agent/src/core/session-manager.ts`：一个文件里存整棵会话树，`/tree` 可以在分支之间切换；
  - Pi `core/compaction/branch-summarization.ts`、`docs/compaction.md` 的「Branch Summarization」一节；
  - Hermes 的 `/branch`。
- **做法**：
  - Atlas 现有的分叉树界面（F090）改成以 Hermes SessionDB 的分支关系为准。
  - 切换到另一个分支时，照 Pi 的做法，把离开的那条分支自动总结成一条摘要，挂在分叉点上，回来时可以看。
- **测试**：分叉 → 两条分支各自继续 → 来回切换，记录都对；分支摘要生成并显示出来。

## 3. 两套检查点合一（S3）

- **现状**：Atlas 自己有 `core/atlas/agent/checkpoints.py`（影子 git，写前建快照）；Hermes 有 `tools/checkpoint_manager.py`、`/rollback`、`/snapshot`，C1 时关掉了。
- **做法**：
  1. 先对比两套：快照粒度、大文件处理、清理策略、撤回对话的联动、Windows 下的表现，选更强的一套为主。
  2. 另一套的独有优点合并过来，比如 Hermes 的快照数量和总大小上限、清理策略。
  3. 撤回、重做、改动面板、文件历史版本这些界面不变。
- **测试**：撤回到某条消息之前，文件和对话一起回去；重做；超过上限后自动清理最旧的快照。

## 4. 五档权限（I1）

- **来源**：ZCode 的五档，Shift+Tab 循环切换：
  1. 每步都问；
  2. 改前问我（现有的 `ask_writes`）；
  3. 自动改文件，但运行命令要问；
  4. 计划模式；
  5. 完全访问（默认）。

  另外保留现有的「只读」。
- **做法**：扩展 C1 的权限插件（`core/atlas/engine/hermes_policy.py`）；输入框的权限菜单显示五档，加上「只读」；按 Shift+Tab 循环切换；按对话保存。
- **不做**：Claude Code 那种「自动模式」分类器。那属于安全审查，用户自己做。
- **测试**：每一档对文件写入、命令、MCP、子 Agent 的拦截都正确；子 Agent 的权限不超过父级。

## 5. 计划模式开放只读命令（I2）

- **来源**：Claude Code 的计划模式，最后用 ExitPlanMode 交出计划；OpenCode `packages/opencode/src/tool/plan.ts` 和 `plan-enter.txt`、`plan-exit.txt`；Hermes `agent/plan_prompt.py`；Codex 判断「已知安全的命令」的那段逻辑，在 `codex-rs/shell-command` 或 `codex-rs/execpolicy` 里找 `is_known_safe_command` 一类的函数。
- **做法**：
  - 计划模式下允许只读命令：`git status/log/diff/show`、`ls`、`dir`、`rg`、`cat`、`type`、`Get-Content` 等。判断函数从 Codex 翻译过来，**整份搬，不要自写缩水版**。
  - 计划写完后用「提交计划」工具交出来（对应 Claude Code 的 ExitPlanMode）；前端的计划卡片沿用现有的。
- **测试**：只读命令放行；会写入的命令（`git commit`、重定向写文件、`rm` 等）被拦下。

## 6. 对话内的 Goal（I3）

- **来源**：Codex `/goal`；ZCode `/goal`（设一个能验证的目标，不断迭代直到验证通过）；Hermes `/goal`、`/subgoal`。
- **做法**：在对话里输入 `/goal 目标 [验证方式]` 就启动持续目标，走 Hermes 的 goal 机制；运行头部显示目标和进度；自动化页里已有的「持续目标」也改走同一套。
- **测试**：设定目标后，假模型几轮迭代，验证通过才结束；可以暂停、替换。

## 7. 斜杠命令补齐（I5）

1. 先做一张对照表：Codex（`codex-rs/tui/src/slash_command.rs`，约 60 条）、Hermes（`hermes_cli/commands.py`，约 100 条）、Claude Code（看官方文档，约 50 条）。每条标上「主体相关 / 外部功能 / 不适用」。
2. 主体相关的全部实现，至少包括：`/model`、`/context`、`/diff`、`/review`、`/init`、`/resume`、`/fork`、`/undo`、`/redo`、`/status`、`/usage`、`/compact`、`/goal`、`/plan`、`/btw`、`/permissions`、`/mcp`、`/skills`、`/hooks`、`/agents`、`/export`、`/rename`、`/new`、`/clear`、`/ps`、`/stop`、`/copy`。
3. 输入 `/` 弹出的菜单按分组显示，支持模糊搜索。
4. 对照表写进结果文件。

## 8. 状态栏（I6）

- **来源**：Codex `/statusline`，可以配置显示哪些项；Claude Code 的状态栏。
- **做法**：对话底部加一条状态栏，可以显示：模型、推理档位、上下文占用百分比、本次花费、分支、权限档位、运行中的后台进程数。显示哪些项由用户在设置里勾选。

## 9. 上下文构成（X7）

- **来源**：Claude Code `/context`；Hermes `agent/context_breakdown.py`；Codex `get_context_remaining`。
- **做法**：`/context` 和右栏「上下文」页显示一个分项条：系统提示词、工具定义、规则文件、记忆、历史消息、工具输出各占多少 token，以及上限。数据来自 Hermes 的 `context_breakdown`。

## 10. 后台任务面板（I7）

- 接 Hermes 的进程表（`tools/process_registry.py`）：看输出、结束进程、看结束通知；`/ps`、`/stop`。

## 11. 子 Agent 的验收和界面（A2、A4）

- **后端（A2）**：W07 的并行验收逻辑在新内核上重写，修掉 W07B 第一节写的那个误判（见 `tasks/taskbooks/ATLAS-W07B-ORCHESTRATION-COMPLETION.md` 第一节）。
- **前端（A4）**，参考 `wip/c3-frontend-from-laptop`，对照新内核的事件做：
  - Worker 组卡片：每个子任务显示「已验收 / 未通过」，点开看结果和验收意见；
  - 后台完成卡片、会诊卡片；
  - 待办条：输入框上方，默认折叠成「待办 2/5 · 正在做：…」；
  - 子任务的「补充要求」入口；
  - 「设置 → 子 Agent」：五家定义文件的列表、启用和停用、默认模型；
  - 团队看板；
  - 项目记事本：右栏「上下文」页，可以编辑 `NOTES.md`。
- **用户的界面要求**：要美观；放不下的做成可折叠的。

## 12. 测试（假模型，从 WebSocket 发起）

每节各自的测试，加两条端到端：
1. 立即转向 → 分叉 → 切分支 → 撤回 → 重做；
2. 计划模式出计划 → 切到「自动改文件但命令要问」执行 → 子 Agent 并行，其中一个验收不通过后重派 → 完成。

## 13. 交付

- 结果文件写清：每节做了什么、检查点的对比结论、斜杠命令对照表、从 wip 分支搬了哪些部分。
- 更新 CORE-PARITY；前端四项检查通过；无头 Edge 截图，每个新界面至少一张，浅色和深色主题都要截。

## 验收清单

1. 列出的 12 行 CORE-PARITY 都做到「最强做法」写到的细节。
2. wip 分支搬过来的界面，事件和字段都对照过新内核，没有只在旧内核下才能用的代码。
3. 截图检查：好看、不挤；放不下的内容可以折叠。
4. 已有功能不倒退。
