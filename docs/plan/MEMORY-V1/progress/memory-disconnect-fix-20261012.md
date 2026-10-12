# Atlas 统一记忆断链修复报告

**日期**：2026-10-12
**执行**：AI计划（本会话，自主施工）
**起因**：主人「去干，都是你自己干」
**范围**：Atlas 记忆断链（LEDGER 44 卡之外、但阻塞全部记忆相关卡的前置故障）

---

## 一、症状

`D:\MemoryOSData\db\memoryos.sqlite3` 最后写入停在 **2026-10-10 17:09 UTC**（北京 10-11 01:09），
此后 30 小时主人在 Atlas 里聊的全部内容**没有一条进记忆**。
`data/memos-home/bridge-status.json` 报 `disconnected / Hermes chat disconnected`。

---

## 二、根因：五层独立缺陷叠加

**关键教训**：这条链要**五层全通**才写记忆，每层都会单独失败且症状都是「没记忆」。
停在第一层就下结论会漏掉后面四层。

| # | 层 | 根因 | 判据 | 修法 |
|---|---|---|---|---|
| 1 | 配置 | `config/atlas.toml` 缺 `[memory.unified]` 整段 | `/api/unified-memory/*` 全 404；`get_config().get("memory.unified.enabled")` 为 None | 补 `[memory.unified]`：enabled/service_url/service_dir/data_root/subject_binding/internal_token |
| 2 | 子进程环境 | `_start()` 不注入 `MEMORYOS_INTERNAL_TOKEN`；且沿用 `os.environ` 的外来 `PYTHONPATH` | 服务端恒 **503 INTERNAL_AUTH_NOT_CONFIGURED**；子进程 `ModuleNotFoundError: pydantic_core._pydantic_core` | 抽出 `_child_env()`：剥离 PYTHONPATH + 注入 token/data_root |
| 3 | 启动超时 | `STARTUP_TIMEOUT_SECONDS=12`，真实库冷启 **11.1s**（语义模型 warmup 8.5s） | 只剩 0.87s 余量，真机必 flaky | 45s（可配 `memory.unified.startup_timeout_seconds`） |
| 4 | **探测超时（真凶）** | `HEALTH_TIMEOUT_SECONDS=0.5`，而 `GET /v1/health` 实测 **P50 1384ms**（freshness 水印校验） | 探测**在数学上不可能通过** | 10s（可配 `memory.unified.health_timeout_seconds`） |
| 5 | 远端性能 bug | MemoryOS `repository.py::observation_watermarks` 全局分支对 **episodes 每一行**重算 `_formed_source_event_ids`，而 distinct subject 只有 1 个 | `/v1/unified/status` 带 token 耗时 **12.4s**（`_load_json` 调 **528 万次**）> Atlas 代理 5s 超时 → **503 timeout** | `SELECT DISTINCT memory_subject_id` → **0.01s（1239×）**，语义等价 |
| 6 | 反射器上下文 | `reflector.py:957` fallback context 只给 2 字段，契约要 6 个必填 | `POST /v1/unified/consolidation:apply` 恒 **422「MemoryContext 字段不完整」**，反射器每轮空转（`idle_cycle_error`） | 新增 `_default_context()`：优先借 facade 的 `default_context()`（造全 9 字段），退化时本地补齐 6 必填 |

### 附带 bug（第 3 层邻居）
启动失败路径**不回收自己拉起的子进程** → 逃逸进程占住 `service_url` 端口 →
后续每次启动都 `child exited during startup (3)`（bind 10048），且外部看不出谁占的。
修法：`except` 里加 `await self._reap_failed_child()`。

---

## 三、改动清单

**Atlas 侧**（`D:\Atlas`，未提交，工作区改动）
| 文件 | 改动 |
|---|---|
| `config/atlas.toml` | 新增 `[memory.unified]` 段（本地实配，gitignored） |
| `core/atlas/memory/service_lifecycle.py` | +94/-7：`_child_env()`、`internal_token`/`data_root`/`health_timeout_seconds`/`startup_timeout_seconds` 属性、`_reap_failed_child()`、常量 45s/10s |
| `core/atlas/memory/reflector.py` | 新增 `_default_context()`；`apply_operations` 不再用 2 字段 fallback |

**MemoryOS 侧**（`D:\MemoryOS`，未提交）
| 文件 | 改动 |
|---|---|
| `service/unified/repository.py` | `SELECT DISTINCT memory_subject_id`（+6/-1） |

> ⚠️ 提交纪律：AGENTS.md 规定「不要新建 git commit / push，除非用户明确要求」。
> 本次一度建了 commit 后**已 `git reset --soft` 撤回**，改动保留在工作区。

---

## 四、验证证据

### 4.1 隔离 E2E（8766 端口，同一份配置）
```
 t      | 8099/health | 8099/unified/status | Atlas proxy
 4.1s   |         200 |                 401 |         200   ← 贯通
>>> Atlas 统一记忆就绪 ✅
```

### 4.2 写路径（生产代码路径，非手拼 payload）
`CaptureService.capture_user_message()` → outbox → `capture_flush_loop()` → MemoryOS

| 指标 | 前 | 后 | 增量 |
|---|---|---|---|
| evidence_events | 32936 | 32938 | **+2** |
| episodes | 2299 | 2301 | **+2** |
| memories | 67 | 69 | **+2** |

### 4.3 性能（第五层修复）
| | 修复前 | 修复后 |
|---|---|---|
| `repository.status()` | 12.39s | **0.01s** |
| 函数调用数 | 58,150,991 | **25,379** |

### 4.4 零回归（受控对比）
`tests/unified_memory`（同命令、同 ignore 集）：

| 运行 | 结果 | 失败项 |
|---|---|---|
| 基线（改动 stash） | 7 failed / 358 passed | bootstrap、capture_lifecycle×2、intent_bridge、restart_continuation、windows_activity×2 |
| 我的改动 | **7 failed / 358 passed** | **逐字相同** |

> 注：中途一次 41 failed 是**我自己的测量错误**——把 `tests/test_memoryos_service_lifecycle.py`
> 与 harness 测试混在同一次运行，它按字典序先跑并占用真实 8099 后不释放，污染后续健康等待。
> 分开跑即恢复。

### 4.5 主实例（重启后，主人界面）
```
/api/unified-memory/status = HTTP 200 ✅
unified 路由数 = 34（修复前 0）
counts: events 32939, memories 72
wired.observe/recall = True/True
contract = UM-WIN-1.0
health.components.memoryos = "ready"   ← 修复前从未出现
component_errors = {}
8099 由 Atlas 托管
```

### 4.6 反射器（第六刀）
```
重启前: idle_cycle_error 17 条（每轮必错，MemoryContext 字段不完整）
重启后: 20:13:03  memory_reflector.receipt
       20:13:03  memory_reflector.idle_cycle_completed   ← 首次成功完成反射周期
       错误总数停在 17，不再增长
```

### 4.7 终极验收（真实 observe 契约，字段齐全）
```
POST /v1/unified/observe -> HTTP 201
{"accepted":1,"created":1,"duplicates":0,
 "receipts":[{"result":"CREATED","event_id":"ev-c24fac24549844c6"}]}

增量: evidence_events +1, episodes +1, memories +1   ✅
```

---

## 五、未做 / 待办

1. **改动未提交**——AGENTS.md 规定无明确授权不建 commit，当前保留在工作区。
   修复已通过后端重启生效（lifespan 启动时读配置）。一度误建 commit，已 reset --soft 撤回。
2. **★ 启动 Atlas 必须用干净环境**：从 Hermes 的 bash 会话里 `wscript Atlas.vbs`
   会继承 `PYTHONPATH`（指向 Hermes 的 site-packages），污染后端的 `agent` 包解析，
   导致 `engine_warmup_failed`（`ModuleNotFoundError: agent.agent_hooks`）。
   **正确姿势**：先 `Remove-Item Env:PYTHONPATH`，或让主人双击桌面快捷方式。
3. **Atlas 重启姿势**：electron 的 `before-quit` 会 `taskkill /T /F` 收后端；
   **不要用 `Stop-Process -Force` 硬杀 electron**（会跳过后端清理，留下占端口的孤儿）。
4. **capture state = STOPPED**：这是 T05.3 设计（被动采集需 `POST /api/unified-memory/capture/start`
   显式选观察源）；**对话/工具的主动 capture 不受此影响**（走 outbox 常驻 flush）。
5. **LEDGER 剩余 22 张卡未启动**、**工作台 v2 未动**（本次只修了阻塞性故障）。
6. **`test_memoryos_service_lifecycle.py` 不能与 harness 测试同批跑**：它按路径字典序
   先跑，占用真实 8099 后不释放，导致 harness 的健康等待集体失败（本次踩过，41 failed 假象）。
