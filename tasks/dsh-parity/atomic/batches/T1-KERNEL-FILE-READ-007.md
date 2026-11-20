# T1-KERNEL-FILE-READ-007

Status: DONE (local Kernel path; SSH file reads remain a separate OPEN atom)

## Atomic scope

Expose full-file read in the direct AtlasKernel model schema and dispatch. DSH `@deepseek-ai/dsh-tools` README defines `read_file(path: absolute string, offset?: number, limit?: number) -> string`; Atlas' direct Kernel currently offers neither this schema nor a `read_file` dispatch branch, while the legacy `tool_registry` alias is not called by the API/kernel path. `grep` is a separate search operation and is not equivalent to reading complete file contents.

## Files

- Modify: `core/atlas/engine/kernel/tools.py` — add `read_file` wire schema with path/offset/limit.
- Modify: `core/atlas/engine/kernel/loop.py` — dispatch `read_file` via current run's `EditManager` and preserve owner/workspace/tool-policy boundaries.
- Test: `core/tests/test_c1_websocket_acceptance.py` — isolated API wire offering, execution result, and SessionDB cross-turn replay.
- Test: `core/tests/test_kernel_file_read.py` — direct handler boundary tests (valid read, pagination, missing/outside path, absent workspace/edit manager).
- Evidence: `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`, `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`, `tasks/dsh-parity/atomic/interaction-edges.jsonl`, `tasks/dsh-parity/atomic/batch-queue.jsonl`.

## Dependencies

- Implementation: `T1-API-TOOL-CONSUMER-006` corrected API transcript fixture; existing `EditManager` in `core/atlas/engine/kernel/edit.py` owns canonical local workspace path resolution, file snapshots, and stale-write tracking.
- Source reference: fixed DSH README example at `packages/core/tools/README.md` in commit `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Shared writer: `kernel/tools.py` and `kernel/loop.py` are owned by this batch until focused tests pass.

## Binary acceptance

1. First API wire request offers `tool_search`; after `select:read_file`, the next wire request offers `read_file` and the fake provider calls it only then.
2. A real isolated `/ws/chat` run calls it and receives complete fixture content; after another turn, SessionDB model history contains the assistant tool call and matching tool-role content.
3. Relative and in-workspace absolute paths work; symlink/path escape, missing path, SSH workspace without the SSH read implementation, or absent EditManager fail closed and never read host data.
4. `offset`/`limit` are bounded and line-based; reading records a complete snapshot in EditManager so a subsequent guarded write can use the existing stale-write invariant.

## Verification

- Add the API tool-call test first and run it red with explicit `-o addopts=`.
- Add direct handler tests marked `pytest.mark.unit`; verify exact collected node count.
- Run focused API and helper tests, `py_compile`, `git diff --check`, and AST check for `_dispatch` arguments/branch placement.
- Record output and evidence level. No real model or public backend is part of this batch.

## Evidence

- Red: `test_websocket_read_file_is_offered_executed_and_replayed` observed the first request omit `read_file`; forcing it surfaced a missing schema. After adding the schema, the API call exposed `UnboundLocalError: cannot access local variable 'Path' where it is not associated with a value` because `_dispatch` had a conditional inner `Path` import. The import was removed; the module-level `Path` is used.
- Green command from `D:\Atlas\core`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_kernel_file_read.py tests/test_c1_websocket_acceptance.py::test_websocket_read_file_is_offered_executed_and_replayed tests/test_c1_websocket_acceptance.py::test_websocket_read_file_denies_absolute_path_outside_workspace tests/test_c1_websocket_acceptance.py::test_websocket_multiturn_keeps_tool_transcript --tb=short`; output `7 passed, 5 warnings in 25.12s`, exit 0.
- Syntax and diff checks passed. AST reports `_dispatch` line 3506, `read_file` branch line 3736, parent chain `If < AsyncFunctionDef < ClassDef < Module`, and the `EditManager.read_file_page` method reference at line 3757.
- Evidence is isolated API process + local FakeLLMServer and unit EditManager tests; SSH-backed reads, desktop, real model and remote machine are not covered by this batch.

## Rollback boundary

Only this batch's newly added lines/files may be reverted if its acceptance proves invalid. Preserve all pre-existing dirty worktree edits; do not reset, clean, stash, commit, or push.
