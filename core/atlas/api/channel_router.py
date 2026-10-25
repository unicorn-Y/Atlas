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
import asyncio
import ipaddress
import secrets
import subprocess
import sys
import time
from contextlib import suppress
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from structlog import get_logger

from atlas.channels import ChannelManager, WebhookError
from atlas.origin_guard import TOKEN_HEADER, is_trusted

router = APIRouter(prefix="/api/channels", tags=["channels"])
log = get_logger()

_manager: ChannelManager | None = None
_SECRET_FIELDS = {
    "secret", "password", "bot_token", "app_token", "app_secret", "client_secret",
    "corp_secret", "webhook_secret", "encoding_aes_key", "token",
}
_CHANNEL_INSTALL_PACKAGES = {
    "slack": ("slack-sdk>=3.33.0", "slack-bolt>=1.18.0", "aiohttp>=3.9.0", "cryptography>=41.0.0"),
    "feishu": ("lark-oapi>=1.3.0", "cryptography>=41.0.0"),
    "dingtalk": ("dingtalk-stream>=0.24.0", "aiohttp>=3.9.0", "cryptography>=41.0.0", "defusedxml>=0.7.0"),
}
_install_state: dict[str, Any] = {"status": "idle", "channel": None, "message": ""}
_install_lock = asyncio.Lock()
_slack_oauth_states: dict[str, dict[str, Any]] = {}
_SLACK_BOT_SCOPES = frozenset({
    "app_mentions:read", "channels:history", "channels:read", "chat:write",
    "files:read", "groups:history", "groups:read", "im:history", "im:read",
    "im:write", "mpim:history", "mpim:read", "users:read",
})


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
    """Return shared capabilities plus the live adapter registration state."""
    from atlas.channels.catalog import channels_with_registry

    return {"channels": channels_with_registry(_manager.registry if _manager else {})}


@router.get("/dependencies/status", dependencies=[Depends(_require_trusted_origin)])
async def channel_dependency_install_status() -> dict[str, Any]:
    """Return progress for the optional SDK installer without exposing credentials."""
    return dict(_install_state)


@router.post("/dependencies/{channel}/install", dependencies=[Depends(_require_trusted_origin)])
async def install_channel_dependencies(channel: str) -> dict[str, Any]:
    """Install one catalog adapter's pinned extra packages into this Atlas Python."""
    channel = channel.strip().lower()
    packages = _CHANNEL_INSTALL_PACKAGES.get(channel)
    if packages is None:
        raise HTTPException(status_code=404, detail="该渠道没有可安装的可选依赖")
    if _install_lock.locked():
        raise HTTPException(status_code=409, detail="另一个渠道依赖安装正在进行")
    async with _install_lock:
        _install_state.update(status="installing", channel=channel, message="正在使用当前 Atlas Python 安装渠道依赖…")
        output_lines: list[str] = []
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", *packages,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            assert process.stdout is not None
            deadline = asyncio.get_running_loop().time() + 900
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError("pip install 超过 15 分钟")
                raw_line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
                if not raw_line:
                    break
                output_lines.append(raw_line.decode("utf-8", errors="replace").rstrip())
                del output_lines[:-40]
                _install_state.update(message="\n".join(output_lines)[-6000:])
            return_code = await asyncio.wait_for(process.wait(), timeout=max(0.1, deadline - asyncio.get_running_loop().time()))
        except (OSError, TimeoutError, asyncio.TimeoutError) as exc:
            if "process" in locals() and process.returncode is None:
                process.kill()
                await process.wait()
            message = f"依赖安装失败：{type(exc).__name__}: {str(exc)[:400]}"
            _install_state.update(status="failed", message=message)
            raise HTTPException(status_code=500, detail=message) from exc
        output = "\n".join(output_lines)
        output = output[-6000:]
        if return_code != 0:
            message = f"pip install 退出码 {return_code}\n{output}"[:6500]
            _install_state.update(status="failed", message=message)
            raise HTTPException(status_code=500, detail=message)
        if _manager is not None:
            from atlas.channels.adapters import register_builtin_channels
            register_builtin_channels(_manager.register_channel)
        _install_state.update(status="complete", message=output or "依赖安装成功")
        return {"ok": True, "channel": channel, "python": sys.executable, "output": output[-3000:]}


class SessionLinkPayload(BaseModel):
    agent_id: str = Field(min_length=1, max_length=120)
    channel: str = Field(min_length=1, max_length=80)
    account: str = Field(default="", max_length=120)
    peer: str = Field(min_length=1, max_length=240)
    conversation_id: str = Field(min_length=1, max_length=120)
    linked_by: str = Field(default="local-user", min_length=1, max_length=120)


class HandoffStatePayload(BaseModel):
    state: Literal["agent", "human", "paused"]


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


@router.get("/handoffs", dependencies=[Depends(_require_trusted_origin)])
async def list_handoffs() -> dict[str, Any]:
    """List active human takeovers and their auditable state events."""
    from atlas import server as atlas_server

    bridge = getattr(atlas_server, "gateway_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="渠道会话服务尚未启动")
    handoffs = bridge.sessions.handoffs(active_only=False)
    for item in handoffs:
        item["events"] = bridge.sessions.handoff_events(item["handoff_id"])
    return {"handoffs": handoffs}


@router.put("/handoffs/{handoff_id}", dependencies=[Depends(_require_trusted_origin)])
async def set_handoff_state(handoff_id: str, payload: HandoffStatePayload) -> dict[str, Any]:
    """Resume bot ownership or leave an ended handoff paused from local settings."""
    from atlas import server as atlas_server

    bridge = getattr(atlas_server, "gateway_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="渠道会话服务尚未启动")
    current = bridge.sessions.get_handoff(handoff_id)
    if current is None:
        raise HTTPException(status_code=404, detail="接管记录不存在")
    saved = bridge.sessions.update_handoff(handoff_id, payload.state, "local-user")
    for channel, chat, account in ((current["source_channel"], current["source_chat"], current["source_account"]),
                                   (current["human_channel"], current["human_chat"], current["human_account"])):
        with suppress(Exception):
            await bridge.manager.send(channel, chat,
                                      "bot 自动回复已恢复。" if payload.state == "agent" else "接管已结束；bot 保持暂停。",
                                      account=account)
    return {"handoff": saved, "events": bridge.sessions.handoff_events(handoff_id)}


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
        cleaned = {k: v for k, v in config.items() if k not in _SECRET_FIELDS}
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


class SlackOAuthStart(BaseModel):
    client_id: str
    redirect_uri: str


@router.post("/slack/oauth/start", dependencies=[Depends(_require_trusted_origin)])
async def slack_oauth_start(payload: SlackOAuthStart) -> dict[str, str]:
    """Create a one-use OAuth state and Slack app install link."""
    from atlas.channels.adapters._vendor.credentials_bridge import get_channel_secret

    client_id = payload.client_id.strip()
    redirect_uri = payload.redirect_uri.strip()
    if not client_id or len(client_id) > 200:
        raise HTTPException(422, "请先填写 Slack OAuth Client ID")
    try:
        from urllib.parse import urlparse
        parsed = urlparse(redirect_uri)
        if parsed.scheme != "http" or not parsed.hostname or parsed.path != "/api/channels/slack/oauth/callback" or parsed.query or parsed.fragment:
            raise ValueError
        if not ipaddress.ip_address(parsed.hostname).is_loopback and parsed.hostname != "localhost":
            raise ValueError
    except ValueError as exc:
        raise HTTPException(422, "OAuth 回调地址必须是本机 /api/channels/slack/oauth/callback") from exc
    if not get_channel_secret("slack", "oauth_client_secret"):
        raise HTTPException(422, "请先在 Slack 设置中保存 OAuth Client Secret")
    now = time.monotonic()
    for key, entry in list(_slack_oauth_states.items()):
        if entry["expires"] <= now:
            _slack_oauth_states.pop(key, None)
    state = secrets.token_urlsafe(32)
    _slack_oauth_states[state] = {"client_id": client_id, "redirect_uri": redirect_uri, "expires": now + 600}
    query = urlencode({
        "client_id": client_id, "scope": ",".join(sorted(_SLACK_BOT_SCOPES)),
        "redirect_uri": redirect_uri, "state": state,
    })
    return {"url": f"https://slack.com/oauth/v2/authorize?{query}", "redirect_uri": redirect_uri}


class SlackOAuthConfig(BaseModel):
    client_id: str
    client_secret: str = ""


@router.post("/slack/oauth/config", dependencies=[Depends(_require_trusted_origin)])
async def slack_oauth_save_config(payload: SlackOAuthConfig) -> dict[str, Any]:
    """Persist public app id and write-only app secret in the channel credential vault."""
    client_id = payload.client_id.strip()
    if not client_id or len(client_id) > 200:
        raise HTTPException(422, "Slack OAuth Client ID 不能为空")
    manager = get_channel_manager()
    manager.configure("slack", {"oauth_client_id": client_id})
    if payload.client_secret.strip():
        try:
            manager.credentials.set("slack", "oauth_client_secret", payload.client_secret.strip())
        except RuntimeError as exc:
            raise HTTPException(503, "无法把 OAuth Client Secret 保存到系统凭据库") from exc
    from atlas.channels.adapters._vendor.credentials_bridge import get_channel_secret

    return {"ok": True, "client_id": client_id,
            "client_secret_configured": bool(get_channel_secret("slack", "oauth_client_secret"))}


@router.get("/slack/oauth/config")
async def slack_oauth_get_config(request: Request) -> dict[str, Any]:
    from atlas.channels.adapters._vendor.credentials_bridge import get_channel_secret

    manager = get_channel_manager()
    host = request.url.hostname or "127.0.0.1"
    port = request.url.port
    authority = f"{host}:{port}" if port else host
    return {
        "client_id": str((manager.configs.get("slack") or {}).get("oauth_client_id") or ""),
        "client_secret_configured": bool(get_channel_secret("slack", "oauth_client_secret")),
        "redirect_uri": f"http://{authority}/api/channels/slack/oauth/callback",
    }


@router.get("/slack/oauth/callback")
async def slack_oauth_callback(code: str = "", state: str = "", error: str = "") -> dict[str, Any]:
    """Exchange a one-use Slack OAuth code, persist bot token, enable and check Slack."""
    from atlas.channels.adapters._vendor.credentials_bridge import get_channel_secret
    grant = _slack_oauth_states.pop(state, None)
    if not state or grant is None or grant["expires"] < time.monotonic():
        raise HTTPException(400, "Slack 授权状态无效或已过期，请重新开始安装")
    if error:
        raise HTTPException(400, f"Slack 安装未完成：{error[:100]}")
    if not code:
        raise HTTPException(400, "Slack 未返回授权码")
    client_secret = get_channel_secret("slack", "oauth_client_secret")
    if not client_secret:
        raise HTTPException(422, "本机没有 Slack OAuth Client Secret")
    import httpx

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post("https://slack.com/api/oauth.v2.access", data={
                "client_id": grant["client_id"], "client_secret": client_secret,
                "code": code, "redirect_uri": grant["redirect_uri"],
            })
            response.raise_for_status()
            result = response.json()
    except Exception as exc:
        log.warning("slack.oauth_exchange_failed", error_type=type(exc).__name__)
        raise HTTPException(502, "Slack 授权码交换失败，请检查网络和 Redirect URL") from exc
    if not isinstance(result, dict) or not result.get("ok"):
        reason = str(result.get("error") or "响应无效") if isinstance(result, dict) else "响应无效"
        raise HTTPException(502, f"Slack 授权失败：{reason[:100]}")
    scopes = {item.strip() for item in str(result.get("scope") or "").split(",") if item.strip()}
    missing = sorted(_SLACK_BOT_SCOPES - scopes)
    if missing:
        raise HTTPException(422, "Slack 授权缺少所需 scope：" + ", ".join(missing))
    bot_token = str(result.get("access_token") or "")
    if not bot_token.startswith("xoxb-"):
        raise HTTPException(502, "Slack 没有返回有效的 Bot Token")
    manager = get_channel_manager()
    try:
        manager.credentials.set("slack", "bot_token", bot_token)
        manager.configure("slack", {"enabled": True})
        await manager.restart_channel("slack")
    except Exception as exc:
        log.warning("slack.oauth_install_apply_failed", error_type=type(exc).__name__)
        raise HTTPException(503, "授权成功，但本机无法保存凭据或启用 Slack 渠道") from exc
    team = result.get("team") if isinstance(result.get("team"), dict) else {}
    status = next((row for row in manager.status().get("channels", []) if row.get("name") == "slack"), {})
    return {
        "ok": True, "team": str(team.get("name") or "Slack 工作区"),
        "enabled": bool(status.get("enabled")), "running": bool(status.get("running")),
        "connection": "connected" if status.get("running") else str(status.get("last_error") or "等待 Socket Mode App Token（xapp-）"),
        "app_token_configured": bool(get_channel_secret("slack", "app_token")),
    }


class TestPayload(BaseModel):
    channel: str
    chat_id: str
    text: str = ""


class SendMessagePayload(BaseModel):
    channel: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=512)
    text: str = Field(min_length=1, max_length=10000)


@router.post("/send", dependencies=[Depends(_require_trusted_origin)])
async def send_to_channel(payload: SendMessagePayload) -> dict[str, Any]:
    """Queue a user-directed message through the same durable channel delivery path."""
    manager = get_channel_manager()
    try:
        channel, target = manager.validate_target(payload.channel, payload.target)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="消息内容不能为空")
    key = await manager.send(channel, target, text, metadata={"source": "manual"})
    record = manager.delivery.get(key)
    return {"ok": True, "idempotency_key": key, "status": record.status if record else "pending"}


@router.get("/delivery/{key}", dependencies=[Depends(_require_trusted_origin)])
async def channel_delivery_status(key: str) -> dict[str, Any]:
    """Return a safe delivery outcome without exposing adapter errors or message text."""
    if len(key) != 64 or any(char not in "0123456789abcdef" for char in key.lower()):
        raise HTTPException(status_code=422, detail="幂等键格式无效")
    record = get_channel_manager().delivery.get(key)
    if record is None:
        raise HTTPException(status_code=404, detail="没有找到对应的投递记录")
    status_message = {
        "pending": "消息已排队，等待投递" if record.attempts == 0 else "投递失败，已安排重试",
        "sending": "正在投递",
        "delivered": "已送达",
        "dead": "投递失败，已停止重试",
    }.get(record.status, record.status)
    return {
        "idempotency_key": record.idempotency_key, "channel": record.channel,
        "target": record.chat_id, "status": record.status, "attempts": record.attempts,
        "next_retry_at": record.next_retry_at or None, "message": status_message,
    }


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
