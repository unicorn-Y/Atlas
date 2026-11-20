# T1-ATLAS-TOOLTIP-QUEUE-SYNC-132 — Record executed picker/Tooltip batches

Status: `DONE_SCOPED` for queue synchronization only.

## Batch contract

- **Depends on:** completed receipts T1-116 through T1-131; existing JSONL batch-queue schema.
- **Files changed:** `tasks/dsh-parity/atomic/batch-queue.jsonl`, this receipt and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** add exactly one queue row for each executed batch ID T1-ATLAS-SCHEDULE-PICKER-116 through T1-ATLAS-TOOLTIP-ESCAPE-131; all rows parse, have unique IDs in the new slice, and point to their existing receipt. The rows describe scoped batch status, not source-level parity.

## Implementation

Appended 16 `DONE_SCOPED` records with priorities 138–153, sequential implementation dependencies, changed-file lists, binary acceptance statements, continuation notes and receipt evidence paths. No code, `atomic-capabilities.jsonl`, `semantic-decisions.jsonl`, `source-index.json` or completion claim was changed.

## Verification

```text
python -c "import json; p=r'tasks/dsh-parity/atomic/batch-queue.jsonl'; rows=[json.loads(x) for x in open(p,encoding='utf-8') if x.strip()]; ids=[r['batch_id'] for r in rows]; wanted=[f'T1-ATLAS-TOOLTIP-{x}' for x in ['PIN-118','KEYCAPS-119','NESTED-SUPPRESSION-120','FOCUS-MODALITY-121','PORTAL-122','ANCHOR-COMPOSITION-123','FOCUS-CANCEL-124','MOUSELEAVE-125','PIN-DELAY-126','DEFAULT-DELAY-127','CLICK-WITHDRAW-128','UNPIN-129','INDEPENDENT-TRIGGERS-130','ESCAPE-131']]+['T1-ATLAS-SCHEDULE-PICKER-116','T1-ATLAS-PICKER-ANCHORING-117']; print('PARSED_ROWS',len(rows),'UNIQUE_IDS',len(set(ids)),'MISSING',[x for x in wanted if x not in ids]); print('TAIL',[(r['batch_id'],r['status'],r['priority']) for r in rows[-16:]])"
```

Actual output: `PARSED_ROWS 187 UNIQUE_IDS 155 MISSING []`; the final 16 rows are the intended IDs in order, `DONE_SCOPED`, priorities 138–153. Earlier repeated batch IDs in the queue are existing ready/completion state transitions; each newly synchronized ID appears once.

## Open source-map obligations

`source-index.json` still contains 344 `UNRESOLVED` semantic units across pinned DSH `Tooltip.tsx`, `input-modality.ts` and `tooltip.client.spec.tsx`. This queue repair does not map those units or add atomic capabilities/semantic decisions. That remains OPEN and prevents Task 1/7 completion.

## Rollback boundary

If rejected, remove only the 16 appended queue rows and this receipt/progress entry; retain all implementation source, test evidence, prior queue history and source-index obligations.
