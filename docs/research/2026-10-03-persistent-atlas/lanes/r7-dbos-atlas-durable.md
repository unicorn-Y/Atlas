# R7 — DBOS durable execution × Atlas 现状调研

> Lane R7 · 2026-10-03 · 只读调研，未改任何代码。
> 源码冻结：DBOS `D:\Atlas-persistent-sources\dbos-transact-py` @ `03fb5c92`（2026-10-01，`git describe` = `3.2.0-4-g03fb5c9`，即 3.2.0 后 4 个 commit）；Atlas `D:\Atlas` @ `a034bff`。

## 结论速览

1. **DBOS 3.x 原生支持 SQLite 且是默认后端**（`DBOSConfig.system_database_url` 缺省即 `sqlite:///{name}`），单机 Windows 无 Docker/Postgres 可跑，Atlas 已经在用（`data/dbos.sqlite`）。
2. **DBOS 3.0（Atlas 当前 pin）已内置动态 cron 调度器**：`DBOS.create_schedule / pause / resume / list / delete / trigger / backfill`，调度的 workflow_id 形如 `sched-{name}-{iso时间}` 天然去重（no duplicate fire），`automatic_backfill=True` 即 missed-run 补跑，`cron_timezone` 支持 IANA 时区。
3. Atlas 现状是"**两个半调度系统**"：AtlasScheduler（APScheduler 4.x + TOML + 进程租约）负责触发，DurableBackend（DBOS）只做一个通用的 `_agent_task_workflow`（单 step 桥接回 server 事件循环），触发与执行状态脱节——**durable 只覆盖执行、不覆盖调度**，missed-run 只在"已触发的 run 中途崩溃"时可恢复；进程死在两次触发之间则该次触发直接丢失（TOML 的 `next_run_at` 只是展示）。
4. 定型方向（本 lane 结论）：**Atlas Automation = 产品状态（TOML/后续可迁）+ DBOS = durable execution handle**。唯一 owner 应为 **DBOS**（调度+执行一体），AtlasScheduler 退役为兼容层后删除；禁止两个 scheduler 并存。

---

## 1. DBOS Python 公开 API（源码确认）

公开面：`dbos/__init__.py`（`__all__`）：`DBOS, DBOSClient, DBOSConfig, DBOSConfiguredInstance, Queue, QueueRateLimit, StepOptions, EnqueueOptions, WorkflowHandle/Async, WorkflowStatus, WorkflowSchedule, ClientScheduleInput, ScheduleInput, SetWorkflowID, SetWorkflowTimeout, WorkflowIDReusePolicy, DuplicationPolicy, Debouncer/DebouncerClient, Serializer, error, run_dbos_database_migrations, SQLAlchemyDatasource/AsyncSQLAlchemyDatasource, ...`

### 1.1 生命周期（`dbos/_dbos.py`）

```python
class DBOSConfig(TypedDict, total=False):   # _dbos_config.py:17
    name: str
    system_database_url: Optional[str]      # 缺省 sqlite:///{name}（SQLite 为默认！）
    db_engine_kwargs / sys_db_pool_size / sys_db_polling_concurrency
    application_version / executor_id / dbos_system_schema
    run_migrations (默认 True) / use_listen_notify (默认 True, PG only)
    scheduler_polling_interval_sec (默认 30.0) / notification_listener_polling_interval_sec
    serializer / conductor_key / conductor_url / enable_otlp ...
```

```python
DBOS(config: DBOSConfig)          # 单例（__new__ 缓存 _dbos_global_instance）
DBOS.launch()                     # 同步；起 sys_db+migrations、恢复线程、队列线程、超时线程、调度线程
DBOS.destroy(destroy_registry=False, workflow_completion_timeout_sec=0)
DBOS.migrate(system_database_url, *, schema="dbos", application_role=None)
DBOS.reset_system_database(...)   # 测试用
```

`_launch()`（`_dbos.py:619`）依次做：建 SystemDatabase → run_migrations → 注册 app version → **启动恢复**（`_dbos.py:709-723`：无 conductor 时 `get_pending_workflows(executor_id, app_version)` → `startup_recovery_thread` 后台逐个 `_recover_workflow`）→ 通知监听线程 → 队列后台线程 → workflow 超时线程 → 动态调度线程（`dynamic_scheduler_loop`，默认 30s 轮询，启动后前 60s 每 1s 快轮询）。

### 1.2 workflow / step 装饰器（当前写法，无 `@DBOS.dbos()` 这种东西；类用 `@DBOS.dbos_class()`）

```python
@DBOS.workflow(name=None, max_recovery_attempts=100, serialization_type=None, validate_args=None)
async def wf(payload: dict) -> dict: ...

@DBOS.step(name=None, retries_allowed=False, interval_seconds=1.0, max_attempts=3,
           backoff_rate=2.0, should_retry=None, preemptible=False, timeout_seconds=None)
async def st(payload: dict) -> dict: ...
```

- workflow 内必须经 step/DBOS API 才有 durable 语义；step 失败重试可配指数退避 + `should_retry` 谓词；async step 支持 `timeout_seconds`/`preemptible`。
- `DEFAULT_MAX_RECOVERY_ATTEMPTS = 100`（`_registrations.py:10`），超过后状态 `MAX_RECOVERY_ATTEMPTS_EXCEEDED`。

启动/入队/查询：

```python
DBOS.start_workflow(fn, *args) -> WorkflowHandle           # 立即执行（带唯一 workflow_id）
DBOS.start_workflow_async(fn, *args) -> WorkflowHandleAsync
DBOS.enqueue_workflow(queue, fn, *args)
DBOS.enqueue_workflow_with_options(options: EnqueueOptions, *args)  # 同步/async 变体
DBOS.retrieve_workflow(workflow_id) -> WorkflowHandle
DBOS.get_workflow_status(workflow_id) -> WorkflowStatus | None
DBOS.get_result(workflow_id); DBOS.wait_first(handles, ...)   # 等任一完成
DBOS.list_workflows(...)                                    # 按 status/name/时间等过滤（含 async）
```

`EnqueueOptions`（`_enqueue_options.py`）：`workflow_name, queue_name` 必填；可选 `workflow_id, workflow_id_reuse_policy("return-existing"|"reject"), app_version, workflow_timeout, delay_seconds, deduplication_id, duplication_policy("reject"|"return-existing"), priority(0~2^31-1, 0 最高), queue_partition_key, authenticated_user/roles, serialization_type, attributes, application_name, otel_context`。

`WorkflowStatusInternal` 字段（`_sys_db.py:240`，即 run history 每行）：`workflow_uuid, status, name, class_name, queue_name, executor_id, app_version, recovery_attempts, workflow_timeout_ms, workflow_deadline_epoch_ms, deduplication_id, priority, inputs(序列化), queue_partition_key, forked_from, parent_workflow_id, started_at_epoch_ms, created_at/updated_at, delay_until_epoch_ms, attributes(自由 dict), schedule_name, application_name, ...`
状态机：`ENQUEUED → PENDING → SUCCESS/ERROR`，另有 `DELAYED, CANCELLED, MAX_RECOVERY_ATTEMPTS_EXCEEDED`。

### 1.3 Queue（并发/限流/分区/去重）

```python
q = DBOS.register_queue(Queue(              # _queue.py:78
    name, *,
    concurrency=None,                       # deprecated → global_concurrency
    global_concurrency=None,                # 全进程最大并行
    worker_concurrency=None,                # 本 executor 最大并行
    partition_concurrency=None,             # 按 queue_partition_key 分区串行/并行
    partition_worker_concurrency=None,
    limiter=None,                           # QueueRateLimit {"limit": int, "period": float}
    partition_limiter=None,
))
DBOS.retrieve_queue(name) / DBOS.delete_queue(name) / DBOS.list_queues(...)
```

出队由 launch 起的 `queue_thread` 完成：`ENQUEUED→PENDING` 原子认领，保证一个 run 只有一个 runner（重复 recovery 请求幂等，`_recovery.py:14-27` 注释明说）。

### 1.4 Durable sleep / event / 消息

```python
DBOS.sleep(seconds)            # durable sleep：完成的 sleep 恢复时直接跳过（记录为特殊 step）
DBOS.sleep_async(seconds)
DBOS.set_event(key, value)     # 只能在 workflow 内；可覆盖
DBOS.get_event(workflow_id, key, timeout_seconds=60)   # 任意处（含外部）等待事件出现
DBOS.send(workflow_id, message, topic=None)            # workflow 内/外均可（外部用 client）
DBOS.recv(topic=None, timeout_seconds=60)              # 只能 workflow 内，durable 等待
DBOS.send_bulk(...) / DBOS.asyncio_wait(...)
```

### 1.5 动态 cron 调度（重点；3.0 即有）

```python
DBOS.create_schedule(*, schedule_name, workflow_fn, schedule: str,   # cron 表达式，支持 6 字段(秒)
    context: Any = None, automatic_backfill: bool = False,
    cron_timezone: str|None = None, queue_name: str|None = None)     # None→内部队列
DBOS.list_schedules(*, status, workflow_name, schedule_name_prefix, application_name)
DBOS.get_schedule(name) -> WorkflowSchedule | None
DBOS.pause_schedule(name) / DBOS.resume_schedule(name) / DBOS.delete_schedule(name)
DBOS.trigger_schedule(name) -> workflow_id        # 立即触发一次（_scheduler.py:216）
DBOS.backfill_schedule(sys_db, name, start, end) -> list[workflow_id]  # 区间补跑
```

`WorkflowSchedule`（`_sys_db.py:339`）：`schedule_id, schedule_name, workflow_name, workflow_class_name, schedule, status("ACTIVE"/"PAUSED"), context(序列化), last_fired_at, automatic_backfill, cron_timezone, queue_name, application_name`。

语义（`_scheduler.py`）：
- 调度**存在 sys_db 表里**，`dynamic_scheduler_loop` 轮询发现新增/删除/修改（signature 变化即重启该 schedule 线程），多进程共享同一 DB 自动收敛（各自进程只跑本地 application 的 schedule，单机单进程无冲突）。
- 触发时 workflow_id = `sched-{schedule_name}-{计划时间 iso}`，先查 `get_workflow_status` 不存在才入队 → **no duplicate fire**（重启、多实例都幂等）。
- `automatic_backfill=True`：schedule 线程（重）启动时把 `last_fired_at→now` 之间错过的每次执行逐一补成独立 workflow（missed-run policy = 全部补跑，粒度为每个 cron 点）。
- 每次 run 也是一条 WorkflowStatus 记录（`schedule_name` 列归属），run history 免费。
- `context` 是持久化在 schedule 上的 JSON（版本化随 signature 热更新）。

### 1.6 恢复 / 取消 / 重跑

```python
# 启动时自动恢复：_launch → get_pending_workflows(executor_id, app_version) → 重新入队内部队列
DBOS.resume_workflow(workflow_id, *, queue_name=None) -> WorkflowHandle   # CANCELLED → 重新入队
DBOS.resume_workflows([...])
DBOS.cancel_workflow(workflow_id, *, cancel_children=False)
DBOS.cancel_workflows([...])
DBOS.fork_workflow(workflow_id, start_step, *, application_version=None, ...)  # 从第 N 步重放
DBOS.delete_workflow(s)(...); DBOS.update_workflow_attributes(workflow_id, attributes=...)
```

恢复语义 = **at-least-once、按 step 续跑**：已完成的 step 直接读缓存输出，未完成的从断点继续。`app_version` 匹配才恢复本地 pending（版本升级后旧 pending 留给旧版本/人工 recover）。

### 1.7 DBOSClient（进程外客户端，`_client.py:130`）

`DBOSClient(config)`：`enqueue(enqueue_options, *args)`、`retrieve_workflow`、`get_result`、`get_event`、`send`、`cancel/resume/delete_workflow`、`list_workflows`、`register_queue`、**`create_schedule / list / get / delete / pause / resume_schedule`**（`_client.py:1439+`）——UI 后端即使不在 workflow 进程里也能管理调度与 run。另有 `Debouncer(workflow_name, debounce_timeout_sec=..., queue=...)`：`debounce(debounce_key, debounce_period_sec, *args)`，基于 deduplication_id + DELAYED 弹跳实现防抖触发（对 event trigger 直接有用）。

### 1.8 版本

- 冻结源码：tag `3.2.0` + 4 commits（约 3.3.0a4 预览）；相对 3.0.0 多 18 commits，主要是 Conductor/客户端调度管理/防抖等增强，`create_schedule` 全套在 3.0.0 已存在。
- Atlas 依赖 pin：`core/pyproject.toml:34 → dbos==3.0.0`；可选依赖 `aiosqlite>=0.20.0`（:18）、`apscheduler>=4.0.0a5`（:19）。

## 2. 存储：后端与单机 Windows 适配

- 双后端实现：`_datasource_postgres.py` / `_sys_db_postgres.py`（psycopg3 + LISTEN/NOTIFY）与 `_datasource_sqlite.py` / `_sys_db_sqlite.py`（aiosqlite/sqlite3）。`_datasource_sqlite.py` 内置 pragma：`isolation_level=IMMEDIATE`、`busy_timeout=30000`、`foreign_keys=ON`，并有"database is locked"重试判定——**为单文件低并发场景专门调过**。
- `DBOS.migrate` 显式处理 `sqlite://` URL（`_dbos.py:577`）；`use_listen_notify` 在 SQLite 自动退化为轮询。PyPI 可选依赖组 `aiosqlite`。
- **结论：Atlas 单机 Windows 不需要 Postgres/嵌入式 PG；SQLite 完全够**（单 writer、单机进程）。Atlas 现行做法（`data/dbos.sqlite` + `connect_args={"timeout": 30}`）与库的推荐姿势一致。

## 3. Atlas 现有 DBOS 使用现状

| 文件 | 角色 |
|---|---|
| `D:\Atlas\core\atlas\capabilities\durable\dbos_backend.py` | DurableBackend：进程内唯一 DBOS 实例持有者 |
| `D:\Atlas\core\atlas\server.py` | :66-67 导入；:149 全局 `durable`；:309 `_durable_dispatcher`→`_run_scheduled_goal`；:317 `_scheduled_goal`（durable-first + 直跑 fallback + 通知）；:569-571 启动时 `DurableBackend(data/dbos.sqlite)` + `set_dispatcher` + `start()`；:660-695 能力注册 `durable.dbos.status`、`durable.agent_task.run`；:871 停机 `durable.stop()` |
| `D:\Atlas\core\atlas\runtime\hub.py` | :256-263 Hub 常驻进程同样起一份 DurableBackend，dispatcher 指向 hub 的 `agent_callback` |
| `D:\Atlas\core\tests\test_durable.py` | 含**真跨进程崩溃恢复测试**：子进程起 workflow 后 kill，父进程重启同 sys_db，验证 RUNNING workflow 被重新执行 |

DurableBackend 现有形态（`dbos_backend.py:79-131`）：
- `DBOS(config={"name": "atlas", "system_database_url": "sqlite:///.../dbos.sqlite", "db_engine_kwargs": {"connect_args": {"timeout": 30}}})` → 注册一个 `@dbos.step() async _agent_task_step(payload)`（`asyncio.run_coroutine_threadsafe` 桥回 server 事件循环）+ `@dbos.workflow() async _agent_task_workflow(payload)` → `DBOS.launch()`。失败 best-effort（`_start_error`，不阻塞启动）。
- `run_agent_task(payload)`：`DBOS.start_workflow_async(_agent_task_workflow, payload)` → `handle.get_result()`。
- **只用到了 workflow+step+start+自动恢复**；未用 queue、schedule、event、cancel、list——调度仍在 AtlasScheduler 手里。

## 4. AtlasScheduler 完整语义（`core/atlas/scheduler/__init__.py`，967 行）

- **持久化**：`schedules.toml`（与 sqlite 同目录，`_default_schedules_path()` = `cfg.db_path.parent / "schedules.toml"`），人可读可手编；每次变更全量重写 + mtime 热重载（`_reload_shared_tasks`）。
- **任务字段**（`ScheduledTask`，:58）：`id, name, description, trigger_type(cron|interval|date|event), trigger_args(dict→APScheduler trigger 参数), action("agent:<message>" | "goal" | "callback:<dotted.path>"), status(active|paused), tags, created_at/updated_at, last_run_at, next_run_at, run_count, runs(最近20条 {run_id, conversation_id, started_at, status}), legacy_goal*`（Hermes 迁移遗留）。
- **触发引擎**：APScheduler 4.x `AsyncScheduler`（cron/interval/date trigger）；**event 触发不走 APScheduler**——`file.changed` 用 watchdog 文件监听（:528-568），`dispatch_event`（:607）按 `trigger_args.filter`（root/glob/等值匹配）+ 2 秒防抖（进程内 `time.monotonic` dict）匹配后直接执行。
- **多进程单跑**：文件租约 `scheduler.lock`（PID 存活探测 + heartbeat 2s，:384-435）；`desktop` 与 `hub` 抢租约，hub 可抢占 desktop（:396）；非 owner 只读共享 TOML，丢失租约即停 APScheduler。
- **执行**：`_make_executor`（:673）生成闭包 → 记 run（TOML `runs`，截断 20 条）→ 按 action 调 `agent_callback(task_id, message)`。server 的 callback 是 `_scheduled_goal`（durable-first：已启动则 `durable.run_agent_task`，完成/失败发通知；durable 不可用直接 `_run_scheduled_goal`）。
- **missed-run 行为：无**。APScheduler 4 的 misfire 语义未配置（错过的触发丢弃）；进程关机期间的 cron/interval 触发直接丢失，重启后只算下次。`next_run_at/last_run_at/runs` 全是 TOML 展示态，崩溃时可能失真。
- **与 DBOS 交集**：仅在执行阶段（`_scheduled_goal`→`run_agent_task`）。触发时间点、pause 状态、run 历史均不 durable；"一个 run 只跑一次"的保证来自单进程租约，而非数据库原子性。
- 辅助：`run_now`（手动触发，`{id}__manual` job）、`observability_snapshot`（投影 Hermes goal 状态）、`_migrate_hub_tasks`（旧 hub-schedules.toml 一次性合并）。

## 5. Automation/Goals 前后端现状

- **前端** `frontend/src/renderer/pages/AutomationPage.tsx`：直接 REST 调 `/api/hub/status|start|stop`、`/api/schedules`（GET 列表，过滤掉 `action==='goal'` 的条目）、`POST /api/schedules`（`{id, name, action:"agent:<msg>", ...trigger}`）、`/api/schedules/{id}` DELETE、`/{id}/pause|resume|run`。GoalsPanel.tsx 调 `/api/goals`（POST `{id,name,goal,...trigger}`）、`/{id}/run|pause|resume|PUT`。
- **后端** `core/atlas/server.py`：`/api/schedules*`（:5499-5610，薄封装 AtlasScheduler CRUD）、`/api/goals*`（:5639-6010，`GoalCreateRequest{ id,name,goal,description,trigger_type,trigger_args,tags }` → 建 `action="goal"` 的 ScheduledTask + `set_goal(DATA_ROOT/"engine", "scheduled-goal-{id}", goal)` 写入 Hermes 目标状态）、`/api/hub/*`（:3712+，后台常驻进程控制，hub 进程内另有 `/tasks` REST）。goal 执行核心 `_run_scheduled_goal`（:415）：Hermes GoalManager 为唯一生命周期权威，`orchestrator.run()` 循环推进 + `evaluate_goal_after_turn` 判定 continue/blocked + goal 事件流（goal.triggered/evaluated/execution.error）。
- **`D:\Atlas\engine\cron`**：**空目录**，git 无任何历史（从未有文件入库，也不在 .gitignore），代码全库无引用（goal home 是 `DATA_ROOT/"engine"`）。判定：历史遗留/占位的运行时目录，与调度无关，可忽略或清理（非本 lane 决策）。

## 6. 差距分析：Automation → durable 需要什么

| 目标能力 | DBOS 原生 | Atlas 需包装 |
|---|---|---|
| crash/restart resume（执行中） | 有：启动自动恢复 + step 续跑（已在用） | dispatcher 桥接（已有）；恢复时通知/日志 |
| 触发本身 durable（进程死在两次触发之间） | 有：`create_schedule` 存 sys_db + `sched-{name}-{iso}` 幂等触发 | 把 TOML trigger_args 翻译成 cron 表达式；interval/date/event 需自行建模（见下） |
| no duplicate fire | 有：workflow_id 去重 + ENQUEUED→PENDING 原子出队 | 无 |
| missed-run policy | 有：`automatic_backfill`（全部补跑）| 若要"跳过/只补最近一次"策略，需在包装层选择 backfill 或 trigger_schedule |
| queue / 并发 / 限流 | 有：`register_queue`（global/worker/partition concurrency、rate limit、priority） | 建一个 `atlas-agent` 队列（global_concurrency=1 或按机器规格），agent 执行串行化 |
| per-agent owner | 部分：`application_name`（schedule owner）、`executor_id`、deduplication_id 可做 owner 锁 | 单机单 agent 用 `DBOS(config name="atlas")` + deduplication_id=`owner:{agent_id}` 即"同一 agent 同时只一个 active run" |
| delivery outcome（完成/失败通知） | 有：workflow 返回值/ERROR 状态 + `attributes` | workflow 末步调 notifications；失败用 `DBOS.list_workflows(status=ERROR)` 汇总 |
| run history | 有：WorkflowStatus 全量（含 inputs/输出/schedule_name/queue_name/时间戳/recovery_attempts） | `GET /api/automations/{id}/runs` → `list_workflows` 过滤 `attributes["automation_id"]` |
| cancel active run | 有：`cancel_workflow(id, cancel_children=True)` | 包装：由 attributes 或 dedup id 反查 active workflow_id |
| event/condition watcher | 部分：`send/recv`（durable 等待）、`set_event/get_event`（外部注入）、`Debouncer`（防抖） | file.changed 等**外部事件触发**需自建 watcher→`start_workflow`/`enqueue`（DBOS 无文件/通用事件订阅）；condition = 一个常驻 watcher workflow 用 `recv`/`get_event` 循环等待 |
| webhook trigger | 无（无 HTTP 入口概念） | Atlas 已有 server；新增路由 → `enqueue_workflow_with_options(deduplication_id=...)` |
| 定时一次性（date trigger） | 有：`EnqueueOptions.delay_seconds`/`delay_until`（DELAYED 状态），或 cron 一次性表达式 | 包装：`run_time - now` → `delay_seconds` |
| interval（每 N 分钟） | 需翻译：cron 不表达任意 interval；方案 a) 每次运行末尾 `DBOS.sleep`+自续（workflow 自循环）；方案 b) `Debouncer`；方案 c) 保跳 crontab `*/N * * * *`（仅对整除场景成立） | **interval 是包装层最大的语义缺口**，建议方案 a（自续 workflow + durable sleep）或评估 DBOS 后续版本 |

### 字段级映射：Atlas Automation job → DBOS

| Atlas `ScheduledTask` 字段 | DBOS 落点 |
|---|---|
| `id` | `schedule_name`（cron 类）/ `deduplication_id = f"automation-{id}"` / workflow `attributes["automation_id"]` |
| `name/description/tags` | Atlas 产品状态（继续存 TOML 或迁入 automation 表）；不进 DBOS |
| `trigger_type=cron` + `trigger_args`（APScheduler 字段 month/day/hour/minute/...） | `DBOS.create_schedule(schedule=cron 表达式, cron_timezone=cfg.scheduler_timezone, workflow_fn=automation_workflow, context={"automation_id": id, "message": ...}, automatic_backfill=按策略, queue_name="atlas-agent")` |
| `trigger_type=interval` | 自续 workflow（run→`DBOS.sleep(interval)`→re-enqueue 自己，workflow_id 复用策略固定）或 crontab 近似；包装层提供 |
| `trigger_type=date` | `enqueue_workflow_with_options({queue, delay_seconds}, ...)` |
| `trigger_type=event`(file.changed 等) | Atlas watcher（现有 watchdog）→ `DBOS.start_workflow/enqueue` + `Debouncer`（替代现在进程内 2s 防抖，防抖跨重启持久） |
| `action="agent:<msg>"` / `"goal"` | `context`/`attributes` 携带 message/goal；workflow 体内桥接 `_run_scheduled_goal`/agent orchestrator（沿用 `_agent_task_step` 模式） |
| `status=active/paused` | `DBOS.pause_schedule/resume_schedule`（schedule）；date/event 类用 Atlas 产品状态门控 |
| `last_run_at/next_run_at` | `WorkflowSchedule.last_fired_at`（DBOS 持有）；next_run_at 由包装层用 croniter 算展示值 |
| `run_count/runs[]` | `DBOS.list_workflows(attributes 过滤/schedule_name)`（每 run 一行：status/created_at/started_at/recovery_attempts/inputs/output/error） |
| （新增）owner | `attributes["owner"]` + `deduplication_id=f"owner:{id}"` → 每 agent 单 active run；超发即 `DBOSQueueDeduplicatedError` |
| （新增）delivery outcome | workflow 最后一步 step 写通知 + `attributes["delivery"]`；run 记录即审计 |
| （新增）cancel active | `DBOS.cancel_workflow(active_run_id, cancel_children=True)` |

## 7. 落点建议

**唯一 owner 结论：调度与执行的 durable owner = DBOS；AtlasScheduler 不与之并存**（保留只读迁移期，最终删除 APScheduler 依赖与文件租约逻辑；`schedules.toml` 降级为一次性导入源，同 `_migrate_hub_tasks` 先例）。

建议新模块 `D:\Atlas\core\atlas\automation\`：

```
core/atlas/automation/
├── __init__.py            # AutomationService（门面）：CRUD、pause/resume、run_now、runs 查询
├── model.py               # Automation 数据类（现有 ScheduledTask 字段 + owner/missed_policy/delivery）
├── store.py               # 产品状态存储：初版沿用 schedules.toml（只存 DBOS 表达不了的字段），后续迁 sqlite
├── triggers.py            # trigger_args → DBOS 落点翻译：cron 表达式合成、interval 自续、date→delay_seconds、event→watcher+Debouncer
├── workflows.py           # @DBOS.workflow 注册：automation_workflow（桥接 _run_scheduled_goal / orchestrator）、
│                          #   interval_loop_workflow（sleep 自续）、watcher_workflow（recv/get_event 条件等待）
├── queues.py              # register_queue("atlas-agent", global_concurrency, limiter, partition=owner)
└── reconcile.py           # 启动对账：TOML ↔ DBOS schedules diff（create/pause/delete 同步）+ 存量 run 清点
```

与现有代码的接线：
- `dbos_backend.py` 扩展为 AutomationService 的运行时底座（保留 dispatcher 桥 + SQLite config；新增 register_queue/create_schedule 调用点）；
- `server.py` 的 `/api/schedules/*`、`/api/goals/*` 路由改指向 AutomationService（路径可保留以兼容前端），`_scheduled_goal` 的"durable-first + fallback"简化为"durable only + 失败通知"；
- `hub.py` 与 server 共用同一 `dbos.sqlite` + 同一 app name，DBOS 调度线程天然单点（schedule 线程只在持有启动权的进程跑或两边幂等触发，靠 `sched-{name}-{iso}` 去重），**替代** scheduler.lock 文件租约；
- 迁移器：`store.py` 读旧 `schedules.toml` → 为每个任务调 `create_schedule`/入队 date → 标记 `migrated`（对应 `_ensure_goal_migrated` 模式）；
- 明确不做：DBOS 换 Postgres、多机分布式、webhook 网关（Atlas server 已有 HTTP 面）。

风险与注意：
1. **DBOS 单例与热重载**：`destroy(destroy_registry=True)` 后重新注册 workflow 是现行测试过的路径（`stop()` 已处理 default executor 恢复）；新增 schedule 注册须在 `DBOS.launch()` 之后（`create_schedule` 内部已校验 workflow/queue 已注册）。
2. **interval 自续 workflow** 需设 `SetWorkflowID` 固定 id + `WorkflowIDReusePolicy`，防止重启后重复自续链。
3. DBOS 3.0 pin 已够用（create_schedule 全套、queue、client 管理、debouncer 需确认 3.0 是否含 `_debouncer` —— HEAD 有，升级到 3.2.x 前不要依赖 Debouncer，或顺手 bump pin）。
4. SQLite busy_timeout 已由 Atlas config（30s）+ 库内 pragma（30s）双重兜底；automation queue 并发保持 1-2 即可避免写竞争。
