# Multi-turn context growth

Same eight-turn conversation, one word per reply, against both harnesses. Only
accumulated history can change the prompt size, so any growth is the harness
carrying its own transcript.

Measured by `core/scripts/omni_multiturn.py`. Atlas figures come from its usage
ledger; DSH figures from `inputTokens + cacheReadTokens` in its `--json` stream,
which is its full prompt (see BENCH-ANALYSIS.md for why that sum, not
`inputTokens` alone).

## Atlas

| Turn | Prompt tokens | of which cached | New this turn |
|---:|---:|---:|---:|
| 1 | 8,039 | 0 | 8,039 |
| 2 | 9,642 | 7,936 | 1,706 |
| 3 | 11,278 | 9,600 | 1,678 |
| 4 | 12,889 | 11,264 | 1,625 |
| 5 | 14,501 | 12,800 | 1,701 |
| 6 | 16,113 | 14,464 | 1,649 |
| 7 | 17,725 | 16,128 | 1,597 |
| 8 | 19,337 | 17,664 | 1,673 |

Growth: **+1,612 tokens per turn**, essentially flat. The cached share climbs from
82% to 91% as the stable prefix gets reused.

## DSH

| Turn | Prompt tokens | of which cached | New this turn |
|---:|---:|---:|---:|
| 1 | 17,376 | 5,632 | 11,744 |
| 2 | 17,388 | 17,152 | 236 |
| 3 | 17,401 | — | 13 |
| 4 | 17,414 | — | 13 |
| 5 | 17,428 | — | 14 |
| 6 | 17,442 | — | 14 |

Growth: **+13 tokens per turn.** DSH's prompt is almost entirely a fixed prefix
that the gateway serves from cache after turn 1.

## What this means — and what it does not

**DSH does keep history.** It answered "PINEAPPLE" correctly when asked on turn 2
of a fresh session (`session-763db6b9`, verified directly). The flat `totalTokens`
is not a memory bug; it is the gateway reporting a cached prefix.

**The two harnesses have different shapes, and the single-turn table hid it:**

- Atlas starts at **8,039** and grows by ~1,600/turn. It reaches DSH's fixed size
  at about turn 8.
- DSH starts at **17,376** and stays there. Its fixed prefix — system prompt and
  tool schemas — is roughly twice Atlas's entire first-turn prompt.

So the single-turn "Atlas uses half the tokens" result is real but **it erodes**.
By turn 8 they are level (19,337 vs 17,442), and past that Atlas would carry more.
Anyone running long sessions should read the single-turn number as a starting
advantage, not a permanent one.

**Cached share is the number that actually matters for cost.** Both systems serve
most of the prompt from cache once warm — Atlas 91%, DSH 99% by turn 2. Actual
billing follows the uncached column, where Atlas adds ~1,600/turn against DSH's
~13. On a long session DSH's cache strategy is cheaper; Atlas's smaller base is
cheaper on short ones.

This corrects an earlier reading in this session that treated the flat DSH curve as
evidence of missing history. It was not — the check that settled it was asking DSH
to recall a word from the previous turn, not reading token counts.

## Not measured

- Cache pricing: the gateway reports `prompt_cache_hit_tokens` but not what it
  charges for them, so "cheaper" above means fewer uncached tokens, not dollars.
- Contexts long enough to force compaction in either system.
- Turns where the assistant replies with more than one word (history growth would
  scale with reply length, not just the fixed +1,600).
