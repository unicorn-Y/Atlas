# PAR-07-A — CSV/TSV preview defect fixes (worker A)

- Date: 2026-11-19
- Worktree: `D:/Atlas/.worktrees/zcode-exec06-csv-preview`
- Branch: `zcode/exec06-csv-preview`
- Baseline: `060071ab2ecf86d41cab90e98160183ce126bc69` (060071ab), unchanged; no commit/push/merge performed.
- Scope: fix two defects in IMPL-3 CSV/TSV preview and add regressions. Electron main untouched. Only this receipt file written outside the worktree.

## 1. Defects fixed

### 1.1 `parseDelimited('""', 'demo.csv')` dropped the record

Root cause: the EOF flush condition was `cell.length > 0 || row.length > 0 || quoted`. A lone empty quoted field produces no characters, no delimiter and a closed quote, so nothing marked the row as present and the record vanished.

Fix in `frontend/src/renderer/shell/panels/csvPreview.tsx`: added a `rowStarted` flag, set when a quoted field opens / a delimiter or ordinary character is consumed, reset by `endRow()`. EOF now flushes when `rowStarted` is true, so `""` yields one row with one empty cell. Empty input still yields zero rows.

### 1.2 First-line delimiter detection misread quoted multi-line first record

Repro: `parseDelimited('"multi\nline";label\n1;2', 'demo.csv')` split the source at the first physical `\n`, saw no comma in `"multi`, defaulted to `,`, and produced a one-column table.

Fix: new `firstLogicalRecord(source)` scans until the first newline/CR **outside** double quotes (skipping `""` escapes); `detectDelimiter` counts candidate separators outside quotes over that whole logical record. `.tsv` still hard-returns tab. The repro now selects `;` and parses `[['multi\nline','label'], ['1','2']]`.

Limits preserved: `MAX_ROWS=500`, `MAX_COLUMNS=64`, `MAX_CELL_CHARS=2000`; truncation flags, ragged-row behavior, quoted separators/newlines/escaped quotes and binary/empty/truncated notices are untouched.

## 2. Files changed (worktree-relative)

| File | Change |
|---|---|
| `frontend/src/renderer/shell/panels/csvPreview.tsx` | new `firstLogicalRecord`; delimiter scan over first logical record; `rowStarted` EOF flush fix (180 lines) |
| `frontend/src/renderer/shell/panels/csvPreview.test.tsx` | +2 regression tests for the exact inputs (99 lines, 8 tests total) |
| `frontend/src/renderer/shell/panels/documentPreviewRegistry.tsx` | unchanged by this pass (already registers `csv`/`tsv` → `CsvFilePreview`) |

`git diff --stat -- frontend/src/renderer/shell/panels/`: **3 files, +281 insertions, 0 deletions** (this is the full IMPL-3 + PAR-07-A diff vs baseline; files remain intent-to-add/unstaged).

## 3. Regression tests added

In `csvPreview.test.tsx`:

- `keeps a lone empty quoted field as one row at EOF` — exact input `""` via `parseDelimited('""', 'demo.csv')`; asserts delimiter `,`, `totalRows === 1`, `rows === [['']]`, `truncated === false`.
- `detects the delimiter from the first logical record across a quoted newline` — exact input `"multi\nline";label\n1;2`; asserts delimiter `;`, `totalRows === 2`, exact rows, and static render contains `分号`, `multi`, `label`, `2 行`.
- Pre-existing comma, TSV, semicolon-outside-quotes, escaped-quote, truncation (500/511), ragged/column-cap, binary/empty/truncated-source tests all remain and pass.

## 4. Exact commands and results

All commands run with worktree frontend as cwd:

```
cd D:/Atlas/.worktrees/zcode-exec06-csv-preview/frontend
npx vitest run src/renderer/shell/panels/csvPreview.test.tsx src/renderer/shell/panels/documentPreviewRegistry.test.tsx src/renderer/shell/panels/FilesPanel.test.tsx
```

Result (vitest 5.0.4, Node v24.18.1): **3 files passed, 15 tests passed, EXIT 0**.

```
csvPreview.test.tsx                 8 tests  passed
documentPreviewRegistry.test.tsx   3 tests  passed
FilesPanel.test.tsx                4 tests  passed
```

Baseline before this pass was 13 tests (csvPreview 6 + registry 3 + FilesPanel 4); the two new regressions raise it to 15.

```
cd D:/Atlas/.worktrees/zcode-exec06-csv-preview/frontend
npx tsc -p tsconfig.renderer.json --noEmit
```

Result (tsc 7.0.2): no output, **EXIT 0**.

## 5. Product-entry boundary

Static/programmatic entry chain verified:

- `frontend/src/renderer/shell/panels/FilesPanel.tsx` computes `previewing = Boolean(shown && canPreview(shown.path) && mode === 'preview' && ...)` and renders `<DocumentPreview file={shown} workspace={workspace} fallback={...} />`.
- `documentPreviewRegistry.tsx` registers `renderers.set('csv', { id: 'csv', extensions: CSV_PREVIEW_EXTENSIONS, renderer: CsvFilePreview })`; `csvPreview.test.tsx` asserts `documentPreviewRenderer('data.CSV')?.id === 'csv'`, `documentPreviewRenderer('data.tsv')?.id === 'csv'`, `canPreviewDocument('data.csv') === true`, and static-renders the table.

Not verified live in dev Electron. Exact boundary:

1. This isolated worktree has no Electron install (`node_modules/electron/dist/electron.exe`, `node_modules/electron/install.js` absent) and no `frontend/dist-electron` main/preload build. `npm run dev` triggers `predev` → `install:electron` (download/install) and `dev:electron` → compile main + preload + launch.
2. Opening a CSV from the file tree additionally needs a running Python backend plus an interactive workspace selection (native dialog) and GUI automation; neither an isolated backend/workspace fixture nor a GUI harness was set up for this worker.
3. The only Electron runtime available is the read-only main checkout's `D:/Atlas/node_modules/electron`, whose `frontend/dist-electron` main belongs to the main checkout, not this worktree; using it would execute main-checkout code and would not validate this change (and Electron main must not be modified).

Therefore this receipt claims unit + static integration evidence only, not a live GUI click-through.

## 6. Remaining risks

- Delimiter detection is still a first-logical-record heuristic with comma tie-break/no-separator default. A file whose first logical record contains no delimiter (e.g. a single quoted header cell) but whose later rows are semicolon-separated remains ambiguous and will default to comma; not part of the reported defects.
- Malformed/unterminated quoting behavior is unchanged: a trailing unmatched `"` is flushed as an empty/literal cell row, and a quote only opens a quoted field at cell start; this preserves pre-existing behavior rather than tightening RFC-4180.
- `CsvFilePreview`'s empty-file note still triggers for a single all-empty row (e.g. a file containing only `""` or a blank line) even though the parser now preserves that row. The reported parser row-drop is fixed; changing the UI empty-state rule was out of scope and would alter blank-line behavior.
- Verification environment used npx-resolved vitest 5.0.4 and tsc 7.0.2; no full frontend suite or production Vite build was run.