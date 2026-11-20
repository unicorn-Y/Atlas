# T1-DSH-TOOLTIP-OUTSIDE-POINTER-135

Status: `DONE_SCOPED` — this closes only the outside-pointer path named below.

## Change and boundary

- Pinned DSH source calls `useDismissOnOutsidePointer(anchor, openOnClick && visible, dismiss, bubble)`. Atlas had attached its equivalent only while `pinned`, so an `openOnClick` tooltip opened through keyboard focus survived an outside pointerdown.
- The first test draft asserted on Radix's hidden `role=tooltip` description node, so it was not accepted as a red result. The assertion was corrected to the rendered `.pop`; that valid red showed the visible bubble remained after outside pointerdown.
- Atlas now attaches outside-pointer dismissal whenever the tooltip is visible and `openOnClick` is enabled. Its root and bubble containment checks remain intact.
- Thirteen exact DSH units are linked to this atom. One Tooltip call-site unit was already mapped in T1-133; 12 previously unresolved units were newly mapped. Portal-inside behavior for this focus-open path remains explicitly open.

## Verification

Valid red before production change:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx -t "dismisses a focus-open click-enabled tooltip on outside pointer input"
FAIL: 1 failed, 20 skipped; the visible .pop remained after outside pointerdown; exit code 1
```

Green focused suite:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
Test Files  1 passed (1)
Tests       21 passed (21)
Duration    1.09s
exit code   0
```

Renderer typecheck and scoped diff check:

```text
npx tsc --noEmit -p tsconfig.renderer.json
exit code 0; no TypeScript diagnostics
git diff --check -- frontend/src/renderer/ui/Tooltip.tsx frontend/src/renderer/ui/Tooltip.test.tsx
exit code 0
```

Full source audit:

```text
python core/scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan
{"component_count": 369, "file_count": 14988, "head": "d743267388641bc76f17c45ce8b4c231aed1d32c", "mode": "scan", "package_manifest_count": 369, "semantic_unit_count": 418395, "unresolved_semantic_unit_count": 411296}
exit code 0
```

Twelve newly resolved units changed the global unresolved count 411308 → 411296; the thirteenth unit was already linked to T1-133. Global completion remains INCOMPLETE and no browser/Electron or full-tooltip parity claim is made.
