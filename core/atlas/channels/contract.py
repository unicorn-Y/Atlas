"""Channel adapter contract — the single seam between transport adapters and the gateway.

Frozen for the persistent-always-on wave (integration-map.md §2): every channel adapter
implements :class:`ChannelAdapter`; the gateway (:mod:`atlas.channels`) owns lifecycle,
routing, gating, ingress dedupe and delivery. Adapters never import agent/session code —
they only emit :class:`MessageEvent` through the injected dispatcher and send via
:meth:`ChannelAdapter.send`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageType(str, Enum):
    """Normalized inbound message kinds (ported from the Hermes platform event shape)."""

    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    AUDIO = "audio"
    VIDEO = "video"
    STICKER = "sticker"
    SYSTEM = "system"
    REACTION = "reaction"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class Attachment:
    """A normalized inbound/outbound attachment (path or URL plus metadata)."""

    kind: MessageType
    url: str = ""
    local_path: str = ""
    filename: str = ""
    mime_type: str = ""
    size: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MessageEvent:
    """Normalized inbound message delivered to the gateway dispatcher."""

    channel: str
    account: str
    event_id: str
    chat_id: str
    sender_id: str
    kind: MessageType = MessageType.TEXT
    text: str = ""
    thread_id: str = ""
    sender_name: str = ""
    sender_is_bot: bool = False
    is_group: bool = False
    is_mention: bool = False
    mentions: list[str] = field(default_factory=list)
    reply_to_event_id: str = ""
    source_channel: str = ""
    source_event_id: str = ""
    causal_id: str = ""
    bot_depth: int = 0
    attachments: list[Attachment] = field(default_factory=list)
    ts: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


def causality_fields(raw: dict[str, Any], channel: str, event_id: str) -> dict[str, Any]:
    """Preserve Atlas loop metadata carried by adapters that support message metadata."""
    marker = raw.get("_atlas") or raw.get("atlas") or {}
    if not marker and isinstance(raw.get("metadata"), dict):
        marker = raw["metadata"].get("_atlas") or raw["metadata"].get("atlas") or {}
    if not isinstance(marker, dict):
        marker = {}
    try:
        depth = max(0, min(100, int(marker.get("bot_depth", 0) or 0)))
    except (TypeError, ValueError):
        depth = 0
    return {
        "source_channel": str(marker.get("source_channel") or channel),
        "source_event_id": str(marker.get("source_event_id") or event_id),
        "causal_id": str(marker.get("causal_id") or f"{channel}:{event_id}"),
        "bot_depth": depth,
    }


@dataclass(slots=True)
class SendResult:
    """Outcome of one outbound send attempt."""

    ok: bool
    message_id: str = ""
    error: str = ""
    retryable: bool = False


MessageDispatcher = Callable[[MessageEvent], Awaitable[None]]


class ChannelAdapterError(RuntimeError):
    """Adapter-level failure with a retry hint for the gateway delivery queue."""


class ChannelAdapter(ABC):
    """Base class every channel transport must implement.

    Lifecycle: the gateway constructs the adapter with its ``config`` section and a
    dispatcher, then awaits :meth:`start` (subscribe/poll) and later :meth:`stop`.
    Inbound traffic flows exclusively through ``_dispatch``; outbound via :meth:`send`.
    Optional third-party SDKs must be imported lazily inside methods so the adapter
    module import never fails on machines without the SDK (probe with
    :meth:`is_available`).
    """

    name: str = "base"

    def __init__(self, config: dict[str, Any], dispatcher: MessageDispatcher) -> None:
        self.config = config
        self._dispatcher = dispatcher

    @classmethod
    def is_available(cls) -> bool:
        """Whether the optional SDK dependencies for this adapter are importable."""
        return True

    @abstractmethod
    async def start(self) -> None:
        """Connect and begin delivering inbound events via the dispatcher."""

    @abstractmethod
    async def stop(self) -> None:
        """Disconnect and release resources; idempotent."""

    @abstractmethod
    async def send(
        self,
        chat_id: str,
        content: str,
        *,
        reply_to: str = "",
        attachments: list[Attachment] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        """Deliver one outbound message to ``chat_id`` on this channel."""

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        """Best-effort chat metadata (title, kind); adapters may return ``{}``."""
        return {}

    def account_id(self) -> str:
        """Account label this adapter instance serves (defaults to config value)."""
        return str(self.config.get("account", ""))

    async def _dispatch(self, event: MessageEvent) -> None:
        await self._dispatcher(event)
