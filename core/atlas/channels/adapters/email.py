"""Email channel adapter — stdlib ``imaplib`` polling + ``smtplib`` sending (r5 §6.2).

No third-party dependencies. IMAP has no IDLE in stdlib, so the adapter polls
the configured folder on an interval (default 60s) via UID, persists the last
seen UID in SQLite, and normalizes each new mail into a
``MessageEvent(kind=TEXT|FILE)``. Blocking IMAP/SMTP calls run in worker threads.
"""

from __future__ import annotations

import asyncio
import email
import email.policy
import imaplib
import logging
import os
import smtplib
import sqlite3
from email.message import EmailMessage
from email.message import Message as EmailMessage_
from pathlib import Path
from typing import Any

from atlas.channels import AdapterAuthError
from atlas.channels.contract import (
    Attachment,
    ChannelAdapter,
    MessageEvent,
    MessageType,
    SendResult,
)
from atlas.channels.credentials import channel_credentials

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 60.0
DEFAULT_IMAP_PORT = 993
DEFAULT_SMTP_PORT = 465


def default_state_path() -> Path:
    data_dir = Path(os.environ.get("ATLAS_DATA_DIR") or "data")
    return data_dir / "channels" / "email_state.db"


def _decode_header(value: Any) -> str:
    from email.header import decode_header

    if not value:
        return ""
    parts = decode_header(str(value))
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            out.append(text.decode(charset or "utf-8", "replace"))
        else:
            out.append(str(text))
    return "".join(out).strip()


def parse_mail(raw: bytes, *, uid: str, account: str = "") -> MessageEvent:
    """Normalize one raw RFC822 message into a MessageEvent (kind TEXT or FILE)."""
    message: EmailMessage_ = email.message_from_bytes(raw, policy=email.policy.default)
    sender = str(message.get("From", ""))
    subject = _decode_header(message.get("Subject"))
    body_parts: list[str] = []
    attachments: list[Attachment] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = str(part.get_content_disposition() or "")
        content_type = part.get_content_type()
        if disposition == "attachment" or (
            content_type not in ("text/plain", "text/html") and part.get_filename()
        ):
            attachments.append(
                Attachment(
                    kind=MessageType.FILE,
                    filename=_decode_header(part.get_filename()),
                    mime_type=content_type,
                )
            )
            continue
        if content_type == "text/plain" and not body_parts:
            try:
                body_parts.append(part.get_content())
            except Exception:
                logger.exception("Email body decoding failed; falling back to UTF-8")
                payload = part.get_payload(decode=True) or b""
                body_parts.append(payload.decode("utf-8", "replace"))
    body = "\n".join(body_parts).strip()
    text = f"{subject}\n\n{body}".strip() if subject else body
    kind = MessageType.TEXT if body else MessageType.FILE
    if kind is MessageType.FILE:
        text = subject
    sender_address = email.utils.parseaddr(sender)[1]
    sender_name = _decode_header(email.utils.parseaddr(sender)[0])
    ts = 0.0
    try:
        parsed = email.utils.parsedate_to_datetime(str(message.get("Date", "")))
        ts = parsed.timestamp() if parsed else 0.0
    except Exception:
        logger.exception("Email date parsing failed")
        ts = 0.0
    return MessageEvent(
        channel="email",
        account=account,
        event_id=uid,
        chat_id=sender_address,
        sender_id=sender_address,
        kind=kind,
        text=text,
        sender_name=sender_name,
        attachments=attachments,
        ts=ts,
        raw={"subject": subject, "message_id": str(message.get("Message-ID", ""))},
    )


class ChannelRuntimeError(RuntimeError):
    """Transient email transport failure (retryable by the gateway)."""


class EmailAdapter(ChannelAdapter):
    name = "email"

    def __init__(self, config: dict[str, Any], dispatcher) -> None:
        super().__init__(config, dispatcher)
        self.account = str(config.get("account") or "")
        self.host = str(config.get("host") or "")
        self.port = int(config.get("port") or DEFAULT_IMAP_PORT)
        self.smtp_host = str(config.get("smtp_host") or self.host)
        self.smtp_port = int(config.get("smtp_port") or DEFAULT_SMTP_PORT)
        self.user = str(config.get("user") or "")
        self.folder = str(config.get("folder") or "INBOX")
        self.poll_interval = float(config.get("poll_interval", DEFAULT_POLL_INTERVAL))
        filters = config.get("filters") or {}
        self.subject_filters = [str(v).lower() for v in (filters.get("subject_contains") or [])]
        self.from_filters = [str(v).lower() for v in (filters.get("from_contains") or [])]
        self.state_path = Path(config.get("state_path") or default_state_path())
        self._credentials = config.get("credentials") or channel_credentials
        # Test seams: factories return an imaplib.IMAP4-like / smtplib-like client.
        self._imap_factory = config.get("imap_factory") or (
            lambda: imaplib.IMAP4_SSL(self.host, self.port)
        )
        self._smtp_factory = config.get("smtp_factory") or (
            lambda: smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=20)
        )
        self._task: asyncio.Task[None] | None = None
        self._state_db: sqlite3.Connection | None = None
        self.stopping = False
        self._last_uid = self._load_uid()

    # -- lifecycle -------------------------------------------------------------

    @property
    def worker_task(self) -> asyncio.Task[None] | None:
        return self._task

    def account_id(self) -> str:
        return self.account

    def _password(self) -> str:
        password = str(self.config.get("password") or "")
        if password:
            return password
        return self._credentials.get("email", "password") or ""

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not self.host or not self.user:
            raise AdapterAuthError("邮箱渠道未配置 host/user。")
        if not self._password():
            raise AdapterAuthError("邮箱渠道缺少密码凭据。")
        # Fail fast on bad credentials before claiming the channel is running.
        await asyncio.to_thread(self._probe_login)
        self.stopping = False
        self._task = asyncio.create_task(
            self._run_loop(), name=f"atlas-channel-email-{self.account}"
        )

    async def stop(self) -> None:
        self.stopping = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _probe_login(self) -> None:
        client = self._imap_factory()
        try:
            client.login(self.user, self._password())
            client.logout()
        except imaplib.IMAP4.error as exc:
            raise AdapterAuthError(f"邮箱登录失败：{exc}") from None

    async def _run_loop(self) -> None:
        try:
            while not self.stopping:
                events = await asyncio.to_thread(self._poll_once)
                for event in events:
                    await self._dispatch(event)
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            raise

    # -- IMAP polling ------------------------------------------------------------

    def _uid_key(self) -> str:
        return f"email/{self.account}/{self.folder}/last_uid"

    def _state_connection(self) -> sqlite3.Connection:
        if self._state_db is None:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            # Persisted from the poll worker thread; writes are serialized by the
            # polling loop, so the cross-thread connection is safe.
            self._state_db = sqlite3.connect(self.state_path, check_same_thread=False)
            self._state_db.execute(
                "CREATE TABLE IF NOT EXISTS adapter_state"
                " (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        return self._state_db

    def _load_uid(self) -> int:
        try:
            row = self._state_connection().execute(
                "SELECT value FROM adapter_state WHERE key=?", (self._uid_key(),)
            ).fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error:
            return 0

    def _persist_uid(self) -> None:
        try:
            with self._state_connection():
                self._state_db.execute(
                    "INSERT OR REPLACE INTO adapter_state(key, value) VALUES (?,?)",
                    (self._uid_key(), str(self._last_uid)),
                )
        except sqlite3.Error:
            logger.warning("Email UID 持久化失败", exc_info=True)

    def _poll_once(self) -> list[MessageEvent]:
        password = self._password()
        client = self._imap_factory()
        try:
            try:
                client.login(self.user, password)
            except imaplib.IMAP4.error as exc:
                raise AdapterAuthError(f"邮箱登录失败：{exc}") from None
            client.select(self.folder)
            typ, data = client.uid("search", None, f"UID {self._last_uid + 1}:*")
            if typ != "OK":
                raise ChannelRuntimeError("IMAP UID SEARCH 失败。")
            uids = (data[0] or b"").split()
            events: list[MessageEvent] = []
            for uid_bytes in uids:
                uid_int = int(uid_bytes)
                if uid_int <= self._last_uid:
                    continue  # "UID n:*" always re-reports the newest mail
                typ, fetch_data = client.uid("fetch", str(uid_int).encode(), "(BODY.PEEK[])")
                if typ != "OK" or not fetch_data or fetch_data[0] is None:
                    continue
                raw = fetch_data[0][1]
                if not isinstance(raw, bytes):
                    continue
                event = parse_mail(raw, uid=str(uid_int), account=self.account)
                if self._passes_filters(event):
                    events.append(event)
                self._last_uid = uid_int
                self._persist_uid()
            return events
        finally:
            try:
                client.logout()
            except Exception:
                logger.exception("Email IMAP logout failed")

    def _passes_filters(self, event: MessageEvent) -> bool:
        subject = str(event.raw.get("subject", "")).lower()
        sender = event.sender_id.lower()
        if self.subject_filters and not any(v in subject for v in self.subject_filters):
            return False
        if self.from_filters and not any(v in sender for v in self.from_filters):
            return False
        return True

    # -- SMTP sending --------------------------------------------------------------

    async def send(
        self,
        chat_id: str,
        content: str,
        *,
        reply_to: str = "",
        attachments: list[Attachment] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        metadata = metadata or {}
        subject = str(metadata.get("subject") or "Atlas 消息")

        def _send_sync() -> str:
            message = EmailMessage()
            message["From"] = self.user
            message["To"] = str(chat_id)
            message["Subject"] = subject
            if reply_to:
                message["In-Reply-To"] = str(reply_to)
            message.set_content(str(content))
            for item in attachments or []:
                if item.local_path:
                    from pathlib import Path as _Path

                    path = _Path(item.local_path)
                    message.add_attachment(
                        path.read_bytes(),
                        maintype=(item.mime_type.split("/")[0] or "application"),
                        subtype=(item.mime_type.split("/")[1] or "octet-stream"),
                        filename=item.filename or path.name,
                    )
            client = self._smtp_factory()
            try:
                client.login(self.user, self._password())
                client.send_message(message)
            finally:
                try:
                    client.quit()
                except Exception:
                    logger.exception("Email SMTP disconnect failed")
            return str(message.get("Message-ID", ""))

        try:
            message_id = await asyncio.to_thread(_send_sync)
        except smtplib.SMTPAuthenticationError as exc:
            return SendResult(ok=False, error=f"邮箱发信鉴权失败：{exc}", retryable=False)
        except AdapterAuthError as exc:
            return SendResult(ok=False, error=str(exc), retryable=False)
        except Exception as exc:
            logger.exception("Email send failed")
            return SendResult(ok=False, error=f"邮件发送失败：{exc}", retryable=True)
        return SendResult(ok=True, message_id=message_id)


__all__ = ["EmailAdapter", "ChannelRuntimeError", "parse_mail", "default_state_path"]
