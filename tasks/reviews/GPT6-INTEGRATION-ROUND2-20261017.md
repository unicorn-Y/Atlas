# GPT-6 第二轮独立复核｜Atlas 集成版（2026-10-17）

结论：**RETURN_FOR_FIX（仅剩两个精确的记忆正确性问题；不要再做全量审查）**。这是 GitHub 固定代码 SHA 的静态审查，未在用户 Windows D:\Atlas 本机执行或改动数据，不把 Codex 提供的测试结果称为本验收人独立运行。

基线：上一轮集成 2b2b264991c9b7474b7e283d8cbb8e49d4ab7448。
本轮：integration/atlas-fixes-20261017@14bf166371a77fd075da9d9a494e78983a6c82b6。对比新增11次提交，变更19文件。

## 已认可的修复

1. BLOCK-1 的直接旧 owner 行复活：dream.py 改为使用写入时最新页面提取用户确认行，不再 union 旧快照。新增/删除/替换的定向测试存在，报告3 passed。
2. BLOCK-2、BLOCK-3：atlas-update.mjs 已用备份/激活状态逐目录回滚，并把激活后 rebuild 移入清理备份之前。脚本附一次第二目录备份失败、一次激活后重建失败和一次无更新的真实 Node 子进程故障注入，交接称3 passed。本审查没有现场重跑，不代表 Windows 本机更新器实机验收。
3. FIND-4：/api/memlib/search 已用 MemoryIndex.browse_search 分批扫描+SQLite临时表统计，不再靠取前100000结果再过滤；原始 SessionDB 使用 offset 分页。超过10万候选及raw超过50的测试已提交。
4. FIND-5 正常成功路径：KernelRequest、hermes.result、run_phases、MemoryLibrary.schedule_turn 已串联 durable user message_uid；来源验证从 SessionDB 确认 exact UID，未知时标 missing。提供真实临时 SessionDB 两条相同文本的测试。
5. FIND-6：有真实 API/WebSocket run.cancel 经慢工具到 run.cancelled 的集成测试，交接称1 passed；FIND-7：无远端更新时跳过候选 worktree/构建。
6. 模型 W1 R1–R4 改动继续保留，尚未在用户日常 Atlas 实机部署。无需另为此返工。

## 新发现｜BLOCK-4 P1：异常中断后的重复文本可能误复用旧消息 UID

证据：core/atlas/kernel/loop.py::AtlasKernel.run，读取 read_session_model_messages 后：

pending_user = history[-1].role=='user' and _message_text(history[-1])==request.message

如果 pending_user 成立就不 append_session_message，而随后反向从 canonical_rows 搜索「最近一条相同文本的 user message_uid」，并把它作为当前回合 user_message_uid 报给 memory。

明确反例：回合A 的 user「继续」已经 durable 写入，但其助手生成/工具阶段意外失败（从而 SessionDB 最后一条仍是 user「继续」）；用户明确发起新的回合B，也输入「继续」；新的 run_id 不同，而现有逻辑**仅按最后角色和文本相同**就认定旧行是B提前持久化的行，跳过B的写入、为B返回A的UID。此时 MemoryLibrary 即使调用 session_message_evidence 验证，仍将把 B 的新轮记忆错误标成 A 的“exact”。

现有 test_memory_source_uid_e2e.py 两次先显式 append(user,「继续」)，不是「上一轮中断留尾、下一轮新 run_id 再发送同文本」的场景，所以不能覆盖这个反例。

修复：只有能证明 tail user 是**当前 run 的提前写入消息**（稳定 message_uid 或写入事件的 kernel_run_id/source_run_id/请求关联元数据确证）才可复用；无法确证就追加新 user durable row 并使用新UID。不允许为判断“是否已持久化”扫描历史里所有同内容 user。只需要1个 interrupted A+new B 同文本的真实临时 SessionDB 用例；另保留当前已预写当前回合可恢复的路径。

## 新发现｜BLOCK-5 P1：Dream 仍可能将旧快照的已删除内容重新标成「整理」

证据：core/atlas/memory/library/dream.py::_write_project 在模型请求前读 existing_page，传入模型提示词；模型返回 sections。run_dream 在模型返回后确实以 latest current 提取 owner 行，但**未验证模型 sections 基于的 existing_page 是否已经变化**，随后无条件把 sections 写入新 Entry(src=SRC_DREAM)。

反例：模型开始时 existing 里用户确认「待删除旧决定」；模型生成途中用户把该行删除；模型根据旧 existing 返回 sections[现在状态]=[「待删除旧决定」]；run_dream 即使不再保留 old owner 行，仍会把「待删除旧决定」作为 Dream 摘要写回。现有删除/替换测试让 mock _write_project 只返回「模型摘要」，没有模拟该旧内容被模型重复输出，故不覆盖旧模型响应失效。

修复：如果模型期间项目页已改变，不能无条件采用旧快照模型结果。最小方案：对比提炼前后页面内容/hash，检测变更则跳过本项目并保留其未处理 entries 下次再试，或者以最新页面重新生成一次；不能将此次 entries 标为 processed。补一条模型结果包含被删除旧行且磁盘已变化的隔离回归。无需新并发事务架构。

## 放行门槛

仅针对 BLOCK-4 / BLOCK-5 提交两处小修和对应两个真实测试，push 到 integration/atlas-fixes-20261017 并给出新的 SHA、真实测试结果。之后可转入限定范围的 Windows 部署/真实数据备份与冒烟，而不是再次从头审查25项问题、405功能或14分支。

当前状态：**尚未在用户 D:\Atlas 日用实例部署；独立静态验收 NOT PASS，剩余返工范围很小。**
