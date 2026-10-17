# Atlas 全局审查交接

**状态：AWAITING_GPT6_REVIEW**。自测与静态复核不等于网页ChatGPT GPT-6独立验收通过。本轮没有merge、部署或修改真实运行实例。

## 固定基线与交付

- 仓库：unicorn-Y/Atlas。
- 任务书：task/luna-audit-model-policy-20261017@1557f612604a634ebad28728c2787a8085cfa946。
- 真实源码根：D:\Atlas，ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f，12个tracked dirty文件及研究untracked内容原样保留。
- 运行归因（第二轮更正）：审查期间观测到三代：Electron55644 → Python1800/53140（早期）→ Python51284/50140（16:54:17）→ **Python33572/70348（17:36:05 收尾时，属正常使用重启）**；8765后端、9335 CDP。命令行与 cwd 始终 `D:\Atlas\core`。工作进程 `cwd` 实测 `D:\Atlas\core`，**运行内容已核定为 `0b1ba411` + 12 处未提交修改的工作区快照**（相关文件 mtime 均早于后端启动）。实时默认deepseek-v4.1-flash、记忆gemini-3.8-flash。另有一条 `D:\atlas-mem-integrate` 实例跑 9459，不在本轮范围。
- W1代码分支：fix/atlas-model-retry-policy-20261017；最终commit：e259978420f944ef57bdb15ed22a8890486c018e。
- 文档分支：review/atlas-luna-global-audit-20261017。首次交付commit：`f69f8b212d3c004c98bfb9c288610709ae49c18b`；文件内不自引用自身 tip SHA，分支最终 tip 由聊天交付给出。
- 代码分支只实施W1；文档分支只包含tasks/reviews/atlas-luna-20261017下审查产物。

## 覆盖结果

74个远程refs为审查开始快照（第二轮现场为77个，新增 `fix/atlas-model-retry-policy-20261017`、`review/atlas-luna-global-audit-20261017`、`task/hermes-atlas-implementation-20261017`，后者已补审，详见07 §4）：37个标记absorbed（36个tip是基准祖先、1个为`ui-redesign`自身）、36个分叉、1个基准后继；72个tip SHA/tree组。谱系收敛22个最大SHA组/23 refs，其中14个代码独有候选组。另核本地独有分支、worktree dirty源文件和本机真实进程。新增本轮交付分支不倒灌进74快照。

405项canonical ID逐一重新判定：已做107、部分218、未做67、原有13。这里的“已做”表示当前基线源码的入口/调用链已实现，不能解释为405项实机验收。ABSORB 17项全部列出，同义映射去重后另有5个独立议题。未把装饰性或云端商业能力提升为本轮P0；旧ledger_priority单独保存，不计入问题优先级。

去重问题总账25项：P0=0、P1=14、P2=11。W1覆盖其中7个P1症状（原3个 + 第二轮补录ATL-022/023/024/025）；其他仅审查。候选分支风险、功能缺口和待验证项在02明确区分，不混写为本机复现。

## 最紧急的10项

| 问题 | 优先级 | 状态 |
|---|---|---|
| ATL-001 同模型有限重试、取消隐式fallback | P1 | W1已修，待独立验收 |
| ATL-005 模型失败后暂停队列、保留待发项 | P1 | W1已修，待独立验收 |
| ATL-006 错误卡保留具体上游原因和结构化字段 | P1 | W1已修，待独立验收 |
| ATL-002 静默长工具执行期间停止请求延迟 | P1 | 代码确认，未施工 |
| ATL-008 Dream全局checkpoint跳漏迟到经历 | P1 | 代码确认，未施工 |
| ATL-009 Dream旧快照覆盖并发手动编辑 | P1 | 代码确认，未施工 |
| ATL-010 队列三次失败后无恢复入口 | P1 | 代码确认，未施工 |
| ATL-014 来源timestamp最近匹配而非exact UID | P1 | 代码确认，未施工 |
| ATL-017 默认开启CDP并允许任意Origin | P1 | 代码+端口观察；未测跨主机 |
| ATL-018 原地更新构建失败仍可能重启半更新版 | P1 | 代码确认，未故障注入 |

## 索引

1. [00-LOCAL-BASELINE.md](00-LOCAL-BASELINE.md)：真实运行与主目录保护证据。
2. [01-ALL-BRANCHES.md](01-ALL-BRANCHES.md)：74分支、local refs与独有候选；原始索引在evidence。
3. [02-ISSUES.md](02-ISSUES.md)：21项完整问题字段与最小建议。
4. [03-FEATURE-405.md](03-FEATURE-405.md)：405项及17项ABSORB；可机读总表在modules/W7-FEATURES.json。
5. [04-LOCAL-VERIFY.md](04-LOCAL-VERIFY.md)：实测结果、已有失败与未测边界。
6. [05-INTEGRATION-PLAN.md](05-INTEGRATION-PLAN.md)：14代码候选组按能力吸收方案，未授权施工。
7. [06-MODEL-RETRY-FIX.md](06-MODEL-RETRY-FIX.md)：W1补丁、精确命令、输出与限制。
8. modules/W2–W6与ROOT-ADDITIONAL：各模块实际调用链、跨分支证据、记忆V4.1研究差异和语音/视觉后续计划。

## 验证与尚不能确认

W1最终后端定向整文件 38 passed、5 warnings；timeline17 passed；失败队列1 passed/24 skipped；renderer tsc exit0。clean基线完整store测试3 failed/21 passed，具体夹具/React问题见06；没有把定向通过写成全部测试通过。W5三个既有用例分别1 passed；它们不覆盖本轮提出的并发/迟到故障。

未使用真实provider token，未做Electron手工错误卡验收，未运行真实电脑输入、SSH/Android/渠道或插件安装。未读写真实会话/记忆、未执行Dream/迁移/忘记；未做V4.1施工。逐会话模型、全套回归、安装包/冷启动、真实并发Git恢复仍未确认。**已在第二轮收口**：运行进程的实际加载内容（cwd + mtime 双证据，见07 §1）；W1 七条策略的独立实测（自建假网关，W1 9/9、运行版 6/9，见04b 与 evidence/W1-VERIFY.json）；W1 落到运行态的合并可行性（实测 1 处冲突，语义消解后测试通过，补丁已产出，见07 §3/ATL-025）。

独立代码复核已纠正error_category映射、malformed tool-call重试、长Retry-After、HTTPX流式错误正文及非瞬态HTTP状态过宽分类。错误正文读取最多16KiB、共享redactor清洗、卡片详情限1000字符；不承诺识别任意未知secret格式。

## GPT-6验收重点

审查固定W1 commit相对0b1ba的diff，核对主/辅助模型无自动换模与总请求上限，partial输出不重发、无工具副作用重放、永久错误和取消即时终止、错误原因与队列状态。审查总账的证据与分类是否匹配，并决定其余问题后续施工任务。验收前不把本轮标为PASS，不直接合并14候选分支。

## 第二轮交接补遗（2026-10-17 复核）

**新增实测结论（全部为亲自跑出，非引用旧报告）**

1. 用户当前运行的**不是**干净的 `0b1ba411`，而是该 commit 加 12 处未提交修改的工作区快照；其中 `expert_harness.py` 会改变 `content_filter` 的处理语义（改写措辞重发而非报错）。
2. W1 七条策略：W1 分支 **9/9 通过**；用户运行版 **6/9**。运行版最刺眼的是「流式已输出部分文本后重发导致文本重复」（实测 `'half answerduplicate'`），以及默认配置下 503 会打 **11 次**请求（任务书允许 3 次）。
3. W1 可以落到运行态，但需要一次语义裁量：`model_call.py` 的 content_filter 块冲突。按任务书取 W1 一侧后，`ast.parse` 通过、定向测试 38 passed。补丁：`D:/Temp/luna-audit-20261017/w1-runtime-integration.patch`。
4. `models/router.py::complete_for` 的硬编码 DeepSeek 追加确认**运行期可达**，覆盖规划/反思/MoA/压缩/摘要，失败时用户完全无感。
5. 分支数 74 → 77；`task/hermes-atlas-implementation-20261017` 已补审：3 个 commit 全为文档，**Atlas 源码改动 0 行**，其任务书承诺的代码施工与 `tasks/results/` 全部缺失。

**仍需用户裁决的唯一一项**

ATL-022/ATL-025：按任务书，`content_filter` 必须终止且不得用提示词改写绕过；这与当前 `expert_mode: true` 下 `CONTINUE_FILTER_GUIDANCE` 的行为直接冲突。要「符合任务书」就得删掉 expert 的改写重发。此项涉及用户既有的使用习惯，本轮只给证据与冲突位置，未擅自改用户工作区。
