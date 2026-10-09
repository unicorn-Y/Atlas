# F1-D 30 场景真实 runner（待总控审阅）

状态：runner 实现待总控读 diff；只完成下文两次单场景 Gemini HTTP 诊断，尚未进行正式 30×3 或 Judge 验收。该报告只覆盖 30 场景 runner，不代表 F1-D 整体验收。

## 输入与隔离

- 30 个 canonical scenario 的规范化 manifest SHA-256：`6abdefcaaab706dd690527a2c305defd43f5d53a556315d0553988e38ea8d1fa`。runner focused test 校验数量、hash 与原始输入；没有改写原话、criteria、步骤顺序或模型动作 payload。
- 默认模式只输出 `plan_only`，没有运行结果、回答或观察写入。真实模式必须显式 `--run-real`，并为每个 scenario/trial 建立新的 `D:\Temp\F1-D-...` Atlas、MemoryOS、Hermes 与 workspace 根。
- Atlas 固定 `gemini-3.8-flash`。隔离环境不继承 provider API key 环境变量；安全设置 helper 只写隔离 settings。runner 记录模型路由元数据，不保存 credential 值。
- 每个 scenario 的隔离 `HERMES_HOME\config.yaml` 只写 `fallback_providers: []`、旧兼容 `fallback_model: []`，并为 `memory_observe` / `memory_reflect` 设 120 秒 timeout、空 fallback chain；不读写默认 Hermes 配置。S27 的隔离 MemoryOS 子进程单独启用其官方 `MEMORYOS_HARD_ERASE_ENABLED=true` 测试 flag，其余场景不设置。
- Atlas HTTP/WS、MemoryOS API、进程生命周期、Capture outbox 读取都限制在隔离 root。Atlas 重启、强制结束只作用于当前 runner `Popen` 创建且经 PID + creation time 校验的进程树。
- 自然语言步骤经真实 `/ws/chat` `run.start` 进入 `run_phases.execute_run`；控制步骤由 `scenario_actions.apply_step_action(action, payload, ctx)` 处理，不伪装成聊天输入。适配器缺失或返回 `unsupported` 会使 scenario 失败。

## 时间与捕获证据边界

canonical `occurred_at` 保留在 scenario step 和结果中，但当前 Atlas `RunRequest` 不接受 `occurred_at` 或 `reference_time`。真实捕获在 `run_phases` 从 SessionDB 取得本轮稳定 message UID 与 `created_at`，再调用 `CaptureService.capture_user_message`；因此评测用的 2026-10-04 场景时间没有进入用户原话、Capture 或 MemoryOS valid-time。结果标记 `occurred_at_used_by_ws=false`，不把它冒充来源时间。

每轮结果只读读取本 scenario 隔离 Atlas outbox 的 `source_event_id`、源类型/对象/revision、valid-time、content hash、ACK 状态和时间戳；不导出 payload 中的原文。末态汇总 actual `ACKED` 与未 ACK 数量，并比对本轮 WS assembled refs 与新 MemoryOS record refs 的交集，便于检查 capture 重复或同轮 self-match。ACK 是 Capture outbox 对 MemoryOS 的接收证据；观察摘要是否形成仍以真实 MemoryOS records 读回为准。

## 有意保留的场景限制

- S27 canonical 首步直接删除“小满”，此前没有创建该实体的原始自然输入。runner 不补录、不预插，不降低目标唯一性；真实 action 找不到唯一目标时必须报告失败。单独的 fixture-backed 删除 probe 不并入 canonical 30 场景成绩。待总控审阅的 harness fixture 候选为 `我的孩子叫小满。`，UTF-8 SHA-256：`e245293a39b02ce671022f97868c5f451e9b738d721d49074d675f8cf4939cef`。来源仅是 S27 描述中的目标名“小满”及其后家庭/孩子查询；该关系句是额外评测输入，不是原始场景历史，尚未发送。
- S29 在第一轮自然请求前记录真实只读 baseline（`GET /api/automations` 与 MemoryOS `facet=INTENT`）。每个自然轮后调用只读 `audit_reminder_state(ctx)`，保留本轮真实 WS result、前序 audit history 与 baseline；adapter 必须按同一 automation ID 检查创建、取消状态变更及无运行 receipt。缺端点、无状态变化、重复触发或 unsupported 都记失败。
- S28 的“暂停期间普通聊天不入库”必须由真实 pause 状态、Capture/Observer 水位和 MemoryOS 记录证明。单有 pause API 成功不算通过。
- S30 的 crash/restart 只检查真实隔离 workspace 文件和进程状态；scenario payload 的 `completed_steps` 不当作事实。

## 本次验证

命令（D:\Atlas 工作目录）：

```powershell
$env:PYTHONPATH='D:\Atlas\scripts\memory_v1;D:\Atlas\core;D:\Atlas'
& 'D:\Atlas\core\.venv\Scripts\python.exe' -m py_compile 'D:\Atlas\scripts\memory_v1\eval_scenarios.py'
& 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider -o addopts= --basetemp 'D:\Temp\F1-D-focused11-20261009' --tb=short -q 'D:\Atlas\scripts\memory_v1\test_eval_scenarios_runner.py'
& 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider -o addopts= --basetemp 'D:\Temp\F1-D-actions-combined2-20261009' --tb=short -q 'D:\Atlas\scripts\memory_v1\test_eval_scenarios_runner.py' 'D:\Atlas\scripts\memory_v1\test_scenario_actions.py'
```

结果：runner focused `11 passed`；runner + action adapter focused `28 passed`；`py_compile` 成功。CLI `--help` 可加载，默认 dry-run 路径由测试覆盖。focused/CLI 检查本身没有启动服务或模型。

## 单场景 canonical S27 诊断（不是正式验收）

两次都只运行原始 S27 两步；没有 setup turn、没有预插记录、没有改原始 manifest。两次都是独立隔离 root、实际 Atlas `/ws/chat`、`gemini-3.8-flash`，非 30×3。

第一次命令：

```powershell
$env:PYTHONPATH='D:\Atlas\scripts\memory_v1;D:\Atlas\core;D:\Atlas'
& 'D:\Atlas\core\.venv\Scripts\python.exe' 'D:\Atlas\scripts\memory_v1\eval_scenarios.py' --scenario 27 --run-real --isolated-dir 'D:\Temp\F1-D-s27-canonical-20261009a' --output 'D:\Temp\F1-D-s27-canonical-20261009a\results.json'
```

结果：Atlas PID `55132`、MemoryOS PID `53560`，端口 `59203`/`59192`；runner 首次探测到该隔离 service 的正式 `MEMORYOS_HARD_ERASE_ENABLED` 为 false，故 delete adapter 在目标解析前返回失败。第二步真实 Gemini 回答当前没有家庭/孩子记录。结果 JSON SHA-256：`D9AA1BB7E88195501E49C2C608B3C1AD164FD1EB335F50558F30B9C7700E145B`。

确认只在 S27 的隔离 MemoryOS 子进程设置官方 flag=true 后，使用新 root 重跑：

```powershell
$env:PYTHONPATH='D:\Atlas\scripts\memory_v1;D:\Atlas\core;D:\Atlas'
& 'D:\Atlas\core\.venv\Scripts\python.exe' 'D:\Atlas\scripts\memory_v1\eval_scenarios.py' --scenario 27 --run-real --isolated-dir 'D:\Temp\F1-D-s27-canonical-20261009b' --output 'D:\Temp\F1-D-s27-canonical-20261009b\results.json'
```

结果：Atlas PID `53472`、MemoryOS PID `3976`，端口 `51778`/`51769`；真实 flag readback 为 true，但 subject `f1d-s27-t01-93ee2e912b` 的实体查询返回 `items=[]`，action 明确失败 `entity target is not unique (matches=0)`，没有调用删除完成路径。第二步 Gemini 仍回答当前无家庭/孩子记录。canonical scenario 为 failed；这与原输入缺少目标前置事实一致，不作为 runner 通过。两条 Capture 源事件（user 与 assistant）真实存在且最终都 `ACKED`（2/2），source IDs、occurred_at/hash 与完整结构化证据留在结果 JSON；当前检索 assembled refs 为空，没有同轮 delta overlap。结果 JSON SHA-256：`B5AA6B6A226EE0D19BCDFE9305368809C82B1ADABAD6C8A3DD9B337EBF0715BE`。

两次诊断发生在新增隔离 Hermes timeout 配置前；此后该配置通过 runner/action focused tests，诊断 JSON 不会被覆盖。两次进程均由 runner 的 identity-checked cleanup 关闭；事后逐 PID 检查四个 PID 全部已退出，四个 Atlas/MemoryOS 端口均无 listener。隔离数据与 `atlas.log` 保留在各自 DTemp root，便于总控抽查。

## 总控后续复跑入口

先由总控审阅 diff 与隔离 helper 后，单场景真实 HTTP spot 可用新建空目录执行；真实数据只写 `D:\Temp`：

```powershell
Set-Location D:\Atlas
& 'D:\Atlas\core\.venv\Scripts\python.exe' 'D:\Atlas\scripts\memory_v1\eval_scenarios.py' --scenario 1 --run-real --isolated-dir 'D:\Temp\F1-D-runner-spot-20261009' --output 'D:\Temp\F1-D-runner-spot-20261009\results.json'
```

正式 30×3 尚未获启动；验收时使用另一个不存在的空目录并显式传 `--all --run-real --repetitions 3`。执行前须先抽查单场景的真实 Gemini 事件、MemoryOS record、outbox source IDs/ACK 和 cleanup。
