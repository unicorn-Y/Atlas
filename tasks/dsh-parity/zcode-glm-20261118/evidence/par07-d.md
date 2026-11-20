# PAR-07 Worker D — Independent acceptance review: conversation worktree POST

Date: 2026-11-19
Baseline: `060071ab2ecf86d41cab90e98160183ce126bc69`
Reviewed: `D:\Atlas\.worktrees\zcode-exec06-worktree-api`, branch `zcode/exec06-worktree-api`
Change shape (`git status --short`): `M core/atlas/api/workspace_router.py`,
`M core/tests/snapshots/routes.json`, `A core/tests/test_conversation_worktree_create.py`
(+71 / snapshot regen / +161).

**Verdict: NOT MERGEABLE — one blocking integration defect.**
The new POST's happy path works and its 404/409/400/500-rollback behaviour checks out,
but it overwrites `conversation.workspace` with the worktree path. The pre-existing
merge and delete routes treat `conversation.workspace` as the *base repository root*,
so an API-created conversation can no longer be merged or deleted through the existing
API. Real HTTP reproduction below; one DELETE attempt left the worktree administratively
removed but the directory present and the conversation still pointing at it.

---

## Boundary notes

- Reviewed worktree and `D:\Atlas` main were read-only. No edits, commits, pushes, merges.
  `git status --short` in the reviewed worktree before and after review: same 3 entries.
- Baseline/regression tests ran in a new isolated worktree I created at
  `D:\Atlas\.worktrees\zcode-par07-worktree-audit` (detached at `060071ab`), into which I
  copied only the 3 reviewed files. That worktree was removed after the review; all
  outputs are reproduced in this receipt.
- Real backend ran on `127.0.0.1:18765` with:
  `ATLAS_DATA_DIR=<audit>\.par07\atlas`, `HOME`/`USERPROFILE`/`APPDATA`/`LOCALAPPDATA`/
  `HERMES_HOME`/`ATLAS_SKILLS_HOME` redirected under `<audit>\.par07`, scheduler disabled,
  tools auto-start empty, `ATLAS_API_TOKEN=` (loopback requests, no Origin → trusted).
  Server log confirms private paths:
  `config.loaded path=...\.par07\atlas\config\atlas.toml` and
  `memory.init db=...\.par07\atlas\data\atlas.db`; zero ERROR/Traceback lines.
  No user data, `data/memory/**`, credentials or other authors' files touched. All temp
  data removed afterwards; backend killed (port 18765 refused connections).
- Evidence diff `zcode-exec06-worktree-api.diff` matches the reviewed change: 3 files,
  new endpoint/lock/test present.

---

## Commands, exit codes, outputs

### 1) Reproduced author's unit tests (audit worktree, reviewed files copied in)

```
cd D:\Atlas\.worktrees\zcode-par07-worktree-audit\core
python -m pytest -q -p no:cacheprovider tests/test_conversation_worktree_create.py tests/test_engine_worktree_pinned_revision.py
```

Exit 0. Output tail: `8 passed, 5 warnings in 7.72s`.
This confirms the author's `exec06-worktree-api-runs.txt` result, but these are direct
handler calls (`SimpleNamespace(memory=memory)`), not HTTP/route/DI tests.

### 2) Baseline snapshot drift (pristine 060071ab, before copying reviewed files)

```
cd D:\Atlas\.worktrees\zcode-par07-worktree-audit\core
python -m pytest -q -p no:cacheprovider tests/test_route_snapshot.py -x --tb=short
```

Exit 1: `1 failed, 7 warnings in 11.48s`; `test_routes_match_frozen_snapshot`
`assert actual == expected` fails (build/routes/components differ).
Lazy-include test alone: `AttributeError: 'APIWebSocketRoute' object has no attribute
'original_route'` at `tests/test_route_snapshot.py:403` — an installed-FastAPI
incompatibility, pre-existing.

### 3) Snapshot after the reviewed regeneration

```
python -m pytest -q -p no:cacheprovider tests/test_route_snapshot.py --tb=short
```

Exit 1: `1 failed, 1 passed, 7 warnings in 11.07s`.
`test_routes_match_frozen_snapshot` PASSES; `test_fastapi_lazy_...` still fails with the
same baseline `APIWebSocketRoute` error. So the large snapshot diff is legitimate
pre-existing drift, not this change.

Structural baseline-vs-reviewed snapshot diff (Python json comparison, exit 0):

- operations old/new: 837 / 858; **21 added, 0 removed, 0 changed**.
- 20 of the additions are pre-existing routes missing from the frozen baseline, e.g.
  `/api/commands/invoke` (`usage_router.py:370`),
  `/api/runtime/runs/{run_id}/events` (`runtime_ws_router.py:21`),
  `/api/conversations/{conversation_id}/explain` (`conversations_router.py:516`),
  `/api/plugins/{name}/patches` (`plugins_router.py:219`), plus permissions/engine-goals/
  export/timeline/refresh-title/plugins-config/runtime-events etc.
- the 21st is exactly the reviewed route:
  `('POST','/api/conversations/{conversation_id}/worktree')`.
- `shadow_order` identical; components: 156→159 schemas, additions
  `PresetRequest`/`ResumePayload`/`RevokeRequest`, one changed `PayloadSpec`
  (`agent_preset_id`, present in baseline code at `automation_router.py:114`).
- build changed from `fastapi_version 0.141.1` to `0.133.1` (installed here is 0.133.1).
  This is the pre-existing environment-versus-frozen-snapshot mismatch, but note the
  regenerated snapshot is now pinned to this env; confirm the canonical FastAPI version
  before merge if CI uses 0.141.1.

### 4) Live app wiring / OpenAPI

Server health: `GET /api/health` → HTTP 200
`{"status":"ok",...,"component_errors":{}}`.
Live `/openapi.json`: path `/api/conversations/{conversation_id}/worktree` exposes
`['delete','get','post']`; POST `operationId` is
`create_conversation_worktree_api_conversations__conversation_id__worktree_post`.
Snapshot has the same POST entry (optional body: `anyOf object|null`, 200 + 422).
Workspace router is in the app mount tuple (`application.py:91,204`).

### 5) Real HTTP acceptance (temp git repo + private DATA_ROOT)

Consolidated script (inline `python - <<'PY'`, exit 0; `ACCEPTANCE SCRIPT OK`):

```
CREATE 200 {"worktree_path":"...\.par07\accept2\.atlas-worktrees\repoA\aade9671",
 "worktree_branch":"atlas/aade9671-final-check","base_branch":"main",
 "workspace":"...\.par07\accept2\.atlas-worktrees\repoA\aade9671"}
STATUS 200 {"path":"...\aade9671","branch":"atlas/aade9671-final-check",
 "base_branch":"main","ahead":0,"behind":0,"dirty":false,"changed_files":[]}
CONV workspace==worktree_path: True | branch: atlas/aade9671-final-check | base: main
SECOND CREATE 409 {"detail":"Conversation already has a worktree"}
MERGE after POST 400 {"detail":"fatal: 'main' is already used by worktree at '...\accept2\repoA'"}
DELETE after workspace=base 200 {"status":"removed"} | fields cleared: True | workspace: D:/.../accept2/repoA
DELETE directly after POST 400 {"detail":"error: failed to delete '...\repoA\13471046': Permission denied"}
  worktree admin entries after failed delete: []
  directory still exists: True
  conversation still points at worktree: True
```

Happy path assertions that passed: branch == `atlas/<id8>-final-check`; worktree dir
exists and `.git` is a file; `git worktree list` count 2; GET status path/branch match;
conversation `workspace == worktree_path == created path`, branch/base fields set;
second POST 409 without a second tree. `POST` with no body also returns 200 with default
branch `atlas/<id8>`.

Error matrix over real HTTP (exit 0; expected statuses observed):

```
2nd POST worktree -> 409 {"detail":"Conversation already has a worktree"} (tree count stays 2)
POST missing conversation -> 404 {"detail":"Conversation not found"}
POST no workspace -> 409 {"detail":"Conversation has no workspace"}
POST non-git workspace -> 409 {"detail":"Workspace is not a git repository"}
POST missing workspace -> 409 {"detail":"Conversation workspace is missing"}
POST invalid base_branch -> 400 {"detail":"fatal: invalid reference: no-such-ref"} (no tree/branch leak)
POST name "../../escape" -> 200; path stayed under .atlas-worktrees/repo2/<id8>;
  branch atlas/<id8>-escape (path traversal sanitized)
```

### 6) 500 rollback at HTTP/ASGI level (not just direct handler)

Inline FastAPI app including `workspace_router.router`, dependency override returning
`AppServices(memory=FailingMemory(real MemoryStore))` where `update_conversation` returns
False, real `WorktreeService`, `TestClient` (exit 0):

```
POST status: 500
POST body: {'detail': 'Conversation worktree was created but could not be recorded; it has been removed.'}
worktree count: 1
branches: ['main']
worktree dirs: ['repo']
```

Rollback removes the linked worktree and its branch; only the empty parent dir remains.
(Caveat: the handler swallows rollback failure at `workspace_router.py:1660-1664` yet
still claims "it has been removed".)

### 7) Existing behaviour / model-tool / auto-cwd checks

- Existing worktree API parity tests (workspace kept = base root):
  `python -m pytest -q -p no:cacheprovider tests/test_backend_parity_wave2.py -k worktree`
  → exit 0, `6 passed, 16 deselected`. These exercise run-request worktree creation,
  GET status and DELETE successfully.
- Model-facing tool EXISTS at baseline:
  `python -c "from atlas.tools.workspace_workflows import workspace_workflow_schemas; ..."`
  → schema list includes `workspace_worktree_manage`. Registered unconditionally in
  `atlas/engine/kernel/tools.py:526-528`; dispatched in `atlas/engine/kernel/loop.py:3452-3469`;
  create/remove implemented at `atlas/tools/workspace_workflows.py:612-697`.
- Run-request auto-worktree/cwd EXISTS at baseline: `run_drive.py:2233-2262`
  (`worktree` body → create → `WorktreeCreate` hook → metadata → run cwd = worktree).
- No product caller of the new POST: `backend-adapter/src/client.ts:284-293` has GET,
  merge, DELETE only; no create POST. `frontend/src` has no POST call site; the UI's
  worktree flow uses the run-request `worktree` field. The new endpoint is API-only,
  with no model-tool or UI wiring.

---

## Blocking finding

**B1. `workspace_router.py:1647` overwrites the base-workspace invariant.**

`workspace=info["worktree_path"]` moves `conversation.workspace` into the worktree. All
existing consumers assume `workspace` is the base repo root:
`merge_conversation_worktree` passes `Path(conv["workspace"])` as the repo root
(`workspace_router.py:1697`), `delete_conversation_worktree` does the same
(`workspace_router.py:1813`), and after a successful DELETE it clears only
`worktree_path/worktree_branch/base_branch`, not `workspace` (`workspace_router.py:1826`).
Established paths deliberately keep `workspace=base` and persist the worktree separately:
model tool `workspace_workflows.py:656-658`, run auto-worktree `run_drive.py:2259-2261`
(`workspace=str(workspace_path)` = base), fork `conversations_router.py:2158-2166`
(`workspace=checkpoint_root`). The new POST is the only writer that breaks this invariant,
and the new tests enshrine it (`test_conversation_worktree_create.py:76`, and the cleanup
after `:158`).

Observed impact (real HTTP, same server):
- `POST .../worktree/merge` → 400 `fatal: 'main' is already used by worktree at '<base>'`
  because merge tries to `git checkout main` inside the worktree. No merge happens.
- `DELETE .../worktree?force=true` → on this Windows host, 400
  `error: failed to delete '<worktree>': Permission denied`; git had already removed the
  worktree admin entry (`.git/worktrees` empty) while the directory remains and the
  conversation still records the worktree. GET status then becomes unreliable (in my
  layout it walked up to the enclosing audit repo and reported unrelated changes).
  On a platform where the rmdir succeeds, DELETE would still leave `workspace` pointing
  at the deleted path, so the next run fails "workspace directory does not exist".
- Only manual repair (`PUT workspace=<base>` first) makes DELETE return 200 and clear the
  fields, which isolates the cause.

Fix direction: persist only `worktree_path/worktree_branch/base_branch` and leave
`workspace=base` (match the existing tool/run/fork paths), or store the base root
explicitly and update merge/delete/status consumers; add an HTTP-level test that
POST → GET → merge → DELETE works on the same conversation.

## Non-blocking findings

1. **Evidence accuracy.** `exec06-worktree-api-20261118.txt` §A/§D says creation only
   happens at fork and the model tool is "blocked/unwired". At baseline
   `workspace_worktree_manage` is a registered, dispatched model tool that creates a
   conversation worktree, and run requests can auto-create one. The API fills a REST gap,
   not a model-tool gap; the change adds no model-facing capability and no auto-cwd switch
   for the active run.
2. **Scope / guards.** `name` traversal is safely sanitized (`../../escape` →
   `atlas/<id8>-escape`, deterministic path). But the API bypasses the path guard in the
   existing tool (`workspace_workflows.py:644-655`) and the `WorktreeCreate` hook that
   run auto-worktree runs (`run_drive.py:2247-2257`). With a directory junction at
   `<base>.atlas-worktrees/<repo>`, the API returned 200 and persisted a path outside
   `.atlas-worktrees` (`...\.par07\outside\<id8>`); native symlink creation was blocked by
   the Windows host, so that specific variant was not run. The tool's guard checks
   `is_symlink()` only, so a junction would bypass it too; still worth reusing the guard
   (and an expected-root assertion) in the API.
3. **Snapshot version pin.** Large diff is legitimate pre-existing drift (see §3), but the
   regenerated `fastapi_version` is this executor's `0.133.1` vs frozen `0.141.1`.
4. **Process-local lock.** `_worktree_create_lock` only serialises one process; two backend
   processes can still race (acknowledged in the evidence). Acceptable for single-process
   desktop, not a cross-process guarantee.
5. **Rollback message.** The 500 detail says "it has been removed" even when
   `remove(...)` raised and was swallowed (`workspace_router.py:1660-1664`).
6. **Test coverage.** No TestClient/route test, no POST→GET test, no merge/delete
   compatibility test, and the rollback cleanup assertion at
   `test_conversation_worktree_create.py:141` is a weak conditional/glob check (no branch
   leakage assertion). Tests pass while the integration contract is broken.

## Capability separation (requested)

| Layer | Status after this change |
|---|---|
| API capability | New POST exists and is mounted: create 200, GET status 200, optional body, 409/404/400, 500+rollback. Happy path verified over real HTTP. **But it breaks merge/delete metadata.** |
| Model-facing tool | Already existed at baseline (`workspace_worktree_manage`, registered + dispatched). This change adds/changes nothing; the new POST is not called by any tool. |
| Auto-cwd switching | Already existed at baseline via run-request `worktree` (`run_drive.py:2233-2262`), which creates the tree, runs the current run there, and keeps `workspace=base`. The new POST only changes next-run conversation metadata; no active-run cwd switch and no caller. |

## Merge conclusion

Reject/return for fix. The blocking issue is small (one metadata field and the tests that
assert it) but it breaks existing user-visible merge and delete flows; re-review after the
invariant fix plus an HTTP-level POST→GET→merge→DELETE test. The snapshot regeneration
itself is legitimate pre-existing drift; the new POST is covered in the snapshot and in
the live OpenAPI.