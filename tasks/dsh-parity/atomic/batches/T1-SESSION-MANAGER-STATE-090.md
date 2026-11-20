# T1-SESSION-MANAGER-STATE-090 — session identity, projection catalog and reconnect

Status: DONE_SCOPED for source mapping and pinned DSH acceptance.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Reviewed all 130 indexed units in `packages/api/session-controller/src/client/sessions/manager.ts` across the full 877-line file, plus its `Session`, projection-store, remote namespace, notifier, ordered-baseline and lineage collaborators.
- Focused acceptance: `manager.client.spec.ts` and `session.client.spec.ts` (157 collected tests).
- Capability atom `T1-DSH-SESSION-MANAGER-STATE-090`; interaction edges `EDGE-T1-DSH-SESSION-MANAGER-OWNERSHIP-090`, `...-CATALOG-PROJECTIONS-090`, and `...-CONTROL-RECONNECT-090`. Every indexed source unit is digest-bound to the atom and a behavior edge.

## Function and state crosswalk

### Session identity and ownership (manager.ts lines 126–345)

- `resolveTarget` installs retained/direct or catalog-derived subagent addresses before acquisition, rejects an entirely unknown id, and configures a resident Session's parent availability.
- `subagentAddress` prefers retained identity, then non-external parent projection catalog, then listed subagent lineage in unknown mode; an external child does not receive a durable local address.
- `drop` withdraws only the exact expected Session instance before stream disposal, so a replacement cannot be accidentally released. `dispose` marks the manager terminal, aborts projection reads, withdraws identities, and drains all tracked Session stream disposals with repeated `allSettled` passes.
- `get` lazily materializes a Session and reconciles blank/running facts from the authoritative summary or catalog; `createSession` supplies onEngaged and projection-store callbacks. Blankness is monotone under engagement and `retainedIds`/`pruneEngagement` prevent losing facts still held by a resident session or child address.

### Query, projection and mutation catalog (lines 346–639)

- `refreshProjections` single-flights per session, uses an AbortController, distinguishes sequenced/migration-required/absent values, tracks loading/ready/migration-required/error, suppresses obsolete replies after abort, retries failed reads and propagates non-remote exceptions.
- `refreshList` journals list mutations that race the pull, merges an ordered baseline after the first successful catalog load, prevents a pull from reviving removed/running entries, folds mutations into the returned baseline, reconciles resident Session state, and applies partial list projections without clearing absent keys.
- `search` sends literal query plus caller cancellation and returns only items/hasMore. `create` and `fork` preallocate or synchronously publish identities as placeholders; a workspace-attachment error that includes an already-published session id is still represented in the list. `fork` retains lineage and cwd. `rename` updates the title projection without opening history.
- `recordMutation` applies synchronously and journals behind an in-flight list pull. `subscribe`, `getListSnapshot`, and `projectionValues` expose cached/stable immutable-store state without opening a session.

### Live control and Host event reconciliation (lines 640–877)

- `handleControlFrame` distinguishes complete baseline replacement from a sequence-numbered update. `applyListBlock` merges sequenced data by comparable sequence and cached checkpoint hints only into missing keys.
- Addition/removal/status/activity/error handlers update catalog and resident Session state; a removed durable subagent becomes unavailable/stopped rather than disappearing like a normal session, while stale projection reads are aborted and removed.
- `handleConnected` invalidates stale projection cuts and list-generation state, starts a new catalog read, then refetches parent projection baselines while open Session follow streams reconnect independently.
- `buildListSnapshot` derives title, blankness and activity from summaries/projections, flattens lineage, preserves row object identity when unchanged and returns a stable cached list snapshot.
- `applyMutation` is the typed reducer for upsert/placeholder/remove/status/activity/engaged with specific precedence: blank can lower but not re-hide; running does not itself establish durable history; last activity only advances.

## Atlas comparison

Atlas exposes conversation list/create/fork/history/search through `core/atlas/api/conversations_router.py` and session search helpers, but this batch did not demonstrate the DSH client-side SessionManager contract: sequenced projection catalog, list mutation journal during refresh, immutable row identity, durable subagent address retention, Host control baselines or reconnect-generation fencing. Atom and edges remain PARTIAL/OPEN; no parity claim and no Atlas product code changed.

## Verification

Focused command:

```text
pnpm exec vitest run packages/api/session-controller/tests/manager.client.spec.ts packages/api/session-controller/tests/session.client.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 2 passed (2); Tests 157 passed (157); Duration 3.14s`; exit 0.

Full pinned scan:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-SESSION-MANAGER-STATE-090-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 269.25, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`; supervisor exit 0. Post-scan check: 130/130 target units have digest-bound MAPPED decisions, zero missing. Global index is 413,747 total / 407,910 unresolved and `INCOMPLETE`.

This package mapping is not Task 2 desktop or live-model evidence and does not close the global source inventory.
