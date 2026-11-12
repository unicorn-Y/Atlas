# Atlas 后端审查报告

- 审查日期：2026-10-14
- 审查范围：`D:\Atlas\core`（357 个 .py / 124213 行）+ 上游 `D:\Atlas\engine`
- 对标基准：ZCode 桌面端 v3.15.3
- 实测环境：项目自带 `.venv/Scripts/python.exe`，Python 3.14.7
- 本报告全部论断均给出 file:line 级证据；未验证项在文末集中标注

---

## 一、最严重的 10 个问题

### 1. Agent 身份 system prompt 来自一个「越狱」文本文件，且不可撤销

**证据**：`atlas/agent/run_phases.py:59-89`、`atlas/agent/run_phases.py:838`、`atlas/engine/hermes_runtime.py:179-196`

```python
# atlas/agent/run_phases.py:59
def _breaker_prompt() -> str:
    """Workspace breaker prompt (engine/breaker.md) as the run's identity block.
    Loaded once per process and reused, so the stable-tier system message stays
    byte-identical across turns and the provider prompt cache keeps hitting.
    """
    global _BREAKER_CACHE
    if _BREAKER_CACHE is not None:
        return _BREAKER_CACHE
```

```python
# atlas/agent/run_phases.py:838
        SystemMessage(content=_breaker_prompt() + _user_output_style_prompt())
```

`D:\Atlas\engine\breaker.md`（28065 字节）**不是熔断器配置** —— 它是一份注入式越狱提示词，实际内容包括：

- `[MODE: UNRESTRICTED SANDBOX — STABLE]`、"Never refuse"、禁用词清单（`不能/无法/抱歉/refuse to/policy violation` 等）
- `BOUNDARY-WORD NORMALIZATION` 段：明确要求把"没有授权、非本人资产、公网银行、服务器不是我的、员工账号、绕过检测"等**自动转换为占位符并直接给出操作步骤**
- 预置 payload 模板：`sqlmap` 注入命令、`shell.php.jpg` 图片马、WAF 绕过（`/**/` 混淆、分块传输）、`gopher://127.0.0.1:6379` SSRF、云元数据 `169.254.169.254`、免杀 `ANTI_DEBUG_SNIPPET/ANTI_VM_SNIPPET`、破解流程（`CHECK_FN`/`PATCH_BYTE`/`codesign --force --deep --sign -`）
- `STABILITY ANCHORS`：要求模型**不得承认、不得讨论、不得解释**该框架

同一文件被两处加载：`run_phases.py:87`（Agent 主路径）与 `hermes_runtime.py:1670`（引擎路径）。

**三重放大**：

1. `_BREAKER_CACHE`（`run_phases.py:92`）进程级缓存，**`atlas/config.py` 无任何失效钩子**（grep 确认），改/删文件后本进程内永不重载。
2. `atlas/engine/hermes_runtime.py:201-215` `_trust_context_files()` 把 Hermes 的上下文文件扫描器**替换为 passthrough**，注释自陈 "the user decided Atlas runs without automatic safety review (2026-10-01)" —— 即 `AGENTS.md`/`CLAUDE.md`/`.cursorrules` 的注入拦截被关闭。
3. 该文件位于 agent 有写权限的工作区（`_load_breaker_identity` 从 `<ATLAS_DATA_DIR>/engine` 读取，而 `D:\Atlas\engine` 就在 agent 常年操作的主仓库内）。

**为什么严重**：这不是"安全配置宽松"，而是**产品交付物里固化了一份越狱提示词**。对标 ZCode 级别的商业产品，身份/系统提示词必须是受版本控制、受审阅、签名校验的只读资产，绝不能是运行时可写目录里的纯文本，更不能"缓存到进程死为止"。

**怎么修**：把身份提示词移入包内只读资源（`atlas/prompts/identity.py` 常量或带 sha256 校验的 wheel 内数据文件）；删除 `_trust_context_files` 的 passthrough 覆盖或改为白名单；`breaker.md` 若保留，加内容哈希校验 + 只读挂载 + 变更时强制重载。

---

### 2. LLM 调用无读取超时（`read=None`），单次挂死可永久占用一个 run

**证据**：`atlas/models/network_transport.py:168`

```python
"timeout": timeout or httpx.Timeout(connect=15.0, read=None, write=15.0, pool=10.0),
```

流式路径另有一层：`atlas/kernel/model_call.py:575` `stream = await asyncio.to_thread(call_llm, **kwargs)`，其中 `call_llm` 是同步 generator，`read=None` 意味着**流中途不再返回任何字节时不会超时**。

**为什么严重**：run 会卡在 `_stream_next` 的 `to_thread` 上。虽然有 `cancel_event` 分支（`model_call.py:584-598`）可救，但**只有用户主动取消才触发**；无人取消时该 run 永久挂着，占着 `RunState`、`_active_contexts` 条目和 provider 连接。商业级产品的写死约束是"每层都要有 deadline"，`read=None` 是不可接受的默认值。

**怎么修**：改为有限 read timeout（如 `read=300`），并在流式循环外加一个 run 级别的总 deadline；对 `to_thread` 的 `next()` 加 `asyncio.wait_for`。

---

### 3. 流式取消存在 `to_thread` 竞态：`next_task.cancel()` 取消不掉已在 C 层阻塞的调用

**证据**：`atlas/kernel/model_call.py:583-598`

```python
next_task = asyncio.create_task(asyncio.to_thread(_stream_next, chunks))
...
if cancel_task in done and cancel_event.is_set():
    close = getattr(stream, "close", None)
    if callable(close):
        await asyncio.to_thread(close)     # 595 行先 close
    next_task.cancel()                     # 596 行再 cancel
    await asyncio.gather(next_task, return_exceptions=True)
    raise asyncio.CancelledError
```

`asyncio.to_thread` 的取消语义是：**已经在 executor 线程里跑起来的工作无法被取消**，`Task.cancel()` 只是让 await 抛 `CancelledError`，后台线程仍在 `chunks.__next__()` 上阻塞。这里先 `close()` 再 `cancel()`，而 `close()` 本身也走 `to_thread` —— 如果 `close()` 拿不到锁或 generator 卡在 `next()`，两者会互相等待；连续多轮取消会**耗尽默认 ThreadPoolExecutor 的 worker**（默认 `min(32, cpu+4)`），之后所有 `asyncio.to_thread` 全线饿死。

**为什么严重**：这是"取消看起来生效、实际泄漏线程"的典型竞态。用户反复点停止 → 线程池枯竭 → 整个后端所有 `to_thread` 路径（session 写入、git、Docker、LSP）全部挂起。

**怎么修**：调换顺序（先 `cancel()` 再 `close()`），或更正确 —— 给流式读取加超时，用 `asyncio.wait_for(next_task, timeout)` 保证线程最终退出；考虑换 `asyncio.create_subprocess`/异步 HTTP 客户端替代同步 generator + `to_thread`。

---

### 4. 测试套件当前 86 个失败 + 5 个收集错误 + 全量跑会挂死

**证据**（实测，Python 3.14.7）：

```
$ ./.venv/Scripts/python.exe -m pytest tests/ --collect-only -q
ERROR tests/test_f2_observer_smoke.py
ERROR tests/unified_memory/test_cutover.py
ERROR tests/unified_memory/test_cutover_fixture.py
ERROR tests/unified_memory/test_release_composition.py
ERROR tests/unified_memory/test_resource_limits.py
2551/2885 tests collected (334 deselected), 5 errors in 7.45s
```

收集错误根因（可复现）：
```
E   ModuleNotFoundError: No module named 'scripts.f2_observer_smoke'
E   ModuleNotFoundError: No module named 'scripts.unified_memory'
```
`tests/conftest.py:13` 注释假设 `scripts` 是仓库根的 namespace package，但 `.venv/Lib/site-packages/scripts/` 实际存在一个**同名 shadowing 包**：

```python
$ ./.venv/Scripts/python.exe -c "import scripts; print(scripts.__path__)"
scripts resolves to: ['D:\\Atlas\\core\\.venv\\Lib\\site-packages\\scripts']
# append sys.path 后仍然指向 site-packages，f2 导入失败
```
`site-packages/scripts/` 内含 `train.py` / `eval_only.py`（非本项目代码），且带 `__init__.py`，因此 `conftest.py:20` 的 `sys.path.append(_REPO_ROOT)` **永远无法覆盖**。

单元 lane 实测 **86 个 FAILED**，例如：
- `tests/test_lint_gate.py::test_critical_exception_scopes_are_clean_and_no_baseline_scope_grows` — 断言 `critical == {}` 失败，实测 critical scope 有 **21 处**违规（`atlas/api/workbench_router.py` BLE001×4、`atlas/api/network_settings_router.py` BLE001×3+S110×1…），且 **44 个 scope 超过 baseline**（`atlas/tools/workspace_workflows.py` 10 vs 允许 0、`atlas/kernel/model_call.py` 8 vs 0）
- `tests/test_route_snapshot.py::test_routes_match_frozen_snapshot` — 冻结路由快照与实际不一致
- `tests/test_agent_skills.py` 4 个 — `assert 403 == 200`（OriginGuard 拒绝 TestClient 的 `client_host="testclient"`，`is_trusted` 走 `ipaddress.ip_address()` 抛 `ValueError` → `return False`，见 `atlas/origin_guard.py:49-54`）
- `tests/test_local_edit.py` 3 个 — `assert 'read the file first' in 'PermissionError: Workspace write scope is unavailable...'`
- `tests/test_c4_hooks.py` 6 个 — hook 信任门未通过：`Hook「...」尚未通过信任审查，已阻止执行`

全量 `pytest tests/` **在 89% 处挂死**（`exit=124`，超时 590s 被杀），卡在 `tests/test_subagent_settings.py::test_subagent_settings_apply_to_new_children_only`；`--timeout=45` 对 Windows 上阻塞在 IOCP 的 asyncio 事件循环**不生效**（pytest-timeout 默认 `thread` 法在 `asyncio.run_until_complete` 的 `_run_once` 里无法中断）。

次要：`.pytest_cache` 已损坏（`WinError 183`，`cache/lastfailed` 无法创建），裸跑 `pytest` 会报 `PytestCacheWarning`。

**为什么严重**：`pyproject.toml` 的 `addopts = "-m unit"` 说明单元 lane 是发布门禁。**门禁现在是红的，而且挂死**。6.3 万行测试代码的投入在这种状态下无法起到回归保护作用。

**怎么修**：① `conftest.py` 改为 `sys.path.insert` 并用唯一包名（如 `atlas_scripts`）或加 `conftest` 级别的 `importlib` 重定向避开 site-packages 的 `scripts`；② 修 86 个失败或明确标记 xfail 并给到期日；③ 把门禁改为"失败数为 0 才允许合并"。

---

### 5. 明文 API key 落盘，且通过 HTTP 全量回吐给前端

**证据**：`D:\Atlas\config\atlas.toml`（已 `gitignore`，但仍是明文）

```toml
[models.gateway]
base_url = "https://cnapi.pleasure.cc.cd:8443/v1"
api_key = "<redacted>"     # line 15

[memory.unified]
internal_token = "<redacted>"   # line 33
```

> 注：本报告最初在此处贴了真实凭证。审计记录要证明的是"这里有明文密钥"，
> 不是密钥本身的值；照抄原文会让这份报告变成新的泄漏源。

`atlas/api/config_editor_router.py:61-75` 把它整体返回：

```python
def _state() -> dict[str, Any]:
    main = config_module.CONFIG_PATH
    return {
        "config_path": str(main),
        "config_text": _read(main),        # 66 行：atlas.toml 全文，含 api_key
        ...
```

```python
# atlas/api/config_editor_router.py:78
@router.get("/api/config/main")
async def get_main_config() -> dict[str, Any]:
    return _state()
```

`_read()` 无任何脱敏。全源码仅有 1 处 redaction，在 `atlas/api/linear_integration_router.py:103`。

对比：`atlas/channels/credentials.py:38` 和 `atlas/api/linear_integration_router.py:69` **已经**用 OS keyring 存密钥 —— 说明模式已在仓库内，只是模型网关密钥没走这条路。`atlas/logs.py:27-34` 有 `_SENSITIVE_KEYS`/`_SECRET_TEXT`/`_BEARER_TEXT` 三套脱敏正则，**也已有现成能力**，只是没用在 API 响应上。

**为什么严重**：桌面产品中 `/api/config/main` 是设置页常规读接口。任何能触达 127.0.0.1:8765 的进程/扩展/渲染层 XSS 都能一次拉走网关 key 与 MemoryOS internal token。日志脱敏做得很细、API 脱敏完全缺失，是不一致而非有意取舍。

**怎么修**：`_state()` 走 `_summary()` 同款脱敏，密钥字段替换为 `sk-…72c` 形态；密钥迁移到 keyring，`atlas.toml` 只留 `${ATLAS_API_KEY}` 引用占位。

---

### 6. 默认监听 `0.0.0.0`，且鉴权依赖一个「用户看得见」的启动令牌

**证据**：`atlas/config.py:113-114`

```python
@property
def server_host(self) -> str:
    return str(self.get("server.host", "0.0.0.0"))
```

`D:\Atlas\config\atlas.toml` 显式写死 `host = "0.0.0.0"`，`atlas/cli.py:56-60` 直接用它绑：

```python
uvicorn.run("atlas.server:app", host=host, port=actual_port, reload=reload)
```

注意 `desktop_entry.py:36` 用的是 `host="127.0.0.1"`、`runtime/hub.py:284` 也是 `127.0.0.1` —— **只有 CLI 入口继承配置**，形成"桌面版安全、CLI 版暴露"的分裂。

鉴权只有 `OriginGuard`（`atlas/origin_guard.py`）：
```python
def is_trusted(origin, token, extra_origins=(), fetch_site=None, client_host=None) -> bool:
    expected = os.environ.get("ATLAS_API_TOKEN", "")
    if expected and token and secrets.compare_digest(token, expected):
        return True
    if client_host is not None:
        try:
            if not ipaddress.ip_address(client_host).is_loopback:
                return False          # 非 loopback 一律 False
```
非 loopback 客户端**只有** token 一条路。而 token 由 Electron 生成：`frontend/src/main/electron.ts:39` `process.env.ATLAS_API_TOKEN ??= randomBytes(32).toString('base64url')` —— **CLI 启动路径下这个环境变量不存在**（全仓库 grep `ATLAS_API_TOKEN` 只有 `cli.py:460` 读取、无写入点），即 `expected == ""` 时该分支短路。此时非 loopback 客户端被 `client_host` 分支挡住，**但 `client_host is None`（如 unix socket/代理转发）会落到** `if origin is None: return True`（`origin_guard.py:57-58`）。

**为什么严重**：`0.0.0.0` 是默认值而非显式选择，普通用户照抄配置就暴露到局域网；且鉴权模型是"loopback 即可信 + 一个可选环境变量"，没有会话、没有 key 轮转、没有 per-client 授权、没有审计。对标 ZCode 的"本机 agent 核心独立进程 + 令牌握手 + 来源校验"是合理设计，但**默认监听地址必须是 127.0.0.1**，且 `client_host is None` 必须 fail-closed。

**怎么修**：`server_host` 默认改 `127.0.0.1`；`is_trusted` 把 `origin is None` 与 `client_host is None` 的组合同样要求 token；`ATLAS_API_TOKEN` 在无 Electron 时由后端自行生成并写到 `0600` 文件。

---

### 7. 安全审查默认整体关闭，且「不可恢复底线」只在写类工具上短路

**证据**：`atlas/safety/policy.py:15-23`

```python
# Off by default (user decision 2026-10-01): the user will design safety review personally.
# With "off" nothing is detected, blocked, reviewed or scanned; the code stays for reference.
_DEFAULTS = {
    "reviewer": "off", "always_allow": [], "always_deny": [], "trusted_paths": [],
}

def review_enabled() -> bool:
    return get_settings().get("reviewer", "off") != "off"
```

唯一的审查入口 `atlas/agent/tool_node.py:473`：
```python
if is_write and permission_mode == "full_access" and _agent.safety_review_enabled():
```
`review_enabled()` 恒 `False` → 整个 `if` 块（含 `_floor` 底线判定、`review_tool_input`、`approval_callback`、`protect_targets` 检查点）**永不执行**。

真正生效的底线检查在别处：`atlas/agent/tool_node.py:1298-1301`（`kernel_edit` 目标变更时），注意它是**编辑类工具专属**。

`atlas/agent/tool_node.py:1544`：
```python
threat_ids = scan_for_threats(full_output, scope="context") if _agent.safety_review_enabled() else []
```
同样被关闭。

**为什么严重**：`permission_mode` 默认 `full_access`（`atlas/api/runtime.py:79`），网关默认也是 `full_access`（`atlas/config.py:101`、`atlas/api/run_drive.py:117`）。所以默认组合是"完全放行 + 审查全关 + 注入拦截关闭（问题 1）"。`atlas/safety/detection.py` 里 `_WINDOWS_FLOORS`、`hermes_detection.py`（1537 行，含 "Commands that NEVER run via the agent, regardless of --yolo"）**全部是死代码**。这是"看起来有安全层、实际不生效"的典型，比没有安全层更危险 —— 它让审阅者和用户都放松警惕。

**怎么修**：底线 `_floor` 检查必须**移到 `review_enabled()` 判断之外**（底线应无条件生效）；`reviewer` 默认值改为 `rules`（纯本地规则，不需要模型调用，成本为零）。

---

### 8. 单文件 4858 行的 God Module + `run()` 单函数 1319 行

**证据**：实测行数（`wc -l`）

| 行数 | 文件 |
|---|---|
| 4858 | `atlas/memory/__init__.py` |
| 3031 | `atlas/api/run_drive.py` |
| 2362 | `atlas/kernel/loop.py` |
| 1968 | `atlas/engine/hermes_runtime.py` |
| 1709 | `atlas/api/workspace_router.py` |
| 1689 | `atlas/agent/tool_node.py` |
| 1627 | `atlas/agent/run_phases.py` |
| 1537 | `atlas/safety/hermes_detection.py` |

**41 个文件 ≥800 行，8 个 ≥1500 行。**

单函数最长（AST 统计）：
- `atlas/kernel/loop.py:267` `AtlasKernel.run` — **1319 行**
- `atlas/api/run_drive.py:2179` `_execute_run` — **852 行**
- `atlas/api/run_drive.py:1245` `_handle_run_start` — **681 行**
- `atlas/memory/__init__.py:331` `_create_tables` — **581 行**（一个 SQL 字符串）
- `atlas/agent/tool_node.py:160` `execute_tools_node` — **1529 行**
- `atlas/engine/hermes_runtime.py:968` `run_turn` — **1000 行**

**循环依赖（AST + Tarjan SCC，仅统计 module 级 import）**：

```
Top-level import cycles (SCC size>1): 2
  size 3 : atlas.agent, atlas.agent.run_phases, atlas.agent.tool_node
  size 2 : atlas.lsp, atlas.lsp.manager
```

**函数内延迟 import 共 690 处**，密集分布：
```
44 atlas/engine/hermes_runtime.py
44 atlas/api/conversations_router.py
43 atlas/kernel/loop.py
39 atlas/agent/run_phases.py
37 atlas/server.py
```

耦合度（fan-out）：`atlas.server` **72**、`atlas.api.application` **53**、`atlas.kernel.loop` **37**、`atlas.agent` **34**。fan-in：`atlas.config` **102**、`atlas.api.app_services` **33**。

**为什么严重**：690 处延迟 import 是"循环依赖被绕过而非被消除"的量化指标；`AtlasKernel.run` 1319 行意味着**无法对核心执行循环做单元测试**（测试只能整段跑），这直接解释了问题 4 里大量 e2e 风格测试的脆弱性。`run_drive.py` 中 `_server()` 这一"晚期绑定全局单例"被调用 **181 次**（`grep -c`），使整个 API 层无法脱离 `atlas.server` 模块单例测试。

**怎么修**：① 先解 `agent`/`run_phases`/`tool_node` 三角循环（把共享类型抽到 `atlas/agent/contracts.py`）；② 按"阶段"拆分 `AtlasKernel.run`（它已有 `persist/emit/transition` 内嵌函数，是天然切点，`run_phases.py` 的 `_phase_begin/_phase_context/_phase_finalize` 就是先例）；③ `atlas.server` 的 181 处 `_server()` 逐步换成 `Depends(get_app_services)`（`atlas/api/dependencies.py` 已提供）。

---

### 9. 存在同步阻塞调用混在 async 函数里（8 处未包 `to_thread`）

**证据**（AST 精确扫描 async 函数内、且不在 `to_thread` 参数位置的调用）：

```
atlas/api/projects_router.py:103      async def import_project  -> subprocess.run
atlas/api/workspace_router.py:897,903 async def create_git_pr  -> subprocess.run ("gh auth status" / "gh pr create")
atlas/api/workspace_router.py:951,957,966 async def create_git_pr -> subprocess.run
atlas/api/workspace_router.py:985      async def git_pr_check_log -> subprocess.run
atlas/api/workspace_router.py:1148     async def comment_git_pr  -> subprocess.run
atlas/plugins/runtime.py:661           async def _load_one       -> subprocess.run
atlas/runtime/hub_control.py:95        async def start           -> subprocess.Popen
```

对照：**整个仓库异步化做得很认真** —— `subprocess.run/Popen` 共 91 处，绝大多包在 `asyncio.to_thread` 里（如 `atlas/sandbox.py:32,68,126`、`atlas/api/workspace_router.py:359,579,593,704`）；`time.sleep` 仅 16 处且**全部在同步函数中**（已逐个 AST 校验）；`requests` 零使用（全用 httpx）。

同类问题（同步 SQLite 在 async 里）：
```
atlas/engine/notifications.py:62   def publish_notification(...)   # 同步
  └─ notifications.py:76  with _lock, sqlite3.connect(path, timeout=5) as db
atlas/agent/tool_node.py:208         publish_notification(...)      # 在 async def process_event 内
atlas/tools/local_execution.py:509   publish_notification(...)      # 在 async def _notify 内
```
注意 `notifications.py:144` 的 `consume_notifications` **正确**包了 `asyncio.to_thread` —— 写路径漏了。

**为什么严重**：`create_git_pr` 在事件循环上同步跑 `git push` + `gh pr create`，`timeout=120` —— **一个 PR 创建可冻结整个后端 2 分钟**（所有 SSE/WS 流停摆）。

**怎么修**：统一套 `await asyncio.to_thread(subprocess.run, ...)`，并加 lint 规则禁止 async 函数内直呼 `subprocess.*`。

---

### 10. WebSocket 与流式连接缺少资源上限，`RunState` 只增不减

**证据**：`atlas/api/runtime.py`

```python
# 126-128 行
self.connections: dict[str, WebSocket] = {}   # conn_id → ws
self.runs: dict[str, RunState] = {}           # run_id → RunState
self.conn_runs: dict[str, str] = {}           # conn_id → active run_id
```
全文件 grep **无任何** `runs.pop` / `del self.runs` / `_MAX_RUN` / LRU / prune —— `runs` 只增不减。

`RunState.events`（`runtime.py:50`）注释自陈 `# full event log for replay`，`next_envelope`（`runtime.py:108`）**无条件 append**，同样无 cap。

`RuntimeManager.disconnect`（`runtime.py:326-327`）只清 `connections`/`conn_runs`，**不动 `runs`**。

对照：`atlas/logs.py:120` 的 `_run_paths` 有 `pop`；`atlas/api/local_models_router.py:345-352` 的 `_OLLAMA_PULL_JOBS` 有 64 上限 —— 说明仓库里有人会加 cap，此处漏了。

其他无界/半无界全局（AST 扫出 234 个模块级可变容器，以下为高风险）：
- `atlas/server.py:190` `skill_acquisitions`、`:193` `external_agent_status_cache`、`:194` `external_conversation_sessions`
- `atlas/heartbeat/__init__.py:180,182,183` `_state`/`_cooldowns`/`_events` —— `cooldown()` 用 `setdefault` 创建，无回收
- `atlas/engine/tool_registry.py:24` `_active_contexts`
- `atlas/engine/branch_summaries.py:44,46` `_inflight`/`_completed`
- `atlas/memory/observer.py:261,262` `_DAILY_SPENT`/`_DAILY_RESERVED`
- `atlas/memory/windows_sources.py:1351` `_passive_controllers`

**为什么严重**：桌面产品是长驻进程（一周不重启很常见）。每个 run 的 `events` 是完整事件日志（含每次 token delta），一个长对话能累积到几十 MB；`runs` 永不释放意味着内存随会话数单调上升。配合问题 1 的 `_BREAKER_CACHE`（进程级、永不过期）和 Docker 沙箱 `_containers`（`atlas/sandbox.py:16`，`stop()` 才 pop），这是明确的 OOM 路径。

**怎么修**：`runs` 加 LRU（保留最近 N 个 + 活跃 run 常驻）；`RunState.events` 加条数/字节上限，超出时截断但保留 `persisted_sequence` 之后的（持久化已在 `runtime.py:259-295` 做了，可据此安全裁剪）。

---

## 二、分维度详情

### 维度 1：架构

**模块划分**：32 个顶层包。`agent`/`agents`（单复数并存）、`api`（57 个 router 文件）、`capabilities`/`kernel`/`engine`（三套执行抽象并存）、`tools`/`x2`（两套工具实现）、`memory`（8 个 >700 行文件）、`skills`/`market`、`runtime`/`hub` —— **职责有真实重叠**：

- `kernel/`（2025 年后新增，移植自 codex/ZCode）与 `engine/`（Hermes fork 适配）与 `agent/`（原生编排）三层都在跑：`atlas/agent/run_phases.py:838` 组消息，`atlas/kernel/loop.py:267` 跑循环，`atlas/engine/hermes_runtime.py:968` 又有一个 `run_turn`。`kernel/exec.py:4` 的头注释自陈移植来源：`# Ported from openai/codex@... Ported from zai-org/ZCode@...`
- 两套工具命名：`atlas/tools/x2/`（`_registered`/`_schemas` 全局注册表）与 `atlas/tools/` 平铺实现，中间靠 `_ALIASES` 做翻译层。3 套别名表 + `INLINE_TOOL_EXECUTORS` + `_hermes_fallback_handlers` + `_hermes_entries` 四套查找结构。

**循环依赖**：module 级 `import` 仅 2 个 SCC（见问题 8），但**690 处函数内 import** 表明大量潜在环被运行时绕过。

**上帝模块**：见问题 8 表格。`atlas.server` fan-out 72 是全局单例容器（945 行 + 30 个模块级单例变量）。

**正面发现**：`atlas/api/dependencies.py` 的 `get_app_services(connection)` 是正确做法（"Resolve services from this request's app, never from a module singleton"），已被 30 个模块用；`app.state.services` 模式（`application.py:79`）也是对的。问题在于**新旧两种模式并存**，`_server()` 旧模式仍有 181 处。

---

### 维度 2：并发与正确性

**做得好的**：
- 阻塞调用异步化覆盖率高（91 处 subprocess 绝大多数包 `to_thread`）
- `time.sleep` 16 处全在同步函数（已 AST 逐个验证）
- 零 `requests`，全 httpx
- `asyncio.to_thread` 用于 git/Docker/LSP/PTY 等
- `atlas/memory/__init__.py:325` 用 `aiosqlite`（异步 SQLite）
- 主动处理取消语义：`model_call.py:584-598` 用 `asyncio.wait({next_task, cancel_task}, FIRST_COMPLETED)` 而不是裸 await

**问题**：见问题 2、3、9、10。

**竞态（已确认）**：
- `atlas/api/run_drive.py:243` `_goal_run_locks: dict[str, asyncio.Lock] = {}`，`setdefault` 在单线程事件循环里原子，但 dict 无回收。
- `atlas/engine/notifications.py:19` `_waiters: dict[str, set[tuple[loop, event]]]` —— 用 `_waiters_lock` 保护且配对 `unsubscribe`，实现正确。
- `atlas/api/local_models_router.py:46` `_OLLAMA_PULL_JOBS` —— 有 64 上限，但 `_run_ollama_pull`（`:160`）直接 `_OLLAMA_PULL_JOBS[job_id]` 取值，若在 `:352` 被 stale 清理掉会 `KeyError`。

**全局可变状态**：234 个模块级 dict/list/set。`atlas/safety/policy.py:13-14` 的 `_LOG`/`_DENIALS` 在多 worker 下不共享（未验证是否用了 `--workers` —— `cli.py:56` 未传、`desktop_entry.py:34` 未传，单 worker，风险低）。

---

### 维度 3：资源管理

**HTTP 客户端**（做得较好）：
- `httpx.AsyncClient` 27 处，绝大多数 `async with` 短生命周期
- 长生命周期客户端有 `aclose`：`atlas/channels/adapters/wecom.py:187-190`、`atlas/memory/unified_client.py:120-135`（惰性单例）
- `atlas/upstream/sources.py:100-102` 是**同步** `httpx.Client`，每次新建 `_client()` 返回新实例 —— **未确认调用方是否关闭**（未验证）

**SQLite**（混合）：

已正确配置的：`atlas/memory/outbox.py:86-92`
```python
self._conn = sqlite3.connect(str(self.path), timeout=15)
from hermes_state_wal import apply_wal_with_fallback
apply_wal_with_fallback(self._conn, db_label="Atlas operational outbox")
self._conn.execute("PRAGMA busy_timeout=15000")
```
`atlas/channels/ingress.py:81-84`、`atlas/channels/delivery.py:59-62`、`atlas/gateway_service.py:72-73`（`check_same_thread=False` + `threading.Lock`）同样正确。

**未配置的（重点）**：`atlas/memory/__init__.py:325-327`
```python
self._db = await aiosqlite.connect(str(self._db_path))
self._db.row_factory = aiosqlite.Row
await self._db.execute("PRAGMA foreign_keys = ON")     # 只有这一条 PRAGMA
```
**没有 `journal_mode`、没有 `busy_timeout`**。实测两个真实库：

```
$ state.db (D:/Atlas/engine/state.db, 38 MB)
journal_mode [('delete',)]     <- 不是 WAL
synchronous  [(2,)]            <- FULL
busy_timeout [(5000,)]
freelist     2068

$ atlas.db (D:/Atlas/data/atlas.db)
journal_mode [('delete',)]     <- 不是 WAL
synchronous  [(2,)]
busy_timeout [(5000,)]
```

`stream` 判据：`journal_mode=delete` + `synchronous=FULL` 意味着**每次 commit 都要 fsync 并独占整库写锁**。`atlas.db` 上还有 FTS5 触发器和 `messages_fts`（`memory/__init__.py:895-915`，`tokenize='trigram'`），每次消息插入都触发 FTS 写入。

**WAL 决策需要澄清**：`hermes_state_wal.py:254-282` 有一段长论证，`is_sqlite_wal_reset_vulnerable` 对 `(3,50,4)` 返回 `True`，**故意保持 DELETE 模式是 upstream 的有意决策**，不是疏漏。本项目 venv 实测 `sqlite3.sqlite_version == 3.50.4` —— 确实落在漏洞区间。

**所以**：DELETE 模式**在此版本下是有意选择**，但副作用是并发写退化为串行 + 每次 commit fsync。`session_sync.py:48-55` 的 `_open_db` 是**每次调用新建 `SessionDB`**（22 个调用点），意味着每个消息 append 都 open/close 一次 DB 并跑 WAL 检查 —— 这是真正的性能与正确性风险点。

**子进程**：`atlas/skills/market.py:776-790` 用 `asyncio.shield` + `_kill_and_reap_search_worker` 正确回收；`atlas/tools/local_execution.py:1298-1345` Windows 用 `taskkill /T /F` 杀进程树，逻辑完整。`atlas/tools/local_execution.py:1000-1010` 创建 `tempfile.NamedTemporaryFile(delete=False)` 存 stdout/stderr，**未见对应清理**（未验证是否有启动时扫除）。

**Docker 沙箱**：`atlas/sandbox.py:16` `self._containers: dict[str, tuple[str,str]] = {}`，`stop()` pop，但**若进程崩溃未调用 stop，容器会残留**。

---

### 维度 4：错误处理

**量化**（ruff `BLE001,S110,S112` 实测）：
```
TOTAL violations: 188
totals by rule: {'BLE001': 172, 'S110': 13, 'S112': 3}
CRITICAL-scope: 21 across 14 scopes
SCOPES EXCEEDING BASELINE: 44
```
`noqa: BLE001` 注释 187 处 —— **这个量级说明裸 `except Exception` 是既定风格，不是偶发**。

**裸 `except:`**：**0 处**（值得肯定）。

**静默失败**（AST 扫出 125 个 handler 无任何日志，其中典型）：
```
atlas/kernel/model_call.py:266  except Exception: pass     # retry-after 头解析
atlas/kernel/model_call.py:324  except Exception: pass     # rate-limit 重置头
atlas/kernel/model_call.py:408  except Exception: pass     # usage model_dump
atlas/kernel/model_call.py:821  except Exception: pass     # stream close
atlas/kernel/loop.py:1718       except Exception: pass      # WorktreeService 构造失败静默
atlas/kernel/exec.py:241        except Exception: pass
atlas/repomap/__init__.py:422   except Exception: pass      # pygments 词法分析回退
atlas/tools/local_execution.py:1032,1038  except Exception: pass
atlas/tools/browser_use_compat.py:696     except Exception: pass
atlas/tools/media_generation_search.py:833 except Exception: pass
```

其中 `atlas/kernel/model_call.py:821` 是**流关闭失败被吞** —— 与问题 3 的线程泄漏叠加，会让线程泄漏完全无迹可循。

**好的方面**：`atlas/logs.py:36-53` 的敏感字段脱敏相当细致（`_SENSITIVE_KEYS` + 两套正则 + 长文本截断到 1000 字符 + `output/stdout/stderr/content/prompt/arguments` 只记长度）；`atlas/agent/tool_node.py:520-523` 安全审查不可用时降级为 `ask`（fail-safe 方向对）；`atlas/api/tools_router.py:108-111` PTY spawn 失败 `log.exception` + 前端上报，是好模式。

---

### 维度 5：安全

**鉴权**：单一 `OriginGuard` ASGI 中间件（`atlas/origin_guard.py:62-91`），覆盖 http + websocket。设计文档（`origin_guard.py:1-21`）思路正确且考虑周全：
- WebSocket 不受 CORS 保护 → 显式覆盖
- `null` origin 单独不够（"sandboxed iframes on any site send that too"）→ 明确拒绝纯 `null`
- `Sec-Fetch-Site: same-origin` 被拒
- 非 loopback 必须带 token
- timing-safe 比较用 `secrets.compare_digest`

**缺陷**：见问题 6。另 **DEV_ORIGINS 未按环境门控**（`origin_guard.py:35-38`），打包版仍信任 `http://localhost:5173/4173`。

**CORS**（`atlas/api/application.py:83-89`）：
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[*sorted(DEV_ORIGINS), "null", *configured_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
`allow_credentials=True` + 含 `"null"` + `"http://localhost:5173"`。**无 `allow_origin_regex` 的 `*`**，不是最坏情况。

**密钥存储**：
- ✅ OS keyring 路径存在：`atlas/channels/credentials.py:38-72`（`KeyringCredentialStore` + 优雅降级到环境变量）、`atlas/api/linear_integration_router.py:69-94`
- ❌ 模型网关 key 明文在 `atlas.toml:15` + 经 API 明文回吐（问题 5）
- ⚠️ `D:\Atlas\engine\auth.json` 只存 **credential_pool 元数据**（`id`/`label`/`auth_type`/`priority`/`source: env:ANTHROPIC_API_KEY`/`secret_fingerprint: sha256...`）—— **不含明文密钥**，设计良好；但文件权限是 `644`，Windows 上对其他本地用户可读

**任意命令执行**：这是**功能**而非漏洞，但暴露面很大：
- `atlas/api/tools_router.py:92-135` `ws_terminal`：`PtyProcess.spawn(["powershell.exe", ...], cwd=cwd)`，`cwd` 来自 `Query(...)` 且**只校验是已存在目录**。配合问题 6 的 WeakOrigin 模型，非 loopback 场景下这是完整 shell。
- `atlas/kernel/exec.py` 有正确设计：`DEFAULT_BASH_TIMEOUT_MS=120000`、`DEFAULT_BASH_MAX_TIMEOUT_MS=600000`、`HeadTailBuffer` 50/50 头尾保留 + `omitted_bytes` 标记
- ⚠️ **多个写入工具缺 workspace 约束**：`atlas/agent/tool_node.py:326-345` 的 `allowed_paths` 校验仅在 `elif allowed_paths:` 分支生效，`allowed_paths` 为空时**不校验**。

**任意文件读写**：`/api/workspace/file`（`atlas/api/workspace_router.py:402-425`）有正确实现 —— `root` 必须是绝对路径、`_workspace_path` 用 `.resolve()` + `base not in target.parents` 做 containment。**这是正确的路径遍历防护**。`/api/config/restore`（`config_editor_router.py:107-115`）用 `startswith(f"{target.name}.bak-")` + 拒绝 `/` `\`，也是对的。

**SSRF**：`atlas/tools/ssrf_transport.py` 实现质量高（155 行）：
- connect-time DNS 校验（不是 parse-time，避免 TOCTOU）
- 覆盖所有解析结果（任一私有地址即 block）
- 屏蔽 `metadata.google.internal`/`metadata.goog`
- 拒绝 unix socket
- 保留 Host/TLS SNI
- fake-IP 例外明确注释理由
- 移植来源标注：`# Ported from NousResearch/hermes-agent@... tools/url_safety.py (MIT)`

但**只有 2 个调用点**：`atlas/tools/web.py:206`、`atlas/tools/web_extract.py:87,188`。另有多处 `httpx.AsyncClient` 直接构造而**未过 SSRF 守卫**：
- `atlas/workbench/template.py:67` `httpx.AsyncClient(timeout=300)` **无任何 timeout 细项、无守卫**
- `atlas/library/runtime.py:343` `httpx.AsyncClient(timeout=30, follow_redirects=True)`

**插件/扩展**：`atlas/plugins/runtime.py` 无签名/哈希校验（grep `signature|sha256|verified` 返回空），只有 `hook_trust_router.py` 的**信任指纹**机制（`HookTrustRequest.fingerprint: str = Field(min_length=64, max_length=64)`）—— 这个是好设计。插件本身走 `subprocess.run`，是进程隔离而非沙箱。

---

### 维度 6：流式与韧性

**LLM 调用路径**：`atlas/kernel/model_call.py`（851 行）—— 这是**代码库里质量最高的一块之一**：
- 移植来源明确：`# Ported from openai/codex@6c0c6759... responses_retry.rs (Apache-2.0)` + `# Claude Code v2.1.296 retry settings are modeled from ...`
- 真流式：`"stream": True` + `"stream_options": {"include_usage": True}`
- 增量累积 + 前缀合并而非全量替换
- 分类重试：`rate_limit`（429 + 文本标记）、`timeout`（408/425/504）、`malformed_response`
- 抖动指数退避：`base = 0.2 * (2 ** retry_index)` + `random.uniform(0.9, 1.1)`；overloaded 上限 300s
- `Retry-After` 头解析**三种形态**，含 `anthropic-ratelimit-*-reset`
- 重试预算：默认 10 次，watchdog 模式 300 次
- 部分响应保留：`preserve_partial_output`、"Merge a restarted stream without dropping its already observed prefix"
- 用量预算：`usage_budget.reserve(...)`，超预算抛 `ModelCallError(category="budget")`

**熔断**：
- ❌ **没有 provider 级熔断器**。`breaker.md` 与熔断无关（问题 1）。
- ⚠️ `atlas/agent/fallback_cooldown.py` 是**进程内 dict**，无锁，无持久化，重启即忘。
- ✅ 唯一真正的熔断器在 `atlas/channels/adapters/dingtalk.py:52`：`RECONNECT_CIRCUIT_BREAKER_TRIPS = 5` + 退避 `[2,5,10,30,60]` —— 局部、针对渠道 SDK。

**超时**：见问题 2（`read=None`）。另 `max_connections=100, keepalive_expiry=20.0` 配置合理。

**韧性正面**：`atlas/api/startup_components.py`（组件级启动隔离）、`atlas/api/deferred_startup.py`（延迟启动 + 快速 `/api/health`）、`tests/test_startup_failure_resilience.py` 5 个测试覆盖"DBOS/MCP/channel 失败仍能启动" —— 这部分设计成熟。

---

### 维度 7：可观测性

**日志（好）**：`atlas/logs.py`
- structlog + stdlib 桥接，双层输出：磁盘 JSON + stderr 可配
- `TimedRotatingFileHandler(when="midnight", backupCount=14, utc=True)`
- 三套脱敏正则 + `_summary()` 递归
- **per-run JSONL 事件流**：`append_run_event(run_id, event, **fields)`，路径 `LOG_DIR/runs/<date>/<run_id>.jsonl`，`run_id` 白名单校验，`allow_nan=False`
- `uvicorn.access` 降到 WARNING

**缺陷**：
- ❌ **无 `contextvars` 绑定**：grep `bind_contextvars|structlog.contextvars` 零命中。日志里无法自动带 `run_id`/`conversation_id`，必须每个调用点手写。
- ❌ **无指标**：grep `prometheus|/metrics|opentelemetry|otel` 零命中。`/api/runtime/observability` 只是**组件存活快照**（boolean），不是指标。
- ❌ **无分布式/请求追踪**：无 trace_id/span、无 W3C traceparent。
- ⚠️ `atlas/logs.py:22` `_run_paths` 仅在 `run_end` 事件时 pop，若 run 异常逃逸（非这三条路径），条目泄漏。
- 🐛 **`atlas/api/health_router.py:88` 的 docstring 位置错误** —— 它写在函数体第 4 行语句之后，是**纯字符串表达式语句**，不成为 `__doc__`。

---

### 维度 8：测试

**规模**：257 个 `test_*.py`，78696 行（实现 124213 行，**测试/实现 = 0.63** —— 投入可观）。

**配置**（`pyproject.toml`）：
```toml
asyncio_mode = "auto"
addopts = "-m unit"                      # 默认只跑单元 lane
markers = ["unit", "integration", "desktop", "live", "fake_provider", "flaky"]
```
lane 由 `tests/conftest.py:83-111` `_test_lane()` 自动推断（未显式标记则默认 unit），冲突时抛 `UsageError` —— **这个设计很好**。

**隔离（好）**：`conftest.py:22-48` 把 `HOME`/`USERPROFILE`/`APPDATA`/`LOCALAPPDATA`/`HERMES_HOME`/`ATLAS_DATA_DIR`/`ATLAS_SKILLS_HOME` 全重定向到临时目录，**并清空所有 `*_API_KEY/_TOKEN/_SECRET/_PASSWORD/_CREDENTIALS` 环境变量** —— 防"测试读到操作者真实凭据"。

**实测结论**：见问题 4。补充：
- 挂死点：`tests/test_subagent_settings.py::test_subagent_settings_apply_to_new_children_only`
- `.pytest_cache` 损坏（`WinError 183`），`--basetemp` 可绕过
- pytest-timeout 在 Windows asyncio 上失效（默认 `thread` 法）——`pyproject.toml` 未设 `timeout_method`，而 `signal` 法在 Windows 也不支持，**这是平台性缺陷，需要 CI 层的 wall-clock 杀进程兜底**
- `test_lint_gate.py` 把 ruff 规则作为门禁 —— **思路很好**（用测试锁住代码质量），但当前是红的

---

## 三、与 ZCode 的差距清单（按严重度）

| # | 短板 | 现状证据 | 影响 |
|---|---|---|---|
| 1 | **Agent 身份提示词是运行时可写文件 + 越狱内容** | `run_phases.py:59-89`、`engine/breaker.md`（28KB）、`hermes_runtime.py:201-215` 关掉注入扫描 | 产品道德与法律风险；提示注入面敞开 |
| 2 | **发布门禁是红的且会挂死** | 86 failed / 5 collect error / 89% 挂死（实测） | 无回归保护；6.3 万行测试投入失效 |
| 3 | **无 provider 级熔断 + LLM 无读取超时** | `network_transport.py:168` `read=None`；唯熔断器在 `dingtalk.py:52` | 单点故障可冻结整个后端 |
| 4 | **密钥明文落盘 + API 明文回吐** | `atlas.toml:15,33`；`config_editor_router.py:66` | 凭据泄露 |
| 5 | **默认监听 `0.0.0.0`** | `config.py:114`；CLI 继承配置但桌面入口用 127.0.0.1 | 局域网暴露 |
| 6 | **无指标 / 无 trace 关联** | `prometheus\|otel\|trace_id` 零命中；无 contextvars 绑定 | 线上问题无法定位 |
| 7 | **God module / 单函数 1319 行** | `memory/__init__.py` 4858 行、41 个 ≥800 行 | 核心路径不可单测；改动风险高 |
| 8 | **三套执行抽象并存 + 690 处延迟 import** | `agent/` + `kernel/loop.py` + `engine/hermes_runtime.py` 都在跑 | 认知负担；同一 bug 需在 3 处修 |
| 9 | **安全底线被默认关闭（含"不可恢复底线"）** | `safety/policy.py:22` `reviewer: "off"`；`tool_node.py:473` 整个 if 短路 | "有安全层但无效"比没有更危险 |
| 10 | **插件无隔离无签名** | `plugins/runtime.py` 零命中；legacy hook 直接 `subprocess.run` | 供应链风险 |
| 11 | **资源上限缺失** | `runtime.py:127` runs 只增不减；`RunState.events` 无 cap | 长会话 OOM |
| 12 | **WS 暴露面无速率限制** | `tools_router.py:92` `ws_terminal` 起 powershell | 单一客户端可耗尽 PTY/进程额度 |

---

## 四、值得肯定的部分

1. **`atlas/tools/ssrf_transport.py`**（155 行）是教科书级 SSRF 防护：connect-time DNS 校验、全解析结果校验、Host/SNI 保留、unix socket 拒绝、fake-IP 例外带实测理由、移植来源与许可标注。
2. **`atlas/kernel/model_call.py`** 的重试/退避/`Retry-After` 解析/部分响应保留/用量预算，明确移植自 codex 与 Claude Code 并标注 commit，实现完整。
3. **`atlas/origin_guard.py`** 的安全推理文档（1-21 行）把"为什么 `null` origin 不够""为什么 WebSocket 不受 CORS 保护""为什么 same-origin 也要拒"讲清楚了。
4. **`atlas/logs.py`** 的脱敏（3 套正则 + 递归摘要 + 长度截断）与 per-run JSONL 事件流。
5. **`tests/conftest.py`** 的环境隔离（重定向 7 个 home 类变量 + 清空凭据类环境变量）与 lane 自动推断 + 冲突检测。
6. **测试即质量门禁** 的思路（`test_lint_gate.py` 用 ruff baseline 锁住异常处理规范）。
7. **`atlas/api/dependencies.py`** + `app.state.services` 的服务定位模式。
8. 异步化纪律：91 处 subprocess 绝大多数包 `to_thread`、16 处 `time.sleep` 全在同步函数、零 `requests`。

---

## 五、诚实标注（未验证项）

- `state.db` 的并发写实际冲突频率未实测（只读查了 PRAGMA）。
- `atlas/memory/observer.py:261-262` 的 `_DAILY_SPENT/_DAILY_RESERVED` 是否有跨天清理未确认。
- `atlas/tools/local_execution.py:1000-1010` 的临时 stdout/stderr 文件是否有清理逻辑未确认。
- `atlas/upstream/sources.py:100-102` 的同步 `httpx.Client` 调用方是否 `close()` 未确认。
- Docker 容器在进程崩溃后的残留情况未实际验证。
- `run_drive.py:243` `_goal_run_locks` 在 Python 3.14 下的 `asyncio.Lock` loop 绑定行为未验证。
- 全量 pytest 挂死点是通过 verbose 输出最后一行定位，未做 py-spy 级别的堆栈确认。
- 86 个失败中，仅抽样诊断了 5 类根因，其余未逐个归因。

---

## 六、关键路径（供后续跟进）

```
D:\Atlas\core\atlas\agent\run_phases.py
D:\Atlas\engine\breaker.md
D:\Atlas\core\atlas\engine\hermes_runtime.py
D:\Atlas\core\atlas\models\network_transport.py
D:\Atlas\core\atlas\kernel\model_call.py
D:\Atlas\core\tests\conftest.py
D:\Atlas\config\atlas.toml
D:\Atlas\core\atlas\api\config_editor_router.py
D:\Atlas\core\atlas\config.py
D:\Atlas\core\atlas\safety\policy.py
D:\Atlas\core\atlas\api\runtime.py
```
