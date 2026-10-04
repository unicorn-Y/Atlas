# ATLAS-H1 H7 production wiring spec (for Lane A)

Writer: Lane E (H6+H7 channels/gateway/heartbeat/automation). Date: 2026-10-04.
Scope rule: this file specifies edits inside files Lane A owns (`core/atlas/server.py`, `core/atlas/api/**`).
Lane E did NOT touch any of them. Apply order W1 → W2 → W3; W4 is H6-adjacent; W5 is the acceptance test.

All gateway-side behavior referenced here is already implemented and tested in Lane E's files
(`core/atlas/gateway_service.py`, `core/atlas/channels/**`); the bridge accepts the knobs below but
production never passes them yet, so every H7 override silently falls back to the constructor default.

---

## W1 — Pass the H7 config knobs and the agent-profile lookup to `GatewayBridge`

File: `core/atlas/server.py`, lifespan block, `gateway_bridge = GatewayBridge(...)` (currently at
line ~1320, right after `async def channel_recovery_notice(...)`).

Current:

```python
    gateway_bridge = GatewayBridge(
        manager=channel_manager,
        db_path=cfg.db_path.parent / "channels.sqlite",
        submit_run=submit_channel_run,
        get_run=manager.runs.get,
        recovery_notice=channel_recovery_notice,
        read_answer=_read_conversation_answer,
        create_conversation=_create_channel_conversation,
        default_workspace=str(channel_workspace) if channel_workspace else None,
        set_agent_status=_set_agent_status_quiet,
    )
```

Insert three keyword arguments (bridge signature: `core/atlas/gateway_service.py:109-124`):

```python
        default_permission_mode=get_config().gateway_default_permission_mode,
        approval_timeout_seconds=get_config().gateway_approval_timeout_seconds,
        get_agent=_channel_agent_profile,
```

and define the tiny helper once near `_sync_channel_routing` (module level, next to it):

```python
def _channel_agent_profile(agent_id: str) -> dict[str, Any] | None:
    """Agent profile for the gateway's permission-mode ladder (binding → profile → default)."""
    try:
        return _agent_service().get(agent_id)
    except Exception:
        return None
```

Why:
- `default_permission_mode`: taskbook §9.1 — `gateway.default_permission_mode` (default
  `ask_writes`) must be honored; today the configured value is never read and the bridge always
  uses its constructor default `ask_writes`. Changing the setting (`[gateway]` in `atlas.toml`)
  currently has zero production effect.
- `approval_timeout_seconds`: §9.2 timeout default 10 min, configurable
  (`atlas.config.AtlasConfig.gateway_approval_timeout_seconds`, config.py:97).
- `get_agent`: the bridge's middle rung of the permission ladder —
  `GatewayBridge.permission_mode()` (`gateway_service.py:151-157`) reads
  `profile["agent"]["permission_mode"]`. Without `get_agent`, per-agent profile overrides
  (persisted by `core/atlas/persistent_agents/store.py:190-193`, validated via
  `validate_profile_record`) never apply. `PersistentAgentService.get` exists
  (`core/atlas/persistent_agents/__init__.py:108`) and returns the normalized record whose
  `["agent"]["permission_mode"]` is exactly what the bridge reads; `_agent_service()` is the
  accessor `api/agent_router.py` already uses.

Semantics proof (bridge side, already green):
`core/tests/test_gateway_permissions.py::test_permission_defaults_and_binding_agent_overrides`.

---

## W2 — Carry `permission_mode` through channel bindings

File: `core/atlas/server.py`, `_sync_channel_routing` (line ~599).

Current:

```python
    for record in roster:
        for row in (record.get("agent") or {}).get("channels") or []:
            bindings.append({
                "agent_id": str(record["id"]),
                "channel": str(row.get("channel", "")),
                "account": str(row.get("account", "")),
                "peer_id": str(row.get("target", "")),
            })
```

Add the binding-level override (the profile store already normalizes + validates it,
`persistent_agents/store.py:266-269`):

```python
            binding = {
                "agent_id": str(record["id"]),
                "channel": str(row.get("channel", "")),
                "account": str(row.get("account", "")),
                "peer_id": str(row.get("target", "")),
            }
            if row.get("permission_mode"):
                binding["permission_mode"] = str(row["permission_mode"])
            bindings.append(binding)
```

Why: §9.1 "每个渠道绑定…可单独覆盖". `GatewayBridge.permission_mode()` checks
`resolve_binding(...)["permission_mode"]` first (`gateway_service.py:152-154`); routing
(`core/atlas/channels/routing.py`) ignores unknown keys, so passing it through is
behavior-preserving for routing. Also call `_sync_channel_routing(agents_service, channel_manager)`
after agent profile updates if not already re-called on every mutation (it runs once during
lifespan at line ~1332 today); the cheapest correct hook is wherever agent create/patch already
refreshes gateway state.

Semantics proof: same test as W1 plus `GatewayBridge.permission_mode` unit path in
`test_gateway_permissions.py` (`bridge.permission_mode(event("task"), "ops") == "ask_each"` with a
binding override).

---

## W3 — Desktop approval card stays first-writer (verify, no change expected)

File: `core/atlas/server.py`, `_handle_run_start` approval callback (line ~6799):
`if bridge is not None and bridge.owns_run(run.run_id): return await bridge.request_approval(...)`
already shares the run's approval future with the channel. Nothing to change; the acceptance test
below covers the shared-future race (`GatewayBridge.request_approval`, `gateway_service.py:162-205`:
first answer wins; desktop-first → channel gets 「已在桌面批准。」; channel-first → desktop future
resolves; timeout → deny + channel notice).

---

## W4 (H6-adjacent, same owner) — `api/channel_router.py` BLE001 residue

`ruff check --ignore-noqa --select BLE001,S110,S112 core/atlas/api/channel_router.py` reports 2
BLE001 violations (`core/tests/test_lint_gate.py` fails today on `atlas/api/**` among other
lanes' scopes; per taskbook §8 the `api/` scope must reach zero). Fix by narrowing the exception
types or `logger.exception` + continue — your call as owner; no behavior change required.

---

## W5 — Acceptance test to add once W1/W2 land (Lane A, app factory owner)

`core/tests/test_gateway_integration.py` boots the real app (`server.app` + lifespan); add one
integration test there that proves the *wired* defaults end-to-end:

1. In the module fixture's `atlas.toml`, add:

   ```toml
   [gateway]
   default_permission_mode = "read_only"
   approval_timeout_seconds = 1
   ```

2. New test: emit a fake-channel inbound task whose scripted FakeLLM responds with
   `ToolCall("write_file", ...)`; assert `bridge.permission_mode(...)` / the submitted
   `data["permission_mode"] == "read_only"`, that no 「需要审批」 message reaches the channel, and
   the file is not written. This is exactly what Lane E's server-free test
   `core/tests/test_gateway_write_approval_e2e.py::test_gateway_default_mode_override_skips_channel_approval`
   proves at the bridge level; the integration variant proves the config value flows through the
   lifespan wiring (W1).

Reference implementations for every scenario (server-free, real FakeLLM write):
`core/tests/test_gateway_write_approval_e2e.py` — channel allow/deny/timeout/desktop-first/override,
all green twice in a row (5 passed, ~40s).

---

## Out-of-scope notes for the record

- `_collect_orchestrator_text` (`server.py`, used by heartbeat/automation/group) runs with
  `permission_mode="full_access"` and a deny-all approval callback; §9.3 says unattended turns
  honor the creator's chosen mode. If you want that honored, add an optional
  `permission_mode: str | None = None` parameter and pass
  `profile["agent"]["permission_mode"]` when the caller knows the agent (heartbeat host and
  automation `dispatch_turn` seams both know `agent_id`). Lane E did not spec the full diff —
  confirm with the controller whether §9.3 extends to unattended turns before changing it.
- `run.recovery.notice` on channel delivery failure is already produced by the bridge
  (`GatewayBridge.delivery_failed` → `channel_recovery_notice`, server.py:1313-1318) and tested in
  `core/tests/test_gateway_permissions.py::test_channel_delivery_failure_logs_and_emits_notice_without_stopping_run`.
