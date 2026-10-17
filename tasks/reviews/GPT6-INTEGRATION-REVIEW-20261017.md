# GPT-6 独立代码验收｜Atlas 正式整合批次（2026-10-17）

结论：**RETURN_FOR_FIX / 暂不放行部署**。这轮确实有真实代码施工，不是规划。已核对 GitHub 固定整合提交 `integration/atlas-fixes-20261017@2b2b264991c9b7474b7e283d8cbb8e49d4ab7448` 相对 `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f`：ahead 22 commits、41 个变更文件。未在用户 Windows 本机重跑、未操作 D:\Atlas；以下为**独立静态代码验收**与对 Codex 提交测试记录的交叉核对，不能写成实机 PASS。

## 一、认可的实际交付

- W1 R1：`core/atlas/models/router.py::complete_for` 已按单一路由对辅助模型请求尝试至多三次；模型固定不 fallback，永久 HTTP 错误不重试，短 Retry-After 与超15秒截止判定存在。相关测试记录为 9 passed（测试结果来自施工交接，非本验收人现场运行）。
- W1 R2：`evidence/harness/verify_w1.py::agent_with` 改用基于 candidate 入参的路由，已修复原固定模型 A 的假阳性。R3：`run_verify.py` 移除无条件 `os._exit(0)`。R4：`model_call.py` 内容过滤终止，不自动改写再发；没有删除其它 expert 功能。
- 内核：工具 batch 等待加入 cancel waiter，已有 `forwarded_results` 去重保留；提交了小范围 Stop/验证提醒测试。
- 记忆：新增失败队列查询/重试 API 和 UI，重启 pending drain，稳定 (at,id) 时间线游标，SourceRef exact 编码、索引候选扩大，Dream 标记 processed_ids，语音麦克风晚到清理。
- 更新：候选 worktree 编译再切换的结构实际存在；有隔离候选**依赖安装失败**保留旧版本的施工测试记录。
- 附加功能：显式上下文 handoff 草稿和父子会话关联。没有证据表明原任务书列举的其他大多数分支功能均已吸收。

## 二、必须返工的代码问题

### BLOCK-1｜P1｜Dream 合并会复活用户并发删除/修改的旧记录

`core/atlas/memory/library/dream.py::run_dream`：
`source_lines = _old_owner_lines(existing)`（调用 LLM 前的旧页面）；然后在锁内从最新 `current` 读取 `_old_owner_lines(current)` 并 `dict.fromkeys([*source_lines[heading], *lines])` 合并。

反例：LLM 请求期间用户在页面里**删除**一条「你改的」记录，`existing` 有而 `current` 无，该记录仍被 `source_lines` 保留并写回；若用户把该记录从「A」改为「B」，旧 A 和新 B 都可能同时保留。这正是 ATL-009 原本要修的并发改写问题中的删除/替换场景，新增路径只覆盖用户**新增**行。

**最小修法**：锁内以最新 current 的 owner 行为准，旧 existing 只作模型生成输入/冲突检查；有不可合并冲突则重新整理或跳过该项目，不得无条件 union 旧快照。补删除、替换、并发新增各 1 个隔离测试。不要重造事务框架。

### BLOCK-2｜P1｜更新在目录备份失败后可能删除活跃构建

`scripts/atlas-update.mjs::replaceDirectory(source,target,backup)` 先将旧 target rename 到 backup 再将 candidate rename 到 target。但 `stagedUpdate` 的 `catch` 在 committed=true 时，对于 dist 和 dist-electron **无条件 rmSync(target)**，仅在 backup 存在时才恢复。

反例：已完成 git ff，第一份 dist 替换完成；轮到 dist-electron，如果因 Windows 文件占用/权限导致**旧 target → backup 的 rename 直接失败**，该目录旧版本仍在 target、backup 不存在；catch 会先删这个尚未备份的旧 target，且没有东西可恢复。如果 rmSync 同样失败，回滚也被异常中断。这违反「更新失败仍能启动旧版」。

**最小修法**：按输出分别记录 backup/activation 已成功的事实；仅恢复确实成功备份/替换的目录；不存在备份时绝不可删除原目录。将一次第二目录 rename 失败注入跑通，断言两套 bundle/HEAD/stamp 均恢复。

### BLOCK-3｜P1/P2｜激活后的 rebuild 不受更新回滚事务保护

`scripts/atlas-update.mjs` 在 `stagedUpdate()` 返回前就删除 `backups`，随后外层还执行 `const steps = rebuild()`。若这一最后的 `rebuild()` 失败，外层 catch 只标记失败，**不会退回已经前移的 git HEAD 和构建/依赖**；在 `--relaunch` 下仍可能启动这份状态。平常重建可能为空操作，但失败路径存在，和任务书「任何构建失败不启动半更新版」不符。

**最小修法**：让全部激活后的必要校验/构建完成之后再提交事务并删旧备份；或证明 `rebuild()` 在此时完全不可能发生改动/失败，并在失败时 rollback。模拟激活后抛错。

## 三、剩余缺口：不必重开全局审查，但不能记 FIXED

### FIND-4｜P2｜ATL-012 搜索候选上限从 1,000 换成 100,000，未真正保证 total/分页

`core/atlas/api/memory_library_router.py::search` 请求 `_lib().search(q,100000,...)`，再从最多十万候选里做 src/from/to/project 后置过滤并 `total=len(filtered)`；`index.py` 本身 FTS/向量/hybrid 都有十万上限，`sources.py::search_raw` 原始会话单次还硬上限50。检索命中数超过上限、或 raw 查找多于50条时，筛选后 total 仍可能虚假完整；处理十万候选还可能明显拖慢 UI。

**修法**：把过滤/pagination 或候选游标下推到查询阶段，或分批流式扫完匹配项并准确计算 total；保留混合相关性算法。最少补一条「过滤命中落在候选窗口之外」和 raw >50 的测试。若这轮只承诺提升到100k，状态改 PARTIAL 而非 FIXED。

### FIND-5｜P2｜ATL-014 新引用的生成仍可能错配重复文本

`memory/library/__init__.py::_source_ref_for_turn(session,user_text)` 取 SessionDB 的 `latest_session_message(...,role='user')` 再用归一化文本相等判断。「继续」之类重复文本，或者晚到的后台提炼轮次，可能错误把早一轮链接到同内容的**最新**消息，尽管输出 ref 被标 `precision='exact'`。

**修法**：从真正写入 SessionDB 的消息事件直接把 message_uid 传到 schedule_turn/队列，按 ID 构造 SourceRef；没有 UID 时标 missing，不能靠「最新＋文本一致」获得 exact 的可信等级。补相同文本连续两轮的回归。

### FIND-6｜P2｜ATL-002 Stop 的完整用户入口仍待验证

`kernel/loop.py` 已 race cancel waiter。但 `core/tests/test_kernel_cancel_verify.py` 只直接取消 `ToolScheduler` task 和测试 waiter cleanup，没有走 `AtlasKernel.run -> run.cancel_event -> API run.cancelled` 的整条路径。不能凭此测试宣称用户真实长工具 Stop E2E PASS。只需补一个隔离假慢工具的整链用例，不必全套环境回归。

### FIND-7｜P2｜没有新版本时仍做昂贵的候选初始化

`scripts/atlas-update.mjs::stagedUpdate` 没有判断 candidateHead==before 就直接结束；即使 upstream 没新 commit，也会在新 detached worktree 创建 .venv、触发 `--launch-only --no-launch` 下的依赖/构建。用户目标速度优先；应在确定远端HEAD与本地相同、且无待合并 pending commit 时跳过候选安装过程。

## 四、其他说明

- `TEST-EVIDENCE.md` 承认 startup 仅试了 candidate 依赖失败，没有完成 frontend build-stage 故障注入；未做真实 provider、真实记忆、Electron 音频、完整 Stop E2E。这些是未测，不是已知失败。
- `integration/atlas-fixes-20261017` 有真实修复实现，与上一次「还在规划」不同；25项问题账本只部分覆盖，14 组候选分支并未全面整合。不要把「完成本批施工」等于「Atlas 全部修好」。
- `D:\Atlas` 含未提交修改，本次 GitHub 检查不能核实用户机器当前 git status 或当前是否已经人工部署。施工交接说未动日用目录；本审查没有现场验证。
- 无需为小文档混进代码 commit 重写 git 历史；不为「纯净提交」另派工。

## 五、最小返工与验收

优先 BLOCK-1/BLOCK-2/BLOCK-3，再处理来源 UID 与检索剩余缺口；STOP E2E和no-op路径各补一条定向验证。分支小修 push 后返回 commit SHA 与隔离故障测试结果；**暂不合并 main、不覆盖真实 D:\Atlas**。

**最终结论：NOT PASS（有实际代码可复用，但存在清楚的并发记忆与更新回滚阻断项）。**
