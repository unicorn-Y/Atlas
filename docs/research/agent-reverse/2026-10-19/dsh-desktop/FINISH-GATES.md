# DSH desktop finish gates — checkpoint

**Overall: WORK IN PROGRESS. Do not mark complete.**

| Gate | Status | Evidence / remaining acceptance condition |
|---|---|---|
| G0 Artifact identity | **PARTIAL** | A/B source ZIPs independently rehashed; versions, commit IDs, sizes and archive topology retained. No compiled A/B binary or source-to-running-binary association. |
| G1 Executable coverage | **PARTIAL** | ZIP member code counts and selected runtime groups quantified. 343 embedded package tarballs hash matched; 15 selected runtime modules extracted. Full registrations/actions in A packages and external Web UI remain incomplete; B UI was not dynamically traversed. |
| G2 UI/IPC/runtime/state chain | **PARTIAL** | A Host and B Tauri management/navigation traced; official inbox API mutation/projection traced. Exact A frontend is pinned and contains no queue mutation UI/caller; B external frontend build remains U. |
| G3 Agent semantics/recovery | **PARTIAL** | Static inbox, persistence, cold Agent resolution and child Session/sidebar projection sourced. Real run/interrupt/retry/restore after process failure remains U. |
| G4 Local run | **PARTIAL** | A Next build passes in scratch. Electron verifier cannot fetch its binary (`TypeError: fetch failed`) and creates no window. Synthetic Node host starts, emits `process.ready`, shuts down cleanly, then verifier fails line 118 on missing `dsh-community-market` bundle record. Host lifecycle only; GUI/Agent R=0. B and synthetic Agent/tool/child/reopen acceptance remain U. |
| G5 Atlas main | **PASS (static trace only)** | `origin/main` fetched; SHA `aa6196f550098cc46081dc6db2c376cb87ddffa5`. Source comparisons and bounded backlog recorded. Runtime equivalence remains U. |
| G6 Evidence set/review | **PARTIAL** | Five required gate artifacts are present and lane docs updated. Cross-review is pending. |
| G7 Stop rule | **OPEN** | Exact A pinned UI absence is established; full executable action coverage, B runtime, GUI, synthetic Agent/tool/child and failure/reopen path remain open. No final acceptance. |

## Checkpoint integrity

- No Atlas product files changed.
- External dirty root `D:\atlas-research-agent-reverse-dsh-desktop-20261019` was read-only; edits are restricted to this lane worktree's research docs.
- Runtime evidence is limited to A Node host boot/readiness/graceful shutdown. No community GUI click, message submission, tool, subagent, interruption, or restoration was observed.
- `R=0`: no community app click, message submission, tool, subagent, interruption, or restoration was observed.
