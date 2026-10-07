# Package G source and vendoring map (S4 Reflector)

## Fixed upstream object

- Repository: `https://github.com/mastra-ai/mastra`
- Commit: `9c2e4c7cde40a4321112e24affd1750e9be827f9`
- Local clone used for inspection: `C:\Users\25011\AppData\Local\Temp\mastra-memory-v1-9c2e4c`
- Inspection method: `git show 9c2e4c7cde40a4321112e24affd1750e9be827f9:<path>`; clone `HEAD` was not used.
- License: Apache-2.0 (`core/atlas/memory/vendor/mastra/LICENSE.md`)

| Pinned source path | Pinned blob | Source symbol / lines | Atlas target | Adaptation & notes |
|---|---|---|---|---|
| `packages/memory/src/processors/observational-memory/reflector-agent.ts` | `bcf92d0c4b2f52aaf34daf5e4f7feed66af059db` | `buildReflectorSystemPrompt`, lines 53–125 | `core/atlas/memory/reflector.py::build_reflector_system_prompt` | Instruction ported and adapted: instructs reflection and consolidation of memories, outputting structured operations list (MERGE, SUPERSEDE, ROLLUP_DAY, ROLLUP_WEEK, PROFILE_UPDATE, IMPORTANCE) instead of raw text rewriting. Prohibits DELETE and ungrounded facts. |
| same | same | `COMPRESSION_GUIDANCE`, lines 145–257 | `core/atlas/memory/reflector.py::COMPRESSION_GUIDANCE` | Levels 0–4 ported directly. Tiered progressive compression instructions for reflection retries. |
| same | same | `buildReflectorPrompt`, lines 267–336 | `core/atlas/memory/reflector.py::build_reflector_user_prompt` | Formats candidate observations by ref, date, facet; includes existing profile context and appends active compression guidance. |
| same | same | `parseReflectorOutput`, lines 360–398 | `core/atlas/memory/reflector.py::parse_reflector_output` | Parses LLM text response into structured operations list, handling markdown code fences and JSON normalization. |
| same | same | `validateCompression`, lines 406–412 | `core/atlas/memory/reflector.py::validate_compression` | Adapted for Atlas Memory V1 specification: enforces profile token count <= 600 (`MAX_PROFILE_TOKENS`), paired with sentence-level `validate_traceability`. |
| `packages/memory/src/processors/observational-memory/thresholds.ts` | `b46e0d2e8142fc812a8c1ccff66d3a7f12cd3d0d` | `getMaxThreshold` line 8; `calculateDynamicThreshold` line 28; `resolveBufferTokens` line 55 | `core/atlas/memory/reflector.py::calculate_dynamic_threshold`, `get_max_threshold`, `should_reflect` | Threshold calculation helpers ported; `should_reflect` implements S4 token-saving pre-check (defaults: 5 records or 2000 tokens). |
| `packages/memory/src/processors/observational-memory/retry.ts` | `0d10609a4666c9be009c56df834c84409ac52289` | `RETRY_CONFIG`, lines 16–26; retryable status checks | `core/atlas/memory/reflector.py::MemoryReflector._complete_with_retry` / `_retryable` | Exponential backoff retry loop for ModelRouter calls with status/network error classification. |
