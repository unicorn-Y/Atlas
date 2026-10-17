# Lossless cutover plan

State: `READY_FOR_CUTOVER`; `NOT_DEPLOYED`.

## Protected starting point

At baseline, `D:\Atlas` was on `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f` with 12 tracked modified paths and 41 untracked top-level paths. None were edited, reset, stashed, removed, or replaced during this task. The running Atlas desktop/backend were left running. An initial isolated Electron launch inherited the default API port and could reach the running API. I observed this before any chat action, made a read-only health probe, and inspected the initial page; the renderer may also have performed startup reads that were not captured. No chat or write action was sent until the isolated Electron was stopped and restarted against port 18765.

An isolated backup is at `D:\atlas-closeout-backup-20261017`:

- `tracked-worktree.patch`, SHA-256 `486C5863CF19A32A5CE131187BCBDF7607831CE6D74A57F95AA7FDA20E5FFF4D` (the original remains unchanged).
- `MANIFEST.json` records hashes for the backed-up source, audit/research files and private config.
- `untracked-research\` contains a copy of the untracked research source/tests/docs needed to preserve that work.
- `local-config\atlas.toml` is a byte-identical copy of the user config (SHA-256 `B606096BB6CF6C0A0322C78682674C98B30957AEFF120AFA3658F95A16A61620`). It was not copied into the candidate or printed. No real data, cache, database, session, or memory directory was copied.

## Candidate integration

Candidate worktree: `D:\atlas-closeout-candidate-20261017`, based on integration `6b5da15adaa32e495c7285b36eb9a50e575e739d`. A normalized *copy* of the backup patch was used because the original patch has no final newline; its SHA and bytes were not changed. Eleven tracked files applied cleanly. One conflicted file is `core/atlas/kernel/model_call.py`.

The conflict is semantic: integration's ATL-022 behavior makes `content_filter` terminal and does not rewrite/resend the prompt. The local dirty version adds expert-harness instructions and reissues the request after a content-filter response. Do not accept that local hunk as-is. Review the rest of this file against the backed-up exact version, preserve any unrelated intended changes separately, and keep terminal content-filter handling. Research source and test copies remain in the isolated candidate for lossless review. No candidate result has been merged into `D:\Atlas`.

## Safe cutover steps after independent review

1. Close Atlas normally from its own UI and confirm the expected `D:\Atlas` process tree has exited. Do not kill by broad image name.
2. Recheck branch, HEAD, tracked diff, untracked inventory, config hash, and memory/data roots. Compare them with the backup manifest before touching any live path.
3. Resolve the `model_call.py` semantic conflict while retaining the terminal `content_filter` policy. Review all 12 tracked changes against the candidate and selectively carry the 8 backed-up research source/test/doc files. Keep `data/config/atlas.toml` and all data/session/memory/cache directories in place; do not replace them from the candidate.
4. Build and run focused checks in a second isolated candidate with a copied config and temporary data root. Confirm model, paths, and user-data directories before launch.
5. Only after that review, prepare a timestamped sibling worktree and a same-volume rollback copy. Switch by renaming the active directory only while the application is closed. Keep the old directory, real data, and config unchanged until post-cutover acceptance.
6. If preflight, build, health, or smoke fails, restore the old directory name and restart its original command. Do not delete the candidate or backup during rollback.

There is no executable live-switch command here because the one semantic conflict needs explicit resolution and the user desktop must be closed first. The current result is a reviewable, reversible candidate, not a deployed release.
