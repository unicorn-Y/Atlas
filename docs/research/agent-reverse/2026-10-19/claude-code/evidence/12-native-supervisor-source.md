# Native background supervisor: readable embedded application source

## Artifact and method

- Artifact: `package/claude.exe` in `@anthropic-ai/claude-code-win32-x64@2.1.302`, archive SHA-256 `cd077f50f24f5155c28800a3658a58c89b5d1ccae2f95a2e096a16ab250a544d`, executable SHA-256 `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae`.
- Target is the shipped Windows AMD64 Bun executable. Its `.bun` section has file offset `0x071e2c00`; the following file offsets point into the executable's actual embedded, readable JS module payload, not a symbol table dump. Source-like module imports refer to build paths such as `B:/~BUN/root/chunk-*.js`; source map/build tree is not included.
- Offsets below were obtained by byte-searching the exact verified executable for complete minified method signatures and extracting the source text in place. This is static shipped-code evidence, not a decompiled native call graph or observed daemon execution. The attached excerpt lengths are capped; exact implementation claims below are restricted to visible code.

## Worker safety and recovery code

### Idle stale-version respawn (`0x0f3adb0d`, byte 255,515,405)

`async respawnIfIdleStale(e,r="sweep")` visible body returns explicit reasons and guards before requesting a restart:

1. It refuses `exec` mode, a transition in progress, terminal outcome, downgrade/stale CLI version mismatch, any attached client, or non-stale worker.
2. For sweep-triggered restarts, it refuses recent input. It reads the current v5 on-disk state, then rechecks transition/outcome/attached-client and input races after the await.
3. It refuses absent state, a newly adopted worker during its grace interval, a settled state outside the sweep's pinned set, non-idle tempo except a narrow parked-idle-fork case, and any `ye(state)` in-flight condition.
4. Only after all guards does it transition to `{kind:"upgrading"}`, emit state with pid, log `tengu_bg_respawn_stale`, call `shutdownWorker()`, and return `{respawned:true}`. The method itself requests worker shutdown; subsequent spawn/restart is handled by the worker exit transition.

The exact method text includes the version check, second state read, repeated race guards and transition call at this offset. It is not a generic unconditional “restart crashed agent” path.

### Settled-worker retirement (`0x0f3ae7ff`, byte 255,518,719)

`async retireIfSettled(e,r,s=e,{shedMonitoringOnly:h=!1}={})` re-reads v5 state and checks transition, outcome, attached clients, host-managed work, pinned worker, recent adoption and recent input. It separately recognizes an empty idle background worker with a grace period. Its settling predicate distinguishes idle/blocked/parked fork, stale version, interactive lineage, non-monitor tasks, queued work, session-cron work, routines, bridge-session grace and task counts from drainable monitors. It will not retire when queued work remains, non-monitor task count remains, `session_cron` is present, a routine is active, or the relevant grace period has not elapsed. On retirement it changes phase to `retiring`, calls `shutdownWorker`, records a bounded cause (for example `abandoned-stale`, `settled`, or `idle-prompt`) and emits `tengu_bg_retired`.

The periodic sweeper `async function ze(f,C)` starts at `0x0f3c9807` (byte 255,629,319). It serializes each interval with a `Re` guard, shifts grace clocks after detected host sleep, loads v5 state once, invokes stale respawn only for workers in the state set, evaluates settlement for workers, then applies staged low-memory cleanup: non-pinned settled workers first, then monitoring-only shedding, and finally pinned settled workers as a last resort if memory pressure persists. This is application source visible in the payload; actual interval execution and memory response were not exercised.

### Spawn/restart and resume selection (`0x0f3b306d`, byte 255,537,261)

`async doSpawn(e,r=!1)` increments `attempt`, clears transient rekey/readiness/interactive marks, and drops `liveTranscriptPath` on retries. It requests spent credential-file paths and discards them on PTY socket ownership errors. On retries it reads worker v5 state and restores `resumeSessionId ?? dispatch.sessionId`, `respawnFlags ?? dispatch.respawnFlags`, `cwd ?? dispatch.cwd`, and `interactiveLineage`; it scans the transcript for messages and records the selected transcript path. If a prior turn is interrupted, source sets `CLAUDE_CODE_RESUME_INTERRUPTED_TURN="1"` and may add a resume prompt plus max-age setting. If no transcript messages remain and the resume ID changed, it sets `CLAUDE_BG_POST_CLEAR_RESPAWN="1"`. It builds CLI environment via internal helpers, then invokes the PTY spawn adapter with selected command/argv, cwd, environment and socket/auth data.

The adjacent visible exit/recovery methods further show a capped attempt count (`He`), timer-based delayed respawn (`St`), terminal state on exhaustion, and `doSpawnUnlessSettledOnDisk()` before retry; the exact delay policy's binding/value is not asserted from an obfuscated identifier. `onExit` classifies fast-crash streak, worker-ready/early exit, host sleep, session-ID collision and launcher fork-and-exit cases before deciding settle or respawn. No actual failure was induced.

### Claim/adopt across daemon ownership (`0x0f3b0d05`, byte 255,528,197; `0x0f3b0dff`, byte 255,528,447)

`buildClaimFrame` rebuilds the worker environment/argv from dispatch state, removes transient PTY auth and no-stable-path markers, injects stored reattach environment and launches with the original session ID/respawn flags. `adopt` rejects a dead PID, obtains process start identity and rejects a mismatch, then reconstructs the worker record as adopted, marks it ready, restores rendezvous/PTY sockets and auth tokens, wires the PTY and connects the rendezvous endpoint. This is concrete process adoption logic in the shipped client binary. It does not by itself show which persistent supervisor registry writer is atomic or prove cross-process takeover succeeds.

`socketAuth()` creates independent 16-byte random hex `rvAuth` and `ptyAuth` values when missing. `doSpawn` supplies `ptyAuth` to the socket/PTY setup; `adopt` restores socket paths/auth from the roster. The static text does not prove token secrecy against same-user processes or the full peer authorization policy.

## Atlas main comparison (source only)

Pinned Atlas source baseline: `main@aa6196f550098cc46081dc6db2c376cb87ddffa5`.

- `core/atlas/runtime/hub.py:119-300` hosts scheduled goal execution; it is not the observed Claude interactive-worker supervisor with attachable PTY/rendezvous sockets.
- `core/atlas/runtime/backends.py:76-127` keeps ACP session managers/connections in an in-process mapping. `core/atlas/runtime/external_process.py:133-134` explicitly raises `NotImplementedError` for generic external-process resume. These are concrete source boundaries for that adapter path, not a claim that Atlas has no other background work.
- `core/atlas/api/run_drive.py:1965-1976` keeps the external-agent mapping in process memory. No matching durable worker v5 record, daemon claim frame, or process-start-validated adopt path was found in these inspected counterparts.
- Atlas has other worktree and checkpoint mechanisms (`core/atlas/agent/subagent_worktree.py:237-343`; `core/atlas/agent/checkpoints.py:24-208`) but these do not establish process supervisor parity.

Assessment: **mechanism differs / no equivalent evidenced in the inspected Atlas paths**, not “Atlas has no background execution.” A broader Atlas search or a running Atlas recovery experiment could change this assessment. No Atlas business code changed.

## Evidence bounds

The excerpt supports shipped client-side code logic only. It does not show cloud/server implementation, full roster/lease persistence schema, exact socket wire envelope, actual PTY process lifecycle, daemon status across process restart, attached terminal interaction, or successful crash recovery. No authenticated model request or user profile was used. These remain U.
