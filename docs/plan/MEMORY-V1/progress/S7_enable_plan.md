# S7 unified memory enablement plan (preparation only)

Status: `PREP_ONLY`. This document records the proposed cutover and rollback. F2-C does not enable the production service, write production configuration/data, or enter S7.

## Current configuration findings

- `config/atlas.toml` has no `[memory.unified]` section, so unified memory remains disabled by the Atlas default.
- The allowlisted `memory_model` is `gemini-3.8-flash`; F2-A verified it matches the registered custom model. No production model value change is needed.
- Atlas `MemoryOSServiceLifecycle` starts `D:\MemoryOS\service\app.py` as a child when unified memory is enabled. It sets `MEMORYOS_SEMANTIC_RECALL_ENABLED=1` for that child and stops only the process it owns during Atlas shutdown.
- The existing 8045 loopback proxy is the configured Gemini route. F2-C will report whether its Gemini `countTokens` route is usable; request bodies and credential values are never written to evidence.

## Proposed production diff (not applied)

`config/atlas.toml` would receive only the following S7 section after the backup gate passes:

```diff
 [memory]
 db_path = "./data/atlas.db"
+
+[memory.unified]
+enabled = true
+capture_mode = "enabled"
+service_url = "http://127.0.0.1:8099"
+service_dir = "D:/MemoryOS"
```

`data/user-settings.json` has no proposed diff: keep `memory_model=gemini-3.8-flash`. Enabling `[memory.unified]` causes Atlas to auto-launch MemoryOS; the semantic switch is set by the existing lifecycle code, so no production environment-variable edit is proposed. The isolated rehearsal uses a separate test subject and one-time in-process internal token; neither is copied into production settings.

## Backup and rollback

- F2-A created the user-settings safety copy at `D:\Atlas\data\user-settings.json.bak-before-f2-a-20261009-1125`. It verified the configured `memory_model` and made no model change.
- F2-C has not created a production database or `atlas.toml` backup. Before a future S7, create a timestamped backup set outside the live DB directories, for example `D:\MemoryOSData\backups\MEMORY-V1-F2-<UTC timestamp>\`, using SQLite's backup API for both `D:\Atlas\data\atlas.db` and `D:\MemoryOSData\db\memoryos.sqlite3`, plus byte-for-byte copies of the Atlas TOML and user settings. Verify each SQLite copy with `PRAGMA integrity_check` and record hashes. This remains a future precondition, not an action performed in this lane.
- The isolated rehearsal snapshots are retained outside both checkouts and production data roots. Their exact path and integrity evidence will be recorded in `F2-C-lifecycle-rehearsal.json`; they are not production rollback backups.
- If a future, separately authorized S7 needs rollback: stop Atlas gracefully so its owned MemoryOS child exits; set only `[memory.unified].enabled=false` (or restore the pre-S7 TOML backup); restart Atlas and verify the legacy memory API responds and port 8099 has no MemoryOS child. Preserve the MemoryOS DB unless a separately approved database restore is required. If restoring a DB is required, stop all writers first, retain the failed state separately, restore only the verified SQLite backup, then run integrity and application health checks. Do not restore the F2-C clone over production.

## Production evidence requested by the task

F2-C will add the recent-30-day `evidence_events` counts and event-type aggregates, Gemini proxy token estimate/status, legacy export/import counts from isolated copies, semantic warm-up and backfill measurements, and the real lifecycle rehearsal. Only counts, timestamps, booleans, hashes, and clone-only reference identifiers are published; copied content and credential values are excluded.

## Boundary

This is preparation evidence only. It does not authorize or perform production enablement, migration, S7 acceptance, or any update to `CURRENT.json`.
