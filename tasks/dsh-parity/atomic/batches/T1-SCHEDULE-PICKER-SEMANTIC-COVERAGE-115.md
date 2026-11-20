# T1-SCHEDULE-PICKER-SEMANTIC-COVERAGE-115 — CSS semantic source coverage

Status: `DONE_SCOPED` for the pinned-source CSS parser extension and the reviewed schedule picker slice. The global Task 1 source inventory remains `INCOMPLETE`; no Atlas parity, visible desktop, or superiority claim is made.

## Batch contract

- **Dependencies:** pinned DSH commit `d743267388641bc76f17c45ce8b4c231aed1d32c`; source-index schema v3 / extractor v18 baseline; T1-114 picker test baseline.
- **Changed Atlas files:** `core/scripts/dsh_capability_audit.py`, `core/tests/test_dsh_capability_audit.py`, `tasks/dsh-parity/atomic/source-index.json`, `semantic-decisions.jsonl`, `atomic-capabilities.jsonl`, `interaction-edges.jsonl`, `batch-queue.jsonl`, `completion.json`, `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`, and this receipt.
- **Read-only pinned DSH sources:** `ClockPicker.tsx` (`663dcca5ad134940bd149de5425597506bd7daf48e274b0da84b5560411eb968`), `ClockPicker.module.css` (`50d4903681f06f7efa41f5ecce302d7adaeab7a299eee3468fead6d3faabbe28`), `DatePicker.tsx` (`8cb1efc82f8788abf0457b4574ce654a94b2ac5a5c9891adc784031fb7eb72a5`), `DatePicker.module.css` (`3c2faf9dcac0813a3c7645894ad4546b18148fe1316244fc9def3f6a3271aab5`), `PickerPopover.tsx` (`655e7c6ae2fc91a47aa847921deeb797c0acb7e3b5958c1a2bff4cbbe6fef529`), `PickerPopover.module.css` (`4a999a92069506cf000313a3111c16995ea87127831be3cd96ce34c42d92bf8d`), `TaskDetail.tsx` (`1278c16b85a509cc66ebc34b90f5729d5fbcec76eb10bdf14f254b78998893db`), and `TaskManagerPage.module.css` (`b9918f78eeae2200c807e92b038c461b85559a56fad3e269b551f2eacd395296`). The shared primitive implementations remain a separate unresolved source batch.

## Finding and implementation

Before this batch, the audit tool treated `.css` files as resources. It did not create semantic units for selectors, declarations, nested rules, or at-rules. Extractor v19 classifies CSS as source and emits deterministic digest-bound units containing selector/at-rule prelude, parent scope, declaration property names and value digests, and source line range. CSS that cannot be structurally closed produces an explicit `css_parse_unresolved` obligation. It does not evaluate imports or claim computed browser style.

The fixed DSH checkout has 219 tracked CSS files. The parser produced 4,584 selector/at-rule rule units and one directive, with zero parser-unresolved files. The full index now reports 14,988 files, 369 components, 418,395 semantic units and 411,335 unresolved units. Every CSS file is source-classified. The increase in unresolved count is expected: newly visible source obligations remain unresolved until reviewed.

This batch added eight stable picker logic/style atoms and six interaction edges. It mapped 130 units: the 92 semantic units from `ClockPicker.tsx`, `DatePicker.tsx`, and `PickerPopover.tsx`; 35 directly consumed picker CSS rules; and three fully reviewed CSS file units. There are 171 unresolved units across the selected source slice. The remaining rules and whole-file review unit in `TaskManagerPage.module.css` remain unresolved; the shared `useAnchoredPosition` and `useDismissOnOutsidePointer` implementation units also remain unresolved because those primitives have other consumers.

## Verification

Legacy extractor red (isolated in-memory copy; repository files not reverted):

```text
python <inline harness execs legacy extractor without CSS suffix/parser> tests/test_dsh_capability_audit.py::test_css_style_rules_are_semantic_units_with_nested_scope_and_declarations
```

Actual result: `1 failed, 5 warnings in 3.16s`, exit 1. The test reached the intended assertion and showed the legacy extractor classified `assets/picker.css` as `resource`, not `source`.

Initial test attempt (harness defect retained):

```text
python -m pytest -q -p no:cacheprovider tests/test_dsh_capability_audit.py::test_css_style_rules_are_semantic_units_with_nested_scope_and_declarations --tb=short
```

Actual result: `1 failed, 5 warnings in 3.64s`, exit 1. This was not a valid product red: the fixture path contained a directory named `fixture`, and `_classify()` correctly applies the test/fixture path rule before suffix classification. The fixture was moved to `assets/picker.css`; the valid legacy red above was then run against an isolated in-memory legacy extractor. This initial failure remains recorded as a fixture-path error.

Pinned stylesheet probe:

```text
PINNED_CSS_FILE_COUNT 219
UNIT_COUNTS {'css_rule': 4584, 'css_directive': 1}
PARSE_UNRESOLVED_FILES 0
```

Collection and full focused audit suite:

```text
python -m pytest --collect-only -q -o addopts= tests/test_dsh_capability_audit.py
43 tests collected in 0.40s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short
43 passed, 5 warnings in 14.62s
EXIT_CODE=0
```

Full pinned-source scan:

```text
python scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan
{"component_count":369,"file_count":14988,"head":"d743267388641bc76f17c45ce8b4c231aed1d32c","mode":"scan","package_manifest_count":369,"semantic_unit_count":418395,"unresolved_semantic_unit_count":411335}
EXIT_CODE=0
```

Ledger reconciliation verified 130 current-head decisions, all source digests matched the regenerated index, and every referenced atom/edge exists. `completion.json` remains `INCOMPLETE`. The pinned 272-test schedule client baseline is from T1-114 and is not represented as Atlas runtime acceptance.

## Next obligations

- Map the shared UI primitive implementations and every consumer, including geometry/error/browser branches.
- Map the Atlas `RemoteTasksPanel` / automation API candidate behavior before claiming an equivalent schedule UI.
- Implement and compare the actual Atlas counterpart in a separate code batch; perform visible browser validation before any UI parity decision.
- Continue all other ready source families. Global source closure and Task 1/2 remain open.

## Rollback boundary

This batch only changes the audit extractor/tests and the listed parity ledgers. Its appended atom/edge/decision rows and `T1-115` queue item may be removed only if the batch itself is rejected. Do not roll back any pre-existing rows, upstream checkout files, prior attempt-isolation changes, or unrelated dirty worktree state.
