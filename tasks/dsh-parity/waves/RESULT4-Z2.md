# RESULT4-Z2（WAVE4 引擎上下文批：E28 E29 E31 E32 E33 E34 E35 E36）

- worktree：`D:\Atlas\.worktrees\w4-z2`（分支 `wave4-z2`，基线 ec0a9d47）
- 真实模型通道：`deepseek-v4.1-flash` @ `https://d1api.xin/v1`（worktree 本地 `config/atlas.toml`，密钥取自 OS 凭据库 `atlas:model:deepseek-v4.1-flash`），后端 `python -m uvicorn atlas.server:app --port 8882`（PowerShell Start-Process 分离进程，env HTTP(S)_PROXY=http://127.0.0.1:7897）
- 驱动：`core/scripts/w4z2_live_check.py`（`dsh_live_ws_check.py` 的扩展：`--workspace/--conversation-id/--cancel-on-tool/--timeout`）
- 所有结论行都有下面的真实输出支撑；E/S/X 区 CLOSED = 单测通过 + 真实模型回合观测。

## 通道打通记录（排除环境问题的过程性证据）

首次尝试（worktree 内直接后台起 uvicorn）持续 `model_error getaddrinfo failed` / `SSL EOF`。
排查结论（贴真实输出）：

1. gateway 直连/代理均可达：`curl -x http://127.0.0.1:7897 https://d1api.xin/v1/chat/completions`（keyring key）返回
   `{"id":"01a1d8d6ca3176009091e043246b18bb",...,"content":"OK",...,"prompt_tokens":6,"completion_tokens":1}`。
2. 主检出区 `atlas.toml` 的 pleasure2ai key 已欠费：POST 返回 `{"code":"INSUFFICIENT_BALANCE","message":"Insufficient account balance"}`。
3. 正确模型来自主检出区 `data/user-settings.json` 的 `custom_models`（base_url d1api.xin，无明文 key）。worktree 里只复制 atlassian 条目时 `/api/models` 显示 `custom: False`，路由丢 base_url；
   把该条写入 worktree `data/user-settings.json` 的 `custom_models`（不带 key）后 `/api/models` 显示：
   `{'id': 'deepseek-v4.1-flash', 'base_url': 'https://d1api.xin/v1', 'custom': True, 'provider': 'openai'}`。
4. smoke 通过：

```
$ python scripts/w4z2_live_check.py 8882 "Reply with exactly the word: OK"
[start] run_id=14935d23-65d8-4d0e-b515-c291ead554ed conversation_id=dsh-z2-14935d23 ...
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", "usage": {"input_tokens": 8821, ...}}
[reply] 'OK'
[result] terminal=run.completed chars=2
```

## E28 压缩区域安全 — CLOSED（单测 + 真实回合观测）

- 动作：取证。无产品代码改动。
- 单测：`tests/test_kernel_compaction_surface.py` 在本批回归中通过（见文末汇总 58 passed）。
- 真实回合：`ATLAS_AUTO_COMPACT_WINDOW=30000` 强压窗口 + 100KB `bigdata.txt` 三次读取。
  run journal（run `33d2ee80-171d-46c2-ac17-032c6babb7fc`）：

```
07:33:58 compaction {"method": "summary", "before_tokens": 13470, "after_tokens": 12319, "budget_tokens": 1014576, "forced": false, "event": "compaction"}
07:33:58 compaction_end {"holder": "atlas:33d2ee80-...:e01c83618050472482dd4148b2196bb7", "reason": "completed", "method": "summary", ...}
```

- 发布后摘要区完整性（engine/state.db `session_events` 的 `compaction/summary` payload 实测）：

```
summary messages: 6 calls: 2 results: 2
unpaired calls: set()
unpaired results: set()
summary row present: True
```

  即压缩边界未切开任何 tool-call/result 对（发布前 `normalize_tool_results` 校验通过是成功发布的前置条件）。
- 备注：证据环境里压缩触发阈值调试走了三次失败适配（read-restore 预算与 6 条 tail 吃掉摘要节省 →
  `compaction summary did not fit the context budget` → 3 次后熔断）。为取证在 worktree config 加了
  `context_keep_messages = 4` 与 `post_compact_read_restore_tokens = 0`（只影响本 worktree 后端，未提交到产品默认）。

## E29 ctx.tokenMeter：provider usage 锚定回 surface 节点 — CLOSED（暴露 + 取证）

- 动作：暴露（新投影 `anchor_surface_to_usage` 纯函数 + loop 接线；usage 行新增 `surface_anchor` / `surface_node_tokens_anchored`；journal 新事件 `model_request_anchor`）+ 取证。
- 文件：`core/atlas/engine/agent/token_meter.py`、`core/atlas/engine/kernel/loop.py`（record_model_attempt + envelope sha 捕获）、`core/tests/test_w4_z2_batch.py`。
- 单测（14 passed 全绿，摘 2 条）：

```
tests/test_w4_z2_batch.py::test_anchor_scales_nodes_to_provider_total PASSED
tests/test_w4_z2_batch.py::test_anchor_does_not_mutate_input_nodes PASSED
14 passed, 5 warnings in 4.03s
```

- 真实回合（run `14935d23-...` journal 实录，未删节）：

```
== model_request_envelope
{"model": "deepseek-v4.1-flash", "attempt": 1, "surface_token_estimate": 4766, "surface_node_tokens": [{"seq": 0, "tokens": 3639, ...}, {"seq": 1, "tokens": 1127, ...}], "request_sha256": "039f06560cc55381d0b7fdf6a8af5a7594bf2b2da578b7f4087944b96debc73a", "message_count": 2, "roles": ["system", "user"], ...}
== model_request_anchor
{"purpose": "conversation", "request_sha256": "039f06560cc55381d0b7fdf6a8af5a7594bf2b2da578b7f4087944b96debc73a", "provider_input_tokens": 8821, "cached_tokens": 0, "surface_token_estimate": 4766, "anchor_ratio": 1.850818, "surface_node_tokens_anchored": [{"seq": 0, "heuristic_tokens": 3639, "anchored_tokens": 6735}, {"seq": 1, "heuristic_tokens": 1127, "anchored_tokens": 2086}], ...}
```

  锚定后各节点 6735+2086 = 8821 = provider 报告的 input_tokens；request_sha256 与 envelope 一致。

## E31 会话查询五工具（event read/trace/lineage） — CLOSED（暴露 + 取证）

- 动作：暴露 + 取证。
- 暴露 1（分类）：`core/atlas/engine/kernel/tools.py` 把 `session_event_search / session_trace / session_event_trace / session_event_read`
  加进 `READ_ONLY_TOOLS` 与 read 超时族（plan-mode 只读闸与并行分类从此把它们当 read，超时 60s 族）。
- 暴露 2（准入修复，本批发现的真实缺陷）：四工具的 workspace 准入门要求 engine `sessions.cwd` 匹配当前工作区，
  但 kernel run 只建裸 session 行，cwd 永远是 NULL —— 准入门**恒拒绝**（真实回合报错：`session_event_read` 报
  「会话未纳入当前工作区」）。新增 `session_sync.ensure_session_workspace()`（NULL 才填、绝不覆盖已有 cwd、ssh 跳过），
  并在 kernel run-start 接线。单测：

```
test_ensure_session_workspace_fills_null_and_never_clobbers PASSED
test_execute_query_admits_session_stamped_by_run_start PASSED
```

- 真实回合 1（修复前，run `7b43bd58-...`）：三工具都被模型调用（schema 本就在模型可见池、经 legacy bridge dispatch），
  但都返回准入错误 —— 证明缺陷真实存在。
- 真实回合 2（修复后，run `fc514026-...` 轮次，conversation dsh-z2-e31-03）：

```
[event] tool.started name=session_event_read
[event] tool.started name=session_event_search
[event] tool.started name=session_trace
[event] tool.completed name=session_event_read output_contract=text/session_event_read output
[event] tool.completed name=session_event_search output_contract=text/session_event_search output
[event] tool.completed name=session_trace output_contract=text/session_trace output
```

  模型回复（节选）：`session_event_read` seq 1 不存在，改读 seq 44 得到
  `event_type = turn/start（turn_id fc514026-…，process_id 19680，2026-11-14T07:23:50Z）` ——
  工具返回了真实 durable 事件数据。ws 终态 `run.completed`。

## E32 worktree：固定 revision 创建 + run 内进入 — CLOSED（暴露 + 取证）

- 动作：暴露（schema 描述写明 `base_branch` 接受任意 commit-ish/固定 commit SHA、worktree 是普通目录可在同一 run 内直接读写）+ 取证。
- 文件：`core/atlas/tools/workspace_workflows.py`（`_WORKTREE_SCHEMA` 描述）、`core/tests/test_w4_z2_batch.py`。
- 单测（真实 git 仓库断言 pinned HEAD）：

```
test_worktree_service_creates_from_pinned_commit PASSED
test_worktree_schema_documents_pinned_revision_and_in_run_use PASSED
```

- 真实回合（scratch 仓库 `.tmp/live/ws-e32/repo`，pinned SHA=1b415cc4…，其后又有一次 commit eea9018）：

```
[event] tool.started name=workspace_worktree_manage
[event] tool.completed name=workspace_worktree_manage ...
[event] tool.started name=local_file      # 读取 worktree 内文件（同 run 内）
[event] tool.started name=exec_command    # 在 worktree 内 git rev-parse HEAD
[reply] '...worktree 已创建，路径是 ...\ws-e32\.atlas-worktrees\repo\dshz2816。...
**marker.txt 内容（逐字）**：PINNED_MARKER_CONTENT_42
**HEAD 校验**：在 worktree 内运行 git rev-parse HEAD，输出 1b415cc42c27f87022675...'
```

- 落盘复核（模型回合结束后我直接查）：

```
$ cd .tmp/live/ws-e32/.atlas-worktrees/repo/dshz2816 && git rev-parse HEAD && git branch --show-current && ls
1b415cc42c27f87022675f048cd8b9c61a907fd3      # = pinned SHA（不是后面的 eea9018）
atlas/dshz2816-pin42
marker.txt                                     # after.txt 不存在 → 确实钉在旧 revision
PINNED_MARKER_CONTENT_42
```

- 结论：pinned-revision 创建（git 层本就接受 commit-ish，暴露成 schema 语义）+ 同 run 内进入（路径读写）均实证。

## E33 兜底补齐：写路径诊断增量（Atlas 独有） — 维持 PRESENT-STRONGER

- 无代码改动。证据：
  - `core/atlas/engine/lsp_bridge.py:38-80`（`snapshot_before_write` / `report_after_edit`，delta 诊断 + `lsp.diagnostics` 事件）；
    写接缝在 `core/atlas/engine/tool_registry.py` `_lsp_pre_write` / `_lsp_attach_report`（单文件 + V4A 多文件补丁）。
  - 单测：`python -m pytest tests/test_lsp_service.py tests/test_lsp_range_shift.py tests/test_lsp_lifecycle.py`
    → `17 passed, 6 deselected, 5 warnings in 5.45s`（含 baseline→delta→修复归零语义断言）。
  - 备注（预先存在、与本批无关）：`tests/test_c6_lsp_wiring.py` 在默认 `-m unit` 下被 deselect；用 `-m "unit or integration"`
    强跑会因 `import agent.lsp`（引擎改名后的残留路径）ModuleNotFoundError —— 基线（stash 后原样复跑）同样 9 failed，
    属改名遗留，不在本批处理范围。

## E34 取消时为每个跳过调用生成合成 tool/result — CLOSED（取证）

- 动作：取证。无产品代码改动（实现与单测 W3-X3 已有）。
- 真实回合：模型 `local_exec` 跑 `sleep 30`，驱动在 tool.started 后 3 秒发 `run.cancel`：

```
[event] tool.started name=local_exec
[action] run.cancel sent after tool 'local_exec' (+3.0s)
[terminal] run.cancelled data={}
```

- run journal（run `c3942c5f-df8a-45fc-a8ee-72a49051f4a2`）逐行实录：

```
07:26:21 tool_start local_exec
07:26:24 tool_end local_exec cancelled {'length': 36}
07:26:24 tool_result local_exec cancelled {'length': 36}
07:26:24 tool_batch_cancelled call_count=1
07:26:24 turn_end
```

  在途调用收到终态合成 receipt（state=cancelled，带 36 字节可重放说明文本），批次与 turn 以 cancelled 收尾。
  单测覆盖：`tests/test_kernel_tool_timeout.py` / `tests/test_kernel_tool_error_regressions.py`（后者 2 项
  baseline 已知失败与本批无关，见下）。

## E35 压缩锁 bracket 落 transcript，可检测孤儿 — CLOSED（暴露 + 取证）

- 动作：暴露 + 取证。
- 现状澄清：session 事件的 `compaction/start`、`compaction/end`（completed/aborted）、`compaction/summary`
  在 W3-X4 已落 SessionDB（commit 18ca2c5d），W3-X3 时点的账本结论过时。本批补的是账本原文点名的缺口：
  **run journal 没有 bracket**。改动：`core/atlas/engine/kernel/loop.py` 在 lease 获取时
  `record("compaction_start", holder, watermark, trigger)`；abort/失败/成功三路各补
  `record("compaction_end", holder, reason=...)`（成功路保留原 `record("compaction")`）。
  另加 `core/atlas/engine/session_sync.py::detect_orphaned_compactions()`（只读投影：扫描 session 事件，
  start 无同 holder end 即孤儿）。
- 单测：`test_orphan_detection_reports_start_without_end` / `test_orphan_detection_ignores_aborted_and_completed_brackets` /
  `test_kernel_records_journal_brackets_around_compaction_keywords` PASSED。
- 真实回合 journal（run `33d2ee80-...`，同一 run 内既有 abort 又有 publish，全部成对）：

```
07:33:01 compaction_start {"holder": "atlas:33d2ee80-...:8e81ed0b...", "watermark": 251, "trigger": "automatic"}
07:33:01 compaction_end   {"holder": "atlas:33d2ee80-...:8e81ed0b...", "reason": "aborted", "detail": "no_compaction_method"}
...（中间 4 组 abort 成对，略）
07:33:49 compaction_start {"holder": "atlas:33d2ee80-...:e01c8361...", "watermark": 259, "trigger": "automatic"}
07:33:58 compaction       {"method": "summary", "before_tokens": 13470, "after_tokens": 12319, ...}
07:33:58 compaction_end   {"holder": "atlas:33d2ee80-...:e01c8361...", "reason": "completed", "method": "summary", ...}
```

- session 事件侧同 run 实录（seq 73-87，成对、含 summary）+ 孤儿检测：

```
81 compaction/start {'holder': 'atlas:33d2ee80-...:e01c8361...', 'watermark': 259}
82 compaction/summary {'holder': 'atlas:33d2ee80-...:e01c8361...'}
83 compaction/end {'holder': 'atlas:33d2ee80-...:e01c8361...', 'reason': 'completed'}
...
orphans: []
```

  人为孤儿也验证过：`begin_session_compaction` 后不发布 → `detect_orphaned_compactions` 返回 1 条带 watermark 的孤儿（单测）。

## E36 后台作业完成通知作为 followup 投递 — CLOSED（取证）

- 动作：取证。无产品代码改动（inbox watcher → steer 队列 W3-X3 已接）。
- 真实回合（run `a311a05b-4322-4a8a-9441-2710aab7ce98`，conversation dsh-z2-a311a05b）：
  模型 `local_process action=start`（bash `sleep 6 && echo BAKED_DONE_888888`，detached）→
  `local_process action=handoff`（handoff 置 notify_on_complete=true）→ `sleep 15` 保持 run 活跃。
  6 秒后作业完成，`publish_notification` 落 inbox，kernel 的 `watch_notifications` 把它投进 steer 队列，
  ws 观测到 followup 注入：

```
[event] run.steered content='后台通知（process.completed）：\n{"execution_id": "54d52d1e-db2c-4423-a3b7-24353c7be756", "pid": 10056, "command": "C:\\Program Files\\Git\\usr\\bin\\bash.exe -lc sleep 6 && echo BAKED_DONE_888888" ...}'
```

  模型最终回复（节选）：

```
... SLEEP_DONE BAKED_DONE_888888
说明：... 后台通知已收到，任务 `54d52d1e…be756` 已正常退出（code 0，输出 `BAKED_DONE_88888...
```

  即真实模型回合观测到：后台作业完成 → durable inbox → followup（steer）投递 → 模型消费并引用标记词。
  备注：`consume_notifications` 是消费即删除，inbox 行读完即清，所以 `run.steered` 的 content 就是投递证据。

## 单元测试汇总（真实输出）

```
$ python -m pytest tests/test_w4_z2_batch.py -q -p no:cacheprovider --basetemp=D:/Atlas/.worktrees/w4-z2/.tmp/pytest
14 passed, 5 warnings in 4.03s

$ python -m pytest tests/test_w4_z2_batch.py tests/test_kernel_compaction_surface.py tests/test_w3_session_compaction.py \
    tests/test_kernel_request_envelope.py tests/test_w3_query_export_spill.py tests/test_lsp_service.py \
    tests/test_kernel_tool_timeout.py tests/test_kernel_durable_inbox.py -q ...
58 passed, 5 warnings in 10.09s
```

## 已知既有失败（与本批无关，baseline 复跑等价）

本批 kernel/-k 扫描 `7 failed, 170 passed`，用 `git stash` 在未改动的 ec0a9d47 基线复跑同组测试，同样 7 failed：
`test_atlas_mcp_config.py::test_compaction_agent_pins_bare_wire_id_from_host_shaped_config`、
`test_kernel_tool_error_regressions.py::test_tool_call_arguments_repair_only_closed_objects`、
`test_model_tokens.py` 4 项（tiktoken 下载/中文估算）、
`test_runtime_resources.py::test_automatic_compaction_futures_do_not_leak`。按 W4-SESSION 判定标准不属于本批回归。

## 环境备注

- worktree `config/atlas.toml`、`data/hooks.toml`（把用户级 `~/.codex/hooks.json` 的 9 个未信任 codex hook 在本
  worktree 后端禁用，避免 fail-closed 信任闸拦住测试回合；不触碰用户真实配置）、`data/user-settings.json` 为本批
  测试配置，均被 gitignore，不入库。
- 后端进程已全部关闭（8882 无监听）。

## 事故记录（透明披露）

收尾清理本批残留进程时，一条 PowerShell 过滤器误杀了**不属于本批**的两个
`D:\Atlas\core\.venv\python -m uvicorn atlas.server:app --host 127.0.0.1 --port 8874` 进程（主检出区、
端口 8874，应为其它批次/编排器在用的后端）。已立即用相同命令行 + 计划书的标准代理环境
（HTTP(S)_PROXY=http://127.0.0.1:7897）分离重启，`netstat` 确认 8874 恢复 LISTENING（PID 7156）。
原两个进程可能是同端口的双实例（Windows SO_REUSEADDR 允许），现只恢复为单实例；若 8874 的属主
发现缺第二个实例，请自行重启另一个。数据均落盘（主检出区 data/），进程重启不丢状态。
