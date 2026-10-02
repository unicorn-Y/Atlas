# ATLAS-C6A-R1-BASEDPYRIGHT：Python LSP 兼容补齐

Branch: `zcode/c6a-lsp-parallel`

This is a minimal repair only.

## Fix

Current Python LSP discovery supports `pyright-langserver` / `pyright` only.

Add fallback discovery for:
- `basedpyright-langserver`
- `basedpyright`

Keep the same Python LSP adapter/server id. Do not create a second manager or separate basedpyright runtime.

Priority:
1. pyright-langserver
2. pyright
3. basedpyright-langserver
4. basedpyright

If the CLI executable is selected instead of the langserver executable, resolve its sibling langserver the same way the current pyright path does.

Update the Chinese missing hint to state that installing either pyright or basedpyright is sufficient.

## Tests

Only add focused tests for:
1. pyright missing + basedpyright present => valid Python spawn spec
2. both available => existing pyright priority preserved

Run only the directly affected LSP server/availability tests or the smallest file selection that proves this.

Do not rerun the full 66-test suite unless your change unexpectedly spreads.

## Delivery

- append a short R1 note to `tasks/results/ATLAS-C6A-LSP-CORE-PARALLEL.result.md`
- set `tasks/ZCODE-CURRENT.md` to `AWAITING_REVIEW`
- push `zcode/c6a-lsp-parallel`
- report new HEAD
- do not merge main
- do not start the next stage
