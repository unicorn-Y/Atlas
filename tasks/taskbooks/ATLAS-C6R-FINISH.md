# ATLAS-C6R-FINISH：C6 两项最小收口

> Only fix the two blockers in `tasks/reviews/ATLAS-C6-CODING-POLISH.review.md`.
> Do not reopen accepted C6 work.
> Do not start T1.

## 1. V4A path-less patch → LSP diagnostics

Current problem:
- Atlas LSP seam only knows `args.path`.
- Hermes V4A whole-repo patch may have no top-level path.
- That production edit path therefore skips baseline/delta reporting.

Required implementation:

1. Reuse Hermes' existing V4A parser/result metadata to obtain the files actually touched. Do not implement a second V4A parser unless the native API exposes no usable file list.
2. Before invoking the native path-less patch:
   - resolve all touched local files inside the current workspace;
   - capture pre-content where readable;
   - call Atlas `snapshot_before_write` for each file.
3. After a successful patch:
   - read each touched file;
   - call the existing Atlas LSP delta/report path for each;
   - emit the normal per-file `lsp.diagnostics` event;
   - append one compact combined Chinese diagnostics section to the patch result.
4. Files with zero new diagnostics stay silent.
5. Deleted/non-text files must not crash the patch.
6. SSH workspace still skips local LSP.
7. Existing single-path `write_file` and `patch` behavior must remain byte-for-byte compatible when there are no diagnostics.

Focused regression:
- a V4A patch touching one Python file introduces a fake LSP error → result contains the new diagnostic + one event;
- a V4A patch touching two files → only files with new diagnostics report;
- fix patch clears diagnostics / zero event;
- single-path patch existing tests remain green.

## 2. /review finding → internal file view + line positioning

Current problem:
- ReviewFindingsCard uses Electron `shell.openPath`.
- It opens the OS default app and merely says “问题在第 N 行”; it does not navigate.

Required:

1. Reuse Atlas's existing FilesPanel/code preview. Do not add a second editor.
2. Add the smallest shared “open workspace file” request/state needed so another component can ask FilesPanel to:
   - open a relative workspace file;
   - expand/select its parent path as needed;
   - switch to code mode for text files;
   - scroll to and visibly highlight the requested 1-based line (or range start).
3. Review finding “打开文件” uses that internal action.
4. If finding.line is null, open file without line positioning.
5. This must work in normal web/dev renderer too; do not depend on `window.atlasDesktop.openPath`.
6. Existing ordinary file browsing behavior stays unchanged.

Focused regression:
- ReviewFindingsCard finding with line=12 dispatches an internal open-file request with file + line;
- FilesPanel consumes request, loads/selects the file and marks/scrolls line 12;
- no-line finding opens file normally;
- existing FilesPanel tests remain green.

## Validation

Only focused validation is needed:
- affected C6 LSP tests;
- affected review/UI tests;
- renderer tsc;
- electron tsc only if shared IPC types/preload are touched (prefer not to touch IPC);
- Vitest for affected files.

Do not rerun backend full pytest unless the fix unexpectedly spreads beyond these two areas.

## Delivery

Append a short C6R section to:
`tasks/results/ATLAS-C6-CODING-POLISH.result.md`

Then:
- `tasks/CURRENT.md` → `AWAITING_REVIEW`
- push main
- verify local HEAD == origin/main
- report new HEAD
- stop
- do not start T1
