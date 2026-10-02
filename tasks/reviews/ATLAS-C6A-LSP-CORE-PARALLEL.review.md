# ATLAS-C6A-LSP-CORE-PARALLEL Review

Verdict: **PARTIAL — one tiny compatibility fix required.**

Reviewed head:
- `4d8a595f10ced15d1c770c28ec4a74f461bdf118`

## Accepted

The LSP core architecture is accepted:

- Hermes-based async LSP client/service was ported at full scale rather than rewritten as a small custom layer.
- workspace/client reuse, diagnostic freshness tracking, before/after delta filtering and line shifting are present.
- Windows process lifecycle includes graceful shutdown and process-tree cleanup.
- Python/TS/JS routing, missing-server hints, fake LSP coverage and lifecycle tests are present.
- C4/C5 production hot files were not touched.
- reported focused suite: **66 passed**, repeated in a second order.

## Remaining blocker

The taskbook explicitly requires Python support for **pyright / basedpyright**.

Current Python spawn discovery only probes:
- `pyright-langserver`
- `pyright`

It does not probe:
- `basedpyright-langserver`
- `basedpyright`

So a machine with basedpyright installed but not pyright is incorrectly treated as missing Python LSP support.

## Required repair

Keep the existing `pyright` server id and protocol path. Add basedpyright binaries as fallback candidates for the same Python server adapter.

Also update the missing hint so it correctly says either pyright or basedpyright is acceptable.

Add one focused regression proving:
- when pyright is absent and basedpyright is discoverable, Python LSP produces a valid spawn spec;
- pyright remains preferred when both exist.

No other C6A code should be reopened.
