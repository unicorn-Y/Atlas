# T1-DSH-INPUT-MODALITY-ANY-KEY-134

Status: `DONE_SCOPED` — closes the 8 named semantic units for Tooltip last-input modality only.

## Change and boundary

- DSH `input-modality.ts:39-44` clears `pointerModality` on every keydown before its IME-composition early return. Atlas previously ignored composing keydowns, leaving `pointerWasLastInput` true and suppressing a subsequent keyboard-focused Tooltip.
- The focused regression first failed on that sequence; Atlas now clears Tooltip last-input modality on every keydown.
- Eight exact DSH units (three source units plus five units from the upstream all-keys test) are MAPPED. Other shared input-modality behavior, especially focus-ring navigation ownership, remains unresolved.
- The DSH test's key list covers ordinary keys, not an explicit composing key. The composing behavior is evidenced by the DSH handler ordering and the new Atlas-specific test; it is not misattributed to the upstream test assertion.

## Verification

Valid red before production fix:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx -t "returns tooltip focus to keyboard modality after a composing key"
FAIL: 1 failed, 19 skipped; assertion expected tooltip node not to be null but received null (Tooltip.test.tsx:299); exit code 1
```

Green focused suite:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
Test Files  1 passed (1)
Tests       20 passed (20)
Duration    1.11s
exit code   0
```

Renderer typecheck:

```text
npx tsc --noEmit -p tsconfig.renderer.json
exit code 0; no TypeScript diagnostics
```

Full source audit:

```text
python core/scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan
{"component_count": 369, "file_count": 14988, "head": "d743267388641bc76f17c45ce8b4c231aed1d32c", "mode": "scan", "package_manifest_count": 369, "semantic_unit_count": 418395, "unresolved_semantic_unit_count": 411308}
exit code 0
```

Ledger validation:

```text
TARGET_SOURCE_UNITS 8 INDEXED 8 MAPPED 8 UNRESOLVED 0
```

This focused improvement is not a claim of complete input-modality or Tooltip parity, packaged desktop verification, or global superiority.
