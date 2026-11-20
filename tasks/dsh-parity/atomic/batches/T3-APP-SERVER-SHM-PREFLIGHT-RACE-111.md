# T3-APP-SERVER-SHM-PREFLIGHT-RACE-111

## Scope

Dependencies: the preflight failure localized in T3-110 and the two-app-server workload from T3-109.

Files changed:

- `core/atlas/engine/state/atlas_state_repair.py`
- `core/tests/test_atlas_state_repair_preflight.py`
- this report
- `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`

## Root cause and correction

`preflight_db_writability()` snapshots existing `-wal` and `-shm` paths, calls `os.access`, and may then attempt an in-scope chmod. SQLite can remove a sidecar while another process closes its connection, between those checks. The old code still raised an unwritable-file `OperationalError` when the same sidecar had already disappeared. The correction skips only a `-wal` or `-shm` path that is absent at the final check; an existing inaccessible sidecar still follows the original fail/repair rules. A missing main database is still reported separately for retry. No ACL check is disabled, and no sidecar is deleted by Atlas.

## Verification

The deterministic red test deleted a real temporary `state.db-shm` during the preflight `os.access` probe. Before the fix it failed with the old read-only error; the companion test that keeps the sidecar present and inaccessible passed. Exit code was 1. After the fix:

```text
python -m pytest -q -p no:cacheprovider tests/test_atlas_state_repair_preflight.py
2 passed, 5 warnings in 2.35s
exit code: 0
```

The present-unwritable-sidecar test confirms the check still raises `sqlite3.OperationalError`. The disappearing-sidecar test confirms the preflight completes without converting absence into a permission failure.

After the correction, the two-app-server case passed five consecutive separate pytest invocations; each run required one provider request, one durable enqueue/start/consume sequence, and both real CLI child processes to exit naturally with code 0. See T3-109 for each actual command summary. The combined app-server subprocess and focused repair tests collected 29 tests and passed as recorded there.

Static checks:

```text
python -m py_compile atlas/engine/state/atlas_state_repair.py atlas/tools/app_server.py tests/test_atlas_state_repair_preflight.py tests/test_app_server_sdk_subprocess_attempts.py
exit code: 0
git diff --check -- atlas/engine/state/atlas_state_repair.py atlas/tools/app_server.py
exit code: 0
test-file trailing whitespace check: none
```

## Limits

The SQLite behavior is exercised only with isolated temporary databases and local fake provider/app-server processes. This does not prove all platform ACL or WAL recovery states, all app-server queue ordering, live model behavior, desktop behavior, or completion of Task 3. Those remain open.
