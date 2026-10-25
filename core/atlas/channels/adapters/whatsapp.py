"""WhatsApp Web multi-device adapter through the isolated Baileys JSONL bridge.

The paired device key material lives only in the local Atlas data directory;
the bridge communicates over inherited stdin/stdout pipes and never logs message
contents, media, QR payloads, or account credentials.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from atlas.channels.contract import (
    Attachment,
    ChannelAdapter,
    ChannelAdapterError,
    MessageEvent,
    MessageType,
    SendResult,
    causality_fields,
)

logger = logging.getLogger(__name__)
_MAX_MEDIA_BYTES = 20 * 1024 * 1024
_MAX_BRIDGE_LINE = 32 * 1024 * 1024


def default_state_directory() -> Path:
    from atlas.config import DATA_ROOT

    return DATA_ROOT / "data" / "channels" / "whatsapp"


def _bridge_paths() -> tuple[Path, Path]:
    """Resolve source bridge in development or staged bridge in packaged Atlas."""
    from atlas.tools.node_runtime import bundled_node_directory

    node_dir = bundled_node_directory()
    packaged = node_dir.parent / "whatsapp-bridge"
    source = Path(__file__).with_name("whatsapp_bridge")
    bridge = packaged if (packaged / "bridge.mjs").is_file() else source
    runtime = node_dir / ("node.exe" if os.name == "nt" else "node")
    if not runtime.is_file():
        runtime = Path(shutil.which("node") or "")
    return bridge, runtime


def normalize_inbound(value: dict[str, Any], *, account: str, media_directory: Path) -> MessageEvent:
    """Translate bridge message records into Atlas's transport-neutral event."""
    event_id = str(value.get("event_id") or "").strip()
    chat_id = str(value.get("chat_id") or "").strip()
    sender_id = str(value.get("sender_id") or chat_id).strip()
    if not event_id or not chat_id or not sender_id:
        raise ValueError("WhatsApp bridge message is missing its id, chat or sender")
    attachments: list[Attachment] = []
    raw_attachment = value.get("attachment")
    if isinstance(raw_attachment, dict) and isinstance(raw_attachment.get("data"), str):
        try:
            decoded = base64.b64decode(raw_attachment["data"], validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("WhatsApp bridge returned malformed media data") from exc
        if len(decoded) > _MAX_MEDIA_BYTES:
            raise ValueError("WhatsApp media exceeds the 20 MiB attachment limit")
        media_directory.mkdir(parents=True, exist_ok=True)
        mime = str(raw_attachment.get("mime_type") or "application/octet-stream")[:160]
        name = Path(str(raw_attachment.get("filename") or "attachment")).name
        suffix = Path(name).suffix[:16] or mimetypes.guess_extension(mime) or ".bin"
        target = media_directory / f"{uuid.uuid4().hex}{suffix}"
        target.write_bytes(decoded)
        kind_name = str(raw_attachment.get("kind") or "file").lower()
        kind = {
            "image": MessageType.IMAGE, "video": MessageType.VIDEO,
            "audio": MessageType.AUDIO, "sticker": MessageType.STICKER,
        }.get(kind_name, MessageType.FILE)
        attachments.append(Attachment(kind=kind, local_path=str(target), filename=name, mime_type=mime, size=len(decoded)))
    kind = attachments[0].kind if attachments else MessageType.TEXT
    try:
        timestamp = float(value.get("timestamp") or 0)
    except (TypeError, ValueError):
        timestamp = 0.0
    raw = {"is_mention": bool(value.get("is_mention")), "reply_to_event_id": str(value.get("reply_to_event_id") or "")}
    return MessageEvent(
        channel="whatsapp", account=account, event_id=event_id, chat_id=chat_id,
        sender_id=sender_id, kind=kind, text=str(value.get("text") or ""),
        sender_name=str(value.get("sender_name") or "")[:256],
        is_group=bool(value.get("is_group")), is_mention=bool(value.get("is_mention")),
        reply_to_event_id=str(value.get("reply_to_event_id") or ""),
        attachments=attachments, ts=timestamp, raw=raw,
        **causality_fields(raw, "whatsapp", event_id),
    )


class WhatsAppAdapter(ChannelAdapter):
    """QR paired WhatsApp multi-device client with retryable local bridge IO."""

    name = "whatsapp"

    def __init__(self, config: dict[str, Any], dispatcher) -> None:
        super().__init__(config, dispatcher)
        self.account = str(config.get("account") or "default")[:128]
        self.state_directory = Path(config.get("state_path") or default_state_directory()).expanduser().resolve()
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._request_id = 0
        self._stopping = False
        self._qr = ""
        self._connection = "disconnected"
        self.last_error = ""

    @classmethod
    def is_available(cls) -> bool:
        bridge, runtime = _bridge_paths()
        return runtime.is_file() and (bridge / "bridge.mjs").is_file() and (bridge / "node_modules" / "@whiskeysockets" / "baileys").is_dir()

    @property
    def worker_task(self) -> asyncio.Task[None] | None:
        return self._reader_task

    def pairing_status(self) -> dict[str, Any]:
        return {"state": self._connection, "qr": self._qr, "error": self.last_error}

    async def start(self) -> None:
        if self._reader_task and not self._reader_task.done():
            return
        if not self.is_available():
            raise ChannelAdapterError("WhatsApp Bridge 依赖未安装；请在 Atlas 渠道设置中安装 Baileys Bridge。")
        bridge, runtime = _bridge_paths()
        self.state_directory.mkdir(parents=True, exist_ok=True)
        self._stopping = False
        self._connection = "starting"
        self._process = await asyncio.create_subprocess_exec(
            str(runtime), str(bridge / "bridge.mjs"), str(self.state_directory / "session"),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=_MAX_BRIDGE_LINE,
            cwd=str(bridge),
            creationflags=getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0),
        )
        self._reader_task = asyncio.create_task(self._read_stdout(), name=f"atlas-whatsapp-{self.account}")
        self._stderr_task = asyncio.create_task(self._read_stderr(), name=f"atlas-whatsapp-stderr-{self.account}")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=15)
        except TimeoutError as exc:
            if self._process.returncode is not None:
                raise ChannelAdapterError(self.last_error or "WhatsApp Bridge stopped before pairing started") from exc
            # Baileys can take longer on a slow first DNS/TLS connection; its
            # reader remains active and pairing status will update asynchronously.

    async def stop(self) -> None:
        self._stopping = True
        process, self._process = self._process, None
        if process is not None and process.stdin:
            process.stdin.close()
            with __import__("contextlib").suppress(Exception):
                await process.stdin.wait_closed()
        if process is not None and process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=4)
            except TimeoutError:
                process.kill()
                await process.wait()
        tasks = [task for task in (self._reader_task, self._stderr_task) if task is not None]
        self._reader_task = self._stderr_task = None
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ChannelAdapterError("WhatsApp Bridge 已停止"))
        self._pending.clear()
        self._connection = "disconnected"

    async def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while line := await process.stdout.readline():
                if len(line) > _MAX_BRIDGE_LINE:
                    raise ChannelAdapterError("WhatsApp Bridge 消息超过大小限制")
                try:
                    record = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self.last_error = "WhatsApp Bridge 返回了无效的 JSON 事件"
                    continue
                await self._handle_record(record)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("whatsapp.bridge_read_failed: %s", type(exc).__name__)
        finally:
            if not self._stopping:
                self._connection = "disconnected"
                self._ready.set()
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(ChannelAdapterError(self.last_error or "WhatsApp Bridge 连接已断开"))

    async def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while line := await process.stderr.readline():
            # Do not persist raw third-party logs: they may contain account IDs.
            if b"error" in line.lower() or b"fatal" in line.lower():
                logger.warning("whatsapp.bridge_reported_error")

    async def _handle_record(self, record: dict[str, Any]) -> None:
        kind = record.get("type")
        if kind == "qr":
            self._qr = str(record.get("value") or "")[:4096]
            self._connection = "pairing"
            self._ready.set()
        elif kind == "connection":
            state = str(record.get("state") or "disconnected")
            self._connection = "connected" if state == "open" else "logged_out" if state == "logged_out" else state
            if state == "open":
                self._qr = ""
                self.last_error = ""
            self._ready.set()
        elif kind == "error":
            self.last_error = str(record.get("message") or "WhatsApp Bridge error")[:500]
            logger.warning("whatsapp.bridge_error")
            self._ready.set()
        elif kind == "warning":
            self.last_error = str(record.get("message") or "WhatsApp media warning")[:500]
        elif kind == "response":
            request_id = str(record.get("id") or "")
            future = self._pending.pop(request_id, None)
            if future is not None and not future.done():
                if record.get("error"):
                    future.set_exception(ChannelAdapterError(str(record["error"])[:500]))
                else:
                    future.set_result(record.get("value") if isinstance(record.get("value"), dict) else {})
        elif kind == "message":
            value = record.get("value")
            if isinstance(value, dict):
                try:
                    event = normalize_inbound(value, account=self.account, media_directory=self.state_directory / "media")
                    await self._dispatch(event)
                except (OSError, ValueError) as exc:
                    self.last_error = f"WhatsApp 消息处理失败：{exc}"
                    logger.warning("whatsapp.inbound_normalize_failed: %s", type(exc).__name__)

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise ChannelAdapterError("WhatsApp Bridge 尚未连接")
        self._request_id += 1
        request_id = str(self._request_id)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        payload = {**payload, "id": request_id}
        try:
            async with self._write_lock:
                process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
                await process.stdin.drain()
            return await asyncio.wait_for(future, timeout=35)
        except (OSError, TimeoutError) as exc:
            self._pending.pop(request_id, None)
            raise ChannelAdapterError("WhatsApp Bridge 请求失败") from exc

    async def send(
        self,
        chat_id: str,
        content: str,
        *,
        reply_to: str = "",
        attachments: list[Attachment] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        del metadata
        target = str(chat_id or "").strip()
        if not target or len(target) > 256 or "@" not in target:
            return SendResult(ok=False, error="目标必须是 WhatsApp user/group JID（例如号码@s.whatsapp.net 或 群ID@g.us）")
        files = attachments or []
        if len(files) > 1:
            return SendResult(ok=False, error="WhatsApp 每条消息目前最多发送一个附件")
        attachment: dict[str, Any] | None = None
        if files:
            file = files[0]
            if file.local_path:
                media_path = Path(file.local_path).expanduser().resolve()
                if not media_path.is_file() or media_path.stat().st_size > _MAX_MEDIA_BYTES:
                    return SendResult(ok=False, error="WhatsApp 附件不存在或超过 20 MiB")
                attachment = {"path": str(media_path), "mime_type": file.mime_type, "filename": file.filename or media_path.name}
            elif file.url.startswith("file://"):
                media_path = Path(file.url[7:]).expanduser().resolve()
                if not media_path.is_file() or media_path.stat().st_size > _MAX_MEDIA_BYTES:
                    return SendResult(ok=False, error="WhatsApp 附件不存在或超过 20 MiB")
                attachment = {"path": str(media_path), "mime_type": file.mime_type, "filename": file.filename or media_path.name}
            else:
                return SendResult(ok=False, error="WhatsApp 出站附件必须是本地文件")
        try:
            result = await self._request({"op": "send", "chat_id": target, "text": str(content or ""), "reply_to": str(reply_to or ""), "attachment": attachment})
            return SendResult(ok=True, message_id=str(result.get("message_id") or ""))
        except ChannelAdapterError as exc:
            return SendResult(ok=False, error=str(exc), retryable=self._connection != "logged_out")

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        return {"title": str(chat_id), "kind": "group" if str(chat_id).endswith("@g.us") else "dm"}

    def account_id(self) -> str:
        return self.account

