# PAR-08-D — Worktree POST rollback-failure semantics and recovery

- Date: 2026-11-19
- Package: PAR-08-D rework of the PAR-07-D acceptance gap
- Worktree: `D:\Atlas\.worktrees\zcode-par07-worktree-api-fix`
- Branch: `zcode/par07-worktree-api-fix`
- HEAD: `060071ab2ecf86d41cab90e98160183ce126bc69` (unchanged; no commit/push/merge)
- Baseline receipt: `par07-codex-acceptance-20261119.md` row D; previous receipts
  `par07-d.md`, `par07-d-fix.md`.

## 1. Acceptance gap being fixed

The create route created the worktree, failed to persist `worktree_path`, then called
`remove`; a bare `except Exception: pass` swallowed cleanup errors and the 500 detail
claimed "it has been removed". Real failure injection showed Git still listing 2
worktrees while the conversation had no `worktree_path`, and nothing durable located the
residue for later cleanup.

## 2. Baseline (before this package's edits)

```
HEAD 060071ab; worktree zcode/par07-worktree-api-fix with the pre-existing uncommitted
POST fix: M core/atlas/api/workspace_router.py, M core/tests/snapshots/routes.json,
A core/tests/test_conversation_worktree_create.py.
```

```
cd core
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  -o addopts= --tb=short --basetemp=.../.tmp/par08-baseline \
  tests/test_conversation_worktree_create.py tests/test_engine_worktree_pinned_revision.py \
  tests/test_route_snapshot.py
```
Exit 1: `1 failed, 10 passed`. The failure is
`test_route_snapshot.py::test_fastapi_lazy_includes_preserve_effective_paths_parameters_and_order`
at `tests/test_route_snapshot.py:403`:
`AttributeError: 'APIWebSocketRoute' object has no attribute 'original_route'`.
`test_routes_match_frozen_snapshot` PASSED at baseline.
Log: `par08-d-baseline.txt`.

## 3. Changes and diff stat

`git diff --stat` vs `060071ab` (includes the pre-existing uncommitted POST fix):

```
 core/atlas/api/workspace_router.py              |  361 ++++++   (+288 this package)
 core/atlas/memory/__init__.py                   |   60 +       (+60 this package)
 core/tests/snapshots/routes.json                | 1640 +++++-- (2 recovery operations)
 core/tests/test_conversation_worktree_create.py |  452 ++++++   (rewritten, +261 net)
 4 files changed, 2288 insertions(+), 225 deletions(-)
```

The pre-task tree already carried the PAR-07-D fix (`+73` router, 191-line test,
1532-line snapshot diff). This package's own delta on top of it is approximately
`+288` router, `+60` memory, `+261` net test rewrite, and `+99/-9` snapshot lines
(the two recovery operations).

### 3.1 `core/atlas/memory/__init__.py`

Added a `worktree_recoveries` table to the existing conversation store (`atlas.db`, the
same `MemoryStore`), not a new database:

- `conversation_id` (PK), `workspace`, `worktree_path`, `worktree_branch`, `base_branch`,
  `reason`, `created_at` (SQLite `datetime('now')`).
- `record_worktree_recovery(...)`, `get_worktree_recovery(...)`,
  `clear_worktree_recovery(...)` (upsert/read/delete).

Rationale: the record failure is `update_conversation`; persisting through the same
method would fail with it. A dedicated row in the same store survives that failure mode
and is the existing persistence layer the router already depends on.

### 3.2 `core/atlas/api/workspace_router.py`

- `_cleanup_worktree_residue(workspace, path, branch)`: idempotent cleanup. Calls the
  existing `WorktreeService.remove(force=True, keep_branch=False)`; if the directory is
  already gone, prunes the admin entry and deletes the branch. Returns `None` only after
  verifying the directory, `git worktree list` registration, and branch are all gone;
  otherwise returns the remaining problems.
- Orphan handling: if `remove` raises but `git worktree list` no longer registers the
  path (the real Windows partial-delete state observed in PAR-07: admin entry gone,
  directory left), the checkout is deleted directly and its branch removed. The `remove`
  error is then superseded by the final verification; recovery does not fail forever on
  a worktree git can no longer address. If the path is still registered, the `remove`
  error remains fatal.
- Create rollback branch now has two truthful outcomes:
  - cleanup verified: 500 detail `status=rolled_back`, message says the worktree and
    branch were removed, includes `worktree_path`, `worktree_branch`, `base_branch`,
    `workspace`, and `record_error`.
  - cleanup failed: 500 detail `status=rollback_failed`, message says it has NOT been
    removed, includes exact path/branch/base/workspace, `cleanup_error`, executable
    `instructions`, and the persisted recovery row (`recovery_persisted`). The
    conversation's `worktree_path/worktree_branch/base_branch` are best-effort cleared;
    `workspace` stays the base root.
- On any later create, a recovery row is found under the create lock; the route first
  runs idempotent cleanup. If cleanup still fails: 409 `recovery_required` with the row
  and instructions, and no new checkout is made. If it succeeds: the marker is cleared
  and creation proceeds.
- `GET /api/conversations/{conversation_id}/worktree/recovery`: returns the marker
  (`recovery` or null), `worktree_exists`.
- `POST /api/conversations/{conversation_id}/worktree/recovery`: explicit idempotent
  cleanup. 200 `recovered`, 200 `nothing_to_recover`, 409 `recovery_failed` while cleanup
  capability is still broken, 409 `recovery_refused` if the conversation owns a recorded
  worktree.
- Both recovery routes are mounted in the real app (`application.py` router tuple) and
  appear in `atlas.server.app.openapi()`.

### 3.3 Tests (`core/tests/test_conversation_worktree_create.py`)

Rewritten from direct handler calls to the real FastAPI router over
`httpx.ASGITransport`, real `MemoryStore` (`tmp_path/memory.sqlite3`) and real temporary
`git init -b main` repositories. All tests carry `pytestmark = pytest.mark.unit`.
Nine tests:

1. `test_create_status_merge_delete_over_http` — normal lifecycle.
2. `test_second_create_conflicts_without_a_second_tree`.
3. `test_non_git_workspace_and_missing_conversation_are_rejected`.
4. `test_record_failure_with_successful_cleanup_reports_rolled_back`.
5. `test_record_and_cleanup_failure_reports_rollback_failed`.
6. `test_retried_create_cleans_residue_clears_marker_and_succeeds`.
7. `test_retry_clears_orphaned_directory_after_git_lost_registration`.
8. `test_explicit_recovery_removes_residue_and_allows_create`.
9. `test_concurrent_create_yields_one_winner` (two real HTTP requests).

Fault injection is centered on `memory.update_conversation` returning `False` and
`WorktreeService.remove` raising `RuntimeError("simulated lock: worktree remove denied")`.

### 3.4 Snapshot

`tests/snapshots/routes.json` regenerated with `python tests/test_route_snapshot.py`.
A probe that removes only the two new routes before building the app proves the snapshot
delta from this package is exactly:

```
unique operations: 858 -> 860
added: GET  /api/conversations/{conversation_id}/worktree/recovery
       POST /api/conversations/{conversation_id}/worktree/recovery
removed: none
all other route entries unchanged: True
shadow_order unchanged: True
components unchanged: True
```

Log: `par08-d-snapshot-delta.txt`.

## 4. Fault-injection matrix (observed)

| Scenario | HTTP response | Git state | Conversation row | Recovery marker |
|---|---|---|---|---|
| Normal POST -> GET -> merge -> DELETE | 200, 200, 200, 200 | 2 worktrees after create; 1 after delete; branch deleted | created path/branch/base; after delete fields cleared; `workspace=base` | none |
| Record failure, cleanup succeeds | 500, `detail.status=rolled_back`, exact path/branch | 1 worktree; branch gone | `worktree_path` empty; `workspace=base` | none |
| Record failure + `remove` failure | 500, `detail.status=rollback_failed`, "has NOT been removed", `cleanup_error`, instructions | 2 worktrees; directory exists; branch exists | `worktree_path/branch/base` empty; `workspace=base` | `worktree_recoveries` row with conversation_id, workspace, path, branch, base, reason, timestamp; `recovery_persisted=true`; listed by GET |
| Retry create after remove capability restored | 200; old branch gone, new branch present; same deterministic path re-created | 2 worktrees (old residue replaced by new checkout) | points at new path/branch; `workspace=base` | cleared |
| Explicit recovery while `remove` still broken | 409, `detail.status=recovery_failed` | 2 worktrees (left in place) | unchanged, empty | retained |
| Explicit recovery after restore, then create | 200 `recovered`; second call 200 `nothing_to_recover`; create 200 | 1 worktree after recovery; 2 after create | empty after recovery; new path after create | cleared |
| Orphan residue: admin entry manually lost, `remove` still broken, retry create | 200 (cleanup then new create) | orphan dir and old branch removed; new branch/checkout created; 2 worktrees | points at new path; `workspace=base` | cleared |

## 5. Commands, exit codes, results

All commands run in `D:\Atlas\.worktrees\zcode-par07-worktree-api-fix\core` with
`PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, `-o addopts=`, and
`--basetemp` under the worktree `.tmp/`. The full target-suite runner was:

```
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  -o addopts= --tb=short \
  --basetemp=D:\Atlas\.worktrees\zcode-par07-worktree-api-fix\.tmp\par08-final3 \
  tests/test_conversation_worktree_create.py tests/test_engine_worktree_pinned_revision.py \
  tests/test_route_snapshot.py
```

Regression runs used the same flags with
`--basetemp=...\.tmp\par08-regress` / `...\par08-memory`.
The snapshot-match-only run used `--basetemp=...\.tmp\par08-snapmatch2` and the single
node id `tests/test_route_snapshot.py::test_routes_match_frozen_snapshot`.
The baseline run used the same three-file command with
`--basetemp=...\.tmp\par08-baseline`.

| Command (abbreviated) | Exit | Result | Log |
|---|---|---|---|
| Baseline: `pytest ... test_conversation_worktree_create.py test_engine_worktree_pinned_revision.py test_route_snapshot.py` | 1 | 10 passed, 1 pre-existing failure | `par08-d-baseline.txt` |
| `pytest ... test_conversation_worktree_create.py` (development run 1) | 1 | 4 failed (test assertions, fixed) | `par08-d-impl1.txt` |
| `pytest ... test_conversation_worktree_create.py` (development run 2) | 0 | 8 passed | `par08-d-impl2.txt` |
| `pytest ... test_conversation_worktree_create.py` (orphan test added) | 1 | 1 failed (orphan fallback kept the stale remove error, fixed) | `par08-d-impl3.txt` |
| `pytest ... test_conversation_worktree_create.py` (orphan fallback corrected) | 0 | **9 passed** | `par08-d-impl4.txt` |
| Final: `pytest ... test_conversation_worktree_create.py test_engine_worktree_pinned_revision.py test_route_snapshot.py` | 1 | **13 passed, 1 failed** (same baseline `test_fastapi_lazy...` at line 403) | `par08-d-runs.txt` |
| `pytest ... test_route_snapshot.py::test_routes_match_frozen_snapshot` | 0 | **1 passed** | `par08-d-snapshot-match.txt` |
| `pytest ... tests/test_backend_parity_wave2.py -k worktree` | 0 | 6 passed, 16 deselected | `par08-d-regress-worktree.txt` |
| `pytest ... tests/test_memory.py` | 0 | 16 passed | `par08-d-regress-memory.txt` |
| `python tests/test_route_snapshot.py` (regeneration) | 0 | snapshot written | `par08-d-snapshot-regen.txt` |
| Snapshot delta probe | 0 | 858 -> 860, only the two recovery routes | `par08-d-snapshot-delta.txt` |
| Production-app OpenAPI probe | 0 | `/worktree` GET/POST/DELETE and `/worktree/recovery` GET/POST present | `par08-d-live-openapi.txt` |
| AST nesting check of the rewritten handler | 0 | final `return` is a direct function child; truthful 500 raises under `if` branches | `par08-d-ast-check.txt` |

Exact final command:

```
cd D:\Atlas\.worktrees\zcode-par07-worktree-api-fix\core
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  -o addopts= --tb=short \
  --basetemp=D:\Atlas\.worktrees\zcode-par07-worktree-api-fix\.tmp\par08-final3 \
  tests/test_conversation_worktree_create.py tests/test_engine_worktree_pinned_revision.py \
  tests/test_route_snapshot.py
```

## 6. Product entry

- The production app (`atlas.server.app`, mounted by
  `core/atlas/api/application.py`) exposes:
  - `POST/GET/DELETE /api/conversations/{conversation_id}/worktree`
  - `GET/POST /api/conversations/{conversation_id}/worktree/recovery`
  - existing `/worktree/merge`, `/worktree/sync`, `/worktree/sync/{action}`.
- No frontend or `backend-adapter` caller was added; like the base POST, this remains an
  API-only capability with no UI wiring. The model tool and run-request auto-worktree
  paths are unchanged.

## 7. Unverified boundaries / notes

- `remove` failure is simulated by monkeypatching `WorktreeService.remove`; a genuine
  Windows file-lock `Permission denied` was observed in the PAR-07 review but not
  reproduced as an OS-level lock here. An exception from `remove` is fatal unless git no
  longer registers the path, in which case the leftover directory is treated as an
  orphan and deleted directly (covered by the orphan recovery test). Disk, registration
  and branch state are verified before any success response.
- Recovery row persistence failure itself is handled (`recovery_persisted=false` plus
  instructions) but not covered by a dedicated test.
- If the base workspace is permanently deleted while a recovery row exists, the row
  cannot be cleared through the API; it remains queryable and the instructions remain.
- Deleting a conversation does not cascade-delete its recovery row (no FK was added);
  the row is unreachable through the API because conversation lookup returns 404.
- Multi-process create race is still only guarded by an in-process `asyncio.Lock`.
- No live Uvicorn network server was started in this package. The route behaviour was
  exercised through the real ASGI router (`httpx.ASGITransport`) with the real
  `MemoryStore` and real temp Git repos; the production `atlas.server.app` OpenAPI probe
  confirms both new recovery operations are mounted.
- Snapshot remains generated against FastAPI 0.133.1 (pre-existing env-vs-frozen
  0.141.1 mismatch noted in `par07-d.md`); the version field is excluded from comparison
  by `test_routes_match_frozen_snapshot`.
- No commit/push/merge; the main worktree `D:\Atlas` was not modified by this package
  except this receipt and its evidence logs under `tasks/dsh-parity/.../evidence/`.