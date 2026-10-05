# ATLAS-H1-CORE-HARDENING 结果（用户决定收尾）

日期：2026-10-05　状态：**CLOSED_BY_USER — 合入 main，不做剩余正式验收**

用户在 Z5 进行中叫停，决定 H1 就此收住、进入日常使用。合入前，Claude 在主机工作树
`D:\Atlas-h1-core-hardening`（HEAD `b0c4ac8`）用 `artifacts/h1r3/controller_pytest.py`
跑全量 unit（`core/tests -n 8 --timeout=300`）：**2011 passed / 4 skipped，exit 0，116 秒，进程正常退出，无残留**。

## 已达成（有证据）

- 内核接口化：Atlas 不再改写 Hermes 私有属性；fork 钉在 `atlas` 分支 `ab4209b0`。
- `server.py` 8609 → 约 760 行；路由快照 394 项一致。
- 会话记录以 SessionDB 为唯一来源；真实库副本迁移 59 会话 / 117 消息零不一致。
- 每会话复用 Agent、MCP 只注册一次、事件驱动；统一模型路由，Claude 原生通道自动探测。
- 冷启动中位数 3.38 秒；无头 CLI `atlas run` / `atlas doctor`。
- 测试污染从源头清掉，并加了 autouse 守卫；默认顺序和 3 个随机顺序全量 unit 都全绿。
- 本波修掉的真实生产 bug：D1/D2/D3（中转站模型名、失败报成成功、工作区 cwd 泄漏）、`/api/search` 500、
  渠道 GAP-1/GAP-2、CLI 计划模式挂死、回退时文件不恢复、分叉摘要位置错误、用量缓存丢失、
  Windows hook 的 bash 解析到 WSL、SQLite 工作线程泄漏、部分用量被当成 0。

## 未完成（用户决定不再追）

- A6 并发隔离测试 20 次独立进程连跑（之前 3 整次 20 轮通过过）。
- A8 原生 Anthropic 四项没有逐项对上测试名。
- A14 unit+integration 层计时、desktop 层、前端全量没按最终口径跑。
- A15 真实模型：上一轮 12 个场景里 10 个 CHECK-OK；08/10/12 的脚本已修好，但没重跑。
- 全量 unit 日志里有一个子进程读取线程的 GBK 解码警告（`subprocess._readerthread`），未定位。

以下为 Codex/ZCode 的阶段性记录，保留作证据。

---

# ATLAS-H1-CORE-HARDENING result checkpoint

Date: 2026-10-05  
Status: **PARTIAL — final gates and independent review evidence remain pending.**

This checkpoint records only evidence already present in the execution ledger or independently reported by the controller. It is not the final acceptance result. No `AWAITING_REVIEW` state is claimed. The acceptance criteria below are copied from §13 of `tasks/taskbooks/ATLAS-H1-CORE-HARDENING.md`; any unrun final gate remains pending.

| # | Criterion | Status | Evidence recorded so far | Remaining acceptance evidence |
|---|---|---|---|---|
| A1 | No Hermes private-attribute writes or identity-string replacement in `core/atlas/` (AST gate). | PENDING | R0 focused run recorded 18 failures / 107 passes / 12 deselected; this is not evidence that the current AST gate passes. See `ATLAS-H1-CORE-HARDENING.progress.md`, “Codex takeover (H1R)”. | Run the current AST tests and inspect the current implementation in the final gate. |
| A2 | All Hermes fork patches are listed in `ATLAS_PATCHES.md` and have tests. | PARTIAL | Fork `atlas` is pinned to merged commit `cc817c54fea53bd6a2eeb7cb86ac1c7d05e354f8`; patch inventory was expanded. On the new pin, patch-focused selections passed 23 tests and 25 tests (one existing skip in the latter); `test_hermes_contract.py` passed 2 tests. The broader fork selection had 10 failures, 459 passes, 1 skip; nine failures reproduced on the frozen old fork as Windows/platform failures. Details are in the progress ledger, “R5 fork closeout”. | Re-run the final fork/contract checks from the final pin and independently check patch-to-test coverage. |
| A3 | Conversation bodies are stored only in SessionDB; migration, fork, rollback and deletion leave `atlas doctor sessions` with zero inconsistencies. | PARTIAL | Controller ran `tests/test_session_migration.py tests/test_hermes_session_sync.py -m "not live" --timeout=300 --show-capture=no --tb=short -q --basetemp=D:/Atlas-h1r-controller-r3-fixed`: **17 passed, 11.59s, exit 0**. A fresh isolated copy imported 59 sessions / 117 messages, retained 9 existing sessions, preserved 117/117 message timestamps and 59/59 session `started_at` values, and reported zero doctor discrepancies. Atlas source hash remained unchanged. | Final user-facing delete/export/import/branch/rollback journey and doctor checks remain part of the final gate; the real production stores were not modified. |
| A4 | `run()` uses `RunRequest` / `RunCallbacks`; `agent/__init__.py` is split and at most 1,200 lines. | PARTIAL | The ledger records the `run()` thin-adapter conversion with signature parity and `agent/__init__.py` reduced from 3,097 to 1,034 lines. | Re-run current API/contract tests and verify the exact public callback/request contracts in final review. |
| A5 | No runtime `os.environ` mutation; MCP registers once; same-session AIAgent reuse; no 50 ms polling; no leaked futures. | PARTIAL | Historical H3 evidence in the ledger reports 8 constructions across 8 sessions × 20 waves, versus 22 constructions / registrations in the before baseline, with event-driven turn-loop measurements. | Re-run current runtime-resource and environment-isolation tests; inspect for regressions after R1–R7 integration. |
| A6 | Eight-session concurrency isolation passes 20 consecutive repetitions. | PENDING | No final 20-run evidence is recorded. | Run `test_concurrency_isolation.py` 20 times under the final isolated harness and retain the aggregate result. |
| A7 | Zero `acompletion` calls outside the model router; handoff, MoA, compression and title paths work with native configuration. | PARTIAL | Historical AST evidence recorded an empty direct-litellm allowlist. R2 compression routing selections passed 11 tests and a narrower 5 tests; they covered prefixed-route manual compression, native-only manual compression, and notification-read recovery. | Re-run the final AST gate and all affected native-only paths after R7 usage wiring. |
| A8 | Native Anthropic cache breakpoints and thinking signatures round-trip; gateway probe and fallback work. | PENDING | No current final evidence for all four behaviors is recorded in the checkpoint. | Run the current native-channel/cache/signature and gateway fallback tests; record each result. |
| A9 | `server.py` is at most 800 lines and the route snapshot is unchanged. | EVIDENCED; final gate pending | Current `server.py` is 761 lines. The ledger records `test_route_snapshot`: **2 passed** and 394 operations (391 HTTP + 3 WebSocket), matching the frozen snapshot. | Re-run `test_route_snapshot` in the final serial gate. |
| A10 | Required Ruff scopes have zero BLE001/S110/S112 violations under `--ignore-noqa`; full repository is no worse than baseline. | PARTIAL | Controller's blind-catch scan found 133 repository violations (BLE001 116, S110 14, S112 3), with zero in the required critical scopes. The root lint gate selection reported 9 passes. | Record the exact final lint command and establish the baseline-relative full-repository comparison in the final gate. |
| A11 | Channel tasks default to `ask_writes`; approval round-trip passes (unless H7 was removed). | PARTIAL | The ledger records 58 focused channel/gateway tests passing and the H7 server-free write-approval scenario. No H7 removal is recorded. | Re-run the current channel approval round-trip and default-policy tests after final integration. |
| A12 | Cold-start median is at most 5 seconds; Electron does not kill a slow backend start. | PARTIAL / NOT MET YET | R1/R4 tests passed 17 cases in 21.29s; `server.py` is 761 lines. The latest uncontaminated cold-start median recorded is **5.0477s**, above the 5.000s requirement. Later 6.0378s / 7.5059s probes were marked contaminated. The old pytest summaries were later found to have lingering processes; their exit status is corrected in the ledger and they are not treated as green. | Obtain three clean, serialized startup measurements meeting the unchanged 5s median limit; retain the Electron slow-start test result. |
| A13 | `atlas run -p` stream-json, exit-code and resume behavior passes. | PARTIAL | The takeover ledger records H9 CLI implementation and 11 focused tests for stream-json, resume and approval-deny behavior. | Re-run the current CLI suite on the final pinned fork and record stream, exit-code and resume assertions. |
| A14 | Unit ≤180s; unit+integration ≤600s; all non-live backend and frontend tests pass. | PENDING | Static R6 inventory: 189 matching test files / 1,950 test definitions; 1,744 unit, 190 integration, 1 desktop and 15 live definitions. The complete non-live suite contains 186 files / 1,935 definitions. No R6 test lane has been run as part of this checkpoint. | Run the R6 unit, unit+integration, desktop and frontend gates serially; record actual collected counts, exit statuses and elapsed times in `docs/plan/EXECUTION-GUIDE.md`. |
| A15 | At least 10/12 real-model scenarios pass, with explicit outcomes for 10 and 12 and root causes for failures. | PENDING | Earlier artifacts recorded CHECK-OK for scenarios 01–09 and 11 but scenario 08's plan step timed out (exit 124); scenarios 10 and 12 lacked results. Later H10.2 work recorded 3/3 targeted defect re-proofs. No new live model calls have been made in H1R. | Complete the authorized 12-scenario R7 rerun within its token budget; report every scenario, especially 08, 10 and 12, and each failure root cause. |
| A16 | Frontend protocol, API paths and event types are unchanged; frontend tests and route snapshot pass. | PARTIAL | The route snapshot is recorded as 394 operations with 2 tests passed. The ledger has earlier frontend suite results (160 passed in the H8 work and 165 in a later Electron stage); neither is the final R8 full frontend gate. | Run the complete current frontend suite and final route snapshot; verify protocol/API/event contracts against the baseline. |

## Known non-green and incomplete evidence

- The R0 takeover selection failed **18 tests** while passing 107 and deselecting 12; the ledger attributes the environment to an unintended host Hermes import and records route snapshot mismatch. This is historical failure evidence, not a current acceptance run.
- Five historical R3 migration runs and one C6 pagination run produced summaries while 12 pytest Python processes and their six PowerShell parents remained alive. Those 18 owned processes were later verified and stopped. Their old summaries are not normal-exit evidence. The independent timestamp-fixed controller run above is a separate valid exit-0 result.
- Startup remains over budget at the latest usable median; the R6 full-suite timing, final lint comparison, concurrency ×20, final frontend run, final route snapshot and R7.1 live scenarios remain pending.

## Evidence source

Detailed historical commands and process-status corrections are in `tasks/results/ATLAS-H1-CORE-HARDENING.progress.md`. Static R6 lane counts and exact staged commands are in `tasks/results/ATLAS-H1R-R6-TEST-PLAN.md` and `tasks/results/ATLAS-H1R-R6-TEST-INVENTORY.json`. This checkpoint contains no API keys, raw live logs, transcript bodies or production database contents.
