# ATLAS-C3R-FINISH Result

状态：施工完成，**AWAITING_REVIEW**。仅补当前任务书的 I3、A4；未进入 C4，未合并 ZCode 独立施工分支。

## 实现提交与来源

- `d13d941`：Automation Goal 统一到 Hermes GoalManager，移除 Scheduler 的独立目标状态、评价与 heartbeat 生命周期。
- `3b8627a`：子 Agent 启用/禁用及默认模型设置，接入既有配置和委派通道。
- `138decb`：旧目标在导入前跨保存/重启保留迁移源，保留已完成及暂停终态，防止重新执行。
- 直接复用本机 Hermes fork `e287231d7906bcce5bc373d20fb2e3e1e6427220` 的 `hermes_cli/goals.py` / `goal_command.py`；fork 未修改。来源登记在 `docs/plan/VENDORED.md`。
- 三个 GPT-6 Luna / high 子代理分别负责 Goal 后端、child 设置后端、设置 UI；主控审 diff、接线边界、结果和提交。当前工具上限为主控加三个并行子代理。

## I3：同一 Goal 生命周期

- Automation 使用稳定会话键 `scheduled-goal-<task id>`；聊天 `/goal` 和 Automation 均从同一 Hermes SessionDB 的 GoalManager 读写目标。API 返回 `goal_session_id`，不再存第二份活跃目标定义或 progress。
- Scheduler 只保存触发、任务和执行时间元数据。触发后使用 Hermes 的 `evaluate_after_turn`、`should_continue` 和 `continuation_prompt`；完成、等待、暂停、阻塞及预算条件由原生 Manager 决定。
- pause/resume 不再暂停另一份 Scheduler goal 状态；聊天恢复后后续调度仍能触发。每轮重新读取 Manager；运行期间 pause/clear 停止后续推进，replace 后跳过旧回复的评价。每个目标使用执行锁避免重叠执行。
- Automation API 的创建、暂停、恢复、替换、清除和 trace 均接同一后端。推进日志位于同一 SessionDB 的审计 metadata，只用于展示，不参与 Goal 判断；可观测性状态亦从 Hermes 读取。
- GoalsPanel 展示原生状态、推进轮数、检查条件、评价原因和推进记录。普通 Automation 列表排除 `action="goal"`，保持与持续目标列表分开。
- 旧 TOML 目标只作为一次导入源：导入前保存目标、旧终态及评价原因；导入成功后移除旧字段。旧 completed 通过原生 `mark_done` 保持 done；旧 blocked/awaiting_approval/paused 或暂停的 schedule 通过原生 pause 保持暂停。clear 后重启不复活。
- 既有 Goal outcome/reflection 接口保留；Hermes done 只在结果记录边界映射为原有 completed/satisfied/evidence 格式。

## A4：子 Agent 设置

- 现有 `/api/settings/configuration` GET/PUT 增加 `subagents_enabled`、`subagent_default_model`；PUT 支持只提交这两个字段，不修改网关或密钥。持久化复用 `load_user_settings` / `save_user_settings`。
- 模型列表和合法模型校验复用 ModelManager。默认模型只替换 child 的 inherit 选择，显式角色模型保持原定义。
- 直接委派、单 child 工具和并行 child 创建读取当前设置；禁用时拒绝新 child。运行中的 child 使用创建时已确定的 options，保存设置不会修改或停止它。
- 设置 UI 复用现有 SettingsPage、Zustand store 和 backend-adapter，含中文启用开关与默认模型选项；未建立第二套 settings store。

## 验证证据

所有后端测试使用临时数据目录和假的模型评价/执行回复；未调用真实模型或外部服务。未运行 backend full pytest，也未重跑整轮 C3。

主控聚焦集成命令：

```text
rtk proxy core/.venv/Scripts/python.exe -m pytest -q core/tests/test_goal_scheduler.py core/tests/test_subagent_settings.py -p no:cacheprovider --basetemp C:/Users/25011/AppData/Local/Temp/atlas-c3r-controller-final --tb=short
....                                                                     [100%]
4 passed in 16.83s
```

Goal 的三个用例覆盖双向 pause/resume/replace/clear、真实 GoalManager 的 continue→done 两轮假执行、一次迁移及 clear 后重启。A4 的一个用例通过真实工具入口到 fake child runner，两个 child 用 Event 保持运行；改变默认模型、禁用新 child 后，原 child 仍使用原模型并可完成。

直接受移除旧 Scheduler Goal API 影响的既有可观测性四个用例改用 Hermes 状态及审计源，保留普通 schedule 计数、跨重启、trace 过滤及运行失败覆盖。主控只跑该文件一次：

```text
rtk proxy core/.venv/Scripts/python.exe -m pytest -q core/tests/test_autonomous_observability.py -p no:cacheprovider --basetemp C:/Users/25011/AppData/Local/Temp/atlas-c3r-controller-observability --tb=short
....                                                                     [100%]
4 passed in 11.93s
```

最终旧 completed/paused 迁移修正后，只重跑对应原有迁移用例；未重复全套：

```text
rtk proxy core/.venv/Scripts/python.exe -m pytest -q core/tests/test_goal_scheduler.py::test_legacy_schedule_imports_once_and_clear_does_not_resurrect -p no:cacheprovider --basetemp C:/Users/25011/AppData/Local/Temp/atlas-c3r-controller-migration --tb=short
.                                                                        [100%]
1 passed in 11.44s
```

前端四项均由主控各执行一次，退出码 0：

```text
rtk proxy npx tsc -p tsconfig.renderer.json --noEmit
rtk proxy npx tsc -p tsconfig.electron.json --noEmit
rtk proxy npx vitest run
 Test Files  9 passed (9)
      Tests  42 passed (42)
rtk proxy npx vite build
✓ 4273 modules transformed.
✓ built in 18.57s
```

新增单个 Vitest 覆盖两个设置的加载/保存及 checkbox、默认模型选项、禁用态的渲染。Vite 的大 chunk 提示仍存在，构建成功。

## 审查、偏差与边界

- I3/A4 已在 CORE-PARITY 标为 ✔，此处表示本轮施工及 focused verification 完成，仍等待上游独立验收。
- 额外四项可观测性回归仅针对本轮实际删除的旧 API，不是重新验收 C3。最终迁移补丁后仅重跑受影响的一个用例。
- 主控发现范围替换误删 Kanban 路由/配方校验并要求恢复；最终以 AST 对比原 HEAD，原有函数、路由均保留，非目标函数实现没有变化。
- `core/atlas/origin_guard.py` 未改。未操作真实用户数据、`design/`、已有用户服务或 ZCode 分支。开工已有未跟踪 `design/` 和 C1 review 文件未纳入提交。
- 子代理曾在仓库创建 pytest 临时目录；已核验绝对路径后删除，后续测试改用系统 TEMP。没有操作真实数据目录。
- 历史 Atlas 独立 step-plan/progress 不复制为第二套 Hermes 状态；导入只保留目标、终态及最近评价原因。旧 Scheduler 历史 goal_events 不回填；新审计保留最近 200 条。它们不作为活跃 Goal 真相。
- 没有启动桌面程序做交互实测或调用真实模型；本任务书要求的假执行、UI Vitest 与编译/构建已有通过证据。

## 上游手动复核

1. 使用隔离数据运行后端，在 Automation 新建目标，取响应的 `goal_session_id`，用同一 Hermes home 的 GoalManager / 聊天 `/goal` 验证 pause/resume/replace/clear 双向一致。
2. 使用脚本化假模型回复 continue、done，确认同一目标 turns_used/last_verdict/last_reason 更新、第二轮收到 Hermes continuation_prompt。
3. 设置中改变默认 child 模型并关闭子 Agent；确认已运行 child 不变，新 child 使用新默认或被拒绝。
4. 复核旧完成/暂停目标的导入以及 clear 后重启；不要以真实用户数据做迁移试验。

交付流程：文档提交后执行 `git pull --rebase origin main`、push main，主控核验 local HEAD、origin/main 及远端 main HEAD 相等，然后停止于 AWAITING_REVIEW。
