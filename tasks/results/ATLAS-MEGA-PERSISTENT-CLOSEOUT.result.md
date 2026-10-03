# ATLAS-MEGA-PERSISTENT-CLOSEOUT — 结果

> 状态：AWAITING_REVIEW（2026-10-04）
> 基线：`main @ 631b5f6`（任务书指定断点）；本轮提交：`b9e30e1`（W8 收口主批）+ 本收口批（见 git log）
> 前置：`tasks/results/ATLAS-MEGA-PERSISTENT-ALWAYS-ON.result.md`（同一连续施工的上一段，本文件只写收口）

## 0. 与任务书的对应

任务书 9 个 integration gap 全部闭合；`ATLAS-MEGA-PERSISTENT-ALWAYS-ON` 的 W1-W7 未重做，全部复用已有模块只做接线。

| CLOSEOUT | 内容 | 状态 |
|---|---|---|
| 1 | Group Chat 真正接入 Agent runtime | ✔ |
| 2 | Persistent Agent session 长期化 + sessions API | ✔ |
| 3 | Desktop / Channel 同一 conversation | ✔ |
| 4 | Automation / Heartbeat → 原渠道真投递 | ✔ |
| 5 | Atlas-owned 笔记本 offline/restart durable 续跑 | ✔ |
| 6 | Takeover ↔ X2 Handoff 桥 | ✔ |
| 7 | Learned skill → 真 Agent run | ✔ |
| 8 | backend wiring errors 清零 | ✔ |
| 9 | P11 16 项无真实 MISSING | ✔ |

## 1. 各项落点（文件级）

### CLOSEOUT-1 群聊接线
- `core/atlas/server.py`：lifespan 构造 `GroupService(GroupStore, lookup=agents_service)` + `GroupOrchestrator(dispatcher=_dispatch_group_member_turn)`，`set_group_service`→`set_group_orchestrator` 顺序绑定，shutdown 复位；`app.include_router(group_router)`（`GROUP_CHAT_MOUNT` 落位）。
- `_handle_run_start` 的 `group chat wiring pending` 闸门删除，替换为 `_start_group_turn_run`：校验群存在 + 发起者是成员，`TurnConflict`→conflict、`DispatcherNotBound`→backend、成功→`run.completed` 携 `GroupTurnReport`。
- 真 dispatcher `_dispatch_group_member_turn`：成员自己的 model/instructions/skills → 复用 `_collect_orchestrator_text` 引擎缝（无第二 Agent loop）；session lineage `agent:<id>:group:<gid>`（复用网关 SessionMapper）。
- 证据：`test_server_agents_wiring.py::test_run_start_group_id_drives_room_and_records_timeline`（alice→@bob 两人真 agent 连续执行、同 timeline）、`test_gateway_integration.py::test_group_handoff_between_persistent_agents`（3 人 @mention handoff 插队、轮转外成员经 handoff 发言、silent 成员零发言、`/api/agents/<id>/sessions` 归属）。

### CLOSEOUT-2 Agent session 长期化
- 重启持久：`test_persistent_agents.py::test_agent_identity_survives_service_restart`（同 root 重开 service/store，identity/model/heartbeat/channels/status 全等）、`::test_session_mapper_mapping_survives_restart`（SessionMapper 重开同 sqlite，同 key 同 conversation）。
- API：`agent_router.py::list_agent_sessions` 占位 stub 删除 → 读网关 `channel_sessions`（只读 sqlite，`agent:<id>:` 前缀过滤）+ conversation 元数据（lifespan 注入 `set_conversation_lookup`）。gateway_service.py 未改。

### CLOSEOUT-3 桌面/渠道同源
- `test_gateway_integration.py::test_channel_conversation_visible_on_desktop`：channel inbound → 回复 → conversation_id 出现在 `GET /api/conversations` 与 `GET /api/conversations/{id}/messages`（user+assistant 两条都在）。无第二套 channel conversation 存储。

### CLOSEOUT-4 回原渠道
- Automation：`test_gateway_integration.py::test_automation_delivery_reaches_channel_target`（`delivery={mode:channel,channel:fake,target:100}` → 真 `_automation_deliver` → `channel_manager.send` → 外发队列 → FakeAdapter 收到；owner 模式不落渠道）。
- Heartbeat：`test_gateway_integration.py::test_heartbeat_event_notifies_channel_target`（event wake → notify → `fake:777` → `_deliver_agent_notification` → 网关 → FakeAdapter）；`NO_REPLY/无变化零通知` 由 `test_heartbeat_service.py` 契约测试继续覆盖。

### CLOSEOUT-5 设备 offline/restart
- `test_devices_registry.py::test_device_offline_window_does_not_block_local_automation_and_presence_recovers`：离线窗口内本地 automation 照常执行记录 + presence 恢复 + 期间 run 可见；自设备 durable 续跑由 `test_durable.py`（跨进程崩溃恢复）+ `test_long_lived_agent_e2e.py` 覆盖。
- **Remote ingress-device queued execution: not required for Atlas-owned laptop semantics in this wave.**（任务书 §7 预留语句，正式记录在此）

### CLOSEOUT-6 Takeover↔X2 桥
- `devices/takeover.py`：卡片增 `run_id` 字段（additive，默认 "" 兼容全部旧调用）。
- `api/device_router.py`：`HandoffRequest.run_id`；resolve 成功后 `_bridge_x2_pending`：`done`→`x2_pending.resolve(run_id,"done")`、`give_up`→`cancel_run(run_id)`（懒 import + try/except，pending 侧故障不阻塞卡片结算、不 500）。
- Fake E2E：`test_takeover_x2_bridge.py`（8 测）——blocked（`wait_for_resolution` 挂起）→ REST 开卡（run_id 回显/PENDING 可见）→ done → 阻塞 run 以 "done" 恢复继续执行；give_up → `GIVE_UP`；409 双结算、无 waiter 卡、无 run_id 卡不触 X2。

### CLOSEOUT-7 Learned skill 进 run
- `server.py::_merge_agent_collection_skills`：agent-sourced run 的 `effective_skills` 在 profile.active_skills 之上合并 `AgentSkillCollections` 显式 per-agent 行（enabled→加、disabled→移除并赢过 profile）。
- 权衡（记录在案）：`decision="global"` 行不注入不清除——`_register_local_skills` 把仓库发现的全目录注册为 registry-active，全局注入会把整个目录塞进每次 run 并打爆 8 技能激活上限；learned 行是显式 per-agent 行，不受影响。
- 证据：`test_server_agents_wiring.py` 场景 16 测试（proposal→approve→relation=learned enabled→该 agent 下一次 run.start→fake LLM 请求 system/prompt 含技能正文）。唯一 SkillRegistry 未复制。

### CLOSEOUT-8 wiring errors 清零
- `test_server_agents_wiring.py` 26/38 → 全绿（本批后该文件 11/11）；`test_gateway_integration.py` 全绿。
- 环境级修复：pytest basetemp 若在仓库内且被 `.gitignore` 的 `.tmp/` 命中，`workspace_search` 的 git-listed 捷径改变行为 → 相关 parity 测试改 tempfile 免疫；fake LLM 配置补 `auto_recovery_cycles: 0`（脚本化 500 秒级到达 run-failed，而非 15/30/60s×5 可用性阶梯）；gateway fixture 写 engine home `config.yaml`（`api_max_retries:1`）。

### CLOSEOUT-9 P11 16 项
- `docs/research/2026-10-03-persistent-atlas/p11-acceptance-map.md` §5 终态附录：原 9 COVERED 不变，5 PARTIAL + 2 MISSING 全部升 COVERED，每项带闭合证据。**无真实 MISSING。**

## 2. 去重确认（任务书 §13）

- 一个 Agent runtime / SessionDB / SkillRegistry / Automation state / DBOS layer / Computer / Browser / Gateway / Device registry：审计 11 项 9 CLEAN + 2 修复，本轮无新增重复。
- Telegram 双 poll：互斥从"仅启动时"补齐运行时半边——`PUT /api/channels/accounts` 启用 telegram 即停旧 poller（`channel_router.py`，懒取 server 单例，stop 失败不影响渠道配置）。
- Scheduler 双触发：`scheduler.enabled` 默认 False（env `ATLAS_SCHEDULER_ENABLED` 可显式开启）；`/api/automations/import-legacy` 导入后暂停旧任务（`pause_legacy=True`）；显式 `[scheduler] enabled=true` 的存量配置仍可运行（用户本机 `config/atlas.toml` 属此类，未擅改）。`test_p10_dedup.py` 8 测背书。

## 3. 测试

- Backend 全量一次：**2008 passed, 1 failed, 7 skipped**（30:45）。唯一失败 `test_computer_use.py::test_real_desktop_observe_input_clipboard_and_window_management`（真桌面窗口创建在 30 分钟满载下 20s 超时，已知桌面焦点偶发），单跑复验通过（4.5s）。跳过 7 项为平台/可选依赖。
- 收口 focused 复跑（收口改动后）：**268 passed**（wiring/gateway/groups/persistent/heartbeat/automation/devices/takeover/bridge/x2/skills/channels/p10 全家，103s）。
- Frontend：renderer tsc ✔、electron tsc ✔、Vitest **155/155** ✔、vite build ✔（无前端改动，回归确认）。
- REQUIRES_USER_DAILY_SMOKE（不阻塞）：真实渠道凭据收发、Windows 真桌面注入、本地 GPU llama-server、安装器 smoke。

## 4. 完成标准核对（任务书 §16）

- [x] Persistent Agent 长期存在（重启持久 + sessions lineage）
- [x] Desktop / Channel 共用 conversation
- [x] Gateway 真能派任务（inbound→run→回执全链 fake E2E）
- [x] Heartbeat 真能主动工作（event/overdue/busy/冷却全链）
- [x] Cron/Automation 持久恢复（DBOS 跨进程恢复 + cron 幂等）
- [x] Automation/Heartbeat 结果回原渠道
- [x] 多 Agent group / handoff
- [x] Windows 笔记本 = Atlas-owned computer（device registry + presence + durable 续跑）
- [x] Human takeover 回到原任务（桥接 E2E）
- [x] Local Models 托管 + 工具调用 probe 闸门
- [x] 学到的 Skill 下一次真能用
- [x] P11 无 MISSING
- [x] integration green / frontend green
- [x] CURRENT = AWAITING_REVIEW

## 5. 未做（任务书明令禁止）

X6 realtime voice、T1、R1、MemoryOS、新 UI 大改、新一轮上游研究——均未启动。
