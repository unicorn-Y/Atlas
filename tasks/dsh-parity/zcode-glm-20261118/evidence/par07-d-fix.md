# PAR-07-D follow-up — worktree POST blocking defect fixed

- Date: 2026-11-19
- Reviewer: worker D (`par07-d.md`), fix by main agent
- Reviewed (rejected) tree: `D:\Atlas\.worktrees\zcode-exec06-worktree-api` (branch `zcode/exec06-worktree-api`)
- Fix tree/branch: `D:\Atlas\.worktrees\zcode-par07-worktree-api-fix` (`zcode/par07-worktree-api-fix`, based on 060071ab + copied reviewed files)
- Baseline: `060071ab`; no commit/push/merge; main tree untouched except this receipt.

## Blocking defect (from par07-d.md)

The POST wrote `workspace=info["worktree_path"]`, breaking the established invariant that
`conversation.workspace` is the base repository root. Existing merge/delete routes consume it
as the base (`workspace_router.py` merge/delete), so an API-created conversation could not be
merged (git "already used by worktree") or deleted (worktree admin removed, directory left,
conversation still pointed there). The author's tests enshrined the wrong value.

## Fix

`core/atlas/api/workspace_router.py`:
- `update_conversation` now writes only `worktree_path`, `worktree_branch`, `base_branch`;
  `workspace` stays the base repo root.
- Docstring states the invariant explicitly.
- Return payload keeps `workspace` as the base root (not the worktree path); callers use
  `worktree_path` to address the checkout.
- Lock, 404/409/400/500-rollback behavior, branch naming, and snapshot route unchanged.

`core/tests/test_conversation_worktree_create.py`:
- First test asserts `conversation.workspace == repo` and `result["workspace"] == repo`.
- New `test_created_worktree_stays_mergeable_and_deletable`: create → GET status → merge → delete
  through the existing routes; asserts worktree fields cleared, workspace still base, worktree
  directory removed, branch gone, `git worktree list` back to 1.

## Verification

```
cd D:\Atlas\.worktrees\zcode-par07-worktree-api-fix\core
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider -o addopts= \
  --tb=short --basetemp=.../pytest-resume02-wtfix-final \
  tests/test_conversation_worktree_create.py tests/test_engine_worktree_pinned_revision.py
```
→ **9 passed, EXIT 0** (`evidence/par07-d-fix-runs.txt`).

Route snapshot:
```
pytest tests/test_route_snapshot.py
```
→ `test_routes_match_frozen_snapshot` PASS; `test_fastapi_lazy_includes...` fails identically
at baseline (environment/FastAPI route-class drift), not introduced here.

Diff: `evidence/zcode-par07-worktree-api-fix.diff` (3 files; logic +73, new test 191,
snapshot regeneration as in the rejected branch). **No merge/push.**

## Capability corrections (from D's review)

- Model-facing worktree tool already exists at baseline:
  `core/atlas/tools/workspace_workflows.py:1089-1090 workspace_worktree_manage`,
  registered in `core/atlas/engine/kernel/tools.py` and dispatched at
  `core/atlas/engine/kernel/loop.py:3779-3783`. The earlier F08 claim "no model tool" was wrong
  (searched only `create_worktree`).
- Auto-cwd for a run already exists via run-request `worktree`
  (`core/atlas/api/run_drive.py:2233-2262`), and conversation worktree creation happens there
  and in fork (`conversations_router.py:2158-2166`).
- What this POST adds is an explicit REST creation entry (no UI/client caller yet); it does not
  add a new model tool and does not itself switch a running conversation's cwd.

## Remaining boundaries

- No client/UI caller in `backend-adapter/src/client.ts` or `frontend/src`.
- Multi-process create race still uncontrolled (in-process asyncio lock only).
- Snapshot diff is mostly pre-existing drift (baseline snapshot test already failed); 21 added
  operations = 20 pre-existing + this POST.