# GPT-6 第三轮独立复核｜Atlas 集成分支（2026-10-17）

**结论：上轮两项代码阻断（BLOCK-4/5）通过静态复核；允许进入受控 Windows 实机冒烟/部署准备阶段。不等于已部署、不等于全系统正式上线 PASS。**

审查目标：`integration/atlas-fixes-20261017@f99bc248141c378a400052c24b4a1bbc1f17df8a`，上一轮提交 `14bf166371a77fd075da9d9a494e78983a6c82b6`。远端对比新增1次提交，4个文件发生代码/测试变更。本次基于 GitHub 实际源码、Commit 说明和测试源文件独立审查；**没有在 Windows D:\Atlas 上运行测试或核实本机部署状态，也未独立执行 pytest**。本次新提交未刷新既有 `tasks/results/.../TEST-EVIDENCE.md`，因此不能把其中旧测试记录当成本提交新用例实际运行的证明。

## BLOCK-4｜通过代码审查

`core/atlas/kernel/loop.py::_reusable_user_uid` 只在 canonical history 的**最后一条**为 user、文本一致、存在 message_uid，且提供的 request_uid 与其一致，或者消息 display_metadata 里的 kernel_run_id/source_run_id 等于当前 run_id 时，才重用 UID。否则 `AtlasKernel.run` 为当前回合 append_session_message 创建新的持久化消息并保存其返回 UID，最终在 hermes.result 转交记忆写入。上一轮“异常退出A尾部用户消息，下一次新运行B重复『继续』”不能只靠相同文本错误继承旧 UID。

新增 `core/tests/test_memory_source_uid_e2e.py::test_interrupted_turn_does_not_donate_its_uid_to_the_next_turn` 用真实临时 SessionDB 持久行模拟 A/B，并验证第二个 UID 与 SourceRef 均不同；`test_current_run_row_is_still_reused` 验证当前运行已预写时允许复用。**注意：这是 helper+真实 SessionDB 的组合回归，不是实际启动整套 Electron/E2E 的全路径测试。** 已满足这次小返工的适当门槛，不建议为此扩大工程量。

## BLOCK-5｜通过代码审查

`core/atlas/memory/library/dream.py::run_dream` 从 `_write_project` 得到模型读取时的 `existing` 快照，在锁内重读 `current`。如果 `current != existing` 就把 project 放入 skipped，并跳过使用这份过期模型 sections。processed_ids 更新明确排除 skipped project，避免把未处理经历误标已消费；仍可正常处理未变化的页面。

新增 `core/tests/test_memory_library_w2.py::test_dream_discards_model_answer_that_repeats_a_line_deleted_while_it_ran` 模拟模型已读取的旧用户确认行被删除，而模型仍在 sections 中输出该旧内容，断言不会写入且记录仍 pending；`test_dream_still_writes_when_the_page_did_not_change` 防止影响正常整理。修复直接覆盖上一轮反例，且没有引入大型并发框架。

## 本轮整体验收口径

- 上轮确认的 W1 R1–R4、Stop、搜索分页、更新器故障恢复等集成代码依然在分支里；它们的有限针对性证据见已有 handoff，未在本轮重复审核每一行。
- **本轮新增 commit 是实际代码修改而非仅文档**；BLOCK-4/5 均有针对性测试源文件。
- GitHub `ui-redesign` 和 `main` 未因本轮审查而合并；不得把集成分支的修复说成已经在用户主机 D:\Atlas 生效。
- 真实高风险操作：不要贸然对含12项 tracked dirty 改动、untracked 研究文件和真实记忆数据库的 D:\Atlas 执行 checkout/reset/clean/覆盖式更新或无备份的首次启动。
- **建议下一步**：由有权限的 Codex 在 Windows 先记录 D:\Atlas HEAD/dirty 文件和数据根位置，备份真实 SessionDB/记忆目录；使用独立 worktree 与隔离数据完成一次 Electron 启动→模型普通请求/503失败卡→Stop慢工具→两轮重复消息记忆引用→Dream用户编辑→更新器失败回滚的小范围冒烟。若稳定，再决定如何安全整合 D:\Atlas 现有 dirty 研究实现并切换日用运行版本。无需第四轮全局静态审查或重写任务书。

**审查状态：CODE_REVIEW_PASS_FOR_BLOCK_4_5；WINDOWS_STAGED_SMOKE_PENDING。**
