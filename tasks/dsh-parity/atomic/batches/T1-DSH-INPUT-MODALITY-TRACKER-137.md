# T1-DSH-INPUT-MODALITY-TRACKER-137

Status: `DONE_SCOPED` — maps the complete DSH input-modality source module and its client event matrix; focus-ring browser styling remains a separate open lane.

## Production changes

- Added a renderer-wide input tracker with separate `pointerModality()` and `data-input-modality` focus-ring ownership state.
- `pointerdown` publishes pointer ownership. Every keydown resets Tooltip last-input mode to keyboard; navigation keys transfer focus-ring ownership immediately, while ordinary keys do so only when focus moves to a different element. Composition clears pending key origin without transferring focus-ring ownership. Window blur clears pending origin.
- `main.tsx` imports the tracker at renderer startup. `Tooltip.tsx` reads its shared pointer-last-input state instead of maintaining a private listener.
- Added an unlayered pointer-owned selector that changes only outline color for noneditable `:focus-visible` elements. Editable fields and non-outline paint remain untouched.

## DSH mapping and limits

- All 14 source semantic units from `packages/client/ui-primitives/src/input-modality.ts` and all 62 client-test semantic units from `input-modality.client.spec.ts` are linked to this atom; eight were already mapped by T1-134 and 68 were newly resolved here.
- Atlas tests mirror the upstream modality transition cases and add an explicit composing-key split assertion for Tooltip versus focus-ring policy.
- The DSH `ui-theme` focus CSS and browser `focus-rings.e2e.ts` are not mapped/verified by this batch. happy-dom and static CSS contract evidence do not establish browser paint or packaged Electron behavior.

## Verification

The style contract was red before the CSS rule existed:

```text
npm test -- src/renderer/styles/styleContracts.test.tsx -t "suppresses pointer-owned focus outlines"
1 failed, 3 skipped; selector absent and matcher received empty string; exit code 1
```

Green event-state matrix:

```text
npm test -- src/renderer/ui/inputModality.test.ts
Test Files  1 passed (1)
Tests       11 passed (11)
Duration    1.27s
exit code   0
```

Green style contract:

```text
npm test -- src/renderer/styles/styleContracts.test.tsx
Test Files  1 passed (1)
Tests       4 passed (4)
Duration    269ms
exit code   0
```

Tooltip regression suite:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
Test Files  1 passed (1)
Tests       23 passed (23)
Duration    1.52s
exit code   0
```

Typecheck:

```text
npx tsc --noEmit -p tsconfig.renderer.json
exit code 0; no TypeScript diagnostics
```

Full audit:

```text
python core/scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan
{"component_count": 369, "file_count": 14988, "head": "d743267388641bc76f17c45ce8b4c231aed1d32c", "mode": "scan", "package_manifest_count": 369, "semantic_unit_count": 418395, "unresolved_semantic_unit_count": 411224}
exit code 0
```

Global completion remains `INCOMPLETE`; unresolved units reduced by 68 from 411292.
