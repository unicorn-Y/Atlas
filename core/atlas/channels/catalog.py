"""Single source of truth for channel support and feature discovery."""
from __future__ import annotations

CHANNEL_CATALOG: tuple[dict[str, object], ...] = (
    {"id": "telegram", "label": "Telegram", "status": "available", "inbound": True, "outbound": True, "attachments": True, "groups": True, "mentions": True, "dependency": "python-telegram-bot", "credentials": ["bot_token"], "setup": "Create a bot with BotFather and enter its token."},
    {"id": "slack", "label": "Slack", "status": "available_optional", "inbound": True, "outbound": True, "attachments": False, "groups": True, "mentions": True, "dependency": "slack-sdk", "credentials": ["bot_token", "app_token"], "setup": "Install the channels extra and configure Socket Mode tokens."},
    {"id": "email", "label": "Email", "status": "available", "inbound": True, "outbound": True, "attachments": True, "groups": False, "mentions": False, "dependency": "IMAP/SMTP", "credentials": ["account", "password"], "setup": "Configure an IMAP mailbox and SMTP sender."},
    {"id": "webhook", "label": "Webhook", "status": "available", "inbound": True, "outbound": True, "attachments": False, "groups": False, "mentions": False, "dependency": None, "credentials": ["secret"], "setup": "Configure the webhook HMAC secret."},
    {"id": "feishu", "label": "飞书 / Lark", "status": "available_optional", "inbound": True, "outbound": True, "attachments": True, "groups": True, "mentions": True, "dependency": "lark-oapi", "credentials": ["app_id", "app_secret"], "setup": "Create a Feishu app and install the optional SDK."},
    {"id": "dingtalk", "label": "钉钉", "status": "available_optional", "inbound": True, "outbound": True, "attachments": False, "groups": True, "mentions": True, "dependency": "cryptography", "credentials": ["client_id", "client_secret"], "setup": "Configure a DingTalk app callback."},
    {"id": "wecom", "label": "企业微信", "status": "available_optional", "inbound": True, "outbound": True, "attachments": False, "groups": True, "mentions": True, "dependency": "cryptography", "credentials": ["corp_id", "corp_secret"], "setup": "Configure a WeCom callback app."},
    *({"id": key, "label": label, "status": "not_implemented", "inbound": False, "outbound": False, "attachments": False, "groups": False, "mentions": False, "dependency": None, "credentials": [], "setup": "Not implemented; no credentials are requested."} for key, label in (("discord", "Discord"), ("matrix", "Matrix"), ("imessage", "iMessage"), ("signal", "Signal"), ("sms", "SMS"), ("whatsapp", "WhatsApp"))),
)

def list_channels() -> list[dict[str, object]]:
    """Return JSON-safe feature metadata for UI and documentation."""
    return [dict(row) for row in CHANNEL_CATALOG]
