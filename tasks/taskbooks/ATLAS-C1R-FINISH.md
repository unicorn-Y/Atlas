# ATLAS-C1R-FINISH：C1 收尾修复与交付

> **当前正式任务。执行模型：GPT-6 Luna，reasoning=high。**
> ZCode 只负责把本任务转给 Codex/通知结果，不负责改代码。
> 完成后由上游规划者独立验收；施工者不要自己宣布进入 C2。

## 目标

把 C1（Hermes 内核替换）剩余的真实缺口收掉，让 C1 达到“可以交给独立验收”的状态。不要扩大范围，不做 C2/C3，不重构已经能用的部分。

先读：
- `docs/plan/ROADMAP-TO-PRODUCT.md`
- `docs/plan/00-MASTER-PLAN.md`
- `docs/plan/CORE-PARITY.md`
- `docs/plan/EXECUTION-GUIDE.md`
- `tasks/results/ATLAS-C1-HERMES-CORE.result.md`
- `tasks/taskbooks/ATLAS-C1-HERMES-CORE.md`

工作目录：`D:\Atlas`。Hermes fork：`D:\hermes-agent` 的 `atlas` 分支。开工前两边都拉到最新。

## 必做

### 1. 修暂停后的多余模型请求

现象：命令已开始执行后点暂停，命令结束后 Hermes 仍可能发起下一次模型请求。

要求：
- 暂停生效后，不再发起下一次模型请求；
- 继续后能从当前状态继续；
- 暂停期间取消能正常结束；
- 只改真正相关的运行时/状态机代码，不额外加“保险层”。

补最小回归测试覆盖这三条即可。

### 2. 修“完整读完文件却被判成只读一部分”

复现并找到真实原因。优先修判定逻辑/工具结果语义，不要通过放宽所有检查来绕过。

补一个能稳定复现旧问题、修复后通过的测试即可。

### 3. 收掉 C1 仍影响实际使用的 Windows/Hermes 问题

按 `ATLAS-C1-HERMES-CORE.result.md` 里记录的 Hermes 源测试范围，**只复查与 Atlas 实际路径有关的失败**：文件读写/patch、MCP、SSH/terminal、压缩、plan prompt。

规则：
- 确实影响 Atlas：在 Hermes fork `atlas` 分支修掉；
- 明确属于 macOS/Linux 专用预期、Windows 不适用：在结果文件记清原因，不为了“全绿”改生产代码；
- 不重新制造大规模平台兼容层。

### 4. 核对 C1 未完成项

重点核对 C1 结果文件里原先未完成的：`L2、L4、T10、T11、T19、S4、A1`。

已经在后续提交里补齐的，直接用代码和现有测试证明并更新 `CORE-PARITY.md`；仍有真实缺口的就修。**不要为了逐行打勾重复实现已有功能。**

### 5. 交付验证

只做下面这些，不做额外测试矩阵：

1. 每个本次修复对应的聚焦测试；
2. C1 的 WebSocket 端到端脚本（如果仓库已有 `core/tests/test_c1_websocket_acceptance.py`，修好并跑它；没有就不要新造庞大框架）；
3. Atlas 后端全量 pytest **只跑一次**；
4. 前端现有四项检查 **各跑一次**：renderer tsc、electron tsc、Vitest、Vite build。

不要用真实模型、真实远端 MCP/SSH，不需要重新做无头浏览器截图，除非本次确实改了前端行为。

## 硬约束

- **禁止过度防御编程**：不要为理论异常堆 fallback、兼容层、重复 try/catch、额外抽象或“以后可能用到”的框架。只解决已复现的问题。
- **禁止过度验收**：一个 bug 一个最小回归；全量只跑一次；不要重复跑同一套测试来“增加信心”。
- 有成熟上游实现时直接搬/改，不从零造缩水版。
- 不放宽 `core/atlas/origin_guard.py`。
- 不做安全审查功能；`core/atlas/safety/` 保持默认关闭。
- 不做本地语音、不碰 C2/C3、不合并 `wip/c3-frontend-from-laptop`。
- 不碰用户真实数据目录；测试全部隔离到临时目录。
- `design/` 是用户目录，不动。
- 不 reset/stash/覆盖别人的未提交改动；发现已有改动先读懂并接着做。

## 提交与结果

按真实修复点提交，避免“一个小改动拆十几个 commit”。涉及 Hermes fork 的修复先推 `unicorn-Y/hermes-agent:atlas`，Atlas 再固定/引用对应提交。

最终：
1. 更新 `docs/plan/CORE-PARITY.md`；
2. 更新 `tasks/CURRENT.md` 为 `AWAITING_REVIEW`；
3. 写 `tasks/results/ATLAS-C1R-FINISH.result.md`，只写：
   - 修了什么；
   - Atlas/Hermes 提交号；
   - 聚焦测试结果；
   - 一次全量 pytest 汇总；
   - 前端四项结果；
   - C1 是否还有真实未完成项。
4. `git pull --rebase` 后 push，核对远端 HEAD，然后停止。

**不要开始 C2。完成并推送后，由 ZCode 通知上游规划者验收。**
