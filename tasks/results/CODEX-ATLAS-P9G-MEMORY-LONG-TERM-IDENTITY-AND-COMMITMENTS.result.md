# CODEX-ATLAS-P9G-MEMORY-LONG-TERM-IDENTITY-AND-COMMITMENTS

## Delivered

- Added durable memory types for ordinary facts, user identity, and commitments.
- Personal memories remain review candidates until approved. Identity recall is
  bounded by the existing deterministic context ranking and requires both an
  approved candidate and its original user-authored source message.
- Legacy `personal` facts migrate to identity and are excluded from context when
  their approval or source evidence is unavailable. Candidates without a valid
  user source message cannot be promoted.
- Added explicit English and Chinese commitment extraction. Approved commitments
  have `active`, `fulfilled`, or `cancelled` lifecycle states; status changes
  require a user message and are retained in commitment history.
- Temporary conversation messages remain outside durable memory unless they
  match the existing conservative extraction rules.

## Verification

- `core/tests/test_memory.py -k "not test_message_with_metadata"`: **36 passed**.
- `core/tests/test_memory_quality.py`: **7 passed**.
- `git diff --check`: passed.
- The excluded `TestMessages.test_message_with_metadata` remains the documented
  baseline failure (`KeyError: 'metadata'`) in
  `docs/KNOWN-BASELINE-ISSUES-2026-09-26.md` Issue 4.

## Delivery baseline

- Pulled `origin/main`; implementation started from `c0e3a7225a94dc20a76e836a868bfafd75c5a5b3`.
