# ATLAS-MEGA-PERSISTENT-CLOSEOUT — 独立验收 review

> 评审人：独立验收 controller（ZCode，非施工方）
> 验收对象：`main @ 2057f17`（基线 `631b5f6` + `b9e30e1` + `2057f17` 两批收口提交）+ 本 review 的测试修复提交
> 依据：`tasks/taskbooks/ATLAS-MEGA-PERSISTENT-CLOSEOUT.md`、`tasks/results/ATLAS-MEGA-PERSISTENT-CLOSEOUT.result.md`、父任务 result、`docs/research/2026-10-03-persistent-atlas/p11-acceptance-map.md` §5
> 日期：2026-10-04

## 结论

**通过（APPROVED，附一项测试修复）。** result 声明的全部关键事实经独立实跑与代码级核查成立。独立全量复验暴露了一个施工方全量跑未踩中的**测试间歇性缺陷**（非产品缺陷，详见 §4），已修复并以全量复跑重新验收。

- local HEAD == origin/main == `2057f17`（修复提交另计，见 §4.3）；
- P11 16 项无真实 MISSING，点名证据测试逐一存在、断言真实、实跑全绿；
- P10 去重两处修复（telegram 运行时互斥、scheduler 默认关）代码与测试均成立；
- takeover↔X2 桥、learned skill runtime bridge、group runtime、channel/desktop 同会话四条链路实现与 fake E2E 证据一致；
- result 全量跑（2008 passed, 1 failed, 7 skipped）中唯一 failed 的 desktop 测试确属环境偶发（本机隔离复验 2/2 通过）。

## 1. 核查方法

静态（代码级）+ 动态（实跑）双轨，全部在本机独立执行，不采信施工方日志：

1. `git diff 631b5f6..2057f17` 全量过目（24 文件，+2286/−91；改动范围与"只接线、不重做 W1-W7"纪律一致，无新重复模块）。
2. 关键落点逐一读码：`server.py`（群派单/技能桥/投递函数/互斥/挂载）、`device_router.py`（X2 桥）、`channel_router.py`（telegram 运行时停旧）、`agent_router.py`（sessions 真查询）、`config.py`（scheduler 默认）、`automation/migrate.py`（pause_legacy）、`skills/agent_collections.py`（effective_skills 语义）。
3. P11 §5 终态映射点名的每个证据测试 grep 落实存在，并抽查断言内容是否为行为终点断言（非空转）。
4. 实跑：focused 超集 484 测 + 桌面测试隔离 2 遍 + 前端四件套 + 全量 pytest 两次（一次暴露缺陷、一次修复后重验收）。
5. 无空转测试迹象：抽查的 E2E 均断言到行为终点（fake LLM 收到的 system/prompt 正文、FakeAdapter 出站内容、timeline 次序、阻塞 run 真实恢复值）。

## 2. 重点核查项逐条结果

### 2.1 P10 去重 — 成立
- **Telegram 双 poll**：启动期互斥在 `server.py:1385-1390`（网关 telegram 未启用才启旧 poller）；本批补齐运行时半边——`channel_router.py::put_accounts` 在启用 telegram 时调 `_stop_legacy_telegram_poller()`（懒取 server 单例，stop 失败仅告警不阻塞渠道配置）。`test_p10_dedup.py` 三个专项（启用即停一次/停用不动/容忍缺失或损坏的旧服务）背书。
- **Scheduler 双触发**：`config.py` `scheduler_enabled` 默认 `False`（env `ATLAS_SCHEDULER_ENABLED` 可覆盖、显式配置可回开）；`/api/automations/import-legacy` 传 `pause_legacy=True`（`automation_router.py:255`，导入成功后仅对本次导入的任务置 paused）。默认关/显式开/env 覆盖/导入暂停/默认不触碰 5 个专项测试全绿。
- 去重清单（§13）其余 9 项：本批 diff 未新增任何第二 runtime/store/registry 模块，结构成立。

### 2.2 P11 16 项 — 无真实 MISSING，成立
§5 终态映射 16 项点名的证据测试全部存在且实跑通过，抽查断言均为行为终点：
- #1 重启持久：`test_agent_identity_survives_service_restart`（同 root 重开 service/store 全等）+ `test_session_mapper_mapping_survives_restart`（同 sqlite 同 key 同 conversation）；`/api/agents/{id}/sessions` 占位 stub 已删，改为只读 `channel_sessions` sqlite（`mode=ro` URI）+ conversation 元数据，测试含跨 agent 前缀不泄漏与未知 agent 404。
- #3 桌面同源：`test_channel_conversation_visible_on_desktop` — channel inbound 的 conversation_id 出现在 `GET /api/conversations`，`/messages` 同时含用户 inbound 与助手回复；无第二套存储。
- #5/#10 回原渠道：`_deliver_agent_notification` / `_automation_deliver` 均 owner→apprise、`channel:target`→`channel_manager.send`；两个 E2E 断言 FakeAdapter 收到指定 chat_id+内容，且 owner 模式不落渠道。
- #11 群 handoff：`test_group_handoff_between_persistent_agents` — 3 个真 persistent agent、@mention 插队（alice→carl）、silent bob 零发言、成员 group session 归属 `agent:<id>:group:<gid>`；接线本体 `test_run_start_group_id_drives_room_and_records_timeline`。
- #12 设备离线：`test_device_offline_window_does_not_block_local_automation_and_presence_recovers`；"远程 ingress-device 队列不属本波语义" 已按任务书 §7 预留语句正式记录在 result。
- #13 takeover↔X2：见 2.3。
- #16 learned skill：见 2.4。

### 2.3 Group runtime + takeover↔X2 — 成立
- 群聊：`group_router` 已挂载（`server.py:1533` GROUP_CHAT_MOUNT）；`GroupService`+`GroupOrchestrator` 按序绑定（`server.py:1322-1335`）；`group chat wiring pending` 闸门已删除（全文件无匹配）；真 dispatcher `_dispatch_group_member_turn` 复用 `_collect_orchestrator_text`（该缝定义 1 处、heartbeat/automation/group 共 5 处引用）——**确无第二 Agent loop**；session lineage 经网关 SessionMapper 持久。
- X2 桥：`device_router.py::_bridge_x2_pending` — 卡片带 `run_id`（additive 默认 ""，旧调用兼容）；`done`→`x2_pending.resolve(run_id,"done")`、`give_up`→`cancel_run`；懒 import + try/except，pending 侧故障不影响已结算卡片（不 500）。E2E 是真链路：真实 `wait_for_resolution` 阻塞 waiter → REST 开卡 → done 后原 run 以 `"done"` 恢复继续执行、waiter 注销；give_up → `GIVE_UP`；含 409 双结算、无 waiter 卡、无 run_id 卡不触 X2 等护栏，共 8 测。

### 2.4 Learned skill runtime bridge — 成立，权衡合理
- `server.py::_merge_agent_collection_skills`：仅对 `decision=="per_agent"` 行生效（enabled→并入、disabled→移除且赢过 profile）；已接入 `_handle_run_start`（:7211）与群派单（:910）两条路径。
- `decision=="global"` 行不注入不清除的权衡在 `skills/agent_collections.py::effective_skills` 语义中得到证实（registry 将全目录标 active，全局注入会破 8 技能激活上限），与 result 记录一致。
- E2E 断言到 fake LLM 实际收到的 messages 正文含技能内容——技能真的进了 run。

### 2.5 result 全量跑的唯一 desktop failed — 确属环境偶发，成立
`test_computer_use.py::test_real_desktop_observe_input_clipboard_and_window_management` 本体是真 Tk 子进程窗口 + 真鼠标/键盘注入 + 前台焦点断言，窗口创建等待仅 20s（`parent.poll(20)`），且焦点被系统拒绝时有优雅 skip 路径——满载跑批下子进程起窗口超时属典型资源竞争偶发。本机隔离复验：**2/2 通过（4.16s / 3.82s）**；独立全量复验中该测试在满载下再次失败，与"满载偶发、单跑即过"的判定自洽。

## 3. 独立实跑记录（本机，2026-10-04）

| 项 | 结果 |
|---|---|
| focused 超集 batch 1（wiring/gateway/groups/persistent/heartbeat/automation/devices/takeover/x2/skills/p10，15 文件） | **221 passed** (77.7s) |
| focused 超集 batch 2（channels 7 文件 + heartbeat wake/guards/outcome + local models 2 文件） | **231 passed** (14.1s) |
| closeout 批改动面补充（parity_wave2 / config / automation_migrate） | **32 passed** (22.5s) |
| 桌面测试隔离复验 ×2 | **2/2 passed** (4.16s / 3.82s) |
| 前端 `npm run build`（electron tsc + renderer tsc + vite build） | ✔（chunk 体积警告为既有） |
| 前端 Vitest | **155 passed** |
| 全量 pytest 第 1 次（独立复验，**暴露 §4 缺陷**） | 2016 passed, **2 failed**, 9 skipped (29:07) |
| 全量 pytest 第 2 次（§4 修复后重验收） | **2016 passed**, 2 failed, 9 skipped (28:54)——§4 缺陷已消失；2 failed = desktop 偶发（§2.5）+ `test_local_execution.py::test_cancelling_atlas_process_terminates_child_tree`（本机隔离复验 **3/3 通过**（8.1–10.0s），真进程树终止在满载下 spawn/kill 时序膨胀，与 desktop 同属"真进程×满载"资源竞争偶发类；施工方全量与本验收第 1 次全量该测试均通过） |

（focused 超集 484 测 ≥ result 声明的 268 测口径，全部覆盖并超出。收集数 2027 与施工方 2016 的差异来自环境相关的条件收集/参数化，不影响结论。）

## 4. 发现并修复：gateway 集成测试的跨测回复泄漏（测试缺陷，非产品缺陷）

### 4.1 现象
全量第 1 次复验中 `test_gateway_integration.py::test_run_failure_answers_with_one_failure_summary` 失败（施工方全量跑该测试通过）；文件级连跑呈间歇性（3 跑 2 挂），单跑恒过。失败断言：`sent[0]` 内容是 `'渠道任务已完成，摘要如下。'`（前序测试脚本的回复文本），而非本测试预期的 "HTTP 500"。

### 4.2 根因
该文件 `app_client` 是**模块级单 app**（一个 lifespan、一个 FakeAdapter 供 9 个测试共享），每个测试仅以 autouse fixture 清空 `adapter.sent`。`test_same_session_key_reuses_conversation` 只等待 3 次 run **提交**（`_submit_run` spy 计数）即结束、不等回复送达；其 run 的引擎启动耗时数秒，回复在后续测试清空 `sent` 之后才落入共享 transport，抢占了 `sent[0]`/污染了全局 `len(sent)` 断言。本机验收期间存在后台负载，引擎启动变慢、泄漏窗口变大，故单跑必过、随文件跑间歇挂；施工方全量跑属于未踩中时序。

### 4.3 修复（`core/tests/test_gateway_integration.py`，一处提交）
把对共享 `sent` 的**全局索引/全局计数断言改为按本测试自己的 peer（chat_id）过滤**——每个测试本就用互不相同的 chat_id，跨测泄漏在构造上不再可能污染断言：
- `test_run_failure_answers_with_one_failure_summary`：wait/`len==1`/内容断言全部过滤 `chat_id=="400"`；
- `test_channel_conversation_visible_on_desktop`：回复等待过滤 `chat_id=="500"`；
- `test_automation_delivery_reaches_channel_target`：owner 模式断言从 `len(sent)==before` 改为内容级（任何含 `deliver-owner-ok` 的消息不得到达 adapter），语义不变且对泄漏免疫；
- `REPLY_WAIT` 保持原值 30.0 不变（实测证明失败与超时预算无关）。

已试并否决的方案：全文件 `REPLY_WAIT` 提到 120（失败照旧，证明非超时问题）；测试 #2 末尾排水等 3 条回复（单跑即证伪——并非每个 run 都恰好一条渠道回执，该计数不变量不成立）。按 peer 作用域是唯一同时满足"语义精确 + 对泄漏免疫"的修法。

### 4.4 修复后验证
- 文件级连跑 **3/3 全绿**（31.1s / 30.8s / 33.1s）；
- 全量 pytest 第 2 次重验收：见 §3 表末行。

## 5. REQUIRES_USER_DAILY_SMOKE（不阻塞，维持 result 列表）

真实渠道凭据收发、Windows 真桌面注入常态化、本地 GPU llama-server 真跑、安装器 smoke——与本轮验收结论无关，维持原判。

## 6. 观察项（非阻塞，不计缺陷）

1. 仓库存在未跟踪的 `design/atlas-glass-prototype.html`（工作区 `?? design/`）——不在本任务范围，未纳入验收；若属有意引入应另行提交或忽略。
2. result 的"focused 268 passed"口径为施工方自选子集；本验收以 484 测超集复核，结论不受影响。
3. `test_computer_use` 的 20s 窗口创建预算在满载下偏紧（本波两次全量均挂在同一处）；属已知桌面偶发口径，不构成本轮阻塞，供后续波次参考放宽。

## 7. 完成标准复核（任务书 §16）

16 条逐条复核成立（persistent 长期存在 / desktop-channel 同会话 / gateway 派活 / heartbeat 主动 / cron 持久恢复 / 回原渠道 / group+handoff / 自有笔记本 / takeover 回原任务 / local models probe / learned skill 生效 / P11 无 MISSING / integration green / frontend green / CURRENT=AWAITING_REVIEW / 未越界启动 X6-T1-R1）。**CURRENT 状态由本 review 更新为 REVIEW_PASSED。**
