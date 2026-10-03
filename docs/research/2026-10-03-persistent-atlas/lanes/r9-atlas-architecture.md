# R9 — Atlas 本体现状地图 + 扩展点（persistent always-on mega wave 主战场勘查）

> 对象：`D:\Atlas` @ HEAD `a034bff`（工作区另有 `a88ef4b` docs 提交）。本 lane 只读，不改代码。
> 范式：逐节给出 `文件:行号` 引用；所有行号以 `a034bff` 工作区为准。
> 结论先行：Atlas 已具备"常驻化"的全部地基——Hub 独立后台进程（`atlas/runtime/hub.py`）、DBOS durable 工作流（`atlas/capabilities/durable/dbos_backend.py`）、lease 心跳式调度器（`atlas/scheduler/__init__.py`）、lease 感知的 Telegram 渠道（`atlas/telegram.py`）。本波新能力大部分是"在既有扩展点上补齐"，而不是新造骨架。四个热文件（server.py / App.tsx / useAtlasStore.ts / hermes_runtime.py）都有低侵入挂载点（§12）。

---

## 1. `core/atlas/server.py`（7925 行，热文件）

### 1.1 路由清单（按功能分组）

装饰器计数：`@app.get` 108、`@app.post` 111、`@app.put` 14、`@app.delete` 19、`@app.patch` 2、`@app.websocket` 3，共 **257 条 @app 路由**；另有 4 个 APIRouter 挂载（§1.4）。

| 分组 | 行号段 | 代表路由 |
|---|---|---|
| 健康/运行时 | 1031–1063, 4031, 4079, 6027 | `GET /api/health`(1031)、`GET /api/runtime/observability`(1041)、`GET /api/runtime/dependency-check`(4031)、`POST /api/runtime/shutdown`(4079)、`GET /api/runtime/protocol`(6027，协议版本 1.10) |
| 模型/设置 | 1066–1251 | `GET /api/models`(1066)、`POST /api/models/select`(1090)、`POST /api/models/custom`(1204)、`GET|PUT /api/settings/configuration`(1101/1167)、`POST /api/settings/test-connection`(1227)、`POST /api/images/generate`(1126) |
| 会话 conversations | 1252–1772 | list/create(1252/1259)、messages(1269)、branches(1286)、goal(1314/1324)、branch-summary(1337)、PUT(1369)、truncate(1441)、rewind/redo/rewinds(1561/1639/1665)、fork(1673)、duplicate(1711)、compact(1734)、DELETE(1754) |
| 项目 projects | 1773–1948 | CRUD(1773–1824)、项目-会话绑定(1825/1838)、recall(1846)、sources(1864–1947) |
| 网页抽取/搜索 | 1891, 1949 | `POST /api/web/extract`(1891)、`GET /api/search`(1949) |
| 工作区 workspace | 2017–2807 | trust(2017/2022)、tree(2125)、file(2169)、raw(2203)、preview(2246)、history(2319–2445)、search(2497)、rules(2741)、notes(2781/2793) |
| Git/SSH/Worktree | 2570–2740 | branches(2570)、pr(2613/2626/2656)、ssh hosts/test(2672/2677)、worktree(2685–2740) |
| 检查点/运行/LSP/进程 | 2809–3040 | checkpoints(2809)、runs changes/diagnostics(2903/2925)、lsp status(2966)、processes(3004/3016/3032) |
| Facts/记忆 | 3091–3554 | facts(3091–3116)；memory 候选/审批/知识治理约 60 条(3118–3554) |
| 工具/集成/MCP | 3557–3627, 3629, 3978, 4016–4166 | tools(3557)、custom-tools CRUD+test(3577–3627)、integrations(3629)、enabled patch(3978)、mcp servers(4016/4091/4124/4136) |
| 通知/渠道/Hub | 3670–3802 | notifications status/test/urls(3670/3775/3784)；**telegram**(3676/3683/3702)；**hub**(3712–3774：status/start/stop/tasks CRUD/run) |
| 插件/市场/外部导入 | 3804–3976 | plugins(3804–3875)、marketplaces(3877–3918)、import external(3939/3956) |
| 知识 knowledge | 4168–4215 | 4 条 |
| Agent 后端/外部会话 | 4216–4340 | capabilities(4216/4224)、backends(4238)、agents external/types(4244/4249)、backend sessions(4264/4281)、prompt/cancel/delete(4300/4320/4331) |
| 技能 skills | 4341–5375 | skills(4341)、dependencies(4355/4373/5023)、discover(4443/5176)、catalog search/inspect/approve/install(4465–4728)、lifecycle(4729–5130)、registry(5189–5257)、单技能/activate/search(5258–5374) |
| Hooks/Commands | 5376–5498 | hooks CRUD+test(5376–5476)、commands(5477/5483) |
| **调度 schedules** | 5499–5638 | list/get(5499/5515)、pause/resume(5525/5534)、create/update/delete(5543/5563/5589)、run now(5599) |
| **目标 goals** | 5639–5787, 5984–6026 | goals CRUD+pause/resume(5639–5748)、trace(5984)、run now(6003) |
| 看板/配方 | 5794–5912 | kanban boards/tasks(5794–5834)、recipes(5835–5912) |
| **档案 profiles** | 5913–5983 | `GET /api/profiles`(5913)、`POST`(5922)、`PUT /{id}`(5963)、`DELETE /{id}`(5975) |
| 用量/安全/ASR | 6033–6083, 6127 | usage(6033)、safety(6046–6063)、asr status/download(6064/6072)、subtask cancel(6127) |

### 1.2 启动流程（lifespan，553–886）

`@asynccontextmanager lifespan`（554）。初始化顺序（全局单例声明在 146–176）：

1. `ModelManager` → `MemoryStore.init()` → `UsageLedger` → `ProjectStore`（560–566）。
2. **DBOS**：`DurableBackend(data/dbos.sqlite)` + `set_dispatcher(_durable_dispatcher)` + `durable.start()`（567–570）。
3. `runtime_mgr.init(db_path)`（572，运行/事件持久化）。
4. `MCPClient.start()` → `LocalExecutionRuntime` → `CuaBackend` → `ComputerUseRuntime` → `CapabilityBus` → `BrowserUseAdapter` → `AgentBackendHost`（574–584）。
5. `SkillManager` 扫描（含 `extensions.hermes_skills` 可选源）→ `CustomToolStore` → `SkillRegistry` → `AgentCapabilityRegistry` + 约 20 个 `capabilities.register(...)`（586–810；含 `durable.agent_task.run`、`agent.delegate_task`、`computer.*`、`browser.*`）。
6. `AgentOrchestrator(...)`（785–797）→ `PluginRuntime.load_all`（804）。
7. `NotificationBus`（813）。
8. **调度器**：`if cfg.scheduler_enabled: scheduler = AtlasScheduler(agent_callback=_scheduled_goal); await scheduler.start()`（817–819）。
9. **Telegram**：`TelegramService(..., owns_lease=_owns_scheduler_lease, submit_task=_telegram_submit_task, command_handler=_telegram_command); telegram_service.start()`（821–825）。
10. C6 动态路由注册：`register_init_routes(app)`、`register_review_tools/routes()`，失败仅降级告警（827–849，**新路由模块低侵入挂载的现成先例**）。

Shutdown（851–886）：telegram → scheduler → mcp → local_execution → computer_use → x2 computer/browser → cua_backend → browser_use sessions → ssh_workspaces → agent_backend_host → durable.stop → projects → usage_ledger → memory → runtime_mgr。

### 1.3 WebSocket 通道（3 条）

- `/ws/terminal`（3042）：终端 PTY 流。
- `/ws/asr`（6084）：语音识别音频上行。
- `/ws/chat`（6361）：**Runtime Event Protocol 主通道**。客户端消息：`run.start / resume / rules.trust / run.cancel / run.steer / subtask.message / input.response / run.plan.approve / run.pause / run.resume / approval.response`（6387–6496）；服务端下行 envelope：`agent_event{run_id,event_id,sequence,timestamp,event,data}`，事件类型含 `run.started/phase/message.delta/message.completed/tool.*/approval.*/run.paused/completed/failed/cancelled` 等（6362–6385）。`RunState`(6143)、`RuntimeManager`(6224)、`runtime_mgr` 单例(6340)。

### 1.4 路由器挂载与中间件

- 中间件：CORSMiddleware(895)、**OriginGuard**（902，`atlas/origin_guard.py`；token 头 `x-atlas-api-token`，origin_guard.py:31）。
- `models_router`（909–910，`atlas/models/routes.py:20`）；X2/X4/X5 路由器集中在 916–928：`computer_router`、`browser_router`、`skills_market_router`（18 条 `@router.`）、`evolution_router`。**这是 server.py 加新路由的标准位置**。

---

## 2. Agent / Profile 体系

### 2.1 `core/atlas/agent/` vs `core/atlas/agents/`

- `core/atlas/agent/`（11 个模块）= **编排层**。`AgentOrchestrator` 实际定义在 `core/atlas/agent/__init__.py`（3095 行，class 在 :289）；`orchestrator.py` 只是 5 行 re-export（compat shim）。周边：capabilities.py（能力注册表）、checkpoints.py（shadow git）、definitions.py（子代理类型导入器）、enrichment.py（AtlasToolBridge/CodeActRuntime/**DelegationService**/MemoryReflectionBridge）、planning.py（TaskPlan）、subagent_worktree.py、todo_state.py、verification_stop.py 等。
- `core/atlas/agents/` = **外部 Agent 后端适配器**（ACP 协议）：`backends/{claude,codex,hermes,pi,zcode}.py`，`create_backends()`（backends/\_\_init\_\_.py:7–16）惰性创建；由 `atlas/runtime/backend_host.py:11 AgentBackendHost` 托管（server 4264/4281 的外部会话端点、delegation 都走它）。

### 2.2 AgentProfile（等价物：dict + TomlRecordStore，无 dataclass）

- 存储：`TomlRecordStore`（`core/atlas/task_artifacts.py:59`，`list/get/put/delete`，`DATA_ROOT/profiles/*.toml`）；server 侧入口 `_profile_store()`（server.py:188，每次调用 `seed_profiles`）。
- 字段白名单 `_validate_profile`（server.py:5932–5958）：`id, name, description, model, reasoning_effort, instructions, active_skills, tools{allow:list|null, deny:list}, mode("act"|"plan"), created_at, updated_at`。`reasoning_effort ∈ {minimal,low,medium,high}`（5938）。
- **内置三角色** `DEFAULT_PROFILES`（task_artifacts.py:126–130）：`default`(默认/act)、`architect`(架构师，allow=[local_file, coding.repo_map, coding.ast_grep.run]，mode=plan)、`reviewer`(审查员，同 allow，act)。`seed_profiles`(134) 幂等播种 + 英文 legacy 文案迁移（137–160）。删除保护：server.py:5978 `{"default","architect","reviewer"}` 409。
- 前端类型：`backend-adapter/src/types.ts:374 AgentProfile`（同字段）；`ProfilesPanel.tsx`（75 行）接 `profiles/models/skills` props，`backend.saveProfile/deleteProfile` 读写（:24–44），`BUILT_IN` 集合锁删除（:7）；store 侧 `profiles` slice + `reloadProfiles/setProfile`（useAtlasStore.ts:83/160–161）。
- **profile → run 的注入点**：`_handle_run_start` server.py:6550–6562 —— `run.start` 带 `profile_id` 时合并 profile 的 `active_skills/mode/model/reasoning_effort`（run 级字段可覆盖）。

### 2.3 子代理 / delegation（C1）

- 内部子任务：`AgentOrchestrator._run_atlas_subtask`（agent/\_\_init\_\_.py:485–648）——独立子 conversation（:502）、worker 提示词（:506）、角色 `leaf|orchestrator` + 深度限制 `max_spawn_depth=2`（:516–521）、leaf 禁 `delegate_task/ask_user/...`（:522–524）；工具白名单交集 `engine/tool_permissions.py`（intersect_tool_allow）。
- 外部委派：`delegate_task`（agent/\_\_init\_\_.py:458–468）→ `DelegationService`（agent/enrichment.py）→ `AgentBackendHost`；Hermes 原生 `delegate_task` 工具桥接在 hermes_runtime.py:709–716（`agent._dispatch_delegate_task`）。
- C1 测试：`core/tests/test_c1_child_policy.py`（白名单交集 :11、inline delegate 生命周期 :26、native child 限制 :41）、`test_c1_inline_tools.py`、`test_c1_lifecycle_subtask.py`、验收 `test_c1_websocket_acceptance.py`（真实 uvicorn 子进程 + FakeLLM）。
- 子代理"类型"定义（另一套，导入式）：`agent/definitions.py:14–21 BUILTINS`（explore/researcher/plan/oracle/verifier/general），支持 Claude/Codex(.toml)/Copilot(.agent.md)/OpenCode/workspace `.atlas/agents/*.md` 导入（:92–101），端点 `/api/agents/types`(server.py:4249)。

---

## 3. 会话体系

### 3.1 两层真相

- **Atlas 侧（SQLite `data/atlas.db`）**：`MemoryStore`（`core/atlas/memory/__init__.py:94`，4255 行）。`conversations` 表（:123–144）：`title/pinned/archived/workspace/worktree_*/parent_conversation_id/fork_message_id/permission_mode/allowed_paths/executor/sandbox/extra_roots/source`（`source` 默认 desktop，Telegram 写 "telegram"，server.py:226）；`messages`（:146）、`conversation_rewinds`（:159）。API：create/list/get_conversation/update(704/714/3877/3896)、save_message(777)、branch summaries(834)、session_search(892)。
- **Hermes 侧（`HERMES_HOME` = `DATA_ROOT/engine/`，`state.db`）**：`hermes_state.SessionDB` 是**跨轮次权威历史**（hermes_runtime.py:775–789 注释明确：Atlas 文本 history 只用于导入 C1 之前的数据）。桥接层 `engine/session_sync.py`（302 行）：`capture_session/restore_session/delete_session`(25/30/42)、`rewind_to_atlas_message`(47)、`fork_session`(64)、`list_branch_tree`(105)、goal 系列 `goal_state/set_goal/mutate_goal/record_goal_event/goal_events`(206–287)、`append_branch_summary`(288)。分支摘要 `engine/branch_summaries.py`（282 行）；会话标题 `engine/session_titles.py`。

### 3.2 `engine/hermes_runtime.py`（890 行）驱动方式

- `HermesRuntime`（:67）：`home = DATA_ROOT/engine`；`run_turn`（:347–890）把 Hermes 同步 `AIAgent.run_conversation` 放到 worker 线程（`run_sync` :760，`asyncio.to_thread`），回调 emit 到 asyncio queue 再逐条 yield：`chunk/tool_call/tool_result/input.required/run.compaction.progress/process.completed/run_usage/run.recovery.notice/session.title/hermes.result`。
- 会话语义：worker 线程内先从 Hermes SessionDB 读 `get_messages_as_conversation(conversation_id, include_ancestors=True)` 作为 turn_history（:776–789）；`input_callback`/`on_clarify`(:448) 支撑 ask_user；`steer_queue` + `agent.steer`（:843–858）；cancel → `agent.interrupt(hard_cancel=True)`（:839）；子代理经 `atlas_delegate`(:709) 回到 Atlas registry；MoA 参考模型 `collect_moa_references`(:83)；compaction `compact_session`(:254)；`build_atlas_layer`(:740) 改写系统提示为 "You are Atlas"。
- 系统提示词来自上游 pinned 包 `hermes-agent @ git+...@7912500ffd...`（core/pyproject.toml:47；已装 0.21.4）。

### 3.3 一条消息的调用链（server → runtime → 回复）

```
前端 ws run.start
→ ws_chat (server.py:6361) 消息分派
→ _handle_run_start (server.py:6499)：workspace/extra_roots/profile/attachments//review 拦截 校验
→ RunState(run_id, conv_id, model) (server.py:6143; 实例化 :7042)
→ run.task = create_task(execute) (server.py:7057)
→ orchestrator.run(...) 消费 (server.py:7634；定义 agent/__init__.py:2186)
→ [hermes 引擎分支] execute_hermes_turn (agent/__init__.py:2599)
→ HermesRuntime(data_dir=DATA_ROOT).run_turn (hermes_runtime.py:347)
→ worker 线程 AIAgent.run_conversation（SessionDB 历史 + 工具循环）
→ 事件经 callback→queue→yield 回 orchestrator → runtime_mgr envelope → /ws/chat 下行
```
另两条入口复用同一链：Telegram `_telegram_submit_task`（server.py:208，conn_id="telegram"）；定时目标 `_run_scheduled_goal`（server.py:415，conv=`scheduled-goal-<task_id>`，while 循环 run→`evaluate_goal_after_turn`→续跑，goal 状态存 HERMES_HOME）。

---

## 4. 调度

### 4.1 AtlasScheduler（`core/atlas/scheduler/__init__.py`，967 行）

- 数据模型 `ScheduledTask`（:75–124）：`id,name,description,trigger_type(cron|interval|date|event :47–52),trigger_args,action("goal" 或 "agent:<message>"),status(active|paused :63),tags,created_at,updated_at,last_run_at,next_run_at,run_count,legacy_goal*(迁移用),runs(仅留最近 20)`。
- TOML 持久化：`data/schedules.toml`（`_default_schedules_path` :127–130；load/save :176/208；human-editable，文件头注明）。
- 触发循环：APScheduler 4.x `AsyncScheduler`。`start()`(:354) 先抢 **lease 文件**（`_claim_lease` :384，`_lease_loop` :459 每 2 秒心跳 `_heartbeat_lease` :415）；**只有 lease 持有者**启动 APScheduler（`_activate_if_lease_owner` :437–456：migrate hub tasks → 从 TOML 重载 → `configure_task`+`add_schedule(conflict_policy="replace")` → `start_in_background`）；非持有者只做 mtime 热重载（`_reload_shared_tasks` :575 / `_refresh_if_changed` :481）——多窗口/Hub-桌面双实例安全。
- **missed-run 行为**：Atlas 自己不追补——重注册用 `conflict_policy="replace"`，APScheduler 4 默认 misfire 策略（过点即跳过，不补跑），重启后从"下一个触发点"继续。没有 catch-up/backfill 逻辑（心跳/补跑是本波要补的洞）。
- 事件触发：`dispatch_event`（:607，2 秒去重）；`file.changed` 用 watchdog 目录监听（`_start_file_watchers` :528）；server 侧 `scheduler.dispatch_event` 挂在 run 事件上（server.py:7331）。
- 执行：`_make_executor`（:673）记录 run（:678–688）→ `goal`→`agent_callback(task_id,"")`、`agent:<msg>`→`agent_callback(task_id,msg)`（:696–706），callback 即 server.py:317 `_scheduled_goal`。
- Hub 任务一次性并入 canonical store：`_migrate_hub_tasks`（:586）。
- 后端 API：`/api/schedules*`（server.py:5499–5638）、goals（5639–6026，`_goal_payload` :5609、`_goal_session_id` :341）。
- 前端：`AutomationPage.tsx`（203 行）用 `/api/schedules` CRUD + `/api/hub/status|start|stop`（:75–140，"后台常驻"开关即 Hub）；`GoalsPanel.tsx`（207 行）用 `/api/goals` + `/trace` + `/run`（:70–201）。
- 根目录 `engine/cron`、`engine/pairing`：**空目录，无任何代码引用**（全仓 grep 仅 `agent/prompt_caching.py:134` 的字符串枚举提到 "cron/webhook"）。真正的 Hermes home 是 `data/engine/`（其 `cron/ pairing/ sessions/ hooks/ memories/ skills/` 子目录也已建但为空）——属 Hermes 约定目录，不是 Atlas 功能。

---

## 5. 渠道现状

- `core/atlas/telegram.py`（262 行）**收发双向**，长轮询：`_poll_loop`（:139）`getUpdates(offset, timeout=25)`；token 存 OS keyring（`KeyringCredentialStore` :24，键 `atlas.telegram.bot_token`）；设置 `data/telegram.json`（enabled/allowed_user_ids/default_workspace/notify_on，:63–120）。
- 入站：文本 → `submit_task`（server.py:208 `_telegram_submit_task`：新建 conversation（permission=ask_writes，source=telegram）→ `_handle_run_start` → 等 run 结束 → 回摘要+改动文件数）；`/`命令 → `_telegram_command`（server.py:238：/list /status /stop）；审批 → inline keyboard `request_approval`（:218，允许/拒绝 callback，10 分钟过期）。
- **lease 感知**：`owns_lease()` 不成立就休眠（:146）——Hub 开着时由 Hub 进程收发（hub.py:179 有平行实现）。
- 后端 API：`GET|PUT /api/channels/telegram`、`POST .../test`（server.py:3676/3683/3702）。前端 `TelegramPanel.tsx`（75 行，App.tsx SheetPane 'telegram'）经 backend-adapter 调用。
- **其他渠道：没有**。全仓无 email/discord/slack/webhook 渠道代码；`notifications/apprise.py`（NotificationBus）是系统级通知外发（toast/apprise targets），不是聊天渠道。渠道网关移植评估见同目录 `r5-hermes-channels.md`。

---

## 6. 设备 / Computer

- 执行层（三条腿）：
  1. `capabilities/computer/cua_backend.py`（Cua 驱动 0.28.2）+ `uia_backend.py`（pywinauto 窗口枚举）；`capabilities/browser/browser_use.py`（Browser Use 0.13.10）。
  2. `tools/computer_use.py`（ComputerUseRuntime，orchestrator 内置工具）与 **X2 桥**：`tools/x2/computer.py`（`X2ComputerRuntime` :272，Hermes computer 工具优先 + legacy 回退、前台确认、步骤记录/暂停 :538–583）、`tools/x2/browser.py`（含 handoff 等待）、`tools/x2/pending.py`（**人审卡片解析的唯一通道**）、`tools/x2/recording.py`（录制→SKILL.md）、`tools/x2/permissions.py`、`tools/x2/hermes_config_sync.py`。
  3. REST 面：`api/computer_router.py`（`/api/computer/status|foreground|pause|runs/{id}/steps`，:36–78）、`api/browser_router.py`（`/api/browser/handoff|settings|recordings*|vault`，:77–267），两者都自带 `_require_trusted_origin` 双保险。
- **device registry / pairing：不存在**。`engine/pairing`、`data/engine/pairing` 均为空目录，grep 无实现。设备注册/配对是全新能力，可仿 `TomlRecordStore`（task_artifacts.py:59）建 `data/devices/*.toml` 或独立 sqlite。
- 相关：`config.py:182/188` `local_execution_permission_mode` / `computer_use_permission_mode`；ASR `/ws/asr`（server.py:6084）是语音入口；ssh 工作区（server.py:2672，`ssh_workspaces`）是"远程机器"现有形态。

---

## 7. 模型 / Provider 配置

- 配置三层：`atlas.toml`（`config.py:212 load_config`；`AtlasConfig` :66：`gateway_base_url` 默认 `https://api.monkeyapi.net` :111、`gateway_api_key` :114、`custom_models` :121、scheduler 开关 :163–174、权限模式 :182–192）+ 用户设置 `data/user-settings.json`（`load/save_user_settings` :35/48，含 gateway_base_url/api_key/compression_model/subagents_*）+ 运行时 `/api/settings/configuration`（server.py:1101/1167）。
- `ModelManager`（`core/atlas/models/__init__.py:79`，449 行）：`_api_base/_api_key`（:95–96，用户设置优先）、LiteLLM 全局配置（:108）、`current_model`(:147)、`list_models`(:167，合并 custom models)、`resolve_api_key`(:317)。`models/manager.py` 是 re-export shim。
- Provider 目录：`models/catalog.py`（276 行，16 家）字段 `id/label/hermes_provider/api_mode(openai|anthropic_messages)/default_base_url/docs_url/notes`；**Ollama** :173–183（`http://127.0.0.1:11434/v1`，custom profile 别名）、**LM Studio** :184–192（`http://127.0.0.1:1234/v1`，hermes 有 provider=="lmstudio" 专属路径：显式/JIT 模型加载）。`models/models_dev.py` 做 models.dev 元数据对齐（lmstudio :152）。
- reasoning：`models/reasoning_effort.py`、`models/reasoning_stages.py`（profile 与 run 级均可覆盖）。前端模型管理在 SettingsPage 的 models sheet（store：`providers/models/addCustomModel/saveProviderConfig/addProviderKey` useAtlasStore.ts:103–118）。

---

## 8. 前端骨架（`frontend/src/renderer/`）

- **无路由库**：`App.tsx`（1125 行）用 `const [view, setView]`（:102）切换页面；`View` 联合类型与 NAV 定义在 `shell/Sidebar.tsx:11/13–22`：`home 首页 | board 看板 | code 项目 | create 创作 | auto 自动化 | memory 记忆 | skills 技能 | evolution 自动追新`。view→页面渲染集中在 App.tsx:953–1013。轻面板走 `SheetPane`（App.tsx:50）：`models|advanced|usage|profiles|hooks|tools|telegram|shortcuts|appearance|plugins|notifications`。
- `store/useAtlasStore.ts`（1039 行）`AtlasState`（:25–97）主要 slice：连接/配置（apiBaseUrl、providerBaseUrl、apiKeyConfigured、models、providers、reasoningStages）、会话（conversations、conversationMessages、activeConversationId、pinned/archived/unread）、运行（runs、activeRunId、artifacts、queue、pendingSteers、followUpMode）、档案（profiles、recipes、customCommands、profileId、reasoningEffort）、杂项（worktreeRequests、init*）；约 70 个 action（:98–166）。窄选择器 + `useShallow` 消费（App.tsx:88）。
- `shell/`：`Sidebar.tsx`（导航+会话列表）、`HomeView.tsx`（55 行：问候+建议+最近会话）、`Inspector.tsx`（任务侧板）、`panels/`（chat 内嵌面板：Browser/Changes/Files/Processes/PullRequest/Specs/Terminal/Empty/FileHistoryMenu）、`themes.ts`（3 主题：light 白瓷 / aurora 晨光 / dark 夜航，写 `<html data-theme>`）。
- 主题 token：`styles/app.css` —— `:root,[data-theme=light]` :12、`[data-theme=aurora]` :51、`[data-theme=dark]` :89；CSS 变量（--line/--brand/--danger…）+ Tailwind 语义类（bg-sunken、text-fg、card-surface 等）。
- 服务层：`services/api.ts`（fetch 封装）、`runtimeEvents.ts`（协议 envelope 解析）、`x2Api.ts`；类型与 backend 门面统一在 `backend-adapter/src/{types,client,mock}.ts`（`AgentProfile` types.ts:374）。

---

## 9. DBOS 痕迹（core/ 内）

- `core/atlas/capabilities/durable/dbos_backend.py`（160 行）：`DurableBackend` :43 —— 系统库 `data/dbos.sqlite`（:48）、`@dbos.workflow _agent_task_workflow` :108、step 桥回 server 事件循环（:97）、`run_agent_task` :121、未启动时直跑兜底（文件头契约注释）。
- `core/atlas/server.py`：lifespan 初始化 + dispatcher（567–570，`_durable_dispatcher` :300 附近）、shutdown `durable.stop()`（872）、能力 `durable.agent_task.run`（:765 附近）、`dbos_status` 依赖探测（import :63）。
- `core/atlas/runtime/hub.py`（Hub 拥有 durable backend，文件头 :1–13）与 `runtime/capability_bus.py` 各有引用。**没有** `import dbos` 散落在业务模块——全部收口在 DurableBackend。
- 已有验收：`core/tests/test_durable.py`、`test_long_lived_agent_e2e.py`（**跨进程崩溃→DBOS 恢复→新会话恢复上下文** 的完整 E2E，:1–50）。

---

## 10. 测试约定

- 后端：`core/tests/` 129 个文件；`conftest.py`（32 行）autouse 沙箱——HOME/APPDATA/ATLAS_DATA_DIR/HERMES_HOME 指到临时目录、清空所有 `*_API_KEY/_TOKEN` 环境变量、`ATLAS_SCHEDULER_ENABLED=false`、写最小 `atlas.toml`（engine="hermes"）、`ATLAS_API_TOKEN` fixture。
- fakes/：`fake_llm_provider.py`（**真 HTTP** OpenAI 兼容回环服务器，脚本化 ToolCall/Text/StallMidStream，记录请求体；`write_hermes_home` 造 HERMES_HOME）、`fake_mcp_server.py`、`fake_lsp_server.py`、`k1_harness.py`。
- E2E 样板：`test_c1_websocket_acceptance.py` —— `IsolatedBackend`（:14）在随机空闲端口起真实 `uvicorn atlas.server:app` 子进程，环境全隔离（:36–52），websockets 客户端连 `/ws/chat`，FakeLLM 驱动整条真实链路（只脚本化 provider）。`test_long_lived_agent_e2e.py` 是跨进程 durable 样板。
- 运行方式（docs/plan/EXECUTION-GUIDE.md:30）：`cd core && .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp "$TEMP/pt-x" --ignore=tests/test_computer_use.py`（uv 管依赖，core/pyproject.toml dev extra：pytest/pytest-asyncio/ruff；`asyncio_mode="auto"` :80；ruff line-length=100 :73）。
- 前端（frontend/package.json scripts :9–25）：`npm test` = `vitest run --root .`；全量门禁（EXECUTION-GUIDE.md:33）`npx tsc -p tsconfig.renderer.json --noEmit && npx tsc -p tsconfig.electron.json --noEmit && npx vitest run && npx vite build`；adapter 单测 `test:adapter`。

---

## 11. 命名 / 风格约定

- Commit（git log -25）：conventional `type(scope): 摘要`——type ∈ feat/fix/docs/chore/review；scope 用波次代号（c1…c6、m2…m8、m8-r、x2/x4/x5、k1、mega-persistent、plan、tasks、research），上游同步提交带 pinned hash（如 `chore(m8-r2): pin hermes-agent to ... 7912500ffd (upstream eb7e862032)`）。
- 模块命名：包/模块 snake_case、类 PascalCase；存在"re-export shim"惯例（`agent/orchestrator.py`、`memory/store.py`、`models/manager.py` 均为 ≤5 行转发，真身在各包 `__init__.py`）——新代码**不要**再造 shim，直接放子模块。
- 注释/文案：docstring 与结构日志英文（structlog 点分事件名 `scheduler.task_fired`）；**面向用户字符串与 UI 文案中文**；波次集成点用中文注释标注（如 server.py:827 C6 降级注释）。ruff：E/F/I/N/W/UP，line-length 100。
- 前端：单文件组件 + zustand；TS 严格（双 tsconfig）；测试文件 `*.test.ts(x)` 与源码同目录。

---

## 12. 扩展点清单（本波各新能力 → 挂载位置）

| 新能力 | 后端挂载点 | 前端挂载点 | 热文件最小改动 |
|---|---|---|---|
| **persistent agent（常驻代理）** | `runtime/hub.py:119 hub_main`（后台平面已存在：lease+DBOS+orchestrator）；新循环做成 hub 内独立 asyncio task，经 `DurableBackend`（durable/dbos_backend.py:43）拿崩溃恢复；新文件建议 `atlas/runtime/persistent.py`，不要塞 server.py | 会话列表已有 `source` 字段可区分常驻会话（memory/\_\_init\_\_.py:141）；新增状态走 `store/useAtlasStore.ts` 新 slice | server.py 只在 lifespan 加 ≤3 行（仿 telegram :821–825）+ shutdown 一行 |
| **gateway（渠道网关）** | 新包 `atlas/channels/`（adapter ABC 见 r5 报告）；每个渠道仿 `TelegramService`（telegram.py:63）四件套：settings/update_settings/start/stop + `submit_task/command_handler` 回调；lifespan 注册点 :817–825，shutdown :851 | `SheetPane` 联合类型加一项（App.tsx:50）+ 复用 TelegramPanel 版式；渠道状态 API 挂 `/api/channels/*`（现成前缀 :3676） | server.py 仅 import + 两处 ≤5 行（动态注册先例：register_init_routes :826–849，可做到 0 改动——用 entry-point 式注册） |
| **heartbeat（心跳/补跑）** | `scheduler/__init__.py`：`ScheduledTask` 加字段（:75）+ 新 `TriggerType`（:47）或独立心跳任务类；missed-run 追补逻辑放 `_activate_if_lease_owner`（:437）重注册时对比 `next_run_at`；lease 心跳（:459）已是 2 秒节拍器，可挂守护钩子 | AutomationPage.tsx 触发器类型扩展（`Freq`/`EventKind` :27–28） | server.py 无需改（/api/schedules CRUD 已全） |
| **automation（自动化增强）** | 事件源扩展走 `dispatch_event`（scheduler :607）+ `runtime/hooks.py` 事件名表（:24–27）；新触发器在 `_make_trigger`（:296）加分支 | AutomationPage.tsx | 0（API 齐全） |
| **device（设备注册/配对）** | 新 store：`TomlRecordStore(kind="devices")`（task_artifacts.py:59 现成）；配对码/审批复用 `tools/x2/pending.py` 卡片通道；路由新建 `atlas/api/device_router.py`，在 server.py:916–928 一行 include；执行层挂 `CapabilityBus`/`capabilities.register`（lifespan :636+） | Sidebar NAV 加 view 或 Inspector/panels 加面板；`services/` 加 api client | server.py 一行 include_router + lifespan 两行 |
| **local-model（本地模型）** | `models/catalog.py` 已有 ollama/lmstudio 条目（:173/:184）；探测/健康检查加在 `ModelManager.list_models`（models/\_\_init\_\_.py:167）或新 `models/local.py`；Ollama 云端条目 models_dev.py:144 已预留 | SettingsPage models sheet（store actions :103–118 已支持 custom/base_url/key） | server.py 0（/api/models 系列已覆盖） |
| **skill workshop（技能工坊）** | `atlas/skills/`（acquisition/lifecycle/distribution/bundles 已厚）；新工作台逻辑放新子模块，路由走 `skills_market_router`（server.py:928 已挂）；"录制→技能"先例：browser_router.py:178 to-skill | SkillsMarketPage.tsx / SkillDiscoveryPage.tsx 扩展 | server.py 0（market 路由器已挂载） |
| **UI（新页面/新面板）** | —— | `Sidebar.tsx:11/13` 加 View+NAV 各一行 → App.tsx :1005–1013 加一个 view 分支（组件放 `pages/`）→ `useAtlasStore.ts:25` 加独立 slice（或新 store 文件）→ 类型加 `backend-adapter/src/types.ts` | App.tsx 约 2–4 行、useAtlasStore 按域拆分新增，不重构现有 slice |

### 热文件防污染守则

1. **server.py（7925 行）**：一律"新路由器文件 + include_router（:916–928 区块）+ lifespan 增量（:817–849 区块，仿 telegram/降级注册模式）"；业务逻辑进 `atlas/channels|devices|runtime/` 新模块；禁止在既有路由函数体内加分支。
2. **hermes_runtime.py（890 行，上游 pinned 同步文件）**：只允许通过 `run_turn` kwargs 或回调注入扩展；新引擎特性放新 `engine/*.py`（session_sync/steer_dispatch 模式），保证上游 tail-sync 可合并。
3. **App.tsx（1125 行）**：新能力 = 新 `pages/XxxPage.tsx` + NAV 一行 + view 分支一行；全局状态放 store/新文件，不扩大 App.tsx 本体 state。
4. **useAtlasStore.ts（1039 行）**：新领域独立 slice 文件 + `combine`，或独立 zustand store；复用 `backend-adapter` 门面而非散装 fetch。
5. 一切新 E2E 按第 10 节样板：IsolatedBackend + FakeLLM，环境全隔离（conftest 沙箱已保证）。
