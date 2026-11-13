# DSH Parity — Master Task Brief

Work in `D:\Atlas` on branch `ui-redesign`. The gap ledger is
`docs/parity/DSH-GAP-LEDGER.md` — 135 evidence-backed rows comparing Atlas with
DeepSeek-Harness (DSH). Nine are already closed (commit `297e38ce`).

## Your job

Close the remaining rows, in five batches by file ownership so parallel workers
never collide. Do every batch. Do not stop to ask; make the best engineering
decision and record it. Verify with tests, then run a real end-to-end check.

## Hard rules (violating these breaks the product)

1. **Never rewrite `messages` table semantics.** 16 mixins, FTS triggers,
   compaction, rewind, fork, export and migration read it. Add alongside.
2. **`SessionDB._execute_write` is the only transaction boundary** and holds a
   non-reentrant `threading.Lock` (`atlas_state.py:598`, `BEGIN IMMEDIATE` at
   `:1041`). Calling `_execute_write` inside its own callback **deadlocks**.
   Opening a second `SessionDB` inside a live transaction blocks ~21s then raises
   `database is locked`. Write through the cursor you are given.
3. **Event names have three sources** and all must move together:
   `core/atlas/api/event_names.py`, `frontend/src/renderer/services/runtimeEvents.ts`
   (`known`), `frontend/src/types/runtime.ts` (`AgentEventType`). A name missing
   from the second is silently dropped at runtime. Then run
   `tests/test_event_contract.py`.
4. **New router → add to the tuple in `application.py` (~line 135).**
   **New service → add to `AppServices` + fill in `server.py` lifespan.**
5. **Tests need `@pytest.mark.unit`** or they are silently deselected
   (`addopts = "-m unit"`).
6. **Never touch** `origin_guard`, `data/memory/**`, `config/atlas.toml`,
   `data/user-settings.json`, or files outside the batch you are doing.
7. **Do not reformat files you were not asked to change.**

## Batch order and file ownership

### Batch A — Engine (`core/atlas/engine/kernel/`, `core/atlas/agent/`)
Rows: E2, E3, E4, E5, E6, E8, E10, E11, E17, E19, E20, E25
- turn/step lifecycle split with typed `turn/end` reasons
- tool pipeline: `post_execute` waterfall + output contract (`output_schema`)
- two-list inbox (`next-turn` / `next-step`), `inject` without waking
- request envelope logging + tool add/remove developer messages
- compaction at step boundary; todo writes durable; goal revision CAS
- subagent fork child + persona; `concludeTurn`; repeat-call reminder

### Batch B — Session/state (`core/atlas/engine/state/`, `session_sync.py`)
Rows: S3, S4, S6, S9, S11, S13, S16, S19, S21, S22, S25, S32
- append-only `session_events` written through the caller's cursor
- reader-side repair closers instead of rewriting transcript
- checkpoint fail-closed; durable tool-result pruning
- register real session projections; incremental FTS re-index
- durable image attachments; session-scoped fs observation
- OTel spans actually emitted; per-node token pricing; fork open-turn guard

### Batch C — Policy (`approval_policy.py`, `sandbox.py`, `engine/tool_permissions.py`)
Rows: E12, E13, E14, E15, E16, E18
- durable `approval/asked` + `approval/decided` in transcript
- permission presets bind sandbox mode AND approval policy; `custom` derivation
- per-call sandbox mode with enforcement reporting
- PTY owner fencing + `waitReason` taxonomy
- unified background job registry with byte-capped rings
- per-call sandbox escalation with justification + approval

### Batch D — Extension (`core/atlas/plugins/`, `skills/`, `tools/mcp_client.py`)
Rows: X2, X4, X8, X9, X13, X16, X17, X23, X27, X28, X29
- reversible registration disposers for every plugin contribution
- ordered profile/bundle/patch layers with row-id patching
- agent presets as capability sets; preset on externally-created work
- Codex hooks bridge (`.codex/hooks.json`)
- durable skill catalog with digest-diff retirement; `disable-model-invocation`
- MCP server scoping; client extension registry; plugin-registered slash commands
- webhook provider abstraction

### Batch E — Desktop (`frontend/src/`, `core/atlas/api/`)
Rows: D1, D2, D3, D4, D5, D6, D7, D8, D9, D10, D13, D14, D17, D30
- OS-assigned port + boot injection channel; typed host IPC lifecycle
- incremental timeline (no O(all-events) rebuild, no 800-event cap loss)
- keyed ConversationNode renderer registry (removes the central switch)
- durable attachment staging with progress; structured composer draft
- follow-with-baseline reconnect + sequence-gap repair; docking with floats
- in-app reconnect affordance; auto-update schedule; `present` deliverable tool
- question `intent` routing; namespaced i18n; trajectory view

## Verification (all batches)

```bash
cd core
python -m pytest -q -p no:cacheprovider <your new test files>
python -m pytest -q -p no:cacheprovider tests/test_event_contract.py
```
Run files in small groups with `timeout`; running the whole suite in one process
can hang after the summary (known issue).

**Known-failing at baseline — do not fix, do not count as your regression:**
`test_route_snapshot.py` (2), `test_c4_plugin_e2e.py` (1),
`test_atlas_mcp_config.py::test_compaction_agent_pins_bare_wire_id_from_host_shaped_config`,
`test_session_migration.py` (7), several in `test_mcp_client.py` /
`test_mcp_lifecycle_shutdown.py`.

## Real end-to-end check (required before you say done)

```bash
cd core
python -m uvicorn atlas.server:app --port 8811 &
python scripts/dsh_live_ws_check.py 8811 "Reply with exactly the word: OK"
```
Model is `deepseek-v4.1-flash` via `https://d1api.xin/v1` through Clash
`http://127.0.0.1:7897`; the key and proxy are already stored in the OS
credential store, so no env vars are needed. Paste the output.

## Deliverable

Commit on your branch. Then write `tasks/dsh-parity/RESULT-<batch>.md` with:
rows closed (by id), files changed, tests added, exact test output, the e2e
output, and anything you could not do **with the reason**. Never claim a
capability works if you did not run it.

---

# 追加要求：不只是「补齐」，而是「吞并 + 超越」

前面五批是**补齐**（DSH 有、Atlas 没有）。这只做到「一样」。要真正做到「吞并并更多更好」，
还需要三件事，请在五批完成后继续做完，同样不要停下来问：

## 六、把 DSH 的独有能力变成 Atlas 的超集

逐项检查，DSH 的**架构性**能力里，哪些是 Atlas 现在只能「等价」而不能「更强」的。至少覆盖：

1. **会话事件日志 → Atlas 要能回答 DSH 回答不了的问题。**
   DSH 的事件日志只能重放。Atlas 要在此之上加一层**因果查询**：
   `GET /api/conversations/{id}/explain?message_id=N` 返回这条消息**为什么存在**——
   它由哪个 turn/step 产生、引用了哪些工具结果、是否被压缩遮蔽、被哪次 rewind 失活。
   DSH 没有这个，因为它没有 Atlas 的 `messages`/`session_events` 双层结构。

2. **能力缝 → Atlas 要有 DSH 没有的「能力账本」。**
   DSH 的插件能注册服务但不知道自己被谁用。Atlas 要在既有 `introspect` 上扩展：
   `registry.query("capabilities", "usage")` 返回每个 capability/hook/service 的
   **注册来源、调用次数、最后调用时间、失败次数**。这是可观测性上的净增量。

3. **沙箱 → Atlas 要有 DSH 没有的「效果回执」。**
   DSH 报 `full|partial` 执行等级。Atlas 要在每次工具调用后写一条
   `effect receipt`（改了哪些文件、执行了哪些进程、网络出站目标），存进事件流，
   并能按 run 汇总。这是审计能力上的净增量。

## 七、测量「更好」，不要只说「更好」

建 `core/scripts/dsh_parity_bench.py`，对同一组固定任务同时跑 **Atlas** 与 **DSH**
（DSH 在 `D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness`，已 clone），
输出一张对照表，至少包含：

| 指标 | 怎么量 |
|---|---|
| 单回合 prompt tokens | 从各自 usage 读 |
| 工具调用轮数 | 数 tool.call 事件 |
| 同一任务的完成时间 | wall clock |
| 上下文压缩触发次数 | 数 compaction 事件 |
| 失败后自恢复次数 | 数 retry/repair 事件 |
| 事件日志可回答的问题数 | 见第六条 1，Atlas 应有、DSH 为 0 |

**如果某项 Atlas 输了，如实写进 RESULT 并说明原因，不要隐藏。**
「更好」必须有数字支撑，没有数字就不许说更好。

## 八、不许为了「对齐 DSH」而削弱 Atlas 已经更强的地方

这些是 Atlas 的净优势，任何改动都不能让它们退化，必须有回归测试锁住：

| 能力 | 为什么不能动 |
|---|---|
| 长期记忆（`memory/library/`） | DSH 完全没有 |
| 三模式 rewind + 文件还原 | DSH 只有类型字面量 |
| hook 逐条信任/审批门 | DSH 无信任门 |
| skill 依赖/生命周期门 | DSH 只有调用门 |
| 多窗口 / 分栏 / 浮动 composer | DSH 单窗口 |
| 消息级操作（编辑重发、fork+摘要） | DSH 只有复制+分支 |
| 写路径 LSP 诊断增量 | DSH 无 |
| 富文档预览（pptx 元素级引用） | DSH 只有基础预览 |

请为这 8 项各加一条**回归测试**（如果已有则确认它真的会失败于退化），
写进 `core/tests/test_atlas_advantages.py`。

## 九、最终交付物

1. `tasks/dsh-parity/RESULT-{A,B,C,D,E}.md` — 每批的逐条结果
2. `tasks/dsh-parity/COVERAGE.md` — 135 条差距的**最终状态表**：
   每行标 `CLOSED` / `PARTIAL(原因)` / `NOT-DONE(原因)` / `ATLAS-STRONGER`，
   **不允许留空，不允许写 TBD**
3. `tasks/dsh-parity/BENCH.md` — 第七条的实测对照表
4. 真实后端 + 真实模型跑通，贴出 `run.completed` 输出

**禁止事项**：不许把「写了代码」当「做完了」；不许把「测试通过」当「功能可用」；
不许在 RESULT 里写「已实现」而没有贴出真实命令输出。
