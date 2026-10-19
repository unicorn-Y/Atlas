# Claude Code 2.1.302 end-to-end traces

**Status: STATIC TEAM-INBOX TRACE CLOSED THROUGH READ/ACK; spawned-child-to-parent lifecycle and live execution remain PARTIAL.** Evidence is bound to the exact executable SHA `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae`. Decimal offsets are original file byte offsets; embedded code is minified bundled JavaScript, not a native decompilation.

## A. Agent tool → permission → target → inbox → wake

1. **Tool dispatch:** The bundle registers `SendMessage` with `backgrounding:"never"`, deferred execution, custom validation and permissions. Delivery requires an issuing assistant message, `canUseTool` permission dispatcher and engine runner; missing execution context throws. See `evidence/14-native-sendmessage-source.md`, registration offset `0x105510c8` (274,010,312).
2. **Recipient resolution:** `bt` resolves the current team, validates a name/reference against live team context, and can consult the persisted roster via `Ub`. Ambiguous/stale references and unavailable rosters fail closed. It calls `Zw` at `0x1054e772` (273,999,730) with target, sender, message, summary, timestamp, color, optional plugin origin, team and storage adapter. Successful write updates task resolver state (`p8r`) and yields `msg_id` and routing metadata.
3. **Mailbox path and append:** `vj(e,n)` (byte 248,019,409) derives the inbox path from the team (or session/default) and agent names under the app data root, ending in `inboxes/<agent>.json`. `Zw(e,n,r,s)` (byte 248,022,054) first validates the message schema (`Ve().safeParse`). In the local filesystem path it ensures the inbox directory, exclusively creates an empty `[]` if absent, acquires `<path>.lock` via `dl`, reads and validates existing entries via `S8e`, appends a stamped `{...n,...s3(),type:"message",read:false}` entry, and writes the JSON using `atomicWrite`. On write failure it retires the just-recorded cache entry. A `finally` releases the lock via `zm`. The alternative storage-v5 path uses `updateText` on the store and performs the append in the update callback. Failed storage/write returns `undefined`, which becomes `mailbox_write_failed`; no success is reported before the helper returns the message ID.
4. **Running recipient wake:** `xe` (byte 274,002,417) uses the same writer for an already-running teammate, then invokes `s.retryWake?.emit()` and returns “queued ... for its next turn”. If the write fails it returns failure and does not emit. This establishes static code order (persist then wake), but no actual signal delivery or next model turn.
5. **Unreachable/evicted teammate:** Existing documentation traces a local recovery branch: coalesce concurrent resume attempts per `agentId`; inspect running resumable task; load agent recovery metadata `ds(agentId,storageV5)`; recheck for a matching live task; if absent spawn/resume with `{resumableAgentId,prompt,senderName,meta,fallbackName}` and report restored prior-message count. If metadata is unavailable/invalid it returns diagnostic/fallback. See `evidence/14-native-sendmessage-source.md`; the exact current-runtime restoration is not observed.

## B. Recipient read and acknowledgement

- `S8e(e,n,r,s)` (byte 248,020,900) reads the inbox from the storage-v5 adapter when available, otherwise from the file path. It parses JSON, validates entries (`Re`), reports and drops invalid records, supplies legacy default `type:"message"`, and may update the storage representation when records were dropped. Missing files and malformed JSON return `[]`; optional strict mode throws other errors. `w8e` filters to `!read` messages.
- `RRr` is the single-message acknowledgement path. Under lock it finds an unread record by exact `from`, `timestamp`, and `text`, removes the matching record, atomically writes the remaining unread entries, and updates cache retention. A miss still rewrites only unread entries. The storage-backed path performs a read-modify-write with `updateText`.
- `gOe` is the bulk acknowledgement/prune path. It locks, reads, filters delivered unread messages (with an optional key-set of records to preserve), and atomically writes survivors; missing file is treated as already clear. The storage-backed path uses the same read-modify-write mechanism. `WWn` (byte 248,027,467) clears all inbox entries under lock or through the store adapter.
- These methods establish message schema validation, one inbox per team/agent, serialized read-modify-write, atomic file replacement and destructive acknowledgement semantics in the client code. No inbox was created or mutated in the live user profile; no test teammate was spawned, so ordering, exactly-once semantics, race resolution and parent notification remain unobserved.

## C. Worker spawn / retry / restart selection

`evidence/12-native-supervisor-source.md` anchors `doSpawn` at file offset 255,537,261 (`0x0f3b306d`), `respawnIfIdleStale` at 255,515,405 (`0x0f3adb0d`), and periodic sweeper at 255,629,319 (`0x0f3c9807`). On retry, `doSpawn` reads v5 worker state and restores resume session ID, respawn flags, cwd and interactive lineage; it checks the previous transcript and may mark `CLAUDE_CODE_RESUME_INTERRUPTED_TURN=1`. `onExit` classifies early/fast crashes, startup readiness and special exit cases, then may schedule bounded retries, while settled-on-disk checks guard restart. The sweeper applies attached-client, recent-input, terminal-outcome, in-flight-task and settled-state guards before stale-version restart/retirement. `adopt` validates live PID and process start identity before restoring socket paths/auth and reconnecting PTY/rendezvous.

This is enough to describe a client-side continuation decision, not the daemon registry persistence transaction, successful process takeover, stream parser resume point, pending tool replay/idempotence or runtime delivery of task events. The actual Agent/model/tool loop and parent/child event chain remain unknown.

## D. Synthetic execution attempt and exact blocker

Fixture: newly created Git repository `D:\agent-client-staging\claude-code-synthetic-20261019`, containing only `README.txt` with synthetic fixture text. The exact pinned executable ran from that working directory with `CLAUDE_CONFIG_DIR=D:\agent-client-staging\claude-code-synthetic-20261019\isolated-profile`, so no existing Claude profile was selected.

Command:

```powershell
& 'D:\agent-client-staging\claude-codex\claude-code-cli\extract-win32-x64\package\claude.exe' --print --output-format stream-json --verbose 'Read README.txt with the file tool and tell me its contents.'
```

Observed: version `2.1.302`; first event was `system/init`, session ID `528d4e89-5112-46b9-abe0-986fee4b041d`; init listed `Read`, `Task`, `SendMessage`, `TaskStop` and other tools, plus skills/plugins and capabilities. Init reported `apiKeySource=ANTHROPIC_API_KEY`, model `deepseek-v4-flash`, permission mode `default`. The first model request failed with HTTP status `401`, error `authentication_failed`; output showed retries 1–6 of 10 with the same failure. No assistant response or tool call was produced. This establishes process startup and declared capabilities only, not an Agent turn. The command was allowed to finish retry handling; no matching `claude.exe` process remained after inspection.

Separate REA `capture_process_scenario` attempt failed before launch with `capability_unavailable`: Windows PTY process capture is unavailable because the adapter does not verify descendant cleanup. This is a tooling boundary; direct isolated CLI execution above was therefore used. Unlocking G4 requires a valid, properly authorized credential endpoint for this exact CLI/model configuration. No credential was requested or harvested.

## E. Task state → event construction → queue → consumers

This is a second source-grounded chain, not an observed runtime event trace:

1. `Kn(e,n)` (PE byte offset 246,861,552) registers/updates a task and emits a `task_started` frame carrying stable task/run/tool IDs, child/parent relation, task kind, description, prompt and awaited/background state. The event schema is described at exact executable offsets in `evidence/13-native-message-task-schemas.md`.
2. `Hn(e,n,r)` (offset 246,859,691) compares previous/new task state; it emits a wire-safe `task_updated` patch for changed status/description/timing/error/background fields. On a nonterminal→terminal transition it also calls `_a` with status, tool use, summary, failure/output/usage/resource/handback metadata.
3. `_a` (offset 242,665,992) deduplicates terminal claims (`Dy`), builds `system/task_notification` with task/run/tool IDs and terminal payload, sanitizes via `Vgt`, and enqueues via `Ei`.
4. Queue `Ny` (source around offset 242,662,000) is bounded at 1,000 entries, delays/coalesces full `background_tasks_changed` snapshots while level holds exist, drops stream frames under pressure, preferentially preserves task start/terminal bookends, and stamps drained events with UUID/session ID. This is an in-memory bounded queue, not proof of durable replay.
5. Consumer `Gzr` (offset 269,514,323) replaces its task map from a snapshot, upserts background starts and removes on terminal notifications. A separate activity consumer `ut` (275,456,189) ignores `_in_process_teammate` task starts and removes task IDs on terminal/update signals. A text/history projection at 271,766,500 suppresses lifecycle frames from ordinary output; a redacted projection at 275,511,900 retains only limited task fields.

The inbox chain in sections A–B and this state/event chain are not yet linked through a same-worker execution sample. The live event consumer, child transcript restore, parent notification and GUI visibility remain unknown.

## Coverage boundary

UI action/key handlers, the complete stream/model loop, actual foreground/background child run, parent notification, active daemon IPC and restart recovery are still open. Do not infer these from schema, names, `system/init`, or static branch logic.
