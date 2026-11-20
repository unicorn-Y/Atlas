# PAR-09-D2 — Worktree recovery cleanup ownership boundary

- Date: 2026-11-19
- Package: PAR-09-D2 (continues PAR-08-D's rollback/recovery implementation)
- Worktree: `D:\Atlas\.worktrees\zcode-par07-worktree-api-fix`
- Branch: `zcode/par07-worktree-api-fix`
- HEAD: `060071ab2ecf86d41cab90e98160183ce126bc69` (unchanged; no commit/push/merge)
- Pre-task state read: `PAR09-DISPATCH.md` §2, `evidence/par08-d.md`, current
  `workspace_router.py`, `memory/__init__.py` recovery table,
  `tests/test_conversation_worktree_create.py`.

## 1. Baseline (before this package's edits)

The tree already carried PAR-07-D + PAR-08-D uncommitted work:

```
M core/atlas/api/workspace_router.py
M core/atlas/memory/__init__.py
M core/tests/snapshots/routes.json
A core/tests/test_conversation_worktree_create.py
```

Target suite baseline (`par09-d2-baseline.txt`), exit code 1:

```
cd D:\Atlas\.worktrees\zcode-par07-worktree-api-fix\core
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  -o addopts= --tb=short \
  --basetemp=D:\Atlas\.worktrees\zcode-par07-worktree-api-fix\.tmp\par09-baseline2 \
  tests/test_conversation_worktree_create.py tests/test_engine_worktree_pinned_revision.py \
  tests/test_route_snapshot.py
=> 1 failed, 13 passed
```

The single failure is the pre-existing
`tests/test_route_snapshot.py::test_fastapi_lazy_includes_preserve_effective_paths_parameters_and_order`
at `tests/test_route_snapshot.py:403` (`AttributeError: 'APIWebSocketRoute' object has no
attribute 'original_route'`), unchanged from PAR-08-D. `test_routes_match_frozen_snapshot`
passed at baseline and after this package.

## 2. Changes (this package only)

Files changed by PAR-09-D2 (on top of the PAR-08-D uncommitted state):

- `core/atlas/api/workspace_router.py` (~+310 lines)
- `core/tests/test_conversation_worktree_create.py` (~+319 lines; 9 -> 19 tests)

`core/atlas/memory/__init__.py` and `core/tests/snapshots/routes.json` were **not**
changed by this package. No route was added, so the frozen snapshot is unchanged and
`test_routes_match_frozen_snapshot` requires no regeneration.

### 2.1 Canonical managed-path assignment check

`_validate_worktree_target(workspace, conversation_workspace, conversation_id, path,
branch, base_branch)` now proves the recovery target before any mutation:

- `workspace` and `conversation_workspace` are canonicalized with
  `os.path.realpath` (resolves symlinks and Windows junctions) and must be the same
  directory.
- The workspace must not be a filesystem root, and the path must be absolute.
- The expected checkout is exactly
  `<workspace parent>/.atlas-worktrees/<workspace name>/<conversation short id>`,
  where the short id is the existing `WorktreeService.create` rule
  (`conversation_id.replace("-", "")[:8]`). `.atlas-worktrees`, the repository
  directory and the short-id directory are each rejected if they are a symlink,
  junction or other reparse point, and their resolved parents must remain within the
  managed chain.
- The recorded path (normalized absolute) must equal that expected path. Directory
  roots, the workspace/base repository, the managed root, the managed repository root
  and any unmanaged path are rejected with distinct reasons.
- The branch must be exactly `atlas/<short id>` or `atlas/<short id>-<suffix>`
  (the only names `WorktreeService.create` can produce); a foreign branch is refused,
  which also prevents deleting an unrelated local branch.
- `base_branch` must be present, safe, not the branch being deleted, and an existing
  local ref (`HEAD` is accepted as the create fallback).
- If the checkout directory exists and git can report its checked-out branch, it must
  equal the recorded branch; an orphaned checkout whose admin entry is gone cannot
  answer and is not rejected for that reason.

### 2.2 TOCTOU revalidation and deletion boundary

`_cleanup_worktree_residue` has a new signature
`(workspace, conversation_workspace, conversation_id, path, branch, base_branch)`:

- Validation runs before the first destructive call, again immediately before
  `WorktreeService.remove(...)`, again before the orphan `shutil.rmtree`, and again
  before direct `git branch -D` calls.
- The orphan fallback (git's registration disappeared but the directory remains) now
  deletes only the revalidated canonical managed directory. Existence alone is never
  enough; a link-like target is refused and left in place.
- `shutil.rmtree` is never called with the raw record string, only with the canonical
  directory that equals the conversation's assigned path.
- A refusal raises `_WorktreeRecoveryRefusedError` before deleting anything; callers
  keep the recovery record and return it to the caller.

Nested-reparse-point probe: on this Python 3.11.16, `shutil.rmtree` removed a test
worktree containing a junction to an outside directory and the outside target file
survived (`par09-d2-rmtree-junction.txt`). The root-of-checkout link case is still
rejected by validation above.

### 2.3 Route behavior on refusal

- `POST /api/conversations/{id}/worktree/recovery`: 409 with
  `detail.status = "recovery_refused"`, `detail.reason` (specific reason),
  `detail.recovery` (unchanged row), `detail.message` stating cleanup was refused
  before any further deletion and the record was kept.
- `POST /api/conversations/{id}/worktree` retry while an unsafe record exists: 409
  `recovery_refused`, message states cleanup was refused, no new worktree was created,
  and the recovery row was kept; the record survives.
- Create rollback path (`record` failure): a refused cleanup is reported as 500
  `rollback_failed` with `cleanup_error = "ownership check refused: ..."` and
  `cleanup_refused = true`; the 500 text still says the worktree has NOT been removed.
- No generic deletion endpoint or helper was introduced. Only the existing
  create-rollback/retry and explicit-recovery paths call the cleanup function.

## 3. Boundary rejection matrix (observed over real routes, real MemoryStore, real temp Git repos)

All cases use `httpx.ASGITransport` against the real `workspace_router` and a real
`MemoryStore`; worktrees are real `git init -b main` repositories. Every refusal below
asserts: HTTP 409 `recovery_refused`, non-empty specific `reason`, the recovery row is
still readable from `MemoryStore`, and the targeted files/directories were not deleted.

| # | Scenario | Reason fragment observed | Files / Git state after |
|---|---|---|---|
| 1 | record path = filesystem root (`C:\`) | `filesystem root` | repo `README.md` intact; record kept |
| 2 | record path = conversation workspace / base repo root | `conversation workspace (base repository)` | `README.md` intact; record kept |
| 3 | record path = workspace parent | `not the managed worktree assigned` | record kept |
| 4 | record path = managed root (`<parent>/.atlas-worktrees`) | `managed worktree root` | record kept |
| 5 | record path = managed repository root (`.../.atlas-worktrees/<repo>`) | `managed repository root` | record kept |
| 6 | existing unmanaged dir, not in `git worktree list` (old code's orphan `rmtree` path) | `not the managed worktree assigned` | `victim/keep.txt` intact; worktree count still 1; record kept |
| 7 | managed-looking path under a different repository | `not the managed worktree assigned` | other dir `keep.txt` intact; record kept |
| 8 | recovery row workspace != conversation workspace | `does not match the conversation workspace` | other dir `keep.txt` intact; record kept |
| 9 | other conversation's real worktree + branch | `not the managed worktree assigned` | B worktree dir and branch intact; A record kept |
| 10 | own path + other conversation's branch | `is not assigned to conversation` | B branch intact; record kept |
| 11 | own path/branch + nonexistent base | `ghost-base' does not exist` | record kept |
| 12 | base_branch equals the branch to delete | `equals the branch to delete` | record kept |
| 13 | checkout at assigned path is on another branch | `checked out on branch` (+ actual branch name) | checkout dir and actual branch intact; record kept |
| 14 | assigned worktree path is a symlink/junction to an outside dir | `link or junction` | outside `keep.txt` intact; link still present; record kept |
| 15 | `.atlas-worktrees` itself is a symlink/junction to an outside root | `managed worktree root is a link or junction` | outside `keep.txt` intact; link still present; record kept |
| 16 | create retry while record points at an unmanaged dir | `not the managed worktree assigned`; message `no new worktree was created` | victim `keep.txt` intact; worktree count 1; conversation `worktree_path` empty; record kept |

Positive paths re-verified in the same run: normal create -> status -> merge -> delete;
managed residue recovery after a simulated remove failure; explicit recovery; and the
Git-unregistered managed orphan (admin entry manually removed) still cleans up because
it passes the same canonical/assignment validation (`test_retry_clears_orphaned_...`).

## 4. Commands, exit codes, results

All commands run from the worktree's `core/` with
`PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, `-o addopts=`, and a
`--basetemp` under `D:\Atlas\.worktrees\zcode-par07-worktree-api-fix\.tmp\`.

| Command | Exit | Result | Log |
|---|---|---|---|
| baseline 3-file suite | 1 | 1 failed, 13 passed (pre-existing snapshot-lazy failure) | `par09-d2-baseline.txt` |
| `pytest ... tests/test_conversation_worktree_create.py` after implementation | 0 | 9 passed | `par09-d2-impl1.txt` |
| same after adding boundary tests | 0 | 19 passed | `par09-d2-impl2.txt` |
| same after exception rename/trailing newline | 0 | 19 passed | `par09-d2-impl3.txt` |
| same after refusal-message wording change | 0 | 19 passed | `par09-d2-impl4.txt` |
| final 3-file suite | 1 | **23 passed, 1 failed** (same baseline failure) | `par09-d2-final.txt` |
| `pytest ... tests/test_route_snapshot.py::test_routes_match_frozen_snapshot` | 0 | **1 passed** | `par09-d2-snapshot-match.txt` |
| boundary subset `-k "refuses or retry"` (`-v`) | 0 | **11 passed, 8 deselected** (includes the pre-existing managed-orphan retry) | `par09-d2-matrix.txt` |
| `pytest ... tests/test_backend_parity_wave2.py -k worktree` | 0 | 6 passed, 16 deselected | `par09-d2-regress-worktree.txt` |
| `pytest ... tests/test_memory.py` | 0 | 16 passed | `par09-d2-regress-memory.txt` |
| `python -m pytest ... --collect-only` (19 node ids) | 0 | 19 tests collected | `par09-d2-collect.txt` |
| `python -m ruff check` on both changed files | 1 | 182 findings, all pre-existing categories; new-code-only item is the inherited `except Exception`/long `show-ref` line pattern already present in the file. Not a test blocker. | `par09-d2-ruff.txt` |
| AST audit of handler statement depth and `rmtree` call chain | 0 | final success returns are `direct` (create) / `AsyncWith` (recovery); the only worktree `rmtree` is nested inside the orphan branch of `_cleanup_worktree_residue` | `par09-d2-ast-check.txt` |
| nested-junction `shutil.rmtree` probe | 0 | outside target survived | `par09-d2-rmtree-junction.txt` |

Exact final command:

```
cd D:\Atlas\.worktrees\zcode-par07-worktree-api-fix\core
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  -o addopts= --tb=short \
  --basetemp=D:\Atlas\.worktrees\zcode-par07-worktree-api-fix\.tmp\par09-final \
  tests/test_conversation_worktree_create.py tests/test_engine_worktree_pinned_revision.py \
  tests/test_route_snapshot.py
```

For completeness, the baseline taxonomy is the same as PAR-08-D: 23 = 19 worktree tests
+ 2 pinned-revision tests + 2 route-snapshot tests; the one failure is only
`test_fastapi_lazy_includes_preserve_effective_paths_parameters_and_order`.

## 5. Unverified boundaries / notes

- A genuine OS-level Windows `Permission denied` file lock was not reproduced; cleanup
  failures are injected by monkeypatching `WorktreeService.remove`, as in PAR-08-D.
- There remains a check-then-act window between the final link/identity check and
  `git worktree remove` / `shutil.rmtree` (Windows has no dirfd-style atomic handle).
  Mitigation is canonical paths, exact assigned-path equality, and revalidation
  immediately before each destructive step; this is not a claim of lock-free atomicity.
- Reparse points nested *inside* a legitimate worktree checkout are not individually
  audited during orphan `rmtree`; the probe above shows Python 3.11's `shutil.rmtree`
  does not traverse a nested junction, and POSIX symlinks are unlinked, but this is not
  a formal cross-platform guarantee for future Python versions.
- Recovery workspace is required to equal the conversation workspace. If the
  conversation workspace row itself was changed after the failed create, recovery will
  refuse (truthfully) and require manual reconciliation; this is intentional.
- The GET recovery route still reports `worktree_exists` from the recorded path with a
  plain `exists()`; it is read-only and does not validate ownership. Only the POST
  create/recovery paths are destructive.
- As in PAR-08-D: no frontend caller, no cascade delete of recovery rows when a
  conversation is deleted, multi-process create race still guarded only by an
  in-process `asyncio.Lock`.
- No commit/push/merge; `D:\Atlas` main worktree was not modified by this package
  except this receipt and `evidence/par09-d2-*` logs.