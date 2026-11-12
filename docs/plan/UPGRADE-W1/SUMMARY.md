# Atlas UPGRADE-W1 summary

## W3 LoCoMo-Refined evaluation (2026-11-08)

| Metric | Result |
| --- | --- |
| Dataset | `.eval-data/locomo_refined.json`, 2,745,985 bytes; SHA256 `1AEF6DA702087D72515D1B9224F0956A2FBAB415C11936253BF7D967D3CF8C17` |
| Judge | `deepseek-v4.1-flash` via Atlas `ModelManager` / `https://d1api.xin/v1`; non-official (official judge: `Qwen/Qwen3-14B`) |
| Full observation | 10 conversations; 1,382 QA; 521 multimodal skipped; 861 evaluated; 0 judge errors; 168/861 correct (19.51%); 4,455.2 seconds. Not an accepted compliance result: `MemoryLibrary.ready()` implicitly created and committed a Git repo inside that run's temporary memory root. No repository Git operation occurred. |
| Category accuracy | single-hop 8/77 (10.39%); temporal 34/167 (20.36%); multi-hop 11/36 (30.56%); open-domain 115/581 (19.79%) |
| Conv-26 gate | Post-fix compliant run: 419 turns ingested; 138 QA; 51 multimodal skipped; 87 evaluated; 0 errors; 46/87 (52.87%) |
| Verification | Focused tests: 5 passed. Evaluator bypasses `MemoryLibrary.ready()` Git bootstrap, closes SQLite index, and cleans its disposable memory root. HEAD stayed `c72b4c4f`. |

The full-run aggregate above is a real result but is not accepted as compliant because the library bootstrap implicitly committed inside its temporary root. The evaluator was fixed and conv-26 rerun successfully without `.git`; the post-fix 46/87 result is the accepted scoring result. Earlier runs scored 43/87 and the full run's repeated conv-26 scored 40/87, showing judge variation. The judge is non-official. `.eval-data/` is untracked and was not ignored by the current `.gitignore`; it was left untouched and `.gitignore` was not changed. A full compliant rerun was not done because the earlier full pass took 4,455 seconds.

## W2 final completion status (2026-11-08)

| Phase | Final status | Evidence / limits |
| --- | --- | --- |
| P1 MCP stateless | W1 accepted; not rerun in W2 | W1 test results and remaining legacy MCP regressions are recorded below. |
| P2 Memory scope | W1 accepted; not rerun in W2 | W1 focused scope tests passed; related-suite baseline failures remain recorded below. |
| P3 AML adapter | Honest interface only; no score | Removed `PROFILE_DIMENSIONS`; `run_locomo(path)` errors clearly when the dataset is missing and refuses to imply scoring when present. LoCoMo-Refined upstream is https://github.com/mem-eval-suite/LoCoMo_refined; no local dataset or scorer/judge was available. AML tests: 3 passed. |
| P4 In-place compact | Runtime dispatch and phase-boundary trigger connected | `loop.py` installs `compact_in_place_callback` and `phase_boundary_callback`; `ExitPlanMode` evaluates the boundary once per approved plan via `plan:N`. Dispatch-path test uses 40 turns and verifies ≥50% token reduction, in-place list replacement, last two turns, summary work state, and event. P4 tests: 4 passed. |

W2 validation used `--basetemp` directories under `C:\Users\25011\AppData\Local\Temp`; the task-created basetemp directories were removed after the runs. Git log remained `c72b4c4f`, `32c22061`, `b3e5f9d6`; no Git write operation was performed.

## W1 completion status (historical)

| Phase | Status | Evidence |
| --- | --- | --- |
| P1 MCP stateless | Partial | New stateless HTTP list/call acceptance passed; legacy MCP client has 4 failures and -k mcp is blocked during collection. SSE regression is not established. |
| P2 Memory scope | Implemented; focused tests pass | 6 new scope tests pass; related memory suite has 5 failures in source-ref, legacy return-shape, and embedding-loop expectations. |
| P3 AML adapter | Implemented as an adapter seam | Add/Search smoke passed; LoCoMo-Refined end-to-end score not run. |
| P4 In-place compact | Partial | In-place summary and helper tests pass; runtime tool dispatch and phase-boundary call sites are not wired within allowed files. |

## W1 files changed by these phases (historical)

- P1: core/atlas/tools/mcp_client.py; core/tests/test_mcp_stateless_handshake.py; core/tests/fixtures/stateless_mcp_server.py.
- P2: core/atlas/memory/library/index.py; store.py; __init__.py; core/tests/test_memory_scope.py. hybrid.py required no edit.
- P3: core/atlas/memory/aml_adapter.py; docs/plan/UPGRADE-W1/aml-baseline.md.
- P4: core/atlas/kernel/context.py; core/atlas/agent/tool_catalog.py; core/tests/test_context_compact_in_place.py.
- Reports: P1-mcp-stateless.md, P2-memory-scope.md, P3-aml-baseline.md, and P4-compact-in-place.md in this directory.

## W1 test count and results (historical)

Verified pytest runs executed 74 test cases total: 65 passed and 9 failed. This count comprises the P1 acceptance test (1 passed), the MCP client file (18 passed / 4 failed), P2 focused suite (6 passed), related memory regression (38 passed / 5 failed), and P4 tests (2 passed). The broad pytest core/tests -k mcp invocation ran no tests: 2 collection errors and 2,410 deselected. A manual P3 adapter smoke passed (one scoped write and one scoped retrieval).

Commands use D:\Atlas\core\.venv\Scripts\python.exe, PYTHONPATH=D:\Atlas\core, and cwd D:\Atlas; exact command lines and outputs are in the phase reports.

## W1 not done and reasons (historical; superseded for P3/P4 by W2 status above)

- No full LoCoMo-Refined, PersonaMem, or BEAM evaluation was run. Only LoCoMo-Refined has a usable adapter seam; the other benchmarks remain TODO pending schema/protocol selection.
- P1 legacy SSE regression and broad MCP suite remain unverified because the MCP client has failures and collection errors.
- P4 runtime dispatch and the plan-boundary trigger were wired inside `core/atlas/kernel/loop.py`; the subtask-close boundary was not wired because `subtask_close` has no call site in that file. No `tool_node.py` change was needed.
- core/tests/unified_memory has no .py source in this checkout: the directory exists but holds only stale `__pycache__/*.pyc` files, and `git ls-files` returns nothing for it, so the taskbook's 271-passed baseline cannot be reproduced locally. (An earlier revision of this line said the directory was absent, which understated the case: the sources are missing, not the directory.)
- Two empty commits (9c5255bf, 578cb08d) appeared while work was in progress, although the user prohibited commits and the agents report they did not invoke git commit. Since their tree matched origin/ui-redesign, the local branch pointer was restored to origin with a mixed reset; all working-tree changes were preserved and no commits remain on the branch.
- Generated untracked pytest data remains under core/.pytest_tmp_w1_mem.

## W1 risks (historical)

- P1 stateless behavior has only one real HTTP fixture; no evidence yet validates cache-hint expiry or old SSE recovery.
- P2 behavior is scope-tested, but five related memory regressions remain red and lack a clean baseline comparison.
- P3 maps some requested profile dimensions to not measured because LoCoMo-Refined does not isolate rule execution or governance; no benchmark score is claimed.
- P4 exposes a schema without executable dispatch integration, so a model call may not run the compaction operation.
