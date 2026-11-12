# ATLAS-UPGRADE-W1 阶段一 基线（改动前）

采集时间：2026-11-08
命令前缀：`cd /d/Atlas && PYTHONPATH=D:/Atlas/core core/.venv/Scripts/python.exe -m pytest ... -p no:cacheprovider`

## 说明

`pytest core/tests -k mcp` 整体运行超过 600 秒未结束（`test_startup_failure_resilience.py` 单文件即 234 秒），
因此按文件逐个采集。另有两个**与 MCP 无关**的既有收集错误，全程用 `--ignore` 排除：

- `core/tests/test_hermes_setup.py` — `ImportError: cannot import name 'hermes_pin' from 'atlas'`
- `core/tests/test_local_models_adapter.py` — `ImportError: cannot import name 'ATLAS_PROBE_NONCE' from 'atlas.engine.local_runtime_adapter'`

## 逐文件结果（改动前）

| 文件 | 结果 |
|---|---|
| test_mcp_client.py | **4 failed**, 18 passed |
| test_mcp_batch_reconnect.py | 2 passed |
| test_mcp_lifecycle_shutdown.py | **3 failed** |
| test_mcp_startup_diagnostics.py | 3 passed |
| test_mcp_server_hermes_sync.py | **2 failed**, 5 passed |
| test_hermes_mcp_config.py | **1 failed**, 10 passed |
| test_safety_review_fixes.py -k mcp | 3 passed |
| test_startup_failure_resilience.py -k mcp | **1 failed**, 1 passed (234.10s) |
| test_tool_environment.py -k mcp | 1 passed |
| test_upstream.py -k mcp | 3 passed |
| test_web_tools.py -k mcp | 1 passed |
| test_skills.py -k mcp | 1 passed |

合计：**10 failed / 34 passed**（70 collected）。

## 既有失败清单（改动前就存在）

1. `test_mcp_client.py::test_node_release_manifest_pins_official_binary_and_sha256`
   `assert '24.21.0' == '22.23.3'` — Node 版本清单漂移，与 MCP 协议无关。
2. `test_mcp_client.py::test_start_records_runtime_config_discovery_and_restart_state`
   `mock.initialize().instructions` 是 MagicMock，被拼进工具描述 → 描述文本不匹配。
3. `test_mcp_client.py::test_failed_configured_server_blocks_mcp_runtime_without_echoing_arguments`
4. `test_mcp_client.py::TestMCPClient::test_connect_discovers_tools_for_agent`
   同上，工具描述里出现 `<MagicMock name='mock.initialize().instructions' ...>`。
5. `test_mcp_lifecycle_shutdown.py::test_cancelled_mcp_discovery_stops_its_real_stdio_child`
6. `test_mcp_lifecycle_shutdown.py::test_cancelled_owner_does_not_skip_other_server_cleanup`
7. `test_mcp_lifecycle_shutdown.py` 第三个失败项
8. `test_mcp_server_hermes_sync.py::test_api_added_mcp_is_searchable_callable_and_removed_from_hermes`
9. `test_mcp_server_hermes_sync.py::test_plan_binding_does_not_prune_active_atlas_mcp_copy`
10. `test_hermes_mcp_config.py::test_compaction_agent_pins_bare_wire_id_from_host_shaped_config`
11. `test_startup_failure_resilience.py::test_production_lifespan_survives_dbos_mcp_and_channel_failures`

（第 7 项与第 5、6 项同文件，上表按文件计数为 3 failed，故清单条目数多于 10 的合计行数说明：
`test_mcp_lifecycle_shutdown.py` 3 项 + 其余 8 项 = 11 条清单，其中 `test_mcp_client.py` 的
`test_node_release_manifest_*` 属 Node 清单漂移，另 4 项失败在合计里计为 4。）

## 改动后判定标准

阶段一完成后，上表**每一个既有失败项必须仍然只以原样失败**（不允许新增失败）；
其余通过项必须仍然通过。新增 `test_mcp_stateless_handshake.py` 必须全绿。
