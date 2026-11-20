# T1-DSH-TOOLTIP-ESCAPE-SEMANTIC-133

Status: `DONE_SCOPED` — this receipt closes only the 19 named semantic units in this batch.

## Exact scope

- Added the DSH Tooltip Escape/Tab source contract atom and interaction edge.
- Added 19 digest-bound semantic decisions from `Tooltip.tsx:190-203` and `tooltip.client.spec.tsx:468-491`.
- The three indexed files in this capability slice contain 344 semantic units total: 19 mapped here and 325 still unresolved. `input-modality.client.spec.ts` and `Tooltip.module.css` are not in this three-file denominator.
- The Atlas evidence is focused happy-dom DOM behavior. It does not establish browser ordering or packaged Electron parity.

## Verification

Atlas focused test command:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx

RUN v5.0.4 D:/Atlas/frontend
Test Files  1 passed (1)
Tests       19 passed (19)
Duration    1.19s
exit code   0
```

Renderer typecheck command:

```text
npx tsc --noEmit -p tsconfig.renderer.json
exit code 0; no TypeScript diagnostics
```

Full source index audit command:

```text
python core/scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan
{"component_count": 369, "file_count": 14988, "head": "d743267388641bc76f17c45ce8b4c231aed1d32c", "mode": "scan", "package_manifest_count": 369, "semantic_unit_count": 418395, "unresolved_semantic_unit_count": 411316}
exit code 0
```

Focused ledger validation output:

```text
PATH_COUNTS {'packages/client/ui-primitives/src/Tooltip.tsx': 68, 'packages/client/ui-primitives/src/input-modality.ts': 14, 'packages/client/ui-primitives/tests/tooltip.client.spec.tsx': 262}
THREE_FILE_UNITS 344 TARGET_MAPPED 19 TARGET_UNRESOLVED 325
TARGET_SOURCE_UNITS 19 ALL_TARGET_MAPPED True
GLOBAL_STATUS INCOMPLETE
```

The scanner reduced global unresolved units by 19 (411335 → 411316). No global parity or superiority claim is made.
