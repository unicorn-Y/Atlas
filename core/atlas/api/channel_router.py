"""REST surface for the channel gateway (``/api/channels/*``, integration-map §5).

- ``GET  /api/channels``            — per-channel status (enabled/running/errors/counts)
- ``PUT  /api/channels/accounts``   — write non-secret channel config (persisted JSON;
                                       secrets never appear here — use ``POST /credential``)
- ``POST /api/channels/credential`` — store one channel credential via the OS keyring
- ``POST /api/channels/test``       — enqueue a test message through the delivery queue
- ``POST /api/channels/{channel}/inbound`` — webhook ingress (HMAC verified by the manager)

The manager instance is injected at startup by the integration owner via
:func:`set_channel_manager`; until then the router reports a 503 degraded state.
"""

from __future__ import annotations

import inspect
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from structlog import get_logger

from atlas.channels import ChannelManager, WebhookError
from atlas.origin_guard import TOKEN_HEADER, is_trusted

router = APIRouter(prefix="/api/channels", tags=["channels"])
log = get_logger()

_manager: ChannelManager | None = None


def set_channel_manager(manager: ChannelManager | None) -> None:
    """Wire the gateway instance (called once from the server lifespan)."""
    global _manager
    _manager = manager


def get_channel_manager() -> ChannelManager:
    if _manager is None:
        raise HTTPException(status_code=503, detail="渠道网关尚未启动")
    return _manager


def _require_trusted_origin(request: Request) -> None:
    """Mirror of the app-level OriginGuard rule for standalone mounts."""
    trusted = is_trusted(
        request.headers.get("origin"),
        request.headers.get(TOKEN_HEADER),
        fetch_site=request.headers.get("sec-fetch-site"),
    )
    if not trusted:
        raise HTTPException(status_code=403, detail="Requests from this origin are not allowed")


@router.get("")
@router.get("/status")
async def channel_status() -> dict[str, Any]:
    """Aggregate channel gateway status."""
    return get_channel_manager().status()


@router.get("/catalog")
async def channel_catalog() -> dict[str, Any]:
    """Return the shared feature catalog, including platforms not yet implemented."""
    from atlas.channels.catalog import list_channels

    return {"channels": list_channels()}


class SessionLinkPayload(BaseModel):
    agent_id: str = Field(min_length=1, max_length=120)
    channel: str = Field(min_length=1, max_length=80)
    account: str = Field(default="", max_length=120)
    peer: str = Field(min_length=1, max_length=240)
    conversation_id: str = Field(min_length=1, max_length=120)
    linked_by: str = Field(default="local-user", min_length=1, max_length=120)


@router.get("/session-links", dependencies=[Depends(_require_trusted_origin)])
async def list_session_links() -> dict[str, Any]:
    """List explicit cross-channel aliases (identity keys only)."""
    from atlas import server as atlas_server

    bridge = getattr(atlas_server, "gateway_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="渠道会话服务尚未启动")
    return {"links": bridge.sessions.links()}


@router.put("/session-links", dependencies=[Depends(_require_trusted_origin)])
async def put_session_link(payload: SessionLinkPayload, request: Request) -> dict[str, Any]:
    """Bind one channel identity to an existing conversation explicitly."""
    from atlas import server as atlas_server
    from atlas.persistent_agents import session_key

    bridge = getattr(atlas_server, "gateway_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="渠道会话服务尚未启动")
    if payload.channel not in bridge.manager.registry:
        raise HTTPException(status_code=404, detail="渠道尚未注册")
    memory = getattr(atlas_server, "memory", None)
    conversation = await memory.get_conversation(payload.conversation_id) if memory else None
    if not conversation:
        raise HTTPException(status_code=404, detail="目标会话不存在")
    key = session_key(payload.agent_id.strip(), channel=payload.channel.strip(),
                      account=payload.account.strip(), peer=payload.peer.strip())
    try:
        bridge.sessions.link(key, payload.conversation_id.strip(), linked_by=payload.linked_by.strip())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log.info("channels.session_link_created", actor=payload.linked_by, channel=payload.channel,
             account=payload.account or "default", peer=payload.peer,
             conversation_id=payload.conversation_id, origin=request.headers.get("origin", ""))
    return {"ok": True, "session_key": key, "conversation_id": payload.conversation_id}


@router.delete("/session-links", dependencies=[Depends(_require_trusted_origin)])
async def delete_session_link(session_key: str) -> dict[str, Any]:
    """Remove an explicit alias so the channel identity creates a fresh session."""
    from atlas import server as atlas_server

    bridge = getattr(atlas_server, "gateway_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="渠道会话服务尚未启动")
    return {"ok": True, "removed": bridge.sessions.unlink(session_key)}


class ChannelPolicyPayload(BaseModel):
    """Runtime DM/group admission policy; fields mirror ChannelManager._admit."""

    dm_policy: Literal["disabled", "pairing", "open", "allowlist"]
    dm_allowlist: list[str]
    allow_when_empty: bool
    group_policy: Literal["disabled", "open", "allowlist"]
    group_allowlist: list[str]
    require_mention: bool


class AccountsPayload(BaseModel):
    configs: dict[str, dict[str, Any]]


def _resolve_legacy_telegram_service() -> Any:
    """Return the legacy ``TelegramService`` singleton held by ``atlas.server``.

    Local import on purpose: ``atlas.server`` imports this router at boot, so a
    module-level import would be circular. Returns None when the server module
    is unavailable (standalone router mounts) or the service was never built.
    """
    try:
        from atlas import server as atlas_server  # noqa: PLC0415 — 避免循环导入
    except Exception:  # pragma: no cover - server module not importable here
        log.debug("channels.legacy_telegram_probe_failed", exc_info=True)
        return None
    return getattr(atlas_server, "telegram_service", None)


async def _stop_legacy_telegram_poller() -> bool:
    """Best-effort stop of the legacy ``TelegramService`` getUpdates poller.

    The gateway telegram adapter and the legacy poller drive the same bot
    token with competing update offsets, so enabling the gateway at runtime
    must retire the poller immediately (server.py only decides at boot).
    Never raises: the service may be None / already stopped, and channel
    configuration must not fail because of the legacy half. Returns whether a
    stop was actually invoked.
    """
    service = _resolve_legacy_telegram_service()
    if service is None:
        return False
    stop = getattr(service, "stop", None)
    if not callable(stop):
        return False
    try:
        result = stop()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        # H6: blind catch must at least log with the traceback (BLE001).
        log.exception("channels.legacy_telegram_stop_failed", error=str(exc))
        return False
    log.info("channels.legacy_telegram_poller_stopped")
    return True


@router.put("/accounts", dependencies=[Depends(_require_trusted_origin)])
async def put_accounts(payload: AccountsPayload) -> dict[str, Any]:
    """Persist non-secret channel configuration (enabled/account/settings)."""
    manager = get_channel_manager()
    saved: dict[str, dict[str, Any]] = {}
    for name, config in (payload.configs or {}).items():
        if name not in manager.registry:
            raise HTTPException(status_code=404, detail=f"未注册的渠道：{name}")
        cleaned = {k: v for k, v in config.items() if k not in ("secret", "password", "bot_token")}
        saved[name] = manager.configure(name, cleaned)
        if name == "telegram" and cleaned.get("enabled"):
            # P10: enabling the gateway telegram adapter at runtime must stop
            # the legacy getUpdates poller — otherwise both poll one bot token.
            await _stop_legacy_telegram_poller()
    return {"ok": True, "configs": saved, **_without_channels(manager.status())}


@router.put("/{channel}/policy", dependencies=[Depends(_require_trusted_origin)])
async def put_channel_policy(channel: str, payload: ChannelPolicyPayload) -> dict[str, Any]:
    """Persist and apply a channel's real DM/group admission policy."""
    manager = get_channel_manager()
    if channel not in manager.registry:
        raise HTTPException(status_code=404, detail=f"未注册的渠道：{channel}")
    policy = payload.model_dump()
    for key in ("dm_allowlist", "group_allowlist"):
        policy[key] = list(dict.fromkeys(entry.strip() for entry in policy[key] if entry.strip()))
    manager.set_policy(channel, policy)
    return {"ok": True, "channel": channel, "policy": dict(manager.policies[channel])}


class CredentialPayload(BaseModel):
    channel: str
    field: str
    value: str = ""


@router.post("/credential", dependencies=[Depends(_require_trusted_origin)])
async def set_credential(payload: CredentialPayload) -> dict[str, Any]:
    """Store (or clear, when ``value`` is empty) one channel credential."""
    manager = get_channel_manager()
    channel, field_name = payload.channel.strip(), payload.field.strip()
    if not channel or not field_name:
        raise HTTPException(status_code=422, detail="channel/field 不能为空")
    store = manager.credentials
    try:
        if payload.value.strip():
            store.set(channel, field_name, payload.value.strip())
        else:
            store.delete(channel, field_name)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    restarted = await manager.restart_channel(channel)
    return {
        "ok": True,
        "channel": channel,
        "field": field_name,
        "set": bool(payload.value.strip()),
        "restarted": restarted,
    }


class TestPayload(BaseModel):
    channel: str
    chat_id: str
    text: str = ""


@router.post("/test", dependencies=[Depends(_require_trusted_origin)])
async def send_test(payload: TestPayload) -> dict[str, Any]:
    """Send a test message through the durable delivery queue."""
    manager = get_channel_manager()
    if payload.channel not in manager.registry:
        raise HTTPException(status_code=404, detail=f"未注册的渠道：{payload.channel}")
    key = await manager.send_test(payload.channel, payload.chat_id, payload.text)
    return {"ok": True, "idempotency_key": key}


@router.post("/{channel}/inbound")
async def channel_inbound(channel: str, request: Request) -> dict[str, Any]:
    """Webhook ingress — HMAC verified and queued by the gateway."""
    manager = get_channel_manager()
    body = await request.body()
    try:
        return await manager.handle_webhook(channel, dict(request.headers), body)
    except WebhookError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _without_channels(status: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in status.items() if k != "channels"}


__all__ = ["router", "set_channel_manager", "get_channel_manager"]
