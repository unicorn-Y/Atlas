# RESULT4-Z5（WAVE4 扩展层批：X2 X3 X4 X8 X9 X10 X11 X21 X24 X27）

- worktree：`D:\Atlas\.worktrees\w4-z5`（分支 `wave4-z5`，基线 ec0a9d47 = wave3 tip）
- 真实模型通道：`deepseek-v4.1-flash` @ `https://d1api.xin/v1`（worktree 本地 `config/atlas.toml` + `data/user-settings.json` custom_models 条目 `custom: true`，密钥取自 OS 凭据库），WS 后端 `127.0.0.1:8885`（PowerShell Start-Process 分离进程，env `http(s)_proxy=http://127.0.0.1:7897`，隔离 `USERPROFILE=.tmp/live-profile` + 空 `.codex/hooks.json`）
- 驱动：`core/scripts/w4z5_live_check.py`（WS run.start，`--workspace/--permission-preset`）、`core/scripts/w4z5_acp_check.py`（ACP stdio 全方法驱动）、`core/scripts/w4z5_evidence_mcp_server.py`（发布 instructions 的 stdio MCP 证据服务器）
- live 插件 fixture：`data/plugins/w4z5-evidence/`（plugin.json + .mcp.json 指向证据服务器），受限 preset `data/agent-presets/w4z5-restricted.toml`（revision 1，tools.allow=[local_exec, tool_search]，mcp_servers=[]，plugins=[]）

## 总表

| Row | 结论 | 动作 | 关键证据 |
|---|---|---|---|
| X2 | ✅ CLOSED | 取证 | 真实回合 `set_plugin_enabled(false)` → 插件 MCP 工具从注册表消失（直调 `Unknown tool: w4z5-evidence__evidence_ping`）；`set_plugin_enabled(true)` → 恢复（`load_report.loaded=["w4z5-evidence"]`）。反序 disposer/async dispose 有 8 项单测 |
| X3 | ✅ CLOSED | 取证 | 真实回合两次 toggle 均报 `applied=true, restart_required=false`，`load_report.skipped=[{"name":"w4z5-evidence","reason":"disabled"}]`；无需重启。4 项撤回单测 + toggle 报告单测 |
| X4 | ✅ CLOSED | 暴露+取证 | 新增 `GET /api/plugins/config-layers`（scrub 后返回 profile→bundle→row-patch 组合快照，4 项 route 测试）；真实后端 HTTP + CLI `plugins dump-config` 双实证 row-id 替换链 bash→pwsh→nu |
| X8 | PARTIAL | 取证 | live：ACP `session/new` 解析 revision 化 preset，run journal `model_request_envelope` 实证工具池 default=18 个 → restricted=2 个（`['concludeTurn','tool_search']`）。残留：`runtime.plugin_realm` 已接线但**无消费者**（RESULT3-X5 判定不变）；`resolve_versioned` 无调用方 |
| X9 | ✅ CLOSED | 取证 | ACP live 三反例：未知 agent preset / 未知 permission preset / 缺 preset 语义均 `-32602` 拒绝；合法 preset 对建立会话并进入真实模型回合。webhook 半有 `test_automation_capability_binding` 2 项单测 + automation dispatch 传递（run_drive `_automation_dispatch_turn` resolve 双 preset） |
| X10 | ✅ CLOSED | 暴露+取证 | 适配器补齐 `permission_mode` 契约（read_only 拒写 / danger-full-access 免审批 / 其余逐次审批）+ kernel 侧 preset 翻译；live 双腿：full_access 回合写免审批直接生效；`permission_preset=ask` 回合 2 次 `approval.required tool=set_plugin_enabled` → allow_once → 生效 |
| X11 | ✅ CLOSED | 取证 | live `GET /api/plugins` 返回 `official`/`official_attestation`/`availability`/`installed`/`overrides`/`update_available`/`capability_groups` 全字段；单测 test_plugins.py 既有覆盖（:81-118） |
| X21 | ✅ CLOSED | 取证 | live 回合模型**逐字引用** instructions 段首句（ANCHOR_W4Z5 标记）+ 逐字引用工具描述为短指针（无标记内联）；live `GET /api/tools` 实证描述为指针。既有 6 项单测 |
| X24 | PARTIAL | 取证+暴露 | ACP 7 方法 live 全通（new/prompt×2 真实模型/list/set_config_option/resume/cancel/close）+ fail-closed 权限；修了 `MemoryStore.list_conversations` 漏 SELECT `metadata` 列的真 bug（session/list 因此永远筛不出 ACP 会话，单测假 memory 掩盖）。残留：per-session MCP 注入仍显式拒绝（-32602，属新底层编排，WAVE4 不做） |
| X27 | PARTIAL（不改） | 定性 | 桌面端 ConversationNodeDefinition 注册表已有（W3-X5）；application 级 slots/client 插件未贯通，属前端工程，不在本批「暴露+取证」范围，账本维持 W3 结论 |

## 新增/改动文件

产品代码：
- `core/atlas/api/plugins_router.py` — 新增 `GET /api/plugins/config-layers`（X4 暴露；`scrub` 后返回）
- `core/atlas/tools/plugin_marketplace.py` — `execute_plugin_manager_tool` 补 `permission_mode` 参数（read_only 拒写 / danger-full-access 免审批，X10 契约，修复 2 项预存失败）
- `core/atlas/engine/kernel/loop.py` — plugin-manager 派发处把 runtime `permission_mode` 翻译成适配器契约（read_only→read_only、full_access→danger-full-access，其余保持逐次审批）
- `core/atlas/memory/__init__.py` — `list_conversations` SELECT 补 `metadata` 列（X24 live 修复）
- `core/atlas/api/plugins_router.py` 无其他改动；事件面零改动

新测试：`core/tests/test_plugin_config_layers_route.py`（4 项）

脚本/证据基建（入库）：`core/scripts/w4z5_live_check.py`、`core/scripts/w4z5_acp_check.py`、`core/scripts/w4z5_evidence_mcp_server.py`
不入库（gitignore 外的本地 fixture，仅为 live 取证存在）：`config/atlas.toml`、`data/user-settings.json`、`data/plugins/w4z5-evidence/`、`data/plugins/state.json`、`data/agent-presets/w4z5-restricted.toml`、`.tmp/**`

## 单元测试真实输出

定向全套（含全部相关行的既有测试 + 新增 4 项）：

```text
$ cd core && python -m pytest -q -p no:cacheprovider --basetemp=D:/Atlas/.worktrees/w4-z5/.tmp/pytest \
    tests/test_plugin_reload_idempotent.py tests/test_plugin_disable_withdraws.py \
    tests/test_plugin_manager_tools.py tests/test_plugin_patch_layer.py tests/test_plugin_patch_row_ids.py \
    tests/test_plugin_config_layers_route.py tests/test_plugin_patches_http.py \
    tests/test_agent_preset_capabilities.py tests/test_agent_preset_enforcement.py \
    tests/test_automation_capability_binding.py tests/test_app_server_acp.py \
    tests/test_mcp_instructions_section.py tests/test_plugins.py tests/test_event_contract.py \
    tests/test_kernel_tool_timeout.py
...
1 failed, 132 passed, 5 warnings in 13.36s
FAILED tests/test_plugins.py::test_install_local_copies_into_user_dir - PermissionError (incoming.replace(target))
```

该失败为 Windows 满载 rename 偶发，隔离复跑 3 次全过（判定标准按 W4-SESSION）：

```text
$ python -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-rerun1 tests/test_plugins.py::test_install_local_copies_into_user_dir
1 passed, 5 warnings in 2.51s     # rerun2 同样 1 passed 2.42s；rerun3 1 passed 2.51s
```

X10 预存失败修复后：

```text
$ python -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest tests/test_plugin_manager_tools.py
7 passed, 5 warnings in 2.42s
```

（修复前该文件 2 failed：`execute_plugin_manager_tool() got an unexpected keyword argument 'permission_mode'` —— 测试钉住了 X10 的 danger-full-access/read_only 契约而实现缺参，基线 ec0a9d47 即如此。）

产品面回归（memory + ACP + 插件 + event contract + dashboard/projects）：

```text
$ python -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-reg \
    tests/test_memory.py tests/test_app_server_acp.py tests/test_plugin_manager_tools.py \
    tests/test_plugin_reload_idempotent.py tests/test_plugin_disable_withdraws.py \
    tests/test_event_contract.py tests/test_dashboard.py tests/test_projects.py
69 passed, 5 warnings in 8.35s
```

已知预存失败（未修未弱化，与本批改动无关）：`test_mcp_lifecycle_shutdown.py` 3 项（真实 stdio 生命周期）在本分支复跑仍 3 failed；GBK 中文乱码的 `test_installed_plugin_crosses_real_runtime_paths` 见 RESULT3-X5。

loop.py 改动按 AGENTS.md §6 做 AST 父链核验：

```text
assign adapter_mode 3486 -> If:3462 < AsyncFunctionDef:3090
call execute_plugin_manager_tool 3490 -> If:3462 < AsyncFunctionDef:3090
```

## 真实回合证据（原样输出）

### 通道冒烟（8885）

```text
$ python scripts/w4z5_live_check.py 8885 "Reply with exactly the word: OK" --workspace D:/Atlas/.worktrees/w4-z5/.tmp/w4z5-workspace
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 8885, "uncached_input_tokens": 8117, "output_tokens": 2, "cached_input_tokens": 768, ...}}
[reply] 'OK'
[result] terminal=run.completed chars=2
```

### X10+X2+X3 插件生命周期回合（full_access 默认权限）

提示词要求模型只用插件管理工具执行 list → get → disable → 直调被禁 MCP 工具 → enable。真实回复（节选，全文在 `.tmp/live-X10-X2-X3.log`）：

```text
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 117171, ..., "request_count": 11, ...}}
[reply] '...插件生命周期验证完成，五步全部用专用插件工具执行，插件已恢复为启用状态。
1. **list_plugins** — 只发现一个插件：`w4z5-evidence`（W4Z5 Evidence Plugin，1.0.0，source=local，enabled=true，loaded=true）。
2. **get_plugin** — `mcp_servers` 字段原样为：`["w4z5-evidence"]`。
3. **disable** — `applied` = `true`，`restart_required` = `false`，`load_report` = `{"loaded": [], "skipped": [{"name": "w4z5-evidence", "reason": "disabled"}], "errors": {}, "capabilities_removed": 0, "hooks_cleared": 0}`。
4. **禁用状态下调用** — 工具已从注册表消失（tool_search 返回"没有匹配的已安装工具"）；直接调用返回 `is_error: true`，内容为 `Unknown tool: w4z5-evidence__evidence_ping`，`error_category: tool`。
5. **enable** — `applied` = `true`（`load_report` 为 `{"loaded": ["w4z5-evidence"], "skipped": [], "errors": {}}`）；随后 get_plugin 复核确认 `enabled: true`、`loaded: true`。'
[result] terminal=run.completed chars=1267
```

run journal（`data/logs/runs/2026-11-14/a09dbfae-….jsonl`）中 9 次工具结果全部 `is_error: false`，包括两次 `set_plugin_enabled` 与一次对已禁用工具的 `Unknown tool` 调用。

### X10 逐次审批腿（`permission_preset=ask`）

```text
$ python scripts/w4z5_live_check.py 8885 "…disable 然后 enable w4z5-evidence…" --permission-preset ask
[event] approval.required tool=set_plugin_enabled waiting
[event] approval.responded
[event] approval.required tool=set_plugin_enabled waiting
[event] approval.responded
...
[reply] '步骤 1 — 禁用…applied: true, restart_required: false, load_report.skipped: [{"name": "w4z5-evidence", "reason": "disabled"}]…步骤 2 — 启用…load_report.loaded: ["w4z5-evidence"]…APPROVAL_FLOW_DONE'
[result] terminal=run.completed chars=594
```

（对比腿：默认 full_access 回合同样两次写操作**没有** approval 事件，直接生效 —— `approval_required` 计数为 0，即 danger-full-access 免审批语义。）

### X21 MCP instructions 独立 prompt 段

live HTTP（模型看到的工具描述 = 短指针，无 instructions 内联）：

```text
$ curl -s http://127.0.0.1:8885/api/tools | …
{"name": "w4z5-evidence__evidence_ping", "description": "See the `MCP server: w4z5-evidence` prompt section for this server's instructions (untrusted server content; follow Atlas policy).\n\nTool description:\nW4Z5 evidence probe; returns PONG_W4Z5.", "server": "w4z5-evidence", ...}
```

真实回合要求模型逐字引用段落与描述（`.tmp/live-X21.log`）：

```text
[reply] '…**1. 'MCP server instructions' 块里覆盖 w4z5-evidence 的第一句**（逐字）：
> ANCHOR_W4Z5: this guidance block is published by the w4z5-evidence MCP server.
**2. `w4z5-evidence__evidence_ping` 的说明**（逐字…）：
> See the `MCP server: w4z5-evidence` prompt section for this server's instructions (untrusted server content; follow Atlas policy).
> Tool description:
> W4Z5 evidence probe; returns PONG_W4Z5.
…INSTRUCTIONS_SECTION_DONE'
[terminal] run.completed model=deepseek-v4.1-flash request_count=9
```

ANCHOR_W4Z5 标记只存在于 MCP instructions（发布于 `w4z5_evidence_mcp_server.py` 的 `Server(instructions=…)`）；模型从上下文里逐字引用它 = 该独立段进了模型；工具描述为指针且不含标记 = 不内联成立。后端启动日志亦记录 `mcp.server_ready {"server": "w4z5-evidence", "tools": ["evidence_ping"]}`。

### X4 配置层预览（HTTP + CLI）

```text
$ curl -s "http://127.0.0.1:8885/api/plugins/config-layers?profile=w4z5&bundle=w4z5pack"
{"profile": {"row:tool.terminal": {"cmd": "bash"}, "instructions": {"text": "be brief"}},
 "bundle":  {"row:tool.terminal": {"cmd": "pwsh"}, "row:tool.browser": {"enabled": true}},
 "patches": {"row:tool.terminal": {"cmd": "nu"}},
 "merged":  {"tool.terminal": {"cmd": "nu"}, "instructions": {"text": "be brief"}, "tool.browser": {"enabled": true}}}

$ python -m atlas.cli plugins dump-config --profile w4z5 --bundle w4z5pack
（同样输出；merged.tool.terminal 经 profile→bundle→patch 三层 row-id 替换为 nu）
```

route 测试 4 项含 scrub 断言（`sk-` 形状密钥不回显）。

### X11 bundle 清单字段（live）

```text
$ curl -s http://127.0.0.1:8885/api/plugins
{"plugins":[{"name":"w4z5-evidence",…,"source":"local","official":null,"official_attestation":null,
"availability":{"available":true,"reason":"plugin manifest discovered"},"installed":true,
"overrides":[…],"marketplace":null,…,"update_available":false,"update_error":"",
"capability_groups":[…]}]}
```

单测覆盖：`test_plugins.py` 对 `official_attestation`（True/None 两态）、`availability`、`overrides`（含 row_id/order/note）逐一断言（:81-118）。

### X9/X24/X8 ACP stdio 全方法驱动（真实模型）

```text
$ python scripts/w4z5_acp_check.py --workspace …/w4z5-workspace --home …/live-profile \
    --first-prompt "Reply with exactly the word: OK2" --second-prompt "Reply with exactly the word: RESUMED2"
== negative: unknown agent preset ==
    [unknown-agent-preset] error.code=-32602 message='unknown agent preset: does-not-exist-w4z5'
== negative: unknown permission preset ==
    [unknown-permission-preset] error.code=-32602 message=unknown permission preset: not-a-preset
== negative: per-session MCP injection is rejected ==
    [mcp-injection-rejected] error.code=-32602 message=Per-session ACP MCP server injection is unavailable; use an empty mcpServers list.
== session/new with valid presets ==
    sessionId=2e9e8476-…            # agentPresetId=w4z5-restricted + permissionPreset=ask 均通过校验并 resolve
== session/prompt (real model) ==
<-- notify session/update {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "OK2"}}}
    stopReason=end_turn
== session/list ==
    listed=2 first=[{"sessionId": "2e9e8476-…", "cwd": "…w4z5-workspace", "title": "Atlas app-server", "updatedAt": "2026-11-14 09:30:09"}]
== session/set_config_option ==
    currentValue=observe
== session/resume ==
    resumed configOptions.currentValue=observe
== session/prompt after resume (real model) ==
<-- notify session/update {"update": {"sessionUpdate": "agent_message_chunk", …"RES"}} {"…"UM"}} {"…"ED"}}
    stopReason=end_turn
== session/cancel (no active run) ==
<-- id=w4z5-11 {"cancelled": false}
== session/close ==
<-- id=w4z5-12 {}
[result] failures=[]
```

`session/list` 首跑返回 0 条 —— 真 bug：`MemoryStore.list_conversations` 的 SELECT 漏了 `metadata` 列，ACP 会话标记永远读不到（单测的假 memory 掩盖了它）。补列后 live listed=2。元数据落库实查：

```text
sqlite> select id, metadata from conversations …
f19ace55 | {"acp": {"agentPresetId": "w4z5-restricted", "permissionPreset": "ask"}} | 2026-11-14 09:28:51
```

### X8 受限 preset 的工具池对照（durable journal 实录）

default preset（allow_all）会话的 `model_request_envelope`：

```text
envelope tool_names: ['AskUserQuestion', 'ask_user', 'build_repo_map', 'concludeTurn', 'glob', 'grep',
 'lsp_diagnostics', 'memory_search', 'memory_supersede', 'read_terminal', 'request_user_input',
 'run_checks', 'session_search', 'todo_list', 'tool_search', 'update_plan', 'view_image', 'workflow']   # 18 个
```

`w4z5-restricted` preset（allow=[local_exec, tool_search], mcp_servers=[], plugins=[]）会话的 envelope：

```text
envelope tool_names: ['concludeTurn', 'tool_search']    # 2 个 —— tools.allow 交集生效
```

即 revision 化 agent preset 在真实模型回合里实际收窄了模型可见工具面（`run_phases._apply_agent_preset_capabilities` → `intersect_tool_allow`；`mcp_servers` 限制由 loop.py:95 的 `runtime.mcp_server_allow` 消费）。

## 残留与定性

- **X8 PARTIAL**：`runtime.plugin_realm = PluginRealm(…)` 已接线（run_phases.py:351）但全仓库无消费者（`grep plugin_realm` 仅此一处）——子插件行隔离未贯穿模型工具消费链，RESULT3-X5 的判定不变。`resolve_versioned` 同样无调用方。两者接通才算 CLOSED；本批不做新消费链。
- **X24 PARTIAL**：7 个 session 方法 + fail-closed ACP 权限 + configOptions 全部 live 成立；`session/new` 的 per-session MCP 注入按 DSH 语义要求注入任意 stdio server，Atlas 缺少"非配置来源的 MCP server 进程编排"（MCPClient 只从 atlas.toml 起 server），属新底层原语，当前显式 `-32602` 拒绝并在错误信息里说明。
- **X27 PARTIAL（未动）**：本批范围是扩展层后端面；X27 的 application 级 slots/client 插件是桌面端工程（vitest/TS 标准也不同于 X 区），账本维持 W3-X5 结论，未在本批重开。
- 环境事实（给后续批次）：PowerShell Start-Process 需先去重大小写冲突的代理变量（`HTTP_PROXY/http_proxy`、`NO_PROXY/no_proxy` 同现会 `ArgumentException`）；`AgentPresetStore` root 是 `db_path.parent`（即 `data/`），不是仓库根。

## 账本更新

`docs/parity/DSH-GAP-LEDGER.md` 中 X2/X3/X4/X9/X10/X11/X21 已按本批证据改为 ✅ CLOSED（X4 含新暴露面），X8/X24 保持 PARTIAL 并更新现状列（live 证据 + 精确残留），X27 维持 W3 结论。commit 见 wave4-z5 分支。
