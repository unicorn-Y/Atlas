# ATLAS-X7-ALWAYS-ON-PERSONAL-AGENT — Atlas's own always-on laptop

STATUS: PREPARED (future implementation taskbook; no implementation authorized by this document)
OWNER: future Sol-assigned worker
RESULT: `tasks/results/ATLAS-X7-ALWAYS-ON-PERSONAL-AGENT.result.md`
ARCHITECTURE: `docs/research/2026-10-03-x-prep/08-x7-architecture.md`
PRODUCT COMPARISON: `docs/research/2026-10-03-x-prep/07-x7-products.md`

## User-visible goal

The user's Atlas laptop acts as Atlas's persistent computer. A Windows service accepts tasks while the device is awake and online, records them in Atlas's existing durable task/goal/session lifecycle, and supervises the one existing Hermes-backed agent runtime. A per-user interactive worker supplies desktop/browser/UIA operations only while that Windows logon session is available. The user can assign, approve, pause, resume and inspect work through X1/X3/X6 surfaces.

## What this does not do

- It does not create a second scheduler, session store, agent runtime, goal manager, task database, skill registry, permission store, or channel gateway.
- It does not claim a laptop can run while powered off, asleep or offline, or that a Windows service can interact with Session 0's desktop.
- It does not enable lid-close sleep prevention, wake-on-LAN, remote access, account creation, OAuth, or unattended sending without owner setup and X1/X2 policy.
- It does not allow the service or interactive worker to change Atlas's own code, install/promote skills, publish/send external content, or perform irreversible account/security actions outside existing Atlas permission and approval rules.

## Existing Atlas/Hermes authority

Read first at implementation start: `core/pyproject.toml`, `docs/plan/VENDORED.md`, `core/atlas/server.py`, `core/atlas/capabilities/durable/dbos_backend.py`, `core/atlas/scheduler/__init__.py`, `core/atlas/engine/session_sync.py`, `core/atlas/agent/__init__.py`, `core/atlas/engine/hermes_policy.py`, `core/atlas/engine/tool_permissions.py`, `core/atlas/safety/policy.py`, `core/atlas/skills/__init__.py`, `core/atlas/skills/registry.py`, `core/atlas/models/credentials.py`, `core/atlas/capabilities/computer/`, `core/atlas/capabilities/browser/`, and `core/atlas/notifications/`.

At the inspected Atlas base, `server.py` already routes scheduled work through the Hermes GoalManager as lifecycle authority; DBOS already provides durable workflow recovery; Atlas scheduler already supports cron/interval/date/event triggers; Atlas goal sync records lifecycle events; Hermes session state has cross-process turn leases/fencing; Hermes monitor hashes its source and suppresses the agent run when unchanged. The current dependency pin is `unicorn-Y/hermes-agent@e287231d7906bcce5bc373d20fb2e3e1e6427220`; independently verify from `core/pyproject.toml` during implementation. `docs/plan/VENDORED.md` has historical rows; do not use them as current pin authority.

## Sources and exact files

1. Hermes fork/current pin: `D:/hermes-agent/hermes_cli/gateway_windows.py`, `hermes_cli/service_manager.py`, `hermes_cli/gateway_supervised_restart.py`, `hermes_cli/goals.py`, `hermes_state_sessions.py`, `hermes_state_compression.py`, `hermes_state_gateway.py`, `gateway/run_goals.py`, `gateway/slash_commands_goals.py`, `cron/monitor.py`, `cron/scheduler.py`, and `cron/scheduler_detached_worker.py` (MIT). Fresh upstream commit and paths are recorded in `docs/research/2026-10-03-x-prep/08-x7-architecture.md` and `evidence-x5-x7.json`.
2. OpenClaw snapshot `D:/Atlas-x-prep-sources/OpenClaw` at `331a6f0d1d262dcc7bdfb23c94f9b0a97ae9a5fa`, MIT: compare gateway/cron/device-pairing/skill-workshop lifecycle only. Do not port a second agent/service runtime.
3. OpenAI Codex snapshot `D:/Atlas-x-prep-sources/Codex` at `50b4c5e58c1b89f3d1b74155cc1cc1716c2be208`, Apache-2.0 with component-specific licenses: `codex-rs/windows-sandbox-service/src/service.rs` and `codex-rs/windows-sandbox-service/src/service/runtime_lifecycle.rs` concern sandbox-service lifecycle, not a full-time personal-agent service.
4. Microsoft Windows primary references: [Interactive Services](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services) establishes the noninteractive service boundary; [SetThreadExecutionState](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate) does not override lid close or all sleep policy.
5. Product distinctions are sourced in `07-x7-products.md`: cloud scheduling, local companion access, Mac-only personal computer, and device-resident agent claims are not interchangeable.

## Implementation plan, file-level

1. **Baseline and authority check.** Re-read current `core/pyproject.toml` pin, Git `HEAD` in `D:/hermes-agent`, and `docs/plan/VENDORED.md`. Verify same Hermes code/API assumptions at the recorded pin. If dependency authority is inconsistent, stop X7 runtime work and report the exact discrepancy for C1 owner; do not silently change pin.
2. **Classify capabilities.** In `core/atlas/agent/`/capability registration, mark current tools as service-safe or interactive-session-required, preserving the existing tool registry and permission checks. Read UIA/foreground classification from `core/atlas/capabilities/computer/uia_backend.py`, `cua_backend.py`, `core/atlas/capabilities/browser/`, and `core/atlas/tools/local_execution.py`. Reject a request at the boundary if the required worker is absent.
3. **Service lifecycle.** Add the smallest Windows SCM service wrapper and lifecycle entry points under the existing server/runtime package (exact new filenames to be recorded in the X7 implementation result before edits). Base lifecycle handling on Hermes `hermes_cli/gateway_windows.py` and `service_manager.py`. The service owns startup, health, scheduler wakeup, task bridge and controlled restart; it calls the existing Atlas server and one Hermes runtime.
4. **Interactive worker and IPC.** Add a per-user logon worker beside existing computer/browser adapters. Authenticate local service and worker, bind identity to Windows SID + logon session + worker instance, issue bounded expiring requests containing task id, capability, approval id and fencing version. Reject stale task ids, replayed requests, worker permission elevation, wrong SID/session, and duplicate side effects. Never pass raw credentials through IPC payloads.
5. **Durable task/session mapping.** In `core/atlas/capabilities/durable/dbos_backend.py`, `core/atlas/server.py`, and `core/atlas/engine/session_sync.py`, bridge existing DBOS task id, Hermes goal/session id, lease/fencing generation and worker request. DBOS/Hermes remain state authorities. A worker/service restart must resume or reconcile this same identity, not create a duplicate scheduled task/goal/session.
6. **Presence and recovery transitions.** Use existing status/event persistence or propose an enum-compatible mapping at the API edge for waiting user, waiting network, paused by sleep, awaiting approval, recovery required and terminal states. Do not introduce an independent database/state machine. On lock/logoff, yield interactive work to waiting-for-user; on sleep/offline, preserve checkpoint and mark unavailable until resume; after lease expiry, fence stale workers before replay.
7. **No-change monitor.** Keep Hermes `cron/monitor.py` plus scheduler behavior. A stable source hash records cheap unchanged metadata and suppresses the model run. A source error remains error/unknown and preserves the last good hash. Do not add an LLM health poller.
8. **Permission mapping.** Continue using Atlas `full_access`, `ask_writes`, and `read_only`, Atlas tool/safety policy, and approval callback. Interpret `auto` as allowed within inherited mode and safety policy; `ask` as existing owner approval; `forbid` as a deny/read-only rule. Do not add a competing three-level policy system. Money, external send/publish, destructive/irreversible, security/account changes and actions needing presence must have action-level requirements through current policy. A child cannot loosen parent policy.
9. **Identity and skills.** Connect dedicated browser/email/messaging identities via X1/X2 and keep task records as identity references. Atlas `SkillManager` and `SkillRegistry` remain the only skill lifecycle; demonstration/repeated-run workflow proposals come from X4/X5 and stay unapproved until reviewed.
10. **Notifications and handoff.** Return service, user-worker, network, power and task state through existing notification/gateway contracts. X1 channels, X3 device pairing/handoff and X6 voice connect to existing task/session ids; return-to-user resumes the same task by default.
11. **Host setup and operations.** Provide owner-reviewed setup for least-privilege service identity, service startup, per-user worker startup, network reconnect, update/restart window, AC/battery/lid policy, remote access and pairing. Show last heartbeat and precise offline/locked/sleep/update/crash cause. Never say `always available` when only an awake/online laptop was tested.

## Data and event contract

Reuse DBOS task payloads and Hermes goal/session/lease rows. Extend only after schema review, through their owning repositories, with service-instance id, worker-instance id, Windows SID/logon-session id, heartbeat, capability class, task id, approval reference, lease/fencing generation, last observed host network/power state and recovery reason. Secret values and desktop contents are not host-heartbeat data.

Reuse/emit typed events: `host.service.started|healthy|unhealthy|restart_requested`; `worker.online|locked|logged_out|heartbeat_lost`; `task.waiting_for_user|waiting_for_network|paused_for_sleep|resumed|recovery_required`; `monitor.unchanged|changed|failed`; `approval.requested|granted|rejected`; `handoff.created|accepted|expired`. Every event carries task/session id where relevant, timestamp, producer instance, and idempotency key. Unchanged/error polling never invokes an agent turn.

## Tests and real acceptance

Fake-model acceptance must prove: service restart recovers one existing task/goal/session; mid-step crash resumes or reconciles without a duplicate; Hermes lease fencing blocks a stale worker; network disconnect/reconnect retains state; UI tool fails closed while logged out/locked but service-safe timer can continue; source unchanged means zero model calls; source changed triggers one run; failed source check does not mutate last good hash; child cannot expand parent permission; ask/forbid use existing approval/deny; handoff resumes same task; no second runtime/session/scheduler/skill registry is introduced.

Real-device acceptance uses a dedicated Windows test laptop, account/profile and isolated Atlas data, with fake model. Record OS build, service identity/ACL, logon/lock state, AC/battery/lid behavior, NIC/router/WOL capability, network transitions, update/restart, crash injection, worker/SID/session identities, durable task and Hermes session ids, provider trace and duplicate-send reconciliation. Exercise phone/IM ingress only after X1/X3 test channel setup. Dedicated email/browser/messaging accounts are set up only through X1/X2. Sleep/offline must visibly pause execution; WOL is a conditional hardware result. `SetThreadExecutionState` alone is not evidence of lid-close behavior.

## Frontend, dependencies and blockers

- Backend is the first deliverable: service/worker IPC, task/session/lease recovery, and accurate host availability states.
- X7 introduces no separate dashboard; X3 provides paired devices/host state, X1 provides channel/inbox/approvals, X6 provides voice ingress.
- Dependencies: C1 pin/runtime/session completion; X1 channel/auth lifecycle; X2 browser/computer persistent profile; X3 device pairing/handoff; X4 single skill registry/workflow; X5 reviewed skill candidates; X6 voice surfaces. Begin with fake local service/worker acceptance once C1 invariants are met; integrate each user surface in its owning wave.
- Blockers: pin disagreement; undefined service identity/IPC trust; lack of a supported/tested laptop power policy; no dedicated account/connector setup; inability to prove lease fencing and idempotent external actions.
- Proposed CORE-PARITY additions: `X7-windows-service-worker-separation`, `X7-durable-resume-fenced-goals`, `X7-monitor-no-change-zero-model`, `X7-power-network-state-honest`, `X7-owned-identity-reference-only`.
- Result: `tasks/results/ATLAS-X7-ALWAYS-ON-PERSONAL-AGENT.result.md`.
- This X-PREP taskbook is a future construction plan only. It changes no `core/`, `frontend/`, `backend-adapter/`, Hermes fork, or production settings during preparation.

