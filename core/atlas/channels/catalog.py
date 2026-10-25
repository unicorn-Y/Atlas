"""Single source of truth for channel support and feature discovery."""
from __future__ import annotations

CHANNEL_CATALOG: tuple[dict[str, object], ...] = (
    {"id": "telegram", "label": "Telegram", "status": "available", "inbound": True, "outbound": True, "attachments": True, "groups": True, "mentions": True, "dependency": None, "credentials": ["bot_token"], "setup": "在 BotFather 创建 bot，复制 token 到渠道设置；再将 bot 加入群并配置消息权限。", "docs": "https://core.telegram.org/bots"},
    {"id": "slack", "label": "Slack", "status": "optional", "inbound": True, "outbound": True, "attachments": False, "groups": True, "mentions": True, "dependency": "slack-sdk + aiohttp (channels extra)", "credentials": ["bot_token", "app_token"], "setup": "创建 Slack App、启用 Socket Mode 并配置 bot/app token；安装 core 的 channels extra。", "docs": "https://api.slack.com/apis/socket-mode"},
    {"id": "email", "label": "Email", "status": "available", "inbound": True, "outbound": True, "attachments": True, "groups": False, "mentions": False, "dependency": None, "credentials": ["account", "password"], "setup": "配置 IMAP 主机、邮箱账号和应用密码；出站 SMTP 主机按需填写。", "docs": "https://www.rfc-editor.org/rfc/rfc9051"},
    {"id": "webhook", "label": "Webhook", "status": "available", "inbound": True, "outbound": True, "attachments": False, "groups": False, "mentions": False, "dependency": None, "credentials": ["secret"], "setup": "配置 HMAC 密钥；入站请求发送到 /api/channels/webhook/inbound。", "docs": "https://www.rfc-editor.org/rfc/rfc2104"},
    {"id": "feishu", "label": "飞书 / Lark", "status": "optional", "inbound": True, "outbound": True, "attachments": True, "groups": True, "mentions": True, "dependency": "lark-oapi (channels extra)", "credentials": ["app_id", "app_secret"], "setup": "创建企业自建应用并开通 im.message 权限；选择长连接或配置回调验证信息。", "docs": "https://open.feishu.cn/document/"},
    {"id": "dingtalk", "label": "钉钉", "status": "optional", "inbound": True, "outbound": True, "attachments": True, "groups": True, "mentions": True, "dependency": "dingtalk-stream (channels extra)", "credentials": ["client_id", "client_secret"], "setup": "创建企业内部应用，开启机器人 Stream Mode，配置 Client ID/Secret。", "docs": "https://open.dingtalk.com/document/"},
    {"id": "wecom", "label": "企业微信", "status": "optional", "inbound": True, "outbound": True, "attachments": False, "groups": True, "mentions": False, "dependency": "cryptography + httpx", "credentials": ["corp_id", "corp_secret", "agent_id", "token", "encoding_aes_key"], "setup": "创建自建应用并配置可信回调域名、Token、EncodingAESKey 与应用凭据。", "docs": "https://developer.work.weixin.qq.com/document/"},
    *({"id": key, "label": label, "status": "not_implemented", "inbound": False, "outbound": False, "attachments": False, "groups": False, "mentions": False, "dependency": None, "credentials": [], "setup": "尚未实现适配器，不会索取凭据。", "docs": url} for key, label, url in (("discord", "Discord", "https://discord.com/developers/docs/"), ("matrix", "Matrix", "https://spec.matrix.org/"), ("imessage", "iMessage", "https://support.apple.com/messages"), ("signal", "Signal", "https://signal.org/docs/"), ("sms", "SMS", "https://www.twilio.com/docs/sms"), ("whatsapp", "WhatsApp", "https://developers.facebook.com/docs/whatsapp/"))),
)

def list_channels() -> list[dict[str, object]]:
    """Return JSON-safe feature metadata for UI and documentation."""
    return [dict(row) for row in CHANNEL_CATALOG]


def channels_with_registry(registry: dict[str, object]) -> list[dict[str, object]]:
    """Add live adapter registration and optional-dependency state to each row."""
    rows = list_channels()
    for row in rows:
        adapter = registry.get(str(row["id"]))
        row["registered"] = adapter is not None
        if row["status"] == "optional":
            row["status"] = "available" if adapter is not None else "dependency_missing"
    return rows
