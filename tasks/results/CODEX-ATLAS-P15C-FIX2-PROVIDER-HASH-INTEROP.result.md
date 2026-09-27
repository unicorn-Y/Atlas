# CODEX-ATLAS-P15C-FIX2-PROVIDER-HASH-INTEROP Result

## Execution

- Starting branch: `main`
- Recorded `BASE_HEAD`: `f0cd84b40a94e3f17263326c5de77f54724526bb`
- Implementation stays within provider hash handling, GitHub source verification, approval preview diagnostics, and focused tests.
- Atlas local hash remains its deterministic case-folded path-order digest. It is no longer described or used as the skills CLI reference algorithm.
- Public hash reference: [vercel-labs/skills `src/blob.ts`](https://github.com/vercel-labs/skills/blob/main/src/blob.ts), `computeSnapshotHash`.
- Provider hash validation runs the skills CLI reference expression through Node `path.localeCompare` and SHA-256. The verifier fails closed when Node is unavailable or its output is invalid. Runtime compatibility therefore requires Node on `PATH` and uses that Node runtime's Intl locale.
- Independent fixture generated with Node v24.18.0 under `zh-Hans-HK` covers lowercase and mixed-case paths, punctuation, nested paths, Unicode paths, and multiple files. Reference digest: `1a63c16047cbab7120e9d76d5c0a5fb131b6c1b800f5d355544af6f31ffea81c`. Atlas deterministic local digest: `6865336dc11ee7d54b30a21c526b900756efdb31bff52dc5d4d5a675712f36e6`. The fixture records per-locale Node reference digests and confirms `sv-SE` ordering differs from `en-US`.

## Provider mismatch handling

- A provider hash mismatch stays recorded as a mismatch and never grants approval.
- Atlas independently resolves the GitHub commit and root tree SHA, rejects truncated trees, fetches text files at the immutable commit, preserves relative paths, and applies the existing safe-path, size, manifest, and security checks.
- If every provider path and content equals the GitHub source, Atlas creates a GitHub-sourced fallback acquisition with the provider hash and reference-computed hash retained in diagnostics and provenance. It has a fresh acquisition ID and must pass a new preview and approval; WARN still requires second confirmation.
- If file sets differ or GitHub cannot be verified, the provider snapshot remains BLOCK. The preview displays the mismatch or verification failure, and approval remains disabled.
- Install provenance records the provider hash, provider reference-computed hash, mismatch flag, GitHub commit revision and root tree SHA, installed local hash, and fallback reason.

## Real provider smoke

- Search: skills.sh `GET /api/search?q=react+best+practices`; status `available`, 20 results. Selected listed result: `vercel-labs/agent-skills/vercel-react-best-practices`.
- Snapshot: skills.sh `GET /api/download/vercel-labs/agent-skills/vercel-react-best-practices`; 76 files.
- Provider hash: `ca7b0c0c6e5f2750043f7f0cd72d16ac4e2abc48f9b5500d047a4b77a2506212`.
- Node reference-computed hash: `3219a1944e404ffc14d1d9d6aef6dd2e3855b81387ee0a044ccbfe14d34c2357`.
- Atlas local computed hash: `3219a1944e404ffc14d1d9d6aef6dd2e3855b81387ee0a044ccbfe14d34c2357`.
- Provider hash mismatch: yes. The same 76 relative paths and contents were independently retrieved from GitHub at commit `063bee94c3f4df8453406c830b0a7df0f2860278`; root tree SHA `f94978e8351f77b2d84911fac5d3dd9d51408af9`; file-set/content comparison: identical.
- Final preview: safe GitHub fallback, `WARN` (`install_command`). A fresh acquisition was approved with warning confirmation and installed through the Skill Center into a temporary test directory. The registered installed hash and provenance hash matched. No production skill directory was written during smoke.

Relative file paths in the provider and GitHub payload:

```text
AGENTS.md
README.md
SKILL.md
metadata.json
rules/_sections.md
rules/_template.md
rules/advanced-effect-event-deps.md
rules/advanced-event-handler-refs.md
rules/advanced-init-once.md
rules/advanced-use-latest.md
rules/async-api-routes.md
rules/async-cheap-condition-before-await.md
rules/async-defer-await.md
rules/async-dependencies.md
rules/async-parallel.md
rules/async-suspense-boundaries.md
rules/bundle-analyzable-paths.md
rules/bundle-barrel-imports.md
rules/bundle-conditional.md
rules/bundle-defer-third-party.md
rules/bundle-dynamic-imports.md
rules/bundle-preload.md
rules/client-event-listeners.md
rules/client-localstorage-schema.md
rules/client-passive-event-listeners.md
rules/client-swr-dedup.md
rules/js-batch-dom-css.md
rules/js-cache-function-results.md
rules/js-cache-property-access.md
rules/js-cache-storage.md
rules/js-combine-iterations.md
rules/js-early-exit.md
rules/js-flatmap-filter.md
rules/js-hoist-regexp.md
rules/js-index-maps.md
rules/js-length-check-first.md
rules/js-min-max-loop.md
rules/js-request-idle-callback.md
rules/js-set-map-lookups.md
rules/js-tosorted-immutable.md
rules/rendering-activity.md
rules/rendering-animate-svg-wrapper.md
rules/rendering-conditional-render.md
rules/rendering-content-visibility.md
rules/rendering-hoist-jsx.md
rules/rendering-hydration-no-flicker.md
rules/rendering-hydration-suppress-warning.md
rules/rendering-resource-hints.md
rules/rendering-script-defer-async.md
rules/rendering-svg-precision.md
rules/rendering-usetransition-loading.md
rules/rerender-defer-reads.md
rules/rerender-dependencies.md
rules/rerender-derived-state-no-effect.md
rules/rerender-derived-state.md
rules/rerender-functional-setstate.md
rules/rerender-lazy-state-init.md
rules/rerender-memo-with-default-value.md
rules/rerender-memo.md
rules/rerender-move-effect-to-event.md
rules/rerender-no-inline-components.md
rules/rerender-simple-expression-in-memo.md
rules/rerender-split-combined-hooks.md
rules/rerender-transitions.md
rules/rerender-use-deferred-value.md
rules/rerender-use-ref-transient-values.md
rules/server-after-nonblocking.md
rules/server-auth-actions.md
rules/server-cache-lru.md
rules/server-cache-react.md
rules/server-dedup-props.md
rules/server-hoist-static-io.md
rules/server-no-shared-module-state.md
rules/server-parallel-fetching.md
rules/server-parallel-nested-fetching.md
rules/server-serialization.md
```

## Healthy provider availability

The live search returned 20 entries. All 17 returned multi-file snapshots were checked against the Node reference hash; none matched, so no live healthy provider payload was available in this search. The current sample remains a mismatch and is never accepted on its provider hash. A passing healthy provider path was separately exercised with a reference-matching test fixture through PASS, fresh approval, installation, and provenance with no fallback.

| External ID | Files | Provider hash | Reference-computed hash |
|---|---:|---|---|
| `vercel-labs/agent-skills/vercel-react-best-practices` | 76 | `ca7b0c0c6e5f2750043f7f0cd72d16ac4e2abc48f9b5500d047a4b77a2506212` | `3219a1944e404ffc14d1d9d6aef6dd2e3855b81387ee0a044ccbfe14d34c2357` |
| `callstackincubator/agent-skills/react-native-best-practices` | 32 | `274533acfb62c0a9dc787700b01dd34d70b7b6976d056e7d126f531d59a76da1` | `f8227b1fd95388e9e817ae455e827a909ddbde6dfcc69ea486b2d0e3f85d5763` |
| `mastra-ai/mastra/react-best-practices` | 28 | `96c8da2184856ccf094e72f1c82a14b063eb36fb8dc5d0ae1bc03d5e0522621c` | `4cf4bf3c9e5022432710c97461c2c469d3833db889e9408e8c359117aa304272` |
| `alleneubank/claude-code/react-best-practices` | 2 | `1ee0c42b8166f8a9132d842f0bc9bba8ec14c980e598cc8ae3bd9667733b5b2a` | `aee15f49f1782b4602ece026533564db85d7c20a1efb1f79b028aa21da3f177a` |
| `software-mansion-labs/skills/react-native-best-practices` | 58 | `d19e6e2f75a7700f317906b02c77c51262e373421bb0e161d9599ec13e93062c` | `0bb7d3af521e5a3f75b54b8768db6bb24861c9062823585c1daa580e471d1a81` |
| `asyrafhussin/agent-skills/react-vite-best-practices` | 29 | `2495ba2e0dbc9bd43bb17a660cc9bc4d70b7b6976d056e7d126f531d59a76da1` | `82994934665a490b227fabdfec3d148b1fa291d77d82ccf978e761b9e1ff6e4c` |
| `vercel-labs/agent-skills/vercel-react-native-skills` | 42 | `41d24eafa7c3d82e270439808f7cfbc4d51aeb2d14f2809a2267c16275784d06` | `2e9088a7333666d8c2833b8ff58bd51b955501c42b4c7244f72b4cbf22dafcc4` |
| `medusajs/medusa-agent-skills/storefront-best-practices` | 28 | `3af524dc3d2da1af3bc55b286f763d59d94314922242883667cc3dde651829f4` | `ce76ccbdfdf2d9ce99851e3bc70ad78f86e48b39a9a7eb3a24ea58bd52a5c995` |
| `giuseppe-trisciuoglio/developer-kit/tailwind-css-patterns` | 9 | `99bba0245457b130d69c3f3cf2cecc38e99dc65e5b1a6fbde5187e211dcd699f` | `6092620c3af955a46ea2b94ca8a40197ac8392e6bbdc8c7515659328b186c770` |
| `deckardger/tanstack-agent-skills/tanstack-query-best-practices` | 39 | `f65f02e6fb787836133aead873f1531febc30e84b4cf0cfb2e62ee7cb6dc5670` | `8e5a7e3cdc6900c3967945658aa277629ba7b5264ddadc017ee2b76359456719` |
| `deckardger/tanstack-agent-skills/tanstack-start-best-practices` | 33 | `99d19b4758dec92b5c2b6059bd67362211ec5b68a9678effb76bc4b0632ccac1` | `8799a83f34c3c0631915f8ddcdccc470d91e8bff05409564679bcd76b5eb0be8` |
| `affaan-m/ecc/remotion-video-creation` | 32 | `d110d98feb9466ceb8619ee41c2c116aaeadf7275c8699941900ae76ad5874f6` | `bc1054b481bf128749aeb5ecacabd6529e87657dfd84c8f3ec0c4c4fd5111daf` |
| `deckardger/tanstack-agent-skills/tanstack-router-best-practices` | 37 | `1b2f8f303dc81f45e51ea0b38b029c3b9727140ceba7c52ddfee84460e534002` | `659549bfcacc5767cd489fcbceb2889247bd38c82f0a37c282da754eb2603f63` |
| `pproenca/dot-skills/zod` | 49 | `0b0027b1b87e11fd4f1c87e027ec731abbcf5d9eadb764e40d423db0a1f53cf1` | `c69b5133b65643317236707f2cd3e521b4fc6e5ee5fd6c6c00cf62a37dfd0144` |
| `pproenca/dot-skills/react-hook-form` | 41 | `9f6249a0e3b73efbe3e49dbb65d8735072e4e99ba2ff6bdd156e303ce52f9489` | `e9881245bb3f993f93c9fce336ca7a517ce39864aa46c95d04238fc5ebc4e4d1` |
| `giuseppe-trisciuoglio/developer-kit/nextjs-performance` | 11 | `394868a7d61c0dd74d0e10759c45b8eef6b54f624cc94619a6964dcac13393b1` | `ea2ac97c0f3a5afe4d0196969840d383a30882b8e00a4da895e4ea6eaa32af09` |
| `delphi-ai/animate-skill/animate` | 14 | `9aaae574ba5ce94ab1d4c60fe9ee9059731865c519cfcf5d6282d200ab1e970f` | `ffe5d0020ae97e7af2eeab79a3cdb2d13da004cc998dff6817b071308923b71f` |

## Verification

- Backend regressions: 95 passed across skill acquisition, registry API, registry, discovery, skills, and agent capability tests.
- Modified-file Ruff: passed for `core/atlas/skills/acquisition.py` and `core/tests/test_skill_acquisition.py`.
- `git diff --check`: passed.
- Frontend tests: 4 files, 13 tests passed.
- Production build: passed; Vite emitted only the existing large-chunk advisory.
- Full `ruff check core` was also attempted and reports existing diagnostics in unmodified core modules. No unrelated files were changed to address them.
- No Skill正文 was included in this result artifact.
