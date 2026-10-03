# P11 验收映射 — 16 个 Fake E2E 场景 vs 现有测试（2026-10-04，lane D）

任务书：`tasks/taskbooks/ATLAS-MEGA-PERSISTENT-ALWAYS-ON.md` §12 "Phase P11 — 验收：少而真"。
方法：纯静态阅读 `core/tests/`、`frontend/src/renderer/**/*.test.*` 与被测模块（未跑 pytest）。
所有路径相对 `D:\Atlas`；`file::test` 均为 `core/tests/<file>::<test>`（class 用 `::Class::test`）。

判定标准：

- **COVERED** — 现有测试以确定性 fake（fake 传输/fake LLM/fake host/跨进程子进程）端到端驱动真实模块链，断言到行为终点（不只是单点 unit）。
- **PARTIAL** — 核心路径已证，但跨模块接缝缺一环（下文写明复用哪些 fixture、新测试断言什么）。
- **MISSING** — 没有任何测试证明该行为（或行为本身尚无机制）。

---

## 1. 总表

| # | 场景 | 判定 | 证据（file::test） | 缺口（详见 §2） |
|---|------|------|--------------------|------------------|
| 1 | 创建 persistent Agent → 重启 → identity/session 还在 | PARTIAL | `test_persistent_agents.py::test_status_roundtrip_and_persistence`、`::test_crud_roundtrip`、`::test_heartbeat_roundtrip`、`::test_channel_bindings_crud`；`test_server_agents_wiring.py::test_agents_crud_over_real_app` | 无"新建 store/service 实例重开同一 root"的重启测试；`/api/agents/{id}/sessions` 仍是占位 stub（`core/atlas/api/agent_router.py::list_agent_sessions` 返回 `{"note": "wired by integration"}`，被 `test_api_full_flow` 原样断言） |
| 2 | Telegram/Feishu fake inbound → Agent → reply 原渠道 | COVERED | 全管线：`test_gateway_integration.py::test_inbound_event_runs_and_replies_on_channel`（FakeAdapter → 真 manager/bridge/_handle_run_start/FakeLLM → adapter.send，断言 chat_id+reply_to）；Telegram 适配器：`test_channels_adapters.py::test_telegram_long_poll_full_flow_and_offset_persistence`、`::test_telegram_send_edit_and_media_url_normalization`；Feishu 适配器：`test_channels_feishu.py::test_inbound_text_with_mention_resolution`、`::test_send_reply_and_interactive`、`::test_webhook_url_verification_and_ingress` | 无（组合缝可选加强：gateway 用具名 telegram 适配器跑一遍，见 §2.2） |
| 3 | 同一聊天在 channel + desktop 看同一 session | PARTIAL | `test_gateway_integration.py::test_same_session_key_reuses_conversation`（session_key 幂等映射 + sqlite `channel_sessions` 每键一行）；`test_channels_routing.py::test_peer_binding_wins_over_everything` 等 | 只证了 channel 侧映射持久；从未断言 channel 建立的 conversation 出现在桌面同源 API（`GET /api/conversations`、`/messages`）里 |
| 4 | heartbeat 无变化 → 不通知 | COVERED | `test_heartbeat_service.py::TestNoChangeContract::test_no_change_silent_zero_deliveries`（+`::test_structured_notify_false_is_silent`、`::test_hearbeat_ok_ack_is_silent`）；解析契约 `test_heartbeat_outcome.py::TestLegacyText::test_no_reply_token_only_is_silent`；活体应用：`test_gateway_integration.py::test_heartbeat_tick_and_automation_reconcile_over_live_app`（NO_REPLY → `delivered is False`） | 无 |
| 5 | heartbeat 有事件 → Agent 醒来 → 通知 | COVERED | `test_heartbeat_service.py::TestEventWakes::test_event_wake_delivers_exactly_once`、`::test_busy_deferred_by_bus_then_retry_succeeds`；投递：`::TestDelivery::test_legacy_alert_delivers_to_owner`、`::test_delivery_channel_target_passthrough`；唤醒总线：`test_heartbeat_wake.py::TestRetainRetry::test_retryable_busy_skip_is_retained_and_retried` | 通知落"渠道 target"（`telegram:12345`）只证到 FakeHost 记录 target；真 `_deliver_agent_notification`（`core/atlas/server.py` deliver→gateway send）无测试（与场景 10 同缝，见 §2.6） |
| 6 | cron one-shot | COVERED | `test_automation_engine.py::test_date_trigger_delayed_run_and_delete_after_run`（重复 sync 恰好 1 个待执行 run、成功后删除记录）；`::test_cron_schedule_fires_and_run_history_merges_cron_runs`（真 DBOS cron 触发进 run history） | 无 |
| 7 | cron recurring no duplicate | COVERED | `test_automation_engine.py::test_cron_schedule_create_is_idempotent_and_updates`（重 sync 不重建、改签名 delete+create）；`::test_run_now_no_duplicate_fire_with_heartbeat_tick`（活跃期二次 fire 拿同一 workflow，hook 恰好执行 1 次）；`::test_interval_loop_fires_pause_stops_and_resume_restarts`（recurring 多次 run、pause 后零新增） | 无（"每 tick 只 fire 一次"由 DBOS schedule + 幂等 sync + dedup receipt 组合证明） |
| 8 | restart 后 overdue/recovery | COVERED | 真跨进程崩溃恢复：`test_durable.py::test_durable_task_resumes_after_real_process_crash`；全链路：`test_long_lived_agent_e2e.py::test_long_lived_agent_survives_crash_and_recovers_context`；heartbeat overdue：`test_heartbeat_service.py::TestRestart::test_overdue_catchup_runs_exactly_once`（+`::test_cooldown_survives_restart`、`::test_scratch_and_outcome_survive_restart`） | 无 |
| 9 | no-agent script cron | COVERED | `test_automation_engine.py::test_script_payload_runs_real_subprocess`（真 echo 子进程、无 owner agent）、`::test_script_failure_yields_error_outcome`；cron×script 组合：`::test_cron_schedule_fires_and_run_history_merges_cron_runs` | 无 |
| 10 | channel-created cron 回原渠道 | MISSING | 引擎只到注入 hook：`test_automation_engine.py::test_delivery_channel_outcomes`（断言注入 `deliver` 被调、delivered/not-delivered）；真实投递函数 `core/atlas/server.py::_automation_deliver`（owner→apprise，channel→gateway）无任何测试引用（grep 全 tests 无 `_automation_deliver`/gateway 投递断言） | 需要在活体 app 上：建 delivery={mode:channel,channel:fake,target:100} 的 automation → 触发 → 断言 FakeAdapter.sent 收到该 target 的结果文本（§2.6） |
| 11 | 两个 persistent Agent group handoff | PARTIAL | 状态机：`test_groups.py::test_handoff_gives_immediate_next_slot`、`::test_handoff_continuation_cap`、`::test_round_robin_order_rotates_per_round`（FakeDispatcher+FakeLookup）；REST+真 persistent 成员校验：`test_groups_router.py::test_turns_and_timeline_pagination`、`::test_create_validates_members` | 真 dispatcher 缝：`_handle_run_start` 的 group_id 仍被闸门拒绝（`test_server_agents_wiring.py::test_run_start_group_id_is_gated_until_w8`，`core/atlas/server.py` GROUP_CHAT_MOUNT/W8 注释）；无"两个真 persistent agent 经 FakeLLM 跑一轮 handoff"的集成测试 |
| 12 | device offline → online → queued work 继续 | MISSING（后半） | 在线/离线投影：`test_devices_registry.py::test_ingress_online_timeout_window`、`::test_laptop_is_always_online`、`test_devices_router.py::test_presence_beat_and_online_projection`；takeover：`test_devices_takeover.py` 全套、`test_devices_router.py::test_takeover_full_matrix_over_http` | "离线期间排队、上线后继续执行"的机制与测试均不存在（全仓 grep devices/x2 无 queued work）；仅渠道外发队列有重试语义：`test_channels_delivery.py::test_backoff_sequence_and_dead_letter`、`::test_stale_sending_lease_is_reclaimed` |
| 13 | Computer handoff → user done → 原任务继续 | PARTIAL | 阻塞→解决→run 继续：`test_x2_pending.py::test_handoff_endpoint_resolves_blocked_request_handoff`、`::test_foreground_endpoint_resolves_blocked_confirmation`、`::test_resolve_delivers_to_every_waiter_of_the_run`（FakeBoundContext，纯 fake）；接管卡：`test_devices_takeover.py::test_handoff_card_lifecycle`、`::test_handoff_give_up_and_filters`、`test_devices_router.py::test_handoff_endpoints_lifecycle`（unit/REST 切片） | 缝：devices takeover 卡的 resolve 不触达 `x2pending.resolve`（`core/atlas/api/device_router.py` 无引用）；无"真 computer 工具阻塞 → 用户在 takeover 卡点 done → 原 run 拿到 resolution 继续"的一条链 |
| 14 | managed local runtime fake supervisor | COVERED | `test_local_models_adapter.py::test_activate_full_flow`（stub llama-server + `bootstrap.get_supervisor→None`/`endpoint.managed_root→stub` 的假 supervisor 缝）、`::test_activate_bounces_server_that_cannot_see_model`、`::test_download_catalog_model_runs_stubbed_job`、`::test_install_runtime_runs_stubbed_job`；REST 面：`test_local_models_router.py::test_sideload_server_activate_eject_diagnostics`、`::test_job_group_shapes` | 无 |
| 15 | local model activation tool-call probe | COVERED | `test_local_models_adapter.py::test_probe_ok_on_tool_call`（ATLAS_PROBE_TOOL+nonce 回环）、`::test_probe_fails_on_plain_text`、`::test_probe_fails_on_broken_arguments`、`::test_probe_fails_on_connection_refused`、`::test_activate_probe_failure_keeps_diagnosis`（激活闸门保留诊断） | 无 |
| 16 | learned skill proposal → approve → Agent 使用 | PARTIAL | 提案→批准→注册表生效→回滚：`test_skill_proposals.py::test_create_approve_applied_registry_effective_and_rollback`；learned 关系默认启用且 effective：`test_agent_skills.py::test_learned_relation_defaults_enabled_after_apply`、`::test_effective_skills_semantics`；agent 运行时技能来源：`core/atlas/server.py::_handle_run_start` 只读 `profile["active_skills"]` | 无测试证明批准后的 learned skill 真正进入一次 agent run（profile.active_skills ↔ collections.effective_skills 的桥接未证，见 §2.7） |

统计：COVERED 9（#2、4、5、6、7、8、9、14、15），PARTIAL 5（#1、3、11、13、16），MISSING 2（#10、#12 后半）。

---

## 2. PARTIAL / MISSING 的精确缺口与复用件

### 2.1 场景 1 — persistent agent 重启持久
- 现状：record 级持久化已证（store 写 TOML，`test_status_roundtrip_and_persistence` 断言 `store.get` 回读 `last_status`；`test_heartbeat_roundtrip`/`test_channel_bindings_crud` 证配置往返），但所有断言都发生在**同一实例**上。
- 缺口 A（identity 重启）：新测试 = `make_agent(service)` + `set_heartbeat` + `add_channel` + `set_status` 后，`service2 = PersistentAgentService(store=PersistentAgentStore(同一 tmp_path))`，断言 id/name/heartbeat/channels/last_status 全等。纯单测，零新 fixture。
- 缺口 B（session 重启）：`SessionMapper`（`core/atlas/gateway_service.py`，sqlite `channel_sessions`，PRIMARY KEY=session_key）是持久设计，但无"新 SessionMapper 实例打开同一 db → 同 key 返回同 conversation_id"的测试（对照 ingress 侧已有 `test_channels_ingress.py::test_new_instance_same_db_still_sees_tombstones` 的同型测试）。
- 缺口 C（REST session 面）：`agent_router.py::list_agent_sessions` 返回占位 stub；要么接线（从 SessionMapper 按 agent session_key 前缀查询）要么在验收里明确降级为"session 经 channel_sessions + conversation 持久"。
- 注：`test_persistent_agents.py` 可直接加缺口 A/B 的用例；若接线 sessions 端点，改动在 `core/atlas/api/agent_router.py`（不在另一 worker 正在改的两个文件内）。

### 2.2 场景 2（可选加强）
- gateway 集成用泛型 `FakeAdapter`；telegram/feishu 各自的 inbound 解析与 send 已单独证明。若想把"具名适配器"拉进全管线：在 `test_gateway_integration.py` 的 app_client fixture 里 `manager.register_channel("telegram", TelegramAdapter)` 并 monkeypatch 其 httpx 传输（复用 `test_channels_adapters.py` 的 fake long-poll 手法）。非必须——两级证据已闭合。

### 2.3 场景 3 — channel + desktop 同一 session
- 复用：`test_gateway_integration.py` 的 `app_client` fixture（真 app + lifespan + FakeAdapter + FakeLLMServer）。
- 新测试断言：`bundle.adapter.emit(...)` 收到回复后，
  1. `GET /api/conversations` 列表包含 `bridge.sessions.get(expected_key)` 的 conversation_id；
  2. `GET /api/conversations/{id}/messages` 同时含用户 inbound 文本与助手回复文本；
  3. （可选）`/api/agents/{agent_id}/sessions` 若已接线，返回该 conversation。
- 全部确定性：无网络、FakeLLM 文本脚本化。

### 2.4 场景 11 — 两个 persistent agent 的 group handoff（真 dispatcher 缝）
- 现状：轮转/`@` 解析/handoff 插队/上限全部由 `FakeDispatcher` 状态机证明（`test_groups.py`）；成员必须为 persistent 由 `PersistentAgentService` lookup 校验（`test_groups_router.py`）。server 的 `group_id` 闸门（run.failed "group chat wiring pending"）说明 W8 接线未完成——**注意该接缝在 `core/atlas/server.py::_handle_run_start`，属另一 worker 正在修改的文件**，本 lane 不改，只记录。
- 接线后的新测试（建议挂在 `test_gateway_integration.py` 同款 fixture）：两个真 persistent agent（FakeLLM 脚本：alice 回 "@bob 请继续"，bob 回 "done"）；`POST /api/groups/{id}/turns`（或 channel 群消息路由到 group）；断言 FakeLLM 收到两次请求且 session_key 分别为 `agent:alice:group:<gid>`/`agent:bob:group:<gid>`（复用 `test_groups.py::test_member_turn_context_and_session_key` 的键语法）、timeline 含两条成员消息、handoff 使 bob 先于轮转位发言。

### 2.5 场景 12 — device 离线队列
- 现有件：presence 投影（FakeClock 注入，`test_devices_registry.py::test_ingress_online_timeout_window`）、`TakeoverStateMachine`、渠道外发投递队列（退避+死信+租约回收，`test_channels_delivery.py`）。
- 缺口：没有"面向 device 的工作队列"。验收建议二选一：
  1. 若产品语义 = 本机（self laptop）上的 DBOS workflow 在应用重启后继续 → 该语义已由场景 8 覆盖，把场景 12 重定义为"自设备 presence 恢复 + durable 任务恢复"的组合断言（已有测试拼接即可）；
  2. 若语义 = 远程 ingress 设备离线时的任务暂存 → 需要新机制，先补设计再补测试（复用 `AutomationStore`/delivery queue 的 sqlite 模式 + `FakeClock`）。

### 2.6 场景 10 — automation 回原渠道（真投递缝）
- 复用：`test_gateway_integration.py::app_client`（lifespan 已把 `deliver=_automation_deliver` 注入引擎，见 `core/atlas/server.py` `AutomationEngine(..., deliver=_automation_deliver)` 与 `_reconcile_agent_heartbeats`）。
- 新测试：`POST /api/automations` 建 `{trigger:{kind:"interval",every_seconds:0.3}, payload:{kind:"script",script:"echo hi"}, delivery:{mode:"channel",channel:"fake",target:"100"}}` → 等 `state.last_status=="ok"` → 断言 `bundle.adapter.sent` 中存在 `chat_id=="100"` 且内容含 "hi" 的出站消息；再断言 owner 模式（delivery mode 缺省）不走 FakeAdapter。
- 该测试同时闭合场景 5 的"通知落渠道 target"半缝（`_deliver_agent_notification` 的 gateway 分支）。

### 2.7 场景 16 — 批准后的 skill 被 Agent 使用
- 已证：`SkillProposalStore.approve` → 注册表 active + 磁盘落盘 + `AgentSkillCollections` learned/enabled（`test_skill_proposals.py::test_create_approve_applied...`、`test_agent_skills.py::test_learned_relation_defaults_enabled_after_apply`）。
- 未证：`_handle_run_start` 的 `effective_skills` 只取 `profile["active_skills"]`（`core/atlas/server.py` ~6979 行），collections 的 `effective_skills()` 不在运行路径上——除非 profile.active_skills 被同步更新或运行时合并，learned skill 不会自动进入 run。
- 新测试（若桥接补上）：在 `test_server_agents_wiring.py` 的 client fixture 数据目录上建 proposal→approve → `run.start`（agent_id=origin agent）→ 断言 `fake_llm.main_requests()` 的 system/prompt 包含 learned skill 正文（或 run 的 active_skills 镜像含该技能）。**该断言落点在 server.py（另一 worker 文件），先由 controller 排期。**

---

## 3. Controller 最终验收建议实跑清单（fake-only，可全绿）

优先级 1（一次跑齐 9 个 COVERED 场景 + 回归核心缝）：

```
core/tests/test_gateway_integration.py          # 场景 2/3(channel侧)/4/5 + W1↔W4 reconcile
core/tests/test_heartbeat_service.py            # 场景 4/5/8(heartbeat 侧)
core/tests/test_heartbeat_wake.py
core/tests/test_heartbeat_guards.py
core/tests/test_heartbeat_outcome.py
core/tests/test_automation_engine.py            # 场景 6/7/9
core/tests/test_durable.py                      # 场景 8（跨进程，较慢）
core/tests/test_long_lived_agent_e2e.py         # 场景 8（win32-only，慢）
core/tests/test_server_agents_wiring.py         # 场景 1/2 的活体 app 面（他 worker 修复后）
core/tests/test_persistent_agents.py            # 场景 1
core/tests/test_local_models_adapter.py         # 场景 14/15
core/tests/test_local_models_router.py
core/tests/test_skill_proposals.py              # 场景 16
core/tests/test_agent_skills.py
core/tests/test_groups.py                       # 场景 11（状态机层）
core/tests/test_groups_router.py
core/tests/test_devices_registry.py             # 场景 12（presence 半边）
core/tests/test_devices_router.py
core/tests/test_devices_takeover.py             # 场景 13（接管卡层）
core/tests/test_x2_pending.py                   # 场景 13（阻塞→解决→继续）
core/tests/test_channels_adapters.py            # 场景 2（telegram/email/webhook）
core/tests/test_channels_feishu.py
core/tests/test_channels_manager.py
core/tests/test_channels_routing.py
core/tests/test_channels_gating.py
core/tests/test_channels_delivery.py
core/tests/test_channels_ingress.py
```

优先级 2（前端，任务书要求的 renderer/electron 面）：
- `frontend`：renderer tsc、electron tsc、Vitest（含 `frontend/src/renderer/store/persistentSlice.test.ts`、`frontend/src/renderer/pages/agents/AgentsPage.test.tsx` 的 GroupsView/DevicesPage 用例）、Vite build。

P11 补测（建议按 §2 顺序落地后再纳入验收）：场景 3 桌面同源断言、场景 10 渠道回投、场景 1 重启用例、场景 11/16 待 W8/技能桥接接线后补链路测试。

## 4. 无法确定性化 → REQUIRES_USER_DAILY_SMOKE

| 项 | 原因 | 现有最接近的 fake 覆盖 |
|----|------|------------------------|
| Telegram/Feishu/Slack/钉钉/企微/Email 真实凭据收发（真实 bot token、ws 长连、OAuth/网关） | 需要用户 token/登录 | `test_channels_*` 全套 stub 传输 + `test_gateway_integration.py` 全管线 |
| Windows 真桌面 computer-use（真鼠标注入、UAC、真窗口） | 需要真实桌面会话 | `test_x2_computer.py`（FakeBridge/hermes 桩）、`test_x2_pending.py` |
| 本地 GPU 真跑 llama-server（VC redist、真模型加载、真 tool-call） | 需要 GPU/大模型下载 | `test_local_models_adapter.py` 的 stub HTTP llama-server |
| 打包安装器/开机自启（`test_release_acceptance.py::test_nsis_install_uninstall_reinstall_acceptance`、`::test_clean_packaged_daily_usability_twice`） | 需要真安装环境 | 这两个测试本身即真机 smoke，标 REQUIRES_USER_DAILY_SMOKE |

以上均不阻塞代码交付（任务书 §12 原文）。

---

## 5. 终态附录（2026-10-04，CLOSEOUT 收口后）

§2 全部缺口已闭合，16 项不再有真实 MISSING：

| # | 场景 | 终态 | 闭合证据 |
|---|------|------|---------|
| 1 | Agent 重启持久 | **COVERED** | `test_persistent_agents.py::test_agent_identity_survives_service_restart`、`::test_session_mapper_mapping_survives_restart`；`/api/agents/{id}/sessions` 已接线（真 `channel_sessions` 查询 + conversation 元数据，`agent_router.py::list_agent_sessions`） |
| 2 | 渠道 inbound→回复 | COVERED（原判）+具名缝不变 | 无变化 |
| 3 | channel+desktop 同一会话 | **COVERED** | `test_gateway_integration.py::test_channel_conversation_visible_on_desktop` |
| 4 | 无变化不通知 | COVERED（原判） | 无变化 |
| 5 | 事件→通知 | **COVERED（全链）** | 渠道 target 半缝闭合：`test_gateway_integration.py::test_heartbeat_event_notifies_channel_target`（event wake→notify→`fake:777`→真网关外发队列→FakeAdapter） |
| 6/7/8/9 | cron/恢复/脚本 | COVERED（原判） | 无变化 |
| 10 | automation 回渠道 | **COVERED** | `test_gateway_integration.py::test_automation_delivery_reaches_channel_target`（真 `_automation_deliver`→`channel_manager.send`→FakeAdapter；owner 模式不落渠道） |
| 11 | 双 Agent 群 handoff | **COVERED** | `test_gateway_integration.py::test_group_handoff_between_persistent_agents`（3 真 persistent agent、@mention handoff 插队、bob 零发言、成员 group session 归属）；接线本体 `test_server_agents_wiring.py::test_run_start_group_id_drives_room_and_records_timeline` |
| 12 | 设备离线→工作继续 | **COVERED（选项 1 语义）** | `test_devices_registry.py::test_device_offline_window_does_not_block_local_automation_and_presence_recovers`；远程 ingress 队列不在本波语义（结果文档注明） |
| 13 | takeover→X2→原任务继续 | **COVERED** | `test_takeover_x2_bridge.py`（blocked→REST 交接卡 done→`x2_pending.resolve`→阻塞 run 恢复；give_up→GIVE_UP；409/无 waiter/pending 异常不 500） |
| 14/15 | 本地模型/probe | COVERED（原判） | 无变化 |
| 16 | learned skill 进 run | **COVERED** | `test_server_agents_wiring.py` 场景 16 测试（proposal→approve→run.start→fake LLM 请求含技能正文）；桥接 `server.py::_merge_agent_collection_skills`（显式 per-agent 行决定；decision=global 不注入——注册表已将全目录标 active，全局注入会破 8 技能激活上限，权衡记录在 CLOSEOUT result） |
