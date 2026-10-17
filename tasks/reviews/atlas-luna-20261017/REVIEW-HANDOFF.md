# Atlas 全局审查交接

**状态：AWAITING_GPT6_REVIEW**。自测与静态复核不等于网页ChatGPT GPT-6独立验收通过。本轮没有merge、部署或修改真实运行实例。

## 固定基线与交付

- 仓库：unicorn-Y/Atlas。
- 任务书：task/luna-audit-model-policy-20261017@1557f612604a634ebad28728c2787a8085cfa946。
- 真实源码根：D:\Atlas，ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f，12个tracked dirty文件及研究untracked内容原样保留。
- 运行归因：Electron55644 → Python1800 → Python53140；8765后端、9335 CDP。实时默认deepseek-v4.1-flash、记忆gemini-3.8-flash；逐会话模型和进程加载的精确源码字节未核实。
- W1代码分支：fix/atlas-model-retry-policy-20261017；最终commit：e259978420f944ef57bdb15ed22a8890486c018e。
- 文档分支：review/atlas-luna-global-audit-20261017。最终文档commit由主执行者push后在聊天交付；本文件随该commit发布，无自引用SHA。
- 代码分支只实施W1；文档分支只包含tasks/reviews/atlas-luna-20261017下审查产物。

## 覆盖结果

74个远程refs为审查开始快照：37祖先、36分叉、1后继；72个tip SHA/tree组。谱系收敛22个最大SHA组/23 refs，其中14个代码独有候选组。另核本地独有分支、worktree dirty源文件和本机真实进程。新增本轮交付分支不倒灌进74快照。

405项canonical ID逐一重新判定：已做107、部分218、未做67、原有13。这里的“已做”表示当前基线源码的入口/调用链已实现，不能解释为405项实机验收。ABSORB 17项全部列出，同义映射去重后另有5个独立议题。未把装饰性或云端商业能力提升为本轮P0；旧ledger_priority单独保存，不计入问题优先级。

去重问题总账21项：P0=0、P1=10、P2=11。W1覆盖其中3个P1症状；其他仅审查。候选分支风险、功能缺口和待验证项在02明确区分，不混写为本机复现。

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

未使用真实provider token，未做Electron手工错误卡验收，未运行真实电脑输入、SSH/Android/渠道或插件安装。未读写真实会话/记忆、未执行Dream/迁移/忘记；未做V4.1施工。真实进程精确加载字节、启动后磁盘编辑顺序、逐会话模型、全套回归、安装包/冷启动、真实并发Git恢复均未确认。

独立代码复核已纠正error_category映射、malformed tool-call重试、长Retry-After、HTTPX流式错误正文及非瞬态HTTP状态过宽分类。错误正文读取最多16KiB、共享redactor清洗、卡片详情限1000字符；不承诺识别任意未知secret格式。

## GPT-6验收重点

审查固定W1 commit相对0b1ba的diff，核对主/辅助模型无自动换模与总请求上限，partial输出不重发、无工具副作用重放、永久错误和取消即时终止、错误原因与队列状态。审查总账的证据与分类是否匹配，并决定其余问题后续施工任务。验收前不把本轮标为PASS，不直接合并14候选分支。

