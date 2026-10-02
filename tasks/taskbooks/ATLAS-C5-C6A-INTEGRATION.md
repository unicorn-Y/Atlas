# ATLAS-C5-C6A-INTEGRATION：合入已验收 C6A + C5

> C4 已 PASS。C5 与 C6A 都已独立验收 PASS。
> 本波只做安全整合，不开发新功能，不进入剩余 C6。

## 已验收来源

- main / C4 PASS head: `09a5387ce09b569bdd02b53c90d8fd45a37d64db`
- C5 branch: `zcode/c5-models-parallel`
- C5 accepted implementation head: `265c6820f6ec811538bd038dc64118362f6c8ffd`
- C6A branch: `zcode/c6a-lsp-parallel`
- C6A accepted implementation head: `110fdc2f761f0220777dde74555ddabcb02d90d9`

Read:
- `tasks/reviews/ATLAS-C4-EXTENSIONS.review.md`
- `tasks/reviews/ATLAS-C5-ZCODE-PARALLEL.review.md` from C5 branch
- `tasks/reviews/ATLAS-C6A-LSP-CORE-PARALLEL.review.md` from C6A branch
- both result files

## Order

### 1. Integrate C6A first

C6A production files are almost entirely new:
- `core/atlas/lsp/**`
- `core/tests/test_lsp_*.py`
- fake LSP server

Bring the accepted C6A implementation into main without overwriting main task-control files.

Do not copy C6A's `tasks/ZCODE-CURRENT.md` over main.

Run the focused LSP suite once after integration.

### 2. Integrate C5 second

C5 has real overlap with current main. Do **not** blindly merge and take one side.

Preserve both C4/C4R and C5 semantics in shared files, especially:
- `core/atlas/engine/hermes_runtime.py`
- `core/atlas/server.py`
- `backend-adapter/src/types.ts`
- `backend-adapter/src/client.ts`
- `frontend/src/renderer/App.tsx`
- `frontend/src/renderer/store/useAtlasStore.ts`
- `frontend/src/renderer/store/useAtlasStore.test.ts`
- `docs/PARITY.md`
- `docs/plan/CORE-PARITY.md`

C5 model-layer files themselves should come across intact:
- `core/atlas/models/**`
- model credential/cache/reasoning routes/tests
- model settings UI components
- UsagePanel model/cache additions

Preserve C4R features while resolving overlap:
- lifecycle hooks bridge
- PermissionRequest ask/allow/deny behavior
- SubagentStop continuation
- custom-command one-run overrides

Preserve C5 features:
- provider catalog/native Hermes provider routing
- provider-id normalization
- keyring credential pool + cooldown/rotation
- staged reasoning effort
- cache miss diagnostics
- edit/delete models
- C5R alias-aware model edit and no ghost key slots

Do not overwrite `tasks/CURRENT.md` or any main task-control file with ZCode branch copies.

## Integration method

Use whichever is cleanest locally:
- cherry-pick accepted implementation commits and resolve conflicts, or
- rebase a temporary integration branch onto current main then merge it.

Do **not** merge branch history blindly if that would overwrite main control docs.

Use subagents aggressively for conflict review by file group:
- backend engine/server
- backend-adapter
- frontend store/App/model UI
- docs/tests

Use the maximum concurrency the runtime allows; no fixed worker limit.

## Minimal validation

After C6A integration:
- LSP focused suite once.

After C5 integration:
- C5 focused model suites that cover catalog/credentials/routes/reasoning/cache/runtime.
- C4R focused hook/lifecycle/command-overrides tests that touch shared files.
- frontend renderer tsc + Vitest once.
- Vite build once if App/model UI conflict resolution changed frontend production files.

No real model/provider calls.
Backend full pytest is not required for this integration wave unless conflict resolution spreads outside the declared overlap.

## Docs / status

After integration:
- ensure C4 E2–E6 remain ✔
- ensure C5 M1/M2/L8/M5/M6 remain ✔
- mark C6 T8 LSP core as integrated/ready for thin write-path/UI wiring, without claiming the full C6 T8 UX is complete
- preserve VENDORED / THIRD_PARTY notices from C5/C6A as applicable

Write:
`tasks/results/ATLAS-C5-C6A-INTEGRATION.result.md`

Include:
- exact commits integrated from each branch
- conflicts encountered and resolution choice
- shared-file semantic checklist
- focused test results
- resulting main HEAD

Then:
- `tasks/CURRENT.md` → `AWAITING_REVIEW`
- push main
- verify local HEAD == origin/main
- stop; do not enter remaining C6.
