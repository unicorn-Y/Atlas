# F2-C isolated enablement rehearsal

Status: `IN_PROGRESS`. Production enablement is not authorized or performed in this lane. No product code, production data/configuration, or `CURRENT.json` was modified by F2-C.

## Scope and isolation

- Runner: `scripts/memory_v1/f2_enable_rehearsal.py`.
- It uses SQLite's online backup API with a read-only source connection, then performs export, TEST-class import, model calls, chat, restart, and rollback only against caller-supplied isolated roots.
- A generated per-run MemoryOS internal token and a dedicated `f2-c-isolated` subject stay in the child-process environment; neither value is recorded.
- Raw legacy export files and process logs are removed. The retained Atlas/MemoryOS database copies are in the isolated run root; the public JSON contains aggregate counts and hashes only.

## Verification so far

- `python -m py_compile scripts/memory_v1/f2_enable_rehearsal.py scripts/memory_v1/test_f2_enable_rehearsal.py` — passed.
- `python -m pytest scripts/memory_v1/test_f2_enable_rehearsal.py -q -p no:cacheprovider --basetemp D:\Temp\f2c-pytest-20261009-114305-510` — 10 passed, exit code 0. The unique basetemp avoids the Windows pytest symlink-cleanup failure seen on the first run.
- The production route was not called during these local checks. F2-A has started its 10×3 real smoke and requested that F2-C hold all 8045 traffic until it sends the release notice.
- Final success now requires all source hashes to remain unchanged (Atlas DB and WAL, MemoryOS DB and WAL, Atlas `config/atlas.toml`, and `data/user-settings.json`), enable-phase marker evidence growth, and Atlas plus MemoryOS listener ports to be absent after all three Atlas process exits. A sanitized partial JSON checkpoint is written after each completed phase and is carried into a blocked final artifact.

## Remaining for F2-C

1. After F2-A releases 8045, run the isolated production SQLite snapshots and record aggregate evidence stats.
2. Probe Gemini `countTokens` only through the existing 8045 loopback route; record a clear unavailable status if the proxy does not expose it.
3. Export Atlas legacy facts from the clone and import them as `TEST` into the isolated MemoryOS service.
4. Send a real Atlas WebSocket chat with a generated synthetic marker, stop/restart Atlas, verify the marker through MemoryOS recall refs and a new real chat, then disable unified memory and confirm the legacy memory API and child-process cleanup.
5. Record embedding model readiness and estimate remaining backfill from the isolated queue's observed throughput.
6. Update the S7 plan and this report with exact artifact paths, command, evidence, and unresolved items. Do not modify `CURRENT.json` or production state.
