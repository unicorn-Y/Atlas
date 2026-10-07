# Package C source and vendoring map

## Fixed upstream object

- Repository: `https://github.com/mastra-ai/mastra`
- Commit: `9c2e4c7cde40a4321112e24affd1750e9be827f9`
- Local clone used for inspection: `C:\Users\25011\AppData\Local\Temp\mastra-memory-v1-9c2e4c`
- Inspection method: `git show 9c2e4c7cde40a4321112e24affd1750e9be827f9:<path>`; clone `HEAD` was not used.

| Pinned source path | Pinned blob | Source symbol / lines | Atlas target |
|---|---|---|---|
| `packages/memory/src/processors/observational-memory/observer-agent.ts` | `37d963b6b7df63d1b44dea7e8a45ed6f3f1a23e6` | `OBSERVER_EXTRACTION_INSTRUCTIONS`, lines 48–302 | `core/atlas/memory/observer_prompt.py::OBSERVER_EXTRACTION_INSTRUCTIONS`; full string retained. |
| same | same | `OBSERVER_OUTPUT_FORMAT_BASE`, line 305; `buildObserverOutputFormat`, lines 317–365 | Static extraction guidance retained as `core/atlas/memory/observer_prompt.py::OBSERVER_OUTPUT_GUIDANCE`, then constrained by `core/atlas/memory/observer.py::OBSERVER_OUTPUT_SCHEMA`. This is an Atlas JSON transport/schema adaptation, not a claim that the complete TS formatter was copied. |
| same | same | `OBSERVER_GUIDELINES`, lines 367–391 | `core/atlas/memory/observer_prompt.py::OBSERVER_GUIDELINES`; full string retained. |
| `packages/memory/src/processors/observational-memory/constants.ts` | `dcc218d9319e21c1f43bbf73b4a6a11a0a7f90d1` | `messageTokens: 30_000`, line 7; `maxTokensPerBatch: 10_000`, line 19 | `core/atlas/memory/observer.py::OBSERVATION_TRIGGER_TOKENS` and `MAX_TOKENS_PER_BATCH`; splitting and flush logic in `MemoryObserver._split_source` and `_start_batch`. |
| `packages/memory/src/processors/observational-memory/thresholds.ts` | `b46e0d2e8142fc812a8c1ccff66d3a7f12cd3d0d` | `getMaxThreshold` line 8; `calculateDynamicThreshold` line 28; `resolveBufferTokens` line 55 | Atlas uses the pinned 30k/10k defaults above. The context-window-dependent threshold/buffer calculation helpers are not separately ported; this remains an adaptation gap. |
| `packages/memory/src/processors/observational-memory/temporal-markers.ts` | `e5edfd664ada92c93e09b9bf0d433e9c5cb2e70b` | `TEMPORAL_GAP_REMINDER_TYPE` line 7; `insertTemporalGapMarkers` line 68 | Atlas carries capture `occurred_at` and `source_timezone` through source formatting and `_effective_source_time` into DERIVED observations; it does not synthesize Mastra temporal-gap marker messages. Unknown dates remain unknown. This remains a behavioral adaptation gap. |
| `packages/memory/src/processors/observational-memory/observational-memory.ts` | `d9070733c13205ae316d212ed735d30895777b76` | async buffer/flush and observer setup, lines 648–804; `maxRetries` at 687; `maxTokensPerBatch` at 700–701 | `MemoryObserver.add_messages`, `resume`, `pending_sessions`, `_start_batch`, `ack_batch`; persistent queue/batch/watermark operations in `core/atlas/memory/outbox.py`. Runtime hook and HTTP ACK scheduling remain B-owned. |
| `packages/memory/src/processors/observational-memory/retry.ts` | `0d10609a4666c9be009c56df834c84409ac52289` | `RETRY_CONFIG`, lines 16–26; retryable status checks, lines 102–113; backoff helper, lines 192–198 | `MemoryObserver._complete_with_retry` / `_retryable`; 8 retries, 1s initial delay, factor 2, 120s maximum, ±20% jitter, and 408/425/429/5xx/network retry categories. |
| repository `LICENSE.md` | `e1b6e4b6455a882dbbf66ee0b13101ec584d5e63` | Apache License 2.0 text | Copied verbatim to `core/atlas/memory/vendor/mastra/LICENSE.md`; its Git blob hash is identical to the pinned upstream blob. |

## Explicit formatter adaptation

`buildObserverOutputFormat` also inserts the runtime `<current-task>` and `<suggested-response>` continuation sections (source lines 319–333, interpolation at line 360). Those sections belong to Atlas S6 continuation handling and are not part of S2 Observer's structured extraction input. They are intentionally not copied into the S2 schema or prompt. The target therefore preserves the static output guidance but does not claim whole-function parity for `buildObserverOutputFormat`.

The pinned repository root has `LICENSE.md` and no root `NOTICE` file. A `packages/connect/NOTICE.md` exists elsewhere in the repository and is unrelated to the vendored Observer sources; it was not copied or represented as an Observer notice. No synthetic NOTICE was added.

The upstream prompt constants were independently compared by the controller against the pinned Git objects: extraction instructions (13,931 characters), guidelines (1,650 characters), and static output guidance core (935 characters) match the target strings. The dynamic formatter sections and the threshold/temporal adaptations above remain explicitly outside that equality claim.
