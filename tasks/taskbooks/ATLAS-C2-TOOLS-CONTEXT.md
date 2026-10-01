# ATLAS-C2：零件升级——工具与上下文

> 先读 `docs/plan/ROADMAP-TO-PRODUCT.md`、`docs/plan/CORE-PARITY.md`（所有标 C2 的行，以及第 11 节）、`docs/plan/EXECUTION-GUIDE.md`（第三点五、三点六、第五节）。
> 前提：C1 验收通过。

## 本波目标

把内核里「工具」和「上下文」这两块，逐项换成各家最强的做法，同时删掉旧的 LangGraph 循环。
做完以后，CORE-PARITY 里 L3、T3、T5、X1（打磨）、X5、X10 都是 ✔，旧循环不复存在。

**凡是 CORE-PARITY 里标了「初判」的，第一步都是逐行比较两家的源码，选强的那家**，比较结论写进结果文件。

参考仓库都是浅克隆到系统临时目录里用：
- OpenCode：`sst/opencode`
- Pi：`badlogic/pi-mono`
- Codex：`openai/codex`
- Hermes 就是 `D:\hermes-agent`

## 1. 删除旧循环（先做，单独一块）

1. 把旧路径专属的代码找出来，用 grep 加覆盖率证明它们只在 `engine = "legacy"` 时才会被用到：
   - `core/atlas/agent/__init__.py` 里的 LangGraph 图（`_build_graph`、`_think_node`、`_execute_tools_node`、`MAX_TOOL_ROUNDS`、`SYSTEM_PROMPT` 的旧用法）；
   - `agent/enrichment.py` 的 `ContextMaintenance`；
   - 旧的 `prompt_caching.py` 调用；
   - 旧工具里已经被 Hermes 替代的部分。
2. **注意**：C1 的提交 `1ec29f3` 让 Atlas 工具注册表复用了一部分 `tools/local_execution.py` 的旧语义。新内核还在用的函数要保留，只删真正只有旧路径才用的。
3. 删除 `engine` 配置项和设置页里的内核切换（C1 那一波的临时设置），以及 LangGraph 依赖。
4. 在 C1 里固定跑旧内核的那 6 个测试（`legacy_agent_engine` fixture）：能改成测新内核的就改；测的是旧内核专有行为的就删除，并在结果文件里逐个说明。
5. 全量测试必须通过。

## 2. 防原地打转（L3）

- **来源**：LangChain 的 LoopDetectionMiddleware（同一个文件改了 N 次后，提醒模型换思路）；Hermes `agent/repetition_guard.py`（已有，负责检测重复的工具调用）。
- **做法**：在 `core/atlas/engine/` 的插件里挂 `post_tool_call`，按「本轮、同一个文件」统计 `patch` 和 `write_file` 的次数，默认阈值 5，可在 `atlas.toml` 里配置。超过后，**把提醒追加在这次工具结果的末尾**，比如「这个文件本轮已经改了 6 次，先停下来想想是不是方向不对」。
- **为什么写在工具结果里**：不能插入新的用户消息，也不能改系统提示词。这是 Hermes 的硬规则，否则缓存会失效、消息的角色交替也会被打乱，见 Hermes `AGENTS.md`。
- **测试**：假模型连续改同一个文件 6 次，第 6 次的工具结果里出现提醒；换一个文件不触发；新的一轮重新计数。

## 3. 读图片（T3）

- **来源**：Claude Code 的 Read 工具能直接读图；Codex `codex-rs/core/src/tools/handlers/view_image.rs`；Hermes `tools/vision_tools.py`（C1 时关掉了）。
- **做法**：
  - `read_file` 读到图片（png/jpg/jpeg/gif/webp/bmp）时：
    - 当前模型支持看图（看模型的元数据，或用户在模型设置里勾选的「支持图片」）→ 直接把图片作为内容返回给模型；
    - 不支持看图 → 返回提示，并在配置了视觉模型时自动调用 `vision_analyze`。
  - 图片太大就先缩小（参考 Hermes `vision_tools_image_prep.py`）。
  - 在 Hermes fork 里改 `read_file`，或者在 Atlas 工具层包一层，选改动小的那种。
- **前端**：时间线里「读文件」这一步如果读的是图片，显示缩略图。
- **测试**：支持看图和不支持看图两条路径；超大图片会被缩小。

## 4. 编辑容错取并集（T5）

- **来源**：Hermes `tools/fuzzy_match.py`（9 种策略）；OpenCode `packages/opencode/src/tool/edit.ts`（9 种 Replacer：Simple、LineTrimmed、BlockAnchor、WhitespaceNormalized、IndentationFlexible、EscapeNormalized、MultiOccurrence、TrimmedBoundary、ContextAware），以及它的测试（`packages/opencode/test/` 下找 edit 相关的）。
- **做法**：
  1. 列一张对照表，逐项比较两家的策略，看哪些等价、哪些只有一家有，写进结果文件。
  2. 把 OpenCode 独有的策略翻译成 Python，加进 fork 的 `fuzzy_match.py`，策略顺序参照 OpenCode。
  3. 把 OpenCode 的编辑测试用例翻译过来，一起搬。
- **测试**：OpenCode 的用例全部通过；Hermes 原有的用例不倒退。另外，匹配到多处时必须报错，不能乱改。

## 5. 按模型分别写提示词（X5）

- **来源**：
  - OpenCode `packages/opencode/src/session/prompt/`：anthropic、gpt、gemini、kimi、codex、beast、trinity 等十几份；
  - Hermes `agent/prompt_builder.py` 里按模型族加的指引（`TOOL_USE_ENFORCEMENT_MODELS`、`GOOGLE_MODEL_OPERATIONAL_GUIDANCE` 等）；
  - Pi 的经验：提示词要短，越短越好。
- **做法**：
  1. 在 `core/atlas/engine/prompts/` 下按模型族建文件：claude、gpt、gemini、deepseek、kimi、glm、qwen、minimax，外加一份默认。国产模型的内容参考 OpenCode `kimi.txt` 的写法，再结合各家官方文档里对 Agent 和工具调用的建议，查当月的资料。
  2. 按模型名或服务商选用哪一份，放进 Hermes 三层提示词的**稳定层**，整个会话不变。
  3. 每份控制在 600 token 以内，结果文件里写上每份的实际 token 数。
- **测试**：不同的模型名选到正确的那一份；同一个会话里，系统提示词每次都逐字节相同。

## 6. 压缩打磨（X1）

- **来源**：
  - Hermes `agent/context_compressor.py`（现在在用的）；
  - Pi `packages/coding-agent/src/core/compaction/compaction.ts`、`branch-summarization.ts`，以及 `docs/compaction.md`（结构化摘要的格式：目标、约束和偏好、进度（已完成 / 进行中 / 受阻）、关键决定、下一步、关键上下文；切分点的规则；文件累计跟踪）；
  - OpenCode `packages/opencode/src/session/compaction.ts`（先修剪旧的工具输出）。
- **做法**：
  1. 先对比三家的摘要模板、切分规则、触发阈值，写进结果文件。
  2. 把 Hermes 的摘要提示词换成 Pi 的结构化格式，或者两者合并，选更好的。
  3. 摘要里保留「改过和读过的文件清单」，照 Pi 的累计文件跟踪。
  4. 用 Hermes 的 `evals/compaction/`（如果有）或者自建假模型评测，比较改前改后：压缩后继续干活时，能不能答出关键事实（文件名、决定、待办）。
- **测试**：压缩后的摘要包含六个部分和文件清单；连续压缩两次，信息不丢。

## 7. 换个干净的上下文（X10）

- **来源**：Codex `codex-rs/core/src/tools/handlers/new_context_window.rs`、`new_context_window_spec.rs`。
- **做法**：新增工具 `new_context_window`，模型在上下文快满或者任务阶段切换时可以调用。调用时：
  1. 先写一份交接摘要，格式同第 6 节；
  2. 开一个新的上下文，内容只有系统提示词、交接摘要和待办；
  3. Atlas 的对话记录里留一个「已换新上下文」的标记，前端显示成一条分隔线。
- **测试**：调用之后，下一次发给模型的请求只包含摘要；对话记录完整保留，可以回看。

## 8. C1 的遗留

- 如果 C1 验收记录里还有转到 C2 的项，一起做。
- 核实 Git Bash 的识别：已安装 Git Bash、但 PATH 里 WSL 的 bash 排在前面时，要选 Git Bash。

## 9. 前端

- 读图片显示缩略图；「已换新上下文」显示分隔线；防打转的提醒在时间线里显示成一条提示。
- 设置 → 模型：显示当前用的是哪一份提示词，只读。
- 四项前端检查通过；无头 Edge 截图。

## 10. 测试汇总（假模型，从 WebSocket 发起）

第 1 到第 7 节各自的测试，加上一条端到端：一个任务里依次经历读图片 → 编辑（需要容错匹配）→ 连续改同一个文件触发提醒 → 自动压缩 → 换新上下文 → 完成。

## 11. 交付

- 结果文件 `tasks/results/ATLAS-C2-TOOLS-CONTEXT.result.md`，写清：
  - 每节做了什么；
  - 三张对比表（编辑策略、压缩方案、提示词 token 数）；
  - 删掉了哪些旧代码；
  - 全量测试汇总行。
- 更新 CORE-PARITY（C2 各行改成 ✔，写上提交号）、`tasks/CURRENT.md`、`docs/plan/VENDORED.md`（登记 OpenCode、Pi、Codex 搬入的部分）、`THIRD_PARTY_NOTICES.md`（附上各项目的 LICENSE）。

## 验收清单

1. 旧循环和 LangGraph 已删干净，没有误删新内核在用的东西；全量测试通过。
2. 编辑策略的对照表里，每一项都有对应实现或者写明了不搬的理由；OpenCode 的用例全部搬过来并且通过。
3. 提示词稳定，每份不超过 600 token。
4. 压缩的评测有改前改后的对比数字。
5. 已有功能不倒退。
