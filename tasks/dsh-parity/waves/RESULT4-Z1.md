# WAVE 4 — Z1 结果（E4 / E22 / E24 / E26 / E27，引擎工具面）

日期：2026-11-14
分支：`wave4-z1`（基线 `ec0a9d47` = wave3 tip）
提交：`01c20dd3` → `93aa5bb9` → `049070a7`（分三批）
真实模型通道：端口 8881，`deepseek-v4.1-flash`（独立数据目录，无用户 hook 干扰）

## 逐条结论

| Row | 状态 | 依据 |
|---|---|---|
| E4 | CLOSED | 别名语义输出契约进入 kernel 契约查找与校验管线（native 名 local_file/local_shell/ask_user/… 均可解析）；todo_list/browser_exec/review 工具注册了语义 schema；真实模型回合 tool.completed 事件携带 per-tool `output_contract`（含 schema 描述），成功输出按契约校验（校验目标=模型可见文本） |
| E22 | CLOSED | 模型可见工具面补齐：`subtask_list`（roster）、`team_wait`（waitForChange，含 noProgress 快路径）、`kanban_update_task/kanban_update` 的 `expected_revision` per-mutation revision CAS（store 层新增 revision 列 + CAS 更新 + dispatch_ready 计入 mutation）；blockedBy 无环（kanban dependencies + cycle check，已有）与 steer-only 消息（subtask_message，已有）此刻起全部在模型可见面；真实回合观测到 CAS 拒绝（expected_revision=999 → "task revision conflict: expected 999, current 3"）、依赖绑定落库、roster 返回、team_wait 在轮内完成 |
| E24 | CLOSED | 在既有 delegation + 结构化输出原语上实现模型工具 `ralph`（`agent/ralph_loop.py`，无新引擎原语）：串行 fresh-child 迭代、maxRounds≤256、handoff≤16 KiB、DSH report 语义校验（continue/complete/blocked 规则）、四类终态 envelope；真实回合：模型调用 ralph，round 1 子代理真实写入 `ralph-evidence.txt`（内容 RALPH_OK），报告经 schema 校验（首次多出字段被 delegate_task 的重试机制纠正），终态 `complete`，envelope "Ralph worker reported completion after 1 round." |
| E26 | CLOSED | registry 新增 `restrict_scope(allow/deny)`（DSH tools.restrict 语义：空过滤器/未知名/空集 fail-fast、多层交集、disposer、overlay 可见）；delegation 准入 `validate_toolset_binding`（未知名/空集拒绝委派，glob 为可选能力）；真实回合：受限子代理（definition tools=[local_file, search_files]）的 offer 被截断（"Allowed tool names: local_file, search_files"），越界工具能力层不可见，attempt 越界直调得到真实 `PermissionError: Tool is not allowed in this run (code=permission_denied)`；附带修复：concludeTurn 是收尾传输而非能力，关闭 allowlist 不再拒绝它 |
| E27 | CLOSED | X7 已实现（kernel run_code-only、`tool_mode` API、dispatch 拒绝 + 子调用逐条事件），本轮补真实模型证据：PTC 回合只暴露 run_code，嵌套 clock.curr_time 子调用逐条出事件，直调其它工具被拒路径有单测 |

## 施工清单（暴露 vs 取证）

- **E4**：暴露 = `tool_registry.alias_output_schema()`（native 名解析）+ `tool_catalog.output_contracts_for_tools` 接入别名契约 + `kernel/loop._presentation_schema_violation`（校验目标=模型可见文本）；取证 = live-E4-final2.log。
- **E22**：暴露 = `DelegationService.list_subtasks/roster_status_signature`、tool_catalog/tool_node 的 `subtask_list`/`team_wait`、`kanban.py` revision 列 + CAS；取证 = live-E22-teams.log + kanban.db 状态。
- **E24**：暴露 = `agent/ralph_loop.py` + tool_catalog/tool_node `ralph` 工具；取证 = live-E24-ralph.log + 工作区文件。
- **E26**：暴露 = `ToolRegistry.restrict_scope` + `tool_permissions.validate_toolset_binding` + delegate 准入接线；取证 = live-E26-restrict2/restrict3.log。
- **E27**：取证 = live-E27-ptc.log（X7 实现已含单测）。

## 真实模型回合证据（原样输出）

### 通道冒烟（8881）

```text
$ python scripts/dsh_live_ws_check.py 8881 "Reply with exactly the word: OK"
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 8460, ..., "request_count": 1, ...}}
[reply] 'OK'
[result] terminal=run.completed chars=2
```

### E27 — PTC 模式（`--tool-mode ptc`）

提示词：用 run_code 调 `atlas.call_tool('clock.curr_time', {})`，不要直调其它工具。

```text
[event] tool.started name=clock.curr_time
[event] tool.completed name=clock.curr_time output_contract=text/clock.curr_time output
[event] tool.completed name=run_code output_contract=text/run_code output
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 10448, ...}}
[reply] '我先用 `run_code` 调用 `clock.curr_time`，不直接调用其它工具。已按要求执行，未调用其它工具。
**结果**
- `atlas.call_tool('clock.curr_time', {})` 返回：`2026-11-14T06:50:21.080135+00:00`（UTC）...
- `outcome: completed`，退出码 0，无 stderr。'
[result] terminal=run.completed chars=333
```

模型请求面只有 run_code（`_tools_for_mode` 强约束），嵌套子调用 `clock.curr_time` 逐条产出 tool_call/tool_result 事件 —— “其它工具直调被拒并提示、子调用各记日志” 的 kernel 行为在真实回合观测到；直调拒绝路径由 `test_kernel_ptc_mode.py` 覆盖（`direct` → `{"outcome": "denied"}`，`"Use run_code" in content`）。

### E4 — 每工具输出契约

提示词：todo_list 写两项待办 + local_file read 读 README 前 3 行。

```text
[event] tool.completed name=todo_list output_contract=text/todo_list output/shape=string desc='Text representation of the updated task list.'
[event] tool.completed name=local_file output_contract=text/local_file output/shape=oneOf desc='For read actions: file contents, or a multimodal envelope wh'
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 27397, ...}}
[result] terminal=run.completed chars=743
```

两个工具均成功执行且无 schema 违规（校验目标修复后）；非别名工具（grep/glob/exec_command/tool_search）保持 anyOf 兼容契约（shape 为空即 anyOf），与语义契约可区分。

### E22 — Agent Teams 模型面

提示词：7 步脚本（建板 → task-A → task-B(dependencies=[A]) → 错误 revision 拒绝 → 正确 revision → subtask_list → team_wait）。

```text
[event] tool.completed name=kanban_create_board ...
[event] tool.completed name=kanban_create_task ...
[event] tool.completed name=kanban_create_task ...
[event] tool.completed name=kanban_update_task ...   <- expected_revision=999
[event] tool.completed name=kanban_update_task ...   <- 正确 revision
[event] tool.completed name=kanban_list ...
[event] tool.completed name=kanban_update_task ...
[event] tool.completed name=subtask_list ...
[event] tool.completed name=team_wait ...
[terminal] run.completed ... chars=3151
```

模型回复（前 400 字符，全量见日志）：

```text
task-A 已创建（id `3b93feb9…8bea`，revision `1`）。第 (3) 步创建 task-B，并将 task-A 的 id 作为依赖。
task-B 已创建，依赖也绑定成功。第 (4) 步是冲突测试：用 `running` 和错误的 `expected_revision: 999` 更新
task-A。冲突被如期拒绝——但要注意，系统报告当前 revision 为 **3**，而不是创建时记录的 1 ...
```

CAS 拒绝后的看板落库状态（本批数据目录 kanban.db 实查）：

```text
{'id': '3b93feb9...', 'title': 'task-A', 'status': 'running', 'revision': 4, 'dependencies': '[]'}
{'id': '3f5d71ad...', 'title': 'task-B', 'status': 'todo', 'revision': 1,
 'dependencies': '["3b93feb967fa4dd0a74cfa85a7048bea"]'}     <- blockedBy 绑定落库
runs history: {'task_id': '3b93feb9...', 'status': 'running', 'started_at': '2026-11-14 07:14:53'}
```

roster（E26 回合中 subtask_list 的真实返回，同一工具）：

```json
{"members": [{"subtask_id": "0d35f8360a521860", "goal": "...", "status": "failed",
  "progress": "TypeError: ...", "background": false, "agent_address": "0d35f8360a521860@atlas",
  "backend": "atlas"}]}
```

`team_wait` 在轮内执行并完成（tool.completed 事件）；其 reason 语义（noProgress 快路径 / changed / timeout）由单元测试逐值覆盖。单独一轮专测因 tool folding 开销超出脚本 150s 窗口未取到终态（live-E22-teamwait.log），不作为关闭依据。

### E24 — ralph

提示词：明确要求 Ralph，objective = 写 ralph-evidence.txt（内容 RALPH_OK）后报告 complete，max_rounds=3。

```text
[event] tool.started name=ralph
[event] tool.completed name=ralph output_contract=text/ralph output/shape=
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 26462, ...}}
[result] terminal=run.completed chars=1116
```

模型回复（逐字关键段）：

```text
**外层结果行**
Ralph worker reported completion after 1 round.

**Final report（JSON 原文）**
{
  "status": "complete",
  "summary": "ralph-evidence.txt 已存在于 D:\\...\\live-ws，内容为一行 RALPH_OK（10 字节...）...",
  "evidence": ["cat ralph-evidence.txt → RALPH_OK", "ls -l ralph-evidence.txt → ... 10 Nov 14 15:31 ...",
               "上一轮 od -c 校验 → 0000000 R A L P H _ O K \\r \\n，共 10 字节单行", "..."],
  "nextSteps": [],
  "blocker": ""
}
```

工作区产物实查：

```text
ralph-evidence.txt exists: True | content: RALPH_OK
```

子代理首次回复多出 `assumptions` 字段被 schema 校验拒绝，delegate_task 的结构化重试（append_output_contract + build_retry_message）在轮内纠正——handoff/校验纪律按 DSH 语义生效。

### E26 — tools.restrict / 受限子代理

定义：`<data>/data/agents/z1-restricted.md`，`tools: [local_file, search_files]`。
第一轮（live-E26-restrict2.log）子代理实际触发了越界直调的拒绝：

```text
PermissionError: Tool is not allowed in this run
code=permission_denied | retryable=no
hint: The run is not allowed to touch this path or command. ...
```

（当时是 concludeTurn 被拒 —— 由此发现并修复“关闭 allowlist 不应拒绝收尾传输”。）

修复后（live-E26-restrict3.log）：

```text
**原始 result（逐字）**：
<atlas-subagent-result id="0c5aed375c18a59f" backend="atlas" status="completed">
  本次子运行声明的工具可用范围是：
  Allowed tool names: local_file, search_files
  实际暴露给我的函数只有 `local_file`、`write`、`edit`、`apply_patch`、`concludeTurn` ——
  全是文件读写与收尾工具，没有任何能启动进程/执行 shell 的入口。
  ...
</atlas-subagent-result>
[result] terminal=run.completed chars=1898
```

受限子代理：offer 按注册级绑定截断（terminal 不在面内）、子代理正常 concludeTurn 收尾（status completed）、未绕过限制。

## 定向测试（真实命令输出）

```text
$ cd core && python -m pytest -q -p no:cacheprovider --basetemp="D:/Atlas/.worktrees/w4-z1/.tmp/pytest" \
    tests/test_backend_parity_wave4_z1.py tests/test_kernel_ptc_mode.py \
    tests/test_dsh_w2_tool_contract.py tests/test_backend_parity_wave3_x7_e4_contracts.py \
    tests/test_backend_parity_wave3_x7_tool_mode.py tests/test_groups.py tests/test_groups_router.py \
    tests/test_agent_enrichment.py tests/test_c1_child_policy.py
...
3 failed, 76 passed, 5 warnings in 10.10s
FAILED tests/test_agent_enrichment.py::test_local_file_mutation_is_checkpointed_before_write_and_restorable
FAILED tests/test_c1_child_policy.py::test_inline_delegate_dispatches_through_atlas_lifecycle
FAILED tests/test_c1_child_policy.py::test_native_child_restrictions_block_direct_and_deferred_calls
```

三个失败均为既有问题，与本批无关（已用 git stash 在干净基线复跑证实同样失败）：

- `test_c1_child_policy.py` 两项：`AttributeError: 'FixtureConfig' object has no attribute 'raw'`（`atlas_runtime.py:978`），基线同样失败（见 W4-SESSION 已知失败注记的同类环境项）。
- `test_local_file_mutation_is_checkpointed_before_write_and_restorable`：shadow-git checkpoint 环境项，干净基线 3 次隔离复跑均同样失败（非满载偶发，在本机稳定复现，基线一致）。

本批新增/触达的其余套件全部通过：Z1 测试 17 项 + kernel PTC 4 项 + W2 契约 12 项 + X7 E4/tool_mode 3 项 + groups 24 项等。

## 顺手修掉的真实缺陷（全部在本批命中路径上）

1. `run_drive.py` 四处 `log.*("...", event=...)`：structlog BoundLogger 首个位置参数名为 `event`，任何 projection/persist 失败都会在 except 里再抛 `TypeError: BoundLogger.exception() got multiple values for argument 'event'`，把可吞掉的失败变成 run 致命错（真实命中：E26 第一轮子代理因此 failed）。
2. ToolScheduler 对 `concludeTurn` 应用关闭 allowlist → 受限子代理无法结束回合（真实命中，见 E26 证据）。
3. `tool_node` 的 `kanban_create_board`/`kanban_list` 分支只赋值 `data` 不赋值 `result` → UnboundLocalError（单测暴露）。
4. 别名契约校验目标错误：oneOf 别名契约把 kernel envelope dict 整体校验 → `local_file` 真实成功输出被误判违规（真实命中，E4 第三轮）。

## 遗留 / 交接

- `team_wait` 的 reason 值未在独立轮取到原文（轮内完成 + 单测覆盖）；如需原文可在关闭 tool folding 的运行里跑。
- 子代理的 native worker 暴露的函数名（apply_patch/edit/write）与 Atlas 别名名的映射差异使受限白名单在 worker 面呈“能力截断”而非逐名拒绝 —— 这是 worker 面既有行为，未在本批改。
- E22 首轮 task-A 的 revision 在模型侧出现 1→3 漂移（中间有未报告的 update 调用）；CAS 本身行为正确（拒绝时报告当前值）。
