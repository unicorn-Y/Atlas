# F4-A Atlas 时区接线子包

基线：Atlas `memory-v1`，HEAD `4a542ef6919ed0249cd6f709d055c30574e15ba5`。本记录覆盖 Atlas observer / reflector / facade / recall-context 接线；不代表 F4-A 全项验收。

## 变更

- Observer 默认时钟改用 `atlas.time_context.now_local`。每批提取只捕获一次本地时间，并把 IANA 时区、本地日期时间和偏移规则加入模型 system prompt；同一捕获时间也用于 observer 日预算日期。语言重试沿用同一提示和本地日期。
- Reflector 默认时钟改用统一本地时间接口。system prompt 明确日 / 周 rollup 日期使用配置时区的本地日历；`consolidation:apply` 请求在顶层发送 `cue_context.current_timezone`，未塞入 `context`。
- UnifiedMemoryFacade 的 recall 请求在顶层发送 `cue_context.current_timezone`，并公开其配置时区。`recall_context.assemble_recall_context` 接受显式 `current_timezone`，直连 recall body 在顶层发送此 cue，未读取 client 私有配置字段。
- `run_phases` 从统一 facade 的公开时区属性取值，并将其显式传给 `assemble_recall_context`；没有 facade 时从 Atlas 当前配置解析。
- Server 构造 IntentBridge 时传入 Atlas 配置，使提醒意图解析使用同一用户时区配置。

## 验证

隔离根均位于 `C:\Users\25011\AppData\Local\Temp`；没有触碰 `D:\Atlas\data` 或真实模型流量。

专项移交红测命令：

```powershell
$env:ATLAS_DATA_DIR = 'C:\Users\25011\AppData\Local\Temp\atlas-f4-a-wiring-25f77d1c276a404bbab9ec908ecd579d\atlas-data'
& 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -q -o addopts= -p no:cacheprovider --basetemp 'C:\Users\25011\AppData\Local\Temp\atlas-f4-a-wiring-25f77d1c276a404bbab9ec908ecd579d\pytest' core/tests/unified_memory/test_f1_language.py core/tests/unified_memory/test_client_contract.py -k 'observer_prompt_and_daily_budget or reflector_prompt_and_apply or facade_recall_for_conversation_shapes'
```

结果：`3 passed, 28 deselected`。覆盖 Observer 提示与预算日期、Reflector 提示与 apply body、Facade recall body。

时区回归先按 TDD 验证 RED：新接口尚未接入时，测试以 `TypeError: assemble_recall_context() got an unexpected keyword argument 'current_timezone'` 失败。随后测试使用显式 `AtlasConfig(user.timezone=America/Los_Angeles)` 解析时区，并通过直连 fake transport 捕获实际 `/v1/unified/recall` body。专项命令：

```powershell
$env:ATLAS_DATA_DIR = 'C:\Users\25011\AppData\Local\Temp\atlas-f4-a-recall-timezone-config2-138e971573da4c35aab9f3760ce20ef8\atlas-data'
& 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -q -o addopts= -p no:cacheprovider --basetemp 'C:\Users\25011\AppData\Local\Temp\atlas-f4-a-recall-timezone-config2-138e971573da4c35aab9f3760ce20ef8\pytest' core/tests/unified_memory/test_recall_context_s3.py -k 'sends_explicit_timezone_as_cue_context'
```

结果：`1 passed, 6 deselected`。测试确认时区位于顶层 `cue_context`，不在严格 `context` 内。

最终扩展 Atlas 回归命令：

```powershell
$env:ATLAS_DATA_DIR = 'C:\Users\25011\AppData\Local\Temp\atlas-f4-a-wiring-final-ee2c06532c95478c8a94caf3484c09a3\atlas-data'
& 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -q -o addopts= -p no:cacheprovider --basetemp 'C:\Users\25011\AppData\Local\Temp\atlas-f4-a-wiring-final-ee2c06532c95478c8a94caf3484c09a3\pytest' core/tests/unified_memory/test_f1_language.py core/tests/unified_memory/test_client_contract.py core/tests/unified_memory/test_recall_context_s3.py core/tests/unified_memory/test_composition.py
```

结果：`54 passed in 33.24s`。另运行 `core/tests/unified_memory/test_behavioral_use.py::test_pre_plan_constraint_order_in_execution_flow`，结果 `1 passed in 0.85s`，确认 run_phases 模块导入及执行顺序回归。此为单元 / 合约回归证据，不构成真实观察者效果证明。F4-A 真实模型冒烟仍由原 A lane 负责；MemoryOS 时区 API 验证由 BC lane 负责。

将 `run_phases` 的 facade timezone 属性读取加上字符串校验后，补跑请求体与执行入口两个受影响用例：

```powershell
$env:ATLAS_DATA_DIR = 'C:\Users\25011\AppData\Local\Temp\atlas-f4-a-review-final-8b41fa7244684b47b2b040485d5a2523\atlas-data'
& 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -q -o addopts= -p no:cacheprovider --basetemp 'C:\Users\25011\AppData\Local\Temp\atlas-f4-a-review-final-8b41fa7244684b47b2b040485d5a2523\pytest' core/tests/unified_memory/test_recall_context_s3.py::test_assemble_recall_context_sends_explicit_timezone_as_cue_context core/tests/unified_memory/test_behavioral_use.py::test_pre_plan_constraint_order_in_execution_flow
```

结果：`2 passed in 0.92s`；`git diff --check` 通过。

## Observer 提醒分类补修（等待真实重跑）

原 A lane 的首次真实 Observer → service → bridge smoke 有明确结果：用户授权的未来提醒被抽取为 `COMMITMENT`，带本地时区的 `valid_from` 正确，但没有 `INTENT`，因此 bridge 未创建 Automation。按此证据补充通用 system-prompt 分类规则：仅用户直接授权 Atlas 发出未来提醒/通知、且有明确或可解析时间线索时，将获授权的行动记录为 `INTENT`；用户自己计划执行的未来事项仍为 `COMMITMENT`；普通信息提问、即时帮助请求、当下工作指令、建议请求、假设和示例不授权提醒行动，不生成 `INTENT`。规则明确记录的是授权行动而不是把普通请求记作个人事实；没有扩枚举、预填字段、按失败原话特判或修改 validator。

新增 `test_observer_prompt_distinguishes_authorized_reminders_from_commitments` 先确认实际发送的 observer system prompt 包含正向授权规则和原问句/请求负边界。该测试只证明规则进入模型请求，不代表模型实际分类效果；A lane 需按原授权重新执行真实 smoke，结果另行记录。
