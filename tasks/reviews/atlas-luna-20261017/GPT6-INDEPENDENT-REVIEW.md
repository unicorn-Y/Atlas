# GPT-6 独立验收结论：Atlas W1（2026-10-17）

状态：NOT PASS — 有明确的少量返工项。审查只依据 GitHub 实际源码/补丁/测试脚本，未声称在用户 Windows 主机重跑测试。

复核对象：review/atlas-luna-global-audit-20261017@7b17243710b8；fix/atlas-model-retry-policy-20261017@e259978420f9；基线 ui-redesign@0b1ba4114e25。

## 已认可的代码变更

- core/atlas/kernel/model_call.py 的 complete_stream 改为单一当前模型、最多补2次重试；对已经输出的流式内容或工具 delta 不重发；保留取消检查、429 长等待限制和结构化错误。
- core/atlas/models/router.py 的 complete_for 去掉硬编码 DeepSeek 候选，不能在此处因失败静默换模。
- 错误信息已沿 kernel/loop.py → api/run_drive.py → 前端 Timeline 传递；模型失败时有排队项会暂停队列。
- 两套模拟验证脚本提供了有效的局部证据。原报告声称通过的测试，本次并未在本地重跑，不把声称等同于独立执行。

## 返工 R1（P1）：辅助模型没有有限自动重试

core/atlas/models/router.py::complete_for 目前仅 resolve(model_id,purpose) 然后 complete(route,...) 一次；complete 使用一次 _post_completion 请求。因此辅助模型 503/临时连接失败不会像主模型那样最多重试2次。

修复：沿用已有错误分类，辅助模型固定同一个 model_id，总尝试最多3次；401/402/403/404、内容过滤等直接报错；Retry-After 超15秒直接退出；不引入新通用路由平台。原有 complete() 内的预算 reserve/release 行为不能因重试出现遗留。少量针对性测试即可。

## 返工 R2（P1）：换模对照测试有假阳性

evidence/harness/verify_w1.py::agent_with 把 router.resolve 设置成 AsyncMock(return_value=route_for(model_id))，永远返回模型A。即使旧 complete_stream 尝试候选B，Recorder 记录的还是模型A。t4_no_model_switch 仅断言 set(rec.models)=={model-a}，所以无法证实旧版未切换。事实上旧 ui-redesign 源码明确构造 candidates=[model_id,...fallback_models]。

evidence/harness/test_independent_model_retry.py::make_agent 对主模型也用固定 RouteSpec；同样不能用 HTTP body 中不变的 wire_model 单独证明 never switched。但该脚本对 complete_for 另有 resolved_models 入参记录，这一部分有效。

修复：测试中 resolve 根据传入的候选返回对应 RouteSpec，直接核对 resolve 调用序列和不同 wire_model；修正 START-HERE-GPT6.md 中「运行版84次仍为model-a」和依赖该测试的6/9说法。无需全套重测。

## 返工 R3（P2）：验证启动器无条件返回成功退出码

evidence/harness/run_verify.py 使用 finally: os._exit(0)，会覆盖 verify_w1.py 通过 sys.exit(...) 提交的非零退出码。因此打印的 PASS/FAIL 可用，但启动器 exit 0 本身不是通过证据。

修复：保留真实退出码；用一条人为失败断言验证退出码非零。只改几行，禁止额外造测试框架。

## 返工 R4（P1）：必须交可集成的代码，不只是预备 patch

截至本次 GitHub 检查：W1 代码分支仍为 e259978，integration/atlas-fixes-20261017 尚未创建。evidence/harness/w1-runtime-integration.patch 只是已准备的 diff，不是已经合流部署。用户 D:\Atlas 还有12个tracked dirty文件，不能覆盖。

按既定策略，content_filter 为非瞬时失败：明确报错、不靠改写提示词自动重新发送。此修正只处理过滤失败分支，不需删除 expert 模式其它功能。独立 worktree 合流，做精简定向验证与一轮隔离UI错误卡检查，push 集成提交；未经批准不要动正在运行的 D:\Atlas 或真实记忆/会话。

## 报告口径更正（非施工阻断）

- task/hermes-atlas-implementation-20261017 是派工任务书分支，源码零改动完全符合其用途，不能仅因此记作实现故障；真正的事实是后续实现分支尚未在GitHub出现。
- cwd 加 mtime 可以支持「运行自 D:\Atlas」的判断，无法从外部逐字节证明进程实际加载的所有模块内容；用措辞「高度可信」代替「逐字节已核定」。
- W1提交附带说明文档是轻微工程卫生问题，无须改写已发布Git提交；不要因此消耗开发时间。
- 25项问题账本是静态审查成果，不能称25项现场已复现。

## 验收结论与下一步

W1 核心主模型路径有实质修复，但在 R1/R2/R3/R4 处理并提交后，才可重新申请 PASS。本次未改 Atlas 源码或用户主目录。Hermes/Codex直接提交必要小补丁，附模型ID及HTTP请求计数、测试输出、集成分支SHA，不再重做全局审查。
