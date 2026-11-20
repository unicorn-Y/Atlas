# T1-DSH-TOOLTIP-PORTAL-INSIDE-136

Status: `DONE_SCOPED` — closes the inside-target behavior for this focus-open Tooltip scenario only.

## Exact scope

- Atlas test exercises a focus-open `openOnClick` Tooltip with both `portal=true` and `portal=false`.
- Pointerdown on the trigger/root and the visible bubble leave it open; pointerdown on `document.body` closes it.
- Seven DSH units are associated with the atom. Three helper units were already mapped in T1-135, and four exact units from the DSH portaled-surface test are newly mapped.
- This is happy-dom DOM evidence. It does not prove browser hit testing, Electron portal layering, or all Tooltip consumer behavior.

## Verification

Focused command:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx -t "keeps focus-open click-enabled content inside for outside pointer checks"
Test Files  1 passed (1)
Tests       2 passed | 21 skipped (23)
Duration    854ms
exit code   0
```

Complete Tooltip suite:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
Test Files  1 passed (1)
Tests       23 passed (23)
Duration    1.10s
exit code   0
```

Renderer typecheck and scoped diff check:

```text
npx tsc --noEmit -p tsconfig.renderer.json
exit code 0; no TypeScript diagnostics
git diff --check -- frontend/src/renderer/ui/Tooltip.test.tsx tasks/dsh-parity/atomic/semantic-decisions.jsonl tasks/dsh-parity/atomic/atomic-capabilities.jsonl tasks/dsh-parity/atomic/interaction-edges.jsonl tasks/dsh-parity/atomic/batch-queue.jsonl
exit code 0
```

Full source audit:

```text
python core/scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan
{"component_count": 369, "file_count": 14988, "head": "d743267388641bc76f17c45ce8b4c231aed1d32c", "mode": "scan", "package_manifest_count": 369, "semantic_unit_count": 418395, "unresolved_semantic_unit_count": 411292}
exit code 0
```

Four newly resolved source units changed unresolved count 411296 → 411292. Global completion remains INCOMPLETE.
