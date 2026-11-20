# 全功能/全组件原子计划交接记录

2026-11-17。用户要求：不仅大模块，全部功能、组件均纳入精细对齐与超越；随后明确“那就做，不要停下来，当个plan”。

## 计划版本

`docs/glm-hammer/plans/2026-11-17-atlas-dsh-atomic-parity-and-superiority.md`

SHA256：`1999ad5e478f041fb1cb8ba74c9cbd14a29da41b488e5b179093052d662eae4e`。

四阶段、九个主任务、66个去重声明文件路径；这些不是能力数量或全部未来批次数。Task1/7从固定源持续发现原子/协作边，每个新批次实施前明确确切Files/依赖/二元验收，不能用九项做完替代全部目标。

## 普通独立计划评审

- 可行性、接线依赖、覆盖验收三方独立只读评审。
- 第一轮三方ADVISORY_REVISE：来源语义覆盖不足、实施依赖与受阻lane矛盾、benchmark旧启动器凭据/配置/代理风险、attempt遗漏app-server/SDK出口、enqueue后的独立订阅/恢复不足、比较判据未冻结。
- 统一修订后第二轮可行性/接线ADVISORY_APPROVE，覆盖要求进一步定义全局超越门槛。
- 第三版加预冻结required_superiority_set：每运行时组件至少一主要用途优势单元及四类跨组件场景，集合每个单元SUPERIOR，其余必要原子/协作边对等、来源obligation0才整体完成；不能事后缩减。
- 最终三方均ADVISORY_APPROVE，同一上述hash版本。无生产实现/运行成功含义。

Forge认证状态：未验证。当前宿主只有历史plan-seal，无本轮认证runId/generation/journal；没有编造receipt、journal或approved projection，不声称Forge certified PASS。本记录是普通内容评审和CDP交接事实。

## CDP交接

确认 `http://127.0.0.1:9222`、精确页面 `app://-/index.html`、标题“完成 DSH parity 六批任务”、模型按钮“GPT-6 Luna 高”。未操作avatar/detached窗口，未替换模型或创建新生产对话。

向空composer填写完整计划路径、hash、用户精细目标、滚动执行与全部保护边界；点击观察到的“发送”返回 `ATOMIC_PARITY_PLAN_SENT`。要求原Luna完整读计划并Task1来源/原子账本紧接Task2 OLDNEW真实生产修复，涵盖桌面、app-server、SDK、持久化与回放；完成一批立即下个ready，真实权限只阻该lane。

发送后主控确认composer为空、用户消息出现在原会话历史。Luna实际回复：“我先校验计划文件的 SHA256，并完整读取 Task1/Task2 的执行与验收条款；随后先报告这两项的准确落点、依赖和二元验收，再直接写首个红测与生产修复。任何 POSIX/认证阻塞只隔离对应验收，不暂停可执行的其他任务。”会话显示正在思考。该事实证明已收件并开始处理，不等于生产修复已完成；后续代码/验证结果另记。

随后Luna明确报告Task1/2确切Files、依赖与二元验收；Task1 schema可用后立即进Task2，不等全集人工签收归零。桌面显示“Writing source-index tests”以及持续目标。Luna读取固定DSH commit，报告11,160文件、369个package.json；该统计未经主控本轮独立重算，且不是功能数/完成分母，不能与历史52族/331包相混。当前只算施工确认，尚无Task1/2通过结果。

## 首批独立基线

Luna实施前主控用既有40秒监督器、唯一basetemp显式 `-o addopts=` 运行 `test_kernel_recovery.py` 与 `test_event_contract.py`：`33 passed, 5 warnings in 6.93s`，pytest exit0，未超时，2个观测自有进程、测试后残留0、alive=[]，日志 `artifacts/ssh-process-check-20261116-c8a073c2/pytest-d7568c6f.log`。仅作为既有恢复/事件契约基线，不证明OLDNEW修复或整体可用。

原Luna先写来源审计三个unit红测。主控独立执行：`3 failed, 5 warnings in 3.09s`，exit1，无超时、2个自有进程且无残留；日志 `pytest-8824257a.log`。当时scanner尚未实现，失败为build_source_index/check_source_index不可调用，尚非OLDNEW红测。三个断言涉及来源组件/export/platform单元、组件内部新增行为漏录、UNRESOLVED/悬空引用/假CLOSED拒绝；这些只是Task1初始fixture，不代表全语义覆盖。

主控本轮只新增计划与本证据文档，未实现生产代码、未commit/push，未触碰真实数据或8765。
