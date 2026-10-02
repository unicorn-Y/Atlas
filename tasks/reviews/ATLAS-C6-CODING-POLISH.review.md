# ATLAS-C6-CODING-POLISH Review

Verdict: **PARTIAL — two small hard gaps remain before C6 can close.**

Reviewed main head:
- `51d14c1`

## Accepted

The bulk of C6 is accepted and must not be reopened:

- T8 LSP core remains the accepted C6A implementation; Atlas added the thin native write-path bridge, events, Changes UI and LSP status UI.
- P1 `/init`: deterministic project scan, managed AGENTS.md section, diff preview, confirmation-before-write and idempotent rerun.
- P2 `/review`: working tree / branch / commit scopes, existing child runtime, read-only reviewer posture, structured findings and review cards.
- long-session work: react-virtuoso virtualization, event batching, newest-page pagination, bounded conversation cache and measured 2000-message benchmark.
- C6 fake-model main-chain E2E is present.
- reported backend full suite: **1290 passed, 9 skipped** before the final narrow review-policy tightening; the final review-policy changes have focused regression coverage.
- renderer/electron typecheck, Vitest, backend-adapter tests and Vite build passed.
- UX polish and screenshots are accepted.

## Blocker 1 — V4A path-less patch bypasses the LSP seam

Current LSP seam in `core/atlas/engine/tool_registry.py` requires `args["path"]`.

Hermes' V4A whole-repository patch mode can call the native `patch` tool without a top-level `path`; therefore:
- `_lsp_pre_write()` returns the skip sentinel;
- no pre-edit diagnostics baseline is taken;
- no post-edit delta is attached/emitted.

This is not merely cosmetic because GPT/Codex-family models use the V4A patch path.

Required:
- for a path-less V4A patch, determine the actual touched file paths from the patch payload/result using the existing Hermes V4A parser/result metadata rather than writing a second patch parser if possible;
- snapshot all touched local files before the patch;
- after success, collect delta diagnostics for each touched file;
- append a compact combined diagnostics block to the tool result and emit the normal per-file `lsp.diagnostics` events;
- preserve the existing single-path write_file/patch behavior;
- SSH remains excluded;
- zero new diagnostics remains silent.

## Blocker 2 — review card does not actually navigate to the finding line

The C6 taskbook requires review findings to support **打开文件/定位行**.

Current `ReviewFindingsCard.tsx` calls Electron `shell.openPath(target)`. It opens the file in the OS default app and only displays a note saying the problem is on line N; no line navigation occurs.

Required:
- the review finding action must open the file in Atlas's own file/code view and position/highlight the finding line (or range start);
- reuse the existing FilesPanel/code preview path instead of creating a second editor;
- if a finding has no line, opening the file alone is acceptable;
- browser/dev mode without Electron must still work through the Atlas internal file view.

## Non-blockers

These are recorded honestly but do not block C6 closeout:
- cold conversation switch occasionally measured 250–350 ms around the 300 ms target; the taskbook allows real measured numbers when timing noise is present;
- real pyright/typescript server smoke was skipped because servers were not installed; missing-server behavior is covered;
- `test_computer_use.py` remains intentionally excluded.

Fix only the two blockers above. Do not reopen /init, /review engine, virtualization, UX polish or the C6A LSP core.
