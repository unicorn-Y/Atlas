# 阶段一 P0-2：MCP 无状态协议适配

- 任务书：`tasks/taskbooks/ATLAS-UPGRADE-W1.md` 第 33–55 行
- 施工日期：2026-11-08
- 基线：`tasks/upgrade-w1-baseline.txt`（65 行，开工时 `git status --short` 快照）
- 本阶段未执行 `git add` / `commit` / `push`，未切换分支，未改动 `frontend/`、`config/atlas.toml`

---

## 1. 交付内容

| 文件 | 变更量 | 说明 |
| --- | --- | --- |
| `core/atlas/tools/mcp_client.py` | +120 / -17 | 探测式握手、默认 transport、无状态缓存、状态区分 |
| `core/atlas/runtime/external_import.py` | +14 / -4 | 外部导入默认 `streamable_http`，显式 `sse` 保留 |
| `core/tests/test_c4_external_import.py` | +31 | 新增 `test_url_servers_default_to_streamable_http` |
| `core/tests/fixtures/stateless_mcp_server.py` | 新增 | 无状态 + 传统两套 fixture server |
| `core/tests/test_mcp_stateless_handshake.py` | 新增 | 无状态直连、传统回退两条集成用例 |

---

## 2. 五条要求的落地情况

### ① 握手改探测式，`initialize` 失败不抛错，降级无状态直连 `list_tools`

`_connect_server` 在 `http_like` 传输下先调用 `session.discover()`：

- 成功 → `modern = True`，`handle.stateless = True`，日志 `mcp.server_stateless_discovered`
- 失败 → 日志 `mcp.server_discover_unavailable`，随后进入 `initialize()`
- `initialize()` 成功 → 正常有状态路径
- `initialize()` 对 http_like 失败 → 兜底 `handle.stateless = True`，日志 `mcp.server_stateless_fallback`，不抛错

stdio 传输失败仍直接 `raise`（无降级语义），保持原有行为。

### ② 默认 transport `sse` → `streamable_http`，`sse` 保留为显式配置

- `_parse_server_configs`：`transport` 缺省时 `"streamable_http" if data.get("url") else "stdio"`
- `external_import._canonical_mcp`：URL-only 服务器默认 `streamable_http`
- 显式写 `transport = "sse"` 的配置仍走 `_connect_sse`，未删除、未改语义

### ③ 无状态路径带 `MCP-Protocol-Version` 头 + 按 `ttlMs` 缓存 `tools/list`

- 请求头由 SDK 按协议时代逐请求盖章（见 §3.1，这是关键约束）
- `_list_tools_with_cache` 依据 `handle.tool_cache_ttl` 缓存，命中未过期直接返回，过期重取
- `MCPServerHandle` 新增 `tool_cache_until` / `tool_cache_ttl`

> **必须说明：`MCP-Tool-Cache` 是自造兼容层。**
> 当前 SDK（`mcp` 2.1.1）中不存在 `MCP-Tool-Cache` 头，也没有对应的 ttl 类型。
> 实现方式是 `http_client.event_hooks["response"]` 里用正则解析 `tools/list` 响应头
> `MCP-Tool-Cache` 中的 `ttlMs`，换算为秒写入 handle。这不是 SDK 原生能力，
> 服务端不发该头时 `tool_cache_ttl` 恒为 `0.0`，等价于不缓存（即退回每次重取）。

### ④ 保持既有语义不变

`_mcp_rule_matches`、`_redact_mcp_arguments`、连续失败冷却、重连监控均未改动。
`git diff` 核对：这些函数体零改动，仅在连接与列举路径上新增分支。

### ⑤ 状态区分 `connected` / `connected_stateless`

`"state"` 与 `"connection_state"` 同取 `"connected_stateless"` / `"connected"`。

---

## 3. 过程中发现的两个 SDK 约束与一个真 bug

### 3.1 SDK 服务端按 `MCP-Protocol-Version` 请求头决定「协议时代」

`mcp/server/streamable_http_manager.py:173-190`（`_handle_request`）：请求头存在且**不在**
`HANDSHAKE_PROTOCOL_VERSIONS` 中时，请求被交给 `handle_modern_request` → `_serve_modern_stream`。
该路径下：

- `initialize` 直接返回 `UNSUPPORTED_PROTOCOL_VERSION`
- 所有请求必须带 `params._meta` 的 envelope 键（`io.modelcontextprotocol/protocolVersion` +
  `io.modelcontextprotocol/clientCapabilities`），校验在 `mcp/shared/inbound.py:443`，
  错误文案 `params._meta is missing the required envelope key(s): ...`

**结论：无条件设置该头会让降级路径彻底不可达**——客户端自己把 `initialize` 探测
路由到了 modern 时代，探测必然失败且错误信息具有误导性。

### 3.2 发现的真 bug 与修复

初版实现里 `_connect_streamable_http` 有：

```python
headers.setdefault("MCP-Protocol-Version", LATEST_PROTOCOL_VERSION)
```

实测（`tasks/_w1_probe_stateful.log`）报错：

```
EXC MCPError params._meta is missing the required envelope key(s): ...
```

删除该行后同一探针输出：

```
mcp.server_discover_unavailable reason=MCPError server=legacy
mcp.server_initialized protocol=2025-11-25 server=legacy
connected: {... 'state': 'connected', 'connected': True, 'tool_count': 1 ...}
```

即：降级探测失败 → `initialize` 成功 → 状态 `connected`，符合要求 ⑤。
该头现由 SDK 的 `_make_handshake_stamp` / `_make_modern_stamp`（`mcp/client/session.py:153/160`）
按时代自行盖章，无需也不应手工设置。

### 3.3 `stateless_http` 不影响 `server/discover`

`MCPServer.streamable_http_app(stateless_http=False)` 仍会应答 `server/discover`
（`lowlevel/server.py:659` 默认 handler）。因此单靠 `stateless_http` 无法构造「老服务器」，
fixture 必须覆盖 handler：

```python
legacy._lowlevel_server.add_request_handler("server/discover", RequestParams, _no_discover)
```

两个易错点：

- handler 的 params 类型必须是 `mcp.types.RequestParams`，用 `object` 会在
  `mcp/server/runner.py:216` 抛 `AttributeError: type object 'object' has no attribute 'model_validate'`（HTTP 400）
- `MCPError` 在 `mcp.shared.exceptions`，**不在** `mcp.types`；`mcp.types.METHOD_NOT_FOUND == -32601`

---

## 4. 验收证据

### 4.1 新增用例

```
core/tests/test_mcp_stateless_handshake.py ....... 2 passed, 5 warnings in 4.80s
```

- `test_stateless_streamable_http_discovers_and_calls_tool`：工具列表 `["stateless__ping"]`，
  `call_tool` 返回 `pong`，`state == "connected_stateless"`
- `test_legacy_server_falls_back_to_initialize_handshake`：工具列表 `["legacy__ping"]`，
  `call_tool` 返回 `pong`，`state == "connected"`

两条都覆盖了任务书要求的「连上 → list_tools 有工具 → 调用一次成功」，
且第二条即「旧服务器回归仍通过」。

### 4.2 `pytest core/tests -k mcp` 全量结果

命令：

```bash
cd /d/Atlas && PYTHONPATH=D:/Atlas/core \
  D:/Atlas/core/.venv/Scripts/python.exe -m pytest core/tests -k mcp -q -p no:cacheprovider \
  --timeout=60 --ignore=core/tests/test_hermes_setup.py --ignore=core/tests/test_local_models_adapter.py
```

结果：**14 failed, 58 passed, 2419 deselected, 7 warnings in 410.08s**

两个 `--ignore` 是**既有收集期错误**，与本次改动无关（见 §4.4）。

### 4.3 失败归因（HEAD 对照实验）

用开工时保存的 `tasks/_w1_head_mcp_client.py` / `_w1_head_external_import.py`
（`git show HEAD:` 导出，已 `diff` 确认与 HEAD 一致）替换回工作区跑同一批测试，
跑完立即还原并 `diff -q` 校验一致。

| 测试文件 | 改动后 | HEAD 版 | 判定 |
| --- | --- | --- | --- |
| `test_mcp_client.py` | 4 failed, 18 passed | 4 failed, 18 passed | 既有 |
| `test_mcp_lifecycle_shutdown.py` + `test_mcp_server_hermes_sync.py` + `test_hermes_mcp_config.py` | 6 failed, 15 passed | 6 failed, 15 passed | 既有 |
| `test_runtime_resources.py -k mcp` | 2 failed | 2 failed | 既有 |
| `test_c4_external_import.py` | 2 failed, 9 passed | 3 failed, 8 passed | 既有 2 个；第 3 个是新用例，HEAD 上必失败（预期） |
| `test_startup_failure_resilience.py` | 卡死（exit 124） | 卡死（exit 124） | 既有 |
| `test_mcp_stateless_handshake.py` | 2 passed | — | 新增 |

**逐条失败原因（均为既有，与 transport 无关）**：

- `test_node_release_manifest_pins_official_binary_and_sha256`：
  `assert '24.21.0' == '22.23.3'` —— 本机 Node 版本与测试固定版本不符
- `TestMCPClient::test_connect_discovers_tools_for_agent`：
  MagicMock 的 `initialize().instructions` 被拼进工具描述，断言不匹配
- `test_start_records_runtime_config_discovery_and_restart_state` / `test_failed_configured_server_...`：
  mock `_connect_server` 抛错后的状态断言
- `test_codex_import_lands_mcp_rules_commands_model`：
  `{'DOCS_KEY': '{{secret:...}}'} != {'DOCS_KEY': 'x'}` —— secret 脱敏行为，与 transport 无关
- `test_scan_claude_manifest_kinds_conflicts_and_item_shape`：同上范畴，HEAD 也失败
- `test_mcp_lifecycle_shutdown.py` 3 条、`test_mcp_server_hermes_sync.py` 2 条、
  `test_hermes_mcp_config.py` 1 条：HEAD 同样失败

### 4.4 两个收集期错误属既有问题

```
core/tests/test_hermes_setup.py       ImportError: cannot import name 'hermes_pin' from 'atlas'
core/tests/test_local_models_adapter.py ImportError: cannot import name 'ATLAS_PROBE_NONCE'
                                        from 'atlas.engine.local_runtime_adapter'
```

证据：`git status --short` 显示这 4 个相关文件（两个测试 + `core/atlas/__init__.py` +
`core/atlas/engine/local_runtime_adapter.py`）**均未被改动**；开工基线
`tasks/upgrade-w1-baseline.txt` 中也没有它们的记录。

### 4.5 导入自检

```
PYTHONPATH=D:/Atlas/core python -c "from atlas.tools.mcp_client import MCPClient, MCPServerHandle; \
  from atlas.runtime.external_import import import_external; print('import OK')"
→ import OK
```

---

## 5. 未解决 / 需后续处理

1. **`test_startup_failure_resilience.py` 整体挂死**（HEAD 与改动后都挂，`--timeout=100` 也压不住，
   进程被外部 `timeout` 杀掉，exit 124）。这是既有问题，本阶段未修，**但它导致
   「`-k mcp` 全绿」这一验收条件目前无法达成**，需要单独排查该文件内的 MCP 启动路径。
2. `MCP-Tool-Cache` 兼容层无真实服务端可验证，只能验证「不缓存」分支；
   有真实下发该头的服务端时应补一条断言。
3. 既有失败共 12 条（`test_c4_external_import.py` 2 条、`test_mcp_client.py` 4 条、
   `test_mcp_lifecycle_shutdown.py` 3 条、`test_mcp_server_hermes_sync.py` 2 条、
   `test_hermes_mcp_config.py` 1 条）已确认与本次改动无关，但**未修复**，任务书未要求本阶段处理。
   §4.2 全量运行记录的是 14 failed：上述 12 条，加上 `test_runtime_resources.py` 2 条，
   正好 14 条。`test_startup_failure_resilience.py` 的 1 条失败未被计入这 14 条，因为该文件
   整体挂死、进程被外部 `timeout` 杀掉（exit 124，见本节第 1 条），pytest 没有把它统计成
   failed。因此 14 failed 不等于「12 + 全部其他失败」，而是「12 + runtime_resources 2」。

## 6. 回滚方式

本阶段改动集中在 3 个已跟踪文件 + 2 个新增测试文件，未提交：

```bash
cd /d/Atlas
git checkout -- core/atlas/tools/mcp_client.py core/atlas/runtime/external_import.py \
                core/tests/test_c4_external_import.py
rm -f core/tests/test_mcp_stateless_handshake.py core/tests/fixtures/stateless_mcp_server.py
```

即完全回到基线，不影响其他阶段。
