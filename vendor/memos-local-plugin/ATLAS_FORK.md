# Atlas fork of MemOS local plugin

Upstream: `@memtensor/memos-local-plugin` 2.0.20 (MemTensor/MemOS, `apps/memos-local-plugin`, Apache-2.0, see LICENSE).
Source here = the published 2.0.20 package sources + `tsconfig.build.json` / `vitest.config.ts` /
`scripts/*.cjs` from upstream `main` (a7367d0), which the npm package does not ship.
A clean build of the unmodified sources reproduced the published `dist/` byte for byte.

## Build

```
npm install --legacy-peer-deps --ignore-scripts
npm run build
```
`--ignore-scripts` skips the native builds: copy `node_modules/better-sqlite3/build` and
`viewer/dist` from an installed copy of the same version (or drop the flag on a machine with build tools).
Atlas' Hermes engine loads it through the junction `engine/plugins/memory/memtensor` →
`vendor/memos-local-plugin/adapters/hermes/memos_provider`.

## Atlas changes (search for "Atlas fork")

| Change | Files |
|---|---|
| Fact-hygiene rules on every knowledge-generation prompt (questions / hypotheticals / web text are not user facts; newer statement wins) | `core/llm/prompts/index.ts` |
| "关于你" fact layer: per-turn LLM extraction of user-stated key/value facts with verbatim-quote evidence, one active value per key, older values kept as history | `core/facts/observe.ts`, `core/storage/migrations/020-user-facts.sql`, `core/storage/repos/user_facts.ts`, `core/pipeline/orchestrator.ts` |
| Current facts injected at the top of every turn's memory context | `core/pipeline/memory-core.ts` |
| `GET /api/v1/facts`, `DELETE /api/v1/facts/:id` | `server/routes/facts.ts`, `agent-contract/memory-core.ts` |

Extraction rules come from Atlas MEMORY-V1 `core/atlas/memory/observer_prompt.py`
(Mastra observer-agent rules + Chinese rules). Real-model smoke 2026-10-10: 7 turns
(statement, question, hypothetical, pasted web text, two changes, allergy) → 6 correct
fact versions, 0 false facts.
