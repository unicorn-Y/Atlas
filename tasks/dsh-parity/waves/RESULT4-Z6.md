# RESULT4-Z6（扩展+桌面批：X12 X13 X15 X18 X19 X20 X25 X26 X30 X31 X32 X33）

分支：`wave4-z6`（基线 ec0a9d47）。工作目录：`D:\Atlas\.worktrees\w4-z6`。
真实模型端口：**8886**（隔离数据目录 `D:\Atlas\.worktrees\w4-z6\.tmp\live`，隔离
USERPROFILE/HOME/APPDATA + 空 `~/.codex/hooks.json`；模型 `deepseek-v4.1-flash` @ d1api.xin，
keyring 取 key，Clash `http://127.0.0.1:7897` 走 `http_proxy/https_proxy` 环境变量）。

提交：
- `a3fb1dc5` X25：app_server `session/wait` + `shutdown` + `session/status`（暴露）
- `e13016ed` X32：introspect `config.provenance` 逐层来源（暴露）
- `4f321858` X18：introspect `skills.sources` 发现根阶梯 + `with_sources` 分层单测（暴露）
- `38290658` X31：automation conversation_id 绑定贯通单测
- `77450e29` X30：loopback asyncssh 真实 SSH wire 取证测试
- 本次：RESULT + 账本更新

## 单元测试（真实命令输出）

```
> python -m pytest tests/test_app_server_sdk_lifecycle.py tests/test_app_server_acp.py \
    tests/test_introspect_config_provenance.py tests/test_introspect_skill_sources.py \
    tests/test_skill_provider_observation.py tests/test_skills_hot_reload.py \
    tests/test_codex_plugin_hooks.py tests/test_hook_bus_modes.py tests/test_c4_hooks.py \
    tests/test_event_contract.py tests/test_ssh_execution_world.py -q -p no:cacheprovider \
    --basetemp=D:/Atlas/.worktrees/w4-z6/.tmp/pytest
83 passed, 5 warnings, 2 errors in 18.17s
```

2 个 error 是**既有环境问题**，不是本批回归：`test_c4_hooks.py` 两个用例的 fixture 走
`atlas/office.py:115` → `ModuleNotFoundError: No module named 'openpyxl'`（可选 office 依赖未装）。

```
> python -m pytest tests/test_automation_engine.py tests/test_skill_discovery.py \
    tests/test_skill_discovery_catalog.py tests/test_agent_skill_model_invocation.py \
    tests/test_skill_lifecycle.py -q ...
42 passed, 12 deselected, 5 warnings in 12.62s

> python -m pytest tests/test_backend_parity_wave7.py -q ...   # agent definitions 多格式发现
11 passed, 5 warnings in 23.58s

> python -m pytest tests/test_subagent_capacity.py tests/test_dsh_w4_goal_subagent.py -q ...
3 passed, 5 warnings in 3.08s

> python -m pytest tests/test_automation_engine.py::test_agent_turn_conversation_binding_reaches_dispatch_and_receipt -q ...
1 passed, 5 warnings in 7.98s
```

既有预存失败（未修未弱化，引用即可）：GBK 中文乱码断言、`test_mcp_lifecycle_shutdown.py`
3 项真实 stdio 生命周期（见 RESULT3-X5）。

## 逐行结论

| Row | 结论 | 依据 |
|---|---|---|
| X12 | ✅ CLOSED (W4-Z6) | 单测（hook_bus_modes/c4_hooks 部分）+ 真实回合：PreToolUse deny 拦截 local_exec，`hook.ran` 事件在列，模型报告了 hook 原文理由 |
| X13 | ✅ CLOSED (W4-Z6) | `codex:project:`/`codex:user:` 源身份 + fail-closed trust 单测已有（`test_codex_plugin_hooks.py` 4 项全过）；真实回合：codex 项目 hook 执行、输出进会话上下文、模型回显 token；`hook.ran` 事件帧含 `source=codex:project:...codex/hooks.json` |
| X15 | ✅ CLOSED (W4-Z6) | 真实回合双源同名技能：claude-project(30) 胜 claude-user(20)；`skills.sources` 实时列出生效阶梯 |
| X18 | PARTIAL (W4-Z6) | 新暴露 `skills.sources`（live 数据见下）+ `with_sources` 请求作用域分层单测；`list/get`+`handle_change("skills/change")` 契约与不完整观察重试已有单测。仍缺：异步 provider 协议、按 scope 链 keyed 的发现缓存 |
| X19 | ✅ CLOSED (W4-Z6) | 读路径 `_ensure_fresh`（mtime_ns+size 指纹）单测已有（`test_skills_hot_reload.py`）；真实回合：SKILL.md 会话中途编辑、下一次运行即见新 token。DSH 的 chokidar 常驻 watcher 是实现差异，可观测行为（重启外即时生效）已实证 |
| X20 | ✅ CLOSED (W4-Z6)（PRESENT-STRONGER 保持） | 真实回合：`run.failed`，detail=`skill dependencies block activation: mcp_servers:nonexistent-z6-mcp (missing)`；未为对齐退化 |
| X25 | ✅ CLOSED (W4-Z6) | 新增 `session/wait`/`shutdown`/`session.status`（5 项单测）；真实 stdio 全生命周期（见下）。残余差异如实记录：`session/prompt` 仍是阻塞式完成回执（DSH 是 durable enqueue receipt），无 working-directory get/set、无 subagent.started/finished 通知 |
| X26 | HARD (W4-Z6) | 生成层不存在，见下 sweep |
| X30 | PARTIAL (W4-Z6) | loopback asyncssh 真实 SSH wire：exec 通道、OS 探测、SFTP write/read/list、remote exec cwd、remote edit fail-closed 全过（4 项单测）。"fs/subprocess/sandbox 整体搬上 SSH"仍缺——这是新原语，本轮禁建 |
| X31 | ✅ CLOSED (W4-Z6) | 单测：payload.conversation_id 贯通 dispatch 与 receipt、缺省回退 synthetic；真实 date 触发：到期 run 落进绑定会话（见下） |
| X32 | ✅ CLOSED (W4-Z6) | 新增 `config.provenance` 逐层来源（10 项单测）；live 查询见下。`plugins dump-config`（profile→bundle→patch 层）CLI 此前已有 |
| X33 | ✅ CLOSED (W4-Z6) | 真实 delegate 回合：`delegate_task` → 子任务 `a537327c046bf21b`、`backend="atlas"`，子回答以 `Z6REVIEWERMETA` 开头（workspace `.claude/agents/z6-reviewer.md` 定义经多格式发现生效）；`test_backend_parity_wave7.py` 11 项过 |

## 真实模型取证（8886，输出原样）

### 后端与隔离环境

```
> powershell Start-Process ... launch_z6.ps1   # ATLAS_DATA_DIR/USERPROFILE/HOME/APPDATA 重定向
> GET http://127.0.0.1:8886/api/health -> 200
> GET /api/hooks/trust?workspace=D:\Atlas\.worktrees\w4-z6\.tmp\live\workspace
claude-ddd2e85b462666c259d7 | PreToolUse | claude:project:...\.claude\settings.json | unreviewed | python hooks/claude_deny_local_exec.py
codex-e273f1a1b4a6e06b38c7  | SessionStart | codex:project:...\.codex\hooks.json | unreviewed | python hooks/codex_session_context.py
> PUT /api/hooks/{id}/trust ×2 -> trust_state=approved trusted=True（两条源身份各自审批）
```

注：首次启动失败过一次（`ModelCallError: 模型代理凭据缺失`）——隔离 user-settings 复制了
`model_network.proxy_configured=true` 但凭据库无对应条目；改为剥离 `model_network`、走
env 代理（system_proxy/trust_env）后重启成功。通道本身（d1api+keyring key）从未失效。

### 回合 1（X13 + X12）：codex SessionStart hook 上下文注入

```
prompt: "A SessionStart hook placed a probe token into your session context. Reply with ONLY the value of CODEX_PROBE_TOKEN, nothing else."
[event] hook.ran
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 7997, "uncached_input_tokens": 7997, "output_tokens": 520, ...}}
[reply] 'z6codex-a77b4c'
[result] terminal=run.completed chars=14
```

token 来自 `workspace/.codex/hooks.json`（`codex:project:` 源）SessionStart hook 的 stdout
——经 HookBus 桥接为会话上下文，真实模型读到并回显。

### 回合 2（X12）：Claude PreToolUse hook 拦截工具

```
prompt: "Use the local_exec tool to run the command 'echo z6toolprobe'. If a hook blocks the tool, tell me the exact block reason and stop."
[event] tool.preparing name=local_exec
[event] tool.started name=local_exec
[event] hook.ran
[event] tool.completed name=local_exec output_contract=text/local_exec output
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", ...}
[reply] 'Running the probe with local_exec now.Blocked — stopping as instructed.

**Exact block reason returned by the tool:**
```
PermissionError: z6-claude-hook: local_exec denied
code=permission_denied | retryable=no
...
```
`local_exec` was denied before the command ran (`echo ...'
```

Claude `settings.json` PreToolUse hook（`permissionDecision: deny`）在执行前拦截，模型收到
hook 原文理由。

### 回合 3（X15）：发现根阶梯——同名技能双源对决

workspace `.claude/skills/z6-skill`（claude-project，priority 30）说 Z6SKILLACTIVE；
live home `~/.claude/skills/z6-skill`（claude-user，priority 20）说 Z6USERSCOPE：

```
> python ws_driver.py 8886 "The active skill 'z6-skill' defines how you must answer..." --active_skills ["z6-skill"]
[event] hook.ran {"event": "SessionStart", "exit_code": 0, "source": "codex:project:...\.codex\hooks.json"}
[reply] 'Z6SKILLACTIVE'
[terminal] run.completed
```

高优先级的 project 源胜出（Z6USERSCOPE 未出现）。

### 回合 4（X19）：SKILL.md 会话中途编辑即时生效

```
# 无重启，直接编辑 workspace skill：Z6SKILLACTIVE -> Z6SKILLEDITED
> python ws_driver.py 8886 "...reply with only the token it specifies." --active_skills ["z6-skill"]
[event] hook.ran {"event": "SessionStart", "exit_code": 0, "source": "codex:project:..."}
[reply] 'Z6SKILLEDITED'
[terminal] run.completed
```

### 回合 5（X20）：依赖门阻断激活

```
> python ws_driver.py 8886 "Try to follow the active skill." --active_skills ["z6-dep-skill"]
[terminal] run.failed
[detail] skill dependencies block activation: mcp_servers:nonexistent-z6-mcp (missing)
```

（z6-dep-skill 的 frontmatter 声明依赖 MCP server `nonexistent-z6-mcp`。）

### 回合 6（X33）：delegate → workspace agent 定义

```
prompt: "Use the delegate tool exactly once to spawn a subtask with agent='z6-reviewer'..."
[event] tool.started {"name": "tool_search"}
[event] tool.started {"name": "delegate_task"}
[event] hook.ran {"event": "SessionStart", "exit_code": 0, "source": "codex:project:..."}
[reply] 'I'll first check whether a `delegate` tool is registered.
Found `delegate_task` (the delegate tool) — calling it once with the requested agent and goal.
Delegated once via `delegate_task` (agent `z6-reviewer`, status `completed`, subtask `a537327c046bf21b`).
Child's final answer, verbatim:

<atlas-subagent-result id="a537327c046bf21b" backend="atlas" status="completed">
  Z6REVIEWERMETA Review of `D:\...\.tmp\live\workspace`: this child run was given only file-mutation tools'
[terminal] run.completed
```

`.claude/agents/z6-reviewer.md`（claude 多格式发现）作为子代理 persona 生效——子回答以
定义里规定的 `Z6REVIEWERMETA` 开头，经 subagent provider 缝（`agents/backends/`）返回。

### X25：真实 stdio app-server 全生命周期（真实模型）

```
> python appserver_live.py
INIT: {"protocolVersion": 1, "serverInfo": {"name": "Atlas", "version": "0.1.0"}, "capabilities": {"tools": true, "sessions": true, "streaming": true, "approvals": true, "inputRequests": true}}
SESSION: 68362e66-58f4-4c2d-adfd-444d7aee6de6
PROMPT: {"session_id": "68362e66-...", "text": "Z6APPSERVEROK", "status": "completed"}
WAIT: {}
STATUS_ORDER: ['running', 'idle']
SHUTDOWN: {}
PROCESS_EXIT: 0
```

`session/prompt` 用真实模型（deepseek-v4.1-flash）完成；`session/wait` 返回 `{}`（settle
barrier）；`session/status` running→idle 转换按序投递；`shutdown` 回 `{}` 后优雅排空、进程退出 0。

### X31：date 触发的 automation 落回绑定会话

```
> POST /api/automations  {"id":"z6-schedule-bound","trigger":{"kind":"date","at":"<now+90s>"},
                          "payload":{"kind":"agent_turn","message":"Reply with exactly: Z6SCHEDULEBOUND",
                                     "conversation_id":"z6-schedule-target"}}
created: z6-schedule-bound | next_run_at: 2026-11-14T10:06:10+00:00

> GET /api/automations/z6-schedule-bound/runs
WORKFLOW: atlas-auto-run-z6-schedule-bound-8fcc9020b502 | status: SUCCESS | trigger: date
RESULT: {"run_id": "f880e4fba50443afa402ce1e524b831b", "automation_id": "z6-schedule-bound",
         "conversation_id": "z6-schedule-target", "status": "ok",
         "result": {"text": "Z6SCHEDULEBOUND", "conversation_id": "z6-schedule-target"}}

> GET /api/conversations/z6-schedule-target/messages?limit=10
user      | Reply with exactly: Z6SCHEDULEBOUND
assistant | Z6SCHEDULEBOUND
```

到期自动触发的 agent_turn 回到**配置的原会话**（非 synthetic `automation-<id>`），消息持久化在该会话。
（探针 automation 已 pause + DELETE 清理。）

### X18/X32：introspect 新方法 live 查询

```
> POST /api/introspect/query {"provider":"skills","method":"sources"}
{"count": 5, "sources": [
  {"name": "atlas",           "priority": 10, "layout": "category", "root": "...w4-z6\\skills",                      "exists": true,  "skill_md_count": 12},
  {"name": "library",         "priority": 11, "layout": "category", "root": "...live\\data\\library\\skills",        "exists": false, "skill_md_count": 0},
  {"name": "atlas-user",      "priority": 12, "layout": "category", "root": "...live\\home\\.atlas-skills",          "exists": false, "skill_md_count": 0},
  {"name": "claude-user",     "priority": 20, "layout": "flat",     "root": "...live\\home\\.claude\\skills",        "exists": true,  "skill_md_count": 1},
  {"name": "claude-project",  "priority": 30, "layout": "flat",     "root": "...live\\workspace\\.claude\\skills",   "exists": true,  "skill_md_count": 2}
]}

> POST /api/introspect/query {"provider":"config","method":"provenance","input":{"key":"server.port"}}
PROVENANCE server.port -> winner: atlas.toml | found: True | value: 8765
   request-override present= False
   session present= False （当前无会话上下文）
   project present= False （当前无项目上下文）
   expert-overlay present= False
   atlas.toml present= True 8765

> {"provider":"config","method":"provenance","input":{"key":"models.default"}}
   -> winner: atlas.toml | value: claude-sonnet-4
> {"provider":"config","method":"provenance","input":{"key":"gateway.base_url"}}
   -> found: False（隔离 env 未配置该键）
> {"provider":"config","method":"provenance","input":{"key":"models.custom.api_key"}}
   -> found: False（点号路径不寻址列表项；各层值一律过 scrub）
```

## X26 终判 HARD（取证 sweep）

DSH 目标：Typert API Gateway——`@Remote`/`@RemoteScope` 装饰器声明服务方法，构建期生成
Host/Client 描述符、编解码与客户端类型，经 Cordis `ctx.typert` 做对象↔wire-id 绑定。

Atlas 全仓 sweep（core/atlas、frontend/src、backend-adapter，*.py/*.ts/*.tsx）：

- `@Remote|RemoteScope|TypertLookupMap|bindTypertRemote|typert` → **0 命中**
- `openapi-ts|generate.*types|codegen` in frontend/package.json、backend-adapter/package.json → **0 命中**
- `gateway_gen|generate_client|descriptor` 生成器文件 → **0 命中**
- 唯一的 "remote" 是 `cli.py` 的 SSH remote-tasks 命令组（无关）；`gateway_service.py` 是
  channel→agent 桥（Wave-2 dispatcher seam），不是类型化 RPC 网关
- 现状契约机制仍是：手写 FastAPI router + 手写 TS adapter（backend-adapter/），契约靠人

结论：**HARD**——需要引入装饰器协议层 + 构建期 codegen + Cordis 式 lookup 绑定，属新原语，
W4 禁建。RESULT3-X5 的 NOT-DONE 判定维持成立。

## 环境残留清理

- 8886 uvicorn 及其子进程：已按 PID 逐个核对命令行后停止（只杀 `--port 8886` 匹配项）
- 探针 automation `z6-schedule-bound`：pause + DELETE 成功（带 conversation_policy=keep）
- pytest 残留：本批 basetemp `D:/Atlas/.worktrees/w4-z6/.tmp/pytest` 过滤核对，无残留进程
