# ATLAS-C2-TOOLS-CONTEXT：工具与上下文升级

> **当前正式任务。执行模型：GPT-6 Luna，reasoning=high。**
> 前提：C1R 已验收通过。不要回头重做 C1，不要开始 C3。
> 目标是直接把 C2 需要的能力补到可用，不做大而空的重构，不做复杂测试工程。

先读：
- `docs/plan/ROADMAP-TO-PRODUCT.md`
- `docs/plan/00-MASTER-PLAN.md`
- `docs/plan/CORE-PARITY.md` 中 C2 对应行：L3、T3、T5、X1、X5、X10
- `docs/plan/EXECUTION-GUIDE.md`
- `tasks/reviews/ATLAS-C1R-FINISH.review.md`

工作目录：`D:\Atlas`。Hermes fork：`D:\hermes-agent` 的 `atlas` 分支。开工前两边拉最新。

## 本波必须完成

### 1. 删除 legacy LangGraph 循环和陈旧测试

Atlas 默认内核已经是 Hermes，C2 把旧循环正式删掉。

删除/收口：
- `core/atlas/agent/__init__.py` 里只服务 legacy 的 LangGraph graph、think/execute nodes、MAX_TOOL_ROUNDS、旧 prompt 路径；
- legacy engine 配置和前端内核切换；
- 不再使用的 LangGraph 依赖；
- 只为 legacy 存在的测试。

**不要误删** Hermes 仍复用的 Atlas 工具 handler、local execution、权限、checkpoint、事件桥接。

同时处理 C1R 验收记录里的 4 个陈旧失败：
- legacy 流式模型名契约：随 legacy 测试删除/改成 Hermes 等价；
- terminal 默认 PowerShell 的旧断言：按当前“Git Bash 优先，PowerShell 回退”行为改测试；
- 新旧内核内部 tool name/args 必须完全相同的断言：删除，保留对外事件兼容测试；
- 并行子 Agent fake responder：只修 fixture，让父轮拿到 tool result 后返回完成文本，不得为假测试改生产委派逻辑。

这一步结束后，测试基线不能再因为这 4 个旧契约红。

### 2. L3：防原地打转

Hermes 已有 repetition guard；Atlas 只补“同一轮反复改同一个文件”的提醒。

直接做：
- 对 `patch` / `write_file` 按当前 run + 文件路径计数；
- 默认第 6 次开始，在工具结果末尾追加一句短提醒，让模型换思路；
- 新 run 自动清零；
- 阈值可配置，但只加一个简单整数配置，不建新子系统。

不要阻止工具执行，不做自动回滚，不做复杂启发式。

### 3. T3：read_file 直接读图片

优先复用 Hermes 的图片预处理/vision 能力和 Codex `view_image` 的做法。

要求：
- `read_file` 遇到 png/jpg/jpeg/webp/gif/bmp：
  - 当前模型支持视觉：把图片内容直接返回模型；
  - 不支持视觉但配置了视觉模型：走已有 `vision_analyze`；
  - 两者都没有：返回清楚提示。
- 大图复用 Hermes 现有 resize/prep，不自造第二套。
- 前端工具结果里图片显示缩略图。

### 4. T5：编辑容错取 Hermes + OpenCode 的并集

来源：
- Hermes `tools/fuzzy_match.py`
- OpenCode `packages/opencode/src/tool/edit.ts`

先读两边源码，只搬 Hermes 没有、OpenCode 确实更强的 matcher。不要为了“凑 9 种”重复实现等价策略。

硬要求：
- 空白/缩进/边界等常见轻微差异能匹配；
- 多处命中仍必须报错，不允许猜着改；
- 保留 CRLF/LF/BOM 行为。

结果文件只需列：新增了哪几种、为什么值得搬。不要写长研究报告。

### 5. X5：按模型族补短提示词

基于 Hermes 现有 prompt builder，参考 OpenCode 各模型 prompt。

支持：
- Claude
- GPT/Codex
- Gemini
- DeepSeek
- Kimi
- GLM
- Qwen
- MiniMax
- 默认

每份只放**这个模型族真正需要的工具调用/行为差异**，不要复制一大套通用 system prompt。稳定内容进入 Hermes 稳定层，同一会话不能每轮变化。

不要为了 token 数做复杂测量；只保证明显短小。

### 6. X1：压缩摘要打磨

保留 Hermes `ContextCompressor` 主体，不重写。

参考 Pi 的结构化摘要，把摘要固定包含：
- 当前目标/约束
- 已完成
- 正在做/阻塞
- 关键决定
- 下一步
- 关键文件

已有 todo、文件跟踪、工具输出裁剪逻辑能复用就复用。连续压缩后这些字段仍在即可。

不要做 benchmark、打分器或大规模 compaction eval。

### 7. X10：换干净上下文

参考 Codex `new_context_window`，在现有 Hermes 会话上实现最小版本：

调用 `new_context_window` 后：
1. 生成一份和第 6 节同格式的交接摘要；
2. 下一模型上下文只带稳定 system prompt + 交接摘要 + 当前 todo；
3. Atlas 对话历史仍完整保留；
4. 前端时间线显示一条“已切换到新上下文”的分隔事件。

不要创建第二套会话系统，不复制历史数据库。

### 8. Git Bash 回退

把 C1R 暴露的 shell 语义收口：
- Windows 默认优先真实 Git Bash；
- 找不到 Git Bash才用 PowerShell；
- PATH 里如果先出现 WSL bash，不能误当 Git Bash；
- 用户显式指定 powershell/cmd/bash 时尊重选择。

## 最小验证

禁止过度验收。只做：

1. 每个本波功能 1–3 个最小聚焦测试；
2. 一条假模型 WebSocket E2E，串起：读图片 → 容错编辑 → 同文件反复修改触发提醒 → 压缩 → new_context_window → 完成；
3. legacy 删除后，后端全量 pytest **只跑一次**；
4. 前端四项各一次：renderer tsc、electron tsc、Vitest、Vite build。

不跑真实模型、不跑真实网络服务、不做截图矩阵、不重复全量。

## 硬约束

- **禁止过度防御编程**：不堆 fallback、兼容层、额外状态机、重复 try/catch、未来式抽象。
- **禁止过度验收**：只验证本波真实行为，不为了数字重复跑测试。
- 有成熟实现直接搬/改，不写缩水版。
- Atlas 专属代码留 Atlas；只有确实属于 Hermes 内核能力的修改才进 fork。
- 不放宽 `core/atlas/origin_guard.py`。
- 不做安全审查功能，`core/atlas/safety/` 保持默认关闭。
- 不碰真实用户数据和 `design/`。
- 不开始 C3。

## 交付

完成后：
1. 更新 `docs/plan/CORE-PARITY.md`：L3、T3、T5、X1、X5、X10；
2. 必要的上游搬入登记 `docs/plan/VENDORED.md` / `THIRD_PARTY_NOTICES.md`；
3. 写 `tasks/results/ATLAS-C2-TOOLS-CONTEXT.result.md`：
   - 每项做了什么；
   - Atlas/Hermes 提交号；
   - 搬了哪些上游实现；
   - 聚焦测试；
   - 一次全量 pytest 汇总；
   - 前端四项结果；
   - 仍有的真实缺口。
4. `tasks/CURRENT.md` 改成 `AWAITING_REVIEW`；
5. pull --rebase → push → 核对远端 HEAD，然后停止。

**完成后由 ZCode 通知上游规划者验收；不要自行进入 C3。**
